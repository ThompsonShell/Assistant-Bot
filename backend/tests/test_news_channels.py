import json

from app.config import settings
from app.integrations import channels as ch
from app.integrations.news import format_news, parse_feed

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>Claude 5 released</title><link>https://ex.com/a</link></item>
<item><title>Chip news</title><link>https://ex.com/b</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom story</title><link href="https://ex.com/atom1"/></entry>
</feed>"""


def _channel_page(posts):
    """Build a minimal t.me/s/ style page. posts = [(id, text_or_None)]."""
    blocks = []
    for pid, text in posts:
        body = f'<div class="tgme_widget_message_text js-message_text" dir="auto">{text}</div>' if text else ""
        blocks.append(
            f'<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" '
            f'data-post="testchan/{pid}">{body}</div></div>'
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


def test_parse_rss_and_atom():
    rss = parse_feed(RSS, "ex.com")
    assert [i.title for i in rss] == ["Claude 5 released", "Chip news"]
    assert rss[0].link == "https://ex.com/a"
    atom = parse_feed(ATOM, "ex.com")
    assert atom[0].title == "Atom story" and atom[0].link == "https://ex.com/atom1"


def test_format_news_empty_and_list():
    assert "topilmadi" in format_news([])
    out = format_news(parse_feed(RSS, "ex.com"))
    assert "1. Claude 5 released" in out and "https://ex.com/a" in out


def test_parse_channel_html_extracts_text_posts_only():
    page = _channel_page([(5, "Hello <b>AI</b> &amp; LLM"), (6, None), (7, "Second post")])
    posts = ch.parse_channel_html(page, "testchan")
    assert [p.post_id for p in posts] == [5, 7]  # photo-only post (6) skipped
    assert posts[0].text == "Hello AI & LLM"      # tags stripped, entities decoded
    assert posts[0].link == "https://t.me/testchan/5"


def test_keywords_are_whole_word_and_case_insensitive():
    assert ch.matches_keywords("new llm model", ["LLM"]) == ["LLM"]
    assert ch.matches_keywords("Gallium is cool", ["AI"]) == []  # no substring match
    assert ch.matches_keywords("OpenAI shipped", ["openai", "AI"]) == ["openai"]


def test_collect_relevant_baseline_then_forward(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "watch_channels", "testchan")
    monkeypatch.setattr(settings, "channel_keywords", "AI,Python")
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(settings, "channel_state_file", str(state_file))

    pages = {"v": _channel_page([(1, "old AI post")])}
    monkeypatch.setattr(ch, "fetch_channel", lambda channel, http=None: ch.parse_channel_html(pages["v"], channel))

    # First run: baseline only, nothing forwarded even though it matches.
    assert ch.collect_relevant() == []
    assert json.loads(state_file.read_text()) == {"testchan": 1}

    # New posts arrive: one relevant, one not.
    pages["v"] = _channel_page([(1, "old AI post"), (2, "Python 3.14 is out"), (3, "lunch menu")])
    got = ch.collect_relevant()
    assert len(got) == 1
    post, hits = got[0]
    assert post.post_id == 2 and hits == ["Python"]

    # Same page again: nothing new, nothing re-sent.
    assert ch.collect_relevant() == []


def test_channel_watch_noop_without_channels(monkeypatch):
    from app.jobs import channel_watch

    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    monkeypatch.setattr(settings, "watch_channels", "")
    assert channel_watch.run_channel_watch() == 0


def test_news_command_and_channels_command(monkeypatch):
    from app.jobs import telegram_bot as tb
    from app.db import Base, make_engine, make_sessionmaker

    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_sessionmaker(engine)()

    monkeypatch.setattr(settings, "news_enabled", True)
    monkeypatch.setattr("app.integrations.news.fetch_news", lambda limit=8, http=None, topic="tech": parse_feed(RSS, "ex.com")[:limit])
    assert "Claude 5 released" in tb.handle_text(db, None, "/news")

    monkeypatch.setattr(settings, "watch_channels", "")
    assert "WATCH_CHANNELS" in tb.handle_text(db, None, "/channels")
    monkeypatch.setattr(settings, "watch_channels", "techchan, @pychan")
    monkeypatch.setattr(settings, "channel_keywords", "AI,Python")
    out = tb.handle_text(db, None, "/channels")
    assert "@techchan" in out and "@pychan" in out and "Python" in out


# ── Photo cards ───────────────────────────────────────────────────────

RSS_RICH = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Big chip launch</title><link>https://ex.com/chip</link>
<description>&lt;p&gt;The company unveiled its newest processor today, promising big gains.&lt;/p&gt;</description>
<media:content url="https://ex.com/chip.jpg" medium="image"/></item>
<item><title>Inline image story</title><link>https://ex.com/inline</link>
<content:encoded>&lt;img src="https://ex.com/inline.png"/&gt;&lt;p&gt;Body text that is long enough to count.&lt;/p&gt;</content:encoded></item>
<item><title>HN style</title><link>https://ex.com/hn</link>
<description>Article URL: https://x.com Comments URL: https://y.com Points: 5</description></item>
</channel></rss>"""


