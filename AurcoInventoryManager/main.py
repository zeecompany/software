"""AURCO INVENTORY MANAGER — Windows desktop application entry point.

Brand:       AURCO
Created by:  Zain Shami
Platform:    Windows Desktop (.EXE) — offline, local-first, SQLite
"""
from __future__ import annotations

import datetime as _dt
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QSplashScreen
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

from aurco.core import config, demo, licensing as LIC, multiuser as MU, security, theming
from aurco.core.database import Database, set_db
from aurco.ui import widgets as W
from aurco.ui.auth_dialogs import LoginDialog
from aurco.ui.license_dialog import LicenseDialog
from aurco.ui.main_window import MainWindow, StorageWizard


def log_path() -> Path:
    try:
        return config.folder("Logs") / "aurco.log"
    except Exception:
        p = config.appdata_dir() / "aurco.log"
        return p


def log_error(text: str) -> None:
    try:
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(f"\n[{_dt.datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}\n")
    except Exception:
        pass


def excepthook(etype, value, tb):
    text = "".join(traceback.format_exception(etype, value, tb))
    log_error(text)
    try:
        QMessageBox.critical(
            None, "AURCO Inventory Manager — unexpected error",
            f"Something went wrong, but your data is safe.\n\n{value}\n\n"
            f"Technical details were written to:\n{log_path()}")
    except Exception:
        print(text, file=sys.stderr)


def splash() -> QSplashScreen:
    pm = QPixmap(560, 300)
    pm.fill(QColor(W.NAVY))
    p = QPainter(pm)
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 30, QFont.Black))
    p.drawText(pm.rect().adjusted(0, -40, 0, -40), Qt.AlignCenter, "AURCO")
    p.setFont(QFont("Segoe UI", 15))
    p.drawText(pm.rect().adjusted(0, 30, 0, 30), Qt.AlignCenter, "INVENTORY MANAGER")
    p.setPen(QColor(W.ACCENT))
    p.setFont(QFont("Segoe UI", 10))
    p.drawText(pm.rect().adjusted(0, 110, 0, 110), Qt.AlignCenter,
               f"Professional Inventory & Warehouse Management   ·   Created by {config.CREATED_BY}")
    p.end()
    s = QSplashScreen(pm)
    s.show()
    return s


def main() -> int:
    sys.excepthook = excepthook
    QApplication.setApplicationName(config.APP_NAME)
    QApplication.setOrganizationName("AURCO")
    QApplication.setApplicationVersion(config.APP_VERSION)
    app = QApplication(sys.argv)
    app.setWindowIcon(W.app_icon())

    if LIC.should_enforce() and not LicenseDialog.ensure_licensed():
        return 0

    first_run = config.get_storage_root() is None
    load_demo = False
    if first_run:
        wiz = StorageWizard()
        if wiz.exec() != QDialog.Accepted:
            return 0
        load_demo = wiz.chk_demo.isChecked()
    else:
        try:
            config.ensure_structure(config.get_storage_root())
        except Exception as exc:
            QMessageBox.warning(None, "Storage not reachable",
                                f"The configured storage location cannot be used:\n\n{exc}\n\n"
                                "Please choose another location.")
            wiz = StorageWizard()
            if wiz.exec() != QDialog.Accepted:
                return 0
            load_demo = wiz.chk_demo.isChecked()

    sp = splash()
    app.processEvents()
    db = Database(config.db_path())
    set_db(db)
    W.apply_theme(app, theming.get_theme(db))
    # make concurrent access from several PCs safe (WAL + busy timeout)
    MU.apply_network_pragmas(db)
    db.audit("STARTED", "application", "", f"v{config.APP_VERSION}")

    # ---- optional login -----------------------------------------------------
    session = security.Session(db)
    if security.any_password_set(db) or db.get_bool("require_login", False):
        sp.hide()
        dlg = LoginDialog(db)
        if dlg.exec() != QDialog.Accepted or not dlg.ok:
            db.close()
            return 0
        session = dlg.session
        sp.show()
    else:
        db.current_user = session.username

    try:
        MU.register_session(db, session.username, session.role)
    except Exception:
        pass
    win = MainWindow(db, load_demo=load_demo, session=session)
    win.show()
    sp.finish(win)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
