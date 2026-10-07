"""INSTRUMENT STATION — the instrument register, exactly as the site Excel sheet.

The register is deliberately shaped like the sheet the sites already fill in, so
nothing has to be translated on the way in or on the way out:

    Instrument Description · Serial No. · Make / Model · Location · Quantity ·
    Status · Issued To / Employee Name · Employee Code · Iqama ID ·
    Designation · Division/Department · Current Project · Issued By · Remarks

On top of that single table the module keeps **the movement track** — every
handover, transfer and return with who held the instrument, when it moved and
who signed it out — so the question "who has this instrument now, and since
when?" always has an answer.

Enforced physically, not by convention:

    ·  its own SQLite file        <storage>/Instrument Station/instrument_station.db
    ·  its own schema, numbering, audit trail, backups and pictures folder
    ·  no foreign key, join or import from items / stock_ledger / documents
    ·  nothing here ever posts a stock movement

Everything the user types goes through one place (`save_instrument`) and every
custody change goes through one place (`post_movement`), so a movement can never
exist without the instrument row agreeing with it.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import config

MODULE_NAME = "Instrument Station"
FOLDER = MODULE_NAME
LEGACY_FOLDERS = ("Tools Station", "Tools, Instruments & Devices", "Tool Station")
DB_NAME = "instrument_station.db"
LEGACY_DB_NAMES = ("tool_station.db", "tools_station.db", "surveyor_tools.db")

SCHEMA_VERSION = 3

# =========================================================== the register shape
# The single source of truth for the register: column key + printed heading.
# The UI grid, the Excel template, the importer and the reports all read this
# list, so the screen, the sheet and the PDF can never drift apart.
COLUMNS: list[tuple[str, str]] = [
    ("instrument_desc", "Instrument Description"),
    ("serial_no", "Serial No."),
    ("make_model", "Make / Model"),
    ("location", "Location"),
    ("quantity", "Quantity"),
    ("status", "Status"),
    ("issued_to", "Issued To / Employee Name"),
    ("employee_code", "Employee Code"),
    ("iqama_id", "Iqama ID"),
    ("designation", "Designation"),
    ("division", "Division/Department"),
    ("current_project", "Current Project"),
    ("issued_by", "Issued By"),
    ("remarks", "Remarks"),
]
COLUMN_KEYS: list[str] = [k for k, _ in COLUMNS]
COLUMN_LABELS: dict[str, str] = dict(COLUMNS)
LABELS = COLUMN_LABELS

# Kept alongside the sheet columns: not typed by hand every day, but exported,
# imported and searched like the rest.
EXTRA_COLUMNS: list[tuple[str, str]] = [
    ("site_name", "Site Name"),
    ("picture_path", "Picture Path"),
]
ALL_FIELDS: list[tuple[str, str]] = COLUMNS + EXTRA_COLUMNS
ALL_KEYS: list[str] = [k for k, _ in ALL_FIELDS]

# Columns that name a person — filled from the Employee Master when the code is
# typed, and written onto every movement so the history keeps the details of
# the day the instrument moved.
PERSON_FIELDS = ("issued_to", "employee_code", "iqama_id", "designation",
                 "division", "current_project")

# ---------------------------------------------------------------- status words
ST_AVAILABLE = "Available"
ST_ISSUED = "Issued"
ST_AT_SITE = "At Site"
ST_UNDER_REPAIR = "Under Repair"
ST_DAMAGED = "Damaged"
ST_LOST = "Lost"
ST_RETIRED = "Retired"

STATUSES = [ST_AVAILABLE, ST_ISSUED, ST_AT_SITE, ST_UNDER_REPAIR,
            ST_DAMAGED, ST_LOST, ST_RETIRED]
STATUS_COLORS = {
    ST_AVAILABLE: "#1a9c52",
    ST_ISSUED: "#1098ad",
    ST_AT_SITE: "#14538f",
    ST_UNDER_REPAIR: "#e8590c",
    ST_DAMAGED: "#c92a2a",
    ST_LOST: "#7048e8",
    ST_RETIRED: "#6b7c8f",
}
# A row with a holder is "out"; these statuses mean "not usable right now".
NOT_AVAILABLE = {ST_UNDER_REPAIR, ST_DAMAGED, ST_LOST, ST_RETIRED}
OUT_STATUSES = {ST_ISSUED, ST_AT_SITE}

# ------------------------------------------------------------- movement words
MV_REGISTERED = "Registered"
MV_ISSUED = "Issued"
MV_TRANSFERRED = "Transferred"
MV_RETURNED = "Returned"
MV_UPDATED = "Updated"

MOVEMENTS = [MV_REGISTERED, MV_ISSUED, MV_TRANSFERRED, MV_RETURNED, MV_UPDATED]
MOVEMENT_CODES = {MV_REGISTERED: "RG", MV_ISSUED: "IS",
                  MV_TRANSFERRED: "TR", MV_RETURNED: "RT", MV_UPDATED: "UP"}
MOVEMENT_COLORS = {
    MV_REGISTERED: "#6b7c8f",
    MV_ISSUED: "#1098ad",
    MV_TRANSFERRED: "#7048e8",
    MV_RETURNED: "#1a9c52",
    MV_UPDATED: "#e8590c",
}

ACTION_ISSUE = "Issue"
ACTION_TRANSFER = "Transfer"
ACTION_RETURN = "Return"

# --------------------------------------------------------------------- schema
DDL = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS audit (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT DEFAULT (datetime('now','localtime')),
    username  TEXT DEFAULT '',
    action    TEXT DEFAULT '',
    entity    TEXT DEFAULT '',
    entity_id TEXT DEFAULT '',
    details   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS instruments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_desc  TEXT DEFAULT '',
    serial_no        TEXT DEFAULT '',
    make_model       TEXT DEFAULT '',
    location         TEXT DEFAULT '',
    quantity         REAL NOT NULL DEFAULT 1,
    status           TEXT DEFAULT 'Available',
    issued_to        TEXT DEFAULT '',
    employee_code    TEXT DEFAULT '',
    iqama_id         TEXT DEFAULT '',
    designation      TEXT DEFAULT '',
    division         TEXT DEFAULT '',
    current_project  TEXT DEFAULT '',
    issued_by        TEXT DEFAULT '',
    remarks          TEXT DEFAULT '',
    site_name        TEXT DEFAULT '',
    picture_path     TEXT DEFAULT '',
    key_value        TEXT DEFAULT '',
    source           TEXT DEFAULT 'Manual Entry',
    source_file      TEXT DEFAULT '',
    file_hash        TEXT DEFAULT '',
    last_movement    TEXT DEFAULT '',
    last_movement_at TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now','localtime')),
    updated_at       TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_inst_serial   ON instruments(serial_no);
CREATE INDEX IF NOT EXISTS ix_inst_desc     ON instruments(instrument_desc);
CREATE INDEX IF NOT EXISTS ix_inst_status   ON instruments(status);
CREATE INDEX IF NOT EXISTS ix_inst_location ON instruments(location);
CREATE INDEX IF NOT EXISTS ix_inst_employee ON instruments(employee_code);

CREATE TABLE IF NOT EXISTS movements (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_no             TEXT DEFAULT '',
    instrument_id      INTEGER NOT NULL,
    movement_type      TEXT DEFAULT '',
    movement_date      TEXT DEFAULT '',
    from_holder        TEXT DEFAULT '',
    from_employee_code TEXT DEFAULT '',
    to_holder          TEXT DEFAULT '',
    to_employee_code   TEXT DEFAULT '',
    iqama_id           TEXT DEFAULT '',
    designation        TEXT DEFAULT '',
    division           TEXT DEFAULT '',
    current_project    TEXT DEFAULT '',
    location           TEXT DEFAULT '',
    quantity           REAL DEFAULT 0,
    status_after       TEXT DEFAULT '',
    issued_by          TEXT DEFAULT '',
    remarks            TEXT DEFAULT '',
    details            TEXT DEFAULT '',
    picture_path       TEXT DEFAULT '',
    source             TEXT DEFAULT 'Manual Entry',
    source_file        TEXT DEFAULT '',
    created_by         TEXT DEFAULT '',
    created_at         TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_mov_inst  ON movements(instrument_id);
CREATE INDEX IF NOT EXISTS ix_mov_type  ON movements(movement_type);
CREATE INDEX IF NOT EXISTS ix_mov_date  ON movements(movement_date);
CREATE INDEX IF NOT EXISTS ix_mov_emp   ON movements(to_employee_code);

CREATE TABLE IF NOT EXISTS sync_folders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    path          TEXT UNIQUE NOT NULL,
    label         TEXT DEFAULT '',
    site_name     TEXT DEFAULT '',
    auto_sync     INTEGER NOT NULL DEFAULT 0,
    sync_interval INTEGER NOT NULL DEFAULT 15,
    active        INTEGER NOT NULL DEFAULT 1,
    added_at      TEXT DEFAULT (datetime('now','localtime')),
    last_scan     TEXT DEFAULT '',
    last_success  TEXT DEFAULT '',
    last_error    TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sync_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id     INTEGER DEFAULT 0,
    path          TEXT UNIQUE NOT NULL,
    name          TEXT DEFAULT '',
    site_name     TEXT DEFAULT '',
    size_kb       REAL DEFAULT 0,
    modified      TEXT DEFAULT '',
    file_hash     TEXT DEFAULT '',
    status        TEXT DEFAULT 'New',
    last_sync     TEXT DEFAULT '',
    rows_total    INTEGER DEFAULT 0,
    rows_created  INTEGER DEFAULT 0,
    rows_updated  INTEGER DEFAULT 0,
    rows_failed   INTEGER DEFAULT 0,
    note          TEXT DEFAULT '',
    seen_at       TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_sf_status ON sync_files(status);
CREATE INDEX IF NOT EXISTS ix_sf_folder ON sync_files(folder_id);

CREATE TABLE IF NOT EXISTS sync_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT DEFAULT (datetime('now','localtime')),
    folder_id     INTEGER DEFAULT 0,
    file_id       INTEGER DEFAULT 0,
    source_file   TEXT DEFAULT '',
    site_name     TEXT DEFAULT '',
    status        TEXT DEFAULT '',
    total_rows    INTEGER DEFAULT 0,
    created_rows  INTEGER DEFAULT 0,
    updated_rows  INTEGER DEFAULT 0,
    failed_rows   INTEGER DEFAULT 0,
    details       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_sr_file ON sync_runs(file_id);
"""


# ------------------------------------------------------------------ smalltalk
def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return _dt.date.today().isoformat()


