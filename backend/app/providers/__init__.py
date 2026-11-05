"""AI provider abstraction.

The MVP runs with no automated AI: `DeterministicProvider` is the active
engine and makes no external calls. A real Claude API provider can be dropped
in later behind the same `AIProvider` interface — a config change, not a
rewrite.
"""
from ..config import settings
from .base import AIProvider, PlanResult
from .deterministic import DeterministicProvider

__all__ = ["AIProvider", "PlanResult", "DeterministicProvider", "get_provider"]

_provider: AIProvider | None = None


def _build_provider() -> AIProvider:
    # 1) API key -> official Claude API (recommended).
    if settings.anthropic_api_key:
        from .claude_api import ClaudeApiProvider

        return ClaudeApiProvider()
    # 2) Subscription via Claude Agent SDK (opt-in; see policy note in claude_agent.py).
    if settings.use_claude_subscription or settings.claude_code_oauth_token:
        from .claude_agent import ClaudeAgentProvider

        return ClaudeAgentProvider()
    # 3) No AI configured -> deterministic fallback.
    return DeterministicProvider()


def get_provider() -> AIProvider:
    global _provider
    if _provider is None:
        _provider = _build_provider()
    return _provider
