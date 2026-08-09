#!/usr/bin/env python3
"""
Единый локальный сервер: рулетка + розыгрыши на одном порту (по умолчанию 58971).

Giveaway Bot (Flask) слушает только localhost:51999; снаружи доступен через /giveaway/*.
Портал со ссылками: http://127.0.0.1:58971/
"""
from __future__ import annotations

import http.client
import importlib.util
import logging
import mimetypes
import os
import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(ROOT)
GIVEAWAY_BOT_DIR = os.path.join(ROOT, "giveaway_bot")
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)
if GIVEAWAY_BOT_DIR not in sys.path:
    sys.path.insert(0, GIVEAWAY_BOT_DIR)

INTERNAL_GIVEAWAY_PORT = int(os.environ.get("GIVEAWAY_INTERNAL_PORT", "51999"))
DEFAULT_PORT = int(os.environ.get("OBS_ROULETTE_PORT", "58971"))
SLOTS_UPSTREAM = (
    os.environ.get("OBS_SLOTS_HOST", "127.0.0.1"),
    int(os.environ.get("OBS_SLOTS_PORT", "8765")),
)
WALLET_UPSTREAM = (
    os.environ.get("OBS_WALLET_HOST", "127.0.0.1"),
    int(os.environ.get("OBS_WALLET_PORT", "8766")),
)
GIVEAWAY_PREFIX = "/giveaway"
CALENDAR_PREFIX = "/calendar"
SLOTS_PREFIX = "/slots"
WALLET_PREFIX = "/wallet"
CALENDAR_DIST = os.path.join(WORKSPACE, "dep-calendar", "dist")

PLATFORM_PREFIXES = (
    "/login",
    "/logout",
    "/admin",
    "/api/auth",
    "/api/admin",
    "/api/calendar",
)


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


roulette_mod = _load_module("roulette_server", os.path.join(ROOT, "server.py"))
giveaway_mod = _load_module("giveaway_server", os.path.join(ROOT, "giveaway_bot", "server.py"))

RouletteHTTPHandler = roulette_mod.RouletteHTTPHandler
_norm_request_path = roulette_mod._norm_request_path
giveaway_app = giveaway_mod.app


def _run_giveaway():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    os.chdir(os.path.join(ROOT, "giveaway_bot"))
    for folder in ("fonts", "images"):
        folder_path = os.path.join(ROOT, "giveaway_bot", folder)
        os.makedirs(folder_path, exist_ok=True)
    from obs_platform import init_platform

    init_platform(giveaway_app, WORKSPACE)
    giveaway_app.run(
        host="127.0.0.1",
        port=INTERNAL_GIVEAWAY_PORT,
        threaded=True,
        use_reloader=False,
    )


def _wait_giveaway_ready(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", INTERNAL_GIVEAWAY_PORT, timeout=1)
            conn.request("GET", "/api/status")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            if resp.status < 500:
                return True
        except OSError:
            pass
        time.sleep(0.15)
    return False


def _read_body(handler, method: str) -> bytes | None:
    if method not in ("POST", "PUT", "PATCH"):
        return None
    length = int(handler.headers.get("Content-Length", "0") or "0")
    return handler.rfile.read(length) if length > 0 else b""


_GIVEAWAY_BOOT_JS = """<script>(function(){
  var m = location.pathname.match(/\\/t\\/([^/]+)/);
  var token = (m && m[1]) || new URLSearchParams(location.search).get('token') || '';
  window.__OBS_TOKEN__ = token;
  var orig = window.fetch.bind(window);
  window.fetch = function(input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    if (typeof url === 'string' && url) {
      try {
        var abs = url.indexOf('://') !== -1 || url.indexOf('//') === 0;
        var u = new URL(url, location.origin);
        var changed = false;
        if (!abs && url.charAt(0) === '/' && u.pathname.indexOf('/api/') === 0 &&
            location.pathname.indexOf('/giveaway') !== -1) {
          u.pathname = '/giveaway' + u.pathname;
          changed = true;
        }
        if (token && (u.pathname.indexOf('/api/') === 0 || u.pathname.indexOf('/giveaway/api/') === 0) &&
            !u.searchParams.has('token')) {
          u.searchParams.set('token', token);
          changed = true;
        }
        if (changed) {
          url = abs ? u.href : (u.pathname + u.search + u.hash);
          input = typeof input === 'string' ? url : new Request(url, input);
        }
      } catch (e) {}
    }
    return orig(input, init);
  };
})();</script>"""


def _inject_giveaway_base(html: str) -> str:
    base_tag = f'<base href="{GIVEAWAY_PREFIX}/">'
    inject = base_tag + _GIVEAWAY_BOOT_JS
    if "<base " in html.lower():
        inject = _GIVEAWAY_BOOT_JS
    lowered = html.lower()
    head_idx = lowered.find("<head>")
    if head_idx >= 0:
        insert_at = head_idx + len("<head>")
        return html[:insert_at] + inject + html[insert_at:]
    return inject + html


class UnifiedHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            return False
        except OSError:
            return True


def _is_platform_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in PLATFORM_PREFIXES)


