"""Lightweight web lookup helpers used by in-app Google search previews."""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterable

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0 Safari/537.36"
)

_SKIP_TITLES = {
    "cached", "similar", "translate this page", "feedback", "more results",
    "next", "previous",
}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    domain: str = ""


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_A_RE = re.compile(r"<a\b[^>]*href=(['\"])(.*?)\1[^>]*>(.*?)</a>", re.I | re.S)


def google_search_url(query: str, limit: int = 6) -> str:
    q = urllib.parse.quote_plus(str(query or "").strip())
    num = max(1, min(10, int(limit or 6)))
    return f"https://www.google.com/search?hl=en&gbv=1&num={num}&q={q}"


def _strip_tags(text: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text or "", flags=re.I | re.S)
    text = _TAG_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", html.unescape(text)).strip()


def _clean_href(href: str) -> str:
    href = html.unescape(str(href or "").strip())
    if not href:
        return ""
    if href.startswith("/url?"):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("q", [""])[0]
        return urllib.parse.unquote(q)
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return ""


def parse_google_results(markup: str, limit: int = 6) -> list[dict]:
    """Best-effort extraction from Google's lightweight HTML results page."""
    page = str(markup or "")
    out: list[dict] = []
    seen: set[str] = set()
    for m in _A_RE.finditer(page):
        href = _clean_href(m.group(2))
        if not href or href in seen:
            continue
        host = urllib.parse.urlsplit(href).netloc.lower()
        if not host or host.endswith("google.com") or host.endswith("google.sa"):
            continue
        title = _strip_tags(m.group(3))
        if not title or title.lower() in _SKIP_TITLES or len(title) < 3:
            continue
        tail = page[m.end():m.end() + 900]
        snippet = _strip_tags(tail)
        if snippet.lower().startswith(title.lower()):
            snippet = snippet[len(title):].lstrip(" :-|·")
        snippet = snippet[:240].rstrip()
        seen.add(href)
        out.append({
            "title": title[:160],
            "url": href,
            "snippet": snippet,
            "domain": host,
        })
        if len(out) >= max(1, int(limit or 6)):
            break
    return out


def fetch_google_results(query: str, limit: int = 6, timeout: float = 8.0) -> list[dict]:
    q = str(query or "").strip()
    if not q:
        return []
    req = urllib.request.Request(
        google_search_url(q, limit),
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="ignore")
    return parse_google_results(raw, limit=limit)


def results_html(query: str, results: Iterable[dict], error: str = "") -> str:
    q = html.escape(str(query or "").strip())
    rows = []
    for r in results:
        title = html.escape(str(r.get("title") or r.get("url") or "Result"))
        url = html.escape(str(r.get("url") or ""))
        dom = html.escape(str(r.get("domain") or ""))
        snip = html.escape(str(r.get("snippet") or ""))
        rows.append(
            "<div style='margin:0 0 12px 0;padding:10px 12px;"
            "border:1px solid #d8e1ea;border-radius:10px;background:#ffffff;'>"
            f"<div style='color:#5f6368;font-size:11px'>{dom}</div>"
            f"<div><a href='{url}' style='font-size:15px;color:#1a0dab;text-decoration:none;'>"
            f"<b>{title}</b></a></div>"
            f"<div style='color:#202124;font-size:12px;margin-top:4px'>{snip or 'Open result'}</div>"
            "</div>"
        )
    if not rows:
        rows.append(
            "<div style='padding:12px;border:1px solid #d8e1ea;border-radius:10px;"
            "background:#ffffff;color:#5f6368'>"
            + html.escape(error or "No preview results were returned. You can still open the search in Google.")
            + "</div>"
        )
    open_url = html.escape(google_search_url(query, limit=8))
    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;background:#f5f7fa;padding:10px'>"
        f"<div style='font-size:12px;color:#5f6368;margin-bottom:8px'>Google preview for: <b>{q}</b></div>"
        + "".join(rows)
        + f"<div style='margin-top:8px'><a href='{open_url}'>Open full Google search</a></div>"
        + "</div>"
    )
