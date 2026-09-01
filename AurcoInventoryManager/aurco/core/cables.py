"""CABLE RECORDS — drum register, cutting log and cable schedule.

A stand-alone module in the same spirit as *Tools, Instruments & Devices* and
the *Admin Station*: cable on site is not counted in pieces, it is counted in
**metres left on a drum**, so it needs its own book-keeping:

    ·  its own SQLite file   <storage>/Cable Records/cable_records.db
    ·  its own numbering, audit trail, backups and reports
    ·  no foreign key, join or import from items / stock_ledger / documents
    ·  nothing here ever posts a stock movement

Three registers, one story:

    1. DRUMS      every physical drum: what cable is on it, where it came
                  from (supplier, PO, GRN, test certificate), where it is
                  now, its original length and what is **still on it**.

    2. CUTS       every length taken off a drum — or put back on it. A cut
                  can be tied to a cable tag, a project and a delivery note.
                  The drum's remaining length is derived from these records,
                  never typed, so the register can always be re-proved.

    3. SCHEDULE   the cable schedule / pulling record: tag number, from and
                  to equipment, route, required length, which drum served it,
                  how much was actually pulled, and the megger / IR test that
                  closed it out.

Life of a drum:

    In Stock ──issue──> Partly Used ──issue──> Empty
        │                    │
        └──reserve──> Reserved      └──scrap──> Scrapped

A cable tag walks: Planned → Issued → Pulled → Glanded → Terminated →
Tested → Energized (or Cancelled).
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

MODULE_NAME = "Cable Records"
FOLDER = MODULE_NAME
DB_NAME = "cable_records.db"
SCHEMA_VERSION = 1

# ------------------------------------------------------------------ vocabulary
#: drum status
IN_STOCK = "In Stock"
PARTLY = "Partly Used"
EMPTY = "Empty"
RESERVED = "Reserved"
SCRAPPED = "Scrapped"
DRUM_STATUS = (IN_STOCK, PARTLY, EMPTY, RESERVED, SCRAPPED)

DRUM_COLORS = {
    IN_STOCK: "#1a9c52",
    PARTLY: "#1098ad",
    EMPTY: "#6b7c8f",
    RESERVED: "#7048e8",
    SCRAPPED: "#c92a2a",
}

#: what a cut record is
CUT_ISSUE = "Issue"
CUT_RETURN = "Return"
CUT_SCRAP = "Scrap"
CUT_ADJUST = "Adjustment"
CUT_TYPES = (CUT_ISSUE, CUT_RETURN, CUT_SCRAP, CUT_ADJUST)

CUT_COLORS = {
    CUT_ISSUE: "#0b6e83",
    CUT_RETURN: "#1a9c52",
    CUT_SCRAP: "#c92a2a",
    CUT_ADJUST: "#e8590c",
}

#: how much of a cut leaves the drum (+1) or comes back onto it (-1)
CUT_SIGN = {CUT_ISSUE: -1.0, CUT_RETURN: +1.0, CUT_SCRAP: -1.0, CUT_ADJUST: +1.0}

#: cable tag / pulling status
PLANNED = "Planned"
ISSUED = "Issued"
PULLED = "Pulled"
GLANDED = "Glanded"
TERMINATED = "Terminated"
TESTED = "Tested"
ENERGIZED = "Energized"
TAG_CANCELLED = "Cancelled"
TAG_STATUS = (PLANNED, ISSUED, PULLED, GLANDED, TERMINATED, TESTED, ENERGIZED,
              TAG_CANCELLED)

TAG_COLORS = {
    PLANNED: "#6b7c8f",
    ISSUED: "#0b6e83",
    PULLED: "#1098ad",
    GLANDED: "#7048e8",
    TERMINATED: "#e8590c",
    TESTED: "#9a6700",
    ENERGIZED: "#1a9c52",
    TAG_CANCELLED: "#c92a2a",
}

#: the step of the tag life-cycle each status represents (for progress charts)
TAG_ORDER = {name: i for i, name in enumerate(TAG_STATUS)}

TEST_PASS = "Pass"
TEST_FAIL = "Fail"
TEST_PENDING = "Pending"
TEST_RESULTS = (TEST_PENDING, TEST_PASS, TEST_FAIL)
TEST_COLORS = {TEST_PASS: "#1a9c52", TEST_FAIL: "#c92a2a", TEST_PENDING: "#6b7c8f"}

#: common vocabulary offered in the drop-downs (free text is still allowed)
CABLE_TYPES = ("Power", "Control", "Instrumentation", "Lighting", "Earthing",
               "Fire Alarm", "Telecom / Data", "Fibre Optic", "Flexible / Welding")
INSULATIONS = ("XLPE/PVC/SWA/PVC", "XLPE/PVC", "PVC/PVC", "XLPE/LSZH",
               "PVC/SWA/PVC", "Rubber", "MICC", "Bare")
CONDUCTORS = ("Copper", "Aluminium", "Tinned Copper", "Fibre")
VOLTAGE_GRADES = ("300/500 V", "450/750 V", "0.6/1 kV", "3.6/6 kV", "6/10 kV",
                  "12/20 kV", "19/33 kV", "Data / Signal")
ARMOURS = ("Unarmoured", "SWA", "STA", "AWA", "Braided", "Screened")

#: a leftover shorter than this is treated as an off-cut worth chasing
DEFAULT_OFFCUT_LIMIT = 50.0
#: a drum untouched for this long is "idle" on the dashboard
DEFAULT_IDLE_DAYS = 90

DDL = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS drums (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    drum_no        TEXT UNIQUE NOT NULL,
    cable_code     TEXT DEFAULT '',
    description    TEXT DEFAULT '',
    cable_type     TEXT DEFAULT '',
    insulation     TEXT DEFAULT '',
    conductor      TEXT DEFAULT '',
    cores          TEXT DEFAULT '',
    size_mm2       TEXT DEFAULT '',
    voltage_grade  TEXT DEFAULT '',
    armour         TEXT DEFAULT '',
    manufacturer   TEXT DEFAULT '',
    batch_no       TEXT DEFAULT '',
    supplier       TEXT DEFAULT '',
    po_no          TEXT DEFAULT '',
    grn_no         TEXT DEFAULT '',
    project        TEXT DEFAULT '',
    warehouse      TEXT DEFAULT '',
    location       TEXT DEFAULT '',
    received_date  TEXT DEFAULT '',
    original_length REAL NOT NULL DEFAULT 0,
    remaining_length REAL NOT NULL DEFAULT 0,
    uom            TEXT DEFAULT 'M',
    unit_cost      REAL NOT NULL DEFAULT 0,
    test_cert      TEXT DEFAULT '',
    cert_date      TEXT DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'In Stock',
    reserved_for   TEXT DEFAULT '',
    remarks        TEXT DEFAULT '',
    photo          TEXT DEFAULT '',
    created_by     TEXT DEFAULT '',
    created_at     TEXT DEFAULT (datetime('now','localtime')),
    updated_at     TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_dr_status  ON drums(status);
CREATE INDEX IF NOT EXISTS ix_dr_type    ON drums(cable_type);
CREATE INDEX IF NOT EXISTS ix_dr_project ON drums(project);
CREATE INDEX IF NOT EXISTS ix_dr_size    ON drums(size_mm2);

CREATE TABLE IF NOT EXISTS cuts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cut_no      TEXT UNIQUE NOT NULL,
    drum_id     INTEGER NOT NULL,
    drum_no     TEXT DEFAULT '',
    cut_date    TEXT DEFAULT '',
    txn_type    TEXT NOT NULL DEFAULT 'Issue',
    length      REAL NOT NULL DEFAULT 0,
    tag_no      TEXT DEFAULT '',
    project     TEXT DEFAULT '',
    issued_to   TEXT DEFAULT '',
    dn_no       TEXT DEFAULT '',
    from_point  TEXT DEFAULT '',
    to_point    TEXT DEFAULT '',
    remarks     TEXT DEFAULT '',
    voided      INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_cut_drum ON cuts(drum_id);
CREATE INDEX IF NOT EXISTS ix_cut_tag  ON cuts(tag_no);
CREATE INDEX IF NOT EXISTS ix_cut_date ON cuts(cut_date);

CREATE TABLE IF NOT EXISTS schedule (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_no          TEXT UNIQUE NOT NULL,
    project         TEXT DEFAULT '',
    area            TEXT DEFAULT '',
    system          TEXT DEFAULT '',
    from_point      TEXT DEFAULT '',
    to_point        TEXT DEFAULT '',
    route           TEXT DEFAULT '',
    cable_type      TEXT DEFAULT '',
    cores           TEXT DEFAULT '',
    size_mm2        TEXT DEFAULT '',
    voltage_grade   TEXT DEFAULT '',
    required_length REAL NOT NULL DEFAULT 0,
    pulled_length   REAL NOT NULL DEFAULT 0,
    drum_no         TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'Planned',
    pulled_date     TEXT DEFAULT '',
    glanded_date    TEXT DEFAULT '',
    terminated_date TEXT DEFAULT '',
    test_date       TEXT DEFAULT '',
    ir_value        REAL NOT NULL DEFAULT 0,
    continuity      TEXT DEFAULT '',
    test_result     TEXT DEFAULT 'Pending',
    tested_by       TEXT DEFAULT '',
    test_cert       TEXT DEFAULT '',
    remarks         TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now','localtime')),
    updated_at      TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_sc_status  ON schedule(status);
CREATE INDEX IF NOT EXISTS ix_sc_project ON schedule(project);

CREATE TABLE IF NOT EXISTS audit (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT DEFAULT (datetime('now','localtime')),
    username  TEXT DEFAULT '',
    action    TEXT DEFAULT '',
    entity    TEXT DEFAULT '',
    entity_id TEXT DEFAULT '',
    details   TEXT DEFAULT ''
);
"""


