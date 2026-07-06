import sys
from flask import Flask, render_template, jsonify, request, send_from_directory, g, session, redirect, url_for, has_app_context
import pytchat
import threading
import random
import time
import json
import os
import re
from urllib.parse import quote

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

try:
    from obs_platform import db as platform_db
except ImportError:
    platform_db = None

from user_context import (
    get_giveaway,
    get_giveaway_for_user,
    get_user_id,
    get_stop_flag,
    get_stop_flag_for_user,
    get_chat_thread,
    set_chat_thread,
    get_chat_instance,
    set_chat_instance,
    resolve_user,
    _chat_instances,
)

app = Flask(__name__)
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BOT_DIR, "widget_settings.json")
CHANNEL_PATH = os.path.join(BOT_DIR, "channel.json")

# Legacy alias — всегда указывает на розыгрыш текущего пользователя
class _GiveawayProxy:
    def __getitem__(self, key):
        return get_giveaway()[key]

    def __setitem__(self, key, value):
        get_giveaway()[key] = value

    def get(self, key, default=None):
        return get_giveaway().get(key, default)


giveaway = _GiveawayProxy()

# Настройки виджета по умолчанию (текущий пресет стримера)
default_widget_settings = {
    "width": 800,
    "height": 30,
    "border_radius": 1,
    "widget_align_h": "left",
    "font_size_label": 25,
    "font_size_keyword": 31,
    "font_size_separator": 16,
    "font_size_count": 17,
    "font_size_countdown": 36,
    "font_size_winner_label": 22,
    "font_size_winner_name": 27,
    "font_size_timer": 19,
    "text_label": "Пиши в чат",
    "text_separator": "|",
    "text_count_suffix": "чел.",
    "text_winner_label_start": "Победил",
    "text_winner_label_end": "🏆",
    "text_timer_prefix": "⏱️",
    "show_label": True,
    "show_keyword": True,
    "show_separator": True,
    "show_count": True,
    "show_winner_label_start": True,
    "show_winner_label_end": False,
    "show_winner_name": True,
    "show_winner_avatar": True,
    "show_timer": True,
    "bg_type_active": "image",
    "bg_color_1": "#667eea",
    "bg_color_2": "#764ba2",
    "bg_image_active": "17490234969549.jpg",
    "bg_type_winner": "image",
    "winner_bg_1": "#f39c12",
    "winner_bg_2": "#e74c3c",
    "bg_image_winner": "gradient-background-geometric-gradient-wallpaper-abstract-background-premium-gradient_1003782-672.jpg",
    "text_color_label": "#ffffff",
    "text_color_keyword": "#ffffff",
    "text_color_separator": "#e3e3e3",
    "text_color_count": "#ededed",
    "text_color_countdown": "#ffffff",
    "text_color_winner_label": "#ffffff",
    "text_color_winner_name": "#ffffff",
    "text_color_timer": "#ffffff",
    "keyword_bg_color": "rgba(255,255,255,0.2)",
    "winner_info_bg_enabled": False,
    "winner_info_bg_color": "rgba(0,0,0,0.3)",
    "text_stroke_enabled": False,
    "text_stroke_color": "#000000",
    "text_stroke_width": 1,
    "text_shadow_enabled": True,
    "text_shadow_color": "#3b3b3b",
    "text_shadow_x": 0,
    "text_shadow_y": 0,
    "text_shadow_blur": 20,
    "winner_avatar_size": 45,
    "winner_avatar_border_radius": 50,
}

widget_settings = default_widget_settings.copy()
_settings_lock = threading.Lock()
_settings_cache: dict[int, dict] = {}

saved_channel = {
    "channel_id": ""
}
_channel_cache: dict[int, dict] = {}


def _settings_user_id() -> int:
    if not has_app_context():
        return 0
    resolve_user()
    return get_user_id()


def _get_widget_settings_mutable() -> dict:
    uid = _settings_user_id()
    with _settings_lock:
        if uid not in _settings_cache:
            _settings_cache[uid] = _load_settings_for_user(uid)
        return _settings_cache[uid]