def norm(s: Any) -> str:
    """Lower-case, letters and digits only — the key for every heading match."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def to_float(v: Any, default: float = 0.0) -> float:
    if v in (None, ""):
        return default
    if isinstance(v, (int, float)):
        return float(v)
    t = re.sub(r"[^\d.\-]", "", str(v))
    try:
        return float(t) if t not in ("", "-", ".", "-.") else default
    except ValueError:
        return default


def fmt_qty(v: Any) -> str:
    n = to_float(v, 0)
    return f"{int(n)}" if abs(n - int(n)) < 1e-9 else f"{n:g}"


_DATE_PATTERNS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d",
    "%d/%m/%y", "%d-%m-%y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y",
    "%b %d, %Y", "%d %B %Y", "%m/%d/%Y",
)


def to_date(v: Any) -> str:
    """Best-effort conversion of anything date-like to ISO yyyy-mm-dd."""
    if v in (None, ""):
        return ""
    if isinstance(v, _dt.datetime):
        return v.date().isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    t = str(v).strip()
    if not t or t == "-":
        return ""
    for f in _DATE_PATTERNS:
        try:
            return _dt.datetime.strptime(t, f).date().isoformat()
        except ValueError:
            continue
    try:
        n = float(t)
        if 20000 < n < 60000:
            return (_dt.date(1899, 12, 30) + _dt.timedelta(days=int(n))).isoformat()
    except ValueError:
        pass
    return t


def fmt_date(iso: str) -> str:
    """ISO -> dd/mm/yyyy for screens and print."""
    try:
        return _dt.date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except Exception:          # noqa: BLE001
        return str(iso or "")


# ------------------------------------------------------------------- storage
def _migrate_legacy_folder() -> None:
    """Move older Tool/Instrument Station data folders into the new name."""
    root = config.get_storage_root() or config.default_storage_root()
    new = Path(root) / FOLDER
    for legacy_name in LEGACY_FOLDERS:
        old = Path(root) / legacy_name
        if not old.exists() or old == new:
            continue
        try:
            if not new.exists():
                old.rename(new)
                return
            for item in old.iterdir():
                target = new / item.name
                if target.exists():
                    continue
                shutil.move(str(item), str(target))
            if not any(old.iterdir()):
                old.rmdir()
        except OSError:
            continue


def module_folder() -> Path:
    _migrate_legacy_folder()
    return config.folder(FOLDER)


def db_path() -> Path:
    return module_folder() / DB_NAME


def pictures_dir() -> Path:
    p = module_folder() / "Pictures"
    p.mkdir(parents=True, exist_ok=True)
    return p


def evidence_dir() -> Path:          # old name, still the pictures folder
    return pictures_dir()


def backups_dir() -> Path:
    p = module_folder() / "Backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def store_picture(src: str | Path, hint: str = "instrument") -> str:
    """Copy a picture into the module's own Pictures folder.

    The file is *copied* — the original the user picked is never moved or
    renamed, so a photo on the desktop stays on the desktop.
    """
    src = Path(src)
    if not src.exists():
        return ""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", (hint or src.stem)).strip("_")[:40]
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = pictures_dir() / f"{stem or 'instrument'}_{stamp}{src.suffix.lower()}"
    n = 2
    while dest.exists():
        dest = pictures_dir() / f"{stem or 'instrument'}_{stamp}_{n}{src.suffix.lower()}"
        n += 1
    try:
        shutil.copy2(src, dest)
    except OSError:
        return ""
    return str(dest)


# -------------------------------------------------------------- employee link
def employee_lookup(db_main: Any, employee_code: str = "", iqama_id: str = "",
                    name: str = "") -> dict[str, str]:
    """Read the Employee Master (read-only) for one person.

    Returns {} when the person is not registered yet — that is not an error, the
    operator can still type the name and code by hand.
    """
    code = str(employee_code or "").strip()
    iqama = str(iqama_id or "").strip()
    nm = str(name or "").strip()
    if db_main is None or not (code or iqama or nm):
        return {}
    try:
        from . import employees as EMP
        row = EMP.find_employee(db_main, employee_id=code, iqama_id=iqama, name=nm)
    except Exception:          # noqa: BLE001 - a lookup must never break a form
        return {}
    if not row:
        return {}
    return {
        "employee_code": str(row.get("employee_id") or code).strip(),
        "issued_to": str(row.get("name") or nm).strip(),
        "iqama_id": str(row.get("iqama_id") or iqama).strip(),
        "designation": str(row.get("designation") or "").strip(),
        "division": str(row.get("division") or "").strip(),
        "current_project": str(row.get("current_project") or "").strip(),
        "location": str(row.get("location") or "").strip(),
    }


def apply_employee_defaults(record: dict[str, Any], db_main: Any) -> dict[str, Any]:
    """Fill the person columns from the Employee Master where they are blank."""
    out = dict(record or {})
    if db_main is None:
        return out
    if not any(str(out.get(f) or "").strip()
               for f in ("employee_code", "iqama_id", "issued_to")):
        return out
    # Only look the person up when the form clearly names them but the details
    # are still missing, so a deliberate override is never overwritten.
    if all(str(out.get(f) or "").strip()
           for f in ("designation", "division", "current_project")):
        return out
    found = employee_lookup(db_main, out.get("employee_code", ""),
                            out.get("iqama_id", ""), out.get("issued_to", ""))
    for key, val in found.items():
        if not str(out.get(key) or "").strip():
            out[key] = val
    return out


def employee_choices(db_main: Any) -> list[dict[str, str]]:
    """The Employee Master as a list of {code, name, iqama, ...} for pickers."""
    out: list[dict[str, str]] = []
    if db_main is None:
        return out
    try:
        rows = db_main.query(
            "SELECT employee_id, name, iqama_id, designation, division, "
            "current_project, location FROM employees "
            "WHERE COALESCE(employee_id,'')<>'' OR COALESCE(name,'')<>'' "
            "ORDER BY name")
    except Exception:          # noqa: BLE001
        return out
    for r in rows:
        d = dict(r)
        out.append({
            "employee_code": str(d.get("employee_id") or "").strip(),
            "issued_to": str(d.get("name") or "").strip(),
            "iqama_id": str(d.get("iqama_id") or "").strip(),
            "designation": str(d.get("designation") or "").strip(),
            "division": str(d.get("division") or "").strip(),
            "current_project": str(d.get("current_project") or "").strip(),
            "location": str(d.get("location") or "").strip(),
        })
    return out


# ------------------------------------------------------------------ database
class ToolDB:
    """Standalone database for the Instrument Station module."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or db_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._adopt_legacy_database()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.current_user = "admin"
        self._init()

    # ------------------------------------------------------------- schema
    def _adopt_legacy_database(self) -> None:
        """Keep the data of the older Tool/Instrument Station file.

        The register lives in the same shape either way, so the old file is
        copied (never moved — it stays as the customer's own safety copy) and
        the synced rows are carried over on first open.
        """
        if self.path.exists():
            return
        for legacy in LEGACY_DB_NAMES:
            old = self.path.parent / legacy
            if not old.exists():
                continue
            try:
                shutil.copy2(old, self.path)
            except OSError:
                continue
            self._legacy_source = old
            return

    def _journal_mode(self) -> str:
        p = str(self.path)
        networked = p.startswith("\\\\") or p.startswith("//")
        return "TRUNCATE" if networked else "WAL"

    def _init(self) -> None:
        try:
            self.conn.execute(f"PRAGMA journal_mode={self._journal_mode()}")
        except sqlite3.Error:
            pass
        self.conn.executescript(DDL)
        self.conn.commit()
        self._migrate()
        self._import_legacy_rows()

    def _migrate(self) -> None:
        """Additive migrations only — a column is added, never dropped."""
        wanted = {
            "instruments": {
                "site_name": "TEXT DEFAULT ''",
                "picture_path": "TEXT DEFAULT ''",
                "key_value": "TEXT DEFAULT ''",
                "source": "TEXT DEFAULT 'Manual Entry'",
                "source_file": "TEXT DEFAULT ''",
                "file_hash": "TEXT DEFAULT ''",
                "last_movement": "TEXT DEFAULT ''",
                "last_movement_at": "TEXT DEFAULT ''",
            },
            "movements": {
                "details": "TEXT DEFAULT ''",
                "picture_path": "TEXT DEFAULT ''",
                "source": "TEXT DEFAULT 'Manual Entry'",
                "source_file": "TEXT DEFAULT ''",
                "created_by": "TEXT DEFAULT ''",
            },
            "sync_files": {
                "site_name": "TEXT DEFAULT ''",
                "rows_total": "INTEGER DEFAULT 0",
                "rows_created": "INTEGER DEFAULT 0",
                "rows_updated": "INTEGER DEFAULT 0",
                "rows_failed": "INTEGER DEFAULT 0",
            },
            "sync_folders": {
                "site_name": "TEXT DEFAULT ''",
                "auto_sync": "INTEGER NOT NULL DEFAULT 0",
                "sync_interval": "INTEGER NOT NULL DEFAULT 15",
                "last_success": "TEXT DEFAULT ''",
                "last_error": "TEXT DEFAULT ''",
            },
        }
        for table, cols in wanted.items():
            have = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for col, ddl in cols.items():
                if col not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        self.conn.commit()
        self.set_setting("schema_version", str(SCHEMA_VERSION))

    def _import_legacy_rows(self) -> None:
        """Carry the old tool_station.db site_inventory rows into the register."""
        if getattr(self, "_legacy_done", False):
            return
        self._legacy_done = True
        # Carry the old tool_station.db site_inventory rows into the register.
        if not getattr(self, "_legacy_source", None):
            return
        if self.scalar("SELECT COUNT(*) FROM instruments") > 0:
            return
        try:
            src = sqlite3.connect(str(self._legacy_source))
        except sqlite3.Error:
            return
        try:
            src.row_factory = sqlite3.Row
            tables = {r[0] for r in src.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "site_inventory" not in tables:
                return
            rows = src.execute("SELECT * FROM site_inventory").fetchall()
        except sqlite3.Error:
            return
        finally:
            src.close()
        moved = 0
        for r in rows:
            d = dict(r)
            rec = {
                "instrument_desc": d.get("description", ""),
                "serial_no": d.get("serial_no", ""),
                "make_model": d.get("make_model", ""),
                "location": d.get("location", ""),
                "quantity": d.get("qty", 1),
                "status": d.get("status", "") or ST_AVAILABLE,
                "issued_to": d.get("holder", ""),
                "employee_code": d.get("employee_code", ""),
                "iqama_id": d.get("iqama_id", ""),
                "designation": d.get("designation", ""),
                "division": d.get("department", ""),
                "current_project": d.get("project_id", ""),
                "issued_by": d.get("issued_by", ""),
                "remarks": d.get("remarks", ""),
                "site_name": d.get("site_name", ""),
                "picture_path": d.get("picture_path", ""),
                "source": "Excel Sync",
                "source_file": d.get("source_file", ""),
                "file_hash": d.get("file_hash", ""),
            }
            if not (str(rec["instrument_desc"]).strip() or str(rec["serial_no"]).strip()):
                continue
            try:
                save_instrument(self, rec, movement_type=MV_REGISTERED,
                                source="Excel Sync",
                                source_file=str(rec["source_file"] or "legacy import"))
                moved += 1
            except (ValueError, sqlite3.Error):
                continue
        if moved:
            self.audit("IMPORTED", "register", "", f"{moved} row(s) from the previous register file")

    # --------------------------------------------------------- primitives
    def execute(self, sql: str, params: Sequence = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def query(self, sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def one(self, sql: str, params: Sequence = ()):
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence = (), default: Any = 0) -> Any:
        r = self.conn.execute(sql, params).fetchone()
        return default if r is None or r[0] is None else r[0]

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:          # noqa: BLE001
            pass

    # ----------------------------------------------------------- settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, str(value)))
        self.conn.commit()

    def audit(self, action: str, entity: str = "", entity_id: str = "",
              details: str = "") -> None:
        self.execute("INSERT INTO audit(ts,username,action,entity,entity_id,details)"
                     " VALUES(?,?,?,?,?,?)",
                     (_now(), self.current_user, action, entity,
                      str(entity_id), details))
        self.conn.commit()

    # ------------------------------------------------------------ backups
    def backup(self, dest_folder: str | Path | None = None, note: str = "") -> Path:
        dest = Path(dest_folder or backups_dir())
        dest.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = dest / f"instrument_station_{stamp}.db"
        n = 2
        while out.exists():
            out = dest / f"instrument_station_{stamp}_{n}.db"
            n += 1
        self.conn.commit()
        tgt = sqlite3.connect(str(out))
        with tgt:
            self.conn.backup(tgt)
        tgt.close()
        self.audit("BACKUP", "database", out.name, note)
        return out

    def restore(self, src: str | Path) -> None:
        src = Path(src)
        if not src.exists():
            raise FileNotFoundError(src)
        safety = self.backup(note=f"safety copy before restoring {src.name}")
        if safety.resolve() == src.resolve():
            raise ValueError("Refusing to restore a file over itself.")
        incoming = sqlite3.connect(str(src))
        try:
            with self.conn:
                incoming.backup(self.conn)
        finally:
            incoming.close()
        self.audit("RESTORE", "database", src.name, f"safety copy: {safety.name}")


_db: ToolDB | None = None


def get_tool_db() -> ToolDB:
    """The one module connection the running application shares."""
    global _db
    if _db is None or not _db.path.exists():
        _db = ToolDB()
    return _db


def set_tool_db(db: ToolDB | None) -> None:
    global _db
    _db = db


def reset_tool_db() -> None:
    global _db
    if _db is not None:
        _db.close()
    _db = None


# ---------------------------------------------------------- record building
def instrument_key(rec: dict[str, Any]) -> str:
    """The identity of an instrument, as steady as the sheet allows.

    Serial number first — it is unique in the physical world — then the make /
    model, then the description together with its location.
    """
    serial = norm(rec.get("serial_no"))
    if serial:
        return f"SN:{serial}"
    desc = norm(rec.get("instrument_desc"))
    make = norm(rec.get("make_model"))
    if desc:
        return f"DS:{desc}|{make}|{norm(rec.get('location'))}"
    return ""


def instrument_title(rec: dict[str, Any]) -> str:
    desc = str(rec.get("instrument_desc") or "").strip() or "Instrument"
    serial = str(rec.get("serial_no") or "").strip()
    return f"{desc} ({serial})" if serial else desc


def normalize_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Coerce anything sheet-shaped into one clean register row."""
    out: dict[str, Any] = {k: str(rec.get(k, "") or "").strip() for k in ALL_KEYS}
    out["quantity"] = to_float(rec.get("quantity", rec.get("qty", 1)), 1) or 1
    if not out["location"]:
        out["location"] = out.get("site_name", "")
    if not out["site_name"]:
        out["site_name"] = out.get("location", "")
    status = str(rec.get("status") or "").strip()
    out["status"] = status or (
        ST_ISSUED if out["issued_to"] else
        (ST_AT_SITE if out["location"] and norm(out["location"]) != "warehouse"
         else ST_AVAILABLE))
    if not (out["instrument_desc"] or out["serial_no"]):
        raise ValueError("Enter at least an instrument description or a serial number.")
    out["key_value"] = instrument_key(out)
    return out


def _fill_person_from_master(db: ToolDB, data: dict[str, Any],
                             db_main: Any) -> None:
    if db_main is None:
        return
    found = employee_lookup(db_main, data.get("employee_code", ""),
                            data.get("iqama_id", ""), data.get("issued_to", ""))
    for key in PERSON_FIELDS:
        val = str(found.get(key) or "").strip()
        if val and not str(data.get(key) or "").strip():
            data[key] = val
    if not str(data.get("issued_to") or "").strip() and found.get("issued_to"):
        data["issued_to"] = found["issued_to"]


def _changed_fields(before: dict[str, Any] | None,
                    after: dict[str, Any]) -> list[str]:
    if not before:
        return []
    out = []
    for key, _ in ALL_FIELDS + [("quantity", "Quantity")]:
        if key in ("qty",):
            continue
        b = before.get(key)
        a = after.get(key)
        if key == "quantity":
            if abs(to_float(b, 0) - to_float(a, 0)) > 1e-9:
                out.append(_label_of(key))
            continue
        if str(b or "").strip() != str(a or "").strip():
            out.append(_label_of(key))
    return out


def _label_of(key: str) -> str:
    for k, label in ALL_FIELDS:
        if k == key:
            return label
    return key.replace("_", " ").title()


# ------------------------------------------------------------- the register
def save_instrument(db: ToolDB, data: dict[str, Any],
                    instrument_id: int | None = None,
                    movement_type: str = "",
                    source: str = "Manual Entry",
                    source_file: str = "",
                    file_hash_value: str = "",
                    db_main: Any = None,
                    quiet: bool = False) -> dict[str, Any]:
    """Create or update one register row and keep the movement track honest."""
    before = get_instrument(db, instrument_id) if instrument_id else None
    if instrument_id and before is None:
        raise ValueError("This instrument is no longer in the register.")
    payload = dict(data or {})
    _fill_person_from_master(db, payload, db_main)
    rec = normalize_record(payload)
    if not rec["key_value"]:
        rec["key_value"] = instrument_key(rec)

    clash = db.one("SELECT id, instrument_desc FROM instruments "
                   "WHERE key_value=? AND id<>?",
                   (rec["key_value"], instrument_id or 0))
    if clash:
        # Same serial, same place — update that row instead of storing it twice.
        raise ValueError(
            f"Serial {rec['serial_no'] or rec['instrument_desc']} is already in the "
            f"register ({clash['instrument_desc']}). Edit that row instead.")

    now = _now()
    if before is None:
        cols = ALL_KEYS + ["key_value", "source", "source_file", "file_hash",
                           "created_at", "updated_at"]
        vals = [rec[k] if k != "quantity" else to_float(rec["quantity"], 1)
                for k in ALL_KEYS]
        sql = (f"INSERT INTO instruments ({','.join(cols)}) "
               f"VALUES ({','.join('?' * len(cols))})")
        cur = db.execute(sql, vals + [rec["key_value"], source, source_file,
                                      file_hash_value, now, now])
        instrument_id = int(cur.lastrowid)
        moved = movement_type or MV_REGISTERED
        post_movement(db, instrument_id, moved, movement_date=today(),
                      location=rec["location"], quantity=rec["quantity"],
                      status_after=rec["status"], issued_by=rec["issued_by"],
                      remarks=rec["remarks"], source=source,
                      source_file=source_file, quiet=True)
    else:
        changes = _changed_fields(before, rec)
        sets = []
        params: list[Any] = []
        for key in ALL_KEYS:
            val = to_float(rec[key], 1) if key == "quantity" else rec[key]
            sets.append(f"{key}=?")
            params.append(val)
        sets += ["key_value=?", "source_file=?", "file_hash=?",
                 "updated_at=?", "source=?"]
        params += [rec["key_value"], source_file or before.get("source_file", ""),
                   file_hash_value or before.get("file_hash", ""), now,
                   source or before.get("source", "Manual Entry")]
        db.execute(f"UPDATE instruments SET {', '.join(sets)} WHERE id=?",
                   params + [instrument_id])
        if changes and not quiet:
            post_movement(db, instrument_id, movement_type or MV_UPDATED,
                          movement_date=today(), location=rec["location"],
                          quantity=rec["quantity"], status_after=rec["status"],
                          issued_by=rec["issued_by"], remarks=rec["remarks"],
                          details="Changed: " + ", ".join(changes),
                          source=source, source_file=source_file, quiet=True)
    db.commit()
    db.audit("SAVED" if before is None else "UPDATED", "instrument",
             str(instrument_id), instrument_title(rec))
    row = get_instrument(db, instrument_id)
    return row or {}


def get_instrument(db: ToolDB, instrument_id: int | None) -> dict[str, Any] | None:
    if not instrument_id:
        return None
    r = db.one("SELECT * FROM instruments WHERE id=?", (int(instrument_id),))
    return dict(r) if r else None


def find_instrument(db: ToolDB, serial: str = "",
                    description: str = "") -> dict[str, Any] | None:
    if str(serial or "").strip():
        r = db.one("SELECT * FROM instruments WHERE serial_no=? COLLATE NOCASE",
                   (str(serial).strip(),))
        if r:
            return dict(r)
    if str(description or "").strip():
        r = db.one("SELECT * FROM instruments WHERE instrument_desc=? COLLATE NOCASE",
                   (str(description).strip(),))
        if r:
            return dict(r)
    return None


def find_by_key(db: ToolDB, rec: dict[str, Any]) -> dict[str, Any] | None:
    """The row this sheet line belongs to — serial first, then description+place.

    A shared description on its own never merges two instruments, so a site
    sheet with three identical "TRIPOD" lines still stores three rows.
    """
    key = instrument_key(rec)
    if key:
        r = db.one("SELECT * FROM instruments WHERE key_value=?", (key,))
        if r:
            return dict(r)
    if str(rec.get("serial_no") or "").strip():
        return find_instrument(db, serial=rec.get("serial_no", ""))
    return None


def delete_instruments(db: ToolDB, ids: Iterable[int]) -> int:
    """Remove rows (and their history) — only what the user ticked."""
    gone = 0
    for i in [int(x) for x in ids if x]:
        row = get_instrument(db, i)
        if not row:
            continue
        db.execute("DELETE FROM movements WHERE instrument_id=?", (i,))
        db.execute("DELETE FROM instruments WHERE id=?", (i,))
        db.audit("DELETED", "instrument", str(i), instrument_title(row))
        gone += 1
    db.commit()
    return gone


def search_instruments(db: ToolDB, text: str = "", status: str = "",
                       location: str = "", division: str = "",
                       project: str = "", employee_code: str = "",
                       holder: str = "", issued_only: bool = False,
                       available_only: bool = False, with_picture: bool = False,
                       order: str = "description") -> list[dict[str, Any]]:
    """Filter the register the way the dashboard and the grid need it."""
    sql = "SELECT * FROM instruments WHERE 1=1"
    params: list[Any] = []
    like = f"%{str(text).strip()}%"
    if str(text).strip():
        sql += (" AND (instrument_desc LIKE ? OR serial_no LIKE ? OR make_model LIKE ?"
                " OR location LIKE ? OR status LIKE ? OR issued_to LIKE ?"
                " OR employee_code LIKE ? OR iqama_id LIKE ? OR designation LIKE ?"
                " OR division LIKE ? OR current_project LIKE ? OR issued_by LIKE ?"
                " OR remarks LIKE ?)")
        params += [like] * 13
    for column, value in (("status", status), ("location", location),
                          ("division", division), ("current_project", project),
                          ("employee_code", employee_code), ("issued_to", holder)):
        if str(value or "").strip():
            sql += f" AND {column}=? COLLATE NOCASE"
            params.append(str(value).strip())
    if issued_only:
        sql += " AND TRIM(COALESCE(issued_to,''))<>''"
    if available_only:
        sql += " AND TRIM(COALESCE(issued_to,''))=''"
    if with_picture:
        sql += " AND TRIM(COALESCE(picture_path,''))<>''"
    order_by = {
        "description": "instrument_desc COLLATE NOCASE, serial_no",
        "serial": "serial_no COLLATE NOCASE",
        "location": "location COLLATE NOCASE, instrument_desc",
        "status": "status, instrument_desc",
        "employee": "issued_to COLLATE NOCASE, instrument_desc",
        "updated": "updated_at DESC, id DESC",
        "recent": "id DESC",
    }.get(order, "instrument_desc COLLATE NOCASE, serial_no")
    sql += f" ORDER BY {order_by}"
    return [dict(r) for r in db.query(sql, params)]


def distinct_values(db: ToolDB, column: str) -> list[str]:
    column = column if column in ALL_KEYS else "location"
    rows = db.query(
        f"SELECT DISTINCT {column} v FROM instruments "
        f"WHERE TRIM(COALESCE({column},''))<>'' ORDER BY v COLLATE NOCASE")
    return [str(r["v"]) for r in rows]


def register_total(db: ToolDB) -> dict[str, Any]:
    """Headline numbers for the module banner."""
    rows = db.scalar("SELECT COUNT(*) FROM instruments")
    qty = to_float(db.scalar("SELECT SUM(quantity) FROM instruments", (), 0), 0)
    held = db.scalar("SELECT COUNT(*) FROM instruments "
                     "WHERE TRIM(COALESCE(issued_to,''))<>''")
    movements = db.scalar("SELECT COUNT(*) FROM movements")
    return {"rows": rows, "quantity": qty, "holders": held, "out": held,
            "movements": movements}


# ------------------------------------------------------------- movements
def next_movement_ref(db: ToolDB, movement_type: str,
                      date: str = "") -> str:
    """IS-261007-01 style, unique per type and day."""
    d = to_date(date) or today()
    try:
        stamp = _dt.date.fromisoformat(d).strftime("%y%m%d")
    except ValueError:
        stamp = _dt.date.today().strftime("%y%m%d")
    code = MOVEMENT_CODES.get(movement_type, "MV")
    base = f"{code}-{stamp}"
    n = 1
    while db.one("SELECT 1 FROM movements WHERE ref_no=?", (f"{base}-{n:02d}",)):
        n += 1
    return f"{base}-{n:02d}"


def post_movement(db: ToolDB, instrument_id: int, movement_type: str,
                  movement_date: str = "", to_holder: str = "",
                  to_employee_code: str = "", iqama_id: str = "",
                  designation: str = "", division: str = "",
                  current_project: str = "", location: str = "",
                  quantity: float | None = None, status_after: str = "",
                  issued_by: str = "", remarks: str = "",
                  picture_path: str = "", details: str = "",
                  source: str = "Manual Entry", source_file: str = "",
                  db_main: Any = None, quiet: bool = False) -> dict[str, Any]:
    """Record one movement and move the register row with it.

    Issue / transfer put the instrument in somebody's hands; return takes it
    back. The person columns are copied onto the movement, so the history keeps
    the employee's details as they were on the day of the handover.
    """
    row = get_instrument(db, instrument_id)
    if row is None:
        raise ValueError("Select an instrument in the register first.")
    movement_type = movement_type or MV_UPDATED

    if to_employee_code or iqama_id or to_holder:
        found = employee_lookup(db_main, to_employee_code or row.get("employee_code", ""),
                                iqama_id or row.get("iqama_id", ""), to_holder)
        to_holder = to_holder or found.get("issued_to", "")
        to_employee_code = to_employee_code or found.get("employee_code", "")
        iqama_id = iqama_id or found.get("iqama_id", "")
        designation = designation or found.get("designation", "")
        division = division or found.get("division", "")
        current_project = current_project or found.get("current_project", "")
        location = location or found.get("location", "") or row.get("location", "")

    date = to_date(movement_date) or today()
    qty = to_float(quantity if quantity is not None else row.get("quantity"), 1) or 1
    from_holder = str(row.get("issued_to") or "")
    from_code = str(row.get("employee_code") or "")

    if movement_type == MV_RETURNED:
        to_holder, to_employee_code = "", ""
        iqama_id, designation = "", ""
        division, current_project = "", ""
        status_after = status_after or ST_AVAILABLE
        out_holder = ""
    elif movement_type in (MV_ISSUED, MV_TRANSFERRED):
        if not to_holder:
            raise ValueError("Enter who the instrument is being handed to.")
        if movement_type == MV_TRANSFERRED and not from_holder:
            movement_type = MV_ISSUED
        status_after = status_after or ST_ISSUED
        out_holder = to_holder
    else:
        out_holder = to_holder or from_holder
        status_after = status_after or row.get("status", ST_AVAILABLE)

    if status_after in NOT_AVAILABLE and movement_type != MV_RETURNED:
        # damaged / under repair still belongs to its holder until returned
        out_holder = to_holder or from_holder

    location = str(location or row.get("location") or "").strip()
    ref = next_movement_ref(db, movement_type, date)
    db.execute(
        """INSERT INTO movements (ref_no, instrument_id, movement_type, movement_date,
                                  from_holder, from_employee_code, to_holder,
                                  to_employee_code, iqama_id, designation, division,
                                  current_project, location, quantity, status_after,
                                  issued_by, remarks, details, picture_path, source,
                                  source_file, created_by, created_at)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ref, instrument_id, movement_type, date, from_holder, from_code, to_holder,
         to_employee_code, iqama_id, designation, division, current_project,
         location, qty, status_after, issued_by or row.get("issued_by", ""),
         remarks, details or "", picture_path, source, source_file,
         db.current_user, _now()))

    fields: dict[str, Any] = {
        "location": location,
        "quantity": qty,
        "status": status_after,
        "site_name": location or row.get("site_name", ""),
        "last_movement": movement_type,
        "last_movement_at": date,
        "updated_at": _now(),
    }
    if movement_type == MV_RETURNED:
        # the custodian's own columns go back to empty — the instrument is in store
        for key in PERSON_FIELDS:
            fields[key] = ""
    elif movement_type in (MV_ISSUED, MV_TRANSFERRED):
        fields.update({"issued_to": to_holder, "employee_code": to_employee_code,
                       "iqama_id": iqama_id, "designation": designation,
                       "division": division, "current_project": current_project})
    else:
        # Registered / Updated: never blank what the register already knows
        for key, val in (("issued_to", out_holder),
                         ("employee_code", to_employee_code),
                         ("iqama_id", iqama_id), ("designation", designation),
                         ("division", division),
                         ("current_project", current_project)):
            if str(val or "").strip():
                fields[key] = val
    if remarks:
        fields["remarks"] = remarks
    if picture_path:
        fields["picture_path"] = picture_path
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE instruments SET {sets} WHERE id=?",
               list(fields.values()) + [instrument_id])
    db.commit()
    if not quiet:
        db.audit(movement_type.upper(), "instrument", str(instrument_id),
                 f"{ref} {instrument_title(row)}")
    out = db.one("SELECT * FROM movements WHERE ref_no=?", (ref,))
    return dict(out) if out else {}


