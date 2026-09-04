"""Advanced barcode / label engine.

Adds on top of the old three-column Code128 sheet:

  ·  symbologies      Code128, Code39, EAN-13, EAN-8, QR, Data Matrix-style QR
  ·  label templates  Avery-style sheets and roll labels, or a custom size
  ·  custom caption   the "barcode name" the user asked for: any combination of
                      item fields and free text through {placeholders}
  ·  appearance       font, size, bold, alignment, borders, corner radius,
                      bar height/width, human-readable text on/off, logo,
                      price line, colour, rotation
  ·  presets          named designs stored in settings, so a layout can be
                      reused and shared between machines

Everything is driven by one `LabelDesign` dict so the UI can simply edit keys.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

from . import config
from .database import Database

# --------------------------------------------------------------- symbologies
SYMBOLOGIES = ["Code128", "Code39", "EAN-13", "EAN-8", "QR Code", "QR + Code128"]

# ------------------------------------------------------------------ templates
# width/height in mm, columns x rows, page margins and gaps
TEMPLATES: dict[str, dict] = {
    "A4 · 3 × 8  (63.5 × 33.9 mm)": dict(cols=3, rows=8, w=63.5, h=33.9,
                                         mx=7.0, my=13.0, gx=2.5, gy=0.0),
    "A4 · 2 × 7  (99.1 × 38.1 mm)": dict(cols=2, rows=7, w=99.1, h=38.1,
                                         mx=4.6, my=15.1, gx=2.5, gy=0.0),
    "A4 · 4 × 10 (48.5 × 25.4 mm)": dict(cols=4, rows=10, w=48.5, h=25.4,
                                         mx=8.0, my=21.5, gx=2.0, gy=0.0),
    "A4 · 5 × 13 (38.1 × 21.2 mm)": dict(cols=5, rows=13, w=38.1, h=21.2,
                                         mx=5.0, my=10.7, gx=2.5, gy=0.0),
    "A4 · 2 × 4  (99.1 × 67.7 mm)": dict(cols=2, rows=4, w=99.1, h=67.7,
                                         mx=4.6, my=13.0, gx=2.5, gy=0.0),
    "Shelf tag · 3 × 6 (63.5 × 46 mm)": dict(cols=3, rows=6, w=63.5, h=46.0,
                                             mx=7.0, my=8.0, gx=2.5, gy=0.0),
    "Custom size": dict(cols=3, rows=8, w=63.5, h=33.9, mx=7.0, my=13.0, gx=2.5, gy=0.0),
}

FONTS = ["Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Bold", "Courier",
         "Courier-Bold"]

# Fields a caption line may reference.
PLACEHOLDERS = ["code", "description", "short_desc", "category", "subcategory", "uom",
                "brand", "model", "specification", "barcode", "alt_code", "warehouse",
                "location", "rack", "balance", "unit_cost", "min_level", "max_level",
                "company", "date", "currency"]

DEFAULT_DESIGN: dict[str, Any] = {
    "name": "Default",
    "template": "A4 · 3 × 8  (63.5 × 33.9 mm)",
    "label_w": 63.5, "label_h": 33.9, "cols": 3, "rows": 8,
    "margin_x": 7.0, "margin_y": 13.0, "gap_x": 2.5, "gap_y": 0.0,
    "symbology": "Code128",
    # what is *encoded*
    "value_field": "barcode_or_code",     # barcode_or_code | code | barcode | alt_code | custom
    "value_custom": "{code}",
    # the printed "barcode name" — this is the feature the user asked for
    "title": "{code}",
    "title_font": "Helvetica-Bold", "title_size": 8.0, "title_align": "center",
    "subtitle": "{description}",
    "subtitle_font": "Helvetica", "subtitle_size": 6.4, "subtitle_align": "center",
    "footer": "{warehouse} · {location}",
    "footer_font": "Helvetica", "footer_size": 5.6, "footer_align": "center",
    "show_title": True, "show_subtitle": True, "show_footer": True,
    "show_price": False, "price_prefix": "",
    "human_readable": True,
    "bar_height": 11.0, "bar_width": 0.36, "quiet_zone": 1.5,
    "bar_color": "#000000", "text_color": "#101418", "bg_color": "#ffffff",
    "accent_color": "",                    # blank = theme primary
    "border": True, "border_width": 0.5, "border_color": "#9aa8b6",
    "corner_radius": 1.6,
    "accent_bar": True,                    # thin brand stripe at the top
    "show_logo": False, "logo_height": 5.0,
    "qr_size": 15.0,
    "rotate": 0,                           # 0 | 90
    "copies": 1,
    "start_position": 1,                   # skip already-used labels on a part sheet
    "crop_marks": False,
}

PRESET_KEY = "barcode_presets"
CURRENT_KEY = "barcode_design"


# ------------------------------------------------------------------ storage
def get_design(db: Database) -> dict:
    d = dict(DEFAULT_DESIGN)
    raw = db.get_setting(CURRENT_KEY, "")
    if raw:
        try:
            d.update(json.loads(raw))
        except Exception:
            pass
    return d


def save_design(db: Database, design: dict) -> None:
    db.set_setting(CURRENT_KEY, json.dumps(design))


def list_presets(db: Database) -> dict[str, dict]:
    raw = db.get_setting(PRESET_KEY, "")
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def save_preset(db: Database, name: str, design: dict) -> None:
    p = list_presets(db)
    p[name] = dict(design, name=name)
    db.set_setting(PRESET_KEY, json.dumps(p))
    db.audit("SAVED", "barcode-preset", name)


def delete_preset(db: Database, name: str) -> None:
    p = list_presets(db)
    p.pop(name, None)
    db.set_setting(PRESET_KEY, json.dumps(p))


def apply_template(design: dict, template: str) -> dict:
    t = TEMPLATES.get(template)
    if not t or template == "Custom size":
        design["template"] = template
        return design
    design.update({"template": template, "cols": t["cols"], "rows": t["rows"],
                   "label_w": t["w"], "label_h": t["h"], "margin_x": t["mx"],
                   "margin_y": t["my"], "gap_x": t["gx"], "gap_y": t["gy"]})
    return design


# --------------------------------------------------------------- text engine
def _fmt(template: str, item: dict, db: Database) -> str:
    """Resolve {placeholders} against an item row. Unknown keys stay literal."""
    if not template:
        return ""
    ctx = {k: "" for k in PLACEHOLDERS}
    for k in PLACEHOLDERS:
        if k in item and item.get(k) is not None:
            ctx[k] = item.get(k)
    ctx["company"] = db.get_setting("company_name", "")
    ctx["currency"] = db.get_setting("currency", "")
    ctx["date"] = _dt.date.today().strftime("%d-%m-%Y")
    for k in ("balance", "unit_cost", "min_level", "max_level"):
        v = ctx.get(k)
        if isinstance(v, (int, float)):
            ctx[k] = f"{v:g}"

    def repl(m):
        key = m.group(1).strip()
        return str(ctx.get(key, m.group(0)))

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", repl, str(template)).strip()


def caption_preview(db: Database, design: dict, item: dict) -> dict[str, str]:
    """What the three text lines will say for this item — used by the live preview."""
    return {"title": _fmt(design.get("title", ""), item, db),
            "subtitle": _fmt(design.get("subtitle", ""), item, db),
            "footer": _fmt(design.get("footer", ""), item, db),
            "value": encoded_value(design, item)}


def encoded_value(design: dict, item: dict) -> str:
    mode = design.get("value_field", "barcode_or_code")
    if mode == "custom":
        raw = design.get("value_custom", "{code}")
        return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}",
                      lambda m: str(item.get(m.group(1), "")), raw).strip()
    if mode == "barcode_or_code":
        return str(item.get("barcode") or item.get("code") or "")
    return str(item.get(mode) or item.get("code") or "")


def _ean_ok(value: str, digits: int) -> bool:
    return value.isdigit() and len(value) in (digits - 1, digits)


# ------------------------------------------------------------------ drawing
def _hex(c: str, fallback: str = "#000000"):
    try:
        return colors.HexColor(c or fallback)
    except Exception:
        return colors.HexColor(fallback)


def _text(c, x: float, y: float, w: float, txt: str, font: str, size: float,
          align: str, colour) -> None:
    if not txt:
        return
    c.setFont(font, size)
    c.setFillColor(colour)
    # shrink to fit rather than overflowing the label
    while size > 3.6 and c.stringWidth(txt, font, size) > w:
        size -= 0.2
        c.setFont(font, size)
    if c.stringWidth(txt, font, size) > w:            # still too long -> ellipsis
        while txt and c.stringWidth(txt + "…", font, size) > w:
            txt = txt[:-1]
        txt += "…"
    tw = c.stringWidth(txt, font, size)
    if align == "center":
        c.drawString(x + (w - tw) / 2, y, txt)
    elif align == "right":
        c.drawString(x + w - tw, y, txt)
    else:
        c.drawString(x, y, txt)


def _draw_symbol(c, design: dict, value: str, x: float, y: float, w: float,
                 h: float) -> float:
    """Draw the chosen symbology inside the box. Returns the height used.

    ReportLab's own `humanReadable` flag draws a fixed 12pt caption *inside* the
    bar area without growing `bc.height`, which overprints the bars and any text
    below them. We therefore always switch it off and draw the caption ourselves
    at a size that suits the label.
    """
    sym = design.get("symbology", "Code128")
    bar_col = _hex(design.get("bar_color", "#000000"))
    hr = bool(design.get("human_readable", True))
    hr_size = max(4.5, min(9.0, float(design.get("bar_height", 11)) * 0.62))
    hr_gap = (hr_size * 1.15) if hr else 0.0
    # the bars themselves get whatever is left after the caption
    h = max(3 * mm, h - hr_gap)
    y = y + hr_gap

    def _caption(text: str, cx: float, cw: float) -> None:
        if not hr or not text:
            return
        c.setFont("Helvetica", hr_size)
        c.setFillColor(_hex(design.get("text_color", "#101418")))
        tw = c.stringWidth(text, "Helvetica", hr_size)
        c.drawString(cx + (cw - tw) / 2, y - hr_gap + hr_size * 0.15, text)
    try:
        if sym.startswith("QR"):
            from reportlab.graphics.barcode import qr
            from reportlab.graphics.shapes import Drawing
            from reportlab.graphics import renderPDF
            # QrCodeWidget re-sizes itself once barWidth/barHeight are set, so the
            # drawing needs no extra scaling -- applying one shrinks the code.
            size = min(float(design.get("qr_size", 15)) * mm, h, w)
            code = qr.QrCodeWidget(value or " ")
            code.barWidth = size
            code.barHeight = size
            d2 = Drawing(size, size)
            d2.add(code)
            if sym == "QR + Code128":
                renderPDF.draw(d2, c, x, y + (h - size) / 2)
                from reportlab.graphics.barcode import code128
                rest_x = x + size + 2 * mm
                rest_w = max(6 * mm, w - size - 2 * mm)
                bc = code128.Code128(value or " ",
                                     barHeight=min(h * 0.7, float(design.get("bar_height", 11)) * mm),
                                     barWidth=float(design.get("bar_width", 0.36)) * mm,
                                     humanReadable=False, quiet=False)
                sc = min(1.0, rest_w / max(bc.width, 1e-6))
                c.saveState()
                c.translate(rest_x, y + (h - bc.height * sc) / 2)
                c.scale(sc, sc)
                c.setFillColor(bar_col)
                bc.drawOn(c, 0, 0)
                c.restoreState()
                _caption(value, rest_x, rest_w)
            else:
                renderPDF.draw(d2, c, x + (w - size) / 2, y + (h - size) / 2)
                _caption(value, x, w)
            return h + hr_gap
        if sym == "Code39":
            from reportlab.graphics.barcode import code39
            bc = code39.Extended39(value or " ",
                                   barHeight=float(design.get("bar_height", 11)) * mm,
                                   barWidth=float(design.get("bar_width", 0.36)) * mm,
                                   humanReadable=False, quiet=False)
        elif sym in ("EAN-13", "EAN-8"):
            from reportlab.graphics.barcode import eanbc
            digits = 13 if sym == "EAN-13" else 8
            v = re.sub(r"\D", "", value)[:digits].ljust(digits - 1, "0")
            cls = eanbc.Ean13BarcodeWidget if digits == 13 else eanbc.Ean8BarcodeWidget
            from reportlab.graphics.shapes import Drawing, Group
            from reportlab.graphics import renderPDF
            wid = cls(v, humanReadable=hr,
                      barHeight=float(design.get("bar_height", 11)) * mm
                      + (hr_gap if hr else 0))
            b = wid.getBounds()
            bw, bh = b[2] - b[0], b[3] - b[1]
            sc = min(w / max(bw, 1e-6), h / max(bh, 1e-6), 1.6)
            g = Group(wid)
            g.scale(sc, sc)
            d = Drawing(bw * sc, bh * sc)
            d.add(g)
            renderPDF.draw(d, c, x + (w - bw * sc) / 2, y - hr_gap)
            return bh * sc
        else:
            from reportlab.graphics.barcode import code128
            bc = code128.Code128(value or " ",
                                 barHeight=float(design.get("bar_height", 11)) * mm,
                                 barWidth=float(design.get("bar_width", 0.36)) * mm,
                                 humanReadable=False, quiet=False)
    except Exception:
        c.setFont("Helvetica", 6)
        c.setFillColor(colors.red)
        c.drawCentredString(x + w / 2, y + h / 2, "invalid barcode value")
        return h
    sc = min(1.0, w / max(bc.width, 1e-6))
    c.saveState()
    c.translate(x + (w - bc.width * sc) / 2, y)
    c.scale(sc, sc)
    c.setFillColor(bar_col)
    c.setStrokeColor(bar_col)
    bc.drawOn(c, 0, 0)
    c.restoreState()
    _caption(value, x, w)
    return bc.height * sc + hr_gap


def draw_label(c, db: Database, design: dict, item: dict, x: float, y: float,
               w: float, h: float) -> None:
    """Paint one complete label with its origin at the bottom-left corner."""
    pad = 1.6 * mm
    accent = design.get("accent_color") or db.get_setting("ui_primary", "#0b3d6b")
    txt_col = _hex(design.get("text_color", "#101418"))

    if design.get("bg_color") and design["bg_color"].lower() not in ("#ffffff", "white"):
        c.setFillColor(_hex(design["bg_color"], "#ffffff"))
        c.roundRect(x, y, w, h, float(design.get("corner_radius", 1.6)) * mm,
                    stroke=0, fill=1)
    if design.get("border", True):
        c.setStrokeColor(_hex(design.get("border_color", "#9aa8b6")))
        c.setLineWidth(float(design.get("border_width", 0.5)))
        c.roundRect(x, y, w, h, float(design.get("corner_radius", 1.6)) * mm,
                    stroke=1, fill=0)
    if design.get("accent_bar", True):
        c.setFillColor(_hex(accent, "#0b3d6b"))
        c.rect(x, y + h - 1.2 * mm, w, 1.2 * mm, stroke=0, fill=1)

    inner_x = x + pad
    inner_w = w - 2 * pad
    cur_y = y + h - (2.4 * mm if design.get("accent_bar", True) else pad)

    # optional company logo strip
    if design.get("show_logo"):
        logo = db.get_setting("logo_path", "")
        lh = float(design.get("logo_height", 5)) * mm
        if logo and Path(logo).exists():
            try:
                from reportlab.lib.utils import ImageReader
                img = ImageReader(logo)
                iw, ih = img.getSize()
                lw = min(inner_w, lh * iw / max(ih, 1))
                c.drawImage(img, inner_x + (inner_w - lw) / 2, cur_y - lh, width=lw,
                            height=lh, mask="auto", preserveAspectRatio=True)
                cur_y -= lh + 0.8 * mm
            except Exception:
                pass

    if design.get("show_title", True):
        t = _fmt(design.get("title", ""), item, db)
        if t:
            size = float(design.get("title_size", 8))
            cur_y -= size * 1.05
            _text(c, inner_x, cur_y, inner_w, t, design.get("title_font", "Helvetica-Bold"),
                  size, design.get("title_align", "center"), txt_col)
            cur_y -= 0.6 * mm
    if design.get("show_subtitle", True):
        t = _fmt(design.get("subtitle", ""), item, db)
        if t:
            size = float(design.get("subtitle_size", 6.4))
            cur_y -= size * 1.05
            _text(c, inner_x, cur_y, inner_w, t, design.get("subtitle_font", "Helvetica"),
                  size, design.get("subtitle_align", "center"),
                  _hex("#5a6b7c"))
            cur_y -= 0.5 * mm

    bottom = y + pad
    if design.get("show_footer", True) and _fmt(design.get("footer", ""), item, db):
        bottom += float(design.get("footer_size", 5.6)) * 1.25
    if design.get("show_price"):
        bottom += 7.2

    box_h = max(4 * mm, cur_y - bottom)
    used = _draw_symbol(c, design, encoded_value(design, item), inner_x, bottom,
                        inner_w, box_h)

    if design.get("show_price"):
        cur = db.get_setting("currency", "")
        price = item.get("unit_cost") or 0
        label = f"{design.get('price_prefix','')}{cur} {float(price):,.2f}".strip()
        _text(c, inner_x, y + pad + (float(design.get("footer_size", 5.6)) * 1.25
                                     if design.get("show_footer", True) else 0),
              inner_w, label, "Helvetica-Bold", 7.4, design.get("footer_align", "center"),
              _hex(accent, "#0b3d6b"))
    if design.get("show_footer", True):
        t = _fmt(design.get("footer", ""), item, db)
        if t:
            _text(c, inner_x, y + pad, inner_w, t, design.get("footer_font", "Helvetica"),
                  float(design.get("footer_size", 5.6)),
                  design.get("footer_align", "center"), _hex("#6b7c8f"))


# ------------------------------------------------------------------- sheets
def label_pdf(db: Database, items: Sequence[dict], design: dict | None = None,
              out_path: str | Path | None = None) -> Path:
    """Render a full label sheet using the supplied design."""
    design = dict(DEFAULT_DESIGN, **(design or get_design(db)))
    out = Path(out_path) if out_path else (
        config.folder("Reports") /
        f"Labels_{_dt.datetime.now():%Y%m%d_%H%M%S}.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    lw = float(design.get("label_w", 63.5)) * mm
    lh = float(design.get("label_h", 33.9)) * mm
    cols = max(1, int(design.get("cols", 3)))
    rows = max(1, int(design.get("rows", 8)))
    mx = float(design.get("margin_x", 7)) * mm
    my = float(design.get("margin_y", 13)) * mm
    gx = float(design.get("gap_x", 2.5)) * mm
    gy = float(design.get("gap_y", 0)) * mm

    page = landscape(A4) if int(design.get("rotate", 0)) == 90 else A4
    c = rl_canvas.Canvas(str(out), pagesize=page)
    c.setTitle("AURCO Item Labels")
    c.setAuthor(f"AURCO / {config.CREATED_BY}")
    page_w, page_h = page

    copies = max(1, int(design.get("copies", 1)))
    queue: list[dict] = []
    for it in items:
        n = int(it.get("_copies") or copies)
        queue += [dict(it)] * max(1, n)

    per_page = cols * rows
    slot = max(0, int(design.get("start_position", 1)) - 1) % per_page
    printed = 0
    for rec in queue:
        if slot == 0 and printed:
            c.showPage()
        r, col = divmod(slot, cols)
        x = mx + col * (lw + gx)
        y = page_h - my - (r + 1) * lh - r * gy
        if x + lw > page_w + 0.5 or y < -0.5:
            # design does not fit the page — fall back to a safe grid
            x = min(x, page_w - lw - 2 * mm)
            y = max(y, 2 * mm)
        draw_label(c, db, design, rec, x, y, lw, lh)
        if design.get("crop_marks"):
            c.setStrokeColor(colors.HexColor("#c9d6e2"))
            c.setLineWidth(0.2)
            c.line(x, y - 1.2 * mm, x, y - 2.6 * mm)
            c.line(x + lw, y - 1.2 * mm, x + lw, y - 2.6 * mm)
        printed += 1
        slot = (slot + 1) % per_page
    c.showPage()
    c.save()
    db.audit("PRINTED", "barcodes", design.get("name", ""),
             f"{printed} label(s) · {design.get('symbology')} · {design.get('template')}")
    return out


def preview_png(db: Database, design: dict, item: dict, out_path: str | Path,
                scale: float = 4.0) -> Path:
    """Render a single label to PNG for the live preview in the UI."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lw = float(design.get("label_w", 63.5)) * mm
    lh = float(design.get("label_h", 33.9)) * mm
    tmp = out.with_suffix(".pdf")
    c = rl_canvas.Canvas(str(tmp), pagesize=(lw, lh))
    draw_label(c, db, design, item, 0, 0, lw, lh)
    c.showPage()
    c.save()
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(tmp))
        page = pdf[0]
        page.render(scale=scale).to_pil().save(out)
        pdf.close()
    except Exception:
        return tmp
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return out
