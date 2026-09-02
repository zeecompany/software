"""Reusable UI helpers shared by every module: share bar, item picker, line editor."""
from __future__ import annotations

import csv
import datetime as _dt
import io
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QDate, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox,
                               QComboBox,
                               QDateEdit, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QRadioButton, QTextBrowser,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import config, documents as D
from ..core import services as S
from ..core import web_lookup as WL
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


def _safe_attachment_name(name: str, fallback: str = "attachment") -> str:
    p = Path(str(name or fallback))
    stem = D.safe_file_part(p.stem or fallback, fallback)
    suffix = p.suffix if p.suffix and len(p.suffix) <= 10 else ""
    return f"{stem}{suffix}"


def unique_attachment_path(folder: str | Path, name: str) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    p = Path(_safe_attachment_name(name))
    stem = p.stem or "attachment"
    suffix = p.suffix
    dest = folder / f"{stem}{suffix}"
    n = 2
    while dest.exists():
        dest = folder / f"{stem}_{n}{suffix}"
        n += 1
    return dest


def store_attachment_file(src: str | Path, dest_dir: str | Path | None = None,
                          prefix: str = "") -> Path:
    """Copy one attachment into AURCO's Attachments folder under a safe unique name."""
    src = Path(src)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(src)
    dest_dir = Path(dest_dir or config.folder("Attachments"))
    name = src.name
    if prefix:
        name = f"{prefix}_{name}"
    dest = unique_attachment_path(dest_dir, name)
    try:
        if src.resolve() == dest.resolve():
            return dest
    except OSError:
        pass
    shutil.copy2(src, dest)
    return dest


