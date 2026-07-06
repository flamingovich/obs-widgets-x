import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const PUBLIC = path.join(ROOT, "public");
const SOUNDS = path.join(ROOT, "sounds");
const PORT = Number(process.env.PORT) || 8765;

function normalizeProviderId(raw) {
  const p = String(raw || "").toLowerCase();
  if (p === "pragmaticexternal") return "pragmatic";
  return p;
}

function loadSlots() {
  const raw = fs.readFileSync(path.join(ROOT, "names.txt"), "utf8");
  const obj = JSON.parse("{" + raw + "}");
  return Object.entries(obj).map(([file, name]) => {
    const base = file.replace(/\.[^.]+$/, "");
    const parts = base.split("-");
    const last = parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "unknown";
    const provider = normalizeProviderId(last);
    return { file, name, provider };
  });
}

const slots = loadSlots();
const queue = [];
const providers = Array.from(new Set(slots.map((s) => s.provider))).sort((a, b) => a.localeCompare(b));
let overlayVisible = false;
let selectedProvider = null;
/** Провайдеры, которых нет в прокруте при режиме «Все провайдеры». */
const excludedProviders = new Set();

function slotsForAllMode() {
  return slots.filter((s) => !excludedProviders.has(s.provider));
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".webp": "image/webp",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".ogg": "audio/ogg",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".json": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

function sendJson(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  });
  res.end(data);
}

function sendFile(res, filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const type = MIME[ext] || "application/octet-stream";
  fs.readFile(filePath, (err, buf) => {
    if (err) {
      res.writeHead(err.code === "ENOENT" ? 404 : 500);
      res.end(err.code === "ENOENT" ? "Not found" : "Error");
      return;
    }
    res.writeHead(200, {
      "Content-Type": type,
      "Access-Control-Allow-Origin": "*",
    });
    res.end(buf);
  });
}

const server = http.createServer((req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    });
    res.end();
    return;
  }

  const url = new URL(req.url || "/", `http://127.0.0.1`);

  if (req.method === "GET" && url.pathname === "/api/slots") {
    sendJson(res, 200, { slots });
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/providers") {
    sendJson(res, 200, { providers });
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/next-spin") {
    const next = queue.shift() ?? null;
    sendJson(res, 200, next);
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/state") {
    sendJson(res, 200, {
      visible: overlayVisible,
      provider: selectedProvider || "all",
      excludedProviders: Array.from(excludedProviders).sort((a, b) => a.localeCompare(b)),
    });
    return;
  }

  if (req.method === "POST" && url.pathname === "/api/spin") {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 10_000) req.destroy();
    });
    req.on("end", () => {
      let provider = null;
      if (body) {
        try {
          const parsed = JSON.parse(body);
          if (typeof parsed.provider === "string" && parsed.provider.trim()) {
            provider = normalizeProviderId(parsed.provider.trim().toLowerCase());
          }
        } catch {
          sendJson(res, 400, { error: "Невалидный JSON" });
          return;
        }
      }

      const available = provider
        ? slots.filter((s) => s.provider === provider)
        : slotsForAllMode();
      if (available.length === 0) {
        sendJson(res, 400, {
          error: provider
            ? "Нет слотов для выбранного провайдера"
            : "Нет слотов: все провайдеры исключены или список пуст",
        });
        return;
      }
      if (slots.length === 0) {
        sendJson(res, 400, { error: "Нет слотов" });
        return;
      }

      const winner = available[Math.floor(Math.random() * available.length)];
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      selectedProvider = provider || null;
      overlayVisible = true;
      queue.push({ id, winner, provider: provider || "all" });
      sendJson(res, 200, { ok: true, id, winner, provider: provider || "all" });
    });
    req.on("error", () => {
      sendJson(res, 500, { error: "Ошибка чтения запроса" });
    });
    return;
  }

  if (req.method === "POST" && url.pathname === "/api/state") {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 10_000) req.destroy();
    });
    req.on("end", () => {
      let parsed = {};
      if (body) {
        try {
          parsed = JSON.parse(body);
        } catch {
          sendJson(res, 400, { error: "Невалидный JSON" });
          return;
        }
      }
      if (typeof parsed.visible === "boolean") {
        overlayVisible = parsed.visible;
      }
      if (typeof parsed.provider === "string") {
        const p = normalizeProviderId(parsed.provider.trim().toLowerCase());
        selectedProvider = p && p !== "all" ? p : null;
      }
      if ("excludedProviders" in parsed && Array.isArray(parsed.excludedProviders)) {
        excludedProviders.clear();
        for (const raw of parsed.excludedProviders) {
          const id = normalizeProviderId(String(raw || "").trim().toLowerCase());
          if (id && providers.includes(id)) excludedProviders.add(id);
        }
      }
      sendJson(res, 200, {
        ok: true,
        visible: overlayVisible,
        provider: selectedProvider || "all",
        excludedProviders: Array.from(excludedProviders).sort((a, b) => a.localeCompare(b)),
      });
    });
    req.on("error", () => {
      sendJson(res, 500, { error: "Ошибка чтения запроса" });
    });
    return;
  }

  const pathname = url.pathname === "/" ? "/overlay.html" : url.pathname;
  if (pathname.includes("..")) {
    res.writeHead(400);
    res.end("Bad path");
    return;
  }

  const rel = pathname.replace(/^\//, "");

  if (rel.startsWith("images/")) {
    const img = path.join(ROOT, "images", path.basename(rel));
    const imagesRoot = path.join(ROOT, "images");
    if (img.startsWith(imagesRoot) && fs.existsSync(img) && fs.statSync(img).isFile()) {
      sendFile(res, img);
      return;
    }
  }

  if (rel.startsWith("sounds/")) {
    const snd = path.join(SOUNDS, path.basename(rel));
    if (snd.startsWith(SOUNDS) && fs.existsSync(snd) && fs.statSync(snd).isFile()) {
      sendFile(res, snd);
      return;
    }
  }

  if (rel === "Unbounded-SemiBold.ttf") {
    const fontFile = path.join(ROOT, "Unbounded-SemiBold.ttf");
    if (fs.existsSync(fontFile) && fs.statSync(fontFile).isFile()) {
      sendFile(res, fontFile);
      return;
    }
  }

  const pub = path.join(PUBLIC, rel);
  if (pub.startsWith(PUBLIC) && fs.existsSync(pub) && fs.statSync(pub).isFile()) {
    sendFile(res, pub);
    return;
  }

  res.writeHead(404);
  res.end("Not found");
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`Roulette: http://127.0.0.1:${PORT}/overlay.html (источник браузера)`);
  console.log(`Док-панель: http://127.0.0.1:${PORT}/dock.html`);
  console.log(`Слотов в каталоге: ${slots.length}`);
});
