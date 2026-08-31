"""Sample/demo dataset so the dashboard and reports are testable immediately."""
from __future__ import annotations

import datetime as _dt
import random

from .database import Database
from . import services as S

CATEGORIES = {
    "Electrical": ["Cables", "Breakers", "Lighting"],
    "Mechanical": ["Bearings", "Valves", "Fasteners"],
    "Safety / PPE": ["Head", "Hand", "Body"],
    "Consumables": ["Adhesives", "Cleaning", "Welding"],
    "Tools": ["Hand Tools", "Power Tools", "Measuring"],
    "Civil": ["Cement", "Paint", "Hardware"],
}
UOMS = ["PCS", "MTR", "BOX", "SET", "KG", "LTR", "ROLL", "PKT"]
WAREHOUSES = ["Main Warehouse", "Site Store - Dammam", "Yard Store"]
SITES = ["Jubail Refinery Project", "Dammam Industrial Park", "Ras Tanura Expansion",
         "King Fahd Causeway Maint."]
SUPPLIERS = ["Al Faisal Trading Est.", "Gulf Industrial Supplies", "Eastern Electric Co.",
             "SAFCO Hardware", "Delta Engineering Supplies"]
BRANDS = ["Schneider", "ABB", "SKF", "3M", "Bosch", "Honeywell", "AURCO", "Siemens"]
NAMES = ["Ahmed Khalid", "Bilal Rahman", "Suresh Kumar", "Mohammed Ali", "Imran Sheikh",
         "Rakesh Nair", "Zain Shami"]
DEPTS = ["Maintenance", "Electrical", "Civil Works", "HSE", "Logistics", "Mechanical"]

PRODUCTS = [
    ("XLPE Power Cable 3C x 25mm", "Electrical", "Cables", "MTR", 42.0),
    ("XLPE Power Cable 4C x 16mm", "Electrical", "Cables", "MTR", 33.5),
    ("MCB 32A Triple Pole", "Electrical", "Breakers", "PCS", 78.0),
    ("MCCB 100A", "Electrical", "Breakers", "PCS", 340.0),
    ("LED Flood Light 200W", "Electrical", "Lighting", "PCS", 165.0),
    ("LED Tube Light 18W", "Electrical", "Lighting", "PCS", 22.0),
    ("Cable Gland 25mm Brass", "Electrical", "Cables", "PCS", 9.5),
    ("Deep Groove Ball Bearing 6205", "Mechanical", "Bearings", "PCS", 46.0),
    ("Tapered Roller Bearing 30206", "Mechanical", "Bearings", "PCS", 88.0),
    ("Gate Valve 2 inch CS", "Mechanical", "Valves", "PCS", 260.0),
    ("Ball Valve 1 inch SS316", "Mechanical", "Valves", "PCS", 175.0),
    ("Hex Bolt M12 x 60 Grade 8.8", "Mechanical", "Fasteners", "BOX", 95.0),
    ("Hex Nut M12 Zinc Plated", "Mechanical", "Fasteners", "BOX", 42.0),
    ("Flat Washer M12", "Mechanical", "Fasteners", "PKT", 18.0),
    ("Safety Helmet White", "Safety / PPE", "Head", "PCS", 35.0),
    ("Safety Goggles Clear", "Safety / PPE", "Head", "PCS", 14.0),
    ("Cut Resistant Gloves L", "Safety / PPE", "Hand", "PCS", 21.0),
    ("Leather Welding Gloves", "Safety / PPE", "Hand", "PCS", 28.0),
    ("Hi-Vis Safety Vest", "Safety / PPE", "Body", "PCS", 26.0),
    ("Safety Harness Full Body", "Safety / PPE", "Body", "SET", 310.0),
    ("Silicone Sealant Clear", "Consumables", "Adhesives", "PCS", 16.0),
    ("Epoxy Adhesive 2-Part", "Consumables", "Adhesives", "SET", 58.0),
    ("Industrial Degreaser 5L", "Consumables", "Cleaning", "LTR", 44.0),
    ("Cotton Rags 10kg Bag", "Consumables", "Cleaning", "KG", 32.0),
    ("Welding Electrode 3.2mm E7018", "Consumables", "Welding", "KG", 27.0),
    ("Cutting Disc 4 inch", "Consumables", "Welding", "BOX", 68.0),
    ("Adjustable Wrench 12 inch", "Tools", "Hand Tools", "PCS", 54.0),
    ("Screwdriver Set 6pc", "Tools", "Hand Tools", "SET", 72.0),
    ("Cordless Drill 18V", "Tools", "Power Tools", "SET", 640.0),
    ("Angle Grinder 5 inch", "Tools", "Power Tools", "PCS", 285.0),
    ("Digital Multimeter", "Tools", "Measuring", "PCS", 190.0),
    ("Measuring Tape 8m", "Tools", "Measuring", "PCS", 24.0),
    ("Portland Cement 50kg", "Civil", "Cement", "BOX", 19.0),
    ("Enamel Paint White 4L", "Civil", "Paint", "LTR", 62.0),
    ("Paint Brush 3 inch", "Civil", "Paint", "PCS", 11.0),
    ("Anchor Bolt M16 x 150", "Civil", "Hardware", "PCS", 13.5),
    ("Steel Wire Rope 10mm", "Civil", "Hardware", "MTR", 21.0),
    ("PVC Conduit Pipe 25mm", "Electrical", "Cables", "MTR", 7.5),
    ("Junction Box IP65", "Electrical", "Breakers", "PCS", 38.0),
    ("Grease Cartridge EP2", "Consumables", "Cleaning", "PCS", 23.0),
]