def _load_settings_for_user(user_id: int) -> dict:
    if platform_db and user_id:
        stored = platform_db.get_user_setting(user_id, "giveaway_widget")
        if isinstance(stored, dict):
            return {**default_widget_settings, **stored}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                return {**default_widget_settings, **loaded}
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass
    return default_widget_settings.copy()


def _persist_widget_settings(data: dict) -> None:
    uid = _settings_user_id()
    if platform_db and uid:
        platform_db.save_user_setting(uid, "giveaway_widget", data)
        return
    os.makedirs(BOT_DIR, exist_ok=True)
    tmp_path = SETTINGS_PATH + ".tmp"
    last_err = None
    for attempt in range(5):
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, SETTINGS_PATH)
            return
        except OSError as err:
            last_err = err
            time.sleep(0.05 * (attempt + 1))
    raise last_err


TEST_MALE_FIRST_NAMES = [
    {"ru": "Артём", "en": "Artem"},
    {"ru": "Кирилл", "en": "Kirill"},
    {"ru": "Иван", "en": "Ivan"},
    {"ru": "Дмитрий", "en": "Dmitry"},
    {"ru": "Алексей", "en": "Aleksey"},
    {"ru": "Александр", "en": "Aleksandr"},
    {"ru": "Максим", "en": "Maksim"},
    {"ru": "Егор", "en": "Egor"},
    {"ru": "Никита", "en": "Nikita"},
    {"ru": "Павел", "en": "Pavel"},
    {"ru": "Илья", "en": "Ilya"},
    {"ru": "Владислав", "en": "Vladislav"},
    {"ru": "Константин", "en": "Konstantin"},
    {"ru": "Роман", "en": "Roman"},
    {"ru": "Степан", "en": "Stepan"},
    {"ru": "Фёдор", "en": "Fedor"},
    {"ru": "Матвей", "en": "Matvey"},
    {"ru": "Тимур", "en": "Timur"},
    {"ru": "Олег", "en": "Oleg"},
    {"ru": "Виктор", "en": "Viktor"},
    {"ru": "Богдан", "en": "Bogdan"},
    {"ru": "Ярослав", "en": "Yaroslav"},
    {"ru": "Валерий", "en": "Valeriy"},
    {"ru": "Георгий", "en": "Georgiy"},
    {"ru": "Леонид", "en": "Leonid"},
    {"ru": "Михаил", "en": "Mikhail"},
    {"ru": "Юрий", "en": "Yuriy"},
    {"ru": "Василий", "en": "Vasiliy"},
    {"ru": "Сергей", "en": "Sergey"},
    {"ru": "Анатолий", "en": "Anatoliy"},
    {"ru": "Григорий", "en": "Grigoriy"},
    {"ru": "Денис", "en": "Denis"},
    {"ru": "Пётр", "en": "Petr"},
    {"ru": "Руслан", "en": "Ruslan"},
    {"ru": "Святослав", "en": "Svyatoslav"},
    {"ru": "Глеб", "en": "Gleb"},
    {"ru": "Антон", "en": "Anton"},
    {"ru": "Арсений", "en": "Arseniy"},
    {"ru": "Вадим", "en": "Vadim"},
    {"ru": "Виталий", "en": "Vitaliy"},
    {"ru": "Игорь", "en": "Igor"},
    {"ru": "Марат", "en": "Marat"},
    {"ru": "Назар", "en": "Nazar"},
    {"ru": "Николай", "en": "Nikolay"},
    {"ru": "Ростислав", "en": "Rostislav"},
    {"ru": "Семён", "en": "Semyon"},
    {"ru": "Тарас", "en": "Taras"},
    {"ru": "Ян", "en": "Yan"},
    {"ru": "Эдуард", "en": "Eduard"},
    {"ru": "Лука", "en": "Luka"},
]

