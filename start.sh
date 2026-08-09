#!/usr/bin/env bash
# OBS Widgets — запуск всех сервисов (macOS / Linux)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

RED=$'\033[31m'
GREEN=$'\033[32m'
CYAN=$'\033[36m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

fail() {
  echo "${RED}[ERROR]${RESET} $*" >&2
  exit 1
}

for dir in giveaway-bot random-slot-roulette wallet-dep-withdraw; do
  [[ -d "$dir" ]] || fail "Folder not found: $dir"
done

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  fail "Python not found. Install Python 3.10+ (e.g. brew install python)"
fi

command -v node >/dev/null 2>&1 || fail "Node.js not found. Install from https://nodejs.org/ or: brew install node"

echo
echo "${BOLD}============================================================${RESET}"
echo "  OBS Widgets — запуск всех сервисов (macOS)"
echo "============================================================"
echo

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Освобождаю порт $port (PID: $pids)..."
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.3
    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}

echo "Останавливаю старые процессы на портах 51999, 58971, 8765, 8766..."
for port in 51999 58971 8765 8766; do
  kill_port "$port"
done
sleep 1

LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"
PID_FILE="$LOG_DIR/services.pids"
: > "$PID_FILE"

# Optional: build dep-calendar web dist if missing (portal /calendar)
if [[ ! -d "$ROOT/dep-calendar/dist" ]]; then
  if [[ -f "$ROOT/dep-calendar/package.json" ]] && command -v npm >/dev/null 2>&1; then
    echo "Собираю dep-calendar (vite)..."
    (
      cd "$ROOT/dep-calendar"
      npm install --silent
      npx vite build
    ) || echo "${RED}[WARN]${RESET} dep-calendar build failed — портал без /calendar"
  fi
fi

echo "Ставлю Python-зависимости..."
"$PY" -m pip install -r "$ROOT/giveaway-bot/requirements.txt" -q
"$PY" -m pip install -r "$ROOT/wallet-dep-withdraw/requirements.txt" -q

start_bg() {
  local name="$1"
  local logfile="$2"
  shift 2
  echo "Запуск ${CYAN}${name}${RESET}..."
  (
    "$@" >"$logfile" 2>&1
  ) &
  local pid=$!
  echo "$pid $name" >> "$PID_FILE"
  echo "  → PID $pid, лог: $logfile"
}

start_bg "Giveaway + Roulette portal (58971)" "$LOG_DIR/portal.log" \
  bash -c "cd \"$ROOT/giveaway-bot\" && exec \"$PY\" unified_server.py"

start_bg "Random Slot Roulette (8765)" "$LOG_DIR/roulette.log" \
  bash -c "cd \"$ROOT/random-slot-roulette\" && exec node server.mjs"

start_bg "Wallet Bridge (8766)" "$LOG_DIR/wallet.log" \
  bash -c "cd \"$ROOT/wallet-dep-withdraw\" && exec \"$PY\" likes_bridge.py --port 8766"

sleep 1.5

ok=1
for port in 58971 8765 8766; do
  if lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "${GREEN}[OK]${RESET} порт $port слушает"
  else
    echo "${RED}[FAIL]${RESET} порт $port не поднялся — смотри лог в $LOG_DIR/"
    ok=0
  fi
done

echo
if [[ "$ok" -eq 1 ]]; then
  echo "${GREEN}[OK]${RESET} Все сервисы запущены в фоне."
else
  echo "${RED}[WARN]${RESET} Часть сервисов не стартовала. Логи: $LOG_DIR/"
fi
echo
echo "  Портал:     http://127.0.0.1:58971/"
echo "  Рулетка:    http://127.0.0.1:8765/overlay.html"
echo "  Кошелёк:    http://127.0.0.1:8766/wallet"
echo
echo "Логи:     $LOG_DIR/"
echo "Стоп:     ./stop.sh   или   kill \$(awk '{print \$1}' $PID_FILE)"
echo
echo "Примечание macOS: порт 5000 часто занят AirPlay Receiver —"
echo "основные виджеты используют 58971 / 8765 / 8766, это нормально."
echo
