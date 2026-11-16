"""Global tech news from public RSS/Atom feeds (no API key needed).

Feeds are configured via NEWS_FEEDS (comma-separated URLs). Each feed is
fetched independently, so one broken source never hides the others.

Every item carries a short summary and, when the feed or the article page
offers one, a cover image — so the bot can send each story as a photo card
(image + short text + link) instead of a bare headline.
"""
from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from ..config import settings

logger = logging.getLogger("lifeos.news")

_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}"

_TAG_RE = re.compile(r"<[^>]+>")
_IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:image["\']',
    re.IGNORECASE,
)
_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")

SUMMARY_LIMIT = 300  # a short blurb is enough; the link has the full story


@dataclass
class NewsItem:
    title: str
    link: str
    source: str  # feed host, e.g. "techcrunch.com"
    summary: str = ""
    image: str | None = None


def feed_urls() -> list[str]:
    return [u.strip() for u in (settings.news_feeds or "").split(",") if u.strip()]


def _http_url(url: str | None) -> str | None:
    """Return the URL only if it is a plain http(s) URL (never file:, data:, ...)."""
    if url and urlparse(url.strip()).scheme in ("http", "https"):
        return url.strip()
    return None


def shorten(text: str, limit: int = SUMMARY_LIMIT) -> str:
    """Cut text at a word boundary; short text is returned unchanged."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:-") + "…"


def _clean(raw: str | None) -> str:
    text = html.unescape(_TAG_RE.sub(" ", raw or ""))
    return re.sub(r"\s+", " ", text).strip()


def _summary(raw: str | None, title: str) -> str:
    """Short plain-text blurb, or "" when the feed gives nothing useful.

    Hacker News descriptions are just "Article URL / Comments URL / Points",
    and some feeds repeat the headline — neither helps the reader.
    """
    text = _clean(raw)
    if len(text) < 25 or "Article URL:" in text:
        return ""
    if text.lower().startswith(title.lower()):
        text = text[len(title):].lstrip(" -:—.")
    return shorten(text) if len(text) >= 25 else ""


def _media_image(el: ET.Element) -> str | None:
    """Image URL from media:content / media:thumbnail / enclosure, if any."""
    for tag in (_MEDIA + "content", _MEDIA + "thumbnail"):
        for m in el.findall(tag):
            url = _http_url(m.get("url"))
            kind = (m.get("medium") or m.get("type") or "").lower()
            if url and (kind.startswith("image") or url.lower().split("?")[0].endswith(_IMG_EXT) or tag.endswith("thumbnail")):
                return url
    enc = el.find("enclosure")
    if enc is not None and (enc.get("type") or "").startswith("image"):
        return _http_url(enc.get("url"))
    return None


def _first_img(*fragments: str | None) -> str | None:
    for frag in fragments:
        m = _IMG_RE.search(frag or "")
        if m and _http_url(html.unescape(m.group(1))):
            return html.unescape(m.group(1))
    return None


def parse_feed(xml_text: str, source: str) -> list[NewsItem]:
    """Parse an RSS 2.0 or Atom document into NewsItems (newest-first as given)."""
    root = ET.fromstring(xml_text)
    items: list[NewsItem] = []

    # RSS 2.0: <rss><channel><item>
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not (title and link):
            continue
        desc = it.findtext("description")
        body = it.findtext(_CONTENT + "encoded")
        items.append(
            NewsItem(
                title=title,
                link=link,
                source=source,
                summary=_summary(desc or body, title),
                image=_media_image(it) or _first_img(body, desc),
            )
        )

    # Atom: <feed><entry><link href="..."/>
    for entry in root.iter(_ATOM + "entry"):
        title = (entry.findtext(_ATOM + "title") or "").strip()
        link = ""
        for link_el in entry.findall(_ATOM + "link"):
            if link_el.get("rel") in (None, "alternate") and link_el.get("href"):
                link = link_el.get("href").strip()
                break
        if not (title and link):
            continue
        summ = entry.findtext(_ATOM + "summary")
        content = entry.findtext(_ATOM + "content")
        items.append(
            NewsItem(
                title=title,
                link=link,
                source=source,
                summary=_summary(summ or content, title),
                image=_media_image(entry) or _first_img(content, summ),
            )
        )

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


def fetch_og_image(url: str, http: httpx.Client) -> str | None:
    """Cover image from the article page's og:image tag (best effort)."""
    if not _http_url(url):
        return None
    try:
        resp = http.get(url, timeout=8)
        resp.raise_for_status()
        m = _OG_RE.search(resp.text[:300_000])
    except Exception:  # noqa: BLE001 - an image is a nice-to-have
        return None
    if not m:
        return None
    return _http_url(urljoin(url, html.unescape(m.group(1) or m.group(2))))


def ensure_images(items: list[NewsItem], http: httpx.Client, max_lookups: int = 6) -> None:
    """Fill in missing cover images from the article pages (bounded lookups)."""
    lookups = 0
    for it in items:
        if it.image or lookups >= max_lookups:
            continue
        lookups += 1
        it.image = fetch_og_image(it.link, http)


def card_caption(item: NewsItem) -> str:
    """Photo caption: headline, short summary, then the link at the bottom.

    Short stories are not padded: when the feed has no usable text, only the
    headline and link are shown. Stays well under Telegram's 1024-char caption
    limit (headline <= 200, summary <= 300).
    """
    parts = [f"📰 {shorten(item.title, 200)}"]
    if item.summary:
        parts.append(item.summary)
    parts.append(f"🔗 {item.link}\n— {item.source}")
    return "\n\n".join(parts)


def format_news(items: list[NewsItem], title: str = "🌍 *Texnologiya yangiliklari*") -> str:
    """Plain-text digest (used as a fallback when cards can't be sent)."""
    if not items:
        return f"{title}\n\nHozircha yangilik topilmadi."
    lines = [title, ""]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {it.title}")
        lines.append(f"   {it.source} — {it.link}")
    return "\n".join(lines)
