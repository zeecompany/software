"""Bulk Stock Check — enter/paste/scan many item codes and get quantities at once.

Typical warehouse use: a request list arrives with 40 item codes; the storekeeper
pastes them in and instantly sees which are available, short or missing, then
exports the answer or turns it straight into a Delivery Note.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QSplitter, QVBoxLayout, QWidget)

from ..core import documents as D, importer
from ..core import services as S
from ..core.database import Database
from . import widgets as W
from .common import ShareBar

COLS = ["Item Code", "Description", "UOM", "PR / MR No.", "Available Qty", "Required Qty",
        "Short By", "Result", "Unit Cost", "Value", "Warehouse", "Location", "Rack/Bin", "Status"]


class BulkCheckPage(QWidget):
    """Signals: requestDN(list[dict]) -> send the shortage-free list to Stock Out."""
    requestDN = Signal(list)
    openHistory = Signal(int)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.results: list[dict] = []
        self.last_file: Path | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(9)

        info = QLabel("Enter, paste or scan item codes — one per line. Add a required quantity, "
                      "and optionally a PR number, separated by commas: "
                      "<b>ITM-00012, 50, PR-2026-0148</b>. "
                      "Then 'Create Delivery Note' builds one multi-PR DN from the whole list.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(info)

        split = QSplitter(Qt.Horizontal)

        left = W.Card("Item codes")
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(
            "ITM-00001, 10, PR-2026-0148\n"
            "ITM-00002, 25, PR-2026-0148\n"
            "ITM-00007, 100, PR-2026-0152\n"
            "8901234567890")
        self.input.setMinimumWidth(260)
        left.add(self.input, 1)
        brow = QHBoxLayout()
        brow.addWidget(W.button("✔  Check Stock", "Primary", self.run, shortcut="Ctrl+Return"))
        brow.addWidget(W.button("🧹  Clear", slot=self.clear))
        left.v.addLayout(brow)
        brow2 = QHBoxLayout()
        brow2.addWidget(W.button("📂  Load from file", slot=self.load_file,
                                 tip="Load codes from Excel/CSV/text"))
        brow2.addWidget(W.button("📋  Paste && Check", slot=self.paste_check))
        left.v.addLayout(brow2)
        self.only_problems = QCheckBox("Show only shortages and missing codes")
        self.only_problems.toggled.connect(self._render)
        left.v.addWidget(self.only_problems)
        left.setMaximumWidth(340)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        self.summary = QLabel("Enter item codes on the left and press Check Stock.")
        self.summary.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER};"
                                   "border-radius:8px; padding:10px;")
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setWordWrap(True)
        rv.addWidget(self.summary)

        act = QHBoxLayout()
        act.addWidget(W.button("📄  PDF", "Accent", lambda: self.export("pdf")))
        act.addWidget(W.button("📊  Excel", slot=lambda: self.export("xlsx")))
        act.addWidget(W.button("📑  CSV", slot=lambda: self.export("csv")))
        act.addWidget(W.button("🖨  Print", slot=self.print_out))
        act.addWidget(W.button("📤  Create Delivery Note from this list", "Primary",
                               self.to_delivery_note))
        act.addStretch(1)
        rv.addLayout(act)

        self.table = W.DataTable()
        self.table.doubleClicked.connect(self._open_item)
        rv.addWidget(self.table, 1)
        rv.addWidget(ShareBar(db, lambda: self.last_file, self))
        split.addWidget(right)
        split.setSizes([320, 1100])
        v.addWidget(split, 1)

    # ------------------------------------------------------------------ input
    def clear(self):
        self.input.clear()
        self.results = []
        self.table.setRowCount(0)
        self.summary.setText("Enter item codes on the left and press Check Stock.")

    def paste_check(self):
        from PySide6.QtWidgets import QApplication
        txt = QApplication.clipboard().text()
        if txt.strip():
            self.input.setPlainText(txt)
            self.run()
        else:
            W.error_box(self, "The clipboard is empty.")

    def load_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Load item codes", "",
                                           "All supported (*.xlsx *.xlsm *.csv *.txt)")
        if not f:
            return
        try:
            if Path(f).suffix.lower() in (".xlsx", ".xlsm", ".csv"):
                head, rows = importer.read_table(f)
                lines = []
                for r in rows:
                    code = str(r[0]).strip() if r else ""
                    qty = ""
                    if len(r) > 1 and str(r[1]).strip():
                        qty = f", {str(r[1]).strip()}"
                    if code:
                        lines.append(code + qty)
                self.input.setPlainText("\n".join(lines))
            else:
                self.input.setPlainText(Path(f).read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not read the file.\n\n{exc}")
            return
        self.run()

    @staticmethod
    def _parse(text: str) -> list[tuple[str, float, str]]:
        """Accepts:  CODE  |  CODE, QTY  |  CODE, QTY, PR-NUMBER"""
        out = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            for sep in (";", "\t"):
                line = line.replace(sep, ",")
            if "," in line:
                parts = [p.strip() for p in line.split(",") if p.strip()]
            else:
                parts = [p for p in line.split(" ") if p]
            code = parts[0]
            qty, pr = 0.0, ""
            if len(parts) >= 3:
                try:
                    qty = float(parts[1].replace(",", ""))
                except ValueError:
                    qty = 0.0
                pr = parts[2]
            elif len(parts) == 2:
                try:
                    qty = float(parts[1].replace(",", ""))
                except ValueError:
                    # a second non-numeric field is treated as the PR number
                    pr = parts[1]
            out.append((code, qty, pr))
        return out

    # ------------------------------------------------------------------- run
    def run(self):
        entries = self._parse(self.input.toPlainText())
        if not entries:
            W.error_box(self, "Enter at least one item code.")
            return
        self.results = []
        seen: dict[str, int] = {}          # resolved item code -> row index
        missing_seen: dict[str, int] = {}  # unknown code -> row index
        for code, need, pr in entries:
            it = S.find_by_barcode(self.db, code)
            if it is None:
                key = code.upper()
                if key in missing_seen:
                    self.results[missing_seen[key]]["required"] += need
                    continue
                missing_seen[key] = len(self.results)
                self.results.append({"code": code, "found": False, "required": need,
                                     "pr_no": pr})
                continue
            # merge duplicates even when entered by different identifiers
            # (item code, barcode or alternate code all resolve to one item)
            key = it["code"]
            if key in seen:
                row = self.results[seen[key]]
                row["required"] += need
                if pr and pr not in str(row.get("pr_no", "")).split(" / "):
                    row["pr_no"] = f"{row['pr_no']} / {pr}" if row.get("pr_no") else pr
                if code.upper() != key.upper() and code not in row.get("aliases", []):
                    row.setdefault("aliases", []).append(code)
                continue
            d = dict(it)
            d["found"] = True
            d["required"] = need
            d["pr_no"] = pr
            d["aliases"] = [] if code.upper() == key.upper() else [code]
            seen[key] = len(self.results)
            self.results.append(d)
        for r in self.results:
            if not r["found"]:
                r["short"] = r["required"]
                r["result"] = "NOT FOUND"
            else:
                bal = float(r.get("balance") or 0)
                need = float(r.get("required") or 0)
                r["short"] = max(0.0, need - bal) if need else 0.0
                if need <= 0:
                    r["result"] = "Enquiry only"
                elif bal >= need:
                    r["result"] = "Available"
                elif bal > 0:
                    r["result"] = "Partial"
                else:
                    r["result"] = "No stock"
        self._render()
        self.db.audit("EXPORTED", "bulk-check", "", f"{len(self.results)} code(s) checked")

    def _render(self):
        rows = []
        show = self.results
        if self.only_problems.isChecked():
            show = [r for r in self.results if r["result"] in ("NOT FOUND", "Partial", "No stock")]
        for r in show:
            if not r["found"]:
                rows.append([r["code"], "— not found in item master —", "",
                             r.get("pr_no", ""), 0, r["required"], r["required"],
                             "NOT FOUND", 0, 0, "", "", "", ""])
                continue
            bal = float(r.get("balance") or 0)
            cost = float(r.get("unit_cost") or 0)
            desc = r["description"]
            if r.get("aliases"):
                desc += f"   (also entered as: {', '.join(r['aliases'])})"
            rows.append([r["code"], desc, r["uom"], r.get("pr_no", ""), round(bal, 2),
                         round(float(r["required"]), 2), round(float(r["short"]), 2), r["result"],
                         round(cost, 2), round(bal * cost, 2), r["warehouse"], r["location"],
                         r["rack"], r["status"]])
        self.table.fill(COLS, rows, status_col=13)
        # colour the Result column
        from PySide6.QtGui import QBrush, QColor
        colours = {"Available": W.GREEN, "Partial": W.AMBER, "No stock": W.RED,
                   "NOT FOUND": W.RED, "Enquiry only": W.MUTED}
        for i in range(self.table.rowCount()):
            cell = self.table.item(i, 7)
            if cell:
                cell.setForeground(QBrush(QColor(colours.get(cell.text(), W.TEXT))))
                f = cell.font()
                f.setBold(True)
                cell.setFont(f)

        found = [r for r in self.results if r["found"]]
        missing = [r for r in self.results if not r["found"]]
        short = [r for r in found if r["short"] > 0]
        total_qty = sum(float(r.get("balance") or 0) for r in found)
        total_val = sum(float(r.get("balance") or 0) * float(r.get("unit_cost") or 0) for r in found)
        req = sum(float(r["required"]) for r in self.results)
        cur = self.db.get_setting("currency", "")
        self.summary.setText(
            f"<table width='100%'><tr>"
            f"<td>Codes checked<br><b style='font-size:16px'>{len(self.results)}</b></td>"
            f"<td style='color:{W.GREEN}'>Found<br><b style='font-size:16px'>{len(found)}</b></td>"
            f"<td style='color:{W.RED}'>Not found<br><b style='font-size:16px'>{len(missing)}</b></td>"
            f"<td style='color:{W.AMBER}'>Short / partial<br>"
            f"<b style='font-size:16px'>{len(short)}</b></td>"
            f"<td>Total available qty<br><b style='font-size:16px'>{total_qty:,.2f}</b></td>"
            f"<td>Total required<br><b style='font-size:16px'>{req:,.2f}</b></td>"
            f"<td>Stock value<br><b style='font-size:16px'>{cur} {total_val:,.2f}</b></td>"
            f"</tr></table>")

    def _open_item(self):
        r = self.table.currentRow()
        if r < 0:
            return
        code = self.table.item(r, 0).text()
        it = self.db.one("SELECT id FROM items WHERE code=?", (code,))
        if it:
            self.openHistory.emit(it["id"])

    # ---------------------------------------------------------------- output
    def export(self, kind: str):
        if not self.results:
            W.error_box(self, "Run a stock check first.")
            return
        title = "Bulk Stock Check"
        fn = {"pdf": D.report_pdf, "xlsx": D.export_excel, "csv": D.export_csv}[kind]
        self.last_file = fn(self.db, title, self.table.headers(), self.table.all_rows())
        W.toast(self, f"Saved: {self.last_file.name}")
        D.open_path(self.last_file)

    def print_out(self):
        if not self.results:
            W.error_box(self, "Run a stock check first.")
            return
        self.last_file = D.report_pdf(self.db, "Bulk Stock Check", self.table.headers(),
                                      self.table.all_rows())
        D.print_file(self.db, self.last_file)
        W.toast(self, "Sent to printer.")

    def to_delivery_note(self):
        picks = [r for r in self.results if r["found"] and float(r["required"]) > 0]
        if not picks:
            W.error_box(self, "Add required quantities (e.g. 'ITM-00012, 50') to build a "
                              "Delivery Note from this list.")
            return
        short = [r for r in picks if r["short"] > 0]
        if short and not W.confirm(
                self, f"{len(short)} item(s) do not have enough stock.\n\n"
                      "Continue and add the available quantities to the Delivery Note?"):
            return
        out = []
        for r in picks:
            d = dict(r)
            d["issue_qty"] = min(float(r["required"]), float(r.get("balance") or 0))
            out.append(d)
        self.requestDN.emit(out)