def _change(db: ToolDB, instrument_id: int, movement_type: str, **kw) -> dict:
    kw.setdefault("movement_date", today())
    return post_movement(db, instrument_id, movement_type, **kw)


def issue_instrument(db: ToolDB, instrument_id: int, **kw) -> dict:
    kw.setdefault("status_after", ST_ISSUED)
    return _change(db, instrument_id, MV_ISSUED, **kw)


def transfer_instrument(db: ToolDB, instrument_id: int, **kw) -> dict:
    kw.setdefault("status_after", ST_ISSUED)
    return _change(db, instrument_id, MV_TRANSFERRED, **kw)


def return_instrument(db: ToolDB, instrument_id: int, **kw) -> dict:
    kw.setdefault("status_after", ST_AVAILABLE)
    return _change(db, instrument_id, MV_RETURNED, **kw)


def instrument_history(db: ToolDB, instrument_id: int,
                       limit: int = 500) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT * FROM movements WHERE instrument_id=? "
        "ORDER BY movement_date DESC, id DESC LIMIT ?",
        (int(instrument_id), int(limit)))
    return [dict(r) for r in rows]


def all_movements(db: ToolDB, text: str = "", movement_type: str = "",
                  date_from: str = "", date_to: str = "", employee_code: str = "",
                  instrument_id: int = 0, limit: int = 3000) -> list[dict[str, Any]]:
    """The movement register: one line per handover, transfer and return."""
    sql = ("SELECT m.*, i.instrument_desc, i.serial_no, i.make_model "
           "FROM movements m LEFT JOIN instruments i ON i.id=m.instrument_id "
           "WHERE 1=1")
    params: list[Any] = []
    if str(text).strip():
        like = f"%{str(text).strip()}%"
        sql += (" AND (i.instrument_desc LIKE ? OR i.serial_no LIKE ?"
                " OR m.ref_no LIKE ? OR m.to_holder LIKE ? OR m.from_holder LIKE ?"
                " OR m.to_employee_code LIKE ? OR m.location LIKE ?"
                " OR m.current_project LIKE ? OR m.remarks LIKE ?)")
        params += [like] * 9
    if str(movement_type or "").strip():
        sql += " AND m.movement_type=?"
        params.append(str(movement_type).strip())
    if str(date_from or "").strip():
        sql += " AND m.movement_date>=?"
        params.append(to_date(date_from))
    if str(date_to or "").strip():
        sql += " AND m.movement_date<=?"
        params.append(to_date(date_to))
    if str(employee_code or "").strip():
        sql += " AND (m.to_employee_code=? OR m.from_employee_code=?)"
        params += [str(employee_code).strip()] * 2
    if instrument_id:
        sql += " AND m.instrument_id=?"
        params.append(int(instrument_id))
    sql += " ORDER BY m.movement_date DESC, m.id DESC LIMIT ?"
    params.append(int(limit))
    return [dict(r) for r in db.query(sql, params)]


