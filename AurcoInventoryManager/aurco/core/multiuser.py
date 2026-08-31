"""Multi-PC support — run AURCO on several computers against one shared database.

How it works
------------
The whole system is already file-based: one SQLite database inside the storage
folder. To add a second PC you point both machines at the *same* folder on a
network share and give each person their own login.

    PC 1 (server / store office)      PC 2 (site office, gate, manager)
    D:\\AURCO Inventory        <-->    \\\\STORE-PC\\AURCO Inventory
            \\__ Database\\aurco_inventory.db  (one shared file)

This module makes that safe and easy:

* `configure_shared(path)`     – point this PC at the shared folder and verify
                                 it is reachable and writable
* `apply_network_pragmas(db)`  – WAL + busy timeout so two PCs never corrupt or
                                 "database is locked" each other
* session registry             – every running copy registers itself, so you can
                                 see who else is connected
* `check_health(db)`           – latency, lock and version checks

Concurrency notes
-----------------
SQLite handles many readers and one writer at a time. AURCO writes in short
transactions (a posting takes milliseconds), so 2-10 users on a LAN is
comfortable. The busy timeout makes a second writer wait its turn instead of
failing.
"""
from __future__ import annotations

import datetime as _dt
import os
import socket
import time
from pathlib import Path

from . import config
from .database import Database

HEARTBEAT_SECONDS = 60
STALE_AFTER = 300           # a session is considered gone after 5 minutes


def machine_name() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return os.environ.get("COMPUTERNAME", "PC")


# ------------------------------------------------------------- configuring
def is_network_path(path: str | os.PathLike) -> bool:
    p = str(path)
    return p.startswith("\\\\") or p.startswith("//")


def test_location(path: str | os.PathLike) -> tuple[bool, str]:
    """Check a (possibly shared) folder: reachable, writable, and how fast."""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"The folder cannot be created or reached:\n{exc}"
    probe = p / ".aurco_net_test"
    try:
        t0 = time.perf_counter()
        probe.write_text("ok", encoding="utf-8")
        probe.read_text(encoding="utf-8")
        probe.unlink()
        ms = (time.perf_counter() - t0) * 1000
    except Exception as exc:  # noqa: BLE001
        return False, f"The folder is not writable from this PC:\n{exc}"
    note = f"Reachable and writable.  Round-trip {ms:.0f} ms."
    if ms > 400:
        note += ("\n\nThis share is slow. AURCO will work, but a wired network "
                 "or a faster server is recommended.")
    return True, note


def configure_shared(path: str | os.PathLike) -> Path:
    """Point this PC at a shared storage folder (creates the AURCO structure)."""
    ok, msg = test_location(path)
    if not ok:
        raise OSError(msg)
    root = config.set_storage_root(path)
    return root


def apply_network_pragmas(db: Database, busy_ms: int = 15000) -> None:
    """Make concurrent access from several PCs safe."""
    try:
        db.conn.execute("PRAGMA journal_mode=WAL")
        db.conn.execute(f"PRAGMA busy_timeout={int(busy_ms)}")
        db.conn.execute("PRAGMA synchronous=FULL")
        db.conn.commit()
    except Exception:
        pass


# --------------------------------------------------------------- sessions
def ensure_tables(db: Database) -> None:
    db.conn.executescript("""
    CREATE TABLE IF NOT EXISTS sessions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        machine     TEXT NOT NULL,
        username    TEXT NOT NULL,
        role        TEXT DEFAULT '',
        app_version TEXT DEFAULT '',
        started_at  TEXT,
        last_seen   TEXT,
        UNIQUE(machine, username)
    );""")
    db.conn.commit()


def register_session(db: Database, username: str, role: str = "") -> None:
    ensure_tables(db)
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """INSERT INTO sessions(machine, username, role, app_version, started_at, last_seen)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(machine, username) DO UPDATE SET
             role=excluded.role, app_version=excluded.app_version,
             started_at=excluded.started_at, last_seen=excluded.last_seen""",
        (machine_name(), username, role, config.APP_VERSION, now, now))
    db.commit()


def heartbeat(db: Database, username: str) -> None:
    try:
        db.execute("UPDATE sessions SET last_seen=? WHERE machine=? AND username=?",
                   (_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    machine_name(), username))
        db.commit()
    except Exception:
        pass


