"""Claude via the official Anthropic API (pay-as-you-go API key).

This is the fully-supported way to use Claude from a backend/bot. The SDK is
imported lazily so the app runs without it when no key is configured.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import settings
from .base import PlanResult

logger = logging.getLogger("lifeos.providers.claude_api")


class ClaudeApiProvider:
    name = "claude-api"
    ai_available = True

    def __init__(self) -> None:
        from anthropic import Anthropic  # lazy import

        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    def _complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        history: list[dict[str, str]] | None = None,
        max_tokens: int = 1024,
    ) -> str:
        messages: list[dict[str, Any]] = []
        for h in history or []:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        resp = self._client.messages.create(**kwargs)
        return "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()

    def chat(
        self, prompt: str, *, system: str | None = None, history: list[dict] | None = None
    ) -> str:
        try:
            return self._complete(prompt, system=system, history=history)
        except Exception as exc:  # noqa: BLE001
            logger.warning("claude api error", extra={"extra_fields": {"error": str(exc)[:200]}})
            return f"⚠️ Claude bilan bog'lanishda xato: {str(exc)[:150]}"

    def summarize(self, text: str, *, context: dict | None = None) -> str:
        return self._complete(f"Summarize briefly:\n\n{text}", max_tokens=300)

    def plan(self, instruction: str, *, context: dict | None = None) -> PlanResult:
        text = self._complete(
            "Turn this into a short, realistic task plan with time estimates:\n\n"
            + instruction,
            max_tokens=800,
        )
        return PlanResult(summary=text, tasks=[], ai_generated=True)
