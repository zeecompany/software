"""ADMIN STATION — camp / office record register, completely separate from stock.

Four tabs:
    📊 Dashboard   KPI tiles + charts driven purely by Admin Station data
    📋 Records     grid with filters, inline add / edit / delete, quick return
    ⬆ Upload      paste or file import with a column-mapping wizard + preview
    📈 Reports     12 reports, PDF / Excel / CSV / print / share

Nothing in this file imports the stock engine.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea,
                               QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..core import adminstation as A
from ..core import documents as D
from ..core.database import Database
from . import widgets as W
from .common import ShareBar, date_edit, iso


# ------------------------------------------------------------------ editor
class RecordDialog(QDialog):
    def __init__(self, adb: A.AdminDB, rec_id: int | None = None, parent=None,
                 preset: dict | None = None):
        super().__init__(parent)
        self.adb = adb
        self.rec_id = rec_id
        self.row = A.get_record(adb, rec_id) if rec_id else (preset or {})
        self.setWindowTitle("Admin Station — "
                            + ("Edit Record" if rec_id else "New Record"))
        self.setModal(True)
        self.resize(640, 620)
        v = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)

        g = self.row.get
        self.sr = QLineEdit(str(g("sr_no", "") or ""))
        self.sr.setPlaceholderText("auto")
        self.camp = W.combo(A.distinct(adb, "camp"), editable=True,
                            current=str(g("camp", "") or ""))
        self.date = date_edit(str(g("record_date", "") or "") or None)
        self.cat = W.combo(A.distinct(adb, "category"), editable=True,
                           current=str(g("category", "") or ""))
        self.desc = QLineEdit(str(g("description", "") or ""))
        self.uom = W.combo(A.distinct(adb, "uom") or ["No", "PCS", "SET", "MTR", "KG"],
                           editable=True, current=str(g("uom", "") or ""))
        self.qty = QDoubleSpinBox()
        self.qty.setRange(-1e9, 1e9)
        self.qty.setDecimals(2)
        self.qty.setValue(float(g("qty", 0) or 0))
        self.ret = QDoubleSpinBox()
        self.ret.setRange(-1e9, 1e9)
        self.ret.setDecimals(2)
        self.ret.setValue(float(g("qty_return", 0) or 0))
        self.dest = W.combo(A.distinct(adb, "destination"), editable=True,
                            current=str(g("destination", "") or ""))
        self.remarks = QLineEdit(str(g("remarks", "") or ""))
        self.ref = QLineEdit(str(g("ref_no", "") or ""))
        self.cust = W.combo(A.distinct(adb, "custodian"), editable=True,
                            current=str(g("custodian", "") or ""))
        self.cond = W.combo(A.CONDITIONS, current=str(g("condition", "") or ""))
        self.cost = QDoubleSpinBox()
        self.cost.setRange(0, 1e9)
        self.cost.setDecimals(2)
        self.cost.setValue(float(g("unit_cost", 0) or 0))
        self.status = W.combo(A.STATUSES, current=str(g("status", "") or "Active"))

        for label, wd in (("SR#", self.sr), ("Camp / Office Name", self.camp),
                          ("Date of Record", self.date), ("Item Category", self.cat),
                          ("Item Description", self.desc), ("UOM", self.uom),
                          ("Quantity", self.qty), ("Return", self.ret),
                          ("Destination Location", self.dest), ("Remarks", self.remarks),
                          ("Reference", self.ref), ("Custodian", self.cust),
                          ("Condition", self.cond), ("Unit Cost", self.cost),
                          ("Status", self.status)):
            form.addRow(label, wd)
        v.addLayout(form)

        hint = QLabel("Status updates itself from Quantity vs Return unless you change "
                      "it by hand. This register is stored separately from the "
                      "inventory database.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        v.addWidget(hint)
        v.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _save(self):
        if not self.desc.text().strip() and not self.camp.currentText().strip():
            W.error_box(self, "Enter at least a Camp / Office name or an Item "
                              "Description.")
            return
        data = {
            "sr_no": self.sr.text().strip(), "camp": self.camp.currentText().strip(),
            "record_date": iso(self.date), "category": self.cat.currentText().strip(),
            "description": self.desc.text().strip(), "uom": self.uom.currentText().strip(),
            "qty": self.qty.value(), "qty_return": self.ret.value(),
            "destination": self.dest.currentText().strip(),
            "remarks": self.remarks.text().strip(), "ref_no": self.ref.text().strip(),
            "custodian": self.cust.currentText().strip(),
            "condition": self.cond.currentText(), "unit_cost": self.cost.value(),
            "status": self.status.currentText(),
        }
        A.save_record(self.adb, data, self.rec_id)
        self.accept()


# ------------------------------------------------------------------ upload
class MappingDialog(QDialog):
    """Column mapping + live preview before anything is written."""

    def __init__(self, adb: A.AdminDB, headers, rows, source: str = "", parent=None):
        super().__init__(parent)
        self.adb = adb
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]
        self.source = source
        self.inserted = 0
        self.setWindowTitle("Admin Station — Map the uploaded columns")
        self.setModal(True)
        self.resize(1080, 700)

        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            f"<b>{len(self.rows)} row(s)</b> found in <i>{source or 'the pasted text'}"
            "</i>. Confirm which uploaded column feeds which field — recognised "
            "headings are matched automatically."))

        self.map_table = QTableWidget(len(self.headers), 3)
        self.map_table.setHorizontalHeaderLabels(
            ["Uploaded column", "Sample value", "Store as"])
        self.map_table.verticalHeader().setVisible(False)
        self.map_table.horizontalHeader().setStretchLastSection(True)
        auto = A.auto_map(self.headers)
        self.combos: list[QComboBox] = []
        choices = ["— ignore —"] + [lbl for _, lbl in A.ALL_FIELDS]
        self.by_label = {lbl: f for f, lbl in A.ALL_FIELDS}
        for i, h in enumerate(self.headers):
            self.map_table.setItem(i, 0, QTableWidgetItem(str(h)))
            sample = next((str(r[i]) for r in self.rows[:8]
                           if i < len(r) and str(r[i]).strip()), "")
            self.map_table.setItem(i, 1, QTableWidgetItem(sample[:60]))
            cb = QComboBox()
            cb.addItems(choices)
            if i in auto:
                cb.setCurrentText(A.LABELS[auto[i]])
            cb.currentTextChanged.connect(self._refresh)
            self.map_table.setCellWidget(i, 2, cb)
            self.combos.append(cb)
        self.map_table.resizeColumnsToContents()
        self.map_table.setMaximumHeight(240)
        v.addWidget(self.map_table)

        opts = QHBoxLayout()
        self.def_camp = QLineEdit()
        self.def_camp.setPlaceholderText("Default Camp / Office (used when blank)")
        self.def_date = date_edit()
        self.chk_dedupe = QCheckBox("Skip rows that already exist")
        self.chk_dedupe.setChecked(True)
        opts.addWidget(QLabel("Defaults:"))
        opts.addWidget(self.def_camp, 1)
        opts.addWidget(QLabel("Date:"))
        opts.addWidget(self.def_date)
        opts.addWidget(self.chk_dedupe)
        self.def_camp.textChanged.connect(self._refresh)
        self.def_date.dateChanged.connect(self._refresh)
        v.addLayout(opts)

        self.preview = W.DataTable()
        v.addWidget(self.preview, 1)
        self.info = QLabel()
        self.info.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(self.info)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("⬆  Import Records")
        bb.accepted.connect(self._import)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._refresh()

    def _mapping(self) -> dict[int, str]:
        out = {}
        for i, cb in enumerate(self.combos):
            lbl = cb.currentText()
            if lbl in self.by_label:
                out[i] = self.by_label[lbl]
        return out

    def _defaults(self) -> dict:
        return {"camp": self.def_camp.text().strip(),
                "record_date": iso(self.def_date)}

    def _refresh(self, *_):
        self.records = A.preview(self.headers, self.rows, self._mapping(),
                                 self._defaults())
        cols = [lbl for _, lbl in A.FIELDS] + ["Status"]
        data = [[r["sr_no"], r["camp"], r["record_date"], r["category"], r["description"],
                 r["uom"], r["qty"], r["qty_return"], r["destination"], r["remarks"],
                 r["status"]] for r in self.records[:400]]
        self.preview.fill(cols, data)
        mapped = len(self._mapping())
        self.info.setText(f"{len(self.records)} record(s) ready  ·  {mapped} column(s) "
                          f"mapped  ·  showing first {len(data)}")

    def _import(self):
        if not self.records:
            W.error_box(self, "Nothing to import — map at least one column.")
            return
        ins, skipped = A.import_records(self.adb, self.records, self.source,
                                        self._mapping(),
                                        self.chk_dedupe.isChecked())
        self.inserted = ins
        W.info_box(self, f"{ins} record(s) imported."
                         + (f"\n{skipped} duplicate row(s) skipped." if skipped else ""),
                   "Admin Station")
        self.accept()


class UploadTab(QWidget):
    imported = Signal()

    def __init__(self, adb: A.AdminDB, parent=None):
        super().__init__(parent)
        self.adb = adb
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(10)

        card = W.Card("Recommended upload format")
        cols, sample = A.template_rows()
        t = W.DataTable()
        t.fill(cols, sample)
        t.setMaximumHeight(150)
        card.add(t)
        note = QLabel(
            "Any column order works and unknown headings are ignored — the wizard "
            "matches them automatically and lets you correct the mapping. "
            "Accepted sources: Excel (.xlsx), CSV, tab-separated paste from Excel, "
            "or plain text. <b>Return</b> may be a number or the word "
            "<i>Yes</i> (meaning everything came back).")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        card.add(note)
        row = QHBoxLayout()
        row.addWidget(W.button("⬇  Download Excel Template", slot=self._template))
        row.addWidget(W.button("📂  Import from File...", "Primary", self._file))
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        card.add(holder)
        v.addWidget(card)

        paste_card = W.Card("Paste rows directly from Excel")
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText(
            "Copy the rows in Excel (including the heading row) and press Ctrl+V here, "
            "then click Read Pasted Rows.")
        self.paste.setMinimumHeight(180)
        paste_card.add(self.paste, 1)
        r2 = QHBoxLayout()
        r2.addWidget(W.button("📋  Read Pasted Rows", "Primary", self._paste))
        r2.addWidget(W.button("🧹  Clear", slot=self.paste.clear))
        r2.addStretch(1)
        h2 = QWidget()
        h2.setLayout(r2)
        paste_card.add(h2)
        v.addWidget(paste_card, 1)

        hist = W.Card("Upload history  —  an import can be undone completely")
        self.hist = W.DataTable()
        hist.add(self.hist, 1)
        r3 = QHBoxLayout()
        r3.addWidget(W.button("↩  Undo Selected Import", slot=self._undo))
        r3.addWidget(W.button("🔄  Refresh", slot=self.reload))
        r3.addStretch(1)
        h3 = QWidget()
        h3.setLayout(r3)
        hist.add(h3)
        v.addWidget(hist, 1)
        self.reload()

    def reload(self):
        rows = A.batches(self.adb)
        self.hist.fill(["Batch", "When", "Source", "Imported", "Skipped", "Still present"],
                       [[b["id"], b["ts"], Path(str(b["source"])).name or b["source"],
                         b["rows"], b["skipped"], b["live"]] for b in rows])

    def _template(self):
        cols, sample = A.template_rows()
        f = D.export_excel(self.adb_main_db(), "Admin Station Upload Template", cols,
                           sample, out_path=Path(
                               D.config.folder(A.FOLDER)) / "Upload_Template.xlsx",
                           totals=False)
        W.toast(self, f"Template saved: {f.name}")
        D.open_path(f)

    def adb_main_db(self):
        return self.window().db if hasattr(self.window(), "db") else None

    def _file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select the file to import", "",
            "Spreadsheets and text (*.xlsx *.xlsm *.csv *.txt);;All files (*)")
        if not f:
            return
        try:
            headers, rows = A.read_file(f)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read that file.\n\n{exc}")
            return
        self._wizard(headers, rows, f)

    def _paste(self):
        txt = self.paste.toPlainText()
        if not txt.strip():
            W.error_box(self, "Paste the rows into the box first.")
            return
        headers, rows = A.sniff(txt)
        self._wizard(headers, rows, "pasted rows")

    def _wizard(self, headers, rows, source):
        if not rows:
            W.error_box(self, "No data rows were found.")
            return
        dlg = MappingDialog(self.adb, headers, rows, source, self)
        if dlg.exec() == QDialog.Accepted and dlg.inserted:
            self.paste.clear()
            self.reload()
            self.imported.emit()

    def _undo(self):
        r = self.hist.currentRow()
        if r < 0:
            W.error_box(self, "Select an import from the history first.")
            return
        bid = int(self.hist.item(r, 0).text())
        live = int(self.hist.item(r, 5).text())
        if not live:
            W.error_box(self, "That import has no records left to remove.")
            return
        if not W.confirm(self, f"Remove the {live} record(s) that came from import "
                               f"#{bid}?\n\nThis cannot be undone."):
            return
        n = A.undo_batch(self.adb, bid)
        self.reload()
        self.imported.emit()
        W.toast(self, f"{n} record(s) removed.")


# ---------------------------------------------------------------- records tab
class RecordsTab(QWidget):
    changed = Signal()

    def __init__(self, adb: A.AdminDB, main_db: Database, parent=None):
        super().__init__(parent)
        self.adb = adb
        self.db = main_db
        self.rows: list[dict] = []
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search description, camp, category, destination, "
                                  "remarks, SR#, reference, custodian...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 3)
        self.f_camp = W.combo(["All Camps / Offices"])
        self.f_cat = W.combo(["All Categories"])
        self.f_dest = W.combo(["All Destinations"])
        self.f_status = W.combo(["All Status"] + A.STATUSES)
        for c in (self.f_camp, self.f_cat, self.f_dest, self.f_status):
            c.currentTextChanged.connect(self.reload)
            bar.addWidget(c)
        self.chk_open = QCheckBox("Only outstanding")
        self.chk_open.toggled.connect(self.reload)
        bar.addWidget(self.chk_open)
        v.addLayout(bar)

        dates = QHBoxLayout()
        self.d_from = date_edit()
        self.d_from.setDate(QDate.currentDate().addYears(-3))
        self.d_to = date_edit()
        self.d_to.setDate(QDate.currentDate().addYears(1))
        self.chk_dates = QCheckBox("Filter by date")
        for wd in (self.d_from, self.d_to):
            wd.dateChanged.connect(self.reload)
        self.chk_dates.toggled.connect(self.reload)
        dates.addWidget(self.chk_dates)
        dates.addWidget(QLabel("From:"))
        dates.addWidget(self.d_from)
        dates.addWidget(QLabel("To:"))
        dates.addWidget(self.d_to)
        dates.addStretch(1)
        v.addLayout(dates)

        btns = QHBoxLayout()
        btns.addWidget(W.button("➕  New Record", "Primary", self.new_record))
        btns.addWidget(W.button("✏  Edit", slot=self.edit_record))
        btns.addWidget(W.button("⧉  Duplicate", slot=self.duplicate))
        btns.addWidget(W.button("↩  Mark Returned", slot=self.mark_returned))
        btns.addWidget(W.button("🗑  Delete", slot=self.delete_records))
        btns.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        btns.addWidget(W.button("📄  PDF", slot=lambda: self.export("pdf")))
        btns.addWidget(W.button("📑  CSV", slot=lambda: self.export("csv")))
        btns.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        btns.addWidget(self.count)
        v.addLayout(btns)

        self.table = W.DataTable()
        self.table.doubleClicked.connect(self.edit_record)
        v.addWidget(W.FilterBar(self.table))
        v.addWidget(self.table, 1)
        v.addWidget(ShareBar(main_db, lambda: self.last_file, self))
        self.reload_filters()
        self.reload()

    def reload_filters(self):
        for cb, col, first in ((self.f_camp, "camp", "All Camps / Offices"),
                               (self.f_cat, "category", "All Categories"),
                               (self.f_dest, "destination", "All Destinations")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + A.distinct(self.adb, col))
            i = cb.findText(cur)
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)

    def _filters(self) -> dict:
        return {
            "text": self.search.text(),
            "camp": "" if self.f_camp.currentIndex() <= 0 else self.f_camp.currentText(),
            "category": "" if self.f_cat.currentIndex() <= 0 else self.f_cat.currentText(),
            "destination": ("" if self.f_dest.currentIndex() <= 0
                            else self.f_dest.currentText()),
            "status": ("" if self.f_status.currentIndex() <= 0
                       else self.f_status.currentText()),
            "date_from": iso(self.d_from) if self.chk_dates.isChecked() else "",
            "date_to": iso(self.d_to) if self.chk_dates.isChecked() else "",
            "only_open": self.chk_open.isChecked(),
        }

    def reload(self):
        f = self._filters()
        self.rows = A.search(self.adb, **f)
        data = [[r["id"], r["sr_no"], r["camp"], r["record_date"], r["category"],
                 r["description"], r["uom"], round(r["qty"] or 0, 2),
                 round(r["qty_return"] or 0, 2),
                 round((r["qty"] or 0) - (r["qty_return"] or 0), 2),
                 r["destination"], r["remarks"], r["status"]] for r in self.rows]
        self.table.fill(["ID", "SR#", "Camp / Office", "Date", "Category", "Description",
                         "UOM", "Quantity", "Return", "Outstanding",
                         "Destination Location", "Remarks", "Status"], data)
        self.table.setColumnHidden(0, True)
        qty = sum(r["qty"] or 0 for r in self.rows)
        ret = sum(r["qty_return"] or 0 for r in self.rows)
        self.count.setText(f"{len(self.rows)} record(s)  ·  {qty:,.2f} qty  ·  "
                           f"{ret:,.2f} returned  ·  {qty - ret:,.2f} outstanding")

    def _selected_ids(self) -> list[int]:
        return sorted({int(self.table.item(i.row(), 0).text())
                       for i in self.table.selectedIndexes()
                       if self.table.item(i.row(), 0)})

    def _one(self) -> int | None:
        ids = self._selected_ids()
        if not ids:
            W.error_box(self, "Select a record from the list first.")
            return None
        return ids[0]

    def new_record(self):
        preset = {"camp": ("" if self.f_camp.currentIndex() <= 0
                           else self.f_camp.currentText())}
        if RecordDialog(self.adb, None, self, preset).exec() == QDialog.Accepted:
            self.reload_filters()
            self.reload()
            self.changed.emit()
            W.toast(self, "Record added to the Admin Station register.")

    def edit_record(self):
        rid = self._one()
        if rid and RecordDialog(self.adb, rid, self).exec() == QDialog.Accepted:
            self.reload_filters()
            self.reload()
            self.changed.emit()
            W.toast(self, "Record updated.")

    def duplicate(self):
        rid = self._one()
        if not rid:
            return
        rec = A.get_record(self.adb, rid) or {}
        rec.pop("id", None)
        rec["sr_no"] = ""
        if RecordDialog(self.adb, None, self, rec).exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()

    def mark_returned(self):
        ids = self._selected_ids()
        if not ids:
            W.error_box(self, "Select one or more records first.")
            return
        if not W.confirm(self, f"Mark {len(ids)} record(s) as fully returned?"):
            return
        for rid in ids:
            rec = A.get_record(self.adb, rid)
            if rec:
                rec["qty_return"] = rec["qty"]
                rec["status"] = "Returned"
                A.save_record(self.adb, rec, rid)
        self.reload()
        self.changed.emit()
        W.toast(self, f"{len(ids)} record(s) marked as returned.")

    def delete_records(self):
        ids = self._selected_ids()
        if not ids:
            W.error_box(self, "Select one or more records first.")
            return
        if not W.confirm(self, f"Permanently delete {len(ids)} record(s) from the "
                               "Admin Station register?"):
            return
        A.delete_records(self.adb, ids)
        self.reload_filters()
        self.reload()
        self.changed.emit()
        W.toast(self, f"{len(ids)} record(s) deleted.")

    def export(self, kind: str):
        cols = [lbl for _, lbl in A.FIELDS] + ["Status"]
        data = [[r["sr_no"], r["camp"], r["record_date"], r["category"], r["description"],
                 r["uom"], round(r["qty"] or 0, 2), round(r["qty_return"] or 0, 2),
                 r["destination"], r["remarks"], r["status"]] for r in self.rows]
        title = "Admin Station — Record Register"
        folder = Path(D.config.folder(A.FOLDER))
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        if kind == "xlsx":
            f = D.export_excel(self.db, title, cols, data,
                               folder / f"AdminStation_Records_{stamp}.xlsx")
        elif kind == "csv":
            f = D.export_csv(self.db, title, cols, data,
                             folder / f"AdminStation_Records_{stamp}.csv")
        else:
            f = D.admin_report_pdf(self.db, title, cols, data,
                                   folder / f"AdminStation_Records_{stamp}.pdf",
                                   subtitle=self._subtitle())
        self.last_file = f
        W.toast(self, f"Exported: {f.name}")
        D.open_path(f)

    def _subtitle(self) -> str:
        f = self._filters()
        bits = [f"{k.replace('_', ' ').title()}: {v}" for k, v in f.items()
                if v and k != "only_open"]
        if f["only_open"]:
            bits.append("Only outstanding")
        return "  ·  ".join(bits) or "All records"


class SiteFolderTab(QWidget):
    """Shared drive folder where site admins drop their sheets."""
    imported = Signal()

    def __init__(self, adb: A.AdminDB, parent=None):
        super().__init__(parent)
        self.adb = adb
        self.files: list[dict] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(9)

        card = W.Card("Shared upload folder")
        note = QLabel(
            "Point this at a folder on your drive or network share. Each site "
            "admin saves their sheet there and the Admin Station imports every "
            "new file in one click. Files already imported are remembered, so "
            "the same sheet is never posted twice.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        card.add(note)
        row = QHBoxLayout()
        self.path = QLineEdit(A.get_watch_folder(adb))
        self.path.setPlaceholderText(
            r"e.g.  \\server\shared\AURCO Site Uploads   or   D:\Site Uploads")
        row.addWidget(self.path, 1)
        row.addWidget(W.button("📂  Browse...", "Primary", self._browse))
        row.addWidget(W.button("💾  Save Folder", slot=self._save))
        row.addWidget(W.button("🔄  Scan Now", "Accent", self.reload))
        row.addWidget(W.button("📁  Open Folder", slot=self._open))
        rw = QWidget()
        rw.setLayout(row)
        card.add(rw)
        self.status = QLabel("No folder selected.")
        self.status.setWordWrap(True)
        card.add(self.status)
        v.addWidget(card)

        opts = QHBoxLayout()
        self.chk_done = QCheckBox("Also list files already imported")
        self.chk_done.toggled.connect(self.reload)
        opts.addWidget(self.chk_done)
        self.chk_dedupe = QCheckBox("Skip rows that already exist")
        self.chk_dedupe.setChecked(True)
        opts.addWidget(self.chk_dedupe)
        self.chk_archive = QCheckBox("Move imported files to an 'Imported' sub-folder")
        opts.addWidget(self.chk_archive)
        opts.addStretch(1)
        v.addLayout(opts)

        btns = QHBoxLayout()
        btns.addWidget(W.button("⬆  Import Selected", "Primary", self._import_selected))
        btns.addWidget(W.button("⬆  Import All New", slot=self._import_all))
        btns.addWidget(W.button("👁  Preview / Map Columns...", slot=self._preview))
        btns.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        btns.addWidget(self.count)
        v.addLayout(btns)

        self.table = W.DataTable()
        self.table.doubleClicked.connect(self._preview)
        v.addWidget(W.FilterBar(self.table))
        v.addWidget(self.table, 1)
        self.reload()

    # ------------------------------------------------------------- helpers
    def _browse(self):
        start = self.path.text().strip() or str(Path.home())
        d = QFileDialog.getExistingDirectory(
            self, "Select the shared folder used by site admins", start)
        if d:
            self.path.setText(d)
            self._save()

    def _save(self):
        p = self.path.text().strip()
        ok, msg = A.folder_status(p)
        if p and not ok:
            W.error_box(self, msg)
        A.set_watch_folder(self.adb, p)
        self.reload()
        if ok:
            W.toast(self, "Shared folder saved.")

    def _open(self):
        p = self.path.text().strip()
        if p and Path(p).exists():
            D.open_path(p)
        else:
            W.error_box(self, "Select an existing folder first.")

    def reload(self):
        p = self.path.text().strip()
        ok, msg = A.folder_status(p)
        self.status.setText(
            (f"<b style='color:{W.GREEN}'>✔ Connected</b> — {msg}" if ok
             else f"<b style='color:{W.RED}'>✕</b> {msg}"))
        self.files = A.scan_folder(self.adb, p, self.chk_done.isChecked()) if ok else []
        self.table.fill(["File", "Detected Site", "Size (KB)", "Modified",
                         "Status", "Imported On", "Rows", "Full Path"],
                        [[f["name"], f["site"], f["size_kb"], f["modified"],
                          f["status"], f["imported_at"], f["imported_rows"],
                          f["path"]] for f in self.files])
        self.table.setColumnHidden(7, True)
        new = sum(1 for f in self.files if f["status"] == "New")
        self.count.setText(f"{len(self.files)} file(s) · {new} new")

    def _selected(self) -> list[dict]:
        names = {self.table.item(i.row(), 0).text()
                 for i in self.table.selectedIndexes()
                 if self.table.item(i.row(), 0)}
        return [f for f in self.files if f["name"] in names]

    def _archive_dir(self):
        if not self.chk_archive.isChecked():
            return None
        p = self.path.text().strip()
        return str(Path(p) / "Imported") if p else None

    def _run(self, files: list[dict]):
        if not files:
            W.error_box(self, "No files selected.")
            return
        if not W.confirm(self, f"Import {len(files)} file(s) into the Admin "
                               "Station register?"):
            return
        res = A.import_from_folder(
            self.adb, [f["path"] for f in files],
            skip_duplicates=self.chk_dedupe.isChecked(),
            archive_to=self._archive_dir())
        lines = [f"{e['file']}: "
                 + (f"{e['inserted']} imported"
                    + (f", {e['skipped']} duplicate(s) skipped" if e["skipped"] else "")
                    if not e["error"] or e["inserted"] else "")
                 + (f"  ⚠ {e['error']}" if e["error"] else "")
                 for e in res["files"]]
        self.reload()
        self.imported.emit()
        W.info_box(self, f"{res['inserted']} record(s) imported from "
                         f"{len(files)} file(s).\n"
                         f"{res['failed']} file(s) could not be read.\n\n"
                         + "\n".join(lines[:25]), "Folder import complete")

    def _import_selected(self):
        self._run(self._selected())

    def _import_all(self):
        self._run([f for f in self.files if f["status"] == "New"])

    def _preview(self):
        sel = self._selected() or self.files[:1]
        if not sel:
            W.error_box(self, "Select a file first.")
            return
        try:
            headers, rows = A.read_file(sel[0]["path"])
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read that file.\n\n{exc}")
            return
        dlg = MappingDialog(self.adb, headers, rows, sel[0]["path"], self)
        if dlg.exec() == QDialog.Accepted and dlg.inserted:
            self.reload()
            self.imported.emit()


# ------------------------------------------------------------- dashboard tab
class AdminDashboard(QWidget):
    """Interactive dashboard: filter bar, 16 KPI tiles, 8 analytical charts.

    Every tile and chart honours the filter bar, so the whole page can be
    narrowed to one camp, one category or one period at a time.
    """
    openRecords = Signal(dict)

    def __init__(self, adb: A.AdminDB, main_db: Database | None = None, parent=None):
        super().__init__(parent)
        self.adb = adb
        self.main_db = main_db
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ------------------------------------------------------- filter bar
        fbar = QWidget()
        fbar.setObjectName("Card")
        fl = QHBoxLayout(fbar)
        fl.setContentsMargins(10, 7, 10, 7)
        fl.setSpacing(7)
        self.f_text = W.SearchBox("Filter the whole dashboard...")
        self.f_text.textChanged.connect(self.refresh)
        fl.addWidget(self.f_text, 2)
        self.f_camp = W.combo(["All Camps / Offices"])
        self.f_cat = W.combo(["All Categories"])
        self.f_dest = W.combo(["All Destinations"])
        self.f_status = W.combo(["All Status"] + A.STATUSES)
        for c in (self.f_camp, self.f_cat, self.f_dest, self.f_status):
            c.currentTextChanged.connect(self.refresh)
            fl.addWidget(c)
        self.f_period = W.combo(["All time", "This month", "Last 3 months",
                                 "Last 6 months", "This year", "Last 12 months"])
        self.f_period.currentTextChanged.connect(self.refresh)
        fl.addWidget(self.f_period)
        self.f_open = QCheckBox("Only outstanding")
        self.f_open.toggled.connect(self.refresh)
        fl.addWidget(self.f_open)
        self.f_measure = W.combo(["Measure: Quantity", "Measure: Line count",
                                  "Measure: Value", "Measure: Outstanding"])
        self.f_measure.currentTextChanged.connect(self.refresh)
        fl.addWidget(self.f_measure)
        fl.addWidget(W.button("↺  Reset", slot=self.reset_filters))
        fl.addWidget(W.button("📄  Export View", slot=self._export))
        outer.addWidget(fbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, 1)
        body = QWidget()
        body.setObjectName("Page")
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(8, 10, 8, 14)
        v.setSpacing(13)

        self.cards: dict[str, W.StatCard] = {}
        specs = [("records", "Total Records", "🗃", W.NAVY),
                 ("camps", "Camps / Offices", "🏕", "#14538f"),
                 ("categories", "Item Categories", "🏷", "#7048e8"),
                 ("destinations", "Destinations", "📍", "#0b7285"),
                 ("qty", "Total Quantity", "Σ", W.GREEN),
                 ("returned", "Returned Quantity", "↩", "#1098ad"),
                 ("on_site", "Still On Site", "📦", "#e8590c"),
                 ("open_lines", "Outstanding Lines", "⏳", W.AMBER),
                 ("returned_lines", "Completed Returns", "✔", W.GREEN),
                 ("return_rate", "Return Rate %", "％", "#0b7285"),
                 ("this_month", "Records This Month", "📅", W.NAVY),
                 ("this_month_qty", "Qty This Month", "📈", "#14538f"),
                 ("custodians", "Custodians", "👤", "#7048e8"),
                 ("avg_qty", "Avg Qty / Record", "⌀", "#495057"),
                 ("damaged", "Damaged / Scrap", "🛠", W.RED),
                 ("value", "Estimated Value", "💰", "#1a9c52")]
        grid = QGridLayout()
        grid.setSpacing(11)
        for i, (k, label, glyph, col) in enumerate(specs):
            c = W.StatCard(label, "0", glyph, col)
            c.setToolTip("Click to open these records")
            c.clicked.connect(lambda k=k: self._drill(k))
            grid.addWidget(c, i // 4, i % 4)
            self.cards[k] = c
        v.addLayout(grid)

        r1 = QHBoxLayout()
        r1.setSpacing(12)
        c1 = W.Card("By Camp / Office")
        self.ch_camp = W.BarChart(horizontal=True, color="#14538f")
        self.ch_camp.barClicked.connect(lambda k: self._filter_to("camp", k))
        c1.add(self.ch_camp)
        r1.addWidget(c1, 2)
        c2 = W.Card("By Item Category")
        self.ch_cat = W.BarChart(horizontal=True, color="#7048e8")
        self.ch_cat.barClicked.connect(lambda k: self._filter_to("category", k))
        c2.add(self.ch_cat)
        r1.addWidget(c2, 2)
        v.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(12)
        c3 = QWidget()
        c3l = QVBoxLayout(c3)
        c3l.setContentsMargins(0, 0, 0, 0)
        cc = W.Card("Top Destinations")
        self.ch_dest = W.BarChart(horizontal=True, color="#0b7285")
        self.ch_dest.barClicked.connect(lambda k: self._filter_to("destination", k))
        cc.add(self.ch_dest)
        c3l.addWidget(cc)
        r2.addWidget(c3, 2)
        c4 = W.Card("Issued vs Returned by Month")
        self.ch_io = W.GroupedBarChart()
        c4.add(self.ch_io)
        r2.addWidget(c4, 3)
        v.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(12)
        c5 = W.Card("Monthly Volume Trend")
        self.ch_month = W.LineChart()
        c5.add(self.ch_month)
        r3.addWidget(c5, 3)
        c6 = W.Card("Return Status")
        self.ch_status = W.DonutChart()
        c6.add(self.ch_status)
        r3.addWidget(c6, 2)
        v.addLayout(r3)

        r4 = QHBoxLayout()
        r4.setSpacing(12)
        c7 = W.Card("Outstanding Ageing  (how long material has been out)")
        self.ch_age = W.BarChart(color="#e8590c")
        c7.add(self.ch_age)
        r4.addWidget(c7, 2)
        c8 = W.Card("Most Recorded Items")
        self.ch_items = W.BarChart(horizontal=True, color="#1a9c52")
        c8.add(self.ch_items)
        r4.addWidget(c8, 2)
        c9 = W.Card("Condition")
        self.ch_cond = W.DonutChart()
        c9.add(self.ch_cond)
        r4.addWidget(c9, 2)
        v.addLayout(r4)

        c10 = W.Card("Latest records matching the filters")
        self.recent = W.DataTable()
        self.recent.setMaximumHeight(250)
        c10.add(self.recent)
        v.addWidget(c10)
        v.addStretch(1)

        self.reload_filters()
        self.refresh()

    # -------------------------------------------------------------- filters
    def reload_filters(self):
        for cb, col, first in ((self.f_camp, "camp", "All Camps / Offices"),
                               (self.f_cat, "category", "All Categories"),
                               (self.f_dest, "destination", "All Destinations")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + A.distinct(self.adb, col))
            i = cb.findText(cur)
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)

    def reset_filters(self):
        for wdg in (self.f_camp, self.f_cat, self.f_dest, self.f_status,
                    self.f_period, self.f_measure):
            wdg.blockSignals(True)
            wdg.setCurrentIndex(0)
            wdg.blockSignals(False)
        self.f_text.blockSignals(True)
        self.f_text.clear()
        self.f_text.blockSignals(False)
        self.f_open.blockSignals(True)
        self.f_open.setChecked(False)
        self.f_open.blockSignals(False)
        self.refresh()

    def _period_range(self) -> tuple[str, str]:
        today = _dt.date.today()
        p = self.f_period.currentText()
        if p == "This month":
            return today.replace(day=1).isoformat(), ""
        if p == "Last 3 months":
            return (today - _dt.timedelta(days=91)).isoformat(), ""
        if p == "Last 6 months":
            return (today - _dt.timedelta(days=182)).isoformat(), ""
        if p == "This year":
            return today.replace(month=1, day=1).isoformat(), ""
        if p == "Last 12 months":
            return (today - _dt.timedelta(days=365)).isoformat(), ""
        return "", ""

    def filters(self) -> dict:
        d_from, d_to = self._period_range()
        return {
            "text": self.f_text.text(),
            "camp": "" if self.f_camp.currentIndex() <= 0 else self.f_camp.currentText(),
            "category": ("" if self.f_cat.currentIndex() <= 0
                         else self.f_cat.currentText()),
            "destination": ("" if self.f_dest.currentIndex() <= 0
                            else self.f_dest.currentText()),
            "status": ("" if self.f_status.currentIndex() <= 0
                       else self.f_status.currentText()),
            "date_from": d_from, "date_to": d_to,
            "only_open": self.f_open.isChecked(),
        }

    def _measure(self) -> str:
        return {"Measure: Quantity": "qty", "Measure: Line count": "count",
                "Measure: Value": "value",
                "Measure: Outstanding": "outstanding"}[self.f_measure.currentText()]

    def _filter_to(self, field: str, value: str):
        """Clicking a bar narrows the dashboard to that slice."""
        cb = {"camp": self.f_camp, "category": self.f_cat,
              "destination": self.f_dest}.get(field)
        if cb is None:
            return
        i = cb.findText(value)
        cb.setCurrentIndex(i if i >= 0 else 0)

    def _drill(self, key: str):
        f = self.filters()
        if key in ("open_lines", "on_site"):
            f["only_open"] = True
        elif key == "returned_lines":
            f["status"] = "Returned"
        self.openRecords.emit(f)

    def _export(self):
        f = self.filters()
        title, cols, rows = A.build_report(self.adb, "Full Record Register", f)
        out = Path(D.config.folder(A.FOLDER)) / (
            f"AdminStation_Dashboard_{_dt.datetime.now():%Y%m%d_%H%M%S}.pdf")
        bits = [f"{k.replace('_', ' ').title()}: {v}" for k, v in f.items() if v]
        d = A.dashboard(self.adb, f)
        stats = [("Records", f"{d['records']:,}", "#12283f"),
                 ("Quantity", f"{d['qty']:,.2f}", "#0f7b3d"),
                 ("Returned", f"{d['returned']:,.2f}", "#0b6e83"),
                 ("On Site", f"{d['on_site']:,.2f}", "#9a6700"),
                 ("Outstanding", f"{d['open_lines']:,}", "#b3261e"),
                 ("Return Rate", f"{d['return_rate']:.1f}%", "#12283f")]
        try:
            fp = D.material_check_pdf(
                self.main_db, "Admin Station — Dashboard View", cols, rows,
                stats=stats, out_path=out,
                subtitle="  ·  ".join(bits) or "All records", legend=False)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not export the view.\n\n{exc}")
            return
        W.toast(self, f"Exported: {fp.name}")
        D.open_path(fp)

    # -------------------------------------------------------------- refresh
    def refresh(self):
        f = self.filters()
        m = self._measure()
        d = A.dashboard(self.adb, f)
        for k, card in self.cards.items():
            val = d.get(k, 0)
            if k == "return_rate":
                card.set_value(f"{val:.1f}%")
            elif k == "value":
                card.set_value(f"{val:,.0f}")
            elif isinstance(val, float):
                card.set_value(f"{val:,.2f}")
            else:
                card.set_value(f"{val:,}")
        self.cards["records"].lbl_sub.setText(
            f"last import: {(d['last_import'] or 'never')[:16]}")
        if d.get("no_date"):
            self.cards["this_month"].lbl_sub.setText(f"{d['no_date']} with no date")

        self.ch_camp.set_data(A.by_column(self.adb, "camp", 10, m, f))
        self.ch_cat.set_data(A.by_column(self.adb, "category", 10, m, f))
        self.ch_dest.set_data(A.by_column(self.adb, "destination", 10, m, f))
        self.ch_io.set_data(A.monthly_in_out(self.adb, 8, f))
        self.ch_month.set_data(A.monthly(self.adb, 12, f))
        self.ch_status.set_data([("Outstanding", d["open_lines"], W.AMBER),
                                 ("Returned", d["returned_lines"], W.GREEN)])
        self.ch_age.set_data(A.ageing(self.adb, f))
        self.ch_items.set_data(A.top_items(self.adb, 10, f))
        palette = ["#1a9c52", "#1098ad", "#e0a300", "#e8590c", "#c92a2a", "#7048e8",
                   "#868e96"]
        self.ch_cond.set_data([(k, v, palette[i % len(palette)])
                               for i, (k, v) in
                               enumerate(A.condition_split(self.adb, f))])

        rows = A.search(self.adb, **f)[:40]
        self.recent.fill(["SR#", "Camp / Office", "Date", "Category", "Description",
                          "UOM", "Quantity", "Return", "Destination", "Status"],
                         [[r["sr_no"], r["camp"], r["record_date"], r["category"],
                           r["description"], r["uom"], round(r["qty"] or 0, 2),
                           round(r["qty_return"] or 0, 2), r["destination"],
                           r["status"]] for r in rows])


# --------------------------------------------------------------- reports tab
class AdminReportsTab(QWidget):
    def __init__(self, adb: A.AdminDB, main_db: Database, parent=None):
        super().__init__(parent)
        self.adb = adb
        self.db = main_db
        self.last_file: Path | None = None
        self.cols: list[str] = []
        self.rows: list[list] = []
        self.title = ""

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)
        split = QSplitter(Qt.Horizontal)

        left = W.Card("Admin Station Reports")
        self.list = QListWidget()
        for r in A.REPORT_LIST:
            self.list.addItem(QListWidgetItem("   " + r))
        self.list.currentItemChanged.connect(self.run)
        left.add(self.list)
        left.setMinimumWidth(230)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        filt = QHBoxLayout()
        self.f_text = W.SearchBox("Text filter...")
        self.f_camp = W.combo(["All Camps / Offices"])
        self.f_cat = W.combo(["All Categories"])
        self.f_text.returnPressed.connect(self.run)
        for c in (self.f_camp, self.f_cat):
            c.currentTextChanged.connect(self.run)
        filt.addWidget(self.f_text, 1)
        filt.addWidget(self.f_camp)
        filt.addWidget(self.f_cat)
        filt.addWidget(W.button("🔄  Run", "Primary", self.run))
        rv.addLayout(filt)

        act = QHBoxLayout()
        act.addWidget(W.button("📄  PDF", "Accent", lambda: self.export("pdf")))
        act.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        act.addWidget(W.button("📑  CSV", slot=lambda: self.export("csv")))
        act.addStretch(1)
        self.info = QLabel()
        self.info.setStyleSheet(f"color:{W.MUTED};")
        act.addWidget(self.info)
        rv.addLayout(act)

        self.table = W.DataTable()
        rv.addWidget(self.table, 1)
        rv.addWidget(ShareBar(main_db, lambda: self.last_file, self))
        split.addWidget(right)
        split.setSizes([230, 950])
        v.addWidget(split, 1)
        self.reload_filters()
        self.list.setCurrentRow(0)

    def reload_filters(self):
        for cb, col, first in ((self.f_camp, "camp", "All Camps / Offices"),
                               (self.f_cat, "category", "All Categories")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + A.distinct(self.adb, col))
            i = cb.findText(cur)
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)

    def run(self, *_):
        it = self.list.currentItem()
        if it is None:
            return
        name = it.text().strip()
        f = {"text": self.f_text.text(),
             "camp": "" if self.f_camp.currentIndex() <= 0 else self.f_camp.currentText(),
             "category": ("" if self.f_cat.currentIndex() <= 0
                          else self.f_cat.currentText())}
        self.title, self.cols, self.rows = A.build_report(self.adb, name, f)
        self.table.fill(self.cols, self.rows)
        self.info.setText(f"{len(self.rows)} row(s)")

    def export(self, kind: str):
        if not self.cols:
            W.error_box(self, "Run a report first.")
            return
        title = f"Admin Station — {self.title}"
        folder = Path(D.config.folder(A.FOLDER))
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = D.safe_name(self.title)
        if kind == "xlsx":
            f = D.export_excel(self.db, title, self.cols, self.rows,
                               folder / f"{base}_{stamp}.xlsx")
        elif kind == "csv":
            f = D.export_csv(self.db, title, self.cols, self.rows,
                             folder / f"{base}_{stamp}.csv")
        else:
            f = D.admin_report_pdf(self.db, title, self.cols, self.rows,
                                   folder / f"{base}_{stamp}.pdf",
                                   subtitle="Separate register — not part of the "
                                            "inventory stock ledger")
        self.last_file = f
        W.toast(self, f"Exported: {f.name}")
        D.open_path(f)


# ------------------------------------------------------------------- page
class AdminStationPage(QWidget):
    """Top-level page holding the four Admin Station tabs."""
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.adb = A.get_admin_db()
        self.adb.current_user = db.current_user

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)

        banner = QLabel(
            "🏢  <b>Admin Station</b> — a stand-alone register for camp and office "
            "records. It has its own database file "
            f"(<code>{self.adb.path.name}</code>), its own backups and its own "
            "reports. Nothing here affects inventory stock.")
        banner.setWordWrap(True)
        banner.setStyleSheet(
            f"background:{W.NAVY}; color:white; border-radius:7px; padding:8px 12px;")
        v.addWidget(banner)

        self.tabs = QTabWidget()
        self.dash = AdminDashboard(self.adb, db)
        self.records = RecordsTab(self.adb, db)
        self.upload = UploadTab(self.adb)
        self.sitefolder = SiteFolderTab(self.adb)
        self.reports = AdminReportsTab(self.adb, db)
        self.tabs.addTab(self.dash, "📊  Dashboard")
        self.tabs.addTab(self.records, "📋  Records")
        self.tabs.addTab(self.upload, "⬆  Upload Data")
        self.tabs.addTab(self.sitefolder, "📂  Site Uploads Folder")
        self.tabs.addTab(self.reports, "📈  Reports")
        v.addWidget(self.tabs, 1)

        tools = QHBoxLayout()
        tools.addWidget(W.button("💾  Backup Admin Station", slot=self._backup))
        tools.addWidget(W.button("♻  Restore...", slot=self._restore))
        tools.addWidget(W.button("📂  Open Data Folder", slot=self._folder))
        tools.addWidget(W.button("🔄  Refresh", slot=self.refresh))
        tools.addStretch(1)
        self.stat = QLabel()
        self.stat.setStyleSheet(f"color:{W.MUTED};")
        tools.addWidget(self.stat)
        v.addLayout(tools)

        self.records.changed.connect(self.refresh)
        self.dash.openRecords.connect(self._drill_to_records)
        self.upload.imported.connect(self.refresh)
        self.sitefolder.imported.connect(self.refresh)
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        self.refresh()

    def _drill_to_records(self, f: dict):
        """A dashboard tile was clicked -> open Records with the same filters."""
        r = self.records
        r.search.setText(f.get("text", ""))
        for cb, key in ((r.f_camp, "camp"), (r.f_cat, "category"),
                        (r.f_dest, "destination"), (r.f_status, "status")):
            cb.blockSignals(True)
            i = cb.findText(f.get(key) or "")
            cb.setCurrentIndex(i if (f.get(key) and i >= 0) else 0)
            cb.blockSignals(False)
        r.chk_open.blockSignals(True)
        r.chk_open.setChecked(bool(f.get("only_open")))
        r.chk_open.blockSignals(False)
        if f.get("date_from"):
            r.chk_dates.blockSignals(True)
            r.chk_dates.setChecked(True)
            r.chk_dates.blockSignals(False)
            r.d_from.blockSignals(True)
            r.d_from.setDate(QDate.fromString(f["date_from"], "yyyy-MM-dd"))
            r.d_from.blockSignals(False)
        r.reload()
        self.tabs.setCurrentIndex(1)

    def refresh(self):
        try:
            self.dash.reload_filters()
            self.dash.refresh()
            self.records.reload_filters()
            self.reports.reload_filters()
            d = A.dashboard(self.adb)
            self.stat.setText(f"{d['records']:,} record(s) · {d['camps']} camp(s) · "
                              f"database: {self.adb.path}")
            self.dataChanged.emit()
        except Exception as exc:  # noqa: BLE001
            self.stat.setText(f"Admin Station: {exc}")

    def _backup(self):
        f = self.adb.backup(note="manual backup from the Admin Station page")
        W.info_box(self, f"Admin Station backup created:\n\n{f}", "Backup complete")

    def _restore(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select an Admin Station backup", str(self.adb.path.parent),
            "Admin Station backups (*.db)")
        if not f:
            return
        if not W.confirm(self, "Replace the current Admin Station records with this "
                               "backup?\n\nA safety copy is taken first."):
            return
        try:
            self.adb.restore(f)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Restore failed.\n\n{exc}")
            return
        self.records.reload()
        self.upload.reload()
        self.refresh()
        W.toast(self, "Admin Station restored.")

    def _folder(self):
        D.open_path(self.adb.path.parent)
