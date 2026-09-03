"""Stock In (GRN), Stock Out / Delivery Note, Returns, Transfers, Adjustments, Counts."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, QTime, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QMenu,
                               QLineEdit, QPlainTextEdit, QSizePolicy, QSplitter, QTabWidget,
                               QLayout, QTimeEdit, QVBoxLayout, QWidget)

from ..core import config, documents as D, material as M, reports, signatories as SG
from ..core import services as S
from ..core.database import Database
from . import widgets as W
from .common import (AdjustStockDialog, BarcodeBar, ExcelPasteDialog, ItemPicker, LineTable,
                     ShareBar, clipboard_attachment_entries, date_edit, iso, lookup,
                     store_attachment_file)
from .signature_ui import SignatureBar


class _TxnPage(QWidget):
    """Shared skeleton: header form + barcode bar + line grid + totals + actions."""
    dataChanged = Signal()

    MODE = "IN"
    TITLE = "Transaction"

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        self.last_pdf: Path | None = None
        self.attachments: list[dict[str, object] | str] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(10)

        head = W.Card("")
        head.v.setContentsMargins(0, 0, 0, 0)
        head.v.setSpacing(0)

        # ---- coloured title banner (colours configurable in Settings)
        self.header_banner = QWidget()
        self.header_banner.setObjectName("FormHeader")
        title_row = QHBoxLayout(self.header_banner)
        title_row.setContentsMargins(14, 8, 10, 8)
        title_row.setSpacing(10)
        self.title_lbl = QLabel(self.TITLE)
        self.title_lbl.setObjectName("FormHeaderTitle")
        title_row.addWidget(self.title_lbl)
        title_row.addStretch(1)
        self.summary_lbl = QLabel("")
        self.summary_lbl.setObjectName("FormHeaderSub")
        title_row.addWidget(self.summary_lbl)
        # NOTE: QPushButton.clicked emits clicked(bool checked=False). Passing the
        # bound method straight in made Qt call toggle_header(False) on EVERY
        # click, i.e. "always hide" -- a one-way latch that could never reopen.
        # The lambda swallows the checked flag so the call really toggles.
        self.btn_collapse = W.button("▲  Hide details",
                                     slot=lambda *_: self.toggle_header(),
                                     tip="Collapse the header to give the item table more "
                                         "room  (Ctrl+H)", shortcut="Ctrl+H")
        self.btn_collapse.setObjectName("FormHeaderBtn")
        title_row.addWidget(self.btn_collapse)
        head.v.addWidget(self.header_banner)

        self.form_host = QWidget()
        self.form_grid = QGridLayout(self.form_host)
        self.form_grid.setContentsMargins(14, 10, 14, 10)
        self.form_grid.setHorizontalSpacing(14)
        self.form_grid.setVerticalSpacing(6)
        head.v.addWidget(self.form_host)
        self.head_card = head
        self.form_host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        head.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        v.addWidget(head, 0)
        self.build_form()
        # lock in the natural height AFTER the fields exist, so the item table
        # can never squash the form (rows are 48px + 6px spacing)
        # Let the grid drive the height; forcing minimums here runs after the
        # parent layout is built and makes the card overlap the next widget.
        self._form_min_h = 0
        self._card_min_h = 0
        self.form_grid.setSizeConstraint(QLayout.SetMinimumSize)
        self.form_host.updateGeometry()
        self.head_card.updateGeometry()

        self.scanner = BarcodeBar(db)
        self.scanner.scanned.connect(lambda it: self.lines.add_items([it]))
        v.addWidget(self.scanner)
        self._build_draft_bar(v)
        if hasattr(self, "build_pr_bar"):
            self.build_pr_bar(v)

        row = QHBoxLayout()
        row.addWidget(W.button("➕  Add Items  (F3)", "Primary", self.add_items, shortcut="F3"))
        row.addWidget(W.button("🗑  Remove Line  (Del)", slot=lambda: self.lines.remove_selected()))
        row.addWidget(W.button("🧹  Clear All", slot=self.clear_all))
        row.addWidget(W.button("📋  Paste from Excel", slot=self.paste_from_excel,
                               tip="Paste item lines copied from an Excel sheet",
                               shortcut="Ctrl+Shift+V"))
        row.addWidget(W.button("📊  Export to Excel", slot=self.export_lines_excel,
                               tip="Save the lines below as a branded Excel sheet"))
        if self.MODE in ("OUT", "TRANSFER"):
            row.addWidget(W.button("⚖  Adjust Stock  (F4)", slot=self.adjust_stock,
                                   tip="Correct the system quantity of the selected item",
                                   shortcut="F4"))
            row.addWidget(W.button("🔄  Refresh Stock", slot=self.refresh_availability,
                                   tip="Re-read the available quantities from the database"))
        row.addWidget(W.button("📎  Attach Document", slot=self.attach,
                               tip="Choose supporting files to append after the document PDF"))
        row.addWidget(W.button("📋  Paste Attachment", slot=self.paste_attachment,
                               tip="Paste a copied file or screenshot from the clipboard; "
                                   "it will be appended after the document pages"))
        row.addWidget(W.button("🧹  Clear Attachments", slot=self.clear_attachments,
                               tip="Remove the pending attachments before saving"))
        self.attach_lbl = QLabel("")
        self.attach_lbl.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        self.attach_lbl.setToolTip("Supporting documents that will be saved with this record")
        row.addWidget(self.attach_lbl)
        row.addStretch(1)
        self.totals = QLabel()
        self.totals.setStyleSheet(f"color:{W.NAVY}; font-weight:700; font-size:13px;")
        row.addWidget(self.totals)
        v.addLayout(row)

        self.lines = LineTable(db, self.MODE)
        self.lines.changed.connect(self.update_totals)
        self.lines.pasteRequested.connect(self.paste_from_excel)
        self.lines.rowMenuRequested.connect(self._row_menu)
        self.lines.availabilityEdited.connect(self._availability_edited)
        self.lines.setMinimumHeight(130)      # always show several rows
        self.lines.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self.lines, 10)           # takes all remaining vertical space

        if getattr(self, "SIG_DOC_TYPE", ""):
            sig_card = W.Card("✍  Signatories on this document  "
                              "(defaults come from Settings → Signatories)")
            self.sig_bar = SignatureBar(db, self.SIG_DOC_TYPE)
            sig_card.add(self.sig_bar)
            sig_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            v.addWidget(sig_card, 0)
            self._link_signature_fields()

        act = QHBoxLayout()
        self.build_actions(act)
        v.addLayout(act)
        self.update_totals()
        if not db.get_bool(f"form_expanded_{self.__class__.__name__}", True):
            self.toggle_header(False)

    # -------------------------------------------------------------- helpers
    # ------------------------------------------------------- draft editing
    DRAFT_TYPE = ""          # "DN" / "GRN" — set by pages that can edit drafts

    def _build_draft_bar(self, parent_layout) -> None:
        """Amber strip shown only while an existing DRAFT is being edited."""
        self.draft_id: int | None = None
        self.draft_no: str = ""
        self.draft_status: str = ""
        self.draft_bar = QWidget()
        self.draft_bar.setStyleSheet(
            f"background:{W.AMBER}; border-radius:6px;")
        row = QHBoxLayout(self.draft_bar)
        row.setContentsMargins(12, 6, 8, 6)
        row.setSpacing(10)
        self.draft_lbl = QLabel("")
        self.draft_lbl.setStyleSheet("color:white; font-weight:700;")
        row.addWidget(self.draft_lbl, 1)
        row.addWidget(W.button("✖  Cancel editing", slot=self.cancel_draft_edit,
                               tip="Leave the draft untouched and start a new document"))
        self.draft_bar.setVisible(False)
        parent_layout.addWidget(self.draft_bar)

    def editing_draft(self) -> bool:
        return bool(getattr(self, "draft_id", None))

    def load_draft(self, doc_id: int) -> bool:
        """Re-open a saved draft, or reopen a reversed DN / GRN for correction."""
        if not self.DRAFT_TYPE:
            W.error_box(self, "This form cannot edit drafts.")
            return False
        try:
            head, lines = S.load_draft(self.db, doc_id)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return False
        if head["doc_type"] != self.DRAFT_TYPE:
            W.error_box(self, f"{head['doc_no']} is a {head['doc_type']}, "
                              "it cannot be opened on this form.")
            return False
        if head["status"] not in ("DRAFT", "REVERSED"):
            W.error_box(self, f"{head['doc_no']} is {head['status'].lower()} — only "
                              "drafts or reversed documents can be edited here.\n\n"
                              "Use 'Reverse / Correct' for a finalized document.")
            return False
        self.attachments = []
        self._refresh_attach_label()
        rows = []
        for l in lines:
            it = self.db.one("SELECT * FROM items WHERE id=?", (l["item_id"],))
            d = dict(it) if it else {"id": l["item_id"], "code": l["item_code"],
                                     "description": l["description"], "uom": l["uom"],
                                     "balance": 0}
            d.update({"qty": l["qty"], "unit_cost": l["unit_cost"],
                      "pr_no": (l["pr_no"] if "pr_no" in l.keys() else "") or "",
                      "remarks": l["remarks"] or "", "batch": l["batch"] or "",
                      "location": l["location"] or ""})
            rows.append(d)
        self.lines.load_lines(rows)
        self.apply_draft_header(head)
        self.draft_id = int(head["id"])
        self.draft_no = head["doc_no"]
        self.draft_status = head["status"]
        if head["status"] == "REVERSED":
            self.draft_lbl.setText(
                f"↺  Re-opening reversed {head['doc_no']}  ({head['doc_date']}) — "
                "stock was already corrected. Save as Draft or Finalize to reuse the same number.")
        else:
            self.draft_lbl.setText(
                f"✏  Editing draft {head['doc_no']}  ({head['doc_date']}) — change any "
                "quantity and press Update Draft, or Finalize to post the stock.")
        self.draft_bar.setVisible(True)
        self.update_totals()
        return True

    def apply_draft_header(self, head: dict) -> None:
        """Fill the form fields from a stored document (overridden per page)."""

    def cancel_draft_edit(self) -> None:
        was = self.draft_no
        self.attachments = []
        self._refresh_attach_label()
        self.clear_draft_mode()
        self.lines.clear_lines()
        self.reset_form()
        if was:
            W.toast(self, f"{was} left unchanged.")

    def clear_draft_mode(self) -> None:
        self.draft_id = None
        self.draft_no = ""
        self.draft_status = ""
        if hasattr(self, "draft_bar"):
            self.draft_bar.setVisible(False)

    def add_row(self, r: int, c: int, label: str, widget: QWidget, span: int = 1):
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{W.MUTED}; font-size:11px; font-weight:600;")
        lbl.setFixedHeight(15)
        widget.setMinimumHeight(28)
        box = QVBoxLayout()
        box.setSpacing(2)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(lbl)
        box.addWidget(widget)
        wrap = QWidget()
        wrap.setLayout(box)
        wrap.setMinimumHeight(48)
        wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.form_grid.addWidget(wrap, r, c, 1, span)
        return widget

    def toggle_header(self, force: bool | None = None):
        """Show/hide the header form. `force` None = flip, True/False = set.

        Callers connected to a Qt signal must pass nothing -- see the lambda on
        `btn_collapse`.
        """
        show = (not self.form_host.isVisible()) if force is None else bool(force)
        self.form_host.setVisible(show)
        # release the reserved height so the card shrinks to just the banner
        self.form_host.setMaximumHeight(16777215 if show else 0)
        self.head_card.setMaximumHeight(16777215 if show else
                                        self.header_banner.sizeHint().height() + 4)
        self.head_card.updateGeometry()
        self.btn_collapse.setText("▲  Hide details" if show else "▼  Show details")
        self.summary_lbl.setText("" if show else self.header_summary())
        # persist the operator's preference per screen
        self.db.set_setting(f"form_expanded_{self.__class__.__name__}", int(show))

    def header_summary(self) -> str:
        """One-line recap shown while the header is collapsed."""
        bits = []
        for attr, label in (("from_loc", "From"), ("project", "Project"),
                            ("issued", "Issued to"),
                            ("supplier", "Supplier"), ("ref", "Ref"),
                            ("wh", "Warehouse"), ("reason", "Reason")):
            w = getattr(self, attr, None)
            if w is None:
                continue
            txt = w.currentText() if hasattr(w, "currentText") else w.text()
            if txt:
                bits.append(f"{label}: {txt}")
        return "   ·   ".join(bits) if bits else "(header details hidden)"

    def build_form(self):
        raise NotImplementedError

    def build_actions(self, layout: QHBoxLayout):
        layout.addWidget(W.button("💾  Save && Finalize  (Ctrl+S)", "Accent", self.save,
                                  shortcut="Ctrl+S"))
        layout.addStretch(1)
        layout.addWidget(ShareBar(self.db, lambda: self.last_pdf, self))

    def add_items(self):
        picked = ItemPicker.pick(self.db, self)
        if picked:
            self.lines.add_items(picked)

    def clear_all(self):
        if self.lines.rowCount() and W.confirm(self, "Clear all lines?"):
            self.lines.clear_lines()

    def attach(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Attach supporting documents")
        added = 0
        for f in files:
            try:
                dest = store_attachment_file(f)
            except OSError:
                dest = Path(f)
            self.attachments.append({"file_path": str(dest), "source": "file", "page_order": 1})
            added += 1
        if added:
            self._refresh_attach_label()
            W.toast(self, f"{added} attachment(s) added.")

    def paste_attachment(self):
        try:
            added = clipboard_attachment_entries()
        except ValueError as exc:
            W.error_box(self, str(exc))
            return 0
        self.attachments.extend(added)
        self._refresh_attach_label()
        W.toast(self, f"{len(added)} clipboard attachment(s) added.")
        return len(added)

    def clear_attachments(self):
        if not self.attachments:
            return 0
        n = len(self.attachments)
        self.attachments = []
        self._refresh_attach_label()
        W.toast(self, f"Cleared {n} pending attachment(s).", "warn")
        return n

    def _attachment_entry(self, rec) -> dict[str, object]:
        if isinstance(rec, dict):
            path = str(rec.get("file_path") or rec.get("path") or "")
            source = str(rec.get("source") or "file")
            try:
                order = int(rec.get("page_order") or (2 if source == "clipboard" else 1))
            except (TypeError, ValueError):
                order = 2 if source == "clipboard" else 1
            return {"file_path": path, "source": source, "page_order": order}
        return {"file_path": str(rec), "source": "file", "page_order": 1}

    def _signature_fields(self) -> dict[str, str]:
        """Names typed into the form's own header boxes, keyed by signature role."""
        out: dict[str, str] = {}
        for role, attr in (("Issued By", "issued_by"), ("Delivered By", "delivered_by"),
                           ("Handover To", "handover_to"), ("Received By", "recv"),
                           ("Returned By", "by"), ("Counted By", "by")):
            f = getattr(self, attr, None)
            if f is not None and hasattr(f, "text") and f.text().strip():
                out.setdefault(role, f.text().strip())
        return out

    def showEvent(self, e):
        super().showEvent(e)
        if hasattr(self, "sig_bar"):
            self.sig_bar.refresh_names()

    def _link_signature_fields(self):
        """Mirror the signatory combos and the matching header text boxes so the
        operator only ever types a name once."""
        pairs = {"Issued By": "issued_by", "Delivered By": "delivered_by",
                 "Handover To": "handover_to", "Received By": "recv",
                 "Returned By": "by", "Store Keeper": "recv", "Counted By": "by"}
        for role, attr in pairs.items():
            cb = self.sig_bar.combos.get(role)
            field = getattr(self, attr, None)
            if cb is None or field is None:
                continue
            if cb.currentText() and not field.text():
                field.setText(cb.currentText())

            def sync_to_field(text, f=field):
                if text:
                    f.setText(text)

            def sync_to_combo(text, c=cb):
                if text and c.currentText() != text:
                    c.setCurrentText(text)

            cb.currentTextChanged.connect(sync_to_field)
            field.textChanged.connect(sync_to_combo)

    def _refresh_attach_label(self):
        if not hasattr(self, "attach_lbl"):
            return
        items = [self._attachment_entry(a) for a in self.attachments]
        n = len(items)
        pasted = sum(1 for a in items if a["source"] == "clipboard")
        names = ", ".join(Path(str(a["file_path"])).name for a in items[:3])
        extra = "" if not pasted else f"  ·  {pasted} pasted"
        self.attach_lbl.setText(
            "" if not n else
            f"📎 {n} file(s): {names}" + ("..." if n > 3 else "") + extra)

    # ------------------------------------------------- Excel paste / export
    def paste_from_excel(self):
        """Open the paste sheet, pre-filled from the clipboard."""
        pr = ""
        if hasattr(self, "pr_no"):
            pr = self.pr_no.text().strip()
        dlg = ExcelPasteDialog(self.db, self.MODE, pr, self)
        if dlg.exec() != QDialog.Accepted:
            return 0, 0
        rows = dlg.result_rows()
        if not rows:
            W.error_box(self, "No line could be matched to the item master.")
            return 0, 0
        added, updated = self.lines.merge_rows(rows)
        skipped = sum(1 for r in dlg.rows if r["_status"] == "unknown")
        msg = f"{added} line(s) added"
        if updated:
            msg += f", {updated} updated"
        if skipped and dlg.chk_skip.isChecked():
            msg += f", {skipped} unknown item(s) skipped"
        W.toast(self, msg + ".")
        return added, updated

    def export_lines_excel(self):
        """Save the grid — exactly as it looks — to a branded Excel sheet."""
        self.lines.commit_edits()
        cols, rows = self.lines.grid_rows()
        if not rows:
            W.error_box(self, "There are no lines to export yet.")
            return None
        no = getattr(self, "no", None)
        ref = (no.text().strip() if no is not None else "") or "Draft"
        title = f"{self.TITLE.split('  ')[-1].strip()} {ref}".strip()
        try:
            path = D.export_excel(self.db, title, cols, rows)
        except Exception as exc:            # noqa: BLE001
            W.error_box(self, f"The Excel file could not be written.\n\n{exc}")
            return None
        W.toast(self, f"Exported {len(rows)} line(s) → {Path(path).name}")
        try:
            D.open_path(path)
        except Exception:               # noqa: BLE001 - the file is written either way
            pass
        return path

    # --------------------------------------------- inline stock adjustment
    def _can_adjust(self) -> bool:
        session = getattr(self.window(), "session", None)
        if session is not None and hasattr(session, "can") and not session.can("adjustments"):
            W.error_box(self, "Your role is not allowed to post stock adjustments.")
            return False
        return True

    def _current_row(self) -> int:
        rows = sorted({i.row() for i in self.lines.selectedIndexes()})
        return rows[0] if rows else -1

    def adjust_stock(self, row: int = -1, counted: float | None = None):
        """Correct the system quantity of one line's item (posts an ADJ doc)."""
        if row is None or row < 0:
            row = self._current_row()
        if row < 0 or row >= len(self.lines.items):
            W.error_box(self, "Select the line whose stock you want to correct first.")
            return None
        if not self._can_adjust():
            if counted is not None:
                self.lines.set_available(row, self.lines.items[row].get("balance") or 0)
            return None
        wh = self.wh.currentText() if hasattr(self, "wh") else ""
        dlg = AdjustStockDialog(self.db, self.lines.items[row], self,
                                warehouse=wh, counted=counted)
        ok = dlg.exec() == QDialog.Accepted
        if not ok:
            self.lines.set_available(row, dlg.system_qty)
            return None
        self.lines.set_available(row, dlg.new_balance())
        self.update_totals()
        self.dataChanged.emit()
        W.toast(self, f"Adjustment {dlg.doc_no} posted — "
                      f"{self.lines.items[row].get('code','')} is now "
                      f"{dlg.new_balance():g}.")
        return dlg.doc_no

    def _availability_edited(self, row: int, typed: float):
        """The operator typed a real count into the Available column."""
        self.adjust_stock(row, counted=typed)

    def refresh_availability(self):
        n = self.lines.refresh_availability()
        W.toast(self, f"{n} quantity(ies) updated from the database." if n
                else "All available quantities are already up to date.")
        return n

    def _row_menu(self, row: int, pos):
        menu = QMenu(self)
        act_paste = menu.addAction("📋  Paste lines from Excel")
        act_copy = menu.addAction("📄  Copy grid to clipboard")
        act_xls = menu.addAction("📊  Export lines to Excel")
        act_adj = act_refresh = None
        if self.MODE in ("OUT", "TRANSFER") and 0 <= row < len(self.lines.items):
            menu.addSeparator()
            act_adj = menu.addAction(
                f"⚖  Adjust inventory quantity of "
                f"{self.lines.items[row].get('code','')}")
            act_refresh = menu.addAction("🔄  Refresh available quantities")
        chosen = menu.exec(pos)
        if chosen is None:
            return
        if chosen is act_paste:
            self.paste_from_excel()
        elif chosen is act_copy:
            n = self.lines.copy_to_clipboard()
            W.toast(self, f"{n} line(s) copied — paste them straight into Excel.")
        elif chosen is act_xls:
            self.export_lines_excel()
        elif chosen is act_adj:
            self.adjust_stock(row)
        elif chosen is act_refresh:
            self.refresh_availability()

    def update_totals(self):
        q = self.lines.total_qty()
        txt = f"Lines: {self.lines.rowCount()}   |   Total Qty: {q:,.2f}"
        val = self.lines.total_value()
        if val:
            txt += f"   |   Value: {self.db.get_setting('currency','')} {val:,.2f}"
        self.totals.setText(txt)

    def _register_attachments(self, doc_type: str, doc_no: str):
        for a in self.attachments:
            ent = self._attachment_entry(a)
            self.db.execute(
                "INSERT INTO attachments(doc_type,doc_no,file_path,source,page_order) VALUES(?,?,?,?,?)",
                (doc_type, doc_no, ent["file_path"], ent["source"], ent["page_order"]))
        self.db.commit()
        self.attachments = []
        self._refresh_attach_label()

    def _after_post(self, doc_type: str, doc_no: str, msg: str):
        self._register_attachments(doc_type, doc_no)
        if hasattr(self, "sig_bar"):
            self.sig_bar.apply_to_document(doc_no, self._signature_fields())
        d = self.db.one("SELECT id FROM documents WHERE doc_type=? AND doc_no=?",
                        (doc_type, doc_no))
        self.last_pdf = D.document_pdf(self.db, d["id"])
        self.lines.clear_lines()
        self.reset_form()
        self.dataChanged.emit()
        W.toast(self, msg)
        if W.confirm(self, f"{msg}\n\nOpen the PDF now?", "Document ready"):
            D.open_path(self.last_pdf)

    def reset_form(self):
        pass

    def save(self):
        raise NotImplementedError