TEST_MALE_SURNAMES = [
    {"ru": "Смирнов", "en": "Smirnov"},
    {"ru": "Иванов", "en": "Ivanov"},
    {"ru": "Кузнецов", "en": "Kuznetsov"},
    {"ru": "Попов", "en": "Popov"},
    {"ru": "Соколов", "en": "Sokolov"},
    {"ru": "Лебедев", "en": "Lebedev"},
    {"ru": "Козлов", "en": "Kozlov"},
    {"ru": "Новиков", "en": "Novikov"},
    {"ru": "Морозов", "en": "Morozov"},
    {"ru": "Петров", "en": "Petrov"},
    {"ru": "Волков", "en": "Volkov"},
    {"ru": "Соловьёв", "en": "Solovyov"},
    {"ru": "Васильев", "en": "Vasilev"},
    {"ru": "Зайцев", "en": "Zaitsev"},
    {"ru": "Павлов", "en": "Pavlov"},
    {"ru": "Семёнов", "en": "Semenov"},
    {"ru": "Голубев", "en": "Golubev"},
    {"ru": "Виноградов", "en": "Vinogradov"},
    {"ru": "Богданов", "en": "Bogdanov"},
    {"ru": "Воробьёв", "en": "Vorobyov"},
    {"ru": "Фёдоров", "en": "Fedorov"},
    {"ru": "Михайлов", "en": "Mikhailov"},
    {"ru": "Беляев", "en": "Belyaev"},
    {"ru": "Тарасов", "en": "Tarasov"},
    {"ru": "Белов", "en": "Belov"},
    {"ru": "Комаров", "en": "Komarov"},
    {"ru": "Орлов", "en": "Orlov"},
    {"ru": "Киселёв", "en": "Kiselev"},
    {"ru": "Макаров", "en": "Makarov"},
    {"ru": "Никитин", "en": "Nikitin"},
]

TEST_AVATAR_COLORS = [
    "#6C5CE7", "#E53935", "#1E88E5", "#00897B", "#8E24AA",
    "#3949AB", "#43A047", "#F4511E", "#5E35B1", "#D81B60",
    "#039BE5", "#7CB342", "#FB8C00", "#546E7A", "#C2185B",
]


def random_suffix(size=3):
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(random.choice(chars) for _ in range(size))


def make_test_participant_name():
    first = random.choice(TEST_MALE_FIRST_NAMES)
    last = random.choice(TEST_MALE_SURNAMES)
    is_ru = random.random() < 0.5

    first_name = first["ru"] if is_ru else first["en"]
    last_name = last["ru"] if is_ru else last["en"]
    variant = random.random()

    if variant < 0.35:
        return first_name
    if variant < 0.65:
        return f"{first_name}-{random_suffix(3)}"
    if variant < 0.85:
        spacer = "" if is_ru else "-"
        return f"{first_name}{spacer}{last_name}-{random_suffix(3)}"
    return f"{first_name}{last_name}-{random_suffix(3)}"


def make_letter_avatar(name):
    initial = "U"
    for ch in str(name or "").strip():
        if ch.isalnum():
            initial = ch.upper()
            break
    bg = random.choice(TEST_AVATAR_COLORS)
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='96' height='96' viewBox='0 0 96 96'>"
        f"<rect width='96' height='96' rx='48' fill='{bg}'/>"
        "<text x='50%' y='54%' text-anchor='middle' dominant-baseline='middle' "
        "font-family='Inter, Segoe UI, Arial, sans-serif' font-size='44' font-weight='700' fill='#ffffff'>"
        f"{initial}</text></svg>"
    )
    return "data:image/svg+xml;utf8," + quote(svg, safe="")


def load_settings():
    global widget_settings
    widget_settings = _get_widget_settings_mutable()


def save_settings():
    data = _get_widget_settings_mutable()
    _persist_widget_settings(data)


def load_channel():
    global saved_channel
    uid = _settings_user_id()
    if platform_db and uid:
        stored = platform_db.get_user_setting(uid, "giveaway_channel")
        if isinstance(stored, dict):
            saved_channel = stored
            _channel_cache[uid] = stored
            return
    if os.path.exists(CHANNEL_PATH):
        try:
            with open(CHANNEL_PATH, "r", encoding="utf-8") as f:
                saved_channel = json.load(f)
        except OSError:
            pass


def save_channel():
    global saved_channel
    uid = _settings_user_id()
    if platform_db and uid:
        platform_db.save_user_setting(uid, "giveaway_channel", saved_channel)
        return
    with open(CHANNEL_PATH, "w", encoding="utf-8") as f:
        json.dump(saved_channel, f, ensure_ascii=False)


