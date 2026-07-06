image.png@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "giveaway-bot" (
  echo [ERROR] Folder not found: giveaway-bot
  goto :fail
)
if not exist "random-slot-roulette" (
  echo [ERROR] Folder not found: random-slot-roulette
  goto :fail
)
if not exist "wallet-dep-withdraw" (
  echo [ERROR] Folder not found: wallet-dep-withdraw
  goto :fail
)

echo.
echo ============================================================
echo   OBS Widgets — запуск всех сервисов
echo ============================================================
echo.

echo Останавливаю старые процессы на портах 5000, 51999, 58971, 8765, 8766...
for %%P in (5000 51999 58971 8765 8766) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P" ^| findstr "LISTENING"') do (
    taskkill /PID %%A /F >nul 2>&1
  )
)
timeout /t 1 >nul

where python >nul 2>&1
if %errorlevel% equ 0 (
  set "PY=python"
) else (
  where py >nul 2>&1
  if %errorlevel% equ 0 (
    set "PY=py -3"
  ) else (
    echo [ERROR] Python not found. Install from https://www.python.org/
    goto :fail
  )
)

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not found. Install from https://nodejs.org/
  goto :fail
)

echo Запуск Giveaway + Roulette portal (порт 58971)...
start "OBS Widgets (58971)" cmd /k "cd /d ""%~dp0giveaway-bot"" && %PY% -m pip install -r requirements.txt -q && %PY% unified_server.py"

echo Запуск Random Slot Roulette (порт 8765)...
start "OBS Roulette (8765)" cmd /k "cd /d ""%~dp0random-slot-roulette"" && node server.mjs"

echo Запуск Wallet Bridge (порт 8766)...
start "OBS Wallet (8766)" cmd /k "cd /d ""%~dp0wallet-dep-withdraw"" && %PY% -m pip install -r requirements.txt -q && %PY% likes_bridge.py --port 8766"

echo.
echo [OK] Все сервисы запущены в отдельных окнах.
echo.
echo   Портал:     http://127.0.0.1:58971/
echo   Рулетка:    http://127.0.0.1:8765/overlay.html
echo   Кошелёк:    http://127.0.0.1:8766/wallet
echo.
echo Чтобы остановить — закройте три окна терминала.
echo.
pause
goto :eof

:fail
echo.
pause
exit /b 1
