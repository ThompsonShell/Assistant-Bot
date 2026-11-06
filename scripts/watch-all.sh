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
# shellcheck disable=SC1090
source "$(dirname "$0")/_lib.sh"

OWNER="${1:-}"

lifeos_require_app
lifeos_login

echo "==> Watching all repos${OWNER:+ of $OWNER}"
curl -s -b "$JAR" -X POST "$BASE/github/repos/watch-all" \
  -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d "{\"owner\": \"$OWNER\"}" | python3 -m json.tool
