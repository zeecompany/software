# Sterling Signal — Channel Setup Guide

**Channel name:** Sterling Signal
**Handle:** @SterlingSignal  (fallbacks if taken: @SterlingSignalUK · @TheSterlingSignal · @SterlingSignalTV)
**Tagline:** UK money news, decoded.
**One-liner:** The early signal on what UK money news means for your mortgage, your pay and your tax.

### Why this name
| Test | Result |
|---|---|
| Says what it is | "Sterling" = the pound / UK money; "Signal" = early warning, clarity out of noise |
| Memorable | Alliterative, two words, five syllables |
| Ownable | No existing UK finance channel, brand or publication with this name found; "sterling" also reads as *excellent* |
| Scales beyond mortgages | Works for rates, Budget, pensions, energy bills, markets — not locked to one story |
| Logo-friendly | £ + pulse line is instantly readable at 40 px in the comments column |

Alternatives considered: **Quid Sense** (friendlier, less authoritative), **Pound Watch** (literal, but BBC used "Poundwatch" as a series title), **UK Money Desk** (clear but generic).

---

## 1. Brand kit (in `brand/output/`)

| File | Use | Spec |
|---|---|---|
| `logo_800.png` | **Profile picture** (channel icon) | 800×800, shown as a circle — everything is inside the safe circle |
| `logo_800_light.png` | Light-background version (X/LinkedIn/press) | 800×800 |
| `logo_mark_1024.png` | Transparent mark for overlays / end screens / Shorts | 1024×1024 PNG, alpha |
| `watermark_150.png` | **Branding watermark** on all videos | 150×150 PNG, 72 % white — reads on light and dark footage |
| `banner_2560x1440.jpg` | **Channel banner** | 2560×1440, 347 KB (limit 6 MB). All text/logo inside the 1235×338 safe area |
| `banner_preview_*.jpg` | How it crops on TV / desktop / tablet / mobile | check before upload |
| `wordmark_dark.png` | Horizontal lock-up for lower-thirds, community posts | transparent PNG |

**Palette:** Signal Yellow `#FFD600` · Ink `#0B0F19` · Alert Red `#E21E28` · White `#FFFFFF` · Slate `#A8AEBA`
**Type:** Roboto Black (headlines / numbers) · Roboto Bold (labels) · Roboto Medium (body). Same fonts as the video graphics, so thumbnails, banner and in-video cards match.

