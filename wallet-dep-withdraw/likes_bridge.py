# Локальный бридж для OBS-виджета: лайки с эфира через yt-dlp.
# Запуск: pip install -r requirements.txt
#         python likes_bridge.py
# По умолчанию порт 8766. Виджет дергает GET /status?channel=...&goal=...

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from flask import Flask, Response, jsonify, redirect, request, send_from_directory
import yt_dlp

from wallet_widget_settings import load_wallet_widget, save_wallet_widget

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_TTL = 16.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

META_TTL = 300.0
_meta_cache: dict[str, tuple[float, dict[str, Any]]] = {}

FX_TTL = 300.0
_fx_cache: tuple[float, dict[str, Any]] | None = None


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.after_request
def _after(resp):
    return _cors(resp)


def normalize_watch_url(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    s = s.split("#")[0]
    if "watch?v=" in s or "youtu.be/" in s:
        return s.split("&")[0]
    s = s.rstrip("/")
    if s.endswith("/live"):
        return s
    return s + "/live"


def _pick_video(info: dict[str, Any] | None) -> dict[str, Any] | None:
    if not info:
        return None
    t = info.get("_type")
    if t == "playlist":
        for e in info.get("entries") or []:
            v = _pick_video(e)
            if v:
                return v
        return None
    if info.get("id"):
        return info
    return None


def fetch_likes(target_url: str) -> tuple[int | None, str | None, str | None, str | None]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
    except Exception as e:
        return None, None, None, str(e)

    vid = _pick_video(info)
    if not vid:
        return None, None, None, "Не удалось разобрать ответ YouTube"

    likes = vid.get("like_count")
    if likes is not None:
        try:
            likes = int(likes)
        except (TypeError, ValueError):
            likes = None

    title = vid.get("title") or ""
    vid_id = vid.get("id") or vid.get("display_id")
    return likes, title, vid_id, None


@app.route("/status")
def status():
    channel = (request.args.get("channel") or "").strip()
    goal_raw = request.args.get("goal") or "0"
    try:
        goal = int(float(goal_raw.replace(",", ".")))
    except (TypeError, ValueError):
        goal = 0

    if not channel:
        return jsonify(
            {
                "ok": False,
                "error": "Пустая ссылка",
                "likes": None,
                "goal": goal,
                "title": None,
                "video_id": None,
            }
        )

    url = normalize_watch_url(channel)
    now = time.monotonic()
    hit = _cache.get(url)
    if hit and now - hit[0] < CACHE_TTL:
        body = dict(hit[1])
        body["goal"] = goal
        return jsonify(body)

    likes, title, vid_id, err = fetch_likes(url)
    body: dict[str, Any] = {
        "ok": err is None and likes is not None,
        "error": err,
        "likes": likes,
        "goal": goal,
        "title": title,
        "video_id": vid_id,
    }
    if likes is None and err is None:
        body["ok"] = False
        body["error"] = (
            "YouTube не отдал число лайков (часто так на трансляциях). "
            "Попробуй прямую ссылку на эфир watch?v=..."
        )

    _cache[url] = (now, {k: v for k, v in body.items() if k != "goal"})
    return jsonify(body)


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.route("/")
def root():
    return redirect("/wallet", code=302)


@app.route("/wallet")
def wallet_overlay():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/wallet/dock")
def wallet_dock():
    # Сохраняем token и прочие query-параметры (иначе док и оверлей разъедутся)
    qs = request.query_string.decode("utf-8", errors="ignore")
    target = "/wallet?dock"
    if qs:
        parts = [p for p in qs.split("&") if p and not p.startswith("dock")]
        if parts:
            target += "&" + "&".join(parts)
    return redirect(target, code=302)


_STATE_DIR = os.path.join(BASE_DIR, "state")
_state_lock = __import__("threading").Lock()


def _state_key(token: str | None = None) -> str:
    t = (token if token is not None else (request.args.get("token") or "")).strip()
    if not t:
        t = "_default"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in t)[:80]
    return safe or "_default"


def _state_path(key: str) -> str:
    return os.path.join(_STATE_DIR, f"wallet_{key}.json")


