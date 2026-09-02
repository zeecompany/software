"""Built-in PDF viewer for AURCO documents on shared storage."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

PDF_SUPPORTED = True
try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
except Exception:  # noqa: BLE001
    PDF_SUPPORTED = False
    QPdfDocument = object  # type: ignore[misc,assignment]
    QPdfView = object      # type: ignore[misc,assignment]

from . import widgets as W

_VIEWER = None


class PdfViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AURCO PDF Viewer")
        self.resize(1040, 760)
        self.path = Path()
        self._mtime = 0.0
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.caption = QLabel("No PDF loaded")
        self.caption.setStyleSheet("font-weight:600;color:#0b3d6b")
        top.addWidget(self.caption, 1)
        self.status = QLabel("Built-in viewer")
        self.status.setStyleSheet("color:#5f6368")
        top.addWidget(self.status)
        v.addLayout(top)

        bar = QHBoxLayout()
        self.btn_reload = QPushButton("Reload")
        self.btn_reload.clicked.connect(self.reload_document)
        bar.addWidget(self.btn_reload)
        self.btn_fit = QPushButton("Fit Width")
        self.btn_fit.clicked.connect(self.fit_width)
        bar.addWidget(self.btn_fit)
        self.btn_actual = QPushButton("100%")
        self.btn_actual.clicked.connect(self.actual_size)
        bar.addWidget(self.btn_actual)
        self.btn_in = QPushButton("＋")
        self.btn_in.clicked.connect(lambda: self._zoom(1.15))
        bar.addWidget(self.btn_in)
        self.btn_out = QPushButton("－")
        self.btn_out.clicked.connect(lambda: self._zoom(1 / 1.15))
        bar.addWidget(self.btn_out)
        bar.addStretch(1)
        bar.addWidget(QLabel("Auto-refresh shared file changes"))
        v.addLayout(bar)

        if PDF_SUPPORTED:
            self.doc = QPdfDocument(self)
            self.view = QPdfView(self)
            self.view.setDocument(self.doc)
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            v.addWidget(self.view, 1)
        else:
            self.doc = None
            lab = QLabel("This build does not include Qt PDF support.")
            lab.setAlignment(Qt.AlignCenter)
            self.view = QWidget(self)
            lay = QVBoxLayout(self.view)
            lay.addWidget(lab)
            v.addWidget(self.view, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(2200)
        self.timer.timeout.connect(self._check_file_change)
        self.timer.start()

    def open_file(self, path: str | Path, title: str = "") -> bool:
        p = Path(path)
        if not p.exists() or p.suffix.lower() != ".pdf":
            self.status.setText("PDF file not found.")
            return False
        self.path = p
        self.caption.setText(title or p.name)
        ok = self.reload_document(first=True)
        if ok:
            self.show()
            self.raise_()
            self.activateWindow()
        return ok

    def _read_mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return 0.0

    def reload_document(self, first: bool = False) -> bool:
        if not PDF_SUPPORTED or not self.path:
            return False
        self._mtime = self._read_mtime()
        err = self.doc.load(str(self.path))
        if err == QPdfDocument.Error.None_:
            if first:
                self.fit_width()
            self.status.setText(f"Viewing: {self.path}")
            return True
        self.status.setText(f"Could not load PDF ({err}).")
        return False

    def _check_file_change(self):
        if not PDF_SUPPORTED or not self.path.exists():
            return
        cur = self._read_mtime()
        if cur and cur != self._mtime:
            self.reload_document()
            self.status.setText(f"Updated from shared storage: {self.path.name}")

    def fit_width(self):
        if PDF_SUPPORTED:
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def actual_size(self):
        if PDF_SUPPORTED:
            self.view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.view.setZoomFactor(1.0)

    def _zoom(self, factor: float):
        if PDF_SUPPORTED:
            self.view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.view.setZoomFactor(max(0.2, min(5.0, self.view.zoomFactor() * factor)))


def show_pdf(path: str | Path, parent=None, title: str = "") -> bool:
    global _VIEWER
    if not PDF_SUPPORTED:
        return False
    if _VIEWER is None:
        _VIEWER = PdfViewerDialog(parent)
    return _VIEWER.open_file(path, title)