def get_live_video_id(channel_input):
    import urllib.request
    import urllib.error
    
    channel_input = channel_input.strip()
    
    if re.match(r'^[a-zA-Z0-9_-]{11}$', channel_input):
        return channel_input
    
    if channel_input.startswith('@'):
        live_url = f"https://www.youtube.com/{channel_input}/live"
    elif 'youtube.com' in channel_input:
        channel_input = channel_input.replace('/live', '').rstrip('/')
        live_url = f"{channel_input}/live"
    elif channel_input.startswith('UC'):
        live_url = f"https://www.youtube.com/channel/{channel_input}/live"
    else:
        live_url = f"https://www.youtube.com/@{channel_input}/live"
    
    try:
        print(f"🔍 Ищу стрим: {live_url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        req = urllib.request.Request(live_url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
            
            match = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
            if match:
                video_id = match.group(1)
                print(f"✅ Найден стрим: {video_id}")
                return video_id
            
            match = re.search(r'watch\?v=([a-zA-Z0-9_-]{11})', html)
            if match:
                video_id = match.group(1)
                print(f"✅ Найден стрим: {video_id}")
                return video_id
                
    except Exception as e:
        print(f"❌ Ошибка поиска стрима: {e}")
    
    return None


def get_author_info(message):
    author = message.author
    
    name = None
    if hasattr(author, 'displayName') and author.displayName:
        name = author.displayName
    elif hasattr(author, 'name') and author.name:
        name = author.name
    elif hasattr(author, 'channelName') and author.channelName:
        name = author.channelName
    
    if not name:
        name = "Unknown"
    
    if name.startswith('@'):
        alternatives = ['displayName', 'channelName', 'title', 'authorName']
        for attr in alternatives:
            if hasattr(author, attr):
                alt_name = getattr(author, attr, None)
                if alt_name and not alt_name.startswith('@'):
                    name = alt_name
                    break
    
    avatar = None
    if hasattr(author, 'imageUrl') and author.imageUrl:
        avatar = author.imageUrl
    elif hasattr(author, 'profileImage') and author.profileImage:
        avatar = author.profileImage
    elif hasattr(author, 'avatar') and author.avatar:
        avatar = author.avatar
    
    return name, avatar


def watch_chat(user_id: int):
    gw = get_giveaway_for_user(user_id)
    stop_event = get_stop_flag_for_user(user_id)
    chat_instance = None

    try:
        chat_instance = pytchat.create(video_id=gw["video_id"], interruptable=False)
        _chat_instances[user_id] = chat_instance
        gw["is_connected"] = True
        print(f"✅ Подключился к чату: {gw['video_id']} (user {user_id})")

        while chat_instance.is_alive() and not stop_event.is_set():
            try:
                items = chat_instance.get()
                for message in items.sync_items():
                    author, avatar = get_author_info(message)
                    text = message.message

                    if gw["winner"] and author == gw["winner"]:
                        if gw["winner_first_message_at"] is None:
                            gw["winner_first_message_at"] = time.time()
                            print(f"⏱️ Победитель ответил! Время: {time.time() - gw['winner_picked_at']:.1f} сек")

                        gw["winner_messages"].append({
                            "time": time.strftime("%H:%M:%S"),
                            "text": text
                        })
                        gw["winner_messages"] = gw["winner_messages"][-50:]
                        print(f"💬 {author}: {text}")

                    keyword_ok = gw["keyword"].lower() in text.lower() if gw["keyword"] else False
                    accept_by_mode = gw.get("accept_any_message", False) or keyword_ok
                    selection_in_progress = int(gw.get("countdown") or 0) > 0
                    session_collecting = gw["is_active"] or bool(gw.get("winner"))
                    if session_collecting and (not selection_in_progress) and accept_by_mode:
                        if author not in gw["participants"]:
                            gw["participants"].append(author)
                            gw["participants_data"][author] = {"avatar": avatar}
                            print(f"✅ {author} участвует! (Всего: {len(gw['participants'])})")

            except Exception as e:
                print(f"Ошибка чтения: {e}")

            time.sleep(0.5)

    except Exception as e:
        print(f"Ошибка чата: {e}")
    finally:
        gw["is_connected"] = False
        _chat_instances.pop(user_id, None)
        print("❌ Отключился от чата")


# === СТРАНИЦЫ ===

@app.before_request
def _attach_user():
    resolve_user()


def _require_login_for_panel():
    user = resolve_user()
    if user:
        return None
    return redirect(f"/login?next={request.full_path if request.query_string else request.path}")


@app.route('/')
def admin():
    denied = _require_login_for_panel()
    if denied:
        return denied
    return render_template('admin.html')


@app.route('/obs-dock')
def obs_dock():
    return render_template('obs_dock.html')


@app.route('/widget')
def widget():
    return render_template('widget.html')


@app.route('/constructor')
def constructor():
    denied = _require_login_for_panel()
    if denied:
        return denied
    return render_template('constructor.html')


@app.route('/wheel-integration')
def wheel_integration():
    denied = _require_login_for_panel()
    if denied:
        return denied
    return render_template('wheel_integration.html')


@app.route('/t/<token>/widget')
def widget_by_token(token):
    resolve_user()
    return render_template('widget.html')


@app.route('/t/<token>/obs-dock')
def obs_dock_by_token(token):
    resolve_user()
    return render_template('obs_dock.html')


@app.route('/t/<token>/constructor')
def constructor_by_token(token):
    denied = _require_login_for_panel()
    if denied:
        return denied
    return render_template('constructor.html')


@app.route('/fonts/<path:filename>')
def serve_font(filename):
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
    local_font = os.path.join(fonts_dir, filename)
    if os.path.exists(local_font):
        return send_from_directory(fonts_dir, filename)

    # Fallback: общие шрифты из корня проекта / assets/fonts.
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for sub in ("", os.path.join("assets", "fonts")):
        base = root_dir if sub == "" else os.path.join(root_dir, sub)
        candidate = os.path.join(base, filename)
        if os.path.exists(candidate):
            return send_from_directory(base, filename)

    return jsonify({"error": "Font not found"}), 404


@app.route('/images/<path:filename>')
def serve_image(filename):
    images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'images')
    return send_from_directory(images_dir, filename)


