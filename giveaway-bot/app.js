/*
  Гибридная система "Колесо + Кейс" для OBS.
  Этап 1: колесо (4 сектора)
  Этап 2: кейс-лента (для БОНУСКА и БАЛАНС), либо фикс-результат для КУПОН.
*/

const STORAGE_KEYS = {
  state: "obs_hybrid_state_v1",
  command: "obs_hybrid_command_v1",
  result: "obs_hybrid_last_result_v1",
  reset: "obs_hybrid_reset_v1"
};

const CHANNEL_NAME = "obs_hybrid_channel_v1";
const CARD_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"];
const CARD_SUITS = [
  { key: "hearts", symbol: "♥", color: "red" },
  { key: "diamonds", symbol: "♦", color: "red" },
  { key: "spades", symbol: "♠", color: "black" },
  { key: "clubs", symbol: "♣", color: "black" }
];

/** Порт по умолчанию у server.py (не 8787 — его часто занимает python -m http.server). */
const HYBRID_API_DEFAULT_PORT = "58971";
const HYBRID_API_DEFAULT_ORIGIN = `http://127.0.0.1:${HYBRID_API_DEFAULT_PORT}`;

/** Логи: `?debug=1` в URL или localStorage.setItem('obs_hybrid_debug','1') и обновить страницу. */
const HYBRID_DEBUG = (() => {
  try {
    const q = new URLSearchParams(window.location.search).get("debug");
    if (q === "1" || q === "true") return true;
    if (typeof localStorage !== "undefined" && localStorage.getItem("obs_hybrid_debug") === "1") return true;
  } catch (_e) {}
  return false;
})();

const HYBRID_LOG_MAX = 500;

function hybridDebugLog(scope, message, data) {
  if (!HYBRID_DEBUG) return;
  const ts = new Date().toISOString();
  let extra = "";
  if (data !== undefined) {
    try {
      const s = typeof data === "object" ? JSON.stringify(data) : String(data);
      extra = s.length > 1800 ? `${s.slice(0, 1800)}…` : s;
    } catch (_e) {
      extra = "[data]";
    }
  }
  const line = extra ? `[${ts}] [${scope}] ${message} | ${extra}` : `[${ts}] [${scope}] ${message}`;
  if (!Array.isArray(window.__OBS_HYBRID_LOGS)) window.__OBS_HYBRID_LOGS = [];
  window.__OBS_HYBRID_LOGS.push(line);
  if (window.__OBS_HYBRID_LOGS.length > HYBRID_LOG_MAX) {
    window.__OBS_HYBRID_LOGS.splice(0, window.__OBS_HYBRID_LOGS.length - HYBRID_LOG_MAX);
  }
  console.log("[hybrid]", scope, message, data !== undefined ? data : "");
}

function hybridDebugStateSnap(label, st) {
  if (!st || typeof st !== "object") return { label, empty: true };
  const h = st.history;
  const n = Array.isArray(h) ? h.length : 0;
  return {
    label,
    historyLen: n,
    widgetVisible: st.widgetVisible,
    head: n ? { sector: h[0].sector, item: h[0].item, time: h[0].time } : null
  };
}

window.hybridExportDebugLog = function hybridExportDebugLog() {
  const arr = window.__OBS_HYBRID_LOGS;
  if (!Array.isArray(arr) || !arr.length) return "(пусто — включите ?debug=1)";
  return arr.join("\n");
};

let _hybridDbgThrottleKey = "";
let _hybridDbgThrottleAt = 0;
function hybridDebugThrottled(scope, throttleKey, message, data, ms = 8000) {
  if (!HYBRID_DEBUG) return;
  const now = Date.now();
  const k = `${scope}:${throttleKey}`;
  if (k === _hybridDbgThrottleKey && now - _hybridDbgThrottleAt < ms) return;
  _hybridDbgThrottleKey = k;
  _hybridDbgThrottleAt = now;
  hybridDebugLog(scope, message, data);
}

/** Не дублировать POST на сервер при записи состояния, пришедшего с /api/state (панель ↔ OBS). */
let _stateSyncSuppress = false;
/** Редкий лог успешного poll (иначе сотни строк в секунду). */
let _hybridLastPollLogAt = 0;
let _hybridApi404HintLogged = false;
const RARITY_KEYS = ["blue", "purple", "pink", "red", "gold"];
const LEGACY_RARITY_MAP = { common: "blue", rare: "purple", epic: "pink", legend: "gold" };

const ASSETS_ICONS = "./assets/icons";
const ASSETS_TEXTURES = "./assets/textures";
const DEFAULT_WHEEL_ICON = `${ASSETS_ICONS}/bonus.png`;
const DEFAULT_TEXTURE_FALLBACK = `${ASSETS_TEXTURES}/texture_bonus.png`;

/** Старые сохранённые пути (корень проекта) → новая раскладка assets/. */
function migrateLegacyAssetUrl(url) {
  const s = String(url || "").trim();
  const map = {
    "./bonus.png": `${ASSETS_ICONS}/bonus.png`,
    "./coupon.png": `${ASSETS_ICONS}/coupon.png`,
    "./balance.png": `${ASSETS_ICONS}/balance.png`,
    "./respin.png": `${ASSETS_ICONS}/respin.png`,
    "./texture_bonus.png": `${ASSETS_TEXTURES}/texture_bonus.png`,
    "./texture_coupon.png": `${ASSETS_TEXTURES}/texture_coupon.png`,
    "./texture_balance.png": `${ASSETS_TEXTURES}/texture_balance.png`,
    "./texture_respin.png": `${ASSETS_TEXTURES}/texture_respin.png`
  };
  return map[s] || s;
}

const DEFAULT_WHEEL_PRIZES = [
  { id: "bonus", name: "БОНУСКА", chance: 34, icon: `${ASSETS_ICONS}/bonus.png`, petals: 2 },
  { id: "coupon", name: "КУПОН", chance: 33, icon: `${ASSETS_ICONS}/coupon.png`, petals: 2 },
  { id: "balance", name: "БАЛАНС", chance: 33, icon: `${ASSETS_ICONS}/balance.png`, petals: 2 }
];

/** Сколько равных сегментов на диске занимает приз (визуально). Шанс выпадения по-прежнему из поля «шанс». */
const WHEEL_PETALS_DEFAULT = 2;
const WHEEL_PETALS_MAX = 48;
const DEFAULT_CASE_TABLES = {
  БОНУСКА: [
    { value: "1600", chance: 40, rarity: "blue" },
    { value: "3200", chance: 30, rarity: "purple" },
    { value: "4800", chance: 20, rarity: "pink" },
    { value: "6400", chance: 10, rarity: "gold" }
  ],
  КУПОН: [{ value: "1000 фикс", chance: 100, rarity: "purple" }],
  БАЛАНС: [
    { value: "10$", chance: 35, rarity: "blue" },
    { value: "15$", chance: 30, rarity: "purple" },
    { value: "20$", chance: 20, rarity: "purple" },
    { value: "25$", chance: 10, rarity: "pink" },
    { value: "50$", chance: 5, rarity: "gold" }
  ]
};
const PRESETS_STORAGE_KEY = "obs_hybrid_presets_v1";

function activeSectorNamesFromPrizes(prizes) {
  return (Array.isArray(prizes) ? prizes : [])
    .map((p) => (p && String(p.name || "").trim()) || "")
    .filter(Boolean);
}

function normalizePetals(row) {
  const raw = row && row.petals != null ? row.petals : WHEEL_PETALS_DEFAULT;
  let n = Math.floor(Number(raw));
  if (!Number.isFinite(n) || n < 1) n = 1;
  if (n > WHEEL_PETALS_MAX) n = WHEEL_PETALS_MAX;
  return n;
}

/**
 * Раскладка лепестков по кругу: у приза с чётным числом лепестков пары стоят напротив друг друга;
 * с нечётным — равномерный шаг по свободным ячейкам (без кучности). При нечётном суммарном N — обход круга с шагом, взаимно простым с N.
 */
function buildVisualWedgesFromPrizes(prizes) {
  const src = Array.isArray(prizes) && prizes.length ? prizes : DEFAULT_WHEEL_PRIZES;
  const items = [];
  src.forEach((p) => {
    const name = String(p && p.name ? p.name : "").trim();
    if (!name) return;
    items.push({ name, petals: normalizePetals(p) });
  });
  if (!items.length) return buildVisualWedgesFromPrizes(DEFAULT_WHEEL_PRIZES);

  const N = items.reduce((s, it) => s + it.petals, 0);
  if (N <= 1) return [items[0].name];

  const slots = Array(N).fill(null);

  function gcd(a, b) {
    let x = Math.abs(a);
    let y = Math.abs(b);
    while (y) {
      const t = y;
      y = x % y;
      x = t;
    }
    return x || 1;
  }

  /** Порядок индексов 0..N-1: обход круга с шагом, взаимно простым с N (равномерно). */
  function coprimeWalkIndices(n) {
    if (n <= 1) return [0];
    let step = Math.max(2, Math.floor(n / 3));
    while (gcd(step, n) !== 1) step += 1;
    const out = [];
    let x = 0;
    const seen = new Set();
    for (let k = 0; k < n; k += 1) {
      if (!seen.has(x)) {
        out.push(x);
        seen.add(x);
      }
      x = (x + step) % n;
    }
    while (out.length < n) {
      for (let i = 0; i < n && out.length < n; i += 1) {
        if (!seen.has(i)) {
          out.push(i);
          seen.add(i);
        }
      }
    }
    return out;
  }

  function interleaveMultiset(taskItems) {
    const queues = taskItems.map((it) => ({ name: it.name, q: Array(it.petals).fill(it.name) }));
    const out = [];
    let left = taskItems.reduce((s, it) => s + it.petals, 0);
    while (left > 0) {
      for (const row of queues) {
        if (row.q.length) {
          out.push(row.q.shift());
          left -= 1;
        }
      }
    }
    return out;
  }

  function listEmptyIndices(s) {
    const e = [];
    for (let i = 0; i < s.length; i += 1) if (s[i] == null) e.push(i);
    return e;
  }

  /** Разнести `count` одинаковых имён по текущим пустым ячейкам максимально равномерно. */
  function spreadSinglesInEmpties(name, count, s) {
    let pool = listEmptyIndices(s);
    if (pool.length < count) return;
    pool.sort((a, b) => a - b);
    for (let j = 0; j < count; j += 1) {
      const M = pool.length;
      const t = Math.min(M - 1, Math.round(((j + 0.5) * M) / count - 0.5));
      const idx = pool[t];
      s[idx] = name;
      pool.splice(t, 1);
    }
  }

  if (N % 2 === 1) {
    const seq = interleaveMultiset(items);
    const walk = coprimeWalkIndices(N);
    for (let k = 0; k < N; k += 1) slots[walk[k]] = seq[k];
    return slots;
  }

  const half = N / 2;
  const pairUsed = new Array(half).fill(false);

  for (let t = 0; t < items.length; t += 1) {
    const it = items[t];
    if (it.petals % 2 !== 0) continue;
    const needPairs = it.petals / 2;
    const free = [];
    for (let h = 0; h < half; h += 1) {
      if (pairUsed[h]) continue;
      if (slots[h] != null || slots[h + half] != null) continue;
      free.push(h);
    }
    let pool = free.slice();
    const take = Math.min(needPairs, pool.length);
    for (let j = 0; j < take; j += 1) {
      const M = pool.length;
      const ti = Math.min(M - 1, Math.round(((j + 0.5) * M) / take - 0.5));
      const h = pool[ti];
      pool.splice(ti, 1);
      slots[h] = it.name;
      slots[h + half] = it.name;
      pairUsed[h] = true;
    }
  }

  for (let t = 0; t < items.length; t += 1) {
    const it = items[t];
    if (it.petals % 2 === 0) continue;
    spreadSinglesInEmpties(it.name, it.petals, slots);
  }

  for (let t = 0; t < items.length; t += 1) {
    const it = items[t];
    if (it.petals % 2 !== 0) continue;
    let placed = 0;
    for (let i = 0; i < N; i += 1) if (slots[i] === it.name) placed += 1;
    if (placed >= it.petals) continue;
    const need = it.petals - placed;
    spreadSinglesInEmpties(it.name, need, slots);
  }

  for (let i = 0; i < N; i += 1) {
    if (slots[i] == null) slots[i] = items[0].name;
  }

  return slots;
}

/** Пауза после остановки колеса перед стартом анимации кейса (мс). */
const CASE_START_DELAY_MS = 1600;

/** Длительность анимаций (мс) — совпадают с CSS transition на роторе/ленте. */
const WHEEL_SPIN_MS = 8600;
const CASE_SCROLL_MS = 9600;
const CASE_SPLIT_REVEAL_MS = 520;
const WHEEL_WEDGE_VISUAL_JITTER = 0.28;
const CASE_CELL_VISUAL_JITTER_PX = 22;

