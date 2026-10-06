"""INSTRUMENT STATION — custody register UI rebuilt around Excel/site sync.

Five tabs:
    📊 Dashboard    KPI tiles + charts driven purely by Instrument Station data
    📋 Register     the unified filter — every document type in ONE shape
    🔧 Assets       where is each instrument right now, and its full history
    📂 Sync Folder  index a synchronised folder of signed handover PDFs
    📈 Reports      16 reports, PDF / Excel / CSV / print / share

Nothing in this file imports the stock engine.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QScrollArea, QSpinBox,
                               QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import toolstation as T
from ..core.database import Database
from . import widgets as W
from .common import ShareBar, date_edit, iso


def _paint(table: W.DataTable, col: int, colors: dict) -> None:
    """Tint a status column using the module's colour map."""
    from PySide6.QtGui import QBrush, QColor, QFont
    for r in range(table.rowCount()):
        it = table.item(r, col)
        if it is None:
            continue
        c = colors.get(it.text())
        if c:
            it.setForeground(QBrush(QColor(c)))
            f = QFont(it.font())
            f.setBold(True)
            it.setFont(f)


# ============================================================== dashboard tab
#: every KPI tile the dashboard can show:
#:   key · caption · glyph · colour · the register filter it drills into
TILE_SPECS: list[tuple[str, str, str, str, dict]] = [
    ("documents", "Handover Documents", "🧾", W.NAVY, {}),
    ("total_tools", "Total Instruments", "🧰", W.NAVY, {}),
    ("available", "Available", "✅", "#1a9c52", {}),
    ("issued_site", "Issued", "📤", T.TXN_COLORS[T.ISSUE], {}),
    ("transferred_site", "Transferred to Sites", "🚚", T.TXN_COLORS[T.TRANSFER], {}),
    ("returned_site", "Returned", "↩", T.TXN_COLORS[T.RETURN], {}),
    ("pending_items", "Pending / Missing", "⚠", "#c92a2a", {}),
    ("site_files", "Synced Excel Files", "📄", "#14538f", {}),
    ("sites_covered", "Sites Covered", "📍", "#7048e8", {}),
    ("issues", "Issues", "📤", T.TXN_COLORS[T.ISSUE], {"txn_type": T.ISSUE}),
    ("transfers", "Transfers", "🔁", T.TXN_COLORS[T.TRANSFER], {"txn_type": T.TRANSFER}),
    ("loans", "Temporary Loans", "⏳", T.TXN_COLORS[T.LOAN], {"txn_type": T.LOAN}),
    ("returns", "Returns", "↩", T.TXN_COLORS[T.RETURN], {"txn_type": T.RETURN}),
    ("open", "Still Out", "📦", T.STATUS_COLORS[T.OPEN], {"status": T.OPEN}),
    ("part", "Partially Returned", "◐", T.STATUS_COLORS[T.PART_RETURNED],
     {"status": T.PART_RETURNED}),
    ("closed", "Fully Returned", "✔", T.STATUS_COLORS[T.CLOSED], {"status": T.CLOSED}),
    ("moved", "Transferred Out", "➡", T.STATUS_COLORS[T.TRANSFERRED],
     {"status": T.TRANSFERRED}),
    ("overdue", "Overdue", "⚠", T.STATUS_COLORS[T.OVERDUE], {"overdue_only": True}),
    ("custodians", "Custodians Holding", "👤", "#7048e8", {"only_open": True}),
    ("assets", "Assets Tracked", "🔧", W.NAVY, {}),
    ("assets_out", "Assets Out", "🚚", "#e8590c", {"only_open": True}),
    ("calib_soon", "Calibration Due (30d)", "🎯", "#9a6700", {}),
    ("calib_expired", "Calibration Expired", "⛔", "#c92a2a", {}),
    ("damaged", "Damaged / Defective", "🛠", "#c92a2a", {}),
    ("items", "Item Lines", "📋", W.NAVY, {}),
    ("out_qty", "Qty Outstanding", "Σ", "#0b6e83", {"only_open": True}),
    ("photos", "Photo Evidence", "📷", "#1a9c52", {}),
    ("overdue_days", "Worst Overdue (days)", "🔥", "#c92a2a", {"overdue_only": True}),
]

#: charts and tables that can be switched on or off
PANEL_SPECS: list[tuple[str, str]] = [
    ("type", "By transaction type"),
    ("status", "Custody status"),
    ("month", "Documents per month"),
    ("project", "By project / site"),
    ("holder", "By custodian (who is holding it)"),
    ("category", "By tool category"),
    ("item", "Most handed-over instruments"),
    ("ageing", "Outstanding ageing (how long it has been out)"),
    ("io", "Handed over vs returned by month"),
    ("overdue_table", "⚠ Overdue — chase these first"),
    ("people", "Who is holding what right now"),
    ("recent", "Latest handovers"),
]

DEFAULT_TILES = ["total_tools", "available", "issued_site", "transferred_site", "returned_site",
                 "pending_items", "site_files", "sites_covered", "documents", "issues",
                 "transfers", "returns", "open", "assets", "out_qty", "photos"]
DEFAULT_PANELS = [k for k, _ in PANEL_SPECS]


