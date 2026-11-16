"""Global tech news from public RSS/Atom feeds (no API key needed).

Feeds are configured via NEWS_FEEDS (comma-separated URLs). Each feed is
fetched independently, so one broken source never hides the others.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger("lifeos.news")

_ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class NewsItem:
    title: str
    link: str
    source: str  # feed host, e.g. "techcrunch.com"


def feed_urls() -> list[str]:
    return [u.strip() for u in (settings.news_feeds or "").split(",") if u.strip()]


def parse_feed(xml_text: str, source: str) -> list[NewsItem]:
    """Parse an RSS 2.0 or Atom document into NewsItems (newest-first as given)."""
    root = ET.fromstring(xml_text)
    items: list[NewsItem] = []

    # RSS 2.0: <rss><channel><item>
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if title and link:
            items.append(NewsItem(title=title, link=link, source=source))

    # Atom: <feed><entry><link href="..."/>
    for entry in root.iter(_ATOM + "entry"):
        title = (entry.findtext(_ATOM + "title") or "").strip()
        link_el = entry.find(_ATOM + "link")
        link = (link_el.get("href") if link_el is not None else "") or ""
        if title and link:
            items.append(NewsItem(title=title, link=link.strip(), source=source))

    return items


def fetch_news(limit: int = 8, http: httpx.Client | None = None) -> list[NewsItem]:
    """Fetch all configured feeds and return the merged, de-duplicated headlines.

    Items are interleaved round-robin across sources so one busy feed does not
    push every other source out of the list.
    """
    own = http is None
    client = http or httpx.Client(timeout=15, follow_redirects=True)
    per_feed: list[list[NewsItem]] = []
    try:
        for url in feed_urls():
            source = urlparse(url).netloc.removeprefix("www.")
            try:
                resp = client.get(url)
                resp.raise_for_status()
                per_feed.append(parse_feed(resp.text, source))
            except Exception as exc:  # noqa: BLE001 - keep other feeds working
                logger.warning(
                    "news feed failed",
                    extra={"extra_fields": {"feed": source, "error": str(exc)[:200]}},
                )
    finally:
        if own:
            client.close()

    merged: list[NewsItem] = []
    seen: set[str] = set()
    for round_idx in range(max((len(f) for f in per_feed), default=0)):
        for feed in per_feed:
            if round_idx < len(feed) and feed[round_idx].link not in seen:
                seen.add(feed[round_idx].link)
                merged.append(feed[round_idx])
    return merged[:limit]


def format_news(items: list[NewsItem], title: str = "🌍 *Texnologiya yangiliklari*") -> str:
    if not items:
        return f"{title}\n\nHozircha yangilik topilmadi."
    lines = [title, ""]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {it.title}")
        lines.append(f"   {it.source} — {it.link}")
    return "\n".join(lines)
