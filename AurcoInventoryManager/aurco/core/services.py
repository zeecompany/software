"""Business logic: transaction-based stock engine, alerts, dashboard, search.

Golden rule: item balances are NEVER overwritten blindly. Every change writes an
immutable `stock_ledger` row and the item balance is moved by the same delta,
inside one SQLite transaction.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any

from .database import Database, today
from . import file_search as FS

# ------------------------------------------------------------------ statuses
NORMAL, WARNING, CRITICAL, OUT = "Normal", "Warning", "Critical", "Out of Stock"
STATUS_COLORS = {
    NORMAL: "#1a9c52",
    WARNING: "#e0a300",
    CRITICAL: "#e8590c",
    OUT: "#c92a2a",
}


class StockError(Exception):
    """Raised for any business-rule violation (shown as a friendly message)."""


@dataclass
class Line:
    item_id: int
    qty: float
    unit_cost: float = 0.0
    remarks: str = ""
    condition: str = "USABLE"
    batch: str = ""
    location: str = ""
    issued_qty: float = 0.0
    counted_qty: float = 0.0
    system_qty: float = 0.0
    pr_no: str = ""


@dataclass
class DocHeader:
    doc_type: str
    doc_date: str = field(default_factory=today)
    doc_no: str = ""
    supplier: str = ""
    reference: str = ""
    project: str = ""
    department: str = ""
    requested_by: str = ""
    issued_to: str = ""
    received_by: str = ""
    returned_by: str = ""
    issued_by: str = ""
    delivered_by: str = ""
    handover_to: str = ""
    handover_id: str = ""
    handover_phone: str = ""
    from_location: str = ""
    in_time: str = ""
    out_time: str = ""
    vehicle: str = ""
    driver: str = ""
    purpose: str = ""
    warehouse: str = ""
    to_warehouse: str = ""
    location: str = ""
    to_location: str = ""
    reason: str = ""
    linked_doc: str = ""
    remarks: str = ""


# =============================================================== alert engine
def item_thresholds(db: Database, item: dict | Any) -> tuple[float, float]:
    """Return (min_qty, critical_qty) for an item honouring its threshold mode."""
    it = dict(item)
    mode = (it.get("threshold_mode") or "GLOBAL").upper()
    mx = float(it.get("max_level") or 0)

    def pct(minp, critp):
        return (mx * float(minp) / 100.0, mx * float(critp) / 100.0)

    if mode == "QTY":
        return float(it.get("min_level") or 0), float(it.get("critical_level") or 0)
    if mode == "PERCENT":
        return pct(it.get("min_pct") or db.get_float("global_min_pct", 40),
                   it.get("crit_pct") or db.get_float("global_crit_pct", 20))
    if mode == "CATEGORY":
        row = db.one("SELECT min_pct, crit_pct FROM categories WHERE name=?",
                     (it.get("category") or "",))
        mp = (row["min_pct"] if row and row["min_pct"] is not None
              else db.get_float("global_min_pct", 40))
        cp = (row["crit_pct"] if row and row["crit_pct"] is not None
              else db.get_float("global_crit_pct", 20))
        return pct(mp, cp)
    # GLOBAL: percentage of max, but explicit qty levels win when max is unknown
    if mx > 0:
        return pct(db.get_float("global_min_pct", 40), db.get_float("global_crit_pct", 20))
    return float(it.get("min_level") or 0), float(it.get("critical_level") or 0)


def stock_status(db: Database, item: dict | Any) -> str:
    it = dict(item)
    bal = float(it.get("balance") or 0)
    if bal <= 0:
        return OUT
    mn, crit = item_thresholds(db, it)
    if crit > 0 and bal <= crit:
        return CRITICAL
    if mn > 0 and bal <= mn:
        return WARNING
    return NORMAL


def status_counts(db: Database) -> dict[str, int]:
    counts = {NORMAL: 0, WARNING: 0, CRITICAL: 0, OUT: 0}
    for r in db.query("SELECT * FROM items WHERE active=1"):
        counts[stock_status(db, r)] += 1
    return counts


def items_by_status(db: Database, status: str) -> list[dict]:
    return [dict(r) for r in db.query("SELECT * FROM items WHERE active=1")
            if stock_status(db, r) == status]


# ============================================================== stock engine
def _post(db: Database, item_id: int, txn_type: str, qty_in: float, qty_out: float,
          header: DocHeader, doc_id: int | None, doc_no: str, unit_cost: float = 0.0,
          reason: str = "", party: str = "", location: str = "",
          warehouse: str = "") -> float:
    """Insert one ledger row + move the item balance. Returns new balance."""
    item = db.one("SELECT id, code, balance FROM items WHERE id=?", (item_id,))
    if item is None:
        raise StockError(f"Item id {item_id} does not exist.")
    bal = float(item["balance"] or 0)
    new_bal = bal + float(qty_in or 0) - float(qty_out or 0)
    if new_bal < 0 and not db.get_bool("allow_negative_stock"):
        raise StockError(
            f"Insufficient stock for {item['code']}.\n"
            f"Available: {bal:g}, requested: {qty_out:g}.\n\n"
            f"Enable 'Allow negative stock' in Settings if this is intentional.")
    db.execute(
        """INSERT INTO stock_ledger(item_id,item_code,txn_date,txn_type,doc_type,doc_no,
             doc_id,qty_in,qty_out,balance_after,unit_cost,warehouse,location,party,
             reason,username)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (item_id, item["code"], header.doc_date, txn_type, header.doc_type, doc_no,
         doc_id, qty_in or 0, qty_out or 0, new_bal, unit_cost,
         warehouse or header.warehouse, location or header.location,
         party, reason, db.current_user))
    db.execute("UPDATE items SET balance=?, updated_at=datetime('now','localtime') WHERE id=?",
               (new_bal, item_id))
    return new_bal


def _rebuild_item_balance(db: Database, item_id: int) -> float:
    """Re-sync one item's live balance from the immutable stock ledger."""
    ledger = float(db.scalar(
        "SELECT COALESCE(SUM(qty_in-qty_out),0) FROM stock_ledger WHERE item_id=?",
        (item_id,), 0) or 0)
    db.execute("UPDATE items SET balance=?, updated_at=datetime('now','localtime') WHERE id=?",
               (ledger, item_id))
    return ledger


