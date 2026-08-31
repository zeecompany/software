"""Document browser (DN/GRN/RET/TRF/ADJ/CNT), movement history, global search, audit."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from ..core import documents as D, reports
from ..core import services as S
from ..core.database import Database
from . import widgets as W
from .auth_dialogs import AdminAuthDialog
from .common import ItemPicker, ShareBar, date_edit, iso

TYPES = {"All Documents": "", "Delivery Notes (DN)": "DN", "Goods Receipts (GRN)": "GRN",
         "Returns (RET)": "RET", "Transfers (TRF)": "TRF", "Adjustments (ADJ)": "ADJ",
         "Stock Counts (CNT)": "CNT"}


class DocumentsPage(QWidget):
    dataChanged = Signal()
    editDraft = Signal(int)          # doc_id -> re-open the draft on its form

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.docs: list[dict] = []
        self.last_pdf: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(9)

        bar = QHBoxLayout()
        self.f_type = W.combo(list(TYPES))
        self.f_type.currentTextChanged.connect(self.reload)
        bar.addWidget(QLabel("Type:"))
        bar.addWidget(self.f_type)
        self.f_status = W.combo(["All Status", "DRAFT", "FINAL", "REVERSED"])
        self.f_status.currentTextChanged.connect(self.reload)
        bar.addWidget(QLabel("Status:"))
        bar.addWidget(self.f_status)
        self.d_from = date_edit()
        self.d_from.setDate(self.d_from.date().addMonths(-6))
        self.d_to = date_edit()
        for d in (self.d_from, self.d_to):
            d.dateChanged.connect(self.reload)
        bar.addWidget(QLabel("From:"))
        bar.addWidget(self.d_from)
        bar.addWidget(QLabel("To:"))
        bar.addWidget(self.d_to)
        self.search = W.SearchBox("Search DN / PR / MR number / supplier / project / person...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 1)
        v.addLayout(bar)

        btns = QHBoxLayout()
        btns.addWidget(W.button("🔍  Show Details", slot=self.show_details,
                                tip="Load the lines of the selected document"))
        btns.addWidget(W.button("👁  View / Regenerate PDF", "Primary", self.view_pdf))
        btns.addWidget(W.button("🖨  Reprint", slot=self.reprint))
        btns.addWidget(W.button("📄  Duplicate / Copy", slot=self.duplicate))
        btns.addWidget(W.button("✏  Edit Draft", "Primary", self.edit_draft,
                                tip="Re-open this DRAFT on its form to change "
                                    "quantities, PR numbers or the header"))
        btns.addWidget(W.button("✅  Finalize Draft", slot=self.finalize))
        btns.addWidget(W.button("↩  Reverse / Correct", "Danger", self.reverse))
        btns.addWidget(W.button("📊  Export List to Excel", slot=self.export))
        btns.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        btns.addWidget(self.count)
        v.addLayout(btns)

        split = QSplitter(Qt.Vertical)
        top_docs = QWidget()
        tdl = QVBoxLayout(top_docs)
        tdl.setContentsMargins(0, 0, 0, 0)
        tdl.setSpacing(4)
        self.table = W.DataTable()
        self.table.itemSelectionChanged.connect(self.show_lines)
        self.table.doubleClicked.connect(self.view_pdf)
        tdl.addWidget(W.FilterBar(self.table))
        tdl.addWidget(self.table, 1)
        self.table.filtersChanged.connect(
            lambda n: self.count.setText(
                f"{n} document(s)" + (f"  (filtered from {self.table.rowCount()})"
                                      if n != self.table.rowCount() else "")))
        split.addWidget(top_docs)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 6, 0, 0)
        self.detail = QLabel("Select a document to see its lines")
        self.detail.setStyleSheet(f"color:{W.NAVY}; font-weight:600;")
        bl.addWidget(self.detail)
        self.lines = W.DataTable()
        bl.addWidget(self.lines)
        split.addWidget(bottom)
        split.setSizes([460, 260])
        v.addWidget(split, 1)
        v.addWidget(ShareBar(db, lambda: self.last_pdf, self))
        self.reload()

    def set_filter(self, key: str):
        if key == "DRAFT":
            self.f_type.setCurrentIndex(0)
            self.f_status.setCurrentText("DRAFT")
        else:
            for label, code in TYPES.items():
                if code == key:
                    self.f_type.setCurrentText(label)
                    break
            self.f_status.setCurrentIndex(0)
        self.reload()

    def reload(self):
        dt = TYPES[self.f_type.currentText()]
        sql = "SELECT * FROM documents WHERE doc_date BETWEEN ? AND ?"
        p = [iso(self.d_from), iso(self.d_to)]
        if dt:
            sql += " AND doc_type=?"
            p.append(dt)
        if self.f_status.currentIndex() > 0:
            sql += " AND status=?"
            p.append(self.f_status.currentText())
        if self.search.text().strip():
            like = f"%{self.search.text().strip()}%"
            sql += (" AND (doc_no LIKE ? OR reference LIKE ? OR project LIKE ? OR supplier LIKE ?"
                    " OR issued_to LIKE ? OR received_by LIKE ? OR returned_by LIKE ?"
                    " OR linked_doc LIKE ?"
                    " OR id IN (SELECT doc_id FROM document_lines WHERE pr_no LIKE ?))")
            p += [like] * 9
        sql += " ORDER BY doc_date DESC, id DESC LIMIT 5000"
        self.docs = [dict(r) for r in self.db.query(sql, p)]
        rows = []
        for d in self.docs:
            agg = self.db.one("SELECT COUNT(*) c, COALESCE(SUM(qty),0) q FROM document_lines"
                              " WHERE doc_id=?", (d["id"],))
            rows.append([d["doc_no"], d["doc_type"], d["doc_date"], d["status"],
                         d["supplier"] or d["issued_to"] or d["returned_by"] or d["to_warehouse"],
                         d["project"], d["reference"] or d["linked_doc"] or d["reason"],
                         agg["c"], round(agg["q"], 2), round(d["total_value"] or 0, 2),
                         d["created_by"]])
        self.table.fill(["Document No", "Type", "Date", "Status", "Party", "Project / Site",
                         "Reference", "Lines", "Total Qty", "Value", "User"], rows)
        self.count.setText(f"{len(rows)} document(s)")
        if rows:
            if self.table.currentRow() < 0:
                self.table.selectRow(0)
            self.show_lines()
        else:
            self.lines.setRowCount(0)
            self.detail.setText("No documents match the current filter")

    def _sel(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0 or self.table.item(r, 0) is None:
            return None
        no = self.table.item(r, 0).text()
        dtype = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
        hit = next((d for d in self.docs
                    if d["doc_no"] == no and (not dtype or d["doc_type"] == dtype)), None)
        if hit is None:
            # cached list is stale (sorted / filtered / refreshed) -> re-read
            row = (self.db.one("SELECT * FROM documents WHERE doc_no=? AND doc_type=?",
                               (no, dtype)) if dtype else
                   self.db.one("SELECT * FROM documents WHERE doc_no=?", (no,)))
            hit = dict(row) if row else None
            if hit:
                self.docs = list(self.docs) + [hit]
        return hit

    def show_details(self):
        """Explicit refresh so the lines grid is never left blank."""
        if self.table.currentRow() < 0 and self.table.rowCount():
            self.table.selectRow(0)
        if not self._sel():
            W.error_box(self, "Select a document in the list above first.")
            return
        self.show_lines()

    def show_lines(self):
        d = self._sel()
        if not d:
            if self.table.rowCount():
                self.table.selectRow(0)
                d = self._sel()
            if not d:
                self.lines.setRowCount(0)
                self.detail.setText("Select a document to see its lines")
                return
        rows = self.db.query("SELECT * FROM document_lines WHERE doc_id=? ORDER BY id", (d["id"],))
        def _g(k):
            try:
                return d[k] or ""
            except (IndexError, KeyError):
                return ""
        extra = ""
        if _g("handover_to"):
            ident = " · ".join(x for x in (_g("handover_id"), _g("handover_phone")) if x)
            extra = f"  |  Handover to: {_g('handover_to')}" + (f" ({ident})" if ident else "")
        self.detail.setText(f"{d['doc_type']} {d['doc_no']}  —  {d['status']}  —  {d['doc_date']}"
                            + extra
                            + (f"  |  Remarks: {d['remarks']}" if d["remarks"] else ""))
        self.lines.fill(["Item Code", "Description", "UOM", "Qty", "PR / MR No.", "Unit Cost",
                         "Total", "Condition", "Batch", "System Qty", "Counted", "Variance",
                         "Remarks"],
                        [[r["item_code"], r["description"], r["uom"], r["qty"],
                          (r["pr_no"] if "pr_no" in r.keys() else "") or "", r["unit_cost"],
                          r["total_cost"], r["condition"], r["batch"], r["system_qty"],
                          r["counted_qty"], r["variance"], r["remarks"]] for r in rows])
        if d["pdf_path"] and Path(d["pdf_path"]).exists():
            self.last_pdf = Path(d["pdf_path"])

    def view_pdf(self):
        d = self._sel()
        if not d:
            W.error_box(self, "Select a document first.")
            return
        self.last_pdf = D.document_pdf(self.db, d["id"])
        D.open_path(self.last_pdf)

    def reprint(self):
        d = self._sel()
        if not d:
            return
        f = D.document_pdf(self.db, d["id"])
        self.last_pdf = f
        D.print_file(self.db, f)
        W.toast(self, f"Reprinting {d['doc_no']}")

    def duplicate(self):
        d = self._sel()
        if not d:
            W.error_box(self, "Select a document to copy.")
            return
        if d["doc_type"] not in ("DN", "GRN"):
            W.error_box(self, "Only Delivery Notes and Goods Receipts can be duplicated.")
            return
        if not W.confirm(self, f"Create a new DRAFT copy of {d['doc_no']}?"):
            return
        lines = self.db.query("SELECT * FROM document_lines WHERE doc_id=?", (d["id"],))
        h = S.DocHeader(doc_type=d["doc_type"], project=d["project"], department=d["department"],
                        requested_by=d["requested_by"], issued_to=d["issued_to"],
                        supplier=d["supplier"], reference=d["reference"], purpose=d["purpose"],
                        warehouse=d["warehouse"], remarks=f"Copy of {d['doc_no']}")
        new_lines = [S.Line(item_id=l["item_id"], qty=l["qty"], unit_cost=l["unit_cost"],
                            pr_no=(l["pr_no"] if "pr_no" in l.keys() else "") or "",
                            remarks=l["remarks"]) for l in lines]
        try:
            if d["doc_type"] == "DN":
                no = S.post_issue(self.db, h, new_lines, finalize=False)
            else:
                no = S.post_receipt(self.db, h, new_lines, finalize=False)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        W.toast(self, f"Draft {no} created as a copy of {d['doc_no']}.")

    def edit_draft(self):
        """Send the selected DRAFT back to Stock Out / Stock In for correction."""
        d = self._sel()
        if not d:
            W.error_box(self, "Select a draft document first.")
            return
        if d["status"] != "DRAFT":
            W.error_box(self, f"{d['doc_no']} is {d['status'].lower()} and cannot be "
                              "edited.\n\nOnly DRAFT documents can be changed; use "
                              "'Reverse / Correct' for a finalized document.")
            return
        if d["doc_type"] not in ("DN", "GRN"):
            W.error_box(self, "Only Delivery Note and Goods Receipt drafts can be "
                              "re-opened for editing.")
            return
        self.editDraft.emit(int(d["id"]))

    def finalize(self):
        d = self._sel()
        if not d:
            return
        if d["status"] != "DRAFT":
            W.error_box(self, f"{d['doc_no']} is already {d['status'].lower()}.")
            return
        if not W.confirm(self, f"Finalize {d['doc_no']}?\n\nStock will be updated and the "
                               "document locked against accidental modification."):
            return
        try:
            S.finalize_draft(self.db, d["id"])
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        self.dataChanged.emit()
        W.toast(self, f"{d['doc_no']} finalized — stock updated.")

    def reverse(self):
        d = self._sel()
        if not d:
            return
        if d["status"] != "FINAL":
            W.error_box(self, "Only finalized documents can be reversed.")
            return
        if self.db.get_bool("require_admin_password_reverse", True):
            if not AdminAuthDialog.authorise(
                    self.db, f"Reverse / correct finalized document {d['doc_no']} "
                             f"({d['doc_type']}, {d['doc_date']}).", self):
                W.toast(self, "Reversal cancelled — authorisation was not given.", "warn")
                return
        reason, ok = QInputDialog.getText(
            self, "Authorized correction / reversal",
            f"Reason for reversing {d['doc_no']} (kept in the audit trail):")
        if not ok or not reason.strip():
            return
        try:
            S.reverse_document(self.db, d["id"], reason.strip())
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.reload()
        self.dataChanged.emit()
        W.toast(self, f"{d['doc_no']} reversed — the opposite stock movement was recorded.", "warn")

    def export(self):
        f = D.export_excel(self.db, "Document Register", self.table.headers(), self.table.all_rows())
        W.toast(self, f"Exported {f.name}")
        D.open_path(f)


# ========================================================== movement history
class HistoryPage(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.item: dict | None = None
        self.last_pdf: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(9)

        bar = QHBoxLayout()
        bar.addWidget(W.button("🔍  Choose Item  (F3)", "Primary", self.pick, shortcut="F3"))
        self.lbl = QLabel("No item selected")
        self.lbl.setStyleSheet(f"font-weight:700; color:{W.NAVY}; font-size:14px;")
        bar.addWidget(self.lbl, 1)
        self.d_from = date_edit()
        self.d_from.setDate(self.d_from.date().addYears(-1))
        self.d_to = date_edit()
        for d in (self.d_from, self.d_to):
            d.dateChanged.connect(self.reload)
        bar.addWidget(QLabel("From:"))
        bar.addWidget(self.d_from)
        bar.addWidget(QLabel("To:"))
        bar.addWidget(self.d_to)
        bar.addWidget(W.button("📄  Export PDF", slot=self.pdf))
        bar.addWidget(W.button("📊  Export Excel", slot=self.excel))
        v.addLayout(bar)

        self.summary = QLabel()
        self.summary.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER};"
                                   "border-radius:8px; padding:10px;")
        self.summary.setTextFormat(Qt.RichText)
        v.addWidget(self.summary)

        self.table = W.DataTable()
        v.addWidget(self.table, 1)
        v.addWidget(ShareBar(db, lambda: self.last_pdf, self))

    def pick(self):
        sel = ItemPicker.pick(self.db, self, multi=False)
        if sel:
            self.load_item(sel[0]["id"])

    def load_item(self, item_id: int):
        self.item = dict(self.db.one("SELECT * FROM items WHERE id=?", (item_id,)))
        self.reload()

    def reload(self):
        if not self.item:
            return
        it = dict(self.db.one("SELECT * FROM items WHERE id=?", (self.item["id"],)))
        self.item = it
        s = S.item_movement_summary(self.db, it["id"], iso(self.d_from), iso(self.d_to))
        status = S.stock_status(self.db, it)
        col = S.STATUS_COLORS[status]
        mn, crit = S.item_thresholds(self.db, it)
        self.lbl.setText(f"{it['code']} — {it['description']}")
        self.summary.setText(
            f"<table width='100%'><tr>"
            f"<td>Opening Balance<br><b>{s['opening']:g}</b></td>"
            f"<td style='color:{W.GREEN}'>+ Received<br><b>{s['received']:g}</b></td>"
            f"<td style='color:{W.GREEN}'>+ Returns<br><b>{s['returned']:g}</b></td>"
            f"<td style='color:{W.GREEN}'>+ Transfers In<br><b>{s['transfer_in']:g}</b></td>"
            f"<td style='color:{W.ORANGE}'>− Issued<br><b>{s['issued']:g}</b></td>"
            f"<td style='color:{W.ORANGE}'>− Transfers Out<br><b>{s['transfer_out']:g}</b></td>"
            f"<td>± Adjustments<br><b>{s['adj_in'] - s['adj_out']:+g}</b></td>"
            f"<td style='color:{W.NAVY}'>= Current Balance<br><b>{s['closing']:g}</b> {it['uom']}</td>"
            f"<td style='color:{col}'>Status<br><b>{status}</b><br>"
            f"<span style='font-size:10px'>warn ≤ {mn:g} · critical ≤ {crit:g}</span></td>"
            f"<td>Location<br><b>{it['warehouse']} / {it['location']} / {it['rack']}</b></td>"
            f"</tr></table>")
        rows = [[h["txn_date"], h["txn_type"], h["doc_no"], h["qty_in"] or "", h["qty_out"] or "",
                 h["balance_after"], h["warehouse"], h["location"], h["party"], h["reason"],
                 h["username"]]
                for h in S.item_history(self.db, it["id"])
                if iso(self.d_from) <= h["txn_date"] <= iso(self.d_to)]
        self.table.fill(["Date", "Transaction", "Document No", "In", "Out", "Balance After",
                         "Warehouse", "Location", "Party / Received By", "Reason", "User"], rows)

    def pdf(self):
        if not self.item:
            W.error_box(self, "Choose an item first.")
            return
        self.last_pdf = D.item_history_pdf(self.db, self.item["id"])
        D.open_path(self.last_pdf)

    def excel(self):
        if not self.item:
            return
        f = D.export_excel(self.db, f"History {self.item['code']}", self.table.headers(),
                           self.table.all_rows())
        D.open_path(f)


# ============================================================= global search
class SearchPage(QWidget):
    openItem = Signal(int)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        self.box = W.SearchBox("Search everything: item code, description, barcode, UOM, category, "
                               "brand, location, DN number, MR number, supplier, date...")
        self.box.setMinimumHeight(42)
        self.box.setStyleSheet("font-size:15px;")
        self.box.textChanged.connect(self.run)
        v.addWidget(self.box)
        self.tabs = QTabWidget()
        self.t_items, self.t_docs, self.t_moves = W.DataTable(), W.DataTable(), W.DataTable()
        self.t_items.doubleClicked.connect(self._open_item)
        self.tabs.addTab(self.t_items, "Items")
        self.tabs.addTab(self.t_docs, "Documents")
        self.tabs.addTab(self.t_moves, "Stock Movements")
        v.addWidget(self.tabs, 1)
        self.res: dict = {}

    def focus(self):
        self.box.setFocus()
        self.box.selectAll()

    def run(self):
        t = self.box.text().strip()
        if len(t) < 1:
            for tb in (self.t_items, self.t_docs, self.t_moves):
                tb.setRowCount(0)
            return
        r = S.global_search(self.db, t)
        self.res = r
        self.t_items.fill(["Code", "Description", "Category", "UOM", "Balance", "Warehouse",
                           "Location", "Barcode", "Status"],
                          [[i["code"], i["description"], i["category"], i["uom"],
                            round(i["balance"], 2), i["warehouse"], i["location"], i["barcode"],
                            i["status"]] for i in r["items"]], status_col=8)
        self.t_docs.fill(["Document", "Type", "Date", "Status", "Party", "Project", "Reference"],
                         [[d["doc_no"], d["doc_type"], d["doc_date"], d["status"],
                           d["supplier"] or d["issued_to"] or d["returned_by"], d["project"],
                           d["reference"] or d["linked_doc"]] for d in r["documents"]])
        self.t_moves.fill(["Date", "Type", "Item", "Document", "In", "Out", "Balance", "Party"],
                          [[m["txn_date"], m["txn_type"], m["item_code"], m["doc_no"],
                            m["qty_in"] or "", m["qty_out"] or "", m["balance_after"], m["party"]]
                           for m in r["movements"]])
        self.tabs.setTabText(0, f"Items ({len(r['items'])})")
        self.tabs.setTabText(1, f"Documents ({len(r['documents'])})")
        self.tabs.setTabText(2, f"Stock Movements ({len(r['movements'])})")

    def _open_item(self):
        r = self.t_items.currentRow()
        if r < 0:
            return
        code = self.t_items.item(r, 0).text()
        it = self.db.one("SELECT id FROM items WHERE code=?", (code,))
        if it:
            self.openItem.emit(it["id"])


# ================================================================ audit page
class AuditPage(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        bar = QHBoxLayout()
        self.search = W.SearchBox("Filter the audit trail...")
        self.search.textChanged.connect(lambda t: self.table.filter_rows(t))
        bar.addWidget(self.search, 1)
        bar.addWidget(W.button("🔄  Refresh", slot=self.reload))
        bar.addWidget(W.button("📊  Export Excel", slot=self.export))
        v.addLayout(bar)
        self.table = W.DataTable()
        v.addWidget(self.table, 1)
        self.reload()

    def reload(self):
        title, cols, rows = reports.build_report(self.db, "Audit Trail Report", {})
        self.table.fill(cols, rows)

    def export(self):
        f = D.export_excel(self.db, "Audit Trail", self.table.headers(), self.table.all_rows())
        D.open_path(f)
