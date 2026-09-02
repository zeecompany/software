"""SQLite schema, migrations, settings store and audit trail for AURCO."""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import config

SCHEMA_VERSION = 10

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT UNIQUE NOT NULL,
    full_name    TEXT,
    password_hash TEXT,
    role         TEXT NOT NULL DEFAULT 'Storekeeper',
    permissions  TEXT DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS categories (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT UNIQUE NOT NULL,
    parent   TEXT DEFAULT '',
    min_pct  REAL,           -- category level thresholds (nullable => global)
    crit_pct REAL
);

CREATE TABLE IF NOT EXISTS uoms (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouses (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT UNIQUE NOT NULL,
    address TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS locations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse TEXT NOT NULL,
    name      TEXT NOT NULL,
    UNIQUE(warehouse, name)
);

CREATE TABLE IF NOT EXISTS sites (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS suppliers (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT UNIQUE NOT NULL,
    contact TEXT DEFAULT '',
    phone   TEXT DEFAULT '',
    email   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT UNIQUE NOT NULL,
    description    TEXT NOT NULL,
    short_desc     TEXT DEFAULT '',
    category       TEXT DEFAULT '',
    subcategory    TEXT DEFAULT '',
    uom            TEXT DEFAULT 'PCS',
    brand          TEXT DEFAULT '',
    model          TEXT DEFAULT '',
    specification  TEXT DEFAULT '',
    barcode        TEXT DEFAULT '',
    alt_code       TEXT DEFAULT '',
    min_level      REAL DEFAULT 0,
    max_level      REAL DEFAULT 0,
    reorder_level  REAL DEFAULT 0,
    critical_level REAL DEFAULT 0,
    threshold_mode TEXT DEFAULT 'GLOBAL',   -- GLOBAL | PERCENT | QTY | CATEGORY
    min_pct        REAL,
    crit_pct       REAL,
    opening_balance REAL DEFAULT 0,
    balance        REAL NOT NULL DEFAULT 0,
    damaged_qty    REAL NOT NULL DEFAULT 0,
    unit_cost      REAL DEFAULT 0,
    warehouse      TEXT DEFAULT '',
    location       TEXT DEFAULT '',
    rack           TEXT DEFAULT '',
    remarks        TEXT DEFAULT '',
    image_path     TEXT DEFAULT '',
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT DEFAULT (datetime('now','localtime')),
    updated_at     TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_items_desc ON items(description);
CREATE INDEX IF NOT EXISTS ix_items_cat  ON items(category);
CREATE INDEX IF NOT EXISTS ix_items_bar  ON items(barcode);
CREATE INDEX IF NOT EXISTS ix_items_wh   ON items(warehouse);

-- Document headers (GRN / DN / RET / ADJ / TRF / CNT)
CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type     TEXT NOT NULL,
    doc_no       TEXT NOT NULL,
    doc_date     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'DRAFT',  -- DRAFT | FINAL | REVERSED
    supplier     TEXT DEFAULT '',
    reference    TEXT DEFAULT '',
    project      TEXT DEFAULT '',
    department   TEXT DEFAULT '',
    requested_by TEXT DEFAULT '',
    issued_to    TEXT DEFAULT '',
    received_by  TEXT DEFAULT '',
    issued_by    TEXT DEFAULT '',
    delivered_by TEXT DEFAULT '',
    handover_to  TEXT DEFAULT '',
    handover_id  TEXT DEFAULT '',        -- Iqama / ID of the person taking custody
    handover_phone TEXT DEFAULT '',
    from_location TEXT DEFAULT '',
    in_time      TEXT DEFAULT '',
    out_time     TEXT DEFAULT '',
    returned_by  TEXT DEFAULT '',
    vehicle      TEXT DEFAULT '',
    driver       TEXT DEFAULT '',
    purpose      TEXT DEFAULT '',
    warehouse    TEXT DEFAULT '',
    to_warehouse TEXT DEFAULT '',
    location     TEXT DEFAULT '',
    to_location  TEXT DEFAULT '',
    reason       TEXT DEFAULT '',
    linked_doc   TEXT DEFAULT '',
    remarks      TEXT DEFAULT '',
    total_value  REAL DEFAULT 0,
    pdf_path     TEXT DEFAULT '',
    created_by   TEXT DEFAULT '',
    created_at   TEXT DEFAULT (datetime('now','localtime')),
    finalized_at TEXT,
    UNIQUE(doc_type, doc_no)
);
CREATE INDEX IF NOT EXISTS ix_doc_type_date ON documents(doc_type, doc_date);
CREATE INDEX IF NOT EXISTS ix_doc_no        ON documents(doc_no);

CREATE TABLE IF NOT EXISTS document_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    item_id     INTEGER NOT NULL REFERENCES items(id),
    item_code   TEXT NOT NULL,
    description TEXT DEFAULT '',
    uom         TEXT DEFAULT '',
    qty         REAL NOT NULL DEFAULT 0,
    issued_qty  REAL DEFAULT 0,      -- returns: originally issued
    unit_cost   REAL DEFAULT 0,
    total_cost  REAL DEFAULT 0,
    condition   TEXT DEFAULT '',     -- USABLE | DAMAGED
    batch       TEXT DEFAULT '',
    location    TEXT DEFAULT '',
    system_qty  REAL DEFAULT 0,      -- stock count
    counted_qty REAL DEFAULT 0,
    variance    REAL DEFAULT 0,
    pr_no       TEXT DEFAULT '',      -- Purchase Request number (per line)
    remarks     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_lines_doc  ON document_lines(doc_id);
CREATE INDEX IF NOT EXISTS ix_lines_item ON document_lines(item_id);

-- Immutable stock ledger. One row per stock effect.
CREATE TABLE IF NOT EXISTS stock_ledger (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       INTEGER NOT NULL REFERENCES items(id),
    item_code     TEXT NOT NULL,
    txn_date      TEXT NOT NULL,
    txn_type      TEXT NOT NULL,   -- OPENING|RECEIPT|ISSUE|RETURN|TRANSFER_OUT|TRANSFER_IN|ADJUSTMENT|DAMAGE
    doc_type      TEXT DEFAULT '',
    doc_no        TEXT DEFAULT '',
    doc_id        INTEGER,
    qty_in        REAL DEFAULT 0,
    qty_out       REAL DEFAULT 0,
    balance_after REAL NOT NULL,
    unit_cost     REAL DEFAULT 0,
    warehouse     TEXT DEFAULT '',
    location      TEXT DEFAULT '',
    party         TEXT DEFAULT '',
    reason        TEXT DEFAULT '',
    username      TEXT DEFAULT '',
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_ledger_item ON stock_ledger(item_id, id);
CREATE INDEX IF NOT EXISTS ix_ledger_date ON stock_ledger(txn_date);
CREATE INDEX IF NOT EXISTS ix_ledger_type ON stock_ledger(txn_type);

CREATE TABLE IF NOT EXISTS attachments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type   TEXT,
    doc_no     TEXT,
    item_id    INTEGER,
    file_path  TEXT NOT NULL,
    source     TEXT DEFAULT 'file',
    page_order INTEGER NOT NULL DEFAULT 1,
    added_at   TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS audit_trail (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT DEFAULT (datetime('now','localtime')),
    username  TEXT DEFAULT '',
    action    TEXT NOT NULL,
    entity    TEXT DEFAULT '',
    entity_id TEXT DEFAULT '',
    details   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_trail(ts);

CREATE TABLE IF NOT EXISTS counters (
    doc_type TEXT NOT NULL,
    year     TEXT NOT NULL,
    last_no  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (doc_type, year)
);

CREATE TABLE IF NOT EXISTS signatories (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    designation    TEXT DEFAULT '',
    department     TEXT DEFAULT '',
    role           TEXT DEFAULT '',
    signature_path TEXT DEFAULT '',
    phone          TEXT DEFAULT '',
    id_number      TEXT DEFAULT '',      -- Iqama / national ID / licence
    email          TEXT DEFAULT '',
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_sig_name ON signatories(name);

-- who signed a specific document (overrides the configured defaults)
CREATE TABLE IF NOT EXISTS document_signatures (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type       TEXT NOT NULL,
    doc_no         TEXT NOT NULL,
    role           TEXT NOT NULL,
    name           TEXT DEFAULT '',
    designation    TEXT DEFAULT '',
    signature_path TEXT DEFAULT '',
    id_number      TEXT DEFAULT '',
    phone          TEXT DEFAULT '',
    UNIQUE(doc_type, doc_no, role)
);

CREATE TABLE IF NOT EXISTS material_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mr_no        TEXT UNIQUE NOT NULL,
    mr_date      TEXT NOT NULL,
    project_id   TEXT DEFAULT '',
    site         TEXT DEFAULT '',
    department   TEXT DEFAULT '',
    requested_by TEXT DEFAULT '',
    reference    TEXT DEFAULT '',
    pr_no        TEXT DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'Pending',
    remarks      TEXT DEFAULT '',
    created_by   TEXT DEFAULT '',
    created_at   TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_mr_status  ON material_requests(status);
CREATE INDEX IF NOT EXISTS ix_mr_project ON material_requests(project_id);
CREATE INDEX IF NOT EXISTS ix_mr_date    ON material_requests(mr_date);

CREATE TABLE IF NOT EXISTS mr_lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    mr_id         INTEGER NOT NULL REFERENCES material_requests(id) ON DELETE CASCADE,
    line_no       TEXT DEFAULT '',
    item_id       INTEGER REFERENCES items(id),
    item_code     TEXT DEFAULT '',
    description   TEXT DEFAULT '',
    uom           TEXT DEFAULT '',
    category      TEXT DEFAULT '',
    procurement_category TEXT DEFAULT '',
    project_id    TEXT DEFAULT '',
    pr_no         TEXT DEFAULT '',
    qty_requested REAL NOT NULL DEFAULT 0,
    qty_prepared  REAL NOT NULL DEFAULT 0,
    qty_delivered REAL NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'Pending',
    avail_snapshot TEXT DEFAULT '',
    dn_no         TEXT DEFAULT '',
    prepared_by   TEXT DEFAULT '',
    prepared_at   TEXT,
    delivered_at  TEXT,
    remarks       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_mrl_mr     ON mr_lines(mr_id);
CREATE INDEX IF NOT EXISTS ix_mrl_item   ON mr_lines(item_id);
CREATE INDEX IF NOT EXISTS ix_mrl_status ON mr_lines(status);
CREATE INDEX IF NOT EXISTS ix_mrl_pr     ON mr_lines(pr_no);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT DEFAULT '',
    body       TEXT DEFAULT '',
    color      TEXT DEFAULT 'Yellow',
    category   TEXT DEFAULT '',
    pinned     INTEGER NOT NULL DEFAULT 0,
    archived   INTEGER NOT NULL DEFAULT 0,
    link_type  TEXT DEFAULT '',
    link_ref   TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_notes_pin ON notes(pinned, archived);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    details      TEXT DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'To Do',
    priority     TEXT NOT NULL DEFAULT 'Normal',
    due_date     TEXT DEFAULT '',
    due_time     TEXT DEFAULT '',
    assignee     TEXT DEFAULT '',
    category     TEXT DEFAULT '',
    progress     INTEGER NOT NULL DEFAULT 0,
    checklist    TEXT DEFAULT '',
    repeat_rule  TEXT DEFAULT 'None',
    remind       INTEGER NOT NULL DEFAULT 0,
    link_type    TEXT DEFAULT '',
    link_ref     TEXT DEFAULT '',
    created_by   TEXT DEFAULT '',
    created_at   TEXT,
    updated_at   TEXT,
    completed_at TEXT,
    alerted_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS ix_tasks_due    ON tasks(due_date);

-- General Delivery Notes (no inventory effect -- see core/gdn.py)
CREATE TABLE IF NOT EXISTS gdn_documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_no        TEXT UNIQUE NOT NULL,
    doc_date      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'FINAL',
    title         TEXT DEFAULT 'DELIVERY NOTE',
    from_location TEXT DEFAULT '',
    to_party      TEXT DEFAULT '',
    to_address    TEXT DEFAULT '',
    project       TEXT DEFAULT '',
    reference     TEXT DEFAULT '',
    vehicle       TEXT DEFAULT '',
    driver        TEXT DEFAULT '',
    in_time       TEXT DEFAULT '',
    out_time      TEXT DEFAULT '',
    issued_by     TEXT DEFAULT '',
    delivered_by  TEXT DEFAULT '',
    handover_to   TEXT DEFAULT '',
    handover_id   TEXT DEFAULT '',
    handover_phone TEXT DEFAULT '',
    received_by   TEXT DEFAULT '',
    purpose       TEXT DEFAULT '',
    remarks       TEXT DEFAULT '',
    terms         TEXT DEFAULT '',
    currency      TEXT DEFAULT '',
    show_values   INTEGER NOT NULL DEFAULT 0,
    total_value   REAL DEFAULT 0,
    pdf_path      TEXT DEFAULT '',
    created_by    TEXT DEFAULT '',
    created_at    TEXT DEFAULT (datetime('now','localtime')),
    updated_at    TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_gdn_date ON gdn_documents(doc_date);

CREATE TABLE IF NOT EXISTS gdn_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      INTEGER NOT NULL REFERENCES gdn_documents(id) ON DELETE CASCADE,
    line_no     INTEGER DEFAULT 0,
    item_code   TEXT DEFAULT '',
    description TEXT DEFAULT '',
    uom         TEXT DEFAULT '',
    qty         REAL NOT NULL DEFAULT 0,
    unit_cost   REAL NOT NULL DEFAULT 0,
    total_cost  REAL NOT NULL DEFAULT 0,
    pr_no       TEXT DEFAULT '',
    remarks     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_gdnl_doc ON gdn_lines(doc_id);

CREATE TABLE IF NOT EXISTS gdn_templates (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT UNIQUE NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS backups (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT DEFAULT (datetime('now','localtime')),
    path      TEXT,
    size_kb   REAL,
    kind      TEXT DEFAULT 'MANUAL',
    note      TEXT DEFAULT ''
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "company_name": "ATTIQ UR REHMAN CONT. CO.",
    "company_tagline": "Electro Mechanical Works",
    "company_address": "",
    "company_phone": "",
    "company_email": "",
    "company_vat": "300143665200003",
    "company_cr": "2051062884",
    "company_name_ar": "شركة عتيق الرحمن للمقاولات",
    "company_tagline_ar": "الأشغال الميكانيكية والكهربائية",
    "cr_label_ar": "س.ت",
    "arabic_font_style": "Kufi",       # Kufi | Naskh | Amiri | System
    "arabic_eastern_digits": "1",      # ١٢٣٤ instead of 1234 in Arabic text
    "vat_label_ar": "الرقم الضريبي",
    "company_vat_ar": "",
    "company_cr_ar": "",
    "logo_path": "",
    "created_by": config.CREATED_BY,
    "doc_footer": "This is a system generated document from AURCO Inventory Manager.",
    "currency": "SAR",
    "date_format": "dd-MM-yyyy",
    "theme": "Light",
    "default_uom": "PCS",
    "allow_negative_stock": "0",
    "windows_notifications": "1",
    # global alert thresholds (percent of max level)
    "global_min_pct": "40",
    "global_crit_pct": "20",
    # numbering
    "prefix_DN": "DN", "prefix_RET": "RET", "prefix_GRN": "GRN",
    "prefix_ADJ": "ADJ", "prefix_TRF": "TRF", "prefix_CNT": "CNT", "prefix_MR": "MR",
    "prefix_GDN": "GDN",
    # Material Request header defaults (auto-filled after a paste)
    "mr_default_department": "Site Team",
    "mr_default_requested_by": "By Site Team",
    "mr_site_follows_project": "1",
    "number_pad": "5",
    "number_format": "{prefix}-{year}-{seq}",
    "item_code_prefix": "ITM",
    "item_code_pad": "5",
    # email
    "smtp_host": "", "smtp_port": "587", "smtp_user": "", "smtp_pass": "",
    "smtp_tls": "1", "smtp_from": "",
    # whatsapp
    "wa_default_number": "", "wa_message": "Please find attached the document from AURCO Inventory Manager.",
    # backup
    "backup_folder": "", "auto_backup_on_exit": "1", "backup_keep": "20",
    "printer_name": "",
    # sounds
    "sound_enabled": "1",
    "sound_reminder_interval": "60",   # seconds between reminder checks
    "sound_repeat_overdue": "1",
    # security
    "require_login": "0",
    "require_admin_password_delete": "1",
    "require_admin_password_reverse": "1",
    "auto_logout_minutes": "0",
    "last_user": "admin",
    # appearance / theme
    "ui_preset": "AURCO Light",
    # logo placement on PDFs
    "logo_position": "Left",          # Left | Center | Right | None
    "logo_width_mm": "16",
    "logo_height_mm": "14",
    "logo_show_on_docs": "1",
    "logo_show_on_reports": "1",
    "logo_watermark": "0",
    "sidebar_logo_path": "",
    # delivery note file naming
    "dn_filename_include_pr": "1",
    "dn_filename_separator": " ",
    "dn_filename_use_pattern": "1",
    "dn_filename_template":
        "{docno} Material Delivered ({warehouse} - {project}) {prs}",
    # signatures
    "print_signature_images": "1",
    "signature_line_style": "Line",     # Line | Box | None
    "show_signature_datetime": "1",
    "show_handover_id": "1",          # print Iqama / ID under the handover signature
    # PDF header / footer designer
    "pdf_header_height": "22",
    "pdf_header_show_company": "1",
    "pdf_header_show_tagline": "1",
    "pdf_header_show_title": "1",
    "pdf_header_show_datetime": "1",
    "pdf_header_align": "Left",
    "pdf_header_style": "Gradient",   # Gradient | Solid
    "pdf_header_color1": "",          # band start (blank = theme primary)
    "pdf_header_color2": "",          # gradient end (blank = auto lighter shade)
    "logo_backing": "Auto",           # Auto | White | Dark | None
    "pdf_accent_bar": "1",
    "pdf_footer_show_page": "1",
    "pdf_footer_show_credit": "1",
    "pdf_footer_line": "1",
    "pdf_footer_height": "14",
}


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return _dt.date.today().isoformat()


class Database:
    """Thin, safe wrapper around sqlite3 with helpers used by every module."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or config.db_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.current_user = "admin"
        self._init_schema()

    # ---------------------------------------------------------------- schema
    def _init_schema(self) -> None:
        self.conn.executescript(DDL)
        self.conn.commit()
        self._migrate()
        cur = self.get_setting("schema_version")
        if cur is None:
            self.set_setting("schema_version", str(SCHEMA_VERSION))
        for k, v in DEFAULT_SETTINGS.items():
            if self.get_setting(k) is None:
                self.set_setting(k, str(v))
        from .theming import THEME_KEYS
        for k, v in THEME_KEYS.items():
            if self.get_setting(k) is None:
                self.set_setting(k, str(v))
        # ship the AURCO logo and a matching header out of the box
        if not self.get_setting("logo_path"):
            from .config import bundled_logo
            lg = bundled_logo()
            if lg:
                self.set_setting("logo_path", str(lg))
                self.set_setting("logo_width_mm", "34")
                self.set_setting("logo_height_mm", "9")
                # ship the printed letterhead as the default page header
                import json as _json
                from .header_design import PRESETS as _HP
                if not self.get_setting("header_design___default__"):
                    self.set_setting(
                        "header_design___default__",
                        _json.dumps(_HP["AURCO Letterhead (English + Arabic)"]))
                for k, v in (("pdf_header_color1", "#12161c"),
                             ("pdf_header_color2", "#c1121f"),
                             ("pdf_header_style", "Gradient"),
                             ("pdf_header_height", "26"),
                             ("logo_backing", "None")):
                    if not self.get_setting(k):
                        self.set_setting(k, v)
        if self.scalar("SELECT COUNT(*) FROM users") == 0:
            self.execute(
                "INSERT INTO users(username, full_name, password_hash, role, active)"
                " VALUES('admin','Administrator','', 'Administrator',1)")
        self.conn.commit()

    def _migrate(self) -> None:
        """Additive migrations for databases created by an earlier version.

        Safe to run on every start: each step checks before it changes anything,
        and no existing data is ever dropped or rewritten.
        """
        def columns(table: str) -> set[str]:
            return {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}

        added = []
        # v2: per-line Purchase Request number (multi-PR delivery notes)
        if "pr_no" not in columns("document_lines"):
            self.conn.execute("ALTER TABLE document_lines ADD COLUMN pr_no TEXT DEFAULT ''")
            added.append("document_lines.pr_no")
        # index is created here (not in the base DDL) so that upgrading an older
        # database adds the column first
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_lines_pr ON document_lines(pr_no)")
        # v4/v5/v6: named signatory, gate-pass and handover-identity fields
        for col in ("issued_by", "delivered_by", "handover_to",
                    "from_location", "in_time", "out_time",
                    "handover_id", "handover_phone"):
            if col not in columns("documents"):
                self.conn.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT DEFAULT ''")
                added.append(f"documents.{col}")
        # v7: reminder bookkeeping on tasks
        if "tasks" in {r["name"] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}:
            if "alerted_at" not in columns("tasks"):
                self.conn.execute("ALTER TABLE tasks ADD COLUMN alerted_at TEXT")
                added.append("tasks.alerted_at")
        # v6: Iqama / ID number on the signatory directory and on each signature
        if "id_number" not in columns("signatories"):
            self.conn.execute("ALTER TABLE signatories ADD COLUMN id_number TEXT DEFAULT ''")
            added.append("signatories.id_number")
        for col in ("id_number", "phone"):
            if col not in columns("document_signatures"):
                self.conn.execute(
                    f"ALTER TABLE document_signatures ADD COLUMN {col} TEXT DEFAULT ''")
                added.append(f"document_signatures.{col}")
        # v9: the Arabic letterhead rows now use {cr_ar} / {vat_ar} so the
        # Arabic-side numbers can be corrected independently. Saved designs
        # still holding the old {cr} / {vat} tokens are migrated in place --
        # the fallback makes the output identical unless an override is set.
        for r in self.conn.execute(
                "SELECT key, value FROM settings WHERE key LIKE 'header_design_%'"
                " OR key LIKE 'footer_design_%'").fetchall():
            val = r[1] if not isinstance(r, dict) else r["value"]
            key = r[0] if not isinstance(r, dict) else r["key"]
            if not val or "_ar}" not in str(val):
                continue
            new_val = str(val)
            if "{cr_label_ar} {cr}" in new_val or "{vat_label_ar} {vat}" in new_val:
                new_val = new_val.replace("{cr_label_ar} {cr}",
                                          "{cr_label_ar} {cr_ar}")
                new_val = new_val.replace("{vat_label_ar} {vat}",
                                          "{vat_label_ar} {vat_ar}")
                self.conn.execute("UPDATE settings SET value=? WHERE key=?",
                                  (new_val, key))
                added.append(f"letterhead {key} -> Arabic VAT/CR tokens")

        # v8: General Delivery Note tables (standalone, no stock effect)
        from .gdn import DDL as _GDN_DDL
        self.conn.executescript(_GDN_DDL)

        # v10: attachment source / ordering (clipboard items append last)
        for col, sql in (
            ("source", "ALTER TABLE attachments ADD COLUMN source TEXT DEFAULT 'file'"),
            ("page_order", "ALTER TABLE attachments ADD COLUMN page_order INTEGER NOT NULL DEFAULT 1"),
        ):
            if col not in columns("attachments"):
                self.conn.execute(sql)
                added.append(f"attachments.{col}")
        if added:
            self.conn.commit()
            try:
                self.audit("MIGRATED", "database", "",
                           f"schema upgraded: {', '.join(added)}")
            except Exception:
                pass
        self.set_setting("schema_version", str(SCHEMA_VERSION))

    # ------------------------------------------------------------- primitives
    def execute(self, sql: str, params: Sequence = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        return cur

    def executemany(self, sql: str, seq: Iterable[Sequence]) -> None:
        self.conn.executemany(sql, seq)

    def query(self, sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def one(self, sql: str, params: Sequence = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence = (), default=0):
        r = self.conn.execute(sql, params).fetchone()
        if r is None or r[0] is None:
            return default
        return r[0]

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass

    # --------------------------------------------------------------- settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else default

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.get_setting(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        v = self.get_setting(key)
        if v is None:
            return default
        return str(v) in ("1", "True", "true", "yes")

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.conn.commit()

    def settings_dict(self) -> dict:
        return {r["key"]: r["value"] for r in self.query("SELECT key,value FROM settings")}

    # ------------------------------------------------------------------ audit
    def audit(self, action: str, entity: str = "", entity_id: str = "", details: str = "") -> None:
        self.execute(
            "INSERT INTO audit_trail(ts,username,action,entity,entity_id,details)"
            " VALUES(?,?,?,?,?,?)",
            (_now(), self.current_user, action, entity, str(entity_id), details))
        self.conn.commit()

    # ------------------------------------------------------------- numbering
    def next_doc_number(self, doc_type: str, commit: bool = True) -> str:
        """doc_type in GRN/DN/RET/ADJ/TRF/CNT. Atomic, unique per year."""
        year = _dt.date.today().strftime("%Y")
        prefix = self.get_setting(f"prefix_{doc_type}", doc_type)
        pad = int(self.get_setting("number_pad", 5) or 5)
        fmt = self.get_setting("number_format", "{prefix}-{year}-{seq}")
        self.execute(
            "INSERT INTO counters(doc_type,year,last_no) VALUES(?,?,0) "
            "ON CONFLICT(doc_type,year) DO NOTHING", (doc_type, year))
        self.execute(
            "UPDATE counters SET last_no = last_no + 1 WHERE doc_type=? AND year=?",
            (doc_type, year))
        n = self.scalar("SELECT last_no FROM counters WHERE doc_type=? AND year=?",
                        (doc_type, year))
        if commit:
            self.conn.commit()
        return fmt.format(prefix=prefix, year=year, seq=str(int(n)).zfill(pad))

    def next_item_code(self) -> str:
        prefix = self.get_setting("item_code_prefix", "ITM")
        pad = int(self.get_setting("item_code_pad", 5) or 5)
        rows = self.query("SELECT code FROM items WHERE code LIKE ?", (f"{prefix}-%",))
        mx = 0
        for r in rows:
            tail = r["code"].rsplit("-", 1)[-1]
            if tail.isdigit():
                mx = max(mx, int(tail))
        return f"{prefix}-{str(mx + 1).zfill(pad)}"

    # --------------------------------------------------------------- backups
    def backup(self, dest_folder: str | Path | None = None, kind: str = "MANUAL",
               note: str = "") -> Path:
        dest_folder = Path(dest_folder or self.get_setting("backup_folder")
                           or config.folder("Backups"))
        dest_folder.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_folder / f"aurco_backup_{stamp}.db"
        self.conn.commit()
        target = sqlite3.connect(str(dest))
        with target:
            self.conn.backup(target)
        target.close()
        size = dest.stat().st_size / 1024.0
        self.execute("INSERT INTO backups(ts,path,size_kb,kind,note) VALUES(?,?,?,?,?)",
                     (_now(), str(dest), size, kind, note))
        self.conn.commit()
        self.audit("BACKUP", "database", dest.name, f"{size:.0f} KB")
        self._prune_backups(dest_folder)
        return dest

    def _prune_backups(self, folder: Path) -> None:
        keep = int(self.get_setting("backup_keep", 20) or 20)
        files = sorted(folder.glob("aurco_backup_*.db"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        for f in files[keep:]:
            # With file protection on, an old backup is archived rather than
            # deleted -- see core/protection.py.
            try:
                from . import protection as _P
                if _P.is_enabled(self):
                    _P.archive_instead_of_delete(self, f, "backup rotation")
                    self.execute("DELETE FROM backups WHERE path=?", (str(f),))
                    continue
            except Exception:
                pass
            try:
                f.unlink()
                self.execute("DELETE FROM backups WHERE path=?", (str(f),))
            except OSError:
                pass
        self.conn.commit()

    def restore(self, backup_file: str | Path) -> None:
        """Replace the live database with a backup (a safety copy is taken first)."""
        backup_file = Path(backup_file)
        if not backup_file.exists():
            raise FileNotFoundError(backup_file)
        self.backup(kind="PRE-RESTORE", note=f"before restoring {backup_file.name}")
        self.conn.close()
        shutil.copy2(backup_file, self.path)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self.audit("RESTORE", "database", backup_file.name)

    def validate(self) -> list[str]:
        """Integrity checks: sqlite check + ledger vs item balance reconciliation."""
        msgs = []
        ok = self.scalar("PRAGMA integrity_check", default="?")
        msgs.append(f"SQLite integrity_check: {ok}")
        bad = self.query(
            """SELECT i.code, i.balance,
                      COALESCE((SELECT SUM(qty_in-qty_out) FROM stock_ledger l
                                WHERE l.item_id=i.id),0) AS ledger
               FROM items i""")
        diffs = [r for r in bad if abs((r["balance"] or 0) - (r["ledger"] or 0)) > 1e-6]
        if diffs:
            msgs.append(f"{len(diffs)} item(s) out of sync with ledger:")
            for r in diffs[:20]:
                msgs.append(f"   {r['code']}: item={r['balance']:g} ledger={r['ledger']:g}")
        else:
            msgs.append("All item balances reconcile with the stock ledger.")
        msgs.append(f"Items: {self.scalar('SELECT COUNT(*) FROM items')}  |  "
                    f"Ledger rows: {self.scalar('SELECT COUNT(*) FROM stock_ledger')}  |  "
                    f"Documents: {self.scalar('SELECT COUNT(*) FROM documents')}")
        return msgs

    def repair_balances(self) -> int:
        rows = self.query(
            """SELECT i.id, COALESCE((SELECT SUM(qty_in-qty_out) FROM stock_ledger l
                       WHERE l.item_id=i.id),0) AS ledger FROM items i""")
        n = 0
        for r in rows:
            n += self.execute("UPDATE items SET balance=? WHERE id=? AND balance<>?",
                              (r["ledger"], r["id"], r["ledger"])).rowcount
        self.conn.commit()
        self.audit("REPAIR", "items", "", f"{n} balances rebuilt from ledger")
        return n


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db


def set_db(db: Database) -> None:
    global _db
    _db = db


def reset_db() -> None:
    global _db
    if _db is not None:
        _db.close()
    _db = None