/** Появление/скрытие диска до/после розыгрыша (мс). */
const WHEEL_FADE_MS = 550;
/** После финального итога — пауза до плавного скрытия колеса (мс). */
const WHEEL_HIDE_AFTER_RESULT_MS = 6000;
const WHEEL_TICK_SOUND_URL = "./assets/sounds/schelk.mp3";
const CASE_TICK_SOUND_URL = "./assets/sounds/schelk_case.mp3";
const TICK_POOL_SIZE = 8;
const WHEEL_TICK_VOLUME = 0.40;
const CASE_TICK_VOLUME = 0.40;
const WHEEL_TICK_MIN_INTERVAL_MS = 80;
const CASE_TICK_MIN_INTERVAL_MS = 65;

function normalizeRarity(r) {
  const k = String(r || "").toLowerCase();
  if (RARITY_KEYS.includes(k)) return k;
  if (LEGACY_RARITY_MAP[k]) return LEGACY_RARITY_MAP[k];
  return "blue";
}

function defaultCaseTableByPrizeName(name) {
  const base = DEFAULT_CASE_TABLES[name] || [{ value: "1000", chance: 100, rarity: "blue" }];
  return base.map((x) => ({ ...x, rarity: normalizeRarity(x.rarity) }));
}

function normalizeWheelPrizes(input, legacyChances) {
  const src = Array.isArray(input) && input.length ? input : DEFAULT_WHEEL_PRIZES;
  const out = [];
  src.forEach((row, i) => {
    const name = String(row && row.name ? row.name : "").trim();
    if (!name) return;
    const chanceRaw =
      row && row.chance != null
        ? row.chance
        : legacyChances && Object.prototype.hasOwnProperty.call(legacyChances, name)
          ? legacyChances[name]
          : null;
    const chance = Number(chanceRaw);
    out.push({
      id: String(row && row.id ? row.id : `${name}-${i + 1}`),
      name,
      chance: Number.isFinite(chance) && chance > 0 ? chance : 0,
      icon: migrateLegacyAssetUrl(row && row.icon ? String(row.icon) : DEFAULT_WHEEL_ICON),
      petals: normalizePetals(row)
    });
  });
  if (!out.length) return DEFAULT_WHEEL_PRIZES.map((x) => ({ ...x, petals: normalizePetals(x) }));
  if (out.every((x) => x.chance <= 0)) {
    const eq = Math.round((100 / out.length) * 10) / 10;
    out.forEach((x) => {
      x.chance = eq;
    });
  }
  return out;
}

function normalizeCaseTables(input, wheelPrizes) {
  const names = activeSectorNamesFromPrizes(wheelPrizes);
  const src = input && typeof input === "object" ? input : {};
  const out = {};
  names.forEach((name) => {
    const base = defaultCaseTableByPrizeName(name);
    const arr = Array.isArray(src[name]) ? src[name] : base;
    const rows = [];
    arr.forEach((row, i) => {
      const value = String(row && row.value != null ? row.value : "").trim();
      if (!value) return;
      const chance = Number(row && row.chance != null ? row.chance : base[i] ? base[i].chance : 0);
      rows.push({
        value,
        chance: Number.isFinite(chance) && chance > 0 ? chance : 0,
        rarity: normalizeRarity(row && row.rarity)
      });
    });
    out[name] = rows.length ? rows : base;
  });
  return out;
}

const memoryStorage = {};

function safeStorageGet(key) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? memoryStorage[key] || null : value;
  } catch (_error) {
    return memoryStorage[key] || null;
  }
}

function safeStorageSet(key, value) {
  memoryStorage[key] = value;
  try {
    localStorage.setItem(key, value);
  } catch (_error) {
    // Среда может запрещать localStorage, поэтому оставляем резерв в памяти.
  }
}

function safeJsonParse(raw) {
  try {
    return JSON.parse(raw);
  } catch (_error) {
    return null;
  }
}

function randomCardRank(excludeRank) {
  const pool = CARD_RANKS.filter((r) => r !== excludeRank);
  return pool[randomInt(0, pool.length - 1)];
}

function randomCardSuit() {
  return CARD_SUITS[randomInt(0, CARD_SUITS.length - 1)];
}

function cardSuitByKey(key) {
  return CARD_SUITS.find((s) => s.key === key) || CARD_SUITS[0];
}

function renderCardFaceInto(node, rank, suitKey) {
  if (!node) return;
  const r = String(rank || "A");
  const suit = cardSuitByKey(suitKey || "diamonds");
  const isBlack = suit.color === "black";
  node.className = "play-card face-up";
  if (isBlack) node.classList.add("is-black");
  node.innerHTML = `
    <div class="corner top">${r}<br>${suit.symbol}</div>
    <div class="center">${suit.symbol}</div>
    <div class="corner bottom">${r}<br>${suit.symbol}</div>
  `;
}

function createMessageChannel() {
  if (!("BroadcastChannel" in window)) return null;
  try {
    return new BroadcastChannel(CHANNEL_NAME);
  } catch (_error) {
    return null;
  }
}

function formatDateTime(timestamp) {
  return new Date(timestamp).toLocaleString();
}

/** Первая группа цифр в строке (для сопоставления призов). */
function prizeDigitsKey(valueStr) {
  const m = String(valueStr).replace(/\s/g, "").match(/(\d+)/);
  return m ? m[1] : "";
}

/** Разделитель тысяч для ₽ (1,600). */
function formatThousandsComma(n) {
  const num = Math.round(Number(n));
  if (!Number.isFinite(num)) return String(n);
  return String(num).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** БОНУСКА и КУПОН — ₽; БАЛАНС — $ (префикс). */
function prizeDisplayModeForSector(sector) {
  if (sector === "БАЛАНС") return "usd";
  return "rub";
}

/** Бонус/купон: 1,600 ₽; баланс: $20; купон фикс: 1,000 ₽ фикс */
function formatPrizeDisplay(valueStr, mode = "rub") {
  const s = String(valueStr).trim();
  if (!s || s === "-") return s || "-";

  if (mode === "usd") {
    if (/фикс/i.test(s)) {
      const head = s.replace(/\s*фикс.*$/i, "").trim();
      const d = prizeDigitsKey(head);
      return d ? `$${formatThousandsComma(d)} фикс` : s;
    }
    const d = prizeDigitsKey(s);
    return d ? `$${formatThousandsComma(d)}` : s;
  }

  const suffix = " ₽";
  if (/фикс/i.test(s)) {
    const head = s.replace(/\s*фикс.*$/i, "").trim();
    const d = prizeDigitsKey(head);
    return d ? `${formatThousandsComma(d)}${suffix} фикс` : s;
  }
  if (/\$/.test(s) || /^\d[\d\s]*$/.test(s.replace(/\$/g, ""))) {
    const d = prizeDigitsKey(s);
    return d ? `${formatThousandsComma(d)}${suffix}` : s;
  }
  const d = prizeDigitsKey(s);
  if (d && /^\d+$/.test(s.replace(/\s/g, ""))) return `${formatThousandsComma(d)}${suffix}`;
  return s;
}

function tableItemMatchesForced(internalValue, forcedRaw) {
  if (forcedRaw == null || String(forcedRaw).trim() === "") return false;
  const a = prizeDigitsKey(internalValue);
  const b = prizeDigitsKey(forcedRaw);
  if (a && b && a === b) return true;
  return String(internalValue).trim().toLowerCase() === String(forcedRaw).trim().toLowerCase();
}

/** Объединение историй без потери записей (гонка: колесо уже записало локально, сервер ещё старый). */
function mergeHistoryUnionPreferLocal(localHist, remoteHist, limit = 100) {
  const seen = new Set();
  const out = [];
  for (const lst of [localHist, remoteHist]) {
    if (!Array.isArray(lst)) continue;
    for (const e of lst) {
      if (!e || typeof e !== "object") continue;
      const k = `${e.time}|${String(e.sector)}|${String(e.item)}`;
      if (seen.has(k)) continue;
      seen.add(k);
      out.push(e);
      if (out.length >= limit) return out;
    }
  }
  return out;
}

/** Не затирать локальную историю пустым ответом; при равной длине и разном содержимом — объединить. */
function mergeHistoryRemotePreferred(remoteHist, localHist) {
  const r = Array.isArray(remoteHist) ? remoteHist : [];
  const l = Array.isArray(localHist) ? localHist : [];
  if (r.length > l.length) return r.slice();
  if (l.length > r.length) return l.slice();
  if (r.length === 0) return l.slice();
  if (JSON.stringify(r) === JSON.stringify(l)) return l.slice();
  return mergeHistoryUnionPreferLocal(l, r, 100);
}

function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function normalizeChances(chances, sectors) {
  const keys = Array.isArray(sectors) && sectors.length ? sectors : activeSectorNamesFromPrizes(DEFAULT_WHEEL_PRIZES);
  const result = {};
  keys.forEach((sector) => {
    const num = Number(chances && Object.prototype.hasOwnProperty.call(chances, sector) ? chances[sector] : undefined);
    result[sector] = Number.isFinite(num) && num > 0 ? num : 0;
  });
  if (Object.values(result).every((v) => v <= 0)) {
    const eq = Math.round((100 / keys.length) * 10) / 10;
    keys.forEach((k) => {
      result[k] = eq;
    });
  }
  return result;
}

function buildChancesFromWheelPrizes(prizes) {
  const o = {};
  (Array.isArray(prizes) ? prizes : []).forEach((p) => {
    o[p.name] = Number(p.chance) || 0;
  });
  return normalizeChances(o, activeSectorNamesFromPrizes(prizes));
}

function normalizeStateModel(raw) {
  const parsed = raw && typeof raw === "object" ? raw : {};
  const wheelPrizes = normalizeWheelPrizes(parsed.wheelPrizes, parsed.chances);
  const legacyCaseTables = {};
  if (parsed.caseWeights && typeof parsed.caseWeights === "object") {
    ["БОНУСКА", "БАЛАНС"].forEach((name) => {
      const base = defaultCaseTableByPrizeName(name);
      const weights = parsed.caseWeights[name];
      if (Array.isArray(weights) && weights.length === base.length) {
        legacyCaseTables[name] = base.map((row, i) => ({ ...row, chance: Number(weights[i]) || row.chance }));
      }
    });
  }
  const caseTables = normalizeCaseTables(parsed.caseTables || legacyCaseTables, wheelPrizes);
  return {
    wheelPrizes,
    caseTables,
    chances: buildChancesFromWheelPrizes(wheelPrizes),
    history: Array.isArray(parsed.history) ? parsed.history.slice(0, 100) : [],
    widgetVisible: typeof parsed.widgetVisible === "boolean" ? parsed.widgetVisible : true
  };
}

let SECTORS = activeSectorNamesFromPrizes(DEFAULT_WHEEL_PRIZES);
let VISUAL_WEDGES = buildVisualWedgesFromPrizes(DEFAULT_WHEEL_PRIZES);
let CASE_TABLES = normalizeCaseTables(DEFAULT_CASE_TABLES, DEFAULT_WHEEL_PRIZES);
let CASE_SECTORS_WEIGHTED = [...SECTORS];

function refreshRuntimeMapsFromState(st) {
  SECTORS = activeSectorNamesFromPrizes(st.wheelPrizes);
  VISUAL_WEDGES = buildVisualWedgesFromPrizes(st.wheelPrizes);
  CASE_TABLES = normalizeCaseTables(st.caseTables, st.wheelPrizes);
  CASE_SECTORS_WEIGHTED = [...SECTORS];
}

function normalizeCaseWeights(input) {
  const out = {};
  const src = input && typeof input === "object" ? input : {};
  CASE_SECTORS_WEIGHTED.forEach((key) => {
    const base = CASE_TABLES[key] || [];
    const arr = src[key];
    if (Array.isArray(arr) && arr.length === base.length) {
      out[key] = arr.map((v, i) => {
        const n = Number(v);
        return Number.isFinite(n) && n > 0 ? n : Number(base[i] && base[i].chance ? base[i].chance : 1);
      });
    } else {
      out[key] = base.map((row) => Number(row.chance) || 1);
    }
  });
  return out;
}

function buildEffectiveCaseTable(sector, st) {
  const base = st && st.caseTables ? st.caseTables[sector] : null;
  if (!base) return null;
  return base.map((row) => ({
    value: String(row.value),
    chance: Number(row.chance) > 0 ? Number(row.chance) : 0,
    rarity: normalizeRarity(row.rarity)
  }));
}

/**
 * База API: ?api=http://127.0.0.1:PORT; file:// и OBS — HYBRID_API_DEFAULT_ORIGIN.
 * Панель с Live Server на loopback — тот же дефолтный порт (server.py).
 * Страница уже с того же порта, что и API — относительные пути.
 */
function hybridIsLoopbackHost(host) {
  if (!host) return false;
  const h = String(host).toLowerCase();
  return h === "localhost" || h === "127.0.0.1" || h === "::1";
}

function getHybridApiBase() {
  try {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("api");
    if (q) {
      const t = q.trim();
      if (/^https?:\/\//i.test(t)) return t.replace(/\/$/, "");
    }
  } catch (_e) {}
  if (window.location.protocol === "file:") return HYBRID_API_DEFAULT_ORIGIN;
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    const host = window.location.hostname;
    const port = window.location.port;
    if (hybridIsLoopbackHost(host) && port && port !== HYBRID_API_DEFAULT_PORT) {
      return HYBRID_API_DEFAULT_ORIGIN;
    }
    return "";
  }
  return HYBRID_API_DEFAULT_ORIGIN;
}

function hybridApiUrl(path) {
  const p = path.startsWith("/") ? path : `/${path}`;
  const base = getHybridApiBase();
  let url = base ? `${base}${p}` : p;
  try {
    const token = new URLSearchParams(window.location.search).get("token") || "";
    if (token) {
      const u = new URL(url, window.location.origin);
      if (!u.searchParams.has("token")) u.searchParams.set("token", token);
      url = base ? u.href : `${u.pathname}${u.search}${u.hash}`;
    }
  } catch (_e) {}
  return url;
}

/** Отличить server.py от «python -m http.server» (у последнего нет /api/*). */
function hybridPingObsServer(callback) {
  if (typeof callback !== "function") return;
  try {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", hybridApiUrl("/api/version"), true);
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        callback(false);
        return;
      }
      const data = safeJsonParse(xhr.responseText);
      callback(Boolean(data && data.ok && data.server === "obs-hybrid-roulette"));
    };
    xhr.onerror = () => callback(false);
    xhr.send();
  } catch (_e) {
    callback(false);
  }
}

