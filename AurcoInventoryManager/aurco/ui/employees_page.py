"""Employee master list for the whole system."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import employees as EMP
from ..core.database import Database
from . import widgets as W
from .common import date_edit, iso


class EmployeeDialog(QDialog):
    def __init__(self, row: dict | None = None, parent=None):
        super().__init__(parent)
        self.row = dict(row or {})
        self.setWindowTitle("Employee Master — " + ("Edit Employee" if row else "New Employee"))
        self.resize(680, 430)
        v = QVBoxLayout(self)
        note = QLabel("Keep one clean employee master list here, then use the employee ID, Iqama ID and name across the system.")
        note.setWordWrap(True)
        v.addWidget(note)
        form = QFormLayout()
        self.e_employee_id = QLineEdit(self.row.get("employee_id", ""))
        self.e_name = QLineEdit(self.row.get("name", ""))
        self.e_designation = QLineEdit(self.row.get("designation", ""))
        self.e_iqama = QLineEdit(self.row.get("iqama_id", ""))
        self.e_join = date_edit(self.row.get("date_of_joining") or None)
        self.e_nationality = QLineEdit(self.row.get("nationality", ""))
        self.e_hours = QLineEdit(self.row.get("contract_workhours", ""))
        self.e_division = QLineEdit(self.row.get("division", ""))
        self.e_project = QLineEdit(self.row.get("current_project", ""))
        self.e_location = QLineEdit(self.row.get("location", ""))
        for lbl, wd in (("Employee ID", self.e_employee_id), ("Name", self.e_name),
                        ("Designation", self.e_designation), ("Iqama ID", self.e_iqama),
                        ("Date of Joining", self.e_join), ("Nationality", self.e_nationality),
                        ("Contract WorkHours", self.e_hours), ("Division/Department", self.e_division),
                        ("Current Project", self.e_project), ("Location", self.e_location)):
            form.addRow(lbl, wd)
        v.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def data(self) -> dict:
        return {
            "employee_id": self.e_employee_id.text().strip(),
            "name": self.e_name.text().strip(),
            "designation": self.e_designation.text().strip(),
            "iqama_id": self.e_iqama.text().strip(),
            "date_of_joining": iso(self.e_join),
            "nationality": self.e_nationality.text().strip(),
            "contract_workhours": self.e_hours.text().strip(),
            "division": self.e_division.text().strip(),
            "current_project": self.e_project.text().strip(),
            "location": self.e_location.text().strip(),
        }


class EmployeesPage(QWidget):
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.rows: list[dict] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        note = QLabel("👥  <b>Employee Master</b> — keep employee ID, Iqama ID, designation, department, project and location in one place for use across AURCO.")
        note.setWordWrap(True)
        v.addWidget(note)

        bar = QWidget()
        bar.setObjectName("Card")
        gl = QGridLayout(bar)
        gl.setContentsMargins(10, 8, 10, 8)
        self.f_text = W.SearchBox("Search employee ID, name, Iqama ID, project, department ...")
        self.f_division = W.combo(["All Divisions"])
        self.f_project = W.combo(["All Projects"])
        self.f_location = W.combo(["All Locations"])
        self.f_text.textChanged.connect(self.reload)
        self.f_division.currentTextChanged.connect(self.reload)
        self.f_project.currentTextChanged.connect(self.reload)
        self.f_location.currentTextChanged.connect(self.reload)
        gl.addWidget(self.f_text, 0, 0, 1, 3)
        gl.addWidget(self.f_division, 0, 3)
        gl.addWidget(self.f_project, 0, 4)
        gl.addWidget(self.f_location, 0, 5)
        for i, (txt, slot) in enumerate((
                ("Add", self.add_employee),
                ("Edit", self.edit_employee),
                ("Delete", self.delete_employee),
                ("Export", self.export_excel),
                ("Reset", self.reset_filters),
        ), start=6):
            gl.addWidget(W.button(txt, "Accent" if txt == "Add" else "", slot=slot), 0, i)
        v.addWidget(bar)

        self.table = W.DataTable(["ID", "Employee ID", "Name", "Designation", "Iqama ID",
                                  "Date of Joining", "Nationality", "Contract WorkHours",
                                  "Division/Department", "Current Project", "Location", "Updated"])
        v.addWidget(self.table, 1)
        self.reload()

    def _filters(self) -> dict:
        division = self.f_division.currentText().strip()
        project = self.f_project.currentText().strip()
        location = self.f_location.currentText().strip()
        return {
            "text": self.f_text.text().strip(),
            "division": "" if division == "All Divisions" else division,
            "project": "" if project == "All Projects" else project,
            "location": "" if location == "All Locations" else location,
        }

    def reload_filters(self):
        cur_d = self.f_division.currentText()
        cur_p = self.f_project.currentText()
        cur_l = self.f_location.currentText()
        divs = ["All Divisions"] + EMP.distinct_values(self.db, "division")
        projs = ["All Projects"] + EMP.distinct_values(self.db, "current_project")
        locs = ["All Locations"] + EMP.distinct_values(self.db, "location")
        for box, items, cur in ((self.f_division, divs, cur_d), (self.f_project, projs, cur_p), (self.f_location, locs, cur_l)):
            box.blockSignals(True)
            box.clear(); box.addItems(items)
            if cur in items:
                box.setCurrentText(cur)
            box.blockSignals(False)

    def reload(self):
        self.reload_filters()
        self.rows = EMP.list_employees(self.db, **self._filters())
        self.table.fill(
            ["ID", "Employee ID", "Name", "Designation", "Iqama ID",
             "Date of Joining", "Nationality", "Contract WorkHours",
             "Division/Department", "Current Project", "Location", "Updated"],
            [[r["id"], r.get("employee_id", ""), r.get("name", ""), r.get("designation", ""),
              r.get("iqama_id", ""), r.get("date_of_joining", ""), r.get("nationality", ""),
              r.get("contract_workhours", ""), r.get("division", ""), r.get("current_project", ""),
              r.get("location", ""), r.get("updated_at", "") or r.get("created_at", "")]
             for r in self.rows],
        )
        self.table.setColumnHidden(0, True)
        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _current(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0:
            return None
        rid = int(self.table.item(r, 0).text())
        for row in self.rows:
            if int(row["id"]) == rid:
                return row
        return None

    def reset_filters(self):
        self.f_text.clear()
        self.f_division.setCurrentIndex(0)
        self.f_project.setCurrentIndex(0)
        self.f_location.setCurrentIndex(0)
        self.reload()

    def add_employee(self):
        dlg = EmployeeDialog(parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            EMP.save_employee(self.db, dlg.data())
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.reload()
        self.dataChanged.emit()
        W.toast(self, "Employee saved.")

    def edit_employee(self):
        row = self._current()
        if not row:
            return
        dlg = EmployeeDialog(row, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            EMP.save_employee(self.db, dlg.data(), int(row["id"]))
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.reload()
        self.dataChanged.emit()
        W.toast(self, "Employee updated.")

    def delete_employee(self):
        row = self._current()
        if not row:
            return
        if not W.confirm(self, f"Delete employee '{row['name']}'?"):
            return
        EMP.delete_employee(self.db, int(row["id"]))
        self.reload()
        self.dataChanged.emit()
        W.toast(self, "Employee deleted.")

    def export_excel(self):
        f = D.export_excel(
            self.db,
            "Employee Master List",
            [c[1] for c in EMP.COLUMNS],
            [[r.get("employee_id", ""), r.get("name", ""), r.get("designation", ""), r.get("iqama_id", ""),
              r.get("date_of_joining", ""), r.get("nationality", ""), r.get("contract_workhours", ""),
              r.get("division", ""), r.get("current_project", ""), r.get("location", "")]
             for r in self.rows],
        )
        W.toast(self, f"Exported {f.name}")
        D.open_path(f)
