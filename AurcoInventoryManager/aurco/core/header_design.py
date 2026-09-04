"""Element-based header / footer designer for AURCO PDF documents.

A header (or footer) is a list of *elements*. Each element is fully
independent and controls its own:

    text / source ....... company name, tagline, title, date, page, address,
                          a custom line, or any free text with {placeholders}
    slot ................ Left | Center | Right
    row ................. 0, 1, 2 ... stacked lines inside the band
    font ................ family, size, bold, italic
    colour .............. any hex colour
    visibility .......... on / off per document type

The band itself controls background (solid / gradient / none), height, accent
bar (colour + thickness), bottom border and side padding.

Everything is stored as JSON in the settings table, per document type, with a
"__default__" profile used when a type has no override — so one design can be
shared or each document can look different.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from .database import Database

# --------------------------------------------------------------- elements
SOURCES = {
    "company": "Company name",
    "tagline": "Company tagline",
    "address": "Company address",
    "phone": "Company phone",
    "email": "Company e-mail",
    "vat": "VAT number",
    "cr": "C.R. number",
    "company_ar": "Company name (Arabic)",
    "tagline_ar": "Company tagline (Arabic)",
    "title": "Document title (Delivery Note...)",
    "docno": "Document number",
    "date": "Document date",
    "printdate": "Printed date",
    "printtime": "Printed time",
    "printdatetime": "Printed date + time",
    "page": "Page number",
    "pageof": "Page X of Y",
    "project": "Project / site",
    "warehouse": "Warehouse",
    "user": "Prepared by (user)",
    "custom": "Custom text / placeholders",
}

SLOTS = ["Left", "Center", "Right"]
FONTS = ["Helvetica", "Helvetica-Bold", "Times-Roman", "Courier"]

PLACEHOLDER_HELP = (
    "{company} {tagline} {company_ar} {tagline_ar} {cr_label_ar} {vat_label_ar} "
    "{vat_ar} {cr_ar} "
    "{address} {phone} {email} {vat} {cr} {title} {docno} "
    "{date} {printdate} {printtime} {page} {pages} {project} {warehouse} {user}"
)


def element(source: str = "custom", text: str = "", slot: str = "Left", row: int = 0,
            size: float = 10, bold: bool = False, italic: bool = False,
            color: str = "#ffffff", visible: bool = True) -> dict:
    return {"source": source, "text": text, "slot": slot, "row": row, "size": size,
            "bold": bold, "italic": italic, "color": color, "visible": visible}


# Factory header: logo left, company block left, title + date right.
def default_header() -> dict:
    return {
        "height": 24,
        "bg_style": "Gradient",           # Gradient | Solid | None
        "bg_color1": "#12161c",
        "bg_color2": "#c1121f",
        "bg_angle": "Horizontal",         # Horizontal | Vertical
        "accent_bar": True,
        "accent_color": "#f5a300",
        "accent_height": 1.5,
        "bottom_border": False,
        "border_color": "#c1121f",
        "padding": 12,
        "row_gap": 1.0,
        "logo_show": True,
        "logo_slot": "Left",
        "logo_width": 34,
        "logo_height": 9,
        "logo_backing": "Auto",           # Auto | White | Dark | None
        "elements": [
            element("company", "", "Left", 0, 15, True, False, "#ffffff"),
            element("tagline", "", "Left", 1, 8.5, False, False, "#e6edf3"),
            element("title", "", "Right", 0, 11, True, False, "#ffffff"),
            element("printdatetime", "", "Right", 1, 8, False, False, "#e6edf3"),
        ],
    }


def default_footer() -> dict:
    return {
        "height": 14,
        "bg_style": "None",
        "bg_color1": "#ffffff",
        "bg_color2": "#ffffff",
        "bg_angle": "Horizontal",
        "accent_bar": False,
        "accent_color": "#c1121f",
        "accent_height": 1.0,
        "bottom_border": True,            # in a footer this is the top rule
        "border_color": "#12161c",
        "padding": 12,
        "row_gap": 1.0,
        "logo_show": False,
        "logo_slot": "Left",
        "logo_width": 20,
        "logo_height": 6,
        "logo_backing": "None",
        "elements": [
            element("custom", "{footer_note}", "Left", 0, 7.2, False, False, "#6b7c8f"),
            element("pageof", "", "Right", 0, 7.2, False, False, "#6b7c8f"),
            element("custom", "AURCO Inventory Manager  |  Created by Zain Shami",
                    "Center", 1, 6.8, False, True, "#8a95a1"),
        ],
    }


PRESETS: dict[str, dict] = {}


def _preset(name: str, **over) -> None:
    d = default_header()
    d.update(over)
    PRESETS[name] = d


_preset("AURCO Brand (charcoal → red)")
_preset("Solid Red", bg_style="Solid", bg_color1="#c1121f", bg_color2="#c1121f",
        accent_color="#12161c")
_preset("Corporate Navy", bg_style="Gradient", bg_color1="#0b3d6b",
        bg_color2="#14538f", accent_color="#f5a300")
_preset("Charcoal Minimal", bg_style="Solid", bg_color1="#1d2229",
        bg_color2="#1d2229", accent_bar=False, bottom_border=True,
        border_color="#c1121f")
_preset("White / Letterhead", bg_style="None", bg_color1="#ffffff",
        bg_color2="#ffffff", accent_bar=True, accent_color="#c1121f",
        accent_height=2.0,
        elements=[
            element("company", "", "Left", 0, 16, True, False, "#12161c"),
            element("tagline", "", "Left", 1, 8.5, False, False, "#6b7c8f"),
            element("title", "", "Right", 0, 12, True, False, "#c1121f"),
            element("printdatetime", "", "Right", 1, 8, False, False, "#6b7c8f"),
        ])
_preset("Emerald", bg_style="Gradient", bg_color1="#0a4a36", bg_color2="#0f6b4f",
        accent_color="#f5a300")

# Arabic company details, mirroring the printed stationery.
ARABIC_DEFAULTS = {
    "company_name_ar": "شركة عتيق الرحمن للمقاولات",
    "company_tagline_ar": "الأشغال الميكانيكية والكهربائية",
    "cr_label_ar": "س.ت",
    "vat_label_ar": "الرقم الضريبي",
}


# The company letterhead: red trading name and black registration details on the
# left, AURCO mark in the centre, thin red rule underneath. White background so
# it prints exactly like the printed stationery.
PRESETS["AURCO Letterhead (English + Arabic)"] = {
    "height": 27,
    "bg_style": "None",
    "bg_color1": "#ffffff",
    "bg_color2": "#ffffff",
    "bg_angle": "Horizontal",
    "accent_bar": True,
    "accent_color": "#fc4235",
    "accent_height": 1.2,
    "bottom_border": False,
    "border_color": "#fc4235",
    "padding": 12,
    "row_gap": 0.6,
    "logo_show": True,
    "logo_slot": "Center",
    "logo_width": 40,
    "logo_height": 11,
    "logo_backing": "None",
    "elements": [
        element("custom", "{company}", "Left", 0, 13, True, False, "#fc4235"),
        element("custom", "{tagline}", "Left", 1, 9.5, True, False, "#1a1a1a"),
        element("custom", "C.R. {cr}", "Left", 2, 9.5, True, False, "#1a1a1a"),
        element("custom", "VAT. {vat}", "Left", 3, 9.5, True, False, "#1a1a1a"),
        element("custom", "{company_ar}", "Right", 0, 13, True, False, "#fc4235"),
        element("custom", "{tagline_ar}", "Right", 1, 9.5, True, False, "#1a1a1a"),
        element("custom", "{cr_label_ar} {cr_ar}", "Right", 2, 9.5, True, False, "#1a1a1a"),
        element("custom", "{vat_label_ar} {vat_ar}", "Right", 3, 9.5, True, False, "#1a1a1a"),
    ],
}

PRESETS["AURCO Letterhead"] = {
    "height": 26,
    "bg_style": "None",
    "bg_color1": "#ffffff",
    "bg_color2": "#ffffff",
    "bg_angle": "Horizontal",
    "accent_bar": True,
    "accent_color": "#fc4235",
    "accent_height": 1.2,
    "bottom_border": False,
    "border_color": "#fc4235",
    "padding": 12,
    "row_gap": 0.6,
    "logo_show": True,
    "logo_slot": "Center",
    "logo_width": 42,
    "logo_height": 12,
    "logo_backing": "None",
    "elements": [
        element("custom", "{company}", "Left", 0, 13.5, True, False, "#fc4235"),
        element("custom", "{tagline}", "Left", 1, 10, True, False, "#1a1a1a"),
        element("custom", "C.R. {cr}", "Left", 2, 10, True, False, "#1a1a1a"),
        element("custom", "VAT. {vat}", "Left", 3, 10, True, False, "#1a1a1a"),
    ],
}


# ---------------------------------------------------------------- storage
def _key(kind: str, doc_type: str) -> str:
    return f"{kind}_design_{doc_type}"


def get_design(db: Database, kind: str = "header", doc_type: str = "__default__") -> dict:
    """Design for a document type, falling back to the shared default."""
    base = default_header() if kind == "header" else default_footer()
    for dt in (doc_type, "__default__"):
        raw = db.get_setting(_key(kind, dt))
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            merged = dict(base)
            merged.update({k: v for k, v in data.items() if k != "elements"})
            if isinstance(data.get("elements"), list):
                merged["elements"] = [{**element(), **e} for e in data["elements"]]
            return merged
    return base


def save_design(db: Database, design: dict, kind: str = "header",
                doc_type: str = "__default__") -> None:
    db.set_setting(_key(kind, doc_type), json.dumps(design))
    db.audit("EDITED", f"{kind}-design", doc_type)


def reset_design(db: Database, kind: str = "header",
                 doc_type: str = "__default__") -> None:
    db.set_setting(_key(kind, doc_type), "")


def has_override(db: Database, kind: str, doc_type: str) -> bool:
    return bool(db.get_setting(_key(kind, doc_type)))


def export_design(design: dict) -> str:
    return json.dumps(design, indent=2)


def import_design(text: str) -> dict:
    data = json.loads(text)
    base = default_header()
    base.update({k: v for k, v in data.items() if k != "elements"})
    if isinstance(data.get("elements"), list):
        base["elements"] = [{**element(), **e} for e in data["elements"]]
    return base


# ------------------------------------------------------------- rendering
def context(db: Database, doc_title: str = "", doc: Any = None,
            extra: dict | None = None) -> dict:
    """Values available to header/footer elements and {placeholders}."""
    now = _dt.datetime.now()
    fmt = db.get_setting("date_format", "dd-MM-yyyy")
    py = fmt.replace("dd", "%d").replace("MM", "%m").replace("yyyy", "%Y")

    def g(k, default=""):
        if doc is None:
            return default
        try:
            return doc[k] or default
        except (IndexError, KeyError, TypeError):
            return default

    ctx = {
        "company": db.get_setting("company_name", "AURCO"),
        "tagline": db.get_setting("company_tagline", ""),
        "address": db.get_setting("company_address", ""),
        "phone": db.get_setting("company_phone", ""),
        "email": db.get_setting("company_email", ""),
        "vat": db.get_setting("company_vat", ""),
        "cr": db.get_setting("company_cr", ""),
        "company_ar": db.get_setting("company_name_ar", ""),
        "tagline_ar": db.get_setting("company_tagline_ar", ""),
        "cr_label_ar": db.get_setting("cr_label_ar", "س.ت"),
        "vat_label_ar": db.get_setting("vat_label_ar", "الرقم الضريبي"),
        # Arabic-side numbers: fall back to the English ones when not overridden
        "vat_ar": (db.get_setting("company_vat_ar", "") or "").strip()
                  or db.get_setting("company_vat", ""),
        "cr_ar": (db.get_setting("company_cr_ar", "") or "").strip()
                 or db.get_setting("company_cr", ""),
        "title": doc_title,
        "docno": g("doc_no"),
        "date": g("doc_date"),
        "printdate": now.strftime(py),
        "printtime": now.strftime("%H:%M"),
        "printdatetime": f"{now.strftime(py)}  {now.strftime('%H:%M')}",
        "project": g("project"),
        "warehouse": g("warehouse"),
        "user": g("created_by") or db.current_user,
        "footer_note": db.get_setting("doc_footer", ""),
        "page": "", "pages": "", "pageof": "",
    }
    if extra:
        ctx.update(extra)
    return ctx


def resolve_text(el: dict, ctx: dict) -> str:
    src = el.get("source", "custom")
    if src == "custom":
        raw = el.get("text", "")
    elif src == "pageof":
        raw = "Page {page} of {pages}"
    elif src == "page":
        raw = "Page {page}"
    else:
        raw = "{" + src + "}"
    try:
        return raw.format(**{k: (v if v is not None else "") for k, v in ctx.items()})
    except (KeyError, IndexError, ValueError):
        return raw


def font_name(el: dict) -> str:
    bold, italic = bool(el.get("bold")), bool(el.get("italic"))
    if bold and italic:
        return "Helvetica-BoldOblique"
    if bold:
        return "Helvetica-Bold"
    if italic:
        return "Helvetica-Oblique"
    return "Helvetica"


def rows_used(design: dict) -> int:
    rows = [int(e.get("row", 0)) for e in design.get("elements", [])
            if e.get("visible", True)]
    return (max(rows) + 1) if rows else 1