def movement_ref(db: ToolDB, movement_id: int) -> dict[str, Any] | None:
    r = db.one("SELECT * FROM movements WHERE id=?", (int(movement_id),))
    return dict(r) if r else None


def delete_movements(db: ToolDB, ids: Iterable[int]) -> int:
    gone = 0
    for i in [int(x) for x in ids if x]:
        db.execute("DELETE FROM movements WHERE id=?", (i,))
        gone += 1
    db.commit()
    return gone


def custody_by_person(db: ToolDB) -> list[dict[str, Any]]:
    """Who is holding what right now — the question the module exists for."""
    rows = db.query(
        """SELECT issued_to, employee_code, iqama_id, designation, division,
                  current_project, COUNT(*) rows_held, SUM(quantity) quantity,
                  GROUP_CONCAT(DISTINCT instrument_desc) instruments
             FROM instruments
            WHERE TRIM(COALESCE(issued_to,''))<>''
            GROUP BY issued_to, employee_code
            ORDER BY rows_held DESC, issued_to COLLATE NOCASE""")
    return [dict(r) for r in rows]


def movements_between(db: ToolDB, date_from: str = "", date_to: str = "") -> list[dict]:
    return all_movements(db, date_from=date_from, date_to=date_to)


# ---------------------------------------------------------------- dashboard
DEFAULT_FILTERS: dict[str, Any] = {
    "text": "", "status": "", "location": "", "division": "",
    "project": "", "employee_code": "", "issued_only": False,
}


