#!/usr/bin/env bash
#
# Watch ALL your repositories at once (no more adding them one by one):
#   ./scripts/watch-all.sh                 # every repo your token can access
#   ./scripts/watch-all.sh ThompsonShell   # only that owner's/org's repos
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1090
set -a; source "$ROOT/.env"; set +a
BASE="${BASE_URL:-http://localhost:8000}"
OWNER="${1:-}"

JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT
CSRF="$(
  curl -s -c "$JAR" -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USERNAME:-admin}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('csrf_token',''))"
)"
[ -z "$CSRF" ] && { echo "Login failed — check ADMIN_PASSWORD and that the app is running."; exit 1; }

echo "==> Watching all repos${OWNER:+ of $OWNER}"
curl -s -b "$JAR" -X POST "$BASE/github/repos/watch-all" \
  -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d "{\"owner\": \"$OWNER\"}" | python3 -m json.tool
