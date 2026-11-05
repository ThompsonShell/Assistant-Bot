#!/usr/bin/env bash
#
# Send a test notification (and, if configured, a Telegram message to you).
# Run while the app is running (./scripts/run-local.sh in another terminal).
#
#   ./scripts/test-telegram.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1090
set -a; source "$ROOT/.env"; set +a

BASE="${BASE_URL:-http://localhost:8000}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

echo "==> Logging in as ${ADMIN_USERNAME:-admin}"
CSRF="$(
  curl -s -c "$JAR" -X POST "$BASE/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USERNAME:-admin}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('csrf_token',''))" 2>/dev/null || true
)"

if [ -z "$CSRF" ]; then
  echo "    Login failed. Check ADMIN_PASSWORD in your .env, and that the app is running."
  exit 1
fi

echo "==> Sending test notification"
curl -s -b "$JAR" -X POST "$BASE/notifications/test" -H "X-CSRF-Token: $CSRF" \
  | python3 -m json.tool

echo
echo "If 'telegram_configured' is true and its 'delivered' is true, check your Telegram!"
echo "If false, add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env and restart the app."
