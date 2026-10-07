"""INSTRUMENT STATION — the register, the dashboard and the movement track.

Five tabs, and nothing else:

    📊 Dashboard       KPI tiles and charts built from the register columns
    🔧 Instruments     the register itself — the Excel columns, in Excel order
    🔁 Movements       every handover, transfer and return, with dates
    📊 Excel Sync      read the sites' Excel sheets straight into the register
    📈 Reports         the same data on paper / in Excel

Every custody change goes through one dialog: **Issue · Transfer · Return**.
Typing an Employee Code (or an Iqama ID) fills the name, designation,
division and project from the Employee Master automatically, and the details of
that day are stamped onto the movement row — so the history still shows who was
holding the instrument and where it went, years later.

Nothing in this file imports the stock engine.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QScrollArea, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import toolstation as T
from ..core.database import Database
from . import widgets as W
from .common import ShareBar, date_edit, iso

#: the register grid — the Excel headings, in the Excel order
REGISTER_COLS: list[str] = [label for _, label in T.COLUMNS]
PICTURE_COL = "Picture"
GRID_COLS: list[str] = ["#"] + REGISTER_COLS + [PICTURE_COL]
STATUS_COL = 1 + REGISTER_COLS.index("Status")


def _paint(table: W.DataTable, col: int, colors: dict) -> None:
    """Tint a column using the module's colour map."""
    for r in range(table.rowCount()):
        it = table.item(r, col)
        if it is None:
            continue
        c = colors.get(it.text())
        if c:
            it.setForeground(QBrush(QColor(c)))
            f = QFont(it.font())
            f.setBold(True)
            it.setFont(f)


def _row_values(rec: dict, index: int) -> list:
    """One register row exactly as the sheet reads, left to right."""
    out: list = [index]
    for key, _ in T.COLUMNS:
        val = rec.get(key, "")
        out.append(T.fmt_qty(val) if key == "quantity" else val)
    out.append("✓" if str(rec.get("picture_path") or "").strip() else "")
    return out


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
    label.setPixmap(pm.scaled(label.size() * 0.98, Qt.KeepAspectRatio,
                              Qt.SmoothTransformation))


# ============================================================== picture tools
class PictureViewer(QDialog):
    """Show an attached picture at full size."""

    def __init__(self, path: str, title: str = "Instrument picture", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 680)
        v = QVBoxLayout(self)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl, 1)
        pm = QPixmap(str(path))
        if pm.isNull():
            lbl.setText("This picture could not be read.")
        else:
            lbl.setPixmap(pm.scaled(860, 620, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)


class PictureBox(QGroupBox):
    """Attach one picture to an instrument — copied into the module folder."""

    changed = Signal()

    def __init__(self, path: str = "", hint: str = "", parent=None):
        super().__init__("Picture proof")
        self.path = str(path or "")
        self.hint = hint or "instrument"
        v = QVBoxLayout(self)
        self.preview = QLabel("No picture")
        self.preview.setMinimumSize(240, 170)
        _set_preview(self.preview, self.path)
        v.addWidget(self.preview, 1)
        row = QHBoxLayout()
        row.addWidget(W.button("📷  Choose picture...", slot=self._choose))
        row.addWidget(W.button("👁  View", slot=self._view))
        row.addWidget(W.button("✖  Remove", slot=self._clear))
        row.addStretch(1)
        v.addLayout(row)

    def _choose(self):
        exts = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff)"
        file, _ = QFileDialog.getOpenFileName(self, "Choose a picture", "", exts)
        if not file:
            return
        stored = T.store_picture(file, self.hint or Path(file).stem)
        self.path = stored or file
        _set_preview(self.preview, self.path)
        self.changed.emit()

    def _view(self):
        if not self.path or not Path(self.path).exists():
            W.info_box(self, "No picture is attached to this instrument yet.")
            return
        PictureViewer(self.path, "Instrument picture", self).exec()

    def _clear(self):
        self.path = ""
        _set_preview(self.preview, "")
        self.changed.emit()

    def set_path(self, path: str):
        self.path = str(path or "")
        _set_preview(self.preview, self.path)


# ============================================================ employee fields
class EmployeeFields(QGroupBox):
    """Name, code and the employee details the code brings with it."""

    def __init__(self, db_main: Database, record: dict | None = None, parent=None):
        super().__init__("Issued To / Employee")
        self.db_main = db_main
        rec = dict(record or {})
        self._filling = False

        v = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        v.addLayout(grid)

        self.e_code = QLineEdit(str(rec.get("employee_code") or ""))
        self.e_code.setPlaceholderText("Type the Employee Code — the rest fills in")
        self.e_name = QComboBox()
        self.e_name.setEditable(True)
        self.e_name.addItem("")
        for name in self._employee_names():
            self.e_name.addItem(name)
        self.e_name.setCurrentText(str(rec.get("issued_to") or ""))
        self.e_iqama = QLineEdit(str(rec.get("iqama_id") or ""))
        self.e_designation = QLineEdit(str(rec.get("designation") or ""))
        self.e_division = QLineEdit(str(rec.get("division") or ""))
        self.e_project = QLineEdit(str(rec.get("current_project") or ""))
        self.e_location = QLineEdit(str(rec.get("location") or ""))

        grid.addWidget(QLabel("Employee Code"), 0, 0)
        grid.addWidget(self.e_code, 0, 1)
        grid.addWidget(QLabel("Issued To / Employee Name"), 0, 2)
        grid.addWidget(self.e_name, 0, 3)
        grid.addWidget(QLabel("Iqama ID"), 0, 4)
        grid.addWidget(self.e_iqama, 0, 5)
        grid.addWidget(QLabel("Designation"), 1, 0)
        grid.addWidget(self.e_designation, 1, 1)
        grid.addWidget(QLabel("Division/Department"), 1, 2)
        grid.addWidget(self.e_division, 1, 3)
        grid.addWidget(QLabel("Current Project"), 1, 4)
        grid.addWidget(self.e_project, 1, 5)
        grid.addWidget(QLabel("Location"), 2, 0)
        grid.addWidget(self.e_location, 2, 1, 1, 2)
        grid.addWidget(W.button("🔍  Fill from Employee Master", slot=self.fill_from_master,
                                tip="Read the name, Iqama, designation, division and "
                                    "project for this Employee Code"), 2, 3, 1, 3)

        self.note = QLabel()
        self.note.setStyleSheet(f"color:{W.MUTED};")
        self.note.setWordWrap(True)
        v.addWidget(self.note)

        self.e_code.editingFinished.connect(self.fill_from_master)
        self.e_code.returnPressed.connect(self.fill_from_master)
        self.e_name.currentTextChanged.connect(self._name_changed)
        self.e_iqama.editingFinished.connect(self.fill_from_master)

    # ------------------------------------------------------------------ data
    def _employee_names(self) -> list[str]:
        try:
            return [c["issued_to"] for c in T.employee_choices(self.db_main)
                    if c.get("issued_to")]
        except Exception:          # noqa: BLE001
            return []

    def _name_changed(self, text: str):
        if self._filling or not text:
            return
        self._filling = True
        try:
            self.fill_from_master()
        finally:
            self._filling = False

    def fill_from_master(self, *_):
        """Look the person up in the Employee Master and fill what is blank."""
        code = self.e_code.text().strip()
        iqama = self.e_iqama.text().strip()
        name = self.e_name.currentText().strip()
        if not (code or iqama or name):
            return
        found = T.employee_lookup(self.db_main, code, iqama, name)
        if not found:
            self.note.setText(
                "Not found in the Employee Master — the details you type here are "
                "still saved with the instrument.")
            self.note.setStyleSheet(f"color:{W.AMBER};")
            return
        self._filling = True
        try:
            if found.get("employee_code") and not code:
                self.e_code.setText(found["employee_code"])
            if found.get("issued_to"):
                self.e_name.setCurrentText(found["issued_to"])
            if found.get("iqama_id") and not iqama:
                self.e_iqama.setText(found["iqama_id"])
            for widget, key in ((self.e_designation, "designation"),
                                (self.e_division, "division"),
                                (self.e_project, "current_project"),
                                (self.e_location, "location")):
                if not widget.text().strip() and found.get(key):
                    widget.setText(found[key])
        finally:
            self._filling = False
        self.note.setText("Filled from the Employee Master.")
        self.note.setStyleSheet(f"color:{W.GREEN};")

    # --------------------------------------------------------------- reading
    def values(self) -> dict:
        return {
            "employee_code": self.e_code.text().strip(),
            "issued_to": self.e_name.currentText().strip(),
            "iqama_id": self.e_iqama.text().strip(),
            "designation": self.e_designation.text().strip(),
            "division": self.e_division.text().strip(),
            "current_project": self.e_project.text().strip(),
            "location": self.e_location.text().strip(),
        }

    def clear(self):
        self._filling = True
        try:
            for widget in (self.e_code, self.e_iqama, self.e_designation,
                           self.e_division, self.e_project, self.e_location):
                widget.setText("")
            self.e_name.setCurrentText("")
        finally:
            self._filling = False
        self.note.setText("")