def is_seeded(db: Database) -> bool:
    return bool(db.scalar("SELECT COUNT(*) FROM items"))


def seed(db: Database, force: bool = False) -> None:
    if is_seeded(db) and not force:
        return
    rnd = random.Random(20260817)

    for name, subs in CATEGORIES.items():
        db.execute("INSERT OR IGNORE INTO categories(name,parent) VALUES(?,'')", (name,))
    for u in UOMS:
        db.execute("INSERT OR IGNORE INTO uoms(name) VALUES(?)", (u,))
    for w in WAREHOUSES:
        db.execute("INSERT OR IGNORE INTO warehouses(name) VALUES(?)", (w,))
        for loc in ("Rack A", "Rack B", "Rack C", "Open Yard"):
            db.execute("INSERT OR IGNORE INTO locations(warehouse,name) VALUES(?,?)", (w, loc))
    for s in SITES:
        db.execute("INSERT OR IGNORE INTO sites(name) VALUES(?)", (s,))
    for s in SUPPLIERS:
        db.execute("INSERT OR IGNORE INTO suppliers(name) VALUES(?)", (s,))
    db.commit()

    item_ids: list[int] = []
    for i, (desc, cat, sub, uom, cost) in enumerate(PRODUCTS, 1):
        mx = rnd.choice([100, 150, 200, 300, 500])
        data = {
            "code": f"ITM-{str(i).zfill(5)}", "description": desc,
            "short_desc": desc.split(" ")[0], "category": cat, "subcategory": sub,
            "uom": uom, "brand": rnd.choice(BRANDS), "model": f"MDL-{rnd.randint(1000,9999)}",
            "specification": "As per standard specification",
            "barcode": f"629{str(1000000 + i * 137).zfill(9)}"[:13],
            "alt_code": f"ALT-{str(i).zfill(4)}",
            "min_level": mx * 0.4, "max_level": mx, "reorder_level": mx * 0.5,
            "critical_level": mx * 0.2, "threshold_mode": "GLOBAL",
            "opening_balance": 0, "unit_cost": cost,
            "warehouse": rnd.choice(WAREHOUSES), "location": rnd.choice(["Rack A", "Rack B", "Rack C"]),
            "rack": f"{rnd.choice('ABC')}-{rnd.randint(1,9):02d}-{rnd.randint(1,9):02d}",
            "remarks": "", "active": 1,
        }
        item_ids.append(S.save_item(db, data))

    today = _dt.date.today()

    def d(offset: int) -> str:
        return (today - _dt.timedelta(days=offset)).isoformat()

    # ---- opening receipts (5 months back)
    for gi in range(6):
        day = 150 - gi * 25
        chunk = rnd.sample(item_ids, 12)
        lines = []
        for iid in chunk:
            cost = db.scalar("SELECT unit_cost FROM items WHERE id=?", (iid,))
            lines.append(S.Line(item_id=iid, qty=rnd.choice([50, 80, 100, 120, 200]),
                                unit_cost=cost, batch=f"B{rnd.randint(1000,9999)}"))
        S.post_receipt(db, S.DocHeader(
            doc_type="GRN", doc_date=d(day), supplier=rnd.choice(SUPPLIERS),
            reference=f"PO-{2026}-{rnd.randint(100,999)}", warehouse=rnd.choice(WAREHOUSES),
            location="Rack A", received_by=rnd.choice(NAMES),
            remarks="Initial stocking"), lines)

    # ---- ongoing receipts + issues + returns
    dn_numbers: list[tuple[str, list]] = []
    for day in range(120, -1, -1):
        date = d(day)
        if rnd.random() < 0.22:
            chunk = rnd.sample(item_ids, rnd.randint(2, 6))
            lines = [S.Line(item_id=i, qty=rnd.choice([20, 30, 40, 60, 100]),
                            unit_cost=db.scalar("SELECT unit_cost FROM items WHERE id=?", (i,)))
                     for i in chunk]
            S.post_receipt(db, S.DocHeader(
                doc_type="GRN", doc_date=date, supplier=rnd.choice(SUPPLIERS),
                reference=f"PO-2026-{rnd.randint(100,999)}",
                warehouse=rnd.choice(WAREHOUSES), received_by=rnd.choice(NAMES)), lines)

        for _ in range(rnd.randint(0, 3)):
            chunk = rnd.sample(item_ids, rnd.randint(1, 5))
            lines = []
            for i in chunk:
                bal = db.scalar("SELECT balance FROM items WHERE id=?", (i,))
                if bal <= 1:
                    continue
                qty = min(bal, rnd.choice([2, 5, 8, 10, 15, 25]))
                lines.append(S.Line(item_id=i, qty=qty,
                                    unit_cost=db.scalar("SELECT unit_cost FROM items WHERE id=?", (i,)),
                                    remarks=""))
            if not lines:
                continue
            h = S.DocHeader(doc_type="DN", doc_date=date, project=rnd.choice(SITES),
                            department=rnd.choice(DEPTS), requested_by=rnd.choice(NAMES),
                            issued_to=rnd.choice(NAMES), received_by=rnd.choice(NAMES),
                            reference=f"MR-2026-{rnd.randint(100,999)}",
                            vehicle=f"{rnd.randint(1000,9999)} {rnd.choice(['ABC','DEF','XYZ'])}",
                            driver=rnd.choice(NAMES), purpose="Site consumption",
                            warehouse=rnd.choice(WAREHOUSES))
            dn = S.post_issue(db, h, lines)
            dn_numbers.append((dn, lines))

            if rnd.random() < 0.13 and lines:
                ln = lines[0]
                rq = max(1, round(ln.qty * rnd.choice([0.2, 0.35, 0.5])))
                cond = "DAMAGED" if rnd.random() < 0.3 else "USABLE"
                S.post_return(db, S.DocHeader(
                    doc_type="RET", doc_date=date, linked_doc=dn,
                    returned_by=h.issued_to, received_by=rnd.choice(NAMES),
                    project=h.project, department=h.department,
                    warehouse=h.warehouse, remarks="Site return"),
                    [S.Line(item_id=ln.item_id, qty=rq, issued_qty=ln.qty, condition=cond,
                            remarks="Surplus" if cond == "USABLE" else "Damaged on site")])

    # ---- transfers
    for k in range(4):
        chunk = rnd.sample(item_ids, 3)
        lines = []
        for i in chunk:
            bal = db.scalar("SELECT balance FROM items WHERE id=?", (i,))
            if bal > 5:
                lines.append(S.Line(item_id=i, qty=min(bal, rnd.choice([5, 10, 15]))))
        if lines:
            S.post_transfer(db, S.DocHeader(
                doc_type="TRF", doc_date=d(rnd.randint(1, 60)),
                warehouse=WAREHOUSES[0], to_warehouse=rnd.choice(WAREHOUSES[1:]),
                location="Rack A", to_location="Rack B", issued_to=rnd.choice(NAMES),
                received_by=rnd.choice(NAMES), remarks="Site replenishment"), lines)

    # ---- adjustments
    for reason in ("Physical count correction", "Missing stock", "Found stock"):
        chunk = rnd.sample(item_ids, 2)
        lines = [S.Line(item_id=i, qty=rnd.choice([-3, -2, 2, 4]), remarks="Demo adjustment")
                 for i in chunk]
        S.post_adjustment(db, S.DocHeader(
            doc_type="ADJ", doc_date=d(rnd.randint(1, 45)), reason=reason,
            warehouse=WAREHOUSES[0]), lines)

    # ---- today activity so the dashboard is never empty
    live = rnd.sample(item_ids, 4)
    S.post_receipt(db, S.DocHeader(
        doc_type="GRN", doc_date=today.isoformat(), supplier=SUPPLIERS[0],
        reference="PO-2026-777", warehouse=WAREHOUSES[0], received_by=NAMES[0],
        remarks="Today's delivery"),
        [S.Line(item_id=i, qty=25,
                unit_cost=db.scalar("SELECT unit_cost FROM items WHERE id=?", (i,)))
         for i in live])
    today_dn = S.post_issue(db, S.DocHeader(
        doc_type="DN", doc_date=today.isoformat(), project=SITES[0], department=DEPTS[0],
        requested_by=NAMES[1], issued_to=NAMES[2], received_by=NAMES[3],
        reference="MR-2026-501", purpose="Daily site issue", warehouse=WAREHOUSES[0]),
        [S.Line(item_id=i, qty=5) for i in live[:3]])
    S.post_return(db, S.DocHeader(
        doc_type="RET", doc_date=today.isoformat(), linked_doc=today_dn,
        returned_by=NAMES[2], received_by=NAMES[0], warehouse=WAREHOUSES[0],
        remarks="Unused material"),
        [S.Line(item_id=live[0], qty=2, issued_qty=5, condition="USABLE")])

    # ---- a draft DN so 'pending transactions' shows something
    S.post_issue(db, S.DocHeader(
        doc_type="DN", doc_date=today.isoformat(), project=SITES[1], department=DEPTS[2],
        requested_by=NAMES[4], issued_to=NAMES[5], reference="MR-2026-502",
        purpose="Awaiting approval", warehouse=WAREHOUSES[0]),
        [S.Line(item_id=live[1], qty=3)], finalize=False)

    # ---- drive a few items into warning / critical / out-of-stock
    for iid, factor in zip(rnd.sample(item_ids, 9), [0.0, 0.0, 0.1, 0.15, 0.15, 0.3, 0.3, 0.35, 0.35]):
        it = db.one("SELECT * FROM items WHERE id=?", (iid,))
        target = (it["max_level"] or 100) * factor
        delta = target - (it["balance"] or 0)
        if abs(delta) > 0.5:
            S.post_adjustment(db, S.DocHeader(
                doc_type="ADJ", doc_date=d(2), reason="Data correction",
                warehouse=it["warehouse"], remarks="Demo stock level scenario"),
                [S.Line(item_id=iid, qty=round(delta, 2), remarks="Set demo level")])

    # ---- a physical count with variances
    chunk = rnd.sample(item_ids, 8)
    lines = []
    for i in chunk:
        sysq = db.scalar("SELECT balance FROM items WHERE id=?", (i,))
        counted = max(0, sysq + rnd.choice([-3, -1, 0, 0, 2, 5]))
        lines.append(S.Line(item_id=i, qty=counted, system_qty=sysq, counted_qty=counted,
                            remarks="Cycle count"))
    S.save_stock_count(db, S.DocHeader(
        doc_type="CNT", doc_date=d(3), warehouse=WAREHOUSES[0], location="Rack A",
        received_by=NAMES[0], remarks="Monthly cycle count"), lines)

    db.audit("CREATED", "demo-data", "", f"{len(item_ids)} items with full transaction history")
    db.commit()