def test_parse_feed_extracts_summary_and_image():
    items = {i.title: i for i in parse_feed(RSS_RICH, "ex.com")}
    chip = items["Big chip launch"]
    assert chip.image == "https://ex.com/chip.jpg"
    assert chip.summary.startswith("The company unveiled")
    assert "<p>" not in chip.summary
    assert items["Inline image story"].image == "https://ex.com/inline.png"
    # Hacker News style descriptions carry no useful text and no image.
    hn = items["HN style"]
    assert hn.summary == "" and hn.image is None


def test_card_caption_short_and_with_link_at_bottom():
    from app.integrations.news import NewsItem, card_caption, shorten

    long_text = "word " * 200
    item = NewsItem("Title", "https://ex.com/a", "ex.com", summary=shorten(long_text))
    cap = card_caption(item)
    assert cap.startswith("📰 Title")
    assert len(item.summary) <= 301           # summary is cut short, not full text
    assert cap.rstrip().endswith("— ex.com")
    assert "🔗 https://ex.com/a" in cap
    assert len(cap) < 1024

    # No summary: just headline + link, nothing padded in between.
    bare = card_caption(NewsItem("Only title", "https://ex.com/b", "ex.com"))
    assert bare.count("\n\n") == 1


class _Http:
    """Records posts: (endpoint, payload). Optionally rejects photos."""

    def __init__(self, reject_photo=False):
        self.calls = []
        self.reject_photo = reject_photo

    def post(self, url, json=None, **kw):
        self.calls.append((url.rsplit("/", 1)[-1], json))

        class R:
            status_code = 400 if (self.reject_photo and url.endswith("sendPhoto")) else 200

        return R()

    def get(self, *a, **k):  # no og:image lookups in these tests
        raise RuntimeError("offline")


def test_send_news_cards_photo_and_text_fallback(monkeypatch):
    from app.integrations.news import NewsItem
    from app.jobs import telegram_bot as tb

    monkeypatch.setattr(settings, "news_enabled", True)
    items = [
        NewsItem("With pic", "https://ex.com/1", "ex.com", summary="Short blurb that is fine.", image="https://ex.com/1.jpg"),
        NewsItem("No pic", "https://ex.com/2", "ex.com"),
    ]
    monkeypatch.setattr("app.integrations.news.fetch_news", lambda limit=8, http=None, topic="tech": items)

    http = _Http()
    assert tb.send_news_cards(http, 1, limit=5, heading="Head") == 2
    kinds = [c[0] for c in http.calls]
    assert kinds == ["sendMessage", "sendPhoto", "sendMessage"]   # heading, photo card, text card
    photo = http.calls[1][1]
    assert photo["photo"] == "https://ex.com/1.jpg"
    assert "https://ex.com/1" in photo["caption"]

    # Telegram can't load the image -> falls back to a text card with the link.
    bad = _Http(reject_photo=True)
    for it in items:
        it.image = it.image  # unchanged
    tb.send_news_cards(bad, 1, limit=5)
    assert [c[0] for c in bad.calls] == ["sendPhoto", "sendMessage", "sendMessage"]
    assert "https://ex.com/1" in bad.calls[1][1]["text"]


def test_news_command_sends_cards(monkeypatch):
    from app.integrations.news import NewsItem
    from app.jobs import telegram_bot as tb
    from app.db import Base, make_engine, make_sessionmaker

    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "news_enabled", True)
    monkeypatch.setattr(
        "app.integrations.news.fetch_news",
        lambda limit=8, http=None, topic="tech": [NewsItem("T", "https://ex.com/t", "ex.com", image="https://ex.com/t.jpg")],
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    http = _Http()
    tb.process_update(http, make_sessionmaker(engine), None, {"message": {"chat": {"id": 999}, "text": "/news"}})
    assert "sendPhoto" in [c[0] for c in http.calls]


def test_channel_post_image_parsed_and_forwarded(monkeypatch):
    page = (
        '<div class="tgme_widget_message_wrap"><div data-post="testchan/9">'
        '<a class="tgme_widget_message_photo_wrap" '
        "style=\"width:200px;background-image:url('https://cdn.example/p.jpg')\"></a>"
        '<div class="tgme_widget_message_text js-message_text">New AI model</div></div></div>'
    )
    post = ch.parse_channel_html(page, "testchan")[0]
    assert post.image == "https://cdn.example/p.jpg"
