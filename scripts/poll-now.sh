#!/usr/bin/env bash
#
# Poll all watched repos right now and show the latest events.
#   ./scripts/poll-now.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1090
set -a; source "$ROOT/.env"; set +a
BASE="${BASE_URL:-http://localhost:8000}"

JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT
CSRF="$(
  curl -s -c "$JAR" -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USERNAME:-admin}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('csrf_token',''))"
)"
[ -z "$CSRF" ] && { echo "Login failed — check ADMIN_PASSWORD and that the app is running."; exit 1; }

echo "==> Polling watched repos now"
curl -s -b "$JAR" -X POST "$BASE/github/poll" -H "X-CSRF-Token: $CSRF" | python3 -m json.tool

echo "==> Latest 10 stored events"
curl -s -b "$JAR" "$BASE/github/events?limit=10" | python3 -m json.tool