class DashboardSetupDialog(QDialog):
    """Choose which tiles, charts and tables the dashboard shows."""

    def __init__(self, tiles: list[str], panels: list[str], columns: int,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customise the dashboard")
        self.setMinimumWidth(680)
        v = QVBoxLayout(self)
        note = QLabel("Tick what this dashboard should show. The choice is stored "
                      "with the module, so every screen keeps your layout.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(note)

        self.tile_boxes: dict[str, QCheckBox] = {}
        card = W.Card("KPI tiles")
        grid = QGridLayout()
        for i, (key, label, glyph, _c, _f) in enumerate(TILE_SPECS):
            cb = QCheckBox(f"{glyph}  {label}")
            cb.setChecked(key in tiles)
            self.tile_boxes[key] = cb
            grid.addWidget(cb, i // 3, i % 3)
        card.v.addLayout(grid)
        v.addWidget(card)

        self.panel_boxes: dict[str, QCheckBox] = {}
        card2 = W.Card("Charts and tables")
        grid2 = QGridLayout()
        for i, (key, label) in enumerate(PANEL_SPECS):
            cb = QCheckBox(label)
            cb.setChecked(key in panels)
            self.panel_boxes[key] = cb
            grid2.addWidget(cb, i // 2, i % 2)
        card2.v.addLayout(grid2)
        v.addWidget(card2)

        row = QHBoxLayout()
        row.addWidget(QLabel("Tiles per row:"))
        self.cols = W.combo([str(n) for n in (3, 4, 5, 6)])
        self.cols.setCurrentText(str(columns))
        row.addWidget(self.cols)
        row.addStretch(1)
        row.addWidget(W.button("↺  Restore defaults", slot=self._defaults))
        v.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Apply")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _defaults(self):
        for k, cb in self.tile_boxes.items():
            cb.setChecked(k in DEFAULT_TILES)
        for k, cb in self.panel_boxes.items():
            cb.setChecked(k in DEFAULT_PANELS)
        self.cols.setCurrentText("4")

    def result_config(self) -> tuple[list[str], list[str], int]:
        tiles = [k for k, _l, _g, _c, _f in TILE_SPECS if self.tile_boxes[k].isChecked()]
        panels = [k for k, _l in PANEL_SPECS if self.panel_boxes[k].isChecked()]
        return tiles, panels, int(self.cols.currentText())


class ToolDashboard(QWidget):
    """Filterable, drill-through, user-configurable custody dashboard.

    Everything on screen answers to the one filter bar at the top, and the
    layout itself (which tiles, which charts) is stored in the module's own
    database — so the site can shape the dashboard the way it reads its work.
    """
    openRegister = Signal(dict)

    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.tiles: dict[str, W.StatCard] = {}
        self.panels: dict[str, QWidget] = {}
        self._loading = False
        self.last_file: Path | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_filter_bar())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, 1)
        self.body = QWidget()
        self.body.setObjectName("Page")
        scroll.setWidget(self.body)
        self.body_v = QVBoxLayout(self.body)
        self.body_v.setContentsMargins(8, 10, 8, 14)
        self.body_v.setSpacing(12)

        self.tile_cfg, self.panel_cfg, self.cols_cfg = self._load_config()
        self._build_body()
        self.reload_filters()

    # --------------------------------------------------------------- config
    def _load_config(self) -> tuple[list[str], list[str], int]:
        def read(key: str, default: list[str]) -> list[str]:
            raw = self.tdb.get_setting(key, "")
            picked = [k for k in str(raw).split("|") if k]
            return picked or list(default)

        valid_t = {k for k, *_ in TILE_SPECS}
        valid_p = {k for k, _ in PANEL_SPECS}
        tiles = [k for k in read("dash_tiles", DEFAULT_TILES) if k in valid_t]
        panels = [k for k in read("dash_panels", DEFAULT_PANELS) if k in valid_p]
        try:
            cols = int(self.tdb.get_setting("dash_columns", 4) or 4)
        except (TypeError, ValueError):
            cols = 4
        return (tiles or list(DEFAULT_TILES), panels or list(DEFAULT_PANELS),
                min(6, max(3, cols)))

    def _save_config(self) -> None:
        self.tdb.set_setting("dash_tiles", "|".join(self.tile_cfg))
        self.tdb.set_setting("dash_panels", "|".join(self.panel_cfg))
        self.tdb.set_setting("dash_columns", self.cols_cfg)

    def customise(self):
        dlg = DashboardSetupDialog(self.tile_cfg, self.panel_cfg, self.cols_cfg, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self.tile_cfg, self.panel_cfg, self.cols_cfg = dlg.result_config()
        self._save_config()
        self._build_body()
        self.reload()
        W.toast(self, "Dashboard layout saved.")

    # ----------------------------------------------------------- filter bar
    def _build_filter_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Card")
        fl = QGridLayout(bar)
        fl.setContentsMargins(10, 7, 10, 7)
        fl.setHorizontalSpacing(7)
        fl.setVerticalSpacing(6)

        self.f_text = W.SearchBox("Filter the whole dashboard — reference, "
                                  "custodian, asset, serial, project ...")
        self.f_text.textChanged.connect(self.reload)
        fl.addWidget(self.f_text, 0, 0, 1, 3)
        self.f_type = W.combo(["All Types"] + list(T.TXN_TYPES))
        self.f_status = W.combo(["All Status", T.OPEN, T.PART_RETURNED, T.CLOSED,
                                 T.TRANSFERRED, T.OVERDUE, T.CANCELLED])
        self.f_project = W.combo(["All Projects"])
        self.f_holder = W.combo(["All Custodians"])
        self.f_category = W.combo(["All Categories"])
        self.f_warehouse = W.combo(["All Warehouses"])
        for i, cb in enumerate((self.f_type, self.f_status, self.f_project,
                                self.f_holder, self.f_category, self.f_warehouse)):
            cb.currentTextChanged.connect(self.reload)
            fl.addWidget(cb, 0, 3 + i)

        self.f_period = W.combo(["All time", "This month", "Last 3 months",
                                 "Last 6 months", "This year", "Last 12 months",
                                 "Custom range"])
        self.f_period.currentTextChanged.connect(self._period_changed)
        fl.addWidget(self.f_period, 1, 0)
        self.d_from = date_edit(QDate.currentDate().addMonths(-6).toString("yyyy-MM-dd"))
        self.d_to = date_edit(QDate.currentDate().toString("yyyy-MM-dd"))
        for d in (self.d_from, self.d_to):
            d.dateChanged.connect(lambda _: self.reload())
            d.setEnabled(False)
        fl.addWidget(self.d_from, 1, 1)
        fl.addWidget(self.d_to, 1, 2)
        self.chk_open = QCheckBox("Only still out")
        self.chk_open.toggled.connect(self.reload)
        fl.addWidget(self.chk_open, 1, 3)
        self.chk_overdue = QCheckBox("Only overdue")
        self.chk_overdue.toggled.connect(self.reload)
        fl.addWidget(self.chk_overdue, 1, 4)
        self.f_measure = W.combo(["Measure: Documents / lines",
                                  "Measure: Quantity",
                                  "Measure: Quantity still out"])
        self.f_measure.setToolTip("What the charts should count")
        self.f_measure.currentTextChanged.connect(self.reload)
        fl.addWidget(self.f_measure, 1, 5)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(W.button("↺  Reset", slot=self.reset_filters))
        row.addWidget(W.button("⚙  Customise", slot=self.customise,
                               tip="Choose which tiles, charts and tables are shown"))
        row.addWidget(W.button("📄  Export View", "Primary", self.export_view,
                               tip="PDF of exactly what the filters show"))
        row.addWidget(W.button("📊  Excel", slot=lambda: self.export_view("xlsx")))
        holder = QWidget()
        holder.setLayout(row)
        fl.addWidget(holder, 1, 6, 1, 2)
        return bar

    def _period_changed(self, text: str):
        custom = text == "Custom range"
        self.d_from.setEnabled(custom)
        self.d_to.setEnabled(custom)
        self.reload()

    def reload_filters(self):
        for cb, col, first in ((self.f_project, "project_id", "All Projects"),
                               (self.f_holder, "handed_to", "All Custodians"),
                               (self.f_category, "category", "All Categories"),
                               (self.f_warehouse, "warehouse", "All Warehouses")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + T.distinct(self.tdb, col))
            cb.setCurrentIndex(max(0, cb.findText(cur)))
            cb.blockSignals(False)

    def reset_filters(self):
        self._loading = True
        self.f_text.clear()
        for cb in (self.f_type, self.f_status, self.f_project, self.f_holder,
                   self.f_category, self.f_warehouse, self.f_period, self.f_measure):
            cb.setCurrentIndex(0)
        for c in (self.chk_open, self.chk_overdue):
            c.setChecked(False)
        self._loading = False
        self.reload()

    def _period_range(self) -> tuple[str, str]:
        today = _dt.date.today()
        p = self.f_period.currentText()
        if p == "This month":
            return today.replace(day=1).isoformat(), ""
        if p == "Last 3 months":
            return (today - _dt.timedelta(days=91)).isoformat(), ""
        if p == "Last 6 months":
            return (today - _dt.timedelta(days=182)).isoformat(), ""
        if p == "This year":
            return today.replace(month=1, day=1).isoformat(), ""
        if p == "Last 12 months":
            return (today - _dt.timedelta(days=365)).isoformat(), ""
        if p == "Custom range":
            return iso(self.d_from), iso(self.d_to)
        return "", ""

    def filters(self) -> dict:
        d_from, d_to = self._period_range()
        f: dict = {"text": self.f_text.text().strip()}
        if self.f_type.currentIndex() > 0:
            f["txn_type"] = self.f_type.currentText()
        if self.f_status.currentIndex() > 0:
            f["status"] = self.f_status.currentText()
        if self.f_project.currentIndex() > 0:
            f["project"] = self.f_project.currentText()
        if self.f_holder.currentIndex() > 0:
            f["holder"] = self.f_holder.currentText()
        if self.f_category.currentIndex() > 0:
            f["category"] = self.f_category.currentText()
        if self.f_warehouse.currentIndex() > 0:
            f["warehouse"] = self.f_warehouse.currentText()
        if d_from:
            f["date_from"] = d_from
        if d_to:
            f["date_to"] = d_to
        if self.chk_overdue.isChecked():
            f["overdue_only"] = True
        return {k: v for k, v in f.items() if v not in ("", None, False)}

    def measure(self) -> str:
        return {"Measure: Documents / lines": "count",
                "Measure: Quantity": "qty",
                "Measure: Quantity still out": "outstanding"}[
                    self.f_measure.currentText()]

    # ----------------------------------------------------------------- body
    def _clear_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    def _panel(self, key: str, widget: QWidget, stretch: int = 1) -> QWidget | None:
        """Wrap a chart/table in its titled card when the user wants it."""
        if key not in self.panel_cfg:
            return None
        title = dict(PANEL_SPECS)[key]
        card = W.Card(title)
        card.add(widget, stretch)
        self.panels[key] = card
        return card

    def _build_body(self):
        self._clear_layout(self.body_v)
        self.tiles.clear()
        self.panels.clear()

        grid = QGridLayout()
        grid.setSpacing(10)
        for c in range(self.cols_cfg):
            grid.setColumnStretch(c, 1)      # a half-empty row keeps tile width
        specs = {k: (l, g, c, f) for k, l, g, c, f in TILE_SPECS}
        for i, key in enumerate(self.tile_cfg):
            label, glyph, color, flt = specs[key]
            card = W.StatCard(label, "0", glyph, color)
            card.setToolTip("Click to open these documents in the register")
            card.clicked.connect(lambda k=key: self._drill(k))
            self.tiles[key] = card
            grid.addWidget(card, i // self.cols_cfg, i % self.cols_cfg)
        self.body_v.addLayout(grid)

        # charts are created every time so a hidden one costs nothing
        self.c_type = W.BarChart(color=T.TXN_COLORS[T.ISSUE])
        self.c_type.barClicked.connect(lambda k: self._set_combo(self.f_type, k))
        self.c_status = W.DonutChart()
        self.c_month = W.LineChart()
        self.c_project = W.BarChart(horizontal=True, color="#14538f")
        self.c_project.barClicked.connect(lambda k: self._set_combo(self.f_project, k))
        self.c_holder = W.BarChart(horizontal=True, color="#7048e8")
        self.c_holder.barClicked.connect(lambda k: self._set_combo(self.f_holder, k))
        self.c_category = W.BarChart(horizontal=True, color="#0b7285")
        self.c_category.barClicked.connect(lambda k: self._set_combo(self.f_category, k))
        self.c_item = W.BarChart(horizontal=True, color="#1a9c52")
        self.c_age = W.BarChart(color="#e8590c")
        self.c_io = W.GroupedBarChart(labels=("Handed over", "Returned"))
        self.t_overdue = W.DataTable()
        self.t_overdue.setMinimumHeight(190)
        self.t_people = W.DataTable()
        self.t_people.setMinimumHeight(190)
        self.t_recent = W.DataTable()
        self.t_recent.setMinimumHeight(210)

        rows = [
            [("type", self.c_type, 2), ("status", self.c_status, 2),
             ("month", self.c_month, 3)],
            [("project", self.c_project, 2), ("holder", self.c_holder, 2),
             ("category", self.c_category, 2)],
            [("item", self.c_item, 2), ("ageing", self.c_age, 2), ("io", self.c_io, 3)],
            [("overdue_table", self.t_overdue, 1)],
            [("people", self.t_people, 1)],
            [("recent", self.t_recent, 1)],
        ]
        for group in rows:
            line = QHBoxLayout()
            line.setSpacing(12)
            used = False
            for key, widget, weight in group:
                card = self._panel(key, widget)
                if card is not None:
                    line.addWidget(card, weight)
                    used = True
            if used:
                self.body_v.addLayout(line)
        if not self.tile_cfg and not self.panel_cfg:
            empty = QLabel("Nothing is switched on yet — press ⚙ Customise to "
                           "choose the tiles and charts you want.")
            empty.setStyleSheet(f"color:{W.MUTED};")
            self.body_v.addWidget(empty)
        self.body_v.addStretch(1)

    def _set_combo(self, cb, value: str):
        i = cb.findText(value)
        cb.setCurrentIndex(i if i >= 0 else 0)

    def _drill(self, key: str):
        f = self.filters()
        extra = {k: (l, g, c, x) for k, l, g, c, x in TILE_SPECS}[key][3]
        f.update(extra)
        self.openRegister.emit(f)

    # --------------------------------------------------------------- export
    def export_view(self, kind: str = "pdf"):
        f = self.filters()
        title, cols, rows = T.build_report(self.tdb, "All Handover Documents", f)
        if not rows:
            W.error_box(self, "Nothing matches the current filters.")
            return
        d = T.dashboard(self.tdb, f)
        bits = [f"{k.replace('_', ' ').title()}: {v}" for k, v in f.items()]
        subtitle = "  ·  ".join(bits) or "All handovers"
        try:
            if kind == "xlsx":
                self.last_file = D.export_excel(
                    self.db, "Tools Instruments Devices - Dashboard View", cols, rows)
            else:
                stats = [("Documents", f"{d['documents']:,}", "#12283f"),
                         ("Still Out", f"{d['open']:,}", "#9a6700"),
                         ("Overdue", f"{d['overdue']:,}", "#b3261e"),
                         ("Qty Outstanding", f"{d['out_qty']:,.2f}", "#0f7b3d"),
                         ("Custodians", f"{d['custodians']:,}", "#12283f"),
                         ("Assets Out", f"{d['assets_out']:,}", "#9a6700")]
                self.last_file = D.tool_report_pdf(
                    self.db, "Instrument Station — Dashboard View",
                    cols, rows, subtitle=subtitle, stats=stats)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Could not export the view.\n\n{exc}")
            return
        W.toast(self, f"Exported: {Path(self.last_file).name}")
        D.open_path(self.last_file)

    # --------------------------------------------------------------- render
    def reload(self):
        if self._loading:
            return
        f = self.filters()
        m = self.measure()
        only_open = self.chk_open.isChecked()
        d = T.dashboard(self.tdb, f)
        for key, card in self.tiles.items():
            val = d.get(key, 0)
            card.set_value(f"{val:,.2f}" if isinstance(val, float) and val % 1
                           else f"{val:,.0f}")
        if "overdue" in self.tiles:
            self.tiles["overdue"].lbl_sub.setText(
                f"worst {d.get('overdue_days', 0)} day(s) late" if d.get("overdue")
                else "nothing is late")
        if "documents" in self.tiles:
            self.tiles["documents"].lbl_sub.setText(
                "filtered view" if f else "all handovers")
        if "out_qty" in self.tiles:
            self.tiles["out_qty"].lbl_sub.setText(
                f"{d.get('items', 0):,} item line(s)")

        if "type" in self.panel_cfg:
            self.c_type.set_data(T.by_column(self.tdb, "txn_type", 10, m, f))
        if "status" in self.panel_cfg:
            self.c_status.set_data([
                (name, val, T.STATUS_COLORS.get(name, W.NAVY))
                for name, val in T.by_column(self.tdb, "status", 10, m, f)])
        if "month" in self.panel_cfg:
            self.c_month.set_data(T.monthly(self.tdb, 12, f))
        if "project" in self.panel_cfg:
            self.c_project.set_data(T.by_column(self.tdb, "project_id", 10, m, f))
        if "holder" in self.panel_cfg:
            self.c_holder.set_data(T.by_column(self.tdb, "handed_to", 10, m, f))
        if "category" in self.panel_cfg:
            self.c_category.set_data(T.by_column(self.tdb, "category", 10, m, f))
        if "item" in self.panel_cfg:
            self.c_item.set_data(T.by_column(self.tdb, "description", 10, m, f))
        if "ageing" in self.panel_cfg:
            self.c_age.set_data(T.ageing(self.tdb, f, m))
        if "io" in self.panel_cfg:
            self.c_io.set_data(T.monthly_split(self.tdb, 8, f))

        docs = T.search(self.tdb, **f)
        if only_open:
            docs = [r for r in docs if r["outstanding"] > 1e-9]
        if "overdue_table" in self.panel_cfg:
            od = sorted([r for r in docs if r["status"] == T.OVERDUE],
                        key=lambda r: -r["days_late"])
            self.t_overdue.fill(
                ["Reference", "Type", "Custodian", "Iqama / ID", "Mobile", "Project",
                 "Still Out", "Was Due", "Days Late"],
                [[r["ref_no"], r["txn_type"], r["handed_to"], r["iqama_id"],
                  r["mobile"], r["project_id"], round(r["outstanding"], 2),
                  T.fmt_date(r["expected_return"]), r["days_late"]] for r in od[:40]])
        if "people" in self.panel_cfg:
            self.t_people.fill(
                ["Custodian", "Iqama / ID", "Mobile", "Project", "Documents",
                 "Items Held", "Holding Since", "Overdue Docs"],
                [[p["handed_to"], p["iqama_id"], p.get("mobile", ""), p["project_id"],
                  p["docs"], round(p["outstanding"] or 0, 2), T.fmt_date(p["since"]),
                  p["overdue"]] for p in T.custody_by_person(self.tdb, f)])
        if "recent" in self.panel_cfg:
            self.t_recent.fill(
                ["Reference", "Type", "Date", "Custodian", "Project", "Items",
                 "Qty", "Returned", "Still Out", "Expected Return", "Status"],
                [[r["ref_no"], r["txn_type"], T.fmt_date(r["doc_date"]),
                  r["handed_to"], r["project_id"], r["n_items"],
                  round(float(r["qty"] or 0), 2), round(float(r["qty_back"] or 0), 2),
                  round(r["outstanding"], 2), T.fmt_date(r["expected_return"]),
                  r["status"]] for r in docs[:40]])
            _paint(self.t_recent, 10, T.STATUS_COLORS)
            _paint(self.t_recent, 1, T.TXN_COLORS)


# =============================================================== register tab
class RegisterTab(QWidget):
    """The unified filter: every handover type shown in one consistent shape."""
    changed = Signal()

    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.rows: list[dict] = []
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        # ---- filter bar
        bar = QHBoxLayout()
        self.search = W.SearchBox("Search reference, custodian, iqama, asset, "
                                  "serial, project ...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 3)
        self.f_type = W.combo(["All Types"] + list(T.TXN_TYPES))
        self.f_status = W.combo(["All Status", T.OPEN, T.PART_RETURNED,
                                 T.CLOSED, T.TRANSFERRED, T.OVERDUE,
                                 T.CANCELLED])
        self.f_project = W.combo(["All Projects"])
        self.f_holder = W.combo(["All Custodians"])
        for cb in (self.f_type, self.f_status, self.f_project, self.f_holder):
            cb.currentTextChanged.connect(self.reload)
            bar.addWidget(cb)
        v.addLayout(bar)

        bar2 = QHBoxLayout()
        self.chk_dates = QCheckBox("Date range")
        self.chk_dates.toggled.connect(self.reload)
        self.d_from = date_edit(QDate.currentDate().addMonths(-6)
                                .toString("yyyy-MM-dd"))
        self.d_to = date_edit(QDate.currentDate().toString("yyyy-MM-dd"))
        for d in (self.d_from, self.d_to):
            d.dateChanged.connect(lambda _: self.chk_dates.isChecked()
                                  and self.reload())
        bar2.addWidget(self.chk_dates)
        bar2.addWidget(self.d_from)
        bar2.addWidget(QLabel("to"))
        bar2.addWidget(self.d_to)
        self.chk_overdue = QCheckBox("Overdue only")
        self.chk_overdue.toggled.connect(self.reload)
        bar2.addWidget(self.chk_overdue)
        self.chk_open = QCheckBox("Outstanding only (not returned)")
        self.chk_open.toggled.connect(self.reload)
        bar2.addWidget(self.chk_open)
        self.chk_items = QCheckBox("Show one row per item")
        self.chk_items.setToolTip(
            "Switch between one row per document and one row per tool.")
        self.chk_items.toggled.connect(self.reload)
        bar2.addWidget(self.chk_items)
        bar2.addWidget(W.button("✖  Clear Filters", slot=self.clear_filters))
        bar2.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        bar2.addWidget(self.count)
        v.addLayout(bar2)

        # ---- actions
        act = QHBoxLayout()
        act.addWidget(W.button("➕  New Handover", "Primary", self.new_doc))
        act.addWidget(W.button("✏  Edit", slot=self.edit_doc))
        act.addWidget(W.button("↩  Register Return", "Accent", self.do_return,
                               tip="Book items back in against this handover"))
        act.addWidget(W.button("🔁  Transfer Custody", slot=self.do_transfer))
        act.addWidget(W.button("📄  Print Form", slot=self.print_form,
                               tip="Reprint the controlled handover form"))
        act.addWidget(W.button("📎  Open Scanned File", slot=self.open_scan))
        act.addWidget(W.button("🚫  Cancel", slot=self.cancel_doc))
        act.addWidget(W.button("🗑  Delete", slot=self.delete_doc))
        act.addStretch(1)
        act.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        act.addWidget(W.button("📄  PDF", slot=lambda: self.export("pdf")))
        v.addLayout(act)

        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        self.table = W.DataTable()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._load_lines)
        self.table.doubleClicked.connect(self.edit_doc)
        tv.addWidget(W.FilterBar(self.table))
        tv.addWidget(self.table)
        split.addWidget(top)

        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 6, 0, 0)
        self.lbl_doc = QLabel("Select a handover above")
        self.lbl_doc.setStyleSheet(f"color:{W.NAVY}; font-weight:700;")
        bv.addWidget(self.lbl_doc)
        self.t_lines = W.DataTable()
        bv.addWidget(self.t_lines, 1)
        split.addWidget(bottom)
        split.setSizes([380, 260])
        v.addWidget(split, 1)
        v.addWidget(ShareBar(self.db, lambda: self.last_file, self))

    # ------------------------------------------------------------- filters
    def filters(self) -> dict:
        f: dict = {"text": self.search.text().strip()}
        if self.f_type.currentIndex() > 0:
            f["txn_type"] = self.f_type.currentText()
        if self.f_status.currentIndex() > 0:
            f["status"] = self.f_status.currentText()
        if self.f_project.currentIndex() > 0:
            f["project"] = self.f_project.currentText()
        if self.f_holder.currentIndex() > 0:
            f["holder"] = self.f_holder.currentText()
        if self.chk_dates.isChecked():
            f["date_from"] = iso(self.d_from)
            f["date_to"] = iso(self.d_to)
        if self.chk_overdue.isChecked():
            f["overdue_only"] = True
        return f

    def clear_filters(self):
        for w in (self.search,):
            w.clear()
        for cb in (self.f_type, self.f_status, self.f_project, self.f_holder):
            cb.setCurrentIndex(0)
        for c in (self.chk_dates, self.chk_overdue, self.chk_open,
                  self.chk_items):
            c.setChecked(False)
        self.reload()

    def apply_filter(self, f: dict):
        """Called when a dashboard tile or chart bar is clicked.

        The dashboard now passes its whole filter set, so the register opens on
        exactly the population the tile counted — not just its own key.
        """
        self.clear_filters()
        self.search.blockSignals(True)
        self.search.setText(f.get("text", "") or "")
        self.search.blockSignals(False)
        for key, cb in (("txn_type", self.f_type), ("status", self.f_status),
                        ("project", self.f_project), ("holder", self.f_holder)):
            if f.get(key):
                cb.setCurrentText(f[key])
        if f.get("date_from") or f.get("date_to"):
            self.chk_dates.setChecked(True)
            if f.get("date_from"):
                self.d_from.setDate(QDate.fromString(str(f["date_from"])[:10],
                                                     "yyyy-MM-dd"))
            if f.get("date_to"):
                self.d_to.setDate(QDate.fromString(str(f["date_to"])[:10], "yyyy-MM-dd"))
        if f.get("overdue_only"):
            self.chk_overdue.setChecked(True)
        if f.get("only_open"):
            self.chk_open.setChecked(True)
        if f.get("category"):
            # category lives on the item lines, so show the item view
            self.chk_items.setChecked(True)
            self.search.blockSignals(True)
            self.search.setText(f["category"])
            self.search.blockSignals(False)
        self.reload()

    def reload_filters(self):
        for cb, col, first in ((self.f_project, "project_id", "All Projects"),
                               (self.f_holder, "handed_to", "All Custodians")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + T.distinct(self.tdb, col))
            i = cb.findText(cur)
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)

    # -------------------------------------------------------------- render
    DOC_COLS = ["Reference", "Type", "Date", "Project", "Location", "Handed To",
                "Employee Code", "Iqama / ID", "Mobile", "Items", "Qty", "Returned",
                "Outstanding", "Expected Return", "Days Late", "Issued By",
                "Scanned", "Status"]
    ITEM_COLS = ["Reference", "Type", "Date", "Asset / Tool ID", "Category",
                 "Description", "Make / Model", "Serial No.", "Qty",
                 "Returned", "Outstanding", "Cond.", "Calib. Due",
                 "Handed To", "Employee Code", "Project", "Picture Path", "Status"]

    def reload(self):
        f = self.filters()
        if self.chk_items.isChecked():
            lines = T.search_lines(self.tdb, **f)
            if self.chk_open.isChecked():
                lines = [l for l in lines if l["outstanding"] > 1e-9]
            self.rows = lines
            data = [[l["ref_no"], l["txn_type"], T.fmt_date(l["doc_date"]),
                     l["asset_id"], l["category"], l["description"],
                     l["make_model"], l["serial_no"],
                     round(float(l["qty"] or 0), 2),
                     round(float(l["qty_returned"] or 0), 2),
                     round(l["outstanding"], 2), l["condition"],
                     T.fmt_date(l["calib_due"]), l["handed_to"], l.get("employee_code", ""),
                     l["project_id"], l.get("photo", ""), l["status"]] for l in lines]
            self.table.fill(self.ITEM_COLS, data)
            _paint(self.table, 17, T.STATUS_COLORS)
            _paint(self.table, 1, T.TXN_COLORS)
            self.count.setText(f"{len(data)} item line(s)")
        else:
            rows = T.search(self.tdb, **f)
            if self.chk_open.isChecked():
                rows = [r for r in rows
                        if r["status"] in (T.OPEN, T.PART_RETURNED, T.OVERDUE)]
            self.rows = rows
            data = [[r["ref_no"], r["txn_type"], T.fmt_date(r["doc_date"]),
                     r["project_id"] or r["project_name"], r["location"],
                     r["handed_to"], r.get("employee_code", ""), r["iqama_id"], r["mobile"], r["n_items"],
                     round(r["qty"], 2), round(r["qty_back"], 2),
                     round(r["outstanding"], 2),
                     T.fmt_date(r["expected_return"]),
                     r["days_late"] or "", r["issued_by"],
                     "Yes" if r["source_file"] else "—", r["status"]]
                    for r in rows]
            self.table.fill(self.DOC_COLS, data)
            _paint(self.table, 17, T.STATUS_COLORS)
            _paint(self.table, 1, T.TXN_COLORS)
            out = sum(r["outstanding"] for r in rows)
            self.count.setText(
                f"{len(rows)} document(s) · {out:,.2f} item(s) still out")
        self.reload_filters()
        if self.table.rowCount() and self.table.currentRow() < 0:
            # never leave the detail pane blank on arrival
            self.table.selectRow(0)
        self._load_lines()

    def _selected(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0 or self.table.item(r, 0) is None:
            return None
        ref = self.table.item(r, 0).text()
        return T.by_ref(self.tdb, ref)

    def _load_lines(self):
        h = self._selected()
        if not h:
            self.t_lines.setRowCount(0)
            self.lbl_doc.setText("Select a handover above")
            return
        self.lbl_doc.setText(
            f"{h['ref_no']}  ·  {h['txn_type']}  ·  {h['handed_to'] or '-'}"
            f"  ·  {h['project_id'] or '-'}  ·  status: {h['status']}")
        rows = [[l["line_no"], l["asset_id"], l["category"], l["description"],
                 l["make_model"], l["serial_no"],
                 round(float(l["qty"] or 0), 2),
                 round(float(l["qty_returned"] or 0), 2),
                 round(max(0.0, float(l["qty"] or 0)
                           - float(l["qty_returned"] or 0)), 2),
                 l["accessories"], l["condition"], T.fmt_date(l["calib_due"]),
                 l["remarks"], l.get("photo", "")] for l in h["lines"]]
        self.t_lines.fill(["No.", "Asset / Tool ID", "Category", "Description",
                           "Make / Model", "Serial No.", "Qty", "Returned",
                           "Outstanding", "Accessories", "Cond.", "Calib. Due",
                           "Remarks / Defects", "Picture Path"], rows)

    # ------------------------------------------------------------- actions
    def new_doc(self):
        if HandoverDialog(self.tdb, None, self).exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()
            W.toast(self, "Handover saved.")

    def edit_doc(self):
        h = self._selected()
        if not h:
            W.error_box(self, "Select a handover first.")
            return
        if HandoverDialog(self.tdb, h["id"], self).exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()
            W.toast(self, "Handover updated.")

    def do_return(self):
        h = self._selected()
        if not h:
            W.error_box(self, "Select the handover the items are coming back "
                              "against.")
            return
        if h["status"] in (T.CLOSED, T.CANCELLED, T.TRANSFERRED):
            W.error_box(self, f"{h['ref_no']} is already {h['status'].lower()} "
                              "— nothing is outstanding on it.")
            return
        if ReturnDialog(self.tdb, h, self).exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()
            W.toast(self, "Return registered.")

    def do_transfer(self):
        h = self._selected()
        if not h:
            W.error_box(self, "Select the handover to transfer.")
            return
        if h["status"] in (T.CLOSED, T.CANCELLED, T.TRANSFERRED):
            W.error_box(self, f"{h['ref_no']} is already {h['status'].lower()}.")
            return
        if TransferDialog(self.tdb, h, self).exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()
            W.toast(self, "Custody transferred.")

    def print_form(self):
        h = self._selected()
        if not h:
            W.error_box(self, "Select a handover first.")
            return
        try:
            self.last_file = D.handover_pdf(self.db, self.tdb, h["id"])
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Could not print the form.\n\n{exc}")
            return
        W.toast(self, f"Saved: {self.last_file.name}")
        D.open_path(self.last_file)

    def open_scan(self):
        h = self._selected()
        if not h:
            W.error_box(self, "Select a handover first.")
            return
        src = str(h.get("source_file") or "").strip()
        if not src:
            W.error_box(self, f"{h['ref_no']} has no scanned file linked.\n\n"
                              "Add the folder it lives in on the Sync Folder "
                              "tab and press Sync.")
            return
        if not Path(src).exists():
            W.error_box(self, f"The scanned file is no longer at:\n{src}\n\n"
                              "It may have been moved or the share is offline.")
            return
        D.open_path(Path(src))

    def cancel_doc(self):
        h = self._selected()
        if not h:
            W.error_box(self, "Select a handover first.")
            return
        reason, ok = _ask_text(self, "Cancel handover",
                               f"Why is {h['ref_no']} being cancelled?")
        if not ok:
            return
        try:
            T.cancel_handover(self.tdb, h["id"], reason)
        except ValueError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        self.changed.emit()
        W.toast(self, f"{h['ref_no']} cancelled.")

    def delete_doc(self):
        refs = {self.table.item(i.row(), 0).text()
                for i in self.table.selectedIndexes()
                if self.table.item(i.row(), 0)}
        if not refs:
            W.error_box(self, "Select one or more handovers first.")
            return
        if not W.confirm(self, f"Permanently delete {len(refs)} handover(s)?\n\n"
                               + ", ".join(sorted(refs)[:8])
                               + "\n\nThe custody history goes with them. "
                                 "Cancel instead to keep the record."):
            return
        ids = [T.by_ref(self.tdb, r)["id"] for r in refs
               if T.by_ref(self.tdb, r)]
        n = T.delete_handovers(self.tdb, ids)
        self.reload()
        self.changed.emit()
        W.toast(self, f"{n} handover(s) deleted.")

    def export(self, kind: str):
        if not self.table.rowCount():
            W.error_box(self, "Nothing to export.")
            return
        title = ("Tool Handover Register — items" if self.chk_items.isChecked()
                 else "Tool Handover Register")
        cols = self.table.headers()
        rows = self.table.all_rows()
        if kind == "pdf":
            self.last_file = D.tool_report_pdf(self.db, title, cols, rows)
        else:
            self.last_file = D.export_excel(self.db, title, cols, rows)
        W.toast(self, f"Saved: {self.last_file.name}")
        D.open_path(self.last_file)


def _ask_text(parent, title: str, prompt: str) -> tuple[str, bool]:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(460)
    v = QVBoxLayout(dlg)
    lbl = QLabel(prompt)
    lbl.setWordWrap(True)
    v.addWidget(lbl)
    edit = QLineEdit()
    v.addWidget(edit)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    v.addWidget(bb)
    ok = dlg.exec() == QDialog.Accepted
    text = edit.text().strip()
    if ok and not text:
        W.error_box(parent, "A reason is required.")
        return "", False
    return text, ok


# ============================================================ handover editor
class HandoverDialog(QDialog):
    """Create or edit one handover, following the paper form's sections."""

    def __init__(self, tdb: T.ToolDB, handover_id: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.handover_id = handover_id
        self.row = T.get_handover(tdb, handover_id) if handover_id else {}
        self.setWindowTitle(
            f"Edit Handover — {self.row.get('ref_no')}" if handover_id
            else "New Tools / Instruments Handover")
        self.resize(1080, 720)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        # ---- A + B
        g = QWidget()
        form = QFormLayout(g)
        form.setLabelAlignment(Qt.AlignRight)
        r = self.row
        self.ref = QLineEdit(r.get("ref_no", ""))
        self.ref.setPlaceholderText("leave blank to generate, e.g. "
                                    "WH-087IS2308202601")
        form.addRow("Handover Reference", self.ref)
        self.form_no = QLineEdit(r.get("form_no", ""))
        form.addRow("Form No.", self.form_no)
        self.txn = W.combo(list(T.TXN_TYPES), False, r.get("txn_type", T.ISSUE))
        self.txn.currentTextChanged.connect(self._type_changed)
        form.addRow("Transaction Type *", self.txn)
        self.date = date_edit(r.get("doc_date") or T.today())
        form.addRow("Date *", self.date)
        self.time = QLineEdit(r.get("doc_time", ""))
        self.time.setPlaceholderText("HH:MM")
        form.addRow("Time", self.time)
        self.exp = QLineEdit(r.get("expected_return", ""))
        self.exp.setPlaceholderText("yyyy-mm-dd — required for a temporary loan")
        form.addRow("Expected Return Date", self.exp)
        self.wh = QLineEdit(r.get("warehouse", "WH"))
        form.addRow("Warehouse", self.wh)
        self.proj = QLineEdit(r.get("project_id", ""))
        form.addRow("Project ID", self.proj)
        self.projname = QLineEdit(r.get("project_name", ""))
        form.addRow("Project Name", self.projname)
        self.loc = QLineEdit(r.get("location", ""))
        form.addRow("Project / Site Location", self.loc)
        tabs.addTab(g, "A · Handover Details")

        b = QWidget()
        bf = QFormLayout(b)
        bf.setLabelAlignment(Qt.AlignRight)
        self.to = QLineEdit(r.get("handed_to", ""))
        bf.addRow("Handed To (full name) *", self.to)
        self.emp_code = QLineEdit(r.get("employee_code", ""))
        bf.addRow("Employee Code", self.emp_code)
        self.iqama = QLineEdit(r.get("iqama_id", ""))
        bf.addRow("Iqama / National ID", self.iqama)
        self.job = QLineEdit(r.get("job_title", ""))
        bf.addRow("Designation / Job Title", self.job)
        self.dept = QLineEdit(r.get("department", ""))
        bf.addRow("Division / Department", self.dept)
        self.mob = QLineEdit(r.get("mobile", ""))
        bf.addRow("Mobile No.", self.mob)
        self.comp = QLineEdit(r.get("company", "AURCO"))
        bf.addRow("Company", self.comp)
        self.mail = QLineEdit(r.get("email", ""))
        bf.addRow("Email", self.mail)
        self.sup = QLineEdit(r.get("supervisor", ""))
        bf.addRow("Supervisor / Manager", self.sup)
        self.cost = QLineEdit(r.get("cost_code", ""))
        bf.addRow("Cost Code / WBS", self.cost)
        tabs.addTab(b, "B · Recipient / Custodian")

        # ---- C items
        c = QWidget()
        cv = QVBoxLayout(c)
        row = QHBoxLayout()
        row.addWidget(W.button("➕  Add Row", "Primary", self._add_row))
        row.addWidget(W.button("🗑  Remove Selected", slot=self._del_row))
        row.addWidget(W.button("📋  Paste from Excel", slot=self._paste))
        row.addStretch(1)
        cv.addLayout(row)
        self.items = QTableWidget(0, len(self.ITEM_HEADS))
        self.items.setHorizontalHeaderLabels(self.ITEM_HEADS)
        self.items.setSelectionBehavior(QAbstractItemView.SelectRows)
        cv.addWidget(self.items, 1)
        note = QLabel("Condition grade:  A – New / Excellent   B – Good   "
                      "C – Fair / Usable   D – Damaged / Not Usable")
        note.setStyleSheet(f"color:{W.MUTED};")
        cv.addWidget(note)
        tabs.addTab(c, "C · Item Details")

        # ---- D acknowledgement
        d = QWidget()
        df = QFormLayout(d)
        df.setLabelAlignment(Qt.AlignRight)
        self.iss_by = QLineEdit(r.get("issued_by", ""))
        df.addRow("Issued By — Warehouse", self.iss_by)
        self.iss_at = QLineEdit(r.get("issued_at", ""))
        df.addRow("Issued Date / Time", self.iss_at)
        self.rec_by = QLineEdit(r.get("received_by", ""))
        df.addRow("Received By — Custodian", self.rec_by)
        self.rec_at = QLineEdit(r.get("received_at", ""))
        df.addRow("Received Date / Time", self.rec_at)
        self.v1 = QCheckBox("Serial / Asset ID checked")
        self.v2 = QCheckBox("Accessories checked")
        self.v3 = QCheckBox("Calibration valid")
        self.v4 = QCheckBox("Photos attached")
        for chk, key in ((self.v1, "v_serial"), (self.v2, "v_accessories"),
                         (self.v3, "v_calibration"), (self.v4, "v_photos")):
            chk.setChecked(bool(r.get(key)))
            df.addRow("", chk)
        self.remarks = QPlainTextEdit(r.get("remarks", ""))
        self.remarks.setMaximumHeight(70)
        df.addRow("Remarks", self.remarks)
        tabs.addTab(d, "D · Acknowledgement")

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        for ln in (self.row.get("lines") or []):
            self._add_row(ln)
        if not self.handover_id:
            self._add_row()
        self._type_changed()

    ITEM_HEADS = ["Asset / Tool ID", "Category", "Description", "Make / Model",
                  "Serial No.", "Qty", "Accessories", "Cond.", "Calib. Due",
                  "Remarks", "Picture Path"]
    _KEYS = ["asset_id", "category", "description", "make_model", "serial_no",
             "qty", "accessories", "condition", "calib_due", "remarks", "photo"]

    def _type_changed(self):
        loan = self.txn.currentText() == T.LOAN
        self.exp.setEnabled(True)
        self.exp.setStyleSheet("border:1px solid #e8590c;" if loan and
                               not self.exp.text().strip() else "")

    def _add_row(self, data: dict | None = None):
        data = data if isinstance(data, dict) else {}
        r = self.items.rowCount()
        self.items.insertRow(r)
        for c, key in enumerate(self._KEYS):
            val = data.get(key, "")
            if key == "qty" and not val:
                val = 1
            self.items.setItem(r, c, QTableWidgetItem(str(val)))

    def _del_row(self):
        for i in sorted({x.row() for x in self.items.selectedIndexes()},
                        reverse=True):
            self.items.removeRow(i)

    def _paste(self):
        from PySide6.QtWidgets import QApplication
        text = QApplication.clipboard().text()
        if not text.strip():
            W.error_box(self, "The clipboard is empty.")
            return
        head, rows = T.sniff(text)
        lines = T.rows_to_lines(head, rows)
        if not lines:
            W.error_box(self, "No item rows were recognised.\n\nExpected "
                              "columns such as Asset ID, Description, Serial "
                              "No., Qty.")
            return
        for ln in lines:
            self._add_row(ln)
        W.toast(self, f"{len(lines)} row(s) pasted.")

    def _collect(self) -> list[dict]:
        out = []
        for r in range(self.items.rowCount()):
            d = {}
            for c, key in enumerate(self._KEYS):
                it = self.items.item(r, c)
                d[key] = it.text().strip() if it else ""
            if not (d["asset_id"] or d["description"]):
                continue
            d["line_no"] = len(out) + 1
            d["qty"] = T.to_float(d["qty"], 1) or 1
            out.append(d)
        return out

    def _save(self):
        if not self.to.text().strip():
            W.error_box(self, "Enter who is receiving the items "
                              "(Handed To).")
            return
        lines = self._collect()
        if not lines:
            W.error_box(self, "Add at least one item line.")
            return
        if self.txn.currentText() == T.LOAN and not self.exp.text().strip():
            W.error_box(self, "A Temporary Loan needs an Expected Return Date "
                              "— that is what makes it a loan rather than an "
                              "issue.")
            return
        head = {
            "ref_no": self.ref.text().strip(),
            "form_no": self.form_no.text().strip(),
            "txn_type": self.txn.currentText(),
            "doc_date": iso(self.date),
            "doc_time": self.time.text().strip(),
            "expected_return": self.exp.text().strip(),
            "warehouse": self.wh.text().strip(),
            "project_id": self.proj.text().strip(),
            "project_name": self.projname.text().strip(),
            "location": self.loc.text().strip(),
            "handed_to": self.to.text().strip(),
            "employee_code": self.emp_code.text().strip(),
            "iqama_id": self.iqama.text().strip(),
            "job_title": self.job.text().strip(),
            "department": self.dept.text().strip(),
            "mobile": self.mob.text().strip(),
            "company": self.comp.text().strip(),
            "email": self.mail.text().strip(),
            "supervisor": self.sup.text().strip(),
            "cost_code": self.cost.text().strip(),
            "issued_by": self.iss_by.text().strip(),
            "issued_at": self.iss_at.text().strip(),
            "received_by": self.rec_by.text().strip(),
            "received_at": self.rec_at.text().strip(),
            "v_serial": self.v1.isChecked(),
            "v_accessories": self.v2.isChecked(),
            "v_calibration": self.v3.isChecked(),
            "v_photos": self.v4.isChecked(),
            "remarks": self.remarks.toPlainText().strip(),
            "source_file": self.row.get("source_file", ""),
        }
        try:
            T.save_handover(self.tdb, head, lines, self.handover_id)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Could not save the handover.\n\n{exc}")
            return
        self.accept()


# ================================================================== dialogs
class ReturnDialog(QDialog):
    """Book items back in against an open handover."""

    def __init__(self, tdb: T.ToolDB, handover: dict, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.h = handover
        self.setWindowTitle(f"Register Return — {handover['ref_no']}")
        self.resize(940, 520)
        v = QVBoxLayout(self)
        head = QLabel(
            f"<b>{handover['ref_no']}</b> · {handover['txn_type']} · held by "
            f"<b>{handover['handed_to'] or '-'}</b> · {handover['project_id'] or '-'}")
        head.setWordWrap(True)
        head.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER};"
                           "border-radius:8px; padding:8px;")
        v.addWidget(head)
        note = QLabel("Enter the quantity coming back on each line. Leave a "
                      "line at 0 to keep it out with the custodian — partial "
                      "returns are normal and are tracked.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(note)

        bar = QHBoxLayout()
        bar.addWidget(W.button("↩  Return Everything Outstanding", "Primary",
                               self._all))
        bar.addWidget(QLabel("Condition on return:"))
        self.cond = W.combo([""] + list(T.CONDITIONS))
        bar.addWidget(self.cond)
        bar.addWidget(W.button("Apply to all", slot=self._apply_cond))
        bar.addStretch(1)
        v.addLayout(bar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Asset / Tool ID", "Description", "Serial No.", "Outstanding",
             "Returning", "Cond.", "Remarks", "After Picture Path"])
        v.addWidget(self.table, 1)
        self.lines = [l for l in handover["lines"]
                      if float(l["qty"] or 0) - float(l["qty_returned"] or 0) > 1e-9]
        for l in self.lines:
            r = self.table.rowCount()
            self.table.insertRow(r)
            out = float(l["qty"] or 0) - float(l["qty_returned"] or 0)
            for c, val in enumerate([l["asset_id"], l["description"],
                                     l["serial_no"], f"{out:g}", "0",
                                     l["condition"], "", l.get("photo", "")]):
                it = QTableWidgetItem(str(val))
                if c < 4:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _all(self):
        for r in range(self.table.rowCount()):
            self.table.item(r, 4).setText(self.table.item(r, 3).text())

    def _apply_cond(self):
        c = self.cond.currentText().strip()[:1]
        for r in range(self.table.rowCount()):
            self.table.item(r, 5).setText(c)

    def _save(self):
        rets = []
        for r, l in enumerate(self.lines):
            qty = T.to_float(self.table.item(r, 4).text(), 0)
            if qty <= 0:
                continue
            rets.append({"line_id": l["id"], "qty": qty,
                         "condition": self.table.item(r, 5).text().strip(),
                         "remarks": self.table.item(r, 6).text().strip(),
                         "photo": self.table.item(r, 7).text().strip()})
        if not rets:
            W.error_box(self, "Enter a quantity on at least one line.")
            return
        try:
            T.post_return(self.tdb, self.h["ref_no"], rets)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Could not register the return.\n\n{exc}")
            return
        self.accept()


class TransferDialog(QDialog):
    """Move custody of a handover to another person."""

    def __init__(self, tdb: T.ToolDB, handover: dict, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.h = handover
        self.setWindowTitle(f"Transfer Custody — {handover['ref_no']}")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        out = sum(max(0.0, float(l["qty"] or 0) - float(l["qty_returned"] or 0))
                  for l in handover["lines"])
        head = QLabel(
            f"<b>{out:g}</b> item(s) currently with "
            f"<b>{handover['handed_to'] or '-'}</b> will move to the person "
            "below.<br>A new Transfer document is created and the original is "
            "closed as <b>Transferred Out</b> — the instruments never went back to "
            "the warehouse, so it is not recorded as a return.")
        head.setWordWrap(True)
        head.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER};"
                           "border-radius:8px; padding:8px;")
        v.addWidget(head)

        form = QFormLayout()
        self.to = QLineEdit()
        form.addRow("Transfer To (full name) *", self.to)
        self.emp_code = QLineEdit()
        form.addRow("Employee Code", self.emp_code)
        self.iqama = QLineEdit()
        form.addRow("Iqama / National ID", self.iqama)
        self.job = QLineEdit()
        form.addRow("Designation / Job Title", self.job)
        self.dept = QLineEdit()
        form.addRow("Division / Department", self.dept)
        self.mob = QLineEdit()
        form.addRow("Mobile No.", self.mob)
        self.proj = QLineEdit(handover.get("project_id", ""))
        form.addRow("Project / Site", self.proj)
        self.loc = QLineEdit(handover.get("location", ""))
        form.addRow("Location", self.loc)
        self.date = date_edit(T.today())
        form.addRow("Transfer Date", self.date)
        self.resp = QLineEdit()
        form.addRow("Responsible Person", self.resp)
        self.by = QLineEdit()
        form.addRow("Authorised By", self.by)
        self.after_photo = QLineEdit()
        form.addRow("After Picture Path", self.after_photo)
        v.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _save(self):
        if not self.to.text().strip():
            W.error_box(self, "Enter who is taking custody.")
            return
        try:
            T.post_transfer(self.tdb, self.h["ref_no"], {
                "handed_to": self.to.text().strip(),
                "employee_code": self.emp_code.text().strip(),
                "iqama_id": self.iqama.text().strip(),
                "job_title": self.job.text().strip(),
                "department": self.dept.text().strip(),
                "mobile": self.mob.text().strip(),
                "project_id": self.proj.text().strip(),
                "location": self.loc.text().strip(),
                "doc_date": iso(self.date),
                "company": self.resp.text().strip(),
                "issued_by": self.by.text().strip(),
                "photo": self.after_photo.text().strip(),
            })
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Could not transfer custody.\n\n{exc}")
            return
        self.accept()


# ================================================================ assets tab
class AssetsTab(QWidget):
    """Where is each instrument right now, and how did it get there."""

    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search asset ID, description, serial, "
                                  "holder ...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 3)
        self.f_status = W.combo(["All Status", "In Store", "Issued Out",
                                 "On Loan", "Overdue"])
        self.f_cat = W.combo(["All Categories"])
        for cb in (self.f_status, self.f_cat):
            cb.currentTextChanged.connect(self.reload)
            bar.addWidget(cb)
        bar.addWidget(W.button("🔄  Rebuild Register", slot=self._rebuild,
                               tip="Recompute every asset from its handover "
                                   "history"))
        bar.addWidget(W.button("📊  Excel", slot=self._excel))
        v.addLayout(bar)

        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        self.table = W.DataTable()
        self.table.itemSelectionChanged.connect(self._history)
        tv.addWidget(W.FilterBar(self.table))
        tv.addWidget(self.table)
        split.addWidget(top)

        bot = QWidget()
        bv = QVBoxLayout(bot)
        bv.setContentsMargins(0, 6, 0, 0)
        self.lbl = QLabel("Select an asset to see its movement history")
        self.lbl.setStyleSheet(f"color:{W.NAVY}; font-weight:700;")
        bv.addWidget(self.lbl)
        self.t_hist = W.DataTable()
        bv.addWidget(self.t_hist, 1)
        split.addWidget(bot)
        split.setSizes([360, 260])
        v.addWidget(split, 1)

    def reload(self):
        st = "" if self.f_status.currentIndex() <= 0 else self.f_status.currentText()
        cat = "" if self.f_cat.currentIndex() <= 0 else self.f_cat.currentText()
        rows = T.search_assets(self.tdb, self.search.text(), st, "", cat)
        data = [[a["asset_id"], a["category"], a["description"],
                 a["make_model"], a["serial_no"], a["status"], a["holder"],
                 a["holder_iqama"], a["project_id"], a["location"],
                 a["condition"], T.fmt_date(a["calib_due"]),
                 "" if a["calib_days"] is None else a["calib_days"],
                 a["last_ref"], T.fmt_date(a["last_date"])] for a in rows]
        self.table.fill(["Asset / Tool ID", "Category", "Description",
                         "Make / Model", "Serial No.", "Status", "Held By",
                         "Iqama / ID", "Project", "Location", "Cond.",
                         "Calib. Due", "Days to Calib.", "Last Reference",
                         "Last Movement"], data)
        _paint(self.table, 5, {"In Store": "#1a9c52", "Issued Out": "#1098ad",
                               "On Loan": "#e8590c", "Overdue": "#c92a2a"})
        cur = self.f_cat.currentText()
        self.f_cat.blockSignals(True)
        self.f_cat.clear()
        self.f_cat.addItems(["All Categories"] + T.distinct(self.tdb, "category"))
        i = self.f_cat.findText(cur)
        self.f_cat.setCurrentIndex(max(0, i))
        self.f_cat.blockSignals(False)
        if self.table.rowCount() and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._history()

    def _history(self):
        r = self.table.currentRow()
        if r < 0 or self.table.item(r, 0) is None:
            self.t_hist.setRowCount(0)
            self.lbl.setText("Select an asset to see its movement history")
            return
        aid = self.table.item(r, 0).text()
        self.lbl.setText(f"Movement history — {aid}")
        rows = [[h["ref_no"], h["txn_type"], T.fmt_date(h["doc_date"]),
                 h["doc_time"], h["handed_to"], h.get("employee_code", ""), h["iqama_id"], h["project_id"],
                 h["location"], round(float(h["qty"] or 0), 2),
                 round(float(h["qty_returned"] or 0), 2), h["condition"],
                 h["issued_by"], h.get("remarks", ""), h.get("photo", ""), h["status"]]
                for h in T.asset_history(self.tdb, aid)]
        self.t_hist.fill(["Reference", "Type", "Date", "Time", "Handed To",
                          "Employee Code", "Iqama / ID", "Project", "Location", "Qty",
                          "Returned", "Cond.", "Issued By", "Remarks", "Picture Path", "Status"], rows)
        _paint(self.t_hist, 15, T.STATUS_COLORS)
        _paint(self.t_hist, 1, T.TXN_COLORS)

    def _rebuild(self):
        n = T.rebuild_assets(self.tdb)
        self.reload()
        W.toast(self, f"{n} asset(s) rebuilt from the handover history.")

    def _excel(self):
        if not self.table.rowCount():
            W.error_box(self, "Nothing to export.")
            return
        self.last_file = D.export_excel(self.db, "Tool Asset Register",
                                        self.table.headers(),
                                        self.table.all_rows())
        W.toast(self, f"Saved: {self.last_file.name}")
        D.open_path(self.last_file)


# =========================================================== sync folder tab
class SyncFolderTab(QWidget):
    """Index signed handover PDFs, and manage site-wise Excel sync folders too."""
    imported = Signal()

    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.files: list[dict] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(9)

        card = W.Card("Synchronised handover folders")
        note = QLabel(
            "Point this at the folder your signed handover forms sync to — a "
            "local drive, a network share or a OneDrive / Google Drive folder. "
            "AURCO reads every PDF, decodes the reference number, and files the "
            "handover automatically.<br><b>Files are only ever read.</b> "
            "Nothing in the synchronised folder is moved, renamed or deleted.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        card.add(note)
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText(
            r"e.g.  \\server\shared\AURCO Handovers   or   D:\Handover Forms")
        row.addWidget(self.path, 1)
        row.addWidget(W.button("📂  Browse...", "Primary", self._browse))
        row.addWidget(W.button("➕  Add Folder", slot=self._add))
        rw = QWidget()
        rw.setLayout(row)
        card.add(rw)
        self.t_folders = W.DataTable()
        self.t_folders.setMaximumHeight(130)
        card.add(self.t_folders)
        frow = QHBoxLayout()
        frow.addWidget(W.button("🔄  Sync All Folders", "Accent", self.sync_all))
        frow.addWidget(W.button("🗑  Remove Folder", slot=self._remove))
        frow.addWidget(W.button("📁  Open Folder", slot=self._open))
        frow.addStretch(1)
        self.status = QLabel("No folder added yet.")
        self.status.setStyleSheet(f"color:{W.MUTED};")
        frow.addWidget(self.status)
        fw = QWidget()
        fw.setLayout(frow)
        card.add(fw)
        v.addWidget(card)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search file name or reference ...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 2)
        self.f_status = W.combo(["All", "New", "Imported", "Linked",
                                 "Unreadable", "Failed", "Missing"])
        self.f_status.currentTextChanged.connect(self.reload)
        bar.addWidget(self.f_status)
        bar.addWidget(W.button("⬆  Import Selected", "Primary", self._import_sel))
        bar.addWidget(W.button("♻  Re-import (overwrite)", slot=self._reimport))
        bar.addWidget(W.button("📎  Open File", slot=self._open_file))
        bar.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        bar.addWidget(self.count)
        v.addLayout(bar)

        self.table = W.DataTable()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(self.table, 1)

        self.site_excel = SiteExcelSyncPanel(self.tdb, self.db)
        self.site_excel.imported.connect(self.imported.emit)
        v.addWidget(self.site_excel)
        self.reload()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select the handover folder")
        if d:
            self.path.setText(d)

    def _add(self):
        p = self.path.text().strip()
        if not p:
            W.error_box(self, "Choose a folder first.")
            return
        try:
            T.add_folder(self.tdb, p)
        except ValueError as exc:
            W.error_box(self, str(exc))
            return
        self.path.clear()
        self.reload()
        W.toast(self, "Folder added. Press Sync All Folders to read it.")

    def _sel_folder(self) -> dict | None:
        r = self.t_folders.currentRow()
        if r < 0 or self.t_folders.item(r, 0) is None:
            return None
        path = self.t_folders.item(r, 1).text()
        return next((f for f in T.folders(self.tdb) if f["path"] == path), None)

    def _remove(self):
        f = self._sel_folder()
        if not f:
            W.error_box(self, "Select a folder in the list first.")
            return
        if not W.confirm(self, f"Stop watching this folder?\n\n{f['path']}\n\n"
                               "The files themselves are never touched."):
            return
        T.remove_folder(self.tdb, f["id"])
        self.reload()

    def _open(self):
        f = self._sel_folder()
        if f:
            D.open_path(Path(f["path"]))

    def sync_all(self):
        res = T.sync_all(self.tdb, auto_import=True)
        self.reload()
        self.imported.emit()
        msg = (f"{res['seen']} file(s) seen · {res['new']} new · "
               f"{res['imported']} handover(s) imported")
        if res["offline"]:
            msg += f" · {len(res['offline'])} folder(s) offline"
        W.toast(self, msg)
        if res["errors"]:
            W.info_box(self, "Some files could not be read:\n\n"
                       + "\n".join(res["errors"][:12]), "Sync report")

    def reload(self):
        frows = [[f["label"], f["path"], "Online" if f["online"] else "OFFLINE",
                  f["files"], f["last_scan"] or "never"]
                 for f in T.folders(self.tdb)]
        self.t_folders.fill(["Label", "Folder", "State", "Files", "Last Sync"],
                            frows)
        _paint(self.t_folders, 2, {"Online": "#1a9c52", "OFFLINE": "#c92a2a"})

        st = "" if self.f_status.currentIndex() <= 0 else self.f_status.currentText()
        self.files = T.scan_files(self.tdb, st, self.search.text().strip())
        rows = [[f["name"], f["ref_no"], f["status"], f["size_kb"],
                 f["modified"], f["note"], f["path"]] for f in self.files]
        self.table.fill(["File", "Reference", "Status", "Size (KB)",
                         "Modified", "Note", "Full Path"], rows)
        _paint(self.table, 2, {"Imported": "#1a9c52", "Linked": "#1098ad",
                               "New": "#9a6700", "Unreadable": "#c92a2a",
                               "Failed": "#c92a2a", "Missing": "#c92a2a"})
        self.count.setText(f"{len(rows)} file(s)")
        online = [f for f in T.folders(self.tdb) if f["online"]]
        self.status.setText(
            f"{len(online)} of {len(T.folders(self.tdb))} folder(s) online")

    def _sel_paths(self) -> list[str]:
        return [self.table.item(i.row(), 6).text()
                for i in self.table.selectedIndexes()
                if self.table.item(i.row(), 6)] or []

    def _import_sel(self, overwrite: bool = False):
        paths = sorted(set(self._sel_paths()))
        if not paths:
            W.error_box(self, "Select one or more files first.")
            return
        res = T.import_folder_files(self.tdb, paths, overwrite)
        self.reload()
        self.imported.emit()
        W.toast(self, f"{res['imported']} imported · {res['skipped']} skipped "
                      f"· {res['failed']} failed")
        if res["errors"]:
            W.info_box(self, "\n".join(res["errors"][:12]), "Import report")

    def _reimport(self):
        if not W.confirm(self, "Re-read the selected file(s) and overwrite the "
                               "handover already in the register?\n\n"
                               "Use this after a form has been corrected and "
                               "re-scanned."):
            return
        self._import_sel(overwrite=True)

    def _open_file(self):
        paths = self._sel_paths()
        if not paths:
            W.error_box(self, "Select a file first.")
            return
        p = Path(paths[0])
        if not p.exists():
            W.error_box(self, f"The file is no longer at:\n{p}")
            return
        D.open_path(p)


# =============================================================== reports tab
class ToolReportsTab(QWidget):
    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.pick = W.combo(T.REPORT_LIST)
        self.pick.currentTextChanged.connect(self.run)
        bar.addWidget(QLabel("Report:"))
        bar.addWidget(self.pick, 2)
        self.search = W.SearchBox("Filter text ...")
        self.search.textChanged.connect(self.run)
        bar.addWidget(self.search, 1)
        bar.addWidget(W.button("▶  Run", "Primary", self.run))
        v.addLayout(bar)

        act = QHBoxLayout()
        act.addWidget(W.button("📄  PDF", "Accent", lambda: self.export("pdf")))
        act.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        act.addWidget(W.button("📋  CSV", slot=lambda: self.export("csv")))
        act.addWidget(W.button("🖨  Print", slot=self.print_out))
        act.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        act.addWidget(self.count)
        v.addLayout(act)

        self.table = W.DataTable()
        v.addWidget(W.FilterBar(self.table))
        v.addWidget(self.table, 1)
        v.addWidget(ShareBar(self.db, lambda: self.last_file, self))

    def run(self):
        name = self.pick.currentText()
        f = {"text": self.search.text().strip()} if self.search.text().strip() else {}
        title, cols, rows = T.build_report(self.tdb, name, f)
        self.title, self.cols, self.rows = title, cols, rows
        self.table.fill(cols, rows)
        for i, c in enumerate(cols):
            if c.strip().lower() in ("status", "line status"):
                _paint(self.table, i, T.STATUS_COLORS)
            if c.strip().lower() == "type":
                _paint(self.table, i, T.TXN_COLORS)
        self.count.setText(f"{len(rows)} row(s)")

    def export(self, kind: str):
        if not getattr(self, "rows", None):
            self.run()
        if not self.rows:
            W.error_box(self, "This report has no rows to export.")
            return
        fn = {"pdf": D.tool_report_pdf, "xlsx": D.export_excel,
              "csv": D.export_csv}[kind]
        self.last_file = fn(self.db, self.title, self.cols, self.rows)
        W.toast(self, f"Saved: {self.last_file.name}")
        D.open_path(self.last_file)

    def print_out(self):
        if not getattr(self, "rows", None):
            self.run()
        if not self.rows:
            W.error_box(self, "This report has no rows to print.")
            return
        self.last_file = D.tool_report_pdf(self.db, self.title, self.cols,
                                           self.rows)
        D.print_file(self.db, self.last_file)


# ================================================================= the page
class ToolStationPage(QWidget):
    """Top-level page holding the five Instrument Station tabs."""
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.tdb = T.get_tool_db()
        self.tdb.current_user = db.current_user
        T.refresh_all_statuses(self.tdb)

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)

        banner = QLabel(
            "🎛  <b>Instrument Station</b> — a stand-alone custody register "
            "for instruments, devices and related field equipment: issue, transfer, temporary loan and "
            "return. It has its own database file "
            f"(<code>{self.tdb.path.name}</code>), its own backups and its own "
            "reports. Nothing here affects inventory stock.")
        banner.setWordWrap(True)
        banner.setStyleSheet(
            f"background:{W.NAVY}; color:white; border-radius:7px; "
            "padding:8px 12px;")
        v.addWidget(banner)

        self.tabs = QTabWidget()
        self.dash = ToolDashboard(self.tdb, db)
        self.register = RegisterTab(self.tdb, db)
        self.assets = AssetsTab(self.tdb, db)
        self.sync = SyncFolderTab(self.tdb, db)
        self.reports = ToolReportsTab(self.tdb, db)
        self.tabs.addTab(self.dash, "📊  Dashboard")
        self.tabs.addTab(self.register, "📋  Handover Register")
        self.tabs.addTab(self.assets, "🔧  Assets")
        self.tabs.addTab(self.sync, "📂  Sync Folder")
        self.tabs.addTab(self.reports, "📈  Reports")
        v.addWidget(self.tabs, 1)

        tools = QHBoxLayout()
        tools.addWidget(W.button("💾  Backup Module", slot=self._backup,
                                 tip="Back up the Instrument Station database"))
        tools.addWidget(W.button("♻  Restore...", slot=self._restore))
        tools.addWidget(W.button("📂  Open Data Folder", slot=self._folder))
        tools.addWidget(W.button("🔄  Refresh", slot=self.refresh))
        tools.addStretch(1)
        self.stat = QLabel()
        self.stat.setStyleSheet(f"color:{W.MUTED};")
        tools.addWidget(self.stat)
        v.addLayout(tools)

        self.register.changed.connect(self.refresh)
        self.dash.openRegister.connect(self._drill)
        self.sync.imported.connect(self.refresh)
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        self.refresh()

    def _drill(self, f: dict):
        self.tabs.setCurrentWidget(self.register)
        self.register.apply_filter(f)

    def refresh(self):
        T.refresh_all_statuses(self.tdb)
        i = self.tabs.currentIndex()
        if i == 0:
            self.dash.reload_filters()
            self.dash.reload()
        elif i == 1:
            self.register.reload()
        elif i == 2:
            self.assets.reload()
        elif i == 3:
            self.sync.reload()
        else:
            self.reports.run()
        d = T.dashboard(self.tdb)
        self.stat.setText(
            f"{d['documents']} handover document(s) · {d.get('total_tools', 0)} synced instrument row(s) · "
            f"{d.get('site_files', 0)} Excel file(s) · {d.get('sites_covered', 0)} site(s) · "
            f"{d['overdue']} overdue")
        self.dataChanged.emit()

    def _backup(self):
        try:
            p = self.tdb.backup(note="manual backup")
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Backup failed.\n\n{exc}")
            return
        W.info_box(self, f"Instrument Station backed up to:\n\n{p}",
                   "Backup complete")

    def _restore(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Restore the Instrument Station database", "",
            "Database (*.db)")
        if not f:
            return
        if not W.confirm(self, "Replace the current Instrument Station data with this "
                               "backup?\n\nA safety copy of the current data is "
                               "taken first."):
            return
        try:
            self.tdb.restore(f)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Restore failed.\n\n{exc}")
            return
        self.refresh()
        W.toast(self, "Instrument Station restored.")

    def _folder(self):
        D.open_path(T.module_folder())


class SiteExcelSyncPanel(QWidget):
    """Site-wise Excel synchronisation inside the Tools module."""
    imported = Signal()

    def __init__(self, tdb: T.ToolDB, db: Database, parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.files: list[dict] = []
        self.folders: list[dict] = []
        self.last_file: Path | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(9)

        sample = W.Card("Site-wise Excel folder sync")
        note = QLabel(
            "Each site can maintain its own Excel sheet in a shared folder. AURCO "
            "reads new or updated files, maps the columns intelligently, avoids "
            "duplicate reposting, and keeps a file-wise sync history with errors."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        sample.add(note)
        cols, rows = T.site_sync_template_rows()
        self.t_sample = W.DataTable()
        self.t_sample.fill(cols, rows)
        self.t_sample.setMaximumHeight(130)
        sample.add(self.t_sample)
        a = QHBoxLayout()
        a.addWidget(W.button("⬇  Download Sample Excel File", slot=self._template))
        a.addWidget(W.button("📂  Import Excel", "Primary", self._import_excel))
        a.addWidget(W.button("📂  Bulk Import Files", slot=self._bulk_import))
        a.addWidget(W.button("📊  Export Excel", slot=self._export_inventory))
        a.addWidget(W.button("🔄  Manual Sync Now", "Accent", self._sync_all))
        a.addStretch(1)
        self.lbl_sync = QLabel()
        self.lbl_sync.setStyleSheet(f"color:{W.MUTED};")
        a.addWidget(self.lbl_sync)
        aw = QWidget(); aw.setLayout(a)
        sample.add(aw)
        v.addWidget(sample)

        cfg = W.Card("Folder Sync Settings")
        grid = QGridLayout()
        self.e_path = QLineEdit()
        self.e_path.setPlaceholderText(r"e.g. \\server\shared\Site Excel Inventory")
        self.e_label = QLineEdit()
        self.e_label.setPlaceholderText("Folder label")
        self.e_site = QLineEdit()
        self.e_site.setPlaceholderText("Default site (optional)")
        self.chk_auto = QCheckBox("Enable automatic synchronisation")
        self.sp_interval = QSpinBox(); self.sp_interval.setRange(1, 1440); self.sp_interval.setValue(5)
        self.sp_interval.setSuffix(" min")
        grid.addWidget(QLabel("Folder Path"), 0, 0)
        grid.addWidget(self.e_path, 0, 1, 1, 4)
        grid.addWidget(W.button("Browse...", slot=self._browse_folder), 0, 5)
        grid.addWidget(QLabel("Label"), 1, 0)
        grid.addWidget(self.e_label, 1, 1)
        grid.addWidget(QLabel("Assign to Site"), 1, 2)
        grid.addWidget(self.e_site, 1, 3)
        grid.addWidget(self.chk_auto, 1, 4)
        grid.addWidget(self.sp_interval, 1, 5)
        brow = QHBoxLayout()
        brow.addWidget(W.button("💾  Save / Update Folder", slot=self._save_folder))
        brow.addWidget(W.button("🗑  Remove Folder", slot=self._remove_folder))
        brow.addWidget(W.button("🔄  Sync Selected Folder", slot=self._sync_selected_folder))
        brow.addWidget(W.button("📁  Open Folder", slot=self._open_folder))
        brow.addStretch(1)
        self.lbl_folder_status = QLabel()
        self.lbl_folder_status.setStyleSheet(f"color:{W.MUTED};")
        brow.addWidget(self.lbl_folder_status)
        bw = QWidget(); bw.setLayout(brow)
        gw = QWidget(); gw.setLayout(grid)
        cfg.add(gw)
        self.t_folders = W.DataTable()
        self.t_folders.setMaximumHeight(150)
        self.t_folders.itemSelectionChanged.connect(self._load_folder_form)
        cfg.add(self.t_folders)
        cfg.add(bw)
        v.addWidget(cfg)

        files = W.Card("File-wise sync status and history")
        fbar = QHBoxLayout()
        self.search = W.SearchBox("Search file, site or note ...")
        self.search.textChanged.connect(self.reload)
        self.f_status = W.combo(["All", "New", "Synced", "Failed", "Unchanged"])
        self.f_status.currentTextChanged.connect(self.reload)
        fbar.addWidget(self.search, 1)
        fbar.addWidget(self.f_status)
        fbar.addWidget(W.button("♻  Reprocess Selected", slot=self._reprocess_selected))
        fbar.addWidget(W.button("📎  Open File", slot=self._open_file))
        fbar.addStretch(1)
        self.lbl_counts = QLabel()
        self.lbl_counts.setStyleSheet(f"color:{W.MUTED};")
        fbar.addWidget(self.lbl_counts)
        fw = QWidget(); fw.setLayout(fbar)
        files.add(fw)
        self.t_files = W.DataTable()
        self.t_files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.t_files.itemSelectionChanged.connect(self._reload_history)
        files.add(self.t_files, 1)
        self.t_history = W.DataTable()
        self.t_history.setMaximumHeight(160)
        files.add(self.t_history)
        v.addWidget(files, 1)

        inv = W.Card("Current synced instrument inventory")
        inv_note = QLabel(
            "Manual entries are supported here too. Add an instrument with picture proof, "
            "then edit, transfer or return it later while keeping the movement history."
        )
        inv_note.setWordWrap(True)
        inv_note.setStyleSheet(f"color:{W.MUTED};")
        inv.add(inv_note)
        ibar = QHBoxLayout()
        ibar.addWidget(W.button("➕  Add Manual Instrument", "Primary", self._add_inventory))
        ibar.addWidget(W.button("✏  Edit Selected", slot=self._edit_inventory))
        ibar.addWidget(W.button("🔁  Transfer Selected", slot=self._transfer_inventory))
        ibar.addWidget(W.button("↩  Return Selected", "Accent", self._return_inventory))
        ibar.addWidget(W.button("🖼  Open Picture Proof", slot=self._open_inventory_picture))
        ibar.addStretch(1)
        invw = QWidget(); invw.setLayout(ibar)
        inv.add(invw)
        self.t_inventory = W.DataTable()
        self.t_inventory.itemSelectionChanged.connect(self._reload_asset_events)
        inv.add(self.t_inventory, 1)
        self.t_events = W.DataTable()
        self.t_events.setMaximumHeight(170)
        inv.add(self.t_events)
        v.addWidget(inv, 1)
        self.reload()

    def _selected_inventory_record(self) -> dict | None:
        r = self.t_inventory.currentRow()
        if r < 0 or self.t_inventory.item(r, 0) is None:
            return None
        return T.site_inventory_record(self.tdb, self.t_inventory.item(r, 0).text())

    def _save_inventory_dialog(self, mode: str, record: dict | None = None):
        dlg = InstrumentInventoryDialog(record, mode, self)
        if dlg.exec() != QDialog.Accepted:
            return
        data = dlg.data()
        movement = {
            "add": "Manual Added",
            "edit": "Updated",
            "transfer": "Transferred",
            "return": "Returned",
        }.get(mode, "Updated")
        source_ref = {
            "add": "Manual Add",
            "edit": "Manual Edit",
            "transfer": "Manual Transfer",
            "return": "Manual Return",
        }.get(mode, "Manual Edit")
        try:
            T.manual_site_inventory_save(
                self.tdb, data,
                previous_asset_key=str((record or {}).get("asset_key") or ""),
                movement_type=movement,
                source_ref=source_ref,
            )
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not save that instrument record.\n\n{exc}")
            return
        self.reload()
        self.imported.emit()
        W.toast(self, f"Instrument record {movement.lower()}.")

    def _add_inventory(self):
        self._save_inventory_dialog("add")

    def _edit_inventory(self):
        record = self._selected_inventory_record()
        if not record:
            W.error_box(self, "Select an instrument row first.")
            return
        self._save_inventory_dialog("edit", record)

    def _transfer_inventory(self):
        record = self._selected_inventory_record()
        if not record:
            W.error_box(self, "Select an instrument row first.")
            return
        self._save_inventory_dialog("transfer", record)

    def _return_inventory(self):
        record = self._selected_inventory_record()
        if not record:
            W.error_box(self, "Select an instrument row first.")
            return
        self._save_inventory_dialog("return", record)

    def _open_inventory_picture(self):
        record = self._selected_inventory_record()
        if not record or not str(record.get("picture_path") or "").strip():
            W.error_box(self, "The selected row does not have a picture proof path yet.")
            return
        D.open_path(Path(str(record.get("picture_path"))))

    def _reload_asset_events(self):
        r = self.t_inventory.currentRow()
        if r < 0 or self.t_inventory.item(r, 0) is None:
            self.t_events.setRowCount(0)
            return
        asset_key = self.t_inventory.item(r, 0).text()
        rows = T.site_asset_events(self.tdb, asset_key, 40)
        self.t_events.fill(["Date", "Movement", "From Site", "To Site", "From Holder", "To Holder",
                            "From Status", "To Status", "Responsible", "Remarks"],
                           [[e.get("event_date", ""), e.get("movement_type", ""), e.get("site_before", ""), e.get("site_after", ""),
                             e.get("holder_before", ""), e.get("holder_after", ""), e.get("status_before", ""), e.get("status_after", ""),
                             e.get("responsible_person", ""), e.get("remarks", "")]
                            for e in rows])

    def _template(self):
        cols, rows = T.site_sync_template_rows()
        out = Path(D.config.folder(T.FOLDER)) / f"{D.safe_name(T.MODULE_NAME)}_Site_Sync_Template.xlsx"
        self.last_file = D.export_excel(self.db, "Instrument Station — Site Sync Template", cols, rows, out)
        W.toast(self, f"Template saved: {self.last_file.name}")
        D.open_path(self.last_file)

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select the site Excel folder")
        if d:
            self.e_path.setText(d)

    def _selected_folder(self) -> dict | None:
        r = self.t_folders.currentRow()
        if r < 0 or self.t_folders.item(r, 0) is None:
            return None
        folder = self.t_folders.item(r, 1).text()
        return next((f for f in self.folders if f["path"] == folder), None)

    def _load_folder_form(self):
        row = self._selected_folder()
        if not row:
            return
        self.e_path.setText(row.get("path", ""))
        self.e_label.setText(row.get("label", ""))
        self.e_site.setText(row.get("site_name", ""))
        self.chk_auto.setChecked(bool(row.get("auto_sync")))
        self.sp_interval.setValue(int(row.get("sync_interval") or 5))

    def _save_folder(self):
        try:
            T.save_site_sync_folder(
                self.tdb,
                self.e_path.text().strip(),
                self.e_label.text().strip(),
                self.e_site.text().strip(),
                self.chk_auto.isChecked(),
                self.sp_interval.value(),
                folder_id=(self._selected_folder() or {}).get("id"),
            )
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not save the sync folder.\n\n{exc}")
            return
        self.reload()
        W.toast(self, "Site Excel sync folder saved.")

    def _remove_folder(self):
        row = self._selected_folder()
        if not row:
            W.error_box(self, "Select a folder in the list first.")
            return
        if not W.confirm(self, f"Remove this sync folder?\n\n{row['path']}\n\nThe source files stay untouched."):
            return
        T.remove_site_sync_folder(self.tdb, int(row["id"]))
        self.reload()

    def _sync_selected_folder(self):
        row = self._selected_folder()
        if not row:
            W.error_box(self, "Select a folder in the list first.")
            return
        res = T.sync_site_sync_folder(self.tdb, int(row["id"]), force=True)
        self.reload()
        self.imported.emit()
        W.toast(self, f"{res.get('synced', 0)} file(s) synced · {res.get('failed', 0)} failed")

    def _sync_all(self):
        total_synced = total_failed = total_seen = 0
        errs: list[str] = []
        for row in self.folders:
            if not row.get("online"):
                continue
            res = T.sync_site_sync_folder(self.tdb, int(row["id"]), force=True)
            total_synced += int(res.get("synced") or 0)
            total_failed += int(res.get("failed") or 0)
            total_seen += int(res.get("seen") or 0)
            errs += list(res.get("errors") or [])
        self.reload()
        self.imported.emit()
        W.toast(self, f"{total_seen} file(s) seen · {total_synced} synced · {total_failed} failed")
        if errs:
            W.info_box(self, "\n".join(errs[:15]), "Sync report")

    def _open_folder(self):
        row = self._selected_folder()
        if not row:
            W.error_box(self, "Select a folder in the list first.")
            return
        D.open_path(Path(row["path"]))

    def _import_excel(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select the site Excel file", "",
                                           "Spreadsheets (*.xlsx *.xlsm *.csv *.txt)")
        if not f:
            return
        try:
            headers, rows = T.site_sync_read_table(f)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read that file.\n\n{exc}")
            return
        dlg = SiteSyncMappingDialog(self.tdb, self.db, headers, rows, f, self)
        if dlg.exec() == QDialog.Accepted and dlg.synced:
            self.reload()
            self.imported.emit()

    def _bulk_import(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Excel files", "",
                                                "Spreadsheets (*.xlsx *.xlsm *.csv *.txt)")
        if not files:
            return
        res = T.site_sync_import_files(self.tdb, files, force=True)
        self.reload()
        self.imported.emit()
        W.info_box(self, f"{res['synced']} file(s) imported / updated.\n{res['failed']} failed.",
                   "Bulk import")

    def _selected_file_paths(self) -> list[str]:
        paths = []
        for i in self.t_files.selectedIndexes():
            it = self.t_files.item(i.row(), 8)
            if it:
                paths.append(it.text())
        return sorted(set(paths))

    def _reprocess_selected(self):
        paths = self._selected_file_paths()
        if not paths:
            W.error_box(self, "Select one or more files first.")
            return
        res = T.site_sync_import_files(self.tdb, paths, force=True)
        self.reload()
        self.imported.emit()
        W.toast(self, f"{res['synced']} file(s) reprocessed · {res['failed']} failed")
        if res["errors"]:
            W.info_box(self, "\n".join(res["errors"][:12]), "Reprocess report")

    def _open_file(self):
        paths = self._selected_file_paths()
        if not paths:
            W.error_box(self, "Select a file first.")
            return
        D.open_path(Path(paths[0]))

    def _export_inventory(self):
        rows = T.search_site_inventory(self.tdb)
        if not rows:
            W.error_box(self, "There is no synced site inventory to export yet.")
            return
        cols = ["Site Name", "Instrument Description", "Type", "Serial No.", "Quantity", "Status",
                "Issued To / Employee Name", "Employee Code", "Iqama ID", "Designation",
                "Division/Department", "Current Project", "Location", "Issued By", "Remarks",
                "Picture Path", "Last Updated", "Source File"]
        data = [[r.get("site_name", ""), r.get("description", ""), r.get("item_type", ""),
                 r.get("serial_no", ""), float(r.get("qty") or 0), r.get("status", ""),
                 r.get("holder", ""), r.get("employee_code", ""), r.get("iqama_id", ""),
                 r.get("designation", ""), r.get("department", ""), r.get("project_id", ""),
                 r.get("location", ""), r.get("issued_by", ""), r.get("remarks", ""),
                 r.get("picture_path", ""), r.get("last_updated", ""), Path(str(r.get("source_file", ""))).name]
                for r in rows]
        self.last_file = D.export_excel(self.db, "Instrument Station — Site Sync Inventory", cols, data)
        W.toast(self, f"Exported: {self.last_file.name}")
        D.open_path(self.last_file)

    def _reload_history(self):
        ids = []
        for i in self.t_files.selectedIndexes():
            it = self.t_files.item(i.row(), 0)
            if it:
                ids.append(int(float(it.text())))
        fid = ids[0] if ids else 0
        rows = T.site_sync_runs(self.tdb, fid, 30)
        self.t_history.fill(["Time", "File", "Site", "Status", "Rows", "Created", "Updated", "Failed", "Details"],
                            [[r.get("ts", ""), Path(str(r.get("source_file", ""))).name,
                              r.get("site_name", ""), r.get("status", ""), int(r.get("total_rows") or 0),
                              int(r.get("created_rows") or 0), int(r.get("updated_rows") or 0),
                              int(r.get("failed_rows") or 0), r.get("details", "")]
                             for r in rows])

    def reload(self):
        self.folders = T.site_sync_folders(self.tdb)
        self.t_folders.fill(["ID", "Folder", "Label", "Assigned Site", "Auto", "Interval", "State", "Files", "Last Sync", "Last Success", "Last Error"],
                            [[int(r["id"]), r["path"], r.get("label", ""), r.get("site_name", ""),
                              "Yes" if r.get("auto_sync") else "No", f"{int(r.get('sync_interval') or 5)} min",
                              "Online" if r.get("online") else "OFFLINE", int(r.get("files") or 0),
                              r.get("last_scan", ""), r.get("last_success", ""), r.get("last_error", "")]
                             for r in self.folders])
        if self.t_folders.columnCount() > 0:
            self.t_folders.setColumnHidden(0, True)
        self.lbl_folder_status.setText(f"{sum(1 for r in self.folders if r['online'])} of {len(self.folders)} folder(s) online")

        self.files = T.site_sync_scan_files(self.tdb, status=self.f_status.currentText(), text=self.search.text().strip())
        self.t_files.fill(["ID", "Folder", "File", "Detected Site", "Status", "Modified", "Last Sync", "Created", "Updated", "Full Path", "Note"],
                          [[int(r["id"]), r.get("folder_label", ""), r.get("name", ""),
                            r.get("detected_site") or r.get("assigned_site") or "", r.get("status", ""),
                            r.get("modified", ""), r.get("last_sync", ""), int(r.get("rows_created") or 0),
                            int(r.get("rows_updated") or 0), r.get("path", ""), r.get("note", "")]
                           for r in self.files])
        self.t_files.setColumnHidden(0, True)
        self.t_files.setColumnHidden(9, True)
        self.lbl_counts.setText(f"{len(self.files)} file(s)")
        self._reload_history()

        inv = T.search_site_inventory(self.tdb)[:250]
        self.t_inventory.fill(["Asset Key", "Site Name", "Instrument Description", "Type", "Serial No.", "Quantity", "Status",
                               "Issued To / Employee Name", "Employee Code", "Iqama ID", "Designation",
                               "Division/Department", "Current Project", "Location", "Issued By", "Remarks",
                               "Picture Path", "Last Updated"],
                              [[r.get("asset_key", ""), r.get("site_name", ""), r.get("description", ""), r.get("item_type", ""),
                                r.get("serial_no", ""), float(r.get("qty") or 0), r.get("status", ""),
                                r.get("holder", ""), r.get("employee_code", ""), r.get("iqama_id", ""), r.get("designation", ""),
                                r.get("department", ""), r.get("project_id", ""), r.get("location", ""), r.get("issued_by", ""),
                                r.get("remarks", ""), r.get("picture_path", ""), r.get("last_updated", "")]
                               for r in inv])
        if self.t_inventory.columnCount() > 0:
            self.t_inventory.setColumnHidden(0, True)
        self._reload_asset_events()
        dash = T.site_inventory_dashboard(self.tdb)
        self.lbl_sync.setText(f"Last synced: {(dash.get('last_sync') or 'never')[:16]}  ·  {dash.get('row_count', 0)} row(s)")


class InstrumentInventoryDialog(QDialog):
    """Manual add / edit / transfer / return dialog for site inventory rows."""

    def __init__(self, record: dict | None = None, mode: str = "add", parent=None):
        super().__init__(parent)
        self.record = dict(record or {})
        self.mode = mode
        titles = {
            "add": "Instrument Station — Add Manual Instrument",
            "edit": "Instrument Station — Edit Instrument",
            "transfer": "Instrument Station — Transfer Instrument",
            "return": "Instrument Station — Return Instrument",
        }
        self.setWindowTitle(titles.get(mode, "Instrument Station — Instrument Record"))
        self.resize(760, 560)
        v = QVBoxLayout(self)
        intro = {
            "add": "Create a manual instrument record with picture proof. It will appear in the live dashboard and movement history.",
            "edit": "Update the selected instrument details and keep a proper audit trail.",
            "transfer": "Change the site, custodian or location for this instrument and record it as a transfer.",
            "return": "Return this instrument to store / warehouse custody and save the return proof.",
        }
        note = QLabel(intro.get(mode, ""))
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(note)

        form = QFormLayout()
        self.e_item_code = QLineEdit(self.record.get("item_code", ""))
        self.e_desc = QLineEdit(self.record.get("description", ""))
        self.e_type = QLineEdit(self.record.get("item_type", "Instrument"))
        self.e_cat = QLineEdit(self.record.get("category", self.record.get("item_type", "Instrument")))
        self.e_make = QLineEdit(self.record.get("make_model", ""))
        self.e_serial = QLineEdit(self.record.get("serial_no", ""))
        self.sp_qty = QDoubleSpinBox(); self.sp_qty.setRange(0, 1000000); self.sp_qty.setDecimals(2)
        self.sp_qty.setValue(float(self.record.get("qty") or 1))
        self.c_status = QComboBox(); self.c_status.setEditable(True)
        self.c_status.addItems(["", "Available", "Issued", "At Site", "Returned", "Pending", "Under Repair"])
        self.c_status.setCurrentText(str(self.record.get("status") or ""))
        self.c_condition = QComboBox(); self.c_condition.setEditable(True)
        self.c_condition.addItems(["A", "B", "C", "D"])
        self.c_condition.setCurrentText(str(self.record.get("condition") or "A"))
        self.e_holder = QLineEdit(self.record.get("holder", ""))
        self.e_emp = QLineEdit(self.record.get("employee_code", ""))
        self.e_iqama = QLineEdit(self.record.get("iqama_id", ""))
        self.e_designation = QLineEdit(self.record.get("designation", ""))
        self.e_dept = QLineEdit(self.record.get("department", ""))
        self.e_project = QLineEdit(self.record.get("project_id", ""))
        self.e_site = QLineEdit(self.record.get("site_name", ""))
        self.e_location = QLineEdit(self.record.get("location", ""))
        self.e_issued = QLineEdit(self.record.get("issued_by", ""))
        self.e_remarks = QPlainTextEdit(self.record.get("remarks", ""))
        self.e_remarks.setMaximumHeight(90)
        self.e_picture = QLineEdit(self.record.get("picture_path", ""))
        self.d_updated = date_edit(str(self.record.get("last_updated") or _dt.date.today().isoformat()))

        pic_row = QHBoxLayout()
        pic_row.addWidget(self.e_picture, 1)
        pic_row.addWidget(W.button("Browse...", slot=self._browse_picture))
        pic_row.addWidget(W.button("Open", slot=self._open_picture))
        pic_w = QWidget(); pic_w.setLayout(pic_row)

        form.addRow("Item Code", self.e_item_code)
        form.addRow("Instrument Description*", self.e_desc)
        form.addRow("Type", self.e_type)
        form.addRow("Category", self.e_cat)
        form.addRow("Make / Model", self.e_make)
        form.addRow("Serial No.", self.e_serial)
        form.addRow("Quantity", self.sp_qty)
        form.addRow("Status", self.c_status)
        form.addRow("Condition", self.c_condition)
        form.addRow("Issued To / Employee Name", self.e_holder)
        form.addRow("Employee Code", self.e_emp)
        form.addRow("Iqama ID", self.e_iqama)
        form.addRow("Designation", self.e_designation)
        form.addRow("Division / Department", self.e_dept)
        form.addRow("Current Project", self.e_project)
        form.addRow("Site Name", self.e_site)
        form.addRow("Location", self.e_location)
        form.addRow("Issued By / Responsible", self.e_issued)
        form.addRow("Picture Proof", pic_w)
        form.addRow("Last Updated", self.d_updated)
        form.addRow("Remarks", self.e_remarks)
        v.addLayout(form)

        if mode == "transfer":
            if not self.c_status.currentText().strip():
                self.c_status.setCurrentText("Issued" if self.e_holder.text().strip() else "At Site")
        elif mode == "return":
            self.e_site.setText("Warehouse")
            self.e_project.clear()
            self.e_location.setText("Warehouse")
            self.e_holder.clear()
            self.e_emp.clear()
            self.e_iqama.clear()
            self.e_designation.clear()
            self.e_dept.clear()
            self.c_status.setCurrentText("Available")

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _browse_picture(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select the picture proof", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*.*)"
        )
        if f:
            self.e_picture.setText(f)

    def _open_picture(self):
        path = self.e_picture.text().strip()
        if path:
            D.open_path(Path(path))

    def data(self) -> dict:
        out = dict(self.record)
        out.update({
            "item_code": self.e_item_code.text().strip(),
            "description": self.e_desc.text().strip(),
            "item_type": self.e_type.text().strip() or "Instrument",
            "category": self.e_cat.text().strip() or self.e_type.text().strip() or "Instrument",
            "make_model": self.e_make.text().strip(),
            "serial_no": self.e_serial.text().strip(),
            "qty": self.sp_qty.value(),
            "status": self.c_status.currentText().strip(),
            "condition": self.c_condition.currentText().strip() or "A",
            "holder": self.e_holder.text().strip(),
            "employee_code": self.e_emp.text().strip(),
            "iqama_id": self.e_iqama.text().strip(),
            "designation": self.e_designation.text().strip(),
            "department": self.e_dept.text().strip(),
            "project_id": self.e_project.text().strip(),
            "site_name": self.e_site.text().strip(),
            "location": self.e_location.text().strip(),
            "issued_by": self.e_issued.text().strip(),
            "picture_path": self.e_picture.text().strip(),
            "last_updated": iso(self.d_updated),
            "remarks": self.e_remarks.toPlainText().strip(),
        })
        return out


class SiteSyncMappingDialog(QDialog):
    """Manual Excel import with column preview / mapping."""

    def __init__(self, tdb: T.ToolDB, db: Database, headers, rows, source: str = "", parent=None):
        super().__init__(parent)
        self.tdb = tdb
        self.db = db
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]
        self.source = source
        self.synced = 0
        self.setWindowTitle("Instrument Station — Map the uploaded Excel columns")
        self.resize(1080, 720)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            f"<b>{len(self.rows)} row(s)</b> found in <i>{source or 'the uploaded file'}</i>. "
            "Recognised headings are matched automatically — review them before importing."))
        self.map_table = QTableWidget(len(self.headers), 3)
        self.map_table.setHorizontalHeaderLabels(["Uploaded column", "Sample value", "Store as"])
        self.map_table.verticalHeader().setVisible(False)
        self.map_table.horizontalHeader().setStretchLastSection(True)
        auto = T.site_sync_auto_map(self.headers)
        choices = ["— ignore —"] + [lbl for _, lbl in T.SITE_SYNC_FIELDS]
        self.by_label = {lbl: f for f, lbl in T.SITE_SYNC_FIELDS}
        self.combos: list[QComboBox] = []
        for i, h in enumerate(self.headers):
            self.map_table.setItem(i, 0, QTableWidgetItem(str(h)))
            sample = next((str(r[i]) for r in self.rows[:8] if i < len(r) and str(r[i]).strip()), "")
            self.map_table.setItem(i, 1, QTableWidgetItem(sample[:60]))
            cb = QComboBox(); cb.addItems(choices)
            if i in auto:
                cb.setCurrentText(T.SITE_SYNC_LABELS[auto[i]])
            cb.currentTextChanged.connect(self._refresh)
            self.map_table.setCellWidget(i, 2, cb)
            self.combos.append(cb)
        self.map_table.setMaximumHeight(240)
        v.addWidget(self.map_table)
        opts = QHBoxLayout()
        self.def_site = QLineEdit()
        self.def_site.setPlaceholderText("Default Site Name if the column is blank")
        self.def_updated = date_edit()
        opts.addWidget(QLabel("Defaults:"))
        opts.addWidget(self.def_site, 1)
        opts.addWidget(QLabel("Date:"))
        opts.addWidget(self.def_updated)
        self.def_site.textChanged.connect(self._refresh)
        self.def_updated.dateChanged.connect(self._refresh)
        v.addLayout(opts)
        self.preview = W.DataTable()
        v.addWidget(self.preview, 1)
        self.info = QLabel(); self.info.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(self.info)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("⬆  Import File")
        bb.accepted.connect(self._import)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._refresh()

    def _mapping(self) -> dict[int, str]:
        out = {}
        for i, cb in enumerate(self.combos):
            lbl = cb.currentText()
            if lbl in self.by_label:
                out[i] = self.by_label[lbl]
        return out

    def _defaults(self) -> dict:
        return {"site_name": self.def_site.text().strip(), "last_updated": iso(self.def_updated)}

    def _refresh(self, *_):
        self.records = T.site_sync_preview(self.headers, self.rows, self._mapping(), self._defaults())
        cols = [lbl for _, lbl in T.SITE_SYNC_FIELDS]
        data = [[r.get(f, "") if f != "qty" else float(r.get("qty") or 0) for f, _ in T.SITE_SYNC_FIELDS]
                for r in self.records[:300]]
        self.preview.fill(cols, data)
        self.info.setText(f"{len(self.records)} record(s) ready  ·  {len(self._mapping())} column(s) mapped")

    def _import(self):
        if not self.records:
            W.error_box(self, "Nothing to import — map at least one useful column.")
            return
        try:
            tmp = T.import_site_sync_preview_records(
                self.tdb,
                self.records,
                self.source,
                assigned_site=self.def_site.text().strip(),
            )
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"The file could not be imported.\n\n{exc}")
            return
        self.synced = 1 if tmp.get("status") == "Synced" else 0
        W.info_box(self, f"Created: {tmp.get('created', 0)}\nUpdated: {tmp.get('updated', 0)}\nFailed: {tmp.get('failed', 0)}", "Import result")
        self.accept()
