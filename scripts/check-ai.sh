#!/usr/bin/env bash
#
# Diagnose the AI (Claude) connection. Shows which provider is selected and why,
# without revealing any secret. Run:  ./scripts/check-ai.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1090
set -a; source "$ROOT/.env"; set +a
cd "$ROOT/backend"
# shellcheck disable=SC1091
source .venv/bin/activate

python - <<'PY'
from app.config import settings
from app.providers import _build_provider

print("=== AI config ===")
print("ANTHROPIC_API_KEY set     :", bool(settings.anthropic_api_key))
print("USE_CLAUDE_SUBSCRIPTION    :", settings.use_claude_subscription)
tok = settings.claude_code_oauth_token or ""
print("CLAUDE_CODE_OAUTH_TOKEN set:", bool(tok),
      "| prefix:", (tok[:11] + "…") if tok else "—")
print("anthropic_model            :", settings.anthropic_model)
print("claude_agent_model         :", settings.claude_agent_model)

import shutil
print("claude binary found        :", shutil.which("claude") or "NO (install Claude Code)")

p = _build_provider()
print()
print("Selected provider          :", p.name)
print("ai_available               :", p.ai_available)

if p.name == "deterministic":
    print()
    print(">>> Claude is NOT connected. To fix:")
    print("    A) set ANTHROPIC_API_KEY=sk-ant-... in .env, OR")
    print("    B) set USE_CLAUDE_SUBSCRIPTION=true AND CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat... in .env")
    print("    then restart the app.")
else:
    print()
    print(">>> Testing a tiny Claude call (" + p.name + ")...")
    try:
        reply = p.chat("Reply with exactly: OK")
        print("Reply:", reply[:160])
    except Exception as exc:  # noqa: BLE001
        print("ERROR:", str(exc)[:200])
PY
