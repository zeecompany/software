"""General Delivery Note Maker — a full DN with no inventory backend at all.

Tab 1  ✍ Create   free-text header + line grid, paste support, templates
Tab 2  🗂 Saved    every general DN created, with reprint / duplicate / delete

Lines are typed by hand (or pasted from Excel); no item must exist anywhere.
Nothing on this page reads or writes stock.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QPlainTextEdit, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextEdit, QTimeEdit, QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import gdn as G
from ..core import signatories as SG
from ..core.database import Database, today
from . import widgets as W
from .common import (ShareBar, clipboard_attachment_entries, date_edit, iso, lookup,
                     store_attachment_file)

COLS = ["Item Code", "Description", "UOM", "Quantity", "Unit Price", "Ref / PR", "Remarks"]
KEYS = ["item_code", "description", "uom", "qty", "unit_cost", "pr_no", "remarks"]


class GDNLineTable(QTableWidget):
    """Free-text line grid — every cell is editable, nothing is validated
    against the item master."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(0, len(COLS), parent)
        self.setHorizontalHeaderLabels(COLS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setDefaultSectionSize(26)
        hh = self.horizontalHeader()
        for i, mode in enumerate([QHeaderView.ResizeToContents, QHeaderView.Stretch,
                                  QHeaderView.ResizeToContents,
                                  QHeaderView.ResizeToContents,
                                  QHeaderView.ResizeToContents,
                                  QHeaderView.ResizeToContents, QHeaderView.Stretch]):
            hh.setSectionResizeMode(i, mode)
        self.itemChanged.connect(lambda *_: self.changed.emit())
        self.add_row()

    def add_row(self, values: dict | None = None):
        r = self.rowCount()
        self.insertRow(r)
        self.blockSignals(True)
        for c, key in enumerate(KEYS):
            v = (values or {}).get(key, "")
            if key in ("qty", "unit_cost"):
                v = "" if v in ("", None) else f"{float(v):g}"
            it = QTableWidgetItem(str(v))
            if key in ("qty", "unit_cost"):
                it.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
            self.setItem(r, c, it)
        self.blockSignals(False)
        self.changed.emit()

    def remove_selected(self):
        for r in sorted({i.row() for i in self.selectedIndexes()}, reverse=True):
            self.removeRow(r)
        if not self.rowCount():
            self.add_row()
        self.changed.emit()

    def clear_lines(self):
        self.setRowCount(0)
        self.add_row()

    def _num(self, r: int, c: int) -> float:
        it = self.item(r, c)
        if it is None:
            return 0.0
        try:
            return float(str(it.text()).replace(",", "").strip() or 0)
        except ValueError:
            return 0.0

    def lines(self) -> list[dict]:
        out = []
        for r in range(self.rowCount()):
            rec = {}
            for c, key in enumerate(KEYS):
                it = self.item(r, c)
                rec[key] = it.text().strip() if it else ""
            rec["qty"] = self._num(r, 3)
            rec["unit_cost"] = self._num(r, 4)
            if rec["description"] or rec["item_code"] or rec["qty"]:
                out.append(rec)
        return out

    def set_lines(self, lines):
        self.setRowCount(0)
        for l in lines:
            self.add_row(l)
        if not self.rowCount():
            self.add_row()

    def totals(self) -> tuple[int, float, float]:
        ls = self.lines()
        return (len(ls), sum(l["qty"] for l in ls),
                sum(l["qty"] * l["unit_cost"] for l in ls))

    def paste_rows(self, text: str) -> int:
        """Paste tab/comma separated rows straight from Excel."""
        import csv
        import io
        import re
        raw = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
        if not raw:
            return 0
        if "\t" in raw[0]:
            rows = [ln.split("\t") for ln in raw]
        elif raw[0].count(",") >= 2:
            rows = list(csv.reader(io.StringIO("\n".join(raw))))
        else:
            rows = [re.split(r"\s{2,}", ln.strip()) for ln in raw]
        # drop a heading row if present
        if rows and any(str(c).strip().lower() in ("description", "item", "qty",
                                                   "quantity", "item code")
                        for c in rows[0]):
            rows = rows[1:]
        n = 0
        for r in rows:
            r = [str(c).strip() for c in r] + [""] * len(KEYS)
            self.add_row({k: r[i] for i, k in enumerate(KEYS)})
            n += 1
        # remove a leading empty row left over from the initial state
        if n and not any(self.item(0, c) and self.item(0, c).text().strip()
                         for c in range(self.columnCount())):
            self.removeRow(0)
        self.changed.emit()
        return n


class CreateTab(QWidget):
    saved = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.edit_id: int | None = None
        self.last_file: Path | None = None
        self.attachments: list[dict[str, object] | str] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        hdr = QGroupBox("Delivery note header  —  free text, nothing needs to exist "
                        "in the system")
        cols = QHBoxLayout(hdr)
        f1 = QFormLayout()
        f2 = QFormLayout()
        f3 = QFormLayout()
        for f in (f1, f2, f3):
            f.setSpacing(6)
            cols.addLayout(f, 1)

        self.doc_no = QLabel("<i>assigned when saved</i>")
        self.title = QLineEdit("DELIVERY NOTE")
        self.date = date_edit()
        self.frm = W.combo(lookup(db, "warehouses"), editable=True)
        self.to_party = QLineEdit()
        self.to_party.setPlaceholderText("Company / person receiving the material")
        self.to_address = QLineEdit()
        f1.addRow("DN Number", self.doc_no)
        f1.addRow("Document title", self.title)
        f1.addRow("Date", self.date)
        f1.addRow("From", self.frm)
        f1.addRow("Deliver To", self.to_party)
        f1.addRow("Address", self.to_address)

        self.project = W.combo(lookup(db, "sites"), editable=True)
        self.reference = QLineEdit()
        self.vehicle = QLineEdit()
        self.in_time = QTimeEdit()
        self.in_time.setDisplayFormat("HH:mm")
        self.out_time = QTimeEdit()
        self.out_time.setDisplayFormat("HH:mm")
        self.purpose = QLineEdit()
        f2.addRow("Project / Site", self.project)
        f2.addRow("Reference", self.reference)
        f2.addRow("Vehicle", self.vehicle)
        f2.addRow("In Time", self.in_time)
        f2.addRow("Out Time", self.out_time)
        f2.addRow("Purpose", self.purpose)

        names = [s["name"] for s in SG.list_signatories(db)]
        self.issued_by = W.combo(names, editable=True)
        self.delivered_by = W.combo(names, editable=True)
        self.handover_to = QLineEdit()
        self.handover_to.setPlaceholderText("Driver taking custody")
        self.handover_id = QLineEdit()
        self.handover_id.setPlaceholderText("Iqama / ID number")
        self.handover_phone = QLineEdit()
        self.handover_phone.setPlaceholderText("Phone")
        self.received_by = QLineEdit()
        f3.addRow("Issued By", self.issued_by)
        f3.addRow("Delivered By", self.delivered_by)
        f3.addRow("Handover To (Driver)", self.handover_to)
        f3.addRow("ID / Iqama", self.handover_id)
        f3.addRow("Phone", self.handover_phone)
        f3.addRow("Received By", self.received_by)
        v.addWidget(hdr)

        tools = QHBoxLayout()
        tools.addWidget(W.button("➕  Add Line", "Primary", lambda: self.table.add_row()))
        tools.addWidget(W.button("➖  Remove Line", slot=lambda: self.table.remove_selected()))
        tools.addWidget(W.button("📋  Paste from Excel...", slot=self._paste))
        tools.addWidget(W.button("🧹  Clear Lines", slot=self._clear))
        tools.addWidget(W.button("📎  Attach Document", slot=self._attach,
                                 tip="Choose supporting files to append after the PDF"))
        tools.addWidget(W.button("📋  Paste Attachment", slot=self._paste_attachment,
                                 tip="Paste a copied file or screenshot from the clipboard"))
        tools.addWidget(W.button("🧹  Clear Attachments", slot=self._clear_attachments,
                                 tip="Remove the pending attachments before saving"))
        self.attach_lbl = QLabel("")
        self.attach_lbl.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        tools.addWidget(self.attach_lbl)
        tools.addStretch(1)
        self.chk_values = QCheckBox("Show prices && amounts on the printed note")
        self.chk_values.toggled.connect(self._recalc)
        tools.addWidget(self.chk_values)
        v.addLayout(tools)

        self.table = GDNLineTable()
        self.table.changed.connect(self._recalc)
        v.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.remarks = QLineEdit()
        self.remarks.setPlaceholderText("Remarks printed under the totals")
        self.terms = QLineEdit()
        self.terms.setPlaceholderText("Terms & conditions (optional)")
        bottom.addWidget(QLabel("Remarks:"))
        bottom.addWidget(self.remarks, 2)
        bottom.addWidget(QLabel("Terms:"))
        bottom.addWidget(self.terms, 2)
        v.addLayout(bottom)

        act = QHBoxLayout()
        act.addWidget(W.button("💾  Save && Generate PDF", "Primary", self._save))
        act.addWidget(W.button("👁  Preview PDF", "Accent", lambda: self._save(True)))
        act.addWidget(W.button("🧾  Save as Template...", slot=self._save_template))
        self.cb_template = QComboBox()
        self.cb_template.setMinimumWidth(180)
        act.addWidget(self.cb_template)
        act.addWidget(W.button("📂  Load Template", slot=self._load_template))
        act.addWidget(W.button("🆕  New / Clear Form", slot=self.reset))
        act.addStretch(1)
        self.totals = QLabel()
        self.totals.setStyleSheet(f"color:{W.MUTED}; font-weight:600;")
        act.addWidget(self.totals)
        v.addLayout(act)
        v.addWidget(ShareBar(db, lambda: self.last_file, self))

        self.reload_templates()
        self._recalc()

    # ------------------------------------------------------------- helpers
    def reload_templates(self):
        cur = self.cb_template.currentText()
        self.cb_template.clear()
        names = G.template_names(self.db)
        self.cb_template.addItems(names or ["(no templates yet)"])
        if cur:
            self.cb_template.setCurrentText(cur)

    def _recalc(self, *_):
        n, qty, val = self.table.totals()
        cur = self.db.get_setting("currency", "")
        txt = f"{n} line(s)  ·  {qty:,.2f} qty"
        if self.chk_values.isChecked():
            txt += f"  ·  {cur} {val:,.2f}"
        self.totals.setText(txt)

    def _paste(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Paste delivery note lines")
        dlg.resize(760, 420)
        dv = QVBoxLayout(dlg)
        dv.addWidget(QLabel(
            "Paste rows copied from Excel. Column order: <b>Item Code · Description · "
            "UOM · Quantity · Unit Price · Ref/PR · Remarks</b>. Missing columns are "
            "left blank; a heading row is detected and skipped."))
        box = QPlainTextEdit()
        dv.addWidget(box, 1)
        from PySide6.QtWidgets import QDialogButtonBox
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add Lines")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        dv.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        n = self.table.paste_rows(box.toPlainText())
        W.toast(self, f"{n} line(s) added." if n else "Nothing recognised in the paste.")

    def _clear(self):
        if W.confirm(self, "Remove every line from this delivery note?"):
            self.table.clear_lines()

    def _attachment_entry(self, rec) -> dict[str, object]:
        if isinstance(rec, dict):
            path = str(rec.get("file_path") or rec.get("path") or "")
            source = str(rec.get("source") or "file")
            try:
                order = int(rec.get("page_order") or (2 if source == "clipboard" else 1))
            except (TypeError, ValueError):
                order = 2 if source == "clipboard" else 1
            return {"file_path": path, "source": source, "page_order": order}
        return {"file_path": str(rec), "source": "file", "page_order": 1}

    def _refresh_attachments(self):
        items = [self._attachment_entry(a) for a in self.attachments]
        n = len(items)
        pasted = sum(1 for a in items if a["source"] == "clipboard")
        names = ", ".join(Path(str(a["file_path"])).name for a in items[:3])
        self.attach_lbl.setText(
            "" if not n else
            f"📎 {n} file(s): {names}" + ("..." if n > 3 else "") +
            ("" if not pasted else f"  ·  {pasted} pasted"))

    def _attach(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Attach supporting documents")
        added = 0
        for f in files:
            try:
                dest = store_attachment_file(f)
            except OSError:
                dest = Path(f)
            self.attachments.append({"file_path": str(dest), "source": "file", "page_order": 1})
            added += 1
        if added:
            self._refresh_attachments()
            W.toast(self, f"{added} attachment(s) added.")

    def _paste_attachment(self):
        try:
            added = clipboard_attachment_entries()
        except ValueError as exc:
            W.error_box(self, str(exc))
            return 0
        self.attachments.extend(added)
        self._refresh_attachments()
        W.toast(self, f"{len(added)} clipboard attachment(s) added.")
        return len(added)

    def _clear_attachments(self):
        if not self.attachments:
            return 0
        n = len(self.attachments)
        self.attachments = []
        self._refresh_attachments()
        W.toast(self, f"Cleared {n} pending attachment(s).", "warn")
        return n

    def _register_attachments(self, doc_no: str):
        for a in self.attachments:
            ent = self._attachment_entry(a)
            self.db.execute(
                "INSERT INTO attachments(doc_type,doc_no,file_path,source,page_order) VALUES(?,?,?,?,?)",
                ("GDN", doc_no, ent["file_path"], ent["source"], ent["page_order"]))
        self.db.commit()
        self.attachments = []
        self._refresh_attachments()

    def header(self) -> dict:
        return {
            "doc_date": iso(self.date), "title": self.title.text().strip(),
            "from_location": self.frm.currentText().strip(),
            "to_party": self.to_party.text().strip(),
            "to_address": self.to_address.text().strip(),
            "project": self.project.currentText().strip(),
            "reference": self.reference.text().strip(),
            "vehicle": self.vehicle.text().strip(),
            "driver": self.handover_to.text().strip(),
            "in_time": self.in_time.time().toString("HH:mm"),
            "out_time": self.out_time.time().toString("HH:mm"),
            "issued_by": self.issued_by.currentText().strip(),
            "delivered_by": self.delivered_by.currentText().strip(),
            "handover_to": self.handover_to.text().strip(),
            "handover_id": self.handover_id.text().strip(),
            "handover_phone": self.handover_phone.text().strip(),
            "received_by": self.received_by.text().strip(),
            "purpose": self.purpose.text().strip(),
            "remarks": self.remarks.text().strip(),
            "terms": self.terms.text().strip(),
            "currency": self.db.get_setting("currency", ""),
            "show_values": 1 if self.chk_values.isChecked() else 0,
            "status": "FINAL",
        }

    def load(self, doc_id: int):
        h, lines = G.get(self.db, doc_id)
        if not h:
            W.error_box(self, "That delivery note no longer exists.")
            return
        self.edit_id = doc_id
        self.attachments = []
        self._refresh_attachments()
        self.doc_no.setText(f"<b>{h['doc_no']}</b>  (editing)")
        self.title.setText(h.get("title", "DELIVERY NOTE"))
        self.date.setDate(QDate.fromString(h.get("doc_date", ""), "yyyy-MM-dd")
                          or QDate.currentDate())
        self.frm.setCurrentText(h.get("from_location", ""))
        self.to_party.setText(h.get("to_party", ""))
        self.to_address.setText(h.get("to_address", ""))
        self.project.setCurrentText(h.get("project", ""))
        self.reference.setText(h.get("reference", ""))
        self.vehicle.setText(h.get("vehicle", ""))
        self.purpose.setText(h.get("purpose", ""))
        self.issued_by.setCurrentText(h.get("issued_by", ""))
        self.delivered_by.setCurrentText(h.get("delivered_by", ""))
        self.handover_to.setText(h.get("handover_to", ""))
        self.handover_id.setText(h.get("handover_id", ""))
        self.handover_phone.setText(h.get("handover_phone", ""))
        self.received_by.setText(h.get("received_by", ""))
        self.remarks.setText(h.get("remarks", ""))
        self.terms.setText(h.get("terms", ""))
        self.chk_values.setChecked(bool(h.get("show_values")))
        self.table.set_lines(lines)
        self._recalc()

    def reset(self):
        self.edit_id = None
        self.doc_no.setText("<i>assigned when saved</i>")
        self.attachments = []
        self._refresh_attachments()
        for wd in (self.to_party, self.to_address, self.reference, self.vehicle,
                   self.purpose, self.handover_to, self.handover_id,
                   self.handover_phone, self.received_by, self.remarks, self.terms):
            wd.clear()
        self.title.setText("DELIVERY NOTE")
        self.date.setDate(QDate.currentDate())
        self.table.clear_lines()
        self._recalc()

    def _save(self, preview: bool = False):
        lines = self.table.lines()
        if not lines:
            W.error_box(self, "Add at least one line before saving.")
            return
        h = self.header()
        if self.edit_id:
            h["_edit"] = True
        try:
            doc_id, doc_no = G.save(self.db, h, lines, self.edit_id)
            self._register_attachments(doc_no)
            f = D.general_dn_pdf(self.db, doc_id)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not create the delivery note.\n\n{exc}")
            return
        self.edit_id = doc_id
        self.last_file = f
        self.doc_no.setText(f"<b>{doc_no}</b>")
        self.saved.emit()
        W.toast(self, f"{doc_no} created — {f.name}")
        D.open_path(f)
        if not preview:
            self.reset()

    def _save_template(self):
        name, ok = QInputDialog.getText(self, "Save as template",
                                        "Name for this template:")
        if not ok or not name.strip():
            return
        G.save_template(self.db, name.strip(), self.header(), self.table.lines())
        self.reload_templates()
        W.toast(self, f"Template '{name.strip()}' saved.")

    def _load_template(self):
        name = self.cb_template.currentText()
        h, lines = G.load_template(self.db, name)
        if not h and not lines:
            W.error_box(self, "Select a saved template first.")
            return
        self.edit_id = None
        self.doc_no.setText("<i>assigned when saved</i>")
        self.title.setText(h.get("title", "DELIVERY NOTE"))
        self.frm.setCurrentText(h.get("from_location", ""))
        self.to_party.setText(h.get("to_party", ""))
        self.to_address.setText(h.get("to_address", ""))
        self.project.setCurrentText(h.get("project", ""))
        self.purpose.setText(h.get("purpose", ""))
        self.issued_by.setCurrentText(h.get("issued_by", ""))
        self.delivered_by.setCurrentText(h.get("delivered_by", ""))
        self.terms.setText(h.get("terms", ""))
        self.chk_values.setChecked(str(h.get("show_values", 0)) in ("1", "True"))
        self.table.set_lines(lines)
        self.date.setDate(QDate.currentDate())
        self._recalc()
        W.toast(self, f"Template '{name}' loaded — the date was reset to today.")


class SavedTab(QWidget):
    openNote = Signal(int)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.rows: list[dict] = []
        self.last_file: Path | None = None
        self.attachments: list[dict[str, object] | str] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search number, party, project, reference, vehicle, "
                                  "driver...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 2)
        self.d_from = date_edit()
        self.d_from.setDate(QDate.currentDate().addYears(-2))
        self.d_to = date_edit()
        self.d_to.setDate(QDate.currentDate().addYears(1))
        for wd in (self.d_from, self.d_to):
            wd.dateChanged.connect(self.reload)
        self.f_status = W.combo(["All Status", "FINAL", "DRAFT", "CANCELLED"])
        self.f_status.currentTextChanged.connect(self.reload)
        bar.addWidget(QLabel("From:"))
        bar.addWidget(self.d_from)
        bar.addWidget(QLabel("To:"))
        bar.addWidget(self.d_to)
        bar.addWidget(self.f_status)
        v.addLayout(bar)

        btns = QHBoxLayout()
        btns.addWidget(W.button("📄  Reprint PDF", "Primary", self._pdf))
        btns.addWidget(W.button("✏  Open for Editing", slot=self._edit))
        btns.addWidget(W.button("⧉  Duplicate", slot=self._duplicate))
        btns.addWidget(W.button("🚫  Cancel Note", slot=self._cancel))
        btns.addWidget(W.button("🗑  Delete", slot=self._delete))
        btns.addWidget(W.button("📊  Export List", slot=self._export))
        btns.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        btns.addWidget(self.count)
        v.addLayout(btns)

        self.table = W.DataTable()
        self.table.doubleClicked.connect(self._pdf)
        v.addWidget(self.table, 1)
        v.addWidget(ShareBar(db, lambda: self.last_file, self))
        self.reload()

    def reload(self):
        st = "" if self.f_status.currentIndex() <= 0 else self.f_status.currentText()
        self.rows = G.listing(self.db, self.search.text(), iso(self.d_from),
                              iso(self.d_to), st)
        self.table.fill(
            ["ID", "DN Number", "Date", "Title", "Deliver To", "Project", "Vehicle",
             "Driver / Handover", "Lines", "Quantity", "Reference", "Status"],
            [[r["id"], r["doc_no"], r["doc_date"], r.get("title", ""),
              r.get("to_party", ""), r.get("project", ""), r.get("vehicle", ""),
              r.get("handover_to", ""), r.get("lines", 0),
              round(r.get("qty", 0) or 0, 2), r.get("reference", ""),
              r.get("status", "")] for r in self.rows])
        self.table.setColumnHidden(0, True)
        self.count.setText(f"{len(self.rows)} general delivery note(s)")

    def _sel(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0:
            W.error_box(self, "Select a delivery note from the list first.")
            return None
        did = int(self.table.item(r, 0).text())
        hit = next((x for x in self.rows if x["id"] == did), None)
        if hit is None:                       # cache stale -> read the database again
            self.reload()
            hit = next((x for x in self.rows if x["id"] == did), None)
        return hit

    def _pdf(self):
        d = self._sel()
        if not d:
            return
        try:
            f = D.general_dn_pdf(self.db, d["id"])
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not build the PDF.\n\n{exc}")
            return
        self.last_file = f
        W.toast(self, f"{d['doc_no']} — {f.name}")
        D.open_path(f)

    def _edit(self):
        d = self._sel()
        if d:
            self.openNote.emit(int(d["id"]))

    def _duplicate(self):
        d = self._sel()
        if not d:
            return
        try:
            _, no = G.duplicate(self.db, d["id"])
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.reload()
        W.toast(self, f"Copied to {no}.")

    def _cancel(self):
        d = self._sel()
        if not d:
            return
        reason, ok = QInputDialog.getText(self, "Cancel delivery note", "Reason:")
        if not ok:
            return
        G.cancel(self.db, d["id"], reason.strip())
        self.reload()
        W.toast(self, f"{d['doc_no']} cancelled.")

    def _delete(self):
        d = self._sel()
        if not d:
            return
        if not W.confirm(self, f"Permanently delete {d['doc_no']}?\n\nThis general "
                               "delivery note has no stock effect, so nothing else "
                               "changes."):
            return
        G.delete(self.db, d["id"])
        self.reload()
        W.toast(self, "Deleted.")

    def _export(self):
        cols = self.table.headers()[1:]
        rows = [r[1:] for r in self.table.all_rows()]
        f = D.export_excel(self.db, "General Delivery Notes", cols, rows)
        self.last_file = f
        W.toast(self, f"Exported: {f.name}")
        D.open_path(f)


class GeneralDNPage(QWidget):
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        G.ensure_schema(db)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)

        banner = QLabel(
            "🧾  <b>General Delivery Note Maker</b> — produces a fully branded "
            "delivery note for anything that is not a stocked item. Numbers come "
            "from their own <b>GDN</b> series and <b>no stock movement is ever "
            "posted</b>.")
        banner.setWordWrap(True)
        banner.setStyleSheet("background:#0b7285; color:white; border-radius:7px;"
                             "padding:8px 12px;")
        v.addWidget(banner)

        self.tabs = QTabWidget()
        self.create = CreateTab(db)
        self.saved = SavedTab(db)
        self.tabs.addTab(self.create, "✍  Create Delivery Note")
        self.tabs.addTab(self.saved, "🗂  Saved Notes")
        v.addWidget(self.tabs, 1)

        self.create.saved.connect(self.saved.reload)
        self.create.saved.connect(self.dataChanged)
        self.saved.openNote.connect(self._open)

    def _open(self, doc_id: int):
        self.create.load(doc_id)
        self.tabs.setCurrentIndex(0)

    def refresh(self):
        self.saved.reload()
        self.create.reload_templates()
