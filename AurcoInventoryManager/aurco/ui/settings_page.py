"""Settings: company, storage, lookups, alerts, numbering, email, users, backup."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton,
                               QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..core import arabic as AR, config, documents as D, multiuser as MU, security, sounds as SND, theming
from ..core.database import Database
from . import widgets as W
from .appearance import AppearanceTab
from .header_designer import HeaderDesignerTab
from .signature_ui import DocumentDesignerTab, SignatoryTab
from .auth_dialogs import AdminAuthDialog, ChangePasswordDialog


class SettingsPage(QWidget):
    settingsChanged = Signal()
    storageChanged = Signal(str)

    def __init__(self, db: Database, session=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.session = session or security.Session(db)
        self.setObjectName("Page")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setUsesScrollButtons(True)
        tabs.setElideMode(Qt.ElideNone)
        v.addWidget(tabs, 1)

        def add_tab(widget, title):
            """Every tab scrolls, so no option can be cut off on a short screen.

            Several tabs (Company, Storage) are taller than the window at
            1500x920 and their lower fields were simply unreachable.
            """
            if isinstance(widget, QScrollArea):
                tabs.addTab(widget, title)
                return widget
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            area.setWidget(widget)
            tabs.addTab(area, title)
            return area

        self._add_tab = add_tab
        self.appearance = AppearanceTab(db)
        self.appearance.themeApplied.connect(self.settingsChanged.emit)
        add_tab(self._company(), "Company && Documents")
        add_tab(self.appearance, "Appearance && Theme")
        self.header_designer = HeaderDesignerTab(db)
        add_tab(self.header_designer, "Header && Footer Designer")
        self.designer = DocumentDesignerTab(db)
        add_tab(self.designer, "Document Designer")
        self.signatories = SignatoryTab(db)
        add_tab(self.signatories, "Signatories")
        add_tab(self._security(), "Security && Login")
        add_tab(self._storage(), "Storage && Backup")
        add_tab(self._lookups(), "Categories · UOM · Warehouses · Sites")
        add_tab(self._alerts(), "Stock Alerts")
        add_tab(self._numbering(), "Document Numbering")
        add_tab(self._sharing(), "Email · WhatsApp · Printer")
        add_tab(self._users(), "Users && Permissions")
        add_tab(self._protection(), "🔒 File Protection")
        add_tab(self._about(), "About")

        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(W.button("💾  Save All Settings", "Accent", self.save))
        v.addLayout(bar)

    # ------------------------------------------------------------- sections
    def _line(self, key: str, placeholder: str = "") -> QLineEdit:
        e = QLineEdit(self.db.get_setting(key, "") or "")
        e.setPlaceholderText(placeholder)
        setattr(self, f"f_{key}", e)
        return e

    def _company(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Company information (printed on every PDF)")
        f = QFormLayout(g)
        f.addRow("Company Name", self._line("company_name"))
        f.addRow("Tagline", self._line("company_tagline"))
        f.addRow("Address", self._line("company_address"))
        f.addRow("Phone", self._line("company_phone"))
        f.addRow("Email", self._line("company_email"))
        f.addRow("VAT Number", self._line("company_vat"))
        f.addRow("C.R. Number", self._line("company_cr"))
        f.addRow("Created By", self._line("created_by"))
        logo_row = QHBoxLayout()
        self.f_logo_path = QLineEdit(self.db.get_setting("logo_path", ""))
        logo_row.addWidget(self.f_logo_path, 1)
        logo_row.addWidget(W.button("Browse...", slot=self._pick_logo))
        lw = QWidget()
        lw.setLayout(logo_row)
        f.addRow("AURCO Logo", lw)

        # ---- application window / taskbar icon
        icon_row = QHBoxLayout()
        self.f_app_icon = QLineEdit(self.db.get_setting("app_icon_path", ""))
        self.f_app_icon.setPlaceholderText(
            "Leave blank to use the built-in AURCO icon")
        icon_row.addWidget(self.f_app_icon, 1)
        icon_row.addWidget(W.button("Browse...", slot=self._pick_app_icon))
        icon_row.addWidget(W.button("Clear", slot=lambda: self.f_app_icon.clear()))
        self.lbl_icon_prev = QLabel()
        self.lbl_icon_prev.setFixedSize(32, 32)
        self.lbl_icon_prev.setScaledContents(True)
        icon_row.addWidget(self.lbl_icon_prev)
        iw = QWidget()
        iw.setLayout(icon_row)
        f.addRow("Window / taskbar logo", iw)
        hint = QLabel("Shown in the title bar, the taskbar and Alt-Tab. "
                      "A square .ico or .png of at least 256×256 looks best. "
                      "Applied as soon as you press Save.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        f.addRow("", hint)
        self.f_app_icon.textChanged.connect(self._preview_app_icon)
        self._preview_app_icon()
        v.addWidget(g)

        gmr = QGroupBox("Material Request defaults (auto-filled after a paste)")
        fmr = QFormLayout(gmr)
        self.f_mr_dept = QLineEdit(self.db.get_setting("mr_default_department",
                                                       "Site Team"))
        fmr.addRow("Department", self.f_mr_dept)
        self.f_mr_by = QLineEdit(self.db.get_setting("mr_default_requested_by",
                                                     "By Site Team"))
        fmr.addRow("Requested by", self.f_mr_by)
        mrhint = QLabel("Site is filled from the Project ID and Reference from the "
                        "PR column of the pasted sheet.")
        mrhint.setWordWrap(True)
        mrhint.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        fmr.addRow("", mrhint)
        v.addWidget(gmr)

        gfn = QGroupBox("Delivery Note file naming")
        ffn = QFormLayout(gfn)
        self.f_dn_use_pattern = QCheckBox(
            "Name Delivery Note files with the pattern below")
        self.f_dn_use_pattern.setChecked(
            self.db.get_bool("dn_filename_use_pattern", True))
        ffn.addRow(self.f_dn_use_pattern)
        self.f_dn_filename_template = QLineEdit(
            self.db.get_setting("dn_filename_template", D.DEFAULT_DN_TEMPLATE))
        ffn.addRow("Pattern", self.f_dn_filename_template)
        self.lbl_fn_preview = QLabel()
        self.lbl_fn_preview.setWordWrap(True)
        self.lbl_fn_preview.setStyleSheet(
            "background:#eef3f8; border:1px solid #c9d6e2; border-radius:5px;"
            "padding:6px; font-family:Consolas,monospace; font-size:11px;")
        ffn.addRow("Preview", self.lbl_fn_preview)
        tok = QLabel("  ".join(t for t, _ in D.FILENAME_TOKENS))
        tok.setWordWrap(True)
        tok.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        tok.setToolTip("\n".join(f"{t}   {d}" for t, d in D.FILENAME_TOKENS))
        ffn.addRow("Available", tok)
        row_fn = QHBoxLayout()
        row_fn.addWidget(W.button("↺  Restore AURCO default",
                                  slot=lambda: self.f_dn_filename_template.setText(
                                      D.DEFAULT_DN_TEMPLATE)))
        row_fn.addStretch(1)
        wfn = QWidget()
        wfn.setLayout(row_fn)
        ffn.addRow("", wfn)
        self.f_dn_filename_template.textChanged.connect(self._preview_filename)
        self.f_dn_use_pattern.toggled.connect(self._preview_filename)
        self._preview_filename()
        v.addWidget(gfn)

        g2 = QGroupBox("Document appearance")
        f2 = QFormLayout(g2)
        self.f_doc_footer = QPlainTextEdit(self.db.get_setting("doc_footer", ""))
        self.f_doc_footer.setMaximumHeight(70)
        f2.addRow("PDF footer text", self.f_doc_footer)
        self.f_currency = QLineEdit(self.db.get_setting("currency", "SAR"))
        f2.addRow("Currency", self.f_currency)
        self.f_date_format = W.combo(["dd-MM-yyyy", "yyyy-MM-dd", "MM/dd/yyyy", "dd/MM/yyyy"],
                                     False, self.db.get_setting("date_format", "dd-MM-yyyy"))
        f2.addRow("Date format", self.f_date_format)
        self.f_theme = W.combo(list(theming.PRESETS), False,
                               self.db.get_setting("ui_preset", "AURCO Light"))
        self.f_theme.setToolTip("Full colour control is in the 'Appearance & Theme' tab")
        f2.addRow("Theme preset", self.f_theme)
        self.f_default_uom = QLineEdit(self.db.get_setting("default_uom", "PCS"))
        f2.addRow("Default UOM", self.f_default_uom)
        v.addWidget(g2)

        g_ar = QGroupBox("Arabic text on printed documents")
        f_ar = QFormLayout(g_ar)
        self.f_company_name_ar = QLineEdit(self.db.get_setting("company_name_ar", ""))
        f_ar.addRow("Company name (Arabic)", self.f_company_name_ar)
        self.f_company_tagline_ar = QLineEdit(self.db.get_setting("company_tagline_ar", ""))
        f_ar.addRow("Tagline (Arabic)", self.f_company_tagline_ar)
        self.f_cr_label_ar = QLineEdit(self.db.get_setting("cr_label_ar", "س.ت"))
        f_ar.addRow("C.R. label (Arabic)", self.f_cr_label_ar)
        self.f_vat_label_ar = QLineEdit(self.db.get_setting("vat_label_ar", ""))
        f_ar.addRow("VAT label (Arabic)", self.f_vat_label_ar)

        # The numbers themselves can be corrected for the Arabic side of the
        # letterhead. Left blank they follow the English values, which is what
        # you want unless the Arabic registration genuinely differs.
        self.f_company_vat_ar = QLineEdit(self.db.get_setting("company_vat_ar", ""))
        self.f_company_vat_ar.setPlaceholderText(
            "blank = use the English VAT number")
        f_ar.addRow("VAT number (Arabic side)", self.f_company_vat_ar)
        self.f_company_cr_ar = QLineEdit(self.db.get_setting("company_cr_ar", ""))
        self.f_company_cr_ar.setPlaceholderText(
            "blank = use the English C.R. number")
        f_ar.addRow("C.R. number (Arabic side)", self.f_company_cr_ar)
        arnum = QLabel(
            "These two correct what prints on the Arabic half of the letterhead. "
            "With <b>Arabic-Indic numerals</b> ticked below they are shown as "
            "٢٠٥١٠٦٢٨٨٤ rather than 2051062884.")
        arnum.setWordWrap(True)
        arnum.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        f_ar.addRow("", arnum)
        self.f_arabic_font_style = W.combo(
            AR.STYLE_NAMES, False, self.db.get_setting("arabic_font_style", "Kufi"))
        self.f_arabic_font_style.setToolTip(
            "Kufi  — modern flat-stroke style, matches the company letterhead\n"
            "Naskh — classic book hand\n"
            "Amiri — traditional calligraphic Naskh\n"
            "System — the Windows default Arabic font")
        f_ar.addRow("Arabic typeface", self.f_arabic_font_style)
        self.f_arabic_eastern_digits = QCheckBox(
            "Use Arabic-Indic numerals (٢٠٥١٠٦٢٨٨٤) in Arabic lines")
        self.f_arabic_eastern_digits.setChecked(
            self.db.get_bool("arabic_eastern_digits", True))
        f_ar.addRow(self.f_arabic_eastern_digits)
        prev = QLabel()
        prev.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        prev.setText("Preview is shown on the document itself — use "
                     "Header && Footer Designer → Open sample PDF.")
        prev.setWordWrap(True)
        f_ar.addRow(prev)
        v.addWidget(g_ar)
        v.addWidget(g2)
        v.addStretch(1)
        return w

    def _pick_logo(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select logo", "", "Images (*.png *.jpg *.jpeg)")
        if f:
            self.f_logo_path.setText(f)

    def _preview_filename(self):
        """Live example using a realistic delivery note."""
        sample = {"doc_no": "DN-2026-00821", "doc_type": "DN", "doc_date": "2026-08-21",
                  "from_location": "Main WH", "warehouse": "Main WH",
                  "project": "Jubail Refinery", "issued_to": "Site Team",
                  "vehicle": "ABC-1234", "handover_to": "M. Aslam",
                  "reference": "MR-2026-00044", "supplier": "", "received_by": "",
                  "returned_by": "", "department": "", "driver": "", "linked_doc": ""}
        ctx = D.filename_context(self.db, sample, [])
        ctx["_prs"] = ["001582", "001601"]
        tpl = (self.f_dn_filename_template.text().strip()
               if self.f_dn_use_pattern.isChecked() else "{docno} {prs}")
        try:
            name = D.render_filename(tpl or "{docno}", ctx)
        except Exception as exc:  # noqa: BLE001
            name = f"(invalid pattern: {exc})"
        self.lbl_fn_preview.setText(name + ".pdf")

    def _pick_app_icon(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select the application window logo", "",
            "Icons and images (*.ico *.png *.jpg *.jpeg *.bmp)")
        if f:
            self.f_app_icon.setText(f)

    def _preview_app_icon(self):
        from PySide6.QtGui import QIcon, QPixmap
        path = (self.f_app_icon.text() or "").strip()
        pm = QPixmap()
        if path and Path(path).exists():
            ic = QIcon(path)
            if not ic.isNull():
                pm = ic.pixmap(32, 32)
        if pm.isNull():
            pm = W.app_icon().pixmap(32, 32)
        self.lbl_icon_prev.setPixmap(pm)

    def _storage(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Main storage location (database, PDFs, exports, attachments, backups)")
        f = QFormLayout(g)
        row = QHBoxLayout()
        self.f_storage = QLineEdit(str(config.get_storage_root() or ""))
        row.addWidget(self.f_storage, 1)
        row.addWidget(W.button("📂  Browse Folder / Drive", slot=self._browse_storage))
        row.addWidget(W.button("✔  Test Location", slot=self._test_storage))
        row.addWidget(W.button("🔀  Change && Move Data", "Primary", self._change_storage))
        rw = QWidget()
        rw.setLayout(row)
        f.addRow("Storage folder", rw)
        self.storage_info = QLabel()
        self.storage_info.setWordWrap(True)
        f.addRow("Structure", self.storage_info)
        self._refresh_storage_info()
        v.addWidget(g)

        g2 = QGroupBox("Backup && restore")
        f2 = QFormLayout(g2)
        brow = QHBoxLayout()
        self.f_backup_folder = QLineEdit(self.db.get_setting("backup_folder", ""))
        self.f_backup_folder.setPlaceholderText("(default: <storage>/Backups)")
        brow.addWidget(self.f_backup_folder, 1)
        brow.addWidget(W.button("Browse...", slot=lambda: self._pick_folder(self.f_backup_folder)))
        bw = QWidget()
        bw.setLayout(brow)
        f2.addRow("Backup folder", bw)
        self.f_auto_backup_on_exit = QCheckBox("Automatic backup when the application closes")
        self.f_auto_backup_on_exit.setChecked(self.db.get_bool("auto_backup_on_exit", True))
        f2.addRow("Scheduled backup", self.f_auto_backup_on_exit)
        self.f_backup_keep = QSpinBox()
        self.f_backup_keep.setRange(3, 500)
        self.f_backup_keep.setValue(int(self.db.get_setting("backup_keep", 20) or 20))
        f2.addRow("Backups to keep", self.f_backup_keep)
        brow2 = QHBoxLayout()
        for _b in (W.button("💾  Backup Now", "Primary", self._backup_now),
                   W.button("♻  Restore Backup", "Danger", self._restore),
                   W.button("🩺  Validate Database", slot=self._validate),
                   W.button("🔧  Rebuild Balances", slot=self._repair)):
            _b.setMinimumWidth(160)
            brow2.addWidget(_b)
        brow2.addStretch(1)
        bw2 = QWidget()
        bw2.setLayout(brow2)
        f2.addRow("Actions", bw2)
        v.addWidget(g2)

        g3 = QGroupBox("Backup history")
        v3 = QVBoxLayout(g3)
        self.backup_table = W.DataTable()
        v3.addWidget(self.backup_table)
        v.addWidget(g3, 1)
        self._reload_backups()

        g_net = QGroupBox("Multi-user  —  connect another computer")
        v_net = QVBoxLayout(g_net)
        note = QLabel(
            "Put the storage folder on a shared drive and point every PC at it. "
            "Each person signs in with their own user name, and everyone sees the "
            "same live stock, documents and reports.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        v_net.addWidget(note)
        rowm = QHBoxLayout()
        rowm.addWidget(W.button("📖  Show setup guide", "Primary", self._net_guide))
        rowm.addWidget(W.button("🔌  Connect to a shared folder...", slot=self._net_connect))
        rowm.addWidget(W.button("🩺  Multi-user health check", slot=self._net_health))
        rowm.addWidget(W.button("👥  Who is connected", slot=self._net_who))
        rowm.addStretch(1)
        v_net.addLayout(rowm)
        self.net_table = W.DataTable()
        self.net_table.setMaximumHeight(140)
        v_net.addWidget(self.net_table)
        v.addWidget(g_net)

        g4 = QGroupBox("Stock rules")
        f4 = QFormLayout(g4)
        self.f_allow_negative_stock = QCheckBox("Allow negative stock (not recommended)")
        self.f_allow_negative_stock.setChecked(self.db.get_bool("allow_negative_stock"))
        f4.addRow(self.f_allow_negative_stock)
        self.f_windows_notifications = QCheckBox("Show Windows tray notifications for stock alerts")
        self.f_windows_notifications.setChecked(self.db.get_bool("windows_notifications", True))
        f4.addRow(self.f_windows_notifications)
        v.addWidget(g4)
        return w

    def _refresh_storage_info(self):
        root = config.get_storage_root()
        if root:
            self.storage_info.setText("  ·  ".join(config.SUBFOLDERS) +
                                      f"\nAll folders are created automatically inside: {root}")

    def _pick_folder(self, target: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "Select folder", target.text() or "")
        if d:
            target.setText(d)

    def _browse_storage(self):
        d = QFileDialog.getExistingDirectory(self, "Select the AURCO storage folder or drive",
                                             self.f_storage.text() or "")
        if d:
            self.f_storage.setText(d)

    def _test_storage(self):
        p = self.f_storage.text().strip()
        if not p:
            W.error_box(self, "Enter or browse to a folder first.")
            return
        try:
            config.ensure_structure(p)
            W.info_box(self, f"✔ '{p}' is reachable and writable.\n\n"
                             "The AURCO folder structure has been created:\n  " +
                             "\n  ".join(config.SUBFOLDERS), "Storage test passed")
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"The location cannot be used.\n\n{exc}")

    def _change_storage(self):
        p = self.f_storage.text().strip()
        if not p:
            return
        new = Path(p)
        old = config.get_storage_root()
        if old and Path(old) == new:
            W.info_box(self, "That is already the current storage location.")
            return
        if not W.confirm(self, f"Move AURCO data to:\n{new}\n\n"
                               "The database and generated documents will be copied, and the "
                               "application will use the new location from now on. Continue?"):
            return
        try:
            config.ensure_structure(new)
            if old and Path(old).exists():
                for sub in config.SUBFOLDERS:
                    src = Path(old) / sub
                    if src.exists():
                        for f in src.rglob("*"):
                            if f.is_file():
                                dest = new / sub / f.relative_to(src)
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                if not dest.exists():
                                    shutil.copy2(f, dest)
            config.set_storage_root(new)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not switch storage location.\n\n{exc}")
            return
        self._refresh_storage_info()
        self.storageChanged.emit(str(new))
        W.info_box(self, f"Storage location changed to:\n{new}\n\n"
                         "The application will now reload the database from the new location.")

    def _backup_now(self):
        try:
            f = self.db.backup(self.f_backup_folder.text().strip() or None, "MANUAL")
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Backup failed.\n\n{exc}")
            return
        self._reload_backups()
        W.toast(self, f"Backup created: {f.name}")

    def _restore(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select a backup file",
                                           str(config.folder("Backups")), "Database (*.db)")
        if not f:
            return
        if not W.confirm(self, "Restore this backup?\n\nThe current database will be replaced "
                               "(a safety backup is taken first). Restart is recommended after "
                               "restoring."):
            return
        try:
            self.db.restore(f)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Restore failed.\n\n{exc}")
            return
        self._reload_backups()
        self.settingsChanged.emit()
        W.info_box(self, "Database restored successfully.")

    def _validate(self):
        W.info_box(self, "\n".join(self.db.validate()), "Database validation")

    def _repair(self):
        if W.confirm(self, "Rebuild every item balance from the immutable stock ledger?"):
            n = self.db.repair_balances()
            W.info_box(self, f"{n} balance(s) rebuilt from the ledger.")
            self.settingsChanged.emit()

    def _net_guide(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("Connect a second computer")
        dlg.resize(760, 620)
        lay = QVBoxLayout(dlg)
        box = QPlainTextEdit(MU.connection_guide())
        box.setReadOnly(True)
        f = box.font()
        f.setFamily("Consolas")
        box.setFont(f)
        lay.addWidget(box)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(W.button("Copy", slot=lambda: (
            __import__("PySide6.QtWidgets", fromlist=["QApplication"])
            .QApplication.clipboard().setText(box.toPlainText()),
            W.toast(self, "Guide copied to the clipboard."))))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        row.addWidget(bb)
        lay.addLayout(row)
        dlg.exec()

    def _net_connect(self):
        from PySide6.QtWidgets import QInputDialog
        cur = str(config.get_storage_root() or "")
        path, ok = QInputDialog.getText(
            self, "Connect to a shared folder",
            "Network path of the shared AURCO folder\n"
            "(for example  \\\\STORE-PC\\AURCO Inventory ):", text=cur)
        if not ok or not path.strip():
            return
        good, msg = MU.test_location(path.strip())
        if not good:
            W.error_box(self, msg)
            return
        if not W.confirm(self, f"{msg}\n\nUse this shared folder on this PC?\n"
                               "AURCO will reload the database from there."):
            return
        try:
            MU.configure_shared(path.strip())
        except OSError as exc:
            W.error_box(self, str(exc))
            return
        self.f_storage.setText(path.strip())
        self._refresh_storage_info()
        self.storageChanged.emit(path.strip())
        W.info_box(self, "This PC is now connected to the shared folder.\n\n"
                         "Please restart AURCO Inventory Manager, then sign in with "
                         "your own user name.")

    def _net_health(self):
        W.info_box(self, "\n".join(MU.check_health(self.db)), "Multi-user health check")
        self._net_who()

    def _net_who(self):
        rows = MU.active_sessions(self.db)
        self.net_table.fill(["User", "Computer", "Role", "Version", "Signed in", "Last seen"],
                            [[r["username"], r["machine"], r["role"], r["app_version"],
                              r["started_at"], r["last_seen"]] for r in rows])
        if not rows:
            W.toast(self, "No other sessions are registered yet.")

    def _reload_backups(self):
        rows = self.db.query("SELECT ts, path, size_kb, kind, note FROM backups ORDER BY id DESC")
        self.backup_table.fill(["When", "File", "Size (KB)", "Type", "Note"],
                               [[r["ts"], r["path"], round(r["size_kb"] or 0, 1), r["kind"],
                                 r["note"]] for r in rows])

    # ----------------------------------------------------------- lookups
    def _lookups(self):
        w = QWidget()
        h = QHBoxLayout(w)
        self.lists: dict[str, QListWidget] = {}
        for table, label in (("categories", "Categories"), ("uoms", "Units of Measure"),
                             ("warehouses", "Warehouses / Stores"), ("sites", "Sites / Projects"),
                             ("suppliers", "Suppliers")):
            g = QGroupBox(label)
            gv = QVBoxLayout(g)
            lst = QListWidget()
            self.lists[table] = lst
            gv.addWidget(lst)
            row = QHBoxLayout()
            row.addWidget(W.button("＋ Add", slot=lambda _=None, t=table: self._add_lookup(t)))
            row.addWidget(W.button("✖ Remove", slot=lambda _=None, t=table: self._del_lookup(t)))
            gv.addLayout(row)
            h.addWidget(g)
        self._reload_lookups()
        return w

    def _reload_lookups(self):
        for table, lst in self.lists.items():
            lst.clear()
            lst.addItems([r["name"] for r in
                          self.db.query(f"SELECT name FROM {table} ORDER BY name")])

    def _add_lookup(self, table: str):
        txt, ok = QInputDialog.getText(self, "Add", f"New entry for {table}:")
        if ok and txt.strip():
            self.db.execute(f"INSERT OR IGNORE INTO {table}(name) VALUES(?)", (txt.strip(),))
            self.db.commit()
            self._reload_lookups()
            self.settingsChanged.emit()

    def _del_lookup(self, table: str):
        it = self.lists[table].currentItem()
        if it and W.confirm(self, f"Remove '{it.text()}' from {table}?"):
            self.db.execute(f"DELETE FROM {table} WHERE name=?", (it.text(),))
            self.db.commit()
            self._reload_lookups()
            self.settingsChanged.emit()

    # ------------------------------------------------------------ alerts
    def _alerts(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Global stock alert thresholds (percentage of the maximum stock level)")
        f = QFormLayout(g)
        self.f_global_min_pct = QDoubleSpinBox()
        self.f_global_min_pct.setRange(0, 100)
        self.f_global_min_pct.setValue(self.db.get_float("global_min_pct", 40))
        self.f_global_crit_pct = QDoubleSpinBox()
        self.f_global_crit_pct.setRange(0, 100)
        self.f_global_crit_pct.setValue(self.db.get_float("global_crit_pct", 20))
        f.addRow("Warning below (%)", self.f_global_min_pct)
        f.addRow("Critical below (%)", self.f_global_crit_pct)
        f.addRow(QLabel("Out of Stock is always a balance of 0.\n"
                        "Each item can override this with its own percentage, fixed quantity or "
                        "category rule (Item Master → Stock & Alerts)."))
        v.addWidget(g)

        g2 = QGroupBox("Category level thresholds (used by items set to CATEGORY mode)")
        v2 = QVBoxLayout(g2)
        self.cat_table = W.DataTable()
        from PySide6.QtWidgets import QAbstractItemView
        self.cat_table.setEditTriggers(QAbstractItemView.DoubleClicked |
                                       QAbstractItemView.SelectedClicked)
        v2.addWidget(self.cat_table)
        v2.addWidget(W.button("💾 Save category thresholds", slot=self._save_cat_thresholds))
        self._reload_cat_thresholds()
        v.addWidget(g2, 1)
        return w

    def _reload_cat_thresholds(self):
        rows = self.db.query("SELECT name, min_pct, crit_pct FROM categories ORDER BY name")
        self.cat_table.fill(["Category", "Warning % (blank = global)", "Critical %"],
                            [[r["name"], r["min_pct"] if r["min_pct"] is not None else "",
                              r["crit_pct"] if r["crit_pct"] is not None else ""] for r in rows])

    def _save_cat_thresholds(self):
        for r in range(self.cat_table.rowCount()):
            name = self.cat_table.item(r, 0).text()

            def num(c):
                t = self.cat_table.item(r, c).text().strip() if self.cat_table.item(r, c) else ""
                try:
                    return float(t) if t else None
                except ValueError:
                    return None
            self.db.execute("UPDATE categories SET min_pct=?, crit_pct=? WHERE name=?",
                            (num(1), num(2), name))
        self.db.commit()
        W.toast(self, "Category thresholds saved.")
        self.settingsChanged.emit()

    # --------------------------------------------------------- numbering
    def _numbering(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Automatic document numbers")
        f = QFormLayout(g)
        for key, label in (("prefix_DN", "Delivery Note prefix"), ("prefix_GRN", "Goods Receipt prefix"),
                           ("prefix_RET", "Return prefix"), ("prefix_ADJ", "Adjustment prefix"),
                           ("prefix_TRF", "Transfer prefix"), ("prefix_CNT", "Stock count prefix")):
            f.addRow(label, self._line(key))
        self.f_number_pad = QSpinBox()
        self.f_number_pad.setRange(3, 10)
        self.f_number_pad.setValue(int(self.db.get_setting("number_pad", 5) or 5))
        f.addRow("Sequence digits", self.f_number_pad)
        f.addRow("Number format", self._line("number_format", "{prefix}-{year}-{seq}"))
        f.addRow("Item code prefix", self._line("item_code_prefix"))
        self.f_item_code_pad = QSpinBox()
        self.f_item_code_pad.setRange(3, 10)
        self.f_item_code_pad.setValue(int(self.db.get_setting("item_code_pad", 5) or 5))
        f.addRow("Item code digits", self.f_item_code_pad)
        f.addRow(QLabel("Example: DN-2026-00001 · RET-2026-00001 · GRN-2026-00001 · "
                        "ADJ-2026-00001 · TRF-2026-00001"))
        v.addWidget(g)

        g2 = QGroupBox("Delivery Note file naming")
        f2 = QFormLayout(g2)
        self.f_dn_filename_include_pr = QCheckBox(
            "Add the PR numbers to the end of the Delivery Note file name")
        self.f_dn_filename_include_pr.setChecked(
            self.db.get_bool("dn_filename_include_pr", True))
        f2.addRow(self.f_dn_filename_include_pr)
        self.f_dn_filename_separator = QLineEdit(
            self.db.get_setting("dn_filename_separator", "_"))
        self.f_dn_filename_separator.setMaxLength(3)
        self.f_dn_filename_separator.setMaximumWidth(70)
        f2.addRow("Separator", self.f_dn_filename_separator)
        ex = QLabel("Example: <b>DN-2026-00001_PR-2026-0148_PR-2026-0152.pdf</b><br>"
                    "Each PR number is written once, even when it covers several item "
                    "lines. Very long lists are shortened with '+N-more'.")
        ex.setWordWrap(True)
        ex.setStyleSheet(f"color:{W.MUTED};")
        f2.addRow(ex)
        v.addWidget(g2)
        v.addStretch(1)
        return w

    # ----------------------------------------------------------- sharing
    def _sharing(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Email (SMTP)")
        f = QFormLayout(g)
        f.addRow("SMTP host", self._line("smtp_host", "smtp.office365.com"))
        f.addRow("SMTP port", self._line("smtp_port", "587"))
        f.addRow("Username", self._line("smtp_user"))
        pw = QLineEdit(self.db.get_setting("smtp_pass", ""))
        pw.setEchoMode(QLineEdit.Password)
        self.f_smtp_pass = pw
        f.addRow("Password", pw)
        f.addRow("From address", self._line("smtp_from"))
        self.f_smtp_tls = QCheckBox("Use STARTTLS")
        self.f_smtp_tls.setChecked(self.db.get_bool("smtp_tls", True))
        f.addRow(self.f_smtp_tls)
        f.addRow(QLabel("If SMTP is left empty, the Email button opens your default mail client "
                        "with the file location ready."))
        v.addWidget(g)

        g2 = QGroupBox("WhatsApp sharing")
        f2 = QFormLayout(g2)
        f2.addRow("Default number (with country code)", self._line("wa_default_number", "9665XXXXXXXX"))
        self.f_wa_message = QPlainTextEdit(self.db.get_setting("wa_message", ""))
        self.f_wa_message.setMaximumHeight(70)
        f2.addRow("Default message", self.f_wa_message)
        f2.addRow(QLabel("WhatsApp Web/Desktop opens with the message ready and the document "
                         "folder highlighted so the file can be attached — no unofficial API used. "
                         "The same defaults are reused by the lightweight WhatsApp Desk page."))
        v.addWidget(g2)

        g_snd = QGroupBox("Alert sounds")
        f_snd = QFormLayout(g_snd)
        self.f_sound_enabled = QCheckBox("Play a sound for task reminders and alerts")
        self.f_sound_enabled.setChecked(self.db.get_bool("sound_enabled", True))
        f_snd.addRow(self.f_sound_enabled)
        self.f_sound_reminder_interval = QSpinBox()
        self.f_sound_reminder_interval.setRange(15, 3600)
        self.f_sound_reminder_interval.setSuffix(" seconds")
        self.f_sound_reminder_interval.setValue(
            int(self.db.get_setting("sound_reminder_interval", 60) or 60))
        f_snd.addRow("Check for due tasks every", self.f_sound_reminder_interval)
        trow = QHBoxLayout()
        for nm in ("reminder", "alarm", "urgent", "success", "warning", "error"):
            trow.addWidget(W.button(f"🔊 {nm.title()}",
                                    slot=lambda _=None, n=nm: SND.test(n, self.db)))
        trow.addStretch(1)
        wsnd = QWidget()
        wsnd.setLayout(trow)
        f_snd.addRow("Test", wsnd)
        wav_row = QHBoxLayout()
        self.f_sound_file_reminder = QLineEdit(
            self.db.get_setting("sound_file_reminder", ""))
        self.f_sound_file_reminder.setPlaceholderText("(optional) custom .wav for reminders")
        wav_row.addWidget(self.f_sound_file_reminder, 1)
        wav_row.addWidget(W.button("Browse...", slot=self._pick_wav))
        wwav = QWidget()
        wwav.setLayout(wav_row)
        f_snd.addRow("Custom sound", wwav)
        v.addWidget(g_snd)

        g3 = QGroupBox("Printer")
        f3 = QFormLayout(g3)
        f3.addRow("Printer name (blank = Windows default)", self._line("printer_name"))
        v.addWidget(g3)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------- users
    def _pick_wav(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select a WAV sound", "",
                                           "Sounds (*.wav)")
        if f:
            self.f_sound_file_reminder.setText(f)

    def _users(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Optional user accounts. Roles control which actions are available; "
                           "the daily workflow stays simple with no approval chains."))
        self.user_table = W.DataTable()
        v.addWidget(self.user_table, 1)
        row = QHBoxLayout()
        row.addWidget(W.button("＋ Add User", "Primary", self._add_user))
        row.addWidget(W.button("✏ Edit Role / Permissions", slot=self._edit_user))
        row.addWidget(W.button("🔑 Set Password", slot=self._set_user_password))
        row.addWidget(W.button("✖ Deactivate", slot=self._del_user))
        row.addStretch(1)
        v.addLayout(row)
        self._reload_users()
        return w

    def _reload_users(self):
        rows = self.db.query("SELECT * FROM users ORDER BY username")
        self.user_table.fill(
            ["Username", "Full Name", "Role", "Password", "Permissions", "Active", "Created"],
            [[r["username"], r["full_name"], r["role"],
              "Set" if r["password_hash"] else "— none —",
              r["permissions"] or "(role defaults)",
              "Yes" if r["active"] else "No", r["created_at"]] for r in rows])

    def _add_user(self):
        name, ok = QInputDialog.getText(self, "Add user", "Username:")
        if not ok or not name.strip():
            return
        role, ok = QInputDialog.getItem(self, "Role", "Select role:", security.ROLES, 1, False)
        if not ok:
            return
        try:
            self.db.execute("INSERT INTO users(username, full_name, role) VALUES(?,?,?)",
                            (name.strip(), name.strip(), role))
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not add the user.\n\n{exc}")
            return
        self.db.audit("CREATED", "user", name.strip(), role)
        self._reload_users()

    def _edit_user(self):
        r = self.user_table.currentRow()
        if r < 0:
            return
        username = self.user_table.item(r, 0).text()
        role, ok = QInputDialog.getItem(self, "Role", f"Role for {username}:",
                                        security.ROLES, 0, False)
        if not ok:
            return
        perms, ok = QInputDialog.getText(
            self, "Permissions",
            "Comma separated permissions (blank = use the role defaults):\n" +
            ", ".join(security.PERMISSIONS))
        if not ok:
            return
        self.db.execute("UPDATE users SET role=?, permissions=? WHERE username=?",
                        (role, perms.strip(), username))
        self.db.commit()
        self.db.audit("EDITED", "user", username, f"{role} / {perms}")
        self._reload_users()

    def _del_user(self):
        r = self.user_table.currentRow()
        if r < 0:
            return
        username = self.user_table.item(r, 0).text()
        if username == "admin":
            W.error_box(self, "The built-in administrator cannot be removed.")
            return
        if not AdminAuthDialog.authorise(self.db, f"Deactivate the user account '{username}'.",
                                         self):
            return
        if W.confirm(self, f"Deactivate user '{username}'?"):
            self.db.execute("UPDATE users SET active=0 WHERE username=?", (username,))
            self.db.commit()
            self.db.audit("DELETED", "user", username)
            self._reload_users()

    # ---------------------------------------------------------- security
    def _security(self):
        w = QWidget()
        v = QVBoxLayout(w)

        g = QGroupBox("Login")
        f = QFormLayout(g)
        self.f_require_login = QCheckBox("Ask for a user name and password when AURCO starts")
        self.f_require_login.setChecked(self.db.get_bool("require_login", False))
        f.addRow(self.f_require_login)
        note = QLabel("The login screen only appears once at least one account has a password. "
                      "Set a password below to switch protection on.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        f.addRow(note)
        self.f_auto_logout = QSpinBox()
        self.f_auto_logout.setRange(0, 480)
        self.f_auto_logout.setSuffix(" minutes (0 = never)")
        self.f_auto_logout.setValue(int(self.db.get_setting("auto_logout_minutes", 0) or 0))
        f.addRow("Lock after inactivity", self.f_auto_logout)
        v.addWidget(g)

        g2 = QGroupBox("Actions that require an administrator password")
        f2 = QFormLayout(g2)
        self.f_pw_delete = QCheckBox("Deleting / deactivating an item")
        self.f_pw_delete.setChecked(self.db.get_bool("require_admin_password_delete", True))
        f2.addRow(self.f_pw_delete)
        self.f_pw_reverse = QCheckBox("Reversing or correcting a finalized document")
        self.f_pw_reverse.setChecked(self.db.get_bool("require_admin_password_reverse", True))
        f2.addRow(self.f_pw_reverse)
        warn = QLabel("These prompts appear only when an administrator account actually has a "
                      "password set — otherwise the workflow stays uninterrupted.")
        warn.setWordWrap(True)
        warn.setStyleSheet(f"color:{W.MUTED};")
        f2.addRow(warn)
        v.addWidget(g2)

        g3 = QGroupBox("Passwords")
        h3 = QHBoxLayout(g3)
        h3.addWidget(W.button("🔑  Set / change my password", "Primary", self._change_my_password))
        h3.addWidget(W.button("🔑  Set password for selected user", slot=self._set_user_password,
                              tip="Select a user in the 'Users & Permissions' tab first"))
        h3.addStretch(1)
        v.addWidget(g3)
        v.addStretch(1)
        return w

    def _change_my_password(self):
        ChangePasswordDialog(self.db, self.session.username, True, self).exec()
        self._reload_users()

    def _set_user_password(self):
        r = self.user_table.currentRow() if hasattr(self, "user_table") else -1
        if r < 0:
            W.error_box(self, "Open the 'Users & Permissions' tab and select a user first.")
            return
        username = self.user_table.item(r, 0).text()
        if not AdminAuthDialog.authorise(self.db, f"Set a new password for '{username}'.", self):
            return
        ChangePasswordDialog(self.db, username, False, self).exec()
        self._reload_users()

    # ------------------------------------------------------------- about
    def _protection(self):
        from ..core import protection as P
        w = QWidget()
        v = QVBoxLayout(w)

        g = QGroupBox("Protect AURCO files and folders from deletion")
        f = QFormLayout(g)
        honest = QLabel(
            "<b>What this does</b><br>"
            "1. <b>AURCO will never delete a file.</b> Guaranteed — a delete in "
            "the app archives the file into a <code>_Archive</code> folder "
            "instead, so the bytes stay on disk.<br>"
            "2. <b>Windows blocks casual deletion.</b> Every file is set "
            "read-only and every folder gets an ACL denying DELETE to ordinary "
            "users, so a storekeeper cannot remove anything.<br>"
            "3. <b>Tampering is detected.</b> The size and SHA-256 of every file "
            "is recorded; Verify Now reports anything missing or altered.<br><br>"
            "<b style='color:#c92a2a'>Be aware:</b> no application can stop a "
            "machine <i>Administrator</i>, who can always take ownership and "
            "override any permission, or someone formatting the disk. For a true "
            "\"nobody can delete\" you also need the data folder on a network "
            "share where users are granted Read+Write but <i>not</i> Delete. "
            "This page gives you everything achievable from inside the software, "
            "and makes any deletion visible.")
        honest.setWordWrap(True)
        honest.setStyleSheet("background:#eef3f8; border:1px solid #c9d6e2;"
                             "border-radius:6px; padding:9px; font-size:11px;")
        f.addRow(honest)

        self.f_protect_files = QCheckBox(
            "Protect files — AURCO never deletes, only archives")
        self.f_protect_files.setChecked(self.db.get_bool("protect_files", True))
        f.addRow(self.f_protect_files)
        self.f_protect_readonly = QCheckBox(
            "Set every stored file read-only (blocks deletion in Windows Explorer)")
        self.f_protect_readonly.setChecked(self.db.get_bool("protect_readonly", True))
        f.addRow(self.f_protect_readonly)
        self.f_protect_acl = QCheckBox(
            "Apply a deny-delete permission to the folders (Windows only)")
        self.f_protect_acl.setChecked(self.db.get_bool("protect_acl", True))
        f.addRow(self.f_protect_acl)
        v.addWidget(g)

        g2 = QGroupBox("Status")
        f2 = QVBoxLayout(g2)
        self.lbl_protect = QLabel()
        self.lbl_protect.setWordWrap(True)
        f2.addWidget(self.lbl_protect)
        row = QHBoxLayout()
        row.addWidget(W.button("🔒  Protect All Folders Now", "Primary",
                               self._do_protect))
        row.addWidget(W.button("🔍  Verify Now", "Accent", self._do_verify))
        row.addWidget(W.button("📋  Show Issues", slot=self._show_issues))
        row.addWidget(W.button("🗃  Archived Files", slot=self._show_archive))
        row.addWidget(W.button("🔓  Lift Protection (admin)", slot=self._do_unlock))
        row.addStretch(1)
        rw = QWidget()
        rw.setLayout(row)
        f2.addWidget(rw)
        self.tbl_protect = W.DataTable()
        self.tbl_protect.setMinimumHeight(220)
        f2.addWidget(self.tbl_protect)
        v.addWidget(g2, 1)
        self._refresh_protect()
        return w

    def _refresh_protect(self):
        from ..core import protection as P
        st = P.status_report(self.db)
        acl = ("Deny-delete ACLs available (Windows)" if st["acl_supported"]
               else "Deny-delete ACLs need Windows — on "
                    f"{st['platform']} only file permissions are applied")
        colour = W.GREEN if st["enabled"] else W.RED
        warn = ""
        if st["missing"] or st["changed"]:
            warn = (f"<br><b style='color:{W.RED}'>⚠ {st['missing']} file(s) missing, "
                    f"{st['changed']} altered — press Show Issues.</b>")
        self.lbl_protect.setText(
            f"<b style='color:{colour}'>Protection is "
            f"{'ON' if st['enabled'] else 'OFF'}</b><br>"
            f"Tracking <b>{st['tracked']:,}</b> file(s) "
            f"({st['bytes'] / 1048576:.1f} MB) across {len(st['folders'])} folder(s)"
            f"<br>{st['archived']} file(s) kept in archive instead of being deleted"
            f"<br>{acl}<br><code>{st['root']}</code>{warn}")

    def _do_protect(self):
        from ..core import protection as P
        self.db.set_setting("protect_readonly",
                            int(self.f_protect_readonly.isChecked()))
        self.db.set_setting("protect_acl", int(self.f_protect_acl.isChecked()))
        P.set_enabled(self.db, self.f_protect_files.isChecked())
        res = P.protect_all(self.db)
        self._refresh_protect()
        msg = (f"{res['files']} file(s) in {res['folders']} folder(s) protected.\n"
               f"{res['readonly']} set read-only, {res['recorded']} newly recorded.")
        if res["errors"]:
            msg += "\n\nThe operating system refused some of it:\n" + \
                   "\n".join(res["errors"][:5])
        W.info_box(self, msg, "Protection applied")

    def _do_verify(self):
        from ..core import protection as P
        res = P.verify(self.db, deep=True)
        self._refresh_protect()
        self._show_issues()
        if not res["missing"] and not res["changed"]:
            W.info_box(self, f"All {res['ok']:,} protected file(s) are present and "
                             "unchanged.", "Verification passed")
        else:
            W.error_box(self, f"{len(res['missing'])} file(s) MISSING and "
                              f"{len(res['changed'])} altered.\n\nThey are listed "
                              "below — restore them from a backup.")

    def _show_issues(self):
        from ..core import protection as P
        rows = [r for r in P.ledger(self.db) if r["status"] != "OK"]
        self.tbl_protect.fill(["Status", "File", "Recorded", "Last Checked", "Size"],
                              [[r["status"], r["path"], r["recorded_at"],
                                r["last_seen"], r["size"]] for r in rows]
                              or [["OK", "No problems found", "", "", ""]])

    def _show_archive(self):
        from ..core import protection as P
        arc = P.archived_files(self.db)
        self.tbl_protect.fill(["Archived On", "File", "Original Folder", "Size (KB)",
                               "Full Path"],
                              [[a["archived"], a["name"], a["folder"], a["size_kb"],
                                a["path"]] for a in arc]
                              or [["", "Nothing archived yet", "", "", ""]])

    def _do_unlock(self):
        from ..core import protection as P
        from .auth_dialogs import AdminAuthDialog
        if not AdminAuthDialog.authorise(
                self.db, "Lift file protection for the whole storage folder.\n\n"
                         "Files become deletable again until you protect them.",
                self):
            W.toast(self, "Cancelled — administrator authorisation not given.", "warn")
            return
        if not W.confirm(self, "Lift protection on every AURCO folder?"):
            return
        root = Path(config.get_storage_root() or config.default_storage_root())
        n = 0
        for name in P.PROTECTED_FOLDERS:
            fol = root / name
            if fol.exists():
                n += P.unlock_folder(self.db, fol)["files"]
        P.set_enabled(self.db, False)
        self.f_protect_files.setChecked(False)
        self._refresh_protect()
        W.info_box(self, f"Protection lifted on {n} file(s).\n\nRemember to switch "
                         "it back on when you have finished.", "Protection lifted")

    def _about(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        logo = QLabel()
        logo.setPixmap(W.app_icon().pixmap(120, 120))
        logo.setAlignment(Qt.AlignCenter)
        v.addWidget(logo)
        txt = QLabel(
            f"<div style='text-align:center'>"
            f"<h1 style='color:{W.NAVY}; margin:6px'>AURCO INVENTORY MANAGER</h1>"
            f"<p style='color:{W.MUTED}'>Professional Inventory &amp; Warehouse Management</p>"
            f"<p>Version {config.APP_VERSION} &nbsp;·&nbsp; Windows Desktop Edition</p>"
            f"<p>Local-first · SQLite · Offline capable</p>"
            f"<h3 style='color:{W.NAVY}'>Created by {config.CREATED_BY}</h3>"
            f"<p style='color:{W.MUTED}; font-size:11px'>Storage: {config.get_storage_root()}</p>"
            f"</div>")
        txt.setTextFormat(Qt.RichText)
        txt.setAlignment(Qt.AlignCenter)
        v.addWidget(txt)
        b = W.button("📂  Open Storage Folder", "Primary",
                     lambda: D.open_path(config.get_storage_root()))
        v.addWidget(b, 0, Qt.AlignCenter)
        return w

    # -------------------------------------------------------------- save
    def save(self):
        keys = ["company_name", "company_tagline", "company_address", "company_phone",
                "company_email", "company_vat", "company_cr", "created_by",
                "smtp_host", "smtp_port",
                "smtp_user", "smtp_from", "wa_default_number", "printer_name",
                "prefix_DN", "prefix_GRN", "prefix_RET", "prefix_ADJ", "prefix_TRF", "prefix_CNT",
                "number_format", "item_code_prefix"]
        for k in keys:
            wdg = getattr(self, f"f_{k}", None)
            if wdg is not None:
                self.db.set_setting(k, wdg.text().strip())
        self.db.set_setting("logo_path", self.f_logo_path.text().strip())
        self.db.set_setting("app_icon_path", self.f_app_icon.text().strip())
        self.db.set_setting("protect_files", int(self.f_protect_files.isChecked()))
        self.db.set_setting("protect_readonly",
                            int(self.f_protect_readonly.isChecked()))
        self.db.set_setting("protect_acl", int(self.f_protect_acl.isChecked()))
        self.db.set_setting("mr_default_department",
                            self.f_mr_dept.text().strip() or "Site Team")
        self.db.set_setting("mr_default_requested_by",
                            self.f_mr_by.text().strip() or "By Site Team")
        self.db.set_setting("dn_filename_use_pattern",
                            int(self.f_dn_use_pattern.isChecked()))
        self.db.set_setting("dn_filename_template",
                            self.f_dn_filename_template.text().strip()
                            or D.DEFAULT_DN_TEMPLATE)
        self.db.set_setting("doc_footer", self.f_doc_footer.toPlainText().strip())
        self.db.set_setting("currency", self.f_currency.text().strip())
        self.db.set_setting("date_format", self.f_date_format.currentText())
        self.db.set_setting("default_uom", self.f_default_uom.text().strip() or "PCS")
        for k in ("company_name_ar", "company_tagline_ar", "cr_label_ar",
                  "vat_label_ar", "company_vat_ar", "company_cr_ar"):
            wdg = getattr(self, f"f_{k}", None)
            if wdg is not None:
                self.db.set_setting(k, wdg.text().strip())
        self.db.set_setting("arabic_font_style", self.f_arabic_font_style.currentText())
        self.db.set_setting("arabic_eastern_digits",
                            int(self.f_arabic_eastern_digits.isChecked()))
        AR.register_fonts(self.f_arabic_font_style.currentText(), force=True)
        self.db.set_setting("backup_folder", self.f_backup_folder.text().strip())
        self.db.set_setting("auto_backup_on_exit", int(self.f_auto_backup_on_exit.isChecked()))
        self.db.set_setting("backup_keep", self.f_backup_keep.value())
        self.db.set_setting("allow_negative_stock", int(self.f_allow_negative_stock.isChecked()))
        self.db.set_setting("windows_notifications", int(self.f_windows_notifications.isChecked()))
        self.db.set_setting("global_min_pct", self.f_global_min_pct.value())
        self.db.set_setting("global_crit_pct", self.f_global_crit_pct.value())
        self.db.set_setting("number_pad", self.f_number_pad.value())
        self.db.set_setting("item_code_pad", self.f_item_code_pad.value())
        self.db.set_setting("smtp_pass", self.f_smtp_pass.text())
        self.db.set_setting("smtp_tls", int(self.f_smtp_tls.isChecked()))
        self.db.set_setting("wa_message", self.f_wa_message.toPlainText().strip())
        self.db.set_setting("sound_enabled", int(self.f_sound_enabled.isChecked()))
        self.db.set_setting("sound_reminder_interval",
                            self.f_sound_reminder_interval.value())
        self.db.set_setting("sound_file_reminder",
                            self.f_sound_file_reminder.text().strip())
        self.db.set_setting("require_login", int(self.f_require_login.isChecked()))
        self.db.set_setting("require_admin_password_delete", int(self.f_pw_delete.isChecked()))
        self.db.set_setting("require_admin_password_reverse", int(self.f_pw_reverse.isChecked()))
        self.db.set_setting("auto_logout_minutes", self.f_auto_logout.value())
        self.db.set_setting("ui_preset", self.f_theme.currentText())
        self.db.set_setting("dn_filename_include_pr",
                            int(self.f_dn_filename_include_pr.isChecked()))
        self.db.set_setting("dn_filename_separator",
                            self.f_dn_filename_separator.text().strip() or "_")
        self.db.audit("EDITED", "settings", "", "settings updated")
        self.settingsChanged.emit()
        W.toast(self, "Settings saved.")
