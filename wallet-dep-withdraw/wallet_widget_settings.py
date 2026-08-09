"""Wallet overlay appearance settings (per user / token)."""
from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(BASE_DIR)
SETTINGS_FILE = os.path.join(BASE_DIR, "wallet_widget_settings.json")
SETTING_KEY = "wallet_widget"

if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

try:
    from obs_platform import db as platform_db
except ImportError:
    platform_db = None

_lock = threading.RLock()
_file_cache: dict[str, Any] | None = None

DEFAULT_WALLET_WIDGET: dict[str, Any] = {
    "align_h": "center",
    "card_width": 268,
    "card_radius": 20,
    "card_padding_y": 10,
    "card_padding_x": 13,
    "bar_gap": 16,
    "stack_gap": 13,
    "icon_size": 56,
    "icon_radius": 14,
    "amt_font_size": 42,
    "likes_font_size": 40,
    "likes_card_radius": 18,
    "likes_label": "ЦЕЛЬ:",
    "dep_label": "ДЕП",
    "out_label": "ВЫВОД",
    "card_side_mode": "icon",
    "card_label_font_size": 32,
    "dep_label_font_size": 32,
    "out_label_font_size": 32,
    "dep_amt_font_size": 42,
    "out_amt_font_size": 42,
    "show_dep": True,
    "show_out": True,
    "show_likes": True,
    "show_icons": True,
    "glow_enabled": True,
    "money_bg_enabled": True,
    "money_bg_opacity": 100,
    "likes_bg_enabled": True,
    "likes_bg_opacity": 100,
    "dep_amt_color": "#eef9ff",
    "dep_label_color": "#7dd3fc",
    "out_empty_amt_color": "#f0a0a0",
    "out_filled_amt_color": "#4ade80",
    "out_label_color": "#f0a0a0",
    "out_filled_label_color": "#86efac",
    "likes_label_color": "#c9a86e",
    "likes_cur_color": "#fff8ee",
    "likes_goal_color": "#9a9288",
    "dep_border_color": "rgba(186, 230, 253, 0.42)",
    "dep_bg_1": "#2a4256",
    "dep_bg_2": "#1a2e42",
    "out_empty_border": "rgba(248, 113, 113, 0.42)",
    "out_empty_bg_1": "#4d2228",
    "out_empty_bg_2": "#32161b",
    "out_filled_border": "rgba(74, 222, 128, 0.32)",
    "out_filled_bg_1": "#1a3024",
    "out_filled_bg_2": "#102218",
    "likes_border_color": "rgba(212, 175, 95, 0.26)",
    "likes_bg_1": "#2a2620",
    "likes_bg_2": "#1a1713",
    "likes_fill_1": "#d4af5f",
    "likes_fill_2": "#f0d78c",
    "preview_dep": "50",
    "preview_out": "12.5",
    "preview_likes_cur": "120",
    "preview_likes_goal": "200",
}