def _month_key(iso: str) -> str:
    return str(iso or "")[:7]


def dashboard(db: ToolDB, f: dict | None = None) -> dict[str, Any]:
    """Every number the Instrument Station dashboard shows."""
    f = dict(f or {})
    rows = search_instruments(
        db, text=f.get("text", ""), status=f.get("status", ""),
        location=f.get("location", ""), division=f.get("division", ""),
        project=f.get("project", ""), employee_code=f.get("employee_code", ""),
        issued_only=bool(f.get("issued_only")))
    qty = sum(to_float(r.get("quantity"), 0) for r in rows)
    issued = [r for r in rows if str(r.get("issued_to") or "").strip()]
    available = [r for r in rows if not str(r.get("issued_to") or "").strip()]
    people = {r["issued_to"] for r in issued if r.get("issued_to")}
    issues = sum(1 for r in rows if r.get("status") == ST_ISSUED)
    at_site = sum(1 for r in rows if r.get("status") == ST_AT_SITE)
    repair = sum(1 for r in rows if r.get("status") == ST_UNDER_REPAIR)
    damaged = sum(1 for r in rows if r.get("status") == ST_DAMAGED)
    lost = sum(1 for r in rows if r.get("status") == ST_LOST)
    pictures = sum(1 for r in rows if str(r.get("picture_path") or "").strip())
    issued_qty = sum(to_float(r.get("quantity"), 0) for r in issued)

    by_location = _group(rows, "location", qty_measure=True)
    by_status = [(s, sum(1 for r in rows if r.get("status") == s))
                 for s in STATUSES]
    by_status = [(s, n) for s, n in by_status if n]
    by_project = _group(rows, "current_project", qty_measure=True)
    by_division = _group(rows, "division", qty_measure=True)
    by_description = _group(rows, "instrument_desc")
    by_employee = _group(issued, "issued_to")

    movements = all_movements(
        db, text=f.get("text", ""), employee_code=f.get("employee_code", ""))
    if f.get("location"):
        movements = [m for m in movements if m.get("location") == f["location"]]
    months = _month_series(movements, 12)
    recent = all_movements(db, limit=12)

    return {
        "rows": len(rows),
        "quantity": qty,
        "total_qty": qty,
        "issued": len(issued),
        "issued_qty": issued_qty,
        "available": len(available),
        "available_qty": sum(to_float(r.get("quantity"), 0) for r in available),
        "holders": len(people),
        "employees": len(people),
        "issued_status": issues,
        "at_site": at_site,
        "repair": repair,
        "damaged": damaged,
        "lost": lost,
        "pictures": pictures,
        "sites": len({r["location"] for r in rows if r.get("location")}),
        "locations": len({r["location"] for r in rows if r.get("location")}),
        "projects": len({r["current_project"] for r in rows if r.get("current_project")}),
        "movements": len(movements),
        "movements_30": _recent_moves(movements, 30),
        "transfers": sum(1 for m in movements if m.get("movement_type") == MV_TRANSFERRED),
        "returns": sum(1 for m in movements if m.get("movement_type") == MV_RETURNED),
        "issues": sum(1 for m in movements if m.get("movement_type") == MV_ISSUED),
        "by_location": by_location,
        "by_status": by_status,
        "by_project": by_project,
        "by_division": by_division,
        "by_description": by_description,
        "by_employee": by_employee,
        "by_custodian": by_employee,
        "months": [m for m, _ in months],
        "monthly": months,
        "monthly_issued": months,
        "recent": recent,
        "recent_rows": recent,
        "all": rows,
    }


def _group(rows: Sequence[dict], column: str,
           qty_measure: bool = False) -> list[tuple[str, float]]:
    agg: dict[str, float] = {}
    for r in rows:
        key = str(r.get(column) or "").strip() or "(not set)"
        agg[key] = agg.get(key, 0.0) + (to_float(r.get("quantity"), 0) if qty_measure else 1.0)
    return sorted(agg.items(), key=lambda kv: -kv[1])[:12]


def _month_series(movements: Sequence[dict], months: int = 12) -> list[tuple[str, float]]:
    """Issued quantities per month, oldest first — the trend line."""
    today_d = _dt.date.today()
    keys: list[str] = []
    y, m = today_d.year, today_d.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    keys.reverse()
    agg = {k: 0.0 for k in keys}
    for mv in movements:
        k = _month_key(mv.get("movement_date"))
        if k in agg and mv.get("movement_type") in (MV_ISSUED, MV_TRANSFERRED):
            agg[k] += to_float(mv.get("quantity"), 0)
    return [(k, agg[k]) for k in keys]


def _recent_moves(movements: Sequence[dict], days: int) -> int:
    cut = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    return sum(1 for m in movements if str(m.get("movement_date") or "") >= cut)


# ====================================================== site-wise Excel sync
# Headings exactly as they appear on the sites' sheet, plus the spellings seen
# in the wild — the matcher below is deliberately forgiving.
EXCEL_HEADER_MAP: dict[str, str] = {
    # Instrument Description
    "instrumentdescription": "instrument_desc", "instrument": "instrument_desc",
    "description": "instrument_desc", "itemdescription": "instrument_desc",
    "itemname": "instrument_desc", "item": "instrument_desc",
    "toolname": "instrument_desc", "equipment": "instrument_desc",
    "equipmentdescription": "instrument_desc", "instrumentname": "instrument_desc",
    # Serial No.
    "serialno": "serial_no", "serial": "serial_no", "sn": "serial_no",
    "serialnumber": "serial_no", "srno": "serial_no", "sr": "serial_no",
    "instrumentserial": "serial_no",
    # Make / Model
    "makemodel": "make_model", "make": "make_model", "model": "make_model",
    "brand": "make_model", "makemodelno": "make_model",
    "makeandmodel": "make_model", "brandmodel": "make_model",
    # Location
    "location": "location", "currentlocation": "location",
    "locationname": "location", "site": "location", "sitename": "location",
    "store": "location", "warehouse": "location", "placed": "location",
    # Quantity
    "quantity": "quantity", "qty": "quantity", "nos": "quantity",
    "no": "quantity", "totalquantity": "quantity", "totalqty": "quantity",
    # Status
    "status": "status", "currentstatus": "status", "condition": "status",
    "instrumentstatus": "status",
    # Issued To / Employee Name
    "issuedtoemployeename": "issued_to", "issuedto": "issued_to",
    "employeename": "issued_to", "handedto": "issued_to", "holder": "issued_to",
    "issuedtoto": "issued_to", "custodian": "issued_to",
    "nameofemployee": "issued_to", "assignedto": "issued_to",
    # Employee Code
    "employeecode": "employee_code", "employeeid": "employee_code",
    "empid": "employee_code", "empcode": "employee_code",
    "employeeno": "employee_code", "staffid": "employee_code",
    # Iqama ID
    "iqamaid": "iqama_id", "iqama": "iqama_id", "iqamano": "iqama_id",
    "idiqama": "iqama_id", "idno": "iqama_id", "idnumber": "iqama_id",
    # Designation
    "designation": "designation", "jobtitle": "designation",
    "position": "designation", "job": "designation", "trade": "designation",
    # Division / Department
    "divisiondepartment": "division", "division": "division",
    "department": "division", "dept": "division", "divisiondept": "division",
    # Current Project
    "currentproject": "current_project", "project": "current_project",
    "projectname": "current_project", "projectsite": "current_project",
    "projectno": "current_project", "siteproject": "current_project",
    # Issued By
    "issuedby": "issued_by", "responsibleperson": "issued_by",
    "handedoverby": "issued_by", "issueby": "issued_by", "storekeeper": "issued_by",
    # Remarks
    "remarks": "remarks", "remark": "remarks", "remarksdefects": "remarks",
    "remarkdefects": "remarks", "reamrks": "remarks", "notes": "remarks",
    # Extras carried by richer sheets
    "picturepath": "picture_path", "photopath": "picture_path",
    "imagepath": "picture_path", "photo": "picture_path", "picture": "picture_path",
}
EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".csv", ".txt")

# The template the user downloads is exactly the register heading order.
TEMPLATE_HEADINGS: list[str] = [label for _, label in COLUMNS]


def excel_template_rows() -> tuple[list[str], list[list[Any]]]:
    cols = list(TEMPLATE_HEADINGS)
    rows = [
        ["TOTAL STATION", "1338275", "LEICA (TS02)", "NOOR", 1, "Issued",
         "ZOHAIB BILAL", "IDL-0040", "2482103955", "Surveyor", "SURVEY", "NOOR",
         "M. Ali Zain", ""],
        ["AUTO LEVEL", "5778779", "LEICA (NA2)", "Warehouse", 1, "Available",
         "", "", "", "", "", "", "", ""],
    ]
    return cols, rows