def clipboard_attachment_entries(dest_dir: str | Path | None = None,
                                 prefix: str = "clipboard") -> list[dict[str, Any]]:
    """Return copied files / screenshot images from the clipboard as attachment entries.

    File URLs are copied into the Attachments folder. A copied image is stored as
    a PNG. Clipboard attachments are flagged with page_order=2 so they always
    land after ordinary attachments in the final merged PDF.
    """
    dest_dir = Path(dest_dir or config.folder("Attachments"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    cb = QApplication.clipboard()
    mime = cb.mimeData()
    out: list[dict[str, Any]] = []

    def add_file(p: Path):
        out.append({"file_path": str(p), "source": "clipboard", "page_order": 2})

    urls = list(mime.urls()) if mime and mime.hasUrls() else []
    for url in urls:
        local = Path(url.toLocalFile())
        if local.exists() and local.is_file():
            add_file(store_attachment_file(local, dest_dir))
    if out:
        return out

    img = cb.image()
    if not img.isNull():
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = unique_attachment_path(dest_dir, f"{prefix}_{stamp}.png")
        if not img.save(str(dest), "PNG"):
            raise ValueError("The copied image could not be saved as an attachment.")
        add_file(dest)
        return out

    text = (cb.text() or "").strip()
    if text:
        for line in text.splitlines():
            raw = line.strip().strip('"').strip("'")
            if not raw:
                continue
            p = Path(raw)
            if p.exists() and p.is_file():
                add_file(store_attachment_file(p, dest_dir))
        if out:
            return out

    raise ValueError("The clipboard does not contain a file or image attachment yet.")


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


class GoogleResultsDialog(QDialog):
    """Minimal in-app preview for Google search results."""

    def __init__(self, parent=None, query: str = ""):
        super().__init__(parent)
        self.query = str(query or "").strip()
        self.setWindowTitle("Google Search Preview")
        self.resize(920, 620)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.query_edit = QLineEdit(self.query)
        self.query_edit.setPlaceholderText("Type keywords to search on Google...")
        self.query_edit.returnPressed.connect(self.refresh)
        top.addWidget(self.query_edit, 1)
        self.btn_search = QPushButton("Preview")
        self.btn_search.clicked.connect(self.refresh)
        top.addWidget(self.btn_search)
        self.btn_browser = QPushButton("Open in Browser")
        self.btn_browser.clicked.connect(self.open_browser)
        top.addWidget(self.btn_browser)
        v.addLayout(top)
        self.info = QLabel("Preview lightweight Google results inside AURCO.")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#5f6368")
        v.addWidget(self.info)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setHtml(WL.results_html(self.query, [], "Type a search phrase to begin."))
        v.addWidget(self.view, 1)
        if self.query:
            self.refresh()

    def refresh(self):
        self.query = self.query_edit.text().strip()
        if not self.query:
            self.view.setHtml(WL.results_html("", [], "Type a search phrase to begin."))
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        err = ""
        try:
            results = WL.fetch_google_results(self.query)
        except Exception as e:
            results = []
            err = f"Unable to fetch preview right now: {e}"
        finally:
            QApplication.restoreOverrideCursor()
        self.info.setText(f"Google preview for: {self.query}")
        self.view.setHtml(WL.results_html(self.query, results, err))

    def open_browser(self):
        q = self.query_edit.text().strip()
        if q:
            D.open_path(WL.google_search_url(q, limit=8))

    @staticmethod
    def open(parent=None, query: str = ""):
        GoogleResultsDialog(parent, query).exec()


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
        self.btn_google = QPushButton("Google")
        self.btn_google.clicked.connect(self.open_google_preview)
        top.addWidget(self.btn_google)
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

    def google_query(self) -> str:
        txt = self.search.text().strip()
        if txt:
            return txt
        r = self.table.currentRow()
        if 0 <= r < len(self.rows):
            row = self.rows[r]
            return " ".join(str(row.get(k) or "") for k in ("code", "description", "category")).strip()
        return ""

    def open_google_preview(self):
        query = self.google_query()
        if not query:
            W.error_box(self, "Type a keyword or select an item first.")
            return
        GoogleResultsDialog.open(self, query)

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


# ============================================================ Excel clipboard
#: canonical field -> the header words that may introduce it in a pasted sheet
PASTE_HEADERS: dict[str, tuple[str, ...]] = {
    "code": ("item code", "code", "itemcode", "material code", "part no",
             "part number", "sku", "barcode", "item no", "item"),
    "description": ("description", "item description", "material", "details",
                    "desc", "particulars"),
    "qty": ("qty", "quantity", "required", "required qty", "issue qty",
            "issued qty", "delivered", "requested", "no", "nos", "count"),
    "uom": ("uom", "unit", "unit of measure", "u.o.m"),
    "pr_no": ("pr", "pr no", "pr / mr no.", "pr/mr", "mr no", "mr", "pr number",
              "pr / mr no", "reference", "ref"),
    "unit_cost": ("unit cost", "rate", "price", "unit price", "cost"),
    "batch": ("batch", "lot", "batch/lot", "batch no"),
    "location": ("location", "rack", "bin", "rack/bin", "store location"),
    "remarks": ("remarks", "remark", "notes", "note", "comment", "comments"),
}

#: what an un-headed sheet means, per grid mode (column order)
PASTE_POSITIONS = {
    "OUT": ("code", "qty", "pr_no", "remarks"),
    "IN": ("code", "qty", "unit_cost", "batch", "location", "remarks"),
    "TRANSFER": ("code", "qty", "remarks"),
    "RETURN": ("code", "qty", "remarks"),
    "ADJUST": ("code", "qty", "remarks"),
    "COUNT": ("code", "qty", "remarks"),
}


def _norm_head(text: Any) -> str:
    return re.sub(r"[^a-z0-9 /.]", "", str(text or "").strip().lower())


def _to_number(value: Any) -> float | None:
    txt = re.sub(r"[^\d.\-]", "", str(value or "").replace(",", ""))
    if txt in ("", "-", "."):
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def split_pasted_table(text: str) -> tuple[list[str], list[list[str]]]:
    """Split clipboard text into (headers, rows).

    Understands an Excel paste (tab separated), CSV, a pipe table and columns
    padded with spaces — with or without a header row.
    """
    raw = [ln for ln in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
           if ln.strip()]
    if not raw:
        return [], []
    if "\t" in raw[0]:
        rows = [ln.split("\t") for ln in raw]
    elif raw[0].count(",") >= 2:
        rows = list(csv.reader(io.StringIO("\n".join(raw))))
    elif raw[0].count("|") >= 2:
        rows = [[c.strip() for c in ln.strip("|").split("|")] for ln in raw]
    elif raw[0].count(",") == 1:
        rows = [ln.split(",") for ln in raw]
    else:
        rows = [re.split(r"\s{2,}|\t", ln.strip()) for ln in raw]
    width = max(len(r) for r in rows)
    rows = [[str(c).strip() for c in (list(r) + [""] * (width - len(r)))] for r in rows]
    head = rows[0]
    known = sum(1 for h in head
                if any(_norm_head(h) in words for words in PASTE_HEADERS.values()))
    if known >= 2:
        return head, rows[1:]
    return [], rows


def map_pasted_columns(headers: list[str], mode: str,
                       width: int) -> dict[str, int]:
    """field -> column index, from the header row or from the column order."""
    out: dict[str, int] = {}
    for i, h in enumerate(headers):
        n = _norm_head(h)
        for field, words in PASTE_HEADERS.items():
            if field in out:
                continue
            if n in words:
                out[field] = i
                break
    if "code" in out or "description" in out:
        return out
    for i, field in enumerate(PASTE_POSITIONS.get(mode, PASTE_POSITIONS["OUT"])):
        if i < width:
            out.setdefault(field, i)
    return out


def resolve_item(db: Database, code: str, description: str = "") -> dict | None:
    """Find one item from a pasted code (code / barcode / alt code) or name."""
    code = str(code or "").strip()
    description = str(description or "").strip()
    row = None
    if code:
        row = db.one("SELECT * FROM items WHERE code=? COLLATE NOCASE"
                     " OR barcode=? COLLATE NOCASE OR alt_code=? COLLATE NOCASE",
                     (code, code, code))
    if row is None and description:
        row = db.one("SELECT * FROM items WHERE description=? COLLATE NOCASE",
                     (description,))
        if row is None:
            hits = db.query("SELECT * FROM items WHERE description LIKE ? LIMIT 2",
                            (f"%{description}%",))
            row = hits[0] if len(hits) == 1 else None
    if row is None and code:
        hits = db.query("SELECT * FROM items WHERE code LIKE ? LIMIT 2", (f"%{code}%",))
        row = hits[0] if len(hits) == 1 else None
    return dict(row) if row else None


def parse_pasted_lines(db: Database, text: str, mode: str = "OUT",
                       default_pr: str = "") -> list[dict]:
    """Turn pasted text into resolved grid rows.

    Every entry carries `_status` ("ok" / "unknown" / "empty") so the operator
    sees what will be imported *before* anything touches the document.
    """
    headers, rows = split_pasted_table(text)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    cols = map_pasted_columns(headers, mode, width)
    out: list[dict] = []

    def cell(r: list[str], field: str) -> str:
        i = cols.get(field)
        return r[i].strip() if i is not None and i < len(r) else ""

    for r in rows:
        if not any(str(c).strip() for c in r):
            continue
        code, desc = cell(r, "code"), cell(r, "description")
        qty = _to_number(cell(r, "qty"))
        if qty is None and not cols.get("qty"):
            qty = _to_number(next((c for c in r[1:] if _to_number(c) is not None), ""))
        if not code and not desc:
            continue
        item = resolve_item(db, code, desc)
        pasted: dict[str, Any] = {
            "_source_code": code or desc,
            "_source_desc": desc,
            "qty": qty or 0,
            "pr_no": cell(r, "pr_no") or default_pr,
            "remarks": cell(r, "remarks"),
            "batch": cell(r, "batch"),
            "location": cell(r, "location"),
        }
        cost = _to_number(cell(r, "unit_cost"))
        # the item master first, then the pasted values — a blank `remarks`
        # column on the item row must never wipe what the operator pasted
        entry: dict[str, Any] = dict(item) if item else {}
        entry.update(pasted)
        if item:
            if cost:
                entry["unit_cost"] = cost
            entry["_status"] = "ok" if (qty or 0) > 0 else "noqty"
        else:
            entry.update({"code": code or desc, "description": desc or code,
                          "uom": cell(r, "uom"), "_status": "unknown"})
        out.append(entry)
    return out


class ExcelPasteDialog(QDialog):
    """Paste (or load) a sheet of item lines straight into a document grid."""

    def __init__(self, db: Database, mode: str = "OUT", default_pr: str = "",
                 parent=None):
        super().__init__(parent)
        self.db = db
        self.mode = mode
        self.default_pr = default_pr
        self.rows: list[dict] = []
        self.setWindowTitle("Paste item lines from Excel")
        self.resize(1080, 660)
        v = QVBoxLayout(self)
        v.setSpacing(8)

        head = QLabel(
            "Copy the columns in Excel and press <b>Paste from clipboard</b> — or "
            "drop the text in below. A header row is recognised automatically "
            "(<i>Item Code, Description, Qty, PR / MR No., Remarks…</i>); without "
            "one the columns are read in that order. Nothing is added to the "
            "document until you press <b>Add to document</b>.")
        head.setWordWrap(True)
        head.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(head)

        bar = QHBoxLayout()
        bar.addWidget(W.button("📋  Paste from clipboard", "Primary", self.from_clipboard,
                               shortcut="Ctrl+V"))
        bar.addWidget(W.button("📂  Load Excel / CSV file...", slot=self.from_file))
        bar.addWidget(W.button("⬇  Excel template", slot=self.template,
                               tip="Save an empty sheet with the right column headings"))
        bar.addWidget(W.button("🧹  Clear", slot=lambda: self.text.clear()))
        bar.addStretch(1)
        self.chk_skip = QCheckBox("Skip lines that are not in the item master")
        self.chk_skip.setChecked(True)
        bar.addWidget(self.chk_skip)
        v.addLayout(bar)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(
            "ITM-00001\t10\t001735\turgent\nITM-00042\t4\t001736")
        self.text.setMaximumHeight(150)
        self.text.textChanged.connect(self.preview)
        v.addWidget(self.text)

        self.table = W.DataTable()
        v.addWidget(self.table, 1)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        self.btn_ok.setText("Add to document")
        self.btn_ok.setEnabled(False)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.from_clipboard(quiet=True)

    # ------------------------------------------------------------- sources
    def from_clipboard(self, quiet: bool = False):
        txt = QApplication.clipboard().text()
        if not txt.strip():
            if not quiet:
                W.error_box(self, "The clipboard is empty — copy the rows in Excel first.")
            return
        self.text.setPlainText(txt)

    def from_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Open a sheet of item lines", "",
            "Spreadsheets (*.xlsx *.xlsm *.csv *.txt)")
        if not f:
            return
        try:
            from ..core import importer
            head, rows = importer.read_table(f)
        except Exception as exc:            # noqa: BLE001
            W.error_box(self, f"That file could not be read.\n\n{exc}")
            return
        lines = ["\t".join(str(c) for c in head)] if head else []
        lines += ["\t".join("" if c is None else str(c) for c in r) for r in rows]
        self.text.setPlainText("\n".join(lines))

    def template(self):
        cols = {"OUT": ["Item Code", "Description", "Qty", "PR / MR No.", "Remarks"],
                "IN": ["Item Code", "Description", "Qty", "Unit Cost", "Batch/Lot",
                       "Location", "Remarks"]}.get(
                           self.mode, ["Item Code", "Description", "Qty", "Remarks"])
        try:
            p = D.export_excel(self.db, "Document Lines Template", cols, [],
                               totals=False)
        except Exception as exc:            # noqa: BLE001
            W.error_box(self, f"Could not write the template.\n\n{exc}")
            return
        W.toast(self, f"Template saved: {Path(p).name}")
        try:
            D.open_path(p)
        except Exception:               # noqa: BLE001
            pass

    # ------------------------------------------------------------- preview
    def preview(self):
        self.rows = parse_pasted_lines(self.db, self.text.toPlainText(), self.mode,
                                       self.default_pr)
        status = {"ok": "✔  found", "noqty": "⚠  no quantity",
                  "unknown": "✖  not in item master"}
        self.table.fill(
            ["Pasted Code", "Item Code", "Description", "UOM", "Qty",
             "PR / MR No.", "Remarks", "Status"],
            [[r["_source_code"], r.get("code", ""), r.get("description", ""),
              r.get("uom", ""), r.get("qty", 0), r.get("pr_no", ""),
              r.get("remarks", ""), status.get(r["_status"], r["_status"])]
             for r in self.rows])
        ok = sum(1 for r in self.rows if r["_status"] == "ok")
        noqty = sum(1 for r in self.rows if r["_status"] == "noqty")
        unknown = [r["_source_code"] for r in self.rows if r["_status"] == "unknown"]
        bits = [f"<b>{ok}</b> line(s) ready"]
        if noqty:
            bits.append(f"<span style='color:{W.AMBER}'>{noqty} without a "
                        "quantity (imported as 0)</span>")
        if unknown:
            bits.append(f"<span style='color:{W.RED}'>{len(unknown)} not in the item "
                        f"master: {', '.join(unknown[:6])}"
                        f"{' …' if len(unknown) > 6 else ''}</span>")
        self.summary.setText("&nbsp; · &nbsp;".join(bits) if self.rows else
                             "Nothing parsed yet.")
        self.btn_ok.setEnabled(bool(self.rows))

    def result_rows(self) -> list[dict]:
        keep = [r for r in self.rows if r["_status"] != "unknown"] \
            if self.chk_skip.isChecked() else list(self.rows)
        return [r for r in keep if r.get("id")]


ADJUST_REASONS = ["Physical count correction", "Missing stock", "Damaged stock",
                  "Found stock", "Data correction", "Opening balance adjustment"]


class AdjustStockDialog(QDialog):
    """Correct the system stock of one item without leaving the document.

    The storekeeper who is picking a Delivery Note is exactly the person who
    discovers that the system balance is wrong; forcing them to abandon the
    note and open the Stock Adjustment screen is how wrong balances survive.
    The correction is posted as a normal ADJ document, so the audit trail and
    the ledger are identical to the dedicated screen.
    """

    def __init__(self, db: Database, item: dict, parent=None,
                 warehouse: str = "", counted: float | None = None):
        super().__init__(parent)
        self.db = db
        self.item = dict(item)
        self.doc_no = ""
        row = db.one("SELECT * FROM items WHERE id=?", (item.get("id"),))
        if row is not None:
            self.item.update(dict(row))
        self.system_qty = round(float(self.item.get("balance") or 0), 4)
        self.setWindowTitle("Adjust inventory quantity")
        self.resize(560, 0)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        title = QLabel(f"<b>{self.item.get('code','')}</b> &nbsp; "
                       f"{self.item.get('description','')}")
        title.setWordWrap(True)
        v.addWidget(title)
        note = QLabel("The correction is posted as a Stock Adjustment (ADJ) "
                      "document with a full audit trail — it is not part of "
                      "this delivery note.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(note)

        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignRight)
        self.lbl_system = QLabel(f"{self.system_qty:g} {self.item.get('uom','')}")
        f.addRow("System quantity", self.lbl_system)

        self.rb_count = QRadioButton("Set the physical quantity to")
        self.rb_delta = QRadioButton("Adjust by (+/-)")
        # The two radios live in different container widgets, so Qt's implicit
        # auto-exclusion does not apply — an explicit group keeps them paired.
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.rb_count)
        self._mode_group.addButton(self.rb_delta)
        self.rb_count.setChecked(True)
        self.sp_count = QDoubleSpinBox()
        self.sp_count.setRange(0, 1e9)
        self.sp_count.setDecimals(3)
        self.sp_count.setValue(self.system_qty if counted is None else float(counted))
        self.sp_delta = QDoubleSpinBox()
        self.sp_delta.setRange(-1e9, 1e9)
        self.sp_delta.setDecimals(3)
        r1 = QHBoxLayout()
        r1.addWidget(self.rb_count)
        r1.addWidget(self.sp_count, 1)
        r2 = QHBoxLayout()
        r2.addWidget(self.rb_delta)
        r2.addWidget(self.sp_delta, 1)
        f.addRow("", _wrap(r1))
        f.addRow("", _wrap(r2))

        self.reason = W.combo(ADJUST_REASONS, True)
        f.addRow("Reason *", self.reason)
        self.wh = W.combo(warehouses(db), True, warehouse)
        f.addRow("Warehouse", self.wh)
        self.remarks = QLineEdit()
        self.remarks.setPlaceholderText("Explain the correction for the audit trail")
        f.addRow("Remarks", self.remarks)
        v.addLayout(f)

        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        v.addWidget(self.preview)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        self.btn_ok.setText("Post adjustment")
        bb.accepted.connect(self.post)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        for w in (self.sp_count, self.sp_delta):
            w.valueChanged.connect(self._refresh)
        for w in (self.rb_count, self.rb_delta):
            w.toggled.connect(self._refresh)
        self._refresh()

    # ------------------------------------------------------------------ calc
    def delta(self) -> float:
        if self.rb_delta.isChecked():
            return round(self.sp_delta.value(), 4)
        return round(self.sp_count.value() - self.system_qty, 4)

    def new_balance(self) -> float:
        return round(self.system_qty + self.delta(), 4)

    def _refresh(self, *_):
        self.sp_count.setEnabled(self.rb_count.isChecked())
        self.sp_delta.setEnabled(self.rb_delta.isChecked())
        d, nb = self.delta(), self.new_balance()
        colour = W.GREEN if d > 0 else (W.RED if d < 0 else W.MUTED)
        self.preview.setText(
            f"<span style='color:{colour}'><b>{d:+g}</b></span> &nbsp;→&nbsp; "
            f"new balance <b>{nb:g}</b> {self.item.get('uom','')}"
            + ("" if nb >= 0 else
               f" &nbsp;<span style='color:{W.RED}'>— a balance cannot be "
               "negative</span>"))
        self.btn_ok.setEnabled(abs(d) > 1e-9 and nb >= 0)

    # ------------------------------------------------------------------ post
    def post(self):
        reason = self.reason.currentText().strip()
        if not reason:
            W.error_box(self, "A reason is mandatory for a stock adjustment.")
            return
        d = self.delta()
        if abs(d) < 1e-9:
            W.error_box(self, "The quantity has not changed.")
            return
        h = S.DocHeader(doc_type="ADJ", doc_date=QDate.currentDate().toString("yyyy-MM-dd"),
                        reason=reason, warehouse=self.wh.currentText(),
                        remarks=self.remarks.text().strip() or
                        f"Corrected from the delivery note screen ({self.item.get('code','')})")
        try:
            self.doc_no = S.post_adjustment(
                self.db, h, [S.Line(item_id=self.item["id"], qty=d,
                                    remarks=self.remarks.text().strip())])
        except Exception as exc:            # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.accept()


