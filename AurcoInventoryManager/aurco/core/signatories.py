"""Signatories & document layout customisation for AURCO documents.

Two things live here:

* **Signatories** — a reusable directory of people (name, designation, optional
  signature image). Each document type has a configurable set of signature
  blocks, and each block can have a *default* signatory that is filled in
  automatically, so a Delivery Note is ready with one click.

* **Document layout** — per-document-type appearance (accent colour, table
  header colour, zebra striping, font size, column widths, which signature
  blocks appear, whether the PR recap table is printed, and so on).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .database import Database

# ------------------------------------------------------------- signatories
ROLE_ISSUED_BY = "Issued By"
ROLE_DELIVERED_BY = "Delivered By"
ROLE_HANDOVER_TO = "Handover To"
ROLE_RECEIVED_BY = "Received By"
ROLE_PREPARED_BY = "Prepared By"
ROLE_CHECKED_BY = "Checked By"
ROLE_APPROVED_BY = "Approved By"
ROLE_STORE_KEEPER = "Store Keeper"
ROLE_RETURNED_BY = "Returned By"
ROLE_COUNTED_BY = "Counted By"
ROLE_VERIFIED_BY = "Verified By"

ALL_ROLES = [ROLE_ISSUED_BY, ROLE_DELIVERED_BY, ROLE_HANDOVER_TO, ROLE_RECEIVED_BY,
             ROLE_PREPARED_BY, ROLE_CHECKED_BY, ROLE_APPROVED_BY, ROLE_STORE_KEEPER,
             ROLE_RETURNED_BY, ROLE_COUNTED_BY, ROLE_VERIFIED_BY]

# The signature blocks printed on each document type, in order.
DEFAULT_BLOCKS: dict[str, list[str]] = {
    "DN": [ROLE_ISSUED_BY, ROLE_DELIVERED_BY, ROLE_HANDOVER_TO, ROLE_RECEIVED_BY],
    "GRN": [ROLE_RECEIVED_BY, ROLE_STORE_KEEPER, ROLE_CHECKED_BY, ROLE_APPROVED_BY],
    "RET": [ROLE_RETURNED_BY, ROLE_RECEIVED_BY, ROLE_STORE_KEEPER, ROLE_VERIFIED_BY],
    "TRF": [ROLE_ISSUED_BY, ROLE_DELIVERED_BY, ROLE_RECEIVED_BY, ROLE_APPROVED_BY],
    "ADJ": [ROLE_PREPARED_BY, ROLE_CHECKED_BY, ROLE_APPROVED_BY],
    "CNT": [ROLE_COUNTED_BY, ROLE_VERIFIED_BY, ROLE_STORE_KEEPER],
}


def list_signatories(db: Database, active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM signatories"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY name"
    return [dict(r) for r in db.query(sql)]


def save_signatory(db: Database, data: dict, sig_id: int | None = None) -> int:
    fields = ("name", "designation", "department", "role", "signature_path", "phone",
              "id_number", "email", "active")
    d = {k: v for k, v in data.items() if k in fields}
    if not d.get("name"):
        raise ValueError("A signatory needs a name.")
    if sig_id:
        sets = ", ".join(f"{k}=?" for k in d)
        db.execute(f"UPDATE signatories SET {sets} WHERE id=?", list(d.values()) + [sig_id])
        db.commit()
        db.audit("EDITED", "signatory", d.get("name", sig_id))
        return sig_id
    cols = ", ".join(d)
    qs = ", ".join("?" * len(d))
    cur = db.execute(f"INSERT INTO signatories({cols}) VALUES({qs})", list(d.values()))
    db.commit()
    db.audit("CREATED", "signatory", d["name"])
    return int(cur.lastrowid)


def delete_signatory(db: Database, sig_id: int) -> None:
    row = db.one("SELECT name FROM signatories WHERE id=?", (sig_id,))
    db.execute("UPDATE signatories SET active=0 WHERE id=?", (sig_id,))
    db.commit()
    db.audit("DELETED", "signatory", row["name"] if row else sig_id)


def get_signatory(db: Database, sig_id: int | None) -> dict | None:
    if not sig_id:
        return None
    r = db.one("SELECT * FROM signatories WHERE id=?", (sig_id,))
    return dict(r) if r else None


def find_signatory(db: Database, name: str) -> dict | None:
    if not name:
        return None
    r = db.one("SELECT * FROM signatories WHERE name=? AND active=1", (name.strip(),))
    return dict(r) if r else None


# --------------------------------------------------------- block config
def blocks_key(doc_type: str) -> str:
    return f"sig_blocks_{doc_type}"


def get_blocks(db: Database, doc_type: str) -> list[str]:
    raw = db.get_setting(blocks_key(doc_type))
    if raw:
        try:
            v = json.loads(raw)
            if isinstance(v, list) and v:
                return [str(x) for x in v]
        except json.JSONDecodeError:
            pass
    return list(DEFAULT_BLOCKS.get(doc_type, [ROLE_ISSUED_BY, ROLE_RECEIVED_BY]))


def set_blocks(db: Database, doc_type: str, roles: list[str]) -> None:
    db.set_setting(blocks_key(doc_type), json.dumps(list(roles)))


def default_key(doc_type: str, role: str) -> str:
    safe = role.replace(" ", "_").lower()
    return f"sig_default_{doc_type}_{safe}"


def get_default(db: Database, doc_type: str, role: str) -> dict | None:
    """The signatory pre-selected for this block, if the user configured one."""
    val = db.get_setting(default_key(doc_type, role))
    if not val:
        return None
    try:
        return get_signatory(db, int(val))
    except (TypeError, ValueError):
        return find_signatory(db, str(val))


def set_default(db: Database, doc_type: str, role: str, sig_id: int | None) -> None:
    db.set_setting(default_key(doc_type, role), sig_id or "")


def resolve_blocks(db: Database, doc_type: str, overrides: dict[str, dict] | None = None
                   ) -> list[dict]:
    """Signature blocks ready for printing.

    Returns [{role, name, designation, signature_path}] where each entry is the
    per-document override if given, else the configured default, else blank.
    """
    overrides = overrides or {}
    out = []
    for role in get_blocks(db, doc_type):
        ov = overrides.get(role) or {}
        if ov.get("name") or ov.get("signature_path"):
            entry = {"role": role, "name": ov.get("name", ""),
                     "designation": ov.get("designation", ""),
                     "signature_path": ov.get("signature_path", ""),
                     "id_number": ov.get("id_number", ""),
                     "phone": ov.get("phone", "")}
            if not entry["id_number"] or not entry["phone"]:
                known = find_signatory(db, entry["name"])
                if known:
                    entry["id_number"] = entry["id_number"] or known.get("id_number", "")
                    entry["phone"] = entry["phone"] or known.get("phone", "")
            out.append(entry)
            continue
        d = get_default(db, doc_type, role)
        if d:
            out.append({"role": role, "name": d["name"],
                        "designation": d.get("designation", ""),
                        "signature_path": (d.get("signature_path", "")
                                           if db.get_bool("print_signature_images", True)
                                           else ""),
                        "id_number": d.get("id_number", ""),
                        "phone": d.get("phone", "")})
        else:
            out.append({"role": role, "name": "", "designation": "",
                        "signature_path": "", "id_number": "", "phone": ""})
    return out


# ------------------------------------------------------- document layout
LAYOUT_DEFAULTS: dict[str, Any] = {
    "accent": "",              # blank = follow the application theme
    "header_color": "",
    "row_stripe": "1",
    "font_size": "7.6",
    "show_logo": "1",
    "show_pr_recap": "0",      # the PR summary table (removed from the DN by default)
    "show_value_column": "1",
    "show_attachments": "1",
    "signature_height": "18",
    "show_terms": "0",
    "terms_text": "",
    "footer_note": "",
    "orientation": "Portrait",
    "show_qr": "0",
    "header_band_color": "",     # blank = theme primary
    "header_band_color2": "",    # gradient end colour
    "header_style": "",          # blank = follow the global setting
    "show_extra_header": "0",    # extra header fields beyond the gate-pass set
    "signature_inline": "0",     # 0 = pin signatures to the bottom of the page
    "signature_caption": "Authorised Signatures",
    "merge_attachments": "1",    # append attachment pages after the document
}


def layout_key(doc_type: str, field: str) -> str:
    return f"doclayout_{doc_type}_{field}"


def get_layout(db: Database, doc_type: str) -> dict:
    out = dict(LAYOUT_DEFAULTS)
    for k in LAYOUT_DEFAULTS:
        v = db.get_setting(layout_key(doc_type, k))
        if v not in (None, ""):
            out[k] = str(v)
    # sensible per-type defaults
    if doc_type == "DN" and db.get_setting(layout_key(doc_type, "show_value_column")) is None:
        out["show_value_column"] = "0"
    return out


def save_layout(db: Database, doc_type: str, data: dict) -> None:
    for k, v in data.items():
        if k in LAYOUT_DEFAULTS:
            db.set_setting(layout_key(doc_type, k), v)
    db.audit("EDITED", "doc-layout", doc_type)


def layout_bool(layout: dict, key: str, default: bool = False) -> bool:
    v = layout.get(key, "1" if default else "0")
    return str(v) in ("1", "True", "true", "yes")
