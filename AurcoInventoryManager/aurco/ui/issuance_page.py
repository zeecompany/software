"""COMPANY ISSUANCE REGISTER — UI.

Five tabs:
    📊 Dashboard   filterable KPI tiles + 8 charts, every tile drills through
    📋 Register    the sheet itself: issue, return, evidence, receipt
    📷 Evidence    photo gallery of every proof, with missing-proof chasing
    ⬆ Import      paste or load the existing Excel sheet
    📈 Reports     14 reports, PDF / Excel / CSV / share

Nothing here imports the stock engine.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPlainTextEdit, QScrollArea,
                               QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import issuance as I
from ..core.database import Database
from . import widgets as W
from .common import ShareBar, date_edit, iso


def _paint_status(table: W.DataTable, col: int) -> None:
    from PySide6.QtGui import QBrush, QColor
    for r in range(table.rowCount()):
        cell = table.item(r, col)
        if cell is None:
            continue
        c = I.STATUS_COLORS.get(cell.text())
        if c:
            cell.setForeground(QBrush(QColor(c)))
            f = cell.font()
            f.setBold(True)
            cell.setFont(f)


# ------------------------------------------------------------ evidence picker
class EvidenceStrip(QWidget):
    """Thumbnail strip with add / view / remove, used inside the editor."""

    def __init__(self, parent=None, title: str = "Photo proof"):
        super().__init__(parent)
        self.paths: list[str] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(QLabel(f"<b>{title}</b>"))
        row.addStretch(1)
        row.addWidget(W.button("📷  Add Picture...", "Primary", self._add))
        row.addWidget(W.button("🗑  Remove", slot=self._remove))
        v.addLayout(row)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(__import__("PySide6.QtCore", fromlist=["QSize"]
                                         ).QSize(104, 78))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMinimumHeight(108)
        self.list.setMaximumHeight(140)
        self.list.itemDoubleClicked.connect(self._open)
        v.addWidget(self.list)
        self.hint = QLabel("No picture attached yet.")
        self.hint.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        v.addWidget(self.hint)

    def _add(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select the proof picture(s)", "",
            "Pictures and PDF (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp "
            "*.pdf);;All files (*)")
        for f in files:
            self.add_path(f)

    def add_path(self, path: str):
        if path in self.paths:
            return
        self.paths.append(path)
        it = QListWidgetItem(Path(path).name[:22])
        pm = QPixmap(path)
        if not pm.isNull():
            it.setIcon(pm.scaled(104, 78, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        it.setData(Qt.UserRole, path)
        it.setToolTip(path)
        self.list.addItem(it)
        self._sync()

    def _remove(self):
        for it in self.list.selectedItems():
            p = it.data(Qt.UserRole)
            if p in self.paths:
                self.paths.remove(p)
            self.list.takeItem(self.list.row(it))
        self._sync()

    def _open(self, it):
        D.open_path(it.data(Qt.UserRole))

    def _sync(self):
        n = len(self.paths)
        self.hint.setText("No picture attached yet." if not n
                          else f"{n} file(s) will be copied into the register.")

    def clear(self):
        self.paths = []
        self.list.clear()
        self._sync()


# ------------------------------------------------------------------- editor
class IssueDialog(QDialog):
    def __init__(self, idb: I.IssuanceDB, issue_id: int | None = None, parent=None,
                 preset: dict | None = None):
        super().__init__(parent)
        self.idb = idb
        self.issue_id = issue_id
        self.row = I.get_issue(idb, issue_id) if issue_id else (preset or {})
        self.setWindowTitle("Company Issuance — "
                            + ("Edit Issue" if issue_id else "New Issue"))
        self.setModal(True)
        self.resize(880, 760)

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, 1)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        v.setSpacing(9)

        g = self.row.get
        g1 = QGroupBox("Who and what")
        f1 = QFormLayout(g1)
        self.record_date = date_edit(str(g("record_date", "") or "") or None)
        self.company = W.combo(I.distinct(idb, "company"), editable=True,
                               current=str(g("company", "") or ""))
        self.mr_no = QLineEdit(str(g("mr_no", "") or ""))
        self.recipient = W.combo(I.distinct(idb, "recipient"), editable=True,
                                 current=str(g("recipient", "") or ""))
        self.iqama = QLineEdit(str(g("iqama", "") or ""))
        self.iqama.setPlaceholderText("Iqama / ID number of the person taking custody")
        self.phone = QLineEdit(str(g("phone", "") or ""))
        self.item = W.combo(I.distinct(idb, "item"), editable=True,
                            current=str(g("item", "") or ""))
        self.item_code = QLineEdit(str(g("item_code", "") or ""))
        self.uom = W.combo(["", "No", "PCS", "SET", "MTR", "KG", "BOX"], editable=True,
                           current=str(g("uom", "") or ""))
        self.qty = QDoubleSpinBox()
        self.qty.setRange(0, 1e9)
        self.qty.setDecimals(2)
        self.qty.setValue(float(g("qty", 1) or 1))
        for lbl, wd in (("Date", self.record_date), ("Company Name", self.company),
                        ("MR (if any)", self.mr_no), ("Recipient", self.recipient),
                        ("Iqama ID", self.iqama), ("Phone", self.phone),
                        ("Item Issued", self.item), ("Item Code", self.item_code),
                        ("UOM", self.uom), ("Qty", self.qty)):
            f1.addRow(lbl, wd)
        v.addWidget(g1)

        g2 = QGroupBox("Issue terms")
        f2 = QFormLayout(g2)
        self.issue_type = W.combo(I.ISSUE_TYPES, current=str(g("issue_type", "")
                                                             or I.TEMPORARY))
        self.issue_type.currentTextChanged.connect(self._type_changed)
        self.issue_date = date_edit(str(g("issue_date", "") or "") or None)
        self.expected = date_edit(str(g("expected_return", "") or "") or None)
        self.chk_expected = QCheckBox("Expect it back by")
        self.chk_expected.setChecked(bool(g("expected_return")))
        self.chk_expected.toggled.connect(
            lambda on: self.expected.setEnabled(on))
        self.expected.setEnabled(self.chk_expected.isChecked())
        exp_row = QWidget()
        exl = QHBoxLayout(exp_row)
        exl.setContentsMargins(0, 0, 0, 0)
        exl.addWidget(self.chk_expected)
        exl.addWidget(self.expected, 1)
        self.condition_out = W.combo(I.CONDITIONS,
                                     current=str(g("condition_out", "") or ""))
        self.dn_no = QLineEdit(str(g("dn_no", "") or ""))
        self.dn_no.setPlaceholderText("DN / gate-pass number (counts as proof)")
        self.project = QLineEdit(str(g("project", "") or ""))
        self.location = QLineEdit(str(g("location", "") or ""))
        self.unit_value = QDoubleSpinBox()
        self.unit_value.setRange(0, 1e9)
        self.unit_value.setDecimals(2)
        self.unit_value.setValue(float(g("unit_value", 0) or 0))
        self.issued_by = QLineEdit(str(g("issued_by", "") or idb.current_user))
        for lbl, wd in (("Issue Type", self.issue_type),
                        ("Date of Issuance", self.issue_date),
                        ("Expected Return", exp_row),
                        ("Condition Out", self.condition_out),
                        ("DN / Gate Pass", self.dn_no), ("Project / Site", self.project),
                        ("Location", self.location), ("Unit Value", self.unit_value),
                        ("Issued By", self.issued_by)):
            f2.addRow(lbl, wd)
        v.addWidget(g2)

        g3 = QGroupBox("Return (fill in when the material comes back)")
        f3 = QFormLayout(g3)
        self.qty_returned = QDoubleSpinBox()
        self.qty_returned.setRange(0, 1e9)
        self.qty_returned.setDecimals(2)
        self.qty_returned.setValue(float(g("qty_returned", 0) or 0))
        self.return_date = date_edit(str(g("return_date", "") or "") or None)
        self.chk_returned = QCheckBox("Returned on")
        self.chk_returned.setChecked(bool(g("return_date")))
        self.chk_returned.toggled.connect(lambda on: self.return_date.setEnabled(on))
        self.return_date.setEnabled(self.chk_returned.isChecked())
        rr = QWidget()
        rrl = QHBoxLayout(rr)
        rrl.setContentsMargins(0, 0, 0, 0)
        rrl.addWidget(self.chk_returned)
        rrl.addWidget(self.return_date, 1)
        self.condition_in = W.combo(I.CONDITIONS, current=str(g("condition_in", "") or ""))
        self.received_back_by = QLineEdit(str(g("received_back_by", "") or ""))
        for lbl, wd in (("Qty Returned", self.qty_returned), ("Date of Return", rr),
                        ("Condition In", self.condition_in),
                        ("Received Back By", self.received_back_by)):
            f3.addRow(lbl, wd)
        v.addWidget(g3)

        self.remarks = QLineEdit(str(g("remarks", "") or ""))
        rg = QGroupBox("Remarks")
        rl = QVBoxLayout(rg)
        rl.addWidget(self.remarks)
        v.addWidget(rg)

        eg = QGroupBox("Evidence — a picture is required for every issuance")
        el = QVBoxLayout(eg)
        self.ev_issue = EvidenceStrip(title="Issue proof")
        el.addWidget(self.ev_issue)
        self.ev_return = EvidenceStrip(title="Return proof")
        el.addWidget(self.ev_return)
        if issue_id:
            have = I.evidence_for(idb, issue_id)
            if have:
                lbl = QLabel("Already stored: " + ", ".join(
                    f"{Path(e['file_path']).name} ({e['kind'].title()})"
                    for e in have[:6]))
                lbl.setWordWrap(True)
                lbl.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
                el.addWidget(lbl)
        v.addWidget(eg)
        v.addStretch(1)

        self._type_changed(self.issue_type.currentText())
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def _type_changed(self, text: str):
        perm = text == I.PERMANENT
        for wd in (self.chk_expected, self.expected, self.qty_returned,
                   self.chk_returned, self.return_date, self.condition_in,
                   self.received_back_by):
            wd.setEnabled(not perm)
        if perm:
            self.chk_expected.setChecked(False)
            self.chk_returned.setChecked(False)

    def _save(self):
        if not self.company.currentText().strip():
            W.error_box(self, "Enter the company the material is going to.")
            return
        if not self.item.currentText().strip():
            W.error_box(self, "Enter the item being issued.")
            return
        if self.qty.value() <= 0:
            W.error_box(self, "Quantity must be greater than zero.")
            return
        data = {
            "record_date": iso(self.record_date),
            "company": self.company.currentText().strip(),
            "mr_no": self.mr_no.text().strip(),
            "recipient": self.recipient.currentText().strip(),
            "iqama": self.iqama.text().strip(), "phone": self.phone.text().strip(),
            "item": self.item.currentText().strip(),
            "item_code": self.item_code.text().strip(),
            "uom": self.uom.currentText().strip(), "qty": self.qty.value(),
            "issue_type": self.issue_type.currentText(),
            "issue_date": iso(self.issue_date),
            "expected_return": (iso(self.expected)
                                if self.chk_expected.isChecked() else ""),
            "return_date": (iso(self.return_date)
                            if self.chk_returned.isChecked() else ""),
            "qty_returned": self.qty_returned.value(),
            "condition_out": self.condition_out.currentText(),
            "condition_in": self.condition_in.currentText(),
            "dn_no": self.dn_no.text().strip(), "project": self.project.text().strip(),
            "location": self.location.text().strip(),
            "unit_value": self.unit_value.value(),
            "issued_by": self.issued_by.text().strip(),
            "received_back_by": self.received_back_by.text().strip(),
            "remarks": self.remarks.text().strip(),
            "issue_no": self.row.get("issue_no", ""),
            "status": self.row.get("status", ""),
        }
        try:
            new_id = I.save_issue(self.idb, data, self.issue_id,
                                  evidence_files=self.ev_issue.paths)
        except ValueError as exc:
            W.error_box(self, str(exc))
            return
        for f in self.ev_return.paths:
            try:
                I.store_evidence(self.idb, new_id, f, "RETURN")
            except OSError:
                pass
        self.issue_id = new_id
        self.accept()


class ReturnDialog(QDialog):
    """Book a return, with its own photo proof."""

    def __init__(self, idb: I.IssuanceDB, rec: dict, parent=None):
        super().__init__(parent)
        self.idb = idb
        self.rec = rec
        self.setWindowTitle(f"Record Return — {rec['issue_no']}")
        self.setModal(True)
        self.resize(620, 520)
        v = QVBoxLayout(self)
        out = I.outstanding_qty(rec)
        head = QLabel(
            f"<b>{rec['item']}</b> issued to <b>{rec['company']}</b><br>"
            f"Recipient: {rec['recipient'] or '-'} &nbsp;·&nbsp; Issued "
            f"{rec['issue_date']} &nbsp;·&nbsp; "
            f"<b>{out:g}</b> of {I.to_float(rec['qty']):g} still outstanding")
        head.setWordWrap(True)
        v.addWidget(head)

        f = QFormLayout()
        self.qty = QDoubleSpinBox()
        self.qty.setRange(0.01, max(0.01, out))
        self.qty.setDecimals(2)
        self.qty.setValue(out)
        self.date = date_edit()
        self.condition = W.combo(I.CONDITIONS, current="Good")
        self.by = QLineEdit(idb.current_user)
        self.remarks = QLineEdit()
        for lbl, wd in (("Quantity returned", self.qty), ("Date of return", self.date),
                        ("Condition in", self.condition), ("Received back by", self.by),
                        ("Remarks", self.remarks)):
            f.addRow(lbl, wd)
        v.addLayout(f)

        self.ev = EvidenceStrip(title="Return proof picture")
        v.addWidget(self.ev)
        v.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("↩  Record Return")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _ok(self):
        try:
            I.record_return(self.idb, self.rec["id"], self.qty.value(),
                            iso(self.date), self.condition.currentText(),
                            self.by.text().strip(), self.remarks.text().strip(),
                            evidence_files=self.ev.paths)
        except ValueError as exc:
            W.error_box(self, str(exc))
            return
        self.accept()


# ---------------------------------------------------------------- register tab
class RegisterTab(QWidget):
    changed = Signal()

    def __init__(self, idb: I.IssuanceDB, db: Database, parent=None):
        super().__init__(parent)
        self.idb = idb
        self.db = db
        self.rows: list[dict] = []
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search item, company, recipient, Iqama, MR, "
                                  "DN, remarks...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 3)
        self.f_company = W.combo(["All Companies"])
        self.f_recipient = W.combo(["All Recipients"])
        self.f_status = W.combo(["All Status"] + I.STATUSES)
        self.f_type = W.combo(["All Types"] + I.ISSUE_TYPES)
        for c in (self.f_company, self.f_recipient, self.f_status, self.f_type):
            c.currentTextChanged.connect(self.reload)
            bar.addWidget(c)
        v.addLayout(bar)

        bar2 = QHBoxLayout()
        self.chk_open = QCheckBox("Only outstanding")
        self.chk_overdue = QCheckBox("Only overdue")
        self.chk_noproof = QCheckBox("Only missing proof")
        for c in (self.chk_open, self.chk_overdue, self.chk_noproof):
            c.toggled.connect(self.reload)
            bar2.addWidget(c)
        self.chk_dates = QCheckBox("Filter by issue date")
        self.chk_dates.toggled.connect(self.reload)
        bar2.addWidget(self.chk_dates)
        self.d_from = date_edit()
        self.d_from.setDate(QDate.currentDate().addYears(-3))
        self.d_to = date_edit()
        self.d_to.setDate(QDate.currentDate().addYears(1))
        for wd in (self.d_from, self.d_to):
            wd.dateChanged.connect(self.reload)
            bar2.addWidget(wd)
        bar2.addStretch(1)
        v.addLayout(bar2)

        btns = QHBoxLayout()
        btns.addWidget(W.button("➕  New Issue", "Primary", self.new_issue))
        btns.addWidget(W.button("✏  Edit", slot=self.edit_issue))
        btns.addWidget(W.button("↩  Record Return", "Accent", self.do_return))
        btns.addWidget(W.button("📷  Add Picture", slot=self.add_photo))
        btns.addWidget(W.button("👁  View Evidence", slot=self.view_evidence))
        btns.addWidget(W.button("📄  Receipt PDF", slot=self.receipt))
        btns.addWidget(W.button("🚫  Write Off", slot=self.write_off))
        btns.addWidget(W.button("🗑  Delete", slot=self.delete_rows))
        btns.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        btns.addWidget(self.count)
        v.addLayout(btns)

        exp = QHBoxLayout()
        exp.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        exp.addWidget(W.button("📄  PDF", slot=lambda: self.export("pdf")))
        exp.addWidget(W.button("📑  CSV", slot=lambda: self.export("csv")))
        exp.addStretch(1)
        v.addLayout(exp)

        self.table = W.DataTable()
        self.table.doubleClicked.connect(self.edit_issue)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        v.addWidget(W.FilterBar(self.table))
        v.addWidget(self.table, 1)
        v.addWidget(ShareBar(db, lambda: self.last_file, self))
        self.reload_filters()
        self.reload()

    def reload_filters(self):
        for cb, col, first in ((self.f_company, "company", "All Companies"),
                               (self.f_recipient, "recipient", "All Recipients")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + I.distinct(self.idb, col))
            i = cb.findText(cur)
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)

    def filters(self) -> dict:
        return {
            "text": self.search.text(),
            "company": ("" if self.f_company.currentIndex() <= 0
                        else self.f_company.currentText()),
            "recipient": ("" if self.f_recipient.currentIndex() <= 0
                          else self.f_recipient.currentText()),
            "status": ("" if self.f_status.currentIndex() <= 0
                       else self.f_status.currentText()),
            "issue_type": ("" if self.f_type.currentIndex() <= 0
                           else self.f_type.currentText()),
            "date_from": iso(self.d_from) if self.chk_dates.isChecked() else "",
            "date_to": iso(self.d_to) if self.chk_dates.isChecked() else "",
            "only_open": self.chk_open.isChecked(),
            "only_overdue": self.chk_overdue.isChecked(),
            "missing_proof": self.chk_noproof.isChecked(),
        }

    def reload(self):
        I.refresh_statuses(self.idb)
        self.rows = I.search(self.idb, **self.filters())
        data = []
        for r in self.rows:
            n_out, n_in = I.evidence_counts(self.idb, r["id"])
            proof = f"📷 {n_out}" if n_out else (r["dn_no"] or "⚠ none")
            if n_in:
                proof += f" / ↩{n_in}"
            data.append([r["id"], r["issue_no"], r["record_date"], r["company"],
                         r["mr_no"], r["recipient"], r["iqama"], r["item"],
                         round(I.to_float(r["qty"]), 2), r["issue_date"],
                         r["expected_return"], r["return_date"],
                         round(I.to_float(r["qty_returned"]), 2),
                         round(I.outstanding_qty(r), 2), r["issue_type"], proof,
                         I.compute_status(r), r["remarks"]])
        self.table.fill(["ID", "Issue No", "Date", "Company", "MR", "Recipient",
                         "Iqama ID", "Item Issued", "Qty", "Date of Issuance",
                         "Expected Return", "Date of Return", "Returned", "Still Out",
                         "Type", "Evidence", "Status", "Remarks"], data)
        self.table.setColumnHidden(0, True)
        _paint_status(self.table, 16)
        qty = sum(I.to_float(r["qty"]) for r in self.rows)
        out = sum(I.outstanding_qty(r) for r in self.rows)
        noproof = sum(1 for r in self.rows
                      if I.evidence_counts(self.idb, r["id"])[0] == 0
                      and not str(r["dn_no"] or "").strip())
        self.count.setText(
            f"{len(self.rows)} issue(s) · {qty:,.2f} issued · {out:,.2f} still out"
            + (f" · ⚠ {noproof} without proof" if noproof else ""))

    def _sel_ids(self) -> list[int]:
        return sorted({int(self.table.item(i.row(), 0).text())
                       for i in self.table.selectedIndexes()
                       if self.table.item(i.row(), 0)})

    def _one(self) -> dict | None:
        ids = self._sel_ids()
        if not ids:
            W.error_box(self, "Select an issuance from the list first.")
            return None
        hit = next((r for r in self.rows if r["id"] == ids[0]), None)
        return hit or I.get_issue(self.idb, ids[0])

    def new_issue(self):
        preset = {"company": ("" if self.f_company.currentIndex() <= 0
                              else self.f_company.currentText())}
        dlg = IssueDialog(self.idb, None, self, preset)
        if dlg.exec() == QDialog.Accepted:
            self.reload_filters()
            self.reload()
            self.changed.emit()
            W.toast(self, "Issuance recorded with its photo proof.")

    def edit_issue(self):
        rec = self._one()
        if rec and IssueDialog(self.idb, rec["id"], self).exec() == QDialog.Accepted:
            self.reload_filters()
            self.reload()
            self.changed.emit()
            W.toast(self, "Issuance updated.")

    def do_return(self):
        rec = self._one()
        if not rec:
            return
        if rec["issue_type"] == I.PERMANENT:
            W.error_box(self, "This was issued permanently — there is nothing to "
                              "return.\n\nChange the type to Temporary first if that "
                              "was a mistake.")
            return
        if I.outstanding_qty(rec) <= 0:
            W.error_box(self, "Everything on this line has already been returned.")
            return
        if ReturnDialog(self.idb, rec, self).exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()
            W.toast(self, "Return recorded.")

    def add_photo(self):
        rec = self._one()
        if not rec:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, f"Add proof for {rec['issue_no']}", "",
            "Pictures and PDF (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp *.pdf)")
        if not files:
            return
        kind, ok = QInputDialog.getItem(self, "Evidence type", "This picture is:",
                                        ["Issue proof", "Return proof"], 0, False)
        if not ok:
            return
        k = "RETURN" if kind.startswith("Return") else "ISSUE"
        n = 0
        for f in files:
            try:
                I.store_evidence(self.idb, rec["id"], f, k)
                n += 1
            except OSError as exc:
                W.error_box(self, f"Could not copy {Path(f).name}\n\n{exc}")
        self.reload()
        self.changed.emit()
        W.toast(self, f"{n} picture(s) attached to {rec['issue_no']}.")

    def view_evidence(self):
        rec = self._one()
        if not rec:
            return
        ev = I.evidence_for(self.idb, rec["id"])
        if not ev:
            W.error_box(self, f"No evidence stored for {rec['issue_no']} yet.")
            return
        EvidenceViewer(self.idb, rec, self).exec()
        self.reload()

    def receipt(self):
        rec = self._one()
        if not rec:
            return
        try:
            f = D.issuance_receipt_pdf(self.idb, self.db, rec["id"])
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not build the receipt.\n\n{exc}")
            return
        self.last_file = f
        W.toast(self, f"Receipt: {f.name}")
        D.open_path(f)

    def write_off(self):
        rec = self._one()
        if not rec:
            return
        reason, ok = QInputDialog.getText(
            self, "Write off", f"Reason for writing off {rec['item']}:")
        if not ok:
            return
        I.mark_lost(self.idb, rec["id"], reason.strip())
        self.reload()
        self.changed.emit()
        W.toast(self, "Marked as lost / written off.")

    def delete_rows(self):
        ids = self._sel_ids()
        if not ids:
            W.error_box(self, "Select one or more rows first.")
            return
        if not W.confirm(self, f"Permanently delete {len(ids)} issuance record(s)?\n\n"
                               "Their evidence entries are removed too."):
            return
        also = W.confirm(self, "Also delete the stored picture files from disk?\n\n"
                               "Choose No to keep the photos in the Evidence folder.")
        I.delete_issues(self.idb, ids, remove_files=also)
        self.reload_filters()
        self.reload()
        self.changed.emit()
        W.toast(self, f"{len(ids)} record(s) deleted.")

    def _menu(self, pos):
        r = self.table.rowAt(pos.y())
        if r >= 0 and not self.table.selectedIndexes():
            self.table.selectRow(r)
        m = QMenu(self)
        m.addAction("✏  Edit", self.edit_issue)
        m.addAction("↩  Record Return", self.do_return)
        m.addSeparator()
        m.addAction("📷  Add Picture", self.add_photo)
        m.addAction("👁  View Evidence", self.view_evidence)
        m.addAction("📄  Receipt PDF", self.receipt)
        m.addSeparator()
        m.addAction("🚫  Write Off", self.write_off)
        m.addAction("🗑  Delete", self.delete_rows)
        m.addSeparator()
        m.addAction("🔄  Refresh", self.reload)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def export(self, kind: str):
        cols = self.table.headers()[1:]
        rows = [r[1:] for r in self.table.visible_rows()]
        title = "Company Issuance Register"
        folder = Path(D.config.folder(I.FOLDER))
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        if kind == "xlsx":
            f = D.export_excel(self.db, title, cols, rows,
                               folder / f"Issuance_Register_{stamp}.xlsx")
        elif kind == "csv":
            f = D.export_csv(self.db, title, cols, rows,
                             folder / f"Issuance_Register_{stamp}.csv")
        else:
            f = D.issuance_report_pdf(self.db, title, cols, rows,
                                      out_path=folder / f"Issuance_Register_{stamp}.pdf",
                                      subtitle=self._subtitle())
        self.last_file = f
        W.toast(self, f"Exported: {f.name}")
        D.open_path(f)

    def _subtitle(self) -> str:
        f = self.filters()
        bits = [f"{k.replace('_', ' ').title()}: {v}" for k, v in f.items()
                if v and not isinstance(v, bool)]
        for flag, lbl in (("only_open", "Only outstanding"),
                          ("only_overdue", "Only overdue"),
                          ("missing_proof", "Only missing proof")):
            if f.get(flag):
                bits.append(lbl)
        return "  ·  ".join(bits) or "All issuances"


class EvidenceViewer(QDialog):
    """Full-size look at the proof stored against one issuance."""

    def __init__(self, idb: I.IssuanceDB, rec: dict, parent=None):
        super().__init__(parent)
        self.idb = idb
        self.rec = rec
        self.setWindowTitle(f"Evidence — {rec['issue_no']}  ·  {rec['item']}")
        self.resize(960, 700)
        v = QVBoxLayout(self)
        head = QLabel(f"<b>{rec['item']}</b> · {rec['company']} · "
                      f"{rec['recipient'] or '-'} · issued {rec['issue_date']}")
        v.addWidget(head)
        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setMaximumWidth(280)
        self.list.currentRowChanged.connect(self._show)
        split.addWidget(self.list)
        self.view = QLabel("Select a picture")
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setStyleSheet("background:#f2f5f8; border:1px solid #d8e1ea;")
        self.view.setMinimumSize(560, 420)
        split.addWidget(self.view)
        split.setSizes([280, 680])
        v.addWidget(split, 1)
        row = QHBoxLayout()
        row.addWidget(W.button("📂  Open in Viewer", slot=self._open))
        row.addWidget(W.button("🗑  Remove Evidence", slot=self._remove))
        row.addStretch(1)
        row.addWidget(W.button("Close", slot=self.accept))
        v.addLayout(row)
        self._fill()

    def _fill(self):
        self.items = I.evidence_for(self.idb, self.rec["id"])
        self.list.clear()
        for e in self.items:
            p = Path(e["file_path"])
            it = QListWidgetItem(f"{e['kind'].title()} · {p.name[:28]}"
                                 + ("" if p.exists() else "  (missing)"))
            it.setData(Qt.UserRole, str(p))
            self.list.addItem(it)
        if self.items:
            self.list.setCurrentRow(0)
        else:
            self.view.setText("No evidence stored.")

    def _show(self, row: int):
        if not (0 <= row < len(self.items)):
            return
        p = Path(self.items[row]["file_path"])
        if not p.exists():
            self.view.setText(f"File is missing from disk:\n{p}")
            return
        if p.suffix.lower() == ".pdf":
            self.view.setText(f"PDF evidence:\n{p.name}\n\nUse Open in Viewer.")
            return
        pm = QPixmap(str(p))
        if pm.isNull():
            self.view.setText(f"Cannot display {p.name}")
            return
        self.view.setPixmap(pm.scaled(self.view.width() - 8, self.view.height() - 8,
                                      Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _open(self):
        r = self.list.currentRow()
        if 0 <= r < len(self.items):
            D.open_path(self.items[r]["file_path"])

    def _remove(self):
        r = self.list.currentRow()
        if not (0 <= r < len(self.items)):
            return
        if not W.confirm(self, "Remove this evidence from the record?"):
            return
        also = W.confirm(self, "Also delete the file from disk?")
        I.delete_evidence(self.idb, self.items[r]["id"], remove_file=also)
        self._fill()


# --------------------------------------------------------------- dashboard tab
class IssuanceDashboard(QWidget):
    """Interactive dashboard: filter bar, 16 KPI tiles, 8 charts, drill-through."""
    openRecords = Signal(dict)

    def __init__(self, idb: I.IssuanceDB, db: Database | None = None, parent=None):
        super().__init__(parent)
        self.idb = idb
        self.db = db
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        fbar = QWidget()
        fbar.setObjectName("Card")
        fl = QHBoxLayout(fbar)
        fl.setContentsMargins(10, 7, 10, 7)
        fl.setSpacing(7)
        self.f_text = W.SearchBox("Filter the whole dashboard...")
        self.f_text.textChanged.connect(self.refresh)
        fl.addWidget(self.f_text, 2)
        self.f_company = W.combo(["All Companies"])
        self.f_recipient = W.combo(["All Recipients"])
        self.f_status = W.combo(["All Status"] + I.STATUSES)
        self.f_type = W.combo(["All Types"] + I.ISSUE_TYPES)
        for c in (self.f_company, self.f_recipient, self.f_status, self.f_type):
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
                                  "Measure: Still Out", "Measure: Value"])
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
        specs = [("records", "Total Issues", "🗂", W.NAVY),
                 ("companies", "Companies", "🏢", "#14538f"),
                 ("recipients", "Recipients", "👤", "#7048e8"),
                 ("items", "Distinct Items", "🔧", "#0b7285"),
                 ("qty_issued", "Qty Issued", "Σ", W.GREEN),
                 ("qty_returned", "Qty Returned", "↩", "#1098ad"),
                 ("qty_out", "Still Out", "📦", "#e8590c"),
                 ("open_lines", "Open Lines", "⏳", W.AMBER),
                 ("overdue", "Overdue", "🔥", W.RED),
                 ("worst_overdue", "Worst Overdue (days)", "⚠", W.RED),
                 ("returned_lines", "Fully Returned", "✔", W.GREEN),
                 ("partial_lines", "Partially Returned", "◐", "#e0a300"),
                 ("permanent_lines", "Permanent Issues", "∞", "#7048e8"),
                 ("missing_proof", "Missing Photo Proof", "📷", W.RED),
                 ("proof_pct", "Proof Coverage %", "％", W.GREEN),
                 ("value_out", "Value Still Out", "💰", "#1a9c52")]
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
        c1 = W.Card("By Company")
        self.ch_company = W.BarChart(horizontal=True, color="#14538f")
        self.ch_company.barClicked.connect(lambda k: self._filter_to("company", k))
        c1.add(self.ch_company)
        r1.addWidget(c1, 2)
        c2 = W.Card("By Recipient (who is holding it)")
        self.ch_recipient = W.BarChart(horizontal=True, color="#7048e8")
        self.ch_recipient.barClicked.connect(lambda k: self._filter_to("recipient", k))
        c2.add(self.ch_recipient)
        r1.addWidget(c2, 2)
        v.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(12)
        c3 = W.Card("Most Issued Items")
        self.ch_items = W.BarChart(horizontal=True, color="#0b7285")
        c3.add(self.ch_items)
        r2.addWidget(c3, 2)
        c4 = W.Card("Issued vs Returned by Month")
        self.ch_io = W.GroupedBarChart()
        c4.add(self.ch_io)
        r2.addWidget(c4, 3)
        v.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(12)
        c5 = W.Card("Outstanding Ageing  (how long it has been out)")
        self.ch_age = W.BarChart(color="#e8590c")
        c5.add(self.ch_age)
        r3.addWidget(c5, 3)
        c6 = W.Card("Status")
        self.ch_status = W.DonutChart()
        c6.add(self.ch_status)
        r3.addWidget(c6, 2)
        v.addLayout(r3)

        r4 = QHBoxLayout()
        r4.setSpacing(12)
        c7 = W.Card("Evidence Coverage")
        self.ch_proof = W.DonutChart()
        c7.add(self.ch_proof)
        r4.addWidget(c7, 2)
        c8 = W.Card("⚠ Overdue — chase these first")
        self.tbl_overdue = W.DataTable()
        self.tbl_overdue.setMinimumHeight(210)
        c8.add(self.tbl_overdue, 1)
        c8.setMinimumHeight(250)
        r4.addWidget(c8, 4)
        v.addLayout(r4)

        c9 = W.Card("Latest issuances")
        self.recent = W.DataTable()
        self.recent.setMinimumHeight(230)
        c9.add(self.recent, 1)
        v.addWidget(c9)
        v.addStretch(1)
        self.reload_filters()
        self.refresh()

    def reload_filters(self):
        for cb, col, first in ((self.f_company, "company", "All Companies"),
                               (self.f_recipient, "recipient", "All Recipients")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + I.distinct(self.idb, col))
            i = cb.findText(cur)
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)

    def reset_filters(self):
        for wd in (self.f_company, self.f_recipient, self.f_status, self.f_type,
                   self.f_period, self.f_measure):
            wd.blockSignals(True)
            wd.setCurrentIndex(0)
            wd.blockSignals(False)
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
            "company": ("" if self.f_company.currentIndex() <= 0
                        else self.f_company.currentText()),
            "recipient": ("" if self.f_recipient.currentIndex() <= 0
                          else self.f_recipient.currentText()),
            "status": ("" if self.f_status.currentIndex() <= 0
                       else self.f_status.currentText()),
            "issue_type": ("" if self.f_type.currentIndex() <= 0
                           else self.f_type.currentText()),
            "date_from": d_from, "date_to": d_to,
            "only_open": self.f_open.isChecked(),
        }

    def _measure(self) -> str:
        return {"Measure: Quantity": "qty", "Measure: Line count": "count",
                "Measure: Still Out": "outstanding",
                "Measure: Value": "value"}[self.f_measure.currentText()]

    def _filter_to(self, field: str, value: str):
        cb = {"company": self.f_company, "recipient": self.f_recipient}.get(field)
        if cb is None:
            return
        i = cb.findText(value)
        cb.setCurrentIndex(i if i >= 0 else 0)

    def _drill(self, key: str):
        f = self.filters()
        if key in ("open_lines", "qty_out", "value_out"):
            f["only_open"] = True
        elif key in ("overdue", "worst_overdue"):
            f["only_overdue"] = True
        elif key == "returned_lines":
            f["status"] = I.ST_RETURNED
        elif key == "partial_lines":
            f["status"] = I.ST_PARTIAL
        elif key == "permanent_lines":
            f["issue_type"] = I.PERMANENT
        elif key in ("missing_proof", "proof_pct"):
            f["missing_proof"] = True
        self.openRecords.emit(f)

    def _export(self):
        f = self.filters()
        title, cols, rows = I.build_report(self.idb, "Full Issuance Register", f)
        d = I.dashboard(self.idb, f)
        stats = [("Issues", f"{d['records']:,}", "#12283f"),
                 ("Qty Issued", f"{d['qty_issued']:,.2f}", "#0f7b3d"),
                 ("Still Out", f"{d['qty_out']:,.2f}", "#9a6700"),
                 ("Overdue", f"{d['overdue']:,}", "#b3261e"),
                 ("No Proof", f"{d['missing_proof']:,}",
                  "#b3261e" if d["missing_proof"] else "#0f7b3d"),
                 ("Proof %", f"{d['proof_pct']:.0f}%", "#12283f")]
        bits = [f"{k.replace('_', ' ').title()}: {v}" for k, v in f.items() if v]
        out = Path(D.config.folder(I.FOLDER)) / (
            f"Issuance_Dashboard_{_dt.datetime.now():%Y%m%d_%H%M%S}.pdf")
        try:
            fp = D.issuance_report_pdf(
                self.db or self.window().db, "Company Issuance — Dashboard View",
                cols, rows, stats=stats, out_path=out,
                subtitle="  ·  ".join(bits) or "All issuances")
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not export the view.\n\n{exc}")
            return
        W.toast(self, f"Exported: {fp.name}")
        D.open_path(fp)

    def refresh(self):
        I.refresh_statuses(self.idb)
        f = self.filters()
        m = self._measure()
        d = I.dashboard(self.idb, f)
        for k, card in self.cards.items():
            val = d.get(k, 0)
            if k == "proof_pct":
                card.set_value(f"{val:.0f}%")
            elif k in ("value_out",):
                card.set_value(f"{val:,.0f}")
            elif isinstance(val, float):
                card.set_value(f"{val:,.2f}")
            else:
                card.set_value(f"{val:,}")
        self.cards["records"].lbl_sub.setText(
            f"{d['evidence_files']} evidence file(s) stored")
        self.cards["qty_out"].lbl_sub.setText(
            f"avg {d['avg_days_out']:.0f} days out")
        self.cards["missing_proof"].lbl_sub.setText(
            "every issue has proof" if not d["missing_proof"] else "needs a picture")

        self.ch_company.set_data(I.by_column(self.idb, "company", 10, m, f))
        self.ch_recipient.set_data(I.by_column(self.idb, "recipient", 10, m, f))
        self.ch_items.set_data(I.by_column(self.idb, "item", 10, m, f))
        self.ch_io.set_data(I.monthly_issue_return(self.idb, 8, f))
        self.ch_age.set_data(I.ageing(self.idb, f))
        self.ch_status.set_data([(k, v, I.STATUS_COLORS.get(k, "#868e96"))
                                 for k, v in I.status_split(self.idb, f)])
        have = max(0, d["records"] - d["missing_proof"])
        self.ch_proof.set_data([("With proof", have, W.GREEN),
                                ("No proof", d["missing_proof"], W.RED)])

        od = [r for r in I.search(self.idb, **f) if I.compute_status(r) == I.ST_OVERDUE]
        od.sort(key=lambda r: -I.days_overdue(r))
        self.tbl_overdue.fill(
            ["Issue No", "Company", "Recipient", "Item", "Still Out", "Was Due",
             "Days Overdue", "Phone"],
            [[r["issue_no"], r["company"], r["recipient"], r["item"],
              round(I.outstanding_qty(r), 2), r["expected_return"],
              I.days_overdue(r), r["phone"]] for r in od[:40]])

        rows = I.search(self.idb, **f)[:40]
        self.recent.fill(
            ["Issue No", "Date", "Company", "Recipient", "Item Issued", "Qty",
             "Still Out", "Type", "Proof", "Status"],
            [[r["issue_no"], r["issue_date"], r["company"], r["recipient"], r["item"],
              round(I.to_float(r["qty"]), 2), round(I.outstanding_qty(r), 2),
              r["issue_type"],
              ("📷 " + str(I.evidence_counts(self.idb, r["id"])[0]))
              if I.evidence_counts(self.idb, r["id"])[0] else (r["dn_no"] or "⚠"),
              I.compute_status(r)] for r in rows])
        _paint_status(self.recent, 9)


# ---------------------------------------------------------------- evidence tab
class EvidenceGalleryTab(QWidget):
    """Every stored proof in one place, plus the missing-proof chase list."""
    changed = Signal()

    def __init__(self, idb: I.IssuanceDB, parent=None):
        super().__init__(parent)
        self.idb = idb
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search company, recipient, item...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 2)
        self.f_kind = W.combo(["All evidence", "Issue proof", "Return proof"])
        self.f_kind.currentTextChanged.connect(self.reload)
        bar.addWidget(self.f_kind)
        self.chk_missing = QCheckBox("Show issues with NO proof")
        self.chk_missing.toggled.connect(self.reload)
        bar.addWidget(self.chk_missing)
        bar.addWidget(W.button("🔄  Refresh", slot=self.reload))
        bar.addWidget(W.button("📂  Open Evidence Folder", slot=self._folder))
        v.addLayout(bar)

        self.info = QLabel()
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        split = QSplitter(Qt.Horizontal)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.IconMode)
        from PySide6.QtCore import QSize
        self.gallery.setIconSize(QSize(150, 112))
        self.gallery.setResizeMode(QListWidget.Adjust)
        self.gallery.setSpacing(8)
        self.gallery.currentRowChanged.connect(self._show)
        self.gallery.itemDoubleClicked.connect(
            lambda it: D.open_path(it.data(Qt.UserRole)))
        split.addWidget(self.gallery)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        self.preview = QLabel("Select a picture")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(360, 300)
        self.preview.setStyleSheet("background:#f2f5f8; border:1px solid #d8e1ea;")
        rl.addWidget(self.preview, 1)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        rl.addWidget(self.caption)
        split.addWidget(right)
        split.setSizes([760, 420])
        v.addWidget(split, 1)
        self.reload()

    def _folder(self):
        D.open_path(I.evidence_root())

    def reload(self):
        needle = self.search.text().strip().lower()
        kind = {"Issue proof": "ISSUE", "Return proof": "RETURN"}.get(
            self.f_kind.currentText(), "")
        self.gallery.clear()
        self.entries: list[dict] = []
        if self.chk_missing.isChecked():
            bad = I.missing_evidence(self.idb)
            if needle:
                bad = [r for r in bad
                       if needle in f"{r['company']} {r['recipient']} {r['item']}".lower()]
            self.info.setText(
                f"<b style='color:{W.RED}'>{len(bad)} issuance(s) have no photo proof "
                "and no DN reference.</b>  Open the Register tab and use "
                "<b>Add Picture</b> to fix them."
                if bad else
                f"<b style='color:{W.GREEN}'>Every issuance has proof.</b>")
            for r in bad:
                it = QListWidgetItem(f"⚠ {r['issue_no']}\n{r['item'][:24]}\n"
                                     f"{r['company'][:20]}")
                it.setData(Qt.UserRole, "")
                it.setToolTip(f"{r['item']} to {r['company']} on {r['issue_date']}")
                self.gallery.addItem(it)
            self.preview.setText("No picture — this issuance needs proof.")
            return

        total = 0
        for r in I.search(self.idb):
            hay = f"{r['company']} {r['recipient']} {r['item']} {r['issue_no']}".lower()
            if needle and needle not in hay:
                continue
            for e in I.evidence_for(self.idb, r["id"], kind):
                p = Path(e["file_path"])
                total += 1
                it = QListWidgetItem(f"{r['issue_no']}\n{r['item'][:22]}\n"
                                     f"{e['kind'].title()}")
                if p.exists() and p.suffix.lower() in I.IMAGE_SUFFIXES:
                    pm = QPixmap(str(p))
                    if not pm.isNull():
                        it.setIcon(pm.scaled(150, 112, Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation))
                elif not p.exists():
                    it.setText(it.text() + "\n(missing)")
                it.setData(Qt.UserRole, str(p))
                it.setToolTip(f"{r['company']} · {r['recipient']}\n{p}")
                self.gallery.addItem(it)
                self.entries.append({"rec": r, "ev": e})
        self.info.setText(f"{total} evidence file(s) stored in "
                          f"<code>{I.evidence_root()}</code>")
        if total:
            self.gallery.setCurrentRow(0)
        else:
            self.preview.setText("No evidence matches the filter.")

    def _show(self, row: int):
        if not (0 <= row < len(getattr(self, "entries", []))):
            return
        ent = self.entries[row]
        p = Path(ent["ev"]["file_path"])
        r = ent["rec"]
        self.caption.setText(
            f"<b>{r['issue_no']}</b> · {r['item']} · {r['company']} · "
            f"{r['recipient'] or '-'}<br>{ent['ev']['kind'].title()} proof added "
            f"{ent['ev']['added_at']}<br><code>{p}</code>")
        if not p.exists():
            self.preview.setText(f"File is missing from disk:\n{p}")
            return
        if p.suffix.lower() == ".pdf":
            self.preview.setText(f"PDF evidence: {p.name}\n\nDouble-click to open.")
            return
        pm = QPixmap(str(p))
        if pm.isNull():
            self.preview.setText(f"Cannot display {p.name}")
            return
        self.preview.setPixmap(pm.scaled(self.preview.width() - 8,
                                         self.preview.height() - 8,
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation))


# ------------------------------------------------------------------ import tab
class IssuanceImportTab(QWidget):
    imported = Signal()

    def __init__(self, idb: I.IssuanceDB, db: Database, parent=None):
        super().__init__(parent)
        self.idb = idb
        self.db = db
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(10)

        card = W.Card("Bring your existing sheet in")
        cols, sample = I.template_rows()
        t = W.DataTable()
        t.fill(cols, sample)
        t.setMaximumHeight(130)
        card.add(t)
        note = QLabel(
            "Paste the rows straight from your Excel sheet, or load the file. The "
            "columns of your current sheet are recognised automatically — including "
            "<b>Receipient</b> and <b>Reamrks</b>. Dates like <b>21-Dec-25</b> are "
            "understood, and a Remarks cell saying <i>Returned</i> or <i>Not Return "
            "yet</i> sets the status. If the Evidence cell holds a file path the "
            "picture is imported; if it holds a DN number it is kept as the reference.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        card.add(note)
        row = QHBoxLayout()
        row.addWidget(W.button("📂  Load Excel / CSV...", "Primary", self._file))
        row.addWidget(W.button("⬇  Download Template", slot=self._template))
        row.addStretch(1)
        h = QWidget()
        h.setLayout(row)
        card.add(h)
        v.addWidget(card)

        pc = W.Card("Paste rows from Excel")
        self.paste = QPlainTextEdit()
        self.paste.setLineWrapMode(QPlainTextEdit.NoWrap)
        from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF
        _f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        _f.setPointSize(9)
        _f.setFixedPitch(True)
        self.paste.setFont(_f)
        self.paste.setTabStopDistance(QFontMetricsF(_f).horizontalAdvance(" ") * 14)
        self.paste.setMinimumHeight(170)
        self.paste.setPlaceholderText(
            "Date\tCompany Name\tMR (If any)\tReceipient\tIqama ID\tItem issued\t"
            "Qty\tDate of issuance\tDate of Return\tEvidence\tRemarks")
        pc.add(self.paste, 1)
        r2 = QHBoxLayout()
        r2.addWidget(W.button("✔  Read && Import", "Primary", self._paste_import))
        r2.addWidget(W.button("🧹  Clear", slot=self.paste.clear))
        r2.addStretch(1)
        h2 = QWidget()
        h2.setLayout(r2)
        pc.add(h2)
        v.addWidget(pc, 1)

        hc = W.Card("Import history — an import can be undone completely")
        self.hist = W.DataTable()
        hc.add(self.hist, 1)
        r3 = QHBoxLayout()
        r3.addWidget(W.button("↩  Undo Selected Import", slot=self._undo))
        r3.addWidget(W.button("🔄  Refresh", slot=self.reload))
        r3.addStretch(1)
        h3 = QWidget()
        h3.setLayout(r3)
        hc.add(h3)
        v.addWidget(hc, 1)
        self.reload()

    def reload(self):
        self.hist.fill(["Batch", "When", "Source", "Imported", "Skipped",
                        "Still present"],
                       [[b["id"], b["ts"], Path(str(b["source"])).name or b["source"],
                         b["rows"], b["skipped"], b["live"]]
                        for b in I.batches(self.idb)])

    def _template(self):
        cols, sample = I.template_rows()
        f = D.export_excel(self.db, "Company Issuance Template", cols, sample,
                           Path(D.config.folder(I.FOLDER)) / "Issuance_Template.xlsx",
                           totals=False)
        W.toast(self, f"Template saved: {f.name}")
        D.open_path(f)

    def _file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select the issuance sheet", "",
            "Spreadsheets and text (*.xlsx *.xlsm *.csv *.txt);;All files (*)")
        if not f:
            return
        try:
            headers, rows = I.read_file(f)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read that file.\n\n{exc}")
            return
        self._run(headers, rows, f)

    def _paste_import(self):
        txt = self.paste.toPlainText()
        if not txt.strip():
            W.error_box(self, "Paste the rows into the box first.")
            return
        headers, rows = I.sniff(txt)
        self._run(headers, rows, "pasted rows")

    def _run(self, headers, rows, source):
        if not rows:
            W.error_box(self, "No data rows were found.")
            return
        mapping = I.auto_map(headers)
        if not mapping:
            W.error_box(self, "None of the columns were recognised.\n\n"
                              "Make sure the heading row is included.")
            return
        recs = I.preview(headers, rows, mapping)
        if not recs:
            W.error_box(self, "No usable rows were found.")
            return
        known = ", ".join(sorted({I.LABELS.get(f, f) for f in mapping.values()
                                  if not f.startswith("_")}))
        if not W.confirm(self, f"{len(recs)} row(s) ready to import from "
                               f"{Path(str(source)).name}.\n\nRecognised columns:\n"
                               f"{known}\n\nImport now?"):
            return
        ins, sk = I.import_records(self.idb, recs, str(source))
        self.paste.clear()
        self.reload()
        self.imported.emit()
        W.info_box(self, f"{ins} issuance(s) imported."
                         + (f"\n{sk} duplicate row(s) skipped." if sk else "")
                         + "\n\nRows imported from a sheet keep whatever proof "
                           "reference they had; use the Register tab to attach "
                           "the actual pictures.", "Import complete")

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
        if not W.confirm(self, f"Remove the {live} record(s) from import #{bid}?"):
            return
        n = I.undo_batch(self.idb, bid)
        self.reload()
        self.imported.emit()
        W.toast(self, f"{n} record(s) removed.")


# ----------------------------------------------------------------- reports tab
class IssuanceReportsTab(QWidget):
    def __init__(self, idb: I.IssuanceDB, db: Database, parent=None):
        super().__init__(parent)
        self.idb = idb
        self.db = db
        self.last_file: Path | None = None
        self.cols: list[str] = []
        self.rows: list[list] = []
        self.title = ""
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)
        split = QSplitter(Qt.Horizontal)

        left = W.Card("Issuance Reports")
        self.list = QListWidget()
        for r in I.REPORT_LIST:
            self.list.addItem(QListWidgetItem("   " + r))
        self.list.currentItemChanged.connect(self.run)
        left.add(self.list)
        left.setMinimumWidth(250)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        filt = QHBoxLayout()
        self.f_text = W.SearchBox("Text filter...")
        self.f_text.returnPressed.connect(self.run)
        self.f_company = W.combo(["All Companies"])
        self.f_recipient = W.combo(["All Recipients"])
        for c in (self.f_company, self.f_recipient):
            c.currentTextChanged.connect(self.run)
        filt.addWidget(self.f_text, 1)
        filt.addWidget(self.f_company)
        filt.addWidget(self.f_recipient)
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
        rv.addWidget(W.FilterBar(self.table))
        rv.addWidget(self.table, 1)
        rv.addWidget(ShareBar(db, lambda: self.last_file, self))
        split.addWidget(right)
        split.setSizes([250, 980])
        v.addWidget(split, 1)
        self.reload_filters()
        self.list.setCurrentRow(0)

    def reload_filters(self):
        for cb, col, first in ((self.f_company, "company", "All Companies"),
                               (self.f_recipient, "recipient", "All Recipients")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + I.distinct(self.idb, col))
            i = cb.findText(cur)
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)

    def run(self, *_):
        it = self.list.currentItem()
        if it is None:
            return
        name = it.text().strip()
        f = {"text": self.f_text.text(),
             "company": ("" if self.f_company.currentIndex() <= 0
                         else self.f_company.currentText()),
             "recipient": ("" if self.f_recipient.currentIndex() <= 0
                           else self.f_recipient.currentText())}
        self.title, self.cols, self.rows = I.build_report(self.idb, name, f)
        self.table.fill(self.cols, self.rows)
        if "Status" in self.cols:
            _paint_status(self.table, self.cols.index("Status"))
        self.info.setText(f"{len(self.rows)} row(s)")

    def export(self, kind: str):
        if not self.cols:
            W.error_box(self, "Run a report first.")
            return
        title = f"Company Issuance — {self.title}"
        folder = Path(D.config.folder(I.FOLDER))
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = D.safe_name(self.title)
        if kind == "xlsx":
            f = D.export_excel(self.db, title, self.cols, self.rows,
                               folder / f"{base}_{stamp}.xlsx")
        elif kind == "csv":
            f = D.export_csv(self.db, title, self.cols, self.rows,
                             folder / f"{base}_{stamp}.csv")
        else:
            d = I.dashboard(self.idb)
            stats = [("Issues", f"{d['records']:,}", "#12283f"),
                     ("Still Out", f"{d['qty_out']:,.2f}", "#9a6700"),
                     ("Overdue", f"{d['overdue']:,}", "#b3261e"),
                     ("No Proof", f"{d['missing_proof']:,}",
                      "#b3261e" if d["missing_proof"] else "#0f7b3d")]
            f = D.issuance_report_pdf(
                self.db, title, self.cols, self.rows, stats=stats,
                out_path=folder / f"{base}_{stamp}.pdf",
                subtitle="Separate register — not part of the inventory stock ledger")
        self.last_file = f
        W.toast(self, f"Exported: {f.name}")
        D.open_path(f)


# ---------------------------------------------------------------------- page
class IssuancePage(QWidget):
    """Top-level page holding the five Company Issuance tabs."""
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.idb = I.get_issuance_db()
        self.idb.current_user = db.current_user

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)
        banner = QLabel(
            "🏢  <b>Company Issuance Register</b> — material issued to other "
            "companies, temporarily or permanently, with a photograph kept as proof "
            f"of every issue and every return. Its own database "
            f"(<code>{self.idb.path.name}</code>) and its own evidence folder. "
            "Nothing here affects inventory stock.")
        banner.setWordWrap(True)
        banner.setStyleSheet("background:#7048e8; color:white; border-radius:7px;"
                             "padding:8px 12px;")
        v.addWidget(banner)

        self.tabs = QTabWidget()
        self.dash = IssuanceDashboard(self.idb, db)
        self.register = RegisterTab(self.idb, db)
        self.evidence = EvidenceGalleryTab(self.idb)
        self.importer = IssuanceImportTab(self.idb, db)
        self.reports = IssuanceReportsTab(self.idb, db)
        self.tabs.addTab(self.dash, "📊  Dashboard")
        self.tabs.addTab(self.register, "📋  Issuance Register")
        self.tabs.addTab(self.evidence, "📷  Evidence")
        self.tabs.addTab(self.importer, "⬆  Import Sheet")
        self.tabs.addTab(self.reports, "📈  Reports")
        v.addWidget(self.tabs, 1)

        tools = QHBoxLayout()
        tools.addWidget(W.button("💾  Backup Register", slot=self._backup))
        tools.addWidget(W.button("♻  Restore...", slot=self._restore))
        tools.addWidget(W.button("📂  Open Data Folder", slot=self._folder))
        self.chk_require = QCheckBox("Require a picture for every new issue")
        self.chk_require.setChecked(self.idb.get_bool("require_evidence", True))
        self.chk_require.toggled.connect(
            lambda on: self.idb.set_setting("require_evidence", int(on)))
        tools.addWidget(self.chk_require)
        tools.addWidget(W.button("🔄  Refresh", slot=self.refresh))
        tools.addStretch(1)
        self.stat = QLabel()
        self.stat.setStyleSheet(f"color:{W.MUTED};")
        tools.addWidget(self.stat)
        v.addLayout(tools)

        self.register.changed.connect(self.refresh)
        self.importer.imported.connect(self.refresh)
        self.dash.openRecords.connect(self._drill_to_register)
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        self.refresh()

    def _drill_to_register(self, f: dict):
        r = self.register
        r.search.setText(f.get("text", ""))
        for cb, key in ((r.f_company, "company"), (r.f_recipient, "recipient"),
                        (r.f_status, "status"), (r.f_type, "issue_type")):
            cb.blockSignals(True)
            i = cb.findText(f.get(key) or "")
            cb.setCurrentIndex(i if (f.get(key) and i >= 0) else 0)
            cb.blockSignals(False)
        for chk, key in ((r.chk_open, "only_open"), (r.chk_overdue, "only_overdue"),
                         (r.chk_noproof, "missing_proof")):
            chk.blockSignals(True)
            chk.setChecked(bool(f.get(key)))
            chk.blockSignals(False)
        r.reload()
        self.tabs.setCurrentIndex(1)

    def refresh(self):
        try:
            I.refresh_statuses(self.idb)
            self.dash.reload_filters()
            self.dash.refresh()
            self.register.reload_filters()
            self.reports.reload_filters()
            d = I.dashboard(self.idb)
            self.stat.setText(
                f"{d['records']:,} issue(s) · {d['qty_out']:,.0f} still out · "
                f"{d['overdue']} overdue · {d['evidence_files']} photo(s) · "
                f"database: {self.idb.path}")
            self.dataChanged.emit()
        except Exception as exc:  # noqa: BLE001
            self.stat.setText(f"Company Issuance: {exc}")

    def _backup(self):
        f = self.idb.backup(note="manual backup")
        W.info_box(self, f"Backup created:\n\n{f}\n\nNote: this backs up the database. "
                         "The photographs live in the Evidence folder — copy that "
                         "folder too for a complete archive.", "Backup complete")

    def _restore(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select a Company Issuance backup", str(self.idb.path.parent),
            "Backups (*.db)")
        if not f:
            return
        if not W.confirm(self, "Replace the current issuance records with this "
                               "backup?\n\nA safety copy is taken first."):
            return
        try:
            self.idb.restore(f)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Restore failed.\n\n{exc}")
            return
        self.register.reload()
        self.importer.reload()
        self.evidence.reload()
        self.refresh()
        W.toast(self, "Register restored.")

    def _folder(self):
        D.open_path(self.idb.path.parent)
