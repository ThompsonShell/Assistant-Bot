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
    monkeypatch.setattr("app.integrations.news.fetch_news", lambda limit=8, http=None: parse_feed(RSS, "ex.com")[:limit])
    assert "Claude 5 released" in tb.handle_text(db, None, "/news")

    monkeypatch.setattr(settings, "watch_channels", "")
    assert "WATCH_CHANNELS" in tb.handle_text(db, None, "/channels")
    monkeypatch.setattr(settings, "watch_channels", "techchan, @pychan")
    monkeypatch.setattr(settings, "channel_keywords", "AI,Python")
    out = tb.handle_text(db, None, "/channels")
    assert "@techchan" in out and "@pychan" in out and "Python" in out
