#!/usr/bin/env python3
"""
Renders the full YouTube video (1920x1080, 30fps, H.264 + AAC) from:

  script.json               chapters + narration text
  assets/audio/<id>.mp3     voiceover per chapter (already generated)
  assets/images/<bg>.jpg    cinematic background per chapter

Pipeline (all done with Pillow + ffmpeg, no NLE needed):

  1. Per chapter, render one static 1920x1080 RGBA "overlay" PNG with Pillow
     (headline card, big stat, lower-third, chapter tag). Text is anti-aliased
     and stroked so it survives YouTube's compression.
  2. ffmpeg composites: Ken-Burns zoom on the background  ->  dark gradient
     ->  overlay PNG that fades/slides in  ->  animated progress bar
     ->  burned-in captions (ASS subtitles, phrase-timed to the voiceover)
  3. Every clip gets a short dip-to-black (0.35s) baked in, then all clips are
     joined with the concat demuxer (stream copy -> no re-encode, ~zero RAM).
     A 3s cold-open title card and a 6s end-screen bookend the chapters.
  4. Audio-only pass: a synthesised music bed (no licensing risk) is ducked
     under the narration with a side-chain compressor and the mix is
     loudness-normalised to YouTube's -14 LUFS target, then muxed with the
     untouched video stream.

  (An earlier version used a 9-way xfade chain; at 1080p that buffers several
   GB of frames and gets OOM-killed on small machines, hence this design.)

Usage:
    python build_video.py            # full render -> output/final_video.mp4
    python build_video.py --preview  # 960x540 fast render for checking

Requires: pillow, numpy, imageio-ffmpeg (bundled ffmpeg with libx264/libass).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import imageio_ffmpeg

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
BUILD = ROOT / "build"          # scratch (git-ignored, not persisted)
TMP = BUILD / "tmp"
OUT_DIR = ROOT / "output"       # deliverables
FF = imageio_ffmpeg.get_ffmpeg_exe()

FPS = 30
FADE = 0.35          # dip-to-black at each chapter edge (s)
INTRO_LEN = 3.0
OUTRO_LEN = 6.0   # may be overridden by end_card.duration in script.json
TAIL_PAD = 0.9       # silence after each chapter's narration (s)

YELLOW = (255, 214, 0)
RED = (226, 30, 40)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
UK_BLUE = (1, 33, 105)

# Per-chapter on-screen graphics, title/end cards and sources all live in
# script.json ("graphics", "title_card", "end_card", "sources") so this file is
# project-agnostic. Colour names in JSON map through this table.
COLOURS = {"YELLOW": YELLOW, "RED": RED, "WHITE": WHITE, "GREEN": (46, 204, 113)}
SCRIPT = json.loads((ROOT / "script.json").read_text())
GRAPHICS = {k: {**v, "accent": COLOURS[v.get("accent", "YELLOW")], "headline": tuple(v["headline"]),
                "rows": [tuple(r) for r in v["rows"]] if "rows" in v else None,
                "bullets": v.get("bullets")}
            for k, v in SCRIPT["graphics"].items()}
for _g in GRAPHICS.values():
    if _g["rows"] is None: _g.pop("rows")
    if _g["bullets"] is None: _g.pop("bullets")
TITLE = SCRIPT["title_card"]
END = SCRIPT["end_card"]
OUTRO_LEN = float(END.get("duration", OUTRO_LEN))
SOURCES_LINE = "Sources: " + " · ".join(SCRIPT["sources"])
VOICE_TEMPO = float(SCRIPT.get("voice_tempo", 1.0))   # 1.0 = untouched; 1.03 = 3% faster


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"ffmpeg failed:\n{' '.join(cmd)}\n\n{res.stderr[-4000:]}")


def probe_duration(path: Path) -> float:
    out = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / "fonts" / name), size)


def ass_time(t: float) -> str:
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


# ---------------------------------------------------------------------------
# 1. overlay graphics (Pillow)
# ---------------------------------------------------------------------------
def text_size(draw, text, fnt, stroke=0):
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt, stroke_width=stroke)
    return r - l, b - t


def render_overlay(seg_id: str, chapter: str, idx: int, total: int, W: int, H: int) -> Path:
    """Static RGBA overlay for a chapter: title card (top-left), big stat card
    (right), optional rows/bullets, lower-third tag, chapter counter."""
    g = GRAPHICS[seg_id]
    s = W / 1920  # scale factor for preview renders
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    accent = g["accent"]
    f_head = font("Roboto-Black.ttf", int(84 * s))
    f_stat = font("Roboto-Black.ttf", int(150 * s))
    f_lab = font("Roboto-Bold.ttf", int(30 * s))
    f_tag = font("Roboto-Black.ttf", int(30 * s))
    f_row = font("Roboto-Bold.ttf", int(40 * s))
    f_row_s = font("Roboto-Medium.ttf", int(28 * s))
    f_small = font("Roboto-Bold.ttf", int(26 * s))

    # --- red/yellow tag pill (top-left) ---
    px, py = int(96 * s), int(78 * s)
    tw, th = text_size(d, g["tag"], f_tag)
    d.rounded_rectangle((px, py, px + tw + int(44 * s), py + th + int(28 * s)), radius=int(10 * s), fill=accent)
    d.text((px + int(22 * s), py + int(12 * s)), g["tag"], font=f_tag,
           fill=BLACK if accent != RED else WHITE)

    # --- two-line headline under tag ---
    hy = py + th + int(60 * s)
    for i, line in enumerate(g["headline"]):
        d.text((px, hy + i * int(96 * s)), line, font=f_head, fill=WHITE if i == 0 else accent,
               stroke_width=int(6 * s), stroke_fill=BLACK)

    # --- big stat card (right) ---
    cw, ch = int(720 * s), int(330 * s)
    cx, cy = W - cw - int(96 * s), int(96 * s)
    card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle((0, 0, cw, ch), radius=int(26 * s), fill=(10, 10, 14, 215), outline=accent, width=int(5 * s))
    cd.rectangle((0, 0, int(16 * s), ch), fill=accent)
    stat = g["stat"]
    # shrink stat font to fit card width
    fs = int(150 * s)
    while True:
        f_try = font("Roboto-Black.ttf", fs)
        sw, sh = text_size(cd, stat, f_try)
        if sw <= cw - int(80 * s) or fs < int(60 * s):
            break
        fs -= 4
    cd.text((cw // 2 + int(8 * s), int(120 * s)), stat, font=f_try, fill=accent, anchor="mm")
    # label (wrap to 2 lines if needed)
    lab = g["stat_label"]
    words, lines, cur = lab.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if text_size(cd, t, f_lab)[0] > cw - int(70 * s):
            lines.append(cur); cur = w_
        else:
            cur = t
    lines.append(cur)
    for i, ln in enumerate(lines[:2]):
        cd.text((cw // 2 + int(8 * s), int(232 * s) + i * int(38 * s)), ln, font=f_lab, fill=WHITE, anchor="mm")
    img.alpha_composite(card, (cx, cy))

    # --- rows table (right, under stat card) ---
    if "rows" in g:
        ry = cy + ch + int(28 * s)
        rh = int(86 * s)
        tbl = Image.new("RGBA", (cw, rh * len(g["rows"])), (0, 0, 0, 0))
        td = ImageDraw.Draw(tbl)
        td.rounded_rectangle((0, 0, cw, rh * len(g["rows"])), radius=int(22 * s), fill=(10, 10, 14, 200))
        for i, (k, v, note) in enumerate(g["rows"]):
            y0 = i * rh
            if i:
                td.line((int(24 * s), y0, cw - int(24 * s), y0), fill=(255, 255, 255, 40), width=2)
            td.text((int(28 * s), y0 + int(16 * s)), k, font=f_row_s, fill=(200, 200, 205))
            td.text((int(28 * s), y0 + int(46 * s)), note, font=font("Roboto-Regular.ttf", int(22 * s)), fill=(150, 150, 158))
            # value right-aligned, auto-shrink
            vf = f_row; vs = int(40 * s)
            while text_size(td, v, vf)[0] > cw * 0.5 and vs > int(22 * s):
                vs -= 2; vf = font("Roboto-Bold.ttf", vs)
            td.text((cw - int(28 * s), y0 + rh // 2), v, font=vf, fill=accent, anchor="rm")
        img.alpha_composite(tbl, (cx, ry))

    # --- bullets (left, under headline) ---
    if "bullets" in g:
        by = hy + 2 * int(96 * s) + int(30 * s)
        bw = int(1000 * s)
        n_b = len(g["bullets"])
        # available height: from under the headline to just above the lower-third
        avail = (H - int(270 * s) - int(16 * s)) - by
        pitch = min(int(78 * s), avail // n_b)          # row pitch shrinks for long lists
        row_h = int(pitch * 0.82)
        for i, b in enumerate(g["bullets"]):
            y0 = by + i * pitch
            d.rounded_rectangle((px, y0, px + bw, y0 + row_h), radius=int(12 * s), fill=(10, 10, 14, 200))
            r_ = int(row_h * 0.31)
            cy_ = y0 + row_h // 2
            d.ellipse((px + int(14 * s), cy_ - r_, px + int(14 * s) + 2 * r_, cy_ + r_), fill=accent)
            d.text((px + int(14 * s) + r_, cy_), str(i + 1), font=font("Roboto-Black.ttf", int(r_ * 1.4)), fill=BLACK, anchor="mm")
            # auto-fit bullet text to the row
            fs_b = min(int(30 * s), int(row_h * 0.46)); fb = font("Roboto-Bold.ttf", fs_b)
            while text_size(d, b, fb)[0] > bw - int(90 * s) and fs_b > int(16 * s):
                fs_b -= 1; fb = font("Roboto-Bold.ttf", fs_b)
            d.text((px + int(72 * s), cy_), b, font=fb, fill=WHITE, anchor="lm")

    # --- lower-third: chapter name + counter (bottom-left, above captions) ---
    ly = H - int(270 * s)
    lt = f"{idx:02d} / {total:02d}   {chapter.upper()}"
    lw, lh = text_size(d, lt, f_small)
    d.rectangle((px, ly, px + int(8 * s), ly + lh + int(20 * s)), fill=accent)
    d.rounded_rectangle((px + int(8 * s), ly, px + lw + int(50 * s), ly + lh + int(20 * s)), radius=int(6 * s), fill=(0, 0, 0, 170))
    d.text((px + int(28 * s), ly + int(9 * s)), lt, font=f_small, fill=WHITE)

    # --- persistent source line (bottom-right) ---
    src = SOURCES_LINE
    sf = font("Roboto-Regular.ttf", int(20 * s))
    sw_, sh_ = text_size(d, src, sf)
    d.text((W - int(96 * s) - sw_, H - int(60 * s)), src, font=sf, fill=(210, 210, 215, 220),
           stroke_width=int(2 * s), stroke_fill=(0, 0, 0, 160))

    out = TMP / f"overlay_{seg_id}.png"
    img.save(out)
    return out


def render_title_card(W: int, H: int) -> Path:
    """Cold-open card shown for INTRO_LEN seconds before the hook."""
    s = W / 1920
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # auto-fit the big title to 90% of the frame width
    fs = int(170 * s)
    while d.textlength(TITLE["title"], font=font("Roboto-Black.ttf", fs)) > W * 0.9 and fs > int(80 * s):
        fs -= 4
    d.text((W // 2, int(H * 0.36)), TITLE["title"], font=font("Roboto-Black.ttf", fs),
           fill=YELLOW, anchor="mm", stroke_width=int(10 * s), stroke_fill=BLACK)
    d.text((W // 2, int(H * 0.53)), TITLE["subtitle"], font=font("Roboto-Black.ttf", int(60 * s)),
           fill=WHITE, anchor="mm", stroke_width=int(6 * s), stroke_fill=BLACK)
    d.rounded_rectangle((W // 2 - int(330 * s), int(H * 0.63), W // 2 + int(330 * s), int(H * 0.63) + int(74 * s)),
                        radius=int(14 * s), fill=RED)
    d.text((W // 2, int(H * 0.63) + int(37 * s)), TITLE["pill"], font=font("Roboto-Black.ttf", int(34 * s)),
           fill=WHITE, anchor="mm")
    d.text((W // 2, int(H * 0.80)), TITLE["date"], font=font("Roboto-Bold.ttf", int(34 * s)),
           fill=(220, 220, 225), anchor="mm", stroke_width=int(3 * s), stroke_fill=BLACK)
    out = TMP / "overlay_intro.png"; img.save(out); return out


def render_end_card(W: int, H: int) -> Path:
    """End-screen: leaves YouTube's standard end-screen zones free
    (two 16:9 element slots on the right + subscribe circle bottom-left)."""
    s = W / 1920
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((int(96 * s), int(120 * s)), "THANKS FOR", font=font("Roboto-Black.ttf", int(96 * s)), fill=WHITE,
           stroke_width=int(6 * s), stroke_fill=BLACK)
    d.text((int(96 * s), int(225 * s)), "WATCHING", font=font("Roboto-Black.ttf", int(96 * s)), fill=YELLOW,
           stroke_width=int(6 * s), stroke_fill=BLACK)
    lines = END["lines"]
    for i, ln in enumerate(lines):
        d.text((int(96 * s), int(370 * s) + i * int(48 * s)), ln, font=font("Roboto-Medium.ttf", int(34 * s)),
               fill=WHITE, stroke_width=int(3 * s), stroke_fill=BLACK)
    # placeholders for end-screen elements (YouTube adds the real ones)
    for (x, y) in [(int(1180 * s), int(130 * s)), (int(1180 * s), int(560 * s))]:
        d.rounded_rectangle((x, y, x + int(620 * s), y + int(350 * s)), radius=int(18 * s),
                            fill=(0, 0, 0, 120), outline=(255, 255, 255, 120), width=int(3 * s))
        d.text((x + int(310 * s), y + int(175 * s)), "NEXT VIDEO", font=font("Roboto-Bold.ttf", int(30 * s)),
               fill=(230, 230, 235), anchor="mm")
    cx, cy, r = int(200 * s), int(820 * s), int(95 * s)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 0, 0, 120), outline=RED, width=int(5 * s))
    d.text((cx, cy), "SUBSCRIBE", font=font("Roboto-Black.ttf", int(26 * s)), fill=WHITE, anchor="mm")
    out = TMP / "overlay_end.png"; img.save(out); return out


# ---------------------------------------------------------------------------
# 2. captions (ASS)  — phrase-timed by proportional character weight, snapped
#    to detected silences in the voiceover so lines change on real pauses.
# ---------------------------------------------------------------------------
def detect_silences(audio: Path) -> list[tuple[float, float]]:
    out = subprocess.run(
        [FF, "-hide_banner", "-i", str(audio), "-af", "silencedetect=noise=-38dB:d=0.18", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    return list(zip(starts, ends[: len(starts)]))


def split_phrases(text: str, max_chars: int = 56) -> list[str]:
    """Sentence split, then break long sentences on commas/colons to keep
    caption lines short enough to read comfortably."""
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
    phrases: list[str] = []
    for sn in sents:
        if len(sn) <= max_chars:
            phrases.append(sn); continue
        parts = [p.strip() for p in re.split(r"(?<=[,:;])\s+", sn) if p.strip()]
        cur = ""
        for p in parts:
            if cur and len(cur) + 1 + len(p) > max_chars:
                phrases.append(cur); cur = p
            else:
                cur = (cur + " " + p).strip()
        if cur:
            phrases.append(cur)
    return phrases


def time_phrases(text: str, audio: Path, lead: float = 0.0) -> list[tuple[float, float, str]]:
    dur = probe_duration(audio)
    sil = detect_silences(audio)
    # speech starts after any leading silence, ends before trailing silence
    speech_start = sil[0][1] if sil and sil[0][0] < 0.05 else 0.0
    speech_end = sil[-1][0] if sil and abs(sil[-1][1] - dur) < 0.15 else dur
    pauses = [(a + b) / 2 for a, b in sil if a > speech_start + 0.3 and b < speech_end - 0.3]

    phrases = split_phrases(text)
    weights = np.array([len(p) + 8 for p in phrases], dtype=float)  # +8 ≈ pause per phrase
    cum = np.cumsum(weights) / weights.sum()
    bounds = [speech_start + c * (speech_end - speech_start) for c in cum]

    # snap each estimated boundary to nearest real pause within 0.45s
    snapped = []
    for b in bounds[:-1]:
        cand = [p for p in pauses if abs(p - b) < 0.45]
        snapped.append(min(cand, key=lambda p: abs(p - b)) if cand else b)
    snapped.append(speech_end)

    cues, t0 = [], speech_start
    for ph, t1 in zip(phrases, snapped):
        t1 = max(t1, t0 + 0.6)
        cues.append((lead + t0, lead + t1, ph))
        t0 = t1
    return cues


def write_ass(cues: list[tuple[float, float, str]], path: Path, W: int, H: int) -> None:
    s = W / 1920
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Roboto,{int(46 * s)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{int(4 * s)},{int(2 * s)},2,{int(200 * s)},{int(200 * s)},{int(110 * s)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for a, b, txt in cues:
        txt = txt.replace("\n", " ")
        lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Cap,,0,0,0,,{{\\fad(120,120)}}{txt}\n")
    path.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. music bed (synthesised — royalty-free by construction)
# ---------------------------------------------------------------------------
def make_music(duration: float, path: Path, sr: int = 44100) -> None:
    """Low, tense news-style pad: slow chord cycle in A minor (70 bpm) with a
    soft kick pulse. Deliberately unobtrusive so speech stays intelligible.
    Everything is computed with analytic envelopes (vectorised, O(N))."""
    n = int(duration * sr)
    t = np.arange(n, dtype=np.float64) / sr
    chords = [  # Am, F, C, G  (one chord per bar)
        (110.0, 130.81, 164.81, 220.0),
        (87.31, 130.81, 174.61, 220.0),
        (98.0, 130.81, 164.81, 196.0),
        (98.0, 123.47, 146.83, 196.0),
    ]
    bpm = 70
    bar = 60 / bpm * 4
    bar_idx = np.floor(t / bar)
    t_in = t - bar_idx * bar
    ramp = 0.25
    env = np.clip(t_in / ramp, 0, 1) * np.clip((bar - t_in) / ramp, 0, 1)   # smooth swell per bar
    chord_of_bar = (bar_idx % 4).astype(np.int8)
    vib = 0.3 * np.sin(2 * np.pi * 0.11 * t)
    out = np.zeros(n, dtype=np.float64)
    for i, ch in enumerate(chords):
        e = env * (chord_of_bar == i)
        for k, f in enumerate(ch):
            out += e * (0.22 / (k + 1)) * np.sin(2 * np.pi * f * t + vib)
            out += e * 0.05 * np.sin(2 * np.pi * 2 * f * t)          # gentle octave shimmer
    beat = 60 / bpm
    t_beat = t - np.floor(t / beat) * beat
    pulse = np.exp(-t_beat / 0.03) * (t_beat < 0.12)
    out += 0.25 * pulse * np.sin(2 * np.pi * 55 * t)                 # soft kick
    out *= 0.85 + 0.15 * np.sin(2 * np.pi * 0.05 * t)                # slow tremolo
    out *= np.clip(np.minimum(t / 2.5, (duration - t) / 4.0), 0, 1)  # fade in/out
    out *= 0.5 / (np.abs(out).max() + 1e-9)
    pcm = (out * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------------------
# 4. per-chapter render
# ---------------------------------------------------------------------------
@dataclass
class Clip:
    path: Path
    duration: float


def condition_audio(src: Path) -> Path:
    """Tighten the TTS delivery: strip leading silence, shorten any pause longer
    than ~0.3s down to 0.26s, and (optionally) apply a gentle tempo change.
    Output is a 48k mono WAV in TMP; the source MP3 is never modified."""
    out = TMP / f"voice_{src.stem}.wav"
    if out.exists():
        return out
    af = ("silenceremove=start_periods=1:start_duration=0.2:start_threshold=-40dB:start_silence=0.15:"
          "stop_periods=-1:stop_duration=0.28:stop_threshold=-40dB:stop_silence=0.22")
    if abs(VOICE_TEMPO - 1.0) > 1e-3:
        af += f",atempo={VOICE_TEMPO}"
    run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", af,
         "-ar", "48000", "-ac", "1", str(out)])
    return out


def render_chapter(seg: dict, idx: int, total: int, W: int, H: int, preset: str, crf: int,
                   total_video_len: float, start_offset: float) -> Clip:
    seg_id = seg["id"]
    audio = condition_audio(ASSETS / "audio" / f"{seg_id}.mp3")
    voice_len = probe_duration(audio)
    dur = voice_len + TAIL_PAD
    overlay = render_overlay(seg_id, seg["chapter"], idx, total, W, H)
    ass = TMP / f"cap_{seg_id}.ass"
    write_ass(time_phrases(seg["text"], audio), ass, W, H)

    # Alternate zoom-in / zoom-out with a slight drift so chapters feel different
    zoom_in = idx % 2 == 1
    z_expr = f"1.02+0.10*on/{int(dur * FPS)}" if zoom_in else f"1.12-0.10*on/{int(dur * FPS)}"
    x_expr = f"iw/2-(iw/zoom/2)+{(-1) ** idx * 40}*on/{int(dur * FPS)}"
    y_expr = "ih/2-(ih/zoom/2)"

    # progress bar: total video position (offset + local t) / total length
    pb_w = f"{W}*({start_offset}+t)/{total_video_len}"

    vf = (
        f"[0:v]scale={int(W * 1.5)}:{int(H * 1.5)}:flags=lanczos,"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d=1:s={W}x{H}:fps={FPS},"
        f"eq=contrast=1.06:saturation=1.05,format=rgba[bg];"
        # dark vignette / gradient so text pops
        f"[bg]drawbox=x=0:y=0:w=iw:h=ih:color=black@0.28:t=fill,"
        f"drawbox=x=0:y=ih*0.62:w=iw:h=ih*0.38:color=black@0.30:t=fill[bgd];"
        # overlay slides up 40px while fading in over 0.6s
        f"[1:v]format=rgba,fade=t=in:st=0:d=0.6:alpha=1[ov];"
        f"[bgd][ov]overlay=x=0:y='if(lt(t,0.6),40*(1-t/0.6)*(1-t/0.6),0)'[withov];"
        # progress bar (bottom edge, accent yellow)
        f"[withov]drawbox=x=0:y={H - 10}:w='{pb_w}':h=10:color=0xFFD600@0.95:t=fill,"
        f"drawbox=x=0:y={H - 10}:w=iw:h=10:color=white@0.12:t=fill[pb];"
        f"[pb]ass='{ass.as_posix()}':fontsdir='{(ASSETS / 'fonts').as_posix()}',"
        f"fade=t=in:st=0:d={FADE},fade=t=out:st={dur - FADE:.3f}:d={FADE},format=yuv420p[v]"
    )
    out = TMP / f"clip_{idx:02d}_{seg_id}.mp4"
    run([FF, "-y", "-hide_banner", "-loglevel", "error",
         "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(ASSETS / "images" / seg["bg"]),
         "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(overlay),
         "-i", str(audio),
         "-filter_complex", vf + f";[2:a]apad=pad_dur={TAIL_PAD},"
                                  f"afade=t=in:st=0:d={FADE},afade=t=out:st={dur - FADE:.3f}:d={FADE}[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         str(out)])
    return Clip(out, dur)


def render_card(name: str, overlay: Path, bg: Path, dur: float, W: int, H: int, preset: str, crf: int,
                zoom_in: bool = True) -> Clip:
    n = int(dur * FPS)
    z = f"1.0+0.06*on/{n}" if zoom_in else f"1.06-0.06*on/{n}"
    vf = (f"[0:v]scale={int(W * 1.5)}:{int(H * 1.5)}:flags=lanczos,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
          f"format=rgba,drawbox=x=0:y=0:w=iw:h=ih:color=black@0.45:t=fill[bg];"
          f"[1:v]format=rgba,fade=t=in:st=0.15:d=0.6:alpha=1[ov];[bg][ov]overlay=0:0,"
          f"fade=t=in:st=0:d={FADE},fade=t=out:st={dur - FADE:.3f}:d={FADE},format=yuv420p[v]")
    out = TMP / f"clip_{name}.mp4"
    run([FF, "-y", "-hide_banner", "-loglevel", "error",
         "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(bg),
         "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(overlay),
         "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
         "-filter_complex", vf, "-map", "[v]", "-map", "2:a", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])
    return Clip(out, dur)


# ---------------------------------------------------------------------------
# 5. assembly
# ---------------------------------------------------------------------------
def assemble(clips: list[Clip], out_path: Path) -> float:
    """Join the (already faded) clips losslessly, then mix the music bed under
    the narration in an audio-only pass and mux with the copied video."""
    lst = TMP / "concat.txt"
    lst.write_text("".join(f"file '{c.path.as_posix()}'\n" for c in clips))
    joined = TMP / "joined.mp4"
    run([FF, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", "-movflags", "+faststart", str(joined)])
    total = probe_duration(joined)

    music = TMP / "music.wav"
    make_music(total, music)
    fc = (
        "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=1.0[music];"
        "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voice][sc];"
        "[music][sc]sidechaincompress=threshold=0.02:ratio=8:attack=40:release=600:makeup=1[ducked];"
        "[voice][ducked]amix=inputs=2:weights='1 0.4':duration=first:normalize=0,"
        "loudnorm=I=-14:TP=-1.5:LRA=11[amix]"
    )
    run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-i", str(music),
         "-filter_complex", fc, "-map", "0:v", "-map", "[amix]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
         "-movflags", "+faststart", str(out_path)])
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="fast 960x540 render")
    args = ap.parse_args()

    W, H = (960, 540) if args.preview else (1920, 1080)
    # clips are stream-copied into the final, so this IS the delivery quality
    preset, crf = ("veryfast", 26) if args.preview else ("fast", 21)
    out_name = "preview.mp4" if args.preview else "final_video.mp4"

    BUILD.mkdir(exist_ok=True); TMP.mkdir(exist_ok=True); OUT_DIR.mkdir(exist_ok=True)
    segs = SCRIPT["segments"]

    durs = [probe_duration(condition_audio(ASSETS / "audio" / f"{s['id']}.mp3")) + TAIL_PAD for s in segs]
    total_len = INTRO_LEN + sum(durs) + OUTRO_LEN
    print(f"Planned length: {total_len:.1f}s ({total_len / 60:.2f} min) at {W}x{H}")

    clips: list[Clip] = []
    clips.append(render_card("intro", render_title_card(W, H), ASSETS / "images" / TITLE["bg"],
                             INTRO_LEN, W, H, preset, crf, zoom_in=True))
    print("  intro card done")
    offset = INTRO_LEN
    for i, seg in enumerate(segs, start=1):
        c = render_chapter(seg, i, len(segs), W, H, preset, crf, total_len, offset)
        offset += c.duration
        clips.append(c)
        print(f"  chapter {i}/{len(segs)} {seg['id']} done ({c.duration:.1f}s)")
    clips.append(render_card("end", render_end_card(W, H), ASSETS / "images" / END["bg"],
                             OUTRO_LEN, W, H, preset, crf, zoom_in=False))
    print("  end card done")

    final = (BUILD if args.preview else OUT_DIR) / out_name
    total = assemble(clips, final)
    print(f"\nDONE -> {final}  ({total:.1f}s = {total / 60:.2f} min)")

    # chapter timestamps for the YouTube description (YouTube needs the first
    # chapter at 00:00 and every chapter >= 10s, so the 3s cold open is folded
    # into chapter 1 and the 6s end card is not listed)
    t, stamps = 0.0, []
    for seg, d in zip(segs, durs):
        stamps.append(f"{int(t // 60):02d}:{int(t % 60):02d} {seg['chapter']}")
        t += d + (INTRO_LEN if t == 0 else 0)
    (OUT_DIR / "chapters.txt").write_text("\n".join(stamps) + "\n")
    print("\n".join(stamps))


if __name__ == "__main__":
    main()
