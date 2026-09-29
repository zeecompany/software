"""SURVEYOR TOOLS RECORD — serials, photos, summary sheet and dashboard."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import surveyor_tools as SV
from ..core.database import Database
from . import widgets as W

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
    def __init__(self, record: dict | None = None, parent=None):
        super().__init__(parent)
        self.record = dict(record or {})
        self.setWindowTitle("Surveyor Tools Record — " + ("Edit Record" if record else "New Record"))
        self.resize(760, 460)
        v = QVBoxLayout(self)

        note = QLabel("Enter the survey instrument / tool details here. The picture is optional and will be "
                      "copied into the module folder automatically.")
        note.setWordWrap(True)
        v.addWidget(note)

        body = QHBoxLayout()
        v.addLayout(body, 1)

        form_host = QWidget()
        form = QFormLayout(form_host)
        self.e_desc = QLineEdit(self.record.get("instrument_desc", ""))
        self.e_desc.setPlaceholderText("Auto Level / Total Station / GPS ...")
        self.e_serial = QLineEdit(self.record.get("serial_no", ""))
        self.e_make = QLineEdit(self.record.get("make_model", ""))
        self.e_location = W.combo(SV.DEFAULT_LOCATIONS, editable=True,
                                  current=self.record.get("location", SV.LOC_WAREHOUSE))
        self.e_qty = QDoubleSpinBox()
        self.e_qty.setDecimals(2)
        self.e_qty.setRange(0.01, 999999)
        self.e_qty.setValue(float(self.record.get("qty") or 1))
        self.e_status = W.combo(SV.STATUSES, current=self.record.get("status", SV.ST_ACTIVE))
        self.e_remarks = QPlainTextEdit(self.record.get("remarks", ""))
        self.e_remarks.setMaximumHeight(120)
        self.e_picture = QLineEdit(self.record.get("picture_path", ""))
        self.e_picture.setPlaceholderText("Optional photo path")
        pic_row = QHBoxLayout()
        pic_row.addWidget(self.e_picture, 1)
        pic_row.addWidget(W.button("Browse...", slot=self._pick_picture))
        pic_holder = QWidget()
        pic_holder.setLayout(pic_row)

        form.addRow("Instrument Description", self.e_desc)
        form.addRow("Serial No.", self.e_serial)
        form.addRow("Make / Model", self.e_make)
        form.addRow("Location", self.e_location)
        form.addRow("Quantity", self.e_qty)
        form.addRow("Status", self.e_status)
        form.addRow("Remarks", self.e_remarks)
        form.addRow("Picture", pic_holder)
        body.addWidget(form_host, 2)

        side = W.Card("Picture preview")
        self.preview = QLabel()
        self.preview.setMinimumSize(260, 260)
        self.preview.resize(260, 260)
        side.add(self.preview, 1)
        side.add(QLabel("Tip: use one row per serial number when possible. For items without serials, "
                        "you can keep Serial No. blank and use Quantity."))
        body.addWidget(side, 1)
        self._refresh_preview()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

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
            "serial_no": self.e_serial.text().strip(),
            "make_model": self.e_make.text().strip(),
            "location": self.e_location.currentText().strip(),
            "qty": float(self.e_qty.value()),
            "status": self.e_status.currentText().strip(),
            "remarks": self.e_remarks.toPlainText().strip(),
            "picture_path": self.e_picture.text().strip(),
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
        self.f_text = W.SearchBox("Filter the dashboard — description, serial, location, remarks ...")
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

    def __init__(self, sdb: SV.SurveyorDB, parent=None):
        super().__init__(parent)
        self.sdb = sdb
        self.records: list[dict] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QWidget()
        bar.setObjectName("Card")
        bl = QGridLayout(bar)
        bl.setContentsMargins(10, 8, 10, 8)
        self.f_text = W.SearchBox("Search description, serial no., location, make/model, remarks ...")
        self.f_desc = W.combo(["All Instruments"], editable=False)
        self.f_loc = W.combo(["All Locations"] + SV.DEFAULT_LOCATIONS, editable=True)
        self.f_status = W.combo(["All Status"] + SV.STATUSES)
        for w in (self.f_text, self.f_desc, self.f_loc, self.f_status):
            if hasattr(w, "textChanged"):
                w.textChanged.connect(self.reload)
            else:
                w.currentTextChanged.connect(self.reload)
        bl.addWidget(self.f_text, 0, 0, 1, 3)
        bl.addWidget(self.f_desc, 0, 3)
        bl.addWidget(self.f_loc, 0, 4)
        bl.addWidget(self.f_status, 0, 5)
        for i, (txt, slot) in enumerate((
                ("Add", self.add_record),
                ("Edit", self.edit_record),
                ("Delete", self.delete_record),
                ("Open Picture", self.open_picture),
                ("Export", self.export_excel),
                ("Reset", self.reset_filters),
        ), start=6):
            bl.addWidget(W.button(txt, "Accent" if txt == "Add" else "", slot=slot), 0, i)
        v.addWidget(bar)

        split = QSplitter()
        split.setChildrenCollapsible(False)
        v.addWidget(split, 1)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.table = W.DataTable(["ID", "Instrument Description", "Serial No.", "Make / Model",
                                  "Location", "Status", "Qty", "Picture", "Remarks", "Updated"])
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
        split.addWidget(self.detail)
        split.setSizes([950, 360])

    def _filters(self) -> dict:
        desc = self.f_desc.currentText().strip()
        loc = self.f_loc.currentText().strip()
        stat = self.f_status.currentText().strip()
        return {
            "text": self.f_text.text().strip(),
            "instrument_desc": "" if desc == "All Instruments" else desc,
            "location": "" if loc == "All Locations" else loc,
            "status": "" if stat == "All Status" else stat,
        }

    def reload_filters(self):
        cur_desc = self.f_desc.currentText()
        cur_loc = self.f_loc.currentText()
        descs = ["All Instruments"] + SV.distinct_values(self.sdb, "instrument_desc")
        locs = ["All Locations"] + sorted({*SV.DEFAULT_LOCATIONS, *SV.distinct_values(self.sdb, 'location')})
        self.f_desc.blockSignals(True)
        self.f_desc.clear(); self.f_desc.addItems(descs)
        if cur_desc in descs:
            self.f_desc.setCurrentText(cur_desc)
        self.f_desc.blockSignals(False)
        self.f_loc.blockSignals(True)
        self.f_loc.clear(); self.f_loc.addItems(locs)
        if cur_loc in locs:
            self.f_loc.setCurrentText(cur_loc)
        self.f_loc.blockSignals(False)

    def reset_filters(self):
        self.f_text.clear()
        self.f_desc.setCurrentIndex(0)
        self.f_loc.setCurrentIndex(0)
        self.f_status.setCurrentIndex(0)
        self.reload()

    def reload(self):
        self.reload_filters()
        self.records = SV.list_records(self.sdb, **self._filters())
        self.table.fill(
            ["ID", "Instrument Description", "Serial No.", "Make / Model",
             "Location", "Status", "Qty", "Picture", "Remarks", "Updated"],
            [[r["id"], r.get("instrument_desc", ""), r.get("serial_no", ""), r.get("make_model", ""),
              r.get("location", ""), r.get("status", ""), float(r.get("qty") or 0),
              ("Yes" if r.get("picture_path") else ""), r.get("remarks", ""),
              r.get("updated_at", "") or r.get("created_at", "")]
             for r in self.records],
        )
        self.table.setColumnHidden(0, True)
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
        else:
            _set_preview(self.lbl_pic, "")
            self.lbl_detail.setText("No records match the current filters.")

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
            return
        _set_preview(self.lbl_pic, rec.get("picture_path", ""))
        self.lbl_detail.setText(
            "<b>Description:</b> {0}<br>"
            "<b>Serial No.:</b> {1}<br>"
            "<b>Make / Model:</b> {2}<br>"
            "<b>Location:</b> {3}<br>"
            "<b>Status:</b> {4}<br>"
            "<b>Quantity:</b> {5}<br>"
            "<b>Remarks:</b> {6}<br>"
            "<b>Picture:</b> {7}<br>"
            "<b>Updated:</b> {8}"
            .format(
                rec.get("instrument_desc", "") or "—",
                rec.get("serial_no", "") or "—",
                rec.get("make_model", "") or "—",
                rec.get("location", "") or "—",
                rec.get("status", "") or "—",
                _fmt_qty(rec.get("qty", 0)),
                rec.get("remarks", "") or "—",
                rec.get("picture_path", "") or "—",
                rec.get("updated_at", "") or rec.get("created_at", "") or "—",
            )
        )

    def add_record(self):
        dlg = RecordDialog(parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            SV.save_record(self.sdb, dlg.data())
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.reload()
        self.dataChanged.emit()
        W.toast(self, "Surveyor tool record saved.")

    def edit_record(self):
        rec = self._current()
        if not rec:
            return
        dlg = RecordDialog(rec, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            SV.save_record(self.sdb, dlg.data(), int(rec["id"]))
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.reload()
        self.dataChanged.emit()
        W.toast(self, "Surveyor tool record updated.")

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
            "Surveyor Tools Register",
            ["Instrument Description", "Serial No.", "Make / Model", "Location", "Status", "Qty", "Picture", "Remarks", "Updated"],
            [[r.get("instrument_desc", ""), r.get("serial_no", ""), r.get("make_model", ""),
              r.get("location", ""), r.get("status", ""), float(r.get("qty") or 0),
              r.get("picture_path", ""), r.get("remarks", ""),
              r.get("updated_at", "") or r.get("created_at", "")]
             for r in self.records],
        )
        W.toast(self, f"Exported {f.name}")
        D.open_path(f)


class SummaryTab(QWidget):
    def __init__(self, sdb: SV.SurveyorDB, parent=None):
        super().__init__(parent)
        self.sdb = sdb
        self.rows: list[dict] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("This sheet matches the supplied surveyor tools summary layout and is built automatically from the register."))
        bar.addStretch(1)
        bar.addWidget(W.button("Export", slot=self.export_excel))
        bar.addWidget(W.button("Refresh", slot=self.reload))
        v.addLayout(bar)

        self.table = W.DataTable(["SR#", "Instrument Description", "Warehouse", "Hajar", "Zuluf",
                                  "Yanbu", "Noor", "Total Quantity", "Remarks"])
        v.addWidget(self.table, 1)

    def reload(self):
        self.rows = SV.summary_rows(self.sdb)
        self.table.fill(
            ["SR#", "Instrument Description", "Warehouse", "Hajar", "Zuluf",
             "Yanbu", "Noor", "Total Quantity", "Remarks"],
            [[r["sr"], r["instrument_desc"], float(r["Warehouse"]), float(r["Hajar"]),
              float(r["Zuluf"]), float(r["Yanbu"]), float(r["Noor"]),
              float(r["total_qty"]), r["remarks"]]
             for r in self.rows],
        )

    def export_excel(self):
        f = D.export_excel(
            self.sdb,
            "Surveyor Tools Record",
            ["SR#", "Instrument Description", "Warehouse", "Hajar", "Zuluf",
             "Yanbu", "Noor", "Total Quantity", "Remarks"],
            [[r["sr"], r["instrument_desc"], float(r["Warehouse"]), float(r["Hajar"]),
              float(r["Zuluf"]), float(r["Yanbu"]), float(r["Noor"]),
              float(r["total_qty"]), r["remarks"]]
             for r in self.rows],
        )
        W.toast(self, f"Exported {f.name}")
        D.open_path(f)


class SurveyorToolsPage(QWidget):
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.sdb = SV.SurveyorDB(SV.db_path(), current_user=getattr(db, "current_user", "admin"))

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        head = QLabel(
            "🧭  <b>Surveyor Tools Record</b> — keep serial numbers, locations, status, pictures and a "
            "sheet-style summary for Auto Levels, Total Stations, GPS units and other survey instruments."
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
        self.register = RegisterTab(self.sdb)
        self.summary = SummaryTab(self.sdb)
        self.tabs.addTab(self.dash, "📊 Dashboard")
        self.tabs.addTab(self.register, "📋 Register")
        self.tabs.addTab(self.summary, "🧾 Summary Sheet")
        v.addWidget(self.tabs, 1)

        self.register.dataChanged.connect(self._after_register_change)
        self.refresh()

    def backup(self):
        p = self.sdb.backup(note="manual backup")
        W.info_box(self, f"Surveyor Tools Record backed up to:\n\n{p}")

    def _after_register_change(self):
        self.refresh()
        self.dataChanged.emit()

    def refresh(self):
        self.sdb.current_user = getattr(self.db, "current_user", "admin")
        self.register.reload()
        self.summary.reload()
        self.dash.reload()