def _row_score(row: Sequence[Any]) -> int:
    return sum(1 for c in row if norm(c) in EXCEL_HEADER_MAP)


def _prepare_rows(data: Sequence[Sequence[Any]]) -> list[list[Any]]:
    rows = [list(r) for r in data if any(str(c).strip() for c in (r or []))]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    return [list(r) + [""] * (width - len(r)) for r in rows]


def _header_and_body(data: list[list[Any]]) -> tuple[list[str], list[list[Any]]]:
    """Find the real heading row, even when a title block sits above it."""
    best_i, best = 0, -1
    for i, row in enumerate(data[:20]):
        score = _row_score(row)
        if score > best:
            best_i, best = i, score
    if best < 3:
        return [f"Column {i + 1}" for i in range(len(data[0]))], data
    head = [str(c).strip() for c in data[best_i]]
    return head, data[best_i + 1:]


def excel_read_table(path: str | Path) -> tuple[list[str], list[list[Any]]]:
    """Read a site workbook, choosing the sheet that looks most like the sheet."""
    p = Path(path)
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(p, data_only=True, read_only=True)
        best_data: list[list[Any]] = []
        best_rank = (-1, -1, -1)
        try:
            for ws in wb.worksheets:
                sheet_data = _prepare_rows(
                    [[("" if c is None else c) for c in row]
                     for row in ws.iter_rows(values_only=True)])
                if not sheet_data:
                    continue
                score = max((_row_score(r) for r in sheet_data[:20]), default=-1)
                filled = sum(1 for row in sheet_data for c in row if str(c).strip())
                rank = (score, filled, len(sheet_data))
                if rank > best_rank:
                    best_rank, best_data = rank, sheet_data
        finally:
            wb.close()
        data = best_data
    else:
        raw = p.read_text(encoding="utf-8", errors="ignore")
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        sample = "\n".join(lines[:8])[:4096] or ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ","
        data = list(csv.reader(io.StringIO(raw), dialect))
        if data and max(len(r) for r in data) <= 1 and "|" in raw:
            data = list(csv.reader(io.StringIO(raw), delimiter="|"))
        data = _prepare_rows(data)
    if not data:
        return [], []
    return _header_and_body(data)


# The name the Excel panel has always used — kept so saved scripts still run.
site_sync_read_table = excel_read_table


def excel_auto_map(headers: Sequence[str]) -> dict[int, str]:
    """Best-guess column map for one sheet, tolerant of small wording changes."""
    out: dict[int, str] = {}
    used: set[str] = set()
    probes = sorted(EXCEL_HEADER_MAP.items(), key=lambda kv: len(kv[0]), reverse=True)
    for i, h in enumerate(headers):
        key = norm(h)
        if not key:
            continue
        field = EXCEL_HEADER_MAP.get(key)
        if not field:
            for probe, mapped in probes:
                if mapped in used and mapped not in ("remarks",):
                    continue
                if len(probe) >= 4 and (key.startswith(probe) or key.endswith(probe)
                                        or probe in key):
                    field = mapped
                    break
        if field and (field not in used or field == "remarks"):
            out[i] = field
            used.add(field)
    return out


def site_sync_auto_map(headers: Sequence[str]) -> dict[int, str]:
    return excel_auto_map(headers)


def excel_preview(headers: Sequence[str], rows: Sequence[Sequence[Any]],
                  mapping: dict[int, str] | None = None,
                  defaults: dict | None = None) -> list[dict[str, Any]]:
    """Turn mapped sheet rows into register records (nothing is saved yet)."""
    m = dict(mapping or excel_auto_map(headers))
    defaults = dict(defaults or {})
    out: list[dict[str, Any]] = []
    for raw in rows:
        rec: dict[str, Any] = {k: "" for k in ALL_KEYS}
        for i, field in m.items():
            if field and i < len(raw):
                val = raw[i]
                rec[field] = "" if val is None else (
                    val if isinstance(val, (int, float)) else str(val).strip())
        merged = {**defaults, **{k: v for k, v in rec.items() if str(v).strip() != ""}}
        for key in ("site_name", "location", "division", "current_project",
                    "status", "issued_by"):
            if not str(merged.get(key) or "").strip() and defaults.get(key):
                merged[key] = defaults[key]
        try:
            clean = normalize_record(merged)
        except ValueError:
            continue
        clean["_source"] = "Excel Sync"
        out.append(clean)
    return out


def site_sync_preview(headers: Sequence[str], rows: Sequence[Sequence[Any]],
                      mapping: dict[int, str] | None = None,
                      defaults: dict | None = None) -> list[dict[str, Any]]:
    return excel_preview(headers, rows, mapping, defaults)


def site_sync_template_rows() -> tuple[list[str], list[list[Any]]]:
    return excel_template_rows()


# ------------------------------------------------------------ sync folders
def sync_folders(db: ToolDB, active_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM sync_folders"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY label COLLATE NOCASE, path"
    return [dict(r) for r in db.query(sql)]


def save_sync_folder(db: ToolDB, path: str | Path, label: str = "",
                     site_name: str = "", auto_sync: bool = False,
                     sync_interval: int = 15,
                     folder_id: int | None = None) -> int:
    p = str(Path(path))
    if not Path(p).exists():
        raise FileNotFoundError(f"The folder does not exist:\n{p}")
    if folder_id:
        db.execute("UPDATE sync_folders SET path=?, label=?, site_name=?, "
                   "auto_sync=?, sync_interval=? WHERE id=?",
                   (p, label, site_name, 1 if auto_sync else 0,
                    int(sync_interval), int(folder_id)))
        db.commit()
        db.audit("UPDATED", "sync folder", str(folder_id), p)
        return int(folder_id)
    existing = db.one("SELECT id FROM sync_folders WHERE path=?", (p,))
    if existing:
        db.execute("UPDATE sync_folders SET label=?, site_name=?, active=1 WHERE id=?",
                   (label, site_name, int(existing["id"])))
        db.commit()
        return int(existing["id"])
    cur = db.execute(
        "INSERT INTO sync_folders (path,label,site_name,auto_sync,sync_interval)"
        " VALUES (?,?,?,?,?)",
        (p, label or Path(p).name, site_name, 1 if auto_sync else 0,
         int(sync_interval)))
    db.commit()
    db.audit("ADDED", "sync folder", str(cur.lastrowid), p)
    return int(cur.lastrowid)


def remove_sync_folder(db: ToolDB, folder_id: int) -> None:
    db.execute("DELETE FROM sync_folders WHERE id=?", (int(folder_id),))
    db.commit()


def sync_folder_status(path: str | Path) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, "Folder not found"
    if not p.is_dir():
        return False, "Not a folder"
    files = [f for f in p.iterdir()
             if f.is_file() and f.suffix.lower() in EXCEL_SUFFIXES]
    return True, f"{len(files)} sheet file(s)"


def file_hash(path: str | Path, limit_mb: int = 32) -> str:
    import hashlib
    h = hashlib.sha256()
    p = Path(path)
    try:
        with p.open("rb") as fh:
            read = 0
            while True:
                chunk = fh.read(1024 * 256)
                if not chunk:
                    break
                h.update(chunk)
                read += len(chunk)
                if read > limit_mb * 1024 * 1024:
                    break
    except OSError:
        return ""
    return h.hexdigest()


def scan_sync_files(db: ToolDB, folder_id: int | None = None, status: str = "",
                    text: str = "") -> list[dict[str, Any]]:
    sql = "SELECT * FROM sync_files WHERE 1=1"
    params: list[Any] = []
    if folder_id:
        sql += " AND folder_id=?"
        params.append(int(folder_id))
    if str(status or "").strip():
        sql += " AND status=?"
        params.append(str(status).strip())
    if str(text or "").strip():
        like = f"%{str(text).strip()}%"
        sql += " AND (name LIKE ? OR note LIKE ? OR site_name LIKE ?)"
        params += [like] * 3
    sql += " ORDER BY seen_at DESC, id DESC"
    return [dict(r) for r in db.query(sql, params)]


def sync_runs(db: ToolDB, file_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    sql = "SELECT * FROM sync_runs"
    params: list[Any] = []
    if file_id:
        sql += " WHERE file_id=?"
        params.append(int(file_id))
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    return [dict(r) for r in db.query(sql, params)]


def _track_file(db: ToolDB, path: Path, folder_id: int,
                site_name: str) -> dict[str, Any]:
    stat = path.stat()
    h = file_hash(path)
    row = db.one("SELECT * FROM sync_files WHERE path=?", (str(path),))
    if row:
        db.execute("UPDATE sync_files SET size_kb=?, modified=?, file_hash=?, "
                   "site_name=COALESCE(NULLIF(?,''), site_name), seen_at=? WHERE id=?",
                   (round(stat.st_size / 1024, 1),
                    _dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    h, site_name, _now(), int(row["id"])))
        db.commit()
        return dict(db.one("SELECT * FROM sync_files WHERE id=?", (int(row["id"]),)))
    cur = db.execute(
        "INSERT INTO sync_files (folder_id,path,name,site_name,size_kb,modified,"
        "file_hash,status,seen_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (int(folder_id), str(path), path.name, site_name,
         round(stat.st_size / 1024, 1),
         _dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
         h, "New", _now()))
    db.commit()
    return dict(db.one("SELECT * FROM sync_files WHERE id=?", (int(cur.lastrowid),)))


def _log_run(db: ToolDB, folder_id: int, file_id: int, source_file: str,
             site_name: str, status: str, res: dict) -> None:
    db.execute(
        "INSERT INTO sync_runs (folder_id,file_id,source_file,site_name,status,"
        "total_rows,created_rows,updated_rows,failed_rows,details)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (int(folder_id), int(file_id), source_file, site_name, status,
         int(res.get("total", 0)), int(res.get("created", 0)),
         int(res.get("updated", 0)), int(res.get("failed", 0)),
         "; ".join(res.get("errors", [])[:8])))
    db.commit()


