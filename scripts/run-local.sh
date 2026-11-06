#!/usr/bin/env bash
#
# Private AI LifeOS — one-command local runner (no Docker needed).
#
# What it does:
#   * creates a Python virtualenv and installs backend dependencies,
#   * makes sure Redis is running,
#   * creates a .env with a random secret on first run (SQLite, no Postgres),
#   * starts the API at http://localhost:8000 (docs at /docs).
#
# Usage:
#   chmod +x scripts/run-local.sh
#   ./scripts/run-local.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

echo "==> Python virtualenv"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing dependencies (first run may take a minute)"
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "==> Checking Redis"
if ! redis-cli ping >/dev/null 2>&1; then
  echo "    Redis is not running — trying to start it..."
  if command -v systemctl >/dev/null 2>&1 && sudo systemctl start redis-server 2>/dev/null; then
    :
  else
    redis-server --daemonize yes --save "" --appendonly no
  fi
  sleep 1
fi
if redis-cli ping >/dev/null 2>&1; then
  echo "    Redis OK"
else
  echo "    ERROR: could not start Redis. Install it: sudo apt install redis-server"
  exit 1
fi

echo "==> Environment (.env)"
if [ ! -f "$ROOT/.env" ]; then
  SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  cat > "$ROOT/.env" <<EOF
APP_SECRET_KEY=$SECRET
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me-now
DATABASE_URL=sqlite+pysqlite:///./lifeos.db
REDIS_URL=redis://localhost:6379/0
ENABLE_SCHEDULER=true
GITHUB_POLL_INTERVAL_SECONDS=30
DISPLAY_TIMEZONE=Asia/Tashkent
EOF
  echo "    Created $ROOT/.env"
  echo "    >>> IMPORTANT: open .env and change ADMIN_PASSWORD before real use. <<<"
fi

# Load .env into the environment (exported so pydantic settings pick it up).
set -a
# shellcheck disable=SC1090
source "$ROOT/.env"
set +a

# Free port 8000 if a previous instance is still running.
pkill -f "uvicorn app.main" 2>/dev/null || true
if command -v fuser >/dev/null 2>&1; then fuser -k 8000/tcp 2>/dev/null || true; fi
sleep 1

echo "==> Starting API at http://localhost:8000  (docs: http://localhost:8000/docs)"
echo "    Login with the username/password from your .env file."
echo "    Press Ctrl+C to stop."
exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
