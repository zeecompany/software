"""Visual Header / Footer designer with a live preview."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import config, documents as D, header_design as HD
from ..core.database import Database
from . import widgets as W


class Swatch(QPushButton):
    changed = Signal(str)

    def __init__(self, value: str = "#ffffff", parent=None):
        super().__init__(parent)
        self.setFixedSize(78, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self.set_value(value)

    def set_value(self, v: str):
        self._v = v or "#ffffff"
        c = QColor(self._v)
        fg = "#ffffff" if c.lightness() < 140 else "#101418"
        self.setStyleSheet(f"background:{self._v}; color:{fg}; border:1px solid #888;"
                           f"border-radius:4px; font-size:10px; font-weight:600;")
        self.setText(self._v.upper())

    def value(self) -> str:
        return self._v

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._v), self, "Choose colour")
        if c.isValid():
            self.set_value(c.name())
            self.changed.emit(c.name())


class HeaderDesignerTab(QWidget):
    """Design the printed header and footer element by element."""

    COLS = ["Show", "Content", "Text / template", "Position", "Row", "Size", "B", "I", "Colour"]

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.kind = "header"
        self.doc_type = "__default__"
        self.design = HD.get_design(db, "header", "__default__")
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 8, 8, 0)
        bar.addWidget(QLabel("Design:"))
        self.kind_cb = W.combo(["Header", "Footer"])
        self.kind_cb.currentTextChanged.connect(self._switch)
        bar.addWidget(self.kind_cb)
        bar.addWidget(QLabel("for:"))
        self.doc_cb = QComboBox()
        self.doc_cb.addItem("All documents (default)", "__default__")
        for code, name in D.DOC_TITLES.items():
            self.doc_cb.addItem(f"{name} ({code})", code)
        self.doc_cb.currentIndexChanged.connect(self._switch)
        bar.addWidget(self.doc_cb)
        bar.addWidget(QLabel("Preset:"))
        self.preset_cb = W.combo(["—"] + list(HD.PRESETS))
        bar.addWidget(self.preset_cb)
        bar.addWidget(W.button("Apply preset", slot=self._apply_preset))
        bar.addStretch(1)
        bar.addWidget(W.button("⬇ Export", slot=self._export))
        bar.addWidget(W.button("⬆ Import", slot=self._import))
        bar.addWidget(W.button("↺ Reset", slot=self._reset))
        root.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # ---------------- left: settings
        left = QScrollArea()
        left.setWidgetResizable(True)
        left.setFrameShape(QScrollArea.NoFrame)
        lw = QWidget()
        left.setWidget(lw)
        lv = QVBoxLayout(lw)

        g1 = QGroupBox("Band")
        f1 = QFormLayout(g1)
        self.height = QDoubleSpinBox()
        self.height.setRange(8, 60)
        self.height.setSuffix(" mm")
        f1.addRow("Height", self.height)
        self.bg_style = W.combo(["Gradient", "Solid", "None"])
        f1.addRow("Background", self.bg_style)
        self.bg1 = Swatch()
        f1.addRow("Colour (start)", self.bg1)
        self.bg2 = Swatch()
        f1.addRow("Colour (end)", self.bg2)
        self.bg_angle = W.combo(["Horizontal", "Vertical"])
        f1.addRow("Gradient direction", self.bg_angle)
        self.padding = QDoubleSpinBox()
        self.padding.setRange(4, 40)
        self.padding.setSuffix(" mm")
        f1.addRow("Side padding", self.padding)
        self.row_gap = QDoubleSpinBox()
        self.row_gap.setRange(0, 8)
        self.row_gap.setSingleStep(0.5)
        self.row_gap.setSuffix(" mm")
        f1.addRow("Gap between rows", self.row_gap)
        lv.addWidget(g1)

        g2 = QGroupBox("Accent bar && border")
        f2 = QFormLayout(g2)
        self.accent_bar = QCheckBox("Show the accent bar")
        f2.addRow(self.accent_bar)
        self.accent_color = Swatch("#f5a300")
        f2.addRow("Accent colour", self.accent_color)
        self.accent_h = QDoubleSpinBox()
        self.accent_h.setRange(0.2, 6)
        self.accent_h.setSingleStep(0.1)
        self.accent_h.setSuffix(" mm")
        f2.addRow("Accent thickness", self.accent_h)
        self.bottom_border = QCheckBox("Show a thin rule at the band edge")
        f2.addRow(self.bottom_border)
        self.border_color = Swatch("#c1121f")
        f2.addRow("Rule colour", self.border_color)
        lv.addWidget(g2)

        g3 = QGroupBox("Logo")
        f3 = QFormLayout(g3)
        self.logo_show = QCheckBox("Show the logo in this band")
        f3.addRow(self.logo_show)
        self.logo_slot = W.combo(HD.SLOTS)
        f3.addRow("Position", self.logo_slot)
        self.logo_w = QDoubleSpinBox()
        self.logo_w.setRange(5, 90)
        self.logo_w.setSuffix(" mm")
        f3.addRow("Width", self.logo_w)
        self.logo_h = QDoubleSpinBox()
        self.logo_h.setRange(3, 40)
        self.logo_h.setSuffix(" mm")
        f3.addRow("Height", self.logo_h)
        self.logo_backing = W.combo(["Auto", "White", "Dark", "None"])
        f3.addRow("Backing plate", self.logo_backing)
        row = QHBoxLayout()
        self.logo_path = QLineEdit(db.get_setting("logo_path", ""))
        row.addWidget(self.logo_path, 1)
        row.addWidget(W.button("Browse...", slot=self._pick_logo))
        wrap = QWidget()
        wrap.setLayout(row)
        f3.addRow("Logo file", wrap)
        lv.addWidget(g3)
        lv.addStretch(1)
        left.setMinimumWidth(340)
        split.addWidget(left)

        # ---------------- right: elements + preview
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 6, 6, 6)
        hint = QLabel(
            "Each line below is one piece of text in the band. Set what it shows, where it "
            "sits (left / centre / right), which row, its size, style and colour.<br>"
            f"Custom text may use placeholders: <code>{HD.PLACEHOLDER_HELP}</code>")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{W.MUTED};")
        rv.addWidget(hint)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        for i, w_ in enumerate([46, 170, None, 92, 52, 62, 30, 30, 86]):
            if w_ is None:
                hh.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hh.setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, w_)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setMinimumHeight(190)
        rv.addWidget(self.table, 1)

        brow = QHBoxLayout()
        brow.addWidget(W.button("＋ Add line", "Primary", self._add))
        brow.addWidget(W.button("✖ Remove", slot=self._remove))
        brow.addWidget(W.button("▲", slot=lambda: self._move(-1), tip="Move up"))
        brow.addWidget(W.button("▼", slot=lambda: self._move(1), tip="Move down"))
        brow.addStretch(1)
        brow.addWidget(W.button("🔄 Refresh preview", slot=self.refresh_preview))
        brow.addWidget(W.button("👁 Open sample PDF", slot=self._open_pdf))
        brow.addWidget(W.button("💾  Save Design", "Accent", self.save))
        rv.addLayout(brow)

        pv = QGroupBox("Live preview")
        pvl = QVBoxLayout(pv)
        self.preview = QLabel("Preview appears here")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(150)
        self.preview.setStyleSheet(f"background:#ffffff; border:1px solid {W.BORDER};"
                                   "border-radius:6px;")
        pvl.addWidget(self.preview)
        rv.addWidget(pv)
        split.addWidget(right)
        split.setSizes([340, 1000])

        for wdg in (self.height, self.padding, self.row_gap, self.accent_h,
                    self.logo_w, self.logo_h):
            wdg.valueChanged.connect(self._touch)
        for wdg in (self.bg_style, self.bg_angle, self.logo_slot, self.logo_backing):
            wdg.currentTextChanged.connect(self._touch)
        for wdg in (self.accent_bar, self.bottom_border, self.logo_show):
            wdg.toggled.connect(self._touch)
        for sw in (self.bg1, self.bg2, self.accent_color, self.border_color):
            sw.changed.connect(lambda *_: self._touch())
        self.table.itemChanged.connect(lambda *_: self._touch())
        self._load()

    # ------------------------------------------------------------- loading
    def _switch(self):
        self.kind = self.kind_cb.currentText().lower()
        self.doc_type = self.doc_cb.currentData() or "__default__"
        self.design = HD.get_design(self.db, self.kind, self.doc_type)
        self._load()

    def _load(self):
        self._loading = True
        d = self.design
        self.height.setValue(float(d.get("height", 24)))
        self.bg_style.setCurrentText(d.get("bg_style", "Gradient"))
        self.bg1.set_value(d.get("bg_color1", "#12161c"))
        self.bg2.set_value(d.get("bg_color2", "#c1121f"))
        self.bg_angle.setCurrentText(d.get("bg_angle", "Horizontal"))
        self.padding.setValue(float(d.get("padding", 12)))
        self.row_gap.setValue(float(d.get("row_gap", 1.0)))
        self.accent_bar.setChecked(bool(d.get("accent_bar", True)))
        self.accent_color.set_value(d.get("accent_color", "#f5a300"))
        self.accent_h.setValue(float(d.get("accent_height", 1.5)))
        self.bottom_border.setChecked(bool(d.get("bottom_border", False)))
        self.border_color.set_value(d.get("border_color", "#c1121f"))
        self.logo_show.setChecked(bool(d.get("logo_show", True)))
        self.logo_slot.setCurrentText(d.get("logo_slot", "Left"))
        self.logo_w.setValue(float(d.get("logo_width", 34)))
        self.logo_h.setValue(float(d.get("logo_height", 9)))
        self.logo_backing.setCurrentText(d.get("logo_backing", "Auto"))

        self.table.setRowCount(0)
        for el in d.get("elements", []):
            self._add_row(el)
        self._loading = False
        self.refresh_preview()

    def _add_row(self, el: dict):
        r = self.table.rowCount()
        self.table.insertRow(r)

        chk = QCheckBox()
        chk.setChecked(bool(el.get("visible", True)))
        chk.toggled.connect(self._touch)
        cw = QWidget()
        cl = QHBoxLayout(cw)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setAlignment(Qt.AlignCenter)
        cl.addWidget(chk)
        self.table.setCellWidget(r, 0, cw)

        src = QComboBox()
        for key, label in HD.SOURCES.items():
            src.addItem(label, key)
        i = src.findData(el.get("source", "custom"))
        src.setCurrentIndex(max(0, i))
        src.currentIndexChanged.connect(self._touch)
        self.table.setCellWidget(r, 1, src)

        self.table.setItem(r, 2, QTableWidgetItem(el.get("text", "")))

        slot = QComboBox()
        slot.addItems(HD.SLOTS)
        slot.setCurrentText(el.get("slot", "Left"))
        slot.currentTextChanged.connect(self._touch)
        self.table.setCellWidget(r, 3, slot)

        row = QSpinBox()
        row.setRange(0, 5)
        row.setValue(int(el.get("row", 0)))
        row.valueChanged.connect(self._touch)
        self.table.setCellWidget(r, 4, row)

        size = QDoubleSpinBox()
        size.setRange(5, 30)
        size.setSingleStep(0.5)
        size.setValue(float(el.get("size", 10)))
        size.valueChanged.connect(self._touch)
        self.table.setCellWidget(r, 5, size)

        for col, key in ((6, "bold"), (7, "italic")):
            c = QCheckBox()
            c.setChecked(bool(el.get(key)))
            c.toggled.connect(self._touch)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setAlignment(Qt.AlignCenter)
            hl.addWidget(c)
            self.table.setCellWidget(r, col, holder)

        sw = Swatch(el.get("color", "#ffffff"))
        sw.changed.connect(lambda *_: self._touch())
        self.table.setCellWidget(r, 8, sw)

    def _row_widget(self, r: int, c: int):
        w_ = self.table.cellWidget(r, c)
        if isinstance(w_, (QComboBox, QSpinBox, QDoubleSpinBox, Swatch)):
            return w_
        return w_.findChild(QCheckBox) if w_ else None

    def collect(self) -> dict:
        d = dict(self.design)
        d.update({
            "height": self.height.value(), "bg_style": self.bg_style.currentText(),
            "bg_color1": self.bg1.value(), "bg_color2": self.bg2.value(),
            "bg_angle": self.bg_angle.currentText(), "padding": self.padding.value(),
            "row_gap": self.row_gap.value(), "accent_bar": self.accent_bar.isChecked(),
            "accent_color": self.accent_color.value(),
            "accent_height": self.accent_h.value(),
            "bottom_border": self.bottom_border.isChecked(),
            "border_color": self.border_color.value(),
            "logo_show": self.logo_show.isChecked(),
            "logo_slot": self.logo_slot.currentText(),
            "logo_width": self.logo_w.value(), "logo_height": self.logo_h.value(),
            "logo_backing": self.logo_backing.currentText(),
        })
        els = []
        for r in range(self.table.rowCount()):
            txt = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
            els.append({
                "visible": self._row_widget(r, 0).isChecked(),
                "source": self._row_widget(r, 1).currentData(),
                "text": txt,
                "slot": self._row_widget(r, 3).currentText(),
                "row": self._row_widget(r, 4).value(),
                "size": self._row_widget(r, 5).value(),
                "bold": self._row_widget(r, 6).isChecked(),
                "italic": self._row_widget(r, 7).isChecked(),
                "color": self._row_widget(r, 8).value(),
            })
        d["elements"] = els
        return d

    # ------------------------------------------------------------ actions
    def _touch(self, *_):
        if not self._loading:
            self.refresh_preview()

    def _add(self):
        self._add_row(HD.element("custom", "New line", "Left", 0, 9, False, False,
                                 "#ffffff" if self.kind == "header" else "#6b7c8f"))
        self._touch()

    def _remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._touch()

    def _move(self, delta: int):
        r = self.table.currentRow()
        n = self.table.rowCount()
        if r < 0 or not (0 <= r + delta < n):
            return
        d = self.collect()
        els = d["elements"]
        els[r], els[r + delta] = els[r + delta], els[r]
        self.design = d
        self._load()
        self.table.selectRow(r + delta)

    def _apply_preset(self):
        name = self.preset_cb.currentText()
        if name not in HD.PRESETS:
            W.error_box(self, "Choose a preset first.")
            return
        import copy
        self.design = copy.deepcopy(HD.PRESETS[name])
        if self.kind == "footer":
            base = HD.default_footer()
            base.update({k: self.design[k] for k in
                         ("bg_color1", "bg_color2", "accent_color") if k in self.design})
            self.design = base
        self._load()
        W.toast(self, f"Preset '{name}' applied — press Save Design to keep it.")

    def _pick_logo(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select logo", "",
                                           "Images (*.png *.jpg *.jpeg *.bmp)")
        if f:
            self.logo_path.setText(f)
            self.db.set_setting("logo_path", f)
            self._touch()

    def save(self):
        self.design = self.collect()
        self.db.set_setting("logo_path", self.logo_path.text().strip())
        HD.save_design(self.db, self.design, self.kind, self.doc_type)
        W.toast(self, f"{self.kind.title()} design saved for "
                      f"{self.doc_cb.currentText()}.")
        self.refresh_preview()

    def _reset(self):
        if not W.confirm(self, f"Reset this {self.kind} design back to the factory layout?"):
            return
        HD.reset_design(self.db, self.kind, self.doc_type)
        self.design = HD.get_design(self.db, self.kind, self.doc_type)
        self._load()

    def _export(self):
        f, _ = QFileDialog.getSaveFileName(
            self, "Export design",
            str(config.folder("Exports") / f"aurco_{self.kind}.json"), "JSON (*.json)")
        if f:
            Path(f).write_text(HD.export_design(self.collect()), encoding="utf-8")
            W.toast(self, f"Saved {Path(f).name}")

    def _import(self):
        f, _ = QFileDialog.getOpenFileName(self, "Import design",
                                           str(config.folder("Exports")), "JSON (*.json)")
        if not f:
            return
        try:
            self.design = HD.import_design(Path(f).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read that design file.\n\n{exc}")
            return
        self._load()
        W.toast(self, "Design imported — press Save Design to keep it.")

    # ------------------------------------------------------------ preview
    def refresh_preview(self):
        """Render the band exactly as the PDF engine would, then show it."""
        try:
            from reportlab.pdfgen import canvas as _canvas
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm as _mm
            import io

            design = self.collect()
            buf = io.BytesIO()
            band_h = float(design.get("height", 24)) * _mm + 6 * _mm
            c = _canvas.Canvas(buf, pagesize=(A4[0], band_h))

            class _D:  # minimal stand-in for the platypus doc object
                pagesize = (A4[0], band_h)
                page = 1

            ctx = HD.context(self.db, "Delivery Note", None,
                             {"docno": "DN-2026-00001", "date": "18-08-2026",
                              "project": "Jubail Refinery Project",
                              "warehouse": "Main Warehouse",
                              "footer_note": self.db.get_setting("doc_footer", "")})
            ctx["page"], ctx["pages"] = "1", "2"
            D._render_band(c, _D(), self.db, design, ctx,
                           is_footer=(self.kind == "footer"),
                           logo=self.logo_path.text().strip())
            c.showPage()
            c.save()
            buf.seek(0)
            import pypdfium2 as pdfium
            pg = pdfium.PdfDocument(buf.read())[0]
            img = pg.render(scale=2).to_pil()
            data = io.BytesIO()
            img.save(data, format="PNG")
            pm = QPixmap()
            pm.loadFromData(data.getvalue())
            target = max(400, self.preview.width() - 16)
            scaled = pm.scaledToWidth(target, Qt.SmoothTransformation)
            if scaled.height() > self.preview.height() - 8:
                scaled = pm.scaledToHeight(max(80, self.preview.height() - 12),
                                           Qt.SmoothTransformation)
            self.preview.setPixmap(scaled)
        except Exception as exc:  # noqa: BLE001
            self.preview.setText(f"Preview unavailable: {exc}")

    def _open_pdf(self):
        self.save()
        dt = self.doc_type if self.doc_type != "__default__" else "DN"
        row = self.db.one("SELECT id FROM documents WHERE doc_type=? ORDER BY id DESC LIMIT 1",
                          (dt,))
        if not row:
            W.error_box(self, f"No {dt} document exists yet to preview.")
            return
        try:
            f = D.document_pdf(self.db, row["id"],
                               out_path=config.folder("Reports") / f"_hdr_preview_{dt}.pdf")
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not build the preview.\n\n{exc}")
            return
        D.open_path(f)