@app.route('/sounds/<path:filename>')
def serve_sound(filename):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(base_dir)
    workspace_dir = os.path.dirname(project_dir)
    sound_dirs = [
        os.path.join(base_dir, 'sounds'),
        os.path.join(base_dir, 'assets', 'sounds'),
        os.path.join(project_dir, 'assets', 'sounds'),
        os.path.join(workspace_dir, 'assets', 'sounds'),
    ]
    for snd_dir in sound_dirs:
        full = os.path.join(snd_dir, filename)
        if os.path.exists(full):
            return send_from_directory(snd_dir, filename)
    return jsonify({"error": "Sound not found"}), 404


# === API РОЗЫГРЫША ===

@app.route('/api/status')
def status():
    timer_seconds = None
    timer_stopped = False
    
    if giveaway["winner_picked_at"]:
        if giveaway["winner_first_message_at"]:
            timer_seconds = giveaway["winner_first_message_at"] - giveaway["winner_picked_at"]
            timer_stopped = True
        else:
            timer_seconds = time.time() - giveaway["winner_picked_at"]
            timer_stopped = False
    
    return jsonify({
        "video_id": giveaway["video_id"],
        "keyword": giveaway["keyword"],
        "accept_any_message": giveaway.get("accept_any_message", False),
        "participants": giveaway["participants"],
        "participants_data": giveaway["participants_data"],
        "count": len(giveaway["participants"]),
        "winner": giveaway["winner"],
        "pending_winner": giveaway.get("pending_winner"),
        "winner_avatar": giveaway["winner_avatar"],
        "winner_messages": giveaway["winner_messages"],
        "is_active": giveaway["is_active"],
        "is_connected": giveaway["is_connected"],
        "countdown": giveaway["countdown"],
        "is_test_mode": giveaway.get("is_test_mode", False),
        "timer_seconds": timer_seconds,
        "timer_stopped": timer_stopped
    })


