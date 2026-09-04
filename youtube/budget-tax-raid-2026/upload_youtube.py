#!/usr/bin/env python3
"""Upload `output/final_video.mp4` + thumbnail to the Sterling Signal YouTube channel.

Metadata source of truth:
  * title / tags / category  -> this script (title A + tag set from YOUTUBE_METADATA.md)
  * description              -> output/description.txt (chapters already merged in)
  * chapters                 -> output/chapters.txt (already merged into description.txt)

Usage (from this folder):
  /home/user/.venv/bin/python upload_youtube.py --dry-run
  /home/user/.venv/bin/python upload_youtube.py --privacy private
  /home/user/.venv/bin/python upload_youtube.py --privacy private \
      --publish-at 2026-09-07T07:00:00+01:00

Credentials are read from --client-secret / --token (defaults: /home/user/uploads/,
falling back to /home/user/.yt-creds/). The refreshed token is written back to the
token file it was read from. Neither file is ever committed to git.

Not possible via the Data API (do in YouTube Studio after upload):
  * "Altered or synthetic content" = Yes disclosure (synthetic voice / AI b-roll)
  * premiere mode, end screens, info cards, playlists-on-thumbnails etc.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO = os.path.join(HERE, "output", "final_video.mp4")
THUMB = os.path.join(HERE, "output", "thumbnail.jpg")
DESCRIPTION = os.path.join(HERE, "output", "description.txt")

TITLE = ("The £25 BILLION Tax Raid Coming 28 October – "
         "7 Taxes About To Rise (UK Budget 2026)")
TAGS = [t.strip() for t in (
    "budget 2026,autumn budget 2026,uk budget october 2026,john healey budget,"
    "tax rises 2026,uk tax rises,capital gains tax 2026,capital gains tax uk,"
    "inheritance tax changes,pension tax relief,pension tax free lump sum,"
    "isa allowance 2027,cash isa cut,fiscal drag,frozen tax thresholds,"
    "higher rate tax,andy burnham tax,labour tax rises,wealth tax uk,"
    "uk personal finance,money saving uk,tax planning uk,"
    "what to do before the budget,uk economy news,martin lewis budget,"
    "sterling signal").split(",")]
CATEGORY_NEWS_POLITICS = "25"
PLAYLISTS = ["Budget 2026 explained", "Mortgage Shock 2026"]
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def find_creds(cli_value: str | None, names: list[str]) -> str | None:
    if cli_value:
        return cli_value if os.path.exists(cli_value) else None
    for d in ("/home/user/uploads", "/home/user/.yt-creds"):
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return None


def load_credentials(secret_path: str, token_path: str) -> Credentials:
    secret = json.load(open(secret_path))
    inst = secret.get("installed", secret.get("web", secret))
    tok = json.load(open(token_path))
    creds = Credentials(
        token=tok.get("access_token"),
        refresh_token=tok.get("refresh_token"),
        token_uri=inst.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=inst.get("client_id"),
        client_secret=inst.get("client_secret"),
        scopes=tok.get("scopes") or SCOPES,
    )
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return creds


def save_token(creds: Credentials, token_path: str) -> None:
    data = json.load(open(token_path))
    data.update({
        "token": creds.token,
        "refresh_token": creds.refresh_token or data.get("refresh_token"),
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or data.get("scopes") or SCOPES),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    })
    data.pop("access_token", None)  # keep file shape consistent
    json.dump(data, open(token_path, "w"), indent=2)


def build_body(args) -> dict:
    description = open(DESCRIPTION, encoding="utf-8").read().strip("\n")
    problems = []
    if len(TITLE) > 100:
        problems.append(f"title {len(TITLE)} chars > 100")
    if len(description) > 5000:
        problems.append(f"description {len(description)} chars > 5000")
    tag_blob = ",".join(TAGS)
    if len(tag_blob) > 500:
        problems.append(f"tags {len(tag_blob)} chars > 500")
    if problems:
        sys.exit("metadata invalid: " + "; ".join(problems))

    status = {
        "privacyStatus": args.privacy,
        "selfDeclaredMadeForKids": False,
        "embeddable": True,
        "license": "youtube",
    }
    if args.publish_at:
        if args.privacy != "private":
            sys.exit("--publish-at requires --privacy private (scheduled publish)")
        status["publishAt"] = args.publish_at
    return {
        "snippet": {
            "title": TITLE,
            "description": description,
            "tags": TAGS,
            "categoryId": CATEGORY_NEWS_POLITICS,
            "defaultLanguage": "en-GB",
            "defaultAudioLanguage": "en-GB",
        },
        "status": status,
        "recordDetails": {"recordingDate": "2026-09-04"},
    }, tag_blob


def upload(youtube, body: dict) -> str:
    media = MediaFileUpload(VIDEO, mimetype="video/mp4",
                            chunksize=16 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status,recordDetails",
        body=body,
        media_body=media,
        notifySubscribers=True,
    )
    response = None
    started = time.time()
    while response is None:
        status, response = request.next_chunk(num_retries=5)
        if status:
            mb = status.resumable_progress / 1e6
            tot = status.total_size / 1e6
            print(f"  uploaded {mb:6.1f}/{tot:.1f} MB "
                  f"({status.progress() * 100:5.1f}%) "
                  f"{time.time() - started:5.0f}s", flush=True)
    return response["id"]


def set_thumbnail(youtube, video_id: str) -> None:
    youtube.thumbnails().set(
        videoId=video_id,
        media=MediaFileUpload(THUMB, mimetype="image/jpeg"),
    ).execute()


def add_to_playlists(youtube, video_id: str) -> list[str]:
    done, missing = [], []
    try:
        pls = youtube.playlists().list(part="snippet", mine=True,
                                       maxResults=50).execute()
    except HttpError as e:
        print(f"  ! cannot list playlists ({e})")
        return missing
    by_title = {p["snippet"]["title"].strip().lower(): p["id"]
                for p in pls.get("items", [])}
    for name in PLAYLISTS:
        pid = by_title.get(name.lower())
        if not pid:
            missing.append(name)
            continue
        youtube.playlistItems().insert(
            part="snippet",
            body={"snippet": {"playlistId": pid,
                              "resourceId": {"kind": "youtube#video",
                                             "videoId": video_id}}},
        ).execute()
        done.append(name)
    print(f"  playlists: added to {done or 'none'}; missing: {missing or 'none'}")
    return missing


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-secret")
    ap.add_argument("--token")
    ap.add_argument("--privacy", default="private",
                    choices=["private", "unlisted", "public"])
    ap.add_argument("--publish-at", help="ISO8601 scheduled publish time")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    body, tag_blob = build_body(args)
    print(f"title ({len(TITLE)} chars): {TITLE}")
    print(f"description: {len(body['snippet']['description'])} chars, "
          f"tags: {len(tag_blob)} chars, category: {CATEGORY_NEWS_POLITICS}, "
          f"privacy: {args.privacy}"
          + (f", publishAt: {args.publish_at}" if args.publish_at else ""))
    print(f"video: {VIDEO} ({os.path.getsize(VIDEO) / 1e6:.1f} MB), "
          f"thumb: {THUMB}")
    if args.dry_run:
        print("dry run — no API calls made")
        return

    secret_path = find_creds(args.client_secret, ["client_secret.json"])
    token_path = find_creds(args.token, ["token.json"])
    if not secret_path or not token_path:
        sys.exit("credentials not found: expected client_secret.json and "
                 "token.json in /home/user/uploads/ or /home/user/.yt-creds/ "
                 "(or pass --client-secret / --token)")
    print(f"creds: {secret_path} + {token_path}")
    creds = load_credentials(secret_path, token_path)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    me = youtube.channels().list(part="snippet,brandingSettings",
                                 mine=True).execute()
    ch = me["items"][0]["snippet"]["title"]
    print(f"authenticated channel: {ch}")

    video_id = upload(youtube, body)
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"UPLOADED {video_id} -> {url}")

    try:
        set_thumbnail(youtube, video_id)
        print("thumbnail set")
    except HttpError as e:
        print(f"! thumbnail failed (enable custom thumbnails / phone "
              f"verification): {e}")
    add_to_playlists(youtube, video_id)
    save_token(creds, token_path)
    print("DONE — still to do in Studio: synthetic-content disclosure = Yes, "
          "premiere/schedule if wanted, end screen + cards (see "
          "YOUTUBE_METADATA.md §6)")
    print(url)


if __name__ == "__main__":
    main()
