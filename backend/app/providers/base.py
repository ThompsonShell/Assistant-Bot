"""The AI provider interface. All AI access flows through this."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


def extract_json(text: str) -> Optional[Any]:
    """Pull the first JSON object/array out of a model response (tolerant of
    code fences and surrounding prose)."""
    if not text:
        return None
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


PLAN_SYSTEM = (
    "You are a weekly planning assistant. Read the user's plan (any language, "
    "often Uzbek) and produce a realistic schedule. Output ONLY a JSON object:\n"
    '{"summary": "<one short sentence>", "tasks": [{"title": str, "day": '
    '"Monday"|"Tuesday"|"Wednesday"|"Thursday"|"Friday"|"Saturday"|"Sunday"|null, '
    '"duration_minutes": int|null, "priority": "high"|"medium"|"low", '
    '"category": str|null}], "questions": [str]}\n'
    "Distribute tasks across days, respect any stated free/busy days, keep "
    "durations realistic (15-180 min), and include a short 'questions' array "
    "only if key information is missing. Write titles and the summary in the "
    "user's own language. Output nothing except the JSON object."
)


@dataclass
class PlanResult:
    """A structured plan. `ai_generated` tells the UI whether an LLM produced
    this or whether it is a deterministic/rule-based result."""

    summary: str
    tasks: list[dict[str, Any]] = field(default_factory=list)
    ai_generated: bool = False
    notes: list[str] = field(default_factory=list)


_VALID_DAYS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}


def parse_plan_response(text: str) -> "PlanResult":
    """Parse a model's JSON plan into a PlanResult (tolerant of imperfect JSON)."""
    data = extract_json(text or "")
    if not isinstance(data, dict):
        return PlanResult(summary=(text or "").strip()[:300], tasks=[], ai_generated=True)
    tasks: list[dict[str, Any]] = []
    for t in data.get("tasks") or []:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        day = t.get("day")
        day = day if isinstance(day, str) and day.lower() in _VALID_DAYS else None
        dur = t.get("duration_minutes")
        tasks.append(
            {
                "title": str(t.get("title")),
                "day": day,
                "duration_minutes": int(dur) if isinstance(dur, (int, float)) else None,
                "priority": (t.get("priority") or "medium"),
                "category": t.get("category") if isinstance(t.get("category"), str) else None,
            }
        )
    notes = [str(q) for q in (data.get("questions") or []) if q]
    return PlanResult(
        summary=str(data.get("summary", "")), tasks=tasks, ai_generated=True, notes=notes
    )


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

    def plan_tasks(
        self, instruction: str, *, context: dict[str, Any] | None = None
    ) -> PlanResult:
        """Turn a plan into a structured weekly schedule of tasks (title, day,
        duration, priority) for the user to review."""
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
