"""Employee PPE register: manual issue + sync shoes/blankets/FRC/coveralls from DNs."""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QScrollArea, QTabWidget, QVBoxLayout, QWidget)

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
            "batch_id": self.row.get("batch_id"),
            "remarks": self.remarks.toPlainText().strip(),
        }
        try:
            P.save_record(self.pdb, data, self.record_id)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.accept()


class PPEImportTab(QWidget):
    imported = Signal()

    def __init__(self, pdb: P.PPEIssueDB, db: Database, parent=None):
        super().__init__(parent)
        self.pdb = pdb
        self.db = db
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(10)

        card = W.Card("Import PPE issues from Excel / CSV")
        cols, sample = P.template_rows()
        t = W.DataTable()
        t.fill(cols, sample)
        t.setMaximumHeight(130)
        card.add(t)
        note = QLabel(
            "Load your Excel / CSV sheet or paste rows from Excel. The module recognises "
            "common headings automatically: employee code, employee name, project, item code, "
            "description, size, qty, UOM, DN number, remarks and return date. If Item Group is "
            "missing, AURCO detects Shoes, Blanket, FRC and Coverall from the description."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        card.add(note)
        row = QHBoxLayout()
        row.addWidget(W.button("📂  Load Excel / CSV...", "Primary", self._file))
        row.addWidget(W.button("⬇  Download Template", slot=self._template))
        row.addStretch(1)
        h = QWidget(); h.setLayout(row)
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
            "Issue Date\tEmployee Code\tEmployee Name\tProject / Site\tItem Group\tItem Code\tDescription\tSize\tQty\tUOM\tDelivery Note No.\tRemarks"
        )
        pc.add(self.paste, 1)
        r2 = QHBoxLayout()
        r2.addWidget(W.button("✔  Read && Import", "Primary", self._paste_import))
        r2.addWidget(W.button("🧹  Clear", slot=self.paste.clear))
        r2.addStretch(1)
        h2 = QWidget(); h2.setLayout(r2)
        pc.add(h2)
        v.addWidget(pc, 1)

        hc = W.Card("Import history — an import can be undone completely")
        self.hist = W.DataTable()
        hc.add(self.hist, 1)
        r3 = QHBoxLayout()
        r3.addWidget(W.button("↩  Undo Selected Import", slot=self._undo))
        r3.addWidget(W.button("🔄  Refresh", slot=self.reload))
        r3.addStretch(1)
        h3 = QWidget(); h3.setLayout(r3)
        hc.add(h3)
        v.addWidget(hc, 1)
        self.reload()

    def reload(self):
        self.hist.fill(["Batch", "When", "Source", "Imported", "Skipped", "Still present"],
                       [[b["id"], b["ts"], Path(str(b["source"])).name or b["source"],
                         b["rows"], b["skipped"], b["live"]]
                        for b in P.batches(self.pdb)])

    def _template(self):
        cols, sample = P.template_rows()
        f = D.export_excel(self.db, "Employee PPE Template", cols, sample,
                           Path(D.config.folder(P.FOLDER)) / "Employee_PPE_Template.xlsx",
                           totals=False)
        W.toast(self, f"Template saved: {f.name}")
        D.open_path(f)

    def _file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select the PPE sheet", "",
            "Spreadsheets and text (*.xlsx *.xlsm *.csv *.txt);;All files (*)")
        if not f:
            return
        try:
            headers, rows = P.read_file(f)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read that file.\n\n{exc}")
            return
        self._run(headers, rows, f)

    def _paste_import(self):
        txt = self.paste.toPlainText()
        if not txt.strip():
            W.error_box(self, "Paste the rows into the box first.")
            return
        headers, rows = P.sniff(txt)
        self._run(headers, rows, "pasted rows")

    def _run(self, headers, rows, source):
        if not rows:
            W.error_box(self, "No data rows were found.")
            return
        mapping = P.auto_map(headers)
        if not mapping:
            W.error_box(self, "None of the columns were recognised.\n\nMake sure the heading row is included.")
            return
        recs = P.preview(headers, rows, mapping)
        if not recs:
            W.error_box(self, "No usable rows were found.")
            return
        known = ", ".join(sorted({P.LABELS.get(f, f) for f in mapping.values()}))
        if not W.confirm(self, f"{len(recs)} row(s) ready to import from {Path(str(source)).name}.\n\n"
                               f"Recognised columns:\n{known}\n\nImport now?"):
            return
        ins, sk = P.import_records(self.pdb, recs, str(source))
        self.paste.clear()
        self.reload()
        self.imported.emit()
        W.info_box(self, f"{ins} PPE record(s) imported."
                         + (f"\n{sk} duplicate row(s) skipped." if sk else "")
                         + "\n\nYou can edit any imported row later from the Register tab.",
                   "Import complete")

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
        n = P.undo_batch(self.pdb, bid)
        self.reload()
        self.imported.emit()
        W.toast(self, f"{n} record(s) removed.")


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
        self.importer = PPEImportTab(self.pdb, db, self)
        self.tabs.addTab(self.importer, "⬆ Import Sheet")
        self.tabs.addTab(self._reports_tab(), "📈 Reports")
        v.addWidget(self.tabs, 1)
        v.addWidget(ShareBar(db, lambda: self.last_file, self))
        self.importer.imported.connect(self._after_import)
        self.refresh_all()

    def _after_import(self):
        self.refresh_all()
        self.dataChanged.emit()

    def _ensure_user(self):
        self.pdb.current_user = getattr(self.db, "current_user", "admin") or "admin"

    def _dashboard_period_range(self) -> tuple[str, str]:
        today = _dt.date.today()
        p = self.dash_period.currentText() if hasattr(self, "dash_period") else "All time"
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

    def _dashboard_filters(self) -> dict[str, str]:
        date_from, date_to = self._dashboard_period_range()
        return {
            "text": self.dash_text.text().strip() if hasattr(self, "dash_text") else "",
            "item_group": "" if self.dash_group.currentIndex() == 0 else self.dash_group.currentText(),
            "status": "" if self.dash_status.currentIndex() == 0 else self.dash_status.currentText(),
            "source_type": "" if self.dash_source.currentIndex() == 0 else self.dash_source.currentText(),
            "date_from": date_from,
            "date_to": date_to,
        }

    def _dashboard_measure_key(self) -> str:
        return "count" if self.dash_measure.currentText() == "Measure: Line count" else "qty"

    def reset_dashboard_filters(self):
        for wd in (self.dash_group, self.dash_status, self.dash_source,
                   self.dash_period, self.dash_measure):
            wd.blockSignals(True)
            wd.setCurrentIndex(0)
            wd.blockSignals(False)
        self.dash_text.blockSignals(True)
        self.dash_text.clear()
        self.dash_text.blockSignals(False)
        self.reload_dashboard()

    def _dashboard_group_clicked(self, group: str):
        idx = self.dash_group.findText(group)
        if idx >= 0:
            self.dash_group.setCurrentIndex(idx)

    def _dashboard_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        banner = QLabel(
            "🦺  <b>PPE Intelligence Dashboard</b> — live overview of shoes, blankets, FRCs, "
            "coveralls and other employee-issued welfare items, including separate tracking "
            "for records synced from Delivery Notes."
        )
        banner.setWordWrap(True)
        banner.setStyleSheet(
            f"background:{W.NAVY}; color:white; border-radius:8px; padding:10px 14px;")
        outer.addWidget(banner)

        filter_card = W.Card("Dashboard filters")
        flt = QHBoxLayout()
        self.dash_text = W.SearchBox("Filter employee, project, item, DN...")
        self.dash_group = W.combo(["All Groups"] + P.GROUPS)
        self.dash_status = W.combo(["All Status"] + P.STATUSES)
        self.dash_source = W.combo(["All Sources", "MANUAL", "DN"])
        self.dash_period = W.combo(["All time", "This month", "Last 3 months", "Last 6 months",
                                    "This year", "Last 12 months"])
        self.dash_measure = W.combo(["Measure: Quantity", "Measure: Line count"])
        for wd in (self.dash_text, self.dash_group, self.dash_status, self.dash_source,
                   self.dash_period, self.dash_measure):
            if hasattr(wd, "textChanged"):
                wd.textChanged.connect(self.reload_dashboard)
            else:
                wd.currentTextChanged.connect(self.reload_dashboard)
            flt.addWidget(wd)
        flt.addWidget(W.button("↺ Reset", slot=self.reset_dashboard_filters))
        fw = QWidget(); fw.setLayout(flt)
        filter_card.add(fw)
        outer.addWidget(filter_card)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, 1)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(4, 2, 4, 10)
        v.setSpacing(12)

        self.dash_cards: dict[str, W.StatCard] = {}
        specs = [
            ("total_records", "Total Records", "📋", W.NAVY),
            ("employees", "Employees", "👤", W.GREEN),
            ("total_qty", "Total Qty", "Σ", "#14538f"),
            ("outstanding_qty", "Outstanding Qty", "📦", W.AMBER),
            ("returned_qty", "Returned Qty", "↩", "#1098ad"),
            ("synced", "Synced from DNs", "🔄", "#7048e8"),
            ("active_dns", "Delivery Notes", "🧾", "#0b7285"),
            ("missing_info", "Missing Employee Info", "⚠", W.RED),
        ]
        cg = QGridLayout()
        cg.setSpacing(10)
        for i, (key, title, glyph, color) in enumerate(specs):
            card = W.StatCard(title, "0", glyph, color)
            cg.addWidget(card, i // 4, i % 4)
            self.dash_cards[key] = card
        v.addLayout(cg)
        self.k_total = self.dash_cards["total_records"].lbl_value
        self.k_emp = self.dash_cards["employees"].lbl_value
        self.k_sync = self.dash_cards["synced"].lbl_value
        self.k_missing = self.dash_cards["missing_info"].lbl_value

        r1 = QHBoxLayout(); r1.setSpacing(12)
        c1 = W.Card("Issues by PPE Group")
        self.ch_group = W.BarChart(horizontal=True, color="#14538f")
        self.ch_group.barClicked.connect(self._dashboard_group_clicked)
        c1.add(self.ch_group)
        r1.addWidget(c1, 2)
        c2 = W.Card("Record Status Split")
        self.ch_status = W.DonutChart()
        c2.add(self.ch_status)
        r1.addWidget(c2, 1)
        c3 = W.Card("Source Split")
        self.ch_source = W.DonutChart()
        c3.add(self.ch_source)
        r1.addWidget(c3, 1)
        v.addLayout(r1)

        r2 = QHBoxLayout(); r2.setSpacing(12)
        c4 = W.Card("Issued vs Returned by Month")
        self.ch_month = W.GroupedBarChart(labels=("Issued Qty", "Returned Qty"))
        c4.add(self.ch_month)
        r2.addWidget(c4, 2)
        c5 = W.Card("Top Employees")
        self.ch_employees = W.BarChart(horizontal=True, color="#7048e8")
        c5.add(self.ch_employees)
        r2.addWidget(c5, 1)
        c6 = W.Card("Top Issued Items")
        self.ch_items = W.BarChart(horizontal=True, color="#1a9c52")
        c6.add(self.ch_items)
        r2.addWidget(c6, 1)
        v.addLayout(r2)

        r3 = QHBoxLayout(); r3.setSpacing(12)
        c7 = W.Card("Top Projects / Departments")
        self.ch_projects = W.BarChart(horizontal=True, color="#0b7285")
        c7.add(self.ch_projects)
        r3.addWidget(c7, 2)
        c8 = W.Card("Missing Employee Info by Group")
        self.ch_missing = W.BarChart(color="#c92a2a")
        c8.add(self.ch_missing)
        r3.addWidget(c8, 1)
        v.addLayout(r3)

        recent = W.Card("Latest PPE / welfare issues")
        self.t_dash = W.DataTable()
        self.t_dash.setMaximumHeight(270)
        recent.add(self.t_dash)
        v.addWidget(recent)
        v.addStretch(1)
        return page

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
        if hasattr(self, "importer"):
            self.importer.reload()

    def reload_dashboard(self):
        d = P.dashboard_data(self.pdb, self._dashboard_filters())
        self.dash_cards["total_records"].set_value(f"{d['total_records']:,}", "records in current view")
        self.dash_cards["employees"].set_value(f"{d['employees']:,}", "distinct employee codes / names")
        self.dash_cards["total_qty"].set_value(f"{d['total_qty']:,.2f}", "all issued quantities")
        self.dash_cards["outstanding_qty"].set_value(f"{d['outstanding_qty']:,.2f}", f"{d['outstanding_records']:,} open record(s)")
        self.dash_cards["returned_qty"].set_value(f"{d['returned_qty']:,.2f}", f"return rate {d['return_rate']:.1f}%")
        self.dash_cards["synced"].set_value(f"{d['synced']:,}", f"manual records {d['manual_records']:,}")
        self.dash_cards["active_dns"].set_value(f"{d['active_dns']:,}", "distinct Delivery Notes")
        self.dash_cards["missing_info"].set_value(f"{d['missing_info']:,}", "needs employee code or name")

        measure = self._dashboard_measure_key()
        group_map = d["by_group"] if measure == "count" else d["by_group_qty"]
        emp_list = d["top_employees_count"] if measure == "count" else d["top_employees"]
        item_list = d["top_items_count"] if measure == "count" else d["top_items"]
        proj_list = d["top_projects_count"] if measure == "count" else d["top_projects"]
        self.ch_group.set_data([(k, float(v)) for k, v in group_map.items() if float(v or 0) > 0])
        self.ch_status.set_data([
            (P.ST_ISSUED, float(d["by_status"].get(P.ST_ISSUED, 0)), W.AMBER),
            (P.ST_RETURNED, float(d["by_status"].get(P.ST_RETURNED, 0)), W.GREEN),
            (P.ST_NEEDS_INFO, float(d["by_status"].get(P.ST_NEEDS_INFO, 0)), W.RED),
        ])
        self.ch_source.set_data([
            ("Manual", float(d["by_source"].get("MANUAL", 0)), "#14538f"),
            ("From DN", float(d["by_source"].get("DN", 0)), "#7048e8"),
        ])
        self.ch_month.set_data([(m, float(i), float(r)) for m, i, r in d.get("monthly_issue_return", [])])
        self.ch_employees.set_data(emp_list)
        self.ch_items.set_data(item_list)
        self.ch_projects.set_data(proj_list)
        self.ch_missing.set_data([(k, float(v)) for k, v in d.get("missing_by_group", {}).items() if float(v or 0) > 0])

        recent = d.get("recent", [])
        self.t_dash.fill(["Date", "Employee Code", "Employee", "Group", "Description", "Qty", "DN", "Source", "Status"],
                         [[r["issue_date"], r["employee_code"], r["employee_name"], r["item_group"],
                           r["item_desc"], round(float(r["qty"] or 0), 2), r["dn_no"],
                           r["source_type"], P.compute_status(r)]
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
