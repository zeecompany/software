"""GENERAL DELIVERY NOTE — a Delivery Note with no inventory dependency.

Sometimes the store has to hand something over that was never in the item
master: a hired tool, a subcontractor's material, a document pack, a sample.
This module produces a fully branded Delivery Note for exactly that case.

Guarantees:
  ·  it never touches `items`, `stock_ledger` or `documents`
  ·  it never posts a stock movement of any kind
  ·  its numbering series is separate (GDN-2026-00001 by default)
  ·  lines are free text — an item code is optional and purely informational

The PDF uses the same letterhead, signature engine and footer as the real
Delivery Note, so the recipient cannot tell the difference in quality.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .database import Database, today

DDL = """
CREATE TABLE IF NOT EXISTS gdn_documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_no        TEXT UNIQUE NOT NULL,
    doc_date      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'FINAL',    -- DRAFT | FINAL | CANCELLED
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
"""

DOC_TYPE = "GDN"
FOLDER = "Delivery Notes"

HEADER_FIELDS = ["doc_date", "title", "from_location", "to_party", "to_address",
                 "project", "reference", "vehicle", "driver", "in_time", "out_time",
                 "issued_by", "delivered_by", "handover_to", "handover_id",
                 "handover_phone", "received_by", "purpose", "remarks", "terms",
                 "currency", "show_values", "status"]

LINE_FIELDS = ["item_code", "description", "uom", "qty", "unit_cost", "pr_no", "remarks"]


def ensure_schema(db: Database) -> None:
    db.conn.executescript(DDL)
    db.conn.commit()


def next_no(db: Database) -> str:
    """GDN numbering — its own counter, never shares the DN series."""
    year = _dt.date.today().strftime("%Y")
    prefix = db.get_setting("prefix_GDN", "GDN")
    pad = int(db.get_setting("number_pad", 5) or 5)
    fmt = db.get_setting("number_format", "{prefix}-{year}-{seq}")
    db.execute("INSERT INTO counters(doc_type,year,last_no) VALUES(?,?,0)"
               " ON CONFLICT(doc_type,year) DO NOTHING", (DOC_TYPE, year))
    db.execute("UPDATE counters SET last_no = last_no + 1 WHERE doc_type=? AND year=?",
               (DOC_TYPE, year))
    n = db.scalar("SELECT last_no FROM counters WHERE doc_type=? AND year=?",
                  (DOC_TYPE, year))
    db.commit()
    return fmt.format(prefix=prefix, year=year, seq=str(int(n)).zfill(pad))


def save(db: Database, header: dict, lines: Sequence[dict],
         doc_id: int | None = None) -> tuple[int, str]:
    """Create or update a general delivery note. Returns (id, doc_no)."""
    ensure_schema(db)
    clean = [l for l in lines
             if str(l.get("description", "")).strip() or float(l.get("qty") or 0)]
    if not clean:
        raise ValueError("Add at least one line with a description or a quantity.")

    h = {k: header.get(k, "") for k in HEADER_FIELDS}
    h["doc_date"] = h.get("doc_date") or today()
    h["title"] = h.get("title") or "DELIVERY NOTE"
    h["status"] = h.get("status") or "FINAL"
    h["show_values"] = 1 if str(header.get("show_values", 0)) in ("1", "True", "true") else 0
    total = sum(float(l.get("qty") or 0) * float(l.get("unit_cost") or 0) for l in clean)

    if doc_id:
        sets = ", ".join(f"{k}=?" for k in HEADER_FIELDS)
        db.execute(f"UPDATE gdn_documents SET {sets}, total_value=?, updated_at=?"
                   f" WHERE id=?",
                   [h[k] for k in HEADER_FIELDS] + [total, _stamp(), doc_id])
        db.execute("DELETE FROM gdn_lines WHERE doc_id=?", (doc_id,))
        doc_no = db.scalar("SELECT doc_no FROM gdn_documents WHERE id=?", (doc_id,),
                           default="")
    else:
        doc_no = header.get("doc_no") or next_no(db)
        cols = ", ".join(["doc_no", "total_value", "created_by"] + HEADER_FIELDS)
        marks = ", ".join("?" * (len(HEADER_FIELDS) + 3))
        cur = db.execute(f"INSERT INTO gdn_documents({cols}) VALUES({marks})",
                         [doc_no, total, db.current_user] + [h[k] for k in HEADER_FIELDS])
        doc_id = int(cur.lastrowid)

    for i, l in enumerate(clean, 1):
        qty = float(l.get("qty") or 0)
        cost = float(l.get("unit_cost") or 0)
        db.execute(
            "INSERT INTO gdn_lines(doc_id,line_no,item_code,description,uom,qty,"
            "unit_cost,total_cost,pr_no,remarks) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (doc_id, i, str(l.get("item_code", "")), str(l.get("description", "")),
             str(l.get("uom", "")), qty, cost, qty * cost, str(l.get("pr_no", "")),
             str(l.get("remarks", ""))))
    db.commit()
    db.audit("CREATED" if not header.get("_edit") else "EDITED", "general-dn", doc_no,
             f"{len(clean)} line(s), no stock effect")
    return doc_id, str(doc_no)


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get(db: Database, doc_id: int) -> tuple[dict, list[dict]] | tuple[None, list]:
    ensure_schema(db)
    r = db.one("SELECT * FROM gdn_documents WHERE id=?", (doc_id,))
    if r is None:
        return None, []
    lines = [dict(x) for x in db.query(
        "SELECT * FROM gdn_lines WHERE doc_id=? ORDER BY line_no, id", (doc_id,))]
    return dict(r), lines


def listing(db: Database, text: str = "", date_from: str = "", date_to: str = "",
            status: str = "") -> list[dict]:
    ensure_schema(db)
    sql = ("SELECT d.*, (SELECT COUNT(*) FROM gdn_lines l WHERE l.doc_id=d.id) lines,"
           " (SELECT COALESCE(SUM(qty),0) FROM gdn_lines l WHERE l.doc_id=d.id) qty"
           " FROM gdn_documents d WHERE 1=1")
    p: list[Any] = []
    if text.strip():
        like = f"%{text.strip()}%"
        sql += (" AND (d.doc_no LIKE ? OR d.to_party LIKE ? OR d.project LIKE ?"
                " OR d.reference LIKE ? OR d.vehicle LIKE ? OR d.handover_to LIKE ?)")
        p += [like] * 6
    if date_from:
        sql += " AND d.doc_date>=?"
        p.append(date_from)
    if date_to:
        sql += " AND d.doc_date<=?"
        p.append(date_to)
    if status:
        sql += " AND d.status=?"
        p.append(status)
    sql += " ORDER BY d.doc_date DESC, d.id DESC"
    return [dict(r) for r in db.query(sql, p)]


def delete(db: Database, doc_id: int) -> None:
    doc_no = db.scalar("SELECT doc_no FROM gdn_documents WHERE id=?", (doc_id,), default="")
    db.execute("DELETE FROM gdn_lines WHERE doc_id=?", (doc_id,))
    db.execute("DELETE FROM gdn_documents WHERE id=?", (doc_id,))
    db.commit()
    db.audit("DELETED", "general-dn", doc_no)


def cancel(db: Database, doc_id: int, reason: str = "") -> None:
    db.execute("UPDATE gdn_documents SET status='CANCELLED', remarks=COALESCE(remarks,'')"
               " || ? WHERE id=?", (f"\nCANCELLED: {reason}" if reason else "\nCANCELLED",
                                    doc_id))
    db.commit()
    db.audit("CANCELLED", "general-dn", doc_id, reason)


# ------------------------------------------------------------------ templates
def save_template(db: Database, name: str, header: dict, lines: Sequence[dict]) -> None:
    import json
    ensure_schema(db)
    payload = json.dumps({"header": {k: header.get(k, "") for k in HEADER_FIELDS},
                          "lines": [{k: l.get(k, "") for k in LINE_FIELDS}
                                    for l in lines]})
    db.execute("INSERT INTO gdn_templates(name,payload) VALUES(?,?)"
               " ON CONFLICT(name) DO UPDATE SET payload=excluded.payload", (name, payload))
    db.commit()
    db.audit("SAVED", "gdn-template", name)


def load_template(db: Database, name: str) -> tuple[dict, list[dict]]:
    import json
    ensure_schema(db)
    raw = db.scalar("SELECT payload FROM gdn_templates WHERE name=?", (name,), default="")
    if not raw:
        return {}, []
    try:
        d = json.loads(raw)
        return d.get("header", {}), d.get("lines", [])
    except Exception:
        return {}, []


def template_names(db: Database) -> list[str]:
    ensure_schema(db)
    return [r["name"] for r in db.query("SELECT name FROM gdn_templates ORDER BY name")]


def delete_template(db: Database, name: str) -> None:
    db.execute("DELETE FROM gdn_templates WHERE name=?", (name,))
    db.commit()


def duplicate(db: Database, doc_id: int) -> tuple[int, str]:
    """Copy an existing note into a brand-new one — the fastest repeat workflow."""
    h, lines = get(db, doc_id)
    if not h:
        raise ValueError("Delivery note not found")
    h = dict(h)
    h.pop("doc_no", None)
    h["doc_date"] = today()
    return save(db, h, lines)


def stats(db: Database) -> dict:
    ensure_schema(db)
    return {
        "notes": int(db.scalar("SELECT COUNT(*) FROM gdn_documents")),
        "this_month": int(db.scalar(
            "SELECT COUNT(*) FROM gdn_documents WHERE substr(doc_date,1,7)=?",
            (_dt.date.today().strftime("%Y-%m"),))),
        "lines": int(db.scalar("SELECT COUNT(*) FROM gdn_lines")),
        "qty": float(db.scalar("SELECT COALESCE(SUM(qty),0) FROM gdn_lines")),
    }
