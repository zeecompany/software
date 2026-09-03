"""Item Master: searchable grid, full item editor, Excel import wizard, barcodes."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressDialog,
                               QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..core import config, documents as D, importer, reports
from ..core import services as S
from ..core.database import Database
from . import widgets as W
from .auth_dialogs import AdminAuthDialog
from .common import ItemPicker, ShareBar, lookup


class ItemDialog(QDialog):
    def __init__(self, db: Database, item_id: int | None = None, parent=None):
        super().__init__(parent)
        self.db = db
        self.item_id = item_id
        self.row = dict(db.one("SELECT * FROM items WHERE id=?", (item_id,))) if item_id else {}
        self.setWindowTitle(f"Edit Item — {self.row.get('code')}" if item_id else "New Item")
        self.resize(880, 660)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        # ---- general
        g = QWidget()
        form = QFormLayout(g)
        form.setLabelAlignment(Qt.AlignRight)
        self.code = QLineEdit(self.row.get("code", ""))
        self.auto = QCheckBox("Auto-generate")
        self.auto.setChecked(not item_id)
        self.auto.toggled.connect(lambda b: (self.code.setDisabled(b),
                                             self.code.setText(db.next_item_code() if b else "")))
        if not item_id:
            self.code.setText(db.next_item_code())
            self.code.setDisabled(True)
        hc = QHBoxLayout()
        hc.addWidget(self.code, 1)
        hc.addWidget(self.auto)
        w = QWidget()
        w.setLayout(hc)
        form.addRow("Item Code *", w)
        self.desc = QLineEdit(self.row.get("description", ""))
        form.addRow("Description *", self.desc)
        self.short = QLineEdit(self.row.get("short_desc", ""))
        form.addRow("Short Description", self.short)
        self.cat = W.combo([""] + lookup(db, "categories"), True, self.row.get("category", ""))
        form.addRow("Category", self.cat)
        self.subcat = QLineEdit(self.row.get("subcategory", ""))
        form.addRow("Subcategory", self.subcat)
        self.uom = W.combo(lookup(db, "uoms") or ["PCS"], True,
                           self.row.get("uom") or db.get_setting("default_uom", "PCS"))
        form.addRow("UOM", self.uom)
        self.brand = QLineEdit(self.row.get("brand", ""))
        form.addRow("Brand / Manufacturer", self.brand)
        self.model = QLineEdit(self.row.get("model", ""))
        form.addRow("Model / Part Number", self.model)
        self.spec = QPlainTextEdit(self.row.get("specification", ""))
        self.spec.setMaximumHeight(60)
        form.addRow("Specification", self.spec)
        self.barcode = QLineEdit(self.row.get("barcode", ""))
        self.barcode.setPlaceholderText("Scan with USB scanner or type")
        form.addRow("Barcode", self.barcode)
        self.altcode = QLineEdit(self.row.get("alt_code", ""))
        form.addRow("Alternate Code", self.altcode)
        self.active = QCheckBox("Item is active")
        self.active.setChecked(bool(self.row.get("active", 1)))
        form.addRow("Status", self.active)
        tabs.addTab(g, "General")

        # ---- stock & alerts
        s = QWidget()
        sv = QVBoxLayout(s)
        box1 = QGroupBox("Stock levels")
        f1 = QFormLayout(box1)

        def spin(key, val=None, mx=1e9):
            sp = QDoubleSpinBox()
            sp.setRange(-1e9, mx)
            sp.setDecimals(2)
            sp.setValue(float(self.row.get(key, 0) or 0) if val is None else val)
            sp.setMinimumWidth(150)
            return sp

        self.minl = spin("min_level")
        self.maxl = spin("max_level")
        self.reorder = spin("reorder_level")
        self.critl = spin("critical_level")
        self.opening = spin("opening_balance")
        self.cost = spin("unit_cost")
        f1.addRow("Maximum Stock Level", self.maxl)
        f1.addRow("Minimum Stock Level", self.minl)
        f1.addRow("Reorder Level", self.reorder)
        f1.addRow("Critical Stock Level", self.critl)
        f1.addRow("Unit Cost", self.cost)
        if item_id:
            cur = QLabel(f"<b>{self.row.get('balance', 0):g}</b> {self.row.get('uom','')}  "
                         f"(change stock only through transactions)")
            f1.addRow("Current Balance", cur)
            _res = S.reserved_for(db, item_id)
            _free = max(0.0, float(self.row.get("balance", 0) or 0) - _res)
            rl = QLabel(f"<b style='color:#e0a300'>{_res:g}</b> reserved for open "
                        f"material requests &nbsp;·&nbsp; "
                        f"<b style='color:#1a9c52'>{_free:g}</b> free to use")
            rl.setToolTip("Reserved = prepared for a request but no Delivery Note "
                          "yet.\nIt is still on the shelf, so Balance does not change.")
            f1.addRow("Reserved / Free", rl)
        else:
            f1.addRow("Opening Balance", self.opening)
        sv.addWidget(box1)

        box2 = QGroupBox("Stock alert configuration")
        f2 = QFormLayout(box2)
        self.mode = W.combo(["GLOBAL", "PERCENT", "QTY", "CATEGORY"], False,
                            self.row.get("threshold_mode", "GLOBAL"))
        self.mode.setToolTip("GLOBAL: use the % set in Settings\nPERCENT: custom % of max level\n"
                             "QTY: use the fixed Min/Critical quantities above\n"
                             "CATEGORY: use the category thresholds")
        self.minpct = spin("min_pct", float(self.row.get("min_pct") or
                                            db.get_float("global_min_pct", 40)), 100)
        self.critpct = spin("crit_pct", float(self.row.get("crit_pct") or
                                              db.get_float("global_crit_pct", 20)), 100)
        f2.addRow("Threshold mode", self.mode)
        f2.addRow("Warning below (% of max)", self.minpct)
        f2.addRow("Critical below (% of max)", self.critpct)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        f2.addRow("Resulting alerts", self.preview)
        for wdg in (self.mode, self.minpct, self.critpct, self.maxl, self.minl, self.critl):
            sig = wdg.currentTextChanged if isinstance(wdg, QComboBox) else wdg.valueChanged
            sig.connect(self._update_preview)
        sv.addWidget(box2)
        sv.addStretch(1)
        tabs.addTab(s, "Stock && Alerts")

        # ---- location & image
        l = QWidget()
        lf = QFormLayout(l)
        self.wh = W.combo([""] + lookup(db, "warehouses"), True, self.row.get("warehouse", ""))
        lf.addRow("Warehouse / Store", self.wh)
        self.loc = W.combo([""] + [r["name"] for r in db.query(
            "SELECT DISTINCT name FROM locations ORDER BY name")], True, self.row.get("location", ""))
        lf.addRow("Location", self.loc)
        self.rack = QLineEdit(self.row.get("rack", ""))
        lf.addRow("Rack / Bin / Shelf", self.rack)
        self.remarks = QPlainTextEdit(self.row.get("remarks", ""))
        self.remarks.setMaximumHeight(70)
        lf.addRow("Remarks", self.remarks)
        self.image_path = self.row.get("image_path", "")
        self.img_lbl = QLabel("No image")
        self.img_lbl.setFixedSize(190, 150)
        self.img_lbl.setStyleSheet(f"border:1px dashed {W.BORDER}; border-radius:6px;")
        self.img_lbl.setAlignment(Qt.AlignCenter)
        self._show_image()
        hb = QHBoxLayout()
        hb.addWidget(self.img_lbl)
        bv = QVBoxLayout()
        bv.addWidget(W.button("Choose image...", slot=self._pick_image))
        bv.addWidget(W.button("Remove image", slot=self._clear_image))
        bv.addStretch(1)
        hb.addLayout(bv)
        hb.addStretch(1)
        wimg = QWidget()
        wimg.setLayout(hb)
        lf.addRow("Item Image", wimg)
        tabs.addTab(l, "Location && Image")

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._update_preview()

    def _show_image(self):
        if self.image_path and Path(self.image_path).exists():
            self.img_lbl.setPixmap(QPixmap(self.image_path).scaled(
                186, 146, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.img_lbl.setText("No image")

    def _pick_image(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select item image", "",
                                           "Images (*.png *.jpg *.jpeg *.bmp)")
        if f:
            dest = config.folder("Attachments") / f"item_{Path(f).name}"
            try:
                shutil.copy2(f, dest)
                self.image_path = str(dest)
            except OSError:
                self.image_path = f
            self._show_image()

    def _clear_image(self):
        self.image_path = ""
        self._show_image()

    def _update_preview(self):
        fake = {"max_level": self.maxl.value(), "min_level": self.minl.value(),
                "critical_level": self.critl.value(), "threshold_mode": self.mode.currentText(),
                "min_pct": self.minpct.value(), "crit_pct": self.critpct.value(),
                "category": self.cat.currentText(), "balance": 0}
        mn, crit = S.item_thresholds(self.db, fake)
        self.preview.setText(
            f"<span style='color:{W.AMBER}'><b>Warning</b> at or below {mn:g}</span> &nbsp;|&nbsp; "
            f"<span style='color:{W.ORANGE}'><b>Critical</b> at or below {crit:g}</span> &nbsp;|&nbsp; "
            f"<span style='color:{W.RED}'><b>Out of Stock</b> at 0</span>")

    def _save(self):
        data = {
            "code": self.code.text().strip(), "description": self.desc.text().strip(),
            "short_desc": self.short.text().strip(), "category": self.cat.currentText().strip(),
            "subcategory": self.subcat.text().strip(), "uom": self.uom.currentText().strip(),
            "brand": self.brand.text().strip(), "model": self.model.text().strip(),
            "specification": self.spec.toPlainText().strip(),
            "barcode": self.barcode.text().strip(), "alt_code": self.altcode.text().strip(),
            "min_level": self.minl.value(), "max_level": self.maxl.value(),
            "reorder_level": self.reorder.value(), "critical_level": self.critl.value(),
            "threshold_mode": self.mode.currentText(), "min_pct": self.minpct.value(),
            "crit_pct": self.critpct.value(), "unit_cost": self.cost.value(),
            "warehouse": self.wh.currentText().strip(), "location": self.loc.currentText().strip(),
            "rack": self.rack.text().strip(), "remarks": self.remarks.toPlainText().strip(),
            "image_path": self.image_path, "active": 1 if self.active.isChecked() else 0,
        }
        if not self.item_id:
            data["opening_balance"] = self.opening.value()
        try:
            S.save_item(self.db, data, self.item_id)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        for name, table in ((data["category"], "categories"), (data["uom"], "uoms"),
                            (data["warehouse"], "warehouses")):
            if name:
                self.db.execute(f"INSERT OR IGNORE INTO {table}(name) VALUES(?)", (name,))
        self.db.commit()
        self.accept()


# ============================================================ import wizard
class ImportWizard(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.headers: list[str] = []
        self.rows: list[list] = []
        self.setWindowTitle("Excel / CSV Import Wizard")
        self.resize(1000, 680)
        v = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Import type:"))
        self.mode = W.combo(list(importer.MODES))
        self.mode.currentTextChanged.connect(self._rebuild_mapping)
        top.addWidget(self.mode)
        self.path = QLineEdit()
        self.path.setPlaceholderText("Choose an .xlsx / .csv file...")
        top.addWidget(self.path, 1)
        top.addWidget(W.button("Browse...", slot=self._browse))
        self.sheet = W.combo([])
        self.sheet.currentTextChanged.connect(self._load)
        top.addWidget(QLabel("Sheet:"))
        top.addWidget(self.sheet)
        top.addWidget(W.button("⬇ Download template", slot=self._template))
        v.addLayout(top)

        v.addWidget(QLabel("<b>Step 2 — map your spreadsheet columns to AURCO fields</b>"))
        self.map_table = QTableWidget(0, 3)
        self.map_table.setHorizontalHeaderLabels(["AURCO Field", "Your Column", "Sample value"])
        self.map_table.horizontalHeader().setStretchLastSection(True)
        self.map_table.setMaximumHeight(260)
        v.addWidget(self.map_table)

        v.addWidget(QLabel("<b>Step 3 — preview</b>"))
        self.preview = W.DataTable()
        v.addWidget(self.preview, 1)

        bottom = QHBoxLayout()
        self.update_existing = QCheckBox("Update items that already exist (match on Item Code)")
        self.update_existing.setChecked(True)
        bottom.addWidget(self.update_existing)
        bottom.addStretch(1)
        self.info = QLabel("")
        bottom.addWidget(self.info)
        bottom.addWidget(W.button("Import Now", "Primary", self._run))
        bottom.addWidget(W.button("Close", slot=self.reject))
        v.addLayout(bottom)
        self._rebuild_mapping()

    def _template(self):
        mode = self.mode.currentText()
        out = config.folder("Exports") / f"AURCO_{mode.replace(' ', '_')}_Template.xlsx"
        importer.write_template(mode, out)
        W.toast(self, f"Template saved: {out.name}")
        D.open_file_location(out)

    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select file", "",
                                           "Spreadsheets (*.xlsx *.xlsm *.csv)")
        if not f:
            return
        self.path.setText(f)
        self.sheet.blockSignals(True)
        self.sheet.clear()
        self.sheet.addItems(importer.sheet_names(f))
        self.sheet.blockSignals(False)
        self._load()

    def _load(self):
        p = self.path.text().strip()
        if not p or not Path(p).exists():
            return
        try:
            self.headers, self.rows = importer.read_table(p, self.sheet.currentText())
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read the file.\n\n{exc}")
            return
        self.info.setText(f"{len(self.rows)} data row(s) found")
        self._rebuild_mapping()
        self.preview.fill(self.headers or ["(empty)"],
                          [[str(c) for c in r] for r in self.rows[:200]])

    def _rebuild_mapping(self):
        targets = importer.MODES[self.mode.currentText()]
        guess = importer.auto_map(self.headers, targets) if self.headers else {}
        self.map_table.setRowCount(len(targets))
        self.combos: dict[str, QComboBox] = {}
        for r, (field, label) in enumerate(targets.items()):
            self.map_table.setItem(r, 0, QTableWidgetItem(label))
            cb = QComboBox()
            cb.addItem("— not mapped —", -1)
            for i, h in enumerate(self.headers):
                cb.addItem(h, i)
            idx = guess.get(field)
            if idx is not None:
                cb.setCurrentIndex(idx + 1)
            self.map_table.setCellWidget(r, 1, cb)
            self.combos[field] = cb
            sample = ""
            if idx is not None and self.rows:
                sample = str(self.rows[0][idx]) if idx < len(self.rows[0]) else ""
            self.map_table.setItem(r, 2, QTableWidgetItem(sample))
        self.map_table.resizeColumnsToContents()

    def _run(self):
        if not self.rows:
            W.error_box(self, "Choose a file with data first.")
            return
        mapping = {f: cb.currentData() for f, cb in self.combos.items() if cb.currentData() >= 0}
        if not mapping:
            W.error_box(self, "Map at least one column.")
            return
        mode = self.mode.currentText()
        if mode == "Item Master" and "description" not in mapping and "code" not in mapping:
            W.error_box(self, "Map at least the Item Code or the Description column.")
            return
        if not W.confirm(self, f"Import {len(self.rows)} row(s) as {mode}?"):
            return
        prog = QProgressDialog("Importing...", "", 0, 0, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setCancelButton(None)
        prog.show()
        W.QApplication.processEvents()
        res = importer.run_import(self.db, mode, self.headers, self.rows, mapping,
                                  self.update_existing.isChecked())
        prog.close()
        msg = (f"Import finished.\n\nCreated: {res['created']}\nUpdated: {res['updated']}\n"
               f"Skipped: {res['skipped']}\nErrors: {len(res['errors'])}")
        if res["errors"]:
            msg += "\n\nFirst issues:\n" + "\n".join(res["errors"][:12])
        W.info_box(self, msg, "Import result")
        self.accept()


# ============================================================== item master
class ItemsPage(QWidget):
    dataChanged = Signal()
    openHistory = Signal(int)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.rows: list[dict] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search code, description, barcode, brand, model, location...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 3)
        self.f_cat = W.combo(["All Categories"])
        self.f_wh = W.combo(["All Warehouses"])
        self.f_status = W.combo(["All Status", S.NORMAL, S.WARNING, S.CRITICAL, S.OUT])
        self.f_inactive = QCheckBox("Include inactive")
        for wd in (self.f_cat, self.f_wh, self.f_status):
            wd.currentTextChanged.connect(self.reload)
            bar.addWidget(wd)
        self.f_inactive.toggled.connect(self.reload)
        bar.addWidget(self.f_inactive)
        v.addLayout(bar)

        btns = QHBoxLayout()
        btns.addWidget(W.button("➕  New Item", "Primary", self.new_item, "Add an item", "Ctrl+N"))
        btns.addWidget(W.button("✏  Edit", slot=self.edit_item, tip="Edit selected item", shortcut="F2"))
        btns.addWidget(W.button("📜  Movement History", slot=self._history))
        btns.addWidget(W.button("🚫  Deactivate", slot=self.deactivate))
        btns.addWidget(W.button("⬆  Import from Excel", slot=self.import_excel))
        btns.addWidget(W.button("📊  Export Excel", slot=lambda: self._export("xlsx")))
        btns.addWidget(W.button("📄  Export PDF", slot=lambda: self._export("pdf")))
        btns.addWidget(W.button("🏷  Barcode Designer", slot=self._barcodes,
                                tip="Design the label name, size and appearance, "
                                    "then print"))
        btns.addWidget(W.button("⚡  Quick Labels", slot=self._quick_barcodes,
                                tip="Print labels straight away with the saved design"))
        btns.addStretch(1)
        self.count_lbl = QLabel()
        self.count_lbl.setStyleSheet(f"color:{W.MUTED};")
        btns.addWidget(self.count_lbl)
        v.addLayout(btns)

        self.table = W.DataTable()
        self.table.doubleClicked.connect(self.edit_item)
        v.addWidget(W.FilterBar(self.table))
        v.addWidget(self.table, 1)
        self.table.filtersChanged.connect(self._update_count)
        self.reload_filters()
        self.reload()

    def reload_filters(self):
        for cb, table, first in ((self.f_cat, "categories", "All Categories"),
                                 (self.f_wh, "warehouses", "All Warehouses")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + lookup(self.db, table))
            i = cb.findText(cur)
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)

    def set_status_filter(self, status: str):
        self.f_status.setCurrentText(status or "All Status")
        self.reload()

    def reload(self):
        cat = "" if self.f_cat.currentIndex() <= 0 else self.f_cat.currentText()
        wh = "" if self.f_wh.currentIndex() <= 0 else self.f_wh.currentText()
        st = "" if self.f_status.currentIndex() <= 0 else self.f_status.currentText()
        self.rows = S.search_items(self.db, self.search.text(), cat, wh, st,
                                   active_only=not self.f_inactive.isChecked())
        cur = self.db.get_setting("currency", "")
        data = []
        for r in self.rows:
            mn, crit = S.item_thresholds(self.db, r)
            data.append([r["code"], r["description"], r["category"], r["uom"], r["brand"],
                         round(r["balance"], 2), round(r.get("reserved", 0), 2),
                         round(r.get("free", r["balance"]), 2),
                         round(mn, 2), round(r["max_level"] or 0, 2),
                         round(r["unit_cost"] or 0, 2), round(r["value"], 2),
                         r["warehouse"], r["location"], r["rack"], r["barcode"], r["status"]])
        self.table.fill(["Item Code", "Description", "Category", "UOM", "Brand", "Balance",
                         "Reserved", "Free to Use", "Min Level", "Max Level", "Unit Cost",
                         f"Value ({cur})", "Warehouse", "Location", "Rack/Bin", "Barcode",
                         "Status"], data, status_col=16)
        self._paint_reserved()
        self._update_count()

    def _paint_reserved(self):
        """Reserved stock is highlighted so it is never mistaken for free stock."""
        from PySide6.QtGui import QBrush, QColor, QFont
        for r, row in enumerate(self.rows):
            res = float(row.get("reserved", 0) or 0)
            cell = self.table.item(r, 6)
            free = self.table.item(r, 7)
            if cell is None:
                continue
            if res > 1e-9:
                cell.setForeground(QBrush(QColor("#e0a300")))
                f = QFont(cell.font())
                f.setBold(True)
                cell.setFont(f)
                who = self._reserved_detail(row["id"])
                cell.setToolTip(f"{res:g} {row['uom'] or ''} prepared for an open "
                                f"material request but not yet delivered.\n{who}")
                if free is not None:
                    free.setToolTip("Balance minus reserved — what a new request "
                                    "can actually be promised.")
            else:
                cell.setForeground(QBrush(QColor(W.MUTED)))

    def _reserved_detail(self, item_id: int) -> str:
        rows = self.db.query(
            """SELECT m.mr_no, m.project_id,
                      MAX(l.qty_prepared - l.qty_delivered, 0) AS q
                 FROM mr_lines l JOIN material_requests m ON m.id = l.mr_id
                WHERE l.item_id=? AND l.status IN ('Preparing','Ready',
                      'Partially Delivered') AND m.status<>'Cancelled'
                  AND l.qty_prepared > l.qty_delivered
                ORDER BY m.mr_no""", (item_id,))
        if not rows:
            return ""
        bits = [f"  · {r['mr_no']}  {r['q']:g}"
                + (f"  ({r['project_id']})" if r["project_id"] else "")
                for r in rows[:8]]
        if len(rows) > 8:
            bits.append(f"  · ... {len(rows) - 8} more")
        return "\n".join(bits)

    def _update_count(self, *_):
        """Counts always describe what is actually on screen."""
        cur = self.db.get_setting("currency", "")
        vis = {self.table.item(r, 0).text()
               for r in range(self.table.rowCount())
               if not self.table.isRowHidden(r) and self.table.item(r, 0)}
        shown = [r for r in self.rows if r["code"] in vis] if vis or self.table.has_filters() else self.rows
        total = sum(r["value"] for r in shown)
        qty = sum(r["balance"] or 0 for r in shown)
        res = sum(r.get("reserved", 0) or 0 for r in shown)
        suffix = (f"   (filtered from {len(self.rows)})"
                  if len(shown) != len(self.rows) else "")
        txt = f"{len(shown)} item(s) · {qty:,.0f} units"
        if res > 1e-9:
            txt += f" · {res:,.0f} reserved · {qty - res:,.0f} free"
        txt += f" · {cur} {total:,.2f}{suffix}"
        self.count_lbl.setText(txt)

    def _selected(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0:
            W.error_box(self, "Select an item from the list first.")
            return None
        code = self.table.item(r, 0).text()
        return next((x for x in self.rows if x["code"] == code), None)

    def new_item(self):
        if ItemDialog(self.db, None, self).exec() == QDialog.Accepted:
            self.reload_filters()
            self.reload()
            self.dataChanged.emit()
            W.toast(self, "Item created successfully.")

    def edit_item(self):
        it = self._selected()
        if it and ItemDialog(self.db, it["id"], self).exec() == QDialog.Accepted:
            self.reload()
            self.dataChanged.emit()
            W.toast(self, "Item updated.")

    def deactivate(self):
        it = self._selected()
        if not it:
            return
        if not AdminAuthDialog.authorise(
                self.db,
                f"Delete / deactivate item {it['code']} — {it['description']}\n"
                f"Current balance: {it['balance']:g} {it['uom']}",
                self):
            W.toast(self, "Deletion cancelled — administrator authorisation was not given.", "warn")
            return
        if W.confirm(self, f"Mark {it['code']} as inactive?\n\nThe item stays in the database and "
                           "all its transaction history is preserved."):
            S.deactivate_item(self.db, it["id"])
            self.reload()
            self.dataChanged.emit()
            W.toast(self, f"{it['code']} deactivated.")

    def _history(self):
        it = self._selected()
        if it:
            self.openHistory.emit(it["id"])

    def import_excel(self):
        if ImportWizard(self.db, self).exec() == QDialog.Accepted:
            self.reload_filters()
            self.reload()
            self.dataChanged.emit()

    def _export(self, kind: str):
        title, cols, rows = reports.build_report(self.db, "Item Master", {})
        f = (D.export_excel if kind == "xlsx" else D.report_pdf)(self.db, title, cols, rows)
        W.toast(self, f"Exported: {f.name}")
        D.open_path(f)

    def _scope(self) -> list[dict]:
        sel = [r for r in self.rows if r["code"] in
               {self.table.item(i.row(), 0).text() for i in self.table.selectedIndexes()
                if self.table.item(i.row(), 0)}]
        return sel or self.rows

    def _barcodes(self):
        items = self._scope()
        if not items:
            W.error_box(self, "There are no items to print labels for.")
            return
        from .barcode_designer import BarcodeDesigner
        BarcodeDesigner(self.db, items[:2000], self).exec()

    def _quick_barcodes(self):
        """Print immediately using the last saved label design."""
        from ..core import barcodes as B
        items = self._scope()
        if not items:
            W.error_box(self, "There are no items to print labels for.")
            return
        try:
            f = B.label_pdf(self.db, items[:2000], B.get_design(self.db))
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not build the label sheet.\n\n{exc}")
            return
        W.toast(self, f"Label sheet created: {f.name}")
        D.open_path(f)
