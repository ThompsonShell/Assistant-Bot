#!/usr/bin/env bash
#
# Start watching a GitHub repository.
#   ./scripts/watch-repo.sh <owner> <repo>
#   e.g. ./scripts/watch-repo.sh ThompsonShell Assistant-Bot
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1090
set -a; source "$ROOT/.env"; set +a
BASE="${BASE_URL:-http://localhost:8000}"
# shellcheck disable=SC1090
source "$(dirname "$0")/_lib.sh"

if [ $# -lt 2 ]; then
  echo "Usage: $0 <owner> <repo>"
  exit 1
fi
OWNER="$1"; NAME="$2"

lifeos_require_app
lifeos_login

echo "==> Watching $OWNER/$NAME"
curl -s -b "$JAR" -X POST "$BASE/github/repos" \
  -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d "{\"owner\":\"$OWNER\",\"name\":\"$NAME\"}" | python3 -m json.tool
