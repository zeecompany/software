"""TOOLS STATION — separate register for survey instruments and other tools.

This module follows the sheet-style summary the user supplied, but stores the
actual records one line at a time so serial numbers, pictures and locations can
be tracked properly.

Key behaviour
=============
- separate SQLite database under the storage root
- one register row per tracked record / serial batch
- transfer tools between people, projects and sites with permanent movement history
- optional picture copied into the module's own Photos folder
- auto summary by instrument description across the fixed locations:
  Warehouse, Hajar, Zuluf, Yanbu, Noor
- simple dashboard figures with no effect on inventory stock
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from . import config

MODULE_NAME = "Surveyor Tools Record"
FOLDER = MODULE_NAME
LEGACY_FOLDERS = ("Tools Station",)
DB_NAME = "surveyor_tools.db"
SCHEMA_VERSION = 4

SECOND_TYPE_SUGGESTIONS = ["Tool", "Device", "Instrument"]

LOC_WAREHOUSE = "Warehouse"
LOC_HAJAR = "Hajar"
LOC_ZULUF = "Zuluf"
LOC_YANBU = "Yanbu"
LOC_NOOR = "Noor"
DEFAULT_LOCATIONS = [LOC_WAREHOUSE, LOC_HAJAR, LOC_ZULUF, LOC_YANBU, LOC_NOOR]

ST_ACTIVE = "Active"
ST_IN_USE = "In Use"
ST_OUT_OF_ORDER = "Out of Order"
ST_UNDER_REPAIR = "Under Repair"
ST_MISSING = "Missing"
ST_DISPOSED = "Disposed"
STATUSES = [ST_ACTIVE, ST_IN_USE, ST_OUT_OF_ORDER, ST_UNDER_REPAIR, ST_MISSING, ST_DISPOSED]
ACTIVE_STATUSES = {ST_ACTIVE, ST_IN_USE, ST_OUT_OF_ORDER, ST_UNDER_REPAIR, ST_MISSING}

EV_REGISTERED = "REGISTERED"
EV_ISSUED = "ISSUED"
EV_TRANSFER = "TRANSFER"
EVENT_TYPES = [EV_REGISTERED, EV_ISSUED, EV_TRANSFER]

FIELDS = [
    ("instrument_desc", "Instrument Description"),
    ("second_type", "2nd Type"),
    ("serial_no", "Serial No."),
    ("make_model", "Make / Model"),
    ("location", "Location"),
    ("qty", "Quantity"),
    ("status", "Status"),
    ("issued_to", "Issued To / Employee Name"),
    ("employee_code", "Employee Code"),
    ("iqama_id", "Iqama ID"),
    ("designation", "Designation"),
    ("division", "Division/Department"),
    ("current_project", "Current Project"),
    ("issued_by", "Issued By"),
    ("remarks", "Remarks"),
    ("picture_path", "Picture Path"),
]
LABELS = dict(FIELDS)
ALL_FIELDS = FIELDS

HEADER_MAP = {
    "instrumentdescription": "instrument_desc",
    "description": "instrument_desc",
    "instrument": "instrument_desc",
    "tool": "instrument_desc",
    "secondtype": "second_type",
    "2ndtype": "second_type",
    "type2": "second_type",
    "itemtype2": "second_type",
    "itemtype": "second_type",
    "tooltype": "second_type",
    "category": "second_type",
    "subcategory": "second_type",
    "serialno": "serial_no",
    "serialnumber": "serial_no",
    "serial": "serial_no",
    "makemodel": "make_model",
    "make": "make_model",
    "model": "make_model",
    "location": "location",
    "site": "location",
    "projectlocation": "location",
    "qty": "qty",
    "quantity": "qty",
    "status": "status",
    "condition": "status",
    "issuedtoemployeename": "issued_to",
    "issuedto": "issued_to",
    "employeename": "issued_to",
    "employee": "issued_to",
    "name": "issued_to",
    "employeecode": "employee_code",
    "employeeid": "employee_code",
    "empid": "employee_code",
    "empcode": "employee_code",
    "code": "employee_code",
    "iqamaid": "iqama_id",
    "iqama": "iqama_id",
    "designation": "designation",
    "divisiondepartment": "division",
    "division": "division",
    "department": "division",
    "currentproject": "current_project",
    "project": "current_project",
    "issuedby": "issued_by",
    "issuer": "issued_by",
    "issuername": "issued_by",
    "remarks": "remarks",
    "remark": "remarks",
    "notes": "remarks",
    "picture": "picture_path",
    "picturepath": "picture_path",
    "photopath": "picture_path",
    "photo": "picture_path",
}

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_desc   TEXT NOT NULL DEFAULT '',
    second_type       TEXT DEFAULT '',
    serial_no         TEXT DEFAULT '',
    make_model        TEXT DEFAULT '',
    location          TEXT NOT NULL DEFAULT 'Warehouse',
    qty               REAL NOT NULL DEFAULT 1,
    status            TEXT NOT NULL DEFAULT 'Active',
    issued_to         TEXT DEFAULT '',
    employee_code     TEXT DEFAULT '',
    iqama_id          TEXT DEFAULT '',
    designation       TEXT DEFAULT '',
    division          TEXT DEFAULT '',
    current_project   TEXT DEFAULT '',
    issued_by         TEXT DEFAULT '',
    remarks           TEXT DEFAULT '',
    picture_path      TEXT DEFAULT '',
    created_by        TEXT DEFAULT '',
    created_at        TEXT DEFAULT (datetime('now','localtime')),
    updated_at        TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_sv_desc     ON records(instrument_desc);
CREATE INDEX IF NOT EXISTS ix_sv_serial   ON records(serial_no);
CREATE INDEX IF NOT EXISTS ix_sv_location ON records(location);
CREATE INDEX IF NOT EXISTS ix_sv_status   ON records(status);

CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT DEFAULT (datetime('now','localtime')),
    username   TEXT DEFAULT '',
    action     TEXT NOT NULL,
    entity     TEXT DEFAULT '',
    entity_id  TEXT DEFAULT '',
    details    TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_sv_audit ON audit(ts);

CREATE TABLE IF NOT EXISTS transfer_history (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    event_no           TEXT NOT NULL UNIQUE,
    record_id          INTEGER NOT NULL,
    event_type         TEXT NOT NULL DEFAULT 'REGISTERED',
    event_date         TEXT NOT NULL DEFAULT '',
    instrument_desc    TEXT DEFAULT '',
    serial_no          TEXT DEFAULT '',
    qty                REAL NOT NULL DEFAULT 0,
    from_holder        TEXT DEFAULT '',
    from_employee_code TEXT DEFAULT '',
    from_iqama_id      TEXT DEFAULT '',
    from_designation   TEXT DEFAULT '',
    from_division      TEXT DEFAULT '',
    from_project       TEXT DEFAULT '',
    from_location      TEXT DEFAULT '',
    from_status        TEXT DEFAULT '',
    to_holder          TEXT DEFAULT '',
    to_employee_code   TEXT DEFAULT '',
    to_iqama_id        TEXT DEFAULT '',
    to_designation     TEXT DEFAULT '',
    to_division        TEXT DEFAULT '',
    to_project         TEXT DEFAULT '',
    to_location        TEXT DEFAULT '',
    to_status          TEXT DEFAULT '',
    moved_by           TEXT DEFAULT '',
    remarks            TEXT DEFAULT '',
    created_at         TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_sv_hist_record ON transfer_history(record_id, id);
CREATE INDEX IF NOT EXISTS ix_sv_hist_date   ON transfer_history(event_date);
"""


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return _dt.date.today().isoformat()


