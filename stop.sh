#!/usr/bin/env bash
# Остановка сервисов, запущенных через start.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$ROOT/.logs/services.pids"

echo "Останавливаю OBS Widgets..."

if [[ -f "$PID_FILE" ]]; then
  while read -r pid name; do
    [[ -z "${pid:-}" ]] && continue
    if kill -0 "$pid" 2>/dev/null; then
      echo "  kill $pid ($name)"
      kill "$pid" 2>/dev/null || true
    fi
  done < "$PID_FILE"
  sleep 0.5
  while read -r pid name; do
    [[ -z "${pid:-}" ]] && continue
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done < "$PID_FILE"
  : > "$PID_FILE"
fi

for port in 51999 58971 8765 8766; do
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "  освобождаю порт $port ($pids)"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.2
    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
    fi
  fi
done

echo "[OK] Остановлено."
