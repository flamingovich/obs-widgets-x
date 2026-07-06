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

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_TTL = 16.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

META_TTL = 300.0
_meta_cache: dict[str, tuple[float, dict[str, Any]]] = {}


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
    return redirect("/wallet?dock", code=302)


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
