"""Signatory directory, per-document signature picker and the Document Designer."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core import config, documents as D, signatories as SG
from ..core.database import Database
from . import widgets as W


# ======================================================= signatory editor
class SignatoryDialog(QDialog):
    def __init__(self, db: Database, sig_id: int | None = None, parent=None):
        super().__init__(parent)
        self.db = db
        self.sig_id = sig_id
        row = SG.get_signatory(db, sig_id) or {}
        self.sig_path = row.get("signature_path", "")
        self.setWindowTitle("Edit signatory" if sig_id else "New signatory")
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit(row.get("name", ""))
        self.desig = QLineEdit(row.get("designation", ""))
        self.dept = QLineEdit(row.get("department", ""))
        self.role = W.combo([""] + SG.ALL_ROLES, True, row.get("role", ""))
        self.idnum = QLineEdit(row.get("id_number", ""))
        self.idnum.setPlaceholderText("Iqama / national ID / licence number")
        self.phone = QLineEdit(row.get("phone", ""))
        self.email = QLineEdit(row.get("email", ""))
        f.addRow("Name *", self.name)
        f.addRow("Designation", self.desig)
        f.addRow("Department", self.dept)
        f.addRow("Usual role", self.role)
        f.addRow("ID / Iqama No.", self.idnum)
        f.addRow("Phone", self.phone)
        f.addRow("Email", self.email)
        v.addLayout(f)

        g = QGroupBox("Signature image (transparent PNG works best)")
        gv = QVBoxLayout(g)
        self.preview = QLabel()
        self.preview.setFixedHeight(90)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(f"border:1px dashed {W.BORDER}; border-radius:6px;")
        gv.addWidget(self.preview)
        hb = QHBoxLayout()
        hb.addWidget(W.button("📂  Choose image...", slot=self._pick))
        hb.addWidget(W.button("✖  Remove", slot=self._clear))
        gv.addLayout(hb)
        v.addWidget(g)
        self._show()

        self.active = QCheckBox("Active")
        self.active.setChecked(bool(row.get("active", 1)))
        v.addWidget(self.active)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _show(self):
        if self.sig_path and Path(self.sig_path).exists():
            self.preview.setPixmap(QPixmap(self.sig_path).scaled(
                380, 84, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview.setText("No signature image")

    def _pick(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select signature image", "",
                                           "Images (*.png *.jpg *.jpeg *.bmp)")
        if not f:
            return
        dest = config.folder("Attachments") / f"signature_{Path(f).name}"
        try:
            shutil.copy2(f, dest)
            self.sig_path = str(dest)
        except OSError:
            self.sig_path = f
        self._show()

    def _clear(self):
        self.sig_path = ""
        self._show()

    def _save(self):
        if not self.name.text().strip():
            W.error_box(self, "Enter the signatory name.")
            return
        SG.save_signatory(self.db, {
            "name": self.name.text().strip(), "designation": self.desig.text().strip(),
            "department": self.dept.text().strip(), "role": self.role.currentText().strip(),
            "signature_path": self.sig_path, "phone": self.phone.text().strip(),
            "id_number": self.idnum.text().strip(),
            "email": self.email.text().strip(),
            "active": 1 if self.active.isChecked() else 0}, self.sig_id)
        self.accept()


# =================================================== per-document picker
class SignatureBar(QWidget):
    """Signature panel shown under the item table.

    One tidy column per signature block: role caption, name selector and the
    designation of the chosen person. Names are typed or picked here only --
    they are never duplicated in the form header.
    """
    changed = Signal()

    def __init__(self, db: Database, doc_type: str, parent=None):
        super().__init__(parent)
        self.db = db
        self.doc_type = doc_type
        self.combos: dict[str, QComboBox] = {}
        self.desig: dict[str, QLabel] = {}
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 2, 0, 0)
        self.row.setSpacing(10)
        self.rebuild()

    def _clear(self):
        while self.row.count():
            it = self.row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.combos.clear()
        self.desig.clear()

    def rebuild(self):
        self._clear()
        names = [s["name"] for s in SG.list_signatories(self.db)]
        blocks = SG.get_blocks(self.db, self.doc_type)
        for role in blocks:
            box = QVBoxLayout()
            box.setSpacing(3)
            box.setContentsMargins(0, 0, 0, 0)

            is_handover = (role == SG.ROLE_HANDOVER_TO)
            cap = QLabel(role.upper())
            cap.setStyleSheet(
                f"color:{W.NAVY}; font-size:10px; font-weight:800; letter-spacing:.5px;")
            cap.setFixedHeight(14)
            box.addWidget(cap)

            cb = QComboBox()
            cb.setEditable(True)
            cb.addItems([""] + names)
            cb.setMinimumHeight(30)
            cb.setToolTip(f"Who signs as '{role}'.\n"
                          f"Defaults are configured in Settings → Signatories.")
            cb.lineEdit().setPlaceholderText(f"{role} name")
            d = SG.get_default(self.db, self.doc_type, role)
            if d:
                cb.setCurrentText(d["name"])
            box.addWidget(cb)

            if is_handover:
                ident = QHBoxLayout()
                ident.setContentsMargins(0, 0, 0, 0)
                ident.setSpacing(4)
                idw = QLineEdit()
                idw.setPlaceholderText("ID / Iqama")
                idw.setMinimumHeight(26)
                idw.setToolTip("Iqama / national ID of the driver taking custody")
                phw = QLineEdit()
                phw.setPlaceholderText("Phone")
                phw.setMinimumHeight(26)
                phw.setToolTip("Contact number of the driver taking custody")
                ident.addWidget(idw, 3)
                ident.addWidget(phw, 2)
                wrap = QWidget()
                wrap.setLayout(ident)
                box.addWidget(wrap)
                self.id_edit, self.phone_edit = idw, phw
                idw.textChanged.connect(lambda *_: self.changed.emit())
                phw.textChanged.connect(lambda *_: self.changed.emit())
            else:
                # keep every column the same height as the handover column
                spacer = QWidget()
                spacer.setFixedHeight(26)
                box.addWidget(spacer)

            sub = QLabel("")
            sub.setStyleSheet(f"color:{W.MUTED}; font-size:10px;")
            sub.setFixedHeight(13)
            box.addWidget(sub)

            cb.currentTextChanged.connect(
                lambda t, r=role: (self._sync_desig(r), self.changed.emit()))
            self.combos[role] = cb
            self.desig[role] = sub

            cell = QWidget()
            cell.setLayout(box)
            self.row.addWidget(cell, 4 if is_handover else 3)
            self._sync_desig(role)

    def _sync_desig(self, role: str):
        s = SG.find_signatory(self.db, self.combos[role].currentText())
        if role == SG.ROLE_HANDOVER_TO and s and hasattr(self, "id_edit"):
            # pull the driver's stored Iqama / phone, without overwriting typing
            if s.get("id_number") and not self.id_edit.text().strip():
                self.id_edit.setText(s["id_number"])
            if s.get("phone") and not self.phone_edit.text().strip():
                self.phone_edit.setText(s["phone"])
        lbl = self.desig.get(role)
        if lbl is None:
            return
        if s and s.get("designation"):
            has_img = " · signature on file" if s.get("signature_path") else ""
            lbl.setText(f"{s['designation']}{has_img}")
        else:
            lbl.setText("")

    def refresh_names(self) -> None:
        """Reload the signatory list, keeping whatever is already selected."""
        names = [s["name"] for s in SG.list_signatories(self.db)]
        for role, cb in self.combos.items():
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([""] + names)
            if cur:
                cb.setCurrentText(cur)
            else:
                d = SG.get_default(self.db, self.doc_type, role)
                if d:
                    cb.setCurrentText(d["name"])
            cb.blockSignals(False)
            self._sync_desig(role)

    def values(self) -> dict[str, str]:
        return {r: c.currentText().strip() for r, c in self.combos.items()}

    def handover_identity(self) -> tuple[str, str]:
        """(id_number, phone) typed for the person taking custody."""
        if hasattr(self, "id_edit"):
            return self.id_edit.text().strip(), self.phone_edit.text().strip()
        return "", ""

    def role_value(self, role: str) -> str:
        cb = self.combos.get(role)
        return cb.currentText().strip() if cb else ""

    def apply_to_document(self, doc_no: str, extra: dict[str, str] | None = None) -> None:
        """Persist the chosen signatories against the finalized document."""
        merged = dict(self.values())
        for role, name in (extra or {}).items():
            if name and not merged.get(role):
                merged[role] = name
        for role, name in merged.items():
            if not name:
                continue
            s = SG.find_signatory(self.db, name)
            idn = (s or {}).get("id_number", "")
            phn = (s or {}).get("phone", "")
            if role == SG.ROLE_HANDOVER_TO and hasattr(self, "id_edit"):
                idn = self.id_edit.text().strip() or idn
                phn = self.phone_edit.text().strip() or phn
            self.db.execute(
                """INSERT INTO document_signatures(doc_type,doc_no,role,name,designation,
                     signature_path,id_number,phone) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(doc_type,doc_no,role) DO UPDATE SET
                     name=excluded.name, designation=excluded.designation,
                     signature_path=excluded.signature_path,
                     id_number=excluded.id_number, phone=excluded.phone""",
                (self.doc_type, doc_no, role, name,
                 (s or {}).get("designation", ""),
                 (s or {}).get("signature_path", "")
                 if self.db.get_bool("print_signature_images", True) else "",
                 idn, phn))
        self.db.commit()

    def reset(self):
        self.rebuild()


# ================================================== settings: signatories
class SignatoryTab(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "People who sign AURCO documents. Add a signature image once and it is printed "
            "automatically wherever that person is the default signatory."))
        self.table = W.DataTable()
        self.table.doubleClicked.connect(self.edit)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(W.button("＋  Add Signatory", "Primary", self.add))
        row.addWidget(W.button("✏  Edit", slot=self.edit))
        row.addWidget(W.button("✖  Deactivate", slot=self.remove))
        row.addStretch(1)
        v.addLayout(row)

        g = QGroupBox("Default signatories per document type")
        gv = QVBoxLayout(g)
        top = QHBoxLayout()
        self.doc_type = W.combo(list(SG.DEFAULT_BLOCKS))
        self.doc_type.currentTextChanged.connect(self._load_defaults)
        top.addWidget(QLabel("Document type:"))
        top.addWidget(self.doc_type)
        top.addWidget(QLabel("   Signature blocks (order shown on the PDF):"))
        self.blocks = QLineEdit()
        self.blocks.setPlaceholderText("Issued By, Delivered By, Handover To, Received By")
        self.blocks.setToolTip("Comma separated. These become the signature columns.")
        top.addWidget(self.blocks, 1)
        top.addWidget(W.button("💾 Save blocks", slot=self._save_blocks))
        gv.addLayout(top)
        self.def_grid = QGridLayout()
        gv.addLayout(self.def_grid)
        opt = QHBoxLayout()
        self.print_img = QCheckBox("Print signature images on documents")
        self.print_img.setChecked(db.get_bool("print_signature_images", True))
        self.print_img.toggled.connect(
            lambda b: db.set_setting("print_signature_images", int(b)))
        opt.addWidget(self.print_img)
        self.show_dt = QCheckBox("Show a date line under each signature")
        self.show_dt.setChecked(db.get_bool("show_signature_datetime", True))
        self.show_dt.toggled.connect(
            lambda b: db.set_setting("show_signature_datetime", int(b)))
        opt.addWidget(self.show_dt)
        self.show_id = QCheckBox("Print ID / Iqama and phone under the signature")
        self.show_id.setChecked(db.get_bool("show_handover_id", True))
        self.show_id.toggled.connect(lambda b: db.set_setting("show_handover_id", int(b)))
        opt.addWidget(self.show_id)
        opt.addWidget(QLabel("Line style:"))
        self.line_style = W.combo(["Line", "Box", "None"], False,
                                  db.get_setting("signature_line_style", "Line"))
        self.line_style.currentTextChanged.connect(
            lambda t: db.set_setting("signature_line_style", t))
        opt.addWidget(self.line_style)
        opt.addStretch(1)
        gv.addLayout(opt)
        v.addWidget(g)
        self.reload()
        self._load_defaults()

    def reload(self):
        rows = SG.list_signatories(self.db, active_only=False)
        self.rows = rows
        self.table.fill(["Name", "Designation", "Department", "Usual Role", "ID / Iqama",
                         "Phone", "Signature Image", "Email", "Active"],
                        [[r["name"], r["designation"], r["department"], r["role"],
                          (r["id_number"] if "id_number" in r.keys() else "") or "",
                          r["phone"], "Yes" if r["signature_path"] else "—", r["email"],
                          "Yes" if r["active"] else "No"] for r in rows])

    def _sel(self):
        r = self.table.currentRow()
        if r < 0:
            W.error_box(self, "Select a signatory first.")
            return None
        return self.rows[r]

    def add(self):
        if SignatoryDialog(self.db, None, self).exec() == QDialog.Accepted:
            self.reload()
            self._load_defaults()

    def edit(self):
        s = self._sel()
        if s and SignatoryDialog(self.db, s["id"], self).exec() == QDialog.Accepted:
            self.reload()
            self._load_defaults()

    def remove(self):
        s = self._sel()
        if s and W.confirm(self, f"Deactivate '{s['name']}'?"):
            SG.delete_signatory(self.db, s["id"])
            self.reload()

    def _load_defaults(self):
        dt = self.doc_type.currentText()
        self.blocks.setText(", ".join(SG.get_blocks(self.db, dt)))
        while self.def_grid.count():
            it = self.def_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        sigs = SG.list_signatories(self.db)
        names = [s["name"] for s in sigs]
        self.def_combos = {}
        for i, role in enumerate(SG.get_blocks(self.db, dt)):
            self.def_grid.addWidget(QLabel(role), i // 3, (i % 3) * 2)
            cb = QComboBox()
            cb.addItem("— none —", None)
            for s in sigs:
                cb.addItem(f"{s['name']}  ({s['designation']})" if s["designation"]
                           else s["name"], s["id"])
            cur = SG.get_default(self.db, dt, role)
            if cur:
                idx = cb.findData(cur["id"])
                if idx >= 0:
                    cb.setCurrentIndex(idx)
            cb.currentIndexChanged.connect(
                lambda _=0, r=role, c=cb: SG.set_default(self.db, dt, r, c.currentData()))
            cb.setMinimumWidth(210)
            self.def_grid.addWidget(cb, i // 3, (i % 3) * 2 + 1)
            self.def_combos[role] = cb

    def _save_blocks(self):
        dt = self.doc_type.currentText()
        roles = [r.strip() for r in self.blocks.text().split(",") if r.strip()]
        if not roles:
            W.error_box(self, "Enter at least one signature block.")
            return
        SG.set_blocks(self.db, dt, roles)
        self._load_defaults()
        W.toast(self, f"Signature blocks saved for {dt}.")


# ================================================ settings: doc designer
class DocumentDesignerTab(QWidget):
    """Per-document-type appearance control with a live PDF preview."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)

        top = QHBoxLayout()
        top.addWidget(QLabel("Document type:"))
        self.doc_type = W.combo(list(D.DOC_TITLES))
        self.doc_type.currentTextChanged.connect(self._load)
        top.addWidget(self.doc_type)
        top.addStretch(1)
        top.addWidget(W.button("👁  Preview sample PDF", "Primary", self._preview))
        top.addWidget(W.button("↺  Reset this type", slot=self._reset))
        v.addLayout(top)

        g = QGroupBox("Colours && table")
        f = QFormLayout(g)
        self.header_color = QPushButton()
        self.header_color.clicked.connect(lambda: self._pick("header_color"))
        self.header_color.setFixedWidth(120)
        f.addRow("Table header colour", self.header_color)
        self.accent = QPushButton()
        self.accent.clicked.connect(lambda: self._pick("accent"))
        self.accent.setFixedWidth(120)
        f.addRow("Accent colour", self.accent)
        self.header_band = QPushButton()
        self.header_band.clicked.connect(lambda: self._pick("header_band_color"))
        self.header_band.setFixedWidth(120)
        f.addRow("Page header band colour", self.header_band)
        self.row_stripe = QCheckBox("Striped table rows")
        f.addRow(self.row_stripe)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(5.5, 12.0)
        self.font_size.setSingleStep(0.2)
        f.addRow("Table font size", self.font_size)
        self.orientation = W.combo(["Portrait", "Landscape"])
        f.addRow("Page orientation", self.orientation)
        v.addWidget(g)

        g2 = QGroupBox("Sections")
        f2 = QFormLayout(g2)
        self.show_logo = QCheckBox("Show the company logo")
        self.show_pr = QCheckBox("Show the 'Purchase Requests covered' summary table")
        self.show_pr.setToolTip("Off by default — the PR number already appears on every line")
        self.show_value = QCheckBox("Show value / cost columns")
        self.show_att = QCheckBox("List attached supporting documents")
        self.show_qr = QCheckBox("Print a QR code of the document number")
        self.show_extra = QCheckBox("Show extra header fields "
                                    "(department, requester, purpose, driver)")
        self.show_extra.setToolTip("Off = compact gate-pass header: "
                                   "From · Project · Vehicle · In Time · Out Time")
        self.sig_bottom = QCheckBox("Place signatures right under the item table")
        self.sig_bottom.setToolTip("Off (recommended) = the authorised signature is pinned "
                                   "to the bottom of the page, just above the footer line")
        for c in (self.show_logo, self.show_pr, self.show_value, self.show_att,
                  self.show_qr, self.show_extra, self.sig_bottom):
            f2.addRow(c)
        self.sig_caption = QLineEdit()
        self.sig_caption.setPlaceholderText("Authorised Signatures")
        f2.addRow("Signature block caption", self.sig_caption)
        self.sig_height = QSpinBox()
        self.sig_height.setRange(8, 40)
        self.sig_height.setSuffix(" mm")
        f2.addRow("Signature area height", self.sig_height)
        v.addWidget(g2)

        g3 = QGroupBox("Terms && footer")
        f3 = QFormLayout(g3)
        self.show_terms = QCheckBox("Print terms && conditions on this document")
        f3.addRow(self.show_terms)
        self.terms = QPlainTextEdit()
        self.terms.setMaximumHeight(90)
        self.terms.setPlaceholderText("Material received in good condition.\n"
                                      "Any damage must be reported within 24 hours.")
        f3.addRow("Terms text", self.terms)
        self.footer_note = QLineEdit()
        self.footer_note.setPlaceholderText("Extra note printed under the document")
        f3.addRow("Footer note", self.footer_note)
        v.addWidget(g3)

        g5 = QGroupBox("Page header band && footer  (applies to every PDF)")
        f5 = QFormLayout(g5)
        self.hdr_height = QSpinBox()
        self.hdr_height.setRange(14, 45)
        self.hdr_height.setSuffix(" mm")
        self.hdr_height.setValue(int(float(self.db.get_setting("pdf_header_height", 22) or 22)))
        f5.addRow("Header band height", self.hdr_height)
        self.hdr_align = W.combo(["Left", "Center"], False,
                                 self.db.get_setting("pdf_header_align", "Left"))
        f5.addRow("Company name alignment", self.hdr_align)
        self.hdr_style = W.combo(["Gradient", "Solid"], False,
                                 self.db.get_setting("pdf_header_style", "Gradient"))
        f5.addRow("Header band style", self.hdr_style)
        self.hdr_c1 = QPushButton()
        self.hdr_c1.setFixedWidth(120)
        self.hdr_c1.clicked.connect(lambda: self._pick_global("pdf_header_color1", self.hdr_c1))
        f5.addRow("Band colour (start)", self.hdr_c1)
        self.hdr_c2 = QPushButton()
        self.hdr_c2.setFixedWidth(120)
        self.hdr_c2.clicked.connect(lambda: self._pick_global("pdf_header_color2", self.hdr_c2))
        f5.addRow("Band colour (end)", self.hdr_c2)
        self._swatch(self.hdr_c1, self.db.get_setting("pdf_header_color1", "") or "")
        self._swatch(self.hdr_c2, self.db.get_setting("pdf_header_color2", "") or "")
        self.logo_backing = W.combo(["Auto", "White", "Dark", "None"], False,
                                    self.db.get_setting("logo_backing", "Auto"))
        self.logo_backing.setToolTip("A light plate behind the logo keeps dark logos "
                                     "readable on a dark header band")
        f5.addRow("Logo backing plate", self.logo_backing)
        self.hdr_company = QCheckBox("Show company name")
        self.hdr_tagline = QCheckBox("Show tagline")
        self.hdr_title = QCheckBox("Show document title (right)")
        self.hdr_dt = QCheckBox("Show print date and time (right)")
        self.hdr_bar = QCheckBox("Show the accent bar under the header")
        for c, k, d in ((self.hdr_company, "pdf_header_show_company", True),
                        (self.hdr_tagline, "pdf_header_show_tagline", True),
                        (self.hdr_title, "pdf_header_show_title", True),
                        (self.hdr_dt, "pdf_header_show_datetime", True),
                        (self.hdr_bar, "pdf_accent_bar", True)):
            c.setChecked(self.db.get_bool(k, d))
            f5.addRow(c)
        self.ftr_height = QSpinBox()
        self.ftr_height.setRange(8, 30)
        self.ftr_height.setSuffix(" mm")
        self.ftr_height.setValue(int(float(self.db.get_setting("pdf_footer_height", 14) or 14)))
        f5.addRow("Footer height", self.ftr_height)
        self.ftr_page = QCheckBox("Show page numbers")
        self.ftr_credit = QCheckBox("Show the AURCO credit line")
        self.ftr_line = QCheckBox("Show the footer separator line")
        for c, k in ((self.ftr_page, "pdf_footer_show_page"),
                     (self.ftr_credit, "pdf_footer_show_credit"),
                     (self.ftr_line, "pdf_footer_line")):
            c.setChecked(self.db.get_bool(k, True))
            f5.addRow(c)
        hint = QLabel("The AURCO logo file, its position (left / centre / right), size and "
                      "watermark are set in <b>Appearance &amp; Theme → Logo placement</b>.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{W.MUTED};")
        f5.addRow(hint)
        v.addWidget(g5)

        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(W.button("💾  Save Document Design", "Accent", self.save))
        v.addLayout(bar)
        v.addStretch(1)
        self._load()

    def _swatch(self, btn: QPushButton, value: str):
        btn.setProperty("colour", value)
        if value:
            from PySide6.QtGui import QColor
            fg = "#ffffff" if QColor(value).lightness() < 140 else "#101418"
            btn.setStyleSheet(f"background:{value}; color:{fg}; border:1px solid #888;"
                              "border-radius:5px; font-weight:600;")
            btn.setText(value.upper())
        else:
            btn.setStyleSheet("")
            btn.setText("Theme default")

    def _pick_global(self, key: str, btn):
        from PySide6.QtGui import QColor
        cur = btn.property("colour") or self.db.get_setting("ui_primary", "#0b3d6b")
        c = QColorDialog.getColor(QColor(cur), self, "Choose colour")
        if c.isValid():
            self._swatch(btn, c.name())

    def _pick(self, field: str):
        from PySide6.QtGui import QColor
        btn = {"header_color": self.header_color, "accent": self.accent,
               "header_band_color": self.header_band}[field]
        cur = btn.property("colour") or self.db.get_setting("ui_primary", "#0b3d6b")
        c = QColorDialog.getColor(QColor(cur), self, "Choose colour")
        if c.isValid():
            self._swatch(btn, c.name())

    def _load(self):
        dt = self.doc_type.currentText()
        L = SG.get_layout(self.db, dt)
        self._swatch(self.header_color, L.get("header_color", ""))
        self._swatch(self.accent, L.get("accent", ""))
        self._swatch(self.header_band, L.get("header_band_color", ""))
        self.show_extra.setChecked(SG.layout_bool(L, "show_extra_header", False))
        self.sig_bottom.setChecked(SG.layout_bool(L, "signature_inline", False))
        self.sig_caption.setText(L.get("signature_caption", "") or "")
        self.row_stripe.setChecked(SG.layout_bool(L, "row_stripe", True))
        self.font_size.setValue(float(L.get("font_size", 7.6) or 7.6))
        self.orientation.setCurrentText(L.get("orientation", "Portrait"))
        self.show_logo.setChecked(SG.layout_bool(L, "show_logo", True))
        self.show_pr.setChecked(SG.layout_bool(L, "show_pr_recap", False))
        self.show_value.setChecked(SG.layout_bool(L, "show_value_column", True))
        self.show_att.setChecked(SG.layout_bool(L, "show_attachments", True))
        self.show_qr.setChecked(SG.layout_bool(L, "show_qr", False))
        self.sig_height.setValue(int(float(L.get("signature_height", 18) or 18)))
        self.show_terms.setChecked(SG.layout_bool(L, "show_terms", False))
        self.terms.setPlainText(L.get("terms_text", ""))
        self.footer_note.setText(L.get("footer_note", ""))

    def save(self):
        dt = self.doc_type.currentText()
        SG.save_layout(self.db, dt, {
            "header_color": self.header_color.property("colour") or "",
            "accent": self.accent.property("colour") or "",
            "header_band_color": self.header_band.property("colour") or "",
            "show_extra_header": int(self.show_extra.isChecked()),
            "signature_inline": int(self.sig_bottom.isChecked()),
            "signature_caption": self.sig_caption.text().strip(),
            "row_stripe": int(self.row_stripe.isChecked()),
            "font_size": self.font_size.value(),
            "orientation": self.orientation.currentText(),
            "show_logo": int(self.show_logo.isChecked()),
            "show_pr_recap": int(self.show_pr.isChecked()),
            "show_value_column": int(self.show_value.isChecked()),
            "show_attachments": int(self.show_att.isChecked()),
            "show_qr": int(self.show_qr.isChecked()),
            "signature_height": self.sig_height.value(),
            "show_terms": int(self.show_terms.isChecked()),
            "terms_text": self.terms.toPlainText(),
            "footer_note": self.footer_note.text(),
        })
        for c, k in ((self.hdr_company, "pdf_header_show_company"),
                     (self.hdr_tagline, "pdf_header_show_tagline"),
                     (self.hdr_title, "pdf_header_show_title"),
                     (self.hdr_dt, "pdf_header_show_datetime"),
                     (self.hdr_bar, "pdf_accent_bar"),
                     (self.ftr_page, "pdf_footer_show_page"),
                     (self.ftr_credit, "pdf_footer_show_credit"),
                     (self.ftr_line, "pdf_footer_line")):
            self.db.set_setting(k, int(c.isChecked()))
        self.db.set_setting("pdf_header_height", self.hdr_height.value())
        self.db.set_setting("pdf_footer_height", self.ftr_height.value())
        self.db.set_setting("pdf_header_align", self.hdr_align.currentText())
        self.db.set_setting("pdf_header_style", self.hdr_style.currentText())
        self.db.set_setting("pdf_header_color1", self.hdr_c1.property("colour") or "")
        self.db.set_setting("pdf_header_color2", self.hdr_c2.property("colour") or "")
        self.db.set_setting("logo_backing", self.logo_backing.currentText())
        W.toast(self, f"{dt} document design saved.")

    def _reset(self):
        dt = self.doc_type.currentText()
        if not W.confirm(self, f"Reset the {dt} document design to factory defaults?"):
            return
        for k in SG.LAYOUT_DEFAULTS:
            self.db.set_setting(SG.layout_key(dt, k), "")
        self._load()
        W.toast(self, "Reset done.")

    def _preview(self):
        dt = self.doc_type.currentText()
        self.save()
        row = self.db.one("SELECT id FROM documents WHERE doc_type=? ORDER BY id DESC LIMIT 1",
                          (dt,))
        if not row:
            W.error_box(self, f"There is no {dt} document yet to preview.\n\n"
                              "Create one first, then use Preview.")
            return
        try:
            f = D.document_pdf(self.db, row["id"],
                               out_path=config.folder("Reports") / f"_preview_{dt}.pdf")
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not build the preview.\n\n{exc}")
            return
        D.open_path(f)