def _clamp_int(val: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def normalize_wallet_widget(data: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {**DEFAULT_WALLET_WIDGET, **(data or {})}
    base["align_h"] = base["align_h"] if base.get("align_h") in ("left", "center", "right") else "center"
    base["card_width"] = _clamp_int(base.get("card_width"), 268, 160, 480)
    base["card_radius"] = _clamp_int(base.get("card_radius"), 20, 0, 40)
    base["card_padding_y"] = _clamp_int(base.get("card_padding_y"), 10, 4, 28)
    base["card_padding_x"] = _clamp_int(base.get("card_padding_x"), 13, 4, 36)
    base["bar_gap"] = _clamp_int(base.get("bar_gap"), 16, 0, 48)
    base["stack_gap"] = _clamp_int(base.get("stack_gap"), 13, 0, 48)
    base["icon_size"] = _clamp_int(base.get("icon_size"), 56, 32, 96)
    base["icon_radius"] = _clamp_int(base.get("icon_radius"), 14, 0, 40)
    base["amt_font_size"] = _clamp_int(base.get("amt_font_size"), 42, 16, 72)
    base["likes_font_size"] = _clamp_int(base.get("likes_font_size"), 40, 14, 64)
    base["likes_card_radius"] = _clamp_int(base.get("likes_card_radius"), 18, 0, 40)
    incoming = data if isinstance(data, dict) else {}
    legacy_lbl = _clamp_int(base.get("card_label_font_size"), 32, 10, 56)
    base["card_label_font_size"] = legacy_lbl
    if "dep_label_font_size" in incoming:
        base["dep_label_font_size"] = _clamp_int(incoming.get("dep_label_font_size"), legacy_lbl, 10, 56)
    else:
        base["dep_label_font_size"] = legacy_lbl
    if "out_label_font_size" in incoming:
        base["out_label_font_size"] = _clamp_int(incoming.get("out_label_font_size"), legacy_lbl, 10, 56)
    else:
        base["out_label_font_size"] = legacy_lbl
    legacy_amt = base["amt_font_size"]
    if "dep_amt_font_size" in incoming:
        base["dep_amt_font_size"] = _clamp_int(incoming.get("dep_amt_font_size"), legacy_amt, 16, 72)
    else:
        base["dep_amt_font_size"] = legacy_amt
    if "out_amt_font_size" in incoming:
        base["out_amt_font_size"] = _clamp_int(incoming.get("out_amt_font_size"), legacy_amt, 16, 72)
    else:
        base["out_amt_font_size"] = legacy_amt
    for key in (
        "show_dep",
        "show_out",
        "show_likes",
        "show_icons",
        "glow_enabled",
        "money_bg_enabled",
        "likes_bg_enabled",
    ):
        base[key] = bool(base.get(key))
    base["money_bg_opacity"] = _clamp_int(base.get("money_bg_opacity"), 100, 0, 100)
    base["likes_bg_opacity"] = _clamp_int(base.get("likes_bg_opacity"), 100, 0, 100)
    raw_mode = incoming.get("card_side_mode")
    if isinstance(raw_mode, str) and raw_mode.strip().lower() in ("icon", "text", "none"):
        mode = raw_mode.strip().lower()
    elif "show_icons" in incoming:
        mode = "icon" if bool(incoming.get("show_icons")) else "none"
    else:
        mode = "icon"
    base["card_side_mode"] = mode
    base["show_icons"] = mode == "icon"
    base["likes_label"] = str(base.get("likes_label") or "ЦЕЛЬ:")[:32]
    base["dep_label"] = str(base.get("dep_label") if base.get("dep_label") is not None else "ДЕП")[:24]
    base["out_label"] = str(base.get("out_label") if base.get("out_label") is not None else "ВЫВОД")[:24]
    for key in (
        "dep_amt_color",
        "dep_label_color",
        "out_empty_amt_color",
        "out_filled_amt_color",
        "out_label_color",
        "out_filled_label_color",
        "likes_label_color",
        "likes_cur_color",
        "likes_goal_color",
        "dep_border_color",
        "dep_bg_1",
        "dep_bg_2",
        "out_empty_border",
        "out_empty_bg_1",
        "out_empty_bg_2",
        "out_filled_border",
        "out_filled_bg_1",
        "out_filled_bg_2",
        "likes_border_color",
        "likes_bg_1",
        "likes_bg_2",
        "likes_fill_1",
        "likes_fill_2",
    ):
        base[key] = str(base.get(key) or DEFAULT_WALLET_WIDGET[key])
    for key in ("preview_dep", "preview_out", "preview_likes_cur", "preview_likes_goal"):
        base[key] = str(base.get(key) if base.get(key) is not None else DEFAULT_WALLET_WIDGET[key])
    return base


def _resolve_user_id(token: str | None = None) -> int:
    if not platform_db:
        return 0
    tok = (token or "").strip()
    if tok:
        user = platform_db.get_user_by_token(tok)
        if user:
            return int(user["id"])
    return 0


def load_wallet_widget(token: str | None = None, user_id: int | None = None) -> dict[str, Any]:
    uid = user_id if user_id is not None else _resolve_user_id(token)
    with _lock:
        if platform_db and uid:
            stored = platform_db.get_user_setting(uid, SETTING_KEY)
            if isinstance(stored, dict):
                return normalize_wallet_widget(stored)
            # Per-user account: no shared file fallback (isolation)
            return normalize_wallet_widget()

        global _file_cache
        if _file_cache is None:
            if os.path.isfile(SETTINGS_FILE):
                try:
                    with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                        raw = json.load(fh)
                    _file_cache = raw if isinstance(raw, dict) else {}
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    _file_cache = {}
            else:
                _file_cache = {}
        # file fallback is shared (legacy / no auth); keyed by token when present
        key = (token or "").strip() or "_default"
        stored = _file_cache.get(key) if isinstance(_file_cache.get(key), dict) else _file_cache.get("_default")
        if isinstance(stored, dict) and any(k in stored for k in DEFAULT_WALLET_WIDGET):
            return normalize_wallet_widget(stored)
        # old flat file without per-token nesting
        if isinstance(_file_cache, dict) and "card_width" in _file_cache:
            return normalize_wallet_widget(_file_cache)
        return normalize_wallet_widget()


def save_wallet_widget(
    data: dict[str, Any],
    token: str | None = None,
    user_id: int | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    uid = user_id if user_id is not None else _resolve_user_id(token)
    if reset:
        normalized = normalize_wallet_widget(DEFAULT_WALLET_WIDGET.copy())
    else:
        current = load_wallet_widget(token=token, user_id=uid or None)
        normalized = normalize_wallet_widget({**current, **(data or {})})

    with _lock:
        if platform_db and uid:
            platform_db.save_user_setting(uid, SETTING_KEY, normalized)
            return normalized

        global _file_cache
        if _file_cache is None:
            _file_cache = {}
        key = (token or "").strip() or "_default"
        # migrate flat → nested
        if "card_width" in _file_cache and key not in _file_cache:
            _file_cache = {"_default": {k: v for k, v in _file_cache.items() if k in DEFAULT_WALLET_WIDGET or k.startswith(("dep_", "out_", "likes_", "preview_", "show_", "glow", "align", "card", "bar", "stack", "icon", "amt"))}}
        if not isinstance(_file_cache, dict):
            _file_cache = {}
        _file_cache[key] = normalized
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_file_cache, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, SETTINGS_FILE)
        return normalized
