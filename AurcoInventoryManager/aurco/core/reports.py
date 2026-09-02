"""Report Center engine: 24 report definitions -> (title, columns, rows)."""
from __future__ import annotations

import re

import datetime as _dt
from typing import Any, Callable

from .database import Database
from . import services as S

Report = tuple[str, list[str], list[list[Any]]]

REPORT_LIST = [
    "Current Stock Report", "Low Stock Report", "Critical Stock Report",
    "Out of Stock Report", "Stock Movement Report", "Stock In Report",
    "Stock Out Report", "Delivery Note Report", "Return Report",
    "Damaged Stock Report", "Stock Adjustment Report", "Physical Count/Variance Report",
    "Item-wise Consumption", "Category-wise Stock", "Site-wise Consumption",
    "Monthly Inventory Report", "Date-wise Transactions", "Warehouse-wise Stock",
    "Location-wise Stock", "UOM-wise Stock", "Stock Valuation", "Fast Moving Items",
    "Slow Moving Items", "Non-Moving Items", "Consumption Trend", "Stock Transfer Report",
    "Audit Trail Report", "Item Master", "PR / MR-wise Issue Report",
    "Material Request Report", "Material Shortage Report", "Ready for Delivery Report",
    "Reserved Stock Report",
    "Project-wise Request Fulfilment",
    "Project Closure Reconciliation", "Project Material Ledger",
    "Project Loss & Damage Summary",
]


def _f(filters: dict, key: str, default: str = "") -> str:
    v = filters.get(key, default)
    return "" if v is None else str(v)


def _date_clause(filters: dict, col: str = "txn_date") -> tuple[str, list]:
    sql, p = "", []
    if _f(filters, "date_from"):
        sql += f" AND {col}>=?"
        p.append(_f(filters, "date_from"))
    if _f(filters, "date_to"):
        sql += f" AND {col}<=?"
        p.append(_f(filters, "date_to"))
    return sql, p


def _item_rows(db: Database, filters: dict, status: str | None = None) -> list[dict]:
    return S.search_items(db, _f(filters, "text"), _f(filters, "category"),
                          _f(filters, "warehouse"), status or "")


STOCK_COLS = ["Item Code", "Description", "Category", "UOM", "Warehouse", "Location",
              "Balance", "Reserved", "Free", "Min", "Max", "Unit Cost", "Value", "Status"]


def _stock_table(db: Database, rows: list[dict]) -> list[list[Any]]:
    out = []
    for r in rows:
        mn, crit = S.item_thresholds(db, r)
        out.append([r["code"], r["description"], r["category"], r["uom"], r["warehouse"],
                    r["location"], round(r["balance"] or 0, 2),
                    round(r.get("reserved", 0) or 0, 2),
                    round(r.get("free", r["balance"] or 0), 2), round(mn, 2),
                    round(r["max_level"] or 0, 2), round(r["unit_cost"] or 0, 2),
                    round((r["balance"] or 0) * (r["unit_cost"] or 0), 2), r["status"]])
    return out


LEDGER_COLS = ["Date", "Type", "Document", "Item Code", "In", "Out", "Balance",
               "Warehouse", "Party", "Reason", "User"]


def _ledger_table(rows) -> list[list[Any]]:
    return [[r["txn_date"], r["txn_type"], r["doc_no"], r["item_code"],
             round(r["qty_in"] or 0, 2), round(r["qty_out"] or 0, 2),
             round(r["balance_after"] or 0, 2), r["warehouse"], r["party"],
             r["reason"], r["username"]] for r in rows]


DOC_COLS = ["Doc No", "Date", "Status", "Party / Project", "Reference", "Lines", "Qty", "Value"]


def _doc_table(db: Database, doc_type: str, filters: dict, party_col: str) -> list[list[Any]]:
    sql = "SELECT * FROM documents WHERE doc_type=?"
    p: list[Any] = [doc_type]
    dc, dp = _date_clause(filters, "doc_date")
    sql += dc
    p += dp
    if _f(filters, "text"):
        like = f"%{_f(filters, 'text')}%"
        sql += (" AND (doc_no LIKE ? OR reference LIKE ? OR project LIKE ? OR supplier LIKE ?"
                " OR issued_to LIKE ? OR returned_by LIKE ?)")
        p += [like] * 6
    sql += " ORDER BY doc_date DESC, id DESC"
    out = []
    for d in db.query(sql, p):
        agg = db.one("SELECT COUNT(*) c, COALESCE(SUM(qty),0) q, COALESCE(SUM(total_cost),0) v"
                     " FROM document_lines WHERE doc_id=?", (d["id"],))
        out.append([d["doc_no"], d["doc_date"], d["status"],
                    d[party_col] or d["project"] or d["supplier"] or "",
                    d["reference"] or d["linked_doc"] or "", agg["c"],
                    round(agg["q"], 2), round(agg["v"], 2)])
    return out