# =================================================================== STOCK IN
class StockInPage(_TxnPage):
    MODE = "IN"
    SIG_DOC_TYPE = "GRN"
    DRAFT_TYPE = "GRN"
    TITLE = "📥  Stock Receiving  —  Goods Receipt Note"

    def build_form(self):
        db = self.db
        self.no = QLineEdit()
        self.no.setPlaceholderText("Auto-generated on save")
        self.no.setReadOnly(True)
        self.add_row(0, 0, "RECEIVING NUMBER", self.no)
        self.date = date_edit()
        self.add_row(0, 1, "DATE", self.date)
        self.supplier = W.combo([""] + lookup(db, "suppliers"), True)
        self.add_row(0, 2, "SUPPLIER", self.supplier)
        self.ref = QLineEdit()
        self.ref.setPlaceholderText("PO / MR reference")
        self.add_row(0, 3, "PO / MR REFERENCE", self.ref)
        self.wh = W.combo(lookup(db, "warehouses"), True)
        self.add_row(1, 0, "WAREHOUSE", self.wh)
        self.loc = QLineEdit()
        self.add_row(1, 1, "LOCATION", self.loc)
        self.recv = QLineEdit()
        self.add_row(1, 2, "RECEIVED BY", self.recv)
        self.remarks = QLineEdit()
        self.add_row(1, 3, "REMARKS", self.remarks)

    def reset_form(self):
        self.ref.clear()
        self.remarks.clear()
        self.clear_draft_mode()

    def build_actions(self, layout):
        self.btn_draft = W.button("💾  Save as Draft", slot=lambda: self.save(False),
                                  tip="Save without moving stock, edit later")
        layout.addWidget(self.btn_draft)
        layout.addWidget(W.button("💾  Save && Finalize  (Ctrl+S)", "Accent",
                                  lambda: self.save(True), shortcut="Ctrl+S"))
        layout.addStretch(1)
        layout.addWidget(ShareBar(self.db, lambda: self.last_pdf, self))

    def load_draft(self, doc_id: int) -> bool:
        ok = super().load_draft(doc_id)
        if ok:
            self.btn_draft.setText("💾  Save Again as Draft" if self.draft_status == "REVERSED"
                                   else "💾  Update Draft")
        return ok

    def clear_draft_mode(self) -> None:
        super().clear_draft_mode()
        if hasattr(self, "btn_draft"):
            self.btn_draft.setText("💾  Save as Draft")

    def apply_draft_header(self, head: dict) -> None:
        def g(k):
            try:
                return head[k] or ""
            except (KeyError, IndexError):
                return ""

        self.no.setText(g("doc_no"))
        if g("doc_date"):
            self.date.setDate(QDate.fromString(str(g("doc_date"))[:10], "yyyy-MM-dd"))
        self.supplier.setCurrentText(g("supplier"))
        self.ref.setText(g("reference"))
        if g("warehouse"):
            self.wh.setCurrentText(g("warehouse"))
        self.loc.setText(g("location"))
        self.recv.setText(g("received_by"))
        self.remarks.setText(g("remarks"))

    def save(self, finalize: bool = True):
        h = S.DocHeader(doc_type="GRN", doc_date=iso(self.date),
                        supplier=self.supplier.currentText(), reference=self.ref.text(),
                        warehouse=self.wh.currentText(), location=self.loc.text(),
                        received_by=self.recv.text(), remarks=self.remarks.text())
        posting = self.lines.to_lines()
        if self.editing_draft():
            doc_id, no = self.draft_id, self.draft_no
            was_reversed = self.draft_status == "REVERSED"
            try:
                S.update_draft(self.db, doc_id, h, posting)
                if finalize:
                    S.finalize_draft(self.db, doc_id)
            except S.StockError as exc:
                W.error_box(self, str(exc))
                return
            self.no.setText(no)
            self.clear_draft_mode()
            if finalize:
                self._after_post("GRN", no,
                                 (f"Goods Receipt {no} re-finalized after reversal — stock increased again."
                                  if was_reversed else
                                  f"Goods Receipt {no} updated and finalized — stock increased."))
            else:
                self._register_attachments("GRN", no)
                self.lines.clear_lines()
                self.reset_form()
                self.dataChanged.emit()
                W.toast(self, (f"Reversed {no} saved again as a draft with the same number."
                               if was_reversed else f"Draft {no} updated."), "warn")
            return
        try:
            no = S.post_receipt(self.db, h, posting, finalize)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.no.setText(no)
        if finalize:
            self._after_post("GRN", no, f"Goods Receipt {no} finalized — stock increased.")
        else:
            self._register_attachments("GRN", no)
            self.lines.clear_lines()
            self.reset_form()
            self.dataChanged.emit()
            W.toast(self, f"Draft {no} saved. Finalize it later from Documents.", "warn")


