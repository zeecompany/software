"""Notes and Tasks — the storekeeper's personal workspace.

Notes  : quick reminders, pinned, colour-tagged, searchable, optionally linked
         to an item / document / project.
Tasks  : daily work list with priority, due date, reminder, assignee, checklist
         progress, recurrence and a link back to any record in the system.

Both are deliberately lightweight: no approval flow, no separate app — just a
fast place to write things down so nothing is forgotten between shifts.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from .database import Database

# ------------------------------------------------------------------ notes
NOTE_COLORS = {
    "Yellow": "#fff3bf", "Green": "#d3f9d8", "Blue": "#d0ebff",
    "Pink": "#ffdeeb", "Grey": "#e9ecef", "Orange": "#ffe8cc",
}

# ------------------------------------------------------------------ tasks
PRIORITIES = ["Low", "Normal", "High", "Urgent"]
PRIORITY_COLORS = {"Low": "#868e96", "Normal": "#1098ad",
                   "High": "#e8590c", "Urgent": "#c92a2a"}

STATUSES = ["To Do", "In Progress", "Blocked", "Done", "Cancelled"]
STATUS_COLORS = {"To Do": "#6b7c8f", "In Progress": "#1098ad", "Blocked": "#c92a2a",
                 "Done": "#1a9c52", "Cancelled": "#868e96"}
OPEN_STATUSES = ("To Do", "In Progress", "Blocked")

REPEATS = ["None", "Daily", "Weekly", "Monthly"]


def today() -> str:
    return _dt.date.today().isoformat()


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =================================================================== notes
def list_notes(db: Database, text: str = "", include_archived: bool = False,
               category: str = "") -> list[dict]:
    sql = "SELECT * FROM notes WHERE 1=1"
    p: list[Any] = []
    if not include_archived:
        sql += " AND archived=0"
    if category:
        sql += " AND category=?"
        p.append(category)
    if text:
        like = f"%{text}%"
        sql += " AND (title LIKE ? OR body LIKE ? OR category LIKE ? OR link_ref LIKE ?)"
        p += [like] * 4
    sql += " ORDER BY pinned DESC, updated_at DESC"
    return [dict(r) for r in db.query(sql, p)]


def save_note(db: Database, data: dict, note_id: int | None = None) -> int:
    fields = ("title", "body", "color", "category", "pinned", "archived",
              "link_type", "link_ref")
    d = {k: v for k, v in data.items() if k in fields}
    if not (d.get("title") or "").strip() and not (d.get("body") or "").strip():
        raise ValueError("A note needs a title or some text.")
    if note_id:
        sets = ", ".join(f"{k}=?" for k in d)
        db.execute(f"UPDATE notes SET {sets}, updated_at=? WHERE id=?",
                   list(d.values()) + [_now(), note_id])
        db.commit()
        db.audit("EDITED", "note", d.get("title", note_id))
        return note_id
    d.setdefault("color", "Yellow")
    cols = ", ".join(d)
    qs = ", ".join("?" * len(d))
    cur = db.execute(
        f"INSERT INTO notes({cols}, created_by, created_at, updated_at)"
        f" VALUES({qs}, ?, ?, ?)",
        list(d.values()) + [db.current_user, _now(), _now()])
    db.commit()
    db.audit("CREATED", "note", d.get("title", ""))
    return int(cur.lastrowid)


def delete_note(db: Database, note_id: int, hard: bool = False) -> None:
    row = db.one("SELECT title FROM notes WHERE id=?", (note_id,))
    if hard:
        db.execute("DELETE FROM notes WHERE id=?", (note_id,))
    else:
        db.execute("UPDATE notes SET archived=1, updated_at=? WHERE id=?", (_now(), note_id))
    db.commit()
    db.audit("DELETED", "note", row["title"] if row else note_id,
             "removed" if hard else "archived")


def toggle_pin(db: Database, note_id: int) -> None:
    db.execute("UPDATE notes SET pinned = CASE pinned WHEN 1 THEN 0 ELSE 1 END,"
               " updated_at=? WHERE id=?", (_now(), note_id))
    db.commit()


# =================================================================== tasks
def list_tasks(db: Database, status: str = "", text: str = "", assignee: str = "",
               priority: str = "", due: str = "", include_done: bool = True) -> list[dict]:
    """due: '' | 'today' | 'overdue' | 'week' | 'nodate'"""
    sql = "SELECT * FROM tasks WHERE 1=1"
    p: list[Any] = []
    if status:
        sql += " AND status=?"
        p.append(status)
    elif not include_done:
        sql += " AND status IN ('To Do','In Progress','Blocked')"
    if assignee:
        sql += " AND assignee=?"
        p.append(assignee)
    if priority:
        sql += " AND priority=?"
        p.append(priority)
    if text:
        like = f"%{text}%"
        sql += (" AND (title LIKE ? OR details LIKE ? OR category LIKE ?"
                " OR link_ref LIKE ? OR assignee LIKE ?)")
        p += [like] * 5
    t = today()
    if due == "today":
        sql += " AND due_date=?"
        p.append(t)
    elif due == "overdue":
        sql += " AND due_date<>'' AND due_date<? AND status IN ('To Do','In Progress','Blocked')"
        p.append(t)
    elif due == "week":
        end = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
        sql += " AND due_date<>'' AND due_date BETWEEN ? AND ?"
        p += [t, end]
    elif due == "nodate":
        sql += " AND (due_date IS NULL OR due_date='')"
    sql += (" ORDER BY CASE status WHEN 'Blocked' THEN 0 WHEN 'In Progress' THEN 1"
            " WHEN 'To Do' THEN 2 ELSE 3 END,"
            " CASE priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1"
            " WHEN 'Normal' THEN 2 ELSE 3 END,"
            " CASE WHEN due_date='' THEN 1 ELSE 0 END, due_date, id DESC")
    rows = [dict(r) for r in db.query(sql, p)]
    for r in rows:
        r["overdue"] = bool(r["due_date"] and r["due_date"] < t
                            and r["status"] in OPEN_STATUSES)
        r["due_today"] = bool(r["due_date"] == t and r["status"] in OPEN_STATUSES)
    return rows


def save_task(db: Database, data: dict, task_id: int | None = None) -> int:
    fields = ("title", "details", "status", "priority", "due_date", "due_time",
              "assignee", "category", "progress", "checklist", "repeat_rule",
              "remind", "link_type", "link_ref")
    d = {k: v for k, v in data.items() if k in fields}
    if not (d.get("title") or "").strip():
        raise ValueError("A task needs a title.")
    if task_id:
        prev = db.one("SELECT status FROM tasks WHERE id=?", (task_id,))
        sets = ", ".join(f"{k}=?" for k in d)
        db.execute(f"UPDATE tasks SET {sets}, updated_at=? WHERE id=?",
                   list(d.values()) + [_now(), task_id])
        if d.get("status") == "Done" and prev and prev["status"] != "Done":
            db.execute("UPDATE tasks SET completed_at=?, progress=100 WHERE id=?",
                       (_now(), task_id))
            _spawn_repeat(db, task_id)
        db.commit()
        db.audit("EDITED", "task", d.get("title", task_id))
        return task_id
    d.setdefault("status", "To Do")
    d.setdefault("priority", "Normal")
    cols = ", ".join(d)
    qs = ", ".join("?" * len(d))
    cur = db.execute(
        f"INSERT INTO tasks({cols}, created_by, created_at, updated_at)"
        f" VALUES({qs}, ?, ?, ?)",
        list(d.values()) + [db.current_user, _now(), _now()])
    db.commit()
    db.audit("CREATED", "task", d["title"])
    return int(cur.lastrowid)


def set_status(db: Database, task_id: int, status: str) -> None:
    prev = db.one("SELECT status, title FROM tasks WHERE id=?", (task_id,))
    extra = ", completed_at=?, progress=100" if status == "Done" else ""
    params: list[Any] = [status, _now()]
    if status == "Done":
        params.append(_now())
    db.execute(f"UPDATE tasks SET status=?, updated_at=?{extra} WHERE id=?",
               params + [task_id])
    db.commit()
    if status == "Done" and prev and prev["status"] != "Done":
        _spawn_repeat(db, task_id)
    db.audit("EDITED", "task", prev["title"] if prev else task_id, f"status -> {status}")


def _spawn_repeat(db: Database, task_id: int) -> int | None:
    """When a recurring task is completed, queue the next occurrence."""
    t = db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
    if not t or (t["repeat_rule"] or "None") == "None":
        return None
    base = t["due_date"] or today()
    try:
        d0 = _dt.date.fromisoformat(base)
    except ValueError:
        d0 = _dt.date.today()
    rule = t["repeat_rule"]
    if rule == "Daily":
        nxt = d0 + _dt.timedelta(days=1)
    elif rule == "Weekly":
        nxt = d0 + _dt.timedelta(weeks=1)
    else:
        month = d0.month + 1
        year = d0.year + (1 if month > 12 else 0)
        month = 1 if month > 12 else month
        day = min(d0.day, 28)
        nxt = _dt.date(year, month, day)
    return save_task(db, {
        "title": t["title"], "details": t["details"], "priority": t["priority"],
        "due_date": nxt.isoformat(), "due_time": t["due_time"], "assignee": t["assignee"],
        "category": t["category"], "checklist": t["checklist"],
        "repeat_rule": t["repeat_rule"], "remind": t["remind"],
        "link_type": t["link_type"], "link_ref": t["link_ref"], "status": "To Do",
        "progress": 0})


def delete_task(db: Database, task_id: int) -> None:
    row = db.one("SELECT title FROM tasks WHERE id=?", (task_id,))
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    db.commit()
    db.audit("DELETED", "task", row["title"] if row else task_id)


# ------------------------------------------------------------- checklists
def parse_checklist(raw: str | None) -> list[tuple[bool, str]]:
    out = []
    for line in (raw or "").splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        done = line.strip().lower().startswith(("[x]", "[X]".lower()))
        text = line.strip()[3:].strip() if line.strip()[:3] in ("[x]", "[ ]", "[X]") else line.strip()
        out.append((done, text))
    return out


def checklist_progress(raw: str | None) -> int:
    items = parse_checklist(raw)
    if not items:
        return 0
    return int(round(100 * sum(1 for d, _ in items if d) / len(items)))


# --------------------------------------------------------------- overview
def counts(db: Database) -> dict:
    t = today()
    return {
        "open_tasks": db.scalar(
            "SELECT COUNT(*) FROM tasks WHERE status IN ('To Do','In Progress','Blocked')"),
        "due_today": db.scalar(
            "SELECT COUNT(*) FROM tasks WHERE due_date=? AND"
            " status IN ('To Do','In Progress','Blocked')", (t,)),
        "overdue": db.scalar(
            "SELECT COUNT(*) FROM tasks WHERE due_date<>'' AND due_date<? AND"
            " status IN ('To Do','In Progress','Blocked')", (t,)),
        "urgent": db.scalar(
            "SELECT COUNT(*) FROM tasks WHERE priority='Urgent' AND"
            " status IN ('To Do','In Progress','Blocked')"),
        "done_today": db.scalar(
            "SELECT COUNT(*) FROM tasks WHERE status='Done' AND substr(completed_at,1,10)=?",
            (t,)),
        "notes": db.scalar("SELECT COUNT(*) FROM notes WHERE archived=0"),
        "pinned_notes": db.scalar("SELECT COUNT(*) FROM notes WHERE archived=0 AND pinned=1"),
    }


def reminders(db: Database) -> list[dict]:
    """Tasks that should pop a reminder now (due today/overdue, remind on)."""
    t = today()
    return [dict(r) for r in db.query(
        "SELECT * FROM tasks WHERE remind=1 AND status IN ('To Do','In Progress','Blocked')"
        " AND due_date<>'' AND due_date<=? ORDER BY due_date", (t,))]


def due_now(db: Database, grace_minutes: int = 1) -> list[dict]:
    """Tasks whose reminder moment has just arrived and has not fired yet.

    A task with a due time alerts at that time; a task with only a date alerts
    once, the first time it is checked on that day. `alerted_at` stops the same
    task ringing again.
    """
    now = _dt.datetime.now()
    t = now.date().isoformat()
    out = []
    for r in db.query(
            "SELECT * FROM tasks WHERE remind=1 AND status IN ('To Do','In Progress','Blocked')"
            " AND due_date<>'' AND due_date<=?", (t,)):
        row = dict(r)
        if (row.get("alerted_at") or "")[:10] == t:
            continue                      # already rang today
        due_t = (row.get("due_time") or "").strip()
        if due_t and row["due_date"] == t:
            try:
                hh, mm = [int(x) for x in due_t.replace(".", ":").split(":")[:2]]
                when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if now < when - _dt.timedelta(minutes=grace_minutes):
                    continue              # not time yet
            except (ValueError, TypeError):
                pass
        out.append(row)
    return out


def mark_alerted(db: Database, task_ids: list[int]) -> None:
    if not task_ids:
        return
    stamp = _now()
    db.executemany("UPDATE tasks SET alerted_at=? WHERE id=?",
                   [(stamp, i) for i in task_ids])
    db.commit()


def snooze(db: Database, task_id: int, minutes: int = 10) -> None:
    """Silence a task for a while by clearing today's alert stamp later."""
    when = _dt.datetime.now() + _dt.timedelta(minutes=minutes)
    db.execute("UPDATE tasks SET alerted_at=? WHERE id=?",
               (when.strftime("%Y-%m-%d %H:%M:%S"), task_id))
    db.commit()
