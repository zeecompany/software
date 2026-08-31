"""Reusable UI helpers shared by every module: share bar, item picker, line editor."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QDate, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDateEdit,
                               QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import services as S
from ..core.database import Database
from . import widgets as W


def lookup(db: Database, table: str) -> list[str]:
    return [r["name"] for r in db.query(f"SELECT name FROM {table} ORDER BY name")]


def warehouses(db: Database) -> list[str]:
    return lookup(db, "warehouses")


def date_edit(value: str | None = None) -> QDateEdit:
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setDisplayFormat("dd-MM-yyyy")
    d.setDate(QDate.fromString(value, "yyyy-MM-dd") if value else QDate.currentDate())
    return d


def iso(d: QDateEdit) -> str:
    return d.date().toString("yyyy-MM-dd")


class ShareBar(QWidget):
    """PDF / Excel / Print / Email / WhatsApp / Open location / Copy path."""

    def __init__(self, db: Database, get_file: Callable[[], Path | None], parent=None,
                 extra: list[QPushButton] | None = None):
        super().__init__(parent)
        self.db = db
        self.get_file = get_file
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        for b in (extra or []):
            h.addWidget(b)
        h.addWidget(W.button("🖨  Print", slot=self._print, tip="Print the document"))
        h.addWidget(W.button("✉  Email PDF", slot=self._email, tip="Send by email (SMTP in Settings)"))
        h.addWidget(W.button("🟢  WhatsApp PDF", slot=self._whatsapp,
                             tip="Open WhatsApp with the message ready and the file location open"))
        h.addWidget(W.button("📂  Open File Location", slot=self._locate))
        h.addWidget(W.button("🔗  Copy Path", slot=self._copy))
        h.addStretch(1)

    def _f(self) -> Path | None:
        try:
            f = self.get_file()
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return None
        if not f:
            W.error_box(self, "Generate or select a document first.")
            return None
        return Path(f)

    def _print(self):
        f = self._f()
        if f:
            D.print_file(self.db, f)
            W.toast(self, f"Sent to printer: {f.name}")

    def _email(self):
        f = self._f()
        if not f:
            return
        to, ok = QInputDialog.getText(self, "Email PDF", "Recipient email address:")
        if not ok or not to.strip():
            return
        try:
            msg = D.email_pdf(self.db, f, to.strip())
            W.toast(self, msg)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not send the email.\n\n{exc}\n\n"
                              "Check the SMTP settings in Settings → Email.")

    def _whatsapp(self):
        f = self._f()
        if not f:
            return
        num, ok = QInputDialog.getText(
            self, "WhatsApp", "Phone number with country code (leave blank to choose in WhatsApp):",
            text=self.db.get_setting("wa_default_number", ""))
        if not ok:
            return
        D.whatsapp_share(self.db, f, num)
        W.toast(self, "WhatsApp opened — attach the file from the folder that just opened.")

    def _locate(self):
        f = self._f()
        if f:
            D.open_file_location(f)

    def _copy(self):
        f = self._f()
        if f:
            QApplication.clipboard().setText(str(f))
            W.toast(self, "Path copied to clipboard.")


class ItemPicker(QDialog):
    """Fast searchable item selector (barcode scanner friendly)."""

    def __init__(self, db: Database, parent=None, multi: bool = True):
        super().__init__(parent)
        self.db = db
        self.multi = multi
        self.selected: list[dict] = []
        self.setWindowTitle("Select Items")
        self.resize(980, 600)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = W.SearchBox("Scan barcode or type item code / description / category...")
        self.search.textChanged.connect(self.reload)
        self.search.returnPressed.connect(self._enter)
        top.addWidget(self.search, 1)
        self.cat = W.combo([""] + lookup(db, "categories"))
        self.cat.currentTextChanged.connect(self.reload)
        top.addWidget(QLabel("Category:"))
        top.addWidget(self.cat)
        v.addLayout(top)
        self.table = W.DataTable()
        self.table.doubleClicked.connect(self.accept)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection if multi
                                    else QTableWidget.SingleSelection)
        v.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.rows: list[dict] = []
        self.reload()
        self.search.setFocus()

    def _enter(self):
        txt = self.search.text().strip()
        hit = S.find_by_barcode(self.db, txt)
        if hit:
            self.selected = [hit]
            self.accept()
        elif self.table.rowCount() == 1:
            self.table.selectRow(0)
            self.accept()

    def reload(self):
        self.rows = S.search_items(self.db, self.search.text(), self.cat.currentText(), limit=800)
        self.table.fill(
            ["Code", "Description", "UOM", "Category", "Balance", "Reserved", "Free to Use",
             "Warehouse", "Location", "Status"],
            [[r["code"], r["description"], r["uom"], r["category"], round(r["balance"], 2),
              round(r.get("reserved", 0), 2), round(r.get("free", r["balance"]), 2),
              r["warehouse"], r["location"], r["status"]] for r in self.rows], status_col=9)

    def accept(self):
        if not self.selected:
            codes = {self.table.item(i.row(), 0).text() for i in self.table.selectedIndexes()}
            self.selected = [r for r in self.rows if r["code"] in codes]
        if not self.selected:
            W.error_box(self, "Select at least one item.")
            return
        super().accept()

    @staticmethod
    def pick(db: Database, parent=None, multi: bool = True) -> list[dict]:
        dlg = ItemPicker(db, parent, multi)
        return dlg.selected if dlg.exec() == QDialog.Accepted else []


class _RowHeaderResizer(QObject):
    """Lets the user drag the right edge of the row-number gutter.

    QHeaderView has no built-in handle for its own width, so we watch the mouse
    over the last few pixels and resize while dragging. The chosen width is
    remembered per installation.
    """

    GRIP = 5
    MIN_W = 28
    MAX_W = 160

    def __init__(self, table, header):
        super().__init__(header)
        self.table = table
        self.header = header
        self._drag = False
        self._x0 = 0
        self._w0 = 0
        header.setMouseTracking(True)
        header.installEventFilter(self)

    def set_width(self, w: int) -> int:
        """Programmatic resize, clamped to the allowed range."""
        w = max(self.MIN_W, min(self.MAX_W, int(w)))
        self.header.setFixedWidth(w)
        return w

    def _on_grip(self, pos) -> bool:
        return abs(pos.x() - self.header.width()) <= self.GRIP

    def eventFilter(self, obj, ev):
        et = ev.type()
        if et == QEvent.MouseMove:
            if self._drag:
                w = max(self.MIN_W, min(self.MAX_W,
                                        self._w0 + int(ev.position().x() - self._x0)))
                self.header.setFixedWidth(w)
                return True
            self.header.setCursor(Qt.SplitHCursor if self._on_grip(ev.position())
                                  else Qt.ArrowCursor)
        elif et == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            if self._on_grip(ev.position()):
                self._drag = True
                self._x0 = ev.position().x()
                self._w0 = self.header.width()
                return True
        elif et == QEvent.MouseButtonRelease and self._drag:
            self._drag = False
            try:
                self.table.db.set_setting("ui_rowno_width", self.header.width())
            except Exception:
                pass
            return True
        elif et == QEvent.MouseButtonDblClick and self._on_grip(ev.position()):
            self.header.setFixedWidth(38)                  # double-click = reset
            return True
        elif et == QEvent.Leave:
            self.header.setCursor(Qt.ArrowCursor)
        return super().eventFilter(obj, ev)


class LineTable(QTableWidget):
    """Editable document line grid used by every transaction screen."""
    changed = Signal()

    def __init__(self, db: Database, mode: str, parent=None):
        """mode: IN | OUT | RETURN | TRANSFER | ADJUST | COUNT"""
        super().__init__(parent)
        self.db = db
        self.mode = mode
        self.items: list[dict] = []
        self.default_pr = ""   # pre-fills the PR cell of newly added rows
        cols = {
            "IN": ["Item Code", "Description", "UOM", "Quantity", "Unit Cost", "Total", "Batch/Lot",
                   "Location", "Remarks"],
            "OUT": ["Item Code", "Description", "UOM", "Available", "Quantity", "PR / MR No.",
                    "Remarks"],
            "RETURN": ["Item Code", "Description", "UOM", "Issued Qty", "Returned Qty", "Condition",
                       "Remarks"],
            "TRANSFER": ["Item Code", "Description", "UOM", "Available", "Quantity", "Remarks"],
            "ADJUST": ["Item Code", "Description", "UOM", "System Qty", "Adjustment (+/-)",
                       "New Balance", "Remarks"],
            "COUNT": ["Item Code", "Description", "UOM", "System Qty", "Counted Qty", "Variance",
                      "Remarks"],
        }[mode]
        self.cols = cols
        self.setColumnCount(len(cols))
        self.setHorizontalHeaderLabels(cols)
        self.verticalHeader().setDefaultSectionSize(
            max(30, int(float(W.current_theme().get("ui_row_height", 27) or 27)) + 4))
        # Row-number gutter: readable by default but user-resizable, so long
        # line numbers or a wider gutter are possible (was setFixedWidth).
        vh = self.verticalHeader()
        vh.setVisible(True)
        vh.setSectionResizeMode(QHeaderView.Fixed)   # rows keep their height
        # A vertical header is sized by its table, so setFixedWidth is the only
        # thing that actually sticks. The user-resizable range is enforced by
        # _RowHeaderResizer, which clamps every drag to MIN_W..MAX_W.
        _w = int(float(db.get_setting("ui_rowno_width", 38) or 38))
        vh.setFixedWidth(max(_RowHeaderResizer.MIN_W,
                             min(_RowHeaderResizer.MAX_W, _w)))
        vh.setSectionsClickable(True)
        vh.setToolTip("Drag the edge of this column to make the line-number "
                      "gutter wider or narrower")
        self._vh_drag = _RowHeaderResizer(self, vh)
        self.setAlternatingRowColors(False)   # tinted editable cells must stay visible
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._apply_column_widths()
        self.itemChanged.connect(self._recalc)
        QShortcut(QKeySequence("Delete"), self, activated=self.remove_selected)
        # Drag a row by its number to re-order the document lines. The order is
        # what prints on the Delivery Note, so the storekeeper can arrange lines
        # to match the physical picking order.
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.MoveAction)
        self.verticalHeader().setSectionsMovable(False)
        QShortcut(QKeySequence("Ctrl+Up"), self,
                  activated=lambda: self.move_rows(-1)).setContext(
                      Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+Down"), self,
                  activated=lambda: self.move_rows(1)).setContext(
                      Qt.WidgetWithChildrenShortcut)

    # ------------------------------------------------------------ ordering
    def _row_payload(self, r: int) -> list:
        return [self.takeItem(r, c) for c in range(self.columnCount())]

    def _put_row(self, r: int, cells: list) -> None:
        for c, cell in enumerate(cells):
            if cell is not None:
                self.setItem(r, c, cell)

    def move_rows(self, delta: int) -> int:
        """Move the selected rows up (-1) or down (+1), keeping items in step."""
        rows = sorted({i.row() for i in self.selectedIndexes()})
        if not rows or delta == 0:
            return 0
        if delta < 0 and rows[0] == 0:
            return 0
        if delta > 0 and rows[-1] >= self.rowCount() - 1:
            return 0
        order = rows if delta < 0 else list(reversed(rows))
        self.blockSignals(True)
        moved = 0
        for r in order:
            tgt = r + delta
            a, b = self._row_payload(r), self._row_payload(tgt)
            self._put_row(r, b)
            self._put_row(tgt, a)
            if 0 <= r < len(self.items) and 0 <= tgt < len(self.items):
                self.items[r], self.items[tgt] = self.items[tgt], self.items[r]
            moved += 1
        self.blockSignals(False)
        self.clearSelection()
        for r in rows:
            self.selectRow(r + delta)
        self.changed.emit()
        return moved

    def dropEvent(self, event):
        """Re-order by drag, keeping `self.items` aligned with the grid.

        QTableWidget's own InternalMove leaves the backing list untouched, which
        would silently pair every row with the wrong item.
        """
        if event.source() is not self:
            super().dropEvent(event)
            return
        rows = sorted({i.row() for i in self.selectedIndexes()})
        if not rows:
            event.ignore()
            return
        drop_at = self.indexAt(event.position().toPoint()).row()
        if drop_at < 0:
            drop_at = self.rowCount() - 1
        snapshot = [[self.item(r, c) for c in range(self.columnCount())]
                    for r in range(self.rowCount())]
        items = list(self.items) if len(self.items) == self.rowCount() else []
        picked = [snapshot[r] for r in rows]
        picked_items = [items[r] for r in rows] if items else []
        rest = [snapshot[r] for r in range(self.rowCount()) if r not in rows]
        rest_items = ([items[r] for r in range(self.rowCount()) if r not in rows]
                      if items else [])
        before = sum(1 for r in rows if r < drop_at)
        at = max(0, min(len(rest), drop_at - before + 1))
        new_rows = rest[:at] + picked + rest[at:]
        new_items = (rest_items[:at] + picked_items + rest_items[at:]
                     if items else [])
        self.blockSignals(True)
        for r in range(self.rowCount()):
            for c in range(self.columnCount()):
                self.takeItem(r, c)
        for r, cells in enumerate(new_rows):
            for c, cell in enumerate(cells):
                if cell is not None:
                    self.setItem(r, c, cell)
        self.blockSignals(False)
        if new_items:
            self.items = new_items
        self.clearSelection()
        for k in range(len(picked)):
            self.selectRow(at + k)
        event.accept()
        self.changed.emit()
        # Excel-style fill handles are claimed in event()/keyPressEvent below,
        # because Ctrl+D is also a window-level navigation shortcut.

    # ------------------------------------------------------- Excel-style fill
    _FILL_KEYS = {
        (Qt.Key_D, Qt.ControlModifier): "fill_down",
        (Qt.Key_D, Qt.ControlModifier | Qt.ShiftModifier): "fill_column_down",
        (Qt.Key_Apostrophe, Qt.ControlModifier): "copy_from_above",
    }

    def _fill_action(self, ev) -> str:
        mods = ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier)
        return self._FILL_KEYS.get((ev.key(), mods), "")

    def event(self, ev):
        """Claim Ctrl+D before the window-level 'Documents' shortcut sees it.

        Accepting a ShortcutOverride tells Qt to deliver the combination to this
        widget as an ordinary key press instead of firing the global shortcut,
        so Ctrl+D fills down while the grid has focus and still opens Documents
        everywhere else.
        """
        if ev.type() == QEvent.ShortcutOverride and self._fill_action(ev):
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        action = self._fill_action(ev)
        if action:
            getattr(self, action)()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _editable(self, r: int, c: int) -> bool:
        it = self.item(r, c)
        return it is not None and bool(it.flags() & Qt.ItemIsEditable)

    def copy_from_above(self) -> int:
        """Ctrl+' — copy the single cell directly above into the current cell."""
        r, c = self.currentRow(), self.currentColumn()
        if r <= 0 or c < 0 or not self._editable(r, c):
            return 0
        src = self.item(r - 1, c)
        if src is None:
            return 0
        self.blockSignals(True)
        self.item(r, c).setText(src.text())
        self.blockSignals(False)
        self.changed.emit()
        self._recalc()
        return 1

    def fill_down(self) -> int:
        """Ctrl+D — Excel behaviour.

        With a multi-row selection, the top row of each selected column is
        copied into the rows below it. With a single cell (or no real range),
        the value from the cell directly above is pulled down.
        """
        idx = self.selectedIndexes()
        rows = sorted({i.row() for i in idx})
        cols = sorted({i.column() for i in idx})
        if len(rows) < 2:
            return self.copy_from_above()
        n = 0
        self.blockSignals(True)
        for c in cols:
            top = self.item(rows[0], c)
            if top is None:
                continue
            val = top.text()
            for r in rows[1:]:
                if self._editable(r, c):
                    self.item(r, c).setText(val)
                    n += 1
        self.blockSignals(False)
        if n:
            self.changed.emit()
            self._recalc()
        return n

    def fill_column_down(self) -> int:
        """Ctrl+Shift+D — copy the current cell into every row beneath it."""
        r, c = self.currentRow(), self.currentColumn()
        if r < 0 or c < 0 or self.item(r, c) is None:
            return 0
        val = self.item(r, c).text()
        n = 0
        self.blockSignals(True)
        for rr in range(r + 1, self.rowCount()):
            if self._editable(rr, c):
                self.item(rr, c).setText(val)
                n += 1
        self.blockSignals(False)
        if n:
            self.changed.emit()
            self._recalc()
        return n

    # Fixed pixel widths keep every column on screen; only Description flexes,
    # so adding items never pushes Item Code off the left edge.
    WIDTHS = {
        "Item Code": 110, "Description": None, "UOM": 62, "Available": 88,
        "Quantity": 92, "PR / MR No.": 130, "PR No.": 130, "Remarks": 220, "Unit Cost": 92,
        "Total": 100, "Batch/Lot": 90, "Location": 110, "Issued Qty": 88,
        "Returned Qty": 96, "Condition": 110, "System Qty": 92,
        "Adjustment (+/-)": 118, "New Balance": 100, "Counted Qty": 96, "Variance": 88,
    }

    def _apply_column_widths(self) -> None:
        hh = self.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(48)
        hh.setHighlightSections(False)
        for i, name in enumerate(self.cols):
            w = self.WIDTHS.get(name, 100)
            if w is None:                       # Description takes the leftover room
                hh.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hh.setSectionResizeMode(i, QHeaderView.Interactive)
                self.setColumnWidth(i, w)
        # description should never collapse below a usable size
        if "Description" in self.cols:
            hh.setMinimumSectionSize(48)

    # ------------------------------------------------------------ row logic
    def add_items(self, items: list[dict]) -> None:
        # An item may legitimately appear twice on a Delivery Note when the two
        # lines belong to different PR / MR numbers, so the duplicate guard is
        # (code + PR) on the OUT grid and plain code everywhere else.
        def key(d: dict):
            return ((d.get("code"), str(d.get("pr_no") or "").strip())
                    if self.mode == "OUT" else d.get("code"))

        existing = {key(i) for i in self.items}
        for it in items:
            if key(it) in existing:
                continue
            existing.add(key(it))
            self.items.append(it)
            r = self.rowCount()
            self.insertRow(r)
            self.blockSignals(True)
            ro = Qt.ItemIsEnabled
            th = W.current_theme()
            edit_fg = QColor(th.get("ui_text", "#1c2b3a"))
            lock_fg = QColor(th.get("ui_muted", "#6b7c8f"))
            edit_bg = QColor(th.get("ui_card", "#ffffff"))
            # subtle tint so the operator can see which cells accept typing
            edit_bg = (edit_bg.lighter(118) if W.is_dark_theme() else
                       QColor(th.get("ui_selection", "#dbeafe")).lighter(112))

            def cell(text, editable=False, align=Qt.AlignLeft, strong=False):
                c = QTableWidgetItem(str(text))
                if editable:
                    c.setForeground(QBrush(edit_fg))
                    c.setBackground(QBrush(edit_bg))
                    c.setToolTip("Double-click or start typing to edit")
                    if strong:
                        f = c.font()
                        f.setBold(True)
                        f.setPointSizeF(f.pointSizeF() + 1.0)
                        c.setFont(f)
                else:
                    c.setFlags(ro)
                    c.setForeground(QBrush(lock_fg))
                c.setTextAlignment(int(align) | Qt.AlignVCenter)
                return c
            bal = round(float(it.get("balance") or 0), 2)
            cost = round(float(it.get("unit_cost") or 0), 2)

            def preset(*keys, default=0):
                """First non-empty prefilled value for this row.

                Lines pushed in from Bulk Stock Check or a Material Request
                carry their own quantity; ignoring it forced the storekeeper to
                retype every figure (and a retyped 0 silently dropped the line).
                """
                for k in keys:
                    v = it.get(k)
                    if v not in (None, "", 0, 0.0):
                        try:
                            return round(float(v), 4)
                        except (TypeError, ValueError):
                            return default
                return default

            q_out = preset("qty", "issue_qty", "required")
            q_in = preset("qty", "receive_qty")
            base = [cell(it["code"]), cell(it["description"]), cell(it["uom"])]
            if self.mode == "IN":
                row = base + [cell(f"{q_in:g}", True, Qt.AlignRight, True),
                              cell(cost, True, Qt.AlignRight),
                              cell(0, False, Qt.AlignRight), cell(it.get("batch", ""), True),
                              cell(it.get("location", ""), True),
                              cell(it.get("remarks", ""), True)]
            elif self.mode == "OUT":
                row = base + [cell(bal, False, Qt.AlignRight),
                              cell(f"{q_out:g}", True, Qt.AlignRight, True),
                              cell(it.get("pr_no") or self.default_pr, True),
                              cell(it.get("remarks", ""), True)]
            elif self.mode == "TRANSFER":
                row = base + [cell(bal, False, Qt.AlignRight),
                              cell(f"{q_out:g}", True, Qt.AlignRight, True),
                              cell(it.get("remarks", ""), True)]
            elif self.mode == "RETURN":
                row = base + [cell(it.get("issued_qty", 0), True, Qt.AlignRight),
                              cell(it.get("return_qty", 0), True, Qt.AlignRight, True),
                              cell("USABLE", True), cell(it.get("remarks", ""), True)]
            elif self.mode == "ADJUST":
                row = base + [cell(bal, False, Qt.AlignRight),
                              cell(f"{preset('qty', 'adjust_qty'):g}", True,
                                   Qt.AlignRight, True),
                              cell(bal, False, Qt.AlignRight),
                              cell(it.get("remarks", ""), True)]
            else:  # COUNT
                row = base + [cell(bal, False, Qt.AlignRight),
                              cell(bal, True, Qt.AlignRight, True),
                              cell(0, False, Qt.AlignRight), cell("", True)]
            for c, w in enumerate(row):
                self.setItem(r, c, w)
            if self.mode == "RETURN":
                cb = QComboBox()
                cb.addItems(["USABLE", "DAMAGED"])
                self.setCellWidget(r, 5, cb)
            self.blockSignals(False)
        self.scrollToBottom()
        self._recalc()
        self.changed.emit()

    def load_lines(self, rows: list[dict]) -> None:
        """Replace the grid with saved document lines (used to edit a draft)."""
        self.clear_lines()
        self.add_items(rows)
        self._recalc()
        self.changed.emit()

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.selectedIndexes()}, reverse=True)
        for r in rows:
            self.removeRow(r)
            if r < len(self.items):
                self.items.pop(r)
        self.changed.emit()

    def set_default_pr(self, pr: str) -> None:
        """New rows added from now on start with this PR number."""
        self.default_pr = (pr or "").strip()

    def pr_column(self) -> int | None:
        return 5 if self.mode == "OUT" else None

    def apply_pr_to_selection(self, pr: str) -> int:
        """Write a PR number into the selected rows (or all rows when none
        selected). Returns how many rows were changed."""
        col = self.pr_column()
        if col is None:
            return 0
        rows = sorted({i.row() for i in self.selectedIndexes()})
        if not rows:
            rows = list(range(self.rowCount()))
        self.blockSignals(True)
        for r in rows:
            if self.item(r, col) is not None:
                self.item(r, col).setText(pr)
        self.blockSignals(False)
        self.changed.emit()
        return len(rows)

    def fill_pr_down(self) -> int:
        """Copy the PR number of the current row into every row below it."""
        col = self.pr_column()
        if col is None or self.currentRow() < 0:
            return 0
        start = self.currentRow()
        val = self.item(start, col).text() if self.item(start, col) else ""
        self.blockSignals(True)
        n = 0
        for r in range(start + 1, self.rowCount()):
            if self.item(r, col) is not None:
                self.item(r, col).setText(val)
                n += 1
        self.blockSignals(False)
        self.changed.emit()
        return n

    def pr_summary(self) -> dict[str, dict]:
        """Group the current lines by PR number -> {lines, qty}."""
        col = self.pr_column()
        out: dict[str, dict] = {}
        if col is None:
            return out
        for r in range(self.rowCount()):
            pr = (self.item(r, col).text().strip() if self.item(r, col) else "") or "(no PR)"
            qty = self._num(r, 4)
            e = out.setdefault(pr, {"lines": 0, "qty": 0.0})
            e["lines"] += 1
            e["qty"] += qty
        return out

    def clear_lines(self) -> None:
        self.setRowCount(0)
        self.items = []
        self.changed.emit()

    def _num(self, r: int, c: int) -> float:
        it = self.item(r, c)
        if it is None:
            return 0.0
        try:
            return float(str(it.text()).replace(",", "") or 0)
        except ValueError:
            return 0.0

    def _recalc(self, *_):
        self.blockSignals(True)
        for r in range(self.rowCount()):
            if self.mode == "IN":
                tot = self._num(r, 3) * self._num(r, 4)
                self.item(r, 5).setText(f"{tot:,.2f}")
            elif self.mode == "ADJUST":
                self.item(r, 5).setText(f"{self._num(r, 3) + self._num(r, 4):g}")
            elif self.mode == "COUNT":
                var = self._num(r, 4) - self._num(r, 3)
                cell = self.item(r, 5)
                cell.setText(f"{var:+g}")
                cell.setForeground(QBrush(QColor(
                    W.GREEN if var > 0 else (W.RED if var < 0 else W.MUTED))))
            elif self.mode in ("OUT", "TRANSFER"):
                avail, qty = self._num(r, 3), self._num(r, 4)
                cell = self.item(r, 4)
                over = qty > avail
                cell.setForeground(QBrush(QColor(W.RED if over else
                                                 W.current_theme().get("ui_text", "#1c2b3a"))))
                cell.setToolTip("Quantity exceeds the available stock" if over else "")
        self.blockSignals(False)
        self.changed.emit()

    # --------------------------------------------------------------- output
    def commit_edits(self) -> None:
        """Close and COMMIT a cell that is still being typed into.

        Pressing a toolbar button while a quantity cell is still open in its
        editor used to throw the typed value away, so the document was saved
        with the previous quantity. Moving the focus back to the grid makes Qt
        deliver the editor's value to the model first.
        """
        try:
            if self.state() == QAbstractItemView.EditingState:
                idx = self.currentIndex()
                self.setFocus(Qt.OtherFocusReason)
                if idx.isValid():
                    self.closePersistentEditor(idx)
        except Exception:      # noqa: BLE001 - never block a save
            pass

    def to_lines(self) -> list[S.Line]:
        self.commit_edits()
        out: list[S.Line] = []
        for r in range(self.rowCount()):
            it = self.items[r]
            if self.mode == "IN":
                out.append(S.Line(item_id=it["id"], qty=self._num(r, 3), unit_cost=self._num(r, 4),
                                  batch=self.item(r, 6).text(), location=self.item(r, 7).text(),
                                  remarks=self.item(r, 8).text()))
            elif self.mode == "OUT":
                out.append(S.Line(item_id=it["id"], qty=self._num(r, 4),
                                  unit_cost=float(it.get("unit_cost") or 0),
                                  pr_no=self.item(r, 5).text().strip(),
                                  remarks=self.item(r, 6).text()))
            elif self.mode == "TRANSFER":
                out.append(S.Line(item_id=it["id"], qty=self._num(r, 4),
                                  unit_cost=float(it.get("unit_cost") or 0),
                                  remarks=self.item(r, 5).text()))
            elif self.mode == "RETURN":
                w = self.cellWidget(r, 5)
                out.append(S.Line(item_id=it["id"], qty=self._num(r, 4),
                                  issued_qty=self._num(r, 3),
                                  condition=w.currentText() if w else "USABLE",
                                  remarks=self.item(r, 6).text()))
            elif self.mode == "ADJUST":
                out.append(S.Line(item_id=it["id"], qty=self._num(r, 4),
                                  remarks=self.item(r, 6).text()))
            else:
                sysq, cnt = self._num(r, 3), self._num(r, 4)
                out.append(S.Line(item_id=it["id"], qty=cnt, system_qty=sysq, counted_qty=cnt,
                                  remarks=self.item(r, 6).text()))
        return [l for l in out if l.qty or self.mode in ("ADJUST", "COUNT")]

    def total_qty(self) -> float:
        col = {"IN": 3, "OUT": 4, "TRANSFER": 4, "RETURN": 4, "ADJUST": 4, "COUNT": 4}[self.mode]
        return sum(self._num(r, col) for r in range(self.rowCount()))

    def total_value(self) -> float:
        if self.mode != "IN":
            return 0.0
        return sum(self._num(r, 3) * self._num(r, 4) for r in range(self.rowCount()))


