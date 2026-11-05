"""The AI provider interface. All AI access flows through this."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class PlanResult:
    """A structured plan. `ai_generated` tells the UI whether an LLM produced
    this or whether it is a deterministic/rule-based result."""

    summary: str
    tasks: list[dict[str, Any]] = field(default_factory=list)
    ai_generated: bool = False
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class AIProvider(Protocol):
    name: str
    #: True only when real AI inference is available (e.g. Claude API wired up).
    ai_available: bool

    def summarize(self, text: str, *, context: dict[str, Any] | None = None) -> str:
        """Produce a short summary of `text`."""
        ...

    def plan(self, instruction: str, *, context: dict[str, Any] | None = None) -> PlanResult:
        """Turn a natural-language instruction into a structured plan."""
        ...

    def chat(
        self,
        prompt: str,
        *,
        system: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Free-form conversational reply."""
        ...
