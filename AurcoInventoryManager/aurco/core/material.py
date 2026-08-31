"""Material Request (MR) engine — the project-request side of the warehouse.

Workflow this implements:

    1. PASTE    project sends a material request list (Excel / ERP export)
    2. COMPARE  requested qty  vs  what is really available in the warehouse
                -> Full Available / Partial Available / Not Available / Not Found
    3. PREPARE  store team picks and prepares the material  (soft reservation)
    4. READY    prepared material waits for collection  (no Delivery Note yet)
    5. DELIVER  a Delivery Note is generated -> stock actually leaves the store

Stock is only deducted at step 5 (through the normal DN posting), so the
immutable ledger stays the single source of truth. Steps 3-4 hold a *soft
reservation* so two projects cannot be promised the same physical stock.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .database import Database, today
from . import services as S

# ----------------------------------------------------------------- statuses
FULL = "Full Available"
PARTIAL = "Partial Available"
NONE_AVAIL = "Not Available"
NOT_FOUND = "Item Not Found"

AVAIL_COLORS = {
    FULL: "#1a9c52",
    PARTIAL: "#e0a300",
    NONE_AVAIL: "#c92a2a",
    NOT_FOUND: "#7048e8",
}

PENDING = "Pending"
PREPARING = "Preparing"
PARTIAL_MARKED = "Partial Marked"
READY = "Ready"
PART_DELIVERED = "Partially Delivered"
DELIVERED = "Delivered"
CANCELLED = "Cancelled"

FULFIL_COLORS = {
    PENDING: "#6b7c8f",
    PREPARING: "#1098ad",
    PARTIAL_MARKED: "#e8590c",
    READY: "#0b7285",
    PART_DELIVERED: "#e0a300",
    DELIVERED: "#1a9c52",
    CANCELLED: "#c92a2a",
}

OPEN_STATES = (PENDING, PREPARING, PARTIAL_MARKED, READY, PART_DELIVERED)


# ------------------------------------------------------------------ parsing
# Header aliases -> canonical field. Matching is case/space/punctuation free.
HEADER_MAP = {
    "line": "line_no", "lineno": "line_no", "srno": "line_no", "sr": "line_no",
    "s": "line_no", "no": "line_no", "item": "item_code",
    "projectid": "project_id", "project": "project_id", "projectno": "project_id",
    "projectnumber": "project_id",
    "itemnumber": "item_code", "itemcode": "item_code", "itemno": "item_code",
    "materialcode": "item_code", "partnumber": "item_code", "code": "item_code",
    "procurementcategory": "procurement_category",
    "productname": "description", "itemname": "description", "description": "description",
    "materialdescription": "description", "itemdescription": "description",
    "unit": "uom", "uom": "uom", "unitofmeasure": "uom",
    "quantity": "qty", "qty": "qty", "requiredqty": "qty", "requestedqty": "qty",
    "reqqty": "qty",
    "status": "src_status",
    "category": "category",
    "purchaserequisitionreference": "pr_no", "purchaserequisition": "pr_no",
    "prreference": "pr_no", "prno": "pr_no", "pr": "pr_no", "prnumber": "pr_no",
    "requisition": "pr_no", "purchaserequisitionref": "pr_no",
    "remarks": "remarks", "remark": "remarks", "note": "remarks", "notes": "remarks",
    "requestedby": "requested_by", "department": "department", "site": "site",
}

CANON_LABELS = {
    "line_no": "Line", "project_id": "Project ID", "item_code": "Item number",
    "procurement_category": "Procurement category", "description": "Product name",
    "uom": "Unit", "qty": "Quantity", "src_status": "Status", "category": "Category",
    "pr_no": "Purchase requisition reference", "remarks": "Remarks",
    "requested_by": "Requested by", "department": "Department", "site": "Site",
}


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _num(v: Any) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(re.sub(r"[^\d.\-]", "", str(v)) or 0)
    except ValueError:
        return 0.0


def sniff_table(text: str) -> tuple[list[str], list[list[str]]]:
    """Split pasted clipboard text into (headers, rows).

    Handles Excel paste (tab separated), CSV and multi-space columns, with or
    without a header row.
    """
    raw = [ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
           if ln.strip()]
    if not raw:
        return [], []
    if "\t" in raw[0]:
        rows = [ln.split("\t") for ln in raw]
    elif raw[0].count(",") >= 2:
        rows = list(csv.reader(io.StringIO("\n".join(raw))))
    elif raw[0].count("|") >= 2:
        rows = [[c.strip() for c in ln.strip("|").split("|")] for ln in raw]
    else:
        rows = [re.split(r"\s{2,}", ln.strip()) for ln in raw]
    width = max(len(r) for r in rows)
    rows = [list(r) + [""] * (width - len(r)) for r in rows]

    head = [str(c).strip() for c in rows[0]]
    known = sum(1 for h in head if _norm(h) in HEADER_MAP)
    if known >= 2:
        return head, [[str(c).strip() for c in r] for r in rows[1:]]
    generic = [f"Column {i + 1}" for i in range(width)]
    return generic, [[str(c).strip() for c in r] for r in rows]


def auto_map(headers: list[str]) -> dict[str, int]:
    """Map canonical field -> column index, guessed from the header text."""
    out: dict[str, int] = {}
    for i, h in enumerate(headers):
        field_name = HEADER_MAP.get(_norm(h))
        if field_name and field_name not in out:
            out[field_name] = i
    return out


def parse_rows(headers: list[str], rows: list[list[str]],
               mapping: dict[str, int] | None = None) -> list[dict]:
    """Turn raw rows into request-line dicts using the column mapping."""
    m = mapping or auto_map(headers)
    out: list[dict] = []
    for r in rows:
        def val(f: str) -> str:
            i = m.get(f)
            if i is None or i >= len(r):
                return ""
            return str(r[i]).strip()

        code = val("item_code")
        desc = val("description")
        if not code and not desc:
            continue
        qty = _num(val("qty"))
        out.append({
            "line_no": val("line_no"), "project_id": val("project_id"),
            "item_code": code, "procurement_category": val("procurement_category"),
            "description": desc, "uom": val("uom"), "qty": qty,
            "src_status": val("src_status"), "category": val("category"),
            "pr_no": val("pr_no"), "remarks": val("remarks"),
        })
    return out


# -------------------------------------------------------------- reservation
def reserved_qty(db: Database, item_id: int, exclude_mr_id: int | None = None) -> float:
    """Qty already prepared for other open requests but not yet delivered."""
    sql = """SELECT COALESCE(SUM(MAX(l.qty_prepared - l.qty_delivered, 0)), 0)
             FROM mr_lines l JOIN material_requests m ON m.id = l.mr_id
             WHERE l.item_id = ? AND l.status IN ('Preparing','Ready','Partially Delivered')
               AND m.status <> 'Cancelled'"""
    p: list[Any] = [item_id]
    if exclude_mr_id:
        sql += " AND l.mr_id <> ?"
        p.append(exclude_mr_id)
    return float(db.scalar(sql, p) or 0)


def availability(db: Database, item_id: int, exclude_mr_id: int | None = None) -> dict:
    """on_hand / reserved / available-to-promise for one item."""
    on_hand = float(db.scalar("SELECT balance FROM items WHERE id=?", (item_id,)) or 0)
    res = reserved_qty(db, item_id, exclude_mr_id)
    return {"on_hand": on_hand, "reserved": res, "available": max(0.0, on_hand - res)}


def avail_status(requested: float, available: float, found: bool = True) -> str:
    if not found:
        return NOT_FOUND
    if requested <= 0:
        return FULL
    if available <= 0:
        return NONE_AVAIL
    if available + 1e-9 >= requested:
        return FULL
    return PARTIAL


def enrich(db: Database, lines: list[dict], exclude_mr_id: int | None = None) -> list[dict]:
    """Attach live stock figures + availability status to parsed request lines."""
    # aggregate demand per item so two lines of the same item don't both claim it
    claimed: dict[int, float] = {}
    out = []
    for ln in lines:
        row = dict(ln)
        it = S.find_by_barcode(db, row.get("item_code", "")) if row.get("item_code") else None
        if it is None and row.get("description"):
            hit = db.one("SELECT * FROM items WHERE description=? AND active=1",
                         (row["description"],))
            it = dict(hit) if hit else None
        if it is None:
            row.update({"item_id": None, "found": False, "on_hand": 0.0, "reserved": 0.0,
                        "available": 0.0, "short": row.get("qty", 0.0),
                        "avail_status": NOT_FOUND, "stock_status": "",
                        "warehouse": "", "location": "", "rack": "", "unit_cost": 0.0})
            out.append(row)
            continue
        a = availability(db, it["id"], exclude_mr_id)
        already = claimed.get(it["id"], 0.0)
        free = max(0.0, a["available"] - already)
        need = float(row.get("qty") or 0)
        take = min(need, free)
        claimed[it["id"]] = already + take
        row.update({
            "item_id": it["id"], "found": True,
            "item_code": it["code"],
            "description": row.get("description") or it["description"],
            "system_description": it["description"],
            "uom": row.get("uom") or it["uom"],
            "category": row.get("category") or it["category"],
            "on_hand": a["on_hand"], "reserved": a["reserved"] + already,
            "available": free, "short": max(0.0, need - free),
            "avail_status": avail_status(need, free),
            "stock_status": S.stock_status(db, it),
            "warehouse": it["warehouse"], "location": it["location"], "rack": it["rack"],
            "unit_cost": float(it["unit_cost"] or 0),
        })
        out.append(row)
    return out


def summarize(lines: list[dict]) -> dict:
    tot = len(lines)
    full = sum(1 for l in lines if l["avail_status"] == FULL)
    part = sum(1 for l in lines if l["avail_status"] == PARTIAL)
    none = sum(1 for l in lines if l["avail_status"] == NONE_AVAIL)
    nf = sum(1 for l in lines if l["avail_status"] == NOT_FOUND)
    req = sum(float(l.get("qty") or 0) for l in lines)
    can = sum(min(float(l.get("qty") or 0), float(l.get("available") or 0)) for l in lines)
    return {"lines": tot, "full": full, "partial": part, "none": none, "not_found": nf,
            "req_qty": req, "can_supply": can, "short_qty": max(0.0, req - can),
            "value": sum(min(float(l.get("qty") or 0), float(l.get("available") or 0)) *
                         float(l.get("unit_cost") or 0) for l in lines),
            "overall": (FULL if tot and full == tot else
                        (NONE_AVAIL if can <= 0 else PARTIAL))}


# ----------------------------------------------------------------- persistence
def save_request(db: Database, header: dict, lines: list[dict],
                 mr_id: int | None = None) -> str:
    """Create or update a material request. Returns the MR number."""
    if not lines:
        raise S.StockError("The request has no item lines.")
    try:
        if mr_id:
            mr_no = db.scalar("SELECT mr_no FROM material_requests WHERE id=?", (mr_id,),
                              default="")
            db.execute("""UPDATE material_requests SET mr_date=?, project_id=?, site=?,
                            department=?, requested_by=?, reference=?, pr_no=?, remarks=?
                          WHERE id=?""",
                       (header.get("mr_date") or today(), header.get("project_id", ""),
                        header.get("site", ""), header.get("department", ""),
                        header.get("requested_by", ""), header.get("reference", ""),
                        header.get("pr_no", ""), header.get("remarks", ""), mr_id))
            db.execute("DELETE FROM mr_lines WHERE mr_id=? AND qty_prepared=0 AND qty_delivered=0",
                       (mr_id,))
        else:
            mr_no = db.next_doc_number("MR", commit=False)
            cur = db.execute(
                """INSERT INTO material_requests(mr_no,mr_date,project_id,site,department,
                     requested_by,reference,pr_no,status,remarks,created_by)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (mr_no, header.get("mr_date") or today(), header.get("project_id", ""),
                 header.get("site", ""), header.get("department", ""),
                 header.get("requested_by", ""), header.get("reference", ""),
                 header.get("pr_no", ""), PENDING, header.get("remarks", ""),
                 db.current_user))
            mr_id = int(cur.lastrowid)
        for i, ln in enumerate(lines, 1):
            db.execute(
                """INSERT INTO mr_lines(mr_id,line_no,item_id,item_code,description,uom,
                     category,procurement_category,project_id,pr_no,qty_requested,
                     qty_prepared,qty_delivered,status,avail_snapshot,remarks)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?)""",
                (mr_id, ln.get("line_no") or i, ln.get("item_id"),
                 ln.get("item_code", ""), ln.get("description", ""), ln.get("uom", ""),
                 ln.get("category", ""), ln.get("procurement_category", ""),
                 ln.get("project_id", ""), ln.get("pr_no", ""),
                 float(ln.get("qty") or 0), PENDING, ln.get("avail_status", ""),
                 ln.get("remarks", "")))
        _refresh_status(db, mr_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.audit("CREATED" if not header.get("_edit") else "EDITED", "MR", mr_no,
             f"{len(lines)} line(s)")
    return mr_no


def _refresh_status(db: Database, mr_id: int) -> str:
    rows = db.query("SELECT status, qty_requested, qty_prepared, qty_delivered"
                    " FROM mr_lines WHERE mr_id=?", (mr_id,))
    if not rows:
        status = PENDING
    elif all(r["status"] == CANCELLED for r in rows):
        status = CANCELLED
    else:
        live = [r for r in rows if r["status"] != CANCELLED]
        if all(r["status"] == DELIVERED for r in live):
            status = DELIVERED
        elif any(r["qty_delivered"] > 0 for r in live):
            status = PART_DELIVERED
        elif live and all(r["status"] == READY for r in live):
            status = READY
        elif any(r["status"] == PARTIAL_MARKED for r in live):
            status = PARTIAL_MARKED
        elif any(r["status"] in (PREPARING, READY) for r in live):
            status = PREPARING
        else:
            status = PENDING
    db.execute("UPDATE material_requests SET status=? WHERE id=?", (status, mr_id))
    return status


def _line_status(qty_req: float, prepared: float, delivered: float, current: str,
                 available: float | None = None) -> str:
    """Status of one request line.

    `available` is the free stock that *could* have been prepared. When a line
    is only partly prepared even though the warehouse could have covered it in
    full, that is a deliberate decision by the storekeeper rather than a
    shortage, and it is reported as PARTIAL_MARKED so the two cases can be told
    apart at a glance:

        partial because stock is short   -> Preparing   (waiting for stock)
        partial although stock was there -> Partial Marked (chosen)
    """
    if current == CANCELLED:
        return CANCELLED
    if delivered >= qty_req - 1e-9 and delivered > 0:
        return DELIVERED
    if delivered > 0:
        return PART_DELIVERED
    if prepared >= qty_req - 1e-9 and prepared > 0:
        return READY
    if prepared > 0:
        if available is not None and available >= qty_req - 1e-9:
            return PARTIAL_MARKED
        return PREPARING
    return PENDING


def set_prepared(db: Database, line_id: int, qty: float, remarks: str = "") -> None:
    """Record how much the store team has physically prepared (soft reservation)."""
    ln = db.one("SELECT * FROM mr_lines WHERE id=?", (line_id,))
    if ln is None:
        raise S.StockError("Request line not found.")
    qty = max(0.0, float(qty))
    if qty < ln["qty_delivered"]:
        raise S.StockError("Prepared quantity cannot be less than what is already delivered.")
    ceiling = 0.0
    if ln["item_id"]:
        a = availability(db, ln["item_id"], exclude_mr_id=ln["mr_id"])
        own = float(db.scalar("""SELECT COALESCE(SUM(MAX(qty_prepared-qty_delivered,0)),0)
                                 FROM mr_lines WHERE mr_id=? AND item_id=? AND id<>?""",
                              (ln["mr_id"], ln["item_id"], line_id)) or 0)
        ceiling = a["available"] - own
        if qty - float(ln["qty_delivered"]) > ceiling + 1e-9 and \
                not db.get_bool("allow_negative_stock"):
            raise S.StockError(
                f"Only {max(0.0, ceiling):g} available to prepare for {ln['item_code']}.\n\n"
                f"On hand {a['on_hand']:g}, already reserved for other requests "
                f"{a['reserved']:g}.")
    # `could_supply` is what the warehouse could have given this line in full,
    # i.e. free stock plus whatever this line already holds reserved.
    could_supply = None
    if ln["item_id"]:
        could_supply = max(0.0, ceiling) + float(ln["qty_delivered"])
    status = _line_status(ln["qty_requested"], qty, ln["qty_delivered"],
                          ln["status"], could_supply)
    db.execute("""UPDATE mr_lines SET qty_prepared=?, status=?,
                    prepared_by=?, prepared_at=datetime('now','localtime'),
                    remarks=CASE WHEN ?<>'' THEN ? ELSE remarks END
                  WHERE id=?""",
               (qty, status, db.current_user, remarks, remarks, line_id))
    _refresh_status(db, ln["mr_id"])
    db.commit()


def prepare_all_available(db: Database, mr_id: int) -> int:
    """One click: prepare every line up to whatever the warehouse can supply."""
    n = 0
    for ln in db.query("SELECT * FROM mr_lines WHERE mr_id=? AND status IN"
                       " ('Pending','Preparing','Partial Marked')", (mr_id,)):
        if not ln["item_id"]:
            continue
        a = availability(db, ln["item_id"], exclude_mr_id=mr_id)
        own = float(db.scalar("""SELECT COALESCE(SUM(MAX(qty_prepared-qty_delivered,0)),0)
                                 FROM mr_lines WHERE mr_id=? AND item_id=? AND id<>?""",
                              (mr_id, ln["item_id"], ln["id"])) or 0)
        can = max(0.0, min(float(ln["qty_requested"]), a["available"] - own))
        if can > 0:
            set_prepared(db, ln["id"], can)
            n += 1
    return n


def process_lines(db: Database, line_ids: list[int]) -> dict:
    """Move request lines into *Ready to Deliver* in one action.

    This is what the **Process** button does. For each selected line:

      · if the storekeeper has already marked a prepared quantity, that figure
        is respected exactly — the line is simply confirmed as ready;
      · otherwise the line is prepared with whatever the warehouse can supply
        right now, capped at the outstanding quantity;
      · a line already fully delivered, cancelled, or not in the Item Master is
        skipped and reported rather than silently ignored.

    Nothing leaves the warehouse here: this is still the soft reservation, so
    stock is only deducted later when the Delivery Note is created.

    Returns a summary the UI can show verbatim.
    """
    res: dict[str, Any] = {"ready": 0, "kept": 0, "prepared": 0, "qty": 0.0,
                           "skipped": [], "short": [], "lines": []}
    for lid in line_ids:
        ln = db.one("SELECT * FROM mr_lines WHERE id=?", (lid,))
        if ln is None:
            continue
        label = ln["item_code"] or (ln["description"] or "")[:28] or f"line {lid}"
        if ln["status"] == CANCELLED:
            res["skipped"].append(f"{label}: cancelled")
            continue
        requested = float(ln["qty_requested"] or 0)
        delivered = float(ln["qty_delivered"] or 0)
        marked = float(ln["qty_prepared"] or 0)
        outstanding = requested - delivered
        if outstanding <= 1e-9:
            res["skipped"].append(f"{label}: already delivered in full")
            continue
        if not ln["item_id"]:
            res["skipped"].append(f"{label}: not in the Item Master — link or "
                                  "create the item first")
            continue

        # already marked by hand -> take that quantity as-is
        if marked - delivered > 1e-9:
            res["kept"] += 1
            res["ready"] += 1
            res["qty"] += marked - delivered
            res["lines"].append((label, marked - delivered, "marked"))
            if marked < requested - 1e-9:
                res["short"].append(
                    f"{label}: {marked:g} of {requested:g} marked")
            continue

        # nothing marked -> give it whatever is genuinely free
        a = availability(db, ln["item_id"], exclude_mr_id=ln["mr_id"])
        own = float(db.scalar(
            """SELECT COALESCE(SUM(MAX(qty_prepared-qty_delivered,0)),0)
                 FROM mr_lines WHERE mr_id=? AND item_id=? AND id<>?""",
            (ln["mr_id"], ln["item_id"], lid)) or 0)
        can = max(0.0, min(outstanding, a["available"] - own))
        if can <= 1e-9:
            res["skipped"].append(
                f"{label}: nothing available (on hand {a['on_hand']:g}, "
                f"reserved elsewhere {a['reserved']:g})")
            continue
        set_prepared(db, lid, delivered + can)
        res["prepared"] += 1
        res["ready"] += 1
        res["qty"] += can
        res["lines"].append((label, can, "available"))
        if can < outstanding - 1e-9:
            res["short"].append(f"{label}: {can:g} of {outstanding:g} available")
    return res


def process_request(db: Database, mr_id: int) -> dict:
    """Process every open line of one request."""
    ids = [r["id"] for r in db.query(
        "SELECT id FROM mr_lines WHERE mr_id=? AND status<>?", (mr_id, CANCELLED))]
    return process_lines(db, ids)


def cancel_line(db: Database, line_id: int, reason: str = "") -> None:
    ln = db.one("SELECT * FROM mr_lines WHERE id=?", (line_id,))
    if ln is None:
        return
    if ln["qty_delivered"] > 0:
        raise S.StockError("A line that is already delivered cannot be cancelled.")
    db.execute("UPDATE mr_lines SET status=?, qty_prepared=0, remarks=? WHERE id=?",
               (CANCELLED, (ln["remarks"] or "") + f" [cancelled: {reason}]", line_id))
    _refresh_status(db, ln["mr_id"])
    db.commit()
    db.audit("EDITED", "MR-line", ln["item_code"], f"cancelled: {reason}")


def cancel_request(db: Database, mr_id: int, reason: str) -> None:
    mr = db.one("SELECT mr_no FROM material_requests WHERE id=?", (mr_id,))
    db.execute("UPDATE mr_lines SET status=?, qty_prepared=0 WHERE mr_id=? AND qty_delivered=0",
               (CANCELLED, mr_id))
    db.execute("UPDATE material_requests SET status=?, remarks=COALESCE(remarks,'')||? WHERE id=?",
               (CANCELLED, f" [cancelled: {reason}]", mr_id))
    db.commit()
    db.audit("DELETED", "MR", mr["mr_no"] if mr else mr_id, f"cancelled: {reason}")


def can_delete_request(db: Database, mr_id: int) -> tuple[bool, str]:
    """May this request be deleted outright?

    A request that has already delivered stock is part of the audit chain: the
    Delivery Note and its ledger rows reference it, so it must be *cancelled*
    (kept, marked Cancelled) rather than erased. Everything else can go.
    """
    row = db.one("SELECT COALESCE(SUM(qty_delivered),0) d, COUNT(*) n"
                 " FROM mr_lines WHERE mr_id=?", (mr_id,))
    delivered = float(row["d"] or 0) if row else 0.0
    if delivered > 0:
        return False, (f"{delivered:g} unit(s) have already been delivered against this "
                       "request. Delivered history cannot be erased — cancel the request "
                       "instead, which keeps it for the audit trail.")
    return True, ""


def delete_request(db: Database, mr_id: int, force: bool = False) -> str:
    """Permanently remove a request and its lines.

    Any soft reservation the request held is released automatically, because the
    reservation is derived from `mr_lines` rather than stored on the item.
    """
    mr = db.one("SELECT mr_no FROM material_requests WHERE id=?", (mr_id,))
    if mr is None:
        raise S.StockError("That material request no longer exists.")
    ok, why = can_delete_request(db, mr_id)
    if not ok and not force:
        raise S.StockError(why)
    n = db.scalar("SELECT COUNT(*) FROM mr_lines WHERE mr_id=?", (mr_id,))
    try:
        db.execute("DELETE FROM mr_lines WHERE mr_id=?", (mr_id,))
        db.execute("DELETE FROM material_requests WHERE id=?", (mr_id,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.audit("DELETED", "MR", mr["mr_no"], f"request deleted with {n} line(s)")
    return mr["mr_no"]


def delete_requests(db: Database, mr_ids: list[int], force: bool = False
                    ) -> tuple[list[str], list[str]]:
    """Bulk delete. Returns (deleted_numbers, skipped_messages)."""
    done: list[str] = []
    skipped: list[str] = []
    for mid in mr_ids:
        try:
            done.append(delete_request(db, mid, force))
        except S.StockError as exc:
            no = db.scalar("SELECT mr_no FROM material_requests WHERE id=?", (mid,),
                           default=str(mid))
            skipped.append(f"{no}: {exc}")
    return done, skipped


def delete_line(db: Database, line_id: int, force: bool = False) -> None:
    """Remove a single request line completely (releases its reservation)."""
    ln = db.one("SELECT * FROM mr_lines WHERE id=?", (line_id,))
    if ln is None:
        return
    if float(ln["qty_delivered"] or 0) > 0 and not force:
        raise S.StockError("This line has already been delivered — cancel it instead "
                           "so the delivery history is preserved.")
    mr_id = ln["mr_id"]
    db.execute("DELETE FROM mr_lines WHERE id=?", (line_id,))
    if db.scalar("SELECT COUNT(*) FROM mr_lines WHERE mr_id=?", (mr_id,)):
        _refresh_status(db, mr_id)
    db.commit()
    db.audit("DELETED", "MR-line", ln["item_code"], "line removed from the request")


def delete_lines(db: Database, line_ids: list[int], force: bool = False
                 ) -> tuple[int, list[str]]:
    """Bulk-remove request lines. Returns (deleted, skipped_messages).

    A line that has already been delivered is protected: erasing it would break
    the link between the Delivery Note, the ledger and the request. Those are
    reported back so the caller can tell the user exactly what was kept.
    """
    done = 0
    skipped: list[str] = []
    touched: set[int] = set()
    for lid in line_ids:
        ln = db.one("SELECT * FROM mr_lines WHERE id=?", (lid,))
        if ln is None:
            continue
        if float(ln["qty_delivered"] or 0) > 0 and not force:
            skipped.append(f"{ln['item_code'] or ln['description']}: "
                           f"{ln['qty_delivered']:g} already delivered — cancel it "
                           "instead so the history is preserved.")
            continue
        touched.add(ln["mr_id"])
        db.execute("DELETE FROM mr_lines WHERE id=?", (lid,))
        done += 1
    for mr_id in touched:
        if db.scalar("SELECT COUNT(*) FROM mr_lines WHERE mr_id=?", (mr_id,)):
            _refresh_status(db, mr_id)
    if done:
        db.commit()
        db.audit("DELETED", "MR-line", "", f"{done} line(s) removed in bulk")
    return done, skipped


def empty_requests(db: Database) -> list[dict]:
    """Requests left with no lines at all — usually after a bulk line delete."""
    return [dict(r) for r in db.query(
        "SELECT * FROM material_requests m WHERE NOT EXISTS"
        " (SELECT 1 FROM mr_lines l WHERE l.mr_id = m.id)")]


def restore_request(db: Database, mr_id: int) -> None:
    """Undo a cancellation — puts the request and its lines back in play."""
    db.execute("UPDATE mr_lines SET status=? WHERE mr_id=? AND status=?",
               (PENDING, mr_id, CANCELLED))
    _refresh_status(db, mr_id)
    db.commit()
    no = db.scalar("SELECT mr_no FROM material_requests WHERE id=?", (mr_id,), default="")
    db.audit("EDITED", "MR", no, "cancellation reversed")


def restore_line(db: Database, line_id: int) -> None:
    """Undo a cancelled line."""
    ln = db.one("SELECT mr_id, item_code FROM mr_lines WHERE id=?", (line_id,))
    if ln is None:
        return
    db.execute("UPDATE mr_lines SET status=? WHERE id=?", (PENDING, line_id))
    _refresh_status(db, ln["mr_id"])
    db.commit()
    db.audit("EDITED", "MR-line", ln["item_code"], "cancellation reversed")


# --------------------------------------------------------- ready for delivery
def ready_lines(db: Database, project: str = "", mr_no: str = "",
                pr_no: str = "") -> list[dict]:
    """Prepared material still waiting for a Delivery Note."""
    sql = """SELECT l.*, m.mr_no, m.mr_date, m.project_id AS mr_project, m.site,
                    m.department, m.requested_by, m.reference,
                    (l.qty_prepared - l.qty_delivered) AS qty_ready
             FROM mr_lines l JOIN material_requests m ON m.id = l.mr_id
             WHERE l.status IN ('Ready','Preparing','Partial Marked',
                                'Partially Delivered')
               AND (l.qty_prepared - l.qty_delivered) > 0
               AND m.status <> 'Cancelled'"""
    p: list[Any] = []
    if project:
        sql += " AND (m.project_id LIKE ? OR l.project_id LIKE ? OR m.site LIKE ?)"
        p += [f"%{project}%"] * 3
    if mr_no:
        sql += " AND m.mr_no LIKE ?"
        p.append(f"%{mr_no}%")
    if pr_no:
        sql += " AND l.pr_no LIKE ?"
        p.append(f"%{pr_no}%")
    sql += " ORDER BY m.mr_date, m.mr_no, l.line_no"
    return [dict(r) for r in db.query(sql, p)]


def deliver_lines(db: Database, line_ids: list[int], header: S.DocHeader) -> str:
    """Turn prepared MR lines into a real Delivery Note (stock leaves here)."""
    if not line_ids:
        raise S.StockError("Select at least one prepared line to deliver.")
    rows = db.query(
        f"""SELECT l.*, m.mr_no, m.project_id AS mr_project, m.site, m.department,
                   m.requested_by
            FROM mr_lines l JOIN material_requests m ON m.id=l.mr_id
            WHERE l.id IN ({','.join('?' * len(line_ids))})""", line_ids)
    dn_lines: list[S.Line] = []
    for r in rows:
        qty = float(r["qty_prepared"]) - float(r["qty_delivered"])
        if qty <= 0:
            continue
        if not r["item_id"]:
            raise S.StockError(f"{r['item_code']} is not in the Item Master — "
                               "create the item before delivering it.")
        dn_lines.append(S.Line(item_id=r["item_id"], qty=qty, pr_no=r["pr_no"] or "",
                               remarks=(r["remarks"] or "")[:60]))
    if not dn_lines:
        raise S.StockError("Nothing left to deliver on the selected lines.")

    first = rows[0]
    header.doc_type = "DN"
    header.project = header.project or first["mr_project"] or first["site"] or ""
    header.department = header.department or first["department"] or ""
    header.requested_by = header.requested_by or first["requested_by"] or ""
    mrs = sorted({r["mr_no"] for r in rows})
    header.reference = header.reference or ", ".join(mrs)
    dn_no = S.post_issue(db, header, dn_lines)

    doc_id = db.scalar("SELECT id FROM documents WHERE doc_type='DN' AND doc_no=?", (dn_no,))
    for r in rows:
        qty = float(r["qty_prepared"]) - float(r["qty_delivered"])
        if qty <= 0:
            continue
        delivered = float(r["qty_delivered"]) + qty
        status = _line_status(r["qty_requested"], r["qty_prepared"], delivered, r["status"])
        db.execute("""UPDATE mr_lines SET qty_delivered=?, status=?, dn_no=?,
                        delivered_at=datetime('now','localtime') WHERE id=?""",
                   (delivered, status, dn_no, r["id"]))
    for mr_id in {r["mr_id"] for r in rows}:
        _refresh_status(db, mr_id)
    db.commit()
    db.audit("ISSUED", "MR", ", ".join(mrs), f"delivered via {dn_no}")
    return dn_no


# ------------------------------------------------------------------ queries
def list_requests(db: Database, status: str = "", text: str = "",
                  date_from: str = "", date_to: str = "",
                  exclude_status: Sequence[str] = ()) -> list[dict]:
    sql = """SELECT m.*,
                (SELECT COUNT(*) FROM mr_lines l WHERE l.mr_id=m.id) AS n_lines,
                (SELECT COALESCE(SUM(qty_requested),0) FROM mr_lines l WHERE l.mr_id=m.id) AS q_req,
                (SELECT COALESCE(SUM(qty_prepared),0) FROM mr_lines l WHERE l.mr_id=m.id) AS q_prep,
                (SELECT COALESCE(SUM(qty_delivered),0) FROM mr_lines l WHERE l.mr_id=m.id) AS q_del
             FROM material_requests m WHERE 1=1"""
    p: list[Any] = []
    if status:
        sql += " AND m.status=?"
        p.append(status)
    if exclude_status:
        # used by the Requests & Preparation screen so a request that is fully
        # ready disappears from the working list (it now lives on tab 3)
        sql += " AND m.status NOT IN (%s)" % ",".join("?" * len(exclude_status))
        p += list(exclude_status)
    if text:
        like = f"%{text}%"
        sql += (" AND (m.mr_no LIKE ? OR m.project_id LIKE ? OR m.site LIKE ?"
                " OR m.requested_by LIKE ? OR m.reference LIKE ? OR m.pr_no LIKE ?"
                " OR m.id IN (SELECT mr_id FROM mr_lines WHERE item_code LIKE ?"
                "             OR description LIKE ? OR pr_no LIKE ?))")
        p += [like] * 9
    if date_from:
        sql += " AND m.mr_date>=?"
        p.append(date_from)
    if date_to:
        sql += " AND m.mr_date<=?"
        p.append(date_to)
    sql += " ORDER BY m.id DESC"
    return [dict(r) for r in db.query(sql, p)]


def request_lines(db: Database, mr_id: int, live: bool = True) -> list[dict]:
    """Lines of one request, refreshed against current stock."""
    rows = [dict(r) for r in db.query(
        "SELECT * FROM mr_lines WHERE mr_id=? ORDER BY CAST(line_no AS INTEGER), id", (mr_id,))]
    for r in rows:
        r["qty"] = r["qty_requested"]
        r["pending"] = max(0.0, r["qty_requested"] - r["qty_delivered"])
        r["ready_qty"] = max(0.0, r["qty_prepared"] - r["qty_delivered"])
        if live and r["item_id"]:
            a = availability(db, r["item_id"], exclude_mr_id=mr_id)
            own = float(db.scalar(
                """SELECT COALESCE(SUM(MAX(qty_prepared-qty_delivered,0)),0) FROM mr_lines
                   WHERE mr_id=? AND item_id=? AND id<>?""",
                (mr_id, r["item_id"], r["id"])) or 0)
            r.update({"on_hand": a["on_hand"], "reserved": a["reserved"] + own,
                      "available": max(0.0, a["available"] - own)})
            outstanding = max(0.0, r["qty_requested"] - r["qty_prepared"])
            r["short"] = max(0.0, outstanding - r["available"])
            r["avail_status"] = avail_status(
                r["qty_requested"], r["available"] + r["qty_prepared"])
            it = db.one("SELECT * FROM items WHERE id=?", (r["item_id"],))
            if it:
                r["warehouse"], r["location"], r["rack"] = (it["warehouse"], it["location"],
                                                            it["rack"])
                r["unit_cost"] = float(it["unit_cost"] or 0)
                r["stock_status"] = S.stock_status(db, it)
        else:
            r.update({"on_hand": 0.0, "reserved": 0.0, "available": 0.0,
                      "short": r["qty_requested"], "avail_status": NOT_FOUND,
                      "warehouse": "", "location": "", "rack": "", "unit_cost": 0.0,
                      "stock_status": ""})
    return rows


def link_item(db: Database, line_id: int, item_id: int) -> None:
    """Map an unrecognised request code onto an existing item."""
    it = db.one("SELECT * FROM items WHERE id=?", (item_id,))
    if it is None:
        raise S.StockError("Item not found.")
    db.execute("UPDATE mr_lines SET item_id=?, item_code=?, uom=COALESCE(NULLIF(uom,''),?)"
               " WHERE id=?", (item_id, it["code"], it["uom"], line_id))
    db.commit()
    db.audit("EDITED", "MR-line", it["code"], "linked to item master")


def create_item_from_line(db: Database, line_id: int) -> int:
    """Create a new Item Master record straight from an unmatched request line."""
    ln = db.one("SELECT * FROM mr_lines WHERE id=?", (line_id,))
    if ln is None:
        raise S.StockError("Line not found.")
    if db.one("SELECT 1 FROM items WHERE code=?", (ln["item_code"],)):
        raise S.StockError(f"Item code {ln['item_code']} already exists.")
    item_id = S.save_item(db, {
        "code": ln["item_code"] or db.next_item_code(),
        "description": ln["description"] or ln["item_code"],
        "uom": ln["uom"] or db.get_setting("default_uom", "PCS"),
        "category": ln["category"] or ln["procurement_category"] or "",
        "subcategory": ln["procurement_category"] or "",
        "opening_balance": 0,
    })
    link_item(db, line_id, item_id)
    return item_id


def create_items_from_lines(db: Database, line_ids: list[int],
                            overrides: dict[int, dict] | None = None,
                            defaults: dict | None = None) -> dict:
    """Add several request lines to the Item Master in one pass.

    `overrides` is keyed by line id and may carry per-item values the operator
    typed in the bulk dialog — most importantly `opening_balance`, but also
    code, description, uom, category, unit_cost, warehouse, location and the
    min/max levels.

    An opening balance is posted through the normal stock engine, so it lands in
    the immutable ledger as an OPENING row rather than being written straight
    onto the balance. That keeps `items.balance` reconcilable with the ledger,
    which is the guarantee the whole system rests on.

    Returns a per-line summary so the caller can report exactly what happened;
    a line that cannot be created never aborts the rest.
    """
    overrides = overrides or {}
    defaults = defaults or {}
    res: dict[str, Any] = {"created": 0, "linked": 0, "skipped": [], "items": [],
                           "qty": 0.0}
    for lid in line_ids:
        ln = db.one("SELECT * FROM mr_lines WHERE id=?", (lid,))
        if ln is None:
            continue
        ov = dict(defaults)
        ov.update(overrides.get(lid, {}))
        label = ln["item_code"] or (ln["description"] or "")[:30] or f"line {lid}"

        if ln["item_id"]:
            res["skipped"].append(f"{label}: already linked to an item")
            continue
        code = str(ov.get("code") or ln["item_code"] or "").strip()
        if not code:
            code = db.next_item_code()
        existing = db.one("SELECT id, code FROM items WHERE code=?", (code,))
        if existing:
            # the item is already in the master -- link rather than duplicate
            link_item(db, lid, existing["id"])
            res["linked"] += 1
            res["skipped"].append(f"{label}: code {code} already exists — linked "
                                  "to the existing item instead")
            continue
        try:
            qty = float(ov.get("opening_balance") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        data = {
            "code": code,
            "description": (ov.get("description") or ln["description"]
                            or code),
            "uom": ov.get("uom") or ln["uom"] or db.get_setting("default_uom", "PCS"),
            "category": (ov.get("category") or ln["category"]
                         or ln["procurement_category"] or ""),
            "subcategory": ov.get("subcategory") or ln["procurement_category"] or "",
            "warehouse": ov.get("warehouse", ""),
            "location": ov.get("location", ""),
            "unit_cost": float(ov.get("unit_cost") or 0),
            "min_level": float(ov.get("min_level") or 0),
            "max_level": float(ov.get("max_level") or 0),
            "remarks": ov.get("remarks", f"Created from {ln['item_code'] or 'MR line'}"),
            "opening_balance": qty,
        }
        try:
            item_id = S.save_item(db, data)
        except Exception as exc:  # noqa: BLE001
            res["skipped"].append(f"{label}: {exc}")
            continue
        link_item(db, lid, item_id)
        res["created"] += 1
        res["qty"] += qty
        res["items"].append({"id": item_id, "code": code, "qty": qty})
    if res["created"] or res["linked"]:
        db.commit()
        db.audit("CREATED", "items", "",
                 f"{res['created']} item(s) created from request lines, "
                 f"{res['linked']} linked to existing items")
    return res


def unlinked_lines(db: Database, mr_id: int) -> list[dict]:
    """Request lines that are not in the Item Master yet."""
    return [dict(r) for r in db.query(
        "SELECT * FROM mr_lines WHERE mr_id=? AND item_id IS NULL"
        " AND status<>? ORDER BY line_no, id", (mr_id, CANCELLED))]


def dashboard_counts(db: Database) -> dict:
    return {
        "open_requests": db.scalar(
            "SELECT COUNT(*) FROM material_requests WHERE status IN "
            "('Pending','Preparing','Ready','Partially Delivered')"),
        "ready_lines": db.scalar(
            """SELECT COUNT(*) FROM mr_lines l JOIN material_requests m ON m.id=l.mr_id
               WHERE (l.qty_prepared-l.qty_delivered)>0 AND m.status<>'Cancelled'"""),
        "ready_qty": db.scalar(
            """SELECT COALESCE(SUM(l.qty_prepared-l.qty_delivered),0) FROM mr_lines l
               JOIN material_requests m ON m.id=l.mr_id
               WHERE (l.qty_prepared-l.qty_delivered)>0 AND m.status<>'Cancelled'"""),
        # still to be prepared, including the remainder of part-delivered lines
        "pending_qty": db.scalar(
            """SELECT COALESCE(SUM(MAX(l.qty_requested-l.qty_prepared,0)),0) FROM mr_lines l
               JOIN material_requests m ON m.id=l.mr_id
               WHERE l.status IN ('Pending','Preparing','Ready','Partially Delivered')
                 AND m.status<>'Cancelled'"""),
        "shortage_lines": db.scalar(
            """SELECT COUNT(*) FROM mr_lines l JOIN material_requests m ON m.id=l.mr_id
               WHERE l.qty_requested > l.qty_prepared AND l.status<>'Cancelled'
                 AND m.status<>'Cancelled'"""),
    }
