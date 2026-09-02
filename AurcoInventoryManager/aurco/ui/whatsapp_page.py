"""Lightweight in-system WhatsApp desk with a phone-style preview."""
from __future__ import annotations

import html
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget)

from ..core import documents as D
from ..core.database import Database
from . import widgets as W


class WhatsAppPage(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(10)

        title = QLabel("<h2 style='color:#0b3d6b;margin:0'>WhatsApp Desk</h2>"
                       "<div style='color:#5f6368'>"
                       "A light in-system helper: compose a message, preview it in a phone-style view, "
                       "then open WhatsApp Web or the desktop app."
                       "</div>")
        title.setWordWrap(True)
        v.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(14)
        v.addLayout(body, 1)

        left = QWidget()
        form = QFormLayout(left)
        form.setLabelAlignment(Qt.AlignTop)
        self.number = QLineEdit(db.get_setting("wa_default_number", ""))
        self.number.setPlaceholderText("9665XXXXXXXX")
        self.number.textChanged.connect(self._refresh_preview)
        form.addRow("Phone number", self.number)

        self.message = QPlainTextEdit(db.get_setting("wa_message", ""))
        self.message.setPlaceholderText("Type the WhatsApp message to send...")
        self.message.textChanged.connect(self._refresh_preview)
        form.addRow("Message", self.message)

        attach_row = QHBoxLayout()
        self.file = QLineEdit()
        self.file.setPlaceholderText("Optional file to locate before opening WhatsApp")
        self.file.textChanged.connect(self._refresh_preview)
        attach_row.addWidget(self.file, 1)
        attach_row.addWidget(W.button("Browse...", slot=self._browse))
        form.addRow("Attachment", attach_row)

        action_row = QHBoxLayout()
        action_row.addWidget(W.button("Use saved defaults", slot=self._load_defaults,
                                      tip="Reload the default WhatsApp number and starter text from Settings"))
        action_row.addWidget(W.button("Open file location", slot=self._locate_file))
        action_row.addWidget(W.button("Copy link", slot=self._copy_link))
        action_row.addWidget(W.button("Open WhatsApp", "Accent", self._open_whatsapp,
                                      tip="Opens WhatsApp Web/app with the current number and message"))
        action_row.addStretch(1)
        form.addRow("Actions", action_row)
        body.addWidget(left, 1)

        phone = QFrame()
        phone.setStyleSheet(
            "QFrame{background:#111b21;border:1px solid #0b3d6b;border-radius:22px;}"
            "QLabel{color:#e9edef;}"
        )
        phone.setFixedWidth(340)
        pv = QVBoxLayout(phone)
        pv.setContentsMargins(14, 14, 14, 14)
        header = QLabel("WhatsApp preview")
        header.setStyleSheet("font-weight:700;color:#ffffff")
        pv.addWidget(header)
        self.to_lbl = QLabel()
        self.to_lbl.setStyleSheet("color:#aebac1")
        pv.addWidget(self.to_lbl)
        chat = QFrame()
        chat.setStyleSheet("QFrame{background:#0b141a;border-radius:16px;border:1px solid #1f2c34;}")
        cv = QVBoxLayout(chat)
        cv.setContentsMargins(12, 12, 12, 12)
        self.bubble = QLabel()
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.bubble.setStyleSheet(
            "background:#005c4b;color:#e9edef;padding:12px;border-radius:14px;"
        )
        cv.addWidget(self.bubble)
        self.attach_lbl = QLabel()
        self.attach_lbl.setWordWrap(True)
        self.attach_lbl.setStyleSheet(
            "background:#202c33;color:#d1d7db;padding:10px;border-radius:12px;"
        )
        cv.addWidget(self.attach_lbl)
        cv.addStretch(1)
        pv.addWidget(chat, 1)
        self.url_lbl = QLabel()
        self.url_lbl.setWordWrap(True)
        self.url_lbl.setStyleSheet("color:#8696a0;font-size:11px")
        pv.addWidget(self.url_lbl)
        body.addWidget(phone)

        tip = QLabel("Tip: this is intentionally lightweight. It uses your existing WhatsApp app/web session, "
                     "so there is no long API or embedded-browser integration to maintain.")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#5f6368")
        v.addWidget(tip)
        self._refresh_preview()

    def _load_defaults(self):
        self.number.setText(self.db.get_setting("wa_default_number", ""))
        self.message.setPlainText(self.db.get_setting("wa_message", ""))

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Attachment")
        if p:
            self.file.setText(p)

    def _current_message(self) -> str:
        return self.message.toPlainText().strip()

    def _current_url(self) -> str:
        return D.whatsapp_url(self.number.text(), self._current_message())

    def _refresh_preview(self):
        num = "".join(ch for ch in self.number.text() if ch.isdigit())
        self.to_lbl.setText(f"To: {num or 'choose contact in WhatsApp'}")
        msg = self._current_message() or "Start typing your message..."
        self.bubble.setText(html.escape(msg).replace("\n", "<br>"))
        file_txt = self.file.text().strip()
        if file_txt:
            p = Path(file_txt)
            state = "found" if p.exists() else "not found"
            self.attach_lbl.setText(f"Attachment: {p.name or file_txt}\nPath: {file_txt}\nStatus: {state}")
            self.attach_lbl.show()
        else:
            self.attach_lbl.hide()
        self.url_lbl.setText(self._current_url())

    def _locate_file(self):
        p = Path(self.file.text().strip())
        if not str(p):
            W.error_box(self, "Choose a file first.")
            return
        if p.exists():
            D.open_file_location(p)
        else:
            W.error_box(self, "The selected file was not found.")

    def _copy_link(self):
        QApplication.clipboard().setText(self._current_url())
        W.toast(self, "WhatsApp link copied.")

    def _open_whatsapp(self):
        url = self._current_url()
        file_txt = self.file.text().strip()
        num = "".join(ch for ch in self.number.text() if ch.isdigit())
        if file_txt:
            p = Path(file_txt)
            if p.exists():
                try:
                    D.open_file_location(p)
                except Exception:
                    pass
        webbrowser.open(url)
        self.db.audit("EXPORTED", "whatsapp", Path(file_txt).name if file_txt else "message",
                      f"desk to {num or 'chooser'}")
        W.toast(self, "WhatsApp opened.")
