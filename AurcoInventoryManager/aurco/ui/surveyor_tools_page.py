"""TOOLS STATION — serials, photos, summary sheet and dashboard."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCompleter, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import employees as EMP
from ..core import surveyor_tools as SV
from ..core.database import Database
from . import widgets as W
from .common import date_edit, iso

_STATUS_COLORS = {
    SV.ST_ACTIVE: "#1a9c52",
    SV.ST_IN_USE: "#1098ad",
    SV.ST_OUT_OF_ORDER: "#c92a2a",
    SV.ST_UNDER_REPAIR: "#e8590c",
    SV.ST_MISSING: "#7048e8",
    SV.ST_DISPOSED: "#6b7c8f",
}


def _fmt_qty(v) -> str:
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return str(v or "")
    return f"{int(n)}" if abs(n - int(n)) < 1e-9 else f"{n:g}"


def _set_preview(label: QLabel, path: str) -> None:
    label.setText("")
    label.setPixmap(QPixmap())
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet("border:1px solid #d7dee6; border-radius:8px; background:#f8fafc;")
    if not path or not Path(path).exists():
        label.setText("No picture")
        return
    pm = QPixmap(path)
    if pm.isNull():
        label.setText("Picture not readable")
        return
    label.setPixmap(pm.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class RecordDialog(QDialog):
    def __init__(self, main_db: Database, record: dict | None = None, parent=None):
        super().__init__(parent)
        self.main_db = main_db
        self.record = dict(record or {})
        self._filling_employee = False
        self.setWindowTitle("Tools Station — " + ("Edit Record" if record else "New Record"))
        self.resize(860, 560)
        v = QVBoxLayout(self)

        note = QLabel("Enter the tool / instrument details here. Use 2nd Type to classify whether the item is a tool, device, instrument or another group. When a tool is issued, record the employee name together with the employee code or Iqama ID. If that employee already exists in the Employee Master, the details fill automatically.")
        note.setWordWrap(True)
        v.addWidget(note)

        body = QHBoxLayout()
        v.addLayout(body, 1)

        form_host = QWidget()
        form = QFormLayout(form_host)
        self.e_desc = QLineEdit(self.record.get("instrument_desc", ""))
        self.e_desc.setPlaceholderText("Auto Level / Total Station / GPS ...")
        self.e_type2 = W.combo(SV.SECOND_TYPE_SUGGESTIONS, editable=True,
                               current=self.record.get("second_type", ""))
        self.e_serial = QLineEdit(self.record.get("serial_no", ""))
        self.e_make = QLineEdit(self.record.get("make_model", ""))
        self.e_location = W.combo(SV.DEFAULT_LOCATIONS, editable=True,
                                  current=self.record.get("location", SV.LOC_WAREHOUSE))
        self.e_qty = QDoubleSpinBox()
        self.e_qty.setDecimals(2)
        self.e_qty.setRange(0.01, 999999)
        self.e_qty.setValue(float(self.record.get("qty") or 1))
        self.e_status = W.combo(SV.STATUSES, current=self.record.get("status", SV.ST_ACTIVE))
        self.e_issued_to = QLineEdit(self.record.get("issued_to", ""))
        self.e_employee_code = QLineEdit(self.record.get("employee_code", ""))
        self.e_iqama = QLineEdit(self.record.get("iqama_id", ""))
        self.e_designation = QLineEdit(self.record.get("designation", ""))
        self.e_division = QLineEdit(self.record.get("division", ""))
        self.e_project = QLineEdit(self.record.get("current_project", ""))
        self.e_issued_by = QLineEdit(self.record.get("issued_by", "") or getattr(self.main_db, "current_user", ""))
        self.e_remarks = QPlainTextEdit(self.record.get("remarks", ""))
        self.e_remarks.setMaximumHeight(120)
        self.e_picture = QLineEdit(self.record.get("picture_path", ""))
        self.e_picture.setPlaceholderText("Optional photo path")
        self._bind_employee_completers()
        self.e_issued_to.editingFinished.connect(lambda: self._fill_from_master("name"))
        self.e_employee_code.editingFinished.connect(lambda: self._fill_from_master("employee_id"))
        self.e_iqama.editingFinished.connect(lambda: self._fill_from_master("iqama_id"))

        pic_row = QHBoxLayout()
        pic_row.addWidget(self.e_picture, 1)
        pic_row.addWidget(W.button("Browse...", slot=self._pick_picture))
        pic_holder = QWidget()
        pic_holder.setLayout(pic_row)

        for lbl, wd in (("Instrument Description", self.e_desc),
                        ("2nd Type", self.e_type2),
                        ("Serial No.", self.e_serial),
                        ("Make / Model", self.e_make),
                        ("Location", self.e_location),
                        ("Quantity", self.e_qty),
                        ("Status", self.e_status),
                        ("Issued To / Employee Name", self.e_issued_to),
                        ("Employee Code", self.e_employee_code),
                        ("Iqama ID", self.e_iqama),
                        ("Designation", self.e_designation),
                        ("Division/Department", self.e_division),
                        ("Current Project", self.e_project),
                        ("Issued By", self.e_issued_by),
                        ("Remarks", self.e_remarks),
                        ("Picture", pic_holder)):
            form.addRow(lbl, wd)
        body.addWidget(form_host, 2)

        side = W.Card("Picture preview")
        self.preview = QLabel()
        self.preview.setMinimumSize(260, 260)
        self.preview.resize(260, 260)
        side.add(self.preview, 1)
        side.add(QLabel("Tip: keep one row per serial number where possible. Use the Employee Master page to maintain employee ID, Iqama ID, designation, department and project details for quick issue entry."))
        body.addWidget(side, 1)
        self._refresh_preview()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _bind_employee_completers(self):
        for widget, items in ((self.e_issued_to, EMP.employee_names(self.main_db)),
                              (self.e_employee_code, EMP.employee_ids(self.main_db)),
                              (self.e_iqama, EMP.iqama_ids(self.main_db))):
            comp = QCompleter(items, self)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            widget.setCompleter(comp)

    def _fill_from_master(self, mode: str):
        if self._filling_employee:
            return
        kwargs = {
            "employee_id": self.e_employee_code.text().strip() if mode == "employee_id" else "",
            "iqama_id": self.e_iqama.text().strip() if mode == "iqama_id" else "",
            "name": self.e_issued_to.text().strip() if mode == "name" else "",
        }
        emp = EMP.find_employee(self.main_db, **kwargs)
        if not emp:
            return
        self._filling_employee = True
        self.e_issued_to.setText(emp.get("name", ""))
        self.e_employee_code.setText(emp.get("employee_id", ""))
        self.e_iqama.setText(emp.get("iqama_id", ""))
        self.e_designation.setText(emp.get("designation", ""))
        self.e_division.setText(emp.get("division", ""))
        self.e_project.setText(emp.get("current_project", ""))
        self._filling_employee = False

    def _pick_picture(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select picture", self.e_picture.text(),
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*.*)")
        if f:
            self.e_picture.setText(f)
            self._refresh_preview()

    def _refresh_preview(self):
        _set_preview(self.preview, self.e_picture.text().strip())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh_preview()

    def data(self) -> dict:
        return {
            "instrument_desc": self.e_desc.text().strip(),
            "second_type": self.e_type2.currentText().strip(),
            "serial_no": self.e_serial.text().strip(),
            "make_model": self.e_make.text().strip(),
            "location": self.e_location.currentText().strip(),
            "qty": float(self.e_qty.value()),
            "status": self.e_status.currentText().strip(),
            "issued_to": self.e_issued_to.text().strip(),
            "employee_code": self.e_employee_code.text().strip(),
            "iqama_id": self.e_iqama.text().strip(),
            "designation": self.e_designation.text().strip(),
            "division": self.e_division.text().strip(),
            "current_project": self.e_project.text().strip(),
            "issued_by": self.e_issued_by.text().strip(),
            "remarks": self.e_remarks.toPlainText().strip(),
            "picture_path": self.e_picture.text().strip(),
        }


class TransferDialog(QDialog):
    def __init__(self, main_db: Database, record: dict[str, object], parent=None):
        super().__init__(parent)
        self.main_db = main_db
        self.record = dict(record or {})
        self._filling_employee = False
        self.setWindowTitle("Tools Station — Transfer Tool")
        self.resize(760, 500)
        v = QVBoxLayout(self)

        note = QLabel(
            "Use this form whenever a tool moves to another person, site or location. "
            "AURCO will update the current holder and keep a permanent movement history."
        )
        note.setWordWrap(True)
        v.addWidget(note)

        now_card = W.Card("Current custody")
        now_card.add(QLabel(
            f"<b>Description:</b> {self.record.get('instrument_desc', '') or '—'}<br>"
            f"<b>Serial No.:</b> {self.record.get('serial_no', '') or '—'}<br>"
            f"<b>Current holder:</b> {self.record.get('issued_to', '') or '—'}<br>"
            f"<b>Current project/site:</b> {self.record.get('current_project', '') or '—'}<br>"
            f"<b>Current location:</b> {self.record.get('location', '') or '—'}<br>"
            f"<b>Status:</b> {self.record.get('status', '') or '—'}"
        ))
        v.addWidget(now_card)

        form = QFormLayout()
        self.e_date = date_edit()
        self.e_location = W.combo(SV.DEFAULT_LOCATIONS, editable=True,
                                  current=str(self.record.get("location", "") or SV.LOC_WAREHOUSE))
        self.e_status = W.combo(SV.STATUSES, current=str(self.record.get("status", "") or SV.ST_ACTIVE))
        self.e_issued_to = QLineEdit(str(self.record.get("issued_to", "") or ""))
        self.e_employee_code = QLineEdit(str(self.record.get("employee_code", "") or ""))
        self.e_iqama = QLineEdit(str(self.record.get("iqama_id", "") or ""))
        self.e_designation = QLineEdit(str(self.record.get("designation", "") or ""))
        self.e_division = QLineEdit(str(self.record.get("division", "") or ""))
        self.e_project = QLineEdit(str(self.record.get("current_project", "") or ""))
        self.e_moved_by = QLineEdit(getattr(main_db, "current_user", "") or str(self.record.get("issued_by", "") or ""))
        self.e_remarks = QPlainTextEdit(str(self.record.get("remarks", "") or ""))
        self.e_remarks.setMaximumHeight(110)
        self._bind_employee_completers()
        self.e_issued_to.editingFinished.connect(lambda: self._fill_from_master("name"))
        self.e_employee_code.editingFinished.connect(lambda: self._fill_from_master("employee_id"))
        self.e_iqama.editingFinished.connect(lambda: self._fill_from_master("iqama_id"))

        for lbl, wd in (("Transfer Date", self.e_date),
                        ("New Location", self.e_location),
                        ("New Status", self.e_status),
                        ("Transfer To / Employee Name", self.e_issued_to),
                        ("Employee Code", self.e_employee_code),
                        ("Iqama ID", self.e_iqama),
                        ("Designation", self.e_designation),
                        ("Division/Department", self.e_division),
                        ("Project / Site", self.e_project),
                        ("Transferred By", self.e_moved_by),
                        ("Transfer Remarks", self.e_remarks)):
            form.addRow(lbl, wd)
        v.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save Transfer")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _bind_employee_completers(self):
        for widget, items in ((self.e_issued_to, EMP.employee_names(self.main_db)),
                              (self.e_employee_code, EMP.employee_ids(self.main_db)),
                              (self.e_iqama, EMP.iqama_ids(self.main_db))):
            comp = QCompleter(items, self)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            widget.setCompleter(comp)

    def _fill_from_master(self, mode: str):
        if self._filling_employee:
            return
        kwargs = {
            "employee_id": self.e_employee_code.text().strip() if mode == "employee_id" else "",
            "iqama_id": self.e_iqama.text().strip() if mode == "iqama_id" else "",
            "name": self.e_issued_to.text().strip() if mode == "name" else "",
        }
        emp = EMP.find_employee(self.main_db, **kwargs)
        if not emp:
            return
        self._filling_employee = True
        self.e_issued_to.setText(emp.get("name", ""))
        self.e_employee_code.setText(emp.get("employee_id", ""))
        self.e_iqama.setText(emp.get("iqama_id", ""))
        self.e_designation.setText(emp.get("designation", ""))
        self.e_division.setText(emp.get("division", ""))
        self.e_project.setText(emp.get("current_project", ""))
        self._filling_employee = False

    def data(self) -> dict[str, str]:
        return {
            "event_date": iso(self.e_date),
            "location": self.e_location.currentText().strip(),
            "status": self.e_status.currentText().strip(),
            "issued_to": self.e_issued_to.text().strip(),
            "employee_code": self.e_employee_code.text().strip(),
            "iqama_id": self.e_iqama.text().strip(),
            "designation": self.e_designation.text().strip(),
            "division": self.e_division.text().strip(),
            "current_project": self.e_project.text().strip(),
            "moved_by": self.e_moved_by.text().strip(),
            "remarks": self.e_remarks.toPlainText().strip(),
        }


class DashboardTab(QWidget):
    def __init__(self, sdb: SV.SurveyorDB, parent=None):
        super().__init__(parent)
        self.sdb = sdb
        self.cards: dict[str, W.StatCard] = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.bar = QWidget()
        self.bar.setObjectName("Card")
        fl = QGridLayout(self.bar)
        fl.setContentsMargins(10, 8, 10, 8)
        self.f_text = W.SearchBox("Filter the dashboard — description, serial, employee, Iqama, location, remarks ...")
        self.f_loc = W.combo(["All Locations"] + SV.DEFAULT_LOCATIONS, editable=True)
        self.f_status = W.combo(["All Status"] + SV.STATUSES)
        for w in (self.f_text, self.f_loc, self.f_status):
            if hasattr(w, "textChanged"):
                w.textChanged.connect(self.reload)
            else:
                w.currentTextChanged.connect(self.reload)
        fl.addWidget(self.f_text, 0, 0, 1, 3)
        fl.addWidget(self.f_loc, 0, 3)
        fl.addWidget(self.f_status, 0, 4)
        fl.addWidget(W.button("Reset", slot=self.reset_filters), 0, 5)
        v.addWidget(self.bar)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for i, (key, label, glyph, color) in enumerate((
                ("records", "Records", "📋", W.NAVY),
                ("qty", "Total Quantity", "Σ", "#0b6e83"),
                ("ooo", "Out of Order", "⛔", "#c92a2a"),
                ("photos", "Pictures", "📷", "#1a9c52"),
                ("locations", "Locations Used", "📍", "#7048e8"),
        )):
            c = W.StatCard(label, glyph=glyph, color=color)
            self.cards[key] = c
            grid.addWidget(c, i // 3, i % 3)
        v.addLayout(grid)

        charts = QHBoxLayout()
        left = W.Card("Quantity by location")
        self.c_location = W.BarChart([], color="#0b6e83")
        left.add(self.c_location, 1)
        charts.addWidget(left, 1)
        mid = W.Card("Status mix")
        self.c_status = W.DonutChart()
        mid.add(self.c_status, 1)
        charts.addWidget(mid, 1)
        right = W.Card("Top instrument descriptions")
        self.c_desc = W.BarChart([], color="#1f6feb", horizontal=True)
        right.add(self.c_desc, 1)
        charts.addWidget(right, 1)
        v.addLayout(charts, 1)

        rec = W.Card("Recent updates")
        self.t_recent = W.DataTable(["Description", "Serial No.", "Location", "Status", "Qty", "Updated"])
        rec.add(self.t_recent, 1)
        v.addWidget(rec, 1)

    def _filters(self) -> dict:
        loc = self.f_loc.currentText().strip()
        stat = self.f_status.currentText().strip()
        return {
            "text": self.f_text.text().strip(),
            "location": "" if loc == "All Locations" else loc,
            "status": "" if stat == "All Status" else stat,
        }

    def reset_filters(self):
        self.f_text.clear()
        self.f_loc.setCurrentIndex(0)
        self.f_status.setCurrentIndex(0)
        self.reload()

    def reload(self):
        d = SV.dashboard_data(self.sdb, **self._filters())
        self.cards["records"].set_value(f"{d['record_count']:,}", "register row(s)")
        self.cards["qty"].set_value(_fmt_qty(d["total_qty"]), "total quantity tracked")
        self.cards["ooo"].set_value(_fmt_qty(d["out_of_order_qty"]), "needs attention")
        self.cards["photos"].set_value(f"{d['photo_count']:,}", "records with pictures")
        self.cards["locations"].set_value(f"{d['location_count']:,}", "locations represented")
        self.c_location.set_data(d["locations"] or [("No data", 0)])
        self.c_desc.set_data(d["top_descriptions"] or [("No data", 0)])
        self.c_status.set_data([(k, v, _STATUS_COLORS.get(k, W.NAVY)) for k, v in d["statuses"]])
        self.t_recent.fill(
            ["Description", "Serial No.", "Location", "Status", "Qty", "Updated"],
            [[r.get("instrument_desc", ""), r.get("serial_no", ""), r.get("location", ""),
              r.get("status", ""), float(r.get("qty") or 0),
              r.get("updated_at", "") or r.get("created_at", "")]
             for r in d["recent"]],
        )


class RegisterTab(QWidget):
    dataChanged = Signal()

    def __init__(self, sdb: SV.SurveyorDB, main_db: Database, parent=None):
        super().__init__(parent)
        self.sdb = sdb
        self.main_db = main_db
        self.records: list[dict] = []
        self.last_file: Path | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QWidget()
        bar.setObjectName("Card")
        bl = QGridLayout(bar)
        bl.setContentsMargins(10, 8, 10, 8)
        self.f_text = W.SearchBox("Search description, 2nd type, serial no., employee code, Iqama, location, make/model, remarks ...")
        self.f_desc = W.combo(["All Instruments"], editable=False)
        self.f_type2 = W.combo(["All 2nd Types"], editable=True)
        self.f_loc = W.combo(["All Locations"] + SV.DEFAULT_LOCATIONS, editable=True)
        self.f_status = W.combo(["All Status"] + SV.STATUSES)
        for w in (self.f_text, self.f_desc, self.f_type2, self.f_loc, self.f_status):
            if hasattr(w, "textChanged"):
                w.textChanged.connect(self.reload)
            else:
                w.currentTextChanged.connect(self.reload)
        bl.addWidget(self.f_text, 0, 0, 1, 3)
        bl.addWidget(self.f_desc, 0, 3)
        bl.addWidget(self.f_type2, 0, 4)
        bl.addWidget(self.f_loc, 0, 5)
        bl.addWidget(self.f_status, 0, 6)
        for i, (txt, slot) in enumerate((
                ("Add", self.add_record),
                ("Edit", self.edit_record),
                ("Transfer", self.transfer_record),
                ("Delete", self.delete_record),
                ("Open Picture", self.open_picture),
                ("Excel", self.export_excel),
                ("PDF", self.export_pdf),
                ("History PDF", self.export_history_pdf),
                ("Reset", self.reset_filters),
        ), start=7):
            bl.addWidget(W.button(txt, "Accent" if txt == "Add" else "", slot=slot), 0, i)
        v.addWidget(bar)

        split = QSplitter()
        split.setChildrenCollapsible(False)
        v.addWidget(split, 1)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.table = W.DataTable(["ID", "Instrument Description", "2nd Type", "Serial No.", "Make / Model",
                                  "Location", "Issued To", "Employee Code", "Iqama ID",
                                  "Status", "Qty", "Issued By", "Picture", "Remarks", "Updated"])
        self.table.itemSelectionChanged.connect(self._show_current)
        lv.addWidget(self.table, 1)
        split.addWidget(left)

        self.detail = W.Card("Record details")
        self.lbl_pic = QLabel()
        self.lbl_pic.setMinimumSize(280, 220)
        self.lbl_pic.resize(280, 220)
        self.detail.add(self.lbl_pic)
        self.lbl_detail = QLabel("Select a row to see the full details.")
        self.lbl_detail.setWordWrap(True)
        self.detail.add(self.lbl_detail, 1)
        self.detail.add(QLabel("<b>Movement history</b>"))
        self.t_history = W.DataTable(["Date", "Event", "From Holder / Site", "To Holder / Site", "Location", "By", "Remarks"])
        self.t_history.setMaximumHeight(220)
        self.detail.add(self.t_history)
        split.addWidget(self.detail)
        split.setSizes([950, 420])

    def _filters(self) -> dict:
        desc = self.f_desc.currentText().strip()
        type2 = self.f_type2.currentText().strip()
        loc = self.f_loc.currentText().strip()
        stat = self.f_status.currentText().strip()
        return {
            "text": self.f_text.text().strip(),
            "instrument_desc": "" if desc == "All Instruments" else desc,
            "second_type": "" if type2 == "All 2nd Types" else type2,
            "location": "" if loc == "All Locations" else loc,
            "status": "" if stat == "All Status" else stat,
        }

    def reload_filters(self):
        cur_desc = self.f_desc.currentText()
        cur_type2 = self.f_type2.currentText()
        cur_loc = self.f_loc.currentText()
        descs = ["All Instruments"] + SV.distinct_values(self.sdb, "instrument_desc")
        type2s = ["All 2nd Types"] + SV.distinct_values(self.sdb, "second_type")
        locs = ["All Locations"] + sorted({*SV.DEFAULT_LOCATIONS, *SV.distinct_values(self.sdb, 'location')})
        self.f_desc.blockSignals(True)
        self.f_desc.clear(); self.f_desc.addItems(descs)
        if cur_desc in descs:
            self.f_desc.setCurrentText(cur_desc)
        self.f_desc.blockSignals(False)
        self.f_type2.blockSignals(True)
        self.f_type2.clear(); self.f_type2.addItems(type2s)
        if cur_type2 in type2s:
            self.f_type2.setCurrentText(cur_type2)
        self.f_type2.blockSignals(False)
        self.f_loc.blockSignals(True)
        self.f_loc.clear(); self.f_loc.addItems(locs)
        if cur_loc in locs:
            self.f_loc.setCurrentText(cur_loc)
        self.f_loc.blockSignals(False)

    def reset_filters(self):
        self.f_text.clear()
        self.f_desc.setCurrentIndex(0)
        self.f_type2.setCurrentIndex(0)
        self.f_loc.setCurrentIndex(0)
        self.f_status.setCurrentIndex(0)
        self.reload()

    def reload(self):
        self.reload_filters()
        self.records = SV.list_records(self.sdb, **self._filters())
        self.table.fill(
            ["ID", "Instrument Description", "2nd Type", "Serial No.", "Make / Model",
             "Location", "Issued To", "Employee Code", "Iqama ID",
             "Status", "Qty", "Issued By", "Picture", "Remarks", "Updated"],
            [[r["id"], r.get("instrument_desc", ""), r.get("second_type", ""), r.get("serial_no", ""),
              r.get("make_model", ""), r.get("location", ""), r.get("issued_to", ""), r.get("employee_code", ""),
              r.get("iqama_id", ""), r.get("status", ""), float(r.get("qty") or 0),
              r.get("issued_by", ""), ("Yes" if r.get("picture_path") else ""), r.get("remarks", ""),
              r.get("updated_at", "") or r.get("created_at", "")]
             for r in self.records],
        )
        self.table.setColumnHidden(0, True)
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
        else:
            _set_preview(self.lbl_pic, "")
            self.lbl_detail.setText("No records match the current filters.")
            self.t_history.fill(["Date", "Event", "From Holder / Site", "To Holder / Site", "Location", "By", "Remarks"], [])

    def _current(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0 or r >= len(self.records):
            return None
        rid = int(self.table.item(r, 0).text())
        for rec in self.records:
            if int(rec["id"]) == rid:
                return rec
        return None

    def _show_current(self):
        rec = self._current()
        if not rec:
            _set_preview(self.lbl_pic, "")
            self.lbl_detail.setText("Select a row to see the full details.")
            self.t_history.fill(["Date", "Event", "From Holder / Site", "To Holder / Site", "Location", "By", "Remarks"], [])
            return
        _set_preview(self.lbl_pic, rec.get("picture_path", ""))
        hist = SV.transfer_history(self.sdb, int(rec["id"]))
        self.t_history.fill(
            ["Date", "Event", "From Holder / Site", "To Holder / Site", "Location", "By", "Remarks"],
            [[h.get("event_date", ""), h.get("event_type", ""),
              " / ".join(x for x in (str(h.get("from_holder") or "").strip(), str(h.get("from_project") or "").strip()) if x) or "—",
              " / ".join(x for x in (str(h.get("to_holder") or "").strip(), str(h.get("to_project") or "").strip()) if x) or "—",
              f"{h.get('from_location', '') or '—'} → {h.get('to_location', '') or '—'}",
              h.get("moved_by", ""), h.get("remarks", "")]
             for h in hist]
        )
        self.lbl_detail.setText(
            "<b>Description:</b> {0}<br>"
            "<b>2nd Type:</b> {1}<br>"
            "<b>Serial No.:</b> {2}<br>"
            "<b>Make / Model:</b> {3}<br>"
            "<b>Location:</b> {4}<br>"
            "<b>Issued To:</b> {5}<br>"
            "<b>Employee Code:</b> {6}<br>"
            "<b>Iqama ID:</b> {7}<br>"
            "<b>Designation:</b> {8}<br>"
            "<b>Division/Department:</b> {9}<br>"
            "<b>Current Project:</b> {10}<br>"
            "<b>Status:</b> {11}<br>"
            "<b>Quantity:</b> {12}<br>"
            "<b>Issued By:</b> {13}<br>"
            "<b>Remarks:</b> {14}<br>"
            "<b>Picture:</b> {15}<br>"
            "<b>Updated:</b> {16}"
            .format(
                rec.get("instrument_desc", "") or "—",
                rec.get("second_type", "") or "—",
                rec.get("serial_no", "") or "—",
                rec.get("make_model", "") or "—",
                rec.get("location", "") or "—",
                rec.get("issued_to", "") or "—",
                rec.get("employee_code", "") or "—",
                rec.get("iqama_id", "") or "—",
                rec.get("designation", "") or "—",
                rec.get("division", "") or "—",
                rec.get("current_project", "") or "—",
                rec.get("status", "") or "—",
                _fmt_qty(rec.get("qty", 0)),
                rec.get("issued_by", "") or "—",
                rec.get("remarks", "") or "—",
                rec.get("picture_path", "") or "—",
                rec.get("updated_at", "") or rec.get("created_at", "") or "—",
            )
        )

    def add_record(self):
        dlg = RecordDialog(self.main_db, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            SV.save_record(self.sdb, dlg.data())
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.reload()
        self.dataChanged.emit()
        W.toast(self, "Tools Station record saved.")

    def edit_record(self):
        rec = self._current()
        if not rec:
            return
        dlg = RecordDialog(self.main_db, rec, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            SV.save_record(self.sdb, dlg.data(), int(rec["id"]))
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.reload()
        self.dataChanged.emit()
        W.toast(self, "Tools Station record updated.")

    def transfer_record(self):
        rec = self._current()
        if not rec:
            return
        dlg = TransferDialog(self.main_db, rec, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            SV.transfer_record(self.sdb, int(rec["id"]), dlg.data())
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.reload()
        self.dataChanged.emit()
        W.toast(self, "Tool transfer saved.")

    def delete_record(self):
        rec = self._current()
        if not rec:
            return
        if not W.confirm(self, f"Delete the record for '{rec['instrument_desc']}'?"):
            return
        SV.delete_record(self.sdb, int(rec["id"]))
        self.reload()
        self.dataChanged.emit()
        W.toast(self, "Record deleted.")

    def open_picture(self):
        rec = self._current()
        if not rec or not rec.get("picture_path"):
            W.error_box(self, "This record has no picture.")
            return
        p = Path(rec["picture_path"])
        if not p.exists():
            W.error_box(self, "The saved picture file was not found.")
            return
        D.open_path(p)

    def export_excel(self):
        f = D.export_excel(
            self.sdb,
            "Tools Station Register",
            ["Instrument Description", "2nd Type", "Serial No.", "Make / Model", "Location", "Issued To", "Employee Code", "Iqama ID", "Designation", "Division/Department", "Current Project", "Status", "Qty", "Issued By", "Picture", "Remarks", "Updated"],
            [[r.get("instrument_desc", ""), r.get("second_type", ""), r.get("serial_no", ""), r.get("make_model", ""),
              r.get("location", ""), r.get("issued_to", ""), r.get("employee_code", ""), r.get("iqama_id", ""),
              r.get("designation", ""), r.get("division", ""), r.get("current_project", ""), r.get("status", ""), float(r.get("qty") or 0),
              r.get("issued_by", ""), r.get("picture_path", ""), r.get("remarks", ""),
              r.get("updated_at", "") or r.get("created_at", "")]
             for r in self.records],
        )
        self.last_file = f
        W.toast(self, f"Exported {f.name}")
        D.open_path(f)

    def export_pdf(self):
        f = SV.export_register_pdf(self.sdb, self.records)
        self.last_file = f
        W.toast(self, f"Exported {f.name}")
        D.open_path(f)

    def export_history_pdf(self):
        rec = self._current()
        if not rec:
            return
        f = SV.export_history_pdf(self.sdb, int(rec["id"]))
        self.last_file = f
        W.toast(self, f"Exported {f.name}")
        D.open_path(f)


class SurveyorImportTab(QWidget):
    imported = Signal()

    def __init__(self, sdb: SV.SurveyorDB, db: Database, parent=None):
        super().__init__(parent)
        self.sdb = sdb
        self.db = db
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(10)

        card = W.Card("Import tools and instruments from Excel / CSV")
        cols, sample = SV.template_rows()
        t = W.DataTable()
        t.fill(cols, sample)
        t.setMaximumHeight(135)
        card.add(t)
        note = QLabel(
            "Download the template, fill the tools / instruments rows in Excel, then import the file here. "
            "AURCO also recognises common headings automatically — including Instrument Description, 2nd Type, "
            "Serial No., Make / Model, Location, Quantity, Status, Issued To, Employee Code, Iqama ID, "
            "Issued By, Remarks and Picture Path."
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
        self.paste.setMinimumHeight(200)
        self.paste.setPlaceholderText(
            "Instrument Description	2nd Type	Serial No.	Make / Model	Location	Quantity	Status	Issued To / Employee Name	Employee Code	Iqama ID	Designation	Division/Department	Current Project	Issued By	Remarks	Picture Path"
        )
        pc.add(self.paste, 1)
        r2 = QHBoxLayout()
        r2.addWidget(W.button("✔  Read && Import", "Primary", self._paste_import))
        r2.addWidget(W.button("🧹  Clear", slot=self.paste.clear))
        r2.addStretch(1)
        h2 = QWidget(); h2.setLayout(r2)
        pc.add(h2)
        v.addWidget(pc, 1)

    def _template(self):
        cols, sample = SV.template_rows()
        f = D.export_excel(self.db, "Tools Station Template", cols, sample,
                           Path(D.config.folder(SV.FOLDER)) / "Tools_Station_Template.xlsx",
                           totals=False)
        W.toast(self, f"Template saved: {f.name}")
        D.open_path(f)

    def _file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select the Tools Station sheet", "",
            "Spreadsheets and text (*.xlsx *.xlsm *.csv *.txt);;All files (*)")
        if not f:
            return
        try:
            headers, rows = SV.read_file(f)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read that file.\n\n{exc}")
            return
        self._run(headers, rows, f)

    def _paste_import(self):
        txt = self.paste.toPlainText()
        if not txt.strip():
            W.error_box(self, "Paste the rows into the box first.")
            return
        headers, rows = SV.sniff(txt)
        self._run(headers, rows, "pasted rows")

    def _run(self, headers, rows, source):
        if not rows:
            W.error_box(self, "No data rows were found.")
            return
        mapping = SV.auto_map(headers)
        if not mapping:
            W.error_box(self, "None of the columns were recognised.\n\nMake sure the heading row is included.")
            return
        recs = SV.preview(headers, rows, mapping)
        if not recs:
            W.error_box(self, "No usable Tools Station rows were found.")
            return
        known = ", ".join(sorted({SV.LABELS.get(f, f) for f in mapping.values()}))
        if not W.confirm(self, f"{len(recs)} row(s) ready to import from {Path(str(source)).name}.\n\n"
                               f"Recognised columns:\n{known}\n\nImport now?"):
            return
        ins, sk = SV.import_records(self.sdb, recs, str(source))
        self.paste.clear()
        self.imported.emit()
        W.info_box(self, f"{ins} Tools Station record(s) imported."
                         + (f"\n{sk} row(s) skipped because they were duplicate or invalid." if sk else "")
                         + "\n\nYou can edit any imported row later from the Register tab.",
                   "Import complete")


class SummaryTab(QWidget):
    def __init__(self, sdb: SV.SurveyorDB, parent=None):
        super().__init__(parent)
        self.sdb = sdb
        self.rows: list[dict] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("This sheet matches the supplied tools summary layout, adds the 2nd Type classification, and is built automatically from the register."))
        bar.addStretch(1)
        bar.addWidget(W.button("Export", slot=self.export_excel))
        bar.addWidget(W.button("Refresh", slot=self.reload))
        v.addLayout(bar)

        self.table = W.DataTable(["SR#", "Instrument Description", "2nd Type", "Warehouse", "Hajar", "Zuluf",
                                  "Yanbu", "Noor", "Total Quantity", "Remarks"])
        v.addWidget(self.table, 1)

    def reload(self):
        self.rows = SV.summary_rows(self.sdb)
        self.table.fill(
            ["SR#", "Instrument Description", "2nd Type", "Warehouse", "Hajar", "Zuluf",
             "Yanbu", "Noor", "Total Quantity", "Remarks"],
            [[r["sr"], r["instrument_desc"], r.get("second_type", ""), float(r["Warehouse"]), float(r["Hajar"]),
              float(r["Zuluf"]), float(r["Yanbu"]), float(r["Noor"]),
              float(r["total_qty"]), r["remarks"]]
             for r in self.rows],
        )

    def export_excel(self):
        f = D.export_excel(
            self.sdb,
            "Tools Station",
            ["SR#", "Instrument Description", "2nd Type", "Warehouse", "Hajar", "Zuluf",
             "Yanbu", "Noor", "Total Quantity", "Remarks"],
            [[r["sr"], r["instrument_desc"], r.get("second_type", ""), float(r["Warehouse"]), float(r["Hajar"]),
              float(r["Zuluf"]), float(r["Yanbu"]), float(r["Noor"]),
              float(r["total_qty"]), r["remarks"]]
             for r in self.rows],
        )
        W.toast(self, f"Exported {f.name}")
        D.open_path(f)


class AnalyticsTab(QWidget):
    def __init__(self, sdb: SV.SurveyorDB, parent=None):
        super().__init__(parent)
        self.sdb = sdb
        self.rows: list[dict] = []
        self.last_file: Path | None = None
        self.cards: dict[str, W.StatCard] = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        note = QLabel(
            "This analytics module shows where each 2nd Type item currently is — for example tools, devices and instruments by site/location — based on the latest live Tools Station register."
        )
        note.setWordWrap(True)
        v.addWidget(note)

        bar = QWidget()
        bar.setObjectName("Card")
        gl = QGridLayout(bar)
        gl.setContentsMargins(10, 8, 10, 8)
        self.f_text = W.SearchBox("Search 2nd type, description, site, location, custodian or serial ...")
        self.f_type2 = W.combo(["All 2nd Types"], editable=True)
        self.f_site = W.combo(["All Sites"], editable=True)
        self.f_loc = W.combo(["All Locations"] + SV.DEFAULT_LOCATIONS, editable=True)
        self.f_status = W.combo(["All Status"] + SV.STATUSES)
        for w in (self.f_text, self.f_type2, self.f_site, self.f_loc, self.f_status):
            if hasattr(w, "textChanged"):
                w.textChanged.connect(self.reload)
            else:
                w.currentTextChanged.connect(self.reload)
        gl.addWidget(self.f_text, 0, 0, 1, 3)
        gl.addWidget(self.f_type2, 0, 3)
        gl.addWidget(self.f_site, 0, 4)
        gl.addWidget(self.f_loc, 0, 5)
        gl.addWidget(self.f_status, 0, 6)
        gl.addWidget(W.button("Excel", slot=self.export_excel), 0, 7)
        gl.addWidget(W.button("PDF", slot=self.export_pdf), 0, 8)
        gl.addWidget(W.button("Reset", slot=self.reset_filters), 0, 9)
        v.addWidget(bar)

        cards = QGridLayout()
        for i, (key, label, glyph, color) in enumerate((
                ("rows", "Analytics Rows", "📋", W.NAVY),
                ("qty", "Total Quantity", "Σ", "#0b6e83"),
                ("sites", "Sites", "📍", "#7048e8"),
                ("types", "2nd Types", "🧩", "#1a9c52"),
        )):
            c = W.StatCard(label, glyph=glyph, color=color)
            self.cards[key] = c
            cards.addWidget(c, 0, i)
        v.addLayout(cards)

        charts = QHBoxLayout()
        left = W.Card("Quantity by current site")
        self.c_site = W.BarChart([], color="#0b6e83")
        left.add(self.c_site, 1)
        charts.addWidget(left, 1)
        mid = W.Card("2nd type mix")
        self.c_type = W.DonutChart()
        mid.add(self.c_type, 1)
        charts.addWidget(mid, 1)
        right = W.Card("Top items by site")
        self.c_item = W.BarChart([], color="#1f6feb", horizontal=True)
        right.add(self.c_item, 1)
        charts.addWidget(right, 1)
        v.addLayout(charts, 1)

        tbl = W.Card("Current transferred-material analytics")
        self.table = W.DataTable(["2nd Type", "Item Description", "Current Site", "Current Location",
                                  "Status", "Qty", "Custodians", "Serials", "Rows"])
        tbl.add(self.table, 1)
        v.addWidget(tbl, 1)

    def _filters(self) -> dict:
        type2 = self.f_type2.currentText().strip()
        site = self.f_site.currentText().strip()
        loc = self.f_loc.currentText().strip()
        stat = self.f_status.currentText().strip()
        return {
            "text": self.f_text.text().strip(),
            "second_type": "" if type2 == "All 2nd Types" else type2,
            "site": "" if site == "All Sites" else site,
            "location": "" if loc == "All Locations" else loc,
            "status": "" if stat == "All Status" else stat,
        }

    def reset_filters(self):
        self.f_text.clear()
        self.f_type2.setCurrentIndex(0)
        self.f_site.setCurrentIndex(0)
        self.f_loc.setCurrentIndex(0)
        self.f_status.setCurrentIndex(0)
        self.reload()

    def reload_filters(self):
        cur_type2 = self.f_type2.currentText()
        cur_site = self.f_site.currentText()
        cur_loc = self.f_loc.currentText()
        type2s = ["All 2nd Types"] + SV.distinct_values(self.sdb, "second_type")
        sites = ["All Sites"] + SV.distinct_sites(self.sdb)
        locs = ["All Locations"] + sorted({*SV.DEFAULT_LOCATIONS, *SV.distinct_values(self.sdb, 'location')})
        self.f_type2.blockSignals(True)
        self.f_type2.clear(); self.f_type2.addItems(type2s)
        if cur_type2 in type2s:
            self.f_type2.setCurrentText(cur_type2)
        self.f_type2.blockSignals(False)
        self.f_site.blockSignals(True)
        self.f_site.clear(); self.f_site.addItems(sites)
        if cur_site in sites:
            self.f_site.setCurrentText(cur_site)
        self.f_site.blockSignals(False)
        self.f_loc.blockSignals(True)
        self.f_loc.clear(); self.f_loc.addItems(locs)
        if cur_loc in locs:
            self.f_loc.setCurrentText(cur_loc)
        self.f_loc.blockSignals(False)

    def reload(self):
        self.reload_filters()
        d = SV.analytics_data(self.sdb, **self._filters())
        self.rows = d["rows"]
        self.cards["rows"].set_value(f"{d['row_count']:,}", "grouped current position row(s)")
        self.cards["qty"].set_value(_fmt_qty(d["total_qty"]), "quantity currently tracked")
        self.cards["sites"].set_value(f"{d['site_count']:,}", "site / project footprint")
        self.cards["types"].set_value(f"{d['second_type_count']:,}", "2nd type groups")
        self.c_site.set_data(d["by_site"] or [("No data", 0)])
        self.c_type.set_data([(k, v, _STATUS_COLORS.get(SV.ST_ACTIVE, W.NAVY) if i % 2 == 0 else "#7048e8")
                              for i, (k, v) in enumerate(d["by_second_type"])])
        self.c_item.set_data(d["top_items"] or [("No data", 0)])
        self.table.fill(
            ["2nd Type", "Item Description", "Current Site", "Current Location", "Status", "Qty", "Custodians", "Serials", "Rows"],
            [[r.get("second_type", ""), r.get("instrument_desc", ""), r.get("site", ""), r.get("location", ""),
              r.get("status", ""), float(r.get("qty") or 0), r.get("custodians", ""), r.get("serials", ""),
              int(r.get("record_count") or 0)]
             for r in self.rows],
        )

    def export_excel(self):
        f = D.export_excel(
            self.sdb,
            "Tools Station Analytics",
            ["2nd Type", "Item Description", "Current Site", "Current Location", "Status", "Qty", "Custodians", "Serials", "Rows"],
            [[r.get("second_type", ""), r.get("instrument_desc", ""), r.get("site", ""), r.get("location", ""),
              r.get("status", ""), float(r.get("qty") or 0), r.get("custodians", ""), r.get("serials", ""),
              int(r.get("record_count") or 0)]
             for r in self.rows],
        )
        self.last_file = f
        W.toast(self, f"Exported {f.name}")
        D.open_path(f)

    def export_pdf(self):
        f = D.report_pdf(
            self.sdb,
            "Tools Station Analytics",
            ["2nd Type", "Item Description", "Current Site", "Current Location", "Status", "Qty", "Custodians", "Serials", "Rows"],
            [[r.get("second_type", ""), r.get("instrument_desc", ""), r.get("site", ""), r.get("location", ""),
              r.get("status", ""), float(r.get("qty") or 0), r.get("custodians", ""), r.get("serials", ""),
              int(r.get("record_count") or 0)]
             for r in self.rows],
            subtitle="Current transferred-material view grouped by 2nd type, item and site",
        )
        self.last_file = f
        W.toast(self, f"Exported {f.name}")
        D.open_path(f)


class AnalyticsPage(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.sdb = SV.SurveyorDB(SV.db_path(), current_user=getattr(db, "current_user", "admin"))

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        head = QLabel(
            "📈  <b>Analytics</b> — separate transferred-material visibility for Tools Station, "
            "showing where every 2nd Type item currently is by site, location and live quantity."
        )
        head.setWordWrap(True)
        v.addWidget(head)
        self.analytics = AnalyticsTab(self.sdb)
        v.addWidget(self.analytics, 1)

    def refresh(self):
        self.sdb.current_user = getattr(self.db, "current_user", "admin")
        self.analytics.reload()


class SurveyorToolsPage(QWidget):
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.sdb = SV.SurveyorDB(SV.db_path(), current_user=getattr(db, "current_user", "admin"))

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        head = QLabel(
            "🧭  <b>Tools Station</b> — keep serial numbers, 2nd type classification, locations, custody transfers, status, "
            "pictures, analytics and a sheet-style summary for tools, devices, instruments and other survey or site assets."
        )
        head.setWordWrap(True)
        v.addWidget(head)

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(W.button("Back Up Module", slot=self.backup))
        v.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.dash = DashboardTab(self.sdb)
        self.register = RegisterTab(self.sdb, db)
        self.importer = SurveyorImportTab(self.sdb, db)
        self.summary = SummaryTab(self.sdb)
        self.analytics = AnalyticsTab(self.sdb)
        self.tabs.addTab(self.dash, "📊 Dashboard")
        self.tabs.addTab(self.register, "📋 Register")
        self.tabs.addTab(self.importer, "⬆ Import Sheet")
        self.tabs.addTab(self.summary, "🧾 Summary Sheet")
        self.tabs.addTab(self.analytics, "📈 Analytics")
        v.addWidget(self.tabs, 1)

        self.register.dataChanged.connect(self._after_register_change)
        self.importer.imported.connect(self._after_register_change)
        self.refresh()

    def backup(self):
        p = self.sdb.backup(note="manual backup")
        W.info_box(self, f"Tools Station backed up to:\n\n{p}")

    def _after_register_change(self):
        self.refresh()
        self.dataChanged.emit()

    def refresh(self):
        self.sdb.current_user = getattr(self.db, "current_user", "admin")
        self.register.reload()
        self.summary.reload()
        self.analytics.reload()
        self.dash.reload()