**Thumbnail rules (consistency = recognisable in the feed):**
1. One human face with a strong emotion OR one big object, left third.
2. Max 4–5 words, Roboto Black, yellow/white/red with black stroke.
3. One number in a red pill (`+£321`, `5.89%`, `£25bn`).
4. Yellow/ink colour scheme every time; never blue (blends into YouTube's UI).

---

## 2. Step-by-step: create and configure the channel

### 2.1 Create it
1. Sign in to YouTube with a **dedicated Google account** for the channel (not your personal one) → profile icon → **Create a channel**.
2. Choose **"Use a custom name"** → `Sterling Signal`. This creates a Brand Account so you can add managers later without sharing the password.
3. Upload `logo_800.png` when prompted (you can change it later in Customisation).
4. Go to **YouTube Studio → Settings → Channel → Feature eligibility** and complete **phone verification** immediately (unlocks custom thumbnails, videos >15 min, live streaming, external links).

### 2.2 Customisation → Branding
| Field | Set to |
|---|---|
| Picture | `brand/output/logo_800.png` |
| Banner image | `brand/output/banner_2560x1440.jpg` — check the preview on all three device sizes |
| Video watermark | `brand/output/watermark_150.png` · Display time: **Entire video** |

### 2.3 Customisation → Basic info
**Name:** Sterling Signal
**Handle:** @SterlingSignal

**Description (paste exactly — first 100–150 chars matter for search):**
```
UK money news, decoded. Sterling Signal explains what's happening to your mortgage, your interest rates, your tax and your bills — in plain English, with the real numbers, in under 7 minutes.

New videos every week, plus same-day breakdowns of every Bank of England decision and every Budget.

What we cover:
• Mortgage rates, remortgaging and the 2026 fixed-rate cliff
• Bank of England interest rate decisions
• The Budget, tax changes, ISAs and pensions
• Inflation, energy bills and the cost of living
• Gilts, bond markets and why they move your mortgage

Every figure is sourced (ONS, Bank of England, UK Finance, Moneyfacts, OBR, IFS, Resolution Foundation) and shown on screen.

Nothing here is financial advice. For decisions about your own money, speak to an FCA-regulated adviser.

Business & press: [email]
```

**Links** (up to 14; the first one shows on the banner):
1. Latest video / playlist "Mortgage Shock 2026"
2. X (Twitter) — @SterlingSignal
3. TikTok — @sterlingsignal (for Shorts cross-posting)
4. Instagram — @sterlingsignal
5. Newsletter sign-up (Substack/Beehiiv — free, worth setting up in week 1: it's the only audience you *own*)

**Contact info:** a dedicated email (e.g. hello@ or press@ on your domain, or sterlingsignal.uk@gmail.com).

### 2.4 Customisation → Layout
- **Channel trailer (for people who haven't subscribed):** upload a 30–45 s cut of the Mortgage Shock hook (00:03–00:49) with a "Subscribe for the 17 Sept Bank of England breakdown" end line.
- **Featured video (for returning subscribers):** the latest upload.
- **Featured sections, in this order:**
  1. Latest videos
  2. Playlist: *Mortgage Shock 2026* (this video + the 17 Sept and 28 Oct follow-ups)
  3. Playlist: *Bank of England decisions*
  4. Playlist: *Budget 2026 explained*
  5. Playlist: *5 things to do* (action-oriented evergreen)
  6. Shorts

### 2.5 Settings (YouTube Studio → Settings)
**General:** Currency **GBP**.

**Channel → Basic info:** Country of residence **United Kingdom**. Keywords (comma-separated, ≤500 chars):
```
uk money news, uk mortgage rates, interest rates uk, bank of england, budget 2026, uk tax, cost of living uk, remortgage, uk personal finance, uk economy explained, inflation uk, gilts, sterling signal
```

**Channel → Advanced settings:**
- Audience: **"No, set this channel as not made for kids"**
- Google Ads account linking: skip for now
- Automatic captions: leave on (you also have burned-in captions)

**Channel → Feature eligibility:** phone-verify (done in 2.1), then complete **Advanced features** via video verification or valid ID when prompted — this lifts daily upload limits and enables more end-screen links.

**Upload defaults → Basic info** (saves time on every upload):
- Title: leave blank
- Description template:
```
[Hook line]

⏱ CHAPTERS
00:00 

📊 KEY NUMBERS


📚 SOURCES


⚠️ This is information, not financial advice. Speak to an FCA-regulated adviser about your own situation.

🔔 Subscribe: https://www.youtube.com/@SterlingSignal?sub_confirmation=1

#UKMortgage #UKEconomy #CostOfLiving
```
- Visibility: **Private** (so you can add end screens/cards before scheduling)
- Tags: `uk money news, sterling signal, uk mortgage rates, interest rates uk, bank of england, uk economy`

**Upload defaults → Advanced settings:**
- Licence: Standard YouTube
- Category: **News & Politics**
- Video language: **English (United Kingdom)**; Caption certification: "This content has never aired on television in the US"
- Comments: **Hold potentially inappropriate comments for review**; sort by **Top**
- ✅ Allow embedding · ✅ Publish to subscriptions feed · ✅ Show how many viewers like this video
- Altered content: when uploading, tick **Yes** for realistic AI/synthetic content (synthetic voice + AI b-roll) — it's a policy requirement, not optional

**Community → Automated filters:**
- Add moderators once you have help
- **Blocked words:** `crypto, forex signal, whatsapp, telegram, dm me, investment manager, mentor, +44, +1` — finance channels get scam-bot comments from day one; this list catches most of them
- ✅ Block links (holds comments with URLs for review)

**Permissions:** add a second Google account as **Manager** now (recovery + future editor access).

### 2.6 Monetisation readiness (YouTube Partner Programme)
- Thresholds (2026): **1,000 subscribers + 4,000 public watch hours in 12 months** (or 10 M Shorts views in 90 days). The 500-sub / 3,000-hour tier unlocks fan funding only.
- Set up **Google AdSense** when you hit 500 subs so there's no delay later.
- Finance is a high-CPM niche (UK finance RPM is typically several times the YouTube average) — worth designing for mid-rolls: videos ≥ 8 min get manual mid-roll placement, so plan future episodes at 8–10 min once the audience is proven.
- Keep AI-disclosure honest and every claim sourced: "repetitious" or "mass-produced" AI content can fail YPP review; commentary with original analysis, on-screen sourcing and a consistent presenter voice passes.

---

## 3. First 30 days: launch plan

| When | What |
|---|---|
| Day 0 | Create channel, apply brand kit, all settings above, upload **Mortgage Shock** (Private) → add end screen (2 slots + subscribe) + cards → schedule for **17:30 UK** |
| Day 0 | Cut 2 Shorts from it (hook 00:03–00:49; the £321 maths 03:15–03:52), vertical 1080×1920, with the watermark; post on YouTube Shorts + TikTok + Instagram Reels, link to the long-form |
| Day 0–1 | Pin the "what rate are you coming off?" comment; reply to **every** comment in the first 6 hours (drives the algorithm's early engagement signal) |
| Day 1 | Community post + newsletter #1; share in r/UKPersonalFinance-style communities **only where self-promotion rules allow** (better: answer questions there and let people find the channel) |
| Day 7 | Video 2: *"Should you fix for 2 or 5 years right now?"* (search-led, evergreen) |
| **17 Sept** | Video 3: **Bank of England decision — same-day reaction** (publish within 2 hours of 12:00 announcement; title it the moment the decision drops) |
| Day 21 | Video 4: *"The 5 taxes most likely to rise on 28 October"* (pre-Budget search wave starts ~2 weeks out) |
| **28 Oct** | Video 5: **Budget 2026 — what it means for you** (same-day; this is the year's biggest UK finance search spike) |

Cadence after launch: **1 long-form per week + 2–3 Shorts**, and a same-day video for every scheduled BoE / ONS inflation / Budget date. Predictable dates are your unfair advantage: put the whole 2026–27 BoE and ONS calendar in your planner now.

---

## 4. Analytics to watch (Studio → Analytics)
- **CTR** on impressions: target ≥ 6 % in the first 48 h. Below 4 % → swap the thumbnail (Studio's Test & Compare lets you A/B three).
- **Average view duration**: target ≥ 45 % of runtime (≈ 3:00 on a 6:41 video). Watch the retention graph: a dip at a chapter start means the chapter card needs a stronger hook line.
- **Returning viewers vs new**: news topics bring new viewers; the playlists and "5 things" evergreen turn them into returning ones.
- **Traffic source: Browse vs Search**: Browse growth = the algorithm trusts the channel; Search growth = titles/descriptions are working. You want both, but Browse is what makes a video go from 50 k to millions.

---

## 5. Re-generate the brand kit
```bash
cd youtube/mortgage-shock-2026/brand
../../../.venv/bin/python make_brand.py     # or any python with Pillow
```
Edit colours, tagline or the ticker numbers at the top of `make_brand.py`; everything (logo, watermark, banner + device previews) re-renders in ~3 s.
