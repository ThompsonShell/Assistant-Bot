from app.providers import DeterministicProvider, _build_provider


def test_selects_deterministic_without_credentials(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "use_claude_subscription", False)
    monkeypatch.setattr(settings, "claude_code_oauth_token", None)
    p = _build_provider()
    assert isinstance(p, DeterministicProvider)
    assert p.ai_available is False


def test_selects_claude_api_with_key(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    p = _build_provider()
    assert p.name == "claude-api"
    assert p.ai_available is True


def test_selects_agent_with_subscription(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "use_claude_subscription", True)
    p = _build_provider()
    assert p.name == "claude-agent-sdk"


def test_deterministic_chat_message():
    msg = DeterministicProvider().chat("hello")
    assert "ulanmagan" in msg  # tells the user AI isn't connected