@app.route('/api/start', methods=['POST'])
def start():
    data = request.json
    channel_input = data.get("channel", "")
    
    video_id = get_live_video_id(channel_input)
    
    if not video_id:
        return jsonify({"success": False, "error": "Не удалось найти активный стрим на этом канале"})
    
    uid = get_user_id()
    stop_event = get_stop_flag()
    stop_event.set()
    stop_event.clear()
    giveaway["video_id"] = video_id
    giveaway["keyword"] = data.get("keyword", "")
    giveaway["accept_any_message"] = bool(data.get("accept_any_message", False))
    giveaway["participants"] = []
    giveaway["participants_data"] = {}
    giveaway["winner"] = None
    giveaway["pending_winner"] = None
    giveaway["winner_avatar"] = None
    giveaway["winner_messages"] = []
    giveaway["winner_picked_at"] = None
    giveaway["winner_first_message_at"] = None
    giveaway["is_active"] = True
    giveaway["is_test_mode"] = False
    giveaway["test_participant_seq"] = 0
    giveaway["countdown"] = 0
    
    mode_text = "любое сообщение" if giveaway["accept_any_message"] else f"слово: {giveaway['keyword']}"
    print(f"🎲 Розыгрыш запущен! Режим: {mode_text}")
    
    thread = threading.Thread(target=watch_chat, args=(uid,), daemon=True)
    set_chat_thread(thread)
    thread.start()
    
    return jsonify({"success": True, "video_id": video_id})


@app.route('/api/start-test', methods=['POST'])
def start_test():
    data = request.get_json(silent=True) or {}
    get_stop_flag().set()

    giveaway["video_id"] = ""
    giveaway["keyword"] = str(data.get("keyword", "") or "")
    giveaway["accept_any_message"] = bool(data.get("accept_any_message", False))
    giveaway["participants"] = []
    giveaway["participants_data"] = {}
    giveaway["winner"] = None
    giveaway["pending_winner"] = None
    giveaway["winner_avatar"] = None
    giveaway["winner_messages"] = []
    giveaway["winner_picked_at"] = None
    giveaway["winner_first_message_at"] = None
    giveaway["is_active"] = True
    giveaway["is_connected"] = True
    giveaway["countdown"] = 0
    giveaway["is_test_mode"] = True
    giveaway["test_participant_seq"] = 0

    print("🧪 Тестовый розыгрыш запущен")
    return jsonify({"success": True, "is_test_mode": True})


@app.route('/api/test-add-participant', methods=['POST'])
def test_add_participant():
    if not giveaway.get("is_test_mode"):
        return jsonify({"success": False, "error": "Тестовый режим не запущен"})
    if int(giveaway.get("countdown") or 0) > 0:
        return jsonify({"success": False, "error": "Во время выбора добавить участника нельзя"})

    data = request.get_json(silent=True) or {}
    raw_name = str(data.get("name", "") or "").strip()
    avatar = str(data.get("avatar", "") or "").strip() or None

    if raw_name:
        base_name = raw_name
    else:
        giveaway["test_participant_seq"] = int(giveaway.get("test_participant_seq") or 0) + 1
        base_name = make_test_participant_name()

    name = base_name
    suffix = 2
    participants_set = set(giveaway.get("participants") or [])
    while name in participants_set:
        name = f"{base_name} ({suffix})"
        suffix += 1

    giveaway["participants"].append(name)
    giveaway["participants_data"][name] = {"avatar": avatar or make_letter_avatar(name)}
    print(f"🧪 + участник теста: {name} (Всего: {len(giveaway['participants'])})")

    return jsonify({"success": True, "participant": name, "count": len(giveaway["participants"])})


@app.route('/api/stop', methods=['POST'])
def stop():
    get_stop_flag().set()
    giveaway["is_active"] = False
    giveaway["is_test_mode"] = False
    giveaway["is_connected"] = False
    giveaway["countdown"] = 0
    print("⏹️ Розыгрыш остановлен")
    return jsonify({"success": True})


