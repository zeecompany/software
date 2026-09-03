"""DOCUMENT LIBRARY — browse and preview synced folders of Delivery Note scans.

Three tabs:
    📂 Browse    list + thumbnail grid + live preview of every indexed file
    🔗 Folders   add / remove sync folders, scan, and see what is offline
    📊 Overview  KPI tiles and charts over the whole library

The library only ever *reads* your folders. Files are never moved, renamed or
deleted by this page — "Remove from index" forgets the entry and leaves the file
exactly where the site team put it.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QScrollArea, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from ..core import documents as D
from ..core import library as L
from ..core.database import Database
from . import widgets as W
from .common import ShareBar, date_edit, iso


class PreviewPane(QWidget):
    """Shows the selected document: image directly, PDF rendered to an image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 0, 0, 0)
        v.setSpacing(5)
        self.view = QLabel("Select a document to preview")
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(380, 380)
        self.view.setStyleSheet(
            "background:#f2f5f8; border:1px solid #d8e1ea; border-radius:6px;")
        v.addWidget(self.view, 1)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        v.addWidget(self.caption)
        row = QHBoxLayout()
        row.addWidget(W.button("🔍  Open Full Size", "Primary", self.open_file))
        row.addWidget(W.button("🖨  Print", slot=self.print_file))
        row.addWidget(W.button("📂  Show in Folder", slot=self.locate))
        row.addStretch(1)
        v.addLayout(row)

    def show_file(self, rec: dict | None):
        if not rec:
            self.path = None
            self.view.setPixmap(QPixmap())
            self.view.setText("Select a document to preview")
            self.caption.clear()
            return
        p = Path(rec["path"])
        self.path = p
        link = ("linked to " + rec["doc_no"]) if rec.get("matched") else (
            f"detected {rec['doc_no']} — no matching record" if rec.get("doc_no")
            else "no document number in the file name")
        self.caption.setText(
            f"<b>{rec['name']}</b><br>{rec.get('subfolder') or '(root)'} · "
            f"{rec['kind']} · {round((rec.get('size') or 0) / 1024.0, 1)} KB · "
            f"{rec.get('modified', '')}<br>{link}<br><code>{p}</code>")
        if not p.exists():
            self.view.setPixmap(QPixmap())
            self.view.setText(f"This file is no longer on disk:\n{p}")
            return
        img = L.preview_image(p)
        if img is None:
            self.view.setPixmap(QPixmap())
            self.view.setText(f"{rec['kind']} file — no preview available.\n\n"
                              "Use Open Full Size to view it.")
            return
        pm = QPixmap(str(img))
        if pm.isNull():
            self.view.setPixmap(QPixmap())
            self.view.setText(f"Cannot display {p.name}")
            return
        self.view.setPixmap(pm.scaled(max(100, self.view.width() - 10),
                                      max(100, self.view.height() - 10),
                                      Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def open_file(self):
        if self.path and self.path.exists():
            D.open_path(self.path)
        else:
            W.error_box(self, "Select a document that still exists on disk.")

    def print_file(self):
        if not (self.path and self.path.exists()):
            W.error_box(self, "Select a document first.")
            return
        try:
            D.print_file(None, self.path)
        except Exception:
            D.open_path(self.path)

    def locate(self):
        if self.path and self.path.exists():
            D.open_file_location(self.path)


class LinkDialog(QDialog):
    """Correct the document number / project detected from a file name."""

    def __init__(self, db: Database, rec: dict, parent=None):
        super().__init__(parent)
        self.db = db
        self.rec = rec
        self.setWindowTitle(f"Link — {rec['name']}")
        self.setModal(True)
        self.resize(560, 300)
        v = QVBoxLayout(self)
        head = QLabel(f"<b>{rec['name']}</b><br><code>{rec['path']}</code>")
        head.setWordWrap(True)
        v.addWidget(head)
        f = QFormLayout()
        self.doc_no = QLineEdit(rec.get("doc_no", ""))
        self.doc_no.setPlaceholderText("e.g. DN-2026-00821")
        self.project = QLineEdit(rec.get("project", ""))
        self.tags = QLineEdit(rec.get("tags", ""))
        self.tags.setPlaceholderText("comma separated, e.g. signed, gate pass")
        self.notes = QLineEdit(rec.get("notes", ""))
        for lbl, wd in (("Document No", self.doc_no), ("Project", self.project),
                        ("Tags", self.tags), ("Notes", self.notes)):
            f.addRow(lbl, wd)
        v.addLayout(f)
        hint = QLabel("Enter the document number exactly as AURCO issued it. If a "
                      "matching record exists the file is linked automatically.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        v.addWidget(hint)
        v.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _save(self):
        L.set_meta(self.db, self.rec["id"], self.doc_no.text().strip(),
                   self.tags.text().strip(), self.notes.text().strip(),
                   self.project.text().strip())
        self.accept()


# ------------------------------------------------------------------ browse
class BrowseTab(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.rows: list[dict] = []
        self.last_file: Path | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self.search = W.SearchBox("Search file name, folder, DN number, project, "
                                  "PR, tags...")
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 3)
        self.f_folder = W.combo(["All Folders"])
        self.f_sub = W.combo(["All Sub-folders"])
        self.f_kind = W.combo(["All Types"] + L.KINDS)
        self.f_project = W.combo(["All Projects"])
        for c in (self.f_folder, self.f_sub, self.f_kind, self.f_project):
            c.currentTextChanged.connect(self.reload)
            bar.addWidget(c)
        v.addLayout(bar)

        bar2 = QHBoxLayout()
        self.chk_unmatched = QCheckBox("Only unlinked")
        self.chk_matched = QCheckBox("Only linked")
        self.chk_missing = QCheckBox("Show missing files")
        for c in (self.chk_unmatched, self.chk_matched, self.chk_missing):
            c.toggled.connect(self.reload)
            bar2.addWidget(c)
        self.chk_dates = QCheckBox("Filter by date")
        self.chk_dates.toggled.connect(self.reload)
        bar2.addWidget(self.chk_dates)
        from PySide6.QtCore import QDate
        self.d_from = date_edit()
        self.d_from.setDate(QDate.currentDate().addYears(-5))
        self.d_to = date_edit()
        self.d_to.setDate(QDate.currentDate().addYears(1))
        for wd in (self.d_from, self.d_to):
            wd.dateChanged.connect(self.reload)
            bar2.addWidget(wd)
        self.chk_thumbs = QCheckBox("Thumbnails")
        self.chk_thumbs.setChecked(True)
        self.chk_thumbs.toggled.connect(self._mode)
        bar2.addWidget(self.chk_thumbs)
        bar2.addStretch(1)
        v.addLayout(bar2)

        btns = QHBoxLayout()
        btns.addWidget(W.button("🔄  Sync Now", "Primary", self.sync_now,
                                tip="Re-scan every folder for new or changed files"))
        btns.addWidget(W.button("🔍  Open", slot=self._open))
        btns.addWidget(W.button("🖨  Print", slot=self._print))
        btns.addWidget(W.button("📂  Show in Folder", slot=self._locate))
        btns.addWidget(W.button("🔗  Link to Document", slot=self._link))
        btns.addWidget(W.button("📋  Copy Path", slot=self._copy))
        btns.addWidget(W.button("📊  Export List", slot=lambda: self._export("xlsx")))
        btns.addWidget(W.button("📄  PDF List", slot=lambda: self._export("pdf")))
        btns.addWidget(W.button("🚫  Remove from Index", slot=self._forget,
                                tip="Forget the entry — the file stays on disk"))
        btns.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{W.MUTED};")
        btns.addWidget(self.count)
        v.addLayout(btns)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)
        self.table = W.DataTable()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._show_current)
        self.table.doubleClicked.connect(self._open)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lv.addWidget(W.FilterBar(self.table))
        lv.addWidget(self.table, 1)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setIconSize(QSize(150, 118))
        self.gallery.setResizeMode(QListWidget.Adjust)
        self.gallery.setSpacing(8)
        self.gallery.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.gallery.currentRowChanged.connect(self._show_gallery)
        self.gallery.itemDoubleClicked.connect(
            lambda it: D.open_path(it.data(Qt.UserRole)))
        self.gallery.setContextMenuPolicy(Qt.CustomContextMenu)
        self.gallery.customContextMenuRequested.connect(self._menu)
        lv.addWidget(self.gallery, 1)
        split.addWidget(left)
        self.preview = PreviewPane()
        split.addWidget(self.preview)
        split.setSizes([980, 460])
        v.addWidget(split, 1)
        v.addWidget(ShareBar(db, lambda: self.last_file, self))
        self._mode()
        self.reload_filters()
        self.reload()

    # ------------------------------------------------------------- helpers
    def _mode(self):
        on = self.chk_thumbs.isChecked()
        self.gallery.setVisible(on)
        self.table.setVisible(True)

    def reload_filters(self):
        cur = self.f_folder.currentText()
        self.f_folder.blockSignals(True)
        self.f_folder.clear()
        self.f_folder.addItem("All Folders")
        self._folder_ids = [None]
        for f in L.folders(self.db):
            self.f_folder.addItem(f["label"] or Path(f["path"]).name)
            self._folder_ids.append(f["id"])
        i = self.f_folder.findText(cur)
        self.f_folder.setCurrentIndex(max(0, i))
        self.f_folder.blockSignals(False)
        for cb, col, first in ((self.f_sub, "subfolder", "All Sub-folders"),
                               (self.f_project, "project", "All Projects")):
            c2 = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([first] + L.distinct(self.db, col))
            j = cb.findText(c2)
            cb.setCurrentIndex(max(0, j))
            cb.blockSignals(False)

    def filters(self) -> dict:
        idx = self.f_folder.currentIndex()
        fid = (self._folder_ids[idx]
               if 0 <= idx < len(getattr(self, "_folder_ids", [])) else None)
        return {
            "text": self.search.text(),
            "folder_id": fid,
            "kind": "" if self.f_kind.currentIndex() <= 0 else self.f_kind.currentText(),
            "subfolder": ("" if self.f_sub.currentIndex() <= 0
                          else self.f_sub.currentText()),
            "project": ("" if self.f_project.currentIndex() <= 0
                        else self.f_project.currentText()),
            "only_unmatched": self.chk_unmatched.isChecked(),
            "only_matched": self.chk_matched.isChecked(),
            "only_missing": self.chk_missing.isChecked(),
            "date_from": iso(self.d_from) if self.chk_dates.isChecked() else "",
            "date_to": iso(self.d_to) if self.chk_dates.isChecked() else "",
        }

    def reload(self):
        self.rows = L.search(self.db, **self.filters())
        data = [[r["id"], r["name"], r["kind"], r["subfolder"] or "(root)",
                 r["doc_no"] or "-", "✔ linked" if r["matched"] else
                 ("⚠ no record" if r["doc_no"] else "— none —"),
                 r["project"] or "-", r["pr_no"] or "-",
                 round((r["size"] or 0) / 1024.0, 1), r["modified"],
                 r["tags"] or "", r["path"]] for r in self.rows]
        self.table.fill(["ID", "File", "Type", "Sub-folder", "Document No", "Linked",
                         "Project", "PR / MR", "Size (KB)", "Modified", "Tags",
                         "Full Path"], data)
        self.table.setColumnHidden(0, True)
        self._fill_gallery()
        n_link = sum(1 for r in self.rows if r["matched"])
        mb = sum((r["size"] or 0) for r in self.rows) / 1048576.0
        self.count.setText(f"{len(self.rows)} file(s) · {n_link} linked · {mb:,.1f} MB")
        if self.rows and self.table.rowCount():
            self.table.selectRow(0)

    def _fill_gallery(self):
        self.gallery.clear()
        if not self.chk_thumbs.isChecked():
            return
        for r in self.rows[:400]:
            label = r["name"][:26] + ("\n" + r["doc_no"] if r["doc_no"] else "")
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, r["path"])
            it.setToolTip(f"{r['name']}\n{r['subfolder'] or '(root)'}\n{r['path']}")
            img = L.preview_image(r["path"]) if Path(r["path"]).exists() else None
            if img:
                pm = QPixmap(str(img))
                if not pm.isNull():
                    it.setIcon(pm.scaled(150, 118, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation))
            self.gallery.addItem(it)

    def _sel_ids(self) -> list[int]:
        return sorted({int(self.table.item(i.row(), 0).text())
                       for i in self.table.selectedIndexes()
                       if self.table.item(i.row(), 0)})

    def _one(self) -> dict | None:
        ids = self._sel_ids()
        if not ids:
            W.error_box(self, "Select a document in the list first.")
            return None
        return next((r for r in self.rows if r["id"] == ids[0]), None)

    def _show_current(self):
        ids = self._sel_ids()
        rec = next((r for r in self.rows if r["id"] == ids[0]), None) if ids else None
        self.preview.show_file(rec)
        if rec and Path(rec["path"]).exists():
            self.last_file = Path(rec["path"])

    def _show_gallery(self, row: int):
        if 0 <= row < len(self.rows):
            self.preview.show_file(self.rows[row])
            for r_ in range(self.table.rowCount()):
                if (self.table.item(r_, 0)
                        and int(self.table.item(r_, 0).text()) == self.rows[row]["id"]):
                    self.table.blockSignals(True)
                    self.table.selectRow(r_)
                    self.table.blockSignals(False)
                    break

    # ------------------------------------------------------------ actions
    def sync_now(self):
        res = L.sync_all(self.db)
        L.relink(self.db)
        self.reload_filters()
        self.reload()
        if not res["folders"]:
            W.error_box(self, "No sync folder has been added yet.\n\n"
                              "Open the Folders tab and add the folder that holds "
                              "your scanned delivery notes.")
            return
        msg = (f"{res['scanned']} file(s) scanned in {res['folders']} folder(s).\n"
               f"{res['added']} new, {res['updated']} updated, "
               f"{res['missing']} missing.")
        if res["errors"]:
            msg += "\n\nProblems:\n" + "\n".join(res["errors"][:5])
        W.info_box(self, msg, "Sync complete")

    def _open(self):
        rec = self._one()
        if rec:
            if not Path(rec["path"]).exists():
                W.error_box(self, f"That file is no longer on disk:\n{rec['path']}")
                return
            D.open_path(rec["path"])

    def _print(self):
        rec = self._one()
        if rec and Path(rec["path"]).exists():
            try:
                D.print_file(self.db, rec["path"])
                W.toast(self, f"Sent to printer: {rec['name']}")
            except Exception as exc:  # noqa: BLE001
                W.error_box(self, f"Could not print.\n\n{exc}")

    def _locate(self):
        rec = self._one()
        if rec:
            D.open_file_location(rec["path"])

    def _link(self):
        rec = self._one()
        if rec and LinkDialog(self.db, rec, self).exec() == QDialog.Accepted:
            self.reload_filters()
            self.reload()
            W.toast(self, "Document link updated.")

    def _copy(self):
        from PySide6.QtWidgets import QApplication
        ids = self._sel_ids()
        paths = [r["path"] for r in self.rows if r["id"] in ids]
        if not paths:
            W.error_box(self, "Select one or more documents first.")
            return
        QApplication.clipboard().setText("\n".join(paths))
        W.toast(self, f"{len(paths)} path(s) copied.")

    def _forget(self):
        ids = self._sel_ids()
        if not ids:
            W.error_box(self, "Select one or more documents first.")
            return
        if not W.confirm(self, f"Remove {len(ids)} entr(y/ies) from the library "
                               "index?\n\nThe files themselves are NOT deleted — "
                               "they stay exactly where they are on disk."):
            return
        n = L.forget(self.db, ids)
        self.reload()
        W.toast(self, f"{n} entr(y/ies) removed from the index. Files kept.")

    def _export(self, kind: str):
        cols, data = L.export_rows(self.db, self.filters())
        if not data:
            W.error_box(self, "Nothing to export.")
            return
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = Path(D.config.folder("Exports"))
        title = "Document Library Index"
        if kind == "xlsx":
            f = D.export_excel(self.db, title, cols, data,
                               folder / f"Document_Library_{stamp}.xlsx")
        else:
            f = D.report_pdf(self.db, title, cols, data,
                             folder / f"Document_Library_{stamp}.pdf",
                             subtitle="Synced folders of scanned documents")
        self.last_file = f
        W.toast(self, f"Exported: {f.name}")
        D.open_path(f)

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("🔍  Open", self._open)
        m.addAction("🖨  Print", self._print)
        m.addAction("📂  Show in Folder", self._locate)
        m.addSeparator()
        m.addAction("🔗  Link to Document...", self._link)
        m.addAction("📋  Copy Path", self._copy)
        m.addSeparator()
        m.addAction("🚫  Remove from Index (keeps the file)", self._forget)
        m.addAction("🔄  Sync Now", self.sync_now)
        src = self.sender()
        m.exec(src.viewport().mapToGlobal(pos) if hasattr(src, "viewport")
               else self.mapToGlobal(pos))