def end_session(db: Database, username: str) -> None:
    try:
        db.execute("DELETE FROM sessions WHERE machine=? AND username=?",
                   (machine_name(), username))
        db.commit()
    except Exception:
        pass


def active_sessions(db: Database) -> list[dict]:
    """Who is connected right now (stale rows are dropped)."""
    ensure_tables(db)
    cutoff = (_dt.datetime.now() - _dt.timedelta(seconds=STALE_AFTER)
              ).strftime("%Y-%m-%d %H:%M:%S")
    try:
        db.execute("DELETE FROM sessions WHERE last_seen < ?", (cutoff,))
        db.commit()
    except Exception:
        pass
    return [dict(r) for r in db.query(
        "SELECT * FROM sessions ORDER BY machine, username")]


# ----------------------------------------------------------------- health
def check_health(db: Database) -> list[str]:
    """Diagnostics for a shared installation."""
    out = []
    root = config.get_storage_root()
    out.append(f"Storage folder: {root}")
    out.append("Type: network share" if root and is_network_path(root)
               else "Type: local drive")
    try:
        t0 = time.perf_counter()
        db.scalar("SELECT COUNT(*) FROM items")
        out.append(f"Database read: {(time.perf_counter() - t0) * 1000:.0f} ms")
    except Exception as exc:  # noqa: BLE001
        out.append(f"Database read FAILED: {exc}")
    try:
        mode = db.scalar("PRAGMA journal_mode", default="?")
        busy = db.scalar("PRAGMA busy_timeout", default="?")
        out.append(f"Journal mode: {mode} (WAL is required for multi-PC use)")
        out.append(f"Busy timeout: {busy} ms")
    except Exception:
        pass
    users = active_sessions(db)
    out.append(f"Connected now: {len(users)}")
    for u in users:
        out.append(f"   • {u['username']} on {u['machine']} "
                   f"({u['role'] or 'no role'}, v{u['app_version']}) "
                   f"last seen {u['last_seen']}")
    accounts = db.scalar("SELECT COUNT(*) FROM users WHERE active=1")
    withpw = db.scalar("SELECT COUNT(*) FROM users WHERE active=1 AND password_hash<>''")
    out.append(f"User accounts: {accounts} active, {withpw} with a password")
    if withpw == 0:
        out.append("   ⚠ Set a password for each user so every PC signs in "
                   "with its own account.")
    return out


def connection_guide(root: str | os.PathLike | None = None) -> str:
    """Step-by-step text shown in Settings for connecting a second PC."""
    root = root or config.get_storage_root() or r"D:\AURCO Inventory"
    host = machine_name()
    return f"""HOW TO CONNECT A SECOND COMPUTER

ON THIS PC (the one holding the data)
  1. Storage folder:  {root}
  2. In Windows Explorer right-click that folder → Properties → Sharing →
     Advanced Sharing → tick "Share this folder".
  3. Permissions → add the users who need access → allow Change + Read.
  4. Note the share path, e.g.   \\\\{host}\\AURCO Inventory
  5. Keep this PC switched on while others are working.

ON THE SECOND PC
  6. Install AURCO Inventory Manager (or copy the program folder).
  7. Start it. When it asks for the storage location, or in
     Settings → Storage & Backup, enter the share path from step 4.
  8. Press "Test Location" — it must report reachable and writable.
  9. Sign in with that person's own user name and password.

USER ACCOUNTS AND ACCESS
 10. Settings → Users & Permissions → add one account per person and give each
     a role: Administrator, Storekeeper, Logistics or Viewer.
 11. Settings → Security & Login → set a password for each account and switch
     on "Ask for a user name and password when AURCO starts".
 12. Permissions can be tuned per user (issue stock, reverse documents,
     change settings, delete items, and so on).

GOOD TO KNOW
  • Everyone sees the same live stock, documents, PR/MR numbers and reports.
  • Document numbers stay unique — the counter lives in the shared database.
  • Every action is written to the audit trail with the user name and PC.
  • Settings → Storage & Backup → Multi-user shows who is connected.
  • Use a wired network where possible; keep automatic backups switched on.
"""