def project_reconciliation(db: Database, project: str = "",
                           date_from: str = "", date_to: str = "") -> list[dict]:
    """Issued vs returned vs unaccounted, per item, for a project.

    The project-closure question: of everything that went out to a site, how
    much came back good, how much came back damaged, and how much is simply not
    accounted for?

        unaccounted = issued - returned_good - returned_damaged

    A return is attributed to the project of the Delivery Note it is booked
    against, so a RET that carries no project of its own still lands on the
    right job. Grouping is done in Python rather than SQL because that
    attribution needs a lookup per row, and a correlated sub-query in GROUP BY
    silently splits the same item into several rows.

    A negative balance means MORE came back than went out (material returned
    against the wrong project, or a return booked twice). It is surfaced as
    `over_returned` instead of being clamped away.
    """
    rows = db.query("""
        SELECT l.item_code, l.txn_type, l.qty_in, l.qty_out, l.reason, l.txn_date,
               COALESCE(i.description,'') AS description,
               COALESCE(i.uom,'')         AS uom,
               COALESCE(i.unit_cost,0)    AS unit_cost,
               COALESCE(NULLIF(d.project,''), NULLIF(d.department,'')) AS own_proj,
               d.linked_doc               AS linked
          FROM stock_ledger l
          LEFT JOIN items i     ON i.id = l.item_id
          LEFT JOIN documents d ON d.id = l.doc_id
         WHERE l.txn_type IN ('ISSUE','RETURN','DAMAGE')""")

    # doc_no -> project, so a return inherits the job of its delivery note
    doc_proj = {r["doc_no"]: (r["project"] or r["department"] or "")
                for r in db.query("SELECT doc_no, project, department FROM documents")}

    needle = (project or "").strip().lower()
    agg: dict[tuple, dict] = {}
    for r in rows:
        if date_from and (r["txn_date"] or "") < date_from:
            continue
        if date_to and (r["txn_date"] or "") > date_to:
            continue
        proj = r["own_proj"] or doc_proj.get(r["linked"] or "", "") or "(unassigned)"
        if needle and needle not in proj.lower():
            continue
        key = (proj, r["item_code"])
        a = agg.setdefault(key, {
            "project": proj, "item_code": r["item_code"],
            "description": r["description"], "uom": r["uom"],
            "unit_cost": float(r["unit_cost"] or 0),
            "issued": 0.0, "returned": 0.0, "damaged": 0.0})
        if r["txn_type"] == "ISSUE":
            a["issued"] += float(r["qty_out"] or 0)
        elif r["txn_type"] == "RETURN":
            a["returned"] += float(r["qty_in"] or 0)
        else:
            # DAMAGE rows keep the quantity in the reason text, not in qty_in
            m = re.search(r"([\d.]+)", str(r["reason"] or ""))
            if m:
                a["damaged"] += float(m.group(1))

    out = []
    for a in agg.values():
        if a["issued"] <= 0 and a["returned"] <= 0 and a["damaged"] <= 0:
            continue
        balance = a["issued"] - a["returned"] - a["damaged"]
        a["unaccounted"] = max(0.0, balance)
        a["over_returned"] = max(0.0, -balance)
        a["loss_value"] = a["unaccounted"] * a["unit_cost"]
        a["damage_value"] = a["damaged"] * a["unit_cost"]
        a["return_pct"] = (((a["returned"] + a["damaged"]) / a["issued"] * 100.0)
                           if a["issued"] else 0.0)
        out.append(a)
    out.sort(key=lambda r: (r["project"], r["item_code"]))
    return out