def _insert_header(db: Database, h: DocHeader, doc_no: str, status: str,
                   total_value: float) -> int:
    cur = db.execute(
        """INSERT INTO documents(doc_type,doc_no,doc_date,status,supplier,reference,project,
             department,requested_by,issued_to,received_by,returned_by,vehicle,driver,purpose,
             warehouse,to_warehouse,location,to_location,reason,linked_doc,remarks,
             total_value,created_by,issued_by,delivered_by,handover_to,
             handover_id,handover_phone,from_location,in_time,out_time,finalized_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (h.doc_type, doc_no, h.doc_date, status, h.supplier, h.reference, h.project,
         h.department, h.requested_by, h.issued_to, h.received_by, h.returned_by,
         h.vehicle, h.driver, h.purpose, h.warehouse, h.to_warehouse, h.location,
         h.to_location, h.reason, h.linked_doc, h.remarks, total_value, db.current_user,
         h.issued_by, h.delivered_by, h.handover_to,
         h.handover_id, h.handover_phone,
         h.from_location, h.in_time, h.out_time,
         _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "FINAL" else None))
    return int(cur.lastrowid)


def _insert_line(db: Database, doc_id: int, ln: Line) -> None:
    it = db.one("SELECT code, description, uom FROM items WHERE id=?", (ln.item_id,))
    if it is None:
        raise StockError(f"Item id {ln.item_id} not found.")
    db.execute(
        """INSERT INTO document_lines(doc_id,item_id,item_code,description,uom,qty,issued_qty,
             unit_cost,total_cost,condition,batch,location,system_qty,counted_qty,variance,
             pr_no,remarks)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (doc_id, ln.item_id, it["code"], it["description"], it["uom"], ln.qty, ln.issued_qty,
         ln.unit_cost, (ln.qty or 0) * (ln.unit_cost or 0), ln.condition, ln.batch,
         ln.location, ln.system_qty, ln.counted_qty, (ln.counted_qty - ln.system_qty),
         ln.pr_no, ln.remarks))


def _validate(lines: list[Line]) -> None:
    if not lines:
        raise StockError("Add at least one item line before saving.")
    for ln in lines:
        if ln.qty is None:
            raise StockError("Every line needs a quantity.")


