"""My Workspace — sticky Notes and a daily Task board."""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QProgressBar, QScrollArea, QSpinBox, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import workspace as WS
from ..core.database import Database
from . import widgets as W
from .common import date_edit, iso


# ============================================================ note editor
class NoteDialog(QDialog):
    def __init__(self, db: Database, note_id: int | None = None, parent=None):
        super().__init__(parent)
        self.db = db
        self.note_id = note_id
        row = dict(db.one("SELECT * FROM notes WHERE id=?", (note_id,))) if note_id else {}
        self.setWindowTitle("Edit note" if note_id else "New note")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.title = QLineEdit(row.get("title", ""))
        self.title.setPlaceholderText("Short title")
        f.addRow("Title", self.title)
        self.category = W.combo([""] + self._categories(), True, row.get("category", ""))
        f.addRow("Category", self.category)
        self.color = W.combo(list(WS.NOTE_COLORS), False, row.get("color", "Yellow"))
        f.addRow("Colour", self.color)
        self.link = QLineEdit(row.get("link_ref", ""))
        self.link.setPlaceholderText("Optional: item code, DN / PR-MR number, project...")
        f.addRow("Related to", self.link)
        self.pinned = QCheckBox("Pin to the top")
        self.pinned.setChecked(bool(row.get("pinned")))
        f.addRow(self.pinned)
        v.addLayout(f)
        self.body = QPlainTextEdit(row.get("body", ""))
        self.body.setPlaceholderText("Write anything you need to remember...")
        self.body.setMinimumHeight(190)
        v.addWidget(self.body, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.title.setFocus()

    def _categories(self) -> list[str]:
        return [r["category"] for r in self.db.query(
            "SELECT DISTINCT category FROM notes WHERE category<>'' ORDER BY category")]

    def _save(self):
        try:
            WS.save_note(self.db, {
                "title": self.title.text().strip(), "body": self.body.toPlainText(),
                "color": self.color.currentText(),
                "category": self.category.currentText().strip(),
                "link_ref": self.link.text().strip(),
                "pinned": 1 if self.pinned.isChecked() else 0}, self.note_id)
        except ValueError as exc:
            W.error_box(self, str(exc))
            return
        self.accept()


class NoteCard(QFrame):
    """Sticky-note tile."""
    opened = Signal(int)
    pinToggled = Signal(int)
    deleted = Signal(int)

    def __init__(self, note: dict, parent=None):
        super().__init__(parent)
        self.note = note
        bg = WS.NOTE_COLORS.get(note.get("color", "Yellow"), "#fff3bf")
        self.setStyleSheet(f"background:{bg}; border:1px solid rgba(0,0,0,.12);"
                           "border-radius:8px;")
        self.setFixedHeight(158)
        self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(4)

        top = QHBoxLayout()
        t = QLabel(note.get("title") or "(untitled)")
        t.setStyleSheet("font-weight:700; font-size:13px; color:#1a1a1a; background:transparent;")
        t.setWordWrap(True)
        top.addWidget(t, 1)
        pin = W.button("📌" if note.get("pinned") else "📍", tip="Pin / unpin")
        pin.setFixedWidth(34)
        pin.setStyleSheet("background:transparent; border:none; font-size:14px;")
        pin.clicked.connect(lambda: self.pinToggled.emit(note["id"]))
        top.addWidget(pin)
        dele = W.button("✖", tip="Archive this note")
        dele.setFixedWidth(28)
        dele.setStyleSheet("background:transparent; border:none; color:#8a2b2b;")
        dele.clicked.connect(lambda: self.deleted.emit(note["id"]))
        top.addWidget(dele)
        v.addLayout(top)

        body = QLabel((note.get("body") or "").strip()[:220])
        body.setWordWrap(True)
        body.setStyleSheet("color:#333; background:transparent; font-size:11.5px;")
        body.setAlignment(Qt.AlignTop)
        v.addWidget(body, 1)

        meta = []
        if note.get("category"):
            meta.append(note["category"])
        if note.get("link_ref"):
            meta.append("🔗 " + note["link_ref"])
        meta.append((note.get("updated_at") or "")[:16])
        m = QLabel("  ·  ".join(meta))
        m.setStyleSheet("color:#6b6b6b; font-size:10px; background:transparent;")
        v.addWidget(m)

    def mouseDoubleClickEvent(self, e):
        self.opened.emit(self.note["id"])


# ============================================================ task editor
class TaskDialog(QDialog):
    def __init__(self, db: Database, task_id: int | None = None, parent=None):
        super().__init__(parent)
        self.db = db
        self.task_id = task_id
        row = dict(db.one("SELECT * FROM tasks WHERE id=?", (task_id,))) if task_id else {}
        self.setWindowTitle("Edit task" if task_id else "New task")
        self.setMinimumWidth(620)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.title = QLineEdit(row.get("title", ""))
        self.title.setPlaceholderText("What needs to be done?")
        f.addRow("Task *", self.title)

        row1 = QHBoxLayout()
        self.status = W.combo(WS.STATUSES, False, row.get("status", "To Do"))
        self.priority = W.combo(WS.PRIORITIES, False, row.get("priority", "Normal"))
        row1.addWidget(QLabel("Status:"))
        row1.addWidget(self.status, 1)
        row1.addWidget(QLabel("Priority:"))
        row1.addWidget(self.priority, 1)
        w1 = QWidget()
        w1.setLayout(row1)
        f.addRow("", w1)

        row2 = QHBoxLayout()
        self.has_due = QCheckBox("Due")
        self.has_due.setChecked(bool(row.get("due_date")))
        self.due = date_edit(row.get("due_date") or None)
        self.due_time = QLineEdit(row.get("due_time", ""))
        self.due_time.setPlaceholderText("hh:mm (optional)")
        self.due_time.setMaximumWidth(120)
        self.remind = QCheckBox("Remind me")
        self.remind.setChecked(bool(row.get("remind")))
        row2.addWidget(self.has_due)
        row2.addWidget(self.due, 1)
        row2.addWidget(self.due_time)
        row2.addWidget(self.remind)
        w2 = QWidget()
        w2.setLayout(row2)
        f.addRow("Schedule", w2)

        row3 = QHBoxLayout()
        self.assignee = W.combo([""] + self._people(), True, row.get("assignee", ""))
        self.category = W.combo([""] + self._categories(), True, row.get("category", ""))
        self.repeat = W.combo(WS.REPEATS, False, row.get("repeat_rule", "None"))
        row3.addWidget(QLabel("Assigned to:"))
        row3.addWidget(self.assignee, 1)
        row3.addWidget(QLabel("Category:"))
        row3.addWidget(self.category, 1)
        row3.addWidget(QLabel("Repeat:"))
        row3.addWidget(self.repeat)
        w3 = QWidget()
        w3.setLayout(row3)
        f.addRow("", w3)

        self.link = QLineEdit(row.get("link_ref", ""))
        self.link.setPlaceholderText("Optional: item code, DN / PR-MR number, project, MR...")
        f.addRow("Related to", self.link)
        v.addLayout(f)

        self.details = QPlainTextEdit(row.get("details", ""))
        self.details.setPlaceholderText("Notes / description")
        self.details.setMaximumHeight(90)
        v.addWidget(QLabel("Details"))
        v.addWidget(self.details)

        v.addWidget(QLabel("Checklist — one step per line, tick with [x]"))
        self.checklist = QPlainTextEdit(row.get("checklist", ""))
        self.checklist.setPlaceholderText("[ ] Count rack A\n[ ] Update system\n[x] Print sheet")
        self.checklist.setMaximumHeight(110)
        self.checklist.textChanged.connect(self._sync_progress)
        v.addWidget(self.checklist)

        prow = QHBoxLayout()
        prow.addWidget(QLabel("Progress"))
        self.progress = QSpinBox()
        self.progress.setRange(0, 100)
        self.progress.setSuffix(" %")
        self.progress.setValue(int(row.get("progress", 0) or 0))
        prow.addWidget(self.progress)
        self.bar = QProgressBar()
        self.bar.setValue(self.progress.value())
        self.progress.valueChanged.connect(self.bar.setValue)
        prow.addWidget(self.bar, 1)
        v.addLayout(prow)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.title.setFocus()

    def _people(self) -> list[str]:
        return [r["name"] for r in self.db.query(
            "SELECT name FROM signatories WHERE active=1 ORDER BY name")]

    def _categories(self) -> list[str]:
        return [r["category"] for r in self.db.query(
            "SELECT DISTINCT category FROM tasks WHERE category<>'' ORDER BY category")]

    def _sync_progress(self):
        pc = WS.checklist_progress(self.checklist.toPlainText())
        if pc:
            self.progress.setValue(pc)

    def _save(self):
        try:
            WS.save_task(self.db, {
                "title": self.title.text().strip(),
                "details": self.details.toPlainText(),
                "status": self.status.currentText(),
                "priority": self.priority.currentText(),
                "due_date": iso(self.due) if self.has_due.isChecked() else "",
                "due_time": self.due_time.text().strip(),
                "assignee": self.assignee.currentText().strip(),
                "category": self.category.currentText().strip(),
                "progress": self.progress.value(),
                "checklist": self.checklist.toPlainText(),
                "repeat_rule": self.repeat.currentText(),
                "remind": 1 if self.remind.isChecked() else 0,
                "link_ref": self.link.text().strip()}, self.task_id)
        except ValueError as exc:
            W.error_box(self, str(exc))
            return
        self.accept()


# ============================================================== the page
class WorkspacePage(QWidget):
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(9)

        self.kpi = QLabel("")
        self.kpi.setTextFormat(Qt.RichText)
        self.kpi.setStyleSheet(f"background:{W.CARD}; border:1px solid {W.BORDER};"
                               "border-radius:8px; padding:9px;")
        v.addWidget(self.kpi)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_tasks(), "✅  Tasks")
        self.tabs.addTab(self._tab_notes(), "📝  Notes")
        self.tabs.currentChanged.connect(lambda *_: self.reload())
        v.addWidget(self.tabs, 1)
        self.reload()

    # ------------------------------------------------------------- tasks
    def _tab_tasks(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(8)
        bar = QHBoxLayout()
        self.t_search = W.SearchBox("Search tasks...")
        self.t_search.textChanged.connect(self.reload_tasks)
        bar.addWidget(self.t_search, 2)
        self.t_view = W.combo(["All open", "Due today", "Overdue", "This week",
                               "No date", "Done", "Everything"])
        self.t_view.currentTextChanged.connect(self.reload_tasks)
        bar.addWidget(QLabel("View:"))
        bar.addWidget(self.t_view)
        self.t_priority = W.combo(["All priorities"] + WS.PRIORITIES)
        self.t_priority.currentTextChanged.connect(self.reload_tasks)
        bar.addWidget(self.t_priority)
        self.t_assignee = W.combo(["Everyone"])
        self.t_assignee.currentTextChanged.connect(self.reload_tasks)
        bar.addWidget(QLabel("Assignee:"))
        bar.addWidget(self.t_assignee)
        v.addLayout(bar)

        btns = QHBoxLayout()
        btns.addWidget(W.button("➕  New Task", "Primary", self.new_task, shortcut="Ctrl+T"))
        btns.addWidget(W.button("✏  Edit", slot=self.edit_task))
        btns.addWidget(W.button("▶  Start", slot=lambda: self._set("In Progress")))
        btns.addWidget(W.button("✔  Mark Done", "Accent", lambda: self._set("Done")))
        btns.addWidget(W.button("⛔  Blocked", slot=lambda: self._set("Blocked")))
        btns.addWidget(W.button("🗑  Delete", "Danger", self.delete_task))
        btns.addStretch(1)
        btns.addWidget(W.button("📄  Export PDF", slot=lambda: self._export("pdf")))
        btns.addWidget(W.button("📊  Excel", slot=lambda: self._export("xlsx")))
        v.addLayout(btns)

        self.t_table = W.DataTable()
        self.t_table.doubleClicked.connect(self.edit_task)
        v.addWidget(self.t_table, 1)
        return w

    def reload_tasks(self):
        view = self.t_view.currentText()
        due = {"Due today": "today", "Overdue": "overdue", "This week": "week",
               "No date": "nodate"}.get(view, "")
        status = "Done" if view == "Done" else ""
        include_done = view in ("Everything", "Done")
        pr = "" if self.t_priority.currentIndex() == 0 else self.t_priority.currentText()
        asg = "" if self.t_assignee.currentIndex() == 0 else self.t_assignee.currentText()
        self.tasks = WS.list_tasks(self.db, status, self.t_search.text().strip(), asg, pr,
                                   due, include_done)
        rows = []
        for t in self.tasks:
            due_txt = t["due_date"] or ""
            if t["overdue"]:
                due_txt += "  ⚠ overdue"
            elif t["due_today"]:
                due_txt += "  • today"
            if t["due_time"]:
                due_txt += f"  {t['due_time']}"
            rows.append([t["title"], t["status"], t["priority"], due_txt, t["assignee"],
                         t["category"], f"{t['progress']}%", t["repeat_rule"],
                         t["link_ref"], (t["details"] or "").replace("\n", " ")[:60]])
        self.t_table.fill(["Task", "Status", "Priority", "Due", "Assignee", "Category",
                           "Progress", "Repeat", "Related to", "Details"], rows)
        for r, t in enumerate(self.tasks):
            for col, colour in ((1, WS.STATUS_COLORS.get(t["status"])),
                                (2, WS.PRIORITY_COLORS.get(t["priority"]))):
                cell = self.t_table.item(r, col)
                if cell and colour:
                    cell.setForeground(QBrush(QColor(colour)))
                    f = cell.font()
                    f.setBold(True)
                    cell.setFont(f)
            if t["overdue"]:
                cell = self.t_table.item(r, 3)
                if cell:
                    cell.setForeground(QBrush(QColor(W.RED)))
                    f = cell.font()
                    f.setBold(True)
                    cell.setFont(f)
        cur = self.t_assignee.currentText()
        names = [r["assignee"] for r in self.db.query(
            "SELECT DISTINCT assignee FROM tasks WHERE assignee<>'' ORDER BY assignee")]
        self.t_assignee.blockSignals(True)
        self.t_assignee.clear()
        self.t_assignee.addItems(["Everyone"] + names)
        i = self.t_assignee.findText(cur)
        self.t_assignee.setCurrentIndex(max(0, i))
        self.t_assignee.blockSignals(False)

    def _sel_task(self) -> dict | None:
        r = self.t_table.currentRow()
        if r < 0 or r >= len(getattr(self, "tasks", [])):
            W.error_box(self, "Select a task first.")
            return None
        return self.tasks[r]

    def new_task(self):
        if TaskDialog(self.db, None, self).exec() == QDialog.Accepted:
            self.reload()
            self.dataChanged.emit()
            W.toast(self, "Task added.")

    def edit_task(self):
        t = self._sel_task()
        if t and TaskDialog(self.db, t["id"], self).exec() == QDialog.Accepted:
            self.reload()
            self.dataChanged.emit()

    def _set(self, status: str):
        t = self._sel_task()
        if not t:
            return
        WS.set_status(self.db, t["id"], status)
        self.reload()
        self.dataChanged.emit()
        msg = f"'{t['title'][:40]}' → {status}"
        if status == "Done" and (t["repeat_rule"] or "None") != "None":
            msg += f"  ·  next {t['repeat_rule'].lower()} occurrence created"
        W.toast(self, msg)

    def delete_task(self):
        t = self._sel_task()
        if t and W.confirm(self, f"Delete task '{t['title']}'?"):
            WS.delete_task(self.db, t["id"])
            self.reload()
            self.dataChanged.emit()

    def _export(self, kind: str):
        if not getattr(self, "tasks", None):
            W.error_box(self, "No tasks to export.")
            return
        fn = D.report_pdf if kind == "pdf" else D.export_excel
        f = fn(self.db, "Task List", self.t_table.headers(), self.t_table.all_rows())
        W.toast(self, f"Saved {f.name}")
        D.open_path(f)

    # ------------------------------------------------------------- notes
    def _tab_notes(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(8)
        bar = QHBoxLayout()
        self.n_search = W.SearchBox("Search notes...")
        self.n_search.textChanged.connect(self.reload_notes)
        bar.addWidget(self.n_search, 2)
        self.n_archived = QCheckBox("Show archived")
        self.n_archived.toggled.connect(self.reload_notes)
        bar.addWidget(self.n_archived)
        bar.addWidget(W.button("➕  New Note", "Primary", self.new_note, shortcut="Ctrl+Shift+N"))
        bar.addWidget(W.button("🔄  Refresh", slot=self.reload_notes))
        v.addLayout(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        host.setObjectName("Page")
        self.n_grid = QGridLayout(host)
        self.n_grid.setSpacing(10)
        self.n_grid.setAlignment(Qt.AlignTop)
        scroll.setWidget(host)
        v.addWidget(scroll, 1)
        return w

    def reload_notes(self):
        while self.n_grid.count():
            it = self.n_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        notes = WS.list_notes(self.db, self.n_search.text().strip(),
                              self.n_archived.isChecked())
        if not notes:
            empty = QLabel("No notes yet — press ➕ New Note to jot something down.")
            empty.setStyleSheet(f"color:{W.MUTED};")
            self.n_grid.addWidget(empty, 0, 0)
            return
        for i, n in enumerate(notes):
            card = NoteCard(n)
            card.opened.connect(self.open_note)
            card.pinToggled.connect(self.pin_note)
            card.deleted.connect(self.archive_note)
            self.n_grid.addWidget(card, i // 4, i % 4)

    def new_note(self):
        if NoteDialog(self.db, None, self).exec() == QDialog.Accepted:
            self.reload()
            self.dataChanged.emit()
            W.toast(self, "Note saved.")

    def open_note(self, note_id: int):
        if NoteDialog(self.db, note_id, self).exec() == QDialog.Accepted:
            self.reload()
            self.dataChanged.emit()

    def pin_note(self, note_id: int):
        WS.toggle_pin(self.db, note_id)
        self.reload_notes()

    def archive_note(self, note_id: int):
        if W.confirm(self, "Archive this note?\n\nIt stays searchable under 'Show archived'."):
            WS.delete_note(self.db, note_id)
            self.reload()
            self.dataChanged.emit()

    # ----------------------------------------------------------- overview
    def reload(self):
        c = WS.counts(self.db)

        def cell(label, value, colour=""):
            st = f"color:{colour};" if colour else ""
            return (f"<td style='{st}'><span style='font-size:11px'>{label}</span><br>"
                    f"<b style='font-size:17px'>{value}</b></td>")
        self.kpi.setText(
            "<table width='100%'><tr>"
            + cell("Open tasks", c["open_tasks"])
            + cell("Due today", c["due_today"], W.AMBER)
            + cell("Overdue", c["overdue"], W.RED)
            + cell("Urgent", c["urgent"], W.RED)
            + cell("Done today", c["done_today"], W.GREEN)
            + cell("Notes", c["notes"])
            + cell("Pinned", c["pinned_notes"], W.NAVY)
            + "</tr></table>")
        self.reload_tasks()
        self.reload_notes()
