"""DOCUMENT LIBRARY — sync folders of scanned Delivery Notes and see them all.

The problem this solves: signed Delivery Notes, gate passes and site photos end
up scattered across a shared drive in folders and sub-folders, as PDFs and
JPEGs, with no connection to the system that produced them.

This module indexes those folders so every file can be found, previewed,
printed and — where possible — matched back to the Delivery Note record it
belongs to.

Design decisions worth knowing:

  ·  **Files are never moved or copied.** The library is an *index*: it records
     where a file lives, its size and its fingerprint. Your folder structure is
     left exactly as the site team made it. Nothing here deletes either.
  ·  **Sub-folders are included** by default, because that is how people
     actually file things (by month, by project, by site).
  ·  **Document numbers are detected from the file name**, so a scan called
     `DN-2026-00821 signed.pdf` links itself to that Delivery Note. Detection
     is reported, never assumed — an unmatched file is still listed.
  ·  **A file that disappears is flagged, not forgotten**, so you can tell the
     difference between "never scanned" and "someone deleted the scan".
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import config
from .database import Database

# What counts as a viewable document
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp")
PDF_SUFFIXES = (".pdf",)
OFFICE_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".docx", ".doc", ".csv", ".txt")
ALL_SUFFIXES = IMAGE_SUFFIXES + PDF_SUFFIXES + OFFICE_SUFFIXES

KIND_PDF = "PDF"
KIND_IMAGE = "Image"
KIND_OFFICE = "Document"
KINDS = [KIND_PDF, KIND_IMAGE, KIND_OFFICE]

DDL = """
CREATE TABLE IF NOT EXISTS library_folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    path       TEXT UNIQUE NOT NULL,
    label      TEXT DEFAULT '',
    recursive  INTEGER NOT NULL DEFAULT 1,
    active     INTEGER NOT NULL DEFAULT 1,
    last_scan  TEXT DEFAULT '',
    added_at   TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS library_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id   INTEGER REFERENCES library_folders(id) ON DELETE CASCADE,
    path        TEXT UNIQUE NOT NULL,
    name        TEXT DEFAULT '',
    subfolder   TEXT DEFAULT '',
    kind        TEXT DEFAULT '',
    size        INTEGER DEFAULT 0,
    modified    TEXT DEFAULT '',
    doc_no      TEXT DEFAULT '',
    doc_type    TEXT DEFAULT '',
    matched     INTEGER NOT NULL DEFAULT 0,
    project     TEXT DEFAULT '',
    pr_no       TEXT DEFAULT '',
    tags        TEXT DEFAULT '',
    notes       TEXT DEFAULT '',
    sha256      TEXT DEFAULT '',
    status      TEXT DEFAULT 'OK',
    first_seen  TEXT DEFAULT '',
    last_seen   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_lib_folder ON library_files(folder_id);