def import_records(db: ToolDB, records: Sequence[dict], source_file: str = "",
                   site_name: str = "", folder_id: int = 0, file_id: int = 0,
                   file_hash_value: str = "", db_main: Any = None,
                   movement_type: str = MV_REGISTERED,
                   source: str = "Excel Sync") -> dict[str, Any]:
    """Upsert preview records into the register and log the movement."""
    res = {"total": len(records), "created": 0, "updated": 0, "failed": 0,
           "errors": [], "ids": []}
    for rec in records:
        data = {k: rec.get(k, "") for k in ALL_KEYS}
        if site_name:
            data["site_name"] = data.get("site_name") or site_name
            data["location"] = data.get("location") or site_name
        _fill_person_from_master(db, data, db_main)
        try:
            clean = normalize_record(data)
        except ValueError as exc:
            res["failed"] += 1
            res["errors"].append(str(exc))
            continue
        existing = find_by_key(db, clean)
        try:
            if existing:
                before = dict(existing)
                save_instrument(db, clean, instrument_id=int(existing["id"]),
                                source=source, source_file=source_file,
                                file_hash_value=file_hash_value,
                                db_main=db_main, quiet=True)
                after = get_instrument(db, int(existing["id"])) or {}
                changed = _changed_fields(before, after)
                if changed:
                    post_movement(db, int(existing["id"]),
                                  _movement_for_change(before, after),
                                  movement_date=today(),
                                  to_holder=after.get("issued_to", ""),
                                  to_employee_code=after.get("employee_code", ""),
                                  iqama_id=after.get("iqama_id", ""),
                                  designation=after.get("designation", ""),
                                  division=after.get("division", ""),
                                  current_project=after.get("current_project", ""),
                                  location=after.get("location", ""),
                                  quantity=after.get("quantity", 1),
                                  status_after=after.get("status", ""),
                                  issued_by=after.get("issued_by", ""),
                                  details="Excel sync: " + ", ".join(changed),
                                  source=source, source_file=source_file,
                                  quiet=True)
                res["updated"] += 1
                res["ids"].append(int(existing["id"]))
            else:
                row = save_instrument(db, clean, movement_type=movement_type,
                                      source=source, source_file=source_file,
                                      file_hash_value=file_hash_value,
                                      db_main=db_main, quiet=True)
                res["created"] += 1
                res["ids"].append(int(row.get("id") or 0))
        except (ValueError, sqlite3.Error) as exc:
            res["failed"] += 1
            res["errors"].append(f"{clean.get('instrument_desc') or clean.get('serial_no')}: {exc}")
    db.commit()
    return res


def _movement_for_change(before: dict, after: dict) -> str:
    b_holder = norm(before.get("issued_to"))
    a_holder = norm(after.get("issued_to"))
    if b_holder != a_holder:
        if not a_holder:
            return MV_RETURNED
        if not b_holder:
            return MV_ISSUED
        return MV_TRANSFERRED
    return MV_UPDATED


def import_site_sync_preview_records(db: ToolDB, records: Sequence[dict],
                                     source_file: str, assigned_site: str = "",
                                     folder_id: int | None = None,
                                     file_hash_value: str = "",
                                     db_main: Any = None) -> dict[str, Any]:
    return import_records(db, records, source_file=source_file,
                          site_name=assigned_site or "",
                          folder_id=int(folder_id or 0),
                          file_hash_value=file_hash_value, db_main=db_main)


def sync_file(db: ToolDB, path: str | Path, folder_id: int = 0,
              site_name: str = "", force: bool = False,
              db_main: Any = None) -> dict[str, Any]:
    """Read one site sheet into the register. Never moves the source file."""
    p = Path(path)
    res: dict[str, Any] = {"file": p.name, "status": "", "total": 0, "created": 0,
                           "updated": 0, "failed": 0, "errors": [], "skipped": False}
    if not p.exists():
        res["status"] = "Missing"
        res["errors"].append("file not found")
        return res
    if p.suffix.lower() not in EXCEL_SUFFIXES:
        res["status"] = "Ignored"
        res["errors"].append("not a sheet file")
        return res
    tracked = _track_file(db, p, folder_id, site_name or p.parent.name)
    file_id = int(tracked["id"])
    if not force and tracked.get("file_hash") and tracked.get("status") in (
            "Imported", "Up to date") and tracked.get("file_hash") == file_hash(p):
        res["status"] = "Up to date"
        res["skipped"] = True
        return res
    try:
        headers, rows = excel_read_table(p)
    except Exception as exc:           # noqa: BLE001
        res["status"] = "Unreadable"
        res["errors"].append(str(exc))
        _finish_file(db, file_id, "Unreadable", res, folder_id, site_name)
        return res
    if not headers or not rows:
        res["status"] = "Empty"
        res["errors"].append("no rows found")
        _finish_file(db, file_id, "Empty", res, folder_id, site_name)
        return res
    mapping = excel_auto_map(headers)
    if not mapping:
        res["status"] = "Nothing mapped"
        res["errors"].append(
            "no recognisable instrument columns — expected headings like "
            + ", ".join(TEMPLATE_HEADINGS[:5]))
        _finish_file(db, file_id, "Nothing mapped", res, folder_id, site_name)
        return res
    defaults = {"site_name": site_name} if site_name else {}
    records = excel_preview(headers, rows, mapping, defaults)
    res["mapped"] = len(mapping)
    if not records:
        res["status"] = "Nothing mapped"
        res["errors"].append("no usable rows after mapping")
        _finish_file(db, file_id, "Nothing mapped", res, folder_id, site_name)
        return res
    got = import_records(db, records, source_file=str(p),
                         site_name=site_name, folder_id=folder_id,
                         file_id=file_id,
                         file_hash_value=str(tracked.get("file_hash") or ""),
                         db_main=db_main)
    res.update({k: got[k] for k in ("total", "created", "updated", "failed")})
    res["errors"] = got["errors"]
    res["status"] = "Imported" if not got["failed"] else "Imported with errors"
    _finish_file(db, file_id, res["status"], res, folder_id, site_name)
    return res


def _finish_file(db: ToolDB, file_id: int, status: str, res: dict,
                 folder_id: int, site_name: str) -> None:
    db.execute("UPDATE sync_files SET status=?, last_sync=?, rows_total=?, "
               "rows_created=?, rows_updated=?, rows_failed=?, note=? WHERE id=?",
               (status, _now(), int(res.get("total", 0)), int(res.get("created", 0)),
                int(res.get("updated", 0)), int(res.get("failed", 0)),
                "; ".join(res.get("errors", [])[:4]), int(file_id)))
    if folder_id:
        ok = status in ("Imported", "Up to date")
        db.execute("UPDATE sync_folders SET last_scan=?, "
                   "last_success=CASE WHEN ? THEN ? ELSE last_success END, "
                   "last_error=CASE WHEN ? THEN '' ELSE ? END WHERE id=?",
                   (_now(), 1 if ok else 0, _now(), 1 if ok else 0,
                    "; ".join(res.get("errors", [])[:2]), int(folder_id)))
    db.commit()
    _log_run(db, folder_id, file_id, res.get("file", ""), site_name, status, res)


def sync_folder(db: ToolDB, folder_id: int, force: bool = False,
                db_main: Any = None) -> dict[str, Any]:
    folder = db.one("SELECT * FROM sync_folders WHERE id=?", (int(folder_id),))
    if folder is None:
        raise ValueError("That sync folder is no longer registered.")
    root = Path(folder["path"])
    out: dict[str, Any] = {"folder": folder["label"] or root.name, "files": 0,
                           "created": 0, "updated": 0, "failed": 0, "skipped": 0,
                           "errors": [], "results": []}
    if not root.exists():
        out["errors"].append(f"folder not found: {root}")
        db.execute("UPDATE sync_folders SET last_error=? WHERE id=?",
                   (str(out["errors"][0]), int(folder_id)))
        db.commit()
        return out
    files = sorted(f for f in root.rglob("*")
                   if f.is_file() and f.suffix.lower() in EXCEL_SUFFIXES
                   and not f.name.startswith("~$") and not f.name.startswith("."))
    out["files"] = len(files)
    for f in files:
        res = sync_file(db, f, folder_id=int(folder_id),
                        site_name=str(folder["site_name"] or ""),
                        force=force, db_main=db_main)
        out["created"] += int(res.get("created", 0))
        out["updated"] += int(res.get("updated", 0))
        out["failed"] += int(res.get("failed", 0))
        if res.get("skipped"):
            out["skipped"] += 1
        out["errors"] += res.get("errors", [])
        out["results"].append(res)
    db.execute("UPDATE sync_folders SET last_scan=? WHERE id=?", (_now(), int(folder_id)))
    db.commit()
    return out


def sync_all_folders(db: ToolDB, force: bool = False,
                     db_main: Any = None) -> dict[str, Any]:
    out = {"folders": 0, "files": 0, "created": 0, "updated": 0, "failed": 0,
           "skipped": 0, "errors": [], "results": []}
    for folder in sync_folders(db, active_only=True):
        got = sync_folder(db, int(folder["id"]), force=force, db_main=db_main)
        out["folders"] += 1
        for key in ("files", "created", "updated", "failed", "skipped"):
            out[key] += int(got.get(key, 0))
        out["errors"] += got.get("errors", [])
        out["results"].append(got)
    return out


def sync_due_folders(db: ToolDB, db_main: Any = None) -> dict[str, Any]:
    """Auto-sync folders whose interval has elapsed (used by the timer)."""
    out = {"folders": 0, "created": 0, "updated": 0, "failed": 0, "errors": []}
    now = _dt.datetime.now()
    for folder in sync_folders(db, active_only=True):
        if not folder.get("auto_sync"):
            continue
        last = str(folder.get("last_scan") or "")
        try:
            due = (now - _dt.datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
                   ).total_seconds() >= int(folder.get("sync_interval") or 15) * 60
        except ValueError:
            due = True
        if not due:
            continue
        got = sync_folder(db, int(folder["id"]), force=False, db_main=db_main)
        out["folders"] += 1
        out["created"] += int(got.get("created", 0))
        out["updated"] += int(got.get("updated", 0))
        out["failed"] += int(got.get("failed", 0))
        out["errors"] += got.get("errors", [])
    return out


def sync_excel_files(db: ToolDB, paths: Sequence[str], site_name: str = "",
                     force: bool = True, db_main: Any = None) -> dict[str, Any]:
    """Read a hand-picked list of sheet files into the register."""
    out = {"files": 0, "created": 0, "updated": 0, "failed": 0, "errors": [],
           "results": []}
    for path in paths:
        p = Path(path)
        folder_id = 0
        row = db.one("SELECT id FROM sync_folders WHERE path=?", (str(p.parent),))
        if row:
            folder_id = int(row["id"])
        res = sync_file(db, p, folder_id=folder_id, site_name=site_name,
                        force=force, db_main=db_main)
        out["files"] += 1
        out["created"] += int(res.get("created", 0))
        out["updated"] += int(res.get("updated", 0))
        out["failed"] += int(res.get("failed", 0))
        out["errors"] += res.get("errors", [])
        out["results"].append(res)
    return out


def sync_site_sync_file(db: ToolDB, path: str | Path, folder_id: int | None = None,
                        assigned_site: str = "", force: bool = False,
                        db_main: Any = None) -> dict[str, Any]:
    return sync_file(db, path, folder_id=int(folder_id or 0),
                     site_name=assigned_site, force=force, db_main=db_main)


