# Mortgage Shock — UK YouTube explainer (3 Sept 2026)

A complete, ready-to-upload 6½-minute YouTube video on the week's hottest UK money
story: the bond-market rout that pushed UK borrowing costs to a 28-year high, the
knock-on mortgage shock for ~1.8 million households, and the £25bn tax raid expected
in the 28 October Budget.

```
output/final_video.mp4    1920x1080 · 30fps · H.264/AAC · 6:41       ← upload this
output/thumbnail.jpg      1280x720 · 259 KB                          ← custom thumbnail
output/chapters.txt       chapter timestamps (also in the description)
YOUTUBE_METADATA.md       titles, description, tags, pinned comment, upload checklist
SCRIPT.md                 full narration script with fact-check notes
```

## What's in the video
| Time  | Chapter                  | On-screen stat |
|-------|--------------------------|----------------|
| 00:00 | Cold open + the 28-year high | 5.89% |
| 00:49 | The numbers behind the shock | 4.52% |
| 01:36 | Why it's happening       | $94 oil |
| 02:26 | The 1.8 million cliff    | 1.8M |
| 03:15 | Your payment shock       | +£321/month |
| 04:08 | The Budget tax raid      | £25bn |
| 05:02 | 5 things to do right now | action list |
| 05:59 | Your turn (CTA)          | 17 SEPT |

Production notes: narration is a British-English synthetic voice; b-roll and the thumbnail
photo are AI-generated; music bed is procedurally synthesised (no licensing). Captions are
burned in (phrase-timed to the narration). Loudness normalised to −14 LUFS (YouTube target).
Per YouTube policy, tick the **altered/synthetic content** disclosure on upload.

## Rebuilding
```bash
python3 -m venv .venv && .venv/bin/pip install pillow numpy imageio-ffmpeg
.venv/bin/python make_thumbnail.py            # -> output/thumbnail.jpg
.venv/bin/python build_video.py --preview     # 960x540 check render (~5 min)
.venv/bin/python build_video.py               # 1080p final (~15 min on 2 cores)
```
`build/` is scratch and git-ignored. Everything needed to re-render is in `assets/`
(voiceover MP3s, background JPGs, Roboto fonts) plus `script.json`.

### Changing the content
- **Narration/text:** edit `script.json`, regenerate the matching `assets/audio/<id>.mp3`.
- **On-screen numbers:** the `GRAPHICS` dict at the top of `build_video.py`.
- **Backgrounds:** swap any `assets/images/bg_*.jpg` (16:9, ≥1376px wide).
- **Thumbnail copy:** `make_thumbnail.py` (headline, £ figure, badge text).

### How the render works (memory-safe on 4 GB machines)
1. Pillow draws one RGBA overlay PNG per chapter (title, stat card, table/bullets, lower third).
2. ffmpeg per chapter: Ken-Burns zoom → gradient → overlay slide-in → progress bar → ASS captions → dip-to-black edges.
3. Clips are joined with the concat demuxer (stream copy — no re-encode, no frame buffering).
4. Audio-only pass: synthesised music bed, side-chain ducked under the voice, `loudnorm` to −14 LUFS, muxed with the copied video.
