"""CABLE RECORDS — drum register, cutting log, cable schedule and dashboard.

Five tabs:
    📊 Dashboard    configurable KPI tiles + charts, everything drills through
    🥁 Drum Register every drum, what is left on it and where it is
    ✂ Cutting Log   every length issued from — or returned to — a drum
    🧭 Cable Schedule tag by tag: required, pulled, glanded, terminated, tested
    📈 Reports       16 reports with PDF / Excel / CSV / print / share

Nothing in this file imports the stock engine: the module keeps its own
database, exactly like Tools, Instruments & Devices.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMenu, QPlainTextEdit,
                               QScrollArea, QSplitter, QTabWidget, QVBoxLayout,
                               QWidget)

from ..core import cables as CB
from ..core import documents as D
from ..core.database import Database
from . import widgets as W
from .common import ShareBar, date_edit, iso


def _paint(table: W.DataTable, col: int, colors: dict) -> None:
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
#: key · caption · glyph · colour · the register filter the tile drills into
TILE_SPECS: list[tuple[str, str, str, str, dict]] = [
    ("drums", "Drums on Register", "🥁", W.NAVY, {}),
    ("in_stock", "Full Drums", "📦", CB.DRUM_COLORS[CB.IN_STOCK],
     {"status": CB.IN_STOCK}),
    ("partly", "Partly Used", "◐", CB.DRUM_COLORS[CB.PARTLY], {"status": CB.PARTLY}),
    ("empty", "Empty Drums", "␀", CB.DRUM_COLORS[CB.EMPTY], {"status": CB.EMPTY}),
    ("reserved", "Reserved", "🔒", CB.DRUM_COLORS[CB.RESERVED],
     {"status": CB.RESERVED}),
    ("scrapped_drums", "Scrapped", "⛔", CB.DRUM_COLORS[CB.SCRAPPED],
     {"status": CB.SCRAPPED}),
    ("original_length", "Total Length Received", "Σ", W.NAVY, {}),
    ("remaining_length", "Length in Stock", "📏", "#0b6e83", {"in_stock_only": True}),
    ("used_length", "Length Consumed", "✂", "#e8590c", {}),
    ("utilisation", "Utilisation %", "📈", "#7048e8", {}),
    ("stock_value", "Stock Value", "💰", "#1a9c52", {"in_stock_only": True}),
    ("offcuts", "Off-cuts / Short Ends", "🧵", "#9a6700", {"offcuts_only": True}),
    ("offcut_length", "Off-cut Length", "📐", "#9a6700", {"offcuts_only": True}),
    ("idle_drums", "Idle Drums", "🕸", "#c92a2a", {"idle_only": True}),
    ("cuts", "Cut Records", "🧾", W.NAVY, {}),
    ("issued_length", "Issued (period)", "📤", CB.CUT_COLORS[CB.CUT_ISSUE], {}),
    ("returned_length", "Returned (period)", "↩", CB.CUT_COLORS[CB.CUT_RETURN], {}),
    ("scrap_length", "Scrapped Length", "🗑", CB.CUT_COLORS[CB.CUT_SCRAP], {}),
    ("tags", "Cable Tags", "🏷", W.NAVY, {}),
    ("tags_pulled", "Tags Pulled", "🧭", CB.TAG_COLORS[CB.PULLED], {}),
    ("tags_pending", "Tags Not Pulled", "⏳", CB.TAG_COLORS[CB.PLANNED], {}),
    ("tags_terminated", "Terminated", "🔌", CB.TAG_COLORS[CB.TERMINATED], {}),
    ("tests_pass", "Tests Passed", "✔", CB.TEST_COLORS[CB.TEST_PASS], {}),
    ("tests_fail", "Tests Failed", "✖", CB.TEST_COLORS[CB.TEST_FAIL], {}),
    ("tests_pending", "Tests Pending", "🎯", "#9a6700", {}),
    ("required_length", "Length Required (design)", "📋", W.NAVY, {}),
    ("pulled_length", "Length Pulled", "🧲", "#1098ad", {}),
    ("shortfall", "Still To Pull", "⚠", "#c92a2a", {}),
    ("projects", "Projects", "🏗", "#7048e8", {}),
]

#: charts and tables that can be switched on or off
PANEL_SPECS: list[tuple[str, str]] = [
    ("type", "By cable type"),
    ("status", "Drum status"),
    ("size", "By size / CSA"),
    ("month", "Cable consumed per month"),
    ("project", "By project"),
    ("location", "By store location"),
    ("maker", "By manufacturer"),
    ("io", "Issued vs returned by month"),
    ("ageing", "Idle drums — how long since the last cut"),
    ("tagstatus", "Cable schedule progress"),
    ("stock_table", "Cable stock summary"),
    ("offcut_table", "🧵 Off-cuts worth using first"),
    ("tag_table", "Cable tags still to pull"),
    ("test_table", "⚠ Failed and pending tests"),
    ("recent", "Latest cuts"),
]

DEFAULT_TILES = ["drums", "in_stock", "partly", "empty", "remaining_length",
                 "used_length", "utilisation", "stock_value", "offcuts",
                 "idle_drums", "issued_length", "returned_length", "tags",
                 "tags_pulled", "tags_pending", "tests_fail"]
DEFAULT_PANELS = [k for k, _ in PANEL_SPECS]

MEASURE_LABELS = {f"Measure: {v}": k for k, v in CB.MEASURES.items()}


class DashboardSetupDialog(QDialog):
    """Choose which tiles, charts and tables the cable dashboard shows."""

    def __init__(self, tiles: list[str], panels: list[str], columns: int,
                 offcut_limit: float, idle_days: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customise the cable dashboard")
        self.setMinimumWidth(720)
        v = QVBoxLayout(self)
        note = QLabel("Tick what this dashboard should show, and set what your site "
                      "calls an off-cut. The choice is stored with the module, so "
                      "every screen keeps your layout.")
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
        row.addSpacing(18)
        row.addWidget(QLabel("An off-cut is anything up to:"))
        self.sp_offcut = QDoubleSpinBox()
        self.sp_offcut.setRange(0, 100000)
        self.sp_offcut.setDecimals(1)
        self.sp_offcut.setSuffix(" m")
        self.sp_offcut.setValue(float(offcut_limit))
        row.addWidget(self.sp_offcut)
        row.addSpacing(18)
        row.addWidget(QLabel("A drum is idle after:"))
        self.sp_idle = QDoubleSpinBox()
        self.sp_idle.setRange(1, 3650)
        self.sp_idle.setDecimals(0)
        self.sp_idle.setSuffix(" days")
        self.sp_idle.setValue(float(idle_days))
        row.addWidget(self.sp_idle)
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
        self.sp_offcut.setValue(CB.DEFAULT_OFFCUT_LIMIT)
        self.sp_idle.setValue(CB.DEFAULT_IDLE_DAYS)

    def result_config(self) -> tuple[list[str], list[str], int, float, int]:
        tiles = [k for k, _l, _g, _c, _f in TILE_SPECS if self.tile_boxes[k].isChecked()]
        panels = [k for k, _l in PANEL_SPECS if self.panel_boxes[k].isChecked()]
        return (tiles, panels, int(self.cols.currentText()),
                float(self.sp_offcut.value()), int(self.sp_idle.value()))


class CableDashboard(QWidget):
    """Filterable, drill-through, user-configurable cable dashboard."""
    openRegister = Signal(dict)
    openSchedule = Signal(dict)

    def __init__(self, cdb: CB.CableDB, db: Database, parent=None):
        super().__init__(parent)
        self.cdb = cdb
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

        (self.tile_cfg, self.panel_cfg, self.cols_cfg,
         self.offcut_limit, self.idle_days) = self._load_config()
        self._build_body()
        self.reload_filters()

    # --------------------------------------------------------------- config
    def _load_config(self):
        def read(key: str, default: list[str]) -> list[str]:
            raw = self.cdb.get_setting(key, "")
            picked = [k for k in str(raw).split("|") if k]
            return picked or list(default)

        valid_t = {k for k, *_ in TILE_SPECS}
        valid_p = {k for k, _ in PANEL_SPECS}
        tiles = [k for k in read("dash_tiles", DEFAULT_TILES) if k in valid_t]
        panels = [k for k in read("dash_panels", DEFAULT_PANELS) if k in valid_p]
        try:
            cols = int(self.cdb.get_setting("dash_columns", 4) or 4)
        except (TypeError, ValueError):
            cols = 4
        limit = CB.to_float(self.cdb.get_setting("offcut_limit",
                                                 CB.DEFAULT_OFFCUT_LIMIT),
                            CB.DEFAULT_OFFCUT_LIMIT)
        idle = int(CB.to_float(self.cdb.get_setting("idle_days",
                                                    CB.DEFAULT_IDLE_DAYS),
                               CB.DEFAULT_IDLE_DAYS))
        return (tiles or list(DEFAULT_TILES), panels or list(DEFAULT_PANELS),
                min(6, max(3, cols)), limit, idle)

    def _save_config(self) -> None:
        self.cdb.set_setting("dash_tiles", "|".join(self.tile_cfg))
        self.cdb.set_setting("dash_panels", "|".join(self.panel_cfg))
        self.cdb.set_setting("dash_columns", self.cols_cfg)
        self.cdb.set_setting("offcut_limit", self.offcut_limit)
        self.cdb.set_setting("idle_days", self.idle_days)

    def customise(self):
        dlg = DashboardSetupDialog(self.tile_cfg, self.panel_cfg, self.cols_cfg,
                                   self.offcut_limit, self.idle_days, self)
        if dlg.exec() != QDialog.Accepted:
            return
        (self.tile_cfg, self.panel_cfg, self.cols_cfg,
         self.offcut_limit, self.idle_days) = dlg.result_config()
        self._save_config()
        self._build_body()
        self.reload()
        W.toast(self, "Cable dashboard layout saved.")

    # ----------------------------------------------------------- filter bar
    def _build_filter_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Card")
        fl = QGridLayout(bar)
        fl.setContentsMargins(10, 7, 10, 7)
        fl.setHorizontalSpacing(7)
        fl.setVerticalSpacing(6)

        self.f_text = W.SearchBox("Filter the whole dashboard — drum, cable, tag, "
                                  "project, PO, batch, location ...")
        self.f_text.textChanged.connect(self.reload)
        fl.addWidget(self.f_text, 0, 0, 1, 3)
        self.f_status = W.combo(["All Drum Status"] + list(CB.DRUM_STATUS))
        self.f_type = W.combo(["All Cable Types"])
        self.f_size = W.combo(["All Sizes"])
        self.f_project = W.combo(["All Projects"])
        self.f_location = W.combo(["All Locations"])
        self.f_maker = W.combo(["All Manufacturers"])
        for i, cb in enumerate((self.f_status, self.f_type, self.f_size,
                                self.f_project, self.f_location, self.f_maker)):
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
        self.chk_stock = QCheckBox("Only drums with cable left")
        self.chk_stock.toggled.connect(self.reload)
        fl.addWidget(self.chk_stock, 1, 3)
        self.chk_offcut = QCheckBox("Only off-cuts")
        self.chk_offcut.toggled.connect(self.reload)
        fl.addWidget(self.chk_offcut, 1, 4)
        self.f_measure = W.combo([f"Measure: {v}" for v in CB.MEASURES.values()])
        self.f_measure.setToolTip("What the charts should count")
        self.f_measure.currentTextChanged.connect(self.reload)
        fl.addWidget(self.f_measure, 1, 5)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(W.button("↺  Reset", slot=self.reset_filters))
        row.addWidget(W.button("⚙  Customise", slot=self.customise,
                               tip="Choose the tiles, charts, off-cut limit and "
                                   "idle period"))
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
        for cb, table, col, first in (
                (self.f_type, "drums", "cable_type", "All Cable Types"),
                (self.f_size, "drums", "size_mm2", "All Sizes"),
                (self.f_project, "drums", "project", "All Projects"),
                (self.f_location, "drums", "location", "All Locations"),
                (self.f_maker, "drums", "manufacturer", "All Manufacturers")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + CB.distinct(self.cdb, table, col))
            cb.setCurrentIndex(max(0, cb.findText(cur)))
            cb.blockSignals(False)

    def reset_filters(self):
        self._loading = True
        self.f_text.clear()
        for cb in (self.f_status, self.f_type, self.f_size, self.f_project,
                   self.f_location, self.f_maker, self.f_period, self.f_measure):
            cb.setCurrentIndex(0)
        for c in (self.chk_stock, self.chk_offcut):
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
        if self.f_status.currentIndex() > 0:
            f["status"] = self.f_status.currentText()
        if self.f_type.currentIndex() > 0:
            f["cable_type"] = self.f_type.currentText()
        if self.f_size.currentIndex() > 0:
            f["size"] = self.f_size.currentText()
        if self.f_project.currentIndex() > 0:
            f["project"] = self.f_project.currentText()
        if self.f_location.currentIndex() > 0:
            f["location"] = self.f_location.currentText()
        if self.f_maker.currentIndex() > 0:
            f["manufacturer"] = self.f_maker.currentText()
        if d_from:
            f["date_from"] = d_from
        if d_to:
            f["date_to"] = d_to
        if self.chk_stock.isChecked():
            f["in_stock_only"] = True
        if self.chk_offcut.isChecked():
            f["offcuts_only"] = True
        f["offcut_limit"] = self.offcut_limit
        f["idle_days"] = self.idle_days
        return {k: v for k, v in f.items() if v not in ("", None, False)}

    def measure(self) -> str:
        return MEASURE_LABELS.get(self.f_measure.currentText(), "count")

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
        if key not in self.panel_cfg:
            return None
        card = W.Card(dict(PANEL_SPECS)[key])
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
            grid.setColumnStretch(c, 1)
        specs = {k: (l, g, c, f) for k, l, g, c, f in TILE_SPECS}
        for i, key in enumerate(self.tile_cfg):
            label, glyph, color, _flt = specs[key]
            card = W.StatCard(label, "0", glyph, color)
            card.setToolTip("Click to open these records in the register")
            card.clicked.connect(lambda k=key: self._drill(k))
            self.tiles[key] = card
            grid.addWidget(card, i // self.cols_cfg, i % self.cols_cfg)
        self.body_v.addLayout(grid)

        self.c_type = W.BarChart(color="#0b6e83")
        self.c_type.barClicked.connect(lambda k: self._set_combo(self.f_type, k))
        self.c_status = W.DonutChart()
        self.c_size = W.BarChart(horizontal=True, color="#14538f")
        self.c_size.barClicked.connect(lambda k: self._set_combo(self.f_size, k))
        self.c_month = W.LineChart()
        self.c_project = W.BarChart(horizontal=True, color="#7048e8")
        self.c_project.barClicked.connect(lambda k: self._set_combo(self.f_project, k))
        self.c_location = W.BarChart(horizontal=True, color="#1a9c52")
        self.c_location.barClicked.connect(lambda k: self._set_combo(self.f_location, k))
        self.c_maker = W.BarChart(horizontal=True, color="#9a6700")
        self.c_maker.barClicked.connect(lambda k: self._set_combo(self.f_maker, k))
        self.c_io = W.GroupedBarChart(labels=("Issued", "Returned"))
        self.c_age = W.BarChart(color="#e8590c")
        self.c_tag = W.DonutChart()
        self.t_stock = W.DataTable()
        self.t_stock.setMinimumHeight(190)
        self.t_offcut = W.DataTable()
        self.t_offcut.setMinimumHeight(180)
        self.t_tags = W.DataTable()
        self.t_tags.setMinimumHeight(190)
        self.t_tests = W.DataTable()
        self.t_tests.setMinimumHeight(180)
        self.t_recent = W.DataTable()
        self.t_recent.setMinimumHeight(200)

        rows = [
            [("type", self.c_type, 2), ("status", self.c_status, 2),
             ("month", self.c_month, 3)],
            [("size", self.c_size, 2), ("project", self.c_project, 2),
             ("location", self.c_location, 2)],
            [("maker", self.c_maker, 2), ("ageing", self.c_age, 2),
             ("io", self.c_io, 3)],
            [("tagstatus", self.c_tag, 2), ("stock_table", self.t_stock, 4)],
            [("offcut_table", self.t_offcut, 1)],
            [("tag_table", self.t_tags, 1)],
            [("test_table", self.t_tests, 1)],
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
        f.update({k: (l, g, c, x) for k, l, g, c, x in TILE_SPECS}[key][3])
        if key.startswith("tag") or key.startswith("test"):
            self.openSchedule.emit(f)
        else:
            self.openRegister.emit(f)

    # --------------------------------------------------------------- export
    def export_view(self, kind: str = "pdf"):
        f = self.filters()
        title, cols, rows = CB.build_report(self.cdb, CB.REPORT_LIST[0], f)
        if not rows:
            W.error_box(self, "Nothing matches the current filters.")
            return
        d = CB.dashboard(self.cdb, f)
        bits = [f"{k.replace('_', ' ').title()}: {v}" for k, v in f.items()
                if k not in ("offcut_limit", "idle_days")]
        subtitle = "  ·  ".join(bits) or "All cable drums"
        try:
            if kind == "xlsx":
                self.last_file = D.export_excel(
                    self.db, "Cable Records - Dashboard View", cols, rows)
            else:
                stats = [("Drums", f"{d['drums']:,}", "#12283f"),
                         ("Length in Stock", f"{d['remaining_length']:,.0f}", "#0f7b3d"),
                         ("Consumed", f"{d['used_length']:,.0f}", "#9a6700"),
                         ("Utilisation", f"{d['utilisation']:,.1f}%", "#12283f"),
                         ("Off-cuts", f"{d['offcuts']:,}", "#9a6700"),
                         ("Tags Pending", f"{d['tags_pending']:,}", "#b3261e")]
                self.last_file = D.cable_report_pdf(
                    self.db, "Cable Records — Dashboard View", cols, rows,
                    subtitle=subtitle, stats=stats)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Could not export the view.\n\n{exc}")
            return
        W.toast(self, f"Exported: {Path(self.last_file).name}")
        try:
            D.open_path(self.last_file)
        except Exception:                 # noqa: BLE001
            pass

    # --------------------------------------------------------------- render
    def reload(self):
        if self._loading:
            return
        f = self.filters()
        m = self.measure()
        d = CB.dashboard(self.cdb, f)
        for key, card in self.tiles.items():
            val = d.get(key, 0)
            if key == "utilisation":
                card.set_value(f"{val:,.1f} %")
            else:
                card.set_value(f"{val:,.2f}" if isinstance(val, float) and val % 1
                               else f"{val:,.0f}")
        if "remaining_length" in self.tiles:
            self.tiles["remaining_length"].lbl_sub.setText(
                f"of {d['original_length']:,.0f} m received")
        if "utilisation" in self.tiles:
            self.tiles["utilisation"].lbl_sub.setText(
                f"{d['used_length']:,.0f} m consumed")
        if "offcuts" in self.tiles:
            self.tiles["offcuts"].lbl_sub.setText(
                f"≤ {self.offcut_limit:g} m · {d['offcut_length']:,.0f} m total")
        if "idle_drums" in self.tiles:
            self.tiles["idle_drums"].lbl_sub.setText(
                f"no cut for {self.idle_days}+ days")
        if "shortfall" in self.tiles:
            self.tiles["shortfall"].lbl_sub.setText(
                f"{d['tags_pending']} tag(s) not pulled")
        if "drums" in self.tiles:
            self.tiles["drums"].lbl_sub.setText("filtered view" if
                                                len(f) > 2 else "whole register")

        if "type" in self.panel_cfg:
            self.c_type.set_data(CB.by_column(self.cdb, "cable_type", 10, m, f))
        if "status" in self.panel_cfg:
            self.c_status.set_data([
                (name, val, CB.DRUM_COLORS.get(name, W.NAVY))
                for name, val in CB.by_column(self.cdb, "status", 10, m, f)])
        if "size" in self.panel_cfg:
            self.c_size.set_data(CB.by_column(self.cdb, "size_mm2", 10, m, f))
        if "month" in self.panel_cfg:
            self.c_month.set_data(CB.monthly(self.cdb, 12, f))
        if "project" in self.panel_cfg:
            self.c_project.set_data(CB.by_column(self.cdb, "project", 10, m, f))
        if "location" in self.panel_cfg:
            self.c_location.set_data(CB.by_column(self.cdb, "location", 10, m, f))
        if "maker" in self.panel_cfg:
            self.c_maker.set_data(CB.by_column(self.cdb, "manufacturer", 10, m, f))
        if "io" in self.panel_cfg:
            self.c_io.set_data(CB.monthly_split(self.cdb, 8, f))
        if "ageing" in self.panel_cfg:
            self.c_age.set_data(CB.ageing(self.cdb, f, m))
        if "tagstatus" in self.panel_cfg:
            self.c_tag.set_data([
                (name, val, CB.TAG_COLORS.get(name, W.NAVY))
                for name, val in CB.by_column(self.cdb, "status_tag", 10, "count", f)])

        if "stock_table" in self.panel_cfg:
            self.t_stock.fill(
                ["Cable", "Drums", "Original", "Remaining", "Used", "Off-cuts",
                 "Value"],
                [[r["cable"], r["drums"], r["original"], r["remaining"], r["used"],
                  r["offcuts"], r["value"]] for r in CB.stock_by_cable(self.cdb, f)])
        if "offcut_table" in self.panel_cfg:
            oc = CB.search_drums(self.cdb, **{**f, "offcuts_only": True})
            self.t_offcut.fill(
                ["Drum No.", "Cable", "Remaining", "Location", "Project",
                 "Last Movement", "Idle Days"],
                [[r["drum_no"], r["description"], r["remaining_length"],
                  r["location"], r["project"], CB.fmt_date(r["last_movement"]),
                  r["idle_days"]] for r in
                 sorted(oc, key=lambda r: r["remaining_length"])[:40]])
        if "tag_table" in self.panel_cfg:
            tags = [t for t in CB.search_tags(self.cdb, **{
                k: v for k, v in f.items()
                if k in ("text", "project", "date_from", "date_to")})
                if t["balance"] > 1e-9 and t["status"] != CB.TAG_CANCELLED]
            self.t_tags.fill(
                ["Cable Tag", "Project", "From", "To", "Required", "Pulled",
                 "Balance", "Progress %", "Status"],
                [[t["tag_no"], t["project"], t["from_point"], t["to_point"],
                  t["required_length"], t["pulled_length"], t["balance"],
                  t["progress"], t["status"]] for t in tags[:40]])
            _paint(self.t_tags, 8, CB.TAG_COLORS)
        if "test_table" in self.panel_cfg:
            bad = [t for t in CB.search_tags(self.cdb, **{
                k: v for k, v in f.items()
                if k in ("text", "project", "date_from", "date_to")})
                if t["test_result"] in (CB.TEST_FAIL, CB.TEST_PENDING)
                and t["step"] >= CB.TAG_ORDER[CB.PULLED]]
            self.t_tests.fill(
                ["Cable Tag", "Project", "Status", "Pulled", "Test Date",
                 "IR (MΩ)", "Result", "Tested By"],
                [[t["tag_no"], t["project"], t["status"], t["pulled_length"],
                  CB.fmt_date(t["test_date"]), t["ir_value"], t["test_result"],
                  t["tested_by"]] for t in bad[:40]])
            _paint(self.t_tests, 6, CB.TEST_COLORS)
        if "recent" in self.panel_cfg:
            cuts = CB.search_cuts(self.cdb, **{
                k: v for k, v in f.items()
                if k in ("text", "project", "date_from", "date_to")})
            self.t_recent.fill(
                ["Cut No.", "Date", "Type", "Drum", "Length", "Cable Tag",
                 "Project", "Issued To", "DN No.", "Remarks"],
                [[c["cut_no"], CB.fmt_date(c["cut_date"]), c["txn_type"],
                  c["drum_no"], c["length"], c["tag_no"], c["project"],
                  c["issued_to"], c["dn_no"], c["remarks"]] for c in cuts[:40]])
            _paint(self.t_recent, 2, CB.CUT_COLORS)


# ================================================================== dialogs
class DrumDialog(QDialog):
    """Add or edit one cable drum."""

    def __init__(self, cdb: CB.CableDB, drum_id: int | None = None, parent=None):
        super().__init__(parent)
        self.cdb = cdb
        self.drum_id = drum_id
        self.saved_id: int | None = None
        row = CB.get_drum(cdb, drum_id) if drum_id else {}
        self.setWindowTitle("Edit drum" if drum_id else "New cable drum")
        self.resize(880, 0)
        v = QVBoxLayout(self)
        v.setSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)

        def add(col: int, r: int, label: str, widget):
            grid.addWidget(QLabel(label), r, col * 2)
            grid.addWidget(widget, r, col * 2 + 1)
            return widget

        self.drum_no = QLineEdit(str(row.get("drum_no") or ""))
        self.drum_no.setPlaceholderText("Left blank = numbered automatically")
        self.cable_code = QLineEdit(str(row.get("cable_code") or ""))
        self.cable_type = W.combo(list(CB.CABLE_TYPES), True,
                                  str(row.get("cable_type") or ""))
        self.cores = QLineEdit(str(row.get("cores") or ""))
        self.size = QLineEdit(str(row.get("size_mm2") or ""))
        self.voltage = W.combo(list(CB.VOLTAGE_GRADES), True,
                               str(row.get("voltage_grade") or ""))
        self.insulation = W.combo(list(CB.INSULATIONS), True,
                                  str(row.get("insulation") or ""))
        self.conductor = W.combo(list(CB.CONDUCTORS), True,
                                 str(row.get("conductor") or ""))
        self.armour = W.combo(list(CB.ARMOURS), True, str(row.get("armour") or ""))
        add(0, 0, "Drum / reel no.", self.drum_no)
        add(1, 0, "Cable code", self.cable_code)
        add(2, 0, "Cable type", self.cable_type)
        add(0, 1, "Cores", self.cores)
        add(1, 1, "Size / CSA", self.size)
        add(2, 1, "Voltage grade", self.voltage)
        add(0, 2, "Insulation", self.insulation)
        add(1, 2, "Conductor", self.conductor)
        add(2, 2, "Armour / screen", self.armour)

        self.manufacturer = QLineEdit(str(row.get("manufacturer") or ""))
        self.batch = QLineEdit(str(row.get("batch_no") or ""))
        self.supplier = QLineEdit(str(row.get("supplier") or ""))
        self.po = QLineEdit(str(row.get("po_no") or ""))
        self.grn = QLineEdit(str(row.get("grn_no") or ""))
        self.cert = QLineEdit(str(row.get("test_cert") or ""))
        add(0, 3, "Manufacturer", self.manufacturer)
        add(1, 3, "Batch / heat no.", self.batch)
        add(2, 3, "Supplier", self.supplier)
        add(0, 4, "PO no.", self.po)
        add(1, 4, "GRN no.", self.grn)
        add(2, 4, "Test certificate", self.cert)

        self.project = QLineEdit(str(row.get("project") or ""))
        self.warehouse = QLineEdit(str(row.get("warehouse") or ""))
        self.location = QLineEdit(str(row.get("location") or ""))
        self.received = date_edit(str(row.get("received_date") or CB.today()))
        add(0, 5, "Project", self.project)
        add(1, 5, "Warehouse", self.warehouse)
        add(2, 5, "Location / yard", self.location)
        add(0, 6, "Received on", self.received)

        self.original = QDoubleSpinBox()
        self.original.setRange(0, 10 ** 7)
        self.original.setDecimals(2)
        self.original.setValue(CB.to_float(row.get("original_length")))
        self.remaining = QDoubleSpinBox()
        self.remaining.setRange(0, 10 ** 7)
        self.remaining.setDecimals(2)
        self.remaining.setValue(CB.to_float(row.get("remaining_length")))
        self.remaining.setEnabled(drum_id is not None)
        self.remaining.setToolTip(
            "On an existing drum the remaining length is proved by the cutting "
            "log — use ✂ Issue / ↩ Return instead of typing here.")
        self.uom = W.combo(["M", "FT", "KM", "ROLL"], True, str(row.get("uom") or "M"))
        self.cost = QDoubleSpinBox()
        self.cost.setRange(0, 10 ** 7)
        self.cost.setDecimals(3)
        self.cost.setValue(CB.to_float(row.get("unit_cost")))
        add(1, 6, "Original length", self.original)
        add(2, 6, "Remaining length", self.remaining)
        add(0, 7, "Unit of measure", self.uom)
        add(1, 7, "Unit cost", self.cost)
        self.status = W.combo(list(CB.DRUM_STATUS), False,
                              str(row.get("status") or CB.IN_STOCK))
        add(2, 7, "Status", self.status)
        v.addLayout(grid)

        self.remarks = QLineEdit(str(row.get("remarks") or ""))
        self.remarks.setPlaceholderText("Anything the next storekeeper should know")
        f2 = QFormLayout()
        f2.addRow("Remarks", self.remarks)
        v.addLayout(f2)

        if drum_id:
            hist = CB.drum_history(cdb, drum_id)
            card = W.Card(f"Cutting history — {len(hist)} record(s)")
            t = W.DataTable()
            t.setMinimumHeight(160)
            t.fill(["Cut No.", "Date", "Type", "Length", "Cable Tag", "Issued To",
                    "DN No.", "Voided", "Remarks"],
                   [[c["cut_no"], CB.fmt_date(c["cut_date"]), c["txn_type"],
                     c["length"], c["tag_no"], c["issued_to"], c["dn_no"],
                     "YES" if c["voided"] else "", c["remarks"]] for c in hist])
            card.add(t)
            v.addWidget(card)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save drum")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def data(self) -> dict:
        return {
            "drum_no": self.drum_no.text(), "cable_code": self.cable_code.text(),
            "cable_type": self.cable_type.currentText(), "cores": self.cores.text(),
            "size_mm2": self.size.text(),
            "voltage_grade": self.voltage.currentText(),
            "insulation": self.insulation.currentText(),
            "conductor": self.conductor.currentText(),
            "armour": self.armour.currentText(),
            "manufacturer": self.manufacturer.text(), "batch_no": self.batch.text(),
            "supplier": self.supplier.text(), "po_no": self.po.text(),
            "grn_no": self.grn.text(), "test_cert": self.cert.text(),
            "project": self.project.text(), "warehouse": self.warehouse.text(),
            "location": self.location.text(), "received_date": iso(self.received),
            "original_length": self.original.value(),
            "remaining_length": (self.remaining.value() if self.drum_id
                                 else self.original.value()),
            "uom": self.uom.currentText(), "unit_cost": self.cost.value(),
            "status": self.status.currentText(), "remarks": self.remarks.text(),
        }

    def _save(self):
        try:
            self.saved_id = CB.save_drum(self.cdb, self.data(), self.drum_id)
        except CB.CableError as exc:
            W.error_box(self, str(exc))
            return
        self.accept()


class CutDialog(QDialog):
    """Take a length off a drum — or put an off-cut back on it."""

    def __init__(self, cdb: CB.CableDB, drum: dict, txn_type: str = CB.CUT_ISSUE,
                 parent=None):
        super().__init__(parent)
        self.cdb = cdb
        self.drum = drum
        self.cut_no = ""
        self.setWindowTitle(f"{txn_type} cable — drum {drum['drum_no']}")
        self.resize(560, 0)
        v = QVBoxLayout(self)
        v.setSpacing(9)
        head = QLabel(f"<b>{drum['drum_no']}</b> &nbsp; {drum['description']}")
        head.setWordWrap(True)
        v.addWidget(head)
        self.lbl_left = QLabel()
        self.lbl_left.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(self.lbl_left)

        f = QFormLayout()
        self.txn = W.combo(list(CB.CUT_TYPES), False, txn_type)
        self.txn.currentTextChanged.connect(self._refresh)
        f.addRow("Record type", self.txn)
        self.date = date_edit(CB.today())
        f.addRow("Date", self.date)
        self.length = QDoubleSpinBox()
        self.length.setRange(0, 10 ** 7)
        self.length.setDecimals(2)
        self.length.setSuffix(f"  {drum.get('uom') or 'M'}")
        self.length.valueChanged.connect(self._refresh)
        f.addRow("Length", self.length)
        self.tag = W.combo([""] + CB.distinct(cdb, "schedule", "tag_no"), True)
        self.tag.setToolTip("Link this cut to a cable tag so the schedule updates "
                            "itself")
        self.tag.currentTextChanged.connect(self._tag_changed)
        f.addRow("Cable tag", self.tag)
        self.project = QLineEdit(str(drum.get("project") or ""))
        f.addRow("Project", self.project)
        self.issued_to = QLineEdit()
        self.issued_to.setPlaceholderText("Foreman / crew / company receiving it")
        f.addRow("Issued to", self.issued_to)
        self.dn = QLineEdit()
        self.dn.setPlaceholderText("Delivery note or gate pass, if any")
        f.addRow("DN / reference", self.dn)
        self.frm = QLineEdit()
        self.to = QLineEdit()
        f.addRow("From (equipment)", self.frm)
        f.addRow("To (equipment)", self.to)
        self.remarks = QLineEdit()
        f.addRow("Remarks", self.remarks)
        v.addLayout(f)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        v.addWidget(self.preview)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        self.btn_ok.setText("Record")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._refresh()

    def _tag_changed(self, tag_no: str):
        row = CB.tag_by_no(self.cdb, tag_no) if tag_no.strip() else None
        if not row:
            return
        if not self.length.value():
            self.length.setValue(max(0.0, CB.to_float(row["required_length"]) -
                                     CB.to_float(row["pulled_length"])))
        self.frm.setText(str(row["from_point"] or ""))
        self.to.setText(str(row["to_point"] or ""))
        if row["project"]:
            self.project.setText(str(row["project"]))
        self._refresh()

    def _refresh(self, *_):
        uom = self.drum.get("uom") or "M"
        left = CB.to_float(self.drum["remaining_length"])
        sign = CB.CUT_SIGN.get(self.txn.currentText(), -1.0)
        after = round(left + sign * self.length.value(), 3)
        self.lbl_left.setText(
            f"On the drum now: <b>{left:g} {uom}</b> of "
            f"{CB.to_float(self.drum['original_length']):g} {uom}")
        bad = after < -1e-9 or after > CB.to_float(self.drum["original_length"]) + 1e-9
        colour = W.RED if bad else W.GREEN
        self.preview.setText(
            f"After this record the drum holds "
            f"<span style='color:{colour}'><b>{after:g} {uom}</b></span>"
            + ("  — that is not possible" if bad else ""))
        self.btn_ok.setEnabled(self.length.value() > 0 and not bad)

    def _save(self):
        try:
            self.cut_no = CB.post_cut(self.cdb, int(self.drum["id"]), {
                "txn_type": self.txn.currentText(), "cut_date": iso(self.date),
                "length": self.length.value(), "tag_no": self.tag.currentText().strip(),
                "project": self.project.text(), "issued_to": self.issued_to.text(),
                "dn_no": self.dn.text(), "from_point": self.frm.text(),
                "to_point": self.to.text(), "remarks": self.remarks.text()})
        except CB.CableError as exc:
            W.error_box(self, str(exc))
            return
        self.accept()


class TagDialog(QDialog):
    """Add or edit a cable schedule line (one cable tag)."""

    def __init__(self, cdb: CB.CableDB, tag_id: int | None = None, parent=None):
        super().__init__(parent)
        self.cdb = cdb
        self.tag_id = tag_id
        row = CB.get_tag(cdb, tag_id) if tag_id else {}
        self.setWindowTitle("Edit cable tag" if tag_id else "New cable tag")
        self.resize(820, 0)
        v = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)

        def add(col: int, r: int, label: str, widget):
            grid.addWidget(QLabel(label), r, col * 2)
            grid.addWidget(widget, r, col * 2 + 1)
            return widget

        self.tag_no = QLineEdit(str(row.get("tag_no") or ""))
        self.project = QLineEdit(str(row.get("project") or ""))
        self.area = QLineEdit(str(row.get("area") or ""))
        self.system = QLineEdit(str(row.get("system") or ""))
        self.frm = QLineEdit(str(row.get("from_point") or ""))
        self.to = QLineEdit(str(row.get("to_point") or ""))
        self.route = QLineEdit(str(row.get("route") or ""))
        self.cable_type = W.combo(list(CB.CABLE_TYPES), True,
                                  str(row.get("cable_type") or ""))
        self.cores = QLineEdit(str(row.get("cores") or ""))
        self.size = QLineEdit(str(row.get("size_mm2") or ""))
        self.voltage = W.combo(list(CB.VOLTAGE_GRADES), True,
                               str(row.get("voltage_grade") or ""))
        self.required = QDoubleSpinBox()
        self.required.setRange(0, 10 ** 7)
        self.required.setDecimals(2)
        self.required.setValue(CB.to_float(row.get("required_length")))
        self.status = W.combo(list(CB.TAG_STATUS), False,
                              str(row.get("status") or CB.PLANNED))
        add(0, 0, "Cable tag *", self.tag_no)
        add(1, 0, "Project", self.project)
        add(2, 0, "Area", self.area)
        add(0, 1, "System", self.system)
        add(1, 1, "From (equipment)", self.frm)
        add(2, 1, "To (equipment)", self.to)
        add(0, 2, "Route", self.route)
        add(1, 2, "Cable type", self.cable_type)
        add(2, 2, "Cores", self.cores)
        add(0, 3, "Size / CSA", self.size)
        add(1, 3, "Voltage grade", self.voltage)
        add(2, 3, "Required length", self.required)
        add(0, 4, "Status", self.status)
        self.glanded = date_edit(str(row.get("glanded_date") or ""))
        self.terminated = date_edit(str(row.get("terminated_date") or ""))
        add(1, 4, "Glanded on", self.glanded)
        add(2, 4, "Terminated on", self.terminated)
        self.remarks = QLineEdit(str(row.get("remarks") or ""))
        grid.addWidget(QLabel("Remarks"), 5, 0)
        grid.addWidget(self.remarks, 5, 1, 1, 5)
        v.addLayout(grid)

        if tag_id:
            info = QLabel(
                f"Pulled so far: <b>{CB.to_float(row.get('pulled_length')):g}</b> m "
                f"from drum(s) {row.get('drum_no') or '—'} · test "
                f"{row.get('test_result') or CB.TEST_PENDING}")
            info.setStyleSheet(f"color:{W.MUTED};")
            v.addWidget(info)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save tag")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _save(self):
        data = {
            "tag_no": self.tag_no.text(), "project": self.project.text(),
            "area": self.area.text(), "system": self.system.text(),
            "from_point": self.frm.text(), "to_point": self.to.text(),
            "route": self.route.text(),
            "cable_type": self.cable_type.currentText(), "cores": self.cores.text(),
            "size_mm2": self.size.text(),
            "voltage_grade": self.voltage.currentText(),
            "required_length": self.required.value(),
            "status": self.status.currentText(),
            "glanded_date": iso(self.glanded),
            "terminated_date": iso(self.terminated),
            "remarks": self.remarks.text(),
        }
        if self.tag_id:
            old = CB.get_tag(self.cdb, self.tag_id) or {}
            for keep in ("pulled_length", "drum_no", "pulled_date", "test_date",
                         "ir_value", "continuity", "test_result", "tested_by",
                         "test_cert"):
                data[keep] = old.get(keep, "")
        try:
            CB.save_tag(self.cdb, data, self.tag_id)
        except CB.CableError as exc:
            W.error_box(self, str(exc))
            return
        self.accept()


class TestDialog(QDialog):
    """Record the megger / IR and continuity test that closes a cable out."""

    def __init__(self, cdb: CB.CableDB, tag: dict, parent=None):
        super().__init__(parent)
        self.cdb = cdb
        self.tag = tag
        self.setWindowTitle(f"Test record — {tag['tag_no']}")
        self.resize(520, 0)
        v = QVBoxLayout(self)
        head = QLabel(f"<b>{tag['tag_no']}</b> &nbsp; {tag['from_point']} → "
                      f"{tag['to_point']}")
        head.setWordWrap(True)
        v.addWidget(head)
        f = QFormLayout()
        self.date = date_edit(str(tag.get("test_date") or CB.today()))
        f.addRow("Test date", self.date)
        self.ir = QDoubleSpinBox()
        self.ir.setRange(0, 10 ** 6)
        self.ir.setDecimals(2)
        self.ir.setSuffix("  MΩ")
        self.ir.setValue(CB.to_float(tag.get("ir_value")))
        f.addRow("Insulation resistance", self.ir)
        self.continuity = W.combo(["", "Pass", "Fail"], False,
                                  str(tag.get("continuity") or ""))
        f.addRow("Continuity", self.continuity)
        self.result = W.combo(list(CB.TEST_RESULTS), False,
                              str(tag.get("test_result") or CB.TEST_PENDING))
        f.addRow("Result", self.result)
        self.by = QLineEdit(str(tag.get("tested_by") or ""))
        f.addRow("Tested by", self.by)
        self.cert = QLineEdit(str(tag.get("test_cert") or ""))
        f.addRow("Certificate no.", self.cert)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save test")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _save(self):
        try:
            CB.record_test(self.cdb, int(self.tag["id"]), {
                "test_date": iso(self.date), "ir_value": self.ir.value(),
                "continuity": self.continuity.currentText(),
                "test_result": self.result.currentText(),
                "tested_by": self.by.text(), "test_cert": self.cert.text()})
        except CB.CableError as exc:
            W.error_box(self, str(exc))
            return
        self.accept()


class ImportDrumsDialog(QDialog):
    """Paste a drum list straight out of Excel, or load a sheet."""

    def __init__(self, cdb: CB.CableDB, parent=None):
        super().__init__(parent)
        self.cdb = cdb
        self.records: list[dict] = []
        self.result_summary: dict = {}
        self.setWindowTitle("Import cable drums from Excel")
        self.resize(1000, 620)
        v = QVBoxLayout(self)
        note = QLabel(
            "Copy the drum list in Excel and press <b>Paste from clipboard</b>. A "
            "header row is recognised automatically (<i>Drum No., Description, "
            "Size, Length, Remaining, Location, Project…</i>); without one the "
            "columns are read in that order. Existing drum numbers are updated, "
            "new ones are added.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(note)
        bar = QHBoxLayout()
        bar.addWidget(W.button("📋  Paste from clipboard", "Primary",
                               self.from_clipboard))
        bar.addWidget(W.button("📂  Load Excel / CSV...", slot=self.from_file))
        bar.addWidget(W.button("⬇  Excel template", slot=self.template))
        bar.addStretch(1)
        self.chk_update = QCheckBox("Update drums that already exist")
        self.chk_update.setChecked(True)
        bar.addWidget(self.chk_update)
        v.addLayout(bar)
        self.text = QPlainTextEdit()
        self.text.setMaximumHeight(140)
        self.text.textChanged.connect(self.preview)
        v.addWidget(self.text)
        self.table = W.DataTable()
        v.addWidget(self.table, 1)
        self.summary = QLabel("Nothing parsed yet.")
        v.addWidget(self.summary)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        self.btn_ok.setText("Import")
        self.btn_ok.setEnabled(False)
        bb.accepted.connect(self._import)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.from_clipboard(quiet=True)

    def from_clipboard(self, quiet: bool = False):
        from PySide6.QtWidgets import QApplication
        txt = QApplication.clipboard().text()
        if not txt.strip():
            if not quiet:
                W.error_box(self, "The clipboard is empty — copy the rows in Excel "
                                  "first.")
            return
        self.text.setPlainText(txt)

    def from_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open a drum list", "",
                                           "Spreadsheets (*.xlsx *.xlsm *.csv *.txt)")
        if not f:
            return
        try:
            from ..core import importer
            head, rows = importer.read_table(f)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"That file could not be read.\n\n{exc}")
            return
        lines = ["\t".join(str(c) for c in head)] if head else []
        lines += ["\t".join("" if c is None else str(c) for c in r) for r in rows]
        self.text.setPlainText("\n".join(lines))

    def template(self):
        cols, rows = CB.template_rows()
        try:
            p = D.export_excel(self.cdb and None or None, "x", [], []) if False else \
                D.export_excel(self.parent().db, "Cable Drum Import Template",
                               cols, rows, totals=False)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Could not write the template.\n\n{exc}")
            return
        W.toast(self, f"Template saved: {Path(p).name}")
        try:
            D.open_path(p)
        except Exception:                 # noqa: BLE001
            pass

    def preview(self):
        head, rows = CB.sniff(self.text.toPlainText())
        self.records = CB.rows_to_drums(head, rows)
        shown = ["drum_no", "description", "cable_type", "size_mm2",
                 "original_length", "remaining_length", "location", "project"]
        self.table.fill(
            ["Drum No.", "Description", "Type", "Size", "Length", "Remaining",
             "Location", "Project", "Status"],
            [[r.get(k, "") for k in shown] +
             ["update" if r.get("drum_no") and
              CB.drum_by_no(self.cdb, str(r["drum_no"])) else "new"]
             for r in self.records])
        self.summary.setText(f"<b>{len(self.records)}</b> row(s) ready to import."
                             if self.records else "Nothing parsed yet.")
        self.btn_ok.setEnabled(bool(self.records))

    def _import(self):
        self.result_summary = CB.import_drums(self.cdb, self.records,
                                              self.chk_update.isChecked())
        if self.result_summary["errors"]:
            W.error_box(self, "Some rows were refused:\n\n" +
                        "\n".join(self.result_summary["errors"][:12]))
        self.accept()


# ============================================================== drum register
class DrumsTab(QWidget):
    """Every drum, what is left on it, and everything you can do to it."""
    changed = Signal()

    def __init__(self, cdb: CB.CableDB, db: Database, parent=None):
        super().__init__(parent)
        self.cdb = cdb
        self.db = db
        self.rows: list[dict] = []
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search drum, cable, size, PO, GRN, batch, "
                                  "project, location ...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 3)
        self.f_status = W.combo(["All Status"] + list(CB.DRUM_STATUS))
        self.f_type = W.combo(["All Cable Types"])
        self.f_size = W.combo(["All Sizes"])
        self.f_project = W.combo(["All Projects"])
        self.f_location = W.combo(["All Locations"])
        for cb in (self.f_status, self.f_type, self.f_size, self.f_project,
                   self.f_location):
            cb.currentTextChanged.connect(self.reload)
            bar.addWidget(cb)
        v.addLayout(bar)

        bar2 = QHBoxLayout()
        self.chk_stock = QCheckBox("With cable left")
        self.chk_offcut = QCheckBox("Off-cuts only")
        self.chk_idle = QCheckBox("Idle drums")
        for c in (self.chk_stock, self.chk_offcut, self.chk_idle):
            c.toggled.connect(self.reload)
            bar2.addWidget(c)
        bar2.addWidget(W.button("✖  Clear Filters", slot=self.clear_filters))
        bar2.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        bar2.addWidget(self.count)
        v.addLayout(bar2)

        act = QHBoxLayout()
        act.addWidget(W.button("➕  New Drum", "Primary", self.new_drum))
        act.addWidget(W.button("✏  Edit", slot=self.edit_drum))
        act.addWidget(W.button("✂  Issue Length", "Accent", self.issue_cut,
                               tip="Cut a length off this drum"))
        act.addWidget(W.button("↩  Return Off-cut", slot=self.return_cut))
        act.addWidget(W.button("🔒  Reserve", slot=self.reserve))
        act.addWidget(W.button("⛔  Scrap", slot=self.scrap))
        act.addWidget(W.button("📥  Import from Excel", slot=self.import_drums))
        act.addWidget(W.button("🗑  Delete", slot=self.delete_drums))
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
        self.table.itemSelectionChanged.connect(self._load_history)
        self.table.doubleClicked.connect(self.edit_drum)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        tv.addWidget(W.FilterBar(self.table))
        tv.addWidget(self.table)
        split.addWidget(top)

        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 6, 0, 0)
        self.lbl_drum = QLabel("Select a drum above")
        self.lbl_drum.setStyleSheet(f"color:{W.NAVY}; font-weight:700;")
        bv.addWidget(self.lbl_drum)
        self.t_hist = W.DataTable()
        bv.addWidget(self.t_hist, 1)
        split.addWidget(bottom)
        split.setSizes([400, 240])
        v.addWidget(split, 1)
        v.addWidget(ShareBar(self.db, lambda: self.last_file, self))

    # ------------------------------------------------------------- filters
    def filters(self) -> dict:
        f: dict = {"text": self.search.text().strip()}
        if self.f_status.currentIndex() > 0:
            f["status"] = self.f_status.currentText()
        if self.f_type.currentIndex() > 0:
            f["cable_type"] = self.f_type.currentText()
        if self.f_size.currentIndex() > 0:
            f["size"] = self.f_size.currentText()
        if self.f_project.currentIndex() > 0:
            f["project"] = self.f_project.currentText()
        if self.f_location.currentIndex() > 0:
            f["location"] = self.f_location.currentText()
        if self.chk_stock.isChecked():
            f["in_stock_only"] = True
        if self.chk_offcut.isChecked():
            f["offcuts_only"] = True
        if self.chk_idle.isChecked():
            f["idle_only"] = True
        f["offcut_limit"] = CB.to_float(
            self.cdb.get_setting("offcut_limit", CB.DEFAULT_OFFCUT_LIMIT),
            CB.DEFAULT_OFFCUT_LIMIT)
        return f

    def clear_filters(self):
        self.search.clear()
        for cb in (self.f_status, self.f_type, self.f_size, self.f_project,
                   self.f_location):
            cb.setCurrentIndex(0)
        for c in (self.chk_stock, self.chk_offcut, self.chk_idle):
            c.setChecked(False)
        self.reload()

    def apply_filter(self, f: dict):
        """Called when a dashboard tile is clicked."""
        self.clear_filters()
        self.search.setText(str(f.get("text") or ""))
        for key, cb in (("status", self.f_status), ("cable_type", self.f_type),
                        ("size", self.f_size), ("project", self.f_project),
                        ("location", self.f_location)):
            if f.get(key):
                i = cb.findText(str(f[key]))
                cb.setCurrentIndex(i if i >= 0 else 0)
        self.chk_stock.setChecked(bool(f.get("in_stock_only")))
        self.chk_offcut.setChecked(bool(f.get("offcuts_only")))
        self.chk_idle.setChecked(bool(f.get("idle_only")))
        self.reload()

    def reload_filters(self):
        for cb, col, first in ((self.f_type, "cable_type", "All Cable Types"),
                               (self.f_size, "size_mm2", "All Sizes"),
                               (self.f_project, "project", "All Projects"),
                               (self.f_location, "location", "All Locations")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + CB.distinct(self.cdb, "drums", col))
            cb.setCurrentIndex(max(0, cb.findText(cur)))
            cb.blockSignals(False)

    # -------------------------------------------------------------- render
    def reload(self):
        self.rows = CB.search_drums(self.cdb, **self.filters())
        self.table.fill(
            ["Drum No.", "Cable", "Type", "Cores", "Size", "Voltage",
             "Manufacturer", "Original", "Remaining", "Used", "Used %", "UOM",
             "Location", "Project", "Status", "Idle Days", "Value"],
            [[d["drum_no"], d["description"], d["cable_type"], d["cores"],
              d["size_mm2"], d["voltage_grade"], d["manufacturer"],
              d["original_length"], d["remaining_length"], d["used_length"],
              d["utilisation"], d["uom"], d["location"], d["project"],
              d["status"], d["idle_days"], d["value"]] for d in self.rows])
        _paint(self.table, 14, CB.DRUM_COLORS)
        total = sum(float(d["remaining_length"]) for d in self.rows)
        self.count.setText(f"{len(self.rows)} drum(s) · {total:,.1f} m in stock")

    def _selected(self) -> dict | None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return self.rows[rows[0]] if rows and rows[0] < len(self.rows) else None

    def _selected_all(self) -> list[dict]:
        return [self.rows[r] for r in sorted({i.row() for i in
                                              self.table.selectedIndexes()})
                if r < len(self.rows)]

    def _load_history(self):
        d = self._selected()
        if d is None:
            self.lbl_drum.setText("Select a drum above")
            self.t_hist.fill([], [])
            return
        self.lbl_drum.setText(
            f"{d['drum_no']} — {d['description']}   ·   "
            f"{d['remaining_length']:g} of {d['original_length']:g} {d['uom']} left"
            f"   ·   {d['status']}")
        hist = CB.search_cuts(self.cdb, drum_no=d["drum_no"], include_void=True)
        self.t_hist.fill(
            ["Cut No.", "Date", "Type", "Length", "Cable Tag", "Project",
             "Issued To", "DN No.", "From", "To", "Voided", "Remarks"],
            [[c["cut_no"], CB.fmt_date(c["cut_date"]), c["txn_type"], c["length"],
              c["tag_no"], c["project"], c["issued_to"], c["dn_no"],
              c["from_point"], c["to_point"], "YES" if c["voided"] else "",
              c["remarks"]] for c in hist])
        _paint(self.t_hist, 2, CB.CUT_COLORS)

    def _menu(self, pos):
        menu = QMenu(self)
        a_new = menu.addAction("➕  New drum")
        a_edit = menu.addAction("✏  Edit drum")
        menu.addSeparator()
        a_cut = menu.addAction("✂  Issue a length")
        a_ret = menu.addAction("↩  Return an off-cut")
        a_res = menu.addAction("🔒  Reserve this drum")
        a_scr = menu.addAction("⛔  Scrap what is left")
        menu.addSeparator()
        a_del = menu.addAction("🗑  Delete drum")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        for act, fn in ((a_new, self.new_drum), (a_edit, self.edit_drum),
                        (a_cut, self.issue_cut), (a_ret, self.return_cut),
                        (a_res, self.reserve), (a_scr, self.scrap),
                        (a_del, self.delete_drums)):
            if chosen is act:
                fn()
                return

    # ------------------------------------------------------------- actions
    def new_drum(self):
        dlg = DrumDialog(self.cdb, None, self)
        if dlg.exec() == QDialog.Accepted:
            self.reload_filters()
            self.reload()
            self.changed.emit()
            W.toast(self, "Drum added to the register.")

    def edit_drum(self):
        d = self._selected()
        if d is None:
            W.error_box(self, "Select a drum first.")
            return
        dlg = DrumDialog(self.cdb, int(d["id"]), self)
        if dlg.exec() == QDialog.Accepted:
            self.reload_filters()
            self.reload()
            self.changed.emit()

    def _cut(self, txn_type: str):
        d = self._selected()
        if d is None:
            W.error_box(self, "Select a drum first.")
            return
        dlg = CutDialog(self.cdb, d, txn_type, self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()
            self._load_history()
            self.changed.emit()
            W.toast(self, f"{txn_type} recorded as {dlg.cut_no}.")

    def issue_cut(self):
        self._cut(CB.CUT_ISSUE)

    def return_cut(self):
        self._cut(CB.CUT_RETURN)

    def reserve(self):
        d = self._selected()
        if d is None:
            W.error_box(self, "Select a drum first.")
            return
        if d["status"] == CB.RESERVED:
            CB.set_drum_status(self.cdb, int(d["id"]),
                               CB.drum_status_for(float(d["remaining_length"]),
                                                  float(d["original_length"])))
            W.toast(self, f"Drum {d['drum_no']} released.")
        else:
            who, ok = QInputDialog.getText(self, "Reserve drum",
                                           "Reserved for (project / tag / crew):")
            if not ok:
                return
            CB.set_drum_status(self.cdb, int(d["id"]), CB.RESERVED, who.strip())
            W.toast(self, f"Drum {d['drum_no']} reserved for {who.strip() or '—'}.")
        self.reload()
        self.changed.emit()

    def scrap(self):
        d = self._selected()
        if d is None:
            W.error_box(self, "Select a drum first.")
            return
        reason, ok = QInputDialog.getText(
            self, "Scrap cable",
            f"Scrapping writes off the {float(d['remaining_length']):g} "
            f"{d['uom']} left on {d['drum_no']}.\n\nReason (mandatory):")
        if not ok:
            return
        try:
            CB.scrap_drum(self.cdb, int(d["id"]), reason)
        except CB.CableError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        self._load_history()
        self.changed.emit()
        W.toast(self, f"Drum {d['drum_no']} scrapped.")

    def delete_drums(self):
        rows = self._selected_all()
        if not rows:
            W.error_box(self, "Select at least one drum.")
            return
        if not W.confirm(self, f"Delete {len(rows)} drum(s) from the register?\n\n"
                               "Only drums with no cutting history can be deleted."):
            return
        try:
            n = CB.delete_drums(self.cdb, [int(r["id"]) for r in rows])
        except CB.CableError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        self.changed.emit()
        W.toast(self, f"{n} drum(s) deleted.")

    def import_drums(self):
        dlg = ImportDrumsDialog(self.cdb, self)
        if dlg.exec() != QDialog.Accepted:
            return
        s = dlg.result_summary
        self.reload_filters()
        self.reload()
        self.changed.emit()
        W.info_box(self, f"Added: {s.get('added', 0)}\nUpdated: {s.get('updated', 0)}\n"
                         f"Skipped: {s.get('skipped', 0)}\n"
                         f"Refused: {len(s.get('errors', []))}", "Import finished")

    def export(self, kind: str):
        title, cols, rows = CB.build_report(self.cdb, CB.REPORT_LIST[0],
                                            self.filters())
        if not rows:
            W.error_box(self, "Nothing matches the current filters.")
            return
        try:
            if kind == "xlsx":
                self.last_file = D.export_excel(self.db, "Cable Drum Register",
                                                cols, rows)
            else:
                self.last_file = D.cable_report_pdf(self.db, "Cable Drum Register",
                                                   cols, rows)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Export failed.\n\n{exc}")
            return
        W.toast(self, f"Exported: {Path(self.last_file).name}")
        try:
            D.open_path(self.last_file)
        except Exception:                 # noqa: BLE001
            pass


# ================================================================ cutting log
class CutsTab(QWidget):
    """Every length that ever left — or came back to — a drum."""
    changed = Signal()

    def __init__(self, cdb: CB.CableDB, db: Database, parent=None):
        super().__init__(parent)
        self.cdb = cdb
        self.db = db
        self.rows: list[dict] = []
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search cut no., drum, tag, project, DN, "
                                  "receiver ...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 3)
        self.f_type = W.combo(["All Records"] + list(CB.CUT_TYPES))
        self.f_project = W.combo(["All Projects"])
        self.f_tag = W.combo(["All Cable Tags"])
        for cb in (self.f_type, self.f_project, self.f_tag):
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
            d.dateChanged.connect(lambda _: self.chk_dates.isChecked() and self.reload())
        bar2.addWidget(self.chk_dates)
        bar2.addWidget(self.d_from)
        bar2.addWidget(QLabel("to"))
        bar2.addWidget(self.d_to)
        self.chk_void = QCheckBox("Show voided records")
        self.chk_void.toggled.connect(self.reload)
        bar2.addWidget(self.chk_void)
        bar2.addWidget(W.button("🚫  Void Selected", slot=self.void_cut,
                                tip="Cancel a cut — the length goes back on the drum"))
        bar2.addStretch(1)
        bar2.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        bar2.addWidget(W.button("📄  PDF", slot=lambda: self.export("pdf")))
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        bar2.addWidget(self.count)
        v.addLayout(bar2)

        self.table = W.DataTable()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(W.FilterBar(self.table))
        v.addWidget(self.table, 1)
        v.addWidget(ShareBar(self.db, lambda: self.last_file, self))

    def filters(self) -> dict:
        f: dict = {"text": self.search.text().strip()}
        if self.f_type.currentIndex() > 0:
            f["txn_type"] = self.f_type.currentText()
        if self.f_project.currentIndex() > 0:
            f["project"] = self.f_project.currentText()
        if self.f_tag.currentIndex() > 0:
            f["tag_no"] = self.f_tag.currentText()
        if self.chk_dates.isChecked():
            f["date_from"] = iso(self.d_from)
            f["date_to"] = iso(self.d_to)
        if self.chk_void.isChecked():
            f["include_void"] = True
        return f

    def reload_filters(self):
        for cb, table, col, first in ((self.f_project, "cuts", "project",
                                       "All Projects"),
                                      (self.f_tag, "cuts", "tag_no",
                                       "All Cable Tags")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + CB.distinct(self.cdb, table, col))
            cb.setCurrentIndex(max(0, cb.findText(cur)))
            cb.blockSignals(False)

    def reload(self):
        self.rows = CB.search_cuts(self.cdb, **self.filters())
        self.table.fill(
            ["Cut No.", "Date", "Type", "Drum", "Length", "Cable Tag", "Project",
             "Issued To", "DN No.", "From", "To", "Voided", "Remarks"],
            [[c["cut_no"], CB.fmt_date(c["cut_date"]), c["txn_type"], c["drum_no"],
              c["length"], c["tag_no"], c["project"], c["issued_to"], c["dn_no"],
              c["from_point"], c["to_point"], "YES" if c["voided"] else "",
              c["remarks"]] for c in self.rows])
        _paint(self.table, 2, CB.CUT_COLORS)
        issued = sum(float(c["length"]) for c in self.rows
                     if c["txn_type"] == CB.CUT_ISSUE and not c["voided"])
        back = sum(float(c["length"]) for c in self.rows
                   if c["txn_type"] == CB.CUT_RETURN and not c["voided"])
        self.count.setText(f"{len(self.rows)} record(s) · issued {issued:,.1f} m · "
                           f"returned {back:,.1f} m")

    def void_cut(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            W.error_box(self, "Select the cut record to void.")
            return
        cut = self.rows[rows[0]]
        if cut["voided"]:
            W.error_box(self, f"{cut['cut_no']} is already voided.")
            return
        reason, ok = QInputDialog.getText(
            self, "Void cut record",
            f"Voiding {cut['cut_no']} puts {float(cut['length']):g} m back on drum "
            f"{cut['drum_no']}.\n\nReason:")
        if not ok:
            return
        try:
            CB.void_cut(self.cdb, int(cut["id"]), reason.strip())
        except CB.CableError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        self.changed.emit()
        W.toast(self, f"{cut['cut_no']} voided.")

    def export(self, kind: str):
        title, cols, rows = CB.build_report(self.cdb, CB.REPORT_LIST[6],
                                            self.filters())
        if not rows:
            W.error_box(self, "Nothing matches the current filters.")
            return
        try:
            if kind == "xlsx":
                self.last_file = D.export_excel(self.db, "Cable Cutting Log", cols, rows)
            else:
                self.last_file = D.cable_report_pdf(self.db, "Cable Cutting Log",
                                                   cols, rows)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Export failed.\n\n{exc}")
            return
        W.toast(self, f"Exported: {Path(self.last_file).name}")
        try:
            D.open_path(self.last_file)
        except Exception:                 # noqa: BLE001
            pass


# ============================================================= cable schedule
class ScheduleTab(QWidget):
    """Tag by tag: what has to be pulled, what was pulled, and its test."""
    changed = Signal()

    def __init__(self, cdb: CB.CableDB, db: Database, parent=None):
        super().__init__(parent)
        self.cdb = cdb
        self.db = db
        self.rows: list[dict] = []
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search tag, from, to, route, project, area ...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 3)
        self.f_status = W.combo(["All Status"] + list(CB.TAG_STATUS))
        self.f_project = W.combo(["All Projects"])
        self.f_area = W.combo(["All Areas"])
        self.f_test = W.combo(["All Test Results"] + list(CB.TEST_RESULTS))
        for cb in (self.f_status, self.f_project, self.f_area, self.f_test):
            cb.currentTextChanged.connect(self.reload)
            bar.addWidget(cb)
        v.addLayout(bar)

        act = QHBoxLayout()
        act.addWidget(W.button("➕  New Cable Tag", "Primary", self.new_tag))
        act.addWidget(W.button("✏  Edit", slot=self.edit_tag))
        act.addWidget(W.button("✂  Pull From Drum", "Accent", self.pull,
                               tip="Issue the cable for this tag from a drum"))
        act.addWidget(W.button("🎯  Record Test", slot=self.test))
        act.addWidget(W.button("➡  Advance Status", slot=self.advance,
                               tip="Planned → Pulled → Glanded → Terminated → "
                                   "Tested → Energized"))
        act.addWidget(W.button("🗑  Delete", slot=self.delete_tags))
        self.chk_pending = QCheckBox("Still to pull")
        self.chk_pending.toggled.connect(self.reload)
        act.addWidget(self.chk_pending)
        act.addStretch(1)
        act.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        act.addWidget(W.button("📄  PDF", slot=lambda: self.export("pdf")))
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        act.addWidget(self.count)
        v.addLayout(act)

        self.table = W.DataTable()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.doubleClicked.connect(self.edit_tag)
        v.addWidget(W.FilterBar(self.table))
        v.addWidget(self.table, 1)
        v.addWidget(ShareBar(self.db, lambda: self.last_file, self))

    def filters(self) -> dict:
        f: dict = {"text": self.search.text().strip()}
        if self.f_status.currentIndex() > 0:
            f["status"] = self.f_status.currentText()
        if self.f_project.currentIndex() > 0:
            f["project"] = self.f_project.currentText()
        if self.f_area.currentIndex() > 0:
            f["area"] = self.f_area.currentText()
        if self.f_test.currentIndex() > 0:
            f["test_result"] = self.f_test.currentText()
        if self.chk_pending.isChecked():
            f["short_only"] = True
        return f

    def apply_filter(self, f: dict):
        self.search.setText(str(f.get("text") or ""))
        for key, cb in (("status", self.f_status), ("project", self.f_project),
                        ("area", self.f_area), ("test_result", self.f_test)):
            i = cb.findText(str(f.get(key) or ""))
            cb.setCurrentIndex(i if i > 0 else 0)
        self.reload()

    def reload_filters(self):
        for cb, col, first in ((self.f_project, "project", "All Projects"),
                               (self.f_area, "area", "All Areas")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + CB.distinct(self.cdb, "schedule", col))
            cb.setCurrentIndex(max(0, cb.findText(cur)))
            cb.blockSignals(False)

    def reload(self):
        self.rows = CB.search_tags(self.cdb, **self.filters())
        self.table.fill(
            ["Cable Tag", "Project", "Area", "From", "To", "Route", "Type",
             "Cores", "Size", "Required", "Pulled", "Balance", "Progress %",
             "Drum(s)", "Status", "Test", "IR (MΩ)", "Test Date"],
            [[t["tag_no"], t["project"], t["area"], t["from_point"], t["to_point"],
              t["route"], t["cable_type"], t["cores"], t["size_mm2"],
              t["required_length"], t["pulled_length"], t["balance"], t["progress"],
              t["drum_no"], t["status"], t["test_result"], t["ir_value"],
              CB.fmt_date(t["test_date"])] for t in self.rows])
        _paint(self.table, 14, CB.TAG_COLORS)
        _paint(self.table, 15, CB.TEST_COLORS)
        req = sum(float(t["required_length"]) for t in self.rows)
        pul = sum(float(t["pulled_length"]) for t in self.rows)
        self.count.setText(f"{len(self.rows)} tag(s) · required {req:,.0f} m · "
                           f"pulled {pul:,.0f} m")

    def _selected(self) -> dict | None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return self.rows[rows[0]] if rows and rows[0] < len(self.rows) else None

    # ------------------------------------------------------------- actions
    def new_tag(self):
        dlg = TagDialog(self.cdb, None, self)
        if dlg.exec() == QDialog.Accepted:
            self.reload_filters()
            self.reload()
            self.changed.emit()

    def edit_tag(self):
        t = self._selected()
        if t is None:
            W.error_box(self, "Select a cable tag first.")
            return
        dlg = TagDialog(self.cdb, int(t["id"]), self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()

    def pull(self):
        t = self._selected()
        if t is None:
            W.error_box(self, "Select a cable tag first.")
            return
        drums = CB.search_drums(self.cdb, in_stock_only=True)
        if t["size_mm2"]:
            match = [d for d in drums if d["size_mm2"] == t["size_mm2"]]
            drums = match or drums
        if not drums:
            W.error_box(self, "No drum has any cable left.")
            return
        labels = [f"{d['drum_no']} — {d['description']} "
                  f"({d['remaining_length']:g} {d['uom']} left)" for d in drums]
        choice, ok = QInputDialog.getItem(self, f"Pull cable for {t['tag_no']}",
                                          "Take it from which drum?", labels, 0, False)
        if not ok:
            return
        drum = drums[labels.index(choice)]
        dlg = CutDialog(self.cdb, drum, CB.CUT_ISSUE, self)
        dlg.tag.setCurrentText(t["tag_no"])
        dlg.length.setValue(max(0.0, float(t["balance"])))
        dlg.frm.setText(t["from_point"])
        dlg.to.setText(t["to_point"])
        dlg.project.setText(t["project"])
        if dlg.exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()
            W.toast(self, f"{dlg.cut_no} — cable pulled for {t['tag_no']}.")

    def test(self):
        t = self._selected()
        if t is None:
            W.error_box(self, "Select a cable tag first.")
            return
        dlg = TestDialog(self.cdb, t, self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()
            self.changed.emit()

    def advance(self):
        t = self._selected()
        if t is None:
            W.error_box(self, "Select a cable tag first.")
            return
        order = [s for s in CB.TAG_STATUS if s != CB.TAG_CANCELLED]
        try:
            nxt = order[min(order.index(t["status"]) + 1, len(order) - 1)]
        except ValueError:
            nxt = CB.PLANNED
        data = dict(t)
        data["status"] = nxt
        if nxt == CB.GLANDED and not data.get("glanded_date"):
            data["glanded_date"] = CB.today()
        if nxt == CB.TERMINATED and not data.get("terminated_date"):
            data["terminated_date"] = CB.today()
        CB.save_tag(self.cdb, data, int(t["id"]))
        self.reload()
        self.changed.emit()
        W.toast(self, f"{t['tag_no']} is now {nxt}.")

    def delete_tags(self):
        rows = [self.rows[r] for r in sorted({i.row() for i in
                                              self.table.selectedIndexes()})
                if r < len(self.rows)]
        if not rows:
            W.error_box(self, "Select at least one cable tag.")
            return
        if not W.confirm(self, f"Delete {len(rows)} cable tag(s) from the schedule?"):
            return
        CB.delete_tags(self.cdb, [int(r["id"]) for r in rows])
        self.reload()
        self.changed.emit()

    def export(self, kind: str):
        title, cols, rows = CB.build_report(self.cdb, CB.REPORT_LIST[9],
                                            self.filters())
        if not rows:
            W.error_box(self, "Nothing matches the current filters.")
            return
        try:
            if kind == "xlsx":
                self.last_file = D.export_excel(self.db, "Cable Schedule", cols, rows)
            else:
                self.last_file = D.cable_report_pdf(self.db, "Cable Schedule",
                                                   cols, rows)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Export failed.\n\n{exc}")
            return
        W.toast(self, f"Exported: {Path(self.last_file).name}")
        try:
            D.open_path(self.last_file)
        except Exception:                 # noqa: BLE001
            pass


# =================================================================== reports
class CableReportsTab(QWidget):
    def __init__(self, cdb: CB.CableDB, db: Database, parent=None):
        super().__init__(parent)
        self.cdb = cdb
        self.db = db
        self.cols: list[str] = []
        self.rows: list[list] = []
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)
        bar = QHBoxLayout()
        self.pick = W.combo(CB.REPORT_LIST)
        self.pick.currentTextChanged.connect(self.run)
        bar.addWidget(QLabel("Report:"))
        bar.addWidget(self.pick, 2)
        self.search = W.SearchBox("Filter inside the report ...")
        self.search.textChanged.connect(self.run)
        bar.addWidget(self.search, 2)
        self.f_project = W.combo(["All Projects"])
        self.f_project.currentTextChanged.connect(self.run)
        bar.addWidget(self.f_project)
        bar.addWidget(W.button("🔄  Run", "Primary", self.run))
        bar.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        bar.addWidget(W.button("📄  PDF", slot=lambda: self.export("pdf")))
        bar.addWidget(W.button("🖨  Print", slot=self.print_out))
        v.addLayout(bar)
        self.table = W.DataTable()
        v.addWidget(W.FilterBar(self.table))
        v.addWidget(self.table, 1)
        v.addWidget(ShareBar(self.db, lambda: self.last_file, self))

    def reload_filters(self):
        cur = self.f_project.currentText()
        self.f_project.blockSignals(True)
        self.f_project.clear()
        self.f_project.addItems(["All Projects"] +
                                CB.distinct(self.cdb, "drums", "project"))
        self.f_project.setCurrentIndex(max(0, self.f_project.findText(cur)))
        self.f_project.blockSignals(False)

    def filters(self) -> dict:
        f = {"text": self.search.text().strip()}
        if self.f_project.currentIndex() > 0:
            f["project"] = self.f_project.currentText()
        return f

    def run(self):
        try:
            _t, self.cols, self.rows = CB.build_report(
                self.cdb, self.pick.currentText(), self.filters())
        except CB.CableError as exc:
            W.error_box(self, str(exc))
            return
        self.table.fill(self.cols, self.rows)

    def export(self, kind: str):
        if not self.rows:
            self.run()
        if not self.rows:
            W.error_box(self, "That report is empty.")
            return
        name = self.pick.currentText()
        try:
            if kind == "xlsx":
                self.last_file = D.export_excel(self.db, f"Cable — {name}",
                                                self.cols, self.rows)
            else:
                self.last_file = D.cable_report_pdf(self.db, f"Cable Records — {name}",
                                                   self.cols, self.rows)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Export failed.\n\n{exc}")
            return
        W.toast(self, f"Exported: {Path(self.last_file).name}")
        try:
            D.open_path(self.last_file)
        except Exception:                 # noqa: BLE001
            pass

    def print_out(self):
        self.export("pdf")


# ================================================================= main page
class CableRecordsPage(QWidget):
    """Top-level page holding the five Cable Records tabs."""
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.cdb = CB.get_cable_db()
        self.cdb.current_user = db.current_user

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)

        banner = QLabel(
            "🧵  <b>Cable Records</b> — a stand-alone register for cable drums: "
            "what is on every drum, every length cut off it, and the cable "
            "schedule it served (pulled, glanded, terminated, megger tested). "
            f"It has its own database file (<code>{self.cdb.path.name}</code>), "
            "its own backups and its own reports. Nothing here affects "
            "inventory stock.")
        banner.setWordWrap(True)
        banner.setStyleSheet(f"background:{W.NAVY}; color:white; border-radius:7px; "
                             "padding:8px 12px;")
        v.addWidget(banner)

        self.tabs = QTabWidget()
        self.dash = CableDashboard(self.cdb, db)
        self.drums = DrumsTab(self.cdb, db)
        self.cuts = CutsTab(self.cdb, db)
        self.schedule = ScheduleTab(self.cdb, db)
        self.reports = CableReportsTab(self.cdb, db)
        self.tabs.addTab(self.dash, "📊  Dashboard")
        self.tabs.addTab(self.drums, "🥁  Drum Register")
        self.tabs.addTab(self.cuts, "✂  Cutting Log")
        self.tabs.addTab(self.schedule, "🧭  Cable Schedule")
        self.tabs.addTab(self.reports, "📈  Reports")
        v.addWidget(self.tabs, 1)

        tools = QHBoxLayout()
        tools.addWidget(W.button("💾  Backup Module", slot=self._backup,
                                 tip="Back up the Cable Records database"))
        tools.addWidget(W.button("♻  Restore...", slot=self._restore))
        tools.addWidget(W.button("📂  Open Data Folder", slot=self._folder))
        tools.addWidget(W.button("🧮  Rebuild Balances", slot=self._rebuild,
                                 tip="Re-derive every drum's remaining length from "
                                     "its cutting log"))
        tools.addWidget(W.button("🔄  Refresh", slot=self.refresh))
        tools.addWidget(W.button("🧪  Load Sample Data", slot=self._demo,
                                 tip="Fill an empty register with a realistic "
                                     "sample so the dashboard can be tried"))
        tools.addStretch(1)
        self.stat = QLabel()
        self.stat.setStyleSheet(f"color:{W.MUTED};")
        tools.addWidget(self.stat)
        v.addLayout(tools)

        for tab in (self.drums, self.cuts, self.schedule):
            tab.changed.connect(self.refresh)
        self.dash.openRegister.connect(self._drill_drums)
        self.dash.openSchedule.connect(self._drill_schedule)
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        self.refresh()

    def _drill_drums(self, f: dict):
        self.tabs.setCurrentWidget(self.drums)
        self.drums.apply_filter(f)

    def _drill_schedule(self, f: dict):
        self.tabs.setCurrentWidget(self.schedule)
        self.schedule.apply_filter(f)

    def refresh(self):
        i = self.tabs.currentIndex()
        if i == 0:
            self.dash.reload_filters()
            self.dash.reload()
        elif i == 1:
            self.drums.reload_filters()
            self.drums.reload()
        elif i == 2:
            self.cuts.reload_filters()
            self.cuts.reload()
        elif i == 3:
            self.schedule.reload_filters()
            self.schedule.reload()
        else:
            self.reports.reload_filters()
            self.reports.run()
        d = CB.dashboard(self.cdb)
        self.stat.setText(
            f"{d['drums']} drum(s) · {d['remaining_length']:,.0f} m in stock · "
            f"{d['used_length']:,.0f} m consumed · {d['offcuts']} off-cut(s) · "
            f"{d['tags']} cable tag(s)")
        self.dataChanged.emit()

    def _backup(self):
        try:
            p = self.cdb.backup(note="manual backup")
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Backup failed.\n\n{exc}")
            return
        W.info_box(self, f"Cable Records backed up to:\n\n{p}", "Backup complete")

    def _restore(self):
        f, _ = QFileDialog.getOpenFileName(self, "Restore the Cable Records database",
                                           "", "Database (*.db)")
        if not f:
            return
        if not W.confirm(self, "Replace the current cable data with this backup?\n\n"
                               "A safety copy of the current data is taken first."):
            return
        try:
            self.cdb.restore(f)
        except Exception as exc:          # noqa: BLE001
            W.error_box(self, f"Restore failed.\n\n{exc}")
            return
        self.refresh()
        W.toast(self, "Cable Records restored.")

    def _rebuild(self):
        n = CB.rebuild_drums(self.cdb)
        self.refresh()
        W.toast(self, f"{n} drum balance(s) re-derived from the cutting log.")

    def _demo(self):
        if self.cdb.scalar("SELECT COUNT(*) FROM drums"):
            W.error_box(self, "The register already has drums — sample data is only "
                              "loaded into an empty module.")
            return
        CB.seed_demo(self.cdb)
        self.refresh()
        W.toast(self, "Sample cable records loaded.")

    def _folder(self):
        try:
            D.open_path(CB.module_folder())
        except Exception:                 # noqa: BLE001
            pass