def _default_wallet_state() -> dict[str, Any]:
    return {
        "dep": "",
        "out": "",
        "yt": "",
        "goal": "",
        "hideLikes": False,
        "dep_currency": "RUB",
        "out_currency": "RUB",
        "updated_at": 0,
    }


def _load_wallet_state(key: str) -> dict[str, Any]:
    path = _state_path(key)
    base = _default_wallet_state()
    if not os.path.isfile(path):
        return base
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return base
        out = {**base, **data}
        out["hideLikes"] = bool(out.get("hideLikes"))
        out["dep_currency"] = _normalize_currency(out.get("dep_currency"))
        out["out_currency"] = _normalize_currency(out.get("out_currency"))
        return out
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return base


def _normalize_currency(raw: Any, default: str = "RUB") -> str:
    s = str(raw or default).strip().upper()
    if s in ("USD", "$", "USDT", "ДОЛ", "ДОЛЛ"):
        return "USD"
    return "RUB"


def _save_wallet_state(key: str, data: dict[str, Any]) -> dict[str, Any]:
    os.makedirs(_STATE_DIR, exist_ok=True)
    current = _load_wallet_state(key)
    for field in ("dep", "out", "yt", "goal"):
        if field in data and data[field] is not None:
            current[field] = str(data[field])
    if "hideLikes" in data:
        current["hideLikes"] = bool(data["hideLikes"])
    if "dep_currency" in data:
        current["dep_currency"] = _normalize_currency(data.get("dep_currency"))
    if "out_currency" in data:
        current["out_currency"] = _normalize_currency(data.get("out_currency"))
    current["updated_at"] = int(time.time() * 1000)
    path = _state_path(key)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return current


@app.route("/wallet/state", methods=["GET", "POST"])
def wallet_state():
    key = _state_key()
    with _state_lock:
        if request.method == "GET":
            return jsonify({"ok": True, "state": _load_wallet_state(key)})
        incoming = request.get_json(silent=True)
        if not isinstance(incoming, dict):
            incoming = {}
        payload = incoming.get("state") if isinstance(incoming.get("state"), dict) else incoming
        saved = _save_wallet_state(key, payload)
        return jsonify({"ok": True, "state": saved})


