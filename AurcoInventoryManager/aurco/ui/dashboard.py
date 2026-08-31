"""Dashboard: KPI cards, charts, alerts panel, recent activity."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QLabel,
                               QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget)

from ..core import material as M
from ..core import services as S
from ..core.database import Database
from . import widgets as W


class DashboardPage(QWidget):
    """Signals: openItems(status), openDoc(doc_type), openPage(name)"""
    openItems = Signal(str)
    openDocs = Signal(str)
    openPage = Signal(str)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("Page")
        scroll.setWidget(body)
        self.v = QVBoxLayout(body)
        self.v.setContentsMargins(16, 14, 16, 18)
        self.v.setSpacing(14)

        self._build_kpis()
        self._build_charts()
        self._build_alerts()
        self.refresh()

    # ------------------------------------------------------------------ KPI
    def _build_kpis(self):
        self.cards: dict[str, W.StatCard] = {}
        specs = [
            ("total_items", "Total Items", "📦", W.NAVY, lambda: self.openPage.emit("Item Master")),
            ("total_qty", "Total Stock Qty", "Σ", "#14538f", lambda: self.openPage.emit("Item Master")),
            ("total_value", "Total Stock Value", "💰", W.GREEN, lambda: self.openPage.emit("Reports")),
            ("available_items", "Available Stock Items", "✔", W.GREEN, lambda: self.openItems.emit("")),
            ("low", "Low Stock", "⚠", W.AMBER, lambda: self.openItems.emit(S.WARNING)),
            ("critical", "Critical Stock", "🔥", W.ORANGE, lambda: self.openItems.emit(S.CRITICAL)),
            ("out", "Out of Stock", "⛔", W.RED, lambda: self.openItems.emit(S.OUT)),
            ("received_today", "Received Today", "⬇", W.GREEN, lambda: self.openDocs.emit("GRN")),
            ("issued_today", "Issued Today", "⬆", "#e8590c", lambda: self.openDocs.emit("DN")),
            ("returns_today", "Returns Today", "↩", "#7048e8", lambda: self.openDocs.emit("RET")),
            ("pending_docs", "Pending / Draft Docs", "⏳", "#1098ad", lambda: self.openDocs.emit("DRAFT")),
            ("damaged_qty", "Damaged Stock Qty", "🛠", "#868e96", lambda: self.openPage.emit("Returns")),
            ("open_requests", "Open Material Requests", "📋", "#7048e8",
             lambda: self.openPage.emit("Material Requests")),
            ("pending_qty", "Qty Still To Prepare", "⏱", "#e8590c",
             lambda: self.openPage.emit("Material Requests")),
            ("ready_qty", "Ready For Delivery", "🚚", "#0b7285",
             lambda: self.openPage.emit("Material Requests")),
            ("shortage_lines", "Request Lines Short", "⚠", W.RED,
             lambda: self.openPage.emit("Material Requests")),
        ]
        grid = QGridLayout()
        grid.setSpacing(11)
        for i, (key, label, glyph, color, cb) in enumerate(specs):
            c = W.StatCard(label, "0", glyph, color)
            c.clicked.connect(cb)
            c.setToolTip("Click to open the related records")
            grid.addWidget(c, i // 4, i % 4)
            self.cards[key] = c
        self.v.addLayout(grid)

    # --------------------------------------------------------------- charts
    def _build_charts(self):
        row = QHBoxLayout()
        row.setSpacing(12)

        c1 = W.Card("Monthly Stock In / Out")
        self.chart_monthly = W.GroupedBarChart()
        c1.add(self.chart_monthly)
        row.addWidget(c1, 3)

        c2 = W.Card("Stock Health")
        self.chart_health = W.DonutChart()
        c2.add(self.chart_health)
        row.addWidget(c2, 2)
        self.v.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        c3 = W.Card("Stock by Category")
        self.chart_cat = W.BarChart(horizontal=True, color="#14538f")
        self.chart_cat.barClicked.connect(lambda k: self.openPage.emit("Item Master"))
        c3.add(self.chart_cat)
        row2.addWidget(c3, 2)

        c4 = W.Card("Top Issued Items")
        self.chart_top = W.BarChart(horizontal=True, color="#e8590c")
        c4.add(self.chart_top)
        row2.addWidget(c4, 2)

        c5 = W.Card("Stock by UOM")
        self.chart_uom = W.BarChart(horizontal=True, color=W.GREEN)
        c5.add(self.chart_uom)
        row2.addWidget(c5, 2)
        self.v.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(12)
        c6 = W.Card("Consumption Trend (issued qty per month)")
        self.chart_trend = W.LineChart()
        c6.add(self.chart_trend)
        row3.addWidget(c6, 3)
        c7 = W.Card("Stock by Warehouse")
        self.chart_wh = W.BarChart(horizontal=True, color="#7048e8")
        c7.add(self.chart_wh)
        row3.addWidget(c7, 2)
        self.v.addLayout(row3)

    # --------------------------------------------------------------- alerts
    def _build_alerts(self):
        row = QHBoxLayout()
        row.setSpacing(12)
        left = W.Card("⚡ Alerts Panel  —  click a row to open the item")
        self.alert_tabs = QTabWidget()
        self.alert_tables: dict[str, W.DataTable] = {}
        for name in ("LOW STOCK", "CRITICAL STOCK", "OUT OF STOCK", "RECENT RECEIPTS",
                     "RECENT ISSUES", "RECENT RETURNS", "STOCK VARIANCES"):
            t = W.DataTable()
            t.doubleClicked.connect(lambda *_, n=name: self._alert_open(n))
            self.alert_tables[name] = t
            self.alert_tabs.addTab(t, name.title())
        left.add(self.alert_tabs)
        row.addWidget(left, 3)

        right = QVBoxLayout()
        right.setSpacing(12)
        # These two tables used to collapse to ~2 visible rows because the card
        # gave them no minimum height and the row stretched to fit the layout.
        # Give them a real minimum and let them expand, so the list scrolls
        # properly instead of showing a single entry.
        c_dn = W.Card("Recent Delivery Notes  —  double-click to open Documents")
        self.tbl_dn = W.DataTable()
        self.tbl_dn.doubleClicked.connect(lambda: self.openDocs.emit("DN"))
        self.tbl_dn.setMinimumHeight(210)
        self.tbl_dn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tbl_dn.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tbl_dn.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        c_dn.add(self.tbl_dn, 1)
        c_dn.setMinimumHeight(260)
        right.addWidget(c_dn, 1)
        c_mv = W.Card("Recent Stock Movements")
        self.tbl_mv = W.DataTable()
        self.tbl_mv.setMinimumHeight(210)
        self.tbl_mv.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tbl_mv.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tbl_mv.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        c_mv.add(self.tbl_mv, 1)
        c_mv.setMinimumHeight(260)
        right.addWidget(c_mv, 1)
        row.addLayout(right, 2)
        self.alert_tabs.setMinimumHeight(520)
        self.v.addLayout(row)

    def _alert_open(self, name: str):
        if name in ("LOW STOCK", "CRITICAL STOCK", "OUT OF STOCK"):
            self.openItems.emit({"LOW STOCK": S.WARNING, "CRITICAL STOCK": S.CRITICAL,
                                 "OUT OF STOCK": S.OUT}[name])
        elif name == "RECENT RECEIPTS":
            self.openDocs.emit("GRN")
        elif name == "RECENT ISSUES":
            self.openDocs.emit("DN")
        elif name == "RECENT RETURNS":
            self.openDocs.emit("RET")
        else:
            self.openPage.emit("Physical Count")

    # -------------------------------------------------------------- refresh
    def refresh(self):
        db = self.db
        d = S.dashboard_data(db)
        d.update(M.dashboard_counts(db))
        cur = db.get_setting("currency", "")
        fmt = {
            "total_items": f"{d['total_items']:,}",
            "total_qty": f"{d['total_qty']:,.0f}",
            "total_value": f"{cur} {d['total_value']:,.0f}",
            "available_items": f"{d['available_items']:,}",
            "low": f"{d['low']:,}", "critical": f"{d['critical']:,}", "out": f"{d['out']:,}",
            "received_today": f"{d['received_today']:,.0f}",
            "issued_today": f"{d['issued_today']:,.0f}",
            "returns_today": f"{d['returns_today']:,.0f}",
            "pending_docs": f"{d['pending_docs']:,}",
            "damaged_qty": f"{d['damaged_qty']:,.0f}",
            "open_requests": f"{d['open_requests']:,}",
            "pending_qty": f"{d['pending_qty']:,.0f}",
            "ready_qty": f"{d['ready_qty']:,.0f}",
            "shortage_lines": f"{d['shortage_lines']:,}",
        }
        subs = {
            "total_items": f"{d['normal']} healthy · {d['low'] + d['critical']} need attention",
            "total_qty": "across all warehouses",
            "total_value": "valued at last unit cost",
            "available_items": "items with stock on hand",
            "low": "below minimum level", "critical": "below critical level",
            "out": "zero balance", "received_today": "units received today",
            "issued_today": "units issued today", "returns_today": "units returned today",
            "pending_docs": "drafts awaiting finalization", "damaged_qty": "held as damaged",
            "open_requests": "projects waiting for material",
            "pending_qty": "requested but not yet prepared",
            "ready_qty": f"{d['ready_lines']} line(s), no DN yet",
            "shortage_lines": "cannot be fully supplied",
        }
        for k, c in self.cards.items():
            c.set_value(fmt[k], subs[k])

        self.chart_monthly.set_data([(m["m"][-2:] + "/" + m["m"][2:4], m["qin"], m["qout"])
                                     for m in d["monthly"]])
        self.chart_health.set_data([
            ("Normal", d["normal"], W.GREEN), ("Warning", d["low"], W.AMBER),
            ("Critical", d["critical"], W.ORANGE), ("Out of Stock", d["out"], W.RED)])
        self.chart_cat.set_data([(r["k"], r["q"] or 0) for r in d["by_category"]])
        self.chart_top.set_data([(r["item_code"], r["q"] or 0) for r in d["top_issued"]])
        self.chart_uom.set_data([(r["k"], r["q"] or 0) for r in d["by_uom"]])
        self.chart_wh.set_data([(r["k"], r["q"] or 0) for r in d["by_warehouse"]])
        self.chart_trend.set_data([(m["m"], m["qout"]) for m in d["monthly"]])

        self.tbl_dn.fill(["DN Number", "Date", "Issued To", "Project", "Status"],
                         [[r["doc_no"], r["doc_date"], r["issued_to"], r["project"], r["status"]]
                          for r in d["recent_dn"]])
        self.tbl_mv.fill(["Date", "Type", "Item", "In", "Out", "Balance", "Document"],
                         [[r["txn_date"], r["txn_type"], r["item_code"],
                           r["qty_in"] or "", r["qty_out"] or "", r["balance_after"], r["doc_no"]]
                          for r in d["recent_moves"]])

        al = S.alerts_panel(db)
        icols = ["Code", "Description", "UOM", "Balance", "Min Level", "Warehouse", "Location"]
        for key in ("LOW STOCK", "CRITICAL STOCK", "OUT OF STOCK"):
            rows = []
            for r in al[key]:
                mn, _ = S.item_thresholds(db, r)
                rows.append([r["code"], r["description"], r["uom"], round(r["balance"], 2),
                             round(mn, 2), r["warehouse"], r["location"]])
            self.alert_tables[key].fill(icols, rows)
            i = list(self.alert_tables).index(key)
            self.alert_tabs.setTabText(i, f"{key.title()} ({len(rows)})")
        dcols = ["Document", "Date", "Party", "Reference", "Status"]
        for key, party in (("RECENT RECEIPTS", "supplier"), ("RECENT ISSUES", "issued_to"),
                           ("RECENT RETURNS", "returned_by")):
            rows = [[r["doc_no"], r["doc_date"], r[party], r["reference"] or r["linked_doc"],
                     r["status"]] for r in al[key]]
            self.alert_tables[key].fill(dcols, rows)
            self.alert_tabs.setTabText(list(self.alert_tables).index(key),
                                       f"{key.title()} ({len(rows)})")
        vrows = [[r["doc_no"], r["doc_date"], r["item_code"], r["system_qty"], r["counted_qty"],
                  r["variance"]] for r in al["STOCK VARIANCES"]]
        self.alert_tables["STOCK VARIANCES"].fill(
            ["Count No", "Date", "Item", "System Qty", "Counted Qty", "Variance"], vrows)
        self.alert_tabs.setTabText(6, f"Stock Variances ({len(vrows)})")
