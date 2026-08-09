OBS Widgets - единый гайд по запуску
====================================

В этой папке 3 отдельных виджета:
1) giveaway-bot
   - Flask-приложение с giveaway/панелью
   - Локальный URL: http://127.0.0.1:5000

2) random-slot-roulette
   - Node.js сервер для рулетки слотов
   - Локальный URL: http://127.0.0.1:8765

3) wallet-dep-withdraw
   - Python bridge (лайки YouTube) для виджета
   - Локальный URL: http://127.0.0.1:8766
   - По умолчанию порт 8766 (конфликта с roulette нет)


Быстрый запуск (рекомендуется)
------------------------------
macOS / Linux:
1. Из корневой папки: ./start.sh
2. Остановка: ./stop.sh
3. Логи: .logs/portal.log, roulette.log, wallet.log

Windows:
1. Запусти файл: start.bat (из этой корневой папки).
2. Скрипт откроет отдельные окна консоли для сервисов.
3. Остановка: Ctrl+C в окне сервиса (или закрой окна).

Сервисы после старта:
- Giveaway + Roulette portal (58971) — unified_server.py
- Random Slot Roulette (8765)
- Wallet Bridge (8766)

Примечание macOS: порт 5000 часто занят AirPlay Receiver
(Системные настройки → Основные → AirDrop и Handoff → «Ресивер AirPlay»).
Основные виджеты используют 58971 / 8765 / 8766 — конфликта нет.


Что за что отвечает
-------------------
giveaway-bot:
- Файлы запуска:
  - start.bat (корень obs-widgets — всё сразу)
  - giveaway-bot\start.bat (отдельное wheel + cards, порт 58971)
- Основной сервер (для /obs-dock и /widget): giveaway-bot\giveaway_bot\server.py
- Дополнительно (старый hybrid wheel): giveaway-bot\server.py
- Использование:
  - Admin/Panel: http://127.0.0.1:5000
  - Wheel panel: http://127.0.0.1:58971/panel.html
  - Wheel source (колесо + карта): http://127.0.0.1:58971/wheel.html

random-slot-roulette:
- Файл запуска: random-slot-roulette\start.bat
- Основной сервер: random-slot-roulette\server.mjs
- Использование:
  - Dock: http://127.0.0.1:8765/dock.html
  - Overlay: http://127.0.0.1:8765/overlay.html

wallet-dep-withdraw:
- Запуск: start.bat (корень obs-widgets)
- Основной сервер: wallet-dep-withdraw\likes_bridge.py
- Использование:
  - API: http://127.0.0.1:8766/status?channel=...&goal=...


Требования для запуска
----------------------
Обязательно:
- macOS 12+ / Windows 10/11 / Linux
- Python 3.10+ (в PATH: python3 или python)
- Node.js 18+ (для random-slot-roulette)
- Интернет (для некоторых функций, например YouTube likes bridge)

Python-пакеты (start.sh / start.bat ставят сами):
- wallet-dep-withdraw: pip install -r wallet-dep-withdraw/requirements.txt
- giveaway-bot: pip install -r giveaway-bot/requirements.txt

dep-calendar (опционально, для /calendar на портале):
- start.sh соберёт vite-сборку, если нет dep-calendar/dist
- вручную: cd dep-calendar && npm install && npx vite build


Проверка на другом компьютере
-----------------------------
Будет работать, если:
1) Скопировать всю папку obs-widgets целиком.
2) Установить Python и Node.js.
3) macOS/Linux: ./start.sh   |   Windows: start.bat
4) На Windows: разрешить локальные подключения в брандмауэре, если попросит.

Возможные проблемы:
- Порт уже занят другой программой (редко):
  roulette использует 8765, wallet bridge использует 8766.
- Отсутствие Python/Node в PATH.
- Не установлены pip-зависимости.


Если что-то не стартует
-----------------------
1) Проверь версии:
   - python --version
   - node --version
2) Проверь, что запускаешь из этой корневой папки.
3) Запусти нужный подпроект отдельным bat-файлом, чтобы увидеть точную ошибку.
4) Для OBS используй те же URL, что печатаются в консоли.


OBS Studio: куда и что вставлять
--------------------------------
Перед добавлением в OBS:
1) Сначала запусти start.bat (все сервисы) или только нужный сервис вручную.
2) Убедись, что URL открывается в браузере (Chrome / Safari / Edge).
3) Только потом добавляй URL в OBS.


