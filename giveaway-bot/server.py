#!/usr/bin/env python3
"""
Локальный сервер: явный роутер (BaseHTTPRequestHandler), без SimpleHTTPRequestHandler.
Так /api/* никогда не превращается в «поиск файла» и HTML «File not found».

Порт по умолчанию 58971 (не 8787), чтобы не пересекаться с python -m http.server 8787.
Переопределение: set OBS_ROULETTE_PORT=8787
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = int(os.environ.get("OBS_ROULETTE_PORT", "58971"))

_spin_lock = threading.Lock()
_last_spin: dict | None = None
_reset_lock = threading.Lock()
_last_reset: dict | None = None
_card_lock = threading.Lock()
_last_card_command: dict | None = None
_state_lock = threading.Lock()
_shared_state: dict | None = None


def _default_state():
    return {
        "chances": {},
        "history": [],
        "caseWeights": {},
        "wheelPrizes": [],
        "caseTables": {},
        "widgetVisible": True,
    }


def _merge_history_preserve_order(incoming, existing, limit=100):
    seen = set()
    out = []
    for lst in (incoming, existing):
        if not isinstance(lst, list):
            continue
        for e in lst:
            if not isinstance(e, dict):
                continue
            k = (e.get("time"), e.get("sector"), e.get("item"))
            if k in seen:
                continue
            seen.add(k)
            out.append(e)
            if len(out) >= limit:
                return out
    return out[:limit]


def _history_prepend_dedup(history: list, entry: dict, limit: int = 100) -> list:
    key = (entry.get("time"), entry.get("sector"), entry.get("item"))
    out = [entry]
    for e in history:
        if not isinstance(e, dict):
            continue
        k = (e.get("time"), e.get("sector"), e.get("item"))
        if k == key:
            continue
        out.append(e)
    return out[:limit]


def _norm_request_path(handler: BaseHTTPRequestHandler) -> str:
    raw = unquote(urlparse(handler.path).path)
    if not raw.startswith("/"):
        raw = "/" + raw.replace("\\", "/")
    if len(raw) > 1 and raw.endswith("/"):
        return raw[:-1]
    return raw or "/"


class RouletteHTTPHandler(BaseHTTPRequestHandler):
    server_version = "OBSRoulette/2"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send_raw(self, code: int, body: bytes, content_type: str, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj: dict, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        h = {"Cache-Control": "no-store"}
        if extra_headers:
            h.update(extra_headers)
        self._send_raw(code, body, "application/json; charset=utf-8", h)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def _static_file(self, url_path: str) -> str | None:
        rel = url_path.lstrip("/").replace("\\", "/")
        if not rel or ".." in rel.split("/"):
            return None
        full = os.path.normpath(os.path.join(ROOT, rel))
        root_norm = os.path.normpath(ROOT)
        if not full.startswith(root_norm + os.sep) and full != root_norm:
            return None
        return full if os.path.isfile(full) else None

    def log_message(self, format, *args):
        if args and isinstance(args[0], str) and args[0].startswith('"GET /api/'):
            return
        super().log_message(format, *args)

    def do_OPTIONS(self):
        p = _norm_request_path(self)
        allowed = {
            "/api/spin",
            "/api/state",
            "/api/poll",
            "/api/version",
            "/api/card-command",
            "/api/history-append",
            "/api/history-one",
            "/api/reset-wheel",
        }
        if p not in allowed:
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        global _shared_state
        p = _norm_request_path(self)

        if p == "/":
            self.send_response(302)
            self.send_header("Location", "/panel.html")
            self._cors()
            self.end_headers()
            return

        if p == "/api/version":
            listen_port = self.server.server_address[1]
            self._send_json(
                200,
                {"ok": True, "server": "obs-hybrid-roulette", "port": listen_port},
                {"X-OBS-Roulette-Server": "1", "Content-Disposition": "inline"},
            )
            return

        if p == "/api/spin":
            with _spin_lock:
                cmd = dict(_last_spin) if _last_spin else None
            self._send_json(200, {"ok": True, "command": cmd})
            return

        if p == "/api/card-command":
            with _card_lock:
                cmd = dict(_last_card_command) if _last_card_command else None
            self._send_json(200, {"ok": True, "command": cmd})
            return

        if p == "/api/reset-wheel":
            with _reset_lock:
                cmd = dict(_last_reset) if _last_reset else None
            self._send_json(200, {"ok": True, "reset": cmd})
            return

        if p == "/api/state":
            with _state_lock:
                if _shared_state is None:
                    st = _default_state()
                else:
                    st = dict(_shared_state)
            if "widgetVisible" not in st or not isinstance(st.get("widgetVisible"), bool):
                st["widgetVisible"] = True
            self._send_json(200, {"ok": True, "state": st})
            return

        if p == "/api/poll":
            with _state_lock:
                if _shared_state is None:
                    st = _default_state()
                else:
                    st = dict(_shared_state)
            if "widgetVisible" not in st or not isinstance(st.get("widgetVisible"), bool):
                st["widgetVisible"] = True
            with _spin_lock:
                cmd = dict(_last_spin) if _last_spin else None
            with _reset_lock:
                rst = dict(_last_reset) if _last_reset else None
            self._send_json(200, {"ok": True, "state": st, "command": cmd, "reset": rst})
            return

        if p == "/api/history-one":
            qs = parse_qs(urlparse(self.path).query)
            pb = (qs.get("p") or [""])[0]
            entry = None
            if pb:
                try:
                    pad = (-len(pb)) % 4
                    b64 = pb.replace("-", "+").replace("_", "/") + ("=" * pad)
                    raw = base64.b64decode(b64.encode("ascii"))
                    entry = json.loads(raw.decode("utf-8"))
                except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                    entry = None
            if isinstance(entry, dict):
                with _state_lock:
                    if _shared_state is None:
                        _shared_state = _default_state()
                    hist = list(_shared_state.get("history") or [])
                    hist = _history_prepend_dedup(hist, entry)
                    prev = dict(_shared_state)
                    prev["history"] = hist
                    if "widgetVisible" not in prev:
                        prev["widgetVisible"] = True
                    _shared_state = prev
            gif_1x1 = (
                b"GIF89a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00"
                b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x01\x00,\x00\x00\x00\x00"
                b"\x01\x00\x01\x00\x00\x02\x02\x04\x01\x00;"
            )
            self._send_raw(200, gif_1x1, "image/gif", {"Cache-Control": "no-store"})
            return

        fpath = self._static_file(p)
        if fpath:
            with open(fpath, "rb") as fh:
                body = fh.read()
            ctype, _ = mimetypes.guess_type(fpath)
            if not ctype:
                ctype = "application/octet-stream"
            extra = {}
            if fpath.endswith((".html", ".htm", ".js", ".css")):
                extra["Cache-Control"] = "no-cache, no-store, must-revalidate"
            self._send_raw(200, body, ctype, extra)
            return

        self._send_json(404, {"ok": False, "error": "not_found", "path": p})

    def do_POST(self):
        global _shared_state, _last_spin, _last_reset, _last_card_command
        p = _norm_request_path(self)

        if p == "/api/reset-wheel":
            data = self._read_json_body()
            ts = int(data.get("ts") or time.time() * 1000)
            cmd = {"type": "resetWheel", "ts": ts}
            with _spin_lock:
                _last_spin = None
            with _reset_lock:
                _last_reset = cmd
            self._send_json(200, {"ok": True, "ts": ts})
            return

        if p == "/api/card-command":
            data = self._read_json_body()
            ts = int(data.get("ts") or time.time() * 1000)
            cmd = {
                "type": str(data.get("type") or ""),
                "ts": ts,
                "payload": data.get("payload") if isinstance(data.get("payload"), dict) else {},
            }
            with _card_lock:
                _last_card_command = cmd
            self._send_json(200, {"ok": True, "ts": ts})
            return

        if p == "/api/state":
            data = self._read_json_body()
            chances = data.get("chances")
            history = data.get("history")
            case_weights = data.get("caseWeights")
            wheel_prizes = data.get("wheelPrizes")
            case_tables = data.get("caseTables")
            widget_visible = data.get("widgetVisible")
            replace_history = data.get("replaceHistory") is True
            if not isinstance(history, list):
                history = []
            history = history[:100]
            if not isinstance(chances, dict):
                chances = {}
            if not isinstance(case_weights, dict):
                case_weights = {}
            with _state_lock:
                prev = dict(_shared_state) if _shared_state else {}
            if not isinstance(wheel_prizes, list):
                wheel_prizes = prev.get("wheelPrizes") if isinstance(prev.get("wheelPrizes"), list) else []
            if not isinstance(case_tables, dict):
                case_tables = prev.get("caseTables") if isinstance(prev.get("caseTables"), dict) else {}
            if not isinstance(widget_visible, bool):
                pv = prev.get("widgetVisible")
                widget_visible = pv if isinstance(pv, bool) else True
            prev_hist = list(prev.get("history") or []) if isinstance(prev.get("history"), list) else []
            if replace_history:
                merged_hist = history[:100]
            else:
                merged_hist = _merge_history_preserve_order(history, prev_hist, 100)
            with _state_lock:
                _shared_state = {
                    "chances": chances,
                    "history": merged_hist,
                    "caseWeights": case_weights,
                    "wheelPrizes": wheel_prizes,
                    "caseTables": case_tables,
                    "widgetVisible": widget_visible,
                }
            self._send_json(200, {"ok": True})
            return

        if p == "/api/history-append":
            data = self._read_json_body()
            entry = data.get("entry")
            with _state_lock:
                if _shared_state is None:
                    _shared_state = _default_state()
                hist = list(_shared_state.get("history") or [])
                if isinstance(entry, dict):
                    hist = _history_prepend_dedup(hist, entry)
                prev = dict(_shared_state)
                prev["history"] = hist
                if "widgetVisible" not in prev:
                    prev["widgetVisible"] = True
                _shared_state = prev
            self._send_json(200, {"ok": True})
            return

        if p != "/api/spin":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return

        data = self._read_json_body()
        ts = int(time.time() * 1000)
        cmd = {"type": "spin", "ts": ts, "payload": data.get("payload") or {}}
        if data.get("chances") is not None:
            cmd["chances"] = data["chances"]
        if data.get("caseWeights") is not None:
            cmd["caseWeights"] = data["caseWeights"]
        if data.get("wheelPrizes") is not None:
            cmd["wheelPrizes"] = data["wheelPrizes"]
        if data.get("caseTables") is not None:
            cmd["caseTables"] = data["caseTables"]
        with _spin_lock:
            _last_spin = cmd
        self._send_json(200, {"ok": True, "ts": ts})


def main():
    port = int(os.environ.get("OBS_ROULETTE_PORT", str(DEFAULT_PORT)))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), RouletteHTTPHandler)
    print("===============================================")
    print(" OBS Hybrid Roulette — server.py (explicit router)")
    print(f" Folder: {ROOT}")
    print(f" Port:   {port}  (override: set OBS_ROULETTE_PORT)")
    print(" Static: wheel pages + app in project root; images/fonts in ./assets/")
    print(" Open ONLY these URLs while this window is running:")
    print(f"   Panel: http://127.0.0.1:{port}/panel.html")
    print(f"   Wheel: http://127.0.0.1:{port}/wheel.html")
    print("   Cards: embedded into /wheel.html (same Browser Source)")
    print(f"   Check: http://127.0.0.1:{port}/api/version  -> JSON ok:true")
    print(" Stop: Ctrl+C")
    print("===============================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