function hybridFetch(path, init = {}) {
  if (typeof fetch !== "function") return Promise.reject(new Error("no fetch"));
  const url = hybridApiUrl(path);
  return fetch(url, {
    ...init,
    mode: "cors",
    credentials: init.credentials !== undefined ? init.credentials : "omit"
  });
}

/** GET JSON через XMLHttpRequest — в OBS Browser Source надёжнее, чем fetch. */
function hybridHttpGetJson(path, onData) {
  if (typeof onData !== "function") return;
  try {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", hybridApiUrl(path), true);
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        if (HYBRID_DEBUG && xhr.status === 404 && path === "/api/state" && !_hybridApi404HintLogged) {
          _hybridApi404HintLogged = true;
          hybridDebugLog(
            "hint",
            `404 на /api/state: откройте панель с порта server.py (http://127.0.0.1:${HYBRID_API_DEFAULT_PORT}/panel.html) или укажите ?api=... Другой процесс на том же порту — не наш API.`,
            { page: String(window.location.href).slice(0, 120), apiBase: getHybridApiBase() || "(same-origin)" }
          );
        }
        hybridDebugThrottled("GET", `${path}:${xhr.status}`, path, {
          status: xhr.status,
          text: (xhr.responseText || "").slice(0, 200)
        });
        return;
      }
      const data = safeJsonParse(xhr.responseText);
      if (data) onData(data);
      else hybridDebugLog("GET", path, "JSON parse failed");
    };
    xhr.onerror = () => hybridDebugLog("GET", path, "network/onerror");
    xhr.send();
  } catch (err) {
    hybridDebugLog("GET", path, String(err));
  }
}

function loadState() {
  const raw = safeStorageGet(STORAGE_KEYS.state);
  const parsed = raw ? safeJsonParse(raw) : null;
  const normalized = normalizeStateModel(parsed);
  normalized.caseWeights = normalizeCaseWeights(parsed && parsed.caseWeights ? parsed.caseWeights : null);
  refreshRuntimeMapsFromState(normalized);
  return normalized;
}

function saveState(state, opts) {
  const replaceHistory = opts && opts.replaceHistory === true;
  const cur = loadState();
  const normalized = normalizeStateModel({
    ...cur,
    ...state,
    history: (Array.isArray(state.history) ? state.history : cur.history).slice(0, 100),
    widgetVisible: typeof state.widgetVisible === "boolean" ? state.widgetVisible : cur.widgetVisible
  });
  refreshRuntimeMapsFromState(normalized);
  normalized.caseWeights = normalizeCaseWeights(state.caseWeights !== undefined ? state.caseWeights : cur.caseWeights);
  safeStorageSet(STORAGE_KEYS.state, JSON.stringify(normalized));
  hybridDebugLog("saveState", "localStorage+POST", {
    historyLen: normalized.history.length,
    replaceHistory: replaceHistory === true,
    suppress: _stateSyncSuppress,
    widgetVisible: normalized.widgetVisible
  });
  if (!_stateSyncSuppress) {
    syncStateToServerIfHttp(normalized, replaceHistory);
  }
}

function syncStateToServerXHR(normalized, replaceHistory) {
  try {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", hybridApiUrl("/api/state"), true);
    xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        hybridDebugLog("POST", "/api/state", { status: xhr.status, text: (xhr.responseText || "").slice(0, 200) });
      }
    };
    xhr.onerror = () => hybridDebugLog("POST", "/api/state", "network/onerror");
    xhr.send(
      JSON.stringify({
        chances: normalized.chances,
        history: normalized.history,
        caseWeights: normalized.caseWeights,
        wheelPrizes: normalized.wheelPrizes,
        caseTables: normalized.caseTables,
        widgetVisible: normalized.widgetVisible,
        replaceHistory: replaceHistory === true
      })
    );
  } catch (err) {
    hybridDebugLog("POST", "/api/state", String(err));
  }
}

function syncStateToServerIfHttp(normalized, replaceHistory) {
  const body = JSON.stringify({
    chances: normalized.chances,
    history: normalized.history,
    caseWeights: normalized.caseWeights,
    wheelPrizes: normalized.wheelPrizes,
    caseTables: normalized.caseTables,
    widgetVisible: normalized.widgetVisible,
    replaceHistory: replaceHistory === true
  });
  hybridFetch("/api/state", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true
  }).catch((err) => hybridDebugLog("POST", "/api/state fetch", String(err)));
  syncStateToServerXHR(normalized, replaceHistory);
}

/** Дублирующая отправка одной записи — надёжнее, если полный POST /api/state режется средой OBS. */
function pushHistoryEntryToHttpApi(entry) {
  const body = JSON.stringify({ entry });
  hybridFetch("/api/history-append", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true
  }).catch((err) => hybridDebugLog("POST", "/api/history-append fetch", String(err)));
  try {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", hybridApiUrl("/api/history-append"), true);
    xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        hybridDebugLog("POST", "/api/history-append", { status: xhr.status });
      }
    };
    xhr.onerror = () => hybridDebugLog("POST", "/api/history-append", "network/onerror");
    xhr.send(body);
  } catch (err) {
    hybridDebugLog("POST", "/api/history-append", String(err));
  }
}

/**
 * Резерв: запись истории через GET + скрытая картинка (часто проходит там, где fetch из file:// / OBS режется).
 * Параметр p — base64url(JSON), без сырой кириллицы в query.
 */
function pushHistoryEntryViaImagePing(entry) {
  try {
    const json = JSON.stringify(entry);
    let b64;
    if (typeof TextEncoder !== "undefined") {
      const utf8 = new TextEncoder().encode(json);
      let bin = "";
      utf8.forEach((c) => {
        bin += String.fromCharCode(c);
      });
      b64 = btoa(bin);
    } else {
      b64 = btoa(unescape(encodeURIComponent(json)));
    }
    b64 = b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const url = `${hybridApiUrl("/api/history-one")}?p=${encodeURIComponent(b64)}&t=${Date.now()}`;
    const img = new Image();
    img.decoding = "async";
    img.src = url;
  } catch (_e) {}
}

function isNonEmptyPlainObject(o) {
  return o != null && typeof o === "object" && !Array.isArray(o) && Object.keys(o).length > 0;
}

/** Слияние состояния с сервера (история и шансы общие для панели и колеса в OBS). */
function applyRemoteStateMergeFromApi(remote) {
  if (!remote || typeof remote !== "object") return;
  const cur = loadState();
  const nextHist = mergeHistoryRemotePreferred(remote.history, cur.history);
  const remoteWp = remote.wheelPrizes;
  const prizesSrc = Array.isArray(remoteWp) && remoteWp.length > 0 ? remoteWp : cur.wheelPrizes;
  const nextWheelPrizes = normalizeWheelPrizes(prizesSrc, remote.chances || cur.chances);
  const remoteCh = remote.chances;
  const chancesSrc = isNonEmptyPlainObject(remoteCh) ? remoteCh : buildChancesFromWheelPrizes(nextWheelPrizes);
  const nextCh = normalizeChances(chancesSrc, activeSectorNamesFromPrizes(nextWheelPrizes));
  const remoteCt = remote.caseTables;
  const caseTablesSrc = isNonEmptyPlainObject(remoteCt) ? remoteCt : cur.caseTables;
  const nextCaseTables = normalizeCaseTables(caseTablesSrc, nextWheelPrizes);
  const nextCw =
    remote.caseWeights != null &&
    typeof remote.caseWeights === "object" &&
    Object.keys(remote.caseWeights).length > 0
      ? normalizeCaseWeights(remote.caseWeights)
      : cur.caseWeights;
  const nextWv =
    remote.widgetVisible != null && typeof remote.widgetVisible === "boolean" ? remote.widgetVisible : cur.widgetVisible;
  if (
    JSON.stringify(cur.chances) === JSON.stringify(nextCh) &&
    JSON.stringify(cur.history) === JSON.stringify(nextHist) &&
    JSON.stringify(cur.caseWeights) === JSON.stringify(nextCw) &&
    JSON.stringify(cur.wheelPrizes) === JSON.stringify(nextWheelPrizes) &&
    JSON.stringify(cur.caseTables) === JSON.stringify(nextCaseTables) &&
    cur.widgetVisible === nextWv
  ) {
    return;
  }
  const widgetPinTurnedOn = nextWv === true && cur.widgetVisible !== true;
  hybridDebugLog("merge", "applyRemoteStateMergeFromApi", {
    remote: hybridDebugStateSnap("remote", remote),
    mergedHistoryLen: nextHist.length,
    widgetPinTurnedOn
  });
  _stateSyncSuppress = true;
  try {
    saveState({
      chances: nextCh,
      history: nextHist,
      caseWeights: nextCw,
      wheelPrizes: nextWheelPrizes,
      caseTables: nextCaseTables,
      widgetVisible: nextWv
    });
  } finally {
    _stateSyncSuppress = false;
  }
  window.dispatchEvent(new CustomEvent("obsHybridStateUpdated", { detail: { widgetPinTurnedOn } }));
}

function pollSharedStateFromHttp() {
  hybridHttpGetJson("/api/state", (data) => {
    if (data && data.ok && typeof data.state === "object" && data.state) {
      const now = Date.now();
      if (now - _hybridLastPollLogAt > 4000) {
        _hybridLastPollLogAt = now;
        hybridDebugLog("poll", "panel GET /api/state", hybridDebugStateSnap("incoming", data.state));
      }
      applyRemoteStateMergeFromApi(data.state);
    } else {
      hybridDebugLog("poll", "panel GET /api/state bad payload", data);
    }
  });
}

function pushSpinCommandToHttpApi(command) {
  const body = JSON.stringify({
    payload: command.payload || {},
    chances: command.chances != null ? command.chances : null,
    caseWeights: command.caseWeights != null ? command.caseWeights : null,
    wheelPrizes: command.wheelPrizes != null ? command.wheelPrizes : null,
    caseTables: command.caseTables != null ? command.caseTables : null
  });
  hybridFetch("/api/spin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body
  }).catch((err) => hybridDebugLog("POST", "/api/spin fetch", String(err)));
  try {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", hybridApiUrl("/api/spin"), true);
    xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        hybridDebugLog("POST", "/api/spin", { status: xhr.status, ts: command.ts });
      }
    };
    xhr.onerror = () => hybridDebugLog("POST", "/api/spin", "network/onerror");
    xhr.send(body);
    hybridDebugLog("spin", "POST /api/spin XHR sent", { ts: command.ts });
  } catch (err) {
    hybridDebugLog("POST", "/api/spin", String(err));
  }
}

function pushResetWheelToHttpApi(cmd) {
  const body = JSON.stringify({ type: cmd.type, ts: cmd.ts });
  hybridFetch("/api/reset-wheel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body
  }).catch((err) => hybridDebugLog("POST", "/api/reset-wheel fetch", String(err)));
  try {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", hybridApiUrl("/api/reset-wheel"), true);
    xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        hybridDebugLog("POST", "/api/reset-wheel", { status: xhr.status });
      }
    };
    xhr.onerror = () => hybridDebugLog("POST", "/api/reset-wheel", "network/onerror");
    xhr.send(body);
    hybridDebugLog("reset", "POST /api/reset-wheel XHR sent", { ts: cmd.ts });
  } catch (err) {
    hybridDebugLog("POST", "/api/reset-wheel", String(err));
  }
}

function sendResetWheelCommand() {
  const cmd = { type: "resetWheel", ts: Date.now() };
  hybridDebugLog("panel", "sendResetWheelCommand", cmd);
  safeStorageSet(STORAGE_KEYS.reset, JSON.stringify(cmd));
  const channel = createMessageChannel();
  if (channel) {
    channel.postMessage(cmd);
    channel.close();
  }
  pushResetWheelToHttpApi(cmd);
}