# ============================================================ DELIVERY NOTE
class StockOutPage(_TxnPage):
    MODE = "OUT"
    SIG_DOC_TYPE = "DN"
    DRAFT_TYPE = "DN"
    TITLE = "📤  Stock Issue  —  Delivery Note Maker (multi-PR)"

    def build_form(self):
        db = self.db
        self.no = QLineEdit()
        self.no.setReadOnly(True)
        self.no.setPlaceholderText("Auto-generated on save")
        self.add_row(0, 0, "DN NUMBER", self.no)
        self.date = date_edit()
        self.add_row(0, 1, "DATE", self.date)
        self.project = W.combo([""] + lookup(db, "sites"), True)
        self.add_row(0, 2, "PROJECT / SITE", self.project)
        self.dept = QLineEdit()
        self.add_row(0, 3, "DEPARTMENT", self.dept)
        self.req = QLineEdit()
        self.add_row(1, 0, "REQUESTED BY", self.req)
        self.issued = QLineEdit()
        self.add_row(1, 1, "ISSUED TO", self.issued)
        self.ref = QLineEdit()
        self.ref.setPlaceholderText("MR number / overall reference")
        self.add_row(1, 2, "REFERENCE / MR NUMBER", self.ref)
        self.purpose = QLineEdit()
        self.add_row(1, 3, "PURPOSE", self.purpose)
        self.wh = W.combo(lookup(db, "warehouses"), True)
        self.wh.setToolTip("Warehouse whose stock is deducted")
        self.remarks = QLineEdit()

        # ---- gate-pass row: From / Vehicle / In Time / Out Time
        self.from_loc = W.combo(lookup(db, "warehouses"), True)
        self.from_loc.setToolTip("Location the material is dispatched FROM")
        self.add_row(2, 0, "FROM (DISPATCH LOCATION)", self.from_loc)
        vd = QHBoxLayout()
        vd.setContentsMargins(0, 0, 0, 0)
        vd.setSpacing(4)
        self.vehicle = QLineEdit()
        self.vehicle.setPlaceholderText("Plate no.")
        vd.addWidget(self.vehicle, 3)
        self.driver = QLineEdit()
        self.driver.setPlaceholderText("Driver")
        vd.addWidget(self.driver, 2)
        w_vd = QWidget()
        w_vd.setLayout(vd)
        self.add_row(2, 1, "VEHICLE  /  DRIVER", w_vd)

        tin = QHBoxLayout()
        tin.setContentsMargins(0, 0, 0, 0)
        tin.setSpacing(4)
        self.in_time = QTimeEdit()
        self.in_time.setDisplayFormat("hh:mm AP")
        self.in_time.setTime(QTime.currentTime())
        tin.addWidget(self.in_time, 1)
        b_in = W.button("Now", slot=lambda: self.in_time.setTime(QTime.currentTime()),
                        tip="Stamp the current time")
        b_in.setMaximumWidth(52)
        tin.addWidget(b_in)
        w_in = QWidget()
        w_in.setLayout(tin)
        self.add_row(2, 2, "IN TIME", w_in)

        tout = QHBoxLayout()
        tout.setContentsMargins(0, 0, 0, 0)
        tout.setSpacing(4)
        self.out_time = QTimeEdit()
        self.out_time.setDisplayFormat("hh:mm AP")
        self.out_time.setTime(QTime.currentTime())
        tout.addWidget(self.out_time, 1)
        b_out = W.button("Now", slot=lambda: self.out_time.setTime(QTime.currentTime()),
                         tip="Stamp the current time")
        b_out.setMaximumWidth(52)
        tout.addWidget(b_out)
        w_out = QWidget()
        w_out.setLayout(tout)
        self.add_row(2, 3, "OUT TIME", w_out)

        self.add_row(3, 0, "WAREHOUSE (STOCK SOURCE)", self.wh)
        self.add_row(3, 1, "REMARKS", self.remarks, 3)
        self.from_loc.setCurrentText(self.wh.currentText())
        self.wh.currentTextChanged.connect(
            lambda t: self.from_loc.setCurrentText(t) if not self.from_loc.currentText() else None)
        # Issued By / Delivered By / Handover To / Received By live in the
        # signature panel under the item table -- they are not repeated here.
        self.recv = QLineEdit()
        self.issued_by = QLineEdit()
        self.delivered_by = QLineEdit()
        self.handover_to = QLineEdit()
        for _w in (self.recv, self.issued_by, self.delivered_by, self.handover_to):
            _w.setVisible(False)


    def build_pr_bar(self, parent_layout):
        """Row of PR controls: type a PR, then every item you add is tagged with it."""
        bar = QHBoxLayout()
        lbl = QLabel("📋 Current PR / MR No.:")
        lbl.setStyleSheet(f"font-weight:600; color:{W.NAVY};")
        bar.addWidget(lbl)
        self.pr_input = QLineEdit()
        self.pr_input.setPlaceholderText("PR / MR number  —  items added next get this reference")
        self.pr_input.setMinimumWidth(260)
        self.pr_input.setMaximumWidth(340)
        f = self.pr_input.font()
        f.setBold(True)
        self.pr_input.setFont(f)
        self.pr_input.textChanged.connect(
            lambda t: self.lines.set_default_pr(t))
        self.pr_input.returnPressed.connect(self.add_items)
        bar.addWidget(self.pr_input)
        bar.addWidget(W.button("Apply to selected rows", slot=self._apply_pr,
                               tip="Write this PR number into the selected rows "
                                   "(or all rows when nothing is selected)"))
        bar.addWidget(W.button("Fill down ▼", slot=self._fill_pr,
                               tip="Copy the PR of the current row into all rows below"))
        bar.addWidget(W.button("Clear PR", slot=lambda: self.pr_input.clear()))
        bar.addWidget(W.button("📋 Pick from Open PR / MR", slot=self.pick_from_open_request,
                               tip="Load item lines from open material requests / PRs"))
        self.pr_lbl = QLabel("")
        self.pr_lbl.setStyleSheet(f"color:{W.MUTED};")
        self.pr_lbl.setWordWrap(True)
        self.pr_lbl.setMinimumWidth(220)
        bar.addWidget(self.pr_lbl, 1)
        parent_layout.addLayout(bar)

    def _apply_pr(self):
        pr = self.pr_input.text().strip()
        n = self.lines.apply_pr_to_selection(pr)
        if n:
            W.toast(self, f"PR '{pr or '(blank)'}' applied to {n} row(s).")

    def _fill_pr(self):
        n = self.lines.fill_pr_down()
        W.toast(self, f"PR copied down into {n} row(s)." if n
                else "Select a row first, then Fill down.")

    def pick_from_open_request(self):
        picked = OpenRequestPicker.pick(self.db, self)
        if not picked:
            return
        self.lines.add_items(picked)
        mrs = []
        prs = []
        projects = []
        requesters = []
        for row in picked:
            if row.get("mr_no") and row["mr_no"] not in mrs:
                mrs.append(row["mr_no"])
            if row.get("pr_no") and row["pr_no"] not in prs:
                prs.append(row["pr_no"])
            if row.get("mr_project") and row["mr_project"] not in projects:
                projects.append(row["mr_project"])
            if row.get("requested_by") and row["requested_by"] not in requesters:
                requesters.append(row["requested_by"])
        if len(projects) == 1 and not self.project.currentText().strip():
            self.project.setCurrentText(projects[0])
        if len(requesters) == 1 and not self.req.text().strip():
            self.req.setText(requesters[0])
        if mrs and not self.ref.text().strip():
            self.ref.setText(", ".join(mrs))
        if len(prs) == 1 and not self.pr_input.text().strip():
            self.pr_input.setText(prs[0])
        W.toast(self, f"{len(picked)} open PR / MR line(s) added to the Delivery Note.")

    def _picked_request_links(self) -> list[tuple[int, float]]:
        links: list[tuple[int, float]] = []
        for row in range(min(self.lines.rowCount(), len(self.lines.items))):
            src = self.lines.items[row]
            line_id = src.get("mr_line_id")
            if not line_id:
                continue
            qty = self.lines._num(row, 4)
            if qty > 0:
                links.append((int(line_id), float(qty)))
        return links

    def update_totals(self):
        super().update_totals()
        if not hasattr(self, "pr_lbl"):
            return
        groups = self.lines.pr_summary()
        real = {k: v for k, v in groups.items() if k != "(no PR)"}
        if not groups:
            self.pr_lbl.setText("")
            return
        parts = [f"{k} ({v['lines']}×, {v['qty']:g})" for k, v in sorted(real.items())[:4]]
        extra = "" if len(real) <= 4 else f" +{len(real) - 4} more"
        blank = groups.get("(no PR)")
        txt = f"   {len(real)} PR(s):  " + "  ·  ".join(parts) + extra
        if blank:
            txt += f"   ⚠ {blank['lines']} line(s) without a PR number"
        self.pr_lbl.setText(txt)

    def build_actions(self, layout):
        self.btn_draft = W.button("💾  Save as Draft", slot=lambda: self.save(False),
                                  tip="Save without moving stock, edit later")
        layout.addWidget(self.btn_draft)
        layout.addWidget(W.button("✅  Finalize && Generate DN  (Ctrl+S)", "Accent",
                                  lambda: self.save(True), shortcut="Ctrl+S"))
        layout.addWidget(W.button("👁  A4 Preview", slot=self.preview,
                                  tip="Professional A4 preview before printing"))
        layout.addStretch(1)
        layout.addWidget(ShareBar(self.db, lambda: self.last_pdf, self))

    def load_draft(self, doc_id: int) -> bool:
        ok = super().load_draft(doc_id)
        if ok:
            self.btn_draft.setText("💾  Save Again as Draft" if self.draft_status == "REVERSED"
                                   else "💾  Update Draft")
        return ok

    def clear_draft_mode(self) -> None:
        super().clear_draft_mode()
        if hasattr(self, "btn_draft"):
            self.btn_draft.setText("💾  Save as Draft")

    def apply_draft_header(self, head: dict) -> None:
        def g(k):
            try:
                return head[k] or ""
            except (KeyError, IndexError):
                return ""

        self.no.setText(g("doc_no"))
        if g("doc_date"):
            self.date.setDate(QDate.fromString(str(g("doc_date"))[:10], "yyyy-MM-dd"))
        self.project.setCurrentText(g("project"))
        self.dept.setText(g("department"))
        self.req.setText(g("requested_by"))
        self.issued.setText(g("issued_to"))
        self.ref.setText(g("reference"))
        self.purpose.setText(g("purpose"))
        self.remarks.setText(g("remarks"))
        self.vehicle.setText(g("vehicle"))
        self.driver.setText(g("driver"))
        if g("warehouse"):
            self.wh.setCurrentText(g("warehouse"))
        self.from_loc.setCurrentText(g("from_location") or g("warehouse"))
        for role, value in (("Received By", g("received_by")),
                            ("Issued By", g("issued_by")),
                            ("Delivered By", g("delivered_by")),
                            ("Handover To", g("handover_to"))):
            if value and hasattr(self, "sig_bar"):
                cb = self.sig_bar.combos.get(role)
                if cb is not None:
                    cb.setCurrentText(value)
        self.recv.setText(g("received_by"))
        self.issued_by.setText(g("issued_by"))
        self.delivered_by.setText(g("delivered_by"))
        self.handover_to.setText(g("handover_to"))
        for fld, val in ((self.in_time, g("in_time")), (self.out_time, g("out_time"))):
            if val:
                t = QTime.fromString(str(val), "hh:mm AP")
                if t.isValid():
                    fld.setTime(t)

    def _sig(self, role: str, fallback) -> str:
        """Signature panel is the single source for the four handover roles."""
        v = self.sig_bar.role_value(role) if hasattr(self, "sig_bar") else ""
        return v or (fallback.text() if fallback is not None else "")

    def _header(self) -> S.DocHeader:
        recv = self._sig("Received By", self.recv)
        issued_by = self._sig("Issued By", self.issued_by)
        delivered_by = self._sig("Delivered By", self.delivered_by)
        handover_to = self._sig("Handover To", self.handover_to)
        # keep the hidden mirrors in step for exports and reuse
        self.recv.setText(recv)
        self.issued_by.setText(issued_by)
        self.delivered_by.setText(delivered_by)
        self.handover_to.setText(handover_to)
        hid, hph = (self.sig_bar.handover_identity()
                    if hasattr(self, "sig_bar") else ("", ""))
        return S.DocHeader(
            doc_type="DN", doc_date=iso(self.date), project=self.project.currentText(),
            department=self.dept.text(), requested_by=self.req.text(),
            issued_to=self.issued.text(), received_by=recv,
            reference=self.ref.text(), vehicle=self.vehicle.text(), driver=self.driver.text(),
            purpose=self.purpose.text(), warehouse=self.wh.currentText(),
            issued_by=issued_by, delivered_by=delivered_by,
            handover_to=handover_to, remarks=self.remarks.text(),
            handover_id=hid, handover_phone=hph,
            from_location=self.from_loc.currentText(),
            in_time=self.in_time.time().toString("hh:mm AP"),
            out_time=self.out_time.time().toString("hh:mm AP"))

    def reset_form(self):
        for w in (self.dept, self.req, self.issued, self.recv, self.ref, self.vehicle,
                  self.driver, self.purpose, self.remarks, self.pr_input,
                  self.issued_by, self.delivered_by, self.handover_to):
            w.clear()
        self.lines.set_default_pr("")
        self.clear_draft_mode()
        if hasattr(self, "sig_bar"):
            self.sig_bar.reset()

    def preview(self):
        lines = self.lines.to_lines()
        if not lines:
            W.error_box(self, "Add at least one item to preview the Delivery Note.")
            return
        h = self._header()
        rows = []
        for i, l in enumerate(lines, 1):
            it = self.db.one("SELECT code, description, uom FROM items WHERE id=?", (l.item_id,))
            rows.append([i, it["code"], it["description"], it["uom"], f"{l.qty:g}",
                         l.pr_no, l.remarks])
        PreviewDialog(self.db, "DELIVERY NOTE",
                      [("DN Number", "(on finalize)"), ("Date", h.doc_date),
                       ("Project / Site", h.project), ("Department", h.department),
                       ("Requested By", h.requested_by), ("Issued To", h.issued_to),
                       ("From", h.from_location), ("Vehicle", h.vehicle),
                       ("In Time", h.in_time), ("Out Time", h.out_time),
                       ("Issued By", h.issued_by), ("Delivered By", h.delivered_by),
                       ("Handover To (Driver)", h.handover_to),
                       ("Driver ID / Phone",
                        " · ".join(x for x in (h.handover_id, h.handover_phone) if x)),
                       ("Received By", h.received_by),
                       ("Reference / MR", h.reference), ("Purpose", h.purpose)],
                      ["Sr.", "Item Code", "Description", "UOM", "Quantity", "PR / MR No.",
                       "Remarks"], rows, self).exec()

    def save(self, finalize: bool = True):
        posting = self.lines.to_lines()
        picked_links = self._picked_request_links()
        missing = [l for l in posting if not (l.pr_no or "").strip()]
        if missing and finalize:
            if not W.confirm(
                    self, f"{len(missing)} of {len(posting)} line(s) have no PR number.\n\n"
                          "Continue and finalize the Delivery Note anyway?",
                    "Lines without a PR number"):
                return
        if finalize and picked_links:
            try:
                M.validate_picked_lines(self.db, picked_links)
            except S.StockError as exc:
                W.error_box(self, str(exc))
                return
        # ---- editing an existing draft: rewrite it instead of making a new one
        if self.editing_draft():
            doc_id, no = self.draft_id, self.draft_no
            was_reversed = self.draft_status == "REVERSED"
            try:
                S.update_draft(self.db, doc_id, self._header(), posting)
                if finalize:
                    S.finalize_draft(self.db, doc_id)
            except S.StockError as exc:
                W.error_box(self, str(exc))
                return
            self.no.setText(no)
            self.clear_draft_mode()
            if finalize:
                if picked_links:
                    try:
                        M.deliver_picked_lines(self.db, picked_links, no)
                    except Exception as exc:  # noqa: BLE001
                        W.error_box(self, f"Delivery Note {no} was finalized, but the linked PR/MR lines could not be updated.\n\n{exc}")
                        return
                self._after_post("DN", no,
                                 (f"Delivery Note {no} re-finalized after reversal — stock deducted again."
                                  if was_reversed else
                                  f"Delivery Note {no} updated and finalized — stock deducted."))
            else:
                self._register_attachments("DN", no)
                self.lines.clear_lines()
                self.reset_form()
                self.dataChanged.emit()
                W.toast(self,
                        (f"Reversed {no} saved again as a draft with the same number."
                         if was_reversed else
                         f"Draft {no} updated — {len(posting)} line(s), total qty {sum(l.qty for l in posting):g}."),
                        "warn")
            return
        try:
            no = S.post_issue(self.db, self._header(), posting, finalize)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.no.setText(no)
        if finalize:
            if picked_links:
                try:
                    M.deliver_picked_lines(self.db, picked_links, no)
                except Exception as exc:  # noqa: BLE001
                    W.error_box(self, f"Delivery Note {no} was finalized, but the linked PR/MR lines could not be updated.\n\n{exc}")
                    return
            self._after_post("DN", no, f"Delivery Note {no} finalized — stock deducted.")
        else:
            self._register_attachments("DN", no)
            self.lines.clear_lines()
            self.reset_form()
            self.dataChanged.emit()
            W.toast(self, f"Draft {no} saved. Finalize it later from Documents.", "warn")


