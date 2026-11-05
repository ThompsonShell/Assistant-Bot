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

if [ $# -lt 2 ]; then
  echo "Usage: $0 <owner> <repo>"
  exit 1
fi
OWNER="$1"; NAME="$2"

JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT
CSRF="$(
  curl -s -c "$JAR" -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USERNAME:-admin}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('csrf_token',''))"
)"
[ -z "$CSRF" ] && { echo "Login failed — check ADMIN_PASSWORD and that the app is running."; exit 1; }

echo "==> Watching $OWNER/$NAME"
curl -s -b "$JAR" -X POST "$BASE/github/repos" \
  -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d "{\"owner\":\"$OWNER\",\"name\":\"$NAME\"}" | python3 -m json.tool
