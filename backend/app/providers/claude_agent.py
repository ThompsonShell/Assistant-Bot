"""Claude via the Claude Code CLI (`claude -p`) using a subscription token.

Uses the installed ``claude`` binary through a subprocess — NOT the
``claude-agent-sdk`` Python package, which drags in newer pydantic/starlette
that conflict with this app's FastAPI stack. Auth comes from
CLAUDE_CODE_OAUTH_TOKEN (``claude setup-token``) or a local ``claude`` login.

⚠️ Policy note: Anthropic's docs say products/agents should use API-key auth,
not a subscription login. A private, single-user tool is a gray area. The
ClaudeApiProvider (ANTHROPIC_API_KEY) is the fully-supported option.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from ..config import settings
from .base import PLAN_SYSTEM, PlanResult, parse_plan_response

logger = logging.getLogger("lifeos.providers.claude_cli")


def _resolve_bin() -> str:
    env_bin = os.environ.get("CLAUDE_BIN")
    if env_bin:
        return env_bin
    found = shutil.which("claude")
    return found or str(Path.home() / ".local" / "bin" / "claude")


class ClaudeAgentProvider:
    name = "claude-cli"
    ai_available = True

    _EFFORTS = {"low", "medium", "high", "xhigh", "max"}

    def __init__(self) -> None:
        self._model = settings.claude_agent_model or "sonnet"
        self._token = settings.claude_code_oauth_token
        self._bin = _resolve_bin()
        self._effort = settings.claude_effort if settings.claude_effort in self._EFFORTS else "medium"

    def _run(self, system: str, prompt: str, *, timeout: int = 120) -> str:
        # Child env: drop API-key/vars so the subscription login is used.
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
        env.pop("CLAUDE_CODE_SIMPLE", None)
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        if self._token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self._token

        fd, spf = tempfile.mkstemp(suffix=".txt")
        try:
            os.write(fd, (system or "").encode("utf-8"))
            os.close(fd)
            cmd = [
                self._bin, "-p",
                "--output-format", "json",
                "--tools", "",
                "--no-session-persistence",
                "--effort", self._effort,
                "--system-prompt-file", spf,
            ]
            if self._model:
                cmd += ["--model", self._model]
            try:
                proc = subprocess.run(
                    cmd,
                    input=(prompt or "").encode("utf-8"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    timeout=timeout,
                )
            except FileNotFoundError:
                raise RuntimeError(f"`claude` binary not found at {self._bin!r}")
            out = proc.stdout.decode("utf-8", "replace")
            last = ""
            for line in out.splitlines():
                if line.strip():
                    last = line.strip()
            data = json.loads(last) if last else None
            if (
                isinstance(data, dict)
                and not data.get("is_error")
                and data.get("subtype") in (None, "success")
            ):
                return (data.get("result") or "").strip()
            detail = ""
            if isinstance(data, dict):
                detail = data.get("result") or ""
            if not detail:
                detail = proc.stderr.decode("utf-8", "replace")[:200] or "claude failed"
            raise RuntimeError(detail)
        finally:
            try:
                os.unlink(spf)
            except OSError:
                pass

    def chat(
        self, prompt: str, *, system: Optional[str] = None, history: Optional[list] = None
    ) -> str:
        full = prompt
        if history:
            ctx = "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:])
            full = f"Conversation so far:\n{ctx}\n\nUser: {prompt}"
        try:
            return self._run(system or "You are a helpful assistant.", full)
        except Exception as exc:  # noqa: BLE001
            logger.warning("claude cli error", extra={"extra_fields": {"error": str(exc)[:200]}})
            return f"⚠️ Claude (obuna) xatosi: {str(exc)[:160]}"

    def summarize(self, text: str, *, context: Optional[dict] = None) -> str:
        return self.chat(f"Summarize briefly:\n\n{text}")

    def plan(self, instruction: str, *, context: Optional[dict] = None) -> PlanResult:
        return self.plan_tasks(instruction, context=context)

    def plan_tasks(self, instruction: str, *, context: Optional[dict] = None) -> PlanResult:
        try:
            return parse_plan_response(self._run(PLAN_SYSTEM, instruction, timeout=180))
        except Exception as exc:  # noqa: BLE001
            return PlanResult(summary=f"⚠️ Claude error: {str(exc)[:150]}", ai_generated=True)
