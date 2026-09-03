"""Material Requests — paste a project request, compare with stock, prepare,
hold as Ready, then convert to a Delivery Note.

Three tabs:
  1. New / Check      paste the list, see requested vs available instantly
  2. Requests         every saved request, its lines and preparation progress
  3. Ready to Deliver prepared material with no Delivery Note yet
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QFontDatabase,
                           QFontMetricsF, QKeySequence, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMenu, QPlainTextEdit, QSplitter, QTabWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..core import documents as D, importer, material as M
from ..core import services as S
from ..core.database import Database
from . import widgets as W
from .common import GoogleResultsDialog, ItemPicker, ShareBar, date_edit, iso, lookup

CHECK_COLS = ["Line", "Item Code", "Description", "UOM", "Requested", "In Stock", "Reserved",
              "Available", "Can Supply", "Short By", "Availability", "PR / MR No.", "Project",
              "Warehouse", "Location", "Stock Status"]


def _paint(table: W.DataTable, col: int, colors: dict[str, str]) -> None:
    for r in range(table.rowCount()):
        cell = table.item(r, col)
        if cell is None:
            continue
        c = colors.get(cell.text())
        if c:
            cell.setForeground(QBrush(QColor(c)))
            f = cell.font()
            f.setBold(True)
            cell.setFont(f)


class DropPasteEdit(QPlainTextEdit):
    """Paste box that also accepts an Excel/CSV file dropped onto it."""
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            for url in md.urls():
                path = url.toLocalFile()
                if path:
                    self.fileDropped.emit(path)
                    e.acceptProposedAction()
                    return
        super().dropEvent(e)


class BulkCreateItemsDialog(QDialog):
    """Add several request lines to the Item Master, with opening balances.

    One row per item so each can carry its own opening balance, plus an
    "apply to all" bar for the common case of the same warehouse or the same
    quantity across the whole selection.
    """

    COLS = ["Item Code", "Description", "UOM", "Category", "Opening Balance",
            "Unit Cost", "Warehouse", "Location", "Min Level", "Max Level"]
    EDIT = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9}
    NUMERIC = {4, 5, 8, 9}

    def __init__(self, db: Database, lines: list[dict], parent=None):
        super().__init__(parent)
        self.db = db
        self.lines = lines
        self.created: dict | None = None
        self.setWindowTitle(f"Add {len(lines)} item(s) to the Item Master")
        self.setModal(True)
        self.resize(1080, 620)

        v = QVBoxLayout(self)
        head = QLabel(
            f"<b>{len(lines)} request line(s)</b> will be added to the Item Master. "
            "Enter the <b>opening balance</b> you are holding for each — leave it at "
            "0 and receive the stock later through Stock In.<br>"
            "Every value below is editable; the opening balance is posted to the "
            "stock ledger so the item's history starts correctly.")
        head.setWordWrap(True)
        head.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER};"
                           "border-radius:6px; padding:9px;")
        v.addWidget(head)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Apply to all:"))
        self.all_qty = QDoubleSpinBox()
        self.all_qty.setRange(0, 1e9)
        self.all_qty.setDecimals(2)
        self.all_qty.setToolTip("Set the same opening balance on every row")
        bar.addWidget(QLabel("Opening balance"))
        bar.addWidget(self.all_qty)
        bar.addWidget(W.button("Apply", slot=self._apply_qty))
        self.all_wh = W.combo([""] + lookup(db, "warehouses"), editable=True)
        bar.addWidget(QLabel("Warehouse"))
        bar.addWidget(self.all_wh)
        bar.addWidget(W.button("Apply", slot=self._apply_wh))
        self.all_cat = W.combo([""] + lookup(db, "categories"), editable=True)
        bar.addWidget(QLabel("Category"))
        bar.addWidget(self.all_cat)
        bar.addWidget(W.button("Apply", slot=self._apply_cat))
        bar.addStretch(1)
        v.addLayout(bar)

        self.table = QTableWidget(len(lines), len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setDefaultSectionSize(26)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (0, 2, 3, 4, 5, 6, 7, 8, 9):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        default_uom = db.get_setting("default_uom", "PCS")
        for r, ln in enumerate(lines):
            vals = [ln.get("item_code", ""), ln.get("description", ""),
                    ln.get("uom") or default_uom,
                    ln.get("category") or ln.get("procurement_category") or "",
                    "0", "0", "", "", "0", "0"]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                if c in self.NUMERIC:
                    it.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
                self.table.setItem(r, c, it)
        self.table.itemChanged.connect(lambda *_: self._recalc())
        v.addWidget(self.table, 1)

        self.warn = QLabel()
        self.warn.setWordWrap(True)
        v.addWidget(self.warn)
        self.total = QLabel()
        self.total.setStyleSheet(f"color:{W.NAVY}; font-weight:700;")
        v.addWidget(self.total)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("➕  Add to Item Master")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._recalc()

    # ------------------------------------------------------------- helpers
    def _set_col(self, col: int, text: str):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            if self.table.item(r, col):
                self.table.item(r, col).setText(text)
        self.table.blockSignals(False)
        self._recalc()

    def _apply_qty(self):
        self._set_col(4, f"{self.all_qty.value():g}")

    def _apply_wh(self):
        self._set_col(6, self.all_wh.currentText().strip())

    def _apply_cat(self):
        self._set_col(3, self.all_cat.currentText().strip())

    def _num(self, r: int, c: int) -> float:
        it = self.table.item(r, c)
        if it is None:
            return 0.0
        try:
            return float(str(it.text()).replace(",", "").strip() or 0)
        except ValueError:
            return 0.0

    def _txt(self, r: int, c: int) -> str:
        it = self.table.item(r, c)
        return it.text().strip() if it else ""

    def _recalc(self):
        total = sum(self._num(r, 4) for r in range(self.table.rowCount()))
        n_with = sum(1 for r in range(self.table.rowCount()) if self._num(r, 4) > 0)
        self.total.setText(
            f"{self.table.rowCount()} item(s) · {n_with} with an opening balance · "
            f"total opening qty {total:,.2f}")
        # flag codes that already exist or repeat within the dialog
        seen, dupes, exists, blank = set(), [], [], 0
        for r in range(self.table.rowCount()):
            code = self._txt(r, 0)
            if not code:
                blank += 1
                continue
            if code in seen:
                dupes.append(code)
            seen.add(code)
            if self.db.one("SELECT 1 FROM items WHERE code=?", (code,)):
                exists.append(code)
        bits = []
        if exists:
            bits.append(f"<b>{', '.join(exists[:5])}</b> already exist(s) in the "
                        "Item Master — those lines will be linked to the existing "
                        "item instead of duplicated")
        if dupes:
            bits.append(f"<b>{', '.join(dupes[:5])}</b> appear(s) twice in this list")
        if blank:
            bits.append(f"{blank} row(s) have no code — one will be generated")
        self.warn.setText(
            f"<span style='color:{W.AMBER}'>⚠ " + "<br>⚠ ".join(bits) + "</span>"
            if bits else "")

    def _save(self):
        overrides = {}
        for r, ln in enumerate(self.lines):
            overrides[ln["id"]] = {
                "code": self._txt(r, 0), "description": self._txt(r, 1),
                "uom": self._txt(r, 2), "category": self._txt(r, 3),
                "opening_balance": self._num(r, 4), "unit_cost": self._num(r, 5),
                "warehouse": self._txt(r, 6), "location": self._txt(r, 7),
                "min_level": self._num(r, 8), "max_level": self._num(r, 9),
            }
        try:
            self.created = M.create_items_from_lines(
                self.db, [l["id"] for l in self.lines], overrides)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not add the items.\n\n{exc}")
            return
        self.accept()


class MaterialPage(QWidget):
    dataChanged = Signal()
    openHistory = Signal(int)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.checked: list[dict] = []
        self.last_file: Path | None = None
        self.cur_mr_id: int | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(9)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_new(), "1 · New / Check Request")
        self.tabs.addTab(self._tab_requests(), "2 · Requests && Preparation")
        self.tabs.addTab(self._tab_ready(), "3 · Ready to Deliver")
        self.tabs.currentChanged.connect(self._tab_changed)
        v.addWidget(self.tabs, 1)
        self._shortcuts()
        self.reload()

    def _shortcuts(self):
        """Keyboard shortcuts, scoped to this page so they never fight the
        main-window bindings."""
        def sc(seq, slot):
            a = QShortcut(QKeySequence(seq), self)
            a.setContext(Qt.WidgetWithChildrenShortcut)
            a.activated.connect(slot)
            return a

        sc("F5", self._refresh_current)
        sc("Ctrl+P", self._print_current)
        sc("Ctrl+S", self._save_current)
        sc("Ctrl+F", self._focus_search)
        sc("Del", self._delete_current)
        sc("Ctrl+Del", self.delete_request)
        sc("F2", self.set_prepared)
        sc("Ctrl+Shift+P", self.prepare_all)
        sc("Ctrl+D", self._deliver_current)
        sc("Ctrl+Return", self.show_details)
        sc("Alt+1", lambda: self.tabs.setCurrentIndex(0))
        sc("Alt+2", lambda: self.tabs.setCurrentIndex(1))
        sc("Alt+3", lambda: self.tabs.setCurrentIndex(2))

    # -- shortcut routing: the same key does the right thing on each tab
    def _refresh_current(self):
        i = self.tabs.currentIndex()
        if i == 2:
            self._load_ready()
        else:
            self.reload()

    def _print_current(self):
        i = self.tabs.currentIndex()
        if i == 0:
            self.export("pdf")
        elif i == 1:
            self.request_pdf()
        else:
            self.picking_pdf()

    def _save_current(self):
        if self.tabs.currentIndex() == 0:
            self.save_request()

    def _delete_current(self):
        """Del removes whatever is selected on the current tab."""
        i = self.tabs.currentIndex()
        if i == 0:
            self.remove_check_rows()
        elif i == 1:
            if self.t_lines.selectedIndexes():
                self.delete_line()
            else:
                self.delete_request()
        elif i == 2:
            self.delete_ready()

    def _deliver_current(self):
        i = self.tabs.currentIndex()
        if i == 1:
            self.process_lines()
        elif i == 2:
            self.make_dn()

    def _focus_search(self):
        i = self.tabs.currentIndex()
        if i == 1:
            self.f_text.setFocus()
            self.f_text.selectAll()
        elif i == 2:
            self.r_project.setFocus()

    # =============================================================== tab 1
    def _tab_new(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(8)

        info = QLabel(
            "Copy the request rows from Excel (with the header row) and paste below — "
            "or drag the file straight onto the box — then press "
            "<b>Check Availability</b>. Columns such as <i>Item number, Product name, Unit, "
            "Quantity, Purchase requisition reference</i> are recognised automatically.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(info)

        split = QSplitter(Qt.Horizontal)
        left = W.Card("Paste the project request")
        self.paste = DropPasteEdit()
        self.paste.setLineWrapMode(QPlainTextEdit.NoWrap)
        # Pasting from Excel must stay a plain tab-separated grid. Without this
        # the clipboard's HTML flavour is inserted as rich text, so the columns
        # arrive as styled markup and the tab structure is lost.
        try:
            from PySide6.QtWidgets import QTextEdit as _QTE  # noqa: F401
            self.paste.setTabChangesFocus(False)
        except Exception:
            pass
        _f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        _f.setPointSize(9)
        _f.setStyleHint(QFont.Monospace)
        _f.setFixedPitch(True)
        self.paste.setFont(_f)
        # a real tab stop, so pasted columns line up like a spreadsheet
        self.paste.setTabStopDistance(
            QFontMetricsF(_f).horizontalAdvance(" ") * 14)
        self.paste.fileDropped.connect(self._dropped_file)
        self.paste.setStyleSheet(
            "QPlainTextEdit{background:#ffffff; color:#16202b;"
            "border:1px solid #c9d6e2; border-radius:6px; padding:6px;"
            "selection-background-color:#cfe3f7; selection-color:#0b2437;}")
        self.paste.setPlaceholderText(
            "Line\tProject ID\tItem number\tProcurement category\tProduct name\tUnit\t"
            "Quantity\tStatus\tCategory\tPurchase requisition reference\n"
            "1\tPRJ_0000071-0001\t11000WA01\tAccommodation\tWindow AC\tNo\t1.00\tIn review\t"
            "Accommodation\t001282")
        left.add(self.paste, 1)
        row = QHBoxLayout()
        row.addWidget(W.button("✔  Check Availability", "Primary", self.check_paste,
                               shortcut="Ctrl+Return"))
        row.addWidget(W.button("📋  Paste && Check", slot=self.paste_and_check))
        left.v.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(W.button("📂  Load Excel / CSV", slot=self.load_file))
        row2.addWidget(W.button("🧹  Clear", slot=self.clear))
        left.v.addLayout(row2)
        left.setMinimumWidth(430)
        left.setMaximumWidth(520)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)

        hdr = QGroupBox("Request details")
        hf = QGridLayout(hdr)
        hf.setHorizontalSpacing(12)
        self.h_project = QLineEdit()
        self.h_project.setPlaceholderText("Project ID")
        self.h_site = W.combo([""] + lookup(self.db, "sites"), True)
        self.h_dept = QLineEdit(self.db.get_setting("mr_default_department",
                                                    "Site Team"))
        self.h_dept.setPlaceholderText("Department")
        self.h_by = QLineEdit(self.db.get_setting("mr_default_requested_by",
                                                  "By Site Team"))
        self.h_by.setPlaceholderText("Requested by")
        self.h_ref = QLineEdit()
        self.h_ref.setPlaceholderText("Auto-filled from the PR column")
        self.h_date = date_edit()
        for i, (lbl, wd) in enumerate((("Project ID", self.h_project), ("Site", self.h_site),
                                       ("Department", self.h_dept), ("Requested by", self.h_by),
                                       ("Reference", self.h_ref), ("Date", self.h_date))):
            box = QVBoxLayout()
            box.setSpacing(2)
            l = QLabel(lbl.upper())
            l.setStyleSheet(f"color:{W.MUTED}; font-size:10px; font-weight:600;")
            wd.setMinimumWidth(150)
            box.addWidget(l)
            box.addWidget(wd)
            cw = QWidget()
            cw.setLayout(box)
            hf.addWidget(cw, i // 3, i % 3)
        self.autofill_note = QLabel("")
        self.autofill_note.setWordWrap(True)
        self.autofill_note.setStyleSheet(f"color:{W.NAVY}; font-size:11px;")
        hf.addWidget(self.autofill_note, 2, 0, 1, 3)
        rv.addWidget(hdr)

        self.summary = QLabel("Paste a request and press Check Availability.")
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER};"
                                   "border-radius:8px; padding:10px;")
        rv.addWidget(self.summary)

        act = QHBoxLayout()
        act.setSpacing(6)
        act.addWidget(W.button("💾  Save as Material Request", "Accent", self.save_request,
                               tip="Store the request so the team can prepare it"))
        act.addWidget(W.button("📄 PDF", slot=lambda: self.export("pdf")))
        act.addWidget(W.button("📊 Excel", slot=lambda: self.export("xlsx")))
        act.addWidget(W.button("📑 CSV", slot=lambda: self.export("csv")))
        act.addWidget(W.button("🖨 Print", slot=self.print_out))
        act.addWidget(W.button("🗑  Remove Selected Rows", slot=self.remove_check_rows,
                               tip="Take the highlighted lines out of this check "
                                   "before saving  (Del)"))
        self.only_short = QCheckBox("Only shortages")
        self.only_short.toggled.connect(self._render_check)
        act.addWidget(self.only_short)
        act.addStretch(1)
        rv.addLayout(act)

        self.t_check = W.DataTable()
        self.t_check.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.t_check.setContextMenuPolicy(Qt.CustomContextMenu)
        self.t_check.customContextMenuRequested.connect(self._menu_check)
        rv.addWidget(self.t_check, 1)
        rv.addWidget(ShareBar(self.db, lambda: self.last_file, self))
        split.addWidget(right)
        split.setSizes([460, 1040])
        v.addWidget(split, 1)
        return w

    def _autofill_header(self, parsed: list[dict]) -> None:
        """Fill the request header from the pasted rows.

        · Project ID  <- the project column
        · Site        <- the same Project ID (they are one and the same here)
        · Department  <- "Site Team"      (configurable default)
        · Requested by<- "By Site Team"   (configurable default)
        · Reference   <- every distinct PR number found in the paste

        Anything the operator has already typed by hand is left alone.
        """
        projects = [str(l.get("project_id") or "").strip() for l in parsed]
        projects = [p for p in projects if p]
        project = projects[0] if projects else ""

        if project and not self.h_project.text().strip():
            self.h_project.setText(project)
        # Site mirrors the Project ID unless the user picked something else
        if project and not self.h_site.currentText().strip():
            if self.h_site.findText(project) < 0:
                self.h_site.addItem(project)
            self.h_site.setCurrentText(project)

        if not self.h_dept.text().strip():
            self.h_dept.setText(self.db.get_setting("mr_default_department",
                                                    "Site Team"))
        if not self.h_by.text().strip():
            self.h_by.setText(self.db.get_setting("mr_default_requested_by",
                                                  "By Site Team"))

        # Reference = the PR number(s) on the pasted lines, de-duplicated in order
        seen, prs = set(), []
        for l in parsed:
            pr = str(l.get("pr_no") or "").strip()
            if pr and pr not in seen:
                seen.add(pr)
                prs.append(pr)
        if prs and not self.h_ref.text().strip():
            self.h_ref.setText(", ".join(prs))

        extra = ""
        if len(projects) > 1 and len(set(projects)) > 1:
            extra = (f"  ⚠ {len(set(projects))} different project IDs in this paste — "
                     f"using {project}")
        self.autofill_note.setText(
            (f"Auto-filled  ·  Project/Site: <b>{project or '-'}</b>  ·  "
             f"PR: <b>{', '.join(prs) or '-'}</b>{extra}") if (project or prs) else "")

    def clear(self):
        """Clear everything on this tab back to a fresh request."""
        self.paste.clear()
        self.checked = []
        self.t_check.setRowCount(0)
        self.h_project.clear()
        self.h_site.setCurrentIndex(0)
        self.h_site.setCurrentText("")
        self.h_ref.clear()
        self.h_dept.setText(self.db.get_setting("mr_default_department", "Site Team"))
        self.h_by.setText(self.db.get_setting("mr_default_requested_by",
                                              "By Site Team"))
        self.h_date.setDate(QDate.currentDate())
        self.only_short.setChecked(False)
        self.autofill_note.clear()
        self.last_file = None
        self.summary.setText("Paste a request and press Check Availability.")

    def paste_and_check(self):
        from PySide6.QtWidgets import QApplication
        t = QApplication.clipboard().text()
        if not t.strip():
            W.error_box(self, "The clipboard is empty.")
            return
        self.paste.setPlainText(t)
        self.check_paste()

    def _dropped_file(self, path: str):
        """An Excel/CSV file was dragged onto the paste box."""
        from pathlib import Path as _P
        p = _P(path)
        if p.suffix.lower() not in (".xlsx", ".xlsm", ".csv", ".txt"):
            W.error_box(self, f"{p.name} is not a spreadsheet.\n\n"
                              "Drop an .xlsx, .csv or .txt file.")
            return
        self._load_path(str(p))

    def load_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Load request list", "",
                                           "Spreadsheets (*.xlsx *.xlsm *.csv *.txt)")
        if f:
            self._load_path(f)

    def _load_path(self, f: str):
        """Read a request sheet into the paste box and check it (shared by the
        Load button and by dragging a file onto the box)."""
        try:
            if Path(f).suffix.lower() in (".xlsx", ".xlsm", ".csv"):
                head, rows = importer.read_table(f)
                text = "\t".join(head) + "\n" + "\n".join(
                    "\t".join("" if c is None else str(c) for c in r) for r in rows)
            else:
                text = Path(f).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read the file.\n\n{exc}")
            return
        self.paste.setPlainText(text)
        self.check_paste()
        W.toast(self, f"Loaded {Path(f).name}")

    def check_paste(self):
        text = self.paste.toPlainText()
        if not text.strip():
            W.error_box(self, "Paste the request rows first.")
            return
        head, rows = M.sniff_table(text)
        parsed = M.parse_rows(head, rows)
        if not parsed:
            W.error_box(self, "No item rows were recognised.\n\nMake sure the paste includes "
                              "an Item number (or Product name) and a Quantity column.")
            return
        self.checked = M.enrich(self.db, parsed)
        self._autofill_header(parsed)
        self._render_check()
        self.db.audit("EXPORTED", "MR-check", "", f"{len(self.checked)} line(s) checked")

    def _render_check(self):
        show = self.checked
        if self.only_short.isChecked():
            show = [l for l in show if l["avail_status"] in
                    (M.PARTIAL, M.NONE_AVAIL, M.NOT_FOUND)]
        rows = []
        for i, l in enumerate(show, 1):
            can = min(float(l.get("qty") or 0), float(l.get("available") or 0))
            rows.append([l.get("line_no") or i, l["item_code"],
                         l["description"] if l.get("found") else
                         f"{l['description']}  ⚠ not in item master",
                         l.get("uom", ""), round(float(l.get("qty") or 0), 2),
                         round(l["on_hand"], 2), round(l["reserved"], 2),
                         round(l["available"], 2), round(can, 2), round(l["short"], 2),
                         l["avail_status"], l.get("pr_no", ""), l.get("project_id", ""),
                         l.get("warehouse", ""), l.get("location", ""),
                         l.get("stock_status", "")])
        self.t_check.fill(CHECK_COLS, rows, status_col=15)
        _paint(self.t_check, 10, M.AVAIL_COLORS)
        s = M.summarize(self.checked)
        cur = self.db.get_setting("currency", "")
        col = M.AVAIL_COLORS[s["overall"]]
        def cell(label, value, colour="", w=90):
            style = f"color:{colour};" if colour else ""
            return (f"<td width='{w}' style='{style}'>"
                    f"<span style='font-size:11px'>{label}</span><br>"
                    f"<b style='font-size:17px'>{value}</b></td>")
        self.summary.setText(
            "<table width='100%' cellspacing='0'><tr>"
            + cell("Lines", s["lines"], "", 60)
            + cell("Full", s["full"], M.AVAIL_COLORS[M.FULL], 60)
            + cell("Partial", s["partial"], M.AVAIL_COLORS[M.PARTIAL], 70)
            + cell("Not avail.", s["none"], M.AVAIL_COLORS[M.NONE_AVAIL], 80)
            + cell("Not in master", s["not_found"], M.AVAIL_COLORS[M.NOT_FOUND], 100)
            + cell("Requested", f"{s['req_qty']:,.2f}")
            + cell("Can supply", f"{s['can_supply']:,.2f}")
            + cell("Shortage", f"{s['short_qty']:,.2f}",
                   M.AVAIL_COLORS[M.NONE_AVAIL] if s["short_qty"] else "")
            + cell("Value", f"{cur} {s['value']:,.0f}", "", 110)
            + f"<td style='color:{col}'><span style='font-size:11px'>Overall</span><br>"
              f"<b style='font-size:15px'>{s['overall']}</b></td>"
            + "</tr></table>")

    def remove_check_rows(self):
        """Drop the highlighted lines from the check before it is saved.

        Nothing is stored yet at this point, so this only edits the pending
        list — no database record is touched.
        """
        if not self.checked:
            W.error_box(self, "Check a request first.")
            return
        rows = sorted({i.row() for i in self.t_check.selectedIndexes()})
        if not rows:
            W.error_box(self, "Select one or more rows in the table first.")
            return
        # the grid may be filtered to shortages, so match on what is displayed
        keys = set()
        for r in rows:
            code = self.t_check.item(r, 1).text() if self.t_check.item(r, 1) else ""
            line = self.t_check.item(r, 0).text() if self.t_check.item(r, 0) else ""
            keys.add((line, code))
        if not W.confirm(self, f"Remove {len(keys)} line(s) from this check?"):
            return
        kept = []
        for i, l in enumerate(self.checked, 1):
            key = (str(l.get("line_no") or i), l.get("item_code", ""))
            if key not in keys:
                kept.append(l)
        removed = len(self.checked) - len(kept)
        self.checked = kept
        if not self.checked:
            self.clear()
            W.toast(self, "All lines removed — the check is empty.")
            return
        self._render_check()
        W.toast(self, f"{removed} line(s) removed from the check.")

    def save_request(self):
        if not self.checked:
            W.error_box(self, "Check a request first.")
            return
        header = {"mr_date": iso(self.h_date), "project_id": self.h_project.text().strip(),
                  "site": self.h_site.currentText().strip(),
                  "department": self.h_dept.text().strip(),
                  "requested_by": self.h_by.text().strip(),
                  "reference": self.h_ref.text().strip(),
                  "pr_no": ", ".join(sorted({l["pr_no"] for l in self.checked if l.get("pr_no")}))}
        try:
            mr = M.save_request(self.db, header, self.checked)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.dataChanged.emit()
        # The request now lives in tab 2, so tab 1 is wiped ready for the next
        # PR -- leaving the old lines on screen invited saving them twice.
        self.clear()
        self.reload()
        W.toast(self, f"Material Request {mr} saved and moved to "
                      f"Requests & Preparation. The check sheet is now clear.")
        self.tabs.setCurrentIndex(1)
        for r in range(self.t_req.rowCount()):
            if self.t_req.item(r, 0) and self.t_req.item(r, 0).text() == mr:
                self.t_req.selectRow(r)
                self._load_lines(force=True)
                break

    def export(self, kind: str):
        if not self.checked:
            W.error_box(self, "Check a request first.")
            return
        title = self._check_title()
        sub = (f"Project: {self.h_project.text() or '-'}   Site: "
               f"{self.h_site.currentText() or '-'}   Requested by: {self.h_by.text() or '-'}")
        fn = {"xlsx": D.export_excel, "csv": D.export_csv}.get(kind)
        if kind == "pdf":
            self.last_file = D.material_check_pdf(
                self.db, title, self.t_check.headers(), self.t_check.all_rows(),
                stats=self._check_stats(), header_pairs=self._check_pairs(),
                subtitle=sub)
        else:
            self.last_file = fn(self.db, title, self.t_check.headers(), self.t_check.all_rows())
        W.toast(self, f"Saved: {self.last_file.name}")
        D.open_path(self.last_file)

    def _check_stats(self):
        """KPI tiles for the printed check view — mirrors the on-screen strip."""
        s_ = M.summarize(self.checked)
        cur = self.db.get_setting("currency", "")
        return [("Lines", f"{s_['lines']}", "#12283f"),
                ("Full", f"{s_['full']}", M.AVAIL_COLORS[M.FULL]),
                ("Partial", f"{s_['partial']}", M.AVAIL_COLORS[M.PARTIAL]),
                ("Not avail.", f"{s_['none']}", M.AVAIL_COLORS[M.NONE_AVAIL]),
                ("Not in master", f"{s_['not_found']}", M.AVAIL_COLORS[M.NOT_FOUND]),
                ("Requested", f"{s_['req_qty']:,.2f}", "#12283f"),
                ("Can supply", f"{s_['can_supply']:,.2f}", "#0f7b3d"),
                ("Shortage", f"{s_['short_qty']:,.2f}",
                 M.AVAIL_COLORS[M.NONE_AVAIL] if s_["short_qty"] else "#0f7b3d"),
                ("Value", f"{cur} {s_['value']:,.0f}", "#12283f"),
                ("Overall", s_["overall"], M.AVAIL_COLORS[s_["overall"]])]

    def _check_title(self) -> str:
        """Heading for the availability check — names the site's PR number and
        project, which is how the requester identifies the paperwork."""
        prs, seen = [], set()
        for l in self.checked:
            pr = str(l.get("pr_no") or "").strip()
            if pr and pr not in seen:
                seen.add(pr)
                prs.append(pr)
        project = (self.h_project.text().strip()
                   or self.h_site.currentText().strip())
        title = "Material Availability Report"
        if prs:
            shown = prs[:3]
            tail = f" +{len(prs) - 3} more" if len(prs) > 3 else ""
            label = "PR / MR No." if len(prs) == 1 else "PR / MR Nos."
            title += f"  ·  {label} {', '.join(shown)}{tail}"
        if project:
            title += f"  ·  {project}"
        return title

    def _check_pairs(self):
        prs = sorted({l["pr_no"] for l in self.checked if l.get("pr_no")})
        projects = sorted({l.get("project_id") for l in self.checked
                           if l.get("project_id")})
        return [("Date", iso(self.h_date)),
                ("Project", self.h_project.text() or (projects[0] if projects else "-")),
                ("Site", self.h_site.currentText() or "-"),
                ("Department", self.h_dept.text() or "-"),
                ("Requested By", self.h_by.text() or "-"),
                ("Reference", self.h_ref.text() or "-"),
                ("PR / MR No.", ", ".join(prs) or "-"),
                ("Checked By", self.db.current_user),
                ("Checked On", _dt.datetime.now().strftime("%d-%m-%Y %H:%M"))]

    def print_out(self):
        if not self.checked:
            W.error_box(self, "Check a request first.")
            return
        self.last_file = D.material_check_pdf(
            self.db, self._check_title(), self.t_check.headers(),
            self.t_check.all_rows(), stats=self._check_stats(),
            header_pairs=self._check_pairs())
        D.print_file(self.db, self.last_file)

    # =============================================================== tab 2
    def _tab_requests(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(8)
        bar = QHBoxLayout()
        self.f_status = W.combo(["All", M.PENDING, M.PREPARING, M.READY, M.PART_DELIVERED,
                                 M.DELIVERED, M.CANCELLED])
        self.f_status.currentTextChanged.connect(self.reload)
        bar.addWidget(QLabel("Status:"))
        bar.addWidget(self.f_status)
        self.f_text = W.SearchBox("Search MR / project / item / PR ...")
        self.f_text.textChanged.connect(self.reload)
        bar.addWidget(self.f_text, 1)
        self.f_show_ready = QCheckBox("Show completed (Ready / Delivered)")
        self.f_show_ready.setToolTip(
            "A request whose lines are all Ready to Deliver leaves this screen "
            "and lives on tab 3.\nTick this to bring finished requests back into "
            "the list for reference.")
        self.f_show_ready.toggled.connect(self.reload)
        bar.addWidget(self.f_show_ready)
        bar.addWidget(W.button("🔄 Refresh", slot=self.reload))
        v.addLayout(bar)

        ract = QHBoxLayout()
        ract.addWidget(W.button("🗑  Delete Request", slot=self.delete_request,
                                tip="Permanently remove the selected request(s)  (Ctrl+Del)"))
        ract.addWidget(W.button("🚫  Cancel Request", slot=self.cancel_request,
                                tip="Keep the request but mark it Cancelled"))
        ract.addWidget(W.button("♻  Restore Request", slot=self.restore_request,
                                tip="Undo a cancellation"))
        ract.addWidget(W.button("📄  Print / PDF", "Accent", self.request_pdf,
                                tip="Professional print view of this request  (Ctrl+P)"))
        ract.addStretch(1)
        self.lbl_reqcount = QLabel()
        self.lbl_reqcount.setStyleSheet(f"color:{W.MUTED};")
        ract.addWidget(self.lbl_reqcount)
        v.addLayout(ract)

        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        self.t_req = W.DataTable()
        self.t_req.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.t_req.itemSelectionChanged.connect(self._load_lines)
        self.t_req.setContextMenuPolicy(Qt.CustomContextMenu)
        self.t_req.customContextMenuRequested.connect(self._menu_requests)
        tv.addWidget(self.t_req)
        split.addWidget(top)

        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 6, 0, 0)
        bv.setSpacing(6)
        self.lbl_mr = QLabel("Select a request above")
        self.lbl_mr.setStyleSheet(f"color:{W.NAVY}; font-weight:700;")
        bv.addWidget(self.lbl_mr)

        act = QHBoxLayout()
        act.addWidget(W.button("🔍  Show Details", slot=self.show_details,
                               tip="Load the item lines of the selected request"))
        act.addWidget(W.button("✅  Prepare All Available", "Primary", self.prepare_all,
                               tip="Reserve everything the warehouse can supply right now"))
        act.addWidget(W.button("✏  Set Prepared Qty", slot=self.set_prepared,
                               tip="Enter exactly how much was picked for this line"))
        act.addWidget(W.button("↩  Unprepare Line", slot=lambda: self._quick_prepare(0)))
        act.addWidget(W.button("🔗  Link to Item", slot=self.link_item,
                               tip="Map an unknown request code to an existing item"))
        act.addWidget(W.button("🌐  Google Item", slot=self.google_item_lookup,
                               tip="Search the selected request line on Google and preview the result inside AURCO"))
        act.addWidget(W.button("➕  Add to Item Master", slot=self.create_item,
                               tip="Add the selected line(s) to the Item Master and "
                                   "enter their opening balance.\nSelect nothing to "
                                   "add every unlinked line of the request."))
        act.addWidget(W.button("⚙  Process", "Accent", self.process_lines,
                               tip="Move the selected line(s) to Ready to Deliver.\n"
                                   "Uses the quantity you already marked, or "
                                   "whatever is available if nothing is marked.\n"
                                   "Select nothing to process the whole request."))
        act.addWidget(W.button("🚫  Cancel Line", slot=self.cancel_line))
        act.addWidget(W.button("🗑  Delete Line(s)", slot=self.delete_line,
                               tip="Remove the selected line(s) from the request "
                                   "— works on a multi-selection  (Del)"))
        act.addWidget(W.button("☑  Select All Lines",
                               slot=lambda: self.t_lines.selectAll()))
        act.addWidget(W.button("📄  Request PDF", slot=self.request_pdf))
        act.addStretch(1)
        bv.addLayout(act)

        self.t_lines = W.DataTable()
        self.t_lines.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.t_lines.doubleClicked.connect(self.set_prepared)
        self.t_lines.setContextMenuPolicy(Qt.CustomContextMenu)
        self.t_lines.customContextMenuRequested.connect(self._menu_lines)
        bv.addWidget(self.t_lines, 1)
        split.addWidget(bottom)
        split.setSizes([260, 440])
        v.addWidget(split, 1)
        return w

    def reload(self):
        status = "" if self.f_status.currentIndex() == 0 else self.f_status.currentText()
        # Requests & Preparation is a working list: once every live line of a
        # request is Ready to Deliver the request has left preparation, so it is
        # hidden here and worked on from tab 3. Picking that status explicitly in
        # the filter -- or ticking "Show completed" -- brings it back.
        hide = ()
        if not status and not self.f_show_ready.isChecked():
            hide = (M.READY, M.DELIVERED)
        self.requests = M.list_requests(self.db, status, self.f_text.text().strip(),
                                        exclude_status=hide)
        rows = [[r["mr_no"], r["mr_date"], r["project_id"], r["site"], r["requested_by"],
                 r["pr_no"], r["n_lines"], round(r["q_req"], 2), round(r["q_prep"], 2),
                 round(r["q_del"], 2), round(max(0.0, r["q_req"] - r["q_del"]), 2),
                 r["status"]] for r in self.requests]
        self.t_req.fill(["MR Number", "Date", "Project ID", "Site", "Requested By",
                         "PR / MR No.", "Lines", "Req Qty", "Prepared", "Delivered",
                         "Pending", "Status"], rows)
        _paint(self.t_req, 11, M.FULFIL_COLORS)
        if hasattr(self, "lbl_reqcount"):
            txt = f"{len(rows)} open request(s)"
            if hide:
                done = len(M.list_requests(self.db, "", self.f_text.text().strip())) - len(rows)
                if done > 0:
                    txt += f"  ·  {done} completed hidden"
            self.lbl_reqcount.setText(txt)
        if rows and getattr(self, "cur_mr_id", None) and \
                not any(r_["id"] == self.cur_mr_id for r_ in self.requests):
            # the request we were working on has left this screen (now Ready)
            self.cur_mr_id = None
            self.lines = []
            self.t_req.clearSelection()
            self.t_req.setCurrentCell(-1, -1)
        if rows:
            keep = getattr(self, "cur_mr_id", None)
            target = 0
            if keep:
                for i, r_ in enumerate(self.requests):
                    if r_["id"] == keep:
                        target = i
                        break
            if self.t_req.currentRow() < 0:
                self.t_req.selectRow(min(target, self.t_req.rowCount() - 1))
            self._load_lines()
        else:
            self.t_lines.setRowCount(0)
            self.cur_mr_id = None
            self.lines = []
            if hide and "hidden" in self.lbl_reqcount.text():
                self.lbl_mr.setText("Nothing left to prepare — every request is "
                                    "Ready to Deliver or already delivered  "
                                    "(see tab 3)")
            else:
                self.lbl_mr.setText("No requests match the current filter")
        if hasattr(self, "t_ready"):
            self._load_ready()

    def _sel_request(self) -> dict | None:
        r = self.t_req.currentRow()
        if r < 0 or self.t_req.item(r, 0) is None:
            return None
        no = self.t_req.item(r, 0).text()
        hit = next((x for x in getattr(self, "requests", []) if x["mr_no"] == no), None)
        if hit is None:
            # the cached list is stale (sorted / filtered / refreshed elsewhere)
            row = self.db.one("SELECT * FROM material_requests WHERE mr_no=?", (no,))
            hit = dict(row) if row else None
            if hit:
                self.requests = getattr(self, "requests", []) + [hit]
        return hit

    def show_details(self):
        """Explicitly (re)load the selected request — never leaves a blank grid."""
        if self.t_req.currentRow() < 0 and self.t_req.rowCount():
            self.t_req.selectRow(0)
        if not self._sel_request():
            W.error_box(self, "Select a request in the list above first.")
            return
        self._load_lines(force=True)

    def _load_lines(self, force: bool = False):
        mr = self._sel_request()
        if not mr:
            # selection lost (filter change, sort, refresh) -> fall back to row 0
            if self.t_req.rowCount():
                self.t_req.selectRow(0)
                mr = self._sel_request()
            if not mr:
                self.t_lines.setRowCount(0)
                self.lbl_mr.setText("Select a request above")
                return
        self.cur_mr_id = mr["id"]
        self.lines = M.request_lines(self.db, mr["id"])
        rows = []
        for l in self.lines:
            rows.append([l["line_no"], l["item_code"],
                         l["description"] if l["item_id"] else
                         f"{l['description']}  ⚠ not in item master",
                         l["uom"], round(l["qty_requested"], 2), round(l["on_hand"], 2),
                         round(l["available"], 2), round(l["qty_prepared"], 2),
                         round(l["qty_delivered"], 2), round(l["pending"], 2),
                         round(l["short"], 2), l["avail_status"], l["status"],
                         l["pr_no"], l["dn_no"], l["prepared_by"] or "", l["remarks"]])
        self.t_lines.fill(["Line", "Item Code", "Description", "UOM", "Requested", "In Stock",
                           "Available", "Prepared", "Delivered", "Pending", "Short By",
                           "Availability", "Fulfilment", "PR / MR No.", "DN No.", "Prepared By",
                           "Remarks"], rows)
        _paint(self.t_lines, 11, M.AVAIL_COLORS)
        _paint(self.t_lines, 12, M.FULFIL_COLORS)
        self.lbl_mr.setText(
            f"{mr['mr_no']}  ·  {mr['project_id'] or mr['site'] or '-'}  ·  "
            f"requested by {mr['requested_by'] or '-'}  ·  status: {mr['status']}")

    def _sel_line(self) -> dict | None:
        r = self.t_lines.currentRow()
        if r < 0 or not getattr(self, "lines", None):
            W.error_box(self, "Select a request line first.")
            return None
        code = self.t_lines.item(r, 1).text()
        lineno = self.t_lines.item(r, 0).text()
        return next((l for l in self.lines
                     if l["item_code"] == code and str(l["line_no"]) == lineno), None)

    def _sel_lines(self) -> list[dict]:
        """Every request line highlighted in the lines grid."""
        keys = {(self.t_lines.item(i.row(), 0).text(),
                 self.t_lines.item(i.row(), 1).text())
                for i in self.t_lines.selectedIndexes()
                if self.t_lines.item(i.row(), 0) and self.t_lines.item(i.row(), 1)}
        return [l for l in getattr(self, "lines", [])
                if (str(l["line_no"]), l["item_code"]) in keys]

    def prepare_all(self):
        mr = self._sel_request()
        if not mr:
            W.error_box(self, "Select a request first.")
            return
        try:
            n = M.prepare_all_available(self.db, mr["id"])
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        self._load_lines()
        self.dataChanged.emit()
        W.toast(self, f"{n} line(s) prepared and reserved for {mr['mr_no']}.")

    def _quick_prepare(self, qty: float):
        """qty >= 0 sets that quantity; qty < 0 means 'as much as possible'."""
        ln = self._sel_line()
        if not ln:
            return
        if qty < 0:
            qty = float(ln["qty_delivered"] or 0) + min(
                float(ln["pending"] or 0), float(ln["available"] or 0))
        try:
            M.set_prepared(self.db, ln["id"], qty)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        self._load_lines()
        self.dataChanged.emit()

    def set_prepared(self):
        ln = self._sel_line()
        if not ln:
            return
        maxq = ln["qty_requested"]
        val, ok = QInputDialog.getDouble(
            self, "Prepared quantity",
            f"{ln['item_code']} — {ln['description']}\n\n"
            f"Requested: {ln['qty_requested']:g}   In stock: {ln['on_hand']:g}   "
            f"Available: {ln['available']:g}\n\nHow much has the team prepared?",
            min(maxq, ln["qty_prepared"] or min(maxq, ln["available"])), 0, 1e9, 2)
        if not ok:
            return
        try:
            M.set_prepared(self.db, ln["id"], val)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        self._load_lines()
        self.dataChanged.emit()
        W.toast(self, f"{ln['item_code']}: {val:g} prepared.")

    def link_item(self):
        ln = self._sel_line()
        if not ln:
            return
        picked = ItemPicker.pick(self.db, self, multi=False)
        if not picked:
            return
        M.link_item(self.db, ln["id"], picked[0]["id"])
        self._load_lines()
        W.toast(self, f"Linked to {picked[0]['code']}.")

    def _google_query_for_line(self, ln: dict) -> str:
        parts = [ln.get("item_code"), ln.get("description"), ln.get("pr_no")]
        return " ".join(str(p).strip() for p in parts if str(p or "").strip())

    def google_item_lookup(self):
        ln = self._sel_line()
        if not ln:
            return
        GoogleResultsDialog.open(self, self._google_query_for_line(ln))

    def create_item(self):
        """Add the selected request line(s) to the Item Master.

        Works on a multi-selection; with nothing selected it offers every line
        of the request that is not in the master yet. A dialog collects the
        opening balance (and the other item fields) for all of them at once.
        """
        mr = self._sel_request()
        if not mr:
            W.error_box(self, "Select a request first.")
            return
        sel = [l for l in self._sel_lines() if not l.get("item_id")]
        whole = False
        if not sel:
            one = self._sel_line() if self.t_lines.selectedIndexes() else None
            if one and not one.get("item_id"):
                sel = [one]
            elif one and one.get("item_id"):
                W.error_box(self, "That line is already linked to an item.")
                return
        if not sel:
            sel = M.unlinked_lines(self.db, mr["id"])
            whole = True
        if not sel:
            W.error_box(self, "Every line of this request is already in the "
                              "Item Master.")
            return
        if whole and not W.confirm(
                self, f"No line is selected.\n\nAdd all {len(sel)} line(s) that are "
                      f"not yet in the Item Master?"):
            return
        dlg = BulkCreateItemsDialog(self.db, sel, self)
        if dlg.exec() != QDialog.Accepted or not dlg.created:
            return
        res = dlg.created
        self.reload()
        self._load_lines(force=True)
        self.dataChanged.emit()
        bits = []
        if res["created"]:
            bits.append(f"{res['created']} item(s) created")
        if res["qty"]:
            bits.append(f"opening stock {res['qty']:,.2f}")
        if res["linked"]:
            bits.append(f"{res['linked']} linked to existing items")
        W.toast(self, "  ·  ".join(bits) or "Nothing added.")
        if res["skipped"]:
            W.info_box(self, f"{res['created']} item(s) added to the Item Master.\n\n"
                             "These were handled differently:\n  "
                             + "\n  ".join(res["skipped"][:12]),
                       "Add to Item Master")

    def cancel_line(self):
        ln = self._sel_line()
        if not ln:
            return
        reason, ok = QInputDialog.getText(self, "Cancel line", "Reason:")
        if not ok:
            return
        try:
            M.cancel_line(self.db, ln["id"], reason)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        self._load_lines()

    def _sel_requests(self) -> list[dict]:
        """Every request highlighted in the list (supports multi-select)."""
        nos = {self.t_req.item(i.row(), 0).text()
               for i in self.t_req.selectedIndexes() if self.t_req.item(i.row(), 0)}
        out = [x for x in getattr(self, "requests", []) if x["mr_no"] in nos]
        if not out and nos:
            for no in nos:
                row = self.db.one("SELECT * FROM material_requests WHERE mr_no=?", (no,))
                if row:
                    out.append(dict(row))
        return out

    def delete_request(self):
        """Permanently delete the selected request(s)."""
        sel = self._sel_requests()
        if not sel:
            W.error_box(self, "Select one or more requests in the list above first.")
            return
        blocked = []
        for mr in sel:
            ok, why = M.can_delete_request(self.db, mr["id"])
            if not ok:
                blocked.append(f"{mr['mr_no']} — {why}")
        names = ", ".join(m["mr_no"] for m in sel)
        if blocked and len(blocked) == len(sel):
            W.error_box(self, "Nothing can be deleted:\n\n" + "\n\n".join(blocked))
            return
        msg = (f"Permanently delete {len(sel)} material request(s)?\n\n{names}\n\n"
               "The request and all its lines are removed and any reserved stock is "
               "released. Delivered history is never touched.")
        if blocked:
            msg += ("\n\nThese will be SKIPPED because they have deliveries:\n"
                    + "\n".join(blocked))
        if not W.confirm(self, msg):
            return
        done, skipped = M.delete_requests(self.db, [m["id"] for m in sel])
        self.cur_mr_id = None
        self.t_lines.setRowCount(0)
        self.reload()
        self.dataChanged.emit()
        if done:
            W.toast(self, f"Deleted: {', '.join(done)}")
        if skipped:
            W.error_box(self, "Some requests were kept:\n\n" + "\n\n".join(skipped))

    def cancel_request(self):
        sel = self._sel_requests()
        if not sel:
            W.error_box(self, "Select a request first.")
            return
        reason, ok = QInputDialog.getText(
            self, "Cancel request", f"Reason for cancelling {len(sel)} request(s):")
        if not ok:
            return
        for mr in sel:
            M.cancel_request(self.db, mr["id"], reason.strip())
        self.reload()
        self._load_lines()
        self.dataChanged.emit()
        W.toast(self, f"{len(sel)} request(s) cancelled — kept for the audit trail.")

    def restore_request(self):
        sel = self._sel_requests()
        if not sel:
            W.error_box(self, "Select a cancelled request first.")
            return
        for mr in sel:
            M.restore_request(self.db, mr["id"])
        self.reload()
        self._load_lines()
        self.dataChanged.emit()
        W.toast(self, f"{len(sel)} request(s) restored.")

    def delete_line(self):
        """Remove the selected request line(s) — one or many."""
        sel = self._sel_lines()
        if not sel:
            one = self._sel_line()
            sel = [one] if one else []
        if not sel:
            W.error_box(self, "Select one or more request lines first.")
            return
        blocked = [l for l in sel if float(l.get("qty_delivered") or 0) > 0]
        free = [l for l in sel if float(l.get("qty_delivered") or 0) <= 0]
        if not free:
            W.error_box(self, "Every selected line has already been delivered.\n\n"
                              "Cancel them instead so the delivery history is kept.")
            return
        msg = (f"Remove {len(free)} line(s) from this request?\n\n"
               + ", ".join(l["item_code"] or l["description"][:20] for l in free[:8])
               + ("  ..." if len(free) > 8 else "")
               + "\n\nAny reserved stock is released.")
        if blocked:
            msg += (f"\n\n{len(blocked)} delivered line(s) will be SKIPPED and kept "
                    "for the audit trail.")
        if not W.confirm(self, msg):
            return
        done, skipped = M.delete_lines(self.db, [l["id"] for l in free])
        self.reload()
        self._load_lines(force=True)
        self.dataChanged.emit()
        self._offer_cleanup()
        W.toast(self, f"{done} line(s) removed."
                      + (f" {len(skipped)} kept." if skipped else ""))
        if skipped:
            W.error_box(self, "These lines were kept:\n\n" + "\n".join(skipped[:10]))

    def _ready_of(self, lines: list[dict]) -> list[dict]:
        """Only the part of each line that is prepared and not yet delivered."""
        out = []
        for l in lines:
            ready = float(l.get("qty_prepared") or 0) - float(l.get("qty_delivered") or 0)
            if ready > 1e-9 and l.get("status") != M.CANCELLED:
                d = dict(l)
                d["qty_ready"] = ready
                d.setdefault("mr_project", l.get("project_id", ""))
                out.append(d)
        return out

    def process_lines(self):
        """Move the selected lines into Ready to Deliver.

        Respects a quantity the storekeeper already marked; otherwise reserves
        whatever the warehouse can supply. With nothing selected it processes
        the whole request, which is what people expect after pasting a PR.
        """
        # Qt keeps currentRow() after clearSelection(), so a stale row could
        # otherwise be processed without anything visibly highlighted. A reload
        # can also drop the highlight while a request is genuinely still open --
        # in that case re-assert the row rather than refusing the operator.
        if not self.t_req.selectedIndexes():
            restored = False
            if getattr(self, "cur_mr_id", None) and getattr(self, "lines", None):
                for r_ in range(self.t_req.rowCount()):
                    cell = self.t_req.item(r_, 0)
                    hit = next((x for x in getattr(self, "requests", [])
                                if cell and x["mr_no"] == cell.text()), None)
                    if hit and hit["id"] == self.cur_mr_id:
                        self.t_req.selectRow(r_)
                        restored = True
                        break
            if not restored:
                W.error_box(self, "Select a request in the list above first.")
                return
        mr = self._sel_request()
        if not mr:
            W.error_box(self, "Select a request first.")
            return
        sel = self._sel_lines()
        whole = not sel
        if whole:
            sel = [l for l in getattr(self, "lines", [])
                   if l.get("status") != M.CANCELLED]
        if not sel:
            W.error_box(self, f"{mr['mr_no']} has no lines to process.")
            return
        scope = ("every line of " + mr["mr_no"]) if whole else f"{len(sel)} line(s)"
        if not W.confirm(self, f"Process {scope}?\n\n"
                               "Lines you have already marked keep exactly that "
                               "quantity. Anything unmarked is reserved up to what "
                               "the warehouse can supply.\n\n"
                               "Nothing leaves the store yet — the material moves "
                               "to Ready to Deliver."):
            return
        try:
            res = M.process_lines(self.db, [l["id"] for l in sel])
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return

        self.reload()
        if self.cur_mr_id:            # still in preparation -> refresh its lines
            self._load_lines(force=True)
        if hasattr(self, "t_ready"):
            self._load_ready()
        self.dataChanged.emit()

        if not res["ready"]:
            W.error_box(self, "Nothing could be processed.\n\n"
                        + "\n".join(res["skipped"][:10]))
            return
        bits = [f"{res['ready']} line(s) moved to Ready to Deliver",
                f"total qty {res['qty']:,.2f}"]
        gone = self.db.one("SELECT status FROM material_requests WHERE id=?",
                           (mr["id"],))
        if gone and gone["status"] in (M.READY, M.DELIVERED):
            bits.append(f"{mr['mr_no']} left Requests & Preparation")
        if res["kept"]:
            bits.append(f"{res['kept']} used the quantity you marked")
        if res["prepared"]:
            bits.append(f"{res['prepared']} reserved from available stock")
        W.toast(self, "  ·  ".join(bits))
        if res["short"] or res["skipped"]:
            detail = ""
            if res["short"]:
                detail += ("Partly covered:\n  " + "\n  ".join(res["short"][:10])
                           + "\n\n")
            if res["skipped"]:
                detail += "Not processed:\n  " + "\n  ".join(res["skipped"][:10])
            W.info_box(self, f"{res['ready']} line(s) are now Ready to Deliver "
                             f"({res['qty']:,.2f} units).\n\n" + detail,
                       "Process complete")
        # land the operator where the material now is
        self.tabs.setCurrentIndex(2)

    def _deliver(self, ready: list[dict], empty_msg: str):
        """Shared delivery path used by tab 2 and tab 3."""
        if not ready:
            W.error_box(self, empty_msg)
            return
        mr = self._sel_request() or {}
        for r in ready:
            r.setdefault("mr_no", mr.get("mr_no", ""))
            r.setdefault("site", mr.get("site", ""))
            r.setdefault("department", mr.get("department", ""))
            r.setdefault("requested_by", mr.get("requested_by", ""))
            r["mr_project"] = r.get("mr_project") or mr.get("project_id", "")
        dlg = DeliverDialog(self.db, ready, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            dn = M.deliver_lines(self.db, [r["id"] for r in ready], dlg.header())
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        doc = self.db.one("SELECT id FROM documents WHERE doc_type='DN' AND doc_no=?",
                          (dn,))
        self.last_file = D.document_pdf(self.db, doc["id"]) if doc else None
        self.reload()
        self._load_lines(force=True)
        if hasattr(self, "t_ready"):
            self._load_ready()
        self.dataChanged.emit()
        W.toast(self, f"Delivery Note {dn} created — stock deducted.")
        if self.last_file and W.confirm(
                self, f"Delivery Note {dn} created and stock deducted.\n\n"
                      f"Saved as {self.last_file.name}\n\nOpen the PDF now?",
                "Delivery Note ready"):
            D.open_path(self.last_file)

    def _offer_cleanup(self):
        """A request whose last line was deleted is useless — offer to remove it."""
        empties = M.empty_requests(self.db)
        if not empties:
            return
        names = ", ".join(e["mr_no"] for e in empties[:6])
        if not W.confirm(self, f"{len(empties)} request(s) now have no lines left "
                               f"({names}).\n\nDelete the empty request(s) too?"):
            return
        done, _ = M.delete_requests(self.db, [e["id"] for e in empties])
        self.cur_mr_id = None
        self.t_lines.setRowCount(0)
        self.reload()
        self.dataChanged.emit()
        if done:
            W.toast(self, f"Removed empty request(s): {', '.join(done)}")

    def restore_line(self):
        ln = self._sel_line()
        if not ln:
            return
        M.restore_line(self.db, ln["id"])
        self.reload()
        self._load_lines(force=True)
        W.toast(self, "Line restored.")

    # ------------------------------------------------------- context menus
    def _menu_requests(self, pos):
        if self.t_req.currentRow() < 0 and self.t_req.rowCount():
            self.t_req.selectRow(self.t_req.rowAt(pos.y()))
        m = QMenu(self)
        m.addAction("🔍  Show Details\tEnter", self.show_details)
        m.addAction("✅  Prepare All Available\tCtrl+Shift+P", self.prepare_all)
        m.addSeparator()
        m.addAction("📄  Print / PDF\tCtrl+P", self.request_pdf)
        m.addAction("📊  Excel", lambda: self._req_export("xlsx"))
        m.addSeparator()
        m.addAction("♻  Restore Request", self.restore_request)
        m.addAction("🚫  Cancel Request", self.cancel_request)
        act = m.addAction("🗑  Delete Request\tCtrl+Del", self.delete_request)
        act.setShortcutVisibleInContextMenu(True)
        m.addSeparator()
        m.addAction("🔄  Refresh\tF5", self.reload)
        m.exec(self.t_req.viewport().mapToGlobal(pos))

    def _menu_lines(self, pos):
        r = self.t_lines.rowAt(pos.y())
        if r >= 0:
            self.t_lines.selectRow(r)
        m = QMenu(self)
        m.addAction("✏  Set Prepared Qty\tF2", self.set_prepared)
        m.addAction("✅  Prepare This Line Fully", lambda: self._quick_prepare(-1))
        m.addAction("↩  Unprepare Line", lambda: self._quick_prepare(0))
        m.addSeparator()
        m.addAction("⚙  Process → Ready to Deliver\tCtrl+D", self.process_lines)
        m.addSeparator()
        m.addAction("🔗  Link to Item", self.link_item)
        m.addAction("🌐  Search on Google", self.google_item_lookup)
        m.addAction("➕  Add Selected to Item Master...", self.create_item)
        m.addAction("📜  Movement History", self._line_history)
        m.addSeparator()
        m.addAction("♻  Restore Line", self.restore_line)
        m.addAction("🚫  Cancel Line", self.cancel_line)
        m.addAction("☑  Select All Lines\tCtrl+A", self.t_lines.selectAll)
        m.addAction("🗑  Delete Selected Line(s)\tDel", self.delete_line)
        m.addSeparator()
        m.addAction("📋  Copy Row\tCtrl+C", lambda: self._copy(self.t_lines))
        m.exec(self.t_lines.viewport().mapToGlobal(pos))

    def _menu_ready(self, pos):
        r = self.t_ready.rowAt(pos.y())
        if r >= 0 and not self.t_ready.selectedIndexes():
            self.t_ready.selectRow(r)
        m = QMenu(self)
        m.addAction("🚚  Create Delivery Note\tCtrl+D", self.make_dn)
        m.addAction("↩  Return to Stock (unprepare)", self.unprepare)
        m.addAction("🗑  Delete Selected Lines\tDel", self.delete_ready)
        m.addSeparator()
        m.addAction("☑  Select All\tCtrl+A", self.t_ready.selectAll)
        m.addAction("📄  Picking List PDF\tCtrl+P", self.picking_pdf)
        m.addAction("📊  Excel", self.ready_excel)
        m.addSeparator()
        m.addAction("📋  Copy\tCtrl+C", lambda: self._copy(self.t_ready))
        m.addAction("🔄  Refresh\tF5", self._load_ready)
        m.exec(self.t_ready.viewport().mapToGlobal(pos))

    def _menu_check(self, pos):
        r = self.t_check.rowAt(pos.y())
        if r >= 0:
            self.t_check.selectRow(r)
        m = QMenu(self)
        m.addAction("💾  Save as Material Request\tCtrl+S", self.save_request)
        m.addSeparator()
        m.addAction("☑  Select All\tCtrl+A", self.t_check.selectAll)
        m.addAction("🗑  Remove Selected Rows\tDel", self.remove_check_rows)
        m.addSeparator()
        m.addAction("📄  PDF\tCtrl+P", lambda: self.export("pdf"))
        m.addAction("📊  Excel", lambda: self.export("xlsx"))
        m.addAction("📑  CSV", lambda: self.export("csv"))
        m.addAction("🖨  Print", self.print_out)
        m.addSeparator()
        m.addAction("📋  Copy\tCtrl+C", lambda: self._copy(self.t_check))
        m.addAction("🧹  Clear", self.clear)
        m.exec(self.t_check.viewport().mapToGlobal(pos))

    def _copy(self, table):
        from PySide6.QtWidgets import QApplication
        rows = sorted({i.row() for i in table.selectedIndexes()})
        if not rows:
            return
        cols = range(table.columnCount())
        txt = "\n".join("\t".join(table.item(r, c).text() if table.item(r, c) else ""
                                  for c in cols) for r in rows)
        QApplication.clipboard().setText(txt)
        W.toast(self, f"{len(rows)} row(s) copied.")

    def _line_history(self):
        ln = self._sel_line()
        if ln and ln.get("item_id"):
            self.openHistory.emit(int(ln["item_id"]))
        elif ln:
            W.error_box(self, "This request line is not linked to an item yet.")

    def _req_export(self, kind: str):
        mr = self._sel_request()
        if not mr:
            W.error_box(self, "Select a request first.")
            return
        self.last_file = D.export_excel(
            self.db, f"Material Request {mr['mr_no']}", self.t_lines.headers(),
            self.t_lines.all_rows())
        W.toast(self, f"Saved: {self.last_file.name}")
        D.open_path(self.last_file)

    def request_pdf(self):
        mr = self._sel_request()
        if not mr:
            W.error_box(self, "Select a request first.")
            return
        lines = getattr(self, "lines", [])
        req = sum(float(l["qty_requested"] or 0) for l in lines)
        prep = sum(float(l["qty_prepared"] or 0) for l in lines)
        deliv = sum(float(l["qty_delivered"] or 0) for l in lines)
        short = sum(float(l["short"] or 0) for l in lines)
        stats = [("Lines", f"{len(lines)}", "#12283f"),
                 ("Requested", f"{req:,.2f}", "#12283f"),
                 ("Prepared", f"{prep:,.2f}", "#0b6e83"),
                 ("Delivered", f"{deliv:,.2f}", "#0f7b3d"),
                 ("Pending", f"{max(0.0, req - deliv):,.2f}", "#9a6700"),
                 ("Shortage", f"{short:,.2f}", "#b3261e" if short else "#0f7b3d")]
        pairs = [("MR Number", mr["mr_no"]), ("Date", mr["mr_date"]),
                 ("Project", mr["project_id"] or "-"), ("Site", mr["site"] or "-"),
                 ("Department", mr["department"] or "-"),
                 ("Requested By", mr["requested_by"] or "-"),
                 ("PR / MR No.", mr["pr_no"] or "-"), ("Status", mr["status"]),
                 ("Reference", mr["reference"] or "-")]

        # The heading must name the numbers people actually quote: the site's
        # own PR/MR number and the project. The internal MR-2026-xxxxx alone
        # means nothing to the requester who sent PR 001735 for PRJ_0000086.
        prs = self._request_prs(mr, lines)
        project = (mr["project_id"] or mr["site"] or "").strip()
        title = D.mr_title(mr["mr_no"], prs, project)
        self.last_file = D.material_check_pdf(
            self.db, title, self.t_lines.headers(),
            self.t_lines.all_rows(), stats=stats, header_pairs=pairs,
            out_path=D.mr_request_path(self.db, mr["mr_no"], prs, project))
        W.toast(self, f"Saved: {self.last_file.name}")
        D.open_path(self.last_file)

    @staticmethod
    def _request_prs(mr: dict, lines: list[dict]) -> list[str]:
        """Every distinct PR / MR number on the request, header first.

        The header field can hold several ("001735, 001736"), and individual
        lines may carry their own, so both are merged without duplicates.
        """
        seen: list[str] = []
        raw = [str(mr.get("pr_no") or "")] + [str(l.get("pr_no") or "") for l in lines]
        for chunk in raw:
            for pr in re.split(r"[,;/]| {2,}", chunk):
                pr = pr.strip()
                if pr and pr not in seen:
                    seen.append(pr)
        return seen

    # =============================================================== tab 3
    def _tab_ready(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(8)
        note = QLabel("Material already prepared by the store team and waiting for collection. "
                      "<b>No Delivery Note exists yet</b> — stock is reserved but still in the "
                      "warehouse. Select the lines that are going out and press "
                      "<b>Create Delivery Note</b>.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(note)

        bar = QHBoxLayout()
        self.r_project = W.SearchBox("Filter by project / site")
        self.r_mr = W.SearchBox("Filter by MR number")
        self.r_pr = W.SearchBox("Filter by PR number")
        for f in (self.r_project, self.r_mr, self.r_pr):
            f.textChanged.connect(self._load_ready)
            bar.addWidget(f)
        bar.addWidget(W.button("🔄 Refresh", slot=self._load_ready))
        v.addLayout(bar)

        self.ready_summary = QLabel("")
        self.ready_summary.setTextFormat(Qt.RichText)
        self.ready_summary.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER};"
                                         "border-radius:8px; padding:8px;")
        v.addWidget(self.ready_summary)

        act = QHBoxLayout()
        act.addWidget(W.button("☑  Select All", slot=lambda: self.t_ready.selectAll()))
        act.addWidget(W.button("🚚  Create Delivery Note from Selected", "Accent",
                               self.make_dn))
        act.addWidget(W.button("↩  Return to Stock (unprepare)", slot=self.unprepare))
        act.addWidget(W.button("🗑  Delete Selected Lines", slot=self.delete_ready,
                               tip="Remove the selected prepared line(s) from their "
                                   "request entirely  (Del)"))
        act.addWidget(W.button("📄  Picking List PDF", slot=self.picking_pdf,
                               tip="Print the prepared material list for the store team"))
        act.addWidget(W.button("📊  Excel", slot=self.ready_excel))
        act.addStretch(1)
        v.addLayout(act)

        self.t_ready = W.DataTable()
        self.t_ready.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.t_ready.setContextMenuPolicy(Qt.CustomContextMenu)
        self.t_ready.customContextMenuRequested.connect(self._menu_ready)
        v.addWidget(self.t_ready, 1)
        v.addWidget(ShareBar(self.db, lambda: self.last_file, self))
        return w

    def _load_ready(self):
        self.ready = M.ready_lines(self.db, self.r_project.text().strip(),
                                   self.r_mr.text().strip(), self.r_pr.text().strip())
        rows = [[r["mr_no"], r["mr_date"], r["mr_project"] or r["site"], r["item_code"],
                 r["description"], r["uom"], round(r["qty_requested"], 2),
                 round(r["qty_prepared"], 2), round(r["qty_delivered"], 2),
                 round(r["qty_ready"], 2), r["pr_no"], r["requested_by"],
                 r["prepared_by"] or "", r["status"]] for r in self.ready]
        self.t_ready.fill(["MR Number", "Date", "Project / Site", "Item Code", "Description",
                           "UOM", "Requested", "Prepared", "Delivered", "Ready to Deliver",
                           "PR / MR No.", "Requested By", "Prepared By", "Status"], rows)
        _paint(self.t_ready, 13, M.FULFIL_COLORS)
        qty = sum(r["qty_ready"] for r in self.ready)
        projects = len({(r["mr_project"] or r["site"]) for r in self.ready})
        mrs = len({r["mr_no"] for r in self.ready})
        self.ready_summary.setText(
            f"<b>{len(self.ready)}</b> line(s) ready &nbsp;·&nbsp; total qty "
            f"<b>{qty:,.2f}</b> &nbsp;·&nbsp; across <b>{mrs}</b> request(s) and "
            f"<b>{projects}</b> project(s) &nbsp;·&nbsp; "
            f"<span style='color:{W.AMBER}'>awaiting Delivery Note</span>")

    def _sel_ready(self) -> list[dict]:
        keys = {(self.t_ready.item(i.row(), 0).text(), self.t_ready.item(i.row(), 3).text())
                for i in self.t_ready.selectedIndexes()}
        return [r for r in self.ready if (r["mr_no"], r["item_code"]) in keys]

    def make_dn(self):
        self._deliver(self._sel_ready(),
                      "Select the prepared lines that are being delivered.")

    def unprepare(self):
        sel = self._sel_ready()
        if not sel:
            W.error_box(self, "Select the lines to release.")
            return
        if not W.confirm(self, f"Release {len(sel)} prepared line(s) back to free stock?\n\n"
                               "The reservation is removed; nothing has left the warehouse."):
            return
        for r in sel:
            try:
                M.set_prepared(self.db, r["id"], float(r["qty_delivered"]))
            except S.StockError as exc:
                W.error_box(self, str(exc))
        self.reload()
        self._load_ready()
        self.dataChanged.emit()
        W.toast(self, "Reservation released.")

    def delete_ready(self):
        """Remove prepared lines from their request entirely."""
        sel = self._sel_ready()
        if not sel:
            W.error_box(self, "Select the prepared line(s) to delete.")
            return
        blocked = [r for r in sel if float(r.get("qty_delivered") or 0) > 0]
        free = [r for r in sel if float(r.get("qty_delivered") or 0) <= 0]
        if not free:
            W.error_box(self, "Every selected line has already been delivered.\n\n"
                              "Delivered history cannot be erased.")
            return
        msg = (f"Delete {len(free)} prepared line(s) from their request?\n\n"
               "The reservation is released and the line is removed completely. "
               "Nothing has left the warehouse.")
        if blocked:
            msg += f"\n\n{len(blocked)} delivered line(s) will be SKIPPED."
        if not W.confirm(self, msg):
            return
        done, skipped = M.delete_lines(self.db, [r["id"] for r in free])
        self.reload()
        self._load_ready()
        self.dataChanged.emit()
        self._offer_cleanup()
        W.toast(self, f"{done} prepared line(s) deleted.")
        if skipped:
            W.error_box(self, "These lines were kept:\n\n" + "\n".join(skipped[:10]))

    def picking_pdf(self):
        if not self.ready:
            W.error_box(self, "Nothing is prepared yet.")
            return
        self.last_file = D.report_pdf(self.db, "Ready for Delivery - Picking List",
                                      self.t_ready.headers(), self.t_ready.all_rows())
        D.open_path(self.last_file)

    def ready_excel(self):
        if not self.ready:
            W.error_box(self, "Nothing is prepared yet.")
            return
        self.last_file = D.export_excel(self.db, "Ready for Delivery",
                                        self.t_ready.headers(), self.t_ready.all_rows())
        D.open_path(self.last_file)

    def _tab_changed(self, i: int):
        if i == 1:
            self.reload()
        elif i == 2:
            self._load_ready()


class DeliverDialog(QDialog):
    """Collects the Delivery Note header before converting prepared lines."""

    def __init__(self, db: Database, lines: list[dict], parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Create Delivery Note from prepared material")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        mrs = sorted({l["mr_no"] for l in lines})
        prs = sorted({l["pr_no"] for l in lines if l["pr_no"]})
        qty = sum(l["qty_ready"] for l in lines)
        head = QLabel(f"<b>{len(lines)}</b> line(s) · total qty <b>{qty:g}</b><br>"
                      f"Requests: {', '.join(mrs)}<br>"
                      f"PR numbers: {', '.join(prs) if prs else '-'}")
        head.setWordWrap(True)
        head.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER};"
                           "border-radius:6px; padding:9px;")
        v.addWidget(head)

        f = QFormLayout()
        first = lines[0]
        self.date = date_edit()
        self.project = QLineEdit(first["mr_project"] or first["site"] or "")
        self.dept = QLineEdit(first["department"] or "")
        self.req = QLineEdit(first["requested_by"] or "")
        self.issued = QLineEdit()
        self.recv = QLineEdit()
        self.vehicle = QLineEdit()
        self.driver = QLineEdit()
        self.purpose = QLineEdit("Site material issue")
        self.wh = W.combo(lookup(db, "warehouses"), True)
        self.remarks = QLineEdit(f"Against {', '.join(mrs)}")
        for lbl, wd in (("Date", self.date), ("Project / Site", self.project),
                        ("Department", self.dept), ("Requested By", self.req),
                        ("Issued To", self.issued), ("Received By", self.recv),
                        ("Vehicle", self.vehicle), ("Driver", self.driver),
                        ("Purpose", self.purpose), ("Warehouse", self.wh),
                        ("Remarks", self.remarks)):
            f.addRow(lbl, wd)
        v.addLayout(f)
        note = QLabel("Each line keeps its own PR number on the Delivery Note, and the file "
                      "name will end with every PR listed once.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Create Delivery Note")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def header(self) -> S.DocHeader:
        return S.DocHeader(
            doc_type="DN", doc_date=iso(self.date), project=self.project.text(),
            department=self.dept.text(), requested_by=self.req.text(),
            issued_to=self.issued.text(), received_by=self.recv.text(),
            vehicle=self.vehicle.text(), driver=self.driver.text(),
            purpose=self.purpose.text(), warehouse=self.wh.currentText(),
            remarks=self.remarks.text())
