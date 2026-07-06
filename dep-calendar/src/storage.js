const USE_API =
  typeof window !== "undefined" && window.__DEP_CAL_API__ === true;

async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    throw new Error("HTTP " + res.status);
  }
  return res.json();
}

/** @typedef {{ deposit: number; withdraw: number; fix: number; notes?: string; noStream?: boolean }} DayRecord */

export function dayNet(r) {
  const d = Number(r.deposit) || 0;
  const w = Number(r.withdraw) || 0;
  const f = Number(r.fix) || 0;
  return w + f - d;
}

export function dayNetNoFix(r) {
  const d = Number(r.deposit) || 0;
  const w = Number(r.withdraw) || 0;
  return w - d;
}

export function hasData(r) {
  if (!r) return false;
  if (r.noStream) return true;
  return (
    (Number(r.deposit) || 0) !== 0 ||
    (Number(r.withdraw) || 0) !== 0 ||
    (Number(r.fix) || 0) !== 0 ||
    !!(r.notes && String(r.notes).trim())
  );
}

/** @returns {Promise<Record<string, DayRecord>>} */
export async function loadAll() {
  if (USE_API) {
    try {
      const data = await apiFetch("/api/calendar/records");
      return data.records && typeof data.records === "object" ? data.records : {};
    } catch (_) {
      return {};
    }
  }
  try {
    const raw = localStorage.getItem("dep-calendar-finance-v1");
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
  } catch (_) {}
  return {};
}

/** @param {Record<string, DayRecord>} data */
export async function saveAll(data) {
  if (USE_API) {
    await apiFetch("/api/calendar/records", {
      method: "PUT",
      body: JSON.stringify({ records: data }),
    });
    return;
  }
  localStorage.setItem("dep-calendar-finance-v1", JSON.stringify(data));
}

export function exportJson(data) {
  return JSON.stringify(
    { version: 1, exportedAt: new Date().toISOString(), records: data },
    null,
    2
  );
}

/** @returns {{ ok: true; data: Record<string, DayRecord> } | { ok: false; error: string }} */
export function importJson(text) {
  try {
    const o = JSON.parse(text);
    if (o && typeof o === "object" && o.records && typeof o.records === "object") {
      return { ok: true, data: normalizeRecords(o.records) };
    }
    if (o && typeof o === "object" && !o.records) {
      return { ok: true, data: normalizeRecords(o) };
    }
    return { ok: false, error: "Неверный формат файла" };
  } catch (e) {
    return { ok: false, error: String(e?.message ?? e) };
  }
}

/** @param {Record<string, unknown>} raw */
function normalizeRecords(raw) {
  /** @type {Record<string, DayRecord>} */
  const out = {};
  for (const [k, v] of Object.entries(raw)) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(k)) continue;
    if (!v || typeof v !== "object") continue;
    const deposit = Number(v.deposit) || 0;
    const withdraw = Number(v.withdraw) || 0;
    const fix = Number(v.fix) || 0;
    const notes = typeof v.notes === "string" ? v.notes : "";
    const noStream = Boolean(v.noStream);
    out[k] = { deposit, withdraw, fix, notes, noStream };
  }
  return out;
}
