"""Watch selected PUBLIC Telegram channels and forward only relevant posts.

How it reads a channel: every public channel has a web preview at
https://t.me/s/<username> that lists its recent posts without any login. The
bot never joins channels and never reads private chats or channels — only the
public previews of the usernames listed in WATCH_CHANNELS.

Relevance: a post is forwarded only when its text contains one of the
CHANNEL_KEYWORDS (whole-word, case-insensitive). Everything else is ignored.

State: the newest post id seen per channel is stored in a small JSON file so
each post is forwarded at most once. The first run only records a baseline and
sends nothing, so adding a busy channel never floods you with its history.
"""
from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import settings

logger = logging.getLogger("lifeos.channels")

_BASE = "https://t.me/s/"
_WRAP_SPLIT = "tgme_widget_message_wrap"
_POST_RE = re.compile(r'data-post="([A-Za-z0-9_]+)/(\d+)"')
_TEXT_RE = re.compile(
    r'tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


@dataclass
class ChannelPost:
    channel: str
    post_id: int
    text: str

    @property
    def link(self) -> str:
        return f"https://t.me/{self.channel}/{self.post_id}"


def _csv(value: str | None) -> list[str]:
    return [v.strip().lstrip("@") for v in (value or "").split(",") if v.strip()]


def watched_channels() -> list[str]:
    return _csv(settings.watch_channels)


def keywords() -> list[str]:
    return [k for k in _csv(settings.channel_keywords)]


def parse_channel_html(page: str, channel: str) -> list[ChannelPost]:
    """Extract the text posts from a t.me/s/<channel> preview page."""
    posts: list[ChannelPost] = []
    for block in page.split(_WRAP_SPLIT)[1:]:
        meta = _POST_RE.search(block)
        text_m = _TEXT_RE.search(block)
        if not meta or not text_m:  # photo/video-only post, or not a post block
            continue
        raw = _BR_RE.sub("\n", text_m.group(1))
        text = html.unescape(_TAG_RE.sub("", raw)).strip()
        if text:
            posts.append(ChannelPost(channel=channel, post_id=int(meta.group(2)), text=text))
    posts.sort(key=lambda p: p.post_id)  # oldest first
    return posts


def matches_keywords(text: str, words: list[str]) -> list[str]:
    """Return the keywords found in the text (whole-word, case-insensitive)."""
    found = []
    for w in words:
        if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.IGNORECASE):
            found.append(w)
    return found


def fetch_channel(channel: str, http: httpx.Client | None = None) -> list[ChannelPost]:
    own = http is None
    client = http or httpx.Client(timeout=20, follow_redirects=True)
    try:
        resp = client.get(_BASE + channel)
        resp.raise_for_status()
        return parse_channel_html(resp.text, channel)
    finally:
        if own:
            client.close()


def _load_state(path: Path) -> dict[str, int]:
    try:
        return {k: int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    except (FileNotFoundError, ValueError, TypeError):
        return {}


def _save_state(path: Path, state: dict[str, int]) -> None:
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def collect_relevant(http: httpx.Client | None = None) -> list[tuple[ChannelPost, list[str]]]:
    """Check every watched channel and return NEW relevant posts with the
    keywords that matched. Updates the stored baseline as it goes."""
    state_path = Path(settings.channel_state_file)
    state = _load_state(state_path)
    words = keywords()
    results: list[tuple[ChannelPost, list[str]]] = []

    for channel in watched_channels():
        try:
            posts = fetch_channel(channel, http=http)
        except Exception as exc:  # noqa: BLE001 - one channel must not stop the rest
            logger.warning(
                "channel fetch failed",
                extra={"extra_fields": {"channel": channel, "error": str(exc)[:200]}},
            )
            continue
        if not posts:
            continue

        newest = max(p.post_id for p in posts)
        if channel not in state:
            # First time: record a baseline silently, forward nothing.
            state[channel] = newest
            continue

        last = state[channel]
        for post in (p for p in posts if p.post_id > last):
            hits = matches_keywords(post.text, words)
            if hits:
                results.append((post, hits))
        state[channel] = max(last, newest)

    _save_state(state_path, state)
    return results


def format_post(post: ChannelPost, hits: list[str]) -> str:
    snippet = post.text if len(post.text) <= 600 else post.text[:597] + "..."
    return (
        f"📣 @{post.channel} — kalit so'z: {', '.join(hits)}\n\n"
        f"{snippet}\n\n{post.link}"
    )
