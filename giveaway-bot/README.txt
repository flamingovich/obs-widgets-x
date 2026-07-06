OBS Hybrid Roulette (Wheel + Case)
==================================

Локальный проект без фреймворков на фронте; для режима localhost нужен Python (server.py).
Файлы:
- wheel.html       -> виджет для Browser Source (колесо + кейс)
- panel.html       -> панель управления для OBS Dock
- app.js           -> логика проекта
- styles.css       -> стили
- server.py        -> локальный сервер (статика + API для связи панели и колеса)
- assets/          -> иконки, текстуры колеса, шрифт Unbounded (не переносить в корень)
- scripts/         -> start_local_server.*, stop_all.bat (запуск из корня через start_local_* в корне)


1) Быстрый запуск
-----------------
1. Запусти OBS.
2. Добавь виджет:
   - Sources -> + -> Browser
   - Включи Local file
   - Выбери wheel.html
   - Пример размера: 1280x720
3. Добавь панель:
   - View -> Docks -> Custom Browser Docks...
   - Dock Name: Hybrid Roulette
   - URL к panel.html:
     * macOS/Linux: file:///Users/.../папка/panel.html
     * Windows: file:///C:/Users/Имя/.../папка/panel.html
       (слэши только /, диск одна буква и двоеточие, без пробелов в начале)
4. Нажми Apply.
5. Перезагрузи источник виджета (Refresh cache), если он уже был открыт.


1.1) Рекомендуемый запуск через localhost (если через file не работает)
------------------------------------------------------------------------
macOS / Linux:
1. Открой терминал.
2. Выполни:
   cd /путь/к/папке/проекта
   zsh start_local_server.sh   (или: bash start_local_server.sh, если нет zsh)
3. Не закрывай окно терминала, пока тестируешь.

Windows:
1. Установи Python с https://www.python.org/ (поставь галку "Add python.exe to PATH").
2. Вариант А — двойной клик по start_local_server.bat в папке проекта.
   Вариант Б — PowerShell в папке проекта:
   powershell -ExecutionPolicy Bypass -File .\scripts\start_local_server.ps1
   (в корне также есть start_local_server.ps1 — перенаправляет в scripts/)
3. Окно консоли не закрывай, пока тестируешь.

После запуска используй в OBS:
- Виджет (Browser Source URL):
  http://localhost:58971/wheel.html
- Панель (Custom Browser Dock URL):
  http://localhost:58971/panel.html

Важно:
- В этом режиме НЕ включай "Local file" в Browser Source.
- Используй именно URL (http://...).
- Запускай именно server.py (через start_local_server.* или: python server.py).
  Старый вариант «python -m http.server» не поднимает /api/spin: панель в обычном
  браузере и колесо в OBS тогда не видят общий localStorage — крутить из браузера
  не получится.
- Везде один и тот же хост: либо везде localhost, либо везде 127.0.0.1 (не смешивать).


2) Логика игры
--------------
Этап 1 (колесо, 4 сектора):
- БОНУСКА
- КУПОН
- БАЛАНС
- ПЕРЕКРУТ (автоперезапуск колеса)

Этап 2 (кейс):
- БОНУСКА -> кейс со значениями 1600/3200/4800/6400
- КУПОН -> сразу фикс: 1000 (без прокрутки кейса)
- БАЛАНС -> кейс со значениями 10$/15$/20$/25$/50$
- ПЕРЕКРУТ -> кейс не открывается, колесо крутится снова


3) Панель управления
--------------------
- Кнопка "Запустить розыгрыш".
- Настройка шансов для 4 секторов.
- Ручной выбор сектора и результата (для тестов).
- История последних выпадений.


4) URL параметры
----------------
Для wheel.html:
- ?spin=1
- ?forceSector=БОНУСКА
- ?forceItem=6400

Пример:
file:///.../wheel.html?spin=1&forceSector=БАЛАНС&forceItem=50$


5) Если не запускается
----------------------
1. Обнови кэш Browser Source (Refresh cache).
2. Проверь, что wheel.html и panel.html из одной папки.
3. Закрой и открой Dock заново.
4. Проверь, что в панели шансы секторов не все нулевые.
5. Перейди на localhost режим (раздел 1.1) — обычно это сразу решает проблему.
