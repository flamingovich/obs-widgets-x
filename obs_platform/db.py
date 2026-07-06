from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(WORKSPACE_ROOT, "data")
DB_PATH = os.environ.get("OBS_WIDGETS_DB", os.path.join(DATA_DIR, "obs_widgets.db"))
SEED_CALENDAR_PATH = os.path.join(DATA_DIR, "admin_dep_calendar_seed.json")

_db_lock = threading.Lock()
_connection: sqlite3.Connection | None = None

PERMISSION_KEYS = (
    "access_giveaway",
    "access_roulette",
    "access_wallet",
    "access_wheel",
    "access_dep_calendar",
)

DEFAULT_PERMISSIONS = {key: 1 for key in PERMISSION_KEYS}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA foreign_keys = ON")
    return _connection


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            public_token TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_permissions (
            user_id INTEGER PRIMARY KEY,
            access_giveaway INTEGER NOT NULL DEFAULT 0,
            access_roulette INTEGER NOT NULL DEFAULT 0,
            access_wallet INTEGER NOT NULL DEFAULT 0,
            access_wheel INTEGER NOT NULL DEFAULT 0,
            access_dep_calendar INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER NOT NULL,
            setting_key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, setting_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS dep_calendar_days (
            user_id INTEGER NOT NULL,
            day_key TEXT NOT NULL,
            deposit REAL NOT NULL DEFAULT 0,
            withdraw REAL NOT NULL DEFAULT 0,
            fix REAL NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            no_stream INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, day_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()


def init_db(admin_username: str = "admin", admin_password: str = "pizdauzka") -> None:
    with _db_lock:
        conn = _connect()
        _migrate(conn)
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (admin_username,)
        ).fetchone()
        if row:
            _maybe_seed_admin_calendar(conn, int(row["id"]))
            return

        token = secrets.token_urlsafe(16)
        conn.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, public_token, created_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            (
                admin_username,
                generate_password_hash(admin_password),
                token,
                _utc_now(),
            ),
        )
        admin_id = conn.execute(
            "SELECT id FROM users WHERE username = ?", (admin_username,)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO user_permissions (
                user_id, access_giveaway, access_roulette, access_wallet,
                access_wheel, access_dep_calendar
            ) VALUES (?, 1, 1, 1, 1, 1)
            """,
            (admin_id,),
        )
        conn.commit()
        _import_widget_settings_file(conn, admin_id)
        _maybe_seed_admin_calendar(conn, admin_id)


def _import_widget_settings_file(conn: sqlite3.Connection, user_id: int) -> None:
    path = os.path.join(
        WORKSPACE_ROOT, "giveaway-bot", "giveaway_bot", "widget_settings.json"
    )
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            save_user_setting(user_id, "giveaway_widget", data, conn=conn)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass


def _maybe_seed_admin_calendar(conn: sqlite3.Connection, admin_id: int) -> None:
    existing = conn.execute(
        "SELECT COUNT(*) AS c FROM dep_calendar_days WHERE user_id = ?",
        (admin_id,),
    ).fetchone()["c"]
    if existing:
        return
    if not os.path.isfile(SEED_CALENDAR_PATH):
        return
    try:
        with open(SEED_CALENDAR_PATH, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        records = payload.get("records") if isinstance(payload, dict) else payload
        if not isinstance(records, dict):
            return
        replace_dep_calendar_records(admin_id, records, conn=conn)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass


def _row_to_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    user = dict(row)
    user["is_admin"] = bool(user.get("is_admin"))
    return user


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with _db_lock:
        row = _connect().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return _row_to_user(row)


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with _db_lock:
        row = _connect().execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        return _row_to_user(row)


def get_user_by_token(public_token: str) -> dict[str, Any] | None:
    if not public_token:
        return None
    with _db_lock:
        row = _connect().execute(
            "SELECT * FROM users WHERE public_token = ?", (public_token.strip(),)
        ).fetchone()
        return _row_to_user(row)


def verify_user_password(user: dict[str, Any], password: str) -> bool:
    return check_password_hash(user["password_hash"], password or "")


def get_user_permissions(user_id: int) -> dict[str, bool]:
    with _db_lock:
        row = _connect().execute(
            "SELECT * FROM user_permissions WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return {key: False for key in PERMISSION_KEYS}
    return {key: bool(row[key]) for key in PERMISSION_KEYS}


def list_users() -> list[dict[str, Any]]:
    with _db_lock:
        rows = _connect().execute(
            "SELECT id, username, is_admin, public_token, created_at FROM users ORDER BY id"
        ).fetchall()
    users = []
    for row in rows:
        user = dict(row)
        user["is_admin"] = bool(user["is_admin"])
        user["permissions"] = get_user_permissions(user["id"])
        users.append(user)
    return users


def create_user(
    username: str,
    password: str,
    permissions: dict[str, bool] | None = None,
) -> dict[str, Any]:
    username = username.strip()
    if not username:
        raise ValueError("username_required")
    if not password:
        raise ValueError("password_required")
    perms = {**DEFAULT_PERMISSIONS, **(permissions or {})}
    for key in PERMISSION_KEYS:
        perms[key] = bool(perms.get(key))
    token = secrets.token_urlsafe(16)
    with _db_lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, is_admin, public_token, created_at)
                VALUES (?, ?, 0, ?, ?)
                """,
                (username, generate_password_hash(password), token, _utc_now()),
            )
            user_id = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()["id"]
            conn.execute(
                f"""
                INSERT INTO user_permissions (
                    user_id, {", ".join(PERMISSION_KEYS)}
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, *[1 if perms[k] else 0 for k in PERMISSION_KEYS]),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("username_taken") from exc
    user = get_user_by_id(user_id)
    assert user is not None
    user["permissions"] = get_user_permissions(user_id)
    return user


def update_user_permissions(user_id: int, permissions: dict[str, bool]) -> None:
    values = {key: 1 if bool(permissions.get(key)) else 0 for key in PERMISSION_KEYS}
    with _db_lock:
        conn = _connect()
        conn.execute(
            f"""
            UPDATE user_permissions SET
                {", ".join(f"{k} = ?" for k in PERMISSION_KEYS)}
            WHERE user_id = ?
            """,
            (*[values[k] for k in PERMISSION_KEYS], user_id),
        )
        conn.commit()


def update_user_password(user_id: int, password: str) -> None:
    if not password:
        raise ValueError("password_required")
    with _db_lock:
        conn = _connect()
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user_id),
        )
        conn.commit()


def delete_user(user_id: int) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute("DELETE FROM users WHERE id = ? AND is_admin = 0", (user_id,))
        conn.commit()


def get_user_setting(user_id: int, setting_key: str) -> dict[str, Any] | None:
    with _db_lock:
        row = _connect().execute(
            "SELECT value_json FROM user_settings WHERE user_id = ? AND setting_key = ?",
            (user_id, setting_key),
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["value_json"])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def save_user_setting(
    user_id: int,
    setting_key: str,
    value: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    now = _utc_now()
    if conn is None:
        with _db_lock:
            c = _connect()
            c.execute(
                """
                INSERT INTO user_settings (user_id, setting_key, value_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, setting_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, setting_key, payload, now),
            )
            c.commit()
    else:
        conn.execute(
            """
            INSERT INTO user_settings (user_id, setting_key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, setting_key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (user_id, setting_key, payload, now),
        )


def get_dep_calendar_records(user_id: int) -> dict[str, dict[str, Any]]:
    with _db_lock:
        rows = _connect().execute(
            """
            SELECT day_key, deposit, withdraw, fix, notes, no_stream
            FROM dep_calendar_days WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out[row["day_key"]] = {
            "deposit": float(row["deposit"] or 0),
            "withdraw": float(row["withdraw"] or 0),
            "fix": float(row["fix"] or 0),
            "notes": row["notes"] or "",
            "noStream": bool(row["no_stream"]),
        }
    return out


def replace_dep_calendar_records(
    user_id: int,
    records: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> None:
    now = _utc_now()

    def _write(c: sqlite3.Connection) -> None:
        c.execute("DELETE FROM dep_calendar_days WHERE user_id = ?", (user_id,))
        for day_key, raw in records.items():
            if not isinstance(raw, dict):
                continue
            if not isinstance(day_key, str) or len(day_key) != 10:
                continue
            c.execute(
                """
                INSERT INTO dep_calendar_days (
                    user_id, day_key, deposit, withdraw, fix, notes, no_stream, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    day_key,
                    float(raw.get("deposit") or 0),
                    float(raw.get("withdraw") or 0),
                    float(raw.get("fix") or 0),
                    str(raw.get("notes") or ""),
                    1 if raw.get("noStream") else 0,
                    now,
                ),
            )

    if conn is None:
        with _db_lock:
            c = _connect()
            _write(c)
            c.commit()
    else:
        _write(conn)


def upsert_dep_calendar_day(user_id: int, day_key: str, record: dict[str, Any]) -> None:
    now = _utc_now()
    with _db_lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO dep_calendar_days (
                user_id, day_key, deposit, withdraw, fix, notes, no_stream, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, day_key) DO UPDATE SET
                deposit = excluded.deposit,
                withdraw = excluded.withdraw,
                fix = excluded.fix,
                notes = excluded.notes,
                no_stream = excluded.no_stream,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                day_key,
                float(record.get("deposit") or 0),
                float(record.get("withdraw") or 0),
                float(record.get("fix") or 0),
                str(record.get("notes") or ""),
                1 if record.get("noStream") else 0,
                now,
            ),
        )
        conn.commit()


def delete_dep_calendar_day(user_id: int, day_key: str) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute(
            "DELETE FROM dep_calendar_days WHERE user_id = ? AND day_key = ?",
            (user_id, day_key),
        )
        conn.commit()
