"""Employee PPE register: manual issue + sync shoes/blankets/FRC/coveralls from DNs."""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import employee_ppe as P
from ..core.database import Database
from . import widgets as W
from .common import ShareBar, date_edit, iso


class IssueDialog(QDialog):
    def __init__(self, pdb: P.PPEIssueDB, record_id: int | None = None, parent=None, preset: dict | None = None):
        super().__init__(parent)
        self.pdb = pdb
        self.record_id = record_id
        self.row = P.get_record(pdb, record_id) if record_id else (preset or {})
        self.setWindowTitle("Employee PPE Register — " + ("Edit Record" if record_id else "New Issue"))
        self.resize(680, 520)
        v = QVBoxLayout(self)

        f = QFormLayout()
        g = self.row.get
        self.issue_date = date_edit(str(g("issue_date", "") or None) or None)
        self.employee_code = QLineEdit(str(g("employee_code", "") or ""))
        self.employee_name = QLineEdit(str(g("employee_name", "") or ""))
        self.department = QLineEdit(str(g("department", "") or ""))
        self.project = QLineEdit(str(g("project", "") or ""))
        self.item_group = W.combo(P.GROUPS, editable=False, current=str(g("item_group", "") or P.GROUP_OTHER))
        self.item_code = QLineEdit(str(g("item_code", "") or ""))
        self.item_desc = QLineEdit(str(g("item_desc", "") or ""))
        self.size_text = QLineEdit(str(g("size_text", "") or ""))
        self.qty = QDoubleSpinBox(); self.qty.setRange(0, 1e9); self.qty.setDecimals(2); self.qty.setValue(float(g("qty", 1) or 1))
        self.uom = W.combo(["PAIR", "PCS", "SET", "EA", "NOS", "BOX", "PACK"], editable=True,
                           current=str(g("uom", "") or "PCS"))
        self.dn_no = QLineEdit(str(g("dn_no", "") or ""))
        self.status = W.combo(P.STATUSES, editable=False, current=str(g("status", "") or P.ST_ISSUED))
        self.returned = QCheckBox("Returned on")
        self.return_date = date_edit(str(g("return_date", "") or None) or None)
        self.returned.setChecked(bool(g("return_date")) or str(g("status", "")) == P.ST_RETURNED)
        self.return_date.setEnabled(self.returned.isChecked())
        self.returned.toggled.connect(self.return_date.setEnabled)
        rr = QWidget(); rr_l = QHBoxLayout(rr); rr_l.setContentsMargins(0, 0, 0, 0); rr_l.addWidget(self.returned); rr_l.addWidget(self.return_date, 1)
        self.remarks = QPlainTextEdit(str(g("remarks", "") or "")); self.remarks.setMaximumHeight(90)
        for lbl, wd in (("Issue Date", self.issue_date), ("Employee Code", self.employee_code),
                        ("Employee Name", self.employee_name), ("Department", self.department),
                        ("Project / Site", self.project), ("Item Group", self.item_group),
                        ("Item Code", self.item_code), ("Description", self.item_desc),
                        ("Size", self.size_text), ("Qty", self.qty), ("UOM", self.uom),
                        ("Delivery Note No.", self.dn_no), ("Status", self.status), ("Return", rr),
                        ("Remarks", self.remarks)):
            f.addRow(lbl, wd)
        v.addLayout(f)

        note = QLabel("Tip: for synced Delivery Note records you can complete or correct the employee code and name here.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _save(self):
        if not self.item_desc.text().strip():
            W.error_box(self, "Item description is required.")
            return
        data = {
            "issue_date": iso(self.issue_date),
            "employee_code": self.employee_code.text().strip(),
            "employee_name": self.employee_name.text().strip(),
            "department": self.department.text().strip(),
            "project": self.project.text().strip(),
            "item_group": self.item_group.currentText(),
            "item_code": self.item_code.text().strip(),
            "item_desc": self.item_desc.text().strip(),
            "size_text": self.size_text.text().strip() or P.detect_size(self.item_desc.text()),
            "qty": self.qty.value(),
            "uom": self.uom.currentText().strip(),
            "dn_no": self.dn_no.text().strip(),
            "doc_date": self.row.get("doc_date", "") or iso(self.issue_date),
            "pdf_path": self.row.get("pdf_path", "") or "",
            "source_type": self.row.get("source_type", "MANUAL") or "MANUAL",
            "source_doc_id": self.row.get("source_doc_id"),
            "source_line_id": self.row.get("source_line_id"),
            "status": P.ST_RETURNED if self.returned.isChecked() else self.status.currentText(),
            "return_date": iso(self.return_date) if self.returned.isChecked() else "",
            "issued_by": self.row.get("issued_by", self.pdb.current_user),
            "remarks": self.remarks.toPlainText().strip(),
        }
        try:
            P.save_record(self.pdb, data, self.record_id)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.accept()


class EmployeePPEPage(QWidget):
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.pdb = P.get_db(getattr(db, "current_user", "admin"))
        self.records: list[dict] = []
        self.candidates: list[dict] = []
        self.last_file: Path | None = None
        self.setObjectName("Page")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._dashboard_tab(), "📊 Dashboard")
        self.tabs.addTab(self._register_tab(), "📋 Register")
        self.tabs.addTab(self._sync_tab(), "🔄 Sync from Delivery Notes")
        self.tabs.addTab(self._reports_tab(), "📈 Reports")
        v.addWidget(self.tabs, 1)
        v.addWidget(ShareBar(db, lambda: self.last_file, self))
        self.refresh_all()

    def _ensure_user(self):
        self.pdb.current_user = getattr(self.db, "current_user", "admin") or "admin"

    def _dashboard_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        cards = QGridLayout()
        self.k_total = QLabel(); self.k_emp = QLabel(); self.k_sync = QLabel(); self.k_missing = QLabel()
        for i, (title, lab, color) in enumerate((
                ("Total Records", self.k_total, "#0b3d6b"),
                ("Employees", self.k_emp, "#1a7f37"),
                ("Synced from DNs", self.k_sync, "#7048e8"),
                ("Missing Employee Info", self.k_missing, "#c92a2a"))):
            box = QGroupBox(title)
            l = QVBoxLayout(box)
            lab.setStyleSheet(f"font-size:24px;font-weight:700;color:{color}")
            l.addWidget(lab)
            cards.addWidget(box, 0, i)
        v.addLayout(cards)
        self.t_dash = W.DataTable()
        v.addWidget(QLabel("Latest PPE / welfare issues"))
        v.addWidget(self.t_dash, 1)
        return w

    def _register_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.f_text = W.SearchBox("Search employee code, employee, item, DN, project...")
        self.f_text.textChanged.connect(self.reload_register)
        self.f_group = W.combo(["All Groups"] + P.GROUPS)
        self.f_group.currentTextChanged.connect(self.reload_register)
        self.f_status = W.combo(["All Status"] + P.STATUSES)
        self.f_status.currentTextChanged.connect(self.reload_register)
        self.f_source = W.combo(["All Sources", "MANUAL", "DN"])
        self.f_source.currentTextChanged.connect(self.reload_register)
        self.d_from = date_edit(); self.d_from.setDate(self.d_from.date().addYears(-1)); self.d_from.dateChanged.connect(self.reload_register)
        self.d_to = date_edit(); self.d_to.dateChanged.connect(self.reload_register)
        for wdg in (QLabel("From:"), self.d_from, QLabel("To:"), self.d_to, QLabel("Group:"), self.f_group,
                    QLabel("Status:"), self.f_status, QLabel("Source:"), self.f_source):
            bar.addWidget(wdg)
        bar.addWidget(self.f_text, 1)
        v.addLayout(bar)
        act = QHBoxLayout()
        act.addWidget(W.button("➕  New Manual Issue", "Primary", self.new_issue))
        act.addWidget(W.button("✏  Edit Record", slot=self.edit_issue))
        act.addWidget(W.button("↩  Mark Returned", slot=self.mark_returned))
        act.addWidget(W.button("🗑  Delete Record", slot=self.delete_record))
        act.addWidget(W.button("📄  Open Source PDF", slot=self.open_pdf))
        act.addWidget(W.button("🔄  Refresh", slot=self.refresh_all))
        act.addStretch(1)
        v.addLayout(act)
        self.t_reg = W.DataTable()
        self.t_reg.doubleClicked.connect(self.edit_issue)
        v.addWidget(self.t_reg, 1)
        self.lbl_reg = QLabel(); self.lbl_reg.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(self.lbl_reg)
        return w

    def _sync_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.s_from = date_edit(); self.s_from.setDate(self.s_from.date().addYears(-1))
        self.s_to = date_edit()
        self.s_text = W.SearchBox("Preview matching shoes, blankets, FRCs and coveralls from Delivery Notes...")
        bar.addWidget(QLabel("From:")); bar.addWidget(self.s_from)
        bar.addWidget(QLabel("To:")); bar.addWidget(self.s_to)
        bar.addWidget(self.s_text, 1)
        bar.addWidget(W.button("Preview Matches", "Primary", self.preview_sync))
        bar.addWidget(W.button("Import All New Records", "Accent", self.import_sync))
        v.addLayout(bar)
        self.t_sync = W.DataTable()
        self.t_sync.doubleClicked.connect(self.open_sync_pdf)
        v.addWidget(self.t_sync, 1)
        note = QLabel("This tab reads FINAL Delivery Notes and detects PPE / welfare items by item description, code and category. Already-imported lines are skipped safely.")
        note.setWordWrap(True); note.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(note)
        return w

    def _reports_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.r_name = W.combo(P.REPORT_LIST)
        self.r_text = W.SearchBox("Optional report filter...")
        self.r_group = W.combo(["All Groups"] + P.GROUPS)
        self.r_status = W.combo(["All Status"] + P.STATUSES)
        self.r_source = W.combo(["All Sources", "MANUAL", "DN"])
        self.r_from = date_edit(); self.r_from.setDate(self.r_from.date().addYears(-1))
        self.r_to = date_edit()
        bar.addWidget(QLabel("Report:")); bar.addWidget(self.r_name)
        bar.addWidget(QLabel("Group:")); bar.addWidget(self.r_group)
        bar.addWidget(QLabel("Status:")); bar.addWidget(self.r_status)
        bar.addWidget(QLabel("Source:")); bar.addWidget(self.r_source)
        bar.addWidget(QLabel("From:")); bar.addWidget(self.r_from)
        bar.addWidget(QLabel("To:")); bar.addWidget(self.r_to)
        bar.addWidget(self.r_text, 1)
        bar.addWidget(W.button("Run", "Primary", self.run_report))
        v.addLayout(bar)
        act = QHBoxLayout()
        act.addWidget(W.button("📄  PDF", slot=lambda: self.export_report("pdf")))
        act.addWidget(W.button("📊  Excel", slot=lambda: self.export_report("xlsx")))
        act.addWidget(W.button("🧾  CSV", slot=lambda: self.export_report("csv")))
        act.addStretch(1)
        self.lbl_rep = QLabel(); self.lbl_rep.setStyleSheet(f"color:{W.MUTED};")
        act.addWidget(self.lbl_rep)
        v.addLayout(act)
        self.t_rep = W.DataTable()
        v.addWidget(self.t_rep, 1)
        return w

    def refresh_all(self):
        self._ensure_user()
        self.reload_register()
        self.preview_sync()
        self.reload_dashboard()
        self.run_report()

    def reload_dashboard(self):
        d = P.dashboard_data(self.pdb)
        self.k_total.setText(str(d["total_records"]))
        self.k_emp.setText(str(d["employees"]))
        self.k_sync.setText(str(d["synced"]))
        self.k_missing.setText(str(d["missing_info"]))
        recent = d.get("recent", [])
        self.t_dash.fill(["Date", "Employee Code", "Employee", "Group", "Description", "Qty", "DN", "Status"],
                         [[r["issue_date"], r["employee_code"], r["employee_name"], r["item_group"],
                           r["item_desc"], round(float(r["qty"] or 0), 2), r["dn_no"], r["status"]]
                          for r in recent])

    def _filters(self) -> dict[str, str]:
        return {
            "text": self.f_text.text().strip(),
            "item_group": "" if self.f_group.currentIndex() == 0 else self.f_group.currentText(),
            "status": "" if self.f_status.currentIndex() == 0 else self.f_status.currentText(),
            "source_type": "" if self.f_source.currentIndex() == 0 else self.f_source.currentText(),
            "date_from": iso(self.d_from),
            "date_to": iso(self.d_to),
        }

    def reload_register(self):
        self._ensure_user()
        self.records = P.list_records(self.pdb, **self._filters())
        self.t_reg.fill(["Issue No", "Date", "Employee Code", "Employee", "Project / Dept", "Group",
                         "Item Code", "Description", "Size", "Qty", "UOM", "DN", "Source", "Status"],
                        [[r["issue_no"], r["issue_date"], r["employee_code"], r["employee_name"],
                          r["project"] or r["department"], r["item_group"], r["item_code"],
                          r["item_desc"], r["size_text"], round(float(r["qty"] or 0), 2), r["uom"],
                          r["dn_no"], r["source_type"], r["status"]] for r in self.records])
        self.lbl_reg.setText(f"{len(self.records)} record(s)")

    def _sel_record(self) -> dict | None:
        r = self.t_reg.currentRow()
        if r < 0 or r >= len(self.records):
            W.error_box(self, "Select a record first.")
            return None
        return self.records[r]

    def new_issue(self):
        if IssueDialog(self.pdb, parent=self).exec() == QDialog.Accepted:
            self.refresh_all()
            self.dataChanged.emit()

    def edit_issue(self):
        row = self._sel_record()
        if not row:
            return
        if IssueDialog(self.pdb, row["id"], self).exec() == QDialog.Accepted:
            self.refresh_all()
            self.dataChanged.emit()

    def mark_returned(self):
        row = self._sel_record()
        if not row:
            return
        if not W.confirm(self, f"Mark {row['issue_no']} as returned?"):
            return
        P.mark_returned(self.pdb, row["id"])
        self.refresh_all()
        self.dataChanged.emit()

    def delete_record(self):
        row = self._sel_record()
        if not row:
            return
        if not W.confirm(self, f"Delete PPE record {row['issue_no']}?"):
            return
        P.delete_record(self.pdb, row["id"])
        self.refresh_all()
        self.dataChanged.emit()

    def open_pdf(self):
        row = self._sel_record()
        if not row:
            return
        p = Path(row.get("pdf_path") or "")
        if p.exists():
            D.open_path(p)
        elif row.get("dn_no"):
            doc = self.db.one("SELECT id FROM documents WHERE doc_type='DN' AND doc_no=?", (row["dn_no"],))
            if doc:
                D.open_path(D.document_pdf(self.db, doc["id"]))
        else:
            W.error_box(self, "No source PDF is linked to this record.")

    def preview_sync(self):
        self._ensure_user()
        self.candidates = P.sync_candidates(self.db, self.pdb, iso(self.s_from), iso(self.s_to), self.s_text.text().strip())
        self.t_sync.fill(["DN No", "Date", "Employee Code", "Employee", "Group", "Item Code",
                          "Description", "Size", "Qty", "Imported", "Status"],
                         [[r["doc_no"], r["doc_date"], r["employee_code"], r["employee_name"],
                           r["item_group"], r["item_code"], r["item_desc"], r["size_text"],
                           round(float(r["qty"] or 0), 2), "Yes" if r["imported"] else "No", r["status"]]
                          for r in self.candidates])

    def import_sync(self):
        self._ensure_user()
        ins, skipped = P.import_from_delivery_notes(self.db, self.pdb, iso(self.s_from), iso(self.s_to), self.s_text.text().strip())
        self.refresh_all()
        self.dataChanged.emit()
        W.info_box(self, f"Imported {ins} PPE record(s).\nSkipped {skipped} already-synced line(s).")

    def open_sync_pdf(self):
        r = self.t_sync.currentRow()
        if r < 0 or r >= len(self.candidates):
            return
        cand = self.candidates[r]
        p = Path(cand.get("pdf_path") or "")
        if p.exists():
            D.open_path(p)
            return
        doc = self.db.one("SELECT id FROM documents WHERE id=?", (cand["doc_id"],))
        if doc:
            D.open_path(D.document_pdf(self.db, doc["id"]))

    def _report_filters(self) -> dict[str, str]:
        return {
            "text": self.r_text.text().strip(),
            "item_group": "" if self.r_group.currentIndex() == 0 else self.r_group.currentText(),
            "status": "" if self.r_status.currentIndex() == 0 else self.r_status.currentText(),
            "source_type": "" if self.r_source.currentIndex() == 0 else self.r_source.currentText(),
            "date_from": iso(self.r_from),
            "date_to": iso(self.r_to),
        }

    def run_report(self):
        title, cols, rows = P.build_report(self.pdb, self.r_name.currentText(), self._report_filters())
        self.rep_title, self.rep_cols, self.rep_rows = title, cols, rows
        self.t_rep.fill(cols, rows)
        self.lbl_rep.setText(f"{len(rows)} row(s)")

    def export_report(self, kind: str):
        self.run_report()
        fn = {"pdf": D.report_pdf, "xlsx": D.export_excel, "csv": D.export_csv}[kind]
        self.last_file = fn(self.db, self.rep_title, self.rep_cols, self.rep_rows)
        D.open_path(self.last_file)