class UnifiedHTTPHandler(RouletteHTTPHandler):
    def _check_authenticated(self) -> bool:
      cookie = self.headers.get("Cookie", "")
      try:
          conn = http.client.HTTPConnection(
              "127.0.0.1", INTERNAL_GIVEAWAY_PORT, timeout=5
          )
          conn.request("GET", "/api/auth/me", headers={"Cookie": cookie})
          resp = conn.getresponse()
          resp.read()
          conn.close()
          return resp.status == 200
      except OSError:
          return False

    def _proxy_internal(self, method: str, upstream_path: str):
      parsed = urlparse(self.path)
      path = upstream_path
      if parsed.query:
          path += "?" + parsed.query

      headers = {}
      for key, value in self.headers.items():
          lk = key.lower()
          if lk in ("host", "connection", "content-length"):
              continue
          headers[key] = value

      body = _read_body(self, method)
      try:
          conn = http.client.HTTPConnection(
              "127.0.0.1", INTERNAL_GIVEAWAY_PORT, timeout=60
          )
          conn.request(method, path, body=body, headers=headers)
          resp = conn.getresponse()
          data = resp.read()
          status = resp.status
          resp_headers = resp.getheaders()
          conn.close()
      except OSError as exc:
          self._send_json(
              502,
              {"ok": False, "error": "backend_unavailable", "detail": str(exc)},
          )
          return

      ctype = ""
      for h, v in resp_headers:
          if h.lower() == "content-type":
              ctype = v
              break

      if "text/html" in ctype.lower():
          try:
              text = data.decode("utf-8")
              if path.startswith("/calendar") or path == "/calendar":
                  if "window.__DEP_CAL_API__" not in text:
                      text = text.replace(
                          "<head>",
                          "<head><script>window.__DEP_CAL_API__=true;</script>",
                          1,
                      )
              data = text.encode("utf-8")
          except UnicodeDecodeError:
              pass

      self.send_response(status)
      for h, v in resp_headers:
          if h.lower() in ("transfer-encoding", "content-length", "connection"):
              continue
          self.send_header(h, v)
      self._cors()
      self.send_header("Content-Length", str(len(data)))
      self.end_headers()
      self.wfile.write(data)

    def _serve_calendar(self):
      path = _norm_request_path(self)
      rel = path[len(CALENDAR_PREFIX) :] or "/"
      if rel in ("", "/"):
          rel = "/index.html"
      rel = rel.lstrip("/")
      file_path = os.path.join(CALENDAR_DIST, rel)
      if not os.path.isfile(file_path):
          file_path = os.path.join(CALENDAR_DIST, "index.html")
          if not os.path.isfile(file_path):
              self._send_json(404, {"ok": False, "error": "calendar_not_built"})
              return
      with open(file_path, "rb") as fh:
          body = fh.read()
      ctype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
      if file_path.endswith(".html"):
          try:
              text = body.decode("utf-8")
              if "window.__DEP_CAL_API__" not in text:
                  text = text.replace(
                      "<head>",
                      "<head><script>window.__DEP_CAL_API__=true;</script>",
                      1,
                  )
              body = text.encode("utf-8")
          except UnicodeDecodeError:
              pass
          ctype = "text/html; charset=utf-8"
      self._send_raw(200, body, ctype, {"Cache-Control": "no-cache, no-store, must-revalidate"})

    def _serve_hub(self):
      if not self._check_authenticated():
          self.send_response(302)
          self.send_header("Location", "/login?next=/")
          self.end_headers()
          return
      hub_path = os.path.join(ROOT, "hub.html")
      if not os.path.isfile(hub_path):
          self._send_json(404, {"ok": False, "error": "hub_not_found"})
          return
      with open(hub_path, "rb") as fh:
          body = fh.read()
      self._send_raw(
          200,
          body,
          "text/html; charset=utf-8",
          {"Cache-Control": "no-cache, no-store, must-revalidate"},
      )

    def _proxy_giveaway(self, method: str):
      parsed = urlparse(self.path)
      path = _norm_request_path(self)
      upstream_path = path[len(GIVEAWAY_PREFIX) :] or "/"
      if not upstream_path.startswith("/"):
          upstream_path = "/" + upstream_path
      if parsed.query:
          upstream_path += "?" + parsed.query

      headers = {}
      for key, value in self.headers.items():
          lk = key.lower()
          if lk in ("host", "connection", "content-length"):
              continue
          headers[key] = value

      body = _read_body(self, method)
      try:
          conn = http.client.HTTPConnection(
              "127.0.0.1", INTERNAL_GIVEAWAY_PORT, timeout=60
          )
          conn.request(method, upstream_path, body=body, headers=headers)
          resp = conn.getresponse()
          data = resp.read()
          status = resp.status
          resp_headers = resp.getheaders()
          conn.close()
      except OSError as exc:
          self._send_json(
              502,
              {
                  "ok": False,
                  "error": "giveaway_unavailable",
                  "detail": str(exc),
              },
          )
          return

      ctype = ""
      for h, v in resp_headers:
          if h.lower() == "content-type":
              ctype = v
              break

      if "text/html" in ctype.lower():
          try:
              text = data.decode("utf-8")
              data = _inject_giveaway_base(text).encode("utf-8")
          except UnicodeDecodeError:
              pass

      self.send_response(status)
      for h, v in resp_headers:
          if h.lower() in ("transfer-encoding", "content-length", "connection"):
              continue
          self.send_header(h, v)
      self._cors()
      self.send_header("Content-Length", str(len(data)))
      if "text/html" in ctype.lower():
          self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
      self.end_headers()
      self.wfile.write(data)

    def _proxy_service(self, method: str, prefix: str, upstream: tuple[str, int]):
      parsed = urlparse(self.path)
      path = _norm_request_path(self)
      upstream_path = path[len(prefix) :] or "/"
      if not upstream_path.startswith("/"):
          upstream_path = "/" + upstream_path
      if prefix == WALLET_PREFIX:
          if upstream_path in ("/", ""):
              upstream_path = "/wallet"
          elif not (upstream_path == "/wallet" or upstream_path.startswith("/wallet/")):
              # Strip left /wallet → /dock, /constructor, /wallet_appearance.js, etc.
              # Must use "/wallet/" (with slash), else "/wallet_appearance.js" falsely matches.
              if upstream_path.startswith("/dock"):
                  upstream_path = "/wallet" + upstream_path
              elif upstream_path not in ("/status", "/health", "/channel_meta", "/thumb"):
                  upstream_path = "/wallet" + upstream_path
      if parsed.query:
          upstream_path += "?" + parsed.query

      headers = {}
      for key, value in self.headers.items():
          lk = key.lower()
          if lk in ("host", "connection", "content-length"):
              continue
          headers[key] = value

      body = _read_body(self, method)
      host, port = upstream
      try:
          conn = http.client.HTTPConnection(host, port, timeout=60)
          conn.request(method, upstream_path, body=body, headers=headers)
          resp = conn.getresponse()
          data = resp.read()
          status = resp.status
          resp_headers = resp.getheaders()
          conn.close()
      except OSError as exc:
          self._send_json(
              502,
              {"ok": False, "error": "upstream_unavailable", "detail": str(exc)},
          )
          return

      ctype = ""
      for h, v in resp_headers:
          if h.lower() == "content-type":
              ctype = v
              break

      if prefix == SLOTS_PREFIX and "text/html" in ctype.lower():
          try:
              text = data.decode("utf-8")
              boot = (
                  "<script>(function(){"
                  "var token=new URLSearchParams(location.search).get('token')||'';"
                  "var o=window.fetch.bind(window);"
                  "window.fetch=function(input,init){"
                  "var url=typeof input==='string'?input:(input&&input.url)||'';"
                  "if(typeof url==='string'&&url.charAt(0)==='/'&&"
                  "(url.indexOf('/api/')===0||url.indexOf('/images/')===0||url.indexOf('/sounds/')===0)){"
                  "url='/slots'+url;"
                  "if(token){var u=new URL(url,location.origin);if(!u.searchParams.has('token'))"
                  "u.searchParams.set('token',token);url=u.pathname+u.search+u.hash;}"
                  "input=typeof input==='string'?url:new Request(url,input);"
                  "}"
                  "return o(input,init);};"
                  "})();</script>"
              )
              lowered = text.lower()
              idx = lowered.find("<head>")
              if idx >= 0:
                  at = idx + len("<head>")
                  text = text[:at] + boot + text[at:]
              else:
                  text = boot + text
              data = text.encode("utf-8")
          except UnicodeDecodeError:
              pass

      self.send_response(status)
      for h, v in resp_headers:
          if h.lower() in ("transfer-encoding", "content-length", "connection"):
              continue
          self.send_header(h, v)
      self._cors()
      self.send_header("Content-Length", str(len(data)))
      self.end_headers()
      self.wfile.write(data)

    def do_OPTIONS(self):
      path = _norm_request_path(self)
      if (
          path.startswith(GIVEAWAY_PREFIX)
          or path.startswith(SLOTS_PREFIX)
          or path.startswith(WALLET_PREFIX)
          or _is_platform_path(path)
      ):
          self.send_response(204)
          self._cors()
          self.end_headers()
          return
      return super().do_OPTIONS()

    def do_GET(self):
      path = _norm_request_path(self)
      if path in ("/", "/hub.html"):
          return self._serve_hub()
      if path == CALENDAR_PREFIX or path.startswith(CALENDAR_PREFIX + "/"):
          return self._serve_calendar()
      if _is_platform_path(path):
          return self._proxy_internal("GET", path)
      if path.startswith(GIVEAWAY_PREFIX):
          return self._proxy_giveaway("GET")
      if path == SLOTS_PREFIX or path.startswith(SLOTS_PREFIX + "/"):
          return self._proxy_service("GET", SLOTS_PREFIX, SLOTS_UPSTREAM)
      if path == WALLET_PREFIX or path.startswith(WALLET_PREFIX + "/"):
          return self._proxy_service("GET", WALLET_PREFIX, WALLET_UPSTREAM)
      if path in ("/status", "/health", "/channel_meta", "/thumb"):
          return self._proxy_service("GET", "", WALLET_UPSTREAM)
      return super().do_GET()

    def do_POST(self):
      path = _norm_request_path(self)
      if _is_platform_path(path):
          return self._proxy_internal("POST", path)
      if path.startswith(GIVEAWAY_PREFIX):
          return self._proxy_giveaway("POST")
      if path == SLOTS_PREFIX or path.startswith(SLOTS_PREFIX + "/"):
          return self._proxy_service("POST", SLOTS_PREFIX, SLOTS_UPSTREAM)
      if path == WALLET_PREFIX or path.startswith(WALLET_PREFIX + "/"):
          return self._proxy_service("POST", WALLET_PREFIX, WALLET_UPSTREAM)
      return super().do_POST()

    def do_PUT(self):
      path = _norm_request_path(self)
      if _is_platform_path(path):
          return self._proxy_internal("PUT", path)
      if path.startswith(GIVEAWAY_PREFIX):
          return self._proxy_giveaway("PUT")
      self.send_error(405)

    def do_DELETE(self):
      path = _norm_request_path(self)
      if _is_platform_path(path):
          return self._proxy_internal("DELETE", path)
      self.send_error(405)


