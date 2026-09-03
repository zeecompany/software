#!/usr/bin/env python3
"""
Builds the YouTube thumbnail (1280x720) for the Mortgage Shock video.

Layout (classic high-CTR finance thumbnail):
  - Left third : shocked man with letter (AI-generated photo, cut out with a soft vignette)
  - Right side : huge 3-line headline in yellow/white/red with black stroke
  - Bottom-left: red "BREAKING" pill + Union flag stripe
  - Corner    : "28-YEAR HIGH" sticker badge

Usage: python make_thumbnail.py
Output: output/thumbnail.jpg (1280x720, <2MB as YouTube requires)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

ROOT = Path(__file__).parent
FONT_DIR = ROOT / "assets" / "fonts"
OUT = ROOT / "output" / "thumbnail.jpg"

W, H = 1280, 720
YELLOW = (255, 214, 0)
RED = (226, 30, 40)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def draw_outlined(draw: ImageDraw.ImageDraw, xy, text, fnt, fill, stroke=8, stroke_fill=BLACK, anchor="la"):
    draw.text(xy, text, font=fnt, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill, anchor=anchor)


def build():
    # ---- Background: dark stormy street, blurred + darkened ------------------
    bg = Image.open(ROOT / "assets/images/bg_street.jpg").convert("RGB")
    bg = bg.resize((W, H), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(3))
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    bg = ImageEnhance.Contrast(bg).enhance(1.15)

    # Red diagonal "danger" gradient on the right for the text block
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for x in range(W):
        a = int(max(0, min(1, (x - 380) / 700)) ** 1.3 * 170)
        gd.line([(x, 0), (x, H)], fill=(120, 0, 10, a))
    bg = Image.alpha_composite(bg.convert("RGBA"), grad)

    # ---- Subject: shocked man, feathered on the right edge ---------------------
    face = Image.open(ROOT / "assets/images/thumb_face.jpg").convert("RGB")
    # Crop around subject (he sits in left ~55% of the source frame)
    fw, fh = face.size
    crop = face.crop((0, 0, int(fw * 0.62), fh))
    target_h = H
    scale = target_h / crop.height
    crop = crop.resize((int(crop.width * scale), target_h), Image.LANCZOS)
    crop = ImageEnhance.Contrast(crop).enhance(1.12)
    crop = ImageEnhance.Color(crop).enhance(1.25)

    mask = Image.new("L", crop.size, 255)
    md = ImageDraw.Draw(mask)
    feather = 170
    for i in range(feather):
        a = int(255 * (1 - i / feather))
        md.line([(crop.width - feather + i, 0), (crop.width - feather + i, crop.height)], fill=a)
    bg.paste(crop, (-40, 0), mask)

    d = ImageDraw.Draw(bg)

    # ---- Headline block (right side) ------------------------------------------
    tx = 600
    f_big = font("Roboto-Black.ttf", 118)
    f_mid = font("Roboto-Black.ttf", 96)
    draw_outlined(d, (tx, 78), "MORTGAGE", f_big, YELLOW, stroke=10)
    draw_outlined(d, (tx, 205), "SHOCK", f_big, WHITE, stroke=10)

    # £321 / MONTH red pill
    pill = (tx - 6, 352, tx + 560, 470)
    d.rounded_rectangle(pill, radius=22, fill=RED, outline=BLACK, width=6)
    draw_outlined(d, (tx + 22, 362), "+£321", font("Roboto-Black.ttf", 92), WHITE, stroke=6)
    draw_outlined(d, (tx + 330, 386), "/ MONTH", font("Roboto-Black.ttf", 40), WHITE, stroke=5)

    # Sub-line
    draw_outlined(d, (tx, 500), "1.8 MILLION UK HOMES HIT", font("Roboto-Black.ttf", 44), YELLOW, stroke=6)

    # ---- "28-YEAR HIGH" sticker badge (top-left, rotated) ---------------------
    badge = Image.new("RGBA", (420, 130), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.rounded_rectangle((4, 4, 416, 126), radius=18, fill=YELLOW, outline=BLACK, width=6)
    bd.text((210, 40), "28-YEAR HIGH", font=font("Roboto-Black.ttf", 46), fill=BLACK, anchor="mm")
    bd.text((210, 92), "BORROWING COSTS", font=font("Roboto-Bold.ttf", 26), fill=BLACK, anchor="mm")
    badge = badge.rotate(7, expand=True, resample=Image.BICUBIC)
    bg.alpha_composite(badge, (18, 18))

    # ---- BREAKING pill + Union-flag stripe (bottom) ---------------------------
    d = ImageDraw.Draw(bg)
    d.rectangle((0, H - 14, W, H), fill=(1, 33, 105))     # UK blue
    d.rectangle((0, H - 14, W // 3, H), fill=RED)
    d.rectangle((W // 3, H - 14, 2 * W // 3, H), fill=WHITE)

    d.rounded_rectangle((20, H - 96, 300, H - 32), radius=12, fill=RED, outline=BLACK, width=5)
    d.text((160, H - 64), "BREAKING", font=font("Roboto-Black.ttf", 40), fill=WHITE, anchor="mm")

    # Date tag
    draw_outlined(d, (W - 24, H - 34), "SEPT 2026", font("Roboto-Bold.ttf", 32), WHITE, stroke=5, anchor="rd")

    # ---- Slight global sharpen and save -----------------------------------------
    out = bg.convert("RGB").filter(ImageFilter.UnsharpMask(radius=2, percent=60))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, quality=92, optimize=True)
    print(f"Thumbnail written: {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
