import sys
from flask import Flask, render_template, jsonify, request, send_from_directory, g, session, redirect, url_for, has_app_context
import pytchat
import threading
import random
import time
import json
import os
import re
from urllib.parse import quote, urlencode

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
    get_chat_thread_for_user,
    set_chat_thread_for_user,
    bump_chat_session,
    get_chat_session,
    list_giveaway_user_ids,
    resolve_user,
    _chat_instances,
)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BOT_DIR, "widget_settings.json")
CHANNEL_PATH = os.path.join(BOT_DIR, "channel.json")

# Встроенные фоны виджета (не показываются в списке «выбрать картинку»)
DEFAULT_BG_IMAGE_ACTIVE = "default-active.jpg"
DEFAULT_BG_IMAGE_WINNER = "default-winner.jpg"
_BUILTIN_BG_IMAGES = {
    DEFAULT_BG_IMAGE_ACTIVE,
    DEFAULT_BG_IMAGE_WINNER,
    # старые имена до переименования
    "17490234969549.jpg",
    "gradient-background-geometric-gradient-wallpaper-abstract-background-premium-gradient_1003782-672.jpg",
}

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
    "bg_type_active": "default",
    "bg_color_1": "#667eea",
    "bg_color_2": "#764ba2",
    "bg_colors_active": ["#667eea", "#764ba2"],
    "bg_image_active": "",
    "bg_anim_style_active": "shift",
    "bg_anim_speed_active": 6,
    "bg_anim_angle_active": 135,
    "bg_anim_ease_active": "ease",
    "bg_grain_active": 25,
    "bg_type_winner": "default",
    "winner_bg_1": "#f39c12",
    "winner_bg_2": "#e74c3c",
    "bg_colors_winner": ["#f39c12", "#e74c3c"],
    "bg_image_winner": "",
    "bg_anim_style_winner": "shift",
    "bg_anim_speed_winner": 6,
    "bg_anim_angle_winner": 135,
    "bg_anim_ease_winner": "ease",
    "bg_grain_winner": 25,
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
_settings_lock = threading.RLock()
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

    channel_input = (channel_input or "").strip()
    if not channel_input:
        return None

    # Уже video id
    if re.match(r'^[a-zA-Z0-9_-]{11}$', channel_input):
        return channel_input

    # Прямая ссылка на видео / шортс /live/ID
    m = re.search(
        r'(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^#]*&)?v=|live/|shorts/|embed/))([a-zA-Z0-9_-]{11})',
        channel_input,
    )
    if m:
        video_id = m.group(1)
        print(f"✅ Video id из ссылки: {video_id}")
        return video_id

    if channel_input.startswith('@'):
        live_url = f"https://www.youtube.com/{channel_input}/live"
    elif 'youtube.com/' in channel_input:
        base = channel_input.split('?')[0].split('#')[0].rstrip('/')
        if base.endswith('/live'):
            live_url = base
        else:
            live_url = f"{base}/live"
    elif channel_input.startswith('UC'):
        live_url = f"https://www.youtube.com/channel/{channel_input}/live"
    else:
        handle = channel_input.lstrip('@')
        live_url = f"https://www.youtube.com/@{handle}/live"

    try:
        print(f"🔍 Ищу стрим: {live_url}")

        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
        }
        req = urllib.request.Request(live_url, headers=headers)

        with urllib.request.urlopen(req, timeout=12) as response:
            final_url = response.geturl() or ""
            html = response.read().decode('utf-8', errors='ignore')

            # 1) После редиректа /live → /watch?v=… / /live/ID — самый надёжный id
            m = re.search(
                r'(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^#]*&)?v=|live/|shorts/|embed/))([a-zA-Z0-9_-]{11})',
                final_url,
            )
            if m:
                video_id = m.group(1)
                print(f"✅ Найден стрим (redirect): {video_id}")
                return video_id

            m = re.search(
                r'<link rel="canonical" href="[^"]*(?:v=|live/)([a-zA-Z0-9_-]{11})',
                html,
            )
            if m:
                video_id = m.group(1)
                print(f"✅ Найден стрим (canonical): {video_id}")
                return video_id

            # 2) Только id с isLiveNow — не берём случайный videoId со страницы (это был баг)
            for pattern in (
                r'"videoId":"([a-zA-Z0-9_-]{11})"[^}]{0,400}"isLiveNow"\s*:\s*true',
                r'"isLiveNow"\s*:\s*true[^}]{0,400}"videoId":"([a-zA-Z0-9_-]{11})"',
                r'"isLiveNow":true.{0,1200}?"videoId":"([a-zA-Z0-9_-]{11})"',
                r'"videoId":"([a-zA-Z0-9_-]{11})".{0,1200}?"isLiveNow":true',
            ):
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    video_id = match.group(1)
                    print(f"✅ Найден стрим (isLiveNow): {video_id}")
                    return video_id

    except Exception as e:
        print(f"❌ Ошибка поиска стрима: {e}")

    return None


