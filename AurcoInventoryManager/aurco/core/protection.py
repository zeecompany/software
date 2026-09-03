"""FILE & FOLDER PROTECTION — make AURCO's records non-deletable.

Read this before trusting it
============================
There are three different levels of "cannot be deleted", and only the first two
are something software can actually guarantee:

  1. **AURCO never deletes.**  Guaranteed. With protection on, the application
     itself will not unlink a single file. Deleting a record in the UI hides it
     and moves its file to `_Archive/`; the bytes stay on disk forever.

  2. **Windows blocks casual deletion.**  Strong. Every file gets the read-only
     attribute (on Windows this really does stop Explorer deleting it, unlike
     Linux) and every folder gets an ACL that denies DELETE to ordinary users.
     A storekeeper cannot delete anything, by accident or on purpose.

  3. **Nobody at all can delete, ever.**  *Not possible from inside an app.*
     A machine Administrator can always take ownership and strip any ACL; and
     nothing stops someone formatting the disk. Any program claiming otherwise
     is lying. What we do instead is make deletion **detectable**: a tamper
     ledger records the size and SHA-256 of every protected file, so a missing
     or altered file is reported the moment you run a check.

For a genuine "no one can delete" you need protection outside the application —
a NAS/Windows share where users have Read+Write but not Delete, or an immutable
backup target. This module sets up (2) and (3) and tells you plainly when the
operating system refused something.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import platform
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import config
from .database import Database

IS_WINDOWS = os.name == "nt"

#: folders inside the storage root whose contents must never be lost
PROTECTED_FOLDERS = [
    "Database", "Delivery Notes", "Reversed Delivery Notes", "Inventory",
    "Reversed Inventory", "Returns", "Reversed Returns", "Stock Transfers",
    "Reversed Stock Transfers", "Stock Adjustments", "Reversed Stock Adjustments",
    "Stock Counts", "Reversed Stock Counts", "Reports", "Attachments", "Exports",
    "Backups", "Logs", "Admin Station", "Company Issuance", "Labels",
]

ARCHIVE_DIR = "_Archive"
SETTING_ENABLED = "protect_files"
SETTING_READONLY = "protect_readonly"
SETTING_ACL = "protect_acl"


# --------------------------------------------------------------------- state
def is_enabled(db: Database) -> bool:
    return db.get_bool(SETTING_ENABLED, True)


def set_enabled(db: Database, on: bool) -> None:
    db.set_setting(SETTING_ENABLED, int(bool(on)))
    db.audit("EDITED", "protection", "", f"file protection {'ON' if on else 'OFF'}")


def ensure_schema(db: Database) -> None:
    db.conn.executescript("""
        CREATE TABLE IF NOT EXISTS protected_files (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            path       TEXT UNIQUE NOT NULL,
            size       INTEGER DEFAULT 0,
            sha256     TEXT DEFAULT '',
            recorded_at TEXT DEFAULT (datetime('now','localtime')),
            last_seen  TEXT DEFAULT '',
            status     TEXT DEFAULT 'OK'
        );
        CREATE INDEX IF NOT EXISTS ix_prot_status ON protected_files(status);
    """)
    db.conn.commit()


# ------------------------------------------------------------------- hashing
def file_hash(path: str | Path, limit_mb: int = 64) -> str:
    """SHA-256 of a file. Large files are hashed head+tail for speed."""
    p = Path(path)
    h = hashlib.sha256()
    try:
        size = p.stat().st_size
        with open(p, "rb") as fh:
            if size <= limit_mb * 1024 * 1024:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            else:
                h.update(fh.read(8 * 1024 * 1024))
                fh.seek(-8 * 1024 * 1024, os.SEEK_END)
                h.update(fh.read())
                h.update(str(size).encode())
    except OSError:
        return ""
    return h.hexdigest()


# ----------------------------------------------------------- OS level locking
def _win_readonly(path: Path, on: bool) -> bool:
    try:
        if on:
            os.chmod(path, stat.S_IREAD)
        else:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        return True
    except OSError:
        return False


def set_readonly(path: str | Path, on: bool = True) -> bool:
    """Set / clear the read-only attribute on one file.

    On Windows this genuinely prevents deletion through Explorer. On Linux and
    macOS the parent directory governs unlink, so this is advisory only — which
    is why `lock_folder()` also hardens the directory itself.
    """
    p = Path(path)
    if not p.exists() or p.is_dir():
        return False
    if IS_WINDOWS:
        return _win_readonly(p, on)
    try:
        mode = p.stat().st_mode
        if on:
            os.chmod(p, mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        else:
            os.chmod(p, mode | stat.S_IWUSR)
        return True
    except OSError:
        return False


def _icacls(folder: Path, args: list[str]) -> tuple[bool, str]:
    """Run icacls on Windows. Returns (ok, message)."""
    if not IS_WINDOWS:
        return False, "ACLs are a Windows feature"
    try:
        r = subprocess.run(["icacls", str(folder)] + args, capture_output=True,
                           text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ok = r.returncode == 0
        return ok, (r.stdout or r.stderr or "").strip()[:400]
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def deny_delete_acl(folder: str | Path, on: bool = True) -> tuple[bool, str]:
    """Deny DELETE / DELETE_CHILD on a folder tree for ordinary users.

    Applied to *Users*, never to Administrators — an admin must stay able to
    restore or migrate the installation. This is the strongest lock the
    application can apply by itself.
    """
    p = Path(folder)
    if not p.exists():
        return False, f"Folder does not exist: {p}"
    if not IS_WINDOWS:
        # Best effort on POSIX: drop write on the directory so its entries
        # cannot be unlinked.
        try:
            mode = p.stat().st_mode
            if on:
                os.chmod(p, mode & ~stat.S_IWGRP & ~stat.S_IWOTH)
            else:
                os.chmod(p, mode | stat.S_IWUSR)
            return True, ("Directory permissions tightened (POSIX). Full "
                          "deny-delete ACLs need Windows.")
        except OSError as exc:
            return False, str(exc)
    verb = "/deny" if on else "/remove:d"
    args = ([verb, "*S-1-5-32-545:(OI)(CI)(DE,DC)"] if on
            else [verb, "*S-1-5-32-545"]) + ["/T", "/C", "/Q"]
    return _icacls(p, args)


def lock_folder(db: Database, folder: str | Path, recursive: bool = True
                ) -> dict:
    """Protect one folder: hash every file, set read-only, deny delete."""
    ensure_schema(db)
    p = Path(folder)
    res = {"folder": str(p), "files": 0, "readonly": 0, "recorded": 0,
           "acl": "", "errors": []}
    if not p.exists():
        res["errors"].append(f"missing: {p}")
        return res
    it = p.rglob("*") if recursive else p.glob("*")
    for f in it:
        if not f.is_file():
            continue
        if ARCHIVE_DIR in f.parts:
            continue
        # never lock the live database or its WAL: SQLite must keep writing
        if f.suffix.lower() in (".db", ".db-wal", ".db-shm", ".sqlite"):
            continue
        res["files"] += 1
        if record_file(db, f):
            res["recorded"] += 1
        if db.get_bool(SETTING_READONLY, True) and set_readonly(f, True):
            res["readonly"] += 1
    if db.get_bool(SETTING_ACL, True):
        ok, msg = deny_delete_acl(p, True)
        res["acl"] = msg if not ok else "deny-delete applied"
        if not ok and msg:
            res["errors"].append(msg)
    db.commit()
    return res


def unlock_folder(db: Database, folder: str | Path) -> dict:
    """Lift protection so an administrator can maintain or move the data."""
    p = Path(folder)
    res = {"folder": str(p), "files": 0, "acl": ""}
    if not p.exists():
        return res
    for f in p.rglob("*"):
        if f.is_file() and set_readonly(f, False):
            res["files"] += 1
    ok, msg = deny_delete_acl(p, False)
    res["acl"] = "deny-delete removed" if ok else msg
    db.audit("EDITED", "protection", str(p), "protection lifted")
    return res


def protect_all(db: Database) -> dict:
    """Lock every AURCO folder in the current storage root."""
    root = config.get_storage_root() or config.default_storage_root()
    total = {"folders": 0, "files": 0, "readonly": 0, "recorded": 0, "errors": []}
    for name in PROTECTED_FOLDERS:
        folder = Path(root) / name
        if not folder.exists():
            continue
        r = lock_folder(db, folder)
        total["folders"] += 1
        for k in ("files", "readonly", "recorded"):
            total[k] += r[k]
        total["errors"] += r["errors"]
    db.audit("EDITED", "protection", str(root),
             f"protected {total['files']} file(s) in {total['folders']} folder(s)")
    return total


# ------------------------------------------------------------ tamper ledger
def record_file(db: Database, path: str | Path) -> bool:
    """Add / refresh a file in the tamper ledger. True when newly recorded."""
    ensure_schema(db)
    p = Path(path)
    if not p.is_file():
        return False
    try:
        size = p.stat().st_size
    except OSError:
        return False
    existing = db.one("SELECT id FROM protected_files WHERE path=?", (str(p),))
    digest = file_hash(p)
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        db.execute("UPDATE protected_files SET size=?, sha256=?, last_seen=?,"
                   " status='OK' WHERE id=?", (size, digest, now, existing["id"]))
        return False
    db.execute("INSERT INTO protected_files(path,size,sha256,recorded_at,last_seen,"
               "status) VALUES(?,?,?,?,?,'OK')", (str(p), size, digest, now, now))
    return True


def verify(db: Database, deep: bool = False) -> dict:
    """Check every recorded file is still present and unchanged.

    `deep` re-hashes; otherwise size is compared, which is fast and catches
    truncation and replacement.
    """
    ensure_schema(db)
    rows = db.query("SELECT * FROM protected_files")
    out = {"checked": len(rows), "ok": 0, "missing": [], "changed": []}
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        p = Path(r["path"])
        if not p.exists():
            out["missing"].append(r["path"])
            db.execute("UPDATE protected_files SET status='MISSING' WHERE id=?",
                       (r["id"],))
            continue
        try:
            size = p.stat().st_size
        except OSError:
            out["missing"].append(r["path"])
            continue
        bad = size != (r["size"] or 0)
        if not bad and deep and r["sha256"]:
            bad = file_hash(p) != r["sha256"]
        if bad:
            out["changed"].append(r["path"])
            db.execute("UPDATE protected_files SET status='CHANGED', last_seen=?"
                       " WHERE id=?", (now, r["id"]))
        else:
            out["ok"] += 1
            db.execute("UPDATE protected_files SET status='OK', last_seen=?"
                       " WHERE id=?", (now, r["id"]))
    db.commit()
    if out["missing"] or out["changed"]:
        db.audit("VALIDATED", "protection", "",
                 f"{len(out['missing'])} missing, {len(out['changed'])} changed")
    return out


def ledger(db: Database, status: str = "") -> list[dict]:
    ensure_schema(db)
    sql = "SELECT * FROM protected_files"
    p: list[Any] = []
    if status:
        sql += " WHERE status=?"
        p.append(status)
    sql += " ORDER BY status<>'OK' DESC, path"
    return [dict(r) for r in db.query(sql, p)]


def stats(db: Database) -> dict:
    ensure_schema(db)
    return {
        "tracked": int(db.scalar("SELECT COUNT(*) FROM protected_files", default=0)),
        "missing": int(db.scalar("SELECT COUNT(*) FROM protected_files"
                                 " WHERE status='MISSING'", default=0)),
        "changed": int(db.scalar("SELECT COUNT(*) FROM protected_files"
                                 " WHERE status='CHANGED'", default=0)),
        "bytes": int(db.scalar("SELECT COALESCE(SUM(size),0) FROM protected_files",
                               default=0)),
    }


# ------------------------------------------------------- safe delete = archive
def archive_instead_of_delete(db: Database, path: str | Path,
                              reason: str = "") -> Path | None:
    """Move a file into `_Archive/` rather than deleting it.

    This is what every 'delete' in AURCO does while protection is on, so the
    bytes are never lost. Returns the new location, or None when the file was
    already gone.
    """
    p = Path(path)
    if not p.exists():
        return None
    archive = p.parent / ARCHIVE_DIR
    archive.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = archive / f"{p.stem}_{stamp}{p.suffix}"
    n = 1
    while dest.exists():
        dest = archive / f"{p.stem}_{stamp}_{n}{p.suffix}"
        n += 1
    try:
        set_readonly(p, False)          # must be writable to move it
        shutil.move(str(p), str(dest))
        set_readonly(dest, True)
    except OSError:
        return None
    db.execute("UPDATE protected_files SET path=?, status='ARCHIVED' WHERE path=?",
               (str(dest), str(p)))
    db.commit()
    db.audit("ARCHIVED", "file", p.name, reason or "kept instead of deleting")
    return dest


def guarded_unlink(db: Database, path: str | Path, reason: str = "") -> bool:
    """The ONLY place AURCO may remove a file.

    While protection is on this never deletes — it archives and reports False,
    so callers can tell the user the file was kept.
    """
    if is_enabled(db):
        archive_instead_of_delete(db, path, reason)
        return False
    p = Path(path)
    try:
        set_readonly(p, False)
        p.unlink()
        db.audit("DELETED", "file", p.name, reason)
        return True
    except OSError:
        return False


def archived_files(db: Database) -> list[dict]:
    """Everything that was 'deleted' but actually kept."""
    root = config.get_storage_root() or config.default_storage_root()
    out = []
    for arc in Path(root).rglob(ARCHIVE_DIR):
        for f in arc.iterdir():
            if not f.is_file():
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            out.append({"path": str(f), "name": f.name,
                        "folder": str(arc.parent.relative_to(root)),
                        "size_kb": round(st.st_size / 1024.0, 1),
                        "archived": _dt.datetime.fromtimestamp(
                            st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    out.sort(key=lambda r: r["archived"], reverse=True)
    return out


def restore_archived(db: Database, path: str | Path) -> Path | None:
    """Put an archived file back where it came from."""
    p = Path(path)
    if not p.exists() or ARCHIVE_DIR not in p.parts:
        return None
    dest = p.parent.parent / p.name
    n = 1
    while dest.exists():
        dest = p.parent.parent / f"{p.stem}_restored{n}{p.suffix}"
        n += 1
    try:
        set_readonly(p, False)
        shutil.move(str(p), str(dest))
        set_readonly(dest, True)
    except OSError:
        return None
    record_file(db, dest)
    db.audit("RESTORED", "file", dest.name, "recovered from archive")
    return dest


def status_report(db: Database) -> dict:
    """Everything the UI needs to describe the current protection state."""
    root = config.get_storage_root() or config.default_storage_root()
    s = stats(db)
    s.update({
        "enabled": is_enabled(db),
        "root": str(root),
        "platform": platform.system(),
        "acl_supported": IS_WINDOWS,
        "archived": len(archived_files(db)),
        "folders": [n for n in PROTECTED_FOLDERS if (Path(root) / n).exists()],
    })
    return s