class PreviewDialog(QDialog):
    """Simple on-screen A4 preview rendered as rich text."""

    def __init__(self, db: Database, title: str, pairs, cols, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{title} — A4 Preview")
        self.resize(820, 900)
        v = QVBoxLayout(self)
        from PySide6.QtWidgets import QTextBrowser
        tb = QTextBrowser()
        company = db.get_setting("company_name", "AURCO")
        info = "".join(
            f"<tr><td style='background:#eef3f8;padding:4px 7px;'><b>{k}</b></td>"
            f"<td style='padding:4px 7px;'>{v or '-'}</td></tr>" for k, v in pairs)
        head = "".join(f"<th style='background:#0b3d6b;color:white;padding:5px;'>{c}</th>"
                       for c in cols)
        body = "".join("<tr>" + "".join(
            f"<td style='padding:4px 6px;border-bottom:1px solid #dde;'>{c}</td>" for c in r)
            + "</tr>" for r in rows)
        tb.setHtml(f"""
        <div style='font-family:Segoe UI;'>
        <table width='100%' style='background:#0b3d6b;color:white;'><tr>
          <td style='padding:10px'><h2 style='margin:0'>{company.upper()}</h2>
          <div style='font-size:11px'>{db.get_setting('company_tagline','')}</div></td>
          <td align='right' style='padding:10px'><b>{title}</b></td></tr></table>
        <h2 style='color:#0b3d6b;text-align:center'>{title.title()}</h2>
        <table width='100%' cellspacing='0'>{info}</table><br>
        <table width='100%' cellspacing='0'><tr>{head}</tr>{body}</table>
        <br><br>
        <table width='100%'><tr>
          <td style='border-top:1px solid #0b3d6b;padding-top:4px'>Issued By</td>
          <td style='border-top:1px solid #0b3d6b;padding-top:4px'>Received By</td>
          <td style='border-top:1px solid #0b3d6b;padding-top:4px'>Approved By</td></tr></table>
        <p style='color:#888;font-size:10px;text-align:center'>
          {db.get_setting('doc_footer','')}<br>
          AURCO Inventory Manager | Created by {config.CREATED_BY}</p></div>""")
        v.addWidget(tb)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(W.button("Close", "Primary", self.accept))
        v.addLayout(h)


class OpenRequestPicker(QDialog):
    """Pick item lines from open PR / MR requests into the Delivery Note maker."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.rows: list[dict] = []
        self.selected: list[dict] = []
        self.setWindowTitle("Pick Items from Open PR / MR")
        self.resize(1320, 720)
        v = QVBoxLayout(self)

        note = QLabel(
            "Select one or more lines from open material requests. The chosen quantity "
            "is added to the Delivery Note with the same PR / MR number, and when the "
            "DN is finalized the request is updated automatically."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER}; border-radius:8px; padding:8px;")
        v.addWidget(note)

        flt = QHBoxLayout()
        self.f_text = W.SearchBox("Search MR / PR / project / item...")
        self.f_text.textChanged.connect(self.reload)
        self.f_project = W.SearchBox("Project / Site")
        self.f_project.textChanged.connect(self.reload)
        self.f_mr = W.SearchBox("MR Number")
        self.f_mr.textChanged.connect(self.reload)
        self.f_pr = W.SearchBox("PR Number")
        self.f_pr.textChanged.connect(self.reload)
        self.only_ready = QCheckBox("Only ready / prepared lines")
        self.only_ready.toggled.connect(self.reload)
        for w in (self.f_text, self.f_project, self.f_mr, self.f_pr, self.only_ready):
            flt.addWidget(w)
        flt.addWidget(W.button("🔄 Refresh", slot=self.reload))
        v.addLayout(flt)

        self.summary = QLabel("")
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setStyleSheet(f"color:{W.NAVY}; font-weight:600;")
        v.addWidget(self.summary)

        self.table = W.DataTable()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.doubleClicked.connect(self.accept)
        v.addWidget(self.table, 1)

        btns = QHBoxLayout()
        btns.addWidget(W.button("Use Ready Qty", slot=lambda: self._fill_pick("ready_qty")))
        btns.addWidget(W.button("Use Pending Qty", slot=lambda: self._fill_pick("pending_qty")))
        btns.addWidget(W.button("Use Can Pick Now", slot=lambda: self._fill_pick("can_pick_now")))
        btns.addWidget(W.button("☑ Select All", slot=lambda: self.table.selectAll()))
        btns.addStretch(1)
        v.addLayout(btns)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add Selected to Delivery Note")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.reload()

    def reload(self):
        self.rows = M.open_request_lines(
            self.db,
            text=self.f_text.text().strip(),
            project=self.f_project.text().strip(),
            mr_no=self.f_mr.text().strip(),
            pr_no=self.f_pr.text().strip(),
            ready_only=self.only_ready.isChecked(),
        )
        grid = []
        for r in self.rows:
            grid.append([
                r["mr_no"], r["mr_project"] or r["site"], r["pr_no"], r["item_code"],
                r["description"], r["uom"], round(float(r["pending_qty"] or 0), 2),
                round(float(r["ready_qty"] or 0), 2), round(float(r["available"] or 0), 2),
                round(float(r["can_pick_now"] or 0), 2), round(float(r["pick_default"] or 0), 2),
                r["status"], r["stock_status"], r["requested_by"] or "",
            ])
        self.table.fill(["MR Number", "Project / Site", "PR / MR No.", "Item Code", "Description",
                         "UOM", "Pending", "Ready", "Available", "Can Pick Now", "Pick Qty",
                         "Request Status", "Stock Status", "Requested By"],
                        grid, status_col=11)
        pick_col = 10
        for row in range(self.table.rowCount()):
            item = self.table.item(row, pick_col)
            if item is None:
                continue
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setToolTip("Editable — enter the quantity to add to the Delivery Note")
        pending = sum(float(r.get("pending_qty") or 0) for r in self.rows)
        ready = sum(float(r.get("ready_qty") or 0) for r in self.rows)
        can = sum(float(r.get("can_pick_now") or 0) for r in self.rows)
        self.summary.setText(
            f"<b>{len(self.rows)}</b> open line(s) &nbsp;·&nbsp; pending <b>{pending:,.2f}</b> "
            f"&nbsp;·&nbsp; ready <b>{ready:,.2f}</b> &nbsp;·&nbsp; can pick now <b>{can:,.2f}</b>"
        )

    def _fill_pick(self, field: str):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            rows = list(range(self.table.rowCount()))
        self.table.blockSignals(True)
        for r in rows:
            self.table.item(r, 10).setText(f"{round(float(self.rows[r].get(field) or 0), 2):g}")
        self.table.blockSignals(False)

    def _num(self, row: int, col: int) -> float:
        it = self.table.item(row, col)
        if it is None:
            return 0.0
        try:
            return float(str(it.text()).replace(",", "").strip() or 0)
        except ValueError:
            return 0.0

    def accept(self):
        picked_rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not picked_rows:
            W.error_box(self, "Select one or more request lines first.")
            return
        out: list[dict] = []
        for r in picked_rows:
            row = self.rows[r]
            qty = self._num(r, 10)
            if qty <= 0:
                continue
            if not row.get("item_id"):
                W.error_box(self, f"{row['item_code'] or row['description']}: link it to an Item Master record first.")
                return
            if qty > float(row.get("pending_qty") or 0) + 1e-9:
                W.error_box(self, f"{row['item_code']}: pick qty cannot exceed pending qty.")
                return
            if qty > float(row.get("can_pick_now") or 0) + 1e-9:
                W.error_box(self, f"{row['item_code']}: only {row['can_pick_now']:g} can be picked now.")
                return
            item = dict(self.db.one("SELECT * FROM items WHERE id=?", (row["item_id"],)))
            item.update({
                "qty": qty,
                "pr_no": row.get("pr_no", ""),
                "remarks": row.get("remarks", ""),
                "mr_line_id": row["id"],
                "mr_no": row.get("mr_no", ""),
                "mr_project": row.get("mr_project") or row.get("site") or "",
                "requested_by": row.get("requested_by") or "",
            })
            out.append(item)
        if not out:
            W.error_box(self, "The selected rows have no pick quantity yet.")
            return
        self.selected = out
        super().accept()

    @staticmethod
    def pick(db: Database, parent=None) -> list[dict]:
        dlg = OpenRequestPicker(db, parent)
        return dlg.selected if dlg.exec() == QDialog.Accepted else []


# =================================================================== RETURNS
class ReturnsPage(_TxnPage):
    MODE = "RETURN"
    SIG_DOC_TYPE = "RET"
    TITLE = "↩  Stock Return  —  Return Note"

    def build_form(self):
        db = self.db
        self.no = QLineEdit()
        self.no.setReadOnly(True)
        self.no.setPlaceholderText("Auto-generated on save")
        self.add_row(0, 0, "RETURN NUMBER", self.no)
        self.date = date_edit()
        self.add_row(0, 1, "DATE", self.date)
        self.rtype = W.combo(["Return from Site", "Return from Employee/Department",
                              "Return against Delivery Note", "Damaged Return", "Other"])
        self.add_row(0, 2, "RETURN TYPE", self.rtype)
        dn_box = QHBoxLayout()
        self.dn = QLineEdit()
        self.dn.setPlaceholderText("DN-2026-00001")
        dn_box.addWidget(self.dn, 1)
        b = W.button("Load DN", slot=self.load_dn, tip="Load the items of an existing Delivery Note")
        dn_box.addWidget(b)
        wrap = QWidget()
        wrap.setLayout(dn_box)
        self.add_row(0, 3, "ORIGINAL DELIVERY NOTE", wrap)
        self.by = QLineEdit()
        self.add_row(1, 0, "RETURNED BY", self.by)
        self.recv = QLineEdit()
        self.add_row(1, 1, "RECEIVED BY", self.recv)
        self.project = W.combo([""] + lookup(db, "sites"), True)
        self.add_row(1, 2, "PROJECT / SITE", self.project)
        self.wh = W.combo(lookup(db, "warehouses"), True)
        self.add_row(1, 3, "WAREHOUSE", self.wh)
        self.remarks = QLineEdit()
        self.add_row(2, 0, "REMARKS", self.remarks, 4)

    def load_dn(self):
        no = self.dn.text().strip()
        d = self.db.one("SELECT * FROM documents WHERE doc_type='DN' AND doc_no=?", (no,))
        if not d:
            W.error_box(self, f"Delivery Note '{no}' was not found.")
            return
        self.lines.clear_lines()
        items = []
        for l in self.db.query("SELECT * FROM document_lines WHERE doc_id=?", (d["id"],)):
            it = dict(self.db.one("SELECT * FROM items WHERE id=?", (l["item_id"],)))
            returned = self.db.scalar(
                """SELECT COALESCE(SUM(dl.qty),0) FROM document_lines dl
                   JOIN documents dd ON dd.id=dl.doc_id
                   WHERE dd.doc_type='RET' AND dd.linked_doc=? AND dl.item_id=?""",
                (no, l["item_id"]))
            it["issued_qty"] = l["qty"]
            it["return_qty"] = max(0, l["qty"] - returned)
            it["pr_no"] = (l["pr_no"] if "pr_no" in l.keys() else "") or ""
            items.append(it)
        self.lines.add_items(items)
        self.by.setText(d["issued_to"] or "")
        self.project.setCurrentText(d["project"] or "")
        self.wh.setCurrentText(d["warehouse"] or "")
        self.rtype.setCurrentText("Return against Delivery Note")
        W.toast(self, f"Loaded {len(items)} line(s) from {no}. Adjust the returned quantities.")

    def reset_form(self):
        self.dn.clear()
        self.by.clear()
        self.recv.clear()
        self.remarks.clear()

    def save(self):
        h = S.DocHeader(doc_type="RET", doc_date=iso(self.date), linked_doc=self.dn.text().strip(),
                        returned_by=self.by.text(), received_by=self.recv.text(),
                        project=self.project.currentText(), warehouse=self.wh.currentText(),
                        purpose=self.rtype.currentText(), remarks=self.remarks.text())
        lines = [l for l in self.lines.to_lines() if l.qty > 0]
        if not lines:
            W.error_box(self, "Enter a returned quantity for at least one line.")
            return
        try:
            no = S.post_return(self.db, h, lines)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.no.setText(no)
        usable = sum(l.qty for l in lines if l.condition == "USABLE")
        dmg = sum(l.qty for l in lines if l.condition == "DAMAGED")
        self._after_post("RET", no, f"Return {no} saved — {usable:g} usable added back to stock, "
                                    f"{dmg:g} recorded as damaged.")


# ================================================================ TRANSFERS
class TransferPage(_TxnPage):
    MODE = "TRANSFER"
    SIG_DOC_TYPE = "TRF"
    TITLE = "🔁  Stock Transfer"

    def build_form(self):
        db = self.db
        self.no = QLineEdit()
        self.no.setReadOnly(True)
        self.no.setPlaceholderText("Auto-generated on save")
        self.add_row(0, 0, "TRANSFER NUMBER", self.no)
        self.date = date_edit()
        self.add_row(0, 1, "DATE", self.date)
        self.wh_from = W.combo(lookup(db, "warehouses"), True)
        self.add_row(0, 2, "FROM WAREHOUSE / STORE", self.wh_from)
        self.wh_to = W.combo(lookup(db, "warehouses") + lookup(db, "sites"), True)
        self.add_row(0, 3, "TO WAREHOUSE / SITE", self.wh_to)
        self.loc_from = QLineEdit()
        self.add_row(1, 0, "FROM LOCATION / RACK", self.loc_from)
        self.loc_to = QLineEdit()
        self.add_row(1, 1, "TO LOCATION / RACK", self.loc_to)
        self.issued = QLineEdit()
        self.add_row(1, 2, "DISPATCHED BY", self.issued)
        self.recv = QLineEdit()
        self.add_row(1, 3, "RESPONSIBLE / RECEIVED BY", self.recv)
        self.remarks = QLineEdit()
        self.add_row(2, 0, "REMARKS", self.remarks, 4)

    def reset_form(self):
        self.remarks.clear()

    def save(self):
        h = S.DocHeader(doc_type="TRF", doc_date=iso(self.date),
                        warehouse=self.wh_from.currentText(), to_warehouse=self.wh_to.currentText(),
                        location=self.loc_from.text(), to_location=self.loc_to.text(),
                        issued_to=self.issued.text(), received_by=self.recv.text(),
                        remarks=self.remarks.text())
        try:
            no = S.post_transfer(self.db, h, self.lines.to_lines())
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.no.setText(no)
        self._after_post("TRF", no, f"Transfer {no} completed.")


# =============================================================== ADJUSTMENTS
class AdjustmentPage(_TxnPage):
    MODE = "ADJUST"
    TITLE = "⚖  Stock Adjustment  (a reason is mandatory)"

    def build_form(self):
        db = self.db
        self.no = QLineEdit()
        self.no.setReadOnly(True)
        self.no.setPlaceholderText("Auto-generated on save")
        self.add_row(0, 0, "ADJUSTMENT NUMBER", self.no)
        self.date = date_edit()
        self.add_row(0, 1, "DATE", self.date)
        self.reason = W.combo(["Physical count correction", "Missing stock", "Damaged stock",
                               "Found stock", "Data correction", "Opening balance adjustment"], True)
        self.add_row(0, 2, "REASON *", self.reason)
        self.wh = W.combo(lookup(db, "warehouses"), True)
        self.add_row(0, 3, "WAREHOUSE", self.wh)
        self.remarks = QLineEdit()
        self.remarks.setPlaceholderText("Explain the adjustment for the audit trail")
        self.add_row(1, 0, "REMARKS", self.remarks, 4)

    def reset_form(self):
        self.remarks.clear()

    def save(self):
        h = S.DocHeader(doc_type="ADJ", doc_date=iso(self.date),
                        reason=self.reason.currentText(), warehouse=self.wh.currentText(),
                        remarks=self.remarks.text())
        lines = [l for l in self.lines.to_lines() if l.qty]
        if not lines:
            W.error_box(self, "Enter a non-zero adjustment (+ or -) for at least one item.")
            return
        if not W.confirm(self, f"Post {len(lines)} adjustment line(s)?\n\n"
                               f"Reason: {h.reason}\n\nThis is recorded permanently in the audit trail."):
            return
        try:
            no = S.post_adjustment(self.db, h, lines)
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.no.setText(no)
        self._after_post("ADJ", no, f"Adjustment {no} posted.")


# ============================================================ PHYSICAL COUNT
class StockCountPage(_TxnPage):
    MODE = "COUNT"
    TITLE = "🧾  Physical Stock Count"

    def build_form(self):
        db = self.db
        self.no = QLineEdit()
        self.no.setReadOnly(True)
        self.no.setPlaceholderText("Auto-generated on save")
        self.add_row(0, 0, "COUNT NUMBER", self.no)
        self.date = date_edit()
        self.add_row(0, 1, "DATE", self.date)
        self.wh = W.combo([""] + lookup(db, "warehouses"), True)
        self.add_row(0, 2, "WAREHOUSE", self.wh)
        self.loc = QLineEdit()
        self.add_row(0, 3, "LOCATION", self.loc)
        self.by = QLineEdit()
        self.add_row(1, 0, "COUNTED BY", self.by)
        self.remarks = QLineEdit()
        self.add_row(1, 1, "REMARKS", self.remarks, 3)

    def build_actions(self, layout):
        layout.addWidget(W.button("📋  Load All Items", slot=self.load_all,
                                  tip="Load every active item of the selected warehouse"))
        layout.addWidget(W.button("🖨  Print Blank Count Sheet", slot=self.print_sheet))
        layout.addWidget(W.button("💾  Save Count", "Primary", self.save, shortcut="Ctrl+S"))
        layout.addWidget(W.button("⚖  Generate Adjustment from Variances", "Accent",
                                  self.to_adjustment))
        layout.addWidget(W.button("📊  Variance Report", slot=self.variance_report))
        layout.addStretch(1)
        layout.addWidget(ShareBar(self.db, lambda: self.last_pdf, self))

    def load_all(self):
        wh = self.wh.currentText()
        rows = S.search_items(self.db, "", "", wh)
        self.lines.clear_lines()
        self.lines.add_items(rows)
        W.toast(self, f"{len(rows)} item(s) loaded for counting.")

    def print_sheet(self):
        if not self.lines.rowCount():
            self.load_all()
        lines = self.lines.to_lines()
        if not lines:
            W.error_box(self, "No items to print.")
            return
        h = S.DocHeader(doc_type="CNT", doc_date=iso(self.date), warehouse=self.wh.currentText(),
                        location=self.loc.text(), received_by=self.by.text(),
                        remarks="Blank count sheet")
        blank = [S.Line(item_id=l.item_id, qty=0, system_qty=l.system_qty, counted_qty=0)
                 for l in lines]
        no = S.save_stock_count(self.db, h, blank)
        d = self.db.one("SELECT id FROM documents WHERE doc_type='CNT' AND doc_no=?", (no,))
        self.last_pdf = D.document_pdf(self.db, d["id"])
        self.no.setText(no)
        W.toast(self, f"Count sheet {no} generated.")
        D.open_path(self.last_pdf)

    def save(self):
        h = S.DocHeader(doc_type="CNT", doc_date=iso(self.date), warehouse=self.wh.currentText(),
                        location=self.loc.text(), received_by=self.by.text(),
                        remarks=self.remarks.text())
        try:
            no = S.save_stock_count(self.db, h, self.lines.to_lines())
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.no.setText(no)
        self.current_count = no
        d = self.db.one("SELECT id FROM documents WHERE doc_type='CNT' AND doc_no=?", (no,))
        self.last_pdf = D.document_pdf(self.db, d["id"])
        self.dataChanged.emit()
        W.toast(self, f"Stock count {no} saved. Use 'Generate Adjustment' to correct the system.")

    def to_adjustment(self):
        no = self.no.text().strip()
        if not no:
            W.error_box(self, "Save the count first.")
            return
        d = self.db.one("SELECT id FROM documents WHERE doc_type='CNT' AND doc_no=?", (no,))
        try:
            adj = S.count_to_adjustment(self.db, d["id"])
        except S.StockError as exc:
            W.error_box(self, str(exc))
            return
        self.dataChanged.emit()
        W.info_box(self, f"Adjustment {adj} created from the variances of {no}.\n\n"
                         "System stock now matches the physical count.")

    def variance_report(self):
        title, cols, rows = reports.build_report(self.db, "Physical Count/Variance Report", {})
        f = D.report_pdf(self.db, title, cols, rows)
        self.last_pdf = f
        D.open_path(f)
