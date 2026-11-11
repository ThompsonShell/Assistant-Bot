from app.integrations.weather import Weather
from app.jobs import morning


class FakeHttp:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, **kw):
        self.sent.append(json or {})


def test_morning_brief_sends_when_configured(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "telegram_chat_id", "999")
    fake = Weather(city="Toshkent", temp=5.0, feels_like=2.0, wind=10.0, code=71)  # light snow
    monkeypatch.setattr("app.integrations.weather.fetch_weather", lambda *a, **k: fake)

    http = FakeHttp()
    assert morning.send_morning_weather(http=http) is True
    assert len(http.sent) == 1
    body = http.sent[0]
    assert body["chat_id"] == "999"
    assert "Xayrli tong" in body["text"]
    assert "Toshkent" in body["text"]
    assert "Kiyim tavsiyasi" in body["text"]


def test_morning_brief_noop_without_telegram(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")
    http = FakeHttp()
    assert morning.send_morning_weather(http=http) is False
    assert http.sent == []


def test_morning_brief_survives_weather_error(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    monkeypatch.setattr(settings, "telegram_chat_id", "999")

    def boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr("app.integrations.weather.fetch_weather", boom)
    http = FakeHttp()
    # The weather text still renders a friendly fallback, so a message IS sent.
    assert morning.send_morning_weather(http=http) is True
    assert "olib bo'lmadi" in http.sent[0]["text"]
