"""Login screen, admin authorisation prompt and password change dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget)

from ..core import config, security
from ..core.database import Database
from . import widgets as W


class LoginDialog(QDialog):
    """Shown at startup when at least one account has a password."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.session = security.Session(db)
        self.ok = False
        self.setWindowTitle("AURCO Inventory Manager — Sign in")
        self.setWindowIcon(W.app_icon())
        self.setModal(True)
        self.setFixedSize(430, 460)

        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 20)
        v.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(W.app_icon().pixmap(84, 84))
        logo.setAlignment(Qt.AlignCenter)
        v.addWidget(logo)

        title = QLabel("AURCO INVENTORY MANAGER")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size:17px; font-weight:800; color:{W.NAVY};")
        v.addWidget(title)
        sub = QLabel("Please sign in to continue")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(sub)
        v.addSpacing(8)

        self.user = QComboBox()
        self.user.setEditable(True)
        names = [r["username"] for r in
                 db.query("SELECT username FROM users WHERE active=1 ORDER BY username")]
        self.user.addItems(names)
        last = db.get_setting("last_user", "")
        if last in names:
            self.user.setCurrentText(last)
        self.user.setMinimumHeight(34)
        v.addWidget(QLabel("User name"))
        v.addWidget(self.user)

        self.pwd = QLineEdit()
        self.pwd.setEchoMode(QLineEdit.Password)
        self.pwd.setMinimumHeight(34)
        self.pwd.setPlaceholderText("Password")
        self.pwd.returnPressed.connect(self._try)
        v.addWidget(QLabel("Password"))
        v.addWidget(self.pwd)

        self.show_pwd = QCheckBox("Show password")
        self.show_pwd.toggled.connect(
            lambda b: self.pwd.setEchoMode(QLineEdit.Normal if b else QLineEdit.Password))
        v.addWidget(self.show_pwd)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet(f"color:{W.RED}; font-weight:600;")
        v.addWidget(self.msg)
        v.addStretch(1)

        row = QHBoxLayout()
        row.addWidget(W.button("Exit", slot=self.reject))
        row.addStretch(1)
        row.addWidget(W.button("Sign in", "Primary", self._try))
        v.addLayout(row)

        foot = QLabel(f"v{config.APP_VERSION}  ·  Created by {config.CREATED_BY}")
        foot.setAlignment(Qt.AlignCenter)
        foot.setStyleSheet(f"color:{W.MUTED}; font-size:10px;")
        v.addWidget(foot)
        self.pwd.setFocus()

    def _try(self):
        ok, msg = self.session.login(self.user.currentText().strip(), self.pwd.text())
        if not ok:
            self.msg.setText(msg)
            self.pwd.selectAll()
            self.pwd.setFocus()
            return
        self.db.set_setting("last_user", self.session.username)
        self.ok = True
        self.accept()


class AdminAuthDialog(QDialog):
    """Administrator password prompt used to authorise deletions and other
    protected actions."""

    def __init__(self, action: str, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.admin_user = ""
        self.setWindowTitle("Administrator authorisation required")
        self.setModal(True)
        self.setFixedWidth(470)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        head = QLabel("🔒  Administrator authorisation required")
        head.setStyleSheet(f"font-size:15px; font-weight:700; color:{W.NAVY};")
        v.addWidget(head)
        what = QLabel(action)
        what.setWordWrap(True)
        what.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER};"
                           f"border-left:4px solid {W.RED}; border-radius:6px; padding:10px;")
        v.addWidget(what)

        form = QFormLayout()
        admins = [r["username"] for r in db.query(
            "SELECT username FROM users WHERE role='Administrator' AND active=1"
            " AND password_hash<>'' ORDER BY username")]
        self.user = QComboBox()
        self.user.addItems(admins)
        self.user.setEditable(True)
        form.addRow("Administrator", self.user)
        self.pwd = QLineEdit()
        self.pwd.setEchoMode(QLineEdit.Password)
        self.pwd.setPlaceholderText("Administrator password")
        self.pwd.returnPressed.connect(self._try)
        form.addRow("Password", self.pwd)
        v.addLayout(form)

        self.msg = QLabel("")
        self.msg.setStyleSheet(f"color:{W.RED}; font-weight:600;")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(W.button("Cancel", slot=self.reject))
        row.addWidget(W.button("Authorise", "Danger", self._try))
        v.addLayout(row)
        self.pwd.setFocus()

    def _try(self):
        ok, who = security.verify_admin(self.db, self.pwd.text(), self.user.currentText().strip())
        if not ok:
            self.msg.setText(who)
            self.pwd.selectAll()
            self.pwd.setFocus()
            self.db.audit("AUTH_FAILED", "admin-authorisation", self.user.currentText().strip())
            return
        self.admin_user = who
        self.accept()

    @staticmethod
    def authorise(db: Database, action: str, parent=None) -> bool:
        """Returns True when allowed. No prompt when no admin password exists
        or the protection is switched off in Settings."""
        if not security.admin_password_required(db):
            return True
        dlg = AdminAuthDialog(action, db, parent)
        if dlg.exec() == QDialog.Accepted:
            db.audit("AUTHORISED", "admin-authorisation", dlg.admin_user, action)
            return True
        return False


class ChangePasswordDialog(QDialog):
    def __init__(self, db: Database, username: str, require_old: bool = True, parent=None):
        super().__init__(parent)
        self.db = db
        self.username = username
        self.require_old = require_old and security.has_password(db, username)
        self.setWindowTitle(f"Set password — {username}")
        self.setModal(True)
        self.setFixedWidth(420)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.old = QLineEdit()
        self.old.setEchoMode(QLineEdit.Password)
        if self.require_old:
            f.addRow("Current password", self.old)
        self.new1 = QLineEdit()
        self.new1.setEchoMode(QLineEdit.Password)
        self.new2 = QLineEdit()
        self.new2.setEchoMode(QLineEdit.Password)
        f.addRow("New password", self.new1)
        f.addRow("Repeat new password", self.new2)
        v.addLayout(f)
        hint = QLabel("Leave both boxes empty to remove the password from this account.")
        hint.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.msg = QLabel("")
        self.msg.setStyleSheet(f"color:{W.RED}; font-weight:600;")
        v.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _save(self):
        if self.require_old:
            row = self.db.one("SELECT password_hash FROM users WHERE username=?", (self.username,))
            if not security.verify_password(self.old.text(), row["password_hash"] or ""):
                self.msg.setText("The current password is not correct.")
                return
        if self.new1.text() != self.new2.text():
            self.msg.setText("The new passwords do not match.")
            return
        if self.new1.text() and len(self.new1.text()) < 4:
            self.msg.setText("Use at least 4 characters.")
            return
        security.set_password(self.db, self.username, self.new1.text())
        self.accept()
