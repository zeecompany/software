"""Employee master list helpers for the whole AURCO system."""
from __future__ import annotations

import datetime as _dt
from typing import Any

from .database import Database

COLUMNS = [
    ("employee_id", "Employee ID"),
    ("name", "Name"),
    ("designation", "Designation"),
    ("iqama_id", "Iqama ID"),
    ("date_of_joining", "Date of Joining"),
    ("nationality", "Nationality"),
    ("contract_workhours", "Contract WorkHours"),
    ("division", "Division/Department"),
    ("current_project", "Current Project"),
    ("location", "Location"),
]

_DATE_PATTERNS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y",
    "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%d-%b-%y",
    "%d-%m-%y", "%d/%m/%y", "%Y-%m-%d %H:%M:%S",
)


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_date(v: Any) -> str:
    if v in (None, ""):
        return ""
    if isinstance(v, _dt.datetime):
        return v.date().isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    t = str(v).strip()
    if not t or t in ("-", "N/A", "n/a"):
        return ""
    for f in _DATE_PATTERNS:
        try:
            d = _dt.datetime.strptime(t, f).date()
            if d.year < 100:
                d = d.replace(year=d.year + 2000)
            return d.isoformat()
        except ValueError:
            continue
    return t


def save_employee(db: Database, data: dict[str, Any], employee_row_id: int | None = None) -> int:
    emp_id = str(data.get("employee_id") or "").strip()
    name = str(data.get("name") or "").strip()
    if not emp_id:
        raise ValueError("Employee ID is required.")
    if not name:
        raise ValueError("Employee name is required.")
    vals = {
        "employee_id": emp_id,
        "name": name,
        "designation": str(data.get("designation") or "").strip(),
        "iqama_id": str(data.get("iqama_id") or "").strip(),
        "date_of_joining": to_date(data.get("date_of_joining") or ""),
        "nationality": str(data.get("nationality") or "").strip(),
        "contract_workhours": str(data.get("contract_workhours") or "").strip(),
        "division": str(data.get("division") or "").strip(),
        "current_project": str(data.get("current_project") or "").strip(),
        "location": str(data.get("location") or "").strip(),
    }
    params = [vals["employee_id"]]
    sql = "SELECT id FROM employees WHERE employee_id=?"
    if employee_row_id is not None:
        sql += " AND id<>?"
        params.append(int(employee_row_id))
    if db.one(sql, tuple(params)):
        raise ValueError(f"Employee ID '{vals['employee_id']}' already exists.")
    if vals["iqama_id"]:
        params = [vals["iqama_id"]]
        sql = "SELECT id FROM employees WHERE iqama_id=?"
        if employee_row_id is not None:
            sql += " AND id<>?"
            params.append(int(employee_row_id))
        if db.one(sql, tuple(params)):
            raise ValueError(f"Iqama ID '{vals['iqama_id']}' already exists.")
    try:
        if employee_row_id is None:
            cur = db.execute(
                """INSERT INTO employees(employee_id,name,designation,iqama_id,date_of_joining,
                     nationality,contract_workhours,division,current_project,location,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (vals["employee_id"], vals["name"], vals["designation"], vals["iqama_id"],
                 vals["date_of_joining"], vals["nationality"], vals["contract_workhours"],
                 vals["division"], vals["current_project"], vals["location"], _now()),
            )
            new_id = int(cur.lastrowid)
            db.commit()
            db.audit("CREATED", "employee", str(new_id), vals["employee_id"])
            return new_id
        db.execute(
            """UPDATE employees SET employee_id=?, name=?, designation=?, iqama_id=?,
                 date_of_joining=?, nationality=?, contract_workhours=?, division=?,
                 current_project=?, location=?, updated_at=?
               WHERE id=?""",
            (vals["employee_id"], vals["name"], vals["designation"], vals["iqama_id"],
             vals["date_of_joining"], vals["nationality"], vals["contract_workhours"],
             vals["division"], vals["current_project"], vals["location"], _now(), int(employee_row_id)),
        )
        db.commit()
        db.audit("EDITED", "employee", str(employee_row_id), vals["employee_id"])
        return int(employee_row_id)
    except Exception:
        db.rollback()
        raise


def delete_employee(db: Database, employee_row_id: int) -> None:
    row = db.one("SELECT employee_id FROM employees WHERE id=?", (employee_row_id,))
    if row is None:
        return
    db.execute("DELETE FROM employees WHERE id=?", (employee_row_id,))
    db.commit()
    db.audit("DELETED", "employee", str(employee_row_id), str(row[0]))


def list_employees(db: Database, text: str = "", division: str = "", project: str = "",
                   location: str = "") -> list[dict[str, Any]]:
    sql = "SELECT * FROM employees WHERE 1=1"
    p: list[Any] = []
    if division:
        sql += " AND division=?"
        p.append(division)
    if project:
        sql += " AND current_project=?"
        p.append(project)
    if location:
        sql += " AND location=?"
        p.append(location)
    if text.strip():
        like = f"%{text.strip()}%"
        sql += (" AND (employee_id LIKE ? OR name LIKE ? OR designation LIKE ? OR iqama_id LIKE ?"
                " OR division LIKE ? OR current_project LIKE ? OR location LIKE ? OR nationality LIKE ?)")
        p += [like] * 8
    sql += " ORDER BY name COLLATE NOCASE, employee_id COLLATE NOCASE"
    return [dict(r) for r in db.query(sql, p)]


def distinct_values(db: Database, field: str) -> list[str]:
    if field not in {"division", "current_project", "location", "designation", "nationality"}:
        return []
    rows = db.query(f"SELECT DISTINCT {field} FROM employees WHERE COALESCE({field},'')<>'' ORDER BY {field}")
    return [str(r[0]) for r in rows if str(r[0] or "").strip()]


def find_employee(db: Database, employee_id: str = "", iqama_id: str = "", name: str = "") -> dict[str, Any] | None:
    emp_id = str(employee_id or "").strip()
    iqama = str(iqama_id or "").strip()
    nm = str(name or "").strip()
    row = None
    if emp_id:
        row = db.one("SELECT * FROM employees WHERE employee_id=?", (emp_id,))
    if row is None and iqama:
        row = db.one("SELECT * FROM employees WHERE iqama_id=?", (iqama,))
    if row is None and nm:
        row = db.one("SELECT * FROM employees WHERE name=?", (nm,))
    return dict(row) if row else None


def employee_names(db: Database) -> list[str]:
    return [str(r[0]) for r in db.query("SELECT name FROM employees WHERE COALESCE(name,'')<>'' ORDER BY name")]


def employee_ids(db: Database) -> list[str]:
    return [str(r[0]) for r in db.query("SELECT employee_id FROM employees WHERE COALESCE(employee_id,'')<>'' ORDER BY employee_id")]


def iqama_ids(db: Database) -> list[str]:
    return [str(r[0]) for r in db.query("SELECT iqama_id FROM employees WHERE COALESCE(iqama_id,'')<>'' ORDER BY iqama_id")]