def _channel_page_url(channel_input: str) -> str:
    s = (channel_input or "").strip()
    if not s:
        return ""
    if re.match(r'^[a-zA-Z0-9_-]{11}$', s):
        return f"https://www.youtube.com/watch?v={s}"
    m = re.search(
        r'(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^#]*&)?v=|live/|shorts/|embed/))([a-zA-Z0-9_-]{11})',
        s,
    )
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    if s.startswith('@'):
        return f"https://www.youtube.com/{s}"
    if 'youtube.com/' in s:
        return s.split('?')[0].split('#')[0].rstrip('/').replace('/live', '')
    if s.startswith('UC') and re.match(r'^UC[\w-]{20,}$', s):
        return f"https://www.youtube.com/channel/{s}"
    return f"https://www.youtube.com/@{s.lstrip('@')}"


_channel_meta_cache: dict[str, tuple[float, dict]] = {}


def _is_weak_channel_avatar(url: str) -> bool:
    u = (url or "").lower()
    return (not u) or ("default-user" in u)


def _is_weak_channel_title(title: str, raw: str = "", handle: str = "") -> bool:
    t = (title or "").strip()
    if not t:
        return True
    if t.startswith("@"):
        return True
    if raw and t == raw.strip():
        return True
    if handle and t == handle:
        return True
    return False


