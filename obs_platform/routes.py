from __future__ import annotations

import os
import secrets

from flask import (
    Blueprint,
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import auth, db

platform_bp = Blueprint(
    "platform",
    __name__,
    template_folder="templates",
)


def init_platform(app: Flask, workspace_root: str) -> None:
    app.secret_key = _load_secret_key(workspace_root)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    db.init_db()
    app.register_blueprint(platform_bp)


def _load_secret_key(workspace_root: str) -> str:
    env_key = os.environ.get("OBS_WIDGETS_SECRET")
    if env_key:
        return env_key
    path = os.path.join(workspace_root, "data", "secret.key")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            key = fh.read().strip()
            if key:
                return key
    key = secrets.token_hex(32)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(key)
    return key


@platform_bp.before_app_request
def _attach_user():
    auth.load_session_user()


@platform_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        if auth.current_user():
            return redirect(request.args.get("next") or "/")
        return render_template("login.html", error=None)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    user = db.get_user_by_username(username)
    if not user or not db.verify_user_password(user, password):
        return render_template("login.html", error="Неверный логин или пароль"), 401

    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    nxt = request.form.get("next") or request.args.get("next") or "/"
    if not nxt.startswith("/"):
        nxt = "/"
    return redirect(nxt)


@platform_bp.route("/logout")
def logout_page():
    session.clear()
    return redirect(url_for("platform.login_page"))


@platform_bp.route("/admin/users")
@auth.admin_required
def admin_users_page():
    return render_template("admin_users.html")


@platform_bp.route("/api/auth/me")
def api_me():
    from flask import g

    user = auth.current_user()
    if not user:
        return jsonify({"ok": False, "authenticated": False}), 401
    safe = {
        "id": user["id"],
        "username": user["username"],
        "is_admin": user["is_admin"],
        "public_token": user["public_token"],
        "permissions": getattr(g, "permissions", db.get_user_permissions(user["id"])),
    }
    return jsonify({"ok": True, "authenticated": True, "user": safe})


@platform_bp.route("/api/admin/users", methods=["GET"])
@auth.admin_required
def api_list_users():
    return jsonify({"ok": True, "users": db.list_users()})


@platform_bp.route("/api/admin/users", methods=["POST"])
@auth.admin_required
def api_create_user():
    data = request.get_json(silent=True) or {}
    try:
        user = db.create_user(
            data.get("username", ""),
            data.get("password", ""),
            data.get("permissions"),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "user": user})


@platform_bp.route("/api/admin/users/<int:user_id>", methods=["PATCH"])
@auth.admin_required
def api_update_user(user_id: int):
    data = request.get_json(silent=True) or {}
    user = db.get_user_by_id(user_id)
    if not user:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if user.get("is_admin"):
        return jsonify({"ok": False, "error": "cannot_edit_admin"}), 400
    if "password" in data and data["password"]:
        db.update_user_password(user_id, data["password"])
    if "permissions" in data and isinstance(data["permissions"], dict):
        db.update_user_permissions(user_id, data["permissions"])
    updated = db.get_user_by_id(user_id)
    assert updated is not None
    updated["permissions"] = db.get_user_permissions(user_id)
    return jsonify({"ok": True, "user": updated})


@platform_bp.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
@auth.admin_required
def api_delete_user(user_id: int):
    user = db.get_user_by_id(user_id)
    if not user:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if user.get("is_admin"):
        return jsonify({"ok": False, "error": "cannot_delete_admin"}), 400
    db.delete_user(user_id)
    return jsonify({"ok": True})


@platform_bp.route("/api/calendar/records", methods=["GET"])
@auth.login_required
@auth.permission_required("access_dep_calendar")
def api_calendar_get():
    user = auth.current_user()
    assert user is not None
    records = db.get_dep_calendar_records(user["id"])
    return jsonify({"ok": True, "records": records})


@platform_bp.route("/api/calendar/records", methods=["PUT"])
@auth.login_required
@auth.permission_required("access_dep_calendar")
def api_calendar_put():
    user = auth.current_user()
    assert user is not None
    data = request.get_json(silent=True) or {}
    records = data.get("records")
    if not isinstance(records, dict):
        return jsonify({"ok": False, "error": "invalid_records"}), 400
    db.replace_dep_calendar_records(user["id"], records)
    return jsonify({"ok": True})


@platform_bp.route("/api/calendar/records/<day_key>", methods=["PUT"])
@auth.login_required
@auth.permission_required("access_dep_calendar")
def api_calendar_put_day(day_key: str):
    user = auth.current_user()
    assert user is not None
    record = request.get_json(silent=True) or {}
    if not isinstance(record, dict):
        return jsonify({"ok": False, "error": "invalid_record"}), 400
    db.upsert_dep_calendar_day(user["id"], day_key, record)
    return jsonify({"ok": True})


@platform_bp.route("/api/calendar/records/<day_key>", methods=["DELETE"])
@auth.login_required
@auth.permission_required("access_dep_calendar")
def api_calendar_delete_day(day_key: str):
    user = auth.current_user()
    assert user is not None
    db.delete_dep_calendar_day(user["id"], day_key)
    return jsonify({"ok": True})