@app.route('/api/pick', methods=['POST'])
def pick():
    if not giveaway["participants"]:
        return jsonify({"success": False, "error": "Нет участников"})
    if int(giveaway.get("countdown") or 0) > 0:
        return jsonify({"success": False, "error": "Выбор уже идет"})
    planned_winner = random.choice(giveaway["participants"])
    giveaway["pending_winner"] = planned_winner
    
    def countdown_and_pick():
        for i in [5, 4, 3, 2, 1]:
            giveaway["countdown"] = i
            time.sleep(1)
        
        giveaway["countdown"] = 0
        winner = giveaway.get("pending_winner") or planned_winner
        giveaway["winner"] = winner
        giveaway["winner_avatar"] = giveaway["participants_data"].get(winner, {}).get("avatar")
        giveaway["winner_messages"] = []
        giveaway["winner_picked_at"] = time.time()
        giveaway["winner_first_message_at"] = None
        giveaway["is_active"] = False
        giveaway["pending_winner"] = winner
        print(f"🎉 Победитель: {giveaway['winner']}")
    
    thread = threading.Thread(target=countdown_and_pick, daemon=True)
    thread.start()
    
    return jsonify({"success": True})


@app.route('/api/reroll', methods=['POST'])
def reroll():
    if not giveaway["participants"] or not giveaway["winner"]:
        return jsonify({"success": False, "error": "Нет победителя для реролла"})
    if int(giveaway.get("countdown") or 0) > 0:
        return jsonify({"success": False, "error": "Реролл уже идет"})
    
    old_winner = giveaway["winner"]
    if old_winner in giveaway["participants"]:
        giveaway["participants"].remove(old_winner)
    if old_winner in giveaway["participants_data"]:
        del giveaway["participants_data"][old_winner]
    
    if not giveaway["participants"]:
        return jsonify({"success": False, "error": "Больше нет участников"})
    planned_winner = random.choice(giveaway["participants"])
    giveaway["pending_winner"] = planned_winner
    
    def countdown_and_reroll():
        for i in [5, 4, 3, 2, 1]:
            giveaway["countdown"] = i
            time.sleep(1)
        
        giveaway["countdown"] = 0
        winner = giveaway.get("pending_winner") or planned_winner
        giveaway["winner"] = winner
        giveaway["winner_avatar"] = giveaway["participants_data"].get(winner, {}).get("avatar")
        giveaway["winner_messages"] = []
        giveaway["winner_picked_at"] = time.time()
        giveaway["winner_first_message_at"] = None
        giveaway["pending_winner"] = winner
        print(f"🔄 Реролл! Новый победитель: {giveaway['winner']}")
    
    thread = threading.Thread(target=countdown_and_reroll, daemon=True)
    thread.start()
    
    return jsonify({"success": True, "old_winner": old_winner})


@app.route('/api/giveaway-update', methods=['POST'])
def giveaway_update():
    """Смена ключевого слова / режима без перезапуска чата."""
    data = request.get_json(silent=True) or {}
    if "keyword" in data:
        giveaway["keyword"] = str(data.get("keyword") or "")
    if "accept_any_message" in data:
        giveaway["accept_any_message"] = bool(data.get("accept_any_message"))
    return jsonify({"success": True})


@app.route('/api/reconnect-chat', methods=['POST'])
def reconnect_chat():
    """Сохранить канал и переподключить pytchat, не сбрасывая участников/победителя."""
    data = request.get_json(silent=True) or {}
    channel_input = (data.get("channel") or saved_channel.get("channel_id") or "").strip()
    if not channel_input:
        return jsonify({"success": False, "error": "Укажите канал или сохраните ссылку"})
    video_id = get_live_video_id(channel_input)
    if not video_id:
        return jsonify({"success": False, "error": "Не удалось найти активный стрим"})

    saved_channel["channel_id"] = channel_input
    save_channel()

    should_run = bool(giveaway.get("is_active") or giveaway.get("winner"))
    if not should_run:
        giveaway["video_id"] = video_id
        return jsonify({"success": True, "video_id": video_id, "saved_only": True})

    stop_event = get_stop_flag()
    stop_event.set()
    t = get_chat_thread()
    if t and t.is_alive():
        t.join(timeout=5.0)

    stop_event.clear()
    giveaway["video_id"] = video_id
    uid = get_user_id()
    thread = threading.Thread(target=watch_chat, args=(uid,), daemon=True)
    set_chat_thread(thread)
    thread.start()
    return jsonify({"success": True, "video_id": video_id})