def _innertube_channel_from_video(video_id: str) -> dict:
    """Имя/аватар через Innertube — работает на VPS, когда HTML канала режется."""
    import urllib.request

    if not video_id:
        return {}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    ctx = {
        "client": {
            "clientName": "WEB",
            "clientVersion": "2.20260811.01.00",
            "hl": "ru",
            "gl": "RU",
        }
    }
    out: dict = {}
    try:
        body = json.dumps({"context": ctx, "videoId": video_id}).encode("utf-8")
        req = urllib.request.Request(
            "https://www.youtube.com/youtubei/v1/player?prettyPrint=false",
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        vd = data.get("videoDetails") or {}
        mf = ((data.get("microformat") or {}).get("playerMicroformatRenderer") or {})
        title = (vd.get("author") or mf.get("ownerChannelName") or "").strip()
        handle = ""
        profile = mf.get("ownerProfileUrl") or ""
        m = re.search(r"/(@[\w.-]+)", profile)
        if m:
            handle = m.group(1)
        if title:
            out["title"] = title
        if handle:
            out["handle"] = handle
        if vd.get("channelId"):
            out["uc_id"] = vd.get("channelId")
    except Exception:
        pass

    try:
        body = json.dumps({"context": ctx, "videoId": video_id}).encode("utf-8")
        req = urllib.request.Request(
            "https://www.youtube.com/youtubei/v1/next?prettyPrint=false",
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        blob = json.dumps(data, ensure_ascii=False)
        # Берём первую «пачку» аватаров владельца (один hash, разные размеры)
        avatars = re.findall(
            r"https://yt3\.(?:ggpht|googleusercontent)\.com/[A-Za-z0-9_\-.=%]+",
            blob,
        )
        avatars = [u for u in avatars if "default-user" not in u]
        if avatars:
            # предпочитаем более крупный размер того же hash
            best = avatars[0]
            base = best.split("=")[0]
            same = [u for u in avatars if u.startswith(base)]
            for pref in ("=s800-", "=s176-", "=s88-", "=s48-"):
                hit = next((u for u in same if pref in u), None)
                if hit:
                    best = hit
                    break
            else:
                best = same[-1] if same else best
            out["avatar"] = best
    except Exception:
        pass
    return out


def fetch_channel_profile(channel_input: str) -> dict:
    """Название + аватар канала (кэш ~1ч)."""
    import urllib.request

    raw = (channel_input or "").strip()
    if not raw:
        return {"ok": False, "error": "empty"}

    now = time.time()
    hit = _channel_meta_cache.get(raw)
    if hit and now - hit[0] < 3600:
        cached = dict(hit[1])
        weak = _is_weak_channel_title(
            cached.get("title") or "", raw, cached.get("handle") or ""
        ) or _is_weak_channel_avatar(cached.get("avatar") or "")
        # слабый ответ кэшируем только ~60с
        if cached.get("ok") and not weak:
            return cached
        if weak and now - hit[0] < 60:
            return cached

    page = _channel_page_url(raw)
    out = {
        "ok": False,
        "channel_id": raw,
        "title": "",
        "avatar": "",
        "handle": "",
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    if raw.startswith("@"):
        out["handle"] = raw.split("/")[0]
    else:
        m = re.search(r"youtube\.com/(@[\w.-]+)", raw)
        if m:
            out["handle"] = m.group(1)

    html = ""
    try:
        req = urllib.request.Request(page, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        out["error"] = str(e)

    if html:
        title = ""
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
        if m:
            title = m.group(1)
        if not title:
            m = re.search(
                r'"channelMetadataRenderer"\s*:\s*\{[^}]*"title"\s*:\s*"((?:\\.|[^"\\])*)"',
                html,
            )
            if m:
                title = m.group(1).encode("utf-8").decode("unicode_escape")
        if not title:
            m = re.search(r'<meta\s+name="title"\s+content="([^"]+)"', html)
            if m:
                title = m.group(1)
        if title:
            title = title.replace(" - YouTube", "").strip()

        avatar = ""
        for m in re.finditer(
            r'"url"\s*:\s*"(https://yt3\.(?:ggpht|googleusercontent)\.com/[^"]+)"',
            html,
        ):
            cand = m.group(1)
            if not _is_weak_channel_avatar(cand):
                avatar = cand
                break
        if not avatar:
            m = re.search(r'<meta\s+property="og:image"\s+content="(https://[^"]+)"', html)
            if m and not _is_weak_channel_avatar(m.group(1)):
                avatar = m.group(1)

        handle = out.get("handle") or ""
        m = re.search(r'"canonicalBaseUrl"\s*:\s*"/(@[^"]+)"', html)
        if m:
            handle = m.group(1)

        if title and not _is_weak_channel_title(title, raw, handle):
            out["title"] = title
        if avatar:
            out["avatar"] = avatar
        if handle:
            out["handle"] = handle

    # Fallback для VPS: YouTube часто режет HTML канала, но отдаёт player/next по live video
    need_title = _is_weak_channel_title(out.get("title") or "", raw, out.get("handle") or "")
    need_avatar = _is_weak_channel_avatar(out.get("avatar") or "")
    if need_title or need_avatar:
        video_id = None
        m = re.search(
            r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^#]*&)?v=|live/|shorts/|embed/))([a-zA-Z0-9_-]{11})",
            raw,
        )
        if m:
            video_id = m.group(1)
        if not video_id:
            try:
                video_id = get_live_video_id(raw)
            except Exception:
                video_id = None
        if video_id:
            extra = _innertube_channel_from_video(video_id)
            if need_title and extra.get("title"):
                out["title"] = extra["title"]
            if need_avatar and extra.get("avatar"):
                out["avatar"] = extra["avatar"]
            if not out.get("handle") and extra.get("handle"):
                out["handle"] = extra["handle"]

    # oEmbed — ещё один шанс взять имя
    if _is_weak_channel_title(out.get("title") or "", raw, out.get("handle") or ""):
        try:
            oembed_url = page
            if "/watch" not in oembed_url:
                oembed_url = page.rstrip("/") + "/live"
            q = urlencode({"url": oembed_url, "format": "json"})
            req = urllib.request.Request(
                "https://www.youtube.com/oembed?" + q,
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            author = (data.get("author_name") or "").strip()
            if author and not _is_weak_channel_title(author, raw, out.get("handle") or ""):
                out["title"] = author
        except Exception:
            pass

    if not out.get("title"):
        out["title"] = out.get("handle") or raw
    out["ok"] = bool(
        out.get("title")
        and not _is_weak_channel_title(out.get("title") or "", raw, out.get("handle") or "")
    ) or (not _is_weak_channel_avatar(out.get("avatar") or ""))
    if out["ok"]:
        out["error"] = ""
    elif not out.get("error"):
        out["error"] = "meta_not_found"

    _channel_meta_cache[raw] = (now, dict(out))
    return out


def enrich_saved_channel(channel_id: str) -> dict:
    """Сохранить channel_id + title/avatar/handle."""
    profile = fetch_channel_profile(channel_id)
    return {
        "channel_id": channel_id,
        "title": profile.get("title") or "",
        "avatar": profile.get("avatar") or "",
        "handle": profile.get("handle") or "",
    }


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


def _chat_should_listen(gw: dict) -> bool:
    """Keep listening while collecting participants or waiting for winner reply."""
    if gw.get("is_test_mode"):
        return False
    return bool(gw.get("is_active") or gw.get("winner"))


def _terminate_chat_instance(user_id: int) -> None:
    inst = _chat_instances.get(user_id)
    if inst is None:
        return
    for meth in ("terminate", "stop"):
        fn = getattr(inst, meth, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
            break


def _stop_chat_watcher(user_id: int, join_timeout: float = 5.0) -> None:
    """Politely stop current watcher. Does not clear giveaway participants/winner."""
    stop_event = get_stop_flag_for_user(user_id)
    stop_event.set()
    bump_chat_session(user_id)
    gw = get_giveaway_for_user(user_id)
    gw["chat_reconnecting"] = False
    _terminate_chat_instance(user_id)
    t = get_chat_thread_for_user(user_id)
    if t and t.is_alive() and t is not threading.current_thread():
        t.join(timeout=join_timeout)
    if _chat_instances.get(user_id) is not None:
        _chat_instances.pop(user_id, None)
    gw["is_connected"] = False


def _start_chat_watcher(user_id: int) -> None:
    """Start (or replace) chat watcher. Never resets participants/winner/timer."""
    _stop_chat_watcher(user_id)
    stop_event = get_stop_flag_for_user(user_id)
    stop_event.clear()
    session_id = bump_chat_session(user_id)
    gw = get_giveaway_for_user(user_id)
    gw["chat_reconnecting"] = False
    thread = threading.Thread(
        target=watch_chat, args=(user_id, session_id), daemon=True, name=f"watch-chat-{user_id}"
    )
    set_chat_thread_for_user(user_id, thread)
    thread.start()


def watch_chat(user_id: int, session_id: int | None = None):
    """
    Listen to YouTube chat. If the connection drops while the giveaway still needs
    chat (active collection or winner waiting), auto-reconnect with backoff.
    Never clears participants / winner / timer.
    """
    gw = get_giveaway_for_user(user_id)
    stop_event = get_stop_flag_for_user(user_id)
    if session_id is None:
        session_id = get_chat_session(user_id)

    backoff = 1.0
    max_backoff = 12.0
    gw["chat_last_ok_at"] = None
    gw["chat_last_error"] = ""

    def still_mine() -> bool:
        return get_chat_session(user_id) == session_id and not stop_event.is_set()

    while still_mine() and _chat_should_listen(gw):
        video_id = (gw.get("video_id") or "").strip()
        if not video_id:
            break

        chat_instance = None
        try:
            if still_mine():
                gw["is_connected"] = False
                gw["chat_reconnecting"] = True

            chat_instance = pytchat.create(video_id=video_id, interruptable=False)
            if not still_mine():
                try:
                    if hasattr(chat_instance, "terminate"):
                        chat_instance.terminate()
                except Exception:
                    pass
                break

            _chat_instances[user_id] = chat_instance
            gw["is_connected"] = True
            gw["chat_reconnecting"] = False
            gw["chat_last_ok_at"] = time.time()
            gw["chat_last_error"] = ""
            backoff = 1.0
            print(f"✅ Подключился к чату: {video_id} (user {user_id})")

            while (
                still_mine()
                and _chat_should_listen(gw)
                and chat_instance.is_alive()
            ):
                try:
                    items = chat_instance.get()
                    if not still_mine():
                        break
                    batch = items.sync_items()
                    if batch:
                        gw["chat_last_ok_at"] = time.time()
                    for message in batch:
                        if not still_mine():
                            break
                        author, avatar = get_author_info(message)
                        text = message.message or ""

                        if gw["winner"] and author == gw["winner"]:
                            if gw["winner_first_message_at"] is None:
                                gw["winner_first_message_at"] = time.time()
                                print(
                                    f"⏱️ Победитель ответил! "
                                    f"Время: {time.time() - gw['winner_picked_at']:.1f} сек"
                                )

                            gw["winner_messages"].append({
                                "time": time.strftime("%H:%M:%S"),
                                "text": text,
                            })
                            gw["winner_messages"] = gw["winner_messages"][-50:]
                            print(f"💬 {author}: {text}")

                        keyword_ok = (
                            gw["keyword"].lower() in text.lower() if gw["keyword"] else False
                        )
                        accept_by_mode = gw.get("accept_any_message", False) or keyword_ok
                        selection_in_progress = int(gw.get("countdown") or 0) > 0
                        session_collecting = gw["is_active"] or bool(gw.get("winner"))
                        if session_collecting and (not selection_in_progress) and accept_by_mode:
                            if author and author not in gw["participants"]:
                                gw["participants"].append(author)
                                gw["participants_data"][author] = {"avatar": avatar}
                                print(
                                    f"✅ {author} участвует! "
                                    f"(Всего: {len(gw['participants'])})"
                                )

                except Exception as e:
                    gw["chat_last_error"] = str(e)
                    print(f"Ошибка чтения: {e}")
                    # Transient read error — keep trying until is_alive dies
                    if stop_event.wait(0.35):
                        break
                    continue

                if stop_event.wait(0.25):
                    break

        except Exception as e:
            gw["chat_last_error"] = str(e)
            print(f"Ошибка чата: {e}")
        finally:
            if still_mine():
                if chat_instance is not None and _chat_instances.get(user_id) is chat_instance:
                    _chat_instances.pop(user_id, None)
                gw["is_connected"] = False
            else:
                # Superseded by a newer watcher — don't touch shared connection flags
                if chat_instance is not None and _chat_instances.get(user_id) is chat_instance:
                    _chat_instances.pop(user_id, None)
                try:
                    if chat_instance is not None and hasattr(chat_instance, "terminate"):
                        chat_instance.terminate()
                except Exception:
                    pass

        if not still_mine() or not _chat_should_listen(gw):
            break

        # Connection dropped while session still needs chat — auto-reconnect
        gw["chat_reconnecting"] = True
        wait_s = backoff
        print(
            f"♻️ Чат отвалился (user {user_id}), "
            f"переподключение через {wait_s:.0f}с… "
            f"(участники/победитель сохранены)"
        )
        if stop_event.wait(wait_s):
            break
        if not still_mine() or not _chat_should_listen(gw):
            break
        backoff = min(backoff * 1.7, max_backoff)

    if still_mine():
        gw["is_connected"] = False
        gw["chat_reconnecting"] = False
        print(f"❌ Отключился от чата (user {user_id})")


_watchdog_started = False
_watchdog_lock = threading.Lock()


def _chat_watchdog_loop():
    """Если watcher умер или video_id устарел (новый эфир) — переподключить."""
    while True:
        time.sleep(15)
        try:
            for uid in list_giveaway_user_ids():
                gw = get_giveaway_for_user(uid)
                if gw.get("is_test_mode"):
                    continue
                if not _chat_should_listen(gw):
                    continue
                channel = (gw.get("bound_channel") or "").strip()
                if not channel:
                    stored = _channel_cache.get(uid) or {}
                    channel = (stored.get("channel_id") or "").strip()

                thread = get_chat_thread_for_user(uid)
                alive = bool(thread and thread.is_alive())

                # Перепроверка актуального эфира: стример мог начать новый эфир
                if channel:
                    try:
                        fresh = get_live_video_id(channel)
                    except Exception as exc:
                        fresh = None
                        print(f"🛡 Watchdog resolve failed (user {uid}): {exc}")
                    cur = (gw.get("video_id") or "").strip()
                    if fresh and cur and fresh != cur:
                        print(
                            f"🛡 Watchdog: новый эфир {fresh} (был {cur}) — переподключение (user {uid})"
                        )
                        gw["video_id"] = fresh
                        try:
                            _start_chat_watcher(uid)
                        except Exception as exc:
                            print(f"🛡 Watchdog restart failed (user {uid}): {exc}")
                        continue

                if not (gw.get("video_id") or "").strip():
                    continue
                if alive:
                    continue
                print(f"🛡 Watchdog: поток чата мёртв — перезапуск (user {uid})")
                try:
                    _start_chat_watcher(uid)
                except Exception as exc:
                    print(f"🛡 Watchdog restart failed (user {uid}): {exc}")
        except Exception as exc:
            print(f"🛡 Watchdog error: {exc}")


def ensure_chat_watchdog() -> None:
    global _watchdog_started
    with _watchdog_lock:
        if _watchdog_started:
            return
        _watchdog_started = True
        threading.Thread(
            target=_chat_watchdog_loop, daemon=True, name="chat-watchdog"
        ).start()


ensure_chat_watchdog()


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

    load_channel()

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
        "chat_reconnecting": bool(giveaway.get("chat_reconnecting")),
        "chat_last_error": giveaway.get("chat_last_error") or "",
        "channel_id": (saved_channel.get("channel_id") or ""),
        "channel_title": (saved_channel.get("title") or ""),
        "channel_avatar": (saved_channel.get("avatar") or ""),
        "channel_handle": (saved_channel.get("handle") or ""),
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
    # Запомнить канал при запуске
    saved_channel.clear()
    saved_channel.update(enrich_saved_channel(channel_input.strip()))
    if uid:
        _channel_cache[uid] = dict(saved_channel)
    save_channel()
    giveaway["bound_channel"] = channel_input.strip()

    # Сброс состояния розыгрыша — чат перезапускаем отдельно, без гонки stop/clear
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
    giveaway["is_connected"] = False
    giveaway["chat_reconnecting"] = False
    giveaway["chat_last_ok_at"] = None
    giveaway["chat_last_error"] = ""
    
    mode_text = "любое сообщение" if giveaway["accept_any_message"] else f"слово: {giveaway['keyword']}"
    print(f"🎲 Розыгрыш запущен! Режим: {mode_text} video={video_id}")
    
    _start_chat_watcher(uid)
    
    return jsonify({"success": True, "video_id": video_id})


@app.route('/api/start-test', methods=['POST'])
def start_test():
    data = request.get_json(silent=True) or {}
    uid = get_user_id()
    _stop_chat_watcher(uid)

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
    giveaway["chat_reconnecting"] = False
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
    uid = get_user_id()
    giveaway["is_active"] = False
    giveaway["is_test_mode"] = False
    giveaway["countdown"] = 0
    if giveaway.get("winner"):
        # Сбор стоп, чат оставляем — ждём ответ победителя (авто-reconnect тоже работает)
        print("⏹️ Сбор остановлен, чат ждёт сообщение победителя")
    else:
        _stop_chat_watcher(uid)
        print("⏹️ Розыгрыш остановлен")
    return jsonify({"success": True})


@app.route('/api/pick', methods=['POST'])
def pick():
    gw = get_giveaway()
    if not gw["participants"]:
        return jsonify({"success": False, "error": "Нет участников"})
    if int(gw.get("countdown") or 0) > 0:
        return jsonify({"success": False, "error": "Выбор уже идет"})
    planned_winner = random.choice(gw["participants"])
    gw["pending_winner"] = planned_winner
    gw["countdown"] = 5
    # Важно: в фоне нет Flask request context → нельзя писать через proxy giveaway
    # (он уйдёт в user_id=0). Держим прямой dict текущего пользователя.
    uid = get_user_id()

    def countdown_and_pick(user_id: int, planned: str):
        state = get_giveaway_for_user(user_id)
        for i in [5, 4, 3, 2, 1]:
            state["countdown"] = i
            time.sleep(1)

        state["countdown"] = 0
        winner = state.get("pending_winner") or planned
        state["winner"] = winner
        state["winner_avatar"] = state["participants_data"].get(winner, {}).get("avatar")
        state["winner_messages"] = []
        state["winner_picked_at"] = time.time()
        state["winner_first_message_at"] = None
        state["is_active"] = False
        state["pending_winner"] = winner
        print(f"🎉 Победитель: {state['winner']} (user {user_id})")

    thread = threading.Thread(
        target=countdown_and_pick, args=(uid, planned_winner), daemon=True
    )
    thread.start()

    return jsonify({"success": True, "pending_winner": planned_winner})


@app.route('/api/reroll', methods=['POST'])
def reroll():
    gw = get_giveaway()
    if not gw["participants"] or not gw["winner"]:
        return jsonify({"success": False, "error": "Нет победителя для реролла"})
    if int(gw.get("countdown") or 0) > 0:
        return jsonify({"success": False, "error": "Реролл уже идет"})

    old_winner = gw["winner"]
    if old_winner in gw["participants"]:
        gw["participants"].remove(old_winner)
    if old_winner in gw["participants_data"]:
        del gw["participants_data"][old_winner]

    if not gw["participants"]:
        return jsonify({"success": False, "error": "Больше нет участников"})
    planned_winner = random.choice(gw["participants"])
    gw["pending_winner"] = planned_winner
    gw["countdown"] = 5
    uid = get_user_id()

    def countdown_and_reroll(user_id: int, planned: str):
        state = get_giveaway_for_user(user_id)
        for i in [5, 4, 3, 2, 1]:
            state["countdown"] = i
            time.sleep(1)

        state["countdown"] = 0
        winner = state.get("pending_winner") or planned
        state["winner"] = winner
        state["winner_avatar"] = state["participants_data"].get(winner, {}).get("avatar")
        state["winner_messages"] = []
        state["winner_picked_at"] = time.time()
        state["winner_first_message_at"] = None
        state["pending_winner"] = winner
        print(f"🔄 Реролл! Новый победитель: {state['winner']} (user {user_id})")

    thread = threading.Thread(
        target=countdown_and_reroll, args=(uid, planned_winner), daemon=True
    )
    thread.start()

    return jsonify({"success": True, "old_winner": old_winner, "pending_winner": planned_winner})


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
    global saved_channel
    data = request.get_json(silent=True) or {}
    channel_input = (data.get("channel") or saved_channel.get("channel_id") or "").strip()
    if not channel_input:
        return jsonify({"success": False, "error": "Укажите канал или сохраните ссылку"})
    video_id = get_live_video_id(channel_input)
    if not video_id:
        return jsonify({"success": False, "error": "Не удалось найти активный стрим"})

    saved_channel = enrich_saved_channel(channel_input)
    uid = get_user_id()
    if uid:
        _channel_cache[uid] = dict(saved_channel)
    save_channel()
    giveaway["bound_channel"] = channel_input

    giveaway["video_id"] = video_id
    should_run = bool(giveaway.get("is_active") or giveaway.get("winner"))
    if not should_run or giveaway.get("is_test_mode"):
        return jsonify({"success": True, "video_id": video_id, "saved_only": True, **saved_channel})

    _start_chat_watcher(uid)
    return jsonify({"success": True, "video_id": video_id, **saved_channel})


@app.route('/api/reset', methods=['POST'])
def reset():
    uid = get_user_id()
    _stop_chat_watcher(uid)
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
    giveaway["chat_reconnecting"] = False
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
    data = request.get_json(silent=True) or {}
    channel_id = str(data.get("channel_id") or data.get("channel") or "").strip()
    if not channel_id:
        return jsonify({"success": False, "error": "Пустой канал"}), 400
    saved_channel = enrich_saved_channel(channel_id)
    uid = _settings_user_id()
    if uid:
        _channel_cache[uid] = dict(saved_channel)
    save_channel()
    return jsonify({"success": True, **saved_channel})


@app.route('/api/channel-meta')
def channel_meta_api():
    channel = (request.args.get("channel") or saved_channel.get("channel_id") or "").strip()
    if not channel:
        load_channel()
        channel = (saved_channel.get("channel_id") or "").strip()
    if not channel:
        return jsonify({"ok": False, "error": "no_channel"})
    return jsonify(fetch_channel_profile(channel))


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

    # Старые пресеты с «выбранной» дефолтной картинкой → тип «по умолчанию»
    if base.get("bg_type_active") == "image" and (base.get("bg_image_active") or "") in _BUILTIN_BG_IMAGES:
        base["bg_type_active"] = "default"
        base["bg_image_active"] = ""
    if base.get("bg_type_winner") == "image" and (base.get("bg_image_winner") or "") in _BUILTIN_BG_IMAGES:
        base["bg_type_winner"] = "default"
        base["bg_image_winner"] = ""
    _bg_types = ("default", "gradient", "color", "image", "animated_gradient")
    _anim_styles = ("shift", "flow", "pulse", "spin")
    _anim_eases = ("ease", "linear", "ease-in-out")
    if base.get("bg_type_active") not in _bg_types:
        base["bg_type_active"] = "default"
    if base.get("bg_type_winner") not in _bg_types:
        base["bg_type_winner"] = "default"
    if base.get("bg_anim_style_active") not in _anim_styles:
        base["bg_anim_style_active"] = "shift"
    if base.get("bg_anim_style_winner") not in _anim_styles:
        base["bg_anim_style_winner"] = "shift"
    if base.get("bg_anim_ease_active") not in _anim_eases:
        base["bg_anim_ease_active"] = "ease"
    if base.get("bg_anim_ease_winner") not in _anim_eases:
        base["bg_anim_ease_winner"] = "ease"
    base["bg_anim_speed_active"] = _clamp_int(base.get("bg_anim_speed_active"), 6, 1, 30)
    base["bg_anim_speed_winner"] = _clamp_int(base.get("bg_anim_speed_winner"), 6, 1, 30)
    base["bg_anim_angle_active"] = _clamp_int(base.get("bg_anim_angle_active"), 135, 0, 360)
    base["bg_anim_angle_winner"] = _clamp_int(base.get("bg_anim_angle_winner"), 135, 0, 360)
    base["bg_grain_active"] = _clamp_int(base.get("bg_grain_active"), 25, 0, 100)
    base["bg_grain_winner"] = _clamp_int(base.get("bg_grain_winner"), 25, 0, 100)

    def _norm_colors(raw, c1, c2, fallback):
        colors = []
        if isinstance(raw, list):
            for item in raw[:8]:
                s = str(item or "").strip()
                if re.match(r"^#[0-9A-Fa-f]{6}$", s):
                    colors.append(s.lower())
        if len(colors) < 1:
            a = str(c1 or "").strip()
            b = str(c2 or "").strip()
            if re.match(r"^#[0-9A-Fa-f]{6}$", a):
                colors.append(a.lower())
            if re.match(r"^#[0-9A-Fa-f]{6}$", b) and b.lower() not in colors:
                colors.append(b.lower())
        if len(colors) < 1:
            colors = list(fallback)
        return colors

    base["bg_colors_active"] = _norm_colors(
        base.get("bg_colors_active"),
        base.get("bg_color_1"),
        base.get("bg_color_2"),
        ["#667eea", "#764ba2"],
    )
    base["bg_colors_winner"] = _norm_colors(
        base.get("bg_colors_winner"),
        base.get("winner_bg_1"),
        base.get("winner_bg_2"),
        ["#f39c12", "#e74c3c"],
    )
    base["bg_color_1"] = base["bg_colors_active"][0]
    base["bg_color_2"] = base["bg_colors_active"][1] if len(base["bg_colors_active"]) > 1 else base["bg_colors_active"][0]
    base["winner_bg_1"] = base["bg_colors_winner"][0]
    base["winner_bg_2"] = base["bg_colors_winner"][1] if len(base["bg_colors_winner"]) > 1 else base["bg_colors_winner"][0]
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
            if not file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                continue
            if file in _BUILTIN_BG_IMAGES or file.startswith('default-'):
                continue
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