class BarcodeBar(QWidget):
    """USB scanner input line: scan -> item found -> added to the grid."""
    scanned = Signal(dict)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("🔎 Scan / type code:"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Scan barcode with USB scanner or type item code, then press Enter")
        self.edit.returnPressed.connect(self._go)
        self.edit.setMinimumWidth(360)
        h.addWidget(self.edit, 1)
        self.info = QLabel("")
        self.info.setStyleSheet(f"color:{W.MUTED};")
        h.addWidget(self.info, 2)

    def _go(self):
        code = self.edit.text().strip()
        if not code:
            return
        it = S.find_by_barcode(self.db, code)
        if not it:
            self.info.setText(f"❌ No item found for '{code}'")
            self.info.setStyleSheet(f"color:{W.RED}; font-weight:600;")
            return
        col = S.STATUS_COLORS.get(it["status"], W.NAVY)
        self.info.setText(f"✔ {it['code']} — {it['description']}  |  {it['uom']}  |  "
                          f"Stock: {it['balance']:g}  |  {it['warehouse']} / {it['location']}  |  "
                          f"{it['status']}")
        self.info.setStyleSheet(f"color:{col}; font-weight:600;")
        self.edit.clear()
        self.scanned.emit(it)

    def focus(self):
        self.edit.setFocus()
        self.edit.selectAll()
