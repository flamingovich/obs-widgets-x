from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, jsonify, redirect, request, session, url_for

from . import db


def load_session_user() -> dict | None:
    user_id = session.get("user_id")
    if not user_id:
        g.user = None
        g.permissions = {}
        return None
    user = db.get_user_by_id(int(user_id))
    if not user:
        session.clear()
        g.user = None
        g.permissions = {}
        return None
    g.user = user
    g.permissions = db.get_user_permissions(user["id"])
    return user


def current_user() -> dict | None:
    if hasattr(g, "user"):
        return g.user
    return load_session_user()


def login_required(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "auth_required"}), 401
            nxt = request.full_path if request.query_string else request.path
            return redirect(url_for("platform.login_page", next=nxt))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "auth_required"}), 401
            return redirect(url_for("platform.login_page"))
        if not user.get("is_admin"):
            return jsonify({"ok": False, "error": "admin_required"}), 403
        return view(*args, **kwargs)

    return wrapped


def user_has_permission(user: dict | None, key: str) -> bool:
    if not user:
        return False
    if user.get("is_admin"):
        return True
    perms = getattr(g, "permissions", None) or db.get_user_permissions(user["id"])
    return bool(perms.get(key))


def permission_required(key: str):
    def decorator(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "auth_required"}), 401
                return redirect(url_for("platform.login_page"))
            if not user_has_permission(user, key):
                return jsonify({"ok": False, "error": "forbidden"}), 403
            return view(*args, **kwargs)

        return wrapped

    return decorator
