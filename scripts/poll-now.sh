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
# shellcheck disable=SC1090
source "$(dirname "$0")/_lib.sh"

lifeos_require_app
lifeos_login

echo "==> Polling watched repos now"
curl -s -b "$JAR" -X POST "$BASE/github/poll" -H "X-CSRF-Token: $CSRF" | python3 -m json.tool

echo "==> Latest 10 stored events"
curl -s -b "$JAR" "$BASE/github/events?limit=10" | python3 -m json.tool
