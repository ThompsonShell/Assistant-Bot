"""AI provider abstraction.

The MVP runs with no automated AI: `DeterministicProvider` is the active
engine and makes no external calls. A real Claude API provider can be dropped
in later behind the same `AIProvider` interface — a config change, not a
rewrite.
"""
from .base import AIProvider, PlanResult
from .deterministic import DeterministicProvider

__all__ = ["AIProvider", "PlanResult", "DeterministicProvider", "get_provider"]

_provider: AIProvider | None = None


def get_provider() -> AIProvider:
    global _provider
    if _provider is None:
        _provider = DeterministicProvider()
    return _provider
