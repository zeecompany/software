#!/usr/bin/env python3
"""
Sterling Signal — YouTube channel brand kit generator.

Produces (all in brand/output/):
  logo_800.png            800x800 profile picture (circle-safe, dark)
  logo_800_light.png      light-background variant
  logo_mark_1024.png      transparent mark only (for overlays, socials)
  watermark_150.png       150x150 branding watermark (semi-transparent, white)
  banner_2560x1440.jpg    channel banner, all key content inside 1235x338 safe area
  banner_preview_*.jpg    how the banner crops on mobile / desktop / TV
  wordmark_dark.png       horizontal wordmark on transparent bg
  logo_800_preview.png    circle-crop preview (what viewers actually see)

Brand: "£" glyph fused with a heartbeat / signal pulse — the pound's vital signs.
Palette: Signal Yellow #FFD600 · Ink #0B0F19 · Alert Red #E21E28 · White.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).parent
FONTS = ROOT.parent / "assets" / "fonts"
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

YELLOW = (255, 214, 0)
INK = (11, 15, 25)
INK2 = (18, 24, 38)
RED = (226, 30, 40)
WHITE = (255, 255, 255)
GREY = (168, 174, 186)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


# ---------------------------------------------------------------------------
# Logo mark: £ + signal pulse.  Drawn at 4x and downsampled for clean AA.
# ---------------------------------------------------------------------------
def pulse_points(x0: float, x1: float, y: float, amp: float) -> list[tuple[float, float]]:
    """Heartbeat/signal line: flat – small bump – big spike – dip – flat."""
    w = x1 - x0
    pts = [
        (x0, y),
        (x0 + 0.22 * w, y),
        (x0 + 0.28 * w, y - 0.25 * amp),
        (x0 + 0.34 * w, y),
        (x0 + 0.42 * w, y),
        (x0 + 0.50 * w, y - 1.00 * amp),
        (x0 + 0.58 * w, y + 0.45 * amp),
        (x0 + 0.65 * w, y),
        (x0 + 0.78 * w, y),
        (x1, y),
    ]
    return pts


def draw_mark(size: int, fg=YELLOW, pulse_col=WHITE, bg=None, ring=True) -> Image.Image:
    """Return an RGBA image of the mark at `size` px (square)."""
    S = size * 4  # supersample
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if bg is not None:
        d.ellipse((0, 0, S - 1, S - 1), fill=bg)
        # subtle radial highlight
        glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((S * 0.15, S * 0.05, S * 0.85, S * 0.6), fill=(255, 255, 255, 18))
        glow = glow.filter(ImageFilter.GaussianBlur(S * 0.08))
        img.alpha_composite(glow)
        d = ImageDraw.Draw(img)

    if ring and bg is not None:
        d.ellipse((S * 0.035, S * 0.035, S * 0.965, S * 0.965), outline=fg, width=int(S * 0.028))

    # "£" glyph — Roboto Black, large, slightly left of centre to balance pulse
    f = font("Roboto-Black.ttf", int(S * 0.62))
    l, t, r, b = d.textbbox((0, 0), "£", font=f)
    gw, gh = r - l, b - t
    gx = S * 0.47 - gw / 2 - l
    gy = S * 0.50 - gh / 2 - t
    d.text((gx, gy), "£", font=f, fill=fg)

    # Pulse line: runs through the £'s crossbar region, from left to right
    y = S * 0.545
    x0, x1 = S * 0.14, S * 0.86
    amp = S * 0.16
    pts = pulse_points(x0, x1, y, amp)
    lw = int(S * 0.045)
    # dark "knockout" stroke first so the pulse reads over the £
    d.line(pts, fill=(bg or INK) if bg is not None else INK, width=lw + int(S * 0.03), joint="curve")
    d.line(pts, fill=pulse_col, width=lw, joint="curve")
    # round the endpoints + spike tip
    for (px, py) in (pts[0], pts[-1]):
        d.ellipse((px - lw / 2, py - lw / 2, px + lw / 2, py + lw / 2), fill=pulse_col)
    # red dot at the end of the signal = "live"
    ex, ey = pts[-1]
    rr = int(S * 0.045)
    d.ellipse((ex - rr, ey - rr, ex + rr, ey + rr), fill=RED)

    return img.resize((size, size), Image.LANCZOS)


def make_logo():
    # dark profile picture (800x800) — mark on ink disc, everything inside circle
    logo = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
    mark = draw_mark(800, bg=INK)
    logo.alpha_composite(mark)
    logo.convert("RGB").save(OUT / "logo_800.png")

    # light variant
    light = Image.new("RGBA", (800, 800), WHITE)
    light.alpha_composite(draw_mark(800, fg=INK, pulse_col=YELLOW, bg=WHITE))
    light.convert("RGB").save(OUT / "logo_800_light.png")

    # transparent mark only (no disc, no ring)
    draw_mark(1024, bg=None, ring=False).save(OUT / "logo_mark_1024.png")

    # circle-crop preview (what YouTube shows) on a grey page
    prev = Image.new("RGB", (1000, 1000), (30, 30, 34))
    m = Image.new("L", (800, 800), 0)
    ImageDraw.Draw(m).ellipse((0, 0, 799, 799), fill=255)
    prev.paste(logo.convert("RGB"), (100, 100), m)
    prev.save(OUT / "logo_800_preview.png")

    # watermark 150x150: white mark, ~70% opacity, transparent background
    wm = draw_mark(150, fg=WHITE, pulse_col=WHITE, bg=None, ring=False)
    a = wm.split()[3].point(lambda v: int(v * 0.72))
    wm.putalpha(a)
    wm.save(OUT / "watermark_150.png")
    print("logo files written")


# ---------------------------------------------------------------------------
# Wordmark
# ---------------------------------------------------------------------------
def make_wordmark():
    f1 = font("Roboto-Black.ttf", 150)
    f2 = font("Roboto-Medium.ttf", 44)
    W, H = 1700, 330
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    mark = draw_mark(260, bg=INK)
    img.alpha_composite(mark, (20, 35))
    d.text((320, 20), "STERLING", font=f1, fill=WHITE)
    d.text((320, 150), "SIGNAL", font=f1, fill=YELLOW)
    sw = d.textlength("SIGNAL  ", font=f1)
    d.text((320 + sw, 285), "UK MONEY NEWS, DECODED", font=f2, fill=GREY, anchor="ls")
    img.save(OUT / "wordmark_dark.png")
    print("wordmark written")


# ---------------------------------------------------------------------------
# Banner 2560x1440 with 1235x338 safe area centred
# ---------------------------------------------------------------------------
def make_banner():
    W, H = 2560, 1440
    SW, SH = 1235, 338
    sx, sy = (W - SW) // 2, (H - SH) // 2  # 662, 551

    # background: cinematic city image, darkened, with a yellow signal line across
    bg = Image.open(ROOT.parent / "assets/images/bg_city.jpg").convert("RGB")
    bg = bg.resize((W, int(W * bg.height / bg.width)), Image.LANCZOS)
    # centre-crop to H
    top = (bg.height - H) // 2
    bg = bg.crop((0, top, W, top + H))
    bg = bg.filter(ImageFilter.GaussianBlur(2))
    dark = Image.new("RGBA", (W, H), (11, 15, 25, 170))
    bg = Image.alpha_composite(bg.convert("RGBA"), dark)
    # vignette: darker band through the safe area so text pops on every crop
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for i in range(260):
        a = int(140 * (1 - abs(i - 130) / 130) ** 0.8)
        bd.line([(0, sy - 91 + i * 2), (W, sy - 91 + i * 2)], fill=(5, 8, 16, a), width=2)
    bg = Image.alpha_composite(bg, band)

    d = ImageDraw.Draw(bg)

    # long faint pulse across the full width: flat under the safe-area text,
    # with its spikes pushed out to the far left/right (TV/desktop crops only)
    yline = sy + SH - 26
    left = pulse_points(0, sx - 40, yline, 150)
    right = pulse_points(sx + SW + 40, W, yline, 150)
    d.line(left + right, fill=(255, 214, 0, 70), width=10, joint="curve")

    # ---- safe-area content (everything important lives inside 1235x338) ----
    mark = draw_mark(290, bg=INK)
    bg.alpha_composite(mark, (sx + 6, sy + (SH - 290) // 2))

    d = ImageDraw.Draw(bg)
    tx = sx + 330
    f_word = font("Roboto-Black.ttf", 100)
    d.text((tx, sy + 16), "STERLING", font=f_word, fill=WHITE, stroke_width=4, stroke_fill=INK)
    stw = d.textlength("STERLING ", font=f_word)
    d.text((tx + stw, sy + 16), "SIGNAL", font=f_word, fill=YELLOW, stroke_width=4, stroke_fill=INK)
    # yellow rule under the wordmark
    d.rectangle((tx + 6, sy + 150, tx + 6 + 560, sy + 156), fill=YELLOW)
    d.text((tx + 4, sy + 176), "UK MONEY NEWS, DECODED", font=font("Roboto-Bold.ttf", 46), fill=WHITE,
           stroke_width=3, stroke_fill=INK)
    d.text((tx + 4, sy + 244), "Mortgages  ·  Interest rates  ·  Tax  ·  The Budget   |   New video every week",
           font=font("Roboto-Medium.ttf", 30), fill=GREY, stroke_width=2, stroke_fill=INK)
    # sanity: the right edge of the longest text stays inside the safe area
    assert tx + d.textlength("STERLING SIGNAL", font=f_word) < sx + SW - 20, "wordmark overflows safe area"

    # ---- outside safe area (desktop/TV only): ticker strip of numbers ----
    ticker = "30-YR GILT 5.89%   ·   5-YR SWAP 4.52%   ·   AVG 5-YR FIX 5.63%   ·   CPI 2.9%   ·   BASE RATE 3.75%   ·   BUDGET 28 OCT   ·   "
    tf = font("Roboto-Bold.ttf", 34)
    tw = d.textlength(ticker, font=tf)
    y_t = sy + SH - 2  # just under the safe area, fully inside the 423px desktop strip
    d.rectangle((0, y_t - 10, W, y_t + 50), fill=(0, 0, 0, 120))
    x = -200
    while x < W:
        d.text((x, y_t), ticker, font=tf, fill=(255, 214, 0, 210))
        x += tw

    final = bg.convert("RGB")
    final.save(OUT / "banner_2560x1440.jpg", quality=92, optimize=True)

    # crop previews
    crops = {
        "tv_2560x1440": (0, 0, W, H),
        "desktop_2560x423": (0, (H - 423) // 2, W, (H - 423) // 2 + 423),
        "tablet_1855x423": ((W - 1855) // 2, (H - 423) // 2, (W - 1855) // 2 + 1855, (H - 423) // 2 + 423),
        "mobile_1546x423": ((W - 1546) // 2, (H - 423) // 2, (W - 1546) // 2 + 1546, (H - 423) // 2 + 423),
    }
    for name, box in crops.items():
        final.crop(box).save(OUT / f"banner_preview_{name}.jpg", quality=85)

    # safe-area overlay debug image
    dbg = final.copy()
    dd = ImageDraw.Draw(dbg)
    dd.rectangle((sx, sy, sx + SW, sy + SH), outline=(0, 255, 120), width=6)
    dd.rectangle(crops["mobile_1546x423"], outline=(0, 160, 255), width=6)
    dd.rectangle(crops["desktop_2560x423"], outline=(255, 80, 80), width=6)
    dbg.resize((1280, 720), Image.LANCZOS).save(OUT / "banner_safe_area_check.jpg", quality=85)
    print("banner + previews written")


if __name__ == "__main__":
    make_logo()
    make_wordmark()
    make_banner()
    for p in sorted(OUT.iterdir()):
        print(f"  {p.name:36s} {p.stat().st_size // 1024:5d} KB")