function sendSpinCommand(payload) {
  const st = loadState();
  const command = {
    type: "spin",
    ts: Date.now(),
    payload: payload || {},
    chances: st.chances,
    caseWeights: st.caseWeights,
    wheelPrizes: st.wheelPrizes,
    caseTables: st.caseTables
  };
  hybridDebugLog("panel", "sendSpinCommand", { ts: command.ts, payload: command.payload });
  safeStorageSet(STORAGE_KEYS.command, JSON.stringify(command));
  const channel = createMessageChannel();
  if (channel) {
    channel.postMessage(command);
    channel.close();
  }
  pushSpinCommandToHttpApi(command);
}

function sendCardCommand(type, payload) {
  const cmd = { type: String(type || ""), ts: Date.now(), payload: payload && typeof payload === "object" ? payload : {} };
  try {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", hybridApiUrl("/api/card-command"), true);
    xhr.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
    xhr.send(JSON.stringify(cmd));
    hybridDebugLog("card", "POST /api/card-command", cmd);
  } catch (err) {
    hybridDebugLog("card", "POST /api/card-command error", String(err));
  }
}

function weightedPick(items) {
  const safeItems = items.filter((item) => Number(item.chance) > 0);
  const total = safeItems.reduce((acc, item) => acc + Number(item.chance), 0);
  if (total <= 0) return safeItems[0];
  let cursor = Math.random() * total;
  for (let i = 0; i < safeItems.length; i += 1) {
    cursor -= Number(safeItems[i].chance);
    if (cursor <= 0) return safeItems[i];
  }
  return safeItems[safeItems.length - 1];
}

function pickSectorByChances(chances) {
  const items = SECTORS.map((sector) => ({ value: sector, chance: chances[sector] || 0 }));
  const selected = weightedPick(items);
  return selected ? selected.value : "БОНУСКА";
}

/** Точка на окружности (0° — вверх, по часовой). */
function wheelEdgePoint(deg) {
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: Math.cos(rad), y: Math.sin(rad) };
}

const WHEEL_TEXTURE_BY_SECTOR = {
  БОНУСКА: `${ASSETS_TEXTURES}/texture_bonus.png`,
  КУПОН: `${ASSETS_TEXTURES}/texture_coupon.png`,
  БАЛАНС: `${ASSETS_TEXTURES}/texture_balance.png`
};

/** Тонкие линии между лепестками (CSS-слой поверх SVG). */
function getWheelDividerBackground() {
  const step = 360 / VISUAL_WEDGES.length;
  return `repeating-conic-gradient(
    from 0deg,
    rgba(255, 247, 221, 0.96) 0deg 0.16deg,
    rgba(35, 20, 10, 0.86) 0.16deg 0.44deg,
    transparent 0.44deg ${step}deg
  )`;
}

/**
 * Мелкий повторяющийся тайл (pattern tiles) + сдвиг/поворот — полное покрытие лепестка без «дыр» от одного большого растяжения.
 */
function wedgeTexturePatternParams(index) {
  const rot = 8 + index * 23 + (index % 5) * 31 + (index % 2) * 11;
  const scale = 0.92 + (index % 6) * 0.036;
  const tx = (((index * 29) % 13) - 6) * 0.035;
  const ty = (((index * 37) % 15) - 7) * 0.035;
  const tile = 0.24 + (index % 5) * 0.032;
  const brickX = (index % 3) * (tile * 0.37);
  const brickY = (index % 4) * (tile * 0.31);
  return { rot, scale, tx, ty, tile, brickX, brickY };
}

/**
 * 16 лепестков: градиент + текстура 1024×1024 с разным patternTransform на каждый сегмент.
 * SVG вставляется в DOM (не data: URL), чтобы подгружались PNG из assets/textures/.
 */