def _folder_has_content(path: Path) -> bool:
    try:
        next(path.iterdir())
        return True
    except (StopIteration, FileNotFoundError, NotADirectoryError):
        return False


def _legacy_folder(root: Path, current: Path) -> Path | None:
    for legacy_name in LEGACY_FOLDERS:
        legacy = root / legacy_name
        try:
            same = legacy.resolve() == current.resolve()
        except OSError:
            same = False
        if legacy.exists() and not same:
            return legacy
    return None


def _module_folder() -> Path:
    root = config.get_storage_root() or config.default_storage_root()
    root = Path(root)
    current = root / FOLDER
    legacy = _legacy_folder(root, current)
    if legacy is None:
        current.mkdir(parents=True, exist_ok=True)
        return current

    current_exists = current.exists()
    current_has_content = _folder_has_content(current)
    current_db = current / DB_NAME
    legacy_db = legacy / DB_NAME

    # If the new folder already has real content, keep using it.
    if current_db.exists() or current_has_content:
        current.mkdir(parents=True, exist_ok=True)
        return current

    # Brand-new renamed install path with existing old data: move the whole
    # folder in one step so SQLite sidecars stay together. If Windows reports
    # the legacy DB/WAL/SHM files are in use, fall back to the legacy folder
    # for this run instead of crashing; the rename can happen later.
    try:
        if current_exists and not current_has_content:
            current.rmdir()
        shutil.move(str(legacy), str(current))
        return current
    except (PermissionError, OSError):
        legacy.mkdir(parents=True, exist_ok=True)
        if legacy_db.exists() or _folder_has_content(legacy):
            return legacy
        current.mkdir(parents=True, exist_ok=True)
        return current


def db_path() -> Path:
    return _module_folder() / DB_NAME


def photo_folder() -> Path:
    p = _module_folder() / "Photos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_name(text: Any, fallback: str = "file") -> str:
    raw = re.sub(r"[\\/:*?\"<>|]+", " ", str(text or "")).strip()
    raw = re.sub(r"\s+", " ", raw).strip(" .")
    return raw or fallback


def to_float(v: Any) -> float:
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    t = str(v).strip().lower()
    if t in ("-", "n/a", "na", "nil", "none"):
        return 0.0
    try:
        return float(re.sub(r"[^\d.\-]", "", t) or 0)
    except ValueError:
        return 0.0


