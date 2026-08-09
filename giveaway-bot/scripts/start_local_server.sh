#!/bin/zsh

# Простой локальный сервер для OBS виджета.
# Запуск из корня проекта: zsh scripts/start_local_server.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

echo "==============================================="
echo " Local server started for OBS Hybrid Roulette"
echo " Folder: $PROJECT_ROOT"
echo " URL for wheel: http://localhost:58971/wheel.html"
echo " URL for panel: http://localhost:58971/panel.html"
echo " Stop server: Ctrl + C"
echo "==============================================="

python3 server.py