def fetch_usd_rub_rate() -> dict[str, Any]:
    """USD/RUB from CBR (via cbr-xml-daily). Cached ~5 min."""
    global _fx_cache
    now = time.monotonic()
    if _fx_cache and now - _fx_cache[0] < FX_TTL:
        return dict(_fx_cache[1])

    out: dict[str, Any] = {"ok": False}
    sources = (
        "https://www.cbr-xml-daily.ru/daily_json.js",
        "https://www.cbr-xml-daily.ru/daily_json.xml",
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    # JSON (preferred)
    try:
        req = urllib.request.Request(sources[0], headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        usd = (data.get("Valute") or {}).get("USD") or {}
        val = float(usd.get("Value") or 0)
        nominal = float(usd.get("Nominal") or 1)
        if val > 0 and nominal > 0:
            rate = val / nominal
            out = {
                "ok": True,
                "usd_rub": round(rate, 4),
                "source": "cbr",
                "updated_at": int(time.time() * 1000),
            }
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError, TypeError, ValueError):
        pass

    if not out.get("ok") and _fx_cache:
        stale = dict(_fx_cache[1])
        stale["stale"] = True
        return stale

    if out.get("ok"):
        _fx_cache = (now, dict(out))
    return out


@app.route("/wallet/fx")
def wallet_fx():
    return jsonify(fetch_usd_rub_rate())


@app.route("/wallet/constructor")
def wallet_constructor():
    return send_from_directory(BASE_DIR, "constructor.html")


@app.route("/wallet/api/widget-settings", methods=["GET", "POST", "OPTIONS"])
def wallet_widget_settings_api():
    if request.method == "OPTIONS":
        return ("", 204)
    token = (request.args.get("token") or "").strip()
    if request.method == "GET":
        return jsonify({"ok": True, "settings": load_wallet_widget(token=token)})
    incoming = request.get_json(silent=True)
    if not isinstance(incoming, dict):
        incoming = {}
    reset = bool(incoming.get("reset"))
    payload = incoming.get("settings") if isinstance(incoming.get("settings"), dict) else incoming
    if not isinstance(payload, dict):
        payload = {}
    saved = save_wallet_widget(payload, token=token, reset=reset)
    return jsonify({"ok": True, "settings": saved})


@app.route("/wallet/<path:filename>")
def wallet_assets(filename: str):
    return send_from_directory(BASE_DIR, filename)


def _normalize_page_url(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    return s.split("#")[0]


def fetch_channel_meta(raw: str) -> dict[str, Any]:
    u = _normalize_page_url(raw)
    if not u:
        return {"ok": False, "error": "empty"}

    now = time.monotonic()
    hit = _meta_cache.get(u)
    if hit and now - hit[0] < META_TTL:
        return dict(hit[1])

    out: dict[str, Any] = {"ok": False}

    try:
        q = urllib.parse.urlencode({"url": u, "format": "json"})
        req = urllib.request.Request(
            "https://www.youtube.com/oembed?" + q,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        out = {
            "ok": True,
            "author_name": data.get("author_name") or "",
            "title": data.get("title") or "",
            "thumbnail_url": data.get("thumbnail_url") or "",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        try:
            opts: dict[str, Any] = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(u, download=False)
            v = _pick_video(info) or info
            if not isinstance(v, dict):
                v = {}
            thumbs = v.get("thumbnails") or []
            thumb = ""
            if thumbs:
                thumb = thumbs[-1].get("url") or ""
            if not thumb:
                thumb = v.get("thumbnail") or ""
            out = {
                "ok": True,
                "author_name": v.get("uploader")
                or v.get("channel")
                or v.get("uploader_id")
                or "",
                "title": v.get("title") or "",
                "thumbnail_url": thumb,
            }
        except Exception as e:
            out = {"ok": False, "error": str(e)}

    _meta_cache[u] = (now, dict(out))
    return out


@app.route("/channel_meta")
def channel_meta():
    ch = (request.args.get("channel") or "").strip()
    return jsonify(fetch_channel_meta(ch))


def _thumb_url_allowed(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        h = (p.hostname or "").lower()
        return h.endswith("ytimg.com") or h.endswith("ggpht.com") or h.endswith(
            "googleusercontent.com"
        )
    except Exception:
        return False


def _thumb_fetch_candidates(url: str) -> list[str]:
    """maxresdefault / vi_webp часто отдают 404 — пробуем те же кадры в более стабильных URL."""
    out: list[str] = [url]
    try:
        p = urllib.parse.urlparse(url)
        host = (p.hostname or "").lower()
        if "ytimg.com" not in host:
            return out
        segs = [s for s in p.path.split("/") if s]
        if len(segs) < 2 or segs[0] not in ("vi", "vi_webp"):
            return out
        vid = segs[1]
        if not vid:
            return out
        root = f"{p.scheme}://{p.netloc}/vi/{vid}"
        for fname in (
            "hqdefault.jpg",
            "mqdefault.jpg",
            "sddefault.jpg",
            "hqdefault.webp",
            "mqdefault.webp",
            "maxresdefault.jpg",
        ):
            out.append(f"{root}/{fname}")
    except Exception:
        pass
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


_THUMB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.youtube.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def _fetch_thumb_bytes(candidate: str) -> tuple[bytes, str]:
    req = urllib.request.Request(candidate, headers=_THUMB_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        ct = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
        data = resp.read()
    if "image" not in ct:
        ct = "image/jpeg"
    return data, ct


@app.route("/thumb")
def proxy_thumb():
    """Прокси аватарки/превью: OBS часто не грузит i.ytimg.com с file:// дока."""
    u = (request.args.get("u") or "").strip()
    if not u or not _thumb_url_allowed(u):
        return "", 400
    for candidate in _thumb_fetch_candidates(u):
        if not _thumb_url_allowed(candidate):
            continue
        try:
            got = _fetch_thumb_bytes(candidate)
            if not got:
                continue
            data, ct = got
            return Response(
                data,
                mimetype=ct,
                headers={"Cache-Control": "public, max-age=600"},
            )
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
            continue
    return "", 502


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8766)
    args = p.parse_args()
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