function buildWheelFaceSvgMarkup() {
  const colorByPrize = {
    БОНУСКА: ["#fff0b3", "#f2c94c", "#9a5a05"],
    КУПОН: ["#dbf3ff", "#67c8ef", "#136694"],
    БАЛАНС: ["#d4f8f3", "#4ec4b8", "#0f6d62"]
  };

  const gradIdBySector = {
    БОНУСКА: "grad-bonus",
    КУПОН: "grad-coupon",
    БАЛАНС: "grad-balance"
  };

  const gradRows = [
    ["grad-bonus", ...colorByPrize.БОНУСКА],
    ["grad-coupon", ...colorByPrize.КУПОН],
    ["grad-balance", ...colorByPrize.БАЛАНС]
  ];

  let defs =
    '<filter id="wheelTexMicroSoften" x="-25%" y="-25%" width="150%" height="150%">' +
    '<feGaussianBlur in="SourceGraphic" stdDeviation="0.012" result="b"/>' +
    '<feBlend in="SourceGraphic" in2="b" mode="screen"/>' +
    "</filter>";
  for (const row of gradRows) {
    const [id, light, mid, dark] = row;
    defs += `<radialGradient id="${id}" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse"><stop offset="0%" stop-color="${light}"/><stop offset="55%" stop-color="${mid}"/><stop offset="100%" stop-color="${dark}"/></radialGradient>`;
  }

  const step = 360 / VISUAL_WEDGES.length;
  for (let i = 0; i < VISUAL_WEDGES.length; i += 1) {
    const sector = VISUAL_WEDGES[i];
    const src = migrateLegacyAssetUrl(WHEEL_TEXTURE_BY_SECTOR[sector] || DEFAULT_TEXTURE_FALLBACK);
    const { rot, scale, tx, ty, tile, brickX, brickY } = wedgeTexturePatternParams(i);
    const t = tile.toFixed(4);
    const tWide = (tile * (1.06 + (i % 3) * 0.02)).toFixed(4);
    const ptA = `rotate(${rot}) scale(${scale.toFixed(4)}) translate(${tx.toFixed(4)},${ty.toFixed(4)})`;
    const ptB = `rotate(${rot}) scale(${scale.toFixed(4)}) translate(${(tx + brickX).toFixed(4)},${(ty + brickY).toFixed(4)})`;
    const ox = (tx + tile * (0.48 + (i % 5) * 0.04)).toFixed(4);
    const oy = (ty - tile * (0.36 + (i % 4) * 0.05)).toFixed(4);
    const ptC = `rotate(${rot + 14 + (i % 6) * 3}) scale(${(scale * 1.03).toFixed(4)}) translate(${ox},${oy})`;
    defs += `<pattern id="wtp${i}a" patternUnits="userSpaceOnUse" width="${t}" height="${t}" patternTransform="${ptA}">`;
    defs += `<image href="${src}" xlink:href="${src}" width="${t}" height="${t}" preserveAspectRatio="none"/>`;
    defs += `</pattern>`;
    defs += `<pattern id="wtp${i}b" patternUnits="userSpaceOnUse" width="${t}" height="${t}" patternTransform="${ptB}">`;
    defs += `<image href="${src}" xlink:href="${src}" width="${t}" height="${t}" preserveAspectRatio="none"/>`;
    defs += `</pattern>`;
    defs += `<pattern id="wtp${i}c" patternUnits="userSpaceOnUse" width="${tWide}" height="${tWide}" patternTransform="${ptC}">`;
    defs += `<image href="${src}" xlink:href="${src}" width="${tWide}" height="${tWide}" preserveAspectRatio="none"/>`;
    defs += `</pattern>`;
  }

  let basePaths = "";
  let texPathsA = "";
  let texPathsB = "";
  let texPathsC = "";
  for (let i = 0; i < VISUAL_WEDGES.length; i += 1) {
    const start = i * step;
    const end = (i + 1) * step;
    const p0 = wheelEdgePoint(start);
    const p1 = wheelEdgePoint(end);
    const largeArc = end - start > 180 ? 1 : 0;
    const gid = gradIdBySector[VISUAL_WEDGES[i]] || "grad-bonus";
    const d = `M 0 0 L ${p0.x.toFixed(5)} ${p0.y.toFixed(5)} A 1 1 0 ${largeArc} 1 ${p1.x.toFixed(5)} ${p1.y.toFixed(5)} Z`;
    basePaths += `<path d="${d}" fill="url(#${gid})"/>`;
    texPathsA += `<path d="${d}" fill="url(#wtp${i}a)"/>`;
    texPathsB += `<path d="${d}" fill="url(#wtp${i}b)"/>`;
    texPathsC += `<path d="${d}" fill="url(#wtp${i}c)"/>`;
  }

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="-1.02 -1.02 2.04 2.04" preserveAspectRatio="xMidYMid meet">` +
    `<defs>${defs}</defs>` +
    `<g>${basePaths}</g>` +
    `<g filter="url(#wheelTexMicroSoften)" opacity="0.92">` +
    `<g opacity="0.5" style="mix-blend-mode:overlay">${texPathsA}</g>` +
    `<g opacity="0.36" style="mix-blend-mode:overlay">${texPathsB}</g>` +
    `<g opacity="0.26" style="mix-blend-mode:soft-light">${texPathsC}</g>` +
    `</g>` +
    `</svg>`
  );
}

function mountWheelFaceIntoDom(wheelEl) {
  const grain = wheelEl.querySelector(".wheel-grain");
  const markup = buildWheelFaceSvgMarkup();
  const parsed = new DOMParser().parseFromString(markup, "image/svg+xml");
  if (parsed.querySelector("parsererror")) return;
  const parsedRoot = parsed.documentElement;
  if (!parsedRoot || parsedRoot.nodeName.toLowerCase() !== "svg") return;

  const fresh = document.importNode(parsedRoot, true);
  fresh.setAttribute("class", "wheel-face-svg");
  fresh.setAttribute("aria-hidden", "true");

  const oldSvg = wheelEl.querySelector(".wheel-face-svg");
  if (oldSvg) oldSvg.replaceWith(fresh);
  else if (grain) wheelEl.insertBefore(fresh, grain);
  else wheelEl.insertBefore(fresh, wheelEl.firstChild);

  let divLayer = wheelEl.querySelector(".wheel-dividers");
  if (!divLayer) {
    divLayer = document.createElement("div");
    divLayer.className = "wheel-dividers";
    divLayer.setAttribute("aria-hidden", "true");
    const g = wheelEl.querySelector(".wheel-grain");
    if (g) wheelEl.insertBefore(divLayer, g);
    else wheelEl.appendChild(divLayer);
  }
  divLayer.style.background = getWheelDividerBackground();

  wheelEl.style.backgroundImage = "none";
  wheelEl.style.backgroundColor = "transparent";
}

const WHEEL_ICON_BY_SECTOR = {
  БОНУСКА: `${ASSETS_ICONS}/bonus.png`,
  КУПОН: `${ASSETS_ICONS}/coupon.png`,
  БАЛАНС: `${ASSETS_ICONS}/balance.png`
};

function initWheelPage() {
  const wheel = document.getElementById("wheel");
  const wheelRotor = document.getElementById("wheelRotor");
  const wheelLabels = document.getElementById("wheelLabels");
  const wheelStage = document.querySelector(".wheel-stage");
  const caseStage = document.getElementById("caseStage");
  const caseTrack = document.getElementById("caseTrack");
  if (!wheel || !wheelRotor || !wheelLabels || !wheelStage || !caseStage || !caseTrack) return;
  hybridDebugLog("wheel", "initWheelPage", { apiBase: getHybridApiBase() || "(same-origin)", HYBRID_DEBUG });

  const commandChannel = createMessageChannel();
  let state = loadState();
  let spinning = false;
  /* Только команды ПОСЛЕ открытия виджета (не крутить при старте и не повторять прошлый спин). */
  let lastCommandTs = Date.now();
  let lastResetTs = 0;
  let currentRotation = 0;
  /** Не применять «скрыть колесо в простое» до этой метки (ожидание после итога). */
  let wheelHoldUntil = 0;
  /** После сброса / конца розыгрыша не показывать диск снова из-за опроса state, пока не «Показать виджет» или новый спин. */
  let wheelSceneLockedHidden = false;
  const wheelTimeouts = new Set();
  let wheelTickRafId = 0;
  let caseTickRafId = 0;
  const wheelTickPool = [];
  const caseTickPool = [];
  let wheelTickPoolIdx = 0;
  let caseTickPoolIdx = 0;

  function ensureTickPools() {
    if (!wheelTickPool.length) {
      for (let i = 0; i < TICK_POOL_SIZE; i += 1) {
        const a = new Audio(WHEEL_TICK_SOUND_URL);
        a.preload = "auto";
        a.volume = WHEEL_TICK_VOLUME;
        wheelTickPool.push(a);
      }
    }
    if (!caseTickPool.length) {
      for (let i = 0; i < TICK_POOL_SIZE; i += 1) {
        const a = new Audio(CASE_TICK_SOUND_URL);
        a.preload = "auto";
        a.volume = CASE_TICK_VOLUME;
        caseTickPool.push(a);
      }
    }
  }

  function safePlayAudio(audio) {
    if (!audio) return;
    try {
      audio.currentTime = 0;
      const p = audio.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    } catch (_e) {
      // ignore sound errors in OBS/browser contexts
    }
  }

  function playWheelTickSound() {
    if (!wheelTickPool.length) return;
    const snd = wheelTickPool[wheelTickPoolIdx];
    wheelTickPoolIdx = (wheelTickPoolIdx + 1) % wheelTickPool.length;
    snd.volume = WHEEL_TICK_VOLUME;
    safePlayAudio(snd);
  }

  function playCaseTickSound() {
    if (!caseTickPool.length) return;
    const snd = caseTickPool[caseTickPoolIdx];
    caseTickPoolIdx = (caseTickPoolIdx + 1) % caseTickPool.length;
    snd.volume = CASE_TICK_VOLUME;
    safePlayAudio(snd);
  }

  function stopWheelTickWatcher() {
    if (wheelTickRafId) {
      window.cancelAnimationFrame(wheelTickRafId);
      wheelTickRafId = 0;
    }
  }

  function stopCaseTickWatcher() {
    if (caseTickRafId) {
      window.cancelAnimationFrame(caseTickRafId);
      caseTickRafId = 0;
    }
  }

  function stopAllTickWatchers() {
    stopWheelTickWatcher();
    stopCaseTickWatcher();
  }

  function parseTransformValues(el) {
    if (!el) return { x: 0, deg: 0 };
    const tr = window.getComputedStyle(el).transform;
    if (!tr || tr === "none") return { x: 0, deg: 0 };
    const m2 = tr.match(/^matrix\(([^)]+)\)$/);
    if (m2) {
      const p = m2[1].split(",").map((v) => Number(v.trim()) || 0);
      const a = p[0] || 1;
      const b = p[1] || 0;
      const x = p[4] || 0;
      let deg = (Math.atan2(b, a) * 180) / Math.PI;
      if (!Number.isFinite(deg)) deg = 0;
      if (deg < 0) deg += 360;
      return { x, deg };
    }
    const m3 = tr.match(/^matrix3d\(([^)]+)\)$/);
    if (m3) {
      const p = m3[1].split(",").map((v) => Number(v.trim()) || 0);
      const a = p[0] || 1;
      const b = p[1] || 0;
      const x = p[12] || 0;
      let deg = (Math.atan2(b, a) * 180) / Math.PI;
      if (!Number.isFinite(deg)) deg = 0;
      if (deg < 0) deg += 360;
      return { x, deg };
    }
    return { x: 0, deg: 0 };
  }

  function startWheelTickWatcher(segmentDeg) {
    ensureTickPools();
    stopWheelTickWatcher();
    const stepDeg = Math.max(0.01, Number(segmentDeg) || 0.01);
    let prevDeg = parseTransformValues(wheelRotor).deg;
    let totalPassed = 0;
    let lastStep = 0;
    let lastPlayAt = 0;

    function frame() {
      const curDeg = parseTransformValues(wheelRotor).deg;
      let delta = curDeg - prevDeg;
      if (delta < -180) delta += 360;
      else if (delta > 180) delta -= 360;
      if (delta < 0) delta = 0;
      totalPassed += delta;
      prevDeg = curDeg;
      const step = Math.floor(totalPassed / stepDeg);
      if (step > lastStep) {
        const now = Date.now();
        const crossed = Math.min(4, step - lastStep);
        for (let i = 0; i < crossed; i += 1) {
          if (now - lastPlayAt >= WHEEL_TICK_MIN_INTERVAL_MS) {
            playWheelTickSound();
            lastPlayAt = now;
          }
        }
        lastStep = step;
      }
      wheelTickRafId = window.requestAnimationFrame(frame);
    }
    wheelTickRafId = window.requestAnimationFrame(frame);
  }

  function startCaseTickWatcher(itemPitch, wrapperCenterX, padLeft) {
    ensureTickPools();
    stopCaseTickWatcher();
    const pitch = Math.max(1, Number(itemPitch) || 1);
    const centerX = Number(wrapperCenterX) || 0;
    const leftPad = Number(padLeft) || 0;
    let baseX = parseTransformValues(caseTrack).x;
    let lastStep = Math.floor((centerX - (baseX + leftPad)) / pitch);
    let lastPlayAt = 0;

    function frame() {
      const x = parseTransformValues(caseTrack).x;
      const step = Math.floor((centerX - (x + leftPad)) / pitch);
      if (step > lastStep) {
        const now = Date.now();
        const crossed = Math.min(4, step - lastStep);
        for (let i = 0; i < crossed; i += 1) {
          if (now - lastPlayAt >= CASE_TICK_MIN_INTERVAL_MS) {
            playCaseTickSound();
            lastPlayAt = now;
          }
        }
        lastStep = step;
      }
      caseTickRafId = window.requestAnimationFrame(frame);
    }
    caseTickRafId = window.requestAnimationFrame(frame);
  }

  function wheelSetTimeout(fn, ms) {
    const id = window.setTimeout(() => {
      wheelTimeouts.delete(id);
      fn();
    }, ms);
    wheelTimeouts.add(id);
    return id;
  }

  function clearWheelTimeouts() {
    wheelTimeouts.forEach((tid) => window.clearTimeout(tid));
    wheelTimeouts.clear();
  }

  function performFullWheelReset() {
    hybridDebugLog("wheel", "performFullWheelReset", null);
    clearWheelTimeouts();
    stopAllTickWatchers();
    spinning = false;
    wheelHoldUntil = 0;
    lastCommandTs = Date.now() + 1;
    caseStage.classList.add("hidden");
    caseStage.classList.remove("split-reveal");
    caseStage.classList.remove("reveal-from-wheel");
    caseStage.classList.remove("reveal-from-wheel");
    caseTrack.innerHTML = "";
    caseTrack.style.transition = "none";
    caseTrack.style.transform = "translateX(0px)";
    wheelRotor.style.transition = "none";
    currentRotation = 0;
    wheelRotor.style.transform = "rotate(0deg)";
    void wheelRotor.offsetWidth;
    wheelSceneLockedHidden = true;
    wheelStage.classList.add("is-concealed");
  }

  function handleResetCommand(cmd) {
    if (!cmd || cmd.type !== "resetWheel") return;
    if (cmd.ts <= lastResetTs) return;
    lastResetTs = cmd.ts;
    hybridDebugLog("wheel", "handleResetCommand", cmd);
    performFullWheelReset();
  }

  function applyIdleWheelVisibility() {
    if (spinning || Date.now() < wheelHoldUntil) return;
    if (wheelSceneLockedHidden) {
      wheelStage.classList.add("is-concealed");
      return;
    }
    const st = loadState();
    const show = st.widgetVisible === true;
    wheelStage.classList.toggle("is-concealed", !show);
  }

  function fadeWheelIn(done) {
    const already = !wheelStage.classList.contains("is-concealed");
    wheelStage.classList.remove("is-concealed");
    if (typeof done !== "function") return;
    if (already) {
      window.requestAnimationFrame(() => done());
      return;
    }
    wheelSetTimeout(done, WHEEL_FADE_MS);
  }

  function renderWheel() {
    state = loadState();
    const iconMap = {};
    (state.wheelPrizes || []).forEach((p) => {
      iconMap[p.name] = migrateLegacyAssetUrl(p.icon || DEFAULT_WHEEL_ICON);
    });
    mountWheelFaceIntoDom(wheel);
    wheelLabels.innerHTML = "";
    const sectorCount = SECTORS.length;
    const wedgeCount = VISUAL_WEDGES.length;
    const iconScale =
      sectorCount <= 3 ? 0.196 : sectorCount <= 4 ? 0.168 : sectorCount <= 6 ? 0.136 : 0.112;
    const iconRadius =
      wedgeCount <= 6 ? 0.388 : wedgeCount <= 8 ? 0.381 : wedgeCount <= 12 ? 0.373 : 0.367;
    const segment = 360 / VISUAL_WEDGES.length;
    VISUAL_WEDGES.forEach((sector, index) => {
      const label = document.createElement("div");
      label.className = "wheel-label";
      const angle = index * segment + segment / 2;
      const img = document.createElement("img");
      img.className = "wheel-label-icon";
      img.src = migrateLegacyAssetUrl(iconMap[sector] || WHEEL_ICON_BY_SECTOR[sector] || DEFAULT_WHEEL_ICON);
      img.width = 518;
      img.height = 481;
      img.alt = "";
      img.style.width = `calc(var(--wheel-size) * ${iconScale.toFixed(3)})`;
      label.appendChild(img);
      /* Иконка без контр-ворота — «вшита» в лепесток; ширина PNG вдоль касательной (как Crazy Time). */
      label.style.transform = `rotate(${angle}deg) translate(0, calc(-1 * var(--wheel-size) * ${iconRadius.toFixed(3)}))`;
      wheelLabels.appendChild(label);
    });
  }

  function getVisualIndicesForSector(sector) {
    const indices = [];
    for (let i = 0; i < VISUAL_WEDGES.length; i += 1) {
      if (VISUAL_WEDGES[i] === sector) {
        indices.push(i);
      }
    }
    return indices;
  }

  /**
   * Лента кейса: случайные слоты, затем выигрыш, затем «хвост» — чтобы справа от центра не было пустоты.
   */
  function buildCaseRollItems(table, finalValue) {
    const prefixLen = 48;
    const tailLen = 48;
    const items = [];
    for (let i = 0; i < prefixLen; i += 1) {
      items.push(weightedPick(table) || table[0]);
    }
    const finalItem = table.find((item) => item.value === finalValue) || table[0];
    items.push(finalItem);
    for (let j = 0; j < tailLen; j += 1) {
      items.push(weightedPick(table) || table[0]);
    }
    return { items, winnerIndex: prefixLen };
  }

  function renderCaseTrack(items, sector) {
    const mode = prizeDisplayModeForSector(sector);
    caseTrack.innerHTML = "";
    items.forEach((item) => {
      const rarity = normalizeRarity(item && item.rarity);
      const node = document.createElement("div");
      node.className = `case-item rarity-${rarity}`;
      node.dataset.caseSector = sector;
      node.dataset.rarity = rarity;
      node.textContent = formatPrizeDisplay(item.value, mode);
      caseTrack.appendChild(node);
    });
  }

  function animateWheelToSector(sector, onDone) {
    const candidates = getVisualIndicesForSector(sector);
    const index = candidates.length ? candidates[randomInt(0, candidates.length - 1)] : 0;
    const segment = 360 / VISUAL_WEDGES.length;
    const sectorCenter = index * segment + segment / 2;
    const normalizedCurrent = ((currentRotation % 360) + 360) % 360;
    /* Указатель сверху (12 часов) смотрит на 0° диска. */
    const pointerAngleDeg = 0;
    const combined = (normalizedCurrent + sectorCenter) % 360;
    const jitter = (Math.random() * 2 - 1) * (segment * WHEEL_WEDGE_VISUAL_JITTER);
    const delta = (pointerAngleDeg - (combined + jitter) + 360) % 360;
    const loops = randomInt(4, 6);
    currentRotation += loops * 360 + delta;
    wheelRotor.style.transition = `transform ${WHEEL_SPIN_MS}ms cubic-bezier(0.08, 0.93, 0.34, 1)`;
    wheelRotor.style.transform = `rotate(${currentRotation}deg)`;
    // Тик ровно в момент, когда указатель проходит левую границу очередного лепестка.
    startWheelTickWatcher(segment);

    wheelSetTimeout(() => {
      stopWheelTickWatcher();
      if (typeof onDone === "function") onDone();
    }, WHEEL_SPIN_MS);
  }

  function animateCaseOpen(sector, forcedItem, onDone) {
    state = loadState();
    const table = buildEffectiveCaseTable(sector, state);
    if (!table) {
      if (typeof onDone === "function") onDone(null);
      return;
    }
    let final;
    if (forcedItem && String(forcedItem).trim()) {
      const hit = table.find((it) => tableItemMatchesForced(it.value, forcedItem));
      final = hit ? hit.value : weightedPick(table).value;
    } else {
      final = weightedPick(table).value;
    }
    const roll = buildCaseRollItems(table, final);
    renderCaseTrack(roll.items, sector);
    caseTrack.style.transition = "none";
    caseTrack.style.transform = "translateX(0px)";
    caseStage.classList.remove("reveal-from-wheel");
    caseStage.classList.remove("split-reveal");
    caseStage.classList.remove("hidden");
    caseStage.classList.add("reveal-from-wheel");
    void caseTrack.offsetWidth;
    void caseStage.offsetWidth;
    window.requestAnimationFrame(() => {
      caseStage.classList.remove("reveal-from-wheel");
      caseStage.classList.add("split-reveal");
      wheelSetTimeout(() => {
        caseTrack.style.transition = `transform ${CASE_SCROLL_MS}ms cubic-bezier(0.07, 0.74, 0.1, 1)`;
        const allNodes = caseTrack.querySelectorAll(".case-item");
        const gap = Number.parseFloat(window.getComputedStyle(caseTrack).columnGap || window.getComputedStyle(caseTrack).gap || "0") || 0;
        const itemWidth = allNodes[0].getBoundingClientRect().width + gap;
        const wrapperWidth = caseTrack.parentElement.getBoundingClientRect().width;
        const padLeft = Number.parseFloat(window.getComputedStyle(caseTrack).paddingLeft || "0") || 0;
        const targetIndex = roll.winnerIndex;
        const jitterPx = (Math.random() * 2 - 1) * CASE_CELL_VISUAL_JITTER_PX;
        const targetX = -(targetIndex * itemWidth - (wrapperWidth / 2 - itemWidth / 2)) + jitterPx;
        caseTrack.style.transform = `translateX(${targetX}px)`;
        // Тик в момент, когда левая граница слота пересекает центральную жёлтую линию.
        startCaseTickWatcher(itemWidth, wrapperWidth / 2, padLeft);
      }, CASE_SPLIT_REVEAL_MS);
    });

    wheelSetTimeout(() => {
      stopCaseTickWatcher();
      if (typeof onDone === "function") onDone(final);
    }, CASE_SPLIT_REVEAL_MS + CASE_SCROLL_MS + 120);
  }

  function saveRoundResult(selectedSector, finalItem, onDone) {
    const fresh = loadState();
    const entry = {
      sector: selectedSector,
      item: finalItem || "-",
      time: Date.now()
    };
    hybridDebugLog("wheel", "saveRoundResult", entry);
    fresh.history.unshift(entry);
    fresh.history = fresh.history.slice(0, 100);
    saveState(fresh);
    pushHistoryEntryToHttpApi(entry);
    pushHistoryEntryViaImagePing(entry);
    safeStorageSet(STORAGE_KEYS.result, JSON.stringify(entry));
    if (typeof onDone === "function") onDone();
  }

  function runRound(payload, onDone) {
    state = loadState();
    const forcedSector =
      payload && payload.forceSector && SECTORS.includes(payload.forceSector) ? payload.forceSector : "";
    const selectedSector = forcedSector || pickSectorByChances(state.chances);

    animateWheelToSector(selectedSector, () => {
      /* КУПОН: фикс, кейс не показываем. */
      if (selectedSector === "КУПОН") {
        caseStage.classList.add("hidden");
        const couponTable = CASE_TABLES[selectedSector] || [{ value: "1000 фикс", chance: 100, rarity: "purple" }];
        const forced = payload && payload.forceItem ? payload.forceItem : "";
        const hit = forced && couponTable.find((it) => tableItemMatchesForced(it.value, forced));
        const finalItem = hit ? hit.value : couponTable[0].value;
        saveRoundResult(selectedSector, finalItem, onDone);
        return;
      }

      wheelSetTimeout(() => {
        animateCaseOpen(selectedSector, payload && payload.forceItem ? payload.forceItem : "", (finalItem) => {
          saveRoundResult(selectedSector, finalItem, onDone);
        });
      }, CASE_START_DELAY_MS);
    });
  }

  function scheduleWheelHideAfterResult() {
    hybridDebugLog("wheel", "scheduleWheelHideAfterResult", { ms: WHEEL_HIDE_AFTER_RESULT_MS });
    wheelHoldUntil = Date.now() + WHEEL_HIDE_AFTER_RESULT_MS;
    wheelSetTimeout(() => {
      wheelHoldUntil = 0;
      caseStage.classList.add("hidden");
      caseStage.classList.remove("split-reveal");
      wheelSceneLockedHidden = true;
      wheelStage.classList.add("is-concealed");
      applyIdleWheelVisibility();
    }, WHEEL_HIDE_AFTER_RESULT_MS);
  }

  function startGame(payload) {
    if (spinning) {
      hybridDebugLog("wheel", "startGame skipped (spinning)", null);
      return;
    }
    stopAllTickWatchers();
    hybridDebugLog("wheel", "startGame", payload || {});
    spinning = true;
    wheelHoldUntil = 0;
    wheelSceneLockedHidden = false;
    state = loadState();
    caseStage.classList.add("hidden");
    fadeWheelIn(() => {
      runRound(payload || {}, () => {
        spinning = false;
        scheduleWheelHideAfterResult();
      });
    });
  }

  function handleCommand(command) {
    if (!command || command.type !== "spin") return;
    if (command.ts <= lastCommandTs) return;
    lastCommandTs = command.ts;
    hybridDebugLog("wheel", "handleCommand spin", { ts: command.ts, payload: command.payload });
    let sCmd = loadState();
    let cmdDirty = false;
    if (command.chances && typeof command.chances === "object") {
      sCmd.chances = normalizeChances(command.chances);
      cmdDirty = true;
    }
    if (command.caseWeights && typeof command.caseWeights === "object") {
      sCmd.caseWeights = normalizeCaseWeights(command.caseWeights);
      cmdDirty = true;
    }
    if (Array.isArray(command.wheelPrizes)) {
      sCmd.wheelPrizes = normalizeWheelPrizes(command.wheelPrizes, command.chances || sCmd.chances);
      cmdDirty = true;
    }
    if (command.caseTables && typeof command.caseTables === "object") {
      const wp = sCmd.wheelPrizes || loadState().wheelPrizes;
      sCmd.caseTables = normalizeCaseTables(command.caseTables, wp);
      cmdDirty = true;
    }
    if (cmdDirty) saveState(sCmd);
    startGame(command.payload || {});
  }

  /** Без /api/poll (на старом сервере 404): state → reset → spin, порядок важен. */
  function pollWidgetBridge() {
    const x1 = new XMLHttpRequest();
    x1.open("GET", hybridApiUrl("/api/state"), true);
    x1.onerror = () => hybridDebugThrottled("widgetPoll", "state:err", "GET /api/state", "onerror");
    x1.onload = () => {
      if (x1.status >= 200 && x1.status < 300) {
        const d = safeJsonParse(x1.responseText);
        if (d && d.ok && d.state) applyRemoteStateMergeFromApi(d.state);
      } else {
        hybridDebugThrottled("widgetPoll", `state:${x1.status}`, "GET /api/state", { status: x1.status });
      }
      const x2 = new XMLHttpRequest();
      x2.open("GET", hybridApiUrl("/api/reset-wheel"), true);
      x2.onerror = () => hybridDebugThrottled("widgetPoll", "reset:err", "GET /api/reset-wheel", "onerror");
      x2.onload = () => {
        if (x2.status >= 200 && x2.status < 300) {
          const d2 = safeJsonParse(x2.responseText);
          if (d2 && d2.ok && d2.reset) handleResetCommand(d2.reset);
        } else {
          hybridDebugThrottled("widgetPoll", `reset:${x2.status}`, "GET /api/reset-wheel", { status: x2.status });
        }
        const x3 = new XMLHttpRequest();
        x3.open("GET", hybridApiUrl("/api/spin"), true);
        x3.onerror = () => hybridDebugThrottled("widgetPoll", "spin:err", "GET /api/spin", "onerror");
        x3.onload = () => {
          if (x3.status >= 200 && x3.status < 300) {
            const d3 = safeJsonParse(x3.responseText);
            if (d3 && d3.ok && d3.command) handleCommand(d3.command);
          } else {
            hybridDebugThrottled("widgetPoll", `spin:${x3.status}`, "GET /api/spin", { status: x3.status });
          }
        };
        x3.send();
      };
      x2.send();
    };
    x1.send();
  }

  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEYS.command && event.newValue) {
      const command = safeJsonParse(event.newValue);
      if (command) handleCommand(command);
    }
    if (event.key === STORAGE_KEYS.reset && event.newValue) {
      const rst = safeJsonParse(event.newValue);
      if (rst) handleResetCommand(rst);
    }
    if (event.key === STORAGE_KEYS.state) {
      state = loadState();
    }
  });
  if (commandChannel) {
    commandChannel.onmessage = (event) => {
      const d = event.data;
      if (!d || typeof d !== "object") return;
      if (d.type === "resetWheel") handleResetCommand(d);
      else handleCommand(d);
    };
  }
  setInterval(() => {
    const command = safeJsonParse(safeStorageGet(STORAGE_KEYS.command));
    if (command) handleCommand(command);
    const rst = safeJsonParse(safeStorageGet(STORAGE_KEYS.reset));
    if (rst) handleResetCommand(rst);
  }, 450);
  setInterval(pollWidgetBridge, 280);
  pollWidgetBridge();

  window.addEventListener("obsHybridStateUpdated", (ev) => {
    if (ev.detail && ev.detail.widgetPinTurnedOn) {
      wheelSceneLockedHidden = false;
    }
    applyIdleWheelVisibility();
  });

  renderWheel();
  caseStage.classList.add("hidden");
  applyIdleWheelVisibility();
  initCardsPage();
}

function initCardsPage() {
  const shell = document.getElementById("cardsShell");
  const cardMain = document.getElementById("cardMain");
  if (!shell || !cardMain) return;

  let lastTs = 0;

  function applyCardCommand(cmd) {
    if (!cmd || typeof cmd !== "object") return;
    if ((cmd.ts || 0) <= lastTs) return;
    lastTs = cmd.ts || Date.now();
    const t = cmd.type;
    if (t === "hide") {
      shell.classList.remove("is-visible");
      return;
    }
    if (t === "show") {
      cardMain.className = "play-card face-down";
      cardMain.innerHTML = "";
      shell.classList.add("is-visible");
      return;
    }
    if (t === "reveal") {
      const rank = String(cmd.payload && cmd.payload.rank ? cmd.payload.rank : randomCardRank());
      const suitKey = String(cmd.payload && cmd.payload.suit ? cmd.payload.suit : "diamonds");
      cardMain.classList.add("reveal-flip");
      window.setTimeout(() => {
        renderCardFaceInto(cardMain, rank, suitKey);
        cardMain.classList.remove("reveal-flip");
      }, 260);
      shell.classList.add("is-visible");
    }
  }

  function pollCardCommand() {
    hybridHttpGetJson("/api/card-command", (data) => {
      if (data && data.ok && data.command) applyCardCommand(data.command);
    });
  }

  setInterval(pollCardCommand, 280);
  pollCardCommand();
}

function initPanelPage() {
  const chanceRows = document.getElementById("chanceRows");
  const wheelChanceHint = document.getElementById("wheelChanceHint");
  const applyChancesBtn = document.getElementById("applyChancesBtn");
  const quickSavePresetBtn = document.getElementById("quickSavePresetBtn");
  const exportChancesBtn = document.getElementById("exportChancesBtn");
  const importChancesBtn = document.getElementById("importChancesBtn");
  const importChancesFile = document.getElementById("importChancesFile");
  const spinNowBtn = document.getElementById("spinNowBtn");
  const toggleWidgetBtn = document.getElementById("toggleWidgetBtn");
  const forceResetWheelBtn = document.getElementById("forceResetWheelBtn");
  const clearHistoryBtn = document.getElementById("clearHistoryBtn");
  const cardShowBtn = document.getElementById("cardShowBtn");
  const cardRevealBtn = document.getElementById("cardRevealBtn");
  const cardHideBtn = document.getElementById("cardHideBtn");
  const forcedSectorSelect = document.getElementById("forcedSectorSelect");
  const forcedItemInput = document.getElementById("forcedItemInput");
  const historyList = document.getElementById("historyList");
  const caseWeightRows = document.getElementById("caseWeightRows");
  const tabPanelBtn = document.getElementById("tabPanelBtn");
  const tabConstructorBtn = document.getElementById("tabConstructorBtn");
  const tabPresetsBtn = document.getElementById("tabPresetsBtn");
  const panelViewMain = document.getElementById("panelViewMain");
  const constructorViewMain = document.getElementById("constructorViewMain");
  const presetsViewMain = document.getElementById("presetsViewMain");
  const presetNameInput = document.getElementById("presetNameInput");
  const savePresetBtn = document.getElementById("savePresetBtn");
  const exportPresetBtn = document.getElementById("exportPresetBtn");
  const importPresetBtn = document.getElementById("importPresetBtn");
  const importPresetFile = document.getElementById("importPresetFile");
  const presetList = document.getElementById("presetList");
  if (
    !chanceRows ||
    !caseWeightRows ||
    !applyChancesBtn ||
    !exportChancesBtn ||
    !importChancesBtn ||
    !importChancesFile ||
    !spinNowBtn ||
    !clearHistoryBtn ||
    !forcedSectorSelect ||
    !forcedItemInput ||
    !historyList
  ) {
    return;
  }

  const commandChannel = createMessageChannel();
  let state = loadState();
  /** Подпись сохранённого в форме конфига — не перерисовывать конструктор при опросе API, если изменилась только история. */
  let panelConstructorConfigSig = "";
  let cardRound = null;

  function bumpPanelConstructorConfigSig() {
    panelConstructorConfigSig = JSON.stringify({
      wp: state.wheelPrizes,
      ct: state.caseTables,
      cw: state.caseWeights
    });
  }

  function refreshPanelAfterStateSync() {
    state = loadState();
    const sig = JSON.stringify({
      wp: state.wheelPrizes,
      ct: state.caseTables,
      cw: state.caseWeights
    });
    if (sig !== panelConstructorConfigSig) {
      panelConstructorConfigSig = sig;
      renderChanceRows();
      renderCaseWeightRows();
    }
    renderHistory();
    updateAllChanceHints();
    updateWidgetToggleLabel();
    renderForcedSectorSelect();
  }
  const serverWarnEl = document.getElementById("hybridServerWarn");
  hybridPingObsServer((ok) => {
    if (serverWarnEl) serverWarnEl.hidden = ok;
  });

  function updateWheelChanceHint() {
    if (!wheelChanceHint) return;
    const inputs = chanceRows.querySelectorAll("input[data-wheel-chance]");
    let sum = 0;
    inputs.forEach((inp) => {
      sum += Number(inp.value) || 0;
    });
    if (sum <= 100) {
      wheelChanceHint.textContent = `Σ шансов: ${sum.toFixed(1)}% (осталось ${(100 - sum).toFixed(1)}%)`;
      wheelChanceHint.classList.remove("cstr-wheel-hint--over");
    } else {
      wheelChanceHint.textContent = `Σ шансов: ${sum.toFixed(1)}% — на ${(sum - 100).toFixed(1)}% больше 100%`;
      wheelChanceHint.classList.add("cstr-wheel-hint--over");
    }
  }

  function updateCaseWeightHints() {
    if (!caseWeightRows) return;
    (state.wheelPrizes || []).forEach((p) => {
      const sector = p.name;
      const inputs = caseWeightRows.querySelectorAll(`input[data-case-chance="${sector}"]`);
      let sum = 0;
      inputs.forEach((inp) => {
        sum += Number(inp.value) || 0;
      });
      const rows = caseWeightRows.querySelectorAll(`[data-case-row="${sector}"]`);
      const badge = caseWeightRows.querySelector(`[data-case-hint-badge="${sector}"]`);
      if (!badge) return;
      const n = rows.length;
      badge.textContent = `${n} шт. · ${sum.toFixed(1)}%`;
      badge.classList.toggle("cstr-case-badge--warn", sum > 100);
    });
  }

  function updateAllChanceHints() {
    updateWheelChanceHint();
    updateCaseWeightHints();
  }

  function renderChanceRows() {
    chanceRows.innerHTML = "";
    (state.wheelPrizes || []).forEach((prize, index) => {
      const art = document.createElement("article");
      art.className = "cstr-prize";

      const top = document.createElement("div");
      top.className = "cstr-prize-top";

      const num = document.createElement("span");
      num.className = "cstr-prize-num";
      num.textContent = String(index + 1);

      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.className = "yt-input cstr-inp cstr-inp--name";
      nameInput.dataset.wheelName = String(index);
      nameInput.value = prize.name;
      nameInput.placeholder = "Сектор";
      nameInput.title = "Название сектора";

      const chanceInput = document.createElement("input");
      chanceInput.type = "text";
      chanceInput.className = "yt-input cstr-inp cstr-inp--ch";
      chanceInput.dataset.wheelChance = String(index);
      chanceInput.value = String(prize.chance || 0);
      chanceInput.inputMode = "decimal";
      chanceInput.placeholder = "%";
      chanceInput.title = "Шанс, %";

      const petalsInput = document.createElement("input");
      petalsInput.type = "number";
      petalsInput.className = "yt-input cstr-inp cstr-inp--pet";
      petalsInput.min = "1";
      petalsInput.max = String(WHEEL_PETALS_MAX);
      petalsInput.step = "1";
      petalsInput.dataset.wheelPetals = String(index);
      petalsInput.value = String(normalizePetals(prize));
      petalsInput.title = "Лепестки на диске (вид)";

      const tools = document.createElement("div");
      tools.className = "cstr-prize-tools";

      const iconPreview = document.createElement("img");
      iconPreview.className = "cstr-prize-thumb";
      iconPreview.alt = "";

      const iconInput = document.createElement("input");
      iconInput.type = "text";
      iconInput.className = "yt-input cstr-prize-iconurl";
      iconInput.dataset.wheelIcon = String(index);
      iconInput.value = String(prize.icon || "");
      iconInput.placeholder = "URL или ./assets/icons/…";
      iconInput.title = "Иконка";
      iconPreview.src = migrateLegacyAssetUrl(iconInput.value || DEFAULT_WHEEL_ICON);
      iconInput.addEventListener("input", () => {
        iconPreview.src = migrateLegacyAssetUrl(iconInput.value || DEFAULT_WHEEL_ICON);
      });

      const uploadBtn = document.createElement("button");
      uploadBtn.type = "button";
      uploadBtn.className = "cstr-tool-btn";
      uploadBtn.textContent = "↑";
      uploadBtn.title = "Файл";
      const uploadInput = document.createElement("input");
      uploadInput.type = "file";
      uploadInput.accept = "image/*";
      uploadInput.hidden = true;
      uploadBtn.addEventListener("click", () => uploadInput.click());
      uploadInput.addEventListener("change", (e) => {
        const f = e.target.files && e.target.files[0];
        if (!f) return;
        const rd = new FileReader();
        rd.onload = () => {
          if (typeof rd.result === "string") iconInput.value = rd.result;
          iconPreview.src = migrateLegacyAssetUrl(iconInput.value || DEFAULT_WHEEL_ICON);
        };
        rd.readAsDataURL(f);
        e.target.value = "";
      });

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "cstr-tool-btn cstr-tool-btn--danger";
      delBtn.textContent = "×";
      delBtn.title = "Удалить";
      delBtn.addEventListener("click", () => {
        state = loadState();
        state.wheelPrizes.splice(index, 1);
        if (!state.wheelPrizes.length)
          state.wheelPrizes = [{ id: `pr-${Date.now()}`, name: "ПРИЗ", chance: 100, icon: DEFAULT_WHEEL_ICON, petals: WHEEL_PETALS_DEFAULT }];
        state.caseTables = normalizeCaseTables(state.caseTables, state.wheelPrizes);
        saveState(state);
        state = loadState();
        renderChanceRows();
        renderCaseWeightRows();
        updateAllChanceHints();
      });

      tools.append(iconPreview, uploadBtn, delBtn, uploadInput);
      top.append(num, nameInput, chanceInput, petalsInput, tools);
      art.append(top, iconInput);
      chanceRows.appendChild(art);
    });

    const foot = document.createElement("div");
    foot.className = "cstr-wheel-foot";
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "yt-btn yt-btn--ghost cstr-add-sector";
    addBtn.textContent = "+ Сектор";
    addBtn.addEventListener("click", () => {
      state = loadState();
      const idx = state.wheelPrizes.length + 1;
      state.wheelPrizes.push({
        id: `pr-${Date.now()}`,
        name: `ПРИЗ ${idx}`,
        chance: 10,
        icon: DEFAULT_WHEEL_ICON,
        petals: WHEEL_PETALS_DEFAULT
      });
      state.caseTables = normalizeCaseTables(state.caseTables, state.wheelPrizes);
      saveState(state);
      state = loadState();
      renderChanceRows();
      renderCaseWeightRows();
      updateAllChanceHints();
    });
    foot.appendChild(addBtn);
    chanceRows.appendChild(foot);
    updateWheelChanceHint();
  }

  function collectWheelPrizesFromForm() {
    const nameInputs = Array.from(chanceRows.querySelectorAll("input[data-wheel-name]"));
    const chanceInputs = Array.from(chanceRows.querySelectorAll("input[data-wheel-chance]"));
    const petalsInputs = Array.from(chanceRows.querySelectorAll("input[data-wheel-petals]"));
    const iconInputs = Array.from(chanceRows.querySelectorAll("input[data-wheel-icon]"));
    const out = [];
    for (let i = 0; i < nameInputs.length; i += 1) {
      const name = String(nameInputs[i].value || "").trim();
      if (!name) continue;
      out.push({
        id: `pr-${i}-${Date.now()}`,
        name,
        chance: Number(chanceInputs[i] ? chanceInputs[i].value : 0) || 0,
        icon: migrateLegacyAssetUrl(String(iconInputs[i] ? iconInputs[i].value : "").trim() || DEFAULT_WHEEL_ICON),
        petals: normalizePetals({ petals: petalsInputs[i] ? petalsInputs[i].value : null })
      });
    }
    return normalizeWheelPrizes(out);
  }

  function collectCaseTablesFromForm(prizes) {
    const out = {};
    const names = prizes.map((x) => x.name);
    names.forEach((sector) => {
      const rows = Array.from(caseWeightRows.querySelectorAll(`[data-case-row="${sector}"]`));
      out[sector] = rows
        .map((row) => ({
          value: String(row.querySelector("input[data-case-value]")?.value || "").trim(),
          chance: Number(row.querySelector("input[data-case-chance]")?.value || 0) || 0,
          rarity: String(row.querySelector("select[data-case-rarity]")?.value || "blue")
        }))
        .filter((x) => x.value);
    });
    return normalizeCaseTables(out, prizes);
  }

  function createCaseLine(sector, row) {
    const rowEl = document.createElement("div");
    rowEl.className = "cstr-case-line";
    rowEl.dataset.caseRow = sector;

    const valueInput = document.createElement("input");
    valueInput.type = "text";
    valueInput.className = "yt-input cstr-inp cstr-inp--case-val";
    valueInput.dataset.caseValue = "1";
    valueInput.value = String(row.value != null ? row.value : "");
    valueInput.placeholder = "Текст";

    const chanceInp = document.createElement("input");
    chanceInp.type = "text";
    chanceInp.className = "yt-input cstr-inp cstr-inp--case-pct";
    chanceInp.dataset.caseChance = sector;
    chanceInp.value = String(row.chance != null ? row.chance : 0);
    chanceInp.placeholder = "%";

    const rarity = document.createElement("select");
    rarity.className = "yt-input cstr-sel cstr-sel--rare";
    rarity.dataset.caseRarity = "1";
    RARITY_KEYS.forEach((rk) => {
      const o = document.createElement("option");
      o.value = rk;
      o.textContent = rk;
      if (normalizeRarity(row.rarity) === rk) o.selected = true;
      rarity.appendChild(o);
    });

    const rarityDot = document.createElement("span");
    rarityDot.className = `rarity-dot rarity-dot--${normalizeRarity(row.rarity)}`;
    rarityDot.setAttribute("aria-hidden", "true");

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "cstr-tool-btn cstr-tool-btn--danger";
    delBtn.textContent = "×";
    delBtn.title = "Удалить строку";
    delBtn.addEventListener("click", () => {
      rowEl.remove();
      updateCaseWeightHints();
    });

    rarity.addEventListener("change", () => {
      rarityDot.className = `rarity-dot rarity-dot--${normalizeRarity(rarity.value)}`;
    });

    rowEl.append(valueInput, chanceInp, rarity, rarityDot, delBtn);
    return rowEl;
  }

  function renderCaseWeightRows() {
    caseWeightRows.innerHTML = "";
    (state.wheelPrizes || []).forEach((prize, index) => {
      const sector = prize.name;
      const det = document.createElement("details");
      det.className = "cstr-case";
      if (index === 0) det.open = true;

      const sumEl = document.createElement("summary");
      sumEl.className = "cstr-case-sum";

      const nameSpan = document.createElement("span");
      nameSpan.className = "cstr-case-name";
      nameSpan.textContent = sector;

      const badge = document.createElement("span");
      badge.className = "cstr-case-badge";
      badge.dataset.caseHintBadge = sector;

      const chev = document.createElement("span");
      chev.className = "cstr-case-chev";
      chev.setAttribute("aria-hidden", "true");
      chev.textContent = "▾";

      sumEl.append(nameSpan, badge, chev);

      const body = document.createElement("div");
      body.className = "cstr-case-body";

      const rows = state.caseTables[sector] || [];
      rows.forEach((row) => {
        body.appendChild(createCaseLine(sector, row));
      });

      const addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "yt-btn yt-btn--ghost cstr-case-addline";
      addBtn.textContent = "+ Строка";
      addBtn.addEventListener("click", () => {
        body.insertBefore(createCaseLine(sector, { value: "", chance: 10, rarity: "blue" }), addBtn);
        updateCaseWeightHints();
      });

      body.appendChild(addBtn);
      det.append(sumEl, body);
      caseWeightRows.appendChild(det);
    });
    updateCaseWeightHints();
    bumpPanelConstructorConfigSig();
  }

  function updateWidgetToggleLabel() {
    if (!toggleWidgetBtn) return;
    toggleWidgetBtn.textContent = state.widgetVisible ? "Скрыть виджет" : "Отобразить виджет";
  }

  function renderForcedSectorSelect() {
    const prev = forcedSectorSelect.value;
    forcedSectorSelect.innerHTML = '<option value="">Случайно</option>';
    (state.wheelPrizes || []).forEach((p) => {
      const o = document.createElement("option");
      o.value = p.name;
      o.textContent = p.name;
      forcedSectorSelect.appendChild(o);
    });
    if (prev && Array.from(forcedSectorSelect.options).some((o) => o.value === prev)) forcedSectorSelect.value = prev;
  }

  function syncCardButtons(mode) {
    if (!cardShowBtn || !cardRevealBtn || !cardHideBtn) return;
    if (mode === "idle") {
      cardRevealBtn.disabled = true;
      cardHideBtn.style.display = "none";
      return;
    }
    if (mode === "shown") {
      cardRevealBtn.disabled = false;
      cardHideBtn.style.display = "none";
      return;
    }
    if (mode === "revealed") {
      cardRevealBtn.disabled = true;
      cardHideBtn.style.display = "";
      return;
    }
  }


  function renderHistory() {
    historyList.innerHTML = "";
    if (!state.history.length) {
      const empty = document.createElement("li");
      empty.textContent = "История пока пустая.";
      historyList.appendChild(empty);
      return;
    }
    state.history.forEach((entry) => {
      const li = document.createElement("li");
      li.className = "history-item-card";
      const p = (state.wheelPrizes || []).find((x) => x.name === entry.sector);
      const icon = migrateLegacyAssetUrl(p && p.icon ? p.icon : DEFAULT_WHEEL_ICON);
      const itemLine = formatPrizeDisplay(
        String(entry.item || "-"),
        prizeDisplayModeForSector(entry.sector || "")
      );
      li.innerHTML = `
        <img class="history-icon" src="${icon}" alt="">
        <div class="history-content">
          <div><strong>${entry.sector}</strong> → ${itemLine}</div>
          <div class="history-time">${formatDateTime(entry.time)}</div>
        </div>
      `;
      historyList.appendChild(li);
    });
  }

  function applyChancesToStorage() {
    state = loadState();
    state.wheelPrizes = collectWheelPrizesFromForm();
    state.caseTables = collectCaseTablesFromForm(state.wheelPrizes);
    state.chances = buildChancesFromWheelPrizes(state.wheelPrizes);
    state.caseWeights = normalizeCaseWeights(state.caseWeights);
    hybridDebugLog("panel", "applyChancesToStorage", { chances: state.chances, prizes: state.wheelPrizes.length });
    saveState(state);
    alert("Настройки записаны в браузер и отправлены на сервер.");
  }

  function exportChancesToFile() {
    const wheelPrizes = collectWheelPrizesFromForm();
    const caseTables = collectCaseTablesFromForm(wheelPrizes);
    const payload = {
      version: 2,
      exportedAt: Date.now(),
      wheelPrizes,
      caseTables
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const a = document.createElement("a");
    const url = URL.createObjectURL(blob);
    a.href = url;
    a.download = `roulette-chances-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function importChancesFromFile(file) {
    const reader = new FileReader();
    reader.onload = () => {
      const parsed = safeJsonParse(reader.result);
      if (!parsed || typeof parsed !== "object") {
        alert("Файл не подходит (нужен JSON).");
        return;
      }
      state = loadState();
      if (Array.isArray(parsed.wheelPrizes)) {
        state.wheelPrizes = normalizeWheelPrizes(parsed.wheelPrizes, parsed.chances || {});
      }
      if (parsed.caseTables && typeof parsed.caseTables === "object") {
        state.caseTables = normalizeCaseTables(parsed.caseTables, state.wheelPrizes);
      }
      state.chances = buildChancesFromWheelPrizes(state.wheelPrizes);
      saveState(state);
      state = loadState();
      renderChanceRows();
      renderCaseWeightRows();
      updateAllChanceHints();
      alert("Шансы из файла загружены и применены.");
    };
    reader.readAsText(file, "UTF-8");
  }

  function triggerSpin() {
    const payload = {};
    if (forcedSectorSelect.value) payload.forceSector = forcedSectorSelect.value;
    if (forcedItemInput.value.trim()) payload.forceItem = forcedItemInput.value.trim();
    state = loadState();
    state.wheelPrizes = collectWheelPrizesFromForm();
    state.caseTables = collectCaseTablesFromForm(state.wheelPrizes);
    state.chances = buildChancesFromWheelPrizes(state.wheelPrizes);
    saveState(state);
    sendSpinCommand(payload);
    if (commandChannel) {
      const cmd = safeJsonParse(safeStorageGet(STORAGE_KEYS.command));
      if (cmd) commandChannel.postMessage(cmd);
    }
  }

  function clearHistory() {
    state = loadState();
    state.history = [];
    hybridDebugLog("panel", "clearHistory", null);
    saveState(state, { replaceHistory: true });
    renderHistory();
  }

  function loadPresets() {
    const raw = safeStorageGet(PRESETS_STORAGE_KEY);
    const parsed = raw ? safeJsonParse(raw) : null;
    return Array.isArray(parsed) ? parsed : [];
  }

  function savePresets(list) {
    safeStorageSet(PRESETS_STORAGE_KEY, JSON.stringify(Array.isArray(list) ? list : []));
  }

  function collectCurrentPresetPayload() {
    const wheelPrizes = collectWheelPrizesFromForm();
    const caseTables = collectCaseTablesFromForm(wheelPrizes);
    return { wheelPrizes, caseTables };
  }

  function renderPresetList() {
    if (!presetList) return;
    const presets = loadPresets();
    presetList.innerHTML = "";
    if (!presets.length) {
      const li = document.createElement("li");
      li.textContent = "Пресетов пока нет.";
      presetList.appendChild(li);
      return;
    }
    presets.forEach((p, idx) => {
      const li = document.createElement("li");
      li.innerHTML = `<div><strong>${p.name}</strong></div><div class="history-time">${formatDateTime(p.savedAt)}</div>`;
      const actions = document.createElement("div");
      actions.className = "yt-actions";
      actions.style.marginTop = "8px";
      const applyBtn = document.createElement("button");
      applyBtn.type = "button";
      applyBtn.className = "yt-btn yt-btn--green";
      applyBtn.textContent = "Применить";
      applyBtn.addEventListener("click", () => {
        state = loadState();
        state.wheelPrizes = normalizeWheelPrizes(p.wheelPrizes);
        state.caseTables = normalizeCaseTables(p.caseTables, state.wheelPrizes);
        state.chances = buildChancesFromWheelPrizes(state.wheelPrizes);
        saveState(state);
        state = loadState();
        renderChanceRows();
        renderCaseWeightRows();
        updateAllChanceHints();
        alert("Пресет применен.");
      });
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "yt-btn yt-btn--muted";
      delBtn.textContent = "Удалить";
      delBtn.addEventListener("click", () => {
        const next = loadPresets();
        next.splice(idx, 1);
        savePresets(next);
        renderPresetList();
      });
      actions.appendChild(applyBtn);
      actions.appendChild(delBtn);
      li.appendChild(actions);
      presetList.appendChild(li);
    });
  }

  function switchPanelTab(tab) {
    if (panelViewMain) panelViewMain.hidden = tab !== "panel";
    if (constructorViewMain) constructorViewMain.hidden = tab !== "constructor";
    if (presetsViewMain) presetsViewMain.hidden = tab !== "presets";
    if (tabPanelBtn) tabPanelBtn.className = `panel-tab ${tab === "panel" ? "panel-tab--active" : "panel-tab--ghost"}`;
    if (tabConstructorBtn) tabConstructorBtn.className = `panel-tab ${tab === "constructor" ? "panel-tab--active" : "panel-tab--ghost"}`;
    if (tabPresetsBtn) tabPresetsBtn.className = `panel-tab ${tab === "presets" ? "panel-tab--active" : "panel-tab--ghost"}`;
  }

  chanceRows.addEventListener("input", updateWheelChanceHint);
  caseWeightRows.addEventListener("input", updateCaseWeightHints);

  applyChancesBtn.addEventListener("click", applyChancesToStorage);
  exportChancesBtn.addEventListener("click", exportChancesToFile);
  importChancesBtn.addEventListener("click", () => importChancesFile.click());
  importChancesFile.addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (f) importChancesFromFile(f);
    e.target.value = "";
  });
  spinNowBtn.addEventListener("click", triggerSpin);
  if (toggleWidgetBtn) {
    toggleWidgetBtn.addEventListener("click", () => {
      state = loadState();
      state.widgetVisible = !state.widgetVisible;
      hybridDebugLog("panel", "toggleWidget", { widgetVisible: state.widgetVisible });
      saveState(state);
      state = loadState();
      updateWidgetToggleLabel();
    });
  }
  if (forceResetWheelBtn) {
    forceResetWheelBtn.addEventListener("click", () => {
      sendResetWheelCommand();
    });
  }
  clearHistoryBtn.addEventListener("click", clearHistory);
  cardShowBtn?.addEventListener("click", () => {
    const suit = randomCardSuit();
    const rank = randomCardRank();
    cardRound = { rank, suit: suit.key };
    sendCardCommand("show", {});
    syncCardButtons("shown");
  });
  cardRevealBtn?.addEventListener("click", () => {
    if (!cardRound) return;
    sendCardCommand("reveal", { rank: cardRound.rank, suit: cardRound.suit });
    syncCardButtons("revealed");
  });
  cardHideBtn?.addEventListener("click", () => {
    sendCardCommand("hide", {});
    cardRound = null;
    syncCardButtons("idle");
  });
  tabPanelBtn?.addEventListener("click", () => switchPanelTab("panel"));
  tabConstructorBtn?.addEventListener("click", () => switchPanelTab("constructor"));
  tabPresetsBtn?.addEventListener("click", () => {
    switchPanelTab("presets");
    renderPresetList();
  });
  savePresetBtn?.addEventListener("click", () => {
    const name = String(presetNameInput?.value || "").trim() || `Preset ${new Date().toLocaleTimeString()}`;
    const payload = collectCurrentPresetPayload();
    const presets = loadPresets();
    presets.unshift({ name, savedAt: Date.now(), ...payload });
    savePresets(presets.slice(0, 100));
    if (presetNameInput) presetNameInput.value = "";
    renderPresetList();
  });
  quickSavePresetBtn?.addEventListener("click", () => {
    const name = `Preset ${new Date().toLocaleString()}`;
    const payload = collectCurrentPresetPayload();
    const presets = loadPresets();
    presets.unshift({ name, savedAt: Date.now(), ...payload });
    savePresets(presets.slice(0, 100));
    renderPresetList();
    alert("Пресет сохранен.");
  });
  exportPresetBtn?.addEventListener("click", () => {
    const payload = { version: 2, exportedAt: Date.now(), ...collectCurrentPresetPayload() };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const a = document.createElement("a");
    const url = URL.createObjectURL(blob);
    a.href = url;
    a.download = `roulette-preset-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });
  importPresetBtn?.addEventListener("click", () => importPresetFile?.click());
  importPresetFile?.addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      const parsed = safeJsonParse(reader.result);
      if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.wheelPrizes)) {
        alert("Неверный формат пресета.");
        return;
      }
      const presets = loadPresets();
      presets.unshift({
        name: f.name.replace(/\.json$/i, ""),
        savedAt: Date.now(),
        wheelPrizes: normalizeWheelPrizes(parsed.wheelPrizes),
        caseTables: normalizeCaseTables(parsed.caseTables || {}, normalizeWheelPrizes(parsed.wheelPrizes))
      });
      savePresets(presets.slice(0, 100));
      renderPresetList();
    };
    reader.readAsText(f, "UTF-8");
    e.target.value = "";
  });
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEYS.result || event.key === STORAGE_KEYS.state) {
      refreshPanelAfterStateSync();
    }
  });
  window.addEventListener("obsHybridStateUpdated", () => {
    refreshPanelAfterStateSync();
  });
  setInterval(pollSharedStateFromHttp, 350);

  renderChanceRows();
  renderCaseWeightRows();
  updateAllChanceHints();
  updateWidgetToggleLabel();
  renderForcedSectorSelect();
  renderHistory();
  pollSharedStateFromHttp();
  switchPanelTab("panel");
  syncCardButtons("idle");
  renderPresetList();

  if (HYBRID_DEBUG) {
    const debugPanel = document.getElementById("hybridDebugPanel");
    const debugLogView = document.getElementById("hybridDebugLogView");
    const copyBtn = document.getElementById("hybridDebugCopyBtn");
    const clearBtn = document.getElementById("hybridDebugClearBtn");
    if (debugPanel && debugLogView) {
      debugPanel.hidden = false;
      hybridDebugLog("panel", "initPanelPage", { apiBase: getHybridApiBase() || "(same-origin)" });
      function refreshDebugView() {
        debugLogView.value = typeof window.hybridExportDebugLog === "function" ? window.hybridExportDebugLog() : "";
        debugLogView.scrollTop = debugLogView.scrollHeight;
      }
      window.setInterval(refreshDebugView, 400);
      copyBtn?.addEventListener("click", () => {
        const t = window.hybridExportDebugLog();
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(t).catch(() => {});
        } else {
          debugLogView.focus();
          debugLogView.select();
          document.execCommand("copy");
        }
      });
      clearBtn?.addEventListener("click", () => {
        window.__OBS_HYBRID_LOGS = [];
        refreshDebugView();
      });
      refreshDebugView();
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const pageType = document.body.getAttribute("data-page");
  if (pageType === "wheel") initWheelPage();
  if (pageType === "cards") initCardsPage();
  if (pageType === "panel") initPanelPage();
});