def build_report(db: Database, name: str, filters: dict | None = None) -> Report:
    f = filters or {}
    period = ""
    if _f(f, "date_from") or _f(f, "date_to"):
        period = f"  ({_f(f,'date_from') or 'start'} to {_f(f,'date_to') or 'today'})"
    title = name + period

    if name == "Current Stock Report":
        return title, STOCK_COLS, _stock_table(db, _item_rows(db, f))
    if name == "Low Stock Report":
        return title, STOCK_COLS, _stock_table(db, _item_rows(db, f, S.WARNING))
    if name == "Critical Stock Report":
        return title, STOCK_COLS, _stock_table(db, _item_rows(db, f, S.CRITICAL))
    if name == "Out of Stock Report":
        return title, STOCK_COLS, _stock_table(db, _item_rows(db, f, S.OUT))
    if name == "Item Master":
        cols = ["Code", "Description", "Category", "Sub", "UOM", "Brand", "Model", "Barcode",
                "Min", "Max", "Balance", "Reserved", "Free", "Warehouse", "Location",
                "Rack", "Active"]
        _res = S.reserved_map(db)
        rows = [[r["code"], r["description"], r["category"], r["subcategory"], r["uom"],
                 r["brand"], r["model"], r["barcode"], r["min_level"], r["max_level"],
                 r["balance"], round(_res.get(r["id"], 0), 2),
                 round(max(0.0, (r["balance"] or 0) - _res.get(r["id"], 0)), 2),
                 r["warehouse"], r["location"], r["rack"],
                 "Yes" if r["active"] else "No"]
                for r in db.query("SELECT * FROM items ORDER BY code")]
        return title, cols, rows

    if name in ("Stock Movement Report", "Stock In Report", "Stock Out Report",
                "Date-wise Transactions"):
        sql = "SELECT * FROM stock_ledger WHERE 1=1"
        p: list[Any] = []
        dc, dp = _date_clause(f)
        sql += dc
        p += dp
        if name == "Stock In Report":
            sql += " AND txn_type IN ('RECEIPT','RETURN','TRANSFER_IN','OPENING')"
        elif name == "Stock Out Report":
            sql += " AND txn_type IN ('ISSUE','TRANSFER_OUT')"
        if _f(f, "text"):
            like = f"%{_f(f,'text')}%"
            sql += " AND (item_code LIKE ? OR doc_no LIKE ? OR party LIKE ?)"
            p += [like] * 3
        if _f(f, "warehouse"):
            sql += " AND warehouse=?"
            p.append(_f(f, "warehouse"))
        sql += " ORDER BY txn_date DESC, id DESC LIMIT 20000"
        return title, LEDGER_COLS, _ledger_table(db.query(sql, p))

    if name == "Delivery Note Report":
        cols = ["Doc No", "Date", "Status", "Issued To", "Project / Site", "Reference",
                "Item Code", "Description", "UOM", "Qty", "Unit Cost", "Total", "User"]
        sql = ("SELECT d.doc_no,d.doc_date,d.status,d.issued_to,d.project,d.reference,"
               "l.item_code,l.description,l.uom,l.qty,l.unit_cost,l.total_cost,d.created_by"
               " FROM document_lines l JOIN documents d ON d.id=l.doc_id WHERE d.doc_type='DN'")
        p = []
        dc, dp = _date_clause(f, "d.doc_date")
        sql += dc
        p += dp
        if _f(f, "text"):
            like = f"%{_f(f, 'text')}%"
            sql += (" AND (d.doc_no LIKE ? OR d.reference LIKE ? OR d.project LIKE ? OR d.issued_to LIKE ?"
                    " OR l.item_code LIKE ? OR l.description LIKE ?)")
            p += [like] * 6
        sql += " ORDER BY d.doc_date DESC, d.id DESC, l.id"
        return title, cols, [list(r) for r in db.query(sql, p)]
    if name == "Return Report":
        return title, DOC_COLS, _doc_table(db, "RET", f, "returned_by")
    if name == "Stock Adjustment Report":
        cols = ["Doc No", "Date", "Item Code", "Description", "Qty (+/-)", "Reason", "Remarks", "User"]
        sql = ("SELECT d.doc_no,d.doc_date,l.item_code,l.description,l.qty,d.reason,l.remarks,"
               "d.created_by FROM document_lines l JOIN documents d ON d.id=l.doc_id"
               " WHERE d.doc_type='ADJ'")
        p = []
        dc, dp = _date_clause(f, "d.doc_date")
        sql += dc + " ORDER BY d.id DESC"
        p += dp
        return title, cols, [list(r) for r in db.query(sql, p)]
    if name == "Stock Transfer Report":
        cols = ["Doc No", "Date", "Item Code", "Qty", "From WH", "To WH", "From Loc", "To Loc",
                "Responsible"]
        sql = ("SELECT d.doc_no,d.doc_date,l.item_code,l.qty,d.warehouse,d.to_warehouse,"
               "d.location,d.to_location,COALESCE(NULLIF(d.received_by,''),d.issued_to)"
               " FROM document_lines l JOIN documents d ON d.id=l.doc_id WHERE d.doc_type='TRF'")
        dc, dp = _date_clause(f, "d.doc_date")
        return title, cols, [list(r) for r in db.query(sql + dc + " ORDER BY d.id DESC", dp)]

    if name == "Damaged Stock Report":
        cols = ["Item Code", "Description", "UOM", "Damaged Qty", "Good Balance", "Warehouse",
                "Last Damaged Doc"]
        rows = []
        for r in db.query("SELECT * FROM items WHERE damaged_qty>0 ORDER BY damaged_qty DESC"):
            last = db.one("SELECT doc_no FROM stock_ledger WHERE item_id=? AND txn_type='DAMAGE'"
                          " ORDER BY id DESC LIMIT 1", (r["id"],))
            rows.append([r["code"], r["description"], r["uom"], r["damaged_qty"], r["balance"],
                         r["warehouse"], last["doc_no"] if last else ""])
        return title, cols, rows

    if name == "Physical Count/Variance Report":
        cols = ["Count No", "Date", "Item Code", "Description", "System Qty", "Counted Qty",
                "Variance", "Result", "Remarks"]
        sql = ("SELECT d.doc_no,d.doc_date,l.item_code,l.description,l.system_qty,l.counted_qty,"
               "l.variance,l.remarks FROM document_lines l JOIN documents d ON d.id=l.doc_id"
               " WHERE d.doc_type='CNT'")
        dc, dp = _date_clause(f, "d.doc_date")
        rows = []
        for r in db.query(sql + dc + " ORDER BY d.id DESC", dp):
            v = r["variance"] or 0
            rows.append([r["doc_no"], r["doc_date"], r["item_code"], r["description"],
                         r["system_qty"], r["counted_qty"], v,
                         "Excess" if v > 0 else ("Shortage" if v < 0 else "Match"), r["remarks"]])
        return title, cols, rows

    if name in ("Item-wise Consumption", "Fast Moving Items", "Slow Moving Items",
                "Non-Moving Items"):
        dc, dp = _date_clause(f)
        base = ("SELECT i.code, i.description, i.category, i.uom, i.balance,"
                " COALESCE((SELECT SUM(qty_out) FROM stock_ledger l WHERE l.item_id=i.id"
                f"   AND l.txn_type='ISSUE' {dc.replace('txn_date','l.txn_date')}),0) issued,"
                " COALESCE((SELECT COUNT(*) FROM stock_ledger l WHERE l.item_id=i.id"
                "   AND l.txn_type='ISSUE'),0) times"
                " FROM items i WHERE i.active=1")
        rows = [dict(r) for r in db.query(base, dp)]
        if name == "Fast Moving Items":
            rows = sorted(rows, key=lambda r: -r["issued"])[:50]
        elif name == "Slow Moving Items":
            rows = sorted([r for r in rows if r["issued"] > 0], key=lambda r: r["issued"])[:50]
        elif name == "Non-Moving Items":
            rows = [r for r in rows if (r["issued"] or 0) == 0]
        else:
            rows = sorted(rows, key=lambda r: -r["issued"])
        cols = ["Item Code", "Description", "Category", "UOM", "Balance", "Issued Qty", "Times Issued"]
        return title, cols, [[r["code"], r["description"], r["category"], r["uom"],
                              round(r["balance"] or 0, 2), round(r["issued"] or 0, 2), r["times"]]
                             for r in rows]

    if name == "Category-wise Stock":
        cols = ["Category", "Items", "Total Qty", "Total Value"]
        rows = db.query("""SELECT COALESCE(NULLIF(category,''),'(none)') c, COUNT(*) n,
                           SUM(balance) q, SUM(balance*unit_cost) v FROM items WHERE active=1
                           GROUP BY c ORDER BY v DESC""")
        return title, cols, [[r["c"], r["n"], round(r["q"] or 0, 2), round(r["v"] or 0, 2)]
                             for r in rows]
    if name == "Warehouse-wise Stock":
        cols = ["Warehouse", "Items", "Total Qty", "Total Value"]
        rows = db.query("""SELECT COALESCE(NULLIF(warehouse,''),'(none)') c, COUNT(*) n,
                           SUM(balance) q, SUM(balance*unit_cost) v FROM items WHERE active=1
                           GROUP BY c ORDER BY v DESC""")
        return title, cols, [[r["c"], r["n"], round(r["q"] or 0, 2), round(r["v"] or 0, 2)]
                             for r in rows]
    if name == "Location-wise Stock":
        cols = ["Warehouse", "Location", "Rack/Bin", "Items", "Total Qty"]
        rows = db.query("""SELECT warehouse, location, rack, COUNT(*) n, SUM(balance) q
                           FROM items WHERE active=1 GROUP BY warehouse, location, rack
                           ORDER BY warehouse, location""")
        return title, cols, [[r["warehouse"], r["location"], r["rack"], r["n"],
                              round(r["q"] or 0, 2)] for r in rows]
    if name == "UOM-wise Stock":
        cols = ["UOM", "Items", "Total Qty", "Total Value"]
        rows = db.query("""SELECT COALESCE(NULLIF(uom,''),'(none)') c, COUNT(*) n, SUM(balance) q,
                           SUM(balance*unit_cost) v FROM items WHERE active=1 GROUP BY c
                           ORDER BY q DESC""")
        return title, cols, [[r["c"], r["n"], round(r["q"] or 0, 2), round(r["v"] or 0, 2)]
                             for r in rows]
    if name == "Site-wise Consumption":
        cols = ["Project / Site", "Delivery Notes", "Total Qty Issued", "Value"]
        rows = db.query("""SELECT COALESCE(NULLIF(d.project,''),'(unassigned)') s,
                             COUNT(DISTINCT d.id) n, SUM(l.qty) q, SUM(l.total_cost) v
                           FROM documents d JOIN document_lines l ON l.doc_id=d.id
                           WHERE d.doc_type='DN' GROUP BY s ORDER BY q DESC""")
        return title, cols, [[r["s"], r["n"], round(r["q"] or 0, 2), round(r["v"] or 0, 2)]
                             for r in rows]
    if name == "Stock Valuation":
        cols = ["Item Code", "Description", "UOM", "Balance", "Unit Cost", "Stock Value", "Category"]
        rows = db.query("""SELECT * FROM items WHERE active=1 ORDER BY balance*unit_cost DESC""")
        data = [[r["code"], r["description"], r["uom"], round(r["balance"] or 0, 2),
                 round(r["unit_cost"] or 0, 2), round((r["balance"] or 0) * (r["unit_cost"] or 0), 2),
                 r["category"]] for r in rows]
        total = sum(x[5] for x in data)
        data.append(["", "", "", "", "TOTAL", round(total, 2), ""])
        return title, cols, data
    if name in ("Monthly Inventory Report", "Consumption Trend"):
        cols = ["Month", "Received", "Returned", "Issued", "Adjustments +", "Adjustments -",
                "Net Movement"]
        rows = db.query("""SELECT substr(txn_date,1,7) m,
              SUM(CASE WHEN txn_type='RECEIPT' THEN qty_in ELSE 0 END) rec,
              SUM(CASE WHEN txn_type='RETURN' THEN qty_in ELSE 0 END) ret,
              SUM(CASE WHEN txn_type='ISSUE' THEN qty_out ELSE 0 END) iss,
              SUM(CASE WHEN txn_type='ADJUSTMENT' THEN qty_in ELSE 0 END) ap,
              SUM(CASE WHEN txn_type='ADJUSTMENT' THEN qty_out ELSE 0 END) am
              FROM stock_ledger GROUP BY m ORDER BY m DESC LIMIT 24""")
        return title, cols, [[r["m"], round(r["rec"], 2), round(r["ret"], 2), round(r["iss"], 2),
                              round(r["ap"], 2), round(r["am"], 2),
                              round(r["rec"] + r["ret"] - r["iss"] + r["ap"] - r["am"], 2)]
                             for r in rows]
    if name in ("PR / MR-wise Issue Report", "PR-wise Issue Report"):
        cols = ["PR / MR Number", "DN Number", "Date", "Project / Site", "Issued To", "Item Code",
                "Description", "UOM", "Qty", "Value", "Remarks"]
        sql = ("SELECT l.pr_no, d.doc_no, d.doc_date, d.project, d.issued_to, l.item_code,"
               " l.description, l.uom, l.qty, l.total_cost, l.remarks"
               " FROM document_lines l JOIN documents d ON d.id=l.doc_id"
               " WHERE d.doc_type='DN'")
        p = []
        dc, dp = _date_clause(f, "d.doc_date")
        sql += dc
        p += dp
        if _f(f, "text"):
            like = f"%{_f(f,'text')}%"
            sql += " AND (l.pr_no LIKE ? OR d.doc_no LIKE ? OR l.item_code LIKE ?)"
            p += [like] * 3
        sql += " ORDER BY l.pr_no, d.doc_date DESC"
        rows = [[r["pr_no"] or "(no PR)", r["doc_no"], r["doc_date"], r["project"],
                 r["issued_to"], r["item_code"], r["description"], r["uom"],
                 round(r["qty"] or 0, 2), round(r["total_cost"] or 0, 2), r["remarks"]]
                for r in db.query(sql, p)]
        return title, cols, rows

    if name in ("Material Request Report", "Material Shortage Report",
                "Ready for Delivery Report"):
        from . import material as _M
        cols = ["MR Number", "Date", "Project / Site", "Item Code", "Description", "UOM",
                "Requested", "Prepared", "Delivered", "Pending", "In Stock", "Short By",
                "Fulfilment", "PR No.", "DN No.", "Requested By", "Prepared By"]
        sql = """SELECT m.mr_no, m.mr_date,
                        COALESCE(NULLIF(m.project_id,''), m.site) AS proj,
                        l.item_code, l.description, l.uom, l.qty_requested, l.qty_prepared,
                        l.qty_delivered, l.status, l.pr_no, l.dn_no, m.requested_by,
                        l.prepared_by,
                        COALESCE((SELECT balance FROM items i WHERE i.id=l.item_id),0) AS bal
                 FROM mr_lines l JOIN material_requests m ON m.id=l.mr_id WHERE 1=1"""
        p: list[Any] = []
        dc, dp = _date_clause(f, "m.mr_date")
        sql += dc
        p += dp
        if name == "Material Shortage Report":
            sql += " AND l.qty_requested > l.qty_prepared AND l.status<>'Cancelled'"
        elif name == "Ready for Delivery Report":
            sql += " AND (l.qty_prepared - l.qty_delivered) > 0 AND m.status<>'Cancelled'"
        if _f(f, "text"):
            like = f"%{_f(f,'text')}%"
            sql += (" AND (m.mr_no LIKE ? OR m.project_id LIKE ? OR m.site LIKE ?"
                    " OR l.item_code LIKE ? OR l.pr_no LIKE ?)")
            p += [like] * 5
        sql += " ORDER BY m.mr_date DESC, m.mr_no, CAST(l.line_no AS INTEGER)"
        rows = []
        for r in db.query(sql, p):
            pending = max(0.0, (r["qty_requested"] or 0) - (r["qty_delivered"] or 0))
            short = max(0.0, (r["qty_requested"] or 0) - (r["qty_prepared"] or 0))
            rows.append([r["mr_no"], r["mr_date"], r["proj"], r["item_code"], r["description"],
                         r["uom"], round(r["qty_requested"] or 0, 2),
                         round(r["qty_prepared"] or 0, 2), round(r["qty_delivered"] or 0, 2),
                         round(pending, 2), round(r["bal"] or 0, 2), round(short, 2),
                         r["status"], r["pr_no"], r["dn_no"], r["requested_by"],
                         r["prepared_by"]])
        return title, cols, rows

    if name == "Reserved Stock Report":
        # every item whose stock is promised to an open request but not yet
        # delivered -- the audit trail behind the Reserved column
        cols = ["Item Code", "Description", "UOM", "Balance", "Reserved", "Free to Use",
                "Warehouse", "MR Number", "Project / Site", "Reserved Qty",
                "Line Status", "Prepared By", "PR / MR No."]
        sql = """SELECT i.code, i.description, i.uom, i.balance, i.warehouse, i.id AS iid,
                        m.mr_no,
                        COALESCE(NULLIF(m.project_id,''), NULLIF(m.site,''), '') AS proj,
                        MAX(l.qty_prepared - l.qty_delivered, 0) AS q,
                        l.status, l.prepared_by, l.pr_no
                   FROM mr_lines l JOIN material_requests m ON m.id=l.mr_id
                   JOIN items i ON i.id=l.item_id
                  WHERE l.status IN ('Preparing','Ready','Partially Delivered')
                    AND m.status<>'Cancelled' AND l.qty_prepared > l.qty_delivered"""
        p = []
        if _f(f, "warehouse"):
            sql += " AND i.warehouse=?"
            p.append(_f(f, "warehouse"))
        if _f(f, "category"):
            sql += " AND i.category=?"
            p.append(_f(f, "category"))
        if _f(f, "text"):
            like = f"%{_f(f,'text')}%"
            sql += (" AND (i.code LIKE ? OR i.description LIKE ? OR m.mr_no LIKE ?"
                    " OR m.project_id LIKE ? OR m.site LIKE ? OR l.pr_no LIKE ?)")
            p += [like] * 6
        sql += " ORDER BY i.code, m.mr_no"
        res = S.reserved_map(db)
        rows = []
        for r in db.query(sql, p):
            tot = res.get(r["iid"], 0.0)
            rows.append([r["code"], r["description"], r["uom"], round(r["balance"] or 0, 2),
                         round(tot, 2), round(max(0.0, (r["balance"] or 0) - tot), 2),
                         r["warehouse"], r["mr_no"], r["proj"], round(r["q"] or 0, 2),
                         r["status"], r["prepared_by"] or "", r["pr_no"] or ""])
        return title, cols, rows

    if name == "Project-wise Request Fulfilment":
        cols = ["Project / Site", "Requests", "Lines", "Requested Qty", "Prepared Qty",
                "Delivered Qty", "Pending Qty", "Fulfilment %"]
        rows = []
        for r in db.query("""SELECT COALESCE(NULLIF(m.project_id,''), NULLIF(m.site,''),
                                    '(unassigned)') AS proj,
                               COUNT(DISTINCT m.id) n_req, COUNT(l.id) n_lines,
                               COALESCE(SUM(l.qty_requested),0) q_req,
                               COALESCE(SUM(l.qty_prepared),0) q_prep,
                               COALESCE(SUM(l.qty_delivered),0) q_del
                             FROM material_requests m LEFT JOIN mr_lines l ON l.mr_id=m.id
                             GROUP BY proj ORDER BY q_req DESC"""):
            pct = (r["q_del"] / r["q_req"] * 100) if r["q_req"] else 0
            rows.append([r["proj"], r["n_req"], r["n_lines"], round(r["q_req"], 2),
                         round(r["q_prep"], 2), round(r["q_del"], 2),
                         round(max(0.0, r["q_req"] - r["q_del"]), 2), round(pct, 1)])
        return title, cols, rows


    if name == "Project Closure Reconciliation":
        proj = _f(f, "project") or _f(f, "text")
        cur = db.get_setting("currency", "")
        cols = ["Project", "Item Code", "Description", "UOM", "Issued", "Returned",
                "Damaged", "Unaccounted", "Over-Returned", "Return %",
                f"Loss Value ({cur})"]
        data = project_reconciliation(db, proj, _f(f, "date_from"), _f(f, "date_to"))
        rows = [[r["project"], r["item_code"], r["description"], r["uom"],
                 round(r["issued"], 2), round(r["returned"], 2),
                 round(r["damaged"], 2), round(r["unaccounted"], 2),
                 round(r["over_returned"], 2), round(r["return_pct"], 1),
                 round(r["loss_value"], 2)] for r in data]
        if rows:
            rows.append(["TOTAL", "", f"{len(rows)} item(s)", "",
                         round(sum(x[4] for x in rows), 2),
                         round(sum(x[5] for x in rows), 2),
                         round(sum(x[6] for x in rows), 2),
                         round(sum(x[7] for x in rows), 2),
                         round(sum(x[8] for x in rows), 2), "",
                         round(sum(x[10] for x in rows), 2)])
        return title, cols, rows

    if name == "Project Loss & Damage Summary":
        proj = _f(f, "project") or _f(f, "text")
        cur = db.get_setting("currency", "")
        data = project_reconciliation(db, proj, _f(f, "date_from"), _f(f, "date_to"))
        agg: dict[str, dict] = {}
        for r in data:
            a = agg.setdefault(r["project"], {"items": 0, "issued": 0.0,
                                              "returned": 0.0, "damaged": 0.0,
                                              "lost": 0.0, "value": 0.0,
                                              "short_items": 0})
            a["items"] += 1
            a["issued"] += r["issued"]
            a["returned"] += r["returned"]
            a["damaged"] += r["damaged"]
            a["lost"] += r["unaccounted"]
            a["value"] += r["loss_value"] + r["damage_value"]
            if r["unaccounted"] > 1e-9:
                a["short_items"] += 1
        cols = ["Project", "Items", "Issued", "Returned", "Damaged", "Unaccounted",
                "Items Short", "Recovery %", f"Loss + Damage Value ({cur})"]
        rows = []
        for k, a in sorted(agg.items(), key=lambda kv: -kv[1]["value"]):
            rec = ((a["returned"] + a["damaged"]) / a["issued"] * 100.0
                   if a["issued"] else 0.0)
            rows.append([k, a["items"], round(a["issued"], 2),
                         round(a["returned"], 2), round(a["damaged"], 2),
                         round(a["lost"], 2), a["short_items"], round(rec, 1),
                         round(a["value"], 2)])
        if rows:
            rows.append(["TOTAL", sum(x[1] for x in rows),
                         round(sum(x[2] for x in rows), 2),
                         round(sum(x[3] for x in rows), 2),
                         round(sum(x[4] for x in rows), 2),
                         round(sum(x[5] for x in rows), 2),
                         sum(x[6] for x in rows), "",
                         round(sum(x[8] for x in rows), 2)])
        return title, cols, rows

    if name == "Project Material Ledger":
        proj = _f(f, "project") or _f(f, "text")
        cols = ["Date", "Type", "Document", "Item Code", "Description", "UOM",
                "Out", "In", "Project", "Party", "Reason", "User"]
        sql = """SELECT l.*, COALESCE(i.description,'') des, COALESCE(i.uom,'') uom,
                        COALESCE(NULLIF(d.project,''), NULLIF(d.department,''),
                                 NULLIF((SELECT p.project FROM documents p
                                          WHERE p.doc_no = d.linked_doc LIMIT 1),''),
                                 '') proj
                   FROM stock_ledger l
                   LEFT JOIN items i ON i.id=l.item_id
                   LEFT JOIN documents d ON d.id=l.doc_id
                  WHERE l.txn_type IN ('ISSUE','RETURN','DAMAGE')"""
        p2: list[Any] = []
        if proj:
            sql += (" AND COALESCE(NULLIF(d.project,''), NULLIF(d.department,''),"
                    "  (SELECT p.project FROM documents p"
                    "    WHERE p.doc_no = d.linked_doc LIMIT 1)) LIKE ?")
            p2.append(f"%{proj}%")
        dc, dp = _date_clause(f, "l.txn_date")
        sql += dc + " ORDER BY l.txn_date, l.id"
        p2 += dp
        rows = [[r["txn_date"], r["txn_type"], r["doc_no"], r["item_code"], r["des"],
                 r["uom"], round(r["qty_out"] or 0, 2), round(r["qty_in"] or 0, 2),
                 r["proj"], r["party"], r["reason"], r["username"]]
                for r in db.query(sql, p2)]
        return title, cols, rows

    if name == "Audit Trail Report":
        cols = ["Timestamp", "User", "Action", "Entity", "Reference", "Details"]
        sql = "SELECT * FROM audit_trail WHERE 1=1"
        dc, dp = _date_clause(f, "substr(ts,1,10)")
        sql += dc + " ORDER BY id DESC LIMIT 10000"
        return title, cols, [[r["ts"], r["username"], r["action"], r["entity"], r["entity_id"],
                              r["details"]] for r in db.query(sql, dp)]

    return title, ["Info"], [["Report not implemented."]]
