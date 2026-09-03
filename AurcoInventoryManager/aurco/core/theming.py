"""Theme engine: presets + per-element colour, font and form-style customization.

Every visual choice is stored in the settings table so it travels with the
database, and can be exported/imported as a .aurcotheme JSON file.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .database import Database

# Keys that make up a theme, with their factory defaults (Light preset).
THEME_KEYS: dict[str, str] = {
    "ui_primary": "#0b3d6b",        # sidebar / headers / primary buttons
    "ui_primary_dark": "#082c4d",   # sidebar background
    "ui_accent": "#f5a300",         # highlights, accent buttons
    "ui_bg": "#f2f5f9",             # window background
    "ui_card": "#ffffff",           # cards, inputs, tables
    "ui_text": "#1c2b3a",
    "ui_muted": "#6b7c8f",
    "ui_border": "#d8e1ea",
    "ui_ok": "#1a9c52",             # Normal status
    "ui_warn": "#e0a300",           # Warning status
    "ui_crit": "#e8590c",           # Critical status
    "ui_danger": "#c92a2a",         # Out of stock / destructive
    "ui_table_alt": "#f7fafc",      # alternating table row
    "ui_table_header_text": "#ffffff",
    "ui_selection": "#dbeafe",
    # typography & shape
    "ui_font_family": "Segoe UI",
    "ui_font_size": "13",
    "ui_radius": "8",               # corner radius
    "ui_density": "Comfortable",    # Compact | Comfortable | Spacious
    "ui_form_style": "Card",        # Card | Flat | Outlined
    "ui_form_header_bg": "#0b3d6b",     # transaction form title banner
    "ui_form_header_bg2": "#14538f",    # gradient end (same value = flat)
    "ui_form_header_text": "#ffffff",
    "ui_form_header_style": "Gradient",  # Gradient | Solid | Underline | Plain
    "ui_sidebar_width": "252",
    "ui_row_height": "27",
    "ui_show_shadows": "1",
    "ui_grid_lines": "1",
    "ui_stripe_rows": "1",
}

PRESETS: dict[str, dict[str, str]] = {
    "AURCO Light": {},  # the defaults above
    "AURCO Brand (Red)": {
        "ui_primary": "#c1121f", "ui_primary_dark": "#12161c", "ui_accent": "#c1121f",
        "ui_bg": "#f4f5f7", "ui_card": "#ffffff", "ui_text": "#16191f",
        "ui_border": "#dcdfe4", "ui_table_alt": "#faf6f6", "ui_selection": "#f7d9dc",
        "ui_form_header_bg": "#12161c", "ui_form_header_bg2": "#c1121f",
        "ui_crit": "#e8590c", "ui_danger": "#c1121f",
    },
    "AURCO Dark": {
        "ui_form_header_bg": "#123a63", "ui_form_header_bg2": "#1d5c99",
        "ui_primary": "#1d5c99", "ui_primary_dark": "#0d1b2a", "ui_accent": "#f5a300",
        "ui_bg": "#141a22", "ui_card": "#1e2632", "ui_text": "#e6edf3",
        "ui_muted": "#9fb0c0", "ui_border": "#2c3846", "ui_table_alt": "#232c39",
        "ui_selection": "#1d3a5c", "ui_ok": "#2ecc71", "ui_warn": "#f1c40f",
        "ui_crit": "#e67e22", "ui_danger": "#e74c3c",
    },
    "Midnight Blue": {
        "ui_form_header_bg": "#0a2540", "ui_form_header_bg2": "#12395e",
        "ui_primary": "#12395e", "ui_primary_dark": "#0a2540", "ui_accent": "#4fc3f7",
        "ui_bg": "#eef2f7", "ui_card": "#ffffff", "ui_text": "#16232f",
        "ui_border": "#cfdae6",
    },
    "Desert Sand": {
        "ui_form_header_bg": "#5f3d1c", "ui_form_header_bg2": "#8a5a2b",
        "ui_primary": "#8a5a2b", "ui_primary_dark": "#5f3d1c", "ui_accent": "#e0a300",
        "ui_bg": "#faf6f0", "ui_card": "#ffffff", "ui_text": "#3a2c1c",
        "ui_border": "#e3d5c2", "ui_table_alt": "#fbf7f1", "ui_selection": "#f6e6cd",
    },
    "Emerald Warehouse": {
        "ui_form_header_bg": "#0a4a36", "ui_form_header_bg2": "#0f6b4f",
        "ui_primary": "#0f6b4f", "ui_primary_dark": "#0a4a36", "ui_accent": "#f5a300",
        "ui_bg": "#f1f7f4", "ui_card": "#ffffff", "ui_text": "#12261f",
        "ui_border": "#cde3d9", "ui_table_alt": "#f4faf7", "ui_selection": "#d3ede1",
    },
    "Graphite": {
        "ui_form_header_bg": "#2b333c", "ui_form_header_bg2": "#3f4a56",
        "ui_primary": "#3f4a56", "ui_primary_dark": "#2b333c", "ui_accent": "#ff8c42",
        "ui_bg": "#f4f5f7", "ui_card": "#ffffff", "ui_text": "#22282e",
        "ui_border": "#d9dde2",
    },
    "High Contrast": {
        "ui_form_header_bg": "#000000", "ui_form_header_bg2": "#000000",
        "ui_form_header_style": "Solid",
        "ui_primary": "#000000", "ui_primary_dark": "#000000", "ui_accent": "#ffdd00",
        "ui_bg": "#ffffff", "ui_card": "#ffffff", "ui_text": "#000000",
        "ui_muted": "#333333", "ui_border": "#000000", "ui_table_alt": "#f0f0f0",
        "ui_selection": "#ffdd00", "ui_font_size": "14", "ui_radius": "0",
    },
}

DENSITY = {
    "Compact":     {"pad_v": 4, "pad_h": 9,  "row": 22, "gap": 6},
    "Comfortable": {"pad_v": 7, "pad_h": 14, "row": 27, "gap": 10},
    "Spacious":    {"pad_v": 10, "pad_h": 18, "row": 34, "gap": 14},
}


def get_theme(db: Database) -> dict[str, str]:
    t = dict(THEME_KEYS)
    for k in THEME_KEYS:
        v = db.get_setting(k)
        if v not in (None, ""):
            t[k] = str(v)
    return t


def save_theme(db: Database, theme: dict[str, Any]) -> None:
    for k, v in theme.items():
        if k in THEME_KEYS:
            db.set_setting(k, v)
    db.audit("EDITED", "theme", "", "appearance updated")


def apply_preset(db: Database, name: str) -> dict[str, str]:
    t = dict(THEME_KEYS)
    t.update(PRESETS.get(name, {}))
    save_theme(db, t)
    db.set_setting("ui_preset", name)
    return t


def export_theme(db: Database, path: str | Path) -> Path:
    p = Path(path)
    p.write_text(json.dumps(get_theme(db), indent=2), encoding="utf-8")
    return p


def import_theme(db: Database, path: str | Path) -> dict[str, str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    clean = {k: v for k, v in data.items() if k in THEME_KEYS}
    save_theme(db, clean)
    return get_theme(db)


def _lighten(hex_color: str, factor: float) -> str:
    """factor > 1 lightens, < 1 darkens."""
    try:
        c = hex_color.lstrip("#")
        r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
        r, g, b = (min(255, max(0, int(v * factor))) for v in (r, g, b))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


def is_dark(theme: dict[str, str]) -> bool:
    try:
        c = theme["ui_bg"].lstrip("#")
        r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
        return (r * 299 + g * 587 + b * 114) / 1000 < 128
    except Exception:
        return False


def build_stylesheet(theme: dict[str, str]) -> str:
    """Turn a theme dict into the full Qt stylesheet."""
    t = theme
    d = DENSITY.get(t.get("ui_density", "Comfortable"), DENSITY["Comfortable"])
    rad = int(float(t.get("ui_radius", 8) or 8))
    font = t.get("ui_font_family", "Segoe UI")
    size = int(float(t.get("ui_font_size", 13) or 13))
    primary = t["ui_primary"]
    dark_side = t["ui_primary_dark"]
    accent = t["ui_accent"]
    bg, card, text = t["ui_bg"], t["ui_card"], t["ui_text"]
    muted, border = t["ui_muted"], t["ui_border"]
    alt = t["ui_table_alt"] if t.get("ui_stripe_rows", "1") == "1" else card
    sel = t["ui_selection"]
    grid = border if t.get("ui_grid_lines", "1") == "1" else "transparent"
    hdr_text = t.get("ui_table_header_text", "#ffffff")
    dark = is_dark(t)
    hover_btn = _lighten(primary, 1.25 if not dark else 1.35)
    input_bg = card if not dark else _lighten(card, 1.12)
    scroll = _lighten(border, 0.95 if not dark else 1.4)

    # transaction form title banner
    fh1 = t.get("ui_form_header_bg", primary)
    fh2 = t.get("ui_form_header_bg2", fh1)
    fh_style = t.get("ui_form_header_style", "Gradient")
    _r = f"border-top-left-radius:{rad}px; border-top-right-radius:{rad}px;"
    if fh_style == "Plain":
        form_hdr_css = f"background: transparent; {_r} padding: 2px;"
    elif fh_style == "Underline":
        form_hdr_css = (f"background: transparent; border-bottom: 3px solid {fh1}; "
                        f"{_r} padding: 2px;")
    elif fh_style == "Solid":
        form_hdr_css = f"background: {fh1}; {_r} padding: 2px;"
    else:
        form_hdr_css = (f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                        f"stop:0 {fh1}, stop:1 {fh2}); {_r} padding: 2px;")

    # form container style
    style = t.get("ui_form_style", "Card")
    if style == "Flat":
        card_css = f"background: {card}; border: none; border-radius: {rad}px;"
    elif style == "Outlined":
        card_css = f"background: transparent; border: 2px solid {primary}; border-radius: {rad}px;"
    else:
        card_css = f"background: {card}; border: 1px solid {border}; border-radius: {rad}px;"

    return f"""
    QWidget {{ font-family: '{font}', 'Segoe UI', Arial; font-size: {size}px; color: {text}; }}
    QMainWindow, #Page {{ background: {bg}; }}
    QDialog {{ background: {bg}; }}
    #Sidebar {{ background: {dark_side}; }}
    #SidebarLogo {{ color: white; font-size: {size + 4}px; font-weight: 800;
                    padding: 14px 12px 2px 14px; }}
    #SidebarSub {{ color: {_lighten(accent, 1.0)}; font-size: {size - 3}px;
                   padding: 0 14px 12px 14px; letter-spacing: 1px; }}
    #NavButton {{ color: #d7e6f5; background: transparent; border: none; text-align: left;
                  padding: {d['pad_v'] + 2}px 14px; font-size: {size}px;
                  border-left: 3px solid transparent; }}
    #NavButton:hover {{ background: rgba(255,255,255,0.10); color: white; }}
    #NavButton:checked {{ background: rgba(255,255,255,0.14); color: white; font-weight: 600;
                          border-left: 3px solid {accent}; }}
    #NavSection {{ color: {_lighten(muted, 1.05)}; font-size: {size - 3}px; font-weight: 700;
                   padding: 12px 14px 4px 14px; letter-spacing: 1.4px; }}
    #TopBar {{ background: {card}; border-bottom: 1px solid {border}; }}
    #PageTitle {{ font-size: {size + 7}px; font-weight: 700; color: {text}; }}
    #PageSub {{ color: {muted}; font-size: {size - 1}px; }}
    #Card {{ {card_css} }}
    #FormHeader {{ {form_hdr_css} }}
    #FormHeaderTitle {{ color: {t.get("ui_form_header_text", "#ffffff")};
        font-size: {size + 3}px; font-weight: 800; background: transparent; }}
    #FormHeaderSub {{ color: {t.get("ui_form_header_text", "#ffffff")};
        font-size: {size - 2}px; background: transparent; }}
    #FormHeaderBtn {{ background: rgba(255,255,255,0.16);
        color: {t.get("ui_form_header_text", "#ffffff")};
        border: 1px solid rgba(255,255,255,0.35); border-radius: {max(3, rad - 3)}px;
        padding: 4px 12px; font-weight: 600; }}
    #FormHeaderBtn:hover {{ background: rgba(255,255,255,0.30); }}
    #CardTitle {{ font-size: {size}px; font-weight: 700; color: {text}; }}
    #StatValue {{ font-size: {size + 10}px; font-weight: 800; }}
    #StatLabel {{ color: {muted}; font-size: {size - 2}px; font-weight: 600; letter-spacing: .4px; }}
    QPushButton {{ background: {card}; border: 1px solid {border}; border-radius: {max(3, rad - 2)}px;
                   padding: {d['pad_v']}px {d['pad_h']}px; color: {text}; }}
    QPushButton:hover {{ border-color: {primary}; color: {primary}; }}
    QPushButton:disabled {{ color: {muted}; background: {_lighten(card, 0.97)}; }}
    #Primary {{ background: {primary}; color: white; border: none; font-weight: 600;
                padding: {d['pad_v'] + 1}px {d['pad_h'] + 4}px; }}
    #Primary:hover {{ background: {hover_btn}; color: white; }}
    #Accent {{ background: {accent}; color: #3a2a00; border: none; font-weight: 700;
               padding: {d['pad_v'] + 1}px {d['pad_h'] + 4}px; }}
    #Accent:hover {{ background: {_lighten(accent, 1.12)}; }}
    #Danger {{ background: {t['ui_danger']}; color: white; border: none; font-weight: 600; }}
    #Danger:hover {{ background: {_lighten(t['ui_danger'], 1.15)}; }}
    QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
        background: {input_bg}; border: 1px solid {border}; border-radius: {max(3, rad - 2)}px;
        padding: {d['pad_v'] - 1}px 8px; color: {text}; selection-background-color: {primary};
        selection-color: white; }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus {{ border: 2px solid {primary}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {muted}; background: {_lighten(card, 0.96)}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{ background: {card}; border: 1px solid {border}; color: {text};
        selection-background-color: {primary}; selection-color: white; }}
    QTableWidget, QTableView {{ background: {card}; border: 1px solid {border};
        border-radius: {rad}px; gridline-color: {grid}; color: {text};
        alternate-background-color: {alt}; }}
    QTableWidget::item {{ padding: 3px 5px; }}
    QTableWidget::item:selected {{ background: {sel}; color: {text}; }}
    /* the editor that appears while typing inside a table cell -- must stay
       readable on every theme, this is what made numbers "disappear" before */
    QTableWidget QLineEdit, QTableView QLineEdit, QAbstractItemView QLineEdit {{
        background: {input_bg}; color: {text}; border: 2px solid {accent};
        border-radius: 3px; padding: 1px 4px; font-weight: 700;
        selection-background-color: {primary}; selection-color: #ffffff; }}
    QTableWidget QComboBox, QTableView QComboBox {{
        background: {input_bg}; color: {text}; border: 1px solid {primary}; }}
    QHeaderView::section {{ background: {primary}; color: {hdr_text};
        padding: {d['pad_v']}px 6px; border: none;
        border-right: 1px solid rgba(255,255,255,.16); font-weight: 600; font-size: {size - 1}px; }}
    QTabWidget::pane {{ border: 1px solid {border}; border-radius: {rad}px; background: {card};
        top: -1px; }}
    QTabBar::tab {{ background: transparent; padding: {d['pad_v'] + 1}px {d['pad_h'] + 2}px;
        color: {muted}; border-bottom: 2px solid transparent; font-weight: 600; }}
    QTabBar::tab:selected {{ color: {primary}; border-bottom: 2px solid {accent}; }}
    QTabBar::tab:hover {{ color: {text}; }}
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {scroll}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {primary}; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {scroll}; border-radius: 5px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QGroupBox {{ border: 1px solid {border}; border-radius: {rad}px; margin-top: 14px;
        padding-top: 10px; background: {card}; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; color: {primary}; }}
    QStatusBar {{ background: {card}; border-top: 1px solid {border}; color: {muted}; }}
    QMenu {{ background: {card}; border: 1px solid {border}; padding: 4px; color: {text}; }}
    QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {primary}; color: white; }}
    QToolTip {{ background: {dark_side}; color: white; border: none; padding: 5px; }}
    QCheckBox, QRadioButton {{ color: {text}; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}
    QLabel {{ color: {text}; }}
    QSplitter::handle {{ background: {border}; }}
    QProgressBar {{ border: 1px solid {border}; border-radius: 4px; text-align: center;
        background: {card}; color: {text}; }}
    QProgressBar::chunk {{ background: {primary}; border-radius: 3px; }}
    QListWidget {{ background: {card}; border: 1px solid {border}; border-radius: {rad}px;
        color: {text}; }}
    QListWidget::item {{ padding: {d['pad_v']}px 6px; }}
    QListWidget::item:selected {{ background: {primary}; color: white; border-radius: 4px; }}
    #Pill {{ border-radius: 9px; padding: 2px 9px; font-size: {size - 2}px; font-weight: 700;
             color: white; }}
    """