# ============================================================= entry dialogs
class InstrumentDialog(QDialog):
    """Manual entry — one instrument, every column of the sheet, plus a picture."""

    def __init__(self, db: Database, tdb: T.ToolDB, record: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.db = db
        self.tdb = tdb
        self.record = dict(record or {})
        self.new = not self.record.get("id")
        self.setWindowTitle("Instrument Station — "
                            + ("New Instrument Entry" if self.new else "Edit Instrument"))
        self.resize(1040, 700)
        v = QVBoxLayout(self)
        v.setSpacing(8)

        head = QLabel(
            "Enter the instrument exactly as it appears on the site sheet. The "
            "Employee Code fills the name, Iqama, designation, division and project "
            "from the Employee Master — add a picture to prove the handover.")
        head.setWordWrap(True)
        head.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(head)

        body = QHBoxLayout()
        v.addLayout(body, 1)

        left = QWidget()
        form = QFormLayout(left)
        form.setLabelAlignment(Qt.AlignRight)
        self.e_desc = QLineEdit(str(self.record.get("instrument_desc") or ""))
        self.e_desc.setPlaceholderText("TOTAL STATION / AUTO LEVEL / GPS ...")
        self.e_serial = QLineEdit(str(self.record.get("serial_no") or ""))
        self.e_make = QLineEdit(str(self.record.get("make_model") or ""))
        self.e_make.setPlaceholderText("LEICA (TS02) ...")
        self.c_location = W.combo(
            sorted({*T.distinct_values(self.tdb, "location"), "Warehouse"}),
            editable=True, current=str(self.record.get("location") or "Warehouse"))
        self.s_qty = QDoubleSpinBox()
        self.s_qty.setDecimals(2)
        self.s_qty.setRange(0, 1_000_000)
        self.s_qty.setValue(T.to_float(self.record.get("quantity"), 1) or 1)
        self.c_status = W.combo(T.STATUSES, editable=True,
                                current=str(self.record.get("status") or T.ST_AVAILABLE))
        self.e_issued_by = QLineEdit(str(self.record.get("issued_by") or ""))
        self.e_remarks = QPlainTextEdit(str(self.record.get("remarks") or ""))
        self.e_remarks.setFixedHeight(70)

        form.addRow("Instrument Description *", self.e_desc)
        form.addRow("Serial No.", self.e_serial)
        form.addRow("Make / Model", self.e_make)
        form.addRow("Location", self.c_location)
        form.addRow("Quantity", self.s_qty)
        form.addRow("Status", self.c_status)
        form.addRow("Issued By", self.e_issued_by)
        form.addRow("Remarks", self.e_remarks)
        body.addWidget(left, 3)

        right = QVBoxLayout()
        body.addLayout(right, 2)
        self.employee = EmployeeFields(db, self.record)
        right.addWidget(self.employee)
        self.picture = PictureBox(str(self.record.get("picture_path") or ""),
                                  hint=str(self.record.get("serial_no")
                                           or self.record.get("instrument_desc")
                                           or "instrument"))
        self.picture.preview.setMinimumSize(220, 200)
        right.addWidget(self.picture, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("💾  Save Instrument")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _save(self):
        data = {
            "instrument_desc": self.e_desc.text().strip(),
            "serial_no": self.e_serial.text().strip(),
            "make_model": self.e_make.text().strip(),
            "location": self.c_location.currentText().strip(),
            "quantity": self.s_qty.value(),
            "status": self.c_status.currentText().strip(),
            "issued_by": self.e_issued_by.text().strip(),
            "remarks": self.e_remarks.toPlainText().strip(),
            "picture_path": self.picture.path,
        }
        data.update(self.employee.values())
        if not data["instrument_desc"] and not data["serial_no"]:
            W.error_box(self, "Enter at least the Instrument Description or the Serial No.")
            return
        try:
            row = T.save_instrument(
                self.tdb, data,
                instrument_id=int(self.record["id"]) if self.record.get("id") else None,
                source="Manual Entry", db_main=self.db)
        except ValueError as exc:
            W.error_box(self, str(exc))
            return
        self.saved = row
        W.toast(self, "Instrument saved." if self.new else "Instrument updated.")
        self.accept()


class MovementDialog(QDialog):
    """One dialog for Issue · Transfer · Return — the custody track."""

    def __init__(self, db: Database, tdb: T.ToolDB, record: dict,
                 action: str = T.ACTION_ISSUE, parent=None):
        super().__init__(parent)
        self.db = db
        self.tdb = tdb
        self.record = dict(record or {})
        self.action = action
        self.setWindowTitle(f"Instrument Station — {action} Instrument")
        self.resize(980, 620)
        v = QVBoxLayout(self)
        v.setSpacing(8)

        title = QLabel(f"<b>{action}: {T.instrument_title(self.record)}</b>")
        v.addWidget(title)
        current = (f"Currently with <b>{self.record.get('issued_to') or '— store —'}</b>"
                   f"{' · code ' + str(self.record.get('employee_code')) if self.record.get('employee_code') else ''}"
                   f" · location {self.record.get('location') or '—'}"
                   f" · status {self.record.get('status') or '—'}")
        lbl = QLabel(current)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(lbl)

        top = QWidget()
        form = QFormLayout(top)
        self.d_date = date_edit(_dt.date.today().isoformat())
        self.s_qty = QDoubleSpinBox()
        self.s_qty.setDecimals(2)
        self.s_qty.setRange(0, 1_000_000)
        self.s_qty.setValue(T.to_float(self.record.get("quantity"), 1) or 1)
        form.addRow("Date", self.d_date)
        form.addRow("Quantity", self.s_qty)
        v.addWidget(top)

        if action == T.ACTION_RETURN:
            info = QLabel(
                "Return takes the instrument back from the current holder. "
                "The holder fields are cleared and the instrument goes back to store.")
            info.setWordWrap(True)
            v.addWidget(info)
            self.employee = None
        else:
            self.employee = EmployeeFields(db, {})
            v.addWidget(self.employee)
            if action == T.ACTION_TRANSFER:
                self.employee.note.setText(
                    "Transfer: pick the employee taking over. The history keeps the "
                    "person handing it over as well.")

        self.c_status = W.combo(
            T.STATUSES, editable=True,
            current=(T.ST_AVAILABLE if action == T.ACTION_RETURN else T.ST_ISSUED))
        self.e_issued_by = QLineEdit(str(self.record.get("issued_by") or ""))
        self.e_remarks = QLineEdit()
        self.e_remarks.setPlaceholderText("Condition, accessories, anything worth noting")
        row = QWidget()
        form2 = QFormLayout(row)
        form2.addRow("Status after", self.c_status)
        form2.addRow("Issued By", self.e_issued_by)
        form2.addRow("Remarks", self.e_remarks)
        v.addWidget(row)

        self.picture = PictureBox("", hint=str(self.record.get("serial_no") or "instrument"))
        self.picture.setMaximumHeight(220)
        v.addWidget(self.picture)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(f"✔  Save {action}")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _save(self):
        kwargs: dict = {
            "movement_date": iso(self.d_date),
            "quantity": self.s_qty.value(),
            "status_after": self.c_status.currentText().strip(),
            "issued_by": self.e_issued_by.text().strip(),
            "remarks": self.e_remarks.text().strip(),
            "picture_path": self.picture.path,
            "source": "Manual Entry",
            "db_main": self.db,
        }
        values = self.employee.values() if self.employee else {}
        if self.employee:
            kwargs.update({
                "to_holder": values.get("issued_to", ""),
                "to_employee_code": values.get("employee_code", ""),
                "iqama_id": values.get("iqama_id", ""),
                "designation": values.get("designation", ""),
                "division": values.get("division", ""),
                "current_project": values.get("current_project", ""),
                "location": values.get("location", "") or self.record.get("location", ""),
            })
        else:
            kwargs["location"] = self.record.get("location", "")
        fn = {T.ACTION_ISSUE: T.issue_instrument,
              T.ACTION_TRANSFER: T.transfer_instrument,
              T.ACTION_RETURN: T.return_instrument}[self.action]
        try:
            self.movement = fn(self.tdb, int(self.record["id"]), **kwargs)
        except ValueError as exc:
            W.error_box(self, str(exc))
            return
        W.toast(self, f"{self.action} saved on {T.fmt_date(iso(self.d_date))}.")
        self.accept()


# ================================================================= dashboard
class InstrumentDashboard(QWidget):
    """KPI tiles and charts, all from the register columns."""

    openRegister = Signal(dict)

    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.cards: dict[str, W.StatCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        bar = QWidget()
        bar.setObjectName("Card")
        gl = QGridLayout(bar)
        gl.setContentsMargins(10, 8, 10, 8)
        self.f_text = W.SearchBox("Search instrument, serial, employee, project ...")
        self.f_text.textChanged.connect(self.reload)
        self.f_status = W.combo(["All Status"] + T.STATUSES)
        self.f_location = W.combo(["All Locations"], editable=True)
        self.f_project = W.combo(["All Projects"], editable=True)
        for widget in (self.f_status, self.f_location, self.f_project):
            widget.currentTextChanged.connect(self.reload)
        self.chk_issued = QCheckBox("Issued / with an employee only")
        self.chk_issued.toggled.connect(self.reload)
        gl.addWidget(self.f_text, 0, 0, 1, 3)
        gl.addWidget(self.f_status, 0, 3)
        gl.addWidget(self.f_location, 0, 4)
        gl.addWidget(self.f_project, 0, 5)
        gl.addWidget(self.chk_issued, 1, 0, 1, 2)
        gl.addWidget(W.button("♻  Reset", slot=self.clear_filters), 1, 4)
        gl.addWidget(W.button("🔄  Refresh", slot=self.reload), 1, 5)
        outer.addWidget(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, 1)
        host = QWidget()
        scroll.setWidget(host)
        v = QVBoxLayout(host)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(10)

        tiles = [("rows", "Instruments", "🔧", W.NAVY, {}),
                 ("quantity", "Total Quantity", "Σ", "#0b6e83", {}),
                 ("issued", "Issued / With Employee", "📤", "#1098ad",
                  {"issued_only": True}),
                 ("available", "In Store", "🏠", "#1a9c52", {}),
                 ("holders", "Employees Holding", "👥", "#7048e8",
                  {"issued_only": True}),
                 ("sites", "Locations", "📍", "#e8590c", {}),
                 ("movements_30", "Movements (30 days)", "🔁", "#c92a2a", {}),
                 ("pictures", "With Picture", "📷", "#6b7c8f", {})]
        grid = QGridLayout()
        for i, (key, label, glyph, color, drill) in enumerate(tiles):
            card = W.StatCard(label, glyph=glyph, color=color)
            card.setToolTip("Click to see these instruments in the register")
            card.clicked.connect(
                lambda k=key, d=drill: self._drill(k, d))
            self.cards[key] = card
            grid.addWidget(card, i // 4, i % 4)
        v.addLayout(grid)

        row1 = QHBoxLayout()
        c1 = W.Card("Status of every instrument")
        self.c_status = W.DonutChart()
        self.c_status.setMinimumHeight(210)
        c1.add(self.c_status, 1)
        row1.addWidget(c1, 1)
        c2 = W.Card("Where the instruments are (Location)")
        self.c_location = W.BarChart([], color="#14538f")
        self.c_location.barClicked.connect(
            lambda loc: self._drill("location", {"location": loc}))
        c2.add(self.c_location, 1)
        row1.addWidget(c2, 1)
        v.addLayout(row1, 1)

        row2 = QHBoxLayout()
        c3 = W.Card("Who is holding instruments (Employee)")
        self.c_employee = W.BarChart([], color="#7048e8", horizontal=True)
        self.c_employee.barClicked.connect(
            lambda who: self._drill("employee", {"holder": who}))
        c3.add(self.c_employee, 1)
        row2.addWidget(c3, 1)
        c4 = W.Card("Instruments by description")
        self.c_desc = W.BarChart([], color="#1098ad", horizontal=True)
        self.c_desc.barClicked.connect(
            lambda d: self._drill("description", {"text": d}))
        c4.add(self.c_desc, 1)
        row2.addWidget(c4, 1)
        v.addLayout(row2, 1)

        row3 = QHBoxLayout()
        c5 = W.Card("Project-wise distribution")
        self.c_project = W.BarChart([], color="#e8590c", horizontal=True)
        c5.add(self.c_project, 1)
        row3.addWidget(c5, 1)
        c6 = W.Card("Handovers per month (issued + transferred)")
        self.c_month = W.LineChart()
        self.c_month.setMinimumHeight(190)
        c6.add(self.c_month, 1)
        row3.addWidget(c6, 1)
        v.addLayout(row3, 1)

        c7 = W.Card("Latest movements — who took what, and when")
        self.t_recent = W.DataTable()
        self.t_recent.setMaximumHeight(260)
        c7.add(self.t_recent, 1)
        v.addWidget(c7)
        v.addStretch(1)

    # ------------------------------------------------------------------ data
    def filters(self) -> dict:
        f: dict = {"text": self.f_text.text().strip()}
        if self.f_status.currentText() not in ("", "All Status"):
            f["status"] = self.f_status.currentText()
        if self.f_location.currentText() not in ("", "All Locations"):
            f["location"] = self.f_location.currentText()
        if self.f_project.currentText() not in ("", "All Projects"):
            f["project"] = self.f_project.currentText()
        if self.chk_issued.isChecked():
            f["issued_only"] = True
        return f

    def clear_filters(self):
        self.f_text.blockSignals(True)
        self.f_text.clear()
        self.f_text.blockSignals(False)
        self.f_status.setCurrentIndex(0)
        self.f_location.setCurrentText("All Locations")
        self.f_project.setCurrentText("All Projects")
        self.chk_issued.setChecked(False)
        self.reload()

    def reload_filters(self):
        for widget, values, first in (
                (self.f_location, T.distinct_values(self.tdb, "location"), "All Locations"),
                (self.f_project, T.distinct_values(self.tdb, "current_project"),
                 "All Projects")):
            current = widget.currentText()
            widget.blockSignals(True)
            widget.clear()
            widget.addItem(first)
            widget.addItems(values)
            widget.setCurrentText(current or first)
            widget.blockSignals(False)

    def reload(self):
        self.reload_filters()
        d = T.dashboard(self.tdb, self.filters())
        self.cards["rows"].set_value(f"{d['rows']:,}", "rows in the register")
        self.cards["quantity"].set_value(T.fmt_qty(d["quantity"]), "pieces on the sheet")
        self.cards["issued"].set_value(f"{d['issued']:,}", "with an employee")
        self.cards["available"].set_value(f"{d['available']:,}", "not handed out")
        self.cards["holders"].set_value(f"{d['holders']:,}", "employees")
        self.cards["sites"].set_value(f"{d['sites']:,}", "locations")
        self.cards["movements_30"].set_value(f"{d['movements_30']:,}", "handovers")
        self.cards["pictures"].set_value(f"{d['pictures']:,}", "with a picture")

        self.c_status.set_data([(s, n, T.STATUS_COLORS.get(s, W.NAVY))
                                for s, n in d["by_status"]])
        self.c_location.set_data(d["by_location"])
        self.c_employee.set_data(d["by_employee"])
        self.c_desc.set_data(d["by_description"])
        self.c_project.set_data(d["by_project"])
        self.c_month.set_data([(m, v) for m, v in d["monthly"]])

        rows = [[T.fmt_date(m.get("movement_date", "")), m.get("movement_type", ""),
                 m.get("instrument_desc", ""), m.get("serial_no", ""),
                 m.get("from_holder", "") or "—", m.get("to_holder", "") or "—",
                 m.get("to_employee_code", ""), m.get("location", ""),
                 T.fmt_qty(m.get("quantity"))]
                for m in d["recent"]]
        self.t_recent.fill(["Date", "Movement", "Instrument Description", "Serial No.",
                            "From", "To", "Employee Code", "Location", "Quantity"], rows)
        _paint(self.t_recent, 1, T.MOVEMENT_COLORS)

    def _drill(self, key: str, extra: dict):
        f = self.filters()
        f.update(extra)
        self.openRegister.emit(f)


# ================================================================== register
class RegisterTab(QWidget):
    """The register itself — the sheet columns, in the sheet order."""

    changed = Signal()
    openMovements = Signal(int)

    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.rows: list[dict] = []
        self.detail_id: int | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        bar = QWidget()
        bar.setObjectName("Card")
        gl = QGridLayout(bar)
        gl.setContentsMargins(10, 8, 10, 8)
        self.f_text = W.SearchBox("Search any column — description, serial, employee, "
                                  "project, remarks ...")
        self.f_text.textChanged.connect(self.reload)
        self.f_status = W.combo(["All Status"] + T.STATUSES)
        self.f_location = W.combo(["All Locations"], editable=True)
        self.f_division = W.combo(["All Divisions"], editable=True)
        self.f_project = W.combo(["All Projects"], editable=True)
        for widget in (self.f_status, self.f_location, self.f_division, self.f_project):
            widget.currentTextChanged.connect(self.reload)
        self.chk_issued = QCheckBox("Issued only")
        self.chk_picture = QCheckBox("With picture")
        self.chk_issued.toggled.connect(self.reload)
        self.chk_picture.toggled.connect(self.reload)
        gl.addWidget(self.f_text, 0, 0, 1, 4)
        gl.addWidget(self.f_status, 0, 4)
        gl.addWidget(self.f_location, 0, 5)
        gl.addWidget(self.f_division, 0, 6)
        gl.addWidget(self.f_project, 0, 7)
        gl.addWidget(self.chk_issued, 1, 0)
        gl.addWidget(self.chk_picture, 1, 1)
        gl.addWidget(W.button("♻  Reset filters", slot=self.clear_filters), 1, 6)
        gl.addWidget(W.button("🔄  Refresh", slot=self.reload), 1, 7)
        v.addWidget(bar)

        act = QHBoxLayout()
        act.addWidget(W.button("➕  New Entry", "Primary", self.new_entry,
                               tip="Add one instrument by hand, with a picture"))
        act.addWidget(W.button("✏  Edit", slot=self.edit_entry))
        act.addWidget(W.button("🗑  Delete", slot=self.delete_entry))
        act.addSpacing(10)
        act.addWidget(W.button("📤  Issue", "Accent", lambda: self._action(T.ACTION_ISSUE),
                               tip="Hand the instrument to an employee"))
        act.addWidget(W.button("🔁  Transfer", slot=lambda: self._action(T.ACTION_TRANSFER),
                               tip="Move custody from one employee to another"))
        act.addWidget(W.button("📥  Return", slot=lambda: self._action(T.ACTION_RETURN),
                               tip="Take the instrument back into store"))
        act.addSpacing(10)
        act.addWidget(W.button("📷  Picture", slot=self.show_picture))
        act.addWidget(W.button("🕘  History", slot=self.show_history,
                               tip="Every handover, transfer and return for this instrument"))
        act.addStretch(1)
        act.addWidget(W.button("📊  Excel", slot=self.export_excel))
        act.addWidget(W.button("📄  PDF", slot=self.export_pdf))
        v.addLayout(act)

        split = QSplitter(Qt.Horizontal)
        v.addWidget(split, 1)

        host = QWidget()
        hv = QVBoxLayout(host)
        hv.setContentsMargins(0, 0, 0, 0)
        self.table = W.DataTable()
        self.table.setAlternatingRowColors(True)
        hv.addWidget(W.FilterBar(self.table))
        hv.addWidget(self.table, 1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        hv.addWidget(self.count)
        split.addWidget(host)

        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(6, 0, 0, 0)
        self.picture = QLabel("Select a row to see its picture")
        self.picture.setMinimumSize(260, 200)
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setStyleSheet("border:1px solid #d7dee6; border-radius:8px; "
                                   "background:#f8fafc;")
        sv.addWidget(self.picture)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.RichText)
        sv.addWidget(self.details)
        c = W.Card("Track record for this instrument")
        self.t_history = W.DataTable()
        self.t_history.setMaximumHeight(220)
        c.add(self.t_history, 1)
        sv.addWidget(c, 1)
        split.addWidget(side)
        split.setSizes([900, 430])

        self.table.itemSelectionChanged.connect(self._show_details)
        self.table.doubleClicked.connect(lambda *_: self.edit_entry())

    # --------------------------------------------------------------- filters
    def filters(self) -> dict:
        f: dict = {"text": self.f_text.text().strip()}
        if self.f_status.currentText() not in ("", "All Status"):
            f["status"] = self.f_status.currentText()
        if self.f_location.currentText() not in ("", "All Locations"):
            f["location"] = self.f_location.currentText()
        if self.f_division.currentText() not in ("", "All Divisions"):
            f["division"] = self.f_division.currentText()
        if self.f_project.currentText() not in ("", "All Projects"):
            f["project"] = self.f_project.currentText()
        if self.chk_issued.isChecked():
            f["issued_only"] = True
        if self.chk_picture.isChecked():
            f["with_picture"] = True
        return f

    def clear_filters(self):
        for widget in (self.f_text,):
            widget.blockSignals(True)
            widget.clear()
            widget.blockSignals(False)
        self.f_status.setCurrentIndex(0)
        self.f_location.setCurrentText("All Locations")
        self.f_division.setCurrentText("All Divisions")
        self.f_project.setCurrentText("All Projects")
        self.chk_issued.setChecked(False)
        self.chk_picture.setChecked(False)
        self.reload()

    def apply_filter(self, f: dict):
        f = dict(f or {})
        self.f_text.blockSignals(True)
        self.f_text.setText(str(f.get("text", "")))
        self.f_text.blockSignals(False)
        self.f_status.setCurrentText(str(f.get("status") or "All Status"))
        self.f_location.setCurrentText(str(f.get("location") or "All Locations"))
        self.f_division.setCurrentText(str(f.get("division") or "All Divisions"))
        self.f_project.setCurrentText(str(f.get("project") or "All Projects"))
        self.chk_issued.setChecked(bool(f.get("issued_only")))
        self.chk_picture.setChecked(bool(f.get("with_picture")))
        self.reload()

    def reload_filters(self):
        pairs = ((self.f_location, "location", "All Locations"),
                 (self.f_division, "division", "All Divisions"),
                 (self.f_project, "current_project", "All Projects"))
        for widget, column, first in pairs:
            current = widget.currentText()
            widget.blockSignals(True)
            widget.clear()
            widget.addItem(first)
            widget.addItems(T.distinct_values(self.tdb, column))
            widget.setCurrentText(current if current else first)
            widget.blockSignals(False)

    # ------------------------------------------------------------------ grid
    def reload(self):
        self.reload_filters()
        f = self.filters()
        self.rows = T.search_instruments(
            self.tdb, text=f.get("text", ""), status=f.get("status", ""),
            location=f.get("location", ""), division=f.get("division", ""),
            project=f.get("project", ""), issued_only=f.get("issued_only", False),
            with_picture=f.get("with_picture", False))
        keep = self.detail_id
        self.table.fill(GRID_COLS, [_row_values(r, i) for i, r in enumerate(self.rows, 1)])
        _paint(self.table, STATUS_COL, T.STATUS_COLORS)
        self.count.setText(f"{len(self.rows)} instrument(s) · "
                           f"{T.fmt_qty(sum(T.to_float(r.get('quantity'), 0) for r in self.rows))} "
                           f"total quantity")
        if keep:
            for i, r in enumerate(self.rows):
                if int(r["id"]) == int(keep):
                    self.table.selectRow(i)
                    break

    def _selected(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0 or r >= len(self.rows):
            return None
        return self.rows[r]

    def _show_details(self):
        rec = self._selected()
        self.detail_id = int(rec["id"]) if rec else None
        if not rec:
            self.picture.setText("Select a row to see its picture")
            self.picture.setPixmap(QPixmap())
            self.details.setText("")
            self.t_history.fill([], [])
            return
        _set_preview(self.picture, str(rec.get("picture_path") or ""))
        when = T.fmt_date(str(rec.get("last_movement_at") or "")) or "—"
        self.details.setText(
            f"<b>{T.instrument_title(rec)}</b><br>"
            f"<span style='color:{W.MUTED}'>Status</span> {rec.get('status') or '—'} "
            f"&nbsp;·&nbsp; <span style='color:{W.MUTED}'>Location</span> "
            f"{rec.get('location') or '—'}<br>"
            f"<span style='color:{W.MUTED}'>Issued To</span> "
            f"{rec.get('issued_to') or '— store —'}"
            f"{' (' + str(rec.get('employee_code')) + ')' if rec.get('employee_code') else ''}<br>"
            f"<span style='color:{W.MUTED}'>Last movement</span> "
            f"{rec.get('last_movement') or '—'} on {when}<br>"
            f"<span style='color:{W.MUTED}'>Source</span> "
            f"{rec.get('source') or 'Manual Entry'}")
        hist = T.instrument_history(self.tdb, int(rec["id"]), limit=60)
        self.t_history.fill(
            ["Date", "Movement", "Ref", "From", "To", "Employee Code"],
            [[T.fmt_date(m.get("movement_date", "")), m.get("movement_type", ""),
              m.get("ref_no", ""), m.get("from_holder", "") or "—",
              m.get("to_holder", "") or "—", m.get("to_employee_code", "")]
             for m in hist])
        _paint(self.t_history, 1, T.MOVEMENT_COLORS)

    # ---------------------------------------------------------------- actions
    def new_entry(self):
        dlg = InstrumentDialog(self.db, self.tdb, None, self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()

    def edit_entry(self):
        rec = self._selected()
        if not rec:
            W.error_box(self, "Select the instrument you want to edit first.")
            return
        dlg = InstrumentDialog(self.db, self.tdb, rec, self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()

    def delete_entry(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        picks = [self.rows[i] for i in rows if 0 <= i < len(self.rows)]
        if not picks:
            W.error_box(self, "Select the instrument(s) you want to delete first.")
            return
        names = ", ".join(T.instrument_title(r) for r in picks[:4])
        if not W.confirm(self, f"Delete {len(picks)} instrument(s) from the register?\n\n"
                               f"{names}\n\nTheir movement history is removed with them."):
            return
        gone = T.delete_instruments(self.tdb, [int(r["id"]) for r in picks])
        W.toast(self, f"{gone} instrument(s) deleted.")
        self.reload()
        self.changed.emit()

    def _action(self, action: str):
        rec = self._selected()
        if not rec:
            W.error_box(self, "Select the instrument in the register first.")
            return
        if action in (T.ACTION_TRANSFER, T.ACTION_RETURN) and not str(
                rec.get("issued_to") or "").strip():
            if action == T.ACTION_TRANSFER:
                W.info_box(self, "This instrument is in store. Use Issue to hand it to "
                                 "an employee first — a transfer moves it from one "
                                 "employee to another.")
                return
            W.info_box(self, "This instrument is already in store — there is nothing "
                             "to return.")
            return
        dlg = MovementDialog(self.db, self.tdb, rec, action, self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()

    def show_picture(self):
        rec = self._selected()
        if not rec:
            W.error_box(self, "Select an instrument first.")
            return
        path = str(rec.get("picture_path") or "")
        if not path or not Path(path).exists():
            W.info_box(self, "No picture is attached to this instrument yet.\n\n"
                             "Use Edit to add one.")
            return
        PictureViewer(path, T.instrument_title(rec), self).exec()

    def show_history(self):
        rec = self._selected()
        if not rec:
            W.error_box(self, "Select an instrument first.")
            return
        self.openMovements.emit(int(rec["id"]))

    def export_excel(self):
        if not self.rows:
            W.error_box(self, "There is nothing to export.")
            return
        out = D.export_excel(self.db, "Instrument Station Register", GRID_COLS,
                             [_row_values(r, i) for i, r in enumerate(self.rows, 1)])
        W.toast(self, f"Exported {out.name}")
        D.open_path(out)

    def export_pdf(self):
        if not self.rows:
            W.error_box(self, "There is nothing to print.")
            return
        out = D.tool_report_pdf(self.db, "Instrument Station Register", GRID_COLS,
                                [_row_values(r, i) for i, r in enumerate(self.rows, 1)],
                                subtitle="Exactly as the site Excel sheet")
        D.open_path(out)


# ================================================================== movements
class MovementTab(QWidget):
    """Every handover, transfer and return — the track record."""

    changed = Signal()
    openInstrument = Signal(int)

    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.rows: list[dict] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        bar = QWidget()
        bar.setObjectName("Card")
        gl = QGridLayout(bar)
        gl.setContentsMargins(10, 8, 10, 8)
        self.f_text = W.SearchBox("Search instrument, serial, employee, ref, project ...")
        self.f_text.textChanged.connect(self.reload)
        self.f_type = W.combo(["All Movements"] + T.MOVEMENTS)
        self.f_type.currentTextChanged.connect(self.reload)
        self.d_from = date_edit("")
        self.d_to = date_edit("")
        self.chk_dates = QCheckBox("Date range")
        self.chk_dates.toggled.connect(self.reload)
        self.d_from.dateChanged.connect(self.reload)
        self.d_to.dateChanged.connect(self.reload)
        gl.addWidget(self.f_text, 0, 0, 1, 3)
        gl.addWidget(self.f_type, 0, 3)
        gl.addWidget(self.chk_dates, 0, 4)
        gl.addWidget(self.d_from, 0, 5)
        gl.addWidget(self.d_to, 0, 6)
        gl.addWidget(W.button("♻  Reset", slot=self.clear_filters), 0, 7)
        v.addWidget(bar)

        act = QHBoxLayout()
        act.addWidget(W.button("🔧  Open Instrument", "Primary", self._open))
        act.addWidget(W.button("🗑  Delete Movement", slot=self._delete))
        act.addStretch(1)
        act.addWidget(W.button("🖨  Slip", "Accent", self._slip,
                               tip="Print the signed handover / transfer / return slip"))
        act.addWidget(W.button("📊  Excel", slot=lambda: self._export("xlsx")))
        act.addWidget(W.button("📄  PDF", slot=lambda: self._export("pdf")))
        act.addWidget(W.button("🖨  Print", slot=lambda: self._export("print")))
        v.addLayout(act)

        self.table = W.DataTable()
        v.addWidget(W.FilterBar(self.table))
        v.addWidget(self.table, 1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(self.count)
        self.table.doubleClicked.connect(lambda *_: self._open())

    COLUMNS = ["Date", "Movement", "Ref", "Instrument Description", "Serial No.",
               "From", "From Code", "To", "Employee Code", "Iqama ID",
               "Designation", "Division/Department", "Current Project",
               "Location", "Quantity", "Issued By", "Remarks"]

    def clear_filters(self):
        self.f_text.blockSignals(True)
        self.f_text.clear()
        self.f_text.blockSignals(False)
        self.f_type.setCurrentIndex(0)
        self.chk_dates.setChecked(False)
        self.reload()

    def filters(self) -> dict:
        f: dict = {"text": self.f_text.text().strip()}
        if self.f_type.currentText() not in ("", "All Movements"):
            f["movement_type"] = self.f_type.currentText()
        if self.chk_dates.isChecked():
            f["date_from"] = iso(self.d_from)
            f["date_to"] = iso(self.d_to)
        return f

    def reload(self):
        f = self.filters()
        self.rows = T.all_movements(self.tdb, text=f.get("text", ""),
                                    movement_type=f.get("movement_type", ""),
                                    date_from=f.get("date_from", ""),
                                    date_to=f.get("date_to", ""))
        self.table.fill(self.COLUMNS, [self._values(m) for m in self.rows])
        _paint(self.table, 1, T.MOVEMENT_COLORS)
        self.count.setText(f"{len(self.rows)} movement(s) — every handover, transfer "
                           f"and return is kept")

    @staticmethod
    def _values(m: dict) -> list:
        return [T.fmt_date(m.get("movement_date", "")), m.get("movement_type", ""),
                m.get("ref_no", ""), m.get("instrument_desc", ""),
                m.get("serial_no", ""), m.get("from_holder", "") or "—",
                m.get("from_employee_code", ""), m.get("to_holder", "") or "—",
                m.get("to_employee_code", ""), m.get("iqama_id", ""),
                m.get("designation", ""), m.get("division", ""),
                m.get("current_project", ""), m.get("location", ""),
                T.fmt_qty(m.get("quantity")), m.get("issued_by", ""),
                m.get("remarks", "")]

    def _selected(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0 or r >= len(self.rows):
            return None
        return self.rows[r]

    def show_instrument(self, instrument_id: int):
        self.f_text.blockSignals(True)
        self.f_text.clear()
        self.f_text.blockSignals(False)
        self.f_type.setCurrentIndex(0)
        self.rows = T.all_movements(self.tdb, instrument_id=int(instrument_id))
        self.table.fill(self.COLUMNS, [self._values(m) for m in self.rows])
        _paint(self.table, 1, T.MOVEMENT_COLORS)
        self.count.setText(f"{len(self.rows)} movement(s) for this instrument")

    def _open(self):
        rec = self._selected()
        if not rec:
            W.error_box(self, "Select a movement line first.")
            return
        self.openInstrument.emit(int(rec.get("instrument_id") or 0))

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        picks = [self.rows[i] for i in rows if 0 <= i < len(self.rows)]
        if not picks:
            W.error_box(self, "Select the movement line(s) to delete first.")
            return
        if not W.confirm(self, f"Delete {len(picks)} movement line(s)?\n\n"
                               "The register row itself keeps its current values."):
            return
        T.delete_movements(self.tdb, [int(m["id"]) for m in picks])
        W.toast(self, "Movement line(s) deleted.")
        self.reload()
        self.changed.emit()

    def _slip(self):
        """Print the plain-paper slip for the selected movement."""
        rec = self._selected()
        if not rec:
            W.error_box(self, "Select a movement line first.")
            return
        try:
            out = D.instrument_slip_pdf(self.db, self.tdb, int(rec["id"]))
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"The slip could not be produced.\n\n{exc}")
            return
        W.toast(self, f"Slip saved: {out.name}")
        D.print_file(self.db, out)

    def _export(self, kind: str):
        if not self.rows:
            W.error_box(self, "There are no movements to export.")
            return
        rows = [self._values(m) for m in self.rows]
        if kind == "xlsx":
            out = D.export_excel(self.db, "Instrument Movement History",
                                 self.COLUMNS, rows)
        else:
            out = D.tool_report_pdf(self.db, "Instrument Movement History",
                                    self.COLUMNS, rows,
                                    subtitle="Issue · Transfer · Return — kept per instrument")
            if kind == "print":
                D.print_file(self.db, out)
        W.toast(self, f"Saved {out.name}")
        D.open_path(out)


# ================================================================ excel sync
class SyncMappingDialog(QDialog):
    """Map the site sheet onto the register columns, then import."""

    def __init__(self, tdb: T.ToolDB, db: Database, headers: list[str],
                 rows: list[list], source: str = "", parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]
        self.source = source
        self.setWindowTitle("Instrument Station — map the Excel sheet")
        self.resize(1000, 640)
        v = QVBoxLayout(self)

        head = QLabel(
            "Every column of the sheet is matched to a register column. Correct any "
            "line that the automatic mapping got wrong, then import — the register "
            "gains one row per instrument and keeps a movement record of the change.")
        head.setWordWrap(True)
        v.addWidget(head)

        defaults_row = QHBoxLayout()
        self.d_site = QLineEdit()
        self.d_site.setPlaceholderText("Site name (used when the sheet has none)")
        self.d_division = QLineEdit()
        self.d_division.setPlaceholderText("Division/department if the sheet has none")
        defaults_row.addWidget(QLabel("Site")) ; defaults_row.addWidget(self.d_site, 1)
        defaults_row.addWidget(QLabel("Division")) ; defaults_row.addWidget(self.d_division, 1)
        v.addLayout(defaults_row)

        self.maps: list[QComboBox] = []
        grid_host = QWidget()
        gl = QGridLayout(grid_host)
        for i, h in enumerate(self.headers):
            gl.addWidget(QLabel(f"<b>{h}</b>"), i, 0)
            combo = W.combo(["— not imported —"] + [label for _, label in T.ALL_FIELDS])
            auto = T.excel_auto_map(self.headers).get(i)
            if auto:
                combo.setCurrentText(T.COLUMN_LABELS.get(auto)
                                     or dict(T.ALL_FIELDS).get(auto, auto))
            combo.currentTextChanged.connect(self._refresh)
            self.maps.append(combo)
            gl.addWidget(combo, i, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(grid_host)
        v.addWidget(scroll, 1)

        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(self.count)
        self.preview = W.DataTable()
        self.preview.setMaximumHeight(200)
        v.addWidget(self.preview)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("⬆  Import into the register")
        bb.accepted.connect(self._import)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._refresh()

    def _mapping(self) -> dict[int, str]:
        labels = dict((label, key) for key, label in T.ALL_FIELDS)
        out: dict[int, str] = {}
        for i, combo in enumerate(self.maps):
            key = labels.get(combo.currentText())
            if key:
                out[i] = key
        return out

    def _defaults(self) -> dict:
        out = {}
        if self.d_site.text().strip():
            out["site_name"] = self.d_site.text().strip()
            out["location"] = self.d_site.text().strip()
        if self.d_division.text().strip():
            out["division"] = self.d_division.text().strip()
        return out

    def _refresh(self, *_):
        self.records = T.excel_preview(self.headers, self.rows, self._mapping(),
                                       self._defaults())
        cols = [label for _, label in T.COLUMNS][:8]
        self.preview.fill(
            cols,
            [[rec.get(key, "") for key, _ in T.COLUMNS][:8] for rec in self.records[:40]])
        self.count.setText(f"{len(self.records)} usable row(s) of {len(self.rows)} — "
                           f"{len(self._mapping())} column(s) mapped")

    def _import(self):
        if not self.records:
            W.error_box(self, "Nothing to import — map at least one useful column.")
            return
        got = T.import_records(self.tdb, self.records, source_file=self.source,
                               site_name=self.d_site.text().strip(),
                               db_main=self.db)
        self.result = got
        W.info_box(self, f"{got['created']} new instrument(s) added, "
                         f"{got['updated']} updated, {got['failed']} failed."
                         + ("\n\n" + "\n".join(got["errors"][:5]) if got["errors"] else ""),
                   "Excel import finished")
        self.accept()


class ExcelSyncTab(QWidget):
    """Point the module at the sites' Excel folders and read them in."""

    imported = Signal()

    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.files: list[dict] = []
        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self._auto_sync)
        self.timer.start()

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        head = QLabel(
            "The register is exactly the site sheet, so syncing is a straight copy: "
            "point at the folder(s) the sites drop their Excel files into and the "
            "module reads every <b>.xlsx / .xlsm / .csv</b> file inside them — "
            "including sub-folders. Source files are never moved or changed.")
        head.setWordWrap(True)
        v.addWidget(head)

        card = W.Card("Site-wise Excel folders")
        row = QHBoxLayout()
        row.addWidget(W.button("📂  Add folder...", "Primary", self._browse))
        row.addWidget(W.button("▶  Sync selected", slot=self._sync_selected))
        row.addWidget(W.button("⏩  Sync all folders", slot=self._sync_all))
        row.addWidget(W.button("✖  Remove", slot=self._remove_folder))
        row.addWidget(W.button("📂  Open folder", slot=self._open_folder))
        row.addWidget(W.button("📄  Download template", slot=self._template))
        row.addStretch(1)
        row.addWidget(W.button("⬆  Import Excel file(s)...", "Accent", self._import_excel))
        card.add(_wrap(row))
        self.t_folders = W.DataTable()
        self.t_folders.setMaximumHeight(150)
        card.add(self.t_folders, 1)
        v.addWidget(card)

        status = QHBoxLayout()
        status.addWidget(QLabel("Synced files"))
        self.t_files = W.DataTable()
        v.addWidget(self.t_files, 1)
        self.stat = QLabel()
        self.stat.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(self.stat)
        act = QHBoxLayout()
        act.addWidget(W.button("▶  Re-read selected file(s)", slot=self._reprocess))
        act.addWidget(W.button("📂  Open file", slot=self._open_file))
        act.addStretch(1)
        act.addWidget(W.button("📊  Export register", slot=self._export))
        v.addLayout(act)

        c = W.Card("Sync history")
        self.t_runs = W.DataTable()
        self.t_runs.setMaximumHeight(190)
        c.add(self.t_runs, 1)
        v.addWidget(c)

    # ------------------------------------------------------------------ data
    def _template(self):
        cols, rows = T.excel_template_rows()
        out = D.export_excel(self.db, "Instrument Station Template", cols, rows)
        W.info_box(self, f"Template saved to:\n\n{out}\n\nFill it in and drop it into "
                         f"one of the sync folders — the module reads it as it is.")
        D.open_path(out)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder with the site "
                                                        "Excel sheets")
        if not folder:
            return
        T.save_sync_folder(self.tdb, folder, label=Path(folder).name)
        W.toast(self, "Folder added. Press Sync all folders to read it.")
        self.reload()

    def _selected_folder(self) -> dict | None:
        r = self.t_folders.currentRow()
        folders = T.sync_folders(self.tdb)
        if r < 0 or r >= len(folders):
            return None
        return folders[r]

    def _remove_folder(self):
        folder = self._selected_folder()
        if not folder:
            W.error_box(self, "Select a folder first.")
            return
        if not W.confirm(self, f"Stop syncing this folder?\n\n{folder['path']}\n\n"
                               "The instruments already read stay in the register."):
            return
        T.remove_sync_folder(self.tdb, int(folder["id"]))
        self.reload()

    def _open_folder(self):
        folder = self._selected_folder()
        if not folder:
            return
        D.open_path(folder["path"])

    def _sync_selected(self):
        folder = self._selected_folder()
        if not folder:
            W.error_box(self, "Select a folder first.")
            return
        got = T.sync_folder(self.tdb, int(folder["id"]), force=True, db_main=self.db)
        self._report(got)
        self.reload()
        self.imported.emit()

    def _sync_all(self):
        got = T.sync_all_folders(self.tdb, force=True, db_main=self.db)
        self._report(got)
        self.reload()
        self.imported.emit()

    def _auto_sync(self):
        try:
            got = T.sync_due_folders(self.tdb, db_main=self.db)
        except Exception:          # noqa: BLE001
            return
        if got.get("folders"):
            self.reload()
            self.imported.emit()

    def _report(self, got: dict):
        text = (f"{got.get('files', 0)} file(s) read · {got.get('created', 0)} new "
                f"instrument(s) · {got.get('updated', 0)} updated · "
                f"{got.get('failed', 0)} failed")
        if got.get("errors"):
            text += "\n\n" + "\n".join(str(e) for e in got["errors"][:6])
        W.info_box(self, text, "Site-wise Excel sync")

    def _import_excel(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Choose the site Excel sheet(s)", "",
            "Excel / CSV (*.xlsx *.xlsm *.csv *.txt)")
        if not files:
            return
        for f in files:
            try:
                headers, rows = T.excel_read_table(f)
            except Exception as exc:           # noqa: BLE001
                W.error_box(self, f"{Path(f).name}\n\n{exc}")
                continue
            if not rows:
                W.error_box(self, f"{Path(f).name} has no data rows.")
                continue
            dlg = SyncMappingDialog(self.tdb, self.db, headers, rows, f, self)
            if dlg.exec() == QDialog.Accepted:
                self.reload()
                self.imported.emit()

    def _selected_file_paths(self) -> list[str]:
        rows = sorted({i.row() for i in self.t_files.selectedIndexes()})
        return [self.files[i]["path"] for i in rows if 0 <= i < len(self.files)]

    def _reprocess(self):
        paths = self._selected_file_paths()
        if not paths:
            W.error_box(self, "Select one or more files in the list first.")
            return
        got = T.sync_excel_files(self.tdb, paths, force=True, db_main=self.db)
        self._report(got)
        self.reload()
        self.imported.emit()

    def _open_file(self):
        paths = self._selected_file_paths()
        if not paths:
            W.error_box(self, "Select a file first.")
            return
        p = Path(paths[0])
        if not p.exists():
            W.error_box(self, f"The file is no longer at:\n{p}")
            return
        D.open_path(p)

    def _export(self):
        rows = T.search_instruments(self.tdb)
        out = D.export_excel(self.db, "Instrument Station Register",
                             [label for _, label in T.COLUMNS],
                             [[r.get(k, "") for k, _ in T.COLUMNS] for r in rows])
        W.toast(self, f"Exported {out.name}")
        D.open_path(out)

    # --------------------------------------------------------------- refresh
    def reload(self):
        folders = T.sync_folders(self.tdb)
        self.t_folders.fill(
            ["Label", "Site", "Folder", "Auto", "Every (min)", "Files", "Last sync", "Error"],
            [[f.get("label") or Path(str(f.get("path"))).name, f.get("site_name", ""),
              f.get("path", ""), "Yes" if f.get("auto_sync") else "",
              f.get("sync_interval", ""), T.sync_folder_status(f.get("path", ""))[1],
              str(f.get("last_scan") or "")[:16], f.get("last_error", "")]
             for f in folders])
        self.files = T.scan_sync_files(self.tdb)
        self.t_files.fill(
            ["File", "Site", "Size (KB)", "Rows", "New", "Updated", "Failed",
             "Status", "Last sync", "Note"],
            [[f.get("name", ""), f.get("site_name", ""), f.get("size_kb", 0),
              f.get("rows_total", 0), f.get("rows_created", 0),
              f.get("rows_updated", 0), f.get("rows_failed", 0),
              f.get("status", ""), str(f.get("last_sync") or "")[:16],
              f.get("note", "")] for f in self.files])
        runs = T.sync_runs(self.tdb, limit=150)
        self.t_runs.fill(
            ["When", "File", "Site", "Status", "Rows", "New", "Updated", "Failed", "Note"],
            [[str(r.get("ts") or "")[:16], Path(str(r.get("source_file"))).name,
              r.get("site_name", ""), r.get("status", ""), r.get("total_rows", 0),
              r.get("created_rows", 0), r.get("updated_rows", 0),
              r.get("failed_rows", 0), r.get("details", "")] for r in runs])
        d = T.dashboard(self.tdb)
        self.stat.setText(f"{len(folders)} folder(s) · {len(self.files)} file(s) seen · "
                          f"{d['rows']} instrument(s) in the register · "
                          f"{d['movements']} movement(s) recorded")


def _wrap(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w


# =================================================================== reports
class InstrumentReportsTab(QWidget):
    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.pick = W.combo(T.REPORT_LIST)
        self.pick.currentTextChanged.connect(self.run)
        bar.addWidget(QLabel("Report:"))
        bar.addWidget(self.pick, 2)
        self.search = W.SearchBox("Filter text ...")
        self.search.textChanged.connect(self.run)
        bar.addWidget(self.search, 1)
        bar.addWidget(W.button("▶  Run", "Primary", self.run))
        v.addLayout(bar)

        act = QHBoxLayout()
        act.addWidget(W.button("📄  PDF", "Accent", lambda: self.export("pdf")))
        act.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        act.addWidget(W.button("📋  CSV", slot=lambda: self.export("csv")))
        act.addWidget(W.button("🖨  Print", slot=self.print_out))
        act.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        act.addWidget(self.count)
        v.addLayout(act)

        self.table = W.DataTable()
        v.addWidget(W.FilterBar(self.table))
        v.addWidget(self.table, 1)
        v.addWidget(ShareBar(self.db, lambda: self.last_file, self))

    def run(self):
        name = self.pick.currentText()
        f = {"text": self.search.text().strip()} if self.search.text().strip() else {}
        title, cols, rows = T.build_report(self.tdb, name, f)
        self.title, self.cols, self.rows = title, cols, rows
        self.table.fill(cols, rows)
        for i, c in enumerate(cols):
            if c.strip().lower() == "status":
                _paint(self.table, i, T.STATUS_COLORS)
            if c.strip().lower() == "movement":
                _paint(self.table, i, T.MOVEMENT_COLORS)
        self.count.setText(f"{len(rows)} row(s)")

    def export(self, kind: str):
        if not getattr(self, "rows", None):
            self.run()
        if not self.rows:
            W.error_box(self, "This report has no rows to export.")
            return
        fn = {"pdf": D.tool_report_pdf, "xlsx": D.export_excel,
              "csv": D.export_csv}[kind]
        self.last_file = fn(self.db, self.title, self.cols, self.rows)
        W.toast(self, f"Saved: {self.last_file.name}")
        D.open_path(self.last_file)

    def print_out(self):
        if not getattr(self, "rows", None):
            self.run()
        if not self.rows:
            W.error_box(self, "This report has no rows to print.")
            return
        self.last_file = D.tool_report_pdf(self.db, self.title, self.cols, self.rows)
        D.print_file(self.db, self.last_file)


# ====================================================================== page
class ToolStationPage(QWidget):
    """INSTRUMENT STATION — register, dashboard, movements, Excel sync, reports."""

    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.tdb = T.get_tool_db()
        self.tdb.current_user = getattr(db, "current_user", "admin")

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)

        banner = QLabel(
            "🔧  <b>Instrument Station</b> — the instrument register, built exactly on "
            "the site Excel sheet: "
            + " · ".join(label for _, label in T.COLUMNS)
            + f". Every handover, transfer and return is tracked with its date, and the "
              f"Employee Code fills the employee's details from the Employee Master. "
              f"Its own database file (<code>{self.tdb.path.name}</code>); nothing here "
              f"affects inventory stock.")
        banner.setWordWrap(True)
        banner.setStyleSheet(f"background:{W.NAVY}; color:white; border-radius:7px; "
                             f"padding:8px 12px;")
        self.banner = banner
        v.addWidget(banner)

        self.tabs = QTabWidget()
        self.dashboard = InstrumentDashboard(self.tdb, db)
        self.register = RegisterTab(self.tdb, db)
        self.movements = MovementTab(self.tdb, db)
        self.sync = ExcelSyncTab(self.tdb, db)
        self.reports = InstrumentReportsTab(self.tdb, db)
        self.tabs.addTab(self.dashboard, "📊  Dashboard")
        self.tabs.addTab(self.register, "🔧  Instruments")
        self.tabs.addTab(self.movements, "🔁  Movements")
        self.tabs.addTab(self.sync, "📊  Excel Sync")
        self.tabs.addTab(self.reports, "📈  Reports")
        v.addWidget(self.tabs, 1)

        tools = QHBoxLayout()
        tools.addWidget(W.button("💾  Backup Module", slot=self._backup,
                                 tip="Back up the Instrument Station database"))
        tools.addWidget(W.button("♻  Restore...", slot=self._restore))
        tools.addWidget(W.button("📂  Open Data Folder", slot=self._folder))
        tools.addWidget(W.button("📁  Pictures Folder", slot=self._pictures))
        tools.addWidget(W.button("🔄  Refresh", slot=self.refresh))
        tools.addStretch(1)
        self.stat = QLabel()
        self.stat.setStyleSheet(f"color:{W.MUTED};")
        tools.addWidget(self.stat)
        v.addLayout(tools)

        self.register.changed.connect(self.refresh)
        self.register.openMovements.connect(self._open_movements)
        self.movements.openInstrument.connect(self._open_instrument)
        self.movements.changed.connect(self.refresh)
        self.sync.imported.connect(self.refresh)
        self.dashboard.openRegister.connect(self._drill)
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        self.refresh()

    # ------------------------------------------------------------- wiring
    def _drill(self, f: dict):
        self.tabs.setCurrentWidget(self.register)
        self.register.apply_filter(f)

    def _open_movements(self, instrument_id: int):
        self.tabs.setCurrentWidget(self.movements)
        self.movements.show_instrument(instrument_id)

    def _open_instrument(self, instrument_id: int):
        self.tabs.setCurrentWidget(self.register)
        for i, r in enumerate(self.register.rows):
            if int(r["id"]) == int(instrument_id):
                self.register.table.selectRow(i)
                break

    def refresh(self):
        self.tdb.current_user = getattr(self.db, "current_user", "admin")
        i = self.tabs.currentIndex()
        if i == 0:
            self.dashboard.reload()
        elif i == 1:
            self.register.reload()
        elif i == 2:
            self.movements.reload()
        elif i == 3:
            self.sync.reload()
        else:
            self.reports.run()
        d = T.register_total(self.tdb)
        self.stat.setText(
            f"{d['rows']} instrument(s) · {T.fmt_qty(d['quantity'])} total quantity · "
            f"{d['holders']} held by employees · {d['movements']} movement(s)")
        self.dataChanged.emit()

    # ------------------------------------------------------------ housekeeping
    def _backup(self):
        try:
            p = self.tdb.backup(note="manual backup")
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Backup failed.\n\n{exc}")
            return
        W.info_box(self, f"Instrument Station backed up to:\n\n{p}", "Backup complete")

    def _restore(self):
        f, _ = QFileDialog.getOpenFileName(self, "Restore the Instrument Station "
                                                 "database", "", "Database (*.db)")
        if not f:
            return
        if not W.confirm(self, "Replace the current Instrument Station data with this "
                               "backup?\n\nA safety copy of the current data is taken "
                               "first."):
            return
        try:
            self.tdb.restore(f)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Restore failed.\n\n{exc}")
            return
        W.info_box(self, "The register has been restored.")
        self.refresh()

    def _folder(self):
        D.open_path(T.module_folder())

    def _pictures(self):
        D.open_path(T.pictures_dir())
