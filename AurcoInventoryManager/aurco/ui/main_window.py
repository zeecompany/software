"""AURCO Inventory Manager — main window, navigation, shortcuts, tray alerts."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QDialogButtonBox, QFileDialog,
                               QScrollArea, QSizePolicy,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QStackedWidget, QStatusBar, QSystemTrayIcon,
                               QToolButton, QVBoxLayout, QWidget)

from ..core import config, demo, documents as D, material as M, security, theming
from ..core import multiuser as MU
from ..core import sounds as SND
from ..core import workspace as WS
from ..core import services as S
from ..core.database import Database, get_db, set_db
from . import widgets as W
from .auth_dialogs import ChangePasswordDialog, LoginDialog
from .bulk_check import BulkCheckPage
from .dashboard import DashboardPage
from .material_page import MaterialPage
from .workspace_page import WorkspacePage
from .admin_station import AdminStationPage
from .cable_records import CableRecordsPage
from .tool_station import ToolStationPage
from .general_dn import GeneralDNPage
from .issuance_page import IssuancePage
from .library_page import LibraryPage
from .documents_page import AuditPage, DocumentsPage, HistoryPage, SearchPage
from .items import ItemsPage
from .reports_page import ReportsPage
from .settings_page import SettingsPage
from .transactions import (AdjustmentPage, ReturnsPage, StockCountPage, StockInPage, StockOutPage,
                           TransferPage)

def db_theme_width(db) -> str:
    return db.get_setting("ui_sidebar_width", "252") or "252"


NAV = [
    ("MAIN", None, None),
    ("Dashboard", "🏠", "Ctrl+1"),
    ("Global Search", "🔍", "Ctrl+F"),
    ("INVENTORY", None, None),
    ("Item Master", "📦", "Ctrl+2"),
    ("Movement History", "📜", "Ctrl+3"),
    ("Bulk Stock Check", "🧮", "Ctrl+K"),
    ("Material Requests", "📋", "Ctrl+M"),
    ("TRANSACTIONS", None, None),
    ("Stock In / Receiving", "📥", "Ctrl+4"),
    ("Stock Out / Delivery Note", "📤", "Ctrl+5"),
    ("Returns", "↩", "Ctrl+6"),
    ("Stock Transfer", "🔁", "Ctrl+7"),
    ("Stock Adjustment", "⚖", "Ctrl+8"),
    ("Physical Count", "🧾", "Ctrl+9"),
    ("DOCUMENTS & REPORTS", None, None),
    ("Documents", "🗂", "Ctrl+D"),
    ("Document Library", "🖼", "Ctrl+L"),
    ("Report Center", "📊", "Ctrl+R"),
    ("Audit Trail", "🛡", None),
    ("MY WORKSPACE", None, None),
    ("Notes & Tasks", "🗒", "Ctrl+T"),
    ("SEPARATE MODULES", None, None),
    ("Admin Station", "🏢", "Ctrl+Shift+A"),
    ("Tools, Instruments & Devices", "🔧", "Ctrl+Shift+T"),
    ("Cable Records", "🧵", "Ctrl+Shift+B"),
    ("General DN Maker", "🧾", "Ctrl+G"),
    ("Company Issuance", "🏢", "Ctrl+Shift+O"),
    ("SYSTEM", None, None),
    ("Settings", "⚙", "Ctrl+,"),
    ("Calculator", "🧮", "Ctrl+Alt+C"),
    ("User Manual", "📖", "F1"),
]


class StorageWizard(QDialog):
    """First-run: choose where all AURCO data will be stored."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AURCO Inventory Manager — Storage Location")
        self.setModal(True)
        self.resize(680, 330)
        v = QVBoxLayout(self)
        v.setSpacing(12)
        title = QLabel("<h2 style='color:#0b3d6b'>Welcome to AURCO Inventory Manager</h2>"
                       "<p>Select where the application should keep its database, delivery notes, "
                       "returns, reports, attachments, exports and backups.<br>"
                       "You can use a local drive, an external disk or a network share, and change "
                       "it later in Settings.</p>")
        title.setWordWrap(True)
        v.addWidget(title)
        row = QHBoxLayout()
        self.path = QLineEdit(str(config.default_storage_root()))
        row.addWidget(self.path, 1)
        row.addWidget(W.button("📂  Browse...", slot=self._browse))
        v.addLayout(row)
        self.info = QLabel("Folders created automatically:\n   " +
                           "   ·   ".join(config.SUBFOLDERS))
        self.info.setStyleSheet(f"color:{W.MUTED};")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.demo = QMessageBox  # placeholder
        from PySide6.QtWidgets import QCheckBox
        self.chk_demo = QCheckBox("Load sample/demo records so the dashboard and reports can be "
                                  "tested immediately")
        self.chk_demo.setChecked(True)
        v.addWidget(self.chk_demo)
        v.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Create && Start")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select storage folder", self.path.text())
        if d:
            self.path.setText(str(Path(d) / "AURCO Inventory") if not d.rstrip("\\/").endswith(
                "AURCO Inventory") else d)

    def _ok(self):
        try:
            config.set_storage_root(self.path.text().strip())
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"That location cannot be used.\n\n{exc}")
            return
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, db: Database, load_demo: bool = False, session=None):
        super().__init__()
        self.db = db
        self.session = session or security.Session(db)
        self.setWindowTitle(f"{config.APP_NAME}  —  {self.session.full_name} "
                            f"({self.session.role})  —  Created by {config.CREATED_BY}")
        self.setWindowIcon(W.app_icon())
        self.resize(1500, 920)
        self.setMinimumSize(1180, 700)
        self._build_ui()
        if load_demo:
            demo.seed(db)
        self.refresh_all()
        self._tray()
        QTimer.singleShot(1500, self._startup_alerts)
        QTimer.singleShot(3200, self._task_reminders)
        QTimer.singleShot(4000, self._start_reminder_timer)
        QTimer.singleShot(4500, self._start_heartbeat)

    # ---------------------------------------------------------------- build
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("Page")
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.setCentralWidget(central)

        # ---- sidebar
        # Fixed width + a plain layout meant the nav could not fit on short
        # screens and overflowed when the window was maximised / full-screened.
        # It is now a scrollable panel with a width range, resized in
        # resizeEvent() so it stays proportional at any resolution.
        side = QFrame()
        side.setObjectName("Sidebar")
        self._side = side
        self._side_base_w = int(float(db_theme_width(self.db)))
        side.setMinimumWidth(150)
        side.setMaximumWidth(420)
        side.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        side.resize(self._side_base_w, side.height())
        outer_sv = QVBoxLayout(side)
        outer_sv.setContentsMargins(0, 0, 0, 0)
        outer_sv.setSpacing(0)
        self._side_scroll = QScrollArea()
        self._side_scroll.setWidgetResizable(True)
        self._side_scroll.setFrameShape(QScrollArea.NoFrame)
        self._side_scroll.setObjectName("Sidebar")
        self._side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._side_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer_sv.addWidget(self._side_scroll, 1)
        side_inner = QWidget()
        side_inner.setObjectName("Sidebar")
        self._side_scroll.setWidget(side_inner)
        sv = QVBoxLayout(side_inner)
        sv.setContentsMargins(0, 8, 0, 8)
        sv.setSpacing(0)
        logo = QLabel("AURCO")
        logo.setObjectName("SidebarLogo")
        sv.addWidget(logo)
        sub = QLabel("INVENTORY MANAGER")
        sub.setObjectName("SidebarSub")
        sv.addWidget(sub)

        self.nav_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for name, glyph, shortcut in NAV:
            if glyph is None:
                lbl = QLabel(name)
                lbl.setObjectName("NavSection")
                sv.addWidget(lbl)
                continue
            b = QPushButton(f"  {glyph}   {name}".replace("&", "&&"))
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self.go(n))
            if shortcut:
                b.setToolTip(f"{name}  ({shortcut})")
                QShortcut(QKeySequence(shortcut), self, activated=lambda n=name: self.go(n))
            group.addButton(b)
            sv.addWidget(b)
            self.nav_buttons[name] = b
        sv.addStretch(1)
        credit = QLabel("Created by\nZain Shami")
        credit.setStyleSheet("color:#8fb2d4; font-size:11px; padding:10px 14px;")
        sv.addWidget(credit)
        h.addWidget(side)

        # ---- right side
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(62)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 8, 16, 8)
        box = QVBoxLayout()
        box.setSpacing(0)
        self.title = QLabel("Dashboard")
        self.title.setObjectName("PageTitle")
        self.subtitle = QLabel("Live overview of your warehouse")
        self.subtitle.setObjectName("PageSub")
        box.addWidget(self.title)
        box.addWidget(self.subtitle)
        tl.addLayout(box)
        tl.addStretch(1)

        self.quick = QLineEdit()
        self.quick.setPlaceholderText("Quick search / scan barcode  (Ctrl+F)")
        self.quick.setFixedWidth(330)
        self.quick.returnPressed.connect(self._quick_search)
        tl.addWidget(self.quick)
        for text, slot, tip in (
                ("＋ Item", lambda: self._quick("Item Master", "new"), "Quick Add Item (Ctrl+Shift+I)"),
                ("📥 Stock In", lambda: self.go("Stock In / Receiving"), "Quick Stock In"),
                ("📤 Stock Out", lambda: self.go("Stock Out / Delivery Note"), "Quick Delivery Note"),
                ("↩ Return", lambda: self.go("Returns"), "Quick Return"),
                ("📋 Requests", lambda: self.go("Material Requests"),
                 "Material requests (Ctrl+M)"),
                ("🧮", self._calculator, "Calculator (Ctrl+Alt+C or F4)"),
                ("🔄", self.refresh_all, "Refresh (F5)")):
            b = W.button(text, "Primary" if text.startswith("＋") else "", slot, tip)
            tl.addWidget(b)
        h.addLayout(right, 1)
        right.addWidget(top)

        # ---- pages
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        db = self.db
        self.pages: dict[str, QWidget] = {}
        self.page_dashboard = DashboardPage(db)
        self.page_items = ItemsPage(db)
        self.page_history = HistoryPage(db)
        self.page_bulk = BulkCheckPage(db)
        self.page_material = MaterialPage(db)
        self.page_workspace = WorkspacePage(db)
        self.page_in = StockInPage(db)
        self.page_out = StockOutPage(db)
        self.page_ret = ReturnsPage(db)
        self.page_trf = TransferPage(db)
        self.page_adj = AdjustmentPage(db)
        self.page_cnt = StockCountPage(db)
        self.page_docs = DocumentsPage(db)
        self.page_reports = ReportsPage(db)
        self.page_audit = AuditPage(db)
        self.page_search = SearchPage(db)
        self.page_admin = AdminStationPage(db)
        self.page_tools = ToolStationPage(db)
        self.page_cables = CableRecordsPage(db)
        self.page_gdn = GeneralDNPage(db)
        self.page_issuance = IssuancePage(db)
        self.page_library = LibraryPage(db)
        self.page_settings = SettingsPage(db, self.session)
        for name, page in (("Dashboard", self.page_dashboard), ("Global Search", self.page_search),
                           ("Item Master", self.page_items), ("Movement History", self.page_history),
                           ("Bulk Stock Check", self.page_bulk),
                           ("Material Requests", self.page_material),
                           ("Notes & Tasks", self.page_workspace),
                           ("Stock In / Receiving", self.page_in),
                           ("Stock Out / Delivery Note", self.page_out), ("Returns", self.page_ret),
                           ("Stock Transfer", self.page_trf), ("Stock Adjustment", self.page_adj),
                           ("Physical Count", self.page_cnt), ("Documents", self.page_docs),
                           ("Document Library", self.page_library),
                           ("Report Center", self.page_reports), ("Audit Trail", self.page_audit),
                           ("Admin Station", self.page_admin),
                           ("Tools, Instruments & Devices", self.page_tools),
                           ("Cable Records", self.page_cables),
                           ("General DN Maker", self.page_gdn),
                           ("Company Issuance", self.page_issuance),
                           ("Settings", self.page_settings)):
            self.pages[name] = page
            self.stack.addWidget(page)

        # ---- wiring
        self.page_dashboard.openItems.connect(self._open_items_status)
        self.page_dashboard.openDocs.connect(self._open_docs)
        self.page_dashboard.openPage.connect(self.go)
        self.page_items.openHistory.connect(self._open_history)
        self.page_search.openItem.connect(self._open_history)
        self.page_bulk.openHistory.connect(self._open_history)
        self.page_material.openHistory.connect(self._open_history)
        self.page_material.dataChanged.connect(self.refresh_all)
        self.page_workspace.dataChanged.connect(self.refresh_all)
        self.page_bulk.requestDN.connect(self._bulk_to_dn)
        self.page_docs.editDraft.connect(self._edit_draft)
        for p in (self.page_items, self.page_in, self.page_out, self.page_ret, self.page_trf,
                  self.page_adj, self.page_cnt, self.page_docs):
            p.dataChanged.connect(self.refresh_all)
        self.page_settings.settingsChanged.connect(self.refresh_all)
        self.page_settings.storageChanged.connect(self._storage_changed)
        self.page_settings.settingsChanged.connect(self._retheme)
        self.page_gdn.dataChanged.connect(self.refresh_all)

        # ---- status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_lbl = QLabel()
        sb.addWidget(self.status_lbl, 1)
        self.storage_lbl = QLabel()
        sb.addPermanentWidget(self.storage_lbl)
        sb.addPermanentWidget(QLabel(f" AURCO Inventory Manager v{config.APP_VERSION} | "
                                     f"Created by {config.CREATED_BY} "))

        # ---- global shortcuts
        QShortcut(QKeySequence("F5"), self, activated=self.refresh_all)
        QShortcut(QKeySequence("Ctrl+Shift+I"), self,
                  activated=lambda: self._quick("Item Master", "new"))
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._backup_now)
        QShortcut(QKeySequence("F4"), self, activated=self._calculator)
        self.go("Dashboard")
        QTimer.singleShot(0, self._fit_sidebar)

    # ------------------------------------------------------------ behaviour
    def _fit_sidebar(self):
        """Keep the sidebar proportional and always fully reachable.

        Full-screen / maximised used to distort the layout because the width was
        pinned while the nav needed more room than the screen height allowed.
        """
        side = getattr(self, "_side", None)
        if side is None:
            return
        base = getattr(self, "_side_base_w", 252)
        w = max(150, min(420, base, int(self.width() * 0.24)))
        if w != side.width():
            side.setFixedWidth(w)
        # hide the section captions when the panel gets narrow so labels do not
        # wrap into each other
        compact = w < 190
        for lbl in side.findChildren(QLabel, "NavSection"):
            lbl.setVisible(not compact)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_sidebar()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == QEvent.WindowStateChange:
            QTimer.singleShot(0, self._fit_sidebar)

    def go(self, name: str):
        if name == "Calculator":
            self._calculator()
            b = self.nav_buttons.get(name)
            if b:
                b.setChecked(False)
            return
        if name == "User Manual":
            self._help()
            b = self.nav_buttons.get(name)
            if b:
                b.setChecked(False)
            return
        if name not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[name])
        b = self.nav_buttons.get(name)
        if b:
            b.setChecked(True)
        subs = {
            "Dashboard": "Live overview of your warehouse",
            "Global Search": "Find items, documents and movements instantly",
            "Item Master": "Complete catalogue of every stocked item",
            "Movement History": "Full audit of every quantity change per item",
            "Bulk Stock Check": "Enter or paste many item codes and check quantities at once",
            "Material Requests": "Project requests · availability · preparation · ready to deliver",
            "Notes & Tasks": "Your reminders and daily task list",
            "Stock In / Receiving": "Receive goods and increase stock",
            "Stock Out / Delivery Note": "Issue material and generate a Delivery Note",
            "Returns": "Return usable or damaged material to the store",
            "Stock Transfer": "Move stock between warehouses, sites and racks",
            "Stock Adjustment": "Controlled corrections with a mandatory reason",
            "Physical Count": "Count sheets, variance and adjustment proposals",
            "Documents": "Every DN, GRN, return, transfer, adjustment and count",
            "Report Center": "28 reports with PDF, Excel, CSV and print",
            "Audit Trail": "Who did what and when",
            "Document Library": "Synced folders of scanned delivery notes — browse, "
                                "preview and print",
            "Calculator": "Quick calculations without leaving AURCO",
            "Tools, Instruments & Devices": "Separate custody register for tools, instruments "
                            "and devices — issue, transfer, temporary loan and "
                            "return. Its own database; no stock effect.",
            "Cable Records": "Separate cable drum register — length left on every "
                             "drum, every cut, the cable schedule and its megger "
                             "tests. Its own database; no stock effect.",
            "Admin Station": "Separate camp / office register — its own database, "
                             "no link to stock",
            "General DN Maker": "Create a delivery note without any inventory record",
            "Company Issuance": "Material issued to other companies, with photo proof "
                                "of issue and return",
            "Settings": "Company, storage, alerts, numbering, users and backup",
        }
        self.title.setText(name)
        self.subtitle.setText(subs.get(name, ""))
        page = self.pages[name]
        if name == "Global Search":
            page.focus()
        elif name == "Dashboard":
            page.refresh()
        elif hasattr(page, "scanner"):
            page.scanner.focus()

    def _quick(self, page: str, action: str):
        self.go(page)
        if page == "Item Master" and action == "new":
            self.page_items.new_item()

    def _quick_search(self):
        text = self.quick.text().strip()
        if not text:
            return
        hit = S.find_by_barcode(self.db, text)
        if hit:
            self._open_history(hit["id"])
            W.toast(self, f"{hit['code']} — {hit['description']} | Stock {hit['balance']:g} "
                          f"{hit['uom']} | {hit['warehouse']}/{hit['location']} | {hit['status']}")
        else:
            self.go("Global Search")
            self.page_search.box.setText(text)
        self.quick.clear()

    def _open_items_status(self, status: str):
        self.go("Item Master")
        self.page_items.set_status_filter(status)

    def _open_docs(self, key: str):
        self.go("Documents")
        self.page_docs.set_filter(key)

    def _edit_draft(self, doc_id: int):
        """Open a draft, or reopen a reversed DN / GRN on the source form."""
        d = self.db.one("SELECT doc_type, doc_no, status FROM documents WHERE id=?", (doc_id,))
        if d is None:
            W.error_box(self, "Document not found.")
            return
        page, nav = ((self.page_out, "Stock Out / Delivery Note") if d["doc_type"] == "DN"
                     else (self.page_in, "Stock In / Receiving"))
        self.go(nav)
        if page.load_draft(doc_id):
            msg = (f"{d['doc_no']} reopened after reversal — save it again as Draft or Finalize "
                   "to reuse the same number." if d["status"] == "REVERSED" else
                   f"{d['doc_no']} opened for editing — adjust the quantities and press Update Draft.")
            W.toast(self, msg)


    def _open_history(self, item_id: int):
        self.go("Movement History")
        self.page_history.load_item(item_id)

    def refresh_all(self):
        try:
            self.page_dashboard.refresh()
            self.page_items.reload_filters()
            self.page_items.reload()
            self.page_docs.reload()
            self.page_audit.reload()
            d = S.dashboard_data(self.db)
            cur = self.db.get_setting("currency", "")
            self.status_lbl.setText(
                f"  {d['total_items']} items · {d['total_qty']:,.0f} units · {cur} "
                f"{d['total_value']:,.2f} · ⚠ {d['low']} low · 🔥 {d['critical']} critical · "
                f"⛔ {d['out']} out of stock")
            self.storage_lbl.setText(f" 📂 {config.get_storage_root()} ")
            try:
                others = [u for u in MU.active_sessions(self.db)
                          if not (u["machine"] == MU.machine_name()
                                  and u["username"] == self.session.username)]
                if others:
                    self.status_lbl.setText(
                        self.status_lbl.text()
                        + f"   ·   👥 {len(others)} other user(s) online")
            except Exception:
                pass
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def _storage_changed(self, path: str):
        from ..core import database as dbmod
        self.db.close()
        newdb = Database(config.db_path())
        dbmod.set_db(newdb)
        W.info_box(self, "Storage location changed.\n\nPlease restart AURCO Inventory Manager "
                         "so every module uses the new database file.")

    def _backup_now(self):
        try:
            f = self.db.backup(kind="MANUAL", note="Ctrl+B")
            W.toast(self, f"Backup saved: {f.name}")
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Backup failed.\n\n{exc}")

    # ---------------------------------------------------------------- tray
    def _tray(self):
        self.tray = QSystemTrayIcon(W.app_icon(), self)
        menu = QMenu()
        menu.addAction(QAction("Open AURCO Inventory Manager", self,
                               triggered=self.showNormal))
        menu.addAction(QAction("Backup now", self, triggered=self._backup_now))
        menu.addSeparator()
        menu.addAction(QAction("Exit", self, triggered=self.close))
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(config.APP_NAME)
        try:
            self.tray.show()
        except Exception:  # noqa: BLE001
            pass

    def _task_reminders(self):
        """Ring and notify for tasks whose reminder time has arrived.

        Runs at startup and then on a timer, so a task set for 14:30 alerts at
        14:30 while the application is open.
        """
        try:
            due = WS.due_now(self.db)
        except Exception:
            return
        if not due:
            return
        try:
            worst = max(due, key=lambda t: ["Low", "Normal", "High", "Urgent"]
                        .index(t.get("priority", "Normal")))
        except ValueError:
            worst = due[0]
        SND.play_for_task(worst, self.db)
        names = ", ".join(t["title"][:28] for t in due[:3])
        extra = "" if len(due) <= 3 else f" +{len(due) - 3} more"
        try:
            self.tray.showMessage(
                f"⏰ {len(due)} task(s) due now",
                f"{names}{extra}\n\nOpen Notes && Tasks (Ctrl+T) to review them.",
                QSystemTrayIcon.Warning, 10000)
        except Exception:
            pass
        try:
            WS.mark_alerted(self.db, [t["id"] for t in due])
        except Exception:
            pass
        if hasattr(self, "page_workspace"):
            try:
                self.page_workspace.reload()
            except Exception:
                pass

    def _start_heartbeat(self):
        """Tell the shared database this PC is still online."""
        self._hb = QTimer(self)
        self._hb.timeout.connect(
            lambda: MU.heartbeat(self.db, self.session.username))
        self._hb.start(MU.HEARTBEAT_SECONDS * 1000)

    def _start_reminder_timer(self):
        try:
            secs = int(self.db.get_setting("sound_reminder_interval", 60) or 60)
        except (TypeError, ValueError):
            secs = 60
        self._reminder_timer = QTimer(self)
        self._reminder_timer.timeout.connect(self._task_reminders)
        self._reminder_timer.start(max(15, secs) * 1000)

    def _startup_alerts(self):
        if not self.db.get_bool("windows_notifications", True):
            return
        c = S.status_counts(self.db)
        if c[S.CRITICAL] or c[S.OUT] or c[S.WARNING]:
            try:
                self.tray.showMessage(
                    "AURCO stock alerts",
                    f"{c[S.WARNING]} low · {c[S.CRITICAL]} critical · {c[S.OUT]} out of stock.\n"
                    "Click the dashboard alert cards to review them.",
                    QSystemTrayIcon.Warning, 8000)
            except Exception:  # noqa: BLE001
                pass

    def _calculator(self):
        """Small always-available calculator (Ctrl+Alt+C or F4)."""
        from .calculator import CalculatorDialog
        dlg = getattr(self, "_calc", None)
        if dlg is None or not dlg.isVisible():
            self._calc = CalculatorDialog(self.db, self)
            self._calc.show()
        else:
            self._calc.raise_()
            self._calc.activateWindow()

    def _help(self):
        """Open the built-in User Manual (F1)."""
        from .user_manual import UserManualDialog
        dlg = getattr(self, "_manual", None)
        if dlg is None or not dlg.isVisible():
            self._manual = UserManualDialog(self.db, self)
            self._manual.show()
        else:
            self._manual.raise_()
            self._manual.activateWindow()

    def _retheme(self):
        """Re-apply the saved theme to every open widget."""
        theme = theming.get_theme(self.db)
        W.apply_theme(QApplication.instance(), theme)
        # a newly chosen window logo takes effect immediately
        try:
            ic = W.app_icon()
            self.setWindowIcon(ic)
            QApplication.instance().setWindowIcon(ic)
            if getattr(self, "tray", None):
                self.tray.setIcon(ic)
        except Exception:
            pass
        try:
            self._side_base_w = int(float(theme.get("ui_sidebar_width", 252)))
            self._fit_sidebar()
        except Exception:
            pass
        for page in self.pages.values():
            for tbl in page.findChildren(W.DataTable):
                tbl.verticalHeader().setDefaultSectionSize(
                    int(float(theme.get("ui_row_height", 27))))
                tbl.setAlternatingRowColors(theme.get("ui_stripe_rows", "1") == "1")
        self.refresh_all()

    def _bulk_to_dn(self, items: list):
        """Send a bulk-check result list straight into the Delivery Note screen."""
        self.go("Stock Out / Delivery Note")
        p = self.page_out
        p.lines.clear_lines()
        # add_items now carries issue_qty / pr_no into the grid itself, so the
        # rows can no longer drift out of step when a code repeats.
        p.lines.add_items(items)
        W.toast(self, f"{len(items)} item(s) loaded into the Delivery Note — "
                      "fill in the header and finalize.")

    def closeEvent(self, e):
        try:
            MU.end_session(self.db, self.session.username)
        except Exception:
            pass
        if self.db.get_bool("auto_backup_on_exit", True):
            try:
                self.db.backup(kind="AUTO", note="on exit")
            except Exception:  # noqa: BLE001
                pass
        self.db.audit("EXITED", "application")
        self.db.close()
        super().closeEvent(e)
