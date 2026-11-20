#!/usr/bin/env bash
#
# Why does the bot say Jira is not connected? Checks the .env file, what the
# program receives, one call to Jira, and whether an OLD bot is still running.
# No secret is printed. Run:  ./scripts/check-jira.sh
#
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ $ENV_FILE topilmadi. Jira sozlamalari aynan shu faylda bo'lishi kerak"
  echo "   (Assistant-Bot/.env — boshqa loyihaning .env fayli emas)."
  exit 1
fi

# Load .env exactly like run-local.sh does.
set -a
# shellcheck disable=SC1090
if ! source "$ENV_FILE"; then
  echo "❌ .env ni o'qishda xato. Odatda qiymatda bo'sh joy bor va qo'shtirnoq yo'q."
fi
set +a

cd "$ROOT/backend"
# shellcheck disable=SC1091
source .venv/bin/activate
python -m app.integrations.jira_diag "$ENV_FILE"
STATUS=$?

echo
echo "=== 4. Ishlayotgan bot jarayonlari ==="
PROCS="$(ps -eo pid,etime,command | grep -E 'uvicorn app\.main|app\.jobs\.telegram_bot' | grep -v grep || true)"
if [ -z "$PROCS" ]; then
  echo "Hech qanday bot ishlamayapti. ./scripts/run-local.sh bilan ishga tushiring."
else
  echo "PID   VAQT  BUYRUQ"
  echo "$PROCS"
  COUNT="$(echo "$PROCS" | wc -l | tr -d ' ')"
  if [ "$COUNT" -gt 1 ]; then
    echo
    echo "⚠️ $COUNT ta jarayon bor. Telegram xabarlarini ular navbatma-navbat oladi, shuning uchun"
    echo "   javoblar ba'zan ESKI nusxadan (Jira sozlamasiz) keladi. Hammasini to'xtatib, bittasini ishga tushiring:"
    echo "     pkill -f 'uvicorn app.main'; pkill -f 'app.jobs.telegram_bot'; ./scripts/run-local.sh"
  fi
fi
exit $STATUS