1) Виджеты на экране (в сцене) - Browser Source
------------------------------------------------
Используется для того, что зритель видит на стриме (оверлеи, анимации, виджеты).

Шаги в OBS:
1) Открой нужную сцену.
2) В блоке Sources нажми "+".
3) Выбери "Browser" (или "Браузер"), нажми OK.
4) В поле URL вставь адрес виджета.
5) Поставь нужные Width/Height.
6) Нажми OK.

Рекомендуемые URL для оверлеев:
- Giveaway widget: http://127.0.0.1:5000/widget
- Giveaway wheel+cards (отдельный): http://127.0.0.1:58971/wheel.html
- Random Slot overlay: http://127.0.0.1:8765/overlay.html
- Wallet overlay: http://127.0.0.1:8766/wallet

Рекомендуемые размеры:
- Полноэкранный виджет: 1920x1080
- Небольшой блок: 500x500 (или подгоняй вручную)

Полезные опции в Browser Source:
- "Shutdown source when not visible" - обычно ВКЛ, чтобы не грузить систему.
- "Refresh browser when scene becomes active" - ВКЛ, если виджет иногда "зависает".
- "Control audio via OBS" - ВКЛ только если у виджета есть звук.


2) Док-панели внутри OBS - Custom Browser Docks
------------------------------------------------
Используется для управляющих панелей, которые видишь только ты (стример), а не зритель.

Шаги в OBS:
1) В верхнем меню OBS: Docks -> Custom Browser Docks...
2) Нажми "+" (или Add), чтобы добавить новый док.
3) Name: задай название панели (например, "Giveaway Admin").
4) URL: вставь адрес панели.
5) Нажми Apply / Close.
6) Перетащи док мышкой в удобное место интерфейса OBS.

Рекомендуемые URL для доков:
- Giveaway admin/panel: http://127.0.0.1:5000
- Giveaway OBS dock: http://127.0.0.1:5000/obs-dock
- Giveaway wheel panel (отдельная): http://127.0.0.1:58971/panel.html
- Random Slot dock: http://127.0.0.1:8765/dock.html
- Wallet dock (Custom Browser Dock): http://127.0.0.1:8766/wallet/dock


3) Wallet Dep/Withdraw (отдельно)
---------------------------------
`wallet-dep-withdraw` лучше использовать через HTTP от bridge-сервера:
- Оверлей для сцены: `http://127.0.0.1:8766/wallet`
- Док для управления: `http://127.0.0.1:8766/wallet/dock`

Как добавить в OBS:
1) Оверлей на сцену:
   - Sources -> + -> Browser
   - В поле URL: `http://127.0.0.1:8766/wallet`
   - "Local file" должен быть ВЫКЛ
2) Док-панель:
   - Docks -> Custom Browser Docks...
   - URL: `http://127.0.0.1:8766/wallet/dock`

Важно по лайкам YouTube:
- Для блока лайков в этом виджете нужен запущенный bridge:
  `start.bat`
- Bridge URL по умолчанию: `http://127.0.0.1:8766`

Почему раньше могло работать через file://, а сейчас нет:
- В новых версиях OBS/CEF доки и источники иногда изолируют хранилище (`localStorage`) для `file://`.
- Из-за этого док меняет значения, а оверлей их не видит и остаётся на нулях.
- Через единый `http://127.0.0.1:8766` у дока и оверлея один origin, поэтому синхронизация стабильнее.


Что куда вставлять (коротко)
----------------------------
- В "Browser Source" вставляй URL с визуальным оверлеем (обычно /widget или /overlay.html).
- В "Custom Browser Docks" вставляй URL с управлением (обычно /dock, /obs-dock или главная admin-страница).


Если в OBS белый экран или ошибка
---------------------------------
1) Проверь, что сервис реально запущен (окно консоли открыто, ошибок нет).
2) Открой тот же URL в обычном браузере.
3) Проверь, не перепутан ли порт:
   - 5000 -> giveaway-bot
   - 8765 -> random-slot-roulette
   - 8766 -> wallet likes bridge API (нужен для лайков в wallet, но это не отдельный оверлей/док URL)
4) В Browser Source нажми "Refresh cache of current page".
5) Если не помогло - перезапусти сервис и OBS.
