# Shared helpers for the LifeOS scripts. Source this; do not execute it.
# Expects BASE, ADMIN_USERNAME, ADMIN_PASSWORD to be set by the caller.

lifeos_require_app() {
  if ! curl -fsS "$BASE/health" >/dev/null 2>&1; then
    echo "❌ Bot ishlamayapti ($BASE)."
    echo "   Avval BOSHQA terminalда ishga tushiring:"
    echo "       ./scripts/run-local.sh"
    exit 1
  fi
}

lifeos_login() {
  JAR="$(mktemp)"
  trap 'rm -f "$JAR"' EXIT
  local resp
  resp="$(curl -s -c "$JAR" -X POST "$BASE/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USERNAME:-admin}\",\"password\":\"${ADMIN_PASSWORD:-}\"}")"
  CSRF="$(printf '%s' "$resp" | python3 -c '
import sys, json
try:
    print(json.load(sys.stdin).get("csrf_token", ""))
except Exception:
    print("")
')"
  if [ -z "$CSRF" ]; then
    echo "❌ Login ishlamadi. .env dagi ADMIN_PASSWORD ni tekshiring."
    exit 1
  fi
}
