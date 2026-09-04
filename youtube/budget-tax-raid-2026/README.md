# The £25bn Tax Raid — Sterling Signal video 2 (4 Sept 2026)

Ready-to-upload ~7-minute YouTube explainer on the 28 October Budget: why there's a
£10–25bn hole, why income tax / NI / VAT are off the table, what's already locked in
(frozen thresholds, ISA cap, pensions into IHT), the 7 taxes most likely to rise, what it
costs three real households, and 6 things to do before Budget day.

```
output/final_video.mp4    1920x1080 · 30fps · H.264/AAC · ~6:58 · burned-in captions   ← upload
output/thumbnail.jpg      1280x720                                                     ← thumbnail
output/chapters.txt       chapter timestamps for the description
YOUTUBE_METADATA.md       titles, description, tags, keyword plan, pinned comment, checklist
SCRIPT.md                 narration + fact-check notes with sources
```

## Rebuilding
```bash
python3 -m venv .venv && .venv/bin/pip install pillow numpy imageio-ffmpeg
.venv/bin/python make_thumbnail.py          # -> output/thumbnail.jpg
.venv/bin/python build_video.py --preview   # 960x540 check (~5 min)
.venv/bin/python build_video.py             # 1080p final (~15 min on 2 cores)
```

## What changed vs video 1's pipeline
- `build_video.py` is now **project-agnostic**: chapter graphics, title card, end card,
  sources line and voice tempo all come from `script.json` (`graphics`, `title_card`,
  `end_card`, `sources`, `voice_tempo`). Copy the two `.py` files + a new `script.json`
  and assets to start video 3.
- **Audio conditioning** (`condition_audio`): strips leading silence, shortens any
  narration pause > 0.28 s to 0.22 s, and applies an optional gentle `atempo`
  (1.05 here) — this is how a 7.9-min TTS read fits a 7-min cut without re-recording.
- Bullet lists auto-compress their row pitch so 6–7 items stay clear of the lower-third.
- End-card length is configurable (`end_card.duration`, 5 s here).

Disclosure reminder: narration is synthetic; b-roll and thumbnail photo are AI-generated —
tick YouTube's altered/synthetic content box on upload.
