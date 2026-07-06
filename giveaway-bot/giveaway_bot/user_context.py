from __future__ import annotations

import copy
import threading

from flask import g, has_app_context, request, session

try:
    from obs_platform import db as platform_db
except ImportError:
    platform_db = None

GIVEAWAY_TEMPLATE = {
    "video_id": "",
    "keyword": "",
    "accept_any_message": False,
    "participants": [],
    "participants_data": {},
    "winner": None,
    "pending_winner": None,
    "winner_avatar": None,
    "winner_messages": [],
    "winner_picked_at": None,
    "winner_first_message_at": None,
    "is_active": False,
    "is_connected": False,
    "countdown": 0,
    "is_test_mode": False,
    "test_participant_seq": 0,
}

_giveaways: dict[int, dict] = {}
_chat_threads: dict[int, threading.Thread | None] = {}
_stop_flags: dict[int, threading.Event] = {}
_ctx_lock = threading.Lock()


def resolve_user() -> dict | None:
    if not has_app_context():
        return None

    if hasattr(g, "platform_user"):
        return g.platform_user

    token = None
    if request.view_args:
        token = request.view_args.get("token")
    if not token:
        token = request.args.get("token")

    user = None
    if platform_db and token:
        user = platform_db.get_user_by_token(str(token))
    elif platform_db and session.get("user_id"):
        user = platform_db.get_user_by_id(int(session["user_id"]))

    g.platform_user = user
    g.platform_user_id = user["id"] if user else 0
    return user


def get_user_id() -> int:
    if not has_app_context():
        return 0
    resolve_user()
    return getattr(g, "platform_user_id", 0) or 0


def get_giveaway() -> dict:
    uid = get_user_id()
    with _ctx_lock:
        if uid not in _giveaways:
            _giveaways[uid] = copy.deepcopy(GIVEAWAY_TEMPLATE)
        return _giveaways[uid]


def get_chat_thread() -> threading.Thread | None:
    uid = get_user_id()
    return _chat_threads.get(uid)


def set_chat_thread(thread: threading.Thread | None) -> None:
    uid = get_user_id()
    _chat_threads[uid] = thread


def get_giveaway_for_user(user_id: int) -> dict:
    with _ctx_lock:
        if user_id not in _giveaways:
            _giveaways[user_id] = copy.deepcopy(GIVEAWAY_TEMPLATE)
        return _giveaways[user_id]


def get_stop_flag() -> threading.Event:
    uid = get_user_id()
    return get_stop_flag_for_user(uid)


def get_stop_flag_for_user(user_id: int) -> threading.Event:
    with _ctx_lock:
        if user_id not in _stop_flags:
            _stop_flags[user_id] = threading.Event()
        return _stop_flags[user_id]


_chat_instances: dict[int, object] = {}


def get_chat_instance():
    return _chat_instances.get(get_user_id())


def set_chat_instance(instance) -> None:
    uid = get_user_id()
    if instance is None:
        _chat_instances.pop(uid, None)
    else:
        _chat_instances[uid] = instance