def norm_key(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _status_from_text(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    key = norm_key(raw)
    mapping = {norm_key(v): v for v in STATUSES}
    if key in mapping:
        return mapping[key]
    if "repair" in key:
        return ST_UNDER_REPAIR
    if "outoforder" in key or key in {"ooo", "damaged", "faulty"}:
        return ST_OUT_OF_ORDER
    if "missing" in key or "lost" in key:
        return ST_MISSING
    if "disposed" in key or "scrap" in key:
        return ST_DISPOSED
    if "use" in key or "issued" in key or "custody" in key:
        return ST_IN_USE
    return ST_ACTIVE


class SurveyorDB:
    def __init__(self, path: str | Path | None = None, current_user: str = "admin"):
        self.path = Path(path or db_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.current_user = current_user or "admin"
        self.conn.executescript(DDL)
        self.conn.commit()
        self._apply_schema_fixes()
        self.set_setting("schema_version", SCHEMA_VERSION)

    def _apply_schema_fixes(self) -> None:
        cols = {str(r[1]) for r in self.query("PRAGMA table_info(records)")}
        for col, sql in (
            ("second_type", "ALTER TABLE records ADD COLUMN second_type TEXT DEFAULT ''"),
            ("issued_to", "ALTER TABLE records ADD COLUMN issued_to TEXT DEFAULT ''"),
            ("employee_code", "ALTER TABLE records ADD COLUMN employee_code TEXT DEFAULT ''"),
            ("iqama_id", "ALTER TABLE records ADD COLUMN iqama_id TEXT DEFAULT ''"),
            ("designation", "ALTER TABLE records ADD COLUMN designation TEXT DEFAULT ''"),
            ("division", "ALTER TABLE records ADD COLUMN division TEXT DEFAULT ''"),
            ("current_project", "ALTER TABLE records ADD COLUMN current_project TEXT DEFAULT ''"),
            ("issued_by", "ALTER TABLE records ADD COLUMN issued_by TEXT DEFAULT ''"),
        ):
            if col not in cols:
                self.execute(sql)
        self.execute("CREATE INDEX IF NOT EXISTS ix_sv_type2 ON records(second_type)")
        self.execute("CREATE INDEX IF NOT EXISTS ix_sv_hist_record ON transfer_history(record_id, id)")
        self.execute("CREATE INDEX IF NOT EXISTS ix_sv_hist_date ON transfer_history(event_date)")
        self.commit()

    def close(self) -> None:
        self.conn.close()

    def execute(self, sql: str, params: Any = ()):
        return self.conn.execute(sql, params)

    def query(self, sql: str, params: Any = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params))

    def one(self, sql: str, params: Any = ()):
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Any = (), default: Any = 0) -> Any:
        row = self.one(sql, params)
        if row is None:
            return default
        return row[0]

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key,value) VALUES(?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(key), str(value)),
        )
        self.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return str(r[0]) if r else str(default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = str(self.get_setting(key, "1" if default else "0")).strip().lower()
        return raw in {"1", "true", "yes", "y", "on"}

    def audit(self, action: str, entity: str = "", entity_id: str = "", details: str = "") -> None:
        self.execute(
            "INSERT INTO audit(username,action,entity,entity_id,details) VALUES(?,?,?,?,?)",
            (self.current_user, action, entity, entity_id, details),
        )
        self.commit()

    def backup(self, note: str = "") -> Path:
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = config.folder("Backups") / f"Tools_Station_{ts}.db"
        shutil.copy2(self.path, out)
        self.audit("BACKUP", "database", out.name, note)
        return out


def get_db(current_user: str = "admin") -> SurveyorDB:
    return SurveyorDB(current_user=current_user)


def get_record(db: SurveyorDB, record_id: int) -> dict[str, Any] | None:
    row = db.one("SELECT * FROM records WHERE id=?", (int(record_id),))
    return dict(row) if row else None


def next_event_no(db: SurveyorDB) -> str:
    year = _dt.date.today().year
    pref = f"TS-MOV-{year}-"
    n = int(db.scalar("SELECT COUNT(*) FROM transfer_history WHERE event_no LIKE ?",
                      (pref + "%",), 0)) + 1
    while db.one("SELECT 1 FROM transfer_history WHERE event_no=?", (f"{pref}{n:05d}",)):
        n += 1
    return f"{pref}{n:05d}"


def _history_snapshot(rec: dict[str, Any] | sqlite3.Row | None) -> dict[str, Any]:
    row = dict(rec or {})
    return {
        "instrument_desc": str(row.get("instrument_desc") or "").strip(),
        "serial_no": str(row.get("serial_no") or "").strip(),
        "qty": to_float(row.get("qty") or 0),
        "holder": str(row.get("issued_to") or "").strip(),
        "employee_code": str(row.get("employee_code") or "").strip(),
        "iqama_id": str(row.get("iqama_id") or "").strip(),
        "designation": str(row.get("designation") or "").strip(),
        "division": str(row.get("division") or "").strip(),
        "project": str(row.get("current_project") or "").strip(),
        "location": str(row.get("location") or "").strip(),
        "status": str(row.get("status") or "").strip(),
    }


def _insert_history(db: SurveyorDB, record_id: int, event_type: str, event_date: str,
                    before: dict[str, Any] | sqlite3.Row | None,
                    after: dict[str, Any] | sqlite3.Row | None,
                    moved_by: str = "", remarks: str = "") -> int:
    left = _history_snapshot(before)
    right = _history_snapshot(after)
    cur = db.execute(
        """INSERT INTO transfer_history(event_no,record_id,event_type,event_date,instrument_desc,serial_no,qty,
             from_holder,from_employee_code,from_iqama_id,from_designation,from_division,from_project,from_location,from_status,
             to_holder,to_employee_code,to_iqama_id,to_designation,to_division,to_project,to_location,to_status,
             moved_by,remarks)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (next_event_no(db), int(record_id), str(event_type or EV_TRANSFER), str(event_date or today()),
         right.get("instrument_desc") or left.get("instrument_desc") or "",
         right.get("serial_no") or left.get("serial_no") or "",
         right.get("qty") or left.get("qty") or 0,
         left.get("holder", ""), left.get("employee_code", ""), left.get("iqama_id", ""), left.get("designation", ""),
         left.get("division", ""), left.get("project", ""), left.get("location", ""), left.get("status", ""),
         right.get("holder", ""), right.get("employee_code", ""), right.get("iqama_id", ""), right.get("designation", ""),
         right.get("division", ""), right.get("project", ""), right.get("location", ""), right.get("status", ""),
         str(moved_by or db.current_user or "").strip(), str(remarks or "").strip())
    )
    return int(cur.lastrowid)


def ensure_record_history(db: SurveyorDB, record_id: int) -> int:
    if int(db.scalar("SELECT COUNT(*) FROM transfer_history WHERE record_id=?", (int(record_id),), 0) or 0):
        return 0
    row = get_record(db, record_id)
    if not row:
        return 0
    event_date = str(row.get("created_at") or "")[:10] or today()
    event_type = EV_ISSUED if (row.get("issued_to") or row.get("employee_code") or row.get("iqama_id")
                               or row.get("status") == ST_IN_USE) else EV_REGISTERED
    hid = _insert_history(db, int(record_id), event_type, event_date, None, row,
                          moved_by=str(row.get("issued_by") or row.get("created_by") or db.current_user),
                          remarks=str(row.get("remarks") or ""))
    db.commit()
    return hid


def _copy_photo(src: str | Path) -> str:
    p = Path(src)
    if not p.exists() or not p.is_file():
        return ""
    dest_dir = photo_folder()
    ext = p.suffix.lower() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp") else ".png"
    stem = safe_name(p.stem, "photo")
    dest = dest_dir / f"{stem}{ext}"
    n = 2
    while dest.exists():
        dest = dest_dir / f"{stem}_{n}{ext}"
        n += 1
    shutil.copy2(p, dest)
    return str(dest)


def _photo_in_module(path: str | Path) -> bool:
    try:
        return Path(path).resolve().parent == photo_folder().resolve()
    except OSError:
        return False


def save_record(db: SurveyorDB, data: dict[str, Any], record_id: int | None = None) -> int:
    desc = str(data.get("instrument_desc") or "").strip()
    if not desc:
        raise ValueError("Instrument description is required.")
    second_type = str(data.get("second_type") or "").strip()
    serial = str(data.get("serial_no") or "").strip()
    make_model = str(data.get("make_model") or "").strip()
    location = str(data.get("location") or LOC_WAREHOUSE).strip() or LOC_WAREHOUSE
    qty = to_float(data.get("qty") or 0)
    if qty <= 0:
        raise ValueError("Quantity must be greater than zero.")
    status = str(data.get("status") or ST_ACTIVE).strip() or ST_ACTIVE
    if status not in STATUSES:
        status = ST_ACTIVE
    issued_to = str(data.get("issued_to") or "").strip()
    employee_code = str(data.get("employee_code") or "").strip()
    iqama_id = str(data.get("iqama_id") or "").strip()
    designation = str(data.get("designation") or "").strip()
    division = str(data.get("division") or "").strip()
    current_project = str(data.get("current_project") or "").strip()
    issued_by = str(data.get("issued_by") or db.current_user or "").strip()
    remarks = str(data.get("remarks") or "").strip()
    picture = str(data.get("picture_path") or "").strip()

    if status == ST_IN_USE:
        if not issued_to:
            raise ValueError("Issued items need an employee name.")
        if not (employee_code or iqama_id):
            raise ValueError("Enter the employee code or Iqama ID for issued items.")
    if (employee_code or iqama_id) and not issued_to:
        raise ValueError("Enter the employee name when you save an employee code or Iqama ID.")

    params: list[Any] = [serial]
    dup_sql = "SELECT id FROM records WHERE COALESCE(serial_no,'')=? AND COALESCE(serial_no,'')<>''"
    if record_id is not None:
        dup_sql += " AND id<>?"
        params.append(int(record_id))
    if serial and db.one(dup_sql, tuple(params)):
        raise ValueError(f"Serial number '{serial}' already exists in this register.")

    old = db.one("SELECT * FROM records WHERE id=?", (record_id,)) if record_id is not None else None
    final_picture = picture
    if picture and Path(picture).exists() and not _photo_in_module(picture):
        final_picture = _copy_photo(picture)
    elif not picture:
        final_picture = ""

    try:
        if record_id is None:
            cur = db.execute(
                """INSERT INTO records(instrument_desc,second_type,serial_no,make_model,location,qty,status,
                     issued_to,employee_code,iqama_id,designation,division,current_project,
                     issued_by,remarks,picture_path,created_by,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (desc, second_type, serial, make_model, location, qty, status, issued_to, employee_code,
                 iqama_id, designation, division, current_project, issued_by, remarks,
                 final_picture, db.current_user, _now()),
            )
            rec_id = int(cur.lastrowid)
            _insert_history(db, rec_id, EV_ISSUED if (issued_to or employee_code or iqama_id or status == ST_IN_USE) else EV_REGISTERED,
                            today(), None, {
                                "instrument_desc": desc, "second_type": second_type, "serial_no": serial, "qty": qty, "issued_to": issued_to,
                                "employee_code": employee_code, "iqama_id": iqama_id, "designation": designation,
                                "division": division, "current_project": current_project, "location": location, "status": status,
                            }, moved_by=issued_by or db.current_user, remarks=remarks)
            db.commit()
            db.audit("CREATED", "record", str(rec_id), desc)
            return rec_id
        db.execute(
            """UPDATE records SET instrument_desc=?, second_type=?, serial_no=?, make_model=?, location=?, qty=?,
                 status=?, issued_to=?, employee_code=?, iqama_id=?, designation=?,
                 division=?, current_project=?, issued_by=?, remarks=?, picture_path=?,
                 updated_at=? WHERE id=?""",
            (desc, second_type, serial, make_model, location, qty, status, issued_to, employee_code,
             iqama_id, designation, division, current_project, issued_by, remarks,
             final_picture, _now(), int(record_id)),
        )
        db.commit()
        if old and old["picture_path"] and old["picture_path"] != final_picture:
            _delete_photo_if_unused(db, str(old["picture_path"]))
        db.audit("EDITED", "record", str(record_id), desc)
        return int(record_id)
    except Exception:
        db.rollback()
        raise


def _delete_photo_if_unused(db: SurveyorDB, path: str) -> None:
    if not path or not _photo_in_module(path):
        return
    if db.scalar("SELECT COUNT(*) FROM records WHERE picture_path=?", (path,), 0):
        return
    try:
        Path(path).unlink()
    except OSError:
        pass


def delete_record(db: SurveyorDB, record_id: int) -> None:
    row = db.one("SELECT * FROM records WHERE id=?", (record_id,))
    if row is None:
        return
    picture = str(row["picture_path"] or "")
    desc = str(row["instrument_desc"] or "")
    db.execute("DELETE FROM transfer_history WHERE record_id=?", (record_id,))
    db.execute("DELETE FROM records WHERE id=?", (record_id,))
    db.commit()
    _delete_photo_if_unused(db, picture)
    db.audit("DELETED", "record", str(record_id), desc)


def transfer_history(db: SurveyorDB, record_id: int) -> list[dict[str, Any]]:
    ensure_record_history(db, int(record_id))
    rows = db.query("SELECT * FROM transfer_history WHERE record_id=? ORDER BY event_date, id", (int(record_id),))
    return [dict(r) for r in rows]


def transfer_record(db: SurveyorDB, record_id: int, data: dict[str, Any]) -> int:
    current = get_record(db, record_id)
    if not current:
        raise ValueError("Record not found.")
    ensure_record_history(db, int(record_id))
    moved_by = str(data.get("moved_by") or db.current_user or "").strip()
    event_date = str(data.get("event_date") or today()).strip() or today()
    remarks = str(data.get("remarks") or "").strip()
    payload = dict(current)
    payload.update({
        "location": str(data.get("location") or current.get("location") or LOC_WAREHOUSE).strip() or LOC_WAREHOUSE,
        "status": str(data.get("status") or current.get("status") or ST_ACTIVE).strip() or ST_ACTIVE,
        "issued_to": str(data.get("issued_to") or "").strip(),
        "employee_code": str(data.get("employee_code") or "").strip(),
        "iqama_id": str(data.get("iqama_id") or "").strip(),
        "designation": str(data.get("designation") or "").strip(),
        "division": str(data.get("division") or "").strip(),
        "current_project": str(data.get("current_project") or "").strip(),
        "issued_by": moved_by,
        "remarks": remarks or str(current.get("remarks") or ""),
        "picture_path": str(current.get("picture_path") or ""),
    })
    tracked_before = _history_snapshot(current)
    tracked_after = _history_snapshot(payload)
    if tracked_before == tracked_after:
        raise ValueError("Change the person, site, location or status before saving a transfer.")
    save_record(db, payload, int(record_id))
    fresh = get_record(db, int(record_id)) or payload
    hid = _insert_history(db, int(record_id), EV_TRANSFER, event_date, current, fresh,
                          moved_by=moved_by, remarks=remarks)
    db.commit()
    db.audit("TRANSFERRED", "record", str(record_id),
             f"{tracked_before.get('holder') or tracked_before.get('location') or '-'} -> "
             f"{tracked_after.get('holder') or tracked_after.get('location') or '-'}")
    return hid


def distinct_values(db: SurveyorDB, field: str) -> list[str]:
    if field not in {"instrument_desc", "second_type", "location", "status", "make_model", "issued_to", "employee_code", "division", "current_project"}:
        return []
    rows = db.query(
        f"SELECT DISTINCT {field} FROM records WHERE COALESCE({field},'')<>'' ORDER BY {field}"
    )
    return [str(r[0]) for r in rows if str(r[0] or "").strip()]


def list_records(db: SurveyorDB, text: str = "", location: str = "", status: str = "",
                 instrument_desc: str = "", second_type: str = "") -> list[dict[str, Any]]:
    sql = "SELECT * FROM records WHERE 1=1"
    p: list[Any] = []
    if location:
        sql += " AND location=?"
        p.append(location)
    if status:
        sql += " AND status=?"
        p.append(status)
    if instrument_desc:
        sql += " AND instrument_desc=?"
        p.append(instrument_desc)
    if second_type:
        sql += " AND second_type=?"
        p.append(second_type)
    if text.strip():
        like = f"%{text.strip()}%"
        sql += (" AND (instrument_desc LIKE ? OR second_type LIKE ? OR serial_no LIKE ? OR make_model LIKE ? OR"
                " location LIKE ? OR status LIKE ? OR remarks LIKE ? OR issued_to LIKE ? OR"
                " employee_code LIKE ? OR iqama_id LIKE ? OR designation LIKE ? OR division LIKE ? OR current_project LIKE ? OR issued_by LIKE ?)")
        p += [like] * 14
    sql += " ORDER BY instrument_desc COLLATE NOCASE, id DESC"
    return [dict(r) for r in db.query(sql, p)]


def summary_rows(db: SurveyorDB, records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = records if records is not None else list_records(db)
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        if str(r.get("status") or "") == ST_DISPOSED:
            continue
        desc = str(r.get("instrument_desc") or "").strip() or "(Blank description)"
        second_type = str(r.get("second_type") or "").strip() or "(Unspecified)"
        key = (second_type, desc)
        g = grouped.setdefault(key, {
            "second_type": second_type,
            "instrument_desc": desc,
            "Warehouse": 0.0,
            "Hajar": 0.0,
            "Zuluf": 0.0,
            "Yanbu": 0.0,
            "Noor": 0.0,
            "other": {},
            "total_qty": 0.0,
            "remarks_list": [],
            "out_of_order": 0.0,
            "under_repair": 0.0,
            "missing": 0.0,
        })
        qty = to_float(r.get("qty") or 0)
        loc = str(r.get("location") or "").strip() or LOC_WAREHOUSE
        if loc in DEFAULT_LOCATIONS:
            g[loc] += qty
        else:
            g["other"][loc] = g["other"].get(loc, 0.0) + qty
        g["total_qty"] += qty
        remark = str(r.get("remarks") or "").strip()
        if remark and remark not in g["remarks_list"]:
            g["remarks_list"].append(remark)
        status = str(r.get("status") or "")
        if status == ST_OUT_OF_ORDER:
            g["out_of_order"] += qty
        elif status == ST_UNDER_REPAIR:
            g["under_repair"] += qty
        elif status == ST_MISSING:
            g["missing"] += qty
    out: list[dict[str, Any]] = []
    ordered = sorted(grouped.values(), key=lambda g: (str(g["second_type"]).lower(), str(g["instrument_desc"]).lower()))
    for i, g in enumerate(ordered, start=1):
        remarks: list[str] = []
        if g["out_of_order"]:
            remarks.append(f"{g['out_of_order']:g} out of order")
        if g["under_repair"]:
            remarks.append(f"{g['under_repair']:g} under repair")
        if g["missing"]:
            remarks.append(f"{g['missing']:g} missing")
        if g["other"]:
            remarks.append("Other sites: " + ", ".join(
                f"{k} {v:g}" for k, v in sorted(g["other"].items())))
        remarks.extend(g["remarks_list"])
        out.append({
            "sr": i,
            "second_type": g["second_type"],
            "instrument_desc": g["instrument_desc"],
            "Warehouse": g["Warehouse"],
            "Hajar": g["Hajar"],
            "Zuluf": g["Zuluf"],
            "Yanbu": g["Yanbu"],
            "Noor": g["Noor"],
            "total_qty": g["total_qty"],
            "remarks": " · ".join(remarks),
        })
    return out


def _site_name(rec: dict[str, Any] | sqlite3.Row) -> str:
    row = dict(rec)
    return (str(row.get("current_project") or "").strip()
            or str(row.get("location") or "").strip()
            or LOC_WAREHOUSE)


def distinct_sites(db: SurveyorDB) -> list[str]:
    vals = {str(r.get("current_project") or "").strip() for r in list_records(db)}
    vals |= {str(r.get("location") or "").strip() for r in list_records(db)}
    return sorted(v for v in vals if v)


def analytics_rows(db: SurveyorDB, text: str = "", second_type: str = "", site: str = "",
                   location: str = "", status: str = "") -> list[dict[str, Any]]:
    rows = list_records(db, text=text, location=location, status=status, second_type=second_type)
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for r in rows:
        row_status = str(r.get("status") or ST_ACTIVE).strip() or ST_ACTIVE
        if row_status == ST_DISPOSED and status != ST_DISPOSED:
            continue
        row_site = _site_name(r)
        if site and row_site != site:
            continue
        row_type = str(r.get("second_type") or "").strip() or "(Unspecified)"
        desc = str(r.get("instrument_desc") or "").strip() or "(Blank description)"
        loc = str(r.get("location") or LOC_WAREHOUSE).strip() or LOC_WAREHOUSE
        key = (row_type, desc, row_site, loc, row_status)
        g = grouped.setdefault(key, {
            "second_type": row_type,
            "instrument_desc": desc,
            "site": row_site,
            "location": loc,
            "status": row_status,
            "qty": 0.0,
            "record_count": 0,
            "custodians": set(),
            "serials": set(),
        })
        g["qty"] += to_float(r.get("qty") or 0)
        g["record_count"] += 1
        holder = str(r.get("issued_to") or "").strip()
        if holder:
            g["custodians"].add(holder)
        serial = str(r.get("serial_no") or "").strip()
        if serial:
            g["serials"].add(serial)
    out: list[dict[str, Any]] = []
    for g in grouped.values():
        out.append({
            "second_type": g["second_type"],
            "instrument_desc": g["instrument_desc"],
            "site": g["site"],
            "location": g["location"],
            "status": g["status"],
            "qty": g["qty"],
            "record_count": g["record_count"],
            "custodians": ", ".join(sorted(g["custodians"])) or "Store custody",
            "serials": ", ".join(sorted(g["serials"])) or "—",
        })
    return sorted(out, key=lambda r: (
        str(r.get("site") or "").lower(),
        str(r.get("second_type") or "").lower(),
        -to_float(r.get("qty") or 0),
        str(r.get("instrument_desc") or "").lower(),
    ))


def analytics_data(db: SurveyorDB, text: str = "", second_type: str = "", site: str = "",
                   location: str = "", status: str = "") -> dict[str, Any]:
    rows = analytics_rows(db, text=text, second_type=second_type, site=site, location=location, status=status)
    by_site: dict[str, float] = {}
    by_type: dict[str, float] = {}
    by_item: dict[str, float] = {}
    custodians: set[str] = set()
    total_qty = 0.0
    for r in rows:
        qty = to_float(r.get("qty") or 0)
        total_qty += qty
        row_site = str(r.get("site") or "").strip() or LOC_WAREHOUSE
        row_type = str(r.get("second_type") or "").strip() or "(Unspecified)"
        item_label = f"{str(r.get('instrument_desc') or '').strip() or '(Blank description)'} @ {row_site}"
        by_site[row_site] = by_site.get(row_site, 0.0) + qty
        by_type[row_type] = by_type.get(row_type, 0.0) + qty
        by_item[item_label] = by_item.get(item_label, 0.0) + qty
        if str(r.get("custodians") or "") and str(r.get("custodians")) != "Store custody":
            custodians.update([c.strip() for c in str(r.get("custodians")).split(",") if c.strip()])
    return {
        "rows": rows,
        "row_count": len(rows),
        "total_qty": total_qty,
        "site_count": len(by_site),
        "second_type_count": len(by_type),
        "custodian_count": len(custodians),
        "by_site": sorted(by_site.items(), key=lambda kv: (-kv[1], kv[0].lower())),
        "by_second_type": sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0].lower())),
        "top_items": sorted(by_item.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:10],
    }