@app.route('/api/reset', methods=['POST'])
def reset():
    get_stop_flag().set()
    giveaway["video_id"] = ""
    giveaway["keyword"] = ""
    giveaway["accept_any_message"] = False
    giveaway["participants"] = []
    giveaway["participants_data"] = {}
    giveaway["winner"] = None
    giveaway["pending_winner"] = None
    giveaway["winner_avatar"] = None
    giveaway["winner_messages"] = []
    giveaway["winner_picked_at"] = None
    giveaway["winner_first_message_at"] = None
    giveaway["is_active"] = False
    giveaway["is_connected"] = False
    giveaway["countdown"] = 0
    giveaway["is_test_mode"] = False
    giveaway["test_participant_seq"] = 0
    print("🔄 Сброс")
    return jsonify({"success": True})


# === API КАНАЛА ===

@app.route('/api/channel')
def get_channel():
    load_channel()
    return jsonify(saved_channel)


@app.route('/api/channel', methods=['POST'])
def update_channel():
    global saved_channel
    saved_channel = request.json
    save_channel()
    return jsonify({"success": True})


# === API НАСТРОЕК ВИДЖЕТА ===

def _clamp_int(value, default, min_v, max_v):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(min_v, min(max_v, number))


def _normalized_widget_settings(data=None):
    current = data if data is not None else _get_widget_settings_mutable()
    base = {**default_widget_settings, **current}
    base["width"] = _clamp_int(base.get("width"), 400, 100, 1080)
    base["height"] = _clamp_int(base.get("height"), 50, 30, 300)
    base["border_radius"] = _clamp_int(base.get("border_radius"), 10, 0, 50)
    align = str(base.get("widget_align_h") or "left")
    if align not in ("left", "center", "right"):
        align = "left"
    base["widget_align_h"] = align
    return base


@app.route('/api/widget-settings')
def get_widget_settings():
    with _settings_lock:
        load_settings()
        return jsonify(_normalized_widget_settings())


@app.route('/api/widget-settings', methods=['POST'])
def update_widget_settings():
    global widget_settings
    try:
        with _settings_lock:
            uid = _settings_user_id()
            current = _get_widget_settings_mutable()
            incoming = request.get_json(silent=True)
            if not isinstance(incoming, dict):
                incoming = {}
            if incoming.pop("_reset", False):
                new_settings = _normalized_widget_settings(default_widget_settings.copy())
            else:
                new_settings = _normalized_widget_settings(
                    {**default_widget_settings, **current, **incoming}
                )
            _settings_cache[uid] = new_settings
            widget_settings = new_settings
            _persist_widget_settings(new_settings)
        return jsonify({"success": True, "settings": new_settings})
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route('/api/fonts')
def get_fonts():
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
    fonts = []
    
    if os.path.exists(fonts_dir):
        for file in os.listdir(fonts_dir):
            if file.endswith(('.ttf', '.otf', '.woff', '.woff2')):
                fonts.append(file)
    
    return jsonify(fonts)


@app.route('/api/images')
def get_images():
    images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'images')
    images = []
    
    if os.path.exists(images_dir):
        for file in os.listdir(images_dir):
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                images.append(file)
    
    return jsonify(images)


# === ЗАПУСК ===

if __name__ == '__main__':
    for folder in ['fonts', 'images']:
        folder_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), folder)
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
            print(f"📁 Создана папка: {folder_path}")
    
    print("=" * 50)
    print("🎲 СЕРВЕР РОЗЫГРЫШЕЙ ЗАПУЩЕН")
    print("=" * 50)
    print("📍 Панель управления:   http://localhost:5000")
    print("📍 OBS Dock (компакт):  http://localhost:5000/obs-dock")
    print("📍 Конструктор виджета: http://localhost:5000/constructor")
    print("📍 Виджет для OBS:      http://localhost:5000/widget")
    print("=" * 50)
    print()
    app.run(debug=False, port=5000, threaded=True)