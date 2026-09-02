"""Activation dialog for the packaged Windows application."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout)

from ..core import licensing as LIC
from . import widgets as W


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AURCO Inventory Manager — License Activation")
        self.resize(760, 430)
        v = QVBoxLayout(self)
        intro = QLabel(
            "<h2 style='color:#0b3d6b;margin:0'>Activation required</h2>"
            "<p>This Windows copy of AURCO Inventory Manager needs a valid license key. "
            "Send the installation id below to the developer, then paste the issued key here.</p>"
        )
        intro.setWordWrap(True)
        v.addWidget(intro)

        row = QHBoxLayout()
        self.installation = QLineEdit(LIC.installation_id())
        self.installation.setReadOnly(True)
        row.addWidget(self.installation, 1)
        row.addWidget(W.button("Copy Installation ID", slot=self._copy_installation))
        v.addLayout(row)

        self.machine = QLabel(f"Machine: {LIC.machine_name()}")
        self.machine.setStyleSheet("color:#5f6368")
        v.addWidget(self.machine)

        self.key = QPlainTextEdit()
        self.key.setPlaceholderText("Paste the license key issued for this installation...")
        self.key.setMaximumBlockCount(8)
        v.addWidget(self.key, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.btn_activate = W.button("Activate License", "Accent", self.activate)
        bb.addButton(self.btn_activate, QDialogButtonBox.AcceptRole)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _copy_installation(self):
        QApplication.clipboard().setText(self.installation.text())
        self.status.setText("Installation ID copied.")

    def activate(self):
        res = LIC.apply_license_key(self.key.toPlainText().strip())
        if not res["valid"]:
            self.status.setStyleSheet("color:#c92a2a")
            self.status.setText(res["reason"])
            return
        self.status.setStyleSheet("color:#1a7f37")
        self.status.setText("License activated successfully.")
        self.accept()

    @staticmethod
    def ensure_licensed(parent=None) -> bool:
        res = LIC.current_status()
        if res["valid"]:
            return True
        dlg = LicenseDialog(parent)
        return dlg.exec() == QDialog.Accepted