def sniff(text: str) -> tuple[list[str], list[list[str]]]:
    raw = [ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]
    if not raw:
        return [], []
    if "\t" in raw[0]:
        rows = [ln.split("\t") for ln in raw]
    elif raw[0].count(",") >= 2:
        rows = list(csv.reader(io.StringIO("\n".join(raw))))
    elif raw[0].count("|") >= 2:
        rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in raw]
    else:
        rows = [re.split(r"\s{2,}", ln.strip()) for ln in raw]
    rows = [[str(c).strip() for c in r] for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return [], []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head = rows[0]
    if sum(1 for c in head if norm_key(c) in HEADER_MAP) >= max(2, min(4, width)):
        return head, rows[1:]
    return [f"Column {i + 1}" for i in range(width)], rows


def read_file(path: str | Path) -> tuple[list[str], list[list[Any]]]:
    p = Path(path)
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(p, data_only=True, read_only=True)
        ws = wb.active
        data = [[("" if c is None else c) for c in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
        data = [r for r in data if any(str(c).strip() for c in r)]
        if not data:
            return [], []
        head = [str(c).strip() for c in data[0]]
        if sum(1 for c in head if norm_key(c) in HEADER_MAP) >= 2:
            return head, data[1:]
        return [f"Column {i + 1}" for i in range(len(head))], data
    return sniff(p.read_text(encoding="utf-8", errors="ignore"))


def auto_map(headers: Sequence[str]) -> dict[int, str]:
    out: dict[int, str] = {}
    used: set[str] = set()
    for i, h in enumerate(headers):
        field = HEADER_MAP.get(norm_key(h))
        if field and field not in used:
            out[i] = field
            used.add(field)
    return out


def preview(headers: Sequence[str], rows: Sequence[Sequence[Any]],
            mapping: dict[int, str], defaults: dict | None = None) -> list[dict[str, Any]]:
    defaults = defaults or {}
    out: list[dict[str, Any]] = []
    for row in rows:
        rec = {f: "" for f, _ in ALL_FIELDS}
        rec.update({k: v for k, v in defaults.items() if v not in (None, "")})
        for i, field in mapping.items():
            if i < len(row):
                rec[field] = row[i]
        rec["instrument_desc"] = str(rec.get("instrument_desc") or "").strip()
        rec["second_type"] = str(rec.get("second_type") or "").strip()
        rec["serial_no"] = str(rec.get("serial_no") or "").strip()
        rec["make_model"] = str(rec.get("make_model") or "").strip()
        rec["location"] = str(rec.get("location") or "").strip() or LOC_WAREHOUSE
        rec["qty"] = to_float(rec.get("qty") or 0)
        if rec["qty"] <= 0 and rec["instrument_desc"]:
            rec["qty"] = 1.0
        rec["issued_to"] = str(rec.get("issued_to") or "").strip()
        rec["employee_code"] = str(rec.get("employee_code") or "").strip()
        rec["iqama_id"] = str(rec.get("iqama_id") or "").strip()
        rec["designation"] = str(rec.get("designation") or "").strip()
        rec["division"] = str(rec.get("division") or "").strip()
        rec["current_project"] = str(rec.get("current_project") or "").strip()
        rec["issued_by"] = str(rec.get("issued_by") or "").strip()
        rec["remarks"] = str(rec.get("remarks") or "").strip()
        rec["picture_path"] = str(rec.get("picture_path") or "").strip()
        status_hint = rec.get("status")
        if not status_hint and (rec["issued_to"] or rec["employee_code"] or rec["iqama_id"]):
            status_hint = ST_IN_USE
        rec["status"] = _status_from_text(status_hint or ST_ACTIVE)
        if not rec["instrument_desc"]:
            continue
        if rec["qty"] <= 0:
            continue
        out.append(rec)
    return out


def _import_key(rec: dict | sqlite3.Row) -> tuple:
    row = dict(rec)
    serial = norm_key(row.get("serial_no"))
    if serial:
        return ("serial", serial)
    return (
        "row",
        norm_key(row.get("instrument_desc")),
        norm_key(row.get("second_type")),
        norm_key(row.get("make_model")),
        norm_key(row.get("location")),
        round(to_float(row.get("qty")), 3),
        norm_key(row.get("status")),
        norm_key(row.get("issued_to")),
        norm_key(row.get("employee_code")),
        norm_key(row.get("iqama_id")),
    )


def import_records(db: SurveyorDB, records: Sequence[dict[str, Any]], source: str = "",
                   skip_duplicates: bool = True) -> tuple[int, int]:
    existing: set[tuple] = set()
    if skip_duplicates:
        for row in db.query(
                "SELECT instrument_desc, second_type, serial_no, make_model, location, qty, status, issued_to, employee_code, iqama_id FROM records"):
            existing.add(_import_key(row))
    inserted = skipped = 0
    for rec in records:
        key = _import_key(rec)
        if skip_duplicates and key in existing:
            skipped += 1
            continue
        try:
            save_record(db, dict(rec))
            existing.add(key)
            inserted += 1
        except Exception:
            skipped += 1
    db.audit("IMPORTED", "sheet", "", f"{inserted} inserted, {skipped} skipped from {source}")
    return inserted, skipped


def template_rows() -> tuple[list[str], list[list[Any]]]:
    cols = [lbl for _, lbl in FIELDS]
    return cols, [
        ["Auto Level", "Instrument", "AL-100", "Leica", "Warehouse", 1, ST_ACTIVE, "", "", "", "", "", "", "Store Officer", "Ready stock", ""],
        ["Total Station", "Instrument", "TS-205", "Trimble", "Hajar", 1, ST_IN_USE, "Ahmed Salem", "EMP-1001", "2456677889", "Surveyor", "Survey", "Hajar", "Store Officer", "Issued for field use", ""],
        ["GPS", "Device", "GPS-310", "Garmin", "Yanbu", 1, ST_UNDER_REPAIR, "", "", "", "", "", "", "Store Officer", "Sent for repair", ""],
    ]


def dashboard_data(db: SurveyorDB, text: str = "", location: str = "", status: str = "") -> dict[str, Any]:
    rows = list_records(db, text=text, location=location, status=status)
    total_qty = sum(to_float(r.get("qty") or 0) for r in rows if str(r.get("status") or "") != ST_DISPOSED)
    out_of_order_qty = sum(to_float(r.get("qty") or 0) for r in rows if r.get("status") == ST_OUT_OF_ORDER)
    photo_count = sum(1 for r in rows if str(r.get("picture_path") or "").strip())
    loc_qty: dict[str, float] = {}
    stat_qty: dict[str, float] = {}
    desc_qty: dict[str, float] = {}
    recent = sorted(rows, key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)[:20]
    for r in rows:
        if str(r.get("status") or "") == ST_DISPOSED:
            continue
        qty = to_float(r.get("qty") or 0)
        loc = str(r.get("location") or LOC_WAREHOUSE).strip() or LOC_WAREHOUSE
        stat = str(r.get("status") or ST_ACTIVE).strip() or ST_ACTIVE
        desc = str(r.get("instrument_desc") or "(Blank description)").strip() or "(Blank description)"
        loc_qty[loc] = loc_qty.get(loc, 0.0) + qty
        stat_qty[stat] = stat_qty.get(stat, 0.0) + qty
        desc_qty[desc] = desc_qty.get(desc, 0.0) + qty
    top_desc = sorted(desc_qty.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:8]
    return {
        "records": rows,
        "record_count": len(rows),
        "total_qty": total_qty,
        "out_of_order_qty": out_of_order_qty,
        "photo_count": photo_count,
        "location_count": len([k for k, v in loc_qty.items() if v > 0]),
        "locations": sorted(loc_qty.items(), key=lambda kv: (-kv[1], kv[0].lower())),
        "statuses": sorted(stat_qty.items(), key=lambda kv: (-kv[1], kv[0].lower())),
        "top_descriptions": top_desc,
        "recent": recent,
    }


def latest_reference_no(db: SurveyorDB, record_id: int) -> str:
    ensure_record_history(db, int(record_id))
    row = db.one("SELECT event_no FROM transfer_history WHERE record_id=? ORDER BY id DESC LIMIT 1",
                 (int(record_id),))
    return str(row[0]) if row else ""


def _picture_report_entries(db: SurveyorDB, records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in records:
        row = dict(rec)
        pic = Path(str(row.get("picture_path") or "").strip())
        if not pic.exists() or not pic.is_file():
            continue
        out.append({
            "ref_no": latest_reference_no(db, int(row.get("id") or 0)) or f"REC-{int(row.get('id') or 0):05d}",
            "record": row,
            "picture_path": pic,
        })
    return out


def _build_picture_appendix_pdf(db: SurveyorDB, title: str, subtitle: str,
                                entries: Sequence[dict[str, Any]], out_path: Path) -> Path:
    from . import documents as D

    primary, accent = D._brand_colors(db)
    page_w = D.A4[0] - 24 * D.mm
    story: list[Any] = [
        D.Paragraph(title, D.P_TITLE),
        D._rule(primary, accent, page_w),
    ]
    if subtitle:
        story += [D.Paragraph(subtitle, D.P_SUB)]
    story += [D.Spacer(1, 3 * D.mm),
              D.Paragraph("<b>Pictures appendix</b>", D.P_MD),
              D.Paragraph("Photographs are attached at the end of the report together with the latest reference number, serial number and custody details for each tool.", D.P_SM),
              D.Spacer(1, 3 * D.mm)]
    first = True
    for entry in entries:
        rec = dict(entry["record"])
        pic = entry["picture_path"]
        try:
            img = D.Image(str(pic), width=82 * D.mm, height=62 * D.mm, kind="proportional")
        except Exception:
            continue
        meta = [
            ("Reference No.", entry.get("ref_no", "") or f"REC-{int(rec.get('id') or 0):05d}"),
            ("2nd Type", str(rec.get("second_type") or "") or "-"),
            ("Description", str(rec.get("instrument_desc") or "") or "-"),
            ("Serial No.", str(rec.get("serial_no") or "") or "-"),
            ("Make / Model", str(rec.get("make_model") or "") or "-"),
            ("Issued To", str(rec.get("issued_to") or "") or "Store custody"),
            ("Employee Code", str(rec.get("employee_code") or "") or "-"),
            ("Iqama ID", str(rec.get("iqama_id") or "") or "-"),
            ("Project / Site", str(rec.get("current_project") or "") or "-"),
            ("Location", str(rec.get("location") or "") or "-"),
            ("Status", str(rec.get("status") or "") or "-"),
            ("Qty", f"{to_float(rec.get('qty') or 0):g}"),
            ("Picture File", pic.name),
        ]
        detail = D._kv_block(meta, cols=1)
        box = D.Table([[detail, img]], colWidths=[96 * D.mm, 84 * D.mm])
        box.setStyle(D.TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.7, D.colors.HexColor("#c9d6e2")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, D.colors.HexColor("#dfe7ef")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        if not first:
            story.append(D.PageBreak())
        first = False
        story += [D.KeepTogether([
            D.Paragraph(f"<b>{str(rec.get('instrument_desc') or 'Tool')}</b>", D.P_MD),
            D.Spacer(1, 2 * D.mm),
            box,
        ])]
    if first:
        story.append(D.Paragraph("<i>No valid picture files were found for this report.</i>", D.P_MD))
    D._doc(out_path, False, db).build(
        story,
        onFirstPage=D._header_footer(db, "Report", True),
        onLaterPages=D._header_footer(db, "Report", True),
    )
    return out_path


def _merge_pdf_parts(target: Path, main_pdf: Path, appendix_pdf: Path | None = None) -> Path:
    if appendix_pdf is None or not appendix_pdf.exists():
        shutil.move(str(main_pdf), str(target))
        return target
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for src in (main_pdf, appendix_pdf):
        reader = PdfReader(str(src))
        for page in reader.pages:
            writer.add_page(page)
    with open(target, "wb") as fh:
        writer.write(fh)
    try:
        main_pdf.unlink()
    except OSError:
        pass
    try:
        appendix_pdf.unlink()
    except OSError:
        pass
    return target


def export_register_pdf(db: SurveyorDB, records: Sequence[dict[str, Any]], out_path: str | Path | None = None) -> Path:
    from . import documents as D

    rows = [dict(r) for r in records]
    out = Path(out_path) if out_path else (config.folder("Reports") /
                                           f"Tools_Station_Register_{_dt.datetime.now():%Y%m%d_%H%M%S}.pdf")
    tmp_main = out.with_name(out.stem + "__main.pdf")
    tmp_pic = out.with_name(out.stem + "__pictures.pdf")
    cols = ["2nd Type", "Description", "Serial No.", "Make / Model", "Location", "Issued To", "Employee Code",
            "Iqama ID", "Designation", "Division/Department", "Project / Site", "Status", "Qty",
            "Issued By", "Remarks", "Updated"]
    data = [[r.get("second_type", ""), r.get("instrument_desc", ""), r.get("serial_no", ""), r.get("make_model", ""),
             r.get("location", ""), r.get("issued_to", ""), r.get("employee_code", ""),
             r.get("iqama_id", ""), r.get("designation", ""), r.get("division", ""),
             r.get("current_project", ""), r.get("status", ""), float(r.get("qty") or 0),
             r.get("issued_by", ""), r.get("remarks", ""),
             r.get("updated_at", "") or r.get("created_at", "")]
            for r in rows]
    D.report_pdf(db, "Instrument Station Register", cols, data, out_path=tmp_main,
                 subtitle="Current filtered register view")
    entries = _picture_report_entries(db, rows)
    appendix = None
    if entries:
        appendix = _build_picture_appendix_pdf(
            db,
            "Instrument Station Register — Pictures Appendix",
            f"{len(entries)} tool photo(s) attached at the end of the report",
            entries,
            tmp_pic,
        )
    final = _merge_pdf_parts(out, tmp_main, appendix)
    db.audit("EXPORTED", "report", "Instrument Station Register", f"PDF -> {final.name}")
    return final


def export_history_pdf(db: SurveyorDB, record_id: int, out_path: str | Path | None = None) -> Path:
    from . import documents as D

    rec = get_record(db, int(record_id))
    if not rec:
        raise ValueError("Record not found.")
    hist = transfer_history(db, int(record_id))
    out = Path(out_path) if out_path else (config.folder("Reports") /
                                           f"Tools_Station_Transfer_History_{safe_name(str(rec.get('serial_no') or rec.get('instrument_desc') or record_id))}_{_dt.datetime.now():%Y%m%d_%H%M%S}.pdf")
    tmp_main = out.with_name(out.stem + "__main.pdf")
    tmp_pic = out.with_name(out.stem + "__pictures.pdf")
    cols = ["Event No", "Date", "Event", "From Holder", "From Site", "From Location",
            "To Holder", "To Site", "To Location", "Status", "Moved By", "Remarks"]
    data = [[h.get("event_no", ""), h.get("event_date", ""), h.get("event_type", ""),
             h.get("from_holder", ""), h.get("from_project", ""), h.get("from_location", ""),
             h.get("to_holder", ""), h.get("to_project", ""), h.get("to_location", ""),
             h.get("to_status", "") or h.get("from_status", ""), h.get("moved_by", ""), h.get("remarks", "")]
            for h in hist]
    subtitle = (f"Tool: {rec.get('instrument_desc', '') or '—'}  ·  Serial: {rec.get('serial_no', '') or '—'}  ·  "
                f"Current location: {rec.get('location', '') or '—'}")
    D.report_pdf(db, "Instrument Station Transfer History", cols, data, out_path=tmp_main, subtitle=subtitle)
    entries = _picture_report_entries(db, [rec])
    appendix = None
    if entries:
        appendix = _build_picture_appendix_pdf(
            db,
            "Instrument Station Transfer History — Picture Appendix",
            f"Reference number, serial number and current custody details for {rec.get('instrument_desc', '') or 'the selected tool'}.",
            entries,
            tmp_pic,
        )
    final = _merge_pdf_parts(out, tmp_main, appendix)
    db.audit("EXPORTED", "report", "Instrument Station Transfer History", f"PDF -> {final.name}")
    return final