def _wrap(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    layout.setContentsMargins(0, 0, 0, 0)
    return w


class LineTable(QTableWidget):
    """Editable document line grid used by every transaction screen."""
    changed = Signal()
    #: row, quantity typed into the Available column -> ask for a stock adjustment
    availabilityEdited = Signal(int, float)
    #: right-click -> the page decides what the menu offers
    rowMenuRequested = Signal(int, object)
    #: Ctrl+V inside the grid -> the page opens the Excel paste dialog
    pasteRequested = Signal()

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
        self.itemChanged.connect(self._on_item_changed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        QShortcut(QKeySequence("Ctrl+V"), self,
                  activated=lambda: self.pasteRequested.emit()).setContext(
                      Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+C"), self, activated=self.copy_to_clipboard
                  ).setContext(Qt.WidgetWithChildrenShortcut)
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
                # The Available cell is editable on purpose: typing the real
                # physical count here posts a stock adjustment, so a wrong
                # system balance can be fixed without leaving the note.
                avail_cell = cell(bal, True, Qt.AlignRight)
                avail_cell.setToolTip(
                    "System stock. Type the real counted quantity to post a "
                    "stock adjustment for this item.")
                row = base + [avail_cell,
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

    # ------------------------------------------- inline inventory adjustment
    AVAIL_COL = {"OUT": 3, "TRANSFER": 3}

    def _on_item_changed(self, cell: QTableWidgetItem | None = None):
        """Route an edited cell: Available means 'correct the stock'."""
        col = self.AVAIL_COL.get(self.mode)
        if cell is not None and col is not None and cell.column() == col:
            r = cell.row()
            typed = self._num(r, col)
            current = round(float((self.items[r].get("balance") or 0)
                                  if r < len(self.items) else 0), 4)
            if abs(typed - current) > 1e-9:
                self.availabilityEdited.emit(r, typed)
                return
        self._recalc()

    def set_available(self, row: int, balance: float) -> None:
        """Write a fresh stock balance into the grid without re-triggering."""
        col = self.AVAIL_COL.get(self.mode)
        if col is None or not (0 <= row < self.rowCount()):
            return
        if row < len(self.items):
            self.items[row]["balance"] = balance
        self.blockSignals(True)
        if self.item(row, col) is not None:
            self.item(row, col).setText(f"{round(float(balance), 2):g}")
        self.blockSignals(False)
        self._recalc()

    def refresh_availability(self) -> int:
        """Re-read every balance from the database (another PC may have moved it)."""
        n = 0
        for r, it in enumerate(self.items):
            row = self.db.one("SELECT balance FROM items WHERE id=?", (it.get("id"),))
            if row is None:
                continue
            new = round(float(row["balance"] or 0), 4)
            if abs(new - float(it.get("balance") or 0)) > 1e-9:
                n += 1
            self.set_available(r, new)
        return n

    # ------------------------------------------------------- clipboard / xls
    def _context_menu(self, pos):
        idx = self.indexAt(pos)
        self.rowMenuRequested.emit(idx.row(), self.viewport().mapToGlobal(pos))

    def merge_rows(self, rows: list[dict]) -> tuple[int, int]:
        """Add pasted lines, updating a line that is already on the document.

        Returns (added, updated) so the screen can say what happened.
        """
        added = updated = 0
        for r in rows:
            hit = None
            for i, existing in enumerate(self.items):
                same_code = str(existing.get("code")) == str(r.get("code"))
                same_pr = (self.mode != "OUT" or
                           str(existing.get("pr_no") or "").strip() ==
                           str(r.get("pr_no") or "").strip())
                if same_code and same_pr:
                    hit = i
                    break
            if hit is None:
                before = self.rowCount()
                self.add_items([r])
                added += self.rowCount() - before
                continue
            qcol = 3 if self.mode == "IN" else 4
            self.blockSignals(True)
            if self.item(hit, qcol) is not None:
                self.item(hit, qcol).setText(f"{float(r.get('qty') or 0):g}")
            if self.mode == "OUT" and r.get("pr_no") and self.item(hit, 5) is not None:
                self.item(hit, 5).setText(str(r["pr_no"]))
            self.blockSignals(False)
            self.items[hit].update({k: v for k, v in r.items()
                                    if k in ("pr_no", "remarks")})
            updated += 1
        self._recalc()
        self.changed.emit()
        return added, updated

    #: only these headings are exported as numbers — a PR number such as
    #: "001735" must keep its leading zeros, so everything else stays text
    NUMERIC_HEADS = ("quantity", "available", "unit cost", "total", "system qty",
                     "adjustment (+/-)", "new balance", "counted qty", "variance",
                     "issued qty", "returned qty")

    def grid_rows(self) -> tuple[list[str], list[list[Any]]]:
        """The visible grid as (headers, rows) — used for the Excel export."""
        numeric = {i for i, h in enumerate(self.cols)
                   if str(h).strip().lower() in self.NUMERIC_HEADS}
        rows = []
        for r in range(self.rowCount()):
            row: list[Any] = []
            for c in range(self.columnCount()):
                w = self.cellWidget(r, c)
                if isinstance(w, QComboBox):
                    row.append(w.currentText())
                    continue
                cell = self.item(r, c)
                text = cell.text() if cell else ""
                num = _to_number(text) if (c in numeric and text) else None
                row.append(num if num is not None else text)
            rows.append(row)
        return list(self.cols), rows

    def copy_to_clipboard(self) -> int:
        """Ctrl+C — the whole grid (or just the selection) as Excel-ready text."""
        cols, rows = self.grid_rows()
        picked = sorted({i.row() for i in self.selectedIndexes()})
        body = [rows[r] for r in picked] if picked else rows
        if not body:
            return 0
        text = "\n".join(["\t".join(cols)] +
                         ["\t".join("" if c is None else str(c) for c in r)
                          for r in body])
        QApplication.clipboard().setText(text)
        return len(body)

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