# ------------------------------------------------------------------ receipts
def post_receipt(db: Database, h: DocHeader, lines: list[Line], finalize: bool = True) -> str:
    """GRN - stock in."""
    h.doc_type = "GRN"
    _validate(lines)
    for ln in lines:
        if ln.qty <= 0:
            raise StockError("Received quantity must be greater than zero.")
    try:
        doc_no = h.doc_no or db.next_doc_number("GRN", commit=False)
        total = sum((l.qty or 0) * (l.unit_cost or 0) for l in lines)
        doc_id = _insert_header(db, h, doc_no, "FINAL" if finalize else "DRAFT", total)
        for ln in lines:
            _insert_line(db, doc_id, ln)
            if finalize:
                _post(db, ln.item_id, "RECEIPT", ln.qty, 0, h, doc_id, doc_no,
                      unit_cost=ln.unit_cost, party=h.supplier,
                      location=ln.location or h.location)
                if ln.unit_cost:
                    db.execute("UPDATE items SET unit_cost=? WHERE id=?",
                               (ln.unit_cost, ln.item_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.audit("RECEIVED" if finalize else "CREATED", "GRN", doc_no,
             f"{len(lines)} line(s), value {total:.2f}")
    return doc_no


# -------------------------------------------------------------------- issues
def post_issue(db: Database, h: DocHeader, lines: list[Line], finalize: bool = True) -> str:
    """DN - stock out / delivery note."""
    h.doc_type = "DN"
    _validate(lines)
    for ln in lines:
        if ln.qty <= 0:
            raise StockError("Issued quantity must be greater than zero.")
    try:
        doc_no = h.doc_no or db.next_doc_number("DN", commit=False)
        total = sum((l.qty or 0) * (l.unit_cost or 0) for l in lines)
        doc_id = _insert_header(db, h, doc_no, "FINAL" if finalize else "DRAFT", total)
        for ln in lines:
            _insert_line(db, doc_id, ln)
            if finalize:
                _post(db, ln.item_id, "ISSUE", 0, ln.qty, h, doc_id, doc_no,
                      unit_cost=ln.unit_cost, party=h.issued_to or h.project,
                      location=ln.location or h.location,
                      reason=f"PR {ln.pr_no}" if ln.pr_no else "")
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.audit("ISSUED" if finalize else "CREATED", "DN", doc_no, f"{len(lines)} line(s)")
    return doc_no


def load_draft(db: Database, doc_id: int) -> tuple[dict, list[dict]]:
    """Header + lines of a document, ready to be re-opened on a form.

    Raises StockError when the document is gone, so the caller can show a
    friendly message instead of crashing on a None row.
    """
    d = db.one("SELECT * FROM documents WHERE id=?", (doc_id,))
    if d is None:
        raise StockError("Document not found.")
    lines = [dict(r) for r in db.query(
        "SELECT * FROM document_lines WHERE doc_id=? ORDER BY id", (doc_id,))]
    return dict(d), lines


def update_draft(db: Database, doc_id: int, h: DocHeader,
                 lines: list[Line]) -> str:
    """Rewrite a DRAFT document in place, or reopen a REVERSED one as DRAFT.

    This is what makes an adjusted quantity actually stick: the old lines are
    replaced by the edited ones inside a single transaction, so re-opening or
    refreshing the document always shows the quantity that was typed last.

    FINAL documents still cannot be edited directly — they must be corrected
    through `reverse_document` first. A REVERSED DN / GRN may then be saved
    again as DRAFT with the same document number.
    """
    d = db.one("SELECT * FROM documents WHERE id=?", (doc_id,))
    if d is None:
        raise StockError("Document not found.")
    if d["status"] not in ("DRAFT", "REVERSED"):
        raise StockError(
            f"{d['doc_no']} is {d['status'].lower()} and can no longer be edited.\n\n"
            "Use 'Reverse / Correct' on a finalized document instead.")
    if d["status"] == "REVERSED" and d["doc_type"] not in ("DN", "GRN"):
        raise StockError(
            f"{d['doc_no']} is reversed and cannot be reopened on this form.")
    _validate(lines)
    for ln in lines:
        if (ln.qty or 0) <= 0 and d["doc_type"] in ("DN", "GRN"):
            raise StockError("Every line needs a quantity greater than zero.")
    total = sum((l.qty or 0) * (l.unit_cost or 0) for l in lines)
    was_reversed = d["status"] == "REVERSED"
    try:
        db.execute(
            """UPDATE documents SET doc_date=?, supplier=?, reference=?, project=?,
                 department=?, requested_by=?, issued_to=?, received_by=?, returned_by=?,
                 vehicle=?, driver=?, purpose=?, warehouse=?, to_warehouse=?, location=?,
                 to_location=?, reason=?, linked_doc=?, remarks=?, total_value=?,
                 issued_by=?, delivered_by=?, handover_to=?, handover_id=?,
                 handover_phone=?, from_location=?, in_time=?, out_time=?,
                 status='DRAFT', finalized_at=NULL, pdf_path=''
               WHERE id=?""",
            (h.doc_date or d["doc_date"], h.supplier, h.reference, h.project,
             h.department, h.requested_by, h.issued_to, h.received_by, h.returned_by,
             h.vehicle, h.driver, h.purpose, h.warehouse, h.to_warehouse, h.location,
             h.to_location, h.reason, h.linked_doc, h.remarks, total,
             h.issued_by, h.delivered_by, h.handover_to, h.handover_id,
             h.handover_phone, h.from_location, h.in_time, h.out_time, doc_id))
        db.execute("DELETE FROM document_lines WHERE doc_id=?", (doc_id,))
        for ln in lines:
            _insert_line(db, doc_id, ln)
        db.commit()
    except Exception:
        db.rollback()
        raise
    from . import documents as D
    fresh = db.one("SELECT * FROM documents WHERE id=?", (doc_id,))
    if fresh is not None:
        fresh_lines = db.query("SELECT * FROM document_lines WHERE doc_id=? ORDER BY id", (doc_id,))
        D.purge_document_files(db, fresh, fresh_lines)
    db.audit("EDITED", d["doc_type"], d["doc_no"],
             f"{'reopened from reversal and saved as draft' if was_reversed else 'draft updated'}"
             f" — {len(lines)} line(s), qty {sum(l.qty or 0 for l in lines):g}")
    return d["doc_no"]


def finalize_draft(db: Database, doc_id: int) -> None:
    """Post the stock effect of a DRAFT DN/GRN and lock it."""
    d = db.one("SELECT * FROM documents WHERE id=?", (doc_id,))
    if d is None:
        raise StockError("Document not found.")
    if d["status"] != "DRAFT":
        raise StockError(f"{d['doc_no']} is already {d['status'].lower()}.")
    h = DocHeader(doc_type=d["doc_type"], doc_date=d["doc_date"], doc_no=d["doc_no"],
                  warehouse=d["warehouse"], location=d["location"])
    lines = db.query("SELECT * FROM document_lines WHERE doc_id=?", (doc_id,))
    try:
        for ln in lines:
            if d["doc_type"] == "GRN":
                _post(db, ln["item_id"], "RECEIPT", ln["qty"], 0, h, doc_id, d["doc_no"],
                      unit_cost=ln["unit_cost"], party=d["supplier"])
            else:
                _post(db, ln["item_id"], "ISSUE", 0, ln["qty"], h, doc_id, d["doc_no"],
                      unit_cost=ln["unit_cost"], party=d["issued_to"])
        db.execute("UPDATE documents SET status='FINAL', finalized_at=datetime('now','localtime')"
                   " WHERE id=?", (doc_id,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.audit("FINALIZED", d["doc_type"], d["doc_no"])


def reverse_document(db: Database, doc_id: int, reason: str) -> str:
    """Authorised correction: post the exact opposite ledger effect, keep history.

    Every document type is handled. Previously ADJ and TRF flipped the status to
    REVERSED but posted nothing, so the stock was never corrected -- the document
    said "reversed" while the balance still carried its effect.

    When the document came from a Material Request, the request is put back so it
    can be issued again (see `_unwind_material_request`). Reversing a delivery
    that was never un-booked from its MR left the request stranded at Delivered.
    """
    d = db.one("SELECT * FROM documents WHERE id=?", (doc_id,))
    if d is None:
        raise StockError("Document not found.")
    if d["status"] != "FINAL":
        raise StockError("Only finalized documents can be reversed.")
    if not reason.strip():
        raise StockError("A reason is required to reverse a document.")
    lines = db.query("SELECT * FROM document_lines WHERE doc_id=?", (doc_id,))
    typ = d["doc_type"]

    def _g(key, default=""):
        try:
            return d[key] or default
        except (IndexError, KeyError):
            return default

    h = DocHeader(doc_type=typ, doc_date=today(), warehouse=d["warehouse"])
    tag = f"Reversal of {d['doc_no']}: {reason}"
    touched_items: set[int] = set()
    try:
        for ln in lines:
            qty = float(ln["qty"] or 0)
            item_id = int(ln["item_id"])
            if typ == "GRN":
                # goods came in -> take them back out
                _post(db, item_id, "ADJUSTMENT", 0, qty, h, doc_id,
                      d["doc_no"], reason=tag)
                touched_items.add(item_id)
            elif typ == "DN":
                # goods went out -> put them back
                _post(db, item_id, "ADJUSTMENT", qty, 0, h, doc_id,
                      d["doc_no"], reason=tag)
                touched_items.add(item_id)
            elif typ == "RET":
                if (ln["condition"] or "USABLE").upper() == "USABLE":
                    _post(db, item_id, "ADJUSTMENT", 0, qty, h, doc_id,
                          d["doc_no"], reason=tag)
                    touched_items.add(item_id)
                else:
                    db.execute("UPDATE items SET damaged_qty=MAX(0,damaged_qty-?)"
                               " WHERE id=?", (qty, item_id))
            elif typ == "TRF":
                # a transfer is out of one store and into another: undo both legs
                # and send the item back to where it started.
                back = DocHeader(doc_type="TRF", doc_date=today(),
                                 warehouse=_g("to_warehouse") or d["warehouse"],
                                 to_warehouse=d["warehouse"],
                                 location=_g("to_location"),
                                 to_location=_g("location"))
                _post(db, item_id, "TRANSFER_OUT", 0, qty, back, doc_id,
                      d["doc_no"], location=_g("to_location"), reason=tag)
                _post(db, item_id, "TRANSFER_IN", qty, 0, back, doc_id,
                      d["doc_no"], location=_g("location"), reason=tag)
                db.execute("UPDATE items SET warehouse=?, location=? WHERE id=?",
                           (d["warehouse"], _g("location"), item_id))
                touched_items.add(item_id)
            elif typ == "ADJ":
                # an adjustment is signed: +7 is undone by -7 and vice versa
                if qty >= 0:
                    _post(db, item_id, "ADJUSTMENT", 0, qty, h, doc_id,
                          d["doc_no"], reason=tag)
                else:
                    _post(db, item_id, "ADJUSTMENT", -qty, 0, h, doc_id,
                          d["doc_no"], reason=tag)
                touched_items.add(item_id)
            elif typ == "CNT":
                # a count sheet holds no stock effect of its own; the adjustment
                # it produced is the thing to reverse.
                continue
        for item_id in touched_items:
            _rebuild_item_balance(db, item_id)
        db.execute("UPDATE documents SET status='REVERSED', remarks=COALESCE(remarks,'')||?"
                   " WHERE id=?", (f" [REVERSED: {reason}]", doc_id))
        _unwind_material_request(db, d["doc_no"], typ, reason)
        db.commit()
    except Exception:
        db.rollback()
        raise
    if typ == "DN":
        try:
            from . import employee_ppe as PPE
            pdb = PPE.get_db(getattr(db, "current_user", "admin"))
            try:
                PPE.purge_stale_synced_records(db, pdb, [doc_id])
            finally:
                pdb.close()
        except Exception:
            pass
    db.audit("REVERSED", typ, d["doc_no"], reason)
    return d["doc_no"]


def _unwind_material_request(db: Database, doc_no: str, doc_type: str,
                             reason: str) -> int:
    """Put an MR back after its Delivery Note is reversed.

    The delivered quantity is rolled back and the line returns to the prepared
    (Ready) state, so the material can simply be issued again on a corrected
    Delivery Note. The reservation is re-established at the same time, which is
    what makes the stock figures add up: the goods are physically back in the
    store but still promised to that request.
    """
    if doc_type != "DN":
        return 0
    rows = db.query("SELECT * FROM mr_lines WHERE dn_no=?", (doc_no,))
    if not rows:
        return 0
    from . import material as M
    touched: set[int] = set()
    for r in rows:
        delivered = float(r["qty_delivered"] or 0)
        if delivered <= 0:
            continue
        prepared = float(r["qty_prepared"] or 0)
        status = M._line_status(float(r["qty_requested"] or 0), prepared, 0.0,
                                r["status"])
        db.execute(
            """UPDATE mr_lines SET qty_delivered=0, dn_no='', delivered_at=NULL,
                 status=?, remarks=COALESCE(remarks,'') || ?
               WHERE id=?""",
            (status, f" [DN {doc_no} reversed: {reason}]", r["id"]))
        touched.add(r["mr_id"])
    for mr_id in touched:
        M._refresh_status(db, mr_id)
    if touched:
        db.audit("EDITED", "MR", doc_no,
                 f"{len(rows)} line(s) returned to Ready after the DN was reversed")
    return len(rows)


# ------------------------------------------------------------------- returns
def post_return(db: Database, h: DocHeader, lines: list[Line]) -> str:
    """RET - usable qty goes back to stock, damaged qty to damaged tracking."""
    h.doc_type = "RET"
    _validate(lines)
    try:
        doc_no = h.doc_no or db.next_doc_number("RET", commit=False)
        doc_id = _insert_header(db, h, doc_no, "FINAL", 0)
        for ln in lines:
            if ln.qty <= 0:
                continue
            _insert_line(db, doc_id, ln)
            if (ln.condition or "USABLE").upper() == "DAMAGED":
                db.execute("UPDATE items SET damaged_qty=damaged_qty+? WHERE id=?",
                           (ln.qty, ln.item_id))
                it = db.one("SELECT code FROM items WHERE id=?", (ln.item_id,))
                db.execute(
                    """INSERT INTO stock_ledger(item_id,item_code,txn_date,txn_type,doc_type,
                         doc_no,doc_id,qty_in,qty_out,balance_after,warehouse,party,reason,username)
                       VALUES(?,?,?,'DAMAGE','RET',?,?,0,0,
                         (SELECT balance FROM items WHERE id=?),?,?,?,?)""",
                    (ln.item_id, it["code"], h.doc_date, doc_no, doc_id, ln.item_id,
                     h.warehouse, h.returned_by,
                     f"Damaged return {ln.qty:g} ({ln.remarks})", db.current_user))
            else:
                _post(db, ln.item_id, "RETURN", ln.qty, 0, h, doc_id, doc_no,
                      party=h.returned_by, reason=f"Return against {h.linked_doc}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.audit("RETURNED", "RET", doc_no, f"against {h.linked_doc or '-'}")
    return doc_no


# ----------------------------------------------------------------- transfers
def post_transfer(db: Database, h: DocHeader, lines: list[Line]) -> str:
    """TRF - move stock between warehouse/location/rack (net qty unchanged)."""
    h.doc_type = "TRF"
    _validate(lines)
    if not h.to_warehouse and not h.to_location:
        raise StockError("Select a destination warehouse or location.")
    try:
        doc_no = h.doc_no or db.next_doc_number("TRF", commit=False)
        doc_id = _insert_header(db, h, doc_no, "FINAL", 0)
        for ln in lines:
            if ln.qty <= 0:
                raise StockError("Transfer quantity must be greater than zero.")
            _insert_line(db, doc_id, ln)
            _post(db, ln.item_id, "TRANSFER_OUT", 0, ln.qty, h, doc_id, doc_no,
                  warehouse=h.warehouse, location=h.location, party=h.issued_to,
                  reason=f"To {h.to_warehouse}/{h.to_location}")
            _post(db, ln.item_id, "TRANSFER_IN", ln.qty, 0, h, doc_id, doc_no,
                  warehouse=h.to_warehouse, location=h.to_location, party=h.received_by,
                  reason=f"From {h.warehouse}/{h.location}")
            db.execute("UPDATE items SET warehouse=?, location=? WHERE id=?",
                       (h.to_warehouse or h.warehouse, h.to_location or h.location, ln.item_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.audit("TRANSFERRED", "TRF", doc_no, f"{h.warehouse} -> {h.to_warehouse}")
    return doc_no


# --------------------------------------------------------------- adjustments
def post_adjustment(db: Database, h: DocHeader, lines: list[Line]) -> str:
    """ADJ - line.qty is the signed delta (+found / -missing)."""
    h.doc_type = "ADJ"
    _validate(lines)
    if not (h.reason or "").strip():
        raise StockError("A reason is mandatory for every stock adjustment.")
    try:
        doc_no = h.doc_no or db.next_doc_number("ADJ", commit=False)
        doc_id = _insert_header(db, h, doc_no, "FINAL", 0)
        for ln in lines:
            if ln.qty == 0:
                continue
            _insert_line(db, doc_id, ln)
            qin = ln.qty if ln.qty > 0 else 0
            qout = -ln.qty if ln.qty < 0 else 0
            _post(db, ln.item_id, "ADJUSTMENT", qin, qout, h, doc_id, doc_no,
                  reason=f"{h.reason}: {ln.remarks}".strip(": "))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.audit("ADJUSTED", "ADJ", doc_no, h.reason)
    return doc_no


# -------------------------------------------------------------- stock counts
def save_stock_count(db: Database, h: DocHeader, lines: list[Line]) -> str:
    """CNT - stores counted vs system qty. No stock effect until converted."""
    h.doc_type = "CNT"
    _validate(lines)
    try:
        doc_no = h.doc_no or db.next_doc_number("CNT", commit=False)
        doc_id = _insert_header(db, h, doc_no, "DRAFT", 0)
        for ln in lines:
            _insert_line(db, doc_id, ln)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.audit("CREATED", "CNT", doc_no, f"{len(lines)} line(s)")
    return doc_no


def count_to_adjustment(db: Database, count_doc_id: int) -> str:
    """Convert stock-count variances into a posted adjustment document."""
    d = db.one("SELECT * FROM documents WHERE id=? AND doc_type='CNT'", (count_doc_id,))
    if d is None:
        raise StockError("Stock count not found.")
    if d["status"] == "FINAL":
        raise StockError(f"{d['doc_no']} was already converted to an adjustment.")
    rows = db.query("SELECT * FROM document_lines WHERE doc_id=? AND variance<>0",
                    (count_doc_id,))
    if not rows:
        raise StockError("No variances found - nothing to adjust.")
    h = DocHeader(doc_type="ADJ", doc_date=today(), warehouse=d["warehouse"],
                  reason="Physical count correction", linked_doc=d["doc_no"],
                  remarks=f"Auto-generated from stock count {d['doc_no']}")
    lines = [Line(item_id=r["item_id"], qty=r["variance"],
                  remarks=f"System {r['system_qty']:g} vs counted {r['counted_qty']:g}")
             for r in rows]
    adj_no = post_adjustment(db, h, lines)
    db.execute("UPDATE documents SET status='FINAL', linked_doc=? WHERE id=?",
               (adj_no, count_doc_id))
    db.commit()
    return adj_no


# ---------------------------------------------------------------- item CRUD
ITEM_SECOND_TYPES = ["Device", "Instrument", "Tools"]

ITEM_FIELDS = ["code", "description", "short_desc", "category", "second_type", "subcategory", "uom", "brand",
               "model", "specification", "barcode", "alt_code", "min_level", "max_level",
               "reorder_level", "critical_level", "threshold_mode", "min_pct", "crit_pct",
               "opening_balance", "unit_cost", "warehouse", "location", "rack", "remarks",
               "image_path", "active"]


def save_item(db: Database, data: dict, item_id: int | None = None) -> int:
    data = {k: v for k, v in data.items() if k in ITEM_FIELDS}
    if not data.get("description"):
        raise StockError("Item description is required.")
    if item_id:
        sets = ", ".join(f"{k}=?" for k in data)
        db.execute(f"UPDATE items SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
                   list(data.values()) + [item_id])
        db.commit()
        db.audit("EDITED", "item", data.get("code", item_id))
        return item_id
    if not data.get("code"):
        data["code"] = db.next_item_code()
    if db.one("SELECT 1 FROM items WHERE code=?", (data["code"],)):
        raise StockError(f"Item code {data['code']} already exists.")
    opening = float(data.get("opening_balance") or 0)
    cols = ", ".join(data)
    qs = ", ".join("?" * len(data))
    cur = db.execute(f"INSERT INTO items({cols}, balance) VALUES({qs}, 0)", list(data.values()))
    item_id = int(cur.lastrowid)
    if opening:
        h = DocHeader(doc_type="OPENING", doc_date=today(),
                      warehouse=data.get("warehouse", ""), location=data.get("location", ""))
        _post(db, item_id, "OPENING", opening, 0, h, None, "OPENING",
              unit_cost=float(data.get("unit_cost") or 0), reason="Opening balance")
    db.commit()
    db.audit("CREATED", "item", data["code"])
    return item_id


def deactivate_item(db: Database, item_id: int) -> None:
    it = db.one("SELECT code, balance FROM items WHERE id=?", (item_id,))
    if it is None:
        raise StockError("Item not found.")
    db.execute("UPDATE items SET active=0 WHERE id=?", (item_id,))
    db.commit()
    db.audit("DELETED", "item", it["code"], "marked inactive (history preserved)")


def bulk_set_second_type(db: Database, item_ids: Sequence[int], second_type: str = "") -> int:
    ids = [int(i) for i in item_ids if int(i)]
    if not ids:
        return 0
    if second_type and second_type not in ITEM_SECOND_TYPES:
        raise StockError(f"Invalid 2nd Type: {second_type}")
    ph = ",".join("?" * len(ids))
    db.execute(f"UPDATE items SET second_type=?, updated_at=datetime('now','localtime') WHERE id IN ({ph})",
               [str(second_type or "").strip()] + ids)
    db.commit()
    db.audit("EDITED", "item", f"{len(ids)} item(s)", f"bulk 2nd Type -> {second_type or '(blank)'}")
    return len(ids)


# -------------------------------------------------------------- reservation
# A quantity is "reserved" once the store team has prepared/marked it for an
# open material request but the Delivery Note has not been created yet. The
# stock is still physically on the shelf (and still in `items.balance`), but it
# is promised to a project, so it must never be offered to a second request.
RESERVED_STATES = ("Preparing", "Ready", "Partially Delivered")

_RESERVED_SQL = """
    SELECT l.item_id AS iid,
           COALESCE(SUM(MAX(l.qty_prepared - l.qty_delivered, 0)), 0) AS res
      FROM mr_lines l JOIN material_requests m ON m.id = l.mr_id
     WHERE l.item_id IS NOT NULL
       AND l.status IN ('Preparing','Ready','Partially Delivered')
       AND m.status <> 'Cancelled'
"""


def reserved_map(db: Database, exclude_mr_id: int | None = None) -> dict[int, float]:
    """{item_id: reserved qty} for every item with a live reservation.

    One query for the whole grid — calling reserved_for() per row would fire a
    sub-query for each of thousands of items.
    """
    sql = _RESERVED_SQL
    p: list[Any] = []
    if exclude_mr_id:
        sql += " AND l.mr_id <> ?"
        p.append(exclude_mr_id)
    sql += " GROUP BY l.item_id"
    try:
        rows = db.query(sql, p)
    except Exception:          # noqa: BLE001 - pre-migration DB without mr_lines
        return {}
    return {int(r["iid"]): float(r["res"] or 0) for r in rows if (r["res"] or 0) > 0}


def reserved_for(db: Database, item_id: int, exclude_mr_id: int | None = None) -> float:
    """Reserved qty of a single item. Same definition as reserved_map()."""
    sql = _RESERVED_SQL + " AND l.item_id = ?"
    p: list[Any] = [item_id]
    if exclude_mr_id:
        sql += " AND l.mr_id <> ?"
        p.append(exclude_mr_id)
    try:
        return float(db.scalar(sql.replace("l.item_id AS iid,", ""), p) or 0)
    except Exception:          # noqa: BLE001
        return 0.0


# ------------------------------------------------------------------- search
def search_items(db: Database, text: str = "", category: str = "", warehouse: str = "",
                 status: str = "", second_type_filter: str = "", active_only: bool = True,
                 limit: int = 5000) -> list[dict]:
    sql = "SELECT * FROM items WHERE 1=1"
    p: list[Any] = []
    if active_only:
        sql += " AND active=1"
    if text:
        like = f"%{text.strip()}%"
        sql += (" AND (code LIKE ? OR description LIKE ? OR short_desc LIKE ? OR barcode LIKE ?"
                " OR alt_code LIKE ? OR brand LIKE ? OR model LIKE ? OR category LIKE ?"
                " OR second_type LIKE ? OR location LIKE ? OR uom LIKE ?)")
        p += [like] * 11
    if category:
        sql += " AND category=?"
        p.append(category)
    if warehouse:
        sql += " AND warehouse=?"
        p.append(warehouse)
    if second_type_filter == "Normal Items":
        sql += " AND COALESCE(second_type,'')=''"
    elif second_type_filter == "2nd Type Items":
        sql += " AND COALESCE(second_type,'')<>''"
    sql += " ORDER BY code LIMIT ?"
    p.append(limit)
    rows = [dict(r) for r in db.query(sql, p)]
    res = reserved_map(db)
    for r in rows:
        r["status"] = stock_status(db, r)
        r["value"] = (r["balance"] or 0) * (r["unit_cost"] or 0)
        # reserved is stock still on the shelf but promised to an open request;
        # free is what a new request may actually be given
        r["reserved"] = res.get(r["id"], 0.0)
        r["free"] = max(0.0, (r["balance"] or 0) - r["reserved"])
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def find_by_barcode(db: Database, code: str) -> dict | None:
    r = db.one("SELECT * FROM items WHERE barcode=? OR code=? OR alt_code=?",
               (code, code, code))
    if r is None:
        return None
    d = dict(r)
    d["status"] = stock_status(db, d)
    return d


def distinct_second_types(db: Database) -> list[str]:
    rows = db.query("SELECT DISTINCT second_type FROM items WHERE COALESCE(second_type,'')<>'' ORDER BY second_type")
    return [str(r[0]) for r in rows if str(r[0] or "").strip()]


def typed_item_analytics(db: Database, text: str = "", second_type: str = "", site: str = "") -> dict[str, Any]:
    """Current custody position of typed Item Master materials.

    Uses final stock movements, so a DN automatically appears here when its item
    has a 2nd Type on the Item Master. Returns and damaged returns reduce the
    current quantity at that site. Any typed quantity still sitting in inventory
    is also included here under warehouse / store custody. The analytics carries
    the related PR / MR number(s), DN number(s), and DN reference number(s) from
    the issuing DN.
    """
    rows = db.query("""
        SELECT l.item_id, l.item_code, l.txn_type, l.qty_in, l.qty_out, l.reason, l.txn_date,
               COALESCE(i.description,'') AS description,
               COALESCE(i.uom,'') AS uom,
               COALESCE(i.second_type,'') AS second_type,
               COALESCE(i.unit_cost,0) AS unit_cost,
               COALESCE(NULLIF(d.project,''), NULLIF(d.department,''), '') AS own_site,
               COALESCE(NULLIF(d.issued_to,''), NULLIF(d.returned_by,''), '') AS own_party,
               COALESCE(NULLIF(d.location,''), NULLIF(d.to_location,''), NULLIF(d.from_location,''), '') AS own_location,
               d.id AS doc_id, d.doc_type, d.doc_no, d.reference, d.linked_doc
          FROM stock_ledger l
          LEFT JOIN items i ON i.id=l.item_id
          LEFT JOIN documents d ON d.id=l.doc_id
         WHERE l.txn_type IN ('ISSUE','RETURN','DAMAGE')
    """)
    custody_rows = db.query("""
        SELECT id, code, description, uom, second_type, balance, warehouse, location, rack
          FROM items
         WHERE COALESCE(second_type,'')<>''
           AND COALESCE(balance,0) > 0
    """)
    doc_map = {
        str(r["doc_no"]): {
            "id": int(r["id"]),
            "doc_no": str(r["doc_no"] or "").strip(),
            "doc_type": str(r["doc_type"] or "").strip(),
            "reference": str(r["reference"] or "").strip(),
            "site": str(r["project"] or r["department"] or "").strip(),
            "party": str(r["issued_to"] or r["returned_by"] or "").strip(),
            "location": str(r["location"] or r["to_location"] or r["from_location"] or "").strip(),
        }
        for r in db.query(
            "SELECT id, doc_type, doc_no, reference, project, department, issued_to, returned_by, location, to_location, from_location FROM documents"
        )
        if str(r["doc_no"] or "").strip()
    }
    line_map: dict[tuple[int, int], set[str]] = {}
    for r in db.query("SELECT doc_id, item_id, pr_no FROM document_lines WHERE COALESCE(pr_no,'')<>''"):
        key = (int(r["doc_id"]), int(r["item_id"]))
        line_map.setdefault(key, set()).add(str(r["pr_no"] or "").strip())
    needle = text.strip().lower()
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for r in rows:
        row = dict(r)
        row_type = str(row.get("second_type") or "").strip()
        if not row_type:
            continue
        if second_type and row_type != second_type:
            continue
        linked = doc_map.get(str(row.get("linked_doc") or "").strip(), {})
        row_site = str(row.get("own_site") or linked.get("site") or "").strip() or "(unassigned)"
        if site and row_site != site:
            continue
        row_party = str(row.get("own_party") or linked.get("party") or "").strip() or "-"
        row_location = str(row.get("own_location") or linked.get("location") or "").strip() or "-"
        item_id = int(row.get("item_id") or 0)
        item_code = str(row.get("item_code") or "").strip()
        desc = str(row.get("description") or "").strip() or item_code or "(blank description)"
        uom = str(row.get("uom") or "").strip()
        row_doc_type = str(row.get("doc_type") or "").strip()
        row_doc_no = str(row.get("doc_no") or "").strip()
        row_reference = str(row.get("reference") or "").strip()
        row_doc_id = int(row.get("doc_id") or 0)
        source_doc = linked if linked else {}
        if row_doc_type == "DN" and row_doc_no:
            source_doc = {
                "id": row_doc_id,
                "doc_no": row_doc_no,
                "doc_type": row_doc_type,
                "reference": row_reference,
                "site": str(row.get("own_site") or "").strip(),
                "party": str(row.get("own_party") or "").strip(),
                "location": str(row.get("own_location") or "").strip(),
            }
        source_doc_id = int(source_doc.get("id") or 0)
        source_doc_no = str(source_doc.get("doc_no") or "").strip()
        source_ref = str(source_doc.get("reference") or "").strip()
        source_prs = sorted(p for p in line_map.get((source_doc_id, item_id), set()) if p)
        hay = " ".join((
            row_type, item_code, desc, row_site, row_party, row_location, uom,
            source_doc_no, source_ref, ", ".join(source_prs),
        )).lower()
        if needle and needle not in hay:
            continue
        key = (row_type, row_site, row_location, item_code, desc)
        g = grouped.setdefault(key, {
            "second_type": row_type,
            "site": row_site,
            "location": row_location,
            "item_code": item_code,
            "description": desc,
            "uom": uom,
            "issued_to": set(),
            "issued_qty": 0.0,
            "returned_qty": 0.0,
            "damaged_qty": 0.0,
            "dn_nos": set(),
            "dn_refs": set(),
            "pr_nos": set(),
        })
        if row_party and row_party != "-":
            g["issued_to"].add(row_party)
        if source_doc_no:
            g["dn_nos"].add(source_doc_no)
        if source_ref:
            g["dn_refs"].add(source_ref)
        for pr in source_prs:
            g["pr_nos"].add(pr)
        if row.get("txn_type") == "ISSUE":
            g["issued_qty"] += float(row.get("qty_out") or 0)
        elif row.get("txn_type") == "RETURN":
            g["returned_qty"] += float(row.get("qty_in") or 0)
        else:
            m = re.search(r"([\d.]+)", str(row.get("reason") or ""))
            if m:
                g["damaged_qty"] += float(m.group(1))
    out: list[dict[str, Any]] = []
    by_site: dict[str, float] = {}
    by_type: dict[str, float] = {}
    by_item: dict[str, float] = {}
    total_qty = 0.0
    def _add_row(row: dict[str, Any]) -> None:
        nonlocal total_qty
        qty = float(row.get("qty") or 0)
        out.append(row)
        total_qty += qty
        by_site[row["site"]] = by_site.get(row["site"], 0.0) + qty
        by_type[row["second_type"]] = by_type.get(row["second_type"], 0.0) + qty
        item_label = f"{row['description']} @ {row['site']}"
        by_item[item_label] = by_item.get(item_label, 0.0) + qty

    for g in grouped.values():
        current_qty = g["issued_qty"] - g["returned_qty"] - g["damaged_qty"]
        if current_qty <= 1e-9:
            continue
        _add_row({
            "second_type": g["second_type"],
            "site": g["site"],
            "location": g["location"],
            "item_code": g["item_code"],
            "description": g["description"],
            "uom": g["uom"],
            "issued_to": ", ".join(sorted(g["issued_to"])) or "-",
            "pr_nos": ", ".join(sorted(g["pr_nos"])) or "-",
            "dn_nos": ", ".join(sorted(g["dn_nos"])) or "-",
            "dn_refs": ", ".join(sorted(g["dn_refs"])) or "-",
            "qty": current_qty,
            "issued_qty": g["issued_qty"],
            "returned_qty": g["returned_qty"],
            "damaged_qty": g["damaged_qty"],
            "dn_count": len(g["dn_nos"]),
        })

    for r in custody_rows:
        row = dict(r)
        row_type = str(row.get("second_type") or "").strip()
        if not row_type:
            continue
        if second_type and row_type != second_type:
            continue
        row_site = str(row.get("warehouse") or "").strip() or "Store Custody"
        if site and row_site != site:
            continue
        row_location = str(row.get("location") or row.get("rack") or "").strip() or "-"
        item_code = str(row.get("code") or "").strip()
        desc = str(row.get("description") or "").strip() or item_code or "(blank description)"
        uom = str(row.get("uom") or "").strip()
        hay = " ".join((row_type, item_code, desc, row_site, row_location, uom, "Store Custody", "warehouse")).lower()
        if needle and needle not in hay:
            continue
        _add_row({
            "second_type": row_type,
            "site": row_site,
            "location": row_location,
            "item_code": item_code,
            "description": desc,
            "uom": uom,
            "issued_to": "Store Custody",
            "pr_nos": "-",
            "dn_nos": "-",
            "dn_refs": "-",
            "qty": float(row.get("balance") or 0),
            "issued_qty": 0.0,
            "returned_qty": 0.0,
            "damaged_qty": 0.0,
            "dn_count": 0,
        })
    out.sort(key=lambda r: (str(r["site"]).lower(), str(r["second_type"]).lower(), -float(r["qty"]), str(r["description"]).lower()))
    return {
        "rows": out,
        "row_count": len(out),
        "total_qty": total_qty,
        "site_count": len(by_site),
        "second_type_count": len(by_type),
        "by_site": sorted(by_site.items(), key=lambda kv: (-kv[1], kv[0].lower())),
        "by_second_type": sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0].lower())),
        "top_items": sorted(by_item.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:10],
    }


def global_search(db: Database, text: str) -> dict[str, list[dict]]:
    """Search items + documents + ledger + searchable document file contents."""
    text = text.strip()
    like = f"%{text}%"
    items = search_items(db, text, limit=200)
    docs = [dict(r) for r in db.query(
        """SELECT * FROM documents WHERE doc_no LIKE ? OR reference LIKE ? OR project LIKE ?
             OR supplier LIKE ? OR issued_to LIKE ? OR received_by LIKE ? OR returned_by LIKE ?
             OR doc_date LIKE ?
             OR id IN (SELECT doc_id FROM document_lines WHERE pr_no LIKE ?)
           ORDER BY id DESC LIMIT 200""", [like] * 9)]
    moves = [dict(r) for r in db.query(
        """SELECT * FROM stock_ledger WHERE item_code LIKE ? OR doc_no LIKE ? OR party LIKE ?
             OR txn_date LIKE ? ORDER BY id DESC LIMIT 200""", [like] * 4)]
    files = FS.search(db, text, limit=120) if text else []
    return {"items": items, "documents": docs, "movements": moves, "files": files}


def item_history(db: Database, item_id: int) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT * FROM stock_ledger WHERE item_id=? ORDER BY id", (item_id,))]


def item_movement_summary(db: Database, item_id: int, date_from: str = "",
                          date_to: str = "") -> dict:
    where, p = "WHERE item_id=?", [item_id]
    if date_from:
        where += " AND txn_date>=?"
        p.append(date_from)
    if date_to:
        where += " AND txn_date<=?"
        p.append(date_to)

    def s(types: tuple[str, ...], col: str) -> float:
        q = f"SELECT COALESCE(SUM({col}),0) FROM stock_ledger {where} AND txn_type IN ({','.join('?'*len(types))})"
        return float(db.scalar(q, p + list(types)))

    opening = float(db.scalar(
        "SELECT COALESCE(SUM(qty_in-qty_out),0) FROM stock_ledger WHERE item_id=?" +
        (" AND txn_date<?" if date_from else ""),
        [item_id] + ([date_from] if date_from else [])))
    return {
        "opening": opening,
        "received": s(("RECEIPT",), "qty_in"),
        "returned": s(("RETURN",), "qty_in"),
        "issued": s(("ISSUE",), "qty_out"),
        "transfer_in": s(("TRANSFER_IN",), "qty_in"),
        "transfer_out": s(("TRANSFER_OUT",), "qty_out"),
        "adj_in": s(("ADJUSTMENT",), "qty_in"),
        "adj_out": s(("ADJUSTMENT",), "qty_out"),
        "closing": float(db.scalar("SELECT balance FROM items WHERE id=?", [item_id])),
    }


# ---------------------------------------------------------------- dashboard
def dashboard_data(db: Database) -> dict:
    t = today()
    sc = status_counts(db)
    d: dict[str, Any] = {
        "total_items": db.scalar("SELECT COUNT(*) FROM items WHERE active=1"),
        "total_qty": db.scalar("SELECT COALESCE(SUM(balance),0) FROM items WHERE active=1"),
        "total_value": db.scalar(
            "SELECT COALESCE(SUM(balance*unit_cost),0) FROM items WHERE active=1"),
        "available_items": sum(v for k, v in sc.items() if k != OUT),
        "low": sc[WARNING], "critical": sc[CRITICAL], "out": sc[OUT], "normal": sc[NORMAL],
        "damaged_qty": db.scalar("SELECT COALESCE(SUM(damaged_qty),0) FROM items"),
        "received_today": db.scalar(
            "SELECT COALESCE(SUM(qty_in),0) FROM stock_ledger WHERE txn_type='RECEIPT' AND txn_date=?", (t,)),
        "issued_today": db.scalar(
            "SELECT COALESCE(SUM(qty_out),0) FROM stock_ledger WHERE txn_type='ISSUE' AND txn_date=?", (t,)),
        "returns_today": db.scalar(
            "SELECT COALESCE(SUM(qty_in),0) FROM stock_ledger WHERE txn_type='RETURN' AND txn_date=?", (t,)),
        "pending_docs": db.scalar("SELECT COUNT(*) FROM documents WHERE status='DRAFT'"),
        "recent_dn": [dict(r) for r in db.query(
            "SELECT * FROM documents WHERE doc_type='DN' ORDER BY id DESC LIMIT 8")],
        "recent_moves": [dict(r) for r in db.query(
            "SELECT * FROM stock_ledger ORDER BY id DESC LIMIT 12")],
        "top_issued": [dict(r) for r in db.query(
            """SELECT item_code, SUM(qty_out) q FROM stock_ledger WHERE txn_type='ISSUE'
               GROUP BY item_code ORDER BY q DESC LIMIT 8""")],
        "by_category": [dict(r) for r in db.query(
            """SELECT COALESCE(NULLIF(category,''),'(none)') k, SUM(balance) q,
                      SUM(balance*unit_cost) v FROM items WHERE active=1
               GROUP BY k ORDER BY q DESC LIMIT 10""")],
        "by_uom": [dict(r) for r in db.query(
            """SELECT COALESCE(NULLIF(uom,''),'(none)') k, SUM(balance) q FROM items
               WHERE active=1 GROUP BY k ORDER BY q DESC LIMIT 10""")],
        "by_warehouse": [dict(r) for r in db.query(
            """SELECT COALESCE(NULLIF(warehouse,''),'(none)') k, SUM(balance) q,
                      SUM(balance*unit_cost) v FROM items WHERE active=1
               GROUP BY k ORDER BY q DESC""")],
    }
    d["monthly"] = monthly_in_out(db)
    return d


def monthly_in_out(db: Database, months: int = 6) -> list[dict]:
    rows = db.query(
        """SELECT substr(txn_date,1,7) m,
                  SUM(CASE WHEN txn_type IN ('RECEIPT','RETURN') THEN qty_in ELSE 0 END) qin,
                  SUM(CASE WHEN txn_type='ISSUE' THEN qty_out ELSE 0 END) qout
           FROM stock_ledger GROUP BY m ORDER BY m DESC LIMIT ?""", (months,))
    return [dict(r) for r in reversed(rows)]


def alerts_panel(db: Database) -> dict[str, list[dict]]:
    return {
        "LOW STOCK": items_by_status(db, WARNING),
        "CRITICAL STOCK": items_by_status(db, CRITICAL),
        "OUT OF STOCK": items_by_status(db, OUT),
        "RECENT RECEIPTS": [dict(r) for r in db.query(
            "SELECT * FROM documents WHERE doc_type='GRN' ORDER BY id DESC LIMIT 10")],
        "RECENT ISSUES": [dict(r) for r in db.query(
            "SELECT * FROM documents WHERE doc_type='DN' ORDER BY id DESC LIMIT 10")],
        "RECENT RETURNS": [dict(r) for r in db.query(
            "SELECT * FROM documents WHERE doc_type='RET' ORDER BY id DESC LIMIT 10")],
        "STOCK VARIANCES": [dict(r) for r in db.query(
            """SELECT d.doc_no, d.doc_date, l.item_code, l.system_qty, l.counted_qty, l.variance
               FROM document_lines l JOIN documents d ON d.id=l.doc_id
               WHERE d.doc_type='CNT' AND l.variance<>0 ORDER BY d.id DESC LIMIT 25""")],
    }
