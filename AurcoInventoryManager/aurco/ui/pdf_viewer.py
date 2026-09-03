"""Advanced built-in PDF Studio for AURCO documents."""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QColorDialog, QDialog,
                               QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QSlider, QSpinBox, QSplitter, QTabWidget, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget, QCheckBox,
                               QComboBox)

from ..core import documents as D
from ..core import pdf_tools as PT
from ..core.database import get_db
from . import widgets as W

PDF_SUPPORTED = True

_VIEWER = None


class ClickableLabel(QLabel):
    pointPicked = Signal(float, float)

    def mousePressEvent(self, ev):
        if self.pixmap() and self.width() and self.height():
            x = max(0.0, min(100.0, ev.position().x() / max(1.0, self.width()) * 100.0))
            y = max(0.0, min(100.0, ev.position().y() / max(1.0, self.height()) * 100.0))
            self.pointPicked.emit(x, y)
        super().mousePressEvent(ev)


class PdfViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AURCO PDF Studio")
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.source_path: Path | None = None
        self.work_path: Path | None = None
        self.page_index = 0
        self.page_total = 0
        self.zoom_pct = 110
        self.view_rotation = 0
        self.source_mtime = 0.0
        self.restored = False
        self.text_pages: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        hero = QFrame()
        hero.setStyleSheet(
            "QFrame{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #0b3d6b,stop:1 #165d99);"
            "border-radius:16px;} QLabel{color:white;}"
        )
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(16, 14, 16, 14)
        self.caption = QLabel("PDF Studio")
        self.caption.setStyleSheet("font-size:20px;font-weight:700;")
        hv.addWidget(self.caption)
        self.sub = QLabel("View, search, annotate, protect, convert, print and organize PDFs from inside AURCO.")
        self.sub.setWordWrap(True)
        hv.addWidget(self.sub)
        root.addWidget(hero)

        toolbar = QHBoxLayout()
        for text, slot, tip in (
                ("📂 Open PDF", self.pick_file, "Open any PDF file"),
                ("💾 Save", self.save_current, "Save the working copy back to the source file"),
                ("📥 Save Copy", self.save_as, "Save the working copy to a new PDF file"),
                ("⧉ Duplicate", self.duplicate_file, "Create a duplicate PDF file"),
                ("✏ Rename", self.rename_file, "Rename the current PDF"),
                ("↶ Undo", self.undo, "Undo the last PDF change"),
                ("↷ Redo", self.redo, "Redo the last undone change"),
                ("📂 Open Folder", self.open_folder, "Open the file location")):
            toolbar.addWidget(W.button(text, "Primary" if text.startswith("📂 Open") else "", slot, tip))
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        nav = QHBoxLayout()
        self.btn_prev = W.button("◀ Prev", slot=lambda: self.goto_page(self.page_index - 1))
        self.btn_next = W.button("Next ▶", slot=lambda: self.goto_page(self.page_index + 1))
        self.spin_page = QSpinBox()
        self.spin_page.setRange(1, 1)
        self.spin_page.valueChanged.connect(lambda v: self.goto_page(v - 1, sync=False))
        self.lbl_pages = QLabel("/ 0")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search text inside this PDF...")
        self.search.returnPressed.connect(self.run_search)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(40, 260)
        self.zoom_slider.setValue(self.zoom_pct)
        self.zoom_slider.valueChanged.connect(self.set_zoom)
        self.lbl_zoom = QLabel("110%")
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        nav.addWidget(QLabel("Page"))
        nav.addWidget(self.spin_page)
        nav.addWidget(self.lbl_pages)
        nav.addSpacing(12)
        nav.addWidget(W.button("⟲ View Left", slot=lambda: self.rotate_view(-90)))
        nav.addWidget(W.button("⟳ View Right", slot=lambda: self.rotate_view(90)))
        nav.addSpacing(12)
        nav.addWidget(QLabel("Search"))
        nav.addWidget(self.search, 1)
        nav.addWidget(W.button("Find", slot=self.run_search))
        nav.addSpacing(12)
        nav.addWidget(QLabel("Zoom"))
        nav.addWidget(self.zoom_slider)
        nav.addWidget(self.lbl_zoom)
        root.addLayout(nav)

        split = QSplitter()
        root.addWidget(split, 1)

        left = QTabWidget()
        split.addWidget(left)

        self.recent = QListWidget()
        self.recent.itemDoubleClicked.connect(self._open_recent)
        left.addTab(self.recent, "Recent Files")

        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setResizeMode(QListWidget.Adjust)
        self.thumbs.setIconSize(QPixmap(90, 120).size())
        self.thumbs.setMovement(QListWidget.Static)
        self.thumbs.itemClicked.connect(self._open_thumbnail)
        left.addTab(self.thumbs, "Thumbnails")

        self.search_hits = QListWidget()
        self.search_hits.itemClicked.connect(self._open_search_hit)
        left.addTab(self.search_hits, "Search Hits")

        middle = QWidget()
        mv = QVBoxLayout(middle)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(6)
        self.pick_note = QLabel("Tip: drag and drop a PDF here, or open one from Documents / Reports / Library.")
        self.pick_note.setWordWrap(True)
        self.pick_note.setStyleSheet("color:#5f6368")
        mv.addWidget(self.pick_note)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.page_view = ClickableLabel()
        self.page_view.setAlignment(Qt.AlignCenter)
        self.page_view.setMinimumSize(420, 520)
        self.page_view.setStyleSheet("background:#e9ecef;border:1px solid #ced4da;border-radius:12px;")
        self.page_view.setText("Open a PDF to start.")
        self.page_view.pointPicked.connect(self.capture_point)
        self.scroll.setWidget(self.page_view)
        mv.addWidget(self.scroll, 1)
        self.page_meta = QTextBrowser()
        self.page_meta.setMaximumHeight(110)
        self.page_meta.setOpenExternalLinks(True)
        mv.addWidget(self.page_meta)
        split.addWidget(middle)

        right = QTabWidget()
        split.addWidget(right)
        split.setSizes([250, 760, 380])

        # annotate ------------------------------------------------------------
        annot = QWidget()
        av = QVBoxLayout(annot)
        g = QGroupBox("Annotation / signature")
        f = QFormLayout(g)
        self.a_pages = QLineEdit("1")
        self.a_pages.setPlaceholderText("Examples: 1 or 1,3-5")
        self.a_kind = QComboBox()
        self.a_kind.addItems(["Text", "Note", "Stamp", "Highlight", "Underline", "Line", "Box", "Signature"])
        self.a_text = QPlainTextEdit()
        self.a_text.setPlaceholderText("Type the text, note, stamp label or signature caption...")
        self.a_text.setMaximumHeight(90)
        self.a_x = QSpinBox(); self.a_x.setRange(0, 100); self.a_x.setValue(8)
        self.a_y = QSpinBox(); self.a_y.setRange(0, 100); self.a_y.setValue(8)
        self.a_w = QSpinBox(); self.a_w.setRange(1, 100); self.a_w.setValue(30)
        self.a_h = QSpinBox(); self.a_h.setRange(1, 100); self.a_h.setValue(8)
        xy = QHBoxLayout(); xy.addWidget(self.a_x); xy.addWidget(self.a_y); xy.addWidget(self.a_w); xy.addWidget(self.a_h)
        xyw = QWidget(); xyw.setLayout(xy)
        self.a_color = QLineEdit("#ffbf00")
        cbar = QHBoxLayout(); cbar.addWidget(self.a_color, 1); cbar.addWidget(W.button("Pick", slot=self.pick_color))
        cw = QWidget(); cw.setLayout(cbar)
        self.a_image = QLineEdit()
        ibar = QHBoxLayout(); ibar.addWidget(self.a_image, 1)
        ibar.addWidget(W.button("Browse", slot=self.pick_signature_image))
        ibar.addWidget(W.button("Paste", slot=self.paste_signature_image))
        iw = QWidget(); iw.setLayout(ibar)
        f.addRow("Pages", self.a_pages)
        f.addRow("Tool", self.a_kind)
        f.addRow("Text / caption", self.a_text)
        f.addRow("X % / Y % / W % / H %", xyw)
        f.addRow("Colour", cw)
        f.addRow("Signature image", iw)
        av.addWidget(g)
        ag = QHBoxLayout()
        ag.addWidget(W.button("Use current page", slot=lambda: self.a_pages.setText(str(self.page_index + 1))))
        ag.addWidget(W.button("Apply to PDF", "Accent", self.apply_annotation))
        ag.addWidget(W.button("Save Signed Copy", slot=self.save_signed_copy))
        av.addLayout(ag)
        hint = QLabel("Tip: click anywhere on the PDF preview to capture X/Y placement in percentage coordinates.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#5f6368")
        av.addWidget(hint)
        av.addStretch(1)
        right.addTab(annot, "Annotate")

        # organize ------------------------------------------------------------
        org = QWidget()
        ov = QVBoxLayout(org)
        self.page_table = QTableWidget(0, 3)
        self.page_table.setHorizontalHeaderLabels(["Page", "Size", "Actions"])
        self.page_table.verticalHeader().setVisible(False)
        self.page_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.page_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        ov.addWidget(self.page_table, 1)
        row1 = QHBoxLayout()
        row1.addWidget(W.button("▲ Move Up", slot=lambda: self.move_selected_pages(-1)))
        row1.addWidget(W.button("▼ Move Down", slot=lambda: self.move_selected_pages(1)))
        row1.addWidget(W.button("💾 Apply Order", "Accent", self.apply_page_order))
        ov.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(W.button("⧉ Duplicate Pages", slot=self.duplicate_selected_pages))
        row2.addWidget(W.button("🗑 Delete Pages", slot=self.delete_selected_pages))
        row2.addWidget(W.button("📤 Extract Pages", slot=self.extract_selected_pages))
        ov.addLayout(row2)
        row3 = QHBoxLayout()
        row3.addWidget(W.button("⟲ Rotate Left", slot=lambda: self.rotate_selected_pages(-90)))
        row3.addWidget(W.button("⟳ Rotate Right", slot=lambda: self.rotate_selected_pages(90)))
        row3.addWidget(W.button("➕ Merge Another PDF", slot=self.merge_pdf))
        row3.addWidget(W.button("✂ Split by Range", slot=self.split_pdf))
        ov.addLayout(row3)
        right.addTab(org, "Organize")

        # convert -------------------------------------------------------------
        conv = QWidget()
        cv = QVBoxLayout(conv)
        cv.addWidget(QLabel("Export / convert the current working PDF into other useful formats."))
        for text, slot in (("Export to PNG pages", lambda: self.export_images("png")),
                           ("Export to JPG pages", lambda: self.export_images("jpg")),
                           ("Convert to Word (.docx)", self.export_docx),
                           ("Convert to Excel (.xlsx)", self.export_xlsx),
                           ("Export text (.txt)", self.export_txt),
                           ("Export HTML", self.export_html)):
            cv.addWidget(W.button(text, slot=slot))
        cv.addStretch(1)
        right.addTab(conv, "Convert")

        # print ---------------------------------------------------------------
        prn = QWidget()
        pv = QVBoxLayout(prn)
        pg = QGroupBox("Print options")
        pf = QFormLayout(pg)
        self.p_range = QLineEdit("")
        self.p_range.setPlaceholderText("Blank = all pages, or e.g. 1-3,5")
        self.p_orientation = QComboBox(); self.p_orientation.addItems(["Original", "Portrait", "Landscape"])
        self.p_copies = QSpinBox(); self.p_copies.setRange(1, 99); self.p_copies.setValue(1)
        pf.addRow("Page range", self.p_range)
        pf.addRow("Orientation", self.p_orientation)
        pf.addRow("Copies", self.p_copies)
        pv.addWidget(pg)
        prow = QHBoxLayout()
        prow.addWidget(W.button("Preview Print Job", slot=self.preview_print_job))
        prow.addWidget(W.button("Print", "Accent", self.print_with_options))
        pv.addLayout(prow)
        pv.addStretch(1)
        right.addTab(prn, "Print")

        # security ------------------------------------------------------------
        sec = QWidget()
        sv = QVBoxLayout(sec)
        sg = QGroupBox("Password protection / encryption")
        sf = QFormLayout(sg)
        self.sec_user = QLineEdit(); self.sec_user.setEchoMode(QLineEdit.Password)
        self.sec_owner = QLineEdit(); self.sec_owner.setEchoMode(QLineEdit.Password)
        self.sec_print = QCheckBox("Allow printing"); self.sec_print.setChecked(True)
        self.sec_copy = QCheckBox("Allow copying text / graphics"); self.sec_copy.setChecked(True)
        self.sec_modify = QCheckBox("Allow editing / assembly"); self.sec_modify.setChecked(False)
        sf.addRow("Open password", self.sec_user)
        sf.addRow("Owner password", self.sec_owner)
        sf.addRow(self.sec_print)
        sf.addRow(self.sec_copy)
        sf.addRow(self.sec_modify)
        sv.addWidget(sg)
        sv.addWidget(W.button("Save Protected Copy", "Accent", self.protect_copy))
        sv.addStretch(1)
        right.addTab(sec, "Security")

        # share ---------------------------------------------------------------
        shr = QWidget()
        shv = QVBoxLayout(shr)
        share = QGroupBox("Share current PDF")
        sfm = QFormLayout(share)
        self.mail_to = QLineEdit(); self.mail_to.setPlaceholderText("name@example.com")
        self.wa_to = QLineEdit(); self.wa_to.setPlaceholderText("9665XXXXXXXX")
        sfm.addRow("Email to", self.mail_to)
        sfm.addRow("WhatsApp number", self.wa_to)
        shv.addWidget(share)
        srow1 = QHBoxLayout()
        srow1.addWidget(W.button("✉ Email PDF", slot=self.share_email))
        srow1.addWidget(W.button("🟢 WhatsApp PDF", slot=self.share_whatsapp))
        srow1.addWidget(W.button("🔗 Copy file link", slot=self.copy_file_link))
        shv.addLayout(srow1)
        srow2 = QHBoxLayout()
        srow2.addWidget(W.button("📋 Copy path", slot=self.copy_path))
        srow2.addWidget(W.button("📂 Open folder", slot=self.open_folder))
        shv.addLayout(srow2)
        shv.addStretch(1)
        right.addTab(shr, "Share")

        self.status = QLabel("Ready.")
        self.status.setStyleSheet("color:#5f6368;padding:4px")
        root.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.setInterval(2500)
        self.timer.timeout.connect(self._check_source_update)
        self.timer.start()
        self.reload_recent()
        self._update_actions()

    # ----------------------------------------------------------------- events
    def dragEnterEvent(self, ev: QDragEnterEvent):
        if ev.mimeData().hasUrls():
            for url in ev.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
                    ev.acceptProposedAction()
                    return
        ev.ignore()

    def dropEvent(self, ev: QDropEvent):
        for url in ev.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
                self.open_file(url.toLocalFile())
                ev.acceptProposedAction()
                return
        ev.ignore()

    # ---------------------------------------------------------------- helpers
    def _db(self):
        try:
            return get_db()
        except Exception:
            return None

    def _set_status(self, text: str):
        self.status.setText(text)

    def _current_pdf(self) -> Path | None:
        return self.work_path if self.work_path and self.work_path.exists() else None

    def _share_pdf(self) -> Path | None:
        cur = self._current_pdf()
        if not cur or not self.source_path:
            return None
        if self.is_dirty():
            out = PT.default_export_path(self.source_path, ".shared.pdf")
            shutil.copy2(cur, out)
            return out
        return self.source_path

    def is_dirty(self) -> bool:
        if not self.source_path:
            return False
        sp = PT.session_paths(self.source_path)
        if sp["meta"].exists():
            try:
                import json
                meta = json.loads(sp["meta"].read_text(encoding="utf-8"))
                return bool(meta.get("dirty"))
            except Exception:
                return False
        return False

    def _ensure_open(self) -> bool:
        if not self.source_path or not self.work_path or not self.work_path.exists():
            W.error_box(self, "Open a PDF first.")
            return False
        return True

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.page_table.selectedIndexes()})

    def _selected_pages(self) -> list[int]:
        rows = self._selected_rows()
        if not rows:
            rows = [self.page_index]
        return [int(self.page_table.item(r, 0).data(Qt.UserRole)) for r in rows]

    def _picked_range(self) -> list[int]:
        if not self._ensure_open():
            return []
        return PT.parse_page_range(self.a_pages.text(), self.page_total)

    def _apply_workspace(self, maker, msg: str):
        if not self._ensure_open() or not self.source_path:
            return
        PT.replace_workspace(self.source_path, maker)
        self.reload_document(keep_page=True)
        self._set_status(msg + " Auto-saved to the working copy.")

    def _orientation_rotate(self, page_list: list[int]) -> dict[int, int]:
        if not self._ensure_open():
            return {}
        mode = self.p_orientation.currentText()
        if mode == "Original":
            return {}
        sizes = PT.page_sizes(self._current_pdf())
        out = {}
        for i in page_list:
            w, h = sizes[i]
            if mode == "Landscape" and h > w:
                out[i] = 90
            elif mode == "Portrait" and w > h:
                out[i] = 90
        return out

    def _make_subset(self) -> Path | None:
        if not self._ensure_open() or not self.source_path:
            return None
        pdf = self._current_pdf()
        idx = PT.parse_page_range(self.p_range.text(), self.page_total)
        out = PT.default_export_path(self.source_path, ".print-preview.pdf")
        rot = self._orientation_rotate(idx)
        PT._write_pages(PT._reader(pdf), idx, out, rot)
        return out

    # ---------------------------------------------------------------- opening
    def pick_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open PDF", str(Path.home()), "PDF Files (*.pdf)")
        if p:
            self.open_file(p)

    def open_file(self, path: str | Path, title: str = "") -> bool:
        p = Path(path)
        if not p.exists() or p.suffix.lower() != ".pdf":
            self._set_status("PDF file not found.")
            return False
        self.source_path = p.resolve()
        self.work_path, self.restored = PT.load_workspace(self.source_path)
        self.source_mtime = self.source_path.stat().st_mtime
        self.caption.setText(title or self.source_path.name)
        self.sub.setText(str(self.source_path))
        self.page_index = 0
        self.view_rotation = 0
        self.zoom_slider.setValue(110)
        self.reload_recent()
        self.reload_document(keep_page=False)
        self.show()
        self.raise_()
        self.activateWindow()
        self._set_status("Recovered the last auto-saved working copy." if self.restored
                         else "PDF opened in AURCO PDF Studio.")
        return True

    def reload_recent(self):
        self.recent.clear()
        for p in PT.recent_files():
            item = QListWidgetItem(Path(p).name)
            item.setToolTip(p)
            item.setData(Qt.UserRole, p)
            self.recent.addItem(item)

    def reload_document(self, keep_page: bool = True):
        if not self._ensure_open():
            return
        old = self.page_index
        self.page_total = PT.page_count(self.work_path)
        self.spin_page.blockSignals(True)
        self.spin_page.setRange(1, max(1, self.page_total))
        self.lbl_pages.setText(f"/ {self.page_total}")
        self.page_index = min(old if keep_page else 0, max(0, self.page_total - 1))
        self.spin_page.setValue(self.page_index + 1)
        self.spin_page.blockSignals(False)
        self.text_pages = PT.extract_text(self.work_path)
        self._load_thumbnails()
        self._load_page_table()
        self.render_current_page()
        self._update_actions()

    def render_current_page(self):
        if not self._ensure_open():
            return
        img = PT.render_page(self.work_path, self.page_index, scale=max(0.4, self.zoom_pct / 100.0 * 1.25),
                             rotation=self.view_rotation)
        pm = QPixmap.fromImage(ImageQt(img))
        self.page_view.setPixmap(pm)
        self.page_view.resize(pm.size())
        txt = self.text_pages[self.page_index] if self.page_total and self.page_index < len(self.text_pages) else ""
        preview = " ".join((txt or "(no searchable text found on this page)").split())[:700]
        self.page_meta.setHtml(
            f"<b>Page {self.page_index + 1}</b> &nbsp; · &nbsp; Zoom {self.zoom_pct}% &nbsp; · &nbsp; "
            f"View rotation {self.view_rotation % 360}°<br><br>{preview}"
        )
        self._highlight_page_selection()

    def goto_page(self, page_index: int, sync: bool = True):
        if not self._ensure_open() or self.page_total < 1:
            return
        self.page_index = max(0, min(self.page_total - 1, int(page_index)))
        if sync:
            self.spin_page.blockSignals(True)
            self.spin_page.setValue(self.page_index + 1)
            self.spin_page.blockSignals(False)
        self.render_current_page()
        self._update_actions()

    def set_zoom(self, value: int):
        self.zoom_pct = int(value)
        self.lbl_zoom.setText(f"{self.zoom_pct}%")
        if self._current_pdf():
            self.render_current_page()

    def rotate_view(self, angle: int):
        self.view_rotation = (self.view_rotation + int(angle)) % 360
        if self._current_pdf():
            self.render_current_page()

    def _check_source_update(self):
        if not self.source_path or not self.source_path.exists():
            return
        cur = self.source_path.stat().st_mtime
        if cur != self.source_mtime:
            self.source_mtime = cur
            if not self.is_dirty():
                self.work_path, _ = PT.load_workspace(self.source_path)
                self.reload_document(keep_page=True)
                self._set_status("Source PDF refreshed from shared storage.")
            else:
                self._set_status("The source PDF changed on disk, but your local working copy has unsaved edits.")

    # ------------------------------------------------------------- side panels
    def _open_recent(self, item: QListWidgetItem):
        p = item.data(Qt.UserRole)
        if p:
            self.open_file(p)

    def _load_thumbnails(self):
        self.thumbs.clear()
        if not self._current_pdf():
            return
        limit = min(self.page_total, 60)
        for i in range(limit):
            try:
                thumb = PT.render_page(self.work_path, i, scale=0.22)
                pm = QPixmap.fromImage(ImageQt(thumb))
                icon = QIcon(pm)
            except Exception:
                icon = QIcon()
            item = QListWidgetItem(icon, f"{i + 1}")
            item.setData(Qt.UserRole, i)
            self.thumbs.addItem(item)
        if self.page_total > limit:
            item = QListWidgetItem(f"Only the first {limit} thumbnails are shown for speed.")
            item.setFlags(Qt.NoItemFlags)
            self.thumbs.addItem(item)

    def _open_thumbnail(self, item: QListWidgetItem):
        idx = item.data(Qt.UserRole)
        if idx is not None:
            self.goto_page(int(idx))

    def run_search(self):
        if not self._ensure_open():
            return
        self.search_hits.clear()
        hits = PT.search_text(self._current_pdf(), self.search.text().strip())
        for h in hits:
            item = QListWidgetItem(f"Page {h['page']} — {h['snippet']}")
            item.setData(Qt.UserRole, h["page"] - 1)
            self.search_hits.addItem(item)
        if hits:
            self.goto_page(hits[0]["page"] - 1)
            self._set_status(f"Found {len(hits)} text match(es).")
        else:
            self._set_status("No text matches were found in this PDF.")

    def _open_search_hit(self, item: QListWidgetItem):
        idx = item.data(Qt.UserRole)
        if idx is not None:
            self.goto_page(int(idx))

    def capture_point(self, x: float, y: float):
        self.a_x.setValue(round(x))
        self.a_y.setValue(round(y))
        self._set_status(f"Placement captured at X={round(x)}%, Y={round(y)}% on page {self.page_index + 1}.")

    def _load_page_table(self):
        self.page_table.setRowCount(0)
        if not self._current_pdf():
            return
        for r, meta in enumerate(PT.page_summary(self._current_pdf())):
            self.page_table.insertRow(r)
            it = QTableWidgetItem(str(meta["page"]))
            it.setData(Qt.UserRole, meta["page"] - 1)
            self.page_table.setItem(r, 0, it)
            self.page_table.setItem(r, 1, QTableWidgetItem(f"{meta['width']} × {meta['height']} pt"))
            self.page_table.setItem(r, 2, QTableWidgetItem("Organize / rotate / extract"))
        self.page_table.resizeColumnsToContents()

    def _highlight_page_selection(self):
        self.page_table.clearSelection()
        if 0 <= self.page_index < self.page_table.rowCount():
            self.page_table.selectRow(self.page_index)
        for i in range(self.thumbs.count()):
            item = self.thumbs.item(i)
            if item.flags() & Qt.ItemIsEnabled:
                item.setSelected(item.data(Qt.UserRole) == self.page_index)

    def _update_actions(self):
        self.btn_prev.setEnabled(self.page_index > 0)
        self.btn_next.setEnabled(self.page_index < max(0, self.page_total - 1))

    # ----------------------------------------------------------- file actions
    def save_current(self):
        if not self._ensure_open() or not self.source_path:
            return
        PT.commit_workspace(self.source_path)
        self.source_mtime = self.source_path.stat().st_mtime
        self._set_status(f"Saved changes to {self.source_path.name}.")

    def save_as(self):
        if not self._ensure_open() or not self.source_path:
            return
        out, _ = QFileDialog.getSaveFileName(self, "Save PDF Copy", str(self.source_path), "PDF Files (*.pdf)")
        if not out:
            return
        PT.commit_workspace(self.source_path, out)
        self._set_status(f"Saved a new PDF copy: {Path(out).name}")
        self.reload_recent()

    def duplicate_file(self):
        if not self._ensure_open():
            return
        dup = PT.duplicate_file(self._share_pdf() or self._current_pdf())
        self._set_status(f"Duplicate created: {dup.name}")
        self.reload_recent()

    def rename_file(self):
        if not self._ensure_open() or not self.source_path:
            return
        name, ok = QInputDialog.getText(self, "Rename PDF", "New file name:", text=self.source_path.name)
        if not ok or not name.strip():
            return
        if self.is_dirty():
            self.save_current()
        try:
            newp = PT.rename_file(self.source_path, name.strip())
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))
            return
        self.open_file(newp)
        self._set_status(f"Renamed to {newp.name}")

    def undo(self):
        if self.source_path and PT.undo(self.source_path):
            self.reload_document(keep_page=True)
            self._set_status("Undo applied.")

    def redo(self):
        if self.source_path and PT.redo(self.source_path):
            self.reload_document(keep_page=True)
            self._set_status("Redo applied.")

    def open_folder(self):
        if self.source_path:
            D.open_file_location(self.source_path)

    # --------------------------------------------------------- annotate/sign
    def pick_color(self):
        c = QColorDialog.getColor(QColor(self.a_color.text() or "#ffbf00"), self)
        if c.isValid():
            self.a_color.setText(c.name())

    def pick_signature_image(self):
        p, _ = QFileDialog.getOpenFileName(self, "Signature / stamp image", str(Path.home()),
                                           "Images (*.png *.jpg *.jpeg *.bmp)")
        if p:
            self.a_image.setText(p)

    def paste_signature_image(self):
        img = QApplication.clipboard().image()
        if img.isNull() or not self.source_path:
            W.error_box(self, "Copy an image to the clipboard first.")
            return
        out = PT.session_paths(self.source_path)["folder"] / f"signature_{PT._now_tag()}.png"
        if not img.save(str(out), "PNG"):
            W.error_box(self, "The clipboard image could not be saved.")
            return
        self.a_image.setText(str(out))
        self.a_kind.setCurrentText("Signature")
        self._set_status("Signature image pasted from the clipboard.")

    def _annotation_rows(self) -> list[dict]:
        pages = self._picked_range()
        kind = self.a_kind.currentText().lower()
        anns = []
        for i in pages:
            anns.append({
                "page": i + 1,
                "type": kind,
                "text": self.a_text.toPlainText().strip(),
                "x": self.a_x.value(),
                "y": self.a_y.value(),
                "w": self.a_w.value(),
                "h": self.a_h.value(),
                "color": self.a_color.text().strip() or "#ffbf00",
                "image_path": self.a_image.text().strip(),
            })
        return anns

    def apply_annotation(self):
        anns = self._annotation_rows()
        if not anns:
            return
        self._apply_workspace(lambda src, dst: PT.annotate_pdf(src, anns, dst),
                              f"{len(anns)} annotation(s) applied.")

    def save_signed_copy(self):
        anns = self._annotation_rows()
        if not anns:
            return
        out, _ = QFileDialog.getSaveFileName(self, "Save Signed / Annotated PDF",
                                             str(PT.default_export_path(self.source_path or 'signed', '.signed.pdf')),
                                             "PDF Files (*.pdf)")
        if not out:
            return
        PT.annotate_pdf(self._current_pdf(), anns, out)
        self._set_status(f"Signed / annotated copy saved: {Path(out).name}")

    # ------------------------------------------------------------- organize
    def move_selected_pages(self, delta: int):
        rows = self._selected_rows()
        if not rows:
            return
        if delta < 0:
            for r in rows:
                if r > 0:
                    for c in range(self.page_table.columnCount()):
                        upper = self.page_table.takeItem(r - 1, c)
                        cur = self.page_table.takeItem(r, c)
                        self.page_table.setItem(r - 1, c, cur)
                        self.page_table.setItem(r, c, upper)
            for r in [max(0, r - 1) for r in rows]:
                self.page_table.selectRow(r)
        else:
            for r in reversed(rows):
                if r < self.page_table.rowCount() - 1:
                    for c in range(self.page_table.columnCount()):
                        lower = self.page_table.takeItem(r + 1, c)
                        cur = self.page_table.takeItem(r, c)
                        self.page_table.setItem(r + 1, c, cur)
                        self.page_table.setItem(r, c, lower)
            for r in [min(self.page_table.rowCount() - 1, r + 1) for r in rows]:
                self.page_table.selectRow(r)

    def apply_page_order(self):
        if not self._ensure_open():
            return
        order = [int(self.page_table.item(r, 0).data(Qt.UserRole)) for r in range(self.page_table.rowCount())]
        self._apply_workspace(lambda src, dst: PT.reorder_pdf(src, order, dst), "Page order updated.")

    def duplicate_selected_pages(self):
        pages = self._selected_pages()
        self._apply_workspace(lambda src, dst: PT.duplicate_pages(src, pages, dst),
                              f"{len(pages)} page(s) duplicated.")

    def delete_selected_pages(self):
        pages = self._selected_pages()
        if not W.confirm(self, f"Delete {len(pages)} page(s) from the working copy?"):
            return
        try:
            self._apply_workspace(lambda src, dst: PT.delete_pages(src, pages, dst),
                                  f"{len(pages)} page(s) deleted.")
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))

    def extract_selected_pages(self):
        pages = self._selected_pages()
        out, _ = QFileDialog.getSaveFileName(self, "Extract Pages", str(PT.default_export_path(self.source_path or 'extract', '.extract.pdf')),
                                             "PDF Files (*.pdf)")
        if not out:
            return
        PT.extract_pages(self._current_pdf(), pages, out)
        self._set_status(f"Extracted {len(pages)} page(s) to {Path(out).name}")

    def rotate_selected_pages(self, angle: int):
        pages = self._selected_pages()
        self._apply_workspace(lambda src, dst: PT.rotate_pages(src, pages, angle, dst),
                              f"Rotated {len(pages)} page(s) by {angle}°.")

    def merge_pdf(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select PDF(s) to merge", str(Path.home()), "PDF Files (*.pdf)")
        if not files:
            return
        self._apply_workspace(lambda src, dst: PT.merge_pdfs([src, *files], dst),
                              f"Merged {len(files)} extra PDF file(s).")

    def split_pdf(self):
        if not self._ensure_open():
            return
        ranges, ok = QInputDialog.getText(self, "Split PDF", "Page ranges separated by ;\nExample: 1-2;3;4-5")
        if not ok or not ranges.strip():
            return
        out = QFileDialog.getExistingDirectory(self, "Folder for split PDFs", str(self.source_path.parent))
        if not out:
            return
        pieces = PT.split_pdf(self._current_pdf(), [x.strip() for x in ranges.split(";") if x.strip()], out)
        self._set_status(f"Created {len(pieces)} split PDF file(s).")

    # -------------------------------------------------------------- convert
    def export_images(self, fmt: str):
        if not self._ensure_open() or not self.source_path:
            return
        folder = QFileDialog.getExistingDirectory(self, f"Export {fmt.upper()} pages", str(self.source_path.parent))
        if not folder:
            return
        files = PT.export_all_images(self._current_pdf(), folder, fmt=fmt)
        self._set_status(f"Exported {len(files)} page image(s) to {folder}")

    def export_docx(self):
        if not self._ensure_open() or not self.source_path:
            return
        out, _ = QFileDialog.getSaveFileName(self, "Convert to Word", str(PT.default_export_path(self.source_path, ".docx")),
                                             "Word Files (*.docx)")
        if out:
            PT.convert_to_docx(self._current_pdf(), out)
            self._set_status(f"Word file created: {Path(out).name}")

    def export_xlsx(self):
        if not self._ensure_open() or not self.source_path:
            return
        out, _ = QFileDialog.getSaveFileName(self, "Convert to Excel", str(PT.default_export_path(self.source_path, ".xlsx")),
                                             "Excel Files (*.xlsx)")
        if out:
            PT.convert_to_xlsx(self._current_pdf(), out)
            self._set_status(f"Excel file created: {Path(out).name}")

    def export_txt(self):
        if not self._ensure_open() or not self.source_path:
            return
        out, _ = QFileDialog.getSaveFileName(self, "Export Text", str(PT.default_export_path(self.source_path, ".txt")),
                                             "Text Files (*.txt)")
        if out:
            PT.convert_to_txt(self._current_pdf(), out)
            self._set_status(f"Text export created: {Path(out).name}")

    def export_html(self):
        if not self._ensure_open() or not self.source_path:
            return
        out, _ = QFileDialog.getSaveFileName(self, "Export HTML", str(PT.default_export_path(self.source_path, ".html")),
                                             "HTML Files (*.html)")
        if out:
            PT.convert_to_html(self._current_pdf(), out)
            self._set_status(f"HTML export created: {Path(out).name}")

    # --------------------------------------------------------------- print
    def preview_print_job(self):
        out = self._make_subset()
        if out:
            dlg = PdfViewerDialog(self)
            dlg.open_file(out, title=f"Print Preview — {Path(out).name}")
            self._set_status(f"Print preview created with {self.p_copies.value()} copy/copies.")

    def print_with_options(self):
        pdf = self._make_subset()
        if not pdf:
            return
        db = self._db()
        copies = self.p_copies.value()
        for _ in range(copies):
            D.print_file(db, pdf)
        self._set_status(f"Sent {copies} print job(s) for {pdf.name}.")

    # -------------------------------------------------------------- security
    def protect_copy(self):
        if not self._ensure_open() or not self.source_path:
            return
        if not self.sec_user.text():
            W.error_box(self, "Enter at least the open password.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "Save Protected PDF",
                                             str(PT.default_export_path(self.source_path, ".protected.pdf")),
                                             "PDF Files (*.pdf)")
        if not out:
            return
        PT.protect_pdf(self._current_pdf(), out, self.sec_user.text(), self.sec_owner.text(),
                       self.sec_print.isChecked(), self.sec_copy.isChecked(), self.sec_modify.isChecked())
        self._set_status(f"Protected PDF saved: {Path(out).name}")

    # ---------------------------------------------------------------- share
    def share_email(self):
        pdf = self._share_pdf()
        db = self._db()
        if not pdf:
            return
        to = self.mail_to.text().strip()
        if not to:
            W.error_box(self, "Enter the recipient email address first.")
            return
        try:
            msg = D.email_pdf(db, pdf, to)
            self._set_status(msg)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, str(exc))

    def share_whatsapp(self):
        pdf = self._share_pdf()
        db = self._db()
        if pdf:
            D.whatsapp_share(db, pdf, self.wa_to.text().strip())
            self._set_status("WhatsApp opened with the current PDF ready to attach.")

    def copy_file_link(self):
        if self.source_path:
            QApplication.clipboard().setText(self.source_path.resolve().as_uri())
            self._set_status("File link copied.")

    def copy_path(self):
        if self.source_path:
            QApplication.clipboard().setText(str(self.source_path))
            self._set_status("File path copied.")


def show_pdf(path: str | Path, parent=None, title: str = "") -> bool:
    global _VIEWER
    if _VIEWER is None:
        _VIEWER = PdfViewerDialog(parent)
    return _VIEWER.open_file(path, title)


def open_studio(parent=None):
    global _VIEWER
    if _VIEWER is None:
        _VIEWER = PdfViewerDialog(parent)
    _VIEWER.show()
    _VIEWER.raise_()
    _VIEWER.activateWindow()
    return _VIEWER