def sync_site_sync_folder(db: ToolDB, folder_id: int, force: bool = False,
                          db_main: Any = None) -> dict[str, Any]:
    return sync_folder(db, folder_id, force=force, db_main=db_main)


def site_sync_folders(db: ToolDB, active_only: bool = False) -> list[dict[str, Any]]:
    return sync_folders(db, active_only=active_only)


def save_site_sync_folder(db: ToolDB, path: str | Path, label: str = "",
                          site_name: str = "", auto_sync: bool = False,
                          sync_interval: int = 15,
                          folder_id: int | None = None) -> int:
    return save_sync_folder(db, path, label=label, site_name=site_name,
                            auto_sync=auto_sync, sync_interval=sync_interval,
                            folder_id=folder_id)


def remove_site_sync_folder(db: ToolDB, folder_id: int) -> None:
    remove_sync_folder(db, folder_id)


def site_sync_scan_files(db: ToolDB, folder_id: int | None = None, status: str = "",
                         text: str = "") -> list[dict[str, Any]]:
    return scan_sync_files(db, folder_id=folder_id, status=status, text=text)


def site_sync_runs(db: ToolDB, file_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    return sync_runs(db, file_id=file_id, limit=limit)


def site_sync_import_files(db: ToolDB, paths: Sequence[str], assigned_site: str = "",
                           force: bool = True,
                           db_main: Any = None) -> dict[str, Any]:
    return sync_excel_files(db, paths, site_name=assigned_site, force=force,
                            db_main=db_main)


def site_sync_folder_status(path: str | Path) -> tuple[bool, str]:
    return sync_folder_status(path)


# ---------------------------------------------- analytics compatibility layer
# The separate Analytics module reads the register through these names.
def distinct_site_inventory(db: ToolDB, column: str) -> list[str]:
    return distinct_values(db, column)


def search_site_inventory(db: ToolDB, text: str = "", site_name: str = "",
                          category: str = "", item_type: str = "",
                          status: str = "", date_from: str = "",
                          date_to: str = "") -> list[dict[str, Any]]:
    rows = search_instruments(db, text=text, status=status, location=site_name)
    if date_from:
        rows = [r for r in rows if str(r.get("updated_at") or "") >= to_date(date_from)]
    if date_to:
        rows = [r for r in rows if str(r.get("updated_at") or "") <= to_date(date_to) + " 23:59"]
    return rows


def site_inventory_dashboard(db: ToolDB, f: dict | None = None) -> dict[str, Any]:
    return dashboard(db, f)


def site_asset_events(db: ToolDB, asset_key: str = "", limit: int = 200) -> list[dict]:
    """The movement track, optionally for one instrument (by serial or id)."""
    instrument_id = 0
    if str(asset_key or "").strip():
        row = find_instrument(db, serial=str(asset_key).strip())
        instrument_id = int(row["id"]) if row else 0
    return all_movements(db, instrument_id=instrument_id, limit=limit)


# ------------------------------------------------------------------ reports
REPORT_LIST = [
    "Instrument Register — every column",
    "Issued / Handed-over Instruments",
    "In Store — available instruments",
    "By Location / Site",
    "By Employee (custody)",
    "By Instrument Description",
    "By Project",
    "Status Summary",
    "Movement History — issue, transfer and return",
    "Transfers Between Employees",
    "Returns to Store",
    "Instruments Without a Picture",
]

REGISTER_REPORT_COLS = [label for _, label in COLUMNS]


def _register_rows(rows: Sequence[dict]) -> list[list[Any]]:
    return [[r.get(k, "") for k, _ in COLUMNS] for r in rows]


def build_report(db: ToolDB, name: str, f: dict | None = None
                 ) -> tuple[str, list[str], list[list[Any]]]:
    """Every printable report, built from the same register the screen shows."""
    f = dict(f or {})
    rows = search_instruments(
        db, text=f.get("text", ""), status=f.get("status", ""),
        location=f.get("location", ""), division=f.get("division", ""),
        project=f.get("project", ""), employee_code=f.get("employee_code", ""),
        with_picture=False)
    issued = [r for r in rows if str(r.get("issued_to") or "").strip()]

    if name.startswith("Instrument Register"):
        out = [[r.get(k, "") for k, _ in COLUMNS]
               + ["Yes" if str(r.get("picture_path") or "").strip() else ""]
               for r in rows]
        return name, REGISTER_REPORT_COLS + ["Picture"], out
    if name.startswith("Issued / Handed-over"):
        out = [[r.get("instrument_desc", ""), r.get("serial_no", ""),
                r.get("make_model", ""), r.get("issued_to", ""),
                r.get("employee_code", ""), r.get("iqama_id", ""),
                r.get("designation", ""), r.get("division", ""),
                r.get("current_project", ""), r.get("location", ""),
                fmt_qty(r.get("quantity")), r.get("issued_by", ""),
                fmt_date(r.get("last_movement_at", "")), r.get("remarks", "")]
               for r in issued]
        return name, ["Instrument Description", "Serial No.", "Make / Model",
                      "Issued To / Employee Name", "Employee Code", "Iqama ID",
                      "Designation", "Division/Department", "Current Project",
                      "Location", "Quantity", "Issued By", "Handed Over On",
                      "Remarks"], out
    if name.startswith("In Store"):
        out = [[r.get(k, "") for k in ("instrument_desc", "serial_no", "make_model",
                                       "location", "quantity", "status", "remarks")]
               for r in rows if not str(r.get("issued_to") or "").strip()]
        return name, ["Instrument Description", "Serial No.", "Make / Model",
                      "Location", "Quantity", "Status", "Remarks"], out
    if name.startswith("By Location"):
        order = [k for k in ("location", "instrument_desc", "serial_no", "quantity",
                             "status", "issued_to", "employee_code", "current_project")]
        out = [[r.get(k, "") for k in order] for r in
               sorted(rows, key=lambda r: (str(r.get("location") or "").lower(),
                                           str(r.get("instrument_desc") or "").lower()))]
        return name, [COLUMN_LABELS[k] for k in order], out
    if name.startswith("By Employee"):
        out = [[p["issued_to"], p["employee_code"], p["iqama_id"],
                p["designation"], p["division"], p["current_project"],
                p["rows_held"], fmt_qty(p["quantity"]), p["instruments"]]
               for p in custody_by_person(db)]
        return name, ["Employee Name", "Employee Code", "Iqama ID", "Designation",
                      "Division/Department", "Current Project", "Instruments Held",
                      "Total Quantity", "Instruments"], out
    if name.startswith("By Instrument Description"):
        agg: dict[str, list[float]] = {}
        for r in rows:
            key = str(r.get("instrument_desc") or "(not set)")
            agg.setdefault(key, [0, 0.0, 0])
            agg[key][0] += 1
            agg[key][1] += to_float(r.get("quantity"), 0)
            agg[key][2] += 1 if str(r.get("issued_to") or "").strip() else 0
        out = [[k, v[0], fmt_qty(v[1]), v[2], v[0] - v[2]]
               for k, v in sorted(agg.items())]
        return name, ["Instrument Description", "Rows", "Total Quantity",
                      "Issued", "In Store"], out
    if name.startswith("By Project"):
        agg: dict[str, list[float]] = {}
        for r in rows:
            key = str(r.get("current_project") or "(not set)")
            agg.setdefault(key, [0, 0.0])
            agg[key][0] += 1
            agg[key][1] += to_float(r.get("quantity"), 0)
        return name, ["Current Project", "Rows", "Total Quantity"], \
            [[k, v[0], fmt_qty(v[1])] for k, v in sorted(agg.items())]
    if name.startswith("Status Summary"):
        agg: dict[str, list[float]] = {}
        for r in rows:
            key = str(r.get("status") or "(not set)")
            agg.setdefault(key, [0, 0.0])
            agg[key][0] += 1
            agg[key][1] += to_float(r.get("quantity"), 0)
        return name, ["Status", "Rows", "Total Quantity"], \
            [[k, v[0], fmt_qty(v[1])] for k, v in sorted(agg.items())]
    if name.startswith("Movement History"):
        moves = all_movements(db, text=f.get("text", ""))
        out = [[fmt_date(m.get("movement_date", "")), m.get("ref_no", ""),
                m.get("movement_type", ""), m.get("instrument_desc", ""),
                m.get("serial_no", ""), m.get("from_holder", ""),
                m.get("to_holder", ""), m.get("to_employee_code", ""),
                m.get("designation", ""), m.get("division", ""),
                m.get("current_project", ""), m.get("location", ""),
                fmt_qty(m.get("quantity")), m.get("issued_by", ""),
                m.get("remarks", "")]
               for m in moves]
        return name, ["Date", "Ref", "Movement", "Instrument Description",
                      "Serial No.", "From", "To", "Employee Code", "Designation",
                      "Division/Department", "Current Project", "Location",
                      "Quantity", "Issued By", "Remarks"], out
    if name.startswith("Transfers"):
        moves = all_movements(db, movement_type=MV_TRANSFERRED)
        out = [[fmt_date(m.get("movement_date", "")), m.get("ref_no", ""),
                m.get("instrument_desc", ""), m.get("serial_no", ""),
                m.get("from_holder", ""), m.get("from_employee_code", ""),
                m.get("to_holder", ""), m.get("to_employee_code", ""),
                m.get("iqama_id", ""), m.get("designation", ""),
                m.get("division", ""), m.get("current_project", ""),
                m.get("location", ""), m.get("remarks", "")]
               for m in moves]
        return name, ["Date", "Ref", "Instrument Description", "Serial No.",
                      "From", "From Code", "To", "Employee Code", "Iqama ID",
                      "Designation", "Division/Department", "Current Project",
                      "Location", "Remarks"], out
    if name.startswith("Returns"):
        moves = all_movements(db, movement_type=MV_RETURNED)
        out = [[fmt_date(m.get("movement_date", "")), m.get("ref_no", ""),
                m.get("instrument_desc", ""), m.get("serial_no", ""),
                m.get("from_holder", ""), m.get("from_employee_code", ""),
                m.get("location", ""), fmt_qty(m.get("quantity")),
                m.get("remarks", "")]
               for m in moves]
        return name, ["Date", "Ref", "Instrument Description", "Serial No.",
                      "Returned By", "Employee Code", "Location", "Quantity",
                      "Remarks"], out
    # Instruments without a picture
    out = [[r.get("instrument_desc", ""), r.get("serial_no", ""),
            r.get("make_model", ""), r.get("location", ""),
            r.get("status", ""), r.get("issued_to", "")]
           for r in rows if not str(r.get("picture_path") or "").strip()]
    return name, ["Instrument Description", "Serial No.", "Make / Model",
                  "Location", "Status", "Issued To / Employee Name"], out
