"""Arabic (and other RTL) text support for AURCO PDF documents.

reportlab draws glyphs left to right with no shaping, so raw Arabic comes out
disconnected and reversed. This module:

  1. registers a Unicode TrueType font that contains Arabic glyphs,
  2. reshapes the letters into their contextual forms,
  3. applies the bidirectional algorithm so the line reads right to left.

If the optional shaping libraries are missing the text is still drawn with the
Unicode font (readable, just not perfectly joined), so a header never breaks.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from . import config

# Fonts that ship with Windows / Linux and carry Arabic glyphs, best first.
# ---------------------------------------------------------------- styles
# Arabic typeface families bundled with AURCO. "Kufi" is the modern flat-stroke
# style used on the printed company letterhead; Naskh is the classic book hand;
# Amiri is a traditional Naskh with more calligraphic contrast.
FONT_STYLES: dict[str, dict[str, list[str]]] = {
    "Kufi": {
        "regular": ["assets/fonts/NotoKufiArabic-Regular.ttf"],
        "bold": ["assets/fonts/NotoKufiArabic-Bold.ttf"],
    },
    "Naskh": {
        "regular": ["assets/fonts/NotoNaskhArabic-Regular.ttf",
                    r"C:\Windows\Fonts\trado.ttf"],
        "bold": ["assets/fonts/NotoNaskhArabic-Bold.ttf",
                 r"C:\Windows\Fonts\tradbdo.ttf"],
    },
    "Amiri": {
        "regular": ["assets/fonts/Amiri-Regular.ttf"],
        "bold": ["assets/fonts/Amiri-Bold.ttf"],
    },
    "System": {
        "regular": ["assets/fonts/DejaVuSans.ttf",
                    r"C:\Windows\Fonts\arial.ttf",
                    r"C:\Windows\Fonts\tahoma.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
        "bold": ["assets/fonts/DejaVuSans-Bold.ttf",
                 r"C:\Windows\Fonts\arialbd.ttf",
                 r"C:\Windows\Fonts\tahomabd.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    },
}

STYLE_NAMES = list(FONT_STYLES)
DEFAULT_STYLE = "Kufi"          # matches the printed company letterhead
_FALLBACK_ORDER = ["Kufi", "Naskh", "Amiri", "System"]

# ------------------------------------------------------- eastern numerals
_EASTERN = "٠١٢٣٤٥٦٧٨٩"


def to_eastern_digits(text: str) -> str:
    """1234 -> ١٢٣٤  (Arabic-Indic digits, as printed on the letterhead)."""
    return "".join(_EASTERN[int(ch)] if ch.isdigit() else ch
                   for ch in str(text or ""))


def to_western_digits(text: str) -> str:
    out = []
    for ch in str(text or ""):
        i = _EASTERN.find(ch)
        out.append(str(i) if i >= 0 else ch)
    return "".join(out)


FONT_REGULAR = "AurcoArabic"
FONT_BOLD = "AurcoArabic-Bold"

_loaded_style: str | None = None


def _resolve(path: str) -> Path | None:
    p = Path(path)
    if not p.is_absolute():
        p = config.resource_path(path)
    return p if p.exists() else None


def _try_style(style: str) -> bool:
    """Register one typeface family under the standard names."""
    spec = FONT_STYLES.get(style)
    if not spec:
        return False
    got_regular = False
    for kind, name in (("regular", FONT_REGULAR), ("bold", FONT_BOLD)):
        for cand in spec[kind]:
            f = _resolve(cand)
            if not f:
                continue
            try:
                pdfmetrics.registerFont(TTFont(name, str(f)))
                if kind == "regular":
                    got_regular = True
                break
            except Exception:
                continue
    return got_regular


def register_fonts(style: str | None = None, force: bool = False) -> bool:
    """Load an Arabic typeface. Falls back through the other styles."""
    global _loaded_style
    want = style or DEFAULT_STYLE
    if not force and _loaded_style == want:
        return True
    for candidate in [want] + [x for x in _FALLBACK_ORDER if x != want]:
        if _try_style(candidate):
            _loaded_style = candidate
            try:
                names = pdfmetrics.getRegisteredFontNames()
                pdfmetrics.registerFontFamily(
                    FONT_REGULAR, normal=FONT_REGULAR,
                    bold=FONT_BOLD if FONT_BOLD in names else FONT_REGULAR,
                    italic=FONT_REGULAR, boldItalic=FONT_REGULAR)
            except Exception:
                pass
            return True
    _loaded_style = None
    return False


def loaded_style() -> str | None:
    return _loaded_style


# Arabic display fonts often omit Latin punctuation (Noto Kufi has no ".").
# Swap those characters for Arabic equivalents so nothing is silently dropped.
_GLYPH_SWAP = {
    ".": "\u066b",   # Arabic decimal separator, renders as a small dot
    ",": "\u060c",   # Arabic comma
    ";": "\u061b",   # Arabic semicolon
    "?": "\u061f",   # Arabic question mark
    "%": "\u066a",   # Arabic percent
}

_cmap_cache: dict[str, set] = {}


def _font_cmap(font_name: str) -> set:
    """Characters the registered font can actually draw."""
    if font_name in _cmap_cache:
        return _cmap_cache[font_name]
    chars: set = set()
    try:
        face = pdfmetrics.getFont(font_name).face
        for code in getattr(face, "charWidths", {}) or {}:
            chars.add(code)
        if not chars:
            ttf = getattr(face, "_ttf_info", None) or getattr(face, "charToGlyph", None)
            if isinstance(ttf, dict):
                chars = set(ttf)
    except Exception:
        pass
    _cmap_cache[font_name] = chars
    return chars


def fix_missing_glyphs(text: str, font_name: str) -> str:
    """Replace characters the Arabic face cannot draw with equivalents."""
    cmap = _font_cmap(font_name)
    if not cmap:
        # cannot introspect -> apply the known-safe swaps for display faces
        if _loaded_style in ("Kufi",):
            for a, b in _GLYPH_SWAP.items():
                text = text.replace(a, b)
        return text
    out = []
    for ch in text:
        if ord(ch) in cmap or ch in (" ", "\n"):
            out.append(ch)
        else:
            out.append(_GLYPH_SWAP.get(ch, ch))
    return "".join(out)


def configure(db) -> str:
    """Apply the Arabic style saved in Settings. Returns the style in use."""
    try:
        want = db.get_setting("arabic_font_style", DEFAULT_STYLE) or DEFAULT_STYLE
    except Exception:
        want = DEFAULT_STYLE
    register_fonts(want, force=(want != _loaded_style))
    return _loaded_style or "System"


def has_unicode_font() -> bool:
    return register_fonts(_loaded_style)


def is_rtl(text: str) -> bool:
    """True when the string contains Arabic / Hebrew characters."""
    for ch in str(text or ""):
        o = ord(ch)
        if 0x0590 <= o <= 0x08FF or 0xFB1D <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
            return True
    return False


def shape(text: str, eastern_digits: bool = False) -> str:
    """Reshape + reorder Arabic so reportlab draws it correctly."""
    s = str(text or "")
    if not s or not is_rtl(s):
        return s
    if eastern_digits:
        s = to_eastern_digits(s)
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(s))
    except Exception:
        # graceful fallback: at least reverse the run so it reads right to left
        try:
            from bidi.algorithm import get_display
            return get_display(s)
        except Exception:
            return s


def font_for(text: str, bold: bool = False, default: str = "Helvetica") -> str:
    """Font name to use for a string: the Unicode face only when needed."""
    if not is_rtl(text):
        return default
    if not register_fonts(_loaded_style):
        return default
    names = pdfmetrics.getRegisteredFontNames()
    if bold and FONT_BOLD in names:
        return FONT_BOLD
    return FONT_REGULAR if FONT_REGULAR in names else default


def prepare(text: str, bold: bool = False, default_font: str = "Helvetica",
            eastern_digits: bool = False) -> tuple[str, str]:
    """Return (drawable_text, font_name) ready for canvas.drawString()."""
    s = str(text or "")
    if not is_rtl(s):
        return s, default_font
    fname = font_for(s, bold, default_font)
    return fix_missing_glyphs(shape(s, eastern_digits), fname), fname


def para(text: str, bold: bool = False) -> str:
    """Shaped text wrapped for a reportlab Paragraph (adds the font face)."""
    s = str(text or "")
    if not is_rtl(s):
        return s
    shaped = shape(s)
    fname = font_for(s, bold)
    return f'<font name="{fname}">{shaped}</font>'