def main():
    t = threading.Thread(target=_run_giveaway, daemon=True)
    t.start()
    print("Starting Giveaway Bot (internal)...", flush=True)
    if not _wait_giveaway_ready():
        print(
            f"WARNING: Giveaway Bot did not respond on 127.0.0.1:{INTERNAL_GIVEAWAY_PORT}",
            flush=True,
        )

    port = DEFAULT_PORT
    httpd = None
    last_err = None
    for attempt in range(20):
        try:
            httpd = UnifiedHTTPServer(("0.0.0.0", port), UnifiedHTTPHandler)
            break
        except OSError as exc:
            last_err = exc
            print(f"Port {port} busy ({exc}), retry {attempt + 1}/20...", flush=True)
            time.sleep(0.5)
    if httpd is None:
        print(f" ERROR: cannot bind port {port}: {last_err}")
        raise SystemExit(1)
    base = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print(" OBS Widgets — unified local server")
    print(f" Folder: {ROOT}")
    print(f" Port:   {port}")
    print()
    print(" PORTAL (copy links for OBS):")
    print(f"   {base}/")
    print()
    print(" ROULETTE:")
    print(f"   Widget:  {base}/wheel.html")
    print(f"   Dock:    {base}/panel.html")
    print()
    print(" GIVEAWAY:")
    print(f"   Widget:      {base}/giveaway/widget")
    print(f"   Dock:        {base}/giveaway/obs-dock")
    print(f"   Admin:       {base}/giveaway/")
    print(f"   Constructor: {base}/giveaway/constructor")
    print()
    print(" AUTH / ADMIN:")
    print(f"   Login:       {base}/login")
    print(f"   Users admin: {base}/admin/users")
    print()
    print(" DEP CALENDAR:")
    print(f"   Calendar:    {base}/calendar/")
    print()
    print(" Keep this window open while streaming. Stop: Ctrl+C")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
