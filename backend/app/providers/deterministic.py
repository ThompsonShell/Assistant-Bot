"""Deterministic, no-AI provider — the active engine for the MVP.

Makes no external calls and costs nothing. `summarize` and `plan` use simple,
transparent rules. Output is always marked `ai_generated=False` so the system
never presents rule-based results as AI insight.
"""
from __future__ import annotations

from typing import Any

from .base import PlanResult


class DeterministicProvider:
    name = "deterministic"
    ai_available = False

    def summarize(self, text: str, *, context: dict[str, Any] | None = None) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        # First sentence or first 200 chars, whichever is shorter.
        for end in (". ", "\n"):
            idx = text.find(end)
            if 0 < idx < 200:
                return text[: idx + 1].strip()
        return (text[:200] + "…") if len(text) > 200 else text

    def plan(self, instruction: str, *, context: dict[str, Any] | None = None) -> PlanResult:
        # Minimal rule-based extraction: each non-empty line / comma-separated
        # clause becomes a candidate task. Real parsing lands with the planner
        # module in a later phase.
        raw = (instruction or "").replace("\n", ",")
        candidates = [c.strip(" .;-") for c in raw.split(",")]
        tasks = [{"title": c, "status": "proposed"} for c in candidates if c]
        return PlanResult(
            summary=f"Extracted {len(tasks)} candidate task(s) (rule-based).",
            tasks=tasks,
            ai_generated=False,
            notes=["AI planning is disabled; this is a simple rule-based extraction."],
        )