# ----------------------------------------------------------------- folders
class FoldersTab(QWidget):
    changed = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(9)

        card = W.Card("Folders to sync")
        note = QLabel(
            "Add the folder on your drive or network share that holds the scanned "
            "delivery notes. Sub-folders are included, so a structure like "
            "<code>2026 / January / DN-2026-00821.pdf</code> is picked up as-is. "
            "PDF, JPG, PNG, TIFF and Office files are indexed.<br><br>"
            "<b>Your files are never moved, renamed or deleted.</b> The library "
            "only records where each file is so you can find and preview it.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{W.MUTED};")
        card.add(note)
        row = QHBoxLayout()
        row.addWidget(W.button("📂  Add Folder...", "Primary", self._add))
        row.addWidget(W.button("🔄  Sync All Now", "Accent", self._sync_all))
        row.addWidget(W.button("🔍  Deep Sync (fingerprint)", slot=self._deep))
        row.addWidget(W.button("🔗  Re-link to Documents", slot=self._relink,
                               tip="Match indexed scans against document records "
                                   "again — useful after importing old documents"))
        row.addStretch(1)
        rw = QWidget()
        rw.setLayout(row)
        card.add(rw)
        v.addWidget(card)

        btns = QHBoxLayout()
        btns.addWidget(W.button("🔄  Sync Selected", slot=self._sync_one))
        btns.addWidget(W.button("📂  Open Folder", slot=self._open))
        btns.addWidget(W.button("⏸  Enable / Disable", slot=self._toggle))
        btns.addWidget(W.button("🗑  Remove Folder", slot=self._remove,
                                tip="Stop syncing — the files stay on disk"))
        btns.addStretch(1)
        v.addLayout(btns)

        self.table = W.DataTable()
        self.table.doubleClicked.connect(self._sync_one)
        v.addWidget(self.table, 1)
        self.info = QLabel()
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.reload()

    def reload(self):
        self.rows = L.folders(self.db)
        self.table.fill(
            ["ID", "Label", "Folder", "Sub-folders", "Files", "Last Scan", "Status"],
            [[f["id"], f["label"], f["path"],
              "Yes" if f["recursive"] else "No", f["files"], f["last_scan"] or "never",
              ("Active" if f["active"] else "Paused") if f["online"] else "OFFLINE"]
             for f in self.rows])
        self.table.setColumnHidden(0, True)
        bad = [f for f in self.rows if not f["online"]]
        st = L.stats(self.db)
        txt = (f"{len(self.rows)} folder(s) · {st['files']:,} file(s) indexed · "
               f"{st['matched']:,} linked to a document "
               f"({st['match_pct']:.0f}%) · {st['bytes'] / 1048576:,.1f} MB")
        if st["missing"]:
            txt += (f"<br><b style='color:{W.RED}'>⚠ {st['missing']} indexed file(s) "
                    "are no longer on disk.</b>")
        if bad:
            txt += ("<br><b style='color:" + W.RED + "'>Offline: </b>"
                    + ", ".join(b["path"] for b in bad[:3]))
        self.info.setText(txt)

    def _sel(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0 or not self.table.item(r, 0):
            W.error_box(self, "Select a folder from the list first.")
            return None
        fid = int(self.table.item(r, 0).text())
        return next((f for f in self.rows if f["id"] == fid), None)

    def _add(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select the folder that holds the scanned delivery notes",
            str(Path.home()))
        if not d:
            return
        label, ok = QInputDialog.getText(self, "Folder name",
                                         "A short name for this folder:",
                                         text=Path(d).name)
        if not ok:
            return
        try:
            fid = L.add_folder(self.db, d, label.strip(), recursive=True)
        except ValueError as exc:
            W.error_box(self, str(exc))
            return
        res = L.sync_folder(self.db, fid)
        L.relink(self.db)
        self.reload()
        self.changed.emit()
        W.info_box(self, f"{res['added']} document(s) indexed from\n{d}\n\n"
                         f"{res['scanned']} file(s) scanned.", "Folder added")

    def _sync_all(self):
        res = L.sync_all(self.db)
        L.relink(self.db)
        self.reload()
        self.changed.emit()
        W.info_box(self, f"{res['scanned']} file(s) scanned.\n"
                         f"{res['added']} new, {res['updated']} updated, "
                         f"{res['missing']} missing.", "Sync complete")

    def _deep(self):
        res = L.sync_all(self.db, deep=True)
        self.reload()
        self.changed.emit()
        W.info_box(self, f"Deep sync finished — {res['scanned']} file(s) "
                         "fingerprinted.", "Deep sync")

    def _relink(self):
        n = L.relink(self.db)
        self.reload()
        self.changed.emit()
        W.toast(self, f"{n} file(s) re-linked to document records.")

    def _sync_one(self):
        f = self._sel()
        if not f:
            return
        res = L.sync_folder(self.db, f["id"])
        self.reload()
        self.changed.emit()
        W.toast(self, f"{res['added']} new · {res['updated']} updated · "
                      f"{res['missing']} missing")

    def _open(self):
        f = self._sel()
        if f and Path(f["path"]).exists():
            D.open_path(f["path"])
        elif f:
            W.error_box(self, f"That folder is offline:\n{f['path']}")

    def _toggle(self):
        f = self._sel()
        if not f:
            return
        L.set_folder_active(self.db, f["id"], not f["active"])
        self.reload()
        self.changed.emit()

    def _remove(self):
        f = self._sel()
        if not f:
            return
        if not W.confirm(self, f"Stop syncing this folder?\n\n{f['path']}\n\n"
                               "Its entries are removed from the library index. "
                               "The files on disk are NOT touched."):
            return
        L.remove_folder(self.db, f["id"])
        self.reload()
        self.changed.emit()
        W.toast(self, "Folder removed from the library.")


# ---------------------------------------------------------------- overview
class OverviewTab(QWidget):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("Page")
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(8, 10, 8, 14)
        v.setSpacing(13)

        self.cards: dict[str, W.StatCard] = {}
        specs = [("files", "Documents Indexed", "🗂", W.NAVY),
                 ("pdf", "PDF Files", "📄", "#14538f"),
                 ("images", "Scanned Images", "🖼", "#7048e8"),
                 ("other", "Other Files", "📎", "#0b7285"),
                 ("folders", "Sync Folders", "📂", W.GREEN),
                 ("subfolders", "Sub-folders", "🗃", "#1098ad"),
                 ("matched", "Linked to a Document", "🔗", W.GREEN),
                 ("unmatched", "Not Linked", "⚠", W.AMBER),
                 ("match_pct", "Link Coverage %", "％", W.GREEN),
                 ("missing", "Missing From Disk", "🚫", W.RED),
                 ("mb", "Total Size (MB)", "💾", "#495057"),
                 ("last", "Last Sync", "🕒", W.NAVY)]
        grid = QGridLayout()
        grid.setSpacing(11)
        for i, (k, lbl, g, c) in enumerate(specs):
            card = W.StatCard(lbl, "0", g, c)
            grid.addWidget(card, i // 4, i % 4)
            self.cards[k] = card
        v.addLayout(grid)

        r1 = QHBoxLayout()
        r1.setSpacing(12)
        c1 = W.Card("Documents by Sub-folder")
        self.ch_sub = W.BarChart(horizontal=True, color="#14538f")
        c1.add(self.ch_sub)
        r1.addWidget(c1, 2)
        c2 = W.Card("By File Type")
        self.ch_kind = W.DonutChart()
        c2.add(self.ch_kind)
        r1.addWidget(c2, 2)
        v.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(12)
        c3 = W.Card("By Document Type")
        self.ch_type = W.BarChart(horizontal=True, color="#7048e8")
        c3.add(self.ch_type)
        r2.addWidget(c3, 2)
        c4 = W.Card("Documents Added by Month")
        self.ch_month = W.LineChart()
        c4.add(self.ch_month)
        r2.addWidget(c4, 3)
        v.addLayout(r2)

        c5 = W.Card("Link coverage")
        self.ch_link = W.DonutChart()
        c5.add(self.ch_link)
        v.addWidget(c5)
        v.addStretch(1)
        self.refresh()

    def refresh(self):
        st = L.stats(self.db)
        for k, card in self.cards.items():
            if k == "match_pct":
                card.set_value(f"{st['match_pct']:.0f}%")
            elif k == "mb":
                card.set_value(f"{st['bytes'] / 1048576:,.1f}")
            elif k == "last":
                card.set_value((st["last_scan"] or "never")[:16] or "never")
            else:
                card.set_value(f"{st.get(k, 0):,}")
        self.ch_sub.set_data(L.by_column(self.db, "subfolder", 10))
        palette = ["#14538f", "#7048e8", "#0b7285", "#e8590c", "#1a9c52"]
        self.ch_kind.set_data([(k, v, palette[i % len(palette)])
                               for i, (k, v) in
                               enumerate(L.by_column(self.db, "kind", 8))])
        self.ch_type.set_data(L.by_column(self.db, "doc_type", 10))
        self.ch_month.set_data(L.monthly(self.db, 12))
        self.ch_link.set_data([("Linked", st["matched"], W.GREEN),
                               ("Not linked", st["unmatched"], W.AMBER)])


# -------------------------------------------------------------------- page
class LibraryPage(QWidget):
    dataChanged = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("Page")
        L.ensure_schema(db)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)

        banner = QLabel(
            "🗂  <b>Document Library</b> — point AURCO at the folders where your "
            "signed delivery notes are scanned and see every PDF and picture in "
            "one place, with a preview. Sub-folders are included and a file named "
            "after its DN number links itself to that record. "
            "<b>Your files are never moved or deleted.</b>")
        banner.setWordWrap(True)
        banner.setStyleSheet("background:#0b7285; color:white; border-radius:7px;"
                             "padding:8px 12px;")
        v.addWidget(banner)

        self.tabs = QTabWidget()
        self.browse = BrowseTab(db)
        self.folders = FoldersTab(db)
        self.overview = OverviewTab(db)
        self.tabs.addTab(self.browse, "📂  Browse Documents")
        self.tabs.addTab(self.folders, "🔗  Sync Folders")
        self.tabs.addTab(self.overview, "📊  Overview")
        v.addWidget(self.tabs, 1)

        self.folders.changed.connect(self.refresh)
        self.tabs.currentChanged.connect(lambda _: self.refresh())

    def refresh(self):
        try:
            self.browse.reload_filters()
            self.browse.reload()
            self.folders.reload()
            self.overview.refresh()
            self.dataChanged.emit()
        except Exception:  # noqa: BLE001
            pass