CREATE INDEX IF NOT EXISTS ix_lib_docno  ON library_files(doc_no);
CREATE INDEX IF NOT EXISTS ix_lib_name   ON library_files(name);
CREATE INDEX IF NOT EXISTS ix_lib_status ON library_files(status);
"""


def ensure_schema(db: Database) -> None:
    db.conn.executescript(DDL)
    db.conn.commit()


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def kind_of(path: str | Path) -> str:
    suf = Path(path).suffix.lower()
    if suf in PDF_SUFFIXES:
        return KIND_PDF
    if suf in IMAGE_SUFFIXES:
        return KIND_IMAGE
    return KIND_OFFICE


# ------------------------------------------------------- document detection
#: DN-2026-00821, GRN-2026-1, RET_2026_007, GDN 2026 12, ISS-2026-00003 ...
# NOTE: PR/MR are deliberately NOT document prefixes here. A name like
# "scan PRJ_0000026 PR 001603.pdf" would otherwise be misread as the document
# "PR-0016-00003" by greedily splitting the PR number. PR/MR are captured
# separately by _PR_RE as a reference, which is what they actually are.
_DOC_RE = re.compile(
    r"\b(DN|GDN|GRN|RET|TRF|ADJ|CNT|ISS)[\s_\-]*"
    r"(20\d{2})[\s_\-]*(\d{1,7})\b", re.I)
#: bare forms people actually type: DN-0737, DN737
_SHORT_RE = re.compile(r"\b(DN|GDN|GRN|RET|TRF|ADJ|CNT)[\s_\-]*(\d{2,7})\b", re.I)
_PR_RE = re.compile(r"\b(?:PR|MR)(?!J)[\s_\-]*(\d{4,8})\b", re.I)
_PRJ_RE = re.compile(r"\b(PRJ[\s_\-]?\d{4,10}(?:-\d+)?)\b", re.I)


def detect_doc_no(name: str) -> tuple[str, str]:
    """Pull a document number out of a file name.

    Returns (doc_no, doc_type); both blank when nothing recognisable is there.
    The separator is normalised to '-' so `DN_2026_00821` and `DN 2026 00821`
    both resolve to `DN-2026-00821`.
    """
    text = str(name or "")
    m = _DOC_RE.search(text)
    if m:
        prefix, year, seq = m.group(1).upper(), m.group(2), m.group(3)
        return f"{prefix}-{year}-{seq.zfill(5)}", prefix
    m = _SHORT_RE.search(text)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}", m.group(1).upper()
    return "", ""


def detect_project(name: str) -> str:
    m = _PRJ_RE.search(str(name or ""))
    return m.group(1).upper().replace(" ", "_") if m else ""


def detect_pr(name: str) -> str:
    m = _PR_RE.search(str(name or ""))
    return m.group(1) if m else ""


def _match_document(db: Database, doc_no: str) -> tuple[bool, str]:
    """Is this document number a real record in the system?"""
    if not doc_no:
        return False, ""
    row = db.one("SELECT doc_type FROM documents WHERE doc_no=?", (doc_no,))
    if row:
        return True, row["doc_type"]
    row = db.one("SELECT 1 FROM gdn_documents WHERE doc_no=?", (doc_no,))
    if row:
        return True, "GDN"
    # tolerate a file named with an unpadded sequence
    base = doc_no.rsplit("-", 1)
    if len(base) == 2 and base[1].isdigit():
        like = f"{base[0]}-%{int(base[1])}"
        row = db.one("SELECT doc_no, doc_type FROM documents WHERE doc_no LIKE ?"
                     " ORDER BY length(doc_no) LIMIT 1", (like,))
        if row and row["doc_no"].endswith(str(int(base[1])).zfill(5)):
            return True, row["doc_type"]
    return False, ""


def file_hash(path: str | Path, limit_mb: int = 32) -> str:
    p = Path(path)
    h = hashlib.sha256()
    try:
        size = p.stat().st_size
        with open(p, "rb") as fh:
            if size <= limit_mb * 1024 * 1024:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            else:
                h.update(fh.read(4 * 1024 * 1024))
                fh.seek(-4 * 1024 * 1024, os.SEEK_END)
                h.update(fh.read())
                h.update(str(size).encode())
    except OSError:
        return ""
    return h.hexdigest()


# ------------------------------------------------------------------ folders
def folder_status(path: str | Path) -> tuple[bool, str]:
    """Check a sync folder before promising anything."""
    if not str(path or "").strip():
        return False, "No folder selected."
    p = Path(path)
    if not p.exists():
        return False, f"The folder does not exist or is offline:\n{p}"
    if not p.is_dir():
        return False, f"That path is a file, not a folder:\n{p}"
    if not os.access(p, os.R_OK):
        return False, f"No permission to read:\n{p}"
    return True, ("Read and write access." if os.access(p, os.W_OK)
                  else "Read-only — files can be viewed but not renamed.")


def add_folder(db: Database, path: str | Path, label: str = "",
               recursive: bool = True) -> int:
    ensure_schema(db)
    p = str(Path(path))
    ok, msg = folder_status(p)
    if not ok:
        raise ValueError(msg)
    existing = db.one("SELECT id FROM library_folders WHERE path=?", (p,))
    if existing:
        db.execute("UPDATE library_folders SET active=1, label=?, recursive=?"
                   " WHERE id=?", (label, int(recursive), existing["id"]))
        db.commit()
        return int(existing["id"])
    cur = db.execute("INSERT INTO library_folders(path,label,recursive) VALUES(?,?,?)",
                     (p, label or Path(p).name, int(recursive)))
    db.commit()
    db.audit("CREATED", "library-folder", p, label)
    return int(cur.lastrowid)


def remove_folder(db: Database, folder_id: int, forget_files: bool = True) -> None:
    """Stop syncing a folder. The files on disk are never touched."""
    row = db.one("SELECT path FROM library_folders WHERE id=?", (folder_id,))
    if forget_files:
        db.execute("DELETE FROM library_files WHERE folder_id=?", (folder_id,))
    db.execute("DELETE FROM library_folders WHERE id=?", (folder_id,))
    db.commit()
    db.audit("DELETED", "library-folder", row["path"] if row else folder_id,
             "removed from the library index (files left on disk)")


def folders(db: Database, active_only: bool = False) -> list[dict]:
    ensure_schema(db)
    sql = "SELECT * FROM library_folders"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY id"
    out = []
    for r in db.query(sql):
        d = dict(r)
        ok, msg = folder_status(d["path"])
        d["online"] = ok
        d["message"] = msg
        d["files"] = int(db.scalar("SELECT COUNT(*) FROM library_files"
                                   " WHERE folder_id=?", (d["id"],), default=0))
        out.append(d)
    return out


def set_folder_active(db: Database, folder_id: int, active: bool) -> None:
    db.execute("UPDATE library_folders SET active=? WHERE id=?",
               (int(active), folder_id))
    db.commit()


# --------------------------------------------------------------------- sync
def sync_folder(db: Database, folder_id: int, deep: bool = False) -> dict:
    """Index one folder (and its sub-folders). Nothing on disk is modified."""
    ensure_schema(db)
    row = db.one("SELECT * FROM library_folders WHERE id=?", (folder_id,))
    if row is None:
        return {"added": 0, "updated": 0, "missing": 0, "errors": ["unknown folder"]}
    base = Path(row["path"])
    res = {"folder": str(base), "added": 0, "updated": 0, "missing": 0,
           "scanned": 0, "errors": []}
    ok, msg = folder_status(base)
    if not ok:
        res["errors"].append(msg)
        return res

    seen: set[str] = set()
    walker: Iterable[Path] = (base.rglob("*") if row["recursive"] else base.glob("*"))
    for f in walker:
        try:
            if not f.is_file():
                continue
        except OSError:
            continue
        if f.suffix.lower() not in ALL_SUFFIXES:
            continue
        if f.name.startswith("~$") or f.name.startswith("."):
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        res["scanned"] += 1
        key = str(f)
        seen.add(key)
        try:
            sub = str(f.parent.relative_to(base))
        except ValueError:
            sub = ""
        sub = "" if sub == "." else sub
        doc_no, doc_type = detect_doc_no(f.name)
        if not doc_no and sub:
            doc_no, doc_type = detect_doc_no(sub)
        matched, real_type = _match_document(db, doc_no)
        modified = _dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        project = detect_project(f.name) or detect_project(sub)
        pr_no = detect_pr(f.name)

        prev = db.one("SELECT id, size, modified FROM library_files WHERE path=?",
                      (key,))
        digest = file_hash(f) if deep else ""
        if prev:
            changed = (int(prev["size"] or 0) != st.st_size
                       or (prev["modified"] or "") != modified)
            db.execute(
                """UPDATE library_files SET folder_id=?, name=?, subfolder=?, kind=?,
                     size=?, modified=?, doc_no=?, doc_type=?, matched=?, project=?,
                     pr_no=?, status='OK', last_seen=?
                     {} WHERE id=?""".format(", sha256=?" if deep else ""),
                ([folder_id, f.name, sub, kind_of(f), st.st_size, modified, doc_no,
                  real_type or doc_type, int(matched), project, pr_no, _now()]
                 + ([digest] if deep else []) + [prev["id"]]))
            if changed:
                res["updated"] += 1
        else:
            db.execute(
                """INSERT INTO library_files(folder_id,path,name,subfolder,kind,size,
                     modified,doc_no,doc_type,matched,project,pr_no,sha256,status,
                     first_seen,last_seen)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'OK',?,?)""",
                (folder_id, key, f.name, sub, kind_of(f), st.st_size, modified,
                 doc_no, real_type or doc_type, int(matched), project, pr_no,
                 digest, _now(), _now()))
            res["added"] += 1

    # anything indexed before but no longer on disk
    for r in db.query("SELECT id, path FROM library_files WHERE folder_id=?",
                      (folder_id,)):
        if r["path"] not in seen:
            db.execute("UPDATE library_files SET status='MISSING' WHERE id=?",
                       (r["id"],))
            res["missing"] += 1

    db.execute("UPDATE library_folders SET last_scan=? WHERE id=?", (_now(), folder_id))
    db.commit()
    db.audit("IMPORTED", "library", str(base),
             f"{res['added']} new, {res['updated']} updated, {res['missing']} missing")
    return res


def sync_all(db: Database, deep: bool = False) -> dict:
    total = {"folders": 0, "added": 0, "updated": 0, "missing": 0, "scanned": 0,
             "errors": []}
    for f in folders(db, active_only=True):
        r = sync_folder(db, f["id"], deep)
        total["folders"] += 1
        for k in ("added", "updated", "missing", "scanned"):
            total[k] += r[k]
        total["errors"] += r["errors"]
    return total


def relink(db: Database) -> int:
    """Re-check every indexed file against the document records.

    Useful after importing old documents: a scan that could not be matched
    before will link itself once the record exists.
    """
    ensure_schema(db)
    n = 0
    for r in db.query("SELECT id, doc_no, matched FROM library_files"
                      " WHERE COALESCE(doc_no,'')<>''"):
        matched, dtype = _match_document(db, r["doc_no"])
        if int(r["matched"] or 0) != int(matched):
            db.execute("UPDATE library_files SET matched=?, doc_type=COALESCE(?,doc_type)"
                       " WHERE id=?", (int(matched), dtype or None, r["id"]))
            n += 1
    if n:
        db.commit()
        db.audit("EDITED", "library", "", f"{n} file(s) re-linked")
    return n


# ------------------------------------------------------------------ queries
def search(db: Database, text: str = "", folder_id: int | None = None,
           kind: str = "", subfolder: str = "", project: str = "",
           only_missing: bool = False, only_unmatched: bool = False,
           only_matched: bool = False, date_from: str = "",
           date_to: str = "") -> list[dict]:
    ensure_schema(db)
    sql = "SELECT f.*, d.label AS folder_label FROM library_files f" \
          " LEFT JOIN library_folders d ON d.id=f.folder_id WHERE 1=1"
    p: list[Any] = []
    if text.strip():
        like = f"%{text.strip()}%"
        sql += (" AND (f.name LIKE ? OR f.subfolder LIKE ? OR f.doc_no LIKE ?"
                " OR f.project LIKE ? OR f.pr_no LIKE ? OR f.tags LIKE ?"
                " OR f.notes LIKE ? OR f.path LIKE ?)")
        p += [like] * 8
    if folder_id:
        sql += " AND f.folder_id=?"
        p.append(folder_id)
    if kind:
        sql += " AND f.kind=?"
        p.append(kind)
    if subfolder:
        sql += " AND f.subfolder=?"
        p.append(subfolder)
    if project:
        sql += " AND f.project=?"
        p.append(project)
    if only_missing:
        sql += " AND f.status='MISSING'"
    else:
        sql += " AND f.status<>'MISSING'"
    if only_unmatched:
        sql += " AND f.matched=0"
    if only_matched:
        sql += " AND f.matched=1"
    if date_from:
        sql += " AND substr(f.modified,1,10)>=?"
        p.append(date_from)
    if date_to:
        sql += " AND substr(f.modified,1,10)<=?"
        p.append(date_to)
    sql += " ORDER BY f.modified DESC, f.name LIMIT 20000"
    return [dict(r) for r in db.query(sql, p)]


def get_file(db: Database, file_id: int) -> dict | None:
    r = db.one("SELECT * FROM library_files WHERE id=?", (file_id,))
    return dict(r) if r else None


def for_document(db: Database, doc_no: str) -> list[dict]:
    """Every indexed scan belonging to one document number."""
    ensure_schema(db)
    if not doc_no:
        return []
    return [dict(r) for r in db.query(
        "SELECT * FROM library_files WHERE doc_no=? AND status<>'MISSING'"
        " ORDER BY name", (doc_no,))]


def distinct(db: Database, column: str) -> list[str]:
    if column not in ("subfolder", "kind", "project", "doc_type", "pr_no"):
        return []
    return [r[0] for r in db.query(
        f"SELECT DISTINCT {column} FROM library_files"
        f" WHERE COALESCE({column},'')<>'' ORDER BY {column}")]


def set_meta(db: Database, file_id: int, doc_no: str | None = None,
             tags: str | None = None, notes: str | None = None,
             project: str | None = None) -> None:
    """Correct the detected metadata by hand."""
    row = get_file(db, file_id)
    if row is None:
        return
    doc_no = row["doc_no"] if doc_no is None else doc_no.strip()
    matched, dtype = _match_document(db, doc_no)
    db.execute("""UPDATE library_files SET doc_no=?, doc_type=?, matched=?,
                    tags=COALESCE(?,tags), notes=COALESCE(?,notes),
                    project=COALESCE(?,project) WHERE id=?""",
               (doc_no, dtype or row["doc_type"], int(matched), tags, notes,
                project, file_id))
    db.commit()
    db.audit("EDITED", "library-file", row["name"], f"linked to {doc_no or '-'}")


def forget(db: Database, file_ids: Sequence[int]) -> int:
    """Remove entries from the INDEX only. Files on disk are never deleted."""
    ids = list(file_ids)
    if not ids:
        return 0
    db.execute(f"DELETE FROM library_files WHERE id IN ({','.join('?' * len(ids))})",
               ids)
    db.commit()
    db.audit("DELETED", "library-file", "",
             f"{len(ids)} entr(y/ies) removed from the index — files kept on disk")
    return len(ids)


# ------------------------------------------------------------------- stats
def stats(db: Database, f: dict | None = None) -> dict:
    ensure_schema(db)
    rows = search(db, **{k: v for k, v in (f or {}).items()
                         if k in ("text", "folder_id", "kind", "subfolder",
                                  "project", "only_unmatched", "only_matched",
                                  "date_from", "date_to")})
    total = len(rows)
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    matched = sum(1 for r in rows if r["matched"])
    missing = int(db.scalar("SELECT COUNT(*) FROM library_files"
                            " WHERE status='MISSING'", default=0))
    return {
        "files": total,
        "pdf": by_kind.get(KIND_PDF, 0),
        "images": by_kind.get(KIND_IMAGE, 0),
        "other": by_kind.get(KIND_OFFICE, 0),
        "matched": matched,
        "unmatched": total - matched,
        "match_pct": (matched / total * 100.0) if total else 0.0,
        "missing": missing,
        "folders": len(folders(db, active_only=True)),
        "subfolders": len({r["subfolder"] for r in rows if r["subfolder"]}),
        "bytes": sum(int(r["size"] or 0) for r in rows),
        "last_scan": (db.scalar("SELECT MAX(last_scan) FROM library_folders",
                                default="") or ""),
    }


def by_column(db: Database, column: str, limit: int = 10,
              f: dict | None = None) -> list[tuple[str, float]]:
    rows = search(db, **{k: v for k, v in (f or {}).items()
                         if k in ("text", "folder_id", "kind", "subfolder",
                                  "project", "only_unmatched", "only_matched")})
    agg: dict[str, int] = {}
    for r in rows:
        key = str(r.get(column) or "(none)")
        agg[key] = agg.get(key, 0) + 1
    return sorted(agg.items(), key=lambda kv: -kv[1])[:limit]


def monthly(db: Database, months: int = 12) -> list[tuple[str, float]]:
    rows = db.query(
        "SELECT substr(modified,1,7) m, COUNT(*) n FROM library_files"
        " WHERE length(modified)>=7 AND status<>'MISSING'"
        " GROUP BY m ORDER BY m DESC LIMIT ?", (months,))
    return [(r["m"][-2:], float(r["n"])) for r in reversed(rows)]


# ------------------------------------------------------------------ preview
def preview_image(path: str | Path, out_dir: str | Path | None = None,
                  width: int = 900) -> Path | None:
    """Render the first page of a PDF to PNG so it can be shown in the UI.

    Images are returned unchanged. Returns None when nothing can be rendered,
    which the caller shows as a placeholder rather than failing.
    """
    p = Path(path)
    if not p.exists():
        return None
    if p.suffix.lower() in IMAGE_SUFFIXES:
        return p
    if p.suffix.lower() not in PDF_SUFFIXES:
        return None
    out_dir = Path(out_dir or (config.folder("Logs") / "_previews"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = hashlib.md5(str(p).encode()).hexdigest()[:16]
    out = out_dir / f"{stamp}.png"
    try:
        mtime = p.stat().st_mtime
        if out.exists() and out.stat().st_mtime >= mtime:
            return out                      # cached and still current
    except OSError:
        pass
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(p))
        page = pdf[0]
        scale = max(1.0, width / max(1.0, page.get_width()))
        page.render(scale=min(4.0, scale)).to_pil().save(out)
        pdf.close()
        return out
    except Exception:
        return None


def page_count(path: str | Path) -> int:
    p = Path(path)
    if p.suffix.lower() not in PDF_SUFFIXES or not p.exists():
        return 1
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(p))
        n = len(pdf)
        pdf.close()
        return n
    except Exception:
        return 1


def export_rows(db: Database, f: dict | None = None
                ) -> tuple[list[str], list[list[Any]]]:
    """The index as a table, for Excel / PDF export."""
    rows = search(db, **(f or {}))
    cols = ["File", "Type", "Sub-folder", "Document No", "Doc Type", "Linked",
            "Project", "PR / MR", "Size (KB)", "Modified", "Full Path"]
    data = [[r["name"], r["kind"], r["subfolder"] or "(root)", r["doc_no"] or "-",
             r["doc_type"] or "-", "Yes" if r["matched"] else "No",
             r["project"] or "-", r["pr_no"] or "-",
             round((r["size"] or 0) / 1024.0, 1), r["modified"], r["path"]]
            for r in rows]
    return cols, data