# ------------------------------------------------------------------- helpers
def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return _dt.date.today().isoformat()


def module_folder() -> Path:
    return config.folder(FOLDER)


def db_path() -> Path:
    return module_folder() / DB_NAME


def evidence_dir() -> Path:
    return module_folder() / "Evidence"


def to_float(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


_DATE_PATTERNS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y",
                  "%Y/%m/%d", "%d %b %Y", "%d %B %Y")


def to_date(v: Any) -> str:
    """Accept anything a site engineer might type; store ISO."""
    s = str(v or "").strip()
    if not s:
        return ""
    s = s.split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2} ", s) else s
    for pat in _DATE_PATTERNS:
        try:
            return _dt.datetime.strptime(s, pat).date().isoformat()
        except ValueError:
            continue
    return s


def fmt_date(iso_date: str) -> str:
    try:
        return _dt.date.fromisoformat(str(iso_date)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(iso_date or "")


def days_since(date: str) -> int:
    try:
        return (_dt.date.today() - _dt.date.fromisoformat(str(date)[:10])).days
    except (TypeError, ValueError):
        return 0


def describe(d: dict) -> str:
    """A one-line human description of a cable, built from its attributes."""
    bits = [str(d.get("cores") or "").strip(), str(d.get("size_mm2") or "").strip()]
    core_size = " x ".join([b for b in bits if b])
    parts = [str(d.get("cable_type") or "").strip(), core_size,
             str(d.get("insulation") or "").strip(),
             str(d.get("voltage_grade") or "").strip(),
             str(d.get("armour") or "").strip()]
    return "  ".join(p for p in parts if p) or str(d.get("description") or "")


# ------------------------------------------------------------------ database
class CableDB:
    """Stand-alone database for the Cable Records module."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or db_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.current_user = "admin"
        self._init()

    # --------------------------------------------------------------- schema
    def _init(self) -> None:
        try:
            self.conn.execute(f"PRAGMA journal_mode={self._journal_mode()}")
        except sqlite3.Error:
            pass
        self.conn.executescript(DDL)
        self.conn.commit()
        self.set_setting("schema_version", str(SCHEMA_VERSION))

    def _journal_mode(self) -> str:
        p = str(self.path)
        networked = p.startswith("\\\\") or p.startswith("//")
        return "TRUNCATE" if networked else "WAL"

    # ----------------------------------------------------------- primitives
    def execute(self, sql: str, params: Sequence = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def query(self, sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def one(self, sql: str, params: Sequence = ()):
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence = (), default=0):
        r = self.conn.execute(sql, params).fetchone()
        return default if r is None or r[0] is None else r[0]

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:            # noqa: BLE001
            pass

    # ------------------------------------------------------------ settings
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
                     (_now(), self.current_user, action, entity, str(entity_id),
                      details))
        self.conn.commit()

    # ------------------------------------------------------------- backups
    def backup(self, dest_folder: str | Path | None = None, note: str = "") -> Path:
        dest = Path(dest_folder or module_folder() / "Backups")
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / f"cable_records_{_dt.datetime.now():%Y%m%d_%H%M%S}.db"
        n = 2
        while out.exists():
            out = dest / (f"cable_records_{_dt.datetime.now():%Y%m%d_%H%M%S}_{n}.db")
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
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self.conn.close()
        for suffix in ("-wal", "-shm"):
            side = Path(str(self.path) + suffix)
            if side.exists():
                try:
                    side.unlink()
                except OSError:
                    pass
        shutil.copy2(src, self.path)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=15000")
        self._init()
        self.audit("RESTORE", "database", src.name)


_cable_db: CableDB | None = None


def get_cable_db() -> CableDB:
    global _cable_db
    if _cable_db is None:
        _cable_db = CableDB()
    return _cable_db


def set_cable_db(db: CableDB | None) -> None:
    global _cable_db
    _cable_db = db


def reset_cable_db() -> None:
    global _cable_db
    if _cable_db is not None:
        _cable_db.close()
    _cable_db = None


class CableError(Exception):
    """A cable record was refused — always with a reason the user can act on."""


# ----------------------------------------------------------------- numbering
def next_number(db: CableDB, table: str, column: str, prefix: str) -> str:
    """`PREFIX-YYYY-00001`, continuing the highest number of the year."""
    year = _dt.date.today().year
    like = f"{prefix}-{year}-%"
    rows = db.query(f"SELECT {column} AS n FROM {table} WHERE {column} LIKE ?", (like,))
    best = 0
    for r in rows:
        m = re.search(r"(\d+)$", str(r["n"] or ""))
        if m:
            best = max(best, int(m.group(1)))
    return f"{prefix}-{year}-{best + 1:05d}"


def next_drum_no(db: CableDB) -> str:
    return next_number(db, "drums", "drum_no", "DRM")


def next_cut_no(db: CableDB) -> str:
    return next_number(db, "cuts", "cut_no", "CC")


# --------------------------------------------------------------------- drums
DRUM_FIELDS = (
    "drum_no", "cable_code", "description", "cable_type", "insulation",
    "conductor", "cores", "size_mm2", "voltage_grade", "armour", "manufacturer",
    "batch_no", "supplier", "po_no", "grn_no", "project", "warehouse",
    "location", "received_date", "original_length", "remaining_length", "uom",
    "unit_cost", "test_cert", "cert_date", "status", "reserved_for", "remarks",
    "photo",
)

_NUMERIC = {"original_length", "remaining_length", "unit_cost"}
_DATES = {"received_date", "cert_date"}


def _clean_drum(data: dict) -> dict:
    out: dict[str, Any] = {}
    for f in DRUM_FIELDS:
        v = data.get(f, "")
        if f in _NUMERIC:
            out[f] = to_float(v)
        elif f in _DATES:
            out[f] = to_date(v)
        else:
            out[f] = str(v or "").strip()
    return out


def drum_status_for(remaining: float, original: float, current: str = "") -> str:
    """Derive the drum status from what is left on it.

    Reserved and Scrapped are decisions, not measurements, so they are kept.
    """
    if current in (SCRAPPED, RESERVED):
        return current
    if remaining <= 1e-9:
        return EMPTY
    if original > 0 and remaining < original - 1e-9:
        return PARTLY
    return IN_STOCK


def save_drum(db: CableDB, data: dict, drum_id: int | None = None) -> int:
    """Create or update a drum. Returns its id.

    On a new drum the remaining length defaults to the original length — the
    common case is a full drum arriving from the supplier.
    """
    d = _clean_drum(data)
    if not d["drum_no"]:
        d["drum_no"] = next_drum_no(db)
    if d["original_length"] < 0 or d["remaining_length"] < 0:
        raise CableError("A cable length cannot be negative.")
    if drum_id is None and not data.get("remaining_length"):
        d["remaining_length"] = d["original_length"]
    if d["remaining_length"] > d["original_length"] + 1e-9:
        raise CableError(
            f"The remaining length ({d['remaining_length']:g}) cannot be more "
            f"than the original drum length ({d['original_length']:g}).")
    if not d["description"]:
        d["description"] = describe(d)
    if not d["uom"]:
        d["uom"] = "M"
    if not d["received_date"]:
        d["received_date"] = today()
    d["status"] = drum_status_for(d["remaining_length"], d["original_length"],
                                  d["status"])

    clash = db.one("SELECT id FROM drums WHERE drum_no=? AND id<>?",
                   (d["drum_no"], drum_id or -1))
    if clash:
        raise CableError(f"Drum number {d['drum_no']} already exists.")

    if drum_id is None:
        cols = ", ".join(DRUM_FIELDS) + ", created_by"
        marks = ", ".join("?" * (len(DRUM_FIELDS) + 1))
        cur = db.execute(f"INSERT INTO drums({cols}) VALUES({marks})",
                         [d[f] for f in DRUM_FIELDS] + [db.current_user])
        drum_id = int(cur.lastrowid)
        db.commit()
        db.audit("DRUM ADD", "drum", d["drum_no"],
                 f"{d['description']} · {d['original_length']:g} {d['uom']}")
    else:
        sets = ", ".join(f"{f}=?" for f in DRUM_FIELDS)
        db.execute(f"UPDATE drums SET {sets}, updated_at=? WHERE id=?",
                   [d[f] for f in DRUM_FIELDS] + [_now(), drum_id])
        db.commit()
        db.audit("DRUM EDIT", "drum", d["drum_no"], d["description"])
    return int(drum_id)


def get_drum(db: CableDB, drum_id: int) -> dict | None:
    r = db.one("SELECT * FROM drums WHERE id=?", (drum_id,))
    return dict(r) if r else None


def drum_by_no(db: CableDB, drum_no: str) -> dict | None:
    r = db.one("SELECT * FROM drums WHERE drum_no=? COLLATE NOCASE", (str(drum_no),))
    return dict(r) if r else None


def delete_drums(db: CableDB, ids: Iterable[int]) -> int:
    n = 0
    for i in ids:
        row = get_drum(db, int(i))
        if row is None:
            continue
        used = db.scalar("SELECT COUNT(*) FROM cuts WHERE drum_id=? AND voided=0", (i,))
        if used:
            raise CableError(
                f"Drum {row['drum_no']} has {used} cut record(s). Void those "
                "first, or scrap the drum instead of deleting it.")
        db.execute("DELETE FROM drums WHERE id=?", (i,))
        db.audit("DRUM DELETE", "drum", row["drum_no"], row["description"])
        n += 1
    db.commit()
    return n


def recalc_drum(db: CableDB, drum_id: int) -> float:
    """Re-derive the remaining length of a drum from its cut history."""
    row = get_drum(db, drum_id)
    if row is None:
        return 0.0
    moved = db.scalar(
        "SELECT COALESCE(SUM(CASE txn_type WHEN 'Return' THEN length "
        "WHEN 'Adjustment' THEN length ELSE -length END),0) "
        "FROM cuts WHERE drum_id=? AND voided=0", (drum_id,))
    remaining = round(float(row["original_length"]) + float(moved or 0), 3)
    remaining = max(0.0, remaining)
    status = drum_status_for(remaining, float(row["original_length"]), row["status"])
    db.execute("UPDATE drums SET remaining_length=?, status=?, updated_at=? WHERE id=?",
               (remaining, status, _now(), drum_id))
    db.commit()
    return remaining


def rebuild_drums(db: CableDB) -> int:
    for r in db.query("SELECT id FROM drums"):
        recalc_drum(db, int(r["id"]))
    return int(db.scalar("SELECT COUNT(*) FROM drums"))


def set_drum_status(db: CableDB, drum_id: int, status: str, note: str = "") -> None:
    row = get_drum(db, drum_id)
    if row is None:
        raise CableError("That drum no longer exists.")
    if status not in DRUM_STATUS:
        raise CableError(f"Unknown drum status: {status}")
    db.execute("UPDATE drums SET status=?, reserved_for=?, updated_at=? WHERE id=?",
               (status, note if status == RESERVED else row["reserved_for"],
                _now(), drum_id))
    db.commit()
    db.audit("DRUM STATUS", "drum", row["drum_no"], f"{row['status']} → {status} {note}")


# ---------------------------------------------------------------------- cuts
CUT_FIELDS = ("cut_date", "txn_type", "length", "tag_no", "project", "issued_to",
              "dn_no", "from_point", "to_point", "remarks")


def post_cut(db: CableDB, drum_id: int, data: dict) -> str:
    """Record a length taken off (or put back on) a drum. Returns the cut no.

    This is the only way the remaining length of a drum ever changes, so the
    register can always be re-proved from its own history.
    """
    drum = get_drum(db, drum_id)
    if drum is None:
        raise CableError("Select a drum first.")
    txn = str(data.get("txn_type") or CUT_ISSUE).strip() or CUT_ISSUE
    if txn not in CUT_TYPES:
        raise CableError(f"Unknown cut type: {txn}")
    length = round(to_float(data.get("length")), 3)
    if length <= 0:
        raise CableError("Enter a length greater than zero.")
    if drum["status"] == SCRAPPED and txn != CUT_ADJUST:
        raise CableError(f"Drum {drum['drum_no']} is scrapped.")
    remaining = float(drum["remaining_length"])
    if CUT_SIGN[txn] < 0 and length > remaining + 1e-9:
        raise CableError(
            f"Only {remaining:g} {drum['uom']} are left on drum "
            f"{drum['drum_no']} — you asked for {length:g}.")
    if CUT_SIGN[txn] > 0 and remaining + length > float(drum["original_length"]) + 1e-9:
        raise CableError(
            f"Putting {length:g} back would make drum {drum['drum_no']} longer "
            f"than it ever was ({drum['original_length']:g} {drum['uom']}).")

    cut_no = next_cut_no(db)
    row = {f: data.get(f, "") for f in CUT_FIELDS}
    row["cut_date"] = to_date(row["cut_date"]) or today()
    row["txn_type"] = txn
    row["length"] = length
    for f in ("tag_no", "project", "issued_to", "dn_no", "from_point", "to_point",
              "remarks"):
        row[f] = str(row[f] or "").strip()
    if not row["project"]:
        row["project"] = drum["project"]
    cols = ", ".join(["cut_no", "drum_id", "drum_no"] + list(CUT_FIELDS) + ["created_by"])
    marks = ", ".join("?" * (len(CUT_FIELDS) + 4))
    db.execute(f"INSERT INTO cuts({cols}) VALUES({marks})",
               [cut_no, drum_id, drum["drum_no"]] +
               [row[f] for f in CUT_FIELDS] + [db.current_user])
    db.commit()
    recalc_drum(db, drum_id)
    if row["tag_no"]:
        sync_tag_from_cuts(db, row["tag_no"])
    db.audit(f"CABLE {txn.upper()}", "cut", cut_no,
             f"{length:g} {drum['uom']} · drum {drum['drum_no']}"
             + (f" · tag {row['tag_no']}" if row["tag_no"] else ""))
    return cut_no


def void_cut(db: CableDB, cut_id: int, reason: str = "") -> None:
    """Cancel a cut record; the length goes straight back onto the drum."""
    row = db.one("SELECT * FROM cuts WHERE id=?", (cut_id,))
    if row is None:
        raise CableError("That cut record no longer exists.")
    if row["voided"]:
        raise CableError(f"{row['cut_no']} is already voided.")
    db.execute("UPDATE cuts SET voided=1, remarks=? WHERE id=?",
               ((str(row["remarks"] or "") + f" [VOID: {reason}]").strip(), cut_id))
    db.commit()
    recalc_drum(db, int(row["drum_id"]))
    if row["tag_no"]:
        sync_tag_from_cuts(db, row["tag_no"])
    db.audit("CUT VOID", "cut", row["cut_no"], reason)


def scrap_drum(db: CableDB, drum_id: int, reason: str) -> str:
    """Write off whatever is left on a drum, with a mandatory reason."""
    if not str(reason or "").strip():
        raise CableError("A reason is mandatory when scrapping cable.")
    drum = get_drum(db, drum_id)
    if drum is None:
        raise CableError("Select a drum first.")
    cut_no = ""
    if float(drum["remaining_length"]) > 1e-9:
        cut_no = post_cut(db, drum_id, {
            "txn_type": CUT_SCRAP, "length": drum["remaining_length"],
            "remarks": reason, "cut_date": today()})
    db.execute("UPDATE drums SET status=?, updated_at=? WHERE id=?",
               (SCRAPPED, _now(), drum_id))
    db.commit()
    db.audit("DRUM SCRAP", "drum", drum["drum_no"], reason)
    return cut_no


# ------------------------------------------------------------------ schedule
TAG_FIELDS = ("tag_no", "project", "area", "system", "from_point", "to_point",
              "route", "cable_type", "cores", "size_mm2", "voltage_grade",
              "required_length", "pulled_length", "drum_no", "status",
              "pulled_date", "glanded_date", "terminated_date", "test_date",
              "ir_value", "continuity", "test_result", "tested_by", "test_cert",
              "remarks")

_TAG_NUM = {"required_length", "pulled_length", "ir_value"}
_TAG_DATES = {"pulled_date", "glanded_date", "terminated_date", "test_date"}


def save_tag(db: CableDB, data: dict, tag_id: int | None = None) -> int:
    d: dict[str, Any] = {}
    for f in TAG_FIELDS:
        v = data.get(f, "")
        if f in _TAG_NUM:
            d[f] = to_float(v)
        elif f in _TAG_DATES:
            d[f] = to_date(v)
        else:
            d[f] = str(v or "").strip()
    if not d["tag_no"]:
        raise CableError("A cable tag number is mandatory.")
    if d["status"] not in TAG_STATUS:
        d["status"] = PLANNED
    if d["test_result"] not in TEST_RESULTS:
        d["test_result"] = TEST_PENDING
    clash = db.one("SELECT id FROM schedule WHERE tag_no=? COLLATE NOCASE AND id<>?",
                   (d["tag_no"], tag_id or -1))
    if clash:
        raise CableError(f"Cable tag {d['tag_no']} already exists.")
    if tag_id is None:
        cols = ", ".join(TAG_FIELDS) + ", created_by"
        marks = ", ".join("?" * (len(TAG_FIELDS) + 1))
        cur = db.execute(f"INSERT INTO schedule({cols}) VALUES({marks})",
                         [d[f] for f in TAG_FIELDS] + [db.current_user])
        tag_id = int(cur.lastrowid)
        db.audit("TAG ADD", "tag", d["tag_no"],
                 f"{d['from_point']} → {d['to_point']}")
    else:
        sets = ", ".join(f"{f}=?" for f in TAG_FIELDS)
        db.execute(f"UPDATE schedule SET {sets}, updated_at=? WHERE id=?",
                   [d[f] for f in TAG_FIELDS] + [_now(), tag_id])
        db.audit("TAG EDIT", "tag", d["tag_no"], d["status"])
    db.commit()
    return int(tag_id)


def get_tag(db: CableDB, tag_id: int) -> dict | None:
    r = db.one("SELECT * FROM schedule WHERE id=?", (tag_id,))
    return dict(r) if r else None


def tag_by_no(db: CableDB, tag_no: str) -> dict | None:
    r = db.one("SELECT * FROM schedule WHERE tag_no=? COLLATE NOCASE", (str(tag_no),))
    return dict(r) if r else None


def delete_tags(db: CableDB, ids: Iterable[int]) -> int:
    n = 0
    for i in ids:
        row = get_tag(db, int(i))
        if row is None:
            continue
        db.execute("DELETE FROM schedule WHERE id=?", (i,))
        db.audit("TAG DELETE", "tag", row["tag_no"])
        n += 1
    db.commit()
    return n


def sync_tag_from_cuts(db: CableDB, tag_no: str) -> float:
    """Keep the schedule honest: pulled length = what really left the drums."""
    tag = tag_by_no(db, tag_no)
    if tag is None:
        return 0.0
    pulled = db.scalar(
        "SELECT COALESCE(SUM(CASE txn_type WHEN 'Return' THEN -length "
        "ELSE length END),0) FROM cuts "
        "WHERE tag_no=? COLLATE NOCASE AND voided=0 AND txn_type<>'Adjustment'",
        (tag_no,))
    pulled = round(max(0.0, float(pulled or 0)), 3)
    drums = [r["drum_no"] for r in db.query(
        "SELECT DISTINCT drum_no FROM cuts WHERE tag_no=? COLLATE NOCASE AND voided=0",
        (tag_no,)) if r["drum_no"]]
    status = tag["status"]
    if pulled > 0 and TAG_ORDER.get(status, 0) < TAG_ORDER[PULLED]:
        status = PULLED
    if pulled <= 0 and status in (ISSUED, PULLED):
        status = PLANNED
    db.execute("UPDATE schedule SET pulled_length=?, drum_no=?, status=?, "
               "pulled_date=COALESCE(NULLIF(pulled_date,''),?), updated_at=? "
               "WHERE id=?",
               (pulled, ", ".join(drums), status,
                today() if pulled > 0 else "", _now(), tag["id"]))
    db.commit()
    return pulled


def record_test(db: CableDB, tag_id: int, data: dict) -> None:
    """Store the megger / continuity result and move the tag to Tested."""
    tag = get_tag(db, tag_id)
    if tag is None:
        raise CableError("That cable tag no longer exists.")
    result = str(data.get("test_result") or TEST_PENDING).strip()
    if result not in TEST_RESULTS:
        raise CableError(f"Unknown test result: {result}")
    status = tag["status"]
    if result == TEST_PASS and TAG_ORDER.get(status, 0) < TAG_ORDER[TESTED]:
        status = TESTED
    db.execute(
        "UPDATE schedule SET test_date=?, ir_value=?, continuity=?, test_result=?,"
        " tested_by=?, test_cert=?, status=?, updated_at=? WHERE id=?",
        (to_date(data.get("test_date")) or today(), to_float(data.get("ir_value")),
         str(data.get("continuity") or "").strip(), result,
         str(data.get("tested_by") or "").strip(),
         str(data.get("test_cert") or "").strip(), status, _now(), tag_id))
    db.commit()
    db.audit("TAG TEST", "tag", tag["tag_no"],
             f"{result} · IR {to_float(data.get('ir_value')):g} MΩ")


# -------------------------------------------------------------------- search
def _period(sql: list[str], params: list, column: str, f: dict) -> None:
    if f.get("date_from"):
        sql.append(f"AND {column}>=?")
        params.append(f["date_from"])
    if f.get("date_to"):
        sql.append(f"AND {column}<=?")
        params.append(f["date_to"])


def search_drums(db: CableDB, text: str = "", status: str = "", cable_type: str = "",
                 project: str = "", warehouse: str = "", size: str = "",
                 manufacturer: str = "", supplier: str = "", date_from: str = "",
                 date_to: str = "", offcuts_only: bool = False,
                 in_stock_only: bool = False, idle_only: bool = False,
                 offcut_limit: float | None = None,
                 idle_days: int = DEFAULT_IDLE_DAYS, **_extra) -> list[dict]:
    sql = ["SELECT * FROM drums WHERE 1=1"]
    p: list[Any] = []
    if text:
        like = f"%{text.strip()}%"
        sql.append("AND (drum_no LIKE ? OR cable_code LIKE ? OR description LIKE ?"
                   " OR manufacturer LIKE ? OR batch_no LIKE ? OR po_no LIKE ?"
                   " OR grn_no LIKE ? OR project LIKE ? OR location LIKE ?"
                   " OR size_mm2 LIKE ? OR supplier LIKE ?)")
        p += [like] * 11
    for col, val in (("status", status), ("cable_type", cable_type),
                     ("project", project), ("warehouse", warehouse),
                     ("size_mm2", size), ("manufacturer", manufacturer),
                     ("supplier", supplier)):
        if val:
            sql.append(f"AND {col}=?")
            p.append(val)
    _period(sql, p, "received_date", {"date_from": date_from, "date_to": date_to})
    sql.append("ORDER BY drum_no")
    limit = DEFAULT_OFFCUT_LIMIT if offcut_limit is None else float(offcut_limit)
    out = []
    for r in db.query(" ".join(sql), p):
        d = dict(r)
        d["used_length"] = round(float(d["original_length"]) -
                                 float(d["remaining_length"]), 3)
        d["utilisation"] = (round(d["used_length"] / float(d["original_length"]) * 100, 1)
                            if float(d["original_length"]) > 0 else 0.0)
        d["value"] = round(float(d["remaining_length"]) * float(d["unit_cost"]), 2)
        d["age_days"] = days_since(d["received_date"])
        last = db.scalar("SELECT MAX(cut_date) FROM cuts WHERE drum_id=? AND voided=0",
                         (d["id"],), "")
        d["last_movement"] = last or d["received_date"]
        d["idle_days"] = days_since(d["last_movement"])
        d["is_offcut"] = 0 < float(d["remaining_length"]) <= limit
        if offcuts_only and not d["is_offcut"]:
            continue
        if in_stock_only and float(d["remaining_length"]) <= 1e-9:
            continue
        if idle_only and (d["idle_days"] < idle_days or
                          float(d["remaining_length"]) <= 1e-9):
            continue
        out.append(d)
    return out


def search_cuts(db: CableDB, text: str = "", txn_type: str = "", project: str = "",
                drum_no: str = "", tag_no: str = "", issued_to: str = "",
                date_from: str = "", date_to: str = "",
                include_void: bool = False, **_extra) -> list[dict]:
    sql = ["SELECT * FROM cuts WHERE 1=1"]
    p: list[Any] = []
    if not include_void:
        sql.append("AND voided=0")
    if text:
        like = f"%{text.strip()}%"
        sql.append("AND (cut_no LIKE ? OR drum_no LIKE ? OR tag_no LIKE ?"
                   " OR issued_to LIKE ? OR dn_no LIKE ? OR project LIKE ?"
                   " OR from_point LIKE ? OR to_point LIKE ? OR remarks LIKE ?)")
        p += [like] * 9
    for col, val in (("txn_type", txn_type), ("project", project),
                     ("drum_no", drum_no), ("tag_no", tag_no),
                     ("issued_to", issued_to)):
        if val:
            sql.append(f"AND {col}=?")
            p.append(val)
    _period(sql, p, "cut_date", {"date_from": date_from, "date_to": date_to})
    sql.append("ORDER BY cut_date DESC, id DESC")
    out = []
    for r in db.query(" ".join(sql), p):
        d = dict(r)
        d["signed_length"] = round(CUT_SIGN.get(d["txn_type"], -1.0) *
                                   float(d["length"]), 3)
        d["days_ago"] = days_since(d["cut_date"])
        out.append(d)
    return out


def search_tags(db: CableDB, text: str = "", status: str = "", project: str = "",
                area: str = "", test_result: str = "", drum_no: str = "",
                date_from: str = "", date_to: str = "", pending_only: bool = False,
                short_only: bool = False, **_extra) -> list[dict]:
    sql = ["SELECT * FROM schedule WHERE 1=1"]
    p: list[Any] = []
    if text:
        like = f"%{text.strip()}%"
        sql.append("AND (tag_no LIKE ? OR from_point LIKE ? OR to_point LIKE ?"
                   " OR route LIKE ? OR project LIKE ? OR area LIKE ?"
                   " OR system LIKE ? OR drum_no LIKE ?)")
        p += [like] * 8
    for col, val in (("status", status), ("project", project), ("area", area),
                     ("test_result", test_result)):
        if val:
            sql.append(f"AND {col}=?")
            p.append(val)
    if drum_no:
        sql.append("AND drum_no LIKE ?")
        p.append(f"%{drum_no}%")
    _period(sql, p, "pulled_date", {"date_from": date_from, "date_to": date_to})
    sql.append("ORDER BY tag_no")
    out = []
    for r in db.query(" ".join(sql), p):
        d = dict(r)
        req = float(d["required_length"])
        d["balance"] = round(req - float(d["pulled_length"]), 3)
        d["progress"] = round(float(d["pulled_length"]) / req * 100, 1) if req else 0.0
        d["over_pull"] = round(max(0.0, float(d["pulled_length"]) - req), 3)
        d["step"] = TAG_ORDER.get(d["status"], 0)
        if pending_only and d["status"] in (ENERGIZED, TAG_CANCELLED):
            continue
        if short_only and d["balance"] <= 1e-9:
            continue
        out.append(d)
    return out


def distinct(db: CableDB, table: str, column: str) -> list[str]:
    if not re.fullmatch(r"[a-z_]+", table) or not re.fullmatch(r"[a-z_0-9]+", column):
        return []
    rows = db.query(f"SELECT DISTINCT {column} AS v FROM {table} "
                    f"WHERE {column} IS NOT NULL AND {column}<>'' ORDER BY {column}")
    return [str(r["v"]) for r in rows]


def drum_history(db: CableDB, drum_id: int) -> list[dict]:
    return search_cuts(db, include_void=True,
                       drum_no=(get_drum(db, drum_id) or {}).get("drum_no", ""))


# ----------------------------------------------------------------- dashboard
#: what the charts count
MEASURES = {
    "count": "Drums / records",
    "length": "Length (original)",
    "remaining": "Length remaining",
    "used": "Length used",
    "value": "Stock value",
}


def _measure(row: dict, measure: str) -> float:
    if measure == "length":
        return to_float(row.get("original_length") or row.get("length"))
    if measure == "remaining":
        return to_float(row.get("remaining_length"))
    if measure == "used":
        return to_float(row.get("used_length") or row.get("length"))
    if measure == "value":
        return to_float(row.get("value"))
    return 1.0


def dashboard(db: CableDB, f: dict | None = None) -> dict:
    f = dict(f or {})
    offcut_limit = to_float(db.get_setting("offcut_limit", DEFAULT_OFFCUT_LIMIT),
                            DEFAULT_OFFCUT_LIMIT)
    idle_days = int(to_float(db.get_setting("idle_days", DEFAULT_IDLE_DAYS),
                             DEFAULT_IDLE_DAYS))
    f.setdefault("offcut_limit", offcut_limit)
    f.setdefault("idle_days", idle_days)
    offcut_limit = to_float(f["offcut_limit"], offcut_limit)
    idle_days = int(to_float(f["idle_days"], idle_days))
    drums = search_drums(db, **f)
    cuts = search_cuts(db, **{k: v for k, v in f.items()
                              if k in ("text", "project", "date_from", "date_to",
                                       "drum_no", "tag_no", "txn_type")})
    tags = search_tags(db, **{k: v for k, v in f.items()
                              if k in ("text", "project", "status", "area",
                                       "test_result", "date_from", "date_to")})
    original = sum(float(d["original_length"]) for d in drums)
    remaining = sum(float(d["remaining_length"]) for d in drums)
    used = round(original - remaining, 3)
    issued = sum(float(c["length"]) for c in cuts if c["txn_type"] == CUT_ISSUE)
    returned = sum(float(c["length"]) for c in cuts if c["txn_type"] == CUT_RETURN)
    scrapped = sum(float(c["length"]) for c in cuts if c["txn_type"] == CUT_SCRAP)
    return {
        "drums": len(drums),
        "in_stock": sum(1 for d in drums if d["status"] == IN_STOCK),
        "partly": sum(1 for d in drums if d["status"] == PARTLY),
        "empty": sum(1 for d in drums if d["status"] == EMPTY),
        "reserved": sum(1 for d in drums if d["status"] == RESERVED),
        "scrapped_drums": sum(1 for d in drums if d["status"] == SCRAPPED),
        "original_length": round(original, 2),
        "remaining_length": round(remaining, 2),
        "used_length": used,
        "utilisation": round(used / original * 100, 1) if original else 0.0,
        "stock_value": round(sum(float(d["value"]) for d in drums), 2),
        "offcuts": sum(1 for d in drums if d["is_offcut"]),
        "offcut_length": round(sum(float(d["remaining_length"])
                                   for d in drums if d["is_offcut"]), 2),
        "idle_drums": sum(1 for d in drums if d["idle_days"] >= idle_days
                          and float(d["remaining_length"]) > 0),
        "cuts": len(cuts),
        "issued_length": round(issued, 2),
        "returned_length": round(returned, 2),
        "scrap_length": round(scrapped, 2),
        "tags": len(tags),
        "tags_pulled": sum(1 for t in tags if t["step"] >= TAG_ORDER[PULLED]
                           and t["status"] != TAG_CANCELLED),
        "tags_pending": sum(1 for t in tags if t["step"] < TAG_ORDER[PULLED]),
        "tags_terminated": sum(1 for t in tags
                               if t["step"] >= TAG_ORDER[TERMINATED]
                               and t["status"] != TAG_CANCELLED),
        "tests_pass": sum(1 for t in tags if t["test_result"] == TEST_PASS),
        "tests_fail": sum(1 for t in tags if t["test_result"] == TEST_FAIL),
        "tests_pending": sum(1 for t in tags if t["test_result"] == TEST_PENDING
                             and t["status"] != TAG_CANCELLED),
        "required_length": round(sum(float(t["required_length"]) for t in tags), 2),
        "pulled_length": round(sum(float(t["pulled_length"]) for t in tags), 2),
        "shortfall": round(sum(max(0.0, float(t["balance"])) for t in tags), 2),
        "projects": len({d["project"] for d in drums if d["project"]}),
    }


#: columns that live on the cut log rather than on the drum register
CUT_COLUMNS = ("txn_type", "issued_to", "tag_no", "dn_no")
TAG_COLUMNS = ("test_result", "area", "system")


def by_column(db: CableDB, column: str, limit: int = 10, measure: str = "count",
              f: dict | None = None) -> list[tuple[str, float]]:
    """Group any register by any column — the charts all come from here."""
    f = dict(f or {})
    if column in CUT_COLUMNS:
        rows = search_cuts(db, **{k: v for k, v in f.items()
                                  if k in ("text", "project", "date_from",
                                           "date_to", "txn_type", "tag_no")})
        for r in rows:
            r["length"] = float(r["length"])
    elif column == "status_tag":
        rows = search_tags(db, **{k: v for k, v in f.items()
                                  if k in ("text", "project", "date_from",
                                           "date_to")})
        column = "status"
    elif column in TAG_COLUMNS:
        rows = search_tags(db, **{k: v for k, v in f.items()
                                  if k in ("text", "project", "date_from",
                                           "date_to")})
    else:
        rows = search_drums(db, **f)
    agg: dict[str, float] = {}
    for r in rows:
        key = str(r.get(column) or "(blank)")
        agg[key] = agg.get(key, 0.0) + _measure(r, measure)
    return [kv for kv in sorted(agg.items(), key=lambda kv: -kv[1])[:limit] if kv[1]]


#: how long a drum has been sitting without a movement
AGE_BUCKETS = ((0, 30, "0-30 d"), (31, 90, "31-90 d"), (91, 180, "91-180 d"),
               (181, 365, "181-365 d"), (366, 10 ** 6, "1 yr +"))


def ageing(db: CableDB, f: dict | None = None,
           measure: str = "count") -> list[tuple[str, float]]:
    rows = [d for d in search_drums(db, **(f or {}))
            if float(d["remaining_length"]) > 1e-9]
    out = []
    for lo, hi, label in AGE_BUCKETS:
        out.append((label, sum(_measure(r, measure) for r in rows
                               if lo <= int(r["idle_days"]) <= hi)))
    return out


def monthly_split(db: CableDB, months: int = 8,
                  f: dict | None = None) -> list[tuple[str, float, float]]:
    """(month, issued, returned) — the two series of the grouped chart."""
    rows = search_cuts(db, **{k: v for k, v in (f or {}).items()
                              if k in ("text", "project", "date_from", "date_to")})
    agg: dict[str, list[float]] = {}
    for r in rows:
        key = str(r["cut_date"] or "")[:7]
        if not key:
            continue
        cell = agg.setdefault(key, [0.0, 0.0])
        if r["txn_type"] == CUT_RETURN:
            cell[1] += float(r["length"])
        else:
            cell[0] += float(r["length"])
    return [(k, v[0], v[1]) for k, v in sorted(agg.items())[-months:]]


def monthly(db: CableDB, months: int = 12,
            f: dict | None = None) -> list[tuple[str, float]]:
    rows = search_cuts(db, **{k: v for k, v in (f or {}).items()
                              if k in ("text", "project", "date_from", "date_to")})
    agg: dict[str, float] = {}
    for r in rows:
        key = str(r["cut_date"] or "")[:7]
        if key:
            agg[key] = agg.get(key, 0.0) + float(r["length"])
    return sorted(agg.items())[-months:]


def consumption_by_project(db: CableDB, f: dict | None = None) -> list[dict]:
    """Who is eating the cable: issued, returned, net and tags served."""
    rows = search_cuts(db, **{k: v for k, v in (f or {}).items()
                              if k in ("text", "project", "date_from", "date_to")})
    agg: dict[str, dict] = {}
    for r in rows:
        key = str(r["project"] or "(no project)")
        cell = agg.setdefault(key, {"project": key, "issued": 0.0, "returned": 0.0,
                                    "scrapped": 0.0, "cuts": 0, "tags": set()})
        cell["cuts"] += 1
        if r["tag_no"]:
            cell["tags"].add(r["tag_no"])
        if r["txn_type"] == CUT_RETURN:
            cell["returned"] += float(r["length"])
        elif r["txn_type"] == CUT_SCRAP:
            cell["scrapped"] += float(r["length"])
        elif r["txn_type"] == CUT_ISSUE:
            cell["issued"] += float(r["length"])
    out = []
    for cell in agg.values():
        cell["tags"] = len(cell["tags"])
        cell["net"] = round(cell["issued"] - cell["returned"], 2)
        for k in ("issued", "returned", "scrapped"):
            cell[k] = round(cell[k], 2)
        out.append(cell)
    return sorted(out, key=lambda c: -c["net"])


def stock_by_cable(db: CableDB, f: dict | None = None) -> list[dict]:
    """Stock summary the way a cable store thinks: per cable specification."""
    agg: dict[str, dict] = {}
    for d in search_drums(db, **(f or {})):
        key = describe(d) or d["description"] or "(unspecified)"
        cell = agg.setdefault(key, {"cable": key, "drums": 0, "original": 0.0,
                                    "remaining": 0.0, "value": 0.0, "offcuts": 0})
        cell["drums"] += 1
        cell["original"] += float(d["original_length"])
        cell["remaining"] += float(d["remaining_length"])
        cell["value"] += float(d["value"])
        cell["offcuts"] += 1 if d["is_offcut"] else 0
    out = []
    for cell in agg.values():
        cell["used"] = round(cell["original"] - cell["remaining"], 2)
        for k in ("original", "remaining", "value"):
            cell[k] = round(cell[k], 2)
        out.append(cell)
    return sorted(out, key=lambda c: -c["remaining"])


# ------------------------------------------------------------------- reports
Report = tuple[str, list[str], list[list[Any]]]

REPORT_LIST = [
    "Drum Register — everything",
    "Cable Stock Summary (by cable type & size)",
    "Available Drums (with cable left)",
    "Off-cuts / Short Lengths",
    "Empty & Scrapped Drums",
    "Idle Drums (no movement)",
    "Cutting Log — every issue and return",
    "Consumption by Project",
    "Consumption by Cable Tag",
    "Cable Schedule — pulling status",
    "Cables Not Yet Pulled",
    "Megger / IR Test Register",
    "Failed & Pending Tests",
    "Drum Traceability (PO / GRN / batch / certificate)",
    "Stock Value by Cable",
    "Audit Trail",
]


def build_report(db: CableDB, name: str, f: dict | None = None) -> Report:
    f = dict(f or {})
    if name == REPORT_LIST[0]:
        rows = search_drums(db, **f)
        cols = ["Drum No.", "Cable", "Type", "Size", "Voltage", "Manufacturer",
                "Project", "Location", "Original", "Remaining", "Used", "Used %",
                "Status", "Received"]
        return (name, cols,
                [[d["drum_no"], d["description"], d["cable_type"], d["size_mm2"],
                  d["voltage_grade"], d["manufacturer"], d["project"], d["location"],
                  d["original_length"], d["remaining_length"], d["used_length"],
                  d["utilisation"], d["status"], fmt_date(d["received_date"])]
                 for d in rows])
    if name == REPORT_LIST[1]:
        rows = stock_by_cable(db, f)
        return (name, ["Cable", "Drums", "Original", "Remaining", "Used",
                       "Off-cuts", "Value"],
                [[r["cable"], r["drums"], r["original"], r["remaining"], r["used"],
                  r["offcuts"], r["value"]] for r in rows])
    if name == REPORT_LIST[2]:
        rows = search_drums(db, in_stock_only=True, **f)
        return (name, ["Drum No.", "Cable", "Remaining", "Location", "Project",
                       "Status", "Idle Days"],
                [[d["drum_no"], d["description"], d["remaining_length"],
                  d["location"], d["project"], d["status"], d["idle_days"]]
                 for d in rows])
    if name == REPORT_LIST[3]:
        rows = search_drums(db, offcuts_only=True, **f)
        return (name, ["Drum No.", "Cable", "Remaining", "Location", "Last Movement",
                       "Idle Days", "Value"],
                [[d["drum_no"], d["description"], d["remaining_length"],
                  d["location"], fmt_date(d["last_movement"]), d["idle_days"],
                  d["value"]] for d in rows])
    if name == REPORT_LIST[4]:
        rows = [d for d in search_drums(db, **f) if d["status"] in (EMPTY, SCRAPPED)]
        return (name, ["Drum No.", "Cable", "Original", "Status", "Last Movement",
                       "Remarks"],
                [[d["drum_no"], d["description"], d["original_length"], d["status"],
                  fmt_date(d["last_movement"]), d["remarks"]] for d in rows])
    if name == REPORT_LIST[5]:
        rows = search_drums(db, idle_only=True, **f)
        return (name, ["Drum No.", "Cable", "Remaining", "Location", "Last Movement",
                       "Idle Days"],
                [[d["drum_no"], d["description"], d["remaining_length"],
                  d["location"], fmt_date(d["last_movement"]), d["idle_days"]]
                 for d in rows])
    if name == REPORT_LIST[6]:
        rows = search_cuts(db, **f)
        return (name, ["Cut No.", "Date", "Type", "Drum", "Length", "Cable Tag",
                       "Project", "Issued To", "DN No.", "From", "To", "Remarks"],
                [[c["cut_no"], fmt_date(c["cut_date"]), c["txn_type"], c["drum_no"],
                  c["length"], c["tag_no"], c["project"], c["issued_to"], c["dn_no"],
                  c["from_point"], c["to_point"], c["remarks"]] for c in rows])
    if name == REPORT_LIST[7]:
        rows = consumption_by_project(db, f)
        return (name, ["Project", "Cuts", "Tags", "Issued", "Returned", "Scrapped",
                       "Net Used"],
                [[r["project"], r["cuts"], r["tags"], r["issued"], r["returned"],
                  r["scrapped"], r["net"]] for r in rows])
    if name == REPORT_LIST[8]:
        agg: dict[str, dict] = {}
        for c in search_cuts(db, **f):
            key = c["tag_no"] or "(no tag)"
            cell = agg.setdefault(key, {"tag": key, "cuts": 0, "length": 0.0,
                                        "drums": set(), "project": c["project"]})
            cell["cuts"] += 1
            cell["length"] += float(c["length"]) * (1 if c["txn_type"] != CUT_RETURN
                                                    else -1)
            if c["drum_no"]:
                cell["drums"].add(c["drum_no"])
        return (name, ["Cable Tag", "Project", "Cuts", "Drums", "Net Length"],
                [[v["tag"], v["project"], v["cuts"], ", ".join(sorted(v["drums"])),
                  round(v["length"], 2)]
                 for v in sorted(agg.values(), key=lambda v: -v["length"])])
    if name == REPORT_LIST[9]:
        rows = search_tags(db, **f)
        return (name, ["Cable Tag", "Project", "From", "To", "Cable", "Required",
                       "Pulled", "Balance", "Progress %", "Drum(s)", "Status",
                       "Test"],
                [[t["tag_no"], t["project"], t["from_point"], t["to_point"],
                  f"{t['cores']} x {t['size_mm2']}".strip(" x"),
                  t["required_length"], t["pulled_length"], t["balance"],
                  t["progress"], t["drum_no"], t["status"], t["test_result"]]
                 for t in rows])
    if name == REPORT_LIST[10]:
        rows = [t for t in search_tags(db, **f)
                if t["step"] < TAG_ORDER[PULLED] and t["status"] != TAG_CANCELLED]
        return (name, ["Cable Tag", "Project", "Area", "From", "To", "Required",
                       "Status", "Remarks"],
                [[t["tag_no"], t["project"], t["area"], t["from_point"],
                  t["to_point"], t["required_length"], t["status"], t["remarks"]]
                 for t in rows])
    if name == REPORT_LIST[11]:
        rows = [t for t in search_tags(db, **f) if t["test_date"]]
        return (name, ["Cable Tag", "Project", "Test Date", "IR (MΩ)", "Continuity",
                       "Result", "Tested By", "Certificate"],
                [[t["tag_no"], t["project"], fmt_date(t["test_date"]), t["ir_value"],
                  t["continuity"], t["test_result"], t["tested_by"], t["test_cert"]]
                 for t in rows])
    if name == REPORT_LIST[12]:
        rows = [t for t in search_tags(db, **f)
                if t["test_result"] in (TEST_FAIL, TEST_PENDING)
                and t["status"] != TAG_CANCELLED]
        return (name, ["Cable Tag", "Project", "Status", "Pulled", "Test Date",
                       "IR (MΩ)", "Result", "Remarks"],
                [[t["tag_no"], t["project"], t["status"], t["pulled_length"],
                  fmt_date(t["test_date"]), t["ir_value"], t["test_result"],
                  t["remarks"]] for t in rows])
    if name == REPORT_LIST[13]:
        rows = search_drums(db, **f)
        return (name, ["Drum No.", "Cable", "Manufacturer", "Batch / Heat No.",
                       "Supplier", "PO No.", "GRN No.", "Certificate", "Cert Date",
                       "Received"],
                [[d["drum_no"], d["description"], d["manufacturer"], d["batch_no"],
                  d["supplier"], d["po_no"], d["grn_no"], d["test_cert"],
                  fmt_date(d["cert_date"]), fmt_date(d["received_date"])]
                 for d in rows])
    if name == REPORT_LIST[14]:
        rows = stock_by_cable(db, f)
        return (name, ["Cable", "Drums", "Remaining", "Value"],
                [[r["cable"], r["drums"], r["remaining"], r["value"]] for r in rows])
    if name == REPORT_LIST[15]:
        rows = db.query("SELECT * FROM audit ORDER BY id DESC LIMIT 500")
        return (name, ["When", "User", "Action", "Entity", "Reference", "Details"],
                [[r["ts"], r["username"], r["action"], r["entity"], r["entity_id"],
                  r["details"]] for r in rows])
    raise CableError(f"Unknown report: {name}")


# --------------------------------------------------------------- import (xls)
HEADER_MAP = {
    "drum": "drum_no", "drum no": "drum_no", "drum number": "drum_no",
    "reel": "drum_no", "reel no": "drum_no",
    "cable code": "cable_code", "code": "cable_code", "item code": "cable_code",
    "description": "description", "cable": "description",
    "type": "cable_type", "cable type": "cable_type",
    "insulation": "insulation", "construction": "insulation",
    "conductor": "conductor", "material": "conductor",
    "cores": "cores", "core": "cores", "no of cores": "cores",
    "size": "size_mm2", "size mm2": "size_mm2", "csa": "size_mm2",
    "sqmm": "size_mm2", "mm2": "size_mm2",
    "voltage": "voltage_grade", "voltage grade": "voltage_grade", "kv": "voltage_grade",
    "armour": "armour", "armor": "armour",
    "manufacturer": "manufacturer", "make": "manufacturer", "brand": "manufacturer",
    "batch": "batch_no", "batch no": "batch_no", "heat no": "batch_no",
    "supplier": "supplier", "vendor": "supplier",
    "po": "po_no", "po no": "po_no", "purchase order": "po_no",
    "grn": "grn_no", "grn no": "grn_no",
    "project": "project", "project no": "project",
    "warehouse": "warehouse", "store": "warehouse",
    "location": "location", "rack": "location", "yard": "location",
    "received": "received_date", "received date": "received_date",
    "date": "received_date",
    "length": "original_length", "original length": "original_length",
    "drum length": "original_length", "total length": "original_length",
    "remaining": "remaining_length", "remaining length": "remaining_length",
    "balance": "remaining_length", "available": "remaining_length",
    "uom": "uom", "unit": "uom",
    "rate": "unit_cost", "unit cost": "unit_cost", "cost": "unit_cost",
    "price": "unit_cost",
    "certificate": "test_cert", "test cert": "test_cert", "mtc": "test_cert",
    "remarks": "remarks", "remark": "remarks", "notes": "remarks",
}


def sniff(text: str) -> tuple[list[str], list[list[str]]]:
    """Split pasted spreadsheet text into (headers, rows)."""
    raw = [ln for ln in str(text or "").replace("\r\n", "\n").replace("\r", "\n")
           .split("\n") if ln.strip()]
    if not raw:
        return [], []
    if "\t" in raw[0]:
        rows = [ln.split("\t") for ln in raw]
    elif raw[0].count(",") >= 2:
        rows = list(csv.reader(io.StringIO("\n".join(raw))))
    elif raw[0].count("|") >= 2:
        rows = [[c.strip() for c in ln.strip("|").split("|")] for ln in raw]
    else:
        rows = [re.split(r"\s{2,}|\t|,", ln.strip()) for ln in raw]
    width = max(len(r) for r in rows)
    rows = [[str(c).strip() for c in list(r) + [""] * (width - len(r))] for r in rows]
    head = rows[0]
    known = sum(1 for h in head
                if re.sub(r"[^a-z0-9 ]", "", str(h).lower().strip()) in HEADER_MAP)
    return (head, rows[1:]) if known >= 2 else ([], rows)


def auto_map(headers: Sequence[str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for i, h in enumerate(headers):
        key = re.sub(r"[^a-z0-9 ]", "", str(h).lower().strip())
        if key in HEADER_MAP:
            out[i] = HEADER_MAP[key]
    return out


#: column order used when a pasted sheet has no header row
POSITIONAL = ("drum_no", "description", "size_mm2", "original_length",
              "remaining_length", "location", "project", "remarks")


def rows_to_drums(headers: Sequence[str], rows: Sequence[Sequence[Any]],
                  mapping: dict[int, str] | None = None) -> list[dict]:
    m = mapping if mapping is not None else auto_map(headers)
    if not m:
        m = {i: f for i, f in enumerate(POSITIONAL)}
    out = []
    for r in rows:
        d: dict[str, Any] = {}
        for i, field in m.items():
            if i < len(r):
                d[field] = r[i]
        if not any(str(v).strip() for v in d.values()):
            continue
        out.append(d)
    return out


def import_drums(db: CableDB, records: Sequence[dict],
                 update_existing: bool = True) -> dict:
    """Bulk-load drums from a spreadsheet. Never silently overwrites lengths."""
    added = updated = skipped = 0
    errors: list[str] = []
    for rec in records:
        drum_no = str(rec.get("drum_no") or "").strip()
        try:
            existing = drum_by_no(db, drum_no) if drum_no else None
            if existing and not update_existing:
                skipped += 1
                continue
            if existing:
                merged = dict(existing)
                merged.update({k: v for k, v in rec.items()
                               if str(v).strip() != ""})
                save_drum(db, merged, int(existing["id"]))
                updated += 1
            else:
                save_drum(db, rec)
                added += 1
        except CableError as exc:
            errors.append(f"{drum_no or '(no drum no)'}: {exc}")
        except Exception as exc:           # noqa: BLE001
            errors.append(f"{drum_no or '(no drum no)'}: {exc}")
    return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}


def template_rows() -> tuple[list[str], list[list[Any]]]:
    cols = ["Drum No.", "Cable Code", "Description", "Cable Type", "Cores", "Size",
            "Voltage Grade", "Armour", "Manufacturer", "Batch No.", "Supplier",
            "PO No.", "GRN No.", "Project", "Warehouse", "Location",
            "Received Date", "Original Length", "Remaining Length", "UOM",
            "Unit Cost", "Test Cert", "Remarks"]
    sample = [["DRM-0001", "CBL-XLPE-4C25", "XLPE 4C x 25mm² 0.6/1kV SWA", "Power",
               "4", "25mm²", "0.6/1 kV", "SWA", "Riyadh Cables", "B-77120",
               "Al Fanar", "PO-2026-0142", "GRN-2026-00081", "PRJ000087",
               "Main Warehouse", "Yard A / Row 3", today(), 1000, 1000, "M",
               18.5, "MTC-77120", "Full drum"]]
    return cols, sample


def seed_demo(db: CableDB) -> None:
    """A small, realistic set of records so the dashboard is never empty."""
    if db.scalar("SELECT COUNT(*) FROM drums"):
        return
    base = _dt.date.today()
    specs = [
        ("Power", "4", "25mm²", "0.6/1 kV", "SWA", "XLPE/PVC/SWA/PVC", 1000, 18.5),
        ("Power", "3", "185mm²", "0.6/1 kV", "SWA", "XLPE/PVC/SWA/PVC", 500, 96.0),
        ("Control", "12", "1.5mm²", "450/750 V", "SWA", "PVC/SWA/PVC", 1000, 9.4),
        ("Instrumentation", "8P", "1.5mm²", "300/500 V", "Screened", "XLPE/LSZH",
         1000, 12.2),
        ("Lighting", "3", "4mm²", "450/750 V", "Unarmoured", "PVC/PVC", 500, 4.6),
        ("Earthing", "1", "70mm²", "450/750 V", "Unarmoured", "Bare", 250, 22.0),
    ]
    makers = ("Riyadh Cables", "Jeddah Cables", "Saudi Cable Co.", "Elsewedy")
    for i, (ctype, cores, size, kv, armour, ins, length, cost) in enumerate(specs, 1):
        for j in range(2):
            drum_no = f"DRM-{i:02d}{j + 1}"
            save_drum(db, {
                "drum_no": drum_no, "cable_code": f"CBL-{ctype[:3].upper()}-{size}",
                "cable_type": ctype, "cores": cores, "size_mm2": size,
                "voltage_grade": kv, "armour": armour, "insulation": ins,
                "conductor": "Copper", "manufacturer": makers[(i + j) % len(makers)],
                "batch_no": f"B-{7000 + i * 13 + j}", "supplier": "Al Fanar",
                "po_no": f"PO-2026-{100 + i:04d}", "grn_no": f"GRN-2026-{80 + i:05d}",
                "project": f"PRJ0000{80 + (i % 3)}", "warehouse": "Main Warehouse",
                "location": f"Yard {chr(65 + i % 3)} / Row {j + 1}",
                "received_date": (base - _dt.timedelta(days=40 + i * 9 + j * 5)
                                  ).isoformat(),
                "original_length": length, "uom": "M", "unit_cost": cost,
                "test_cert": f"MTC-{7000 + i * 13 + j}",
            })
    tags = [
        ("C-1001", "MCC-01", "PUMP-101", 120, "Power", "4", "25mm²"),
        ("C-1002", "MCC-01", "PUMP-102", 135, "Power", "4", "25mm²"),
        ("C-1003", "SUB-A", "MCC-01", 240, "Power", "3", "185mm²"),
        ("C-2001", "PLC-01", "JB-11", 85, "Instrumentation", "8P", "1.5mm²"),
        ("C-2002", "PLC-01", "JB-12", 96, "Instrumentation", "8P", "1.5mm²"),
        ("C-3001", "DB-3", "LP-07", 60, "Lighting", "3", "4mm²"),
        ("C-3002", "DB-3", "LP-08", 64, "Lighting", "3", "4mm²"),
        ("C-4001", "MESH", "MCC-01", 45, "Earthing", "1", "70mm²"),
    ]
    for k, (tag, a, b, req, ctype, cores, size) in enumerate(tags):
        save_tag(db, {"tag_no": tag, "project": f"PRJ0000{80 + (k % 3)}",
                      "area": f"Area {chr(65 + k % 3)}", "system": ctype,
                      "from_point": a, "to_point": b,
                      "route": f"Trench {k % 4 + 1} / Tray T-{k + 1:02d}",
                      "cable_type": ctype, "cores": cores, "size_mm2": size,
                      "required_length": req, "status": PLANNED})
    # pull the first five tags off matching drums
    for k, (tag, _a, _b, req, ctype, _c, size) in enumerate(tags[:5]):
        drum = db.one("SELECT * FROM drums WHERE cable_type=? AND size_mm2=? "
                      "AND remaining_length>=? ORDER BY remaining_length DESC LIMIT 1",
                      (ctype, size, req))
        if drum is None:
            continue
        post_cut(db, int(drum["id"]), {
            "txn_type": CUT_ISSUE, "length": req + (2 if k % 2 else 0),
            "tag_no": tag, "project": dict(drum)["project"],
            "issued_to": ("Ahmed Khalid", "Ravi Kumar", "Site Team B")[k % 3],
            "dn_no": f"DN-2026-{170 + k:05d}",
            "from_point": _a, "to_point": _b,
            # spread over several months so the trend charts have a shape
            "cut_date": (base - _dt.timedelta(days=150 - k * 33)).isoformat()})
    for tag, result, ir in (("C-1001", TEST_PASS, 850), ("C-1002", TEST_PASS, 720),
                            ("C-2001", TEST_FAIL, 3.2)):
        row = tag_by_no(db, tag)
        if row:
            record_test(db, int(row["id"]), {
                "test_date": (base - _dt.timedelta(days=5)).isoformat(),
                "ir_value": ir, "continuity": "Pass" if result == TEST_PASS else "Fail",
                "test_result": result, "tested_by": "QC / Ahmed",
                "test_cert": f"IR-{tag}"})
    # leave one drum as a short off-cut, so that tile is never a dead zero
    short = db.one("SELECT * FROM drums WHERE cable_type='Lighting' "
                   "ORDER BY remaining_length DESC LIMIT 1")
    if short:
        post_cut(db, int(short["id"]), {
            "txn_type": CUT_ISSUE, "length": float(short["remaining_length"]) - 32,
            "project": dict(short)["project"], "issued_to": "Site Team A",
            "remarks": "Bulk issue to lighting crew",
            "cut_date": (base - _dt.timedelta(days=52)).isoformat()})
    # a returned off-cut, so the dashboard shows both directions
    first = db.one("SELECT * FROM cuts WHERE txn_type='Issue' ORDER BY id LIMIT 1")
    if first:
        post_cut(db, int(first["drum_id"]), {
            "txn_type": CUT_RETURN, "length": 8, "tag_no": first["tag_no"],
            "project": first["project"], "remarks": "Off-cut returned to store",
            "cut_date": (base - _dt.timedelta(days=2)).isoformat()})
