"""Appearance tab: presets, live colour pickers, fonts, density, form styles."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFontComboBox, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ..core import config, theming
from ..core.database import Database
from . import widgets as W

COLOR_FIELDS = [
    ("ui_primary", "Primary / headers", "Sidebar accent, table headers, primary buttons"),
    ("ui_primary_dark", "Sidebar background", "The dark navigation panel"),
    ("ui_accent", "Accent / highlight", "Accent buttons and active markers"),
    ("ui_bg", "Window background", "Behind all pages"),
    ("ui_card", "Card / input background", "Cards, tables, input boxes"),
    ("ui_text", "Text colour", "Main text"),
    ("ui_muted", "Secondary text", "Labels and hints"),
    ("ui_border", "Borders", "Lines around cards, inputs and tables"),
    ("ui_table_alt", "Table stripe", "Alternating table row"),
    ("ui_selection", "Selection", "Selected table row"),
    ("ui_form_header_bg", "Form banner (start)", "Title bar on Stock In / Out / Return forms"),
    ("ui_form_header_bg2", "Form banner (end)", "Gradient end colour of the form title bar"),
    ("ui_form_header_text", "Form banner text", "Text inside the form title bar"),
    ("ui_table_header_text", "Table header text", "Text inside table headers"),
    ("ui_ok", "Status: Normal", "Healthy stock"),
    ("ui_warn", "Status: Warning", "Below minimum level"),
    ("ui_crit", "Status: Critical", "Below critical level"),
    ("ui_danger", "Status: Out of stock", "Zero balance / destructive buttons"),
]


class ColorButton(QPushButton):
    """Swatch button that opens the colour picker."""
    colorChanged = Signal(str)

    def __init__(self, value: str, parent=None):
        super().__init__(parent)
        self.value = value
        self.setFixedSize(92, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._paint()

    def _paint(self):
        c = QColor(self.value)
        fg = "#ffffff" if c.lightness() < 140 else "#101418"
        self.setStyleSheet(f"background:{self.value}; color:{fg}; border:1px solid #888;"
                           f"border-radius:5px; font-weight:600; font-size:11px;")
        self.setText(self.value.upper())

    def set_value(self, v: str):
        self.value = v
        self._paint()

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.value), self, "Choose colour")
        if c.isValid():
            self.value = c.name()
            self._paint()
            self.colorChanged.emit(self.value)


class AppearanceTab(QWidget):
    """Live theme editor — changes apply to the whole app instantly."""
    themeApplied = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.theme = theming.get_theme(db)
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        v.setSpacing(12)

        # ---------------- presets
        g0 = QGroupBox("Theme presets")
        h0 = QHBoxLayout(g0)
        self.preset = QComboBox()
        self.preset.addItems(list(theming.PRESETS))
        cur = db.get_setting("ui_preset", "AURCO Light")
        if cur in theming.PRESETS:
            self.preset.setCurrentText(cur)
        h0.addWidget(QLabel("Preset:"))
        h0.addWidget(self.preset, 1)
        h0.addWidget(W.button("Apply preset", "Primary", self._apply_preset))
        h0.addWidget(W.button("↺ Reset to factory", slot=self._reset))
        h0.addWidget(W.button("⬇ Export theme", slot=self._export))
        h0.addWidget(W.button("⬆ Import theme", slot=self._import))
        v.addWidget(g0)

        # ---------------- colours
        g1 = QGroupBox("Colours — click a swatch to change it")
        grid = QGridLayout(g1)
        grid.setHorizontalSpacing(16)
        self.color_buttons: dict[str, ColorButton] = {}
        for i, (key, label, tip) in enumerate(COLOR_FIELDS):
            r, c = divmod(i, 3)
            cell = QHBoxLayout()
            btn = ColorButton(self.theme.get(key, "#ffffff"))
            btn.setToolTip(tip)
            btn.colorChanged.connect(lambda val, k=key: self._set(k, val))
            self.color_buttons[key] = btn
            lbl = QLabel(label)
            lbl.setToolTip(tip)
            lbl.setMinimumWidth(140)
            cell.addWidget(btn)
            cell.addWidget(lbl, 1)
            wrap = QWidget()
            wrap.setLayout(cell)
            grid.addWidget(wrap, r, c)
        v.addWidget(g1)

        # ---------------- typography & shape
        g2 = QGroupBox("Typography, shape and form style")
        f2 = QFormLayout(g2)
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(self.theme.get("ui_font_family", "Segoe UI")))
        self.font.currentFontChanged.connect(
            lambda fnt: self._set("ui_font_family", fnt.family()))
        f2.addRow("Font family", self.font)

        self.font_size = QSpinBox()
        self.font_size.setRange(9, 20)
        self.font_size.setValue(int(float(self.theme.get("ui_font_size", 13))))
        self.font_size.valueChanged.connect(lambda v_: self._set("ui_font_size", v_))
        f2.addRow("Font size (px)", self.font_size)

        self.radius = QSpinBox()
        self.radius.setRange(0, 20)
        self.radius.setValue(int(float(self.theme.get("ui_radius", 8))))
        self.radius.valueChanged.connect(lambda v_: self._set("ui_radius", v_))
        f2.addRow("Corner radius", self.radius)

        self.density = QComboBox()
        self.density.addItems(list(theming.DENSITY))
        self.density.setCurrentText(self.theme.get("ui_density", "Comfortable"))
        self.density.currentTextChanged.connect(lambda t: self._set("ui_density", t))
        f2.addRow("Spacing / density", self.density)

        self.form_style = QComboBox()
        self.form_style.addItems(["Card", "Flat", "Outlined"])
        self.form_style.setCurrentText(self.theme.get("ui_form_style", "Card"))
        self.form_style.currentTextChanged.connect(lambda t: self._set("ui_form_style", t))
        f2.addRow("Form / card style", self.form_style)

        self.form_header_style = QComboBox()
        self.form_header_style.addItems(["Gradient", "Solid", "Underline", "Plain"])
        self.form_header_style.setCurrentText(
            self.theme.get("ui_form_header_style", "Gradient"))
        self.form_header_style.setToolTip(
            "Look of the coloured title bar on the Stock In / Stock Out / Return forms")
        self.form_header_style.currentTextChanged.connect(
            lambda t: self._set("ui_form_header_style", t))
        f2.addRow("Form banner style", self.form_header_style)

        self.row_h = QSpinBox()
        self.row_h.setRange(18, 46)
        self.row_h.setValue(int(float(self.theme.get("ui_row_height", 27))))
        self.row_h.valueChanged.connect(lambda v_: self._set("ui_row_height", v_))
        f2.addRow("Table row height", self.row_h)

        self.sidebar_w = QSpinBox()
        self.sidebar_w.setRange(180, 360)
        self.sidebar_w.setValue(int(float(self.theme.get("ui_sidebar_width", 252))))
        self.sidebar_w.valueChanged.connect(lambda v_: self._set("ui_sidebar_width", v_))
        f2.addRow("Sidebar width", self.sidebar_w)

        self.shadows = QCheckBox("Card shadows")
        self.shadows.setChecked(self.theme.get("ui_show_shadows", "1") == "1")
        self.shadows.toggled.connect(lambda b: self._set("ui_show_shadows", int(b)))
        f2.addRow(self.shadows)
        self.gridlines = QCheckBox("Table grid lines")
        self.gridlines.setChecked(self.theme.get("ui_grid_lines", "1") == "1")
        self.gridlines.toggled.connect(lambda b: self._set("ui_grid_lines", int(b)))
        f2.addRow(self.gridlines)
        self.stripes = QCheckBox("Striped table rows")
        self.stripes.setChecked(self.theme.get("ui_stripe_rows", "1") == "1")
        self.stripes.toggled.connect(lambda b: self._set("ui_stripe_rows", int(b)))
        f2.addRow(self.stripes)
        v.addWidget(g2)

        # ---------------- logo controls
        g3 = QGroupBox("Logo placement (documents, reports and application)")
        f3 = QFormLayout(g3)
        row = QHBoxLayout()
        self.logo_path = QLineEdit(db.get_setting("logo_path", ""))
        row.addWidget(self.logo_path, 1)
        row.addWidget(W.button("Browse...", slot=self._pick_logo))
        row.addWidget(W.button("Clear", slot=lambda: self.logo_path.clear()))
        rw = QWidget()
        rw.setLayout(row)
        f3.addRow("Logo file", rw)

        self.logo_pos = QComboBox()
        self.logo_pos.addItems(["Left", "Center", "Right", "None"])
        self.logo_pos.setCurrentText(db.get_setting("logo_position", "Left"))
        f3.addRow("Position in PDF header", self.logo_pos)

        self.logo_w = QDoubleSpinBox()
        self.logo_w.setRange(5, 80)
        self.logo_w.setSuffix(" mm")
        self.logo_w.setValue(float(db.get_setting("logo_width_mm", 16) or 16))
        f3.addRow("Logo width", self.logo_w)
        self.logo_h = QDoubleSpinBox()
        self.logo_h.setRange(5, 60)
        self.logo_h.setSuffix(" mm")
        self.logo_h.setValue(float(db.get_setting("logo_height_mm", 14) or 14))
        f3.addRow("Logo height", self.logo_h)

        self.logo_docs = QCheckBox("Show the logo on documents (DN, GRN, returns...)")
        self.logo_docs.setChecked(db.get_bool("logo_show_on_docs", True))
        f3.addRow(self.logo_docs)
        self.logo_reports = QCheckBox("Show the logo on reports")
        self.logo_reports.setChecked(db.get_bool("logo_show_on_reports", True))
        f3.addRow(self.logo_reports)
        self.logo_wm = QCheckBox("Faint logo watermark in the page centre")
        self.logo_wm.setChecked(db.get_bool("logo_watermark", False))
        f3.addRow(self.logo_wm)
        v.addWidget(g3)

        # ---------------- live preview
        g4 = QGroupBox("Live preview")
        pv = QVBoxLayout(g4)
        prev = QWidget()
        prev.setObjectName("Page")
        pl = QHBoxLayout(prev)
        card = W.Card("Sample card")
        card.add(QLabel("Item ITM-00001 — XLPE Power Cable"))
        b1 = W.button("Primary", "Primary")
        b2 = W.button("Accent", "Accent")
        b3 = W.button("Danger", "Danger")
        b4 = W.button("Normal")
        for b in (b1, b2, b3, b4):
            card.add(b)
        pl.addWidget(card, 1)
        t = W.DataTable()
        t.fill(["Code", "Description", "Balance", "Status"],
               [["ITM-00001", "XLPE Power Cable 3C x 25mm", 155, "Normal"],
                ["ITM-00002", "MCB 32A Triple Pole", 35, "Warning"],
                ["ITM-00003", "Gate Valve 2 inch", 12, "Critical"],
                ["ITM-00004", "Safety Helmet White", 0, "Out of Stock"]], status_col=3)
        t.setMaximumHeight(160)
        pl.addWidget(t, 2)
        pv.addWidget(prev)
        v.addWidget(g4)
        v.addStretch(1)

        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(W.button("💾  Save Appearance", "Accent", self.save))
        v.addLayout(bar)
        self.preview_table = t

    # ------------------------------------------------------------------ logic
    def _pick_logo(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select logo image", "",
                                           "Images (*.png *.jpg *.jpeg *.bmp)")
        if f:
            self.logo_path.setText(f)

    def _set(self, key: str, value):
        if self._loading:
            return
        self.theme[key] = str(value)
        self._apply_live()

    def _apply_live(self):
        app = QApplication.instance()
        W.apply_theme(app, self.theme)
        self.preview_table.fill(
            ["Code", "Description", "Balance", "Status"],
            [["ITM-00001", "XLPE Power Cable 3C x 25mm", 155, "Normal"],
             ["ITM-00002", "MCB 32A Triple Pole", 35, "Warning"],
             ["ITM-00003", "Gate Valve 2 inch", 12, "Critical"],
             ["ITM-00004", "Safety Helmet White", 0, "Out of Stock"]], status_col=3)

    def _refresh_widgets(self):
        self._loading = True
        for k, btn in self.color_buttons.items():
            btn.set_value(self.theme.get(k, "#ffffff"))
        self.font.setCurrentFont(QFont(self.theme.get("ui_font_family", "Segoe UI")))
        self.font_size.setValue(int(float(self.theme.get("ui_font_size", 13))))
        self.radius.setValue(int(float(self.theme.get("ui_radius", 8))))
        self.density.setCurrentText(self.theme.get("ui_density", "Comfortable"))
        self.form_style.setCurrentText(self.theme.get("ui_form_style", "Card"))
        self.form_header_style.setCurrentText(
            self.theme.get("ui_form_header_style", "Gradient"))
        self.row_h.setValue(int(float(self.theme.get("ui_row_height", 27))))
        self.sidebar_w.setValue(int(float(self.theme.get("ui_sidebar_width", 252))))
        self.shadows.setChecked(self.theme.get("ui_show_shadows", "1") == "1")
        self.gridlines.setChecked(self.theme.get("ui_grid_lines", "1") == "1")
        self.stripes.setChecked(self.theme.get("ui_stripe_rows", "1") == "1")
        self._loading = False

    def _apply_preset(self):
        name = self.preset.currentText()
        self.theme = dict(theming.THEME_KEYS)
        self.theme.update(theming.PRESETS.get(name, {}))
        self._refresh_widgets()
        self._apply_live()
        W.toast(self, f"Preset '{name}' applied — press Save Appearance to keep it.")

    def _reset(self):
        if not W.confirm(self, "Reset every colour and style back to the AURCO factory theme?"):
            return
        self.theme = dict(theming.THEME_KEYS)
        self._refresh_widgets()
        self._apply_live()

    def _export(self):
        f, _ = QFileDialog.getSaveFileName(
            self, "Export theme", str(config.folder("Exports") / "aurco_theme.aurcotheme"),
            "AURCO theme (*.aurcotheme *.json)")
        if not f:
            return
        theming.save_theme(self.db, self.theme)
        p = theming.export_theme(self.db, f)
        W.toast(self, f"Theme exported: {Path(p).name}")

    def _import(self):
        f, _ = QFileDialog.getOpenFileName(self, "Import theme", str(config.folder("Exports")),
                                           "AURCO theme (*.aurcotheme *.json)")
        if not f:
            return
        try:
            self.theme = theming.import_theme(self.db, f)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read that theme file.\n\n{exc}")
            return
        self._refresh_widgets()
        self._apply_live()
        self.themeApplied.emit()
        W.toast(self, "Theme imported and applied.")

    def save(self):
        theming.save_theme(self.db, self.theme)
        self.db.set_setting("ui_preset", self.preset.currentText())
        self.db.set_setting("logo_path", self.logo_path.text().strip())
        self.db.set_setting("logo_position", self.logo_pos.currentText())
        self.db.set_setting("logo_width_mm", self.logo_w.value())
        self.db.set_setting("logo_height_mm", self.logo_h.value())
        self.db.set_setting("logo_show_on_docs", int(self.logo_docs.isChecked()))
        self.db.set_setting("logo_show_on_reports", int(self.logo_reports.isChecked()))
        self.db.set_setting("logo_watermark", int(self.logo_wm.isChecked()))
        self._apply_live()
        self.themeApplied.emit()
        W.toast(self, "Appearance saved — it will look the same next time you open AURCO.")
