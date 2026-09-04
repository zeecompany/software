"""Barcode & Label Designer — customise the barcode name and its appearance.

Left  : every setting, grouped into Layout / Encoding / Text / Appearance
Right : a live PNG preview of one real label, redrawn on every change
Bottom: presets, print scope and the actual PDF generation
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from ..core import barcodes as B
from ..core import documents as D
from ..core.database import Database
from . import widgets as W

ALIGNS = ["left", "center", "right"]
VALUE_MODES = [("barcode_or_code", "Barcode, or the item code when blank"),
               ("code", "Item code"), ("barcode", "Barcode field only"),
               ("alt_code", "Alternate code"),
               ("custom", "Custom pattern (below)")]


class ColorButton(W.QPushButton if hasattr(W, "QPushButton") else object):
    pass


def _color_row(initial: str, on_change) -> tuple[QWidget, QLineEdit]:
    """A hex field plus a colour swatch/picker."""
    from PySide6.QtWidgets import QColorDialog, QPushButton
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    edit = QLineEdit(initial or "")
    edit.setPlaceholderText("#RRGGBB (blank = theme)")
    btn = QPushButton("🎨")
    btn.setFixedWidth(34)
    btn.setCursor(Qt.PointingHandCursor)

    def pick():
        c = QColorDialog.getColor()
        if c.isValid():
            edit.setText(c.name())

    btn.clicked.connect(pick)
    edit.textChanged.connect(lambda *_: on_change())
    h.addWidget(edit, 1)
    h.addWidget(btn)
    return box, edit


class BarcodeDesigner(QDialog):
    def __init__(self, db: Database, items: list[dict], parent=None):
        super().__init__(parent)
        self.db = db
        self.items = items or []
        self.design = B.get_design(db)
        self.out_file: Path | None = None
        self.setWindowTitle("Barcode & Label Designer")
        self.setModal(True)
        self.resize(1180, 800)

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        root.addLayout(top, 1)

        # ------------------------------------------------------------ left
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setMinimumWidth(560)
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setSpacing(10)
        scroll.setWidget(panel)
        top.addWidget(scroll, 3)

        self._w: dict[str, object] = {}
        d = self.design

        # ---- layout
        g = QGroupBox("Label sheet")
        f = QFormLayout(g)
        self.cb_template = W.combo(list(B.TEMPLATES), current=d.get("template", ""))
        self.cb_template.currentTextChanged.connect(self._template_changed)
        f.addRow("Template", self.cb_template)
        for key, label, lo, hi, step in (("label_w", "Label width (mm)", 10, 300, 0.5),
                                         ("label_h", "Label height (mm)", 8, 300, 0.5),
                                         ("margin_x", "Left margin (mm)", 0, 60, 0.5),
                                         ("margin_y", "Top margin (mm)", 0, 90, 0.5),
                                         ("gap_x", "Column gap (mm)", 0, 30, 0.5),
                                         ("gap_y", "Row gap (mm)", 0, 30, 0.5)):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setDecimals(1)
            sp.setValue(float(d.get(key, 0) or 0))
            sp.valueChanged.connect(self._changed)
            f.addRow(label, sp)
            self._w[key] = sp
        for key, label, lo, hi in (("cols", "Columns per page", 1, 12),
                                   ("rows", "Rows per page", 1, 26),
                                   ("copies", "Copies of each item", 1, 99),
                                   ("start_position", "Start at label #", 1, 200)):
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(int(d.get(key, 1) or 1))
            sp.valueChanged.connect(self._changed)
            f.addRow(label, sp)
            self._w[key] = sp
        pv.addWidget(g)

        # ---- encoding
        g2 = QGroupBox("Barcode")
        f2 = QFormLayout(g2)
        self.cb_sym = W.combo(B.SYMBOLOGIES, current=d.get("symbology", "Code128"))
        self.cb_sym.currentTextChanged.connect(self._changed)
        f2.addRow("Symbology", self.cb_sym)
        self.cb_value = QComboBox()
        for k, lbl in VALUE_MODES:
            self.cb_value.addItem(lbl, k)
        i = self.cb_value.findData(d.get("value_field", "barcode_or_code"))
        self.cb_value.setCurrentIndex(max(0, i))
        self.cb_value.currentIndexChanged.connect(self._changed)
        f2.addRow("Encode", self.cb_value)
        self.ed_value = QLineEdit(d.get("value_custom", "{code}"))
        self.ed_value.textChanged.connect(self._changed)
        f2.addRow("Custom pattern", self.ed_value)
        for key, label, lo, hi, step in (("bar_height", "Bar height (mm)", 3, 40, 0.5),
                                         ("bar_width", "Bar width (mm)", 0.15, 1.2, 0.02),
                                         ("qr_size", "QR size (mm)", 6, 60, 0.5)):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setDecimals(2)
            sp.setValue(float(d.get(key, 0) or 0))
            sp.valueChanged.connect(self._changed)
            f2.addRow(label, sp)
            self._w[key] = sp
        self.chk_hr = QCheckBox("Print the number under the bars")
        self.chk_hr.setChecked(bool(d.get("human_readable", True)))
        self.chk_hr.toggled.connect(self._changed)
        f2.addRow("", self.chk_hr)
        pv.addWidget(g2)

        # ---- text / the "barcode name"
        g3 = QGroupBox("Label text  —  use {code} {description} {category} {uom} "
                       "{brand} {warehouse} {location} {rack} {balance} {company} {date}")
        f3 = QFormLayout(g3)
        for prefix, label, default_font in (("title", "Title line", "Helvetica-Bold"),
                                            ("subtitle", "Second line", "Helvetica"),
                                            ("footer", "Bottom line", "Helvetica")):
            chk = QCheckBox("show")
            chk.setChecked(bool(d.get(f"show_{prefix}", True)))
            chk.toggled.connect(self._changed)
            ed = QLineEdit(str(d.get(prefix, "")))
            ed.textChanged.connect(self._changed)
            font = W.combo(B.FONTS, current=str(d.get(f"{prefix}_font", default_font)))
            font.currentTextChanged.connect(self._changed)
            size = QDoubleSpinBox()
            size.setRange(3.0, 30.0)
            size.setSingleStep(0.2)
            size.setValue(float(d.get(f"{prefix}_size", 7) or 7))
            size.valueChanged.connect(self._changed)
            align = W.combo(ALIGNS, current=str(d.get(f"{prefix}_align", "center")))
            align.currentTextChanged.connect(self._changed)
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0)
            rh.setSpacing(4)
            rh.addWidget(chk)
            rh.addWidget(ed, 3)
            rh.addWidget(font, 2)
            rh.addWidget(size)
            rh.addWidget(align)
            f3.addRow(label, row)
            self._w[f"show_{prefix}"] = chk
            self._w[prefix] = ed
            self._w[f"{prefix}_font"] = font
            self._w[f"{prefix}_size"] = size
            self._w[f"{prefix}_align"] = align
        self.chk_price = QCheckBox("Print the unit price")
        self.chk_price.setChecked(bool(d.get("show_price", False)))
        self.chk_price.toggled.connect(self._changed)
        self.ed_price_pre = QLineEdit(str(d.get("price_prefix", "")))
        self.ed_price_pre.setPlaceholderText("prefix, e.g. 'Price: '")
        self.ed_price_pre.textChanged.connect(self._changed)
        prow = QWidget()
        ph = QHBoxLayout(prow)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.addWidget(self.chk_price)
        ph.addWidget(self.ed_price_pre, 1)
        f3.addRow("Price line", prow)
        pv.addWidget(g3)

        # ---- appearance
        g4 = QGroupBox("Appearance")
        f4 = QFormLayout(g4)
        for key, label, default in (("bar_color", "Bar colour", "#000000"),
                                    ("text_color", "Text colour", "#101418"),
                                    ("bg_color", "Background", "#ffffff"),
                                    ("accent_color", "Accent stripe", ""),
                                    ("border_color", "Border colour", "#9aa8b6")):
            box, edit = _color_row(str(d.get(key, default) or ""), self._changed)
            f4.addRow(label, box)
            self._w[key] = edit
        self.chk_border = QCheckBox("Draw a border around each label")
        self.chk_border.setChecked(bool(d.get("border", True)))
        self.chk_border.toggled.connect(self._changed)
        f4.addRow("", self.chk_border)
        self.chk_accent = QCheckBox("Brand stripe along the top edge")
        self.chk_accent.setChecked(bool(d.get("accent_bar", True)))
        self.chk_accent.toggled.connect(self._changed)
        f4.addRow("", self.chk_accent)
        self.chk_logo = QCheckBox("Print the company logo on every label")
        self.chk_logo.setChecked(bool(d.get("show_logo", False)))
        self.chk_logo.toggled.connect(self._changed)
        f4.addRow("", self.chk_logo)
        self.chk_crop = QCheckBox("Cutting guides between labels")
        self.chk_crop.setChecked(bool(d.get("crop_marks", False)))
        self.chk_crop.toggled.connect(self._changed)
        f4.addRow("", self.chk_crop)
        for key, label, lo, hi, step in (("corner_radius", "Corner radius (mm)", 0, 8, 0.2),
                                         ("border_width", "Border width (pt)", 0.1, 3, 0.1),
                                         ("logo_height", "Logo height (mm)", 2, 20, 0.5)):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setDecimals(2)
            sp.setValue(float(d.get(key, 0) or 0))
            sp.valueChanged.connect(self._changed)
            f4.addRow(label, sp)
            self._w[key] = sp
        pv.addWidget(g4)
        pv.addStretch(1)

        # ----------------------------------------------------------- right
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setSpacing(8)
        top.addWidget(right, 2)

        prev = W.Card("Live preview")
        self.preview = QLabel("…")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(260)
        self.preview.setStyleSheet(
            "background:#f2f5f8; border:1px solid #d8e1ea; border-radius:6px;")
        prev.add(self.preview, 1)
        self.cb_item = QComboBox()
        for it in self.items[:400]:
            self.cb_item.addItem(f"{it.get('code','')} — {it.get('description','')}"[:70])
        self.cb_item.currentIndexChanged.connect(self._changed)
        prev.add(QLabel("Preview this item:"))
        prev.add(self.cb_item)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        prev.add(self.caption)
        rv.addWidget(prev, 1)

        pres = W.Card("Saved designs")
        self.cb_preset = QComboBox()
        self._reload_presets()
        pres.add(self.cb_preset)
        prow = QWidget()
        ph2 = QHBoxLayout(prow)
        ph2.setContentsMargins(0, 0, 0, 0)
        ph2.setSpacing(5)
        ph2.addWidget(W.button("📂  Load", slot=self._load_preset))
        ph2.addWidget(W.button("💾  Save as...", slot=self._save_preset))
        ph2.addWidget(W.button("🗑  Delete", slot=self._delete_preset))
        ph2.addWidget(W.button("↺  Reset", slot=self._reset))
        pres.add(prow)
        rv.addWidget(pres)

        scope = W.Card("What to print")
        self.cb_scope = W.combo([f"All {len(self.items)} listed item(s)",
                                 "Only the selected item"])
        scope.add(self.cb_scope)
        self.lbl_count = QLabel()
        self.lbl_count.setStyleSheet(f"color:{W.MUTED};")
        scope.add(self.lbl_count)
        rv.addWidget(scope)

        bb = QDialogButtonBox()
        bb.addButton("🏷  Generate Labels PDF", QDialogButtonBox.AcceptRole
                     ).clicked.connect(self._generate)
        bb.addButton("Close", QDialogButtonBox.RejectRole).clicked.connect(self.reject)
        root.addWidget(bb)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render)
        self._render()

    # ------------------------------------------------------------- helpers
    def _template_changed(self, name: str):
        self.design = B.apply_template(self._collect(), name)
        for key in ("label_w", "label_h", "margin_x", "margin_y", "gap_x", "gap_y",
                    "cols", "rows"):
            wd = self._w.get(key)
            if wd is not None:
                wd.blockSignals(True)
                wd.setValue(type(wd.value())(self.design.get(key, wd.value())))
                wd.blockSignals(False)
        self._changed()

    def _changed(self, *_):
        self._timer.start(160)

    def _collect(self) -> dict:
        d = dict(self.design)
        d["template"] = self.cb_template.currentText()
        d["symbology"] = self.cb_sym.currentText()
        d["value_field"] = self.cb_value.currentData()
        d["value_custom"] = self.ed_value.text()
        d["human_readable"] = self.chk_hr.isChecked()
        d["show_price"] = self.chk_price.isChecked()
        d["price_prefix"] = self.ed_price_pre.text()
        d["border"] = self.chk_border.isChecked()
        d["accent_bar"] = self.chk_accent.isChecked()
        d["show_logo"] = self.chk_logo.isChecked()
        d["crop_marks"] = self.chk_crop.isChecked()
        for key, wd in self._w.items():
            if isinstance(wd, QCheckBox):
                d[key] = wd.isChecked()
            elif isinstance(wd, (QSpinBox, QDoubleSpinBox)):
                d[key] = wd.value()
            elif isinstance(wd, QComboBox):
                d[key] = wd.currentText()
            elif isinstance(wd, QLineEdit):
                d[key] = wd.text()
        return d

    def _current_item(self) -> dict:
        i = self.cb_item.currentIndex()
        if 0 <= i < len(self.items):
            return self.items[i]
        return {"code": "ITM-00001", "description": "Sample item", "uom": "PCS",
                "barcode": "6291000000017", "warehouse": "Main Store",
                "location": "A-01", "unit_cost": 100.0, "balance": 25}

    def _render(self):
        self.design = self._collect()
        item = self._current_item()
        tmp = Path(tempfile.gettempdir()) / "aurco_label_preview.png"
        try:
            p = B.preview_png(self.db, self.design, item, tmp, scale=5.0)
            pix = QPixmap(str(p))
            if not pix.isNull():
                self.preview.setPixmap(pix.scaled(
                    self.preview.width() - 12, self.preview.height() - 12,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.preview.setText("Preview unavailable — the PDF will still print.")
        except Exception as exc:  # noqa: BLE001
            self.preview.setText(f"Preview failed: {exc}")
        cap = B.caption_preview(self.db, self.design, item)
        self.caption.setText(
            f"<b>Encoded:</b> {cap['value'] or '(empty)'}<br>"
            f"<b>Title:</b> {cap['title']}<br><b>Second:</b> {cap['subtitle']}<br>"
            f"<b>Bottom:</b> {cap['footer']}")
        per = max(1, int(self.design.get("cols", 3)) * int(self.design.get("rows", 8)))
        n = len(self.items) * max(1, int(self.design.get("copies", 1)))
        self.lbl_count.setText(f"{per} label(s) per page  ·  about "
                               f"{-(-n // per)} page(s) for {n} label(s)")

    # ------------------------------------------------------------- presets
    def _reload_presets(self):
        self.cb_preset.clear()
        names = sorted(B.list_presets(self.db))
        self.cb_preset.addItems(names or ["(no saved designs yet)"])

    def _load_preset(self):
        name = self.cb_preset.currentText()
        p = B.list_presets(self.db).get(name)
        if not p:
            W.error_box(self, "Select a saved design first.")
            return
        self.design = dict(B.DEFAULT_DESIGN, **p)
        self._apply_to_widgets()
        W.toast(self, f"Loaded design '{name}'.")

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save design", "Name for this design:")
        if not ok or not name.strip():
            return
        B.save_preset(self.db, name.strip(), self._collect())
        self._reload_presets()
        self.cb_preset.setCurrentText(name.strip())
        W.toast(self, f"Design '{name.strip()}' saved.")

    def _delete_preset(self):
        name = self.cb_preset.currentText()
        if name and W.confirm(self, f"Delete the saved design '{name}'?"):
            B.delete_preset(self.db, name)
            self._reload_presets()

    def _reset(self):
        self.design = dict(B.DEFAULT_DESIGN)
        self._apply_to_widgets()

    def _apply_to_widgets(self):
        d = self.design
        for wd, val in ((self.cb_template, d.get("template")),
                        (self.cb_sym, d.get("symbology"))):
            wd.blockSignals(True)
            wd.setCurrentText(str(val))
            wd.blockSignals(False)
        i = self.cb_value.findData(d.get("value_field", "barcode_or_code"))
        self.cb_value.blockSignals(True)
        self.cb_value.setCurrentIndex(max(0, i))
        self.cb_value.blockSignals(False)
        for wd, val in ((self.ed_value, d.get("value_custom", "")),
                        (self.ed_price_pre, d.get("price_prefix", ""))):
            wd.blockSignals(True)
            wd.setText(str(val))
            wd.blockSignals(False)
        for chk, key in ((self.chk_hr, "human_readable"), (self.chk_price, "show_price"),
                         (self.chk_border, "border"), (self.chk_accent, "accent_bar"),
                         (self.chk_logo, "show_logo"), (self.chk_crop, "crop_marks")):
            chk.blockSignals(True)
            chk.setChecked(bool(d.get(key)))
            chk.blockSignals(False)
        for key, wd in self._w.items():
            v = d.get(key)
            if v is None:
                continue
            wd.blockSignals(True)
            if isinstance(wd, QCheckBox):
                wd.setChecked(bool(v))
            elif isinstance(wd, QSpinBox):
                wd.setValue(int(float(v)))
            elif isinstance(wd, QDoubleSpinBox):
                wd.setValue(float(v))
            elif isinstance(wd, QComboBox):
                wd.setCurrentText(str(v))
            elif isinstance(wd, QLineEdit):
                wd.setText(str(v))
            wd.blockSignals(False)
        self._render()

    # ------------------------------------------------------------ generate
    def _generate(self):
        design = self._collect()
        B.save_design(self.db, design)
        items = (self.items if self.cb_scope.currentIndex() == 0
                 else [self._current_item()])
        if not items:
            W.error_box(self, "There are no items to print.")
            return
        try:
            f = B.label_pdf(self.db, items[:2000], design)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not build the label sheet.\n\n{exc}")
            return
        self.out_file = f
        W.toast(self, f"Label sheet created: {f.name}")
        D.open_path(f)
