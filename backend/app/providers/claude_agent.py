"""Claude via the Claude Agent SDK, authenticated with a Claude subscription.

⚠️ POLICY NOTE: Anthropic's Agent SDK docs state that third-party products/agents
should use API-key authentication, not a claude.ai (Pro/Max) subscription login.
A private, single-user tool is a gray area the docs don't explicitly permit. Use
this path at your own discretion; the ClaudeApiProvider (API key) is the
fully-supported option. See README.

Auth: either a local `claude` login on the machine, or CLAUDE_CODE_OAUTH_TOKEN
(from `claude setup-token`) for headless/server use. ANTHROPIC_API_KEY is removed
from the subprocess env so the subscription is used.
"""
from __future__ import annotations

import asyncio
import logging
import os

from ..config import settings
from .base import PlanResult

logger = logging.getLogger("lifeos.providers.claude_agent")

_SCRATCH = "/tmp/lifeos-claude-scratch"
# Built-in Claude Code tools we disable so the bot behaves as a plain chat model.
_BUILTIN_TOOLS = [
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Agent",
]


class ClaudeAgentProvider:
    name = "claude-agent-sdk"
    ai_available = True

    def __init__(self) -> None:
        self._model = settings.claude_agent_model
        if settings.claude_code_oauth_token:
            os.environ.setdefault(
                "CLAUDE_CODE_OAUTH_TOKEN", settings.claude_code_oauth_token
            )

    async def _ask(self, prompt: str, system: str | None) -> str:
        from claude_agent_sdk import (  # lazy import
            ClaudeAgentOptions,
            ResultMessage,
            query,
        )

        os.makedirs(_SCRATCH, exist_ok=True)
        # Force subscription auth: an API key would take precedence otherwise.
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

        options = ClaudeAgentOptions(
            system_prompt=system or "You are a helpful assistant.",
            model=self._model,
            tools=[],
            disallowed_tools=_BUILTIN_TOOLS,
            setting_sources=[],
            max_turns=1,
            cwd=_SCRATCH,
        )
        text: str | None = None
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                if getattr(message, "is_error", False):
                    raise RuntimeError(f"Claude request failed: {message.subtype}")
                text = message.result
        if text is None:
            raise RuntimeError("No result from Claude Code")
        return text.strip()

    def chat(
        self, prompt: str, *, system: str | None = None, history: list[dict] | None = None
    ) -> str:
        full = prompt
        if history:
            ctx = "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:])
            full = f"Conversation so far:\n{ctx}\n\nUser: {prompt}"
        try:
            return asyncio.run(self._ask(full, system))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "claude agent error", extra={"extra_fields": {"error": str(exc)[:200]}}
            )
            return f"⚠️ Claude (obuna) xatosi: {str(exc)[:150]}"

    def summarize(self, text: str, *, context: dict | None = None) -> str:
        return self.chat(f"Summarize briefly:\n\n{text}")

    def plan(self, instruction: str, *, context: dict | None = None) -> PlanResult:
        return PlanResult(
            summary=self.chat(f"Make a short, realistic task plan from:\n\n{instruction}"),
            ai_generated=True,
        )
