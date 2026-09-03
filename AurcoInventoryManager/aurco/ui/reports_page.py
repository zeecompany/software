"""Report Center: 28 filterable reports with PDF / Excel / CSV / Print / share."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

from ..core import documents as D, reports
from ..core.database import Database
from . import widgets as W
from .common import ShareBar, date_edit, iso, lookup

FAVOURITES = ["Current Stock Report", "Low Stock Report", "Critical Stock Report",
              "Out of Stock Report", "Delivery Note Report", "Stock Valuation",
              "Project Closure Reconciliation"]


class ReportsPage(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.last_file: Path | None = None
        self.cols: list[str] = []
        self.rows: list[list] = []
        self.title = ""

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(9)
        split = QSplitter(Qt.Horizontal)

        left = W.Card("Reports")
        self.list = QListWidget()
        self.list.setStyleSheet("QListWidget{border:none;} QListWidget::item{padding:6px 4px;}"
                                "QListWidget::item:selected{background:#0b3d6b;color:white;"
                                "border-radius:4px;}")
        fav = QListWidgetItem("★  FAVOURITES")
        fav.setFlags(Qt.NoItemFlags)
        self.list.addItem(fav)
        for r in FAVOURITES:
            self.list.addItem(QListWidgetItem("   " + r))
        allh = QListWidgetItem("ALL REPORTS")
        allh.setFlags(Qt.NoItemFlags)
        self.list.addItem(allh)
        for r in reports.REPORT_LIST:
            self.list.addItem(QListWidgetItem("   " + r))
        self.list.currentItemChanged.connect(self.run)
        left.add(self.list)
        left.setMinimumWidth(250)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        filt = QHBoxLayout()
        self.d_from = date_edit()
        self.d_from.setDate(self.d_from.date().addMonths(-12))
        self.d_to = date_edit()
        self.f_cat = W.combo(["All Categories"] + lookup(db, "categories"))
        self.f_wh = W.combo(["All Warehouses"] + lookup(db, "warehouses"))
        # Project filter drives the project-closure reports
        projects = sorted({r[0] for r in db.query(
            "SELECT DISTINCT COALESCE(NULLIF(project,''), department) FROM documents"
            " WHERE COALESCE(NULLIF(project,''), department) IS NOT NULL"
            "   AND COALESCE(NULLIF(project,''), department) <> ''") if r[0]})
        self.f_project = W.combo(["All Projects"] + projects, editable=True)
        self.f_project.setToolTip("Used by the Project Closure reports")
        self.f_text = W.SearchBox("Text filter...")
        for w_ in (self.d_from, self.d_to, self.f_cat, self.f_wh, self.f_project):
            (w_.dateChanged if hasattr(w_, "dateChanged") else w_.currentTextChanged).connect(self.run)
        self.f_text.returnPressed.connect(self.run)
        filt.addWidget(QLabel("From:"))
        filt.addWidget(self.d_from)
        filt.addWidget(QLabel("To:"))
        filt.addWidget(self.d_to)
        filt.addWidget(self.f_cat)
        filt.addWidget(self.f_wh)
        filt.addWidget(self.f_project)
        filt.addWidget(self.f_text, 1)
        filt.addWidget(W.button("🔄  Run", "Primary", self.run))
        rv.addLayout(filt)

        act = QHBoxLayout()
        act.addWidget(W.button("📄  PDF", "Accent", lambda: self.export("pdf")))
        act.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        act.addWidget(W.button("📑  CSV", slot=lambda: self.export("csv")))
        act.addWidget(W.button("🖨  Print", slot=self.print_report))
        act.addStretch(1)
        self.info = QLabel()
        self.info.setStyleSheet(f"color:{W.MUTED};")
        act.addWidget(self.info)
        rv.addLayout(act)

        opts = QHBoxLayout()
        self.opt_totals = QCheckBox("Totals row")
        self.opt_totals.setChecked(True)
        self.opt_totals.setToolTip("Add a TOTAL line to PDF and Excel exports")
        opts.addWidget(self.opt_totals)
        self.opt_zebra = QCheckBox("Striped rows")
        self.opt_zebra.setChecked(True)
        opts.addWidget(self.opt_zebra)
        self.opt_landscape = QComboBox()
        self.opt_landscape.addItems(["Auto layout", "Force portrait", "Force landscape"])
        opts.addWidget(self.opt_landscape)
        opts.addWidget(QLabel("Columns:"))
        self.col_pick = QPushButton("All columns")
        self.col_pick.clicked.connect(self._choose_columns)
        self.col_pick.setMinimumWidth(150)
        opts.addWidget(self.col_pick)
        opts.addStretch(1)
        rv.addLayout(opts)

        self.table = W.DataTable()
        rv.addWidget(W.FilterBar(self.table))
        rv.addWidget(self.table, 1)
        rv.addWidget(ShareBar(db, lambda: self.last_file, self))
        split.addWidget(right)
        split.setSizes([250, 1000])
        v.addWidget(split, 1)
        self.list.setCurrentRow(1)

    def _choose_columns(self):
        """Tick which columns appear in the exported document."""
        if not self.cols:
            W.error_box(self, "Run a report first.")
            return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout as _V
        dlg = QDialog(self)
        dlg.setWindowTitle("Choose columns")
        v = _V(dlg)
        boxes = []
        for c in self.cols:
            cb = QCheckBox(c)
            cb.setChecked(c not in getattr(self, "hidden_cols", set()))
            boxes.append(cb)
            v.addWidget(cb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        self.hidden_cols = {b.text() for b in boxes if not b.isChecked()}
        n = len(self.cols) - len(self.hidden_cols)
        self.col_pick.setText("All columns" if not self.hidden_cols
                              else f"{n} of {len(self.cols)} columns")
        self.run()

    def _visible(self):
        """(cols, rows) after applying the column chooser."""
        hidden = getattr(self, "hidden_cols", set())
        if not hidden:
            return self.cols, self.rows
        keep = [i for i, c in enumerate(self.cols) if c not in hidden]
        return ([self.cols[i] for i in keep],
                [[r[i] if i < len(r) else "" for i in keep] for r in self.rows])

    def _filters(self) -> dict:
        return {"date_from": iso(self.d_from), "date_to": iso(self.d_to),
                "category": "" if self.f_cat.currentIndex() == 0 else self.f_cat.currentText(),
                "warehouse": "" if self.f_wh.currentIndex() == 0 else self.f_wh.currentText(),
                "project": ("" if self.f_project.currentIndex() == 0
                            else self.f_project.currentText().strip()),
                "text": self.f_text.text().strip()}

    def current_report(self) -> str:
        it = self.list.currentItem()
        return it.text().strip() if it else ""

    def run(self, *_):
        name = self.current_report()
        if not name or name in ("★  FAVOURITES", "ALL REPORTS"):
            return
        try:
            self.title, self.cols, self.rows = reports.build_report(self.db, name, self._filters())
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not build the report.\n\n{exc}")
            return
        self.table.fill(self.cols, self.rows,
                        status_col=self.cols.index("Status") if "Status" in self.cols else None)
        self.info.setText(f"{len(self.rows)} row(s)")

    def export(self, kind: str):
        if not self.cols:
            self.run()
        if not self.rows:
            W.error_box(self, "This report has no rows to export.")
            return
        cols, rows = self._visible()
        f = self._filters()
        sub_bits = []
        if f.get("date_from") or f.get("date_to"):
            sub_bits.append(f"Period {f.get('date_from') or 'start'} to "
                            f"{f.get('date_to') or 'today'}")
        if f.get("category"):
            sub_bits.append(f"Category: {f['category']}")
        if f.get("warehouse"):
            sub_bits.append(f"Warehouse: {f['warehouse']}")
        if f.get("text"):
            sub_bits.append(f"Filter: {f['text']}")
        sub_bits.append(f"Prepared by {self.db.current_user}")
        subtitle = "   ·   ".join(sub_bits)
        if kind == "pdf":
            self.last_file = D.report_pdf(self.db, self.title, cols, rows,
                                          subtitle=subtitle,
                                          totals_row=self.opt_totals.isChecked())
        elif kind == "xlsx":
            self.last_file = D.export_excel(self.db, self.title, cols, rows,
                                            totals=self.opt_totals.isChecked())
        else:
            self.last_file = D.export_csv(self.db, self.title, cols, rows)
        W.toast(self, f"Saved: {self.last_file.name}")
        D.open_path(self.last_file)

    def print_report(self):
        if not self.rows:
            W.error_box(self, "Run a report first.")
            return
        self.last_file = D.report_pdf(self.db, self.title, self.cols, self.rows)
        D.print_file(self.db, self.last_file)
        W.toast(self, "Sent to printer.")
