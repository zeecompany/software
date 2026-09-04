"""Shared UI building blocks: theme, cards, charts, tables, toasts, dialogs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QIcon, QKeySequence, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
                               QDialogButtonBox, QFrame, QGraphicsDropShadowEffect, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton,
                               QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

# --------------------------------------------------------------- palette
# These module-level names are the *live* palette. They are refreshed from the
# database theme by apply_theme() so every screen follows the user's colours.
from ..core import theming

NAVY = theming.THEME_KEYS["ui_primary"]
NAVY_DARK = theming.THEME_KEYS["ui_primary_dark"]
ACCENT = theming.THEME_KEYS["ui_accent"]
BG = theming.THEME_KEYS["ui_bg"]
CARD = theming.THEME_KEYS["ui_card"]
TEXT = theming.THEME_KEYS["ui_text"]
MUTED = theming.THEME_KEYS["ui_muted"]
BORDER = theming.THEME_KEYS["ui_border"]
GREEN = theming.THEME_KEYS["ui_ok"]
AMBER = theming.THEME_KEYS["ui_warn"]
ORANGE = theming.THEME_KEYS["ui_crit"]
RED = theming.THEME_KEYS["ui_danger"]

_CURRENT_THEME: dict[str, str] = dict(theming.THEME_KEYS)


def current_theme() -> dict:
    return dict(_CURRENT_THEME)


def is_dark_theme() -> bool:
    return theming.is_dark(_CURRENT_THEME)


def apply_theme(app, theme: dict) -> None:
    """Refresh the live palette + status colours and restyle the whole app."""
    global NAVY, NAVY_DARK, ACCENT, BG, CARD, TEXT, MUTED, BORDER, GREEN, AMBER, ORANGE, RED
    global _CURRENT_THEME
    _CURRENT_THEME = dict(theming.THEME_KEYS)
    _CURRENT_THEME.update({k: v for k, v in theme.items() if k in theming.THEME_KEYS})
    t = _CURRENT_THEME
    NAVY, NAVY_DARK, ACCENT = t["ui_primary"], t["ui_primary_dark"], t["ui_accent"]
    BG, CARD, TEXT = t["ui_bg"], t["ui_card"], t["ui_text"]
    MUTED, BORDER = t["ui_muted"], t["ui_border"]
    GREEN, AMBER, ORANGE, RED = t["ui_ok"], t["ui_warn"], t["ui_crit"], t["ui_danger"]
    # keep stock status colours in sync with the theme
    from ..core import services as _S
    _S.STATUS_COLORS[_S.NORMAL] = GREEN
    _S.STATUS_COLORS[_S.WARNING] = AMBER
    _S.STATUS_COLORS[_S.CRITICAL] = ORANGE
    _S.STATUS_COLORS[_S.OUT] = RED
    if app is not None:
        app.setStyleSheet(theming.build_stylesheet(t))


def build_stylesheet(dark_or_theme=False) -> str:
    """Backwards-compatible helper: accepts a theme dict or a bool."""
    if isinstance(dark_or_theme, dict):
        return theming.build_stylesheet(dark_or_theme)
    t = dict(theming.THEME_KEYS)
    if dark_or_theme:
        t.update(theming.PRESETS["AURCO Dark"])
    return theming.build_stylesheet(t)


def shadow(widget: QWidget, blur: int = 18, alpha: int = 26) -> None:
    if _CURRENT_THEME.get("ui_show_shadows", "1") != "1":
        widget.setGraphicsEffect(None)
        return
    e = QGraphicsDropShadowEffect(widget)
    e.setBlurRadius(blur)
    e.setColor(QColor(QColor(NAVY).red(), QColor(NAVY).green(), QColor(NAVY).blue(), alpha))
    e.setOffset(0, 3)
    widget.setGraphicsEffect(e)


def icon_pixmap(glyph: str, color: str = NAVY, size: int = 26) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(color))
    f = QFont("Segoe UI Symbol", int(size * 0.62))
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, glyph)
    p.end()
    return pm


def app_icon() -> QIcon:
    """The window / taskbar icon.

    A custom icon chosen in Settings wins; otherwise the bundled .ico; otherwise
    the drawn AURCO mark below. Never raises -- a bad path just falls through.
    """
    try:
        from ..core import config as _cfg
        from ..core.database import get_db
        custom = (get_db().get_setting("app_icon_path", "") or "").strip()
        if custom and Path(custom).exists():
            ic = QIcon(custom)
            if not ic.isNull() and ic.availableSizes():
                return ic
        bundled = _cfg.resource_path("assets/aurco.ico")
        if bundled.exists():
            ic = QIcon(str(bundled))
            if not ic.isNull() and ic.availableSizes():
                return ic
    except Exception:
        pass
    return _drawn_app_icon()


def _drawn_app_icon() -> QIcon:
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 256, 256)
    g.setColorAt(0, QColor(NAVY))
    g.setColorAt(1, QColor(NAVY).lighter(140))
    path = QPainterPath()
    path.addRoundedRect(QRectF(8, 8, 240, 240), 46, 46)
    p.fillPath(path, QBrush(g))
    p.setPen(QPen(QColor(ACCENT), 12))
    p.drawLine(40, 196, 216, 196)
    p.setBrush(QColor("#ffffff"))
    p.setPen(Qt.NoPen)
    for x, h in ((58, 60), (108, 100), (158, 78)):
        p.drawRoundedRect(QRectF(x, 186 - h, 40, h), 6, 6)
    p.setPen(QColor(ACCENT))
    p.setFont(QFont("Arial", 42, QFont.Black))
    p.drawText(QRectF(0, 30, 256, 50), Qt.AlignCenter, "AURCO")
    p.end()
    return QIcon(pm)


# ------------------------------------------------------------------- cards
class Card(QFrame):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(14, 12, 14, 12)
        self.v.setSpacing(8)
        if title:
            lbl = QLabel(title)
            lbl.setObjectName("CardTitle")
            self.v.addWidget(lbl)
        shadow(self)

    def add(self, w: QWidget, stretch: int = 0) -> QWidget:
        self.v.addWidget(w, stretch)
        return w


class StatCard(QFrame):
    """Clickable KPI tile."""
    clicked = Signal()

    def __init__(self, label: str, value: str = "0", glyph: str = "", color: str = NAVY,
                 sub: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(84)
        self.color = color
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 12, 10)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setPixmap(icon_pixmap(glyph or "\u25a0", color, 30))
        self.icon.setFixedWidth(34)
        lay.addWidget(self.icon)
        box = QVBoxLayout()
        box.setSpacing(1)
        self.lbl_value = QLabel(value)
        self.lbl_value.setObjectName("StatValue")
        self.lbl_value.setStyleSheet(f"color:{color};")
        self.lbl_label = QLabel(label.upper())
        self.lbl_label.setObjectName("StatLabel")
        self.lbl_sub = QLabel(sub)
        self.lbl_sub.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        box.addWidget(self.lbl_value)
        box.addWidget(self.lbl_label)
        box.addWidget(self.lbl_sub)
        lay.addLayout(box, 1)
        shadow(self)

    def set_value(self, value: Any, sub: str = "") -> None:
        self.lbl_value.setText(str(value))
        if sub:
            self.lbl_sub.setText(sub)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


def status_pill(text: str, color: str) -> QLabel:
    l = QLabel(text)
    l.setObjectName("Pill")
    l.setStyleSheet(f"background:{color}; color:white; border-radius:9px; padding:2px 9px;"
                    f"font-size:11px; font-weight:700;")
    l.setAlignment(Qt.AlignCenter)
    return l


# ------------------------------------------------------------------ charts
class BarChart(QWidget):
    """Lightweight painted bar chart (no external chart dependency)."""
    barClicked = Signal(str)

    def __init__(self, data: Sequence[tuple[str, float]] | None = None, color: str = NAVY,
                 horizontal: bool = False, parent=None):
        super().__init__(parent)
        self.data = list(data or [])
        self.color = color
        self.horizontal = horizontal
        self.setMinimumHeight(180)
        self._rects: list[tuple[QRectF, str]] = []
        self.setMouseTracking(True)

    def set_data(self, data: Sequence[tuple[str, float]]) -> None:
        self.data = list(data)
        self.update()

    def mousePressEvent(self, e):
        for r, k in self._rects:
            if r.contains(e.position()):
                self.barClicked.emit(k)
                return

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        self._rects = []
        if not self.data:
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "No data yet")
            return
        mx = max((v for _, v in self.data), default=1) or 1
        p.setFont(QFont("Segoe UI", 8))
        if self.horizontal:
            lblw = 118
            bh = min(24, (h - 8) / len(self.data))
            for i, (k, v) in enumerate(self.data):
                y = 4 + i * bh
                bw = max(2, (w - lblw - 60) * (v / mx))
                p.setPen(QColor(TEXT))
                p.drawText(QRectF(0, y, lblw - 6, bh), Qt.AlignVCenter | Qt.AlignRight,
                           str(k)[:20])
                r = QRectF(lblw, y + bh * 0.18, bw, bh * 0.64)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(self.color))
                p.drawRoundedRect(r, 3, 3)
                p.setPen(QColor(MUTED))
                p.drawText(QRectF(lblw + bw + 5, y, 56, bh), Qt.AlignVCenter | Qt.AlignLeft,
                           f"{v:,.0f}")
                self._rects.append((r, str(k)))
        else:
            n = len(self.data)
            gap = 8
            bw = max(6, (w - gap * (n + 1)) / n)
            base = h - 22
            for i, (k, v) in enumerate(self.data):
                bh = max(2, (base - 14) * (v / mx))
                r = QRectF(gap + i * (bw + gap), base - bh, bw, bh)
                grad = QLinearGradient(r.topLeft(), r.bottomLeft())
                grad.setColorAt(0, QColor(self.color))
                grad.setColorAt(1, QColor(self.color).lighter(135))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(grad))
                p.drawRoundedRect(r, 4, 4)
                p.setPen(QColor(TEXT))
                p.drawText(QRectF(r.x(), r.y() - 14, bw, 13), Qt.AlignCenter, f"{v:,.0f}")
                p.setPen(QColor(MUTED))
                p.drawText(QRectF(r.x() - 4, base + 3, bw + 8, 18), Qt.AlignCenter, str(k)[:12])
                self._rects.append((r, str(k)))
        p.end()


class GroupedBarChart(QWidget):
    """Two series (In / Out) per category, with a nameable legend."""

    def __init__(self, parent=None, labels: tuple[str, str] = ("Stock In", "Stock Out")):
        super().__init__(parent)
        self.data: list[tuple[str, float, float]] = []
        self.labels = labels
        self.setMinimumHeight(190)

    def set_data(self, data): 
        self.data = list(data)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if not self.data:
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "No movement data yet")
            return
        mx = max(max(a, b) for _, a, b in self.data) or 1
        n = len(self.data)
        gap = 14
        gw = (w - gap * (n + 1)) / n
        bw = gw / 2 - 2
        base = h - 34
        p.setFont(QFont("Segoe UI", 8))
        for i, (k, a, b) in enumerate(self.data):
            x = gap + i * (gw + gap)
            for j, (v, col) in enumerate(((a, GREEN), (b, ORANGE))):
                bh = max(2, (base - 16) * (v / mx))
                r = QRectF(x + j * (bw + 3), base - bh, bw, bh)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(col))
                p.drawRoundedRect(r, 3, 3)
                p.setPen(QColor(MUTED))
                p.drawText(QRectF(r.x() - 6, r.y() - 13, bw + 12, 12), Qt.AlignCenter, f"{v:,.0f}")
            p.setPen(QColor(TEXT))
            p.drawText(QRectF(x, base + 4, gw, 14), Qt.AlignCenter, str(k))
        # legend
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(GREEN))
        p.drawRect(QRectF(gap, h - 15, 10, 10))
        p.setPen(QColor(TEXT))
        p.drawText(QPointF(gap + 15, h - 6), self.labels[0])
        off = gap + 30 + p.fontMetrics().horizontalAdvance(self.labels[0])
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ORANGE))
        p.drawRect(QRectF(off, h - 15, 10, 10))
        p.setPen(QColor(TEXT))
        p.drawText(QPointF(off + 15, h - 6), self.labels[1])
        p.end()


class DonutChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: list[tuple[str, float, str]] = []
        self.setMinimumHeight(190)

    def set_data(self, data):
        self.data = list(data)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        total = sum(v for _, v, _ in self.data)
        size = min(w * 0.52, h) - 16
        rect = QRectF(10, (h - size) / 2, size, size)
        if total <= 0:
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "No data")
            return
        start = 90 * 16
        for _, v, col in self.data:
            span = int(-360 * 16 * v / total)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawPie(rect, start, span)
            start += span
        p.setBrush(QColor(CARD))
        inner = rect.adjusted(size * 0.24, size * 0.24, -size * 0.24, -size * 0.24)
        p.drawEllipse(inner)
        p.setPen(QColor(TEXT))
        p.setFont(QFont("Segoe UI", 12, QFont.Bold))
        p.drawText(inner, Qt.AlignCenter, f"{int(total)}")
        p.setFont(QFont("Segoe UI", 9))
        y = (h - len(self.data) * 20) / 2 + 6
        for k, v, col in self.data:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(rect.right() + 16, y, 11, 11), 3, 3)
            p.setPen(QColor(TEXT))
            p.drawText(QPointF(rect.right() + 33, y + 10), f"{k}  ({int(v)})")
            y += 20
        p.end()


class LineChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: list[tuple[str, float]] = []
        self.setMinimumHeight(170)

    def set_data(self, data):
        self.data = list(data)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if len(self.data) < 2:
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "Not enough data")
            return
        mx = max(v for _, v in self.data) or 1
        base, top, left = h - 24, 14, 34
        step = (w - left - 14) / (len(self.data) - 1)
        pts = [QPointF(left + i * step, base - (base - top) * (v / mx))
               for i, (_, v) in enumerate(self.data)]
        p.setPen(QPen(QColor(BORDER), 1, Qt.DashLine))
        for i in range(5):
            y = top + (base - top) * i / 4
            p.drawLine(QPointF(left, y), QPointF(w - 10, y))
        poly = QPolygonF([QPointF(pts[0].x(), base)] + pts + [QPointF(pts[-1].x(), base)])
        grad = QLinearGradient(0, top, 0, base)
        c0 = QColor(NAVY); c0.setAlpha(90)
        c1 = QColor(NAVY); c1.setAlpha(8)
        grad.setColorAt(0, c0)
        grad.setColorAt(1, c1)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPolygon(poly)
        p.setPen(QPen(QColor(NAVY), 2))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(pts))
        p.setBrush(QColor(ACCENT))
        p.setFont(QFont("Segoe UI", 8))
        for (k, v), pt in zip(self.data, pts):
            p.setPen(Qt.NoPen)
            p.drawEllipse(pt, 3.4, 3.4)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(pt.x() - 26, base + 4, 52, 16), Qt.AlignCenter, str(k)[-5:])
        p.end()


# ------------------------------------------------------------------ tables
class ColumnFilterDialog(QDialog):
    """Excel-style filter for one column: search, tick values, sort."""

    def __init__(self, table, col: int, parent=None):
        super().__init__(parent or table)
        self.table = table
        self.col = col
        header = table.horizontalHeaderItem(col)
        name = header.text() if header else f"Column {col + 1}"
        self.setWindowTitle(f"Filter — {name}")
        self.setModal(True)
        self.resize(320, 460)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        srow = QHBoxLayout()
        srow.addWidget(button("A → Z", slot=lambda: self._sort(Qt.AscendingOrder)))
        srow.addWidget(button("Z → A", slot=lambda: self._sort(Qt.DescendingOrder)))
        v.addLayout(srow)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search values...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refill)
        v.addWidget(self.search)

        brow = QHBoxLayout()
        brow.addWidget(button("Select all", slot=lambda: self._set_all(True)))
        brow.addWidget(button("Clear", slot=lambda: self._set_all(False)))
        v.addLayout(brow)

        self.list = QListWidget()
        v.addWidget(self.list, 1)

        self.count = QLabel()
        self.count.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        v.addWidget(self.count)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.addButton("Clear filter", QDialogButtonBox.ResetRole).clicked.connect(
            self._clear)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        self._values = table.column_values(col)
        self._active = set(table.active_filter(col) or self._values)
        self._refill()

    def _refill(self):
        needle = self.search.text().strip().lower()
        self.list.clear()
        shown = 0
        for val in self._values:
            if needle and needle not in val.lower():
                continue
            it = QListWidgetItem(val if val != "" else "(blank)")
            it.setData(Qt.UserRole, val)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if val in self._active else Qt.Unchecked)
            self.list.addItem(it)
            shown += 1
        self.count.setText(f"{shown} of {len(self._values)} distinct value(s)")

    def _set_all(self, on: bool):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _sort(self, order):
        self.table.sortItems(self.col, order)

    def _clear(self):
        self.table.set_column_filter(self.col, None)
        self.accept()

    def _apply(self):
        # values hidden by the search box keep their previous state
        chosen = set(self._active)
        for i in range(self.list.count()):
            it = self.list.item(i)
            val = it.data(Qt.UserRole)
            if it.checkState() == Qt.Checked:
                chosen.add(val)
            else:
                chosen.discard(val)
        if chosen == set(self._values):
            self.table.set_column_filter(self.col, None)
        else:
            self.table.set_column_filter(self.col, chosen)
        self.accept()


class DataTable(QTableWidget):
    """Sortable, searchable, copy/export friendly table with Excel-style
    per-column filters (Ctrl+click or right-click a heading)."""
    filtersChanged = Signal(int)

    def __init__(self, columns: Sequence[str] | None = None, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(_CURRENT_THEME.get("ui_stripe_rows", "1") == "1")
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(int(_CURRENT_THEME.get("ui_row_height", 27) or 27))
        hh = self.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setHighlightSections(False)
        hh.setSectionsMovable(True)
        hh.setContextMenuPolicy(Qt.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._header_menu)
        hh.sectionClicked.connect(self._maybe_filter)
        self.setWordWrap(False)
        # Excel-style per-column filters
        self._filters: dict[int, set] = {}
        self._filter_search = ""
        if columns:
            self.set_columns(columns)

    # ------------------------------------------------------- Excel filters
    def set_columns(self, columns: Sequence[str]) -> None:
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(list(columns))
        self._base_headers = [str(c) for c in columns]

    def _cell_text(self, r: int, c: int) -> str:
        it = self.item(r, c)
        return it.text() if it else ""

    def column_values(self, col: int) -> list[str]:
        """Every distinct value in a column, naturally sorted."""
        vals = {self._cell_text(r, col) for r in range(self.rowCount())}

        def key(v: str):
            try:
                return (0, float(v.replace(",", "")), "")
            except (ValueError, AttributeError):
                return (1, 0.0, v.lower())

        return sorted(vals, key=key)

    def active_filter(self, col: int):
        return self._filters.get(col)

    def set_column_filter(self, col: int, values) -> None:
        if values is None:
            self._filters.pop(col, None)
        else:
            self._filters[col] = set(values)
        self.apply_filters()

    def clear_filters(self) -> None:
        self._filters.clear()
        self._filter_search = ""
        self.apply_filters()

    def has_filters(self) -> bool:
        return bool(self._filters) or bool(self._filter_search)

    def apply_filters(self) -> None:
        """Hide rows that fail any column filter or the text search."""
        needle = (self._filter_search or "").strip().lower()
        for r in range(self.rowCount()):
            ok = True
            for col, allowed in self._filters.items():
                if col < self.columnCount() and self._cell_text(r, col) not in allowed:
                    ok = False
                    break
            if ok and needle:
                ok = any(needle in self._cell_text(r, c).lower()
                         for c in range(self.columnCount()))
            self.setRowHidden(r, not ok)
        self._mark_filtered_headers()
        self.filtersChanged.emit(self.visible_row_count())

    def visible_row_count(self) -> int:
        return sum(1 for r in range(self.rowCount()) if not self.isRowHidden(r))

    def _mark_filtered_headers(self) -> None:
        base = getattr(self, "_base_headers", None)
        if not base:
            return
        for c in range(min(self.columnCount(), len(base))):
            hi = self.horizontalHeaderItem(c)
            if hi is None:
                continue
            hi.setText(f"{base[c]}  ▼" if c in self._filters else base[c])
            f = hi.font()
            f.setBold(c in self._filters)
            hi.setFont(f)

    def _maybe_filter(self, col: int) -> None:
        """Ctrl+click a header opens its filter (plain click still sorts)."""
        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            self.open_filter(col)

    def open_filter(self, col: int) -> None:
        if col < 0 or col >= self.columnCount():
            return
        ColumnFilterDialog(self, col, self).exec()

    def _header_menu(self, pos) -> None:
        col = self.horizontalHeader().logicalIndexAt(pos)
        m = QMenu(self)
        if col >= 0:
            head = getattr(self, "_base_headers", [""] * self.columnCount())
            name = head[col] if col < len(head) else ""
            m.addAction(f"🔽  Filter '{name}'...", lambda: self.open_filter(col))
            m.addAction("A → Z", lambda: self.sortItems(col, Qt.AscendingOrder))
            m.addAction("Z → A", lambda: self.sortItems(col, Qt.DescendingOrder))
            if col in self._filters:
                m.addAction("✕  Clear this filter",
                            lambda: self.set_column_filter(col, None))
            m.addSeparator()
            m.addAction("↔  Fit this column",
                        lambda: self.resizeColumnToContents(col))
            m.addAction("🙈  Hide this column", lambda: self.setColumnHidden(col, True))
        m.addAction("↔  Fit all columns", self.resizeColumnsToContents)
        hidden = [c for c in range(self.columnCount()) if self.isColumnHidden(c)]
        if hidden:
            sub = m.addMenu("Show hidden column")
            head = getattr(self, "_base_headers", [])
            for c in hidden:
                nm = head[c] if c < len(head) else f"Column {c + 1}"
                sub.addAction(nm, lambda _=False, c=c: self.setColumnHidden(c, False))
        if self.has_filters():
            m.addSeparator()
            m.addAction("✕  Clear ALL filters", self.clear_filters)
        m.exec(self.horizontalHeader().viewport().mapToGlobal(pos))

    def fill(self, columns: Sequence[str], rows: Sequence[Sequence[Any]],
             colors: dict[int, str] | None = None, status_col: int | None = None) -> None:
        self.setSortingEnabled(False)
        self.set_columns(columns)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    it = QTableWidgetItem()
                    it.setData(Qt.DisplayRole, float(val) if isinstance(val, float) else int(val))
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    it = QTableWidgetItem("" if val is None else str(val))
                if status_col is not None and c == status_col:
                    from ..core.services import STATUS_COLORS
                    col = STATUS_COLORS.get(str(val))
                    if col:
                        it.setForeground(QBrush(QColor(col)))
                        f = it.font()
                        f.setBold(True)
                        it.setFont(f)
                self.setItem(r, c, it)
        self.setSortingEnabled(True)
        self.resizeColumnsToContents()
        for c in range(self.columnCount()):
            if self.columnWidth(c) > 320:
                self.setColumnWidth(c, 320)
        # Keep filters across a reload (so Refresh does not lose the user's
        # view) but never let a stale filter blank the whole table: drop any
        # column that has gone, and any filter that no longer matches a single
        # row in the new data.
        kept = {}
        for c, allowed in getattr(self, "_filters", {}).items():
            if c >= self.columnCount():
                continue
            present = {self._cell_text(r, c) for r in range(self.rowCount())}
            still = allowed & present
            if still:
                kept[c] = still
        self._filters = kept
        self.apply_filters()

    def selected_row_values(self) -> list[str]:
        r = self.currentRow()
        if r < 0:
            return []
        return [self.item(r, c).text() if self.item(r, c) else "" for c in range(self.columnCount())]

    def all_rows(self) -> list[list[str]]:
        return [[self.item(r, c).text() if self.item(r, c) else ""
                 for c in range(self.columnCount())] for r in range(self.rowCount())]

    def headers(self) -> list[str]:
        return [self.horizontalHeaderItem(c).text() for c in range(self.columnCount())]

    def filter_rows(self, text: str) -> None:
        """Free-text search across every column, combined with column filters."""
        self._filter_search = text or ""
        self.apply_filters()

    def visible_rows(self) -> list[list[str]]:
        """Only the rows the user can actually see — used by exports."""
        return [[self._cell_text(r, c) for c in range(self.columnCount())]
                for r in range(self.rowCount()) if not self.isRowHidden(r)]

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Copy):
            rows = sorted({i.row() for i in self.selectedIndexes()})
            cols = sorted({i.column() for i in self.selectedIndexes()})
            txt = "\n".join("\t".join(self.item(r, c).text() if self.item(r, c) else ""
                                      for c in cols) for r in rows)
            QApplication.clipboard().setText(txt)
            return
        super().keyPressEvent(e)


class FilterBar(QWidget):
    """Small strip that shows which column filters are active and clears them.

    Sits under the toolbar of any page that uses a DataTable, so the operator
    always knows why a list looks short.
    """

    def __init__(self, table: "DataTable", parent=None):
        super().__init__(parent)
        self.table = table
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        tip = QLabel("🔽 Filters:")
        tip.setStyleSheet(f"color:{MUTED}; font-size:11px; font-weight:700;")
        h.addWidget(tip)
        self.lbl = QLabel("none — Ctrl+click or right-click any column heading")
        self.lbl.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        h.addWidget(self.lbl, 1)
        self.btn_pick = button("🔽  Filter Column...", slot=self._pick,
                               tip="Choose a column to filter")
        h.addWidget(self.btn_pick)
        self.btn_clear = button("✕  Clear Filters", slot=table.clear_filters)
        h.addWidget(self.btn_clear)
        table.filtersChanged.connect(self._update)
        self._update(table.visible_row_count())

    def _pick(self):
        from PySide6.QtWidgets import QInputDialog
        heads = getattr(self.table, "_base_headers", []) or [
            self.table.horizontalHeaderItem(c).text()
            for c in range(self.table.columnCount())
            if self.table.horizontalHeaderItem(c)]
        if not heads:
            return
        name, ok = QInputDialog.getItem(self, "Filter column", "Column:", heads, 0, False)
        if ok and name in heads:
            self.table.open_filter(heads.index(name))

    def _update(self, visible: int = 0):
        heads = getattr(self.table, "_base_headers", [])
        names = [heads[c] if c < len(heads) else f"Col {c + 1}"
                 for c in sorted(self.table._filters)]
        total = self.table.rowCount()
        if names and visible == 0 and total:
            # never leave the operator staring at an unexplained empty grid
            self.lbl.setText(
                f"<b style='color:{RED}'>No rows match {', '.join(names)}</b>"
                f"  —  press Clear Filters to see all {total} row(s)")
            self.lbl.setStyleSheet("font-size:11px;")
        elif names:
            self.lbl.setText(
                f"<b>{', '.join(names)}</b>  ·  showing {visible} of {total} row(s)")
            self.lbl.setStyleSheet(f"color:{NAVY}; font-size:11px;")
        else:
            self.lbl.setText("none — Ctrl+click or right-click any column heading")
            self.lbl.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.btn_clear.setEnabled(self.table.has_filters())


class SearchBox(QLineEdit):
    def __init__(self, placeholder: str = "Search...", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(32)


# ----------------------------------------------------------------- feedback
class Toast(QLabel):
    """Non-blocking confirmation message in the corner of a window."""

    def __init__(self, parent: QWidget, text: str, kind: str = "ok", msec: int = 3200):
        super().__init__(parent)
        col = {"ok": GREEN, "warn": AMBER, "err": RED, "info": NAVY}.get(kind, NAVY)
        self.setText("  " + text)
        self.setStyleSheet(f"background:{col}; color:white; border-radius:7px; padding:11px 18px;"
                           f"font-weight:600; font-size:13px;")
        self.setWordWrap(True)
        self.setMaximumWidth(460)
        self.adjustSize()
        self.move(max(12, parent.width() - self.width() - 26), parent.height() - self.height() - 34)
        self.show()
        self.raise_()
        QTimer.singleShot(msec, self.deleteLater)


def toast(parent: QWidget, text: str, kind: str = "ok") -> None:
    w = parent.window()
    Toast(w, text, kind)


def error_box(parent: QWidget, text: str, title: str = "AURCO Inventory Manager") -> None:
    m = QMessageBox(parent)
    m.setIcon(QMessageBox.Warning)
    m.setWindowTitle(title)
    m.setText(text)
    m.exec()


def confirm(parent: QWidget, text: str, title: str = "Please confirm") -> bool:
    m = QMessageBox(parent)
    m.setIcon(QMessageBox.Question)
    m.setWindowTitle(title)
    m.setText(text)
    m.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    m.setDefaultButton(QMessageBox.No)
    return m.exec() == QMessageBox.Yes


def info_box(parent: QWidget, text: str, title: str = "AURCO Inventory Manager") -> None:
    m = QMessageBox(parent)
    m.setIcon(QMessageBox.Information)
    m.setWindowTitle(title)
    m.setText(text)
    m.exec()


def button(text: str, kind: str = "", slot: Callable | None = None, tip: str = "",
           shortcut: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip + (f"  ({shortcut})" if shortcut else ""))
    if shortcut:
        b.setShortcut(QKeySequence(shortcut))
    b.setCursor(Qt.PointingHandCursor)
    return b


def combo(items: Sequence[str], editable: bool = False, current: str = "") -> QComboBox:
    c = QComboBox()
    c.addItems([str(i) for i in items])
    c.setEditable(editable)
    if editable:
        c.setInsertPolicy(QComboBox.NoInsert)
    if current:
        i = c.findText(current)
        if i >= 0:
            c.setCurrentIndex(i)
        elif editable:
            c.setCurrentText(current)
    return c
