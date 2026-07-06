import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { toPng } from "html-to-image";
import "./App.css";
import { grainLayerProps } from "./grain.js";
import {
  dayNet,
  dayNetNoFix,
  exportJson,
  hasData,
  importJson,
  loadAll,
  saveAll,
} from "./storage.js";
import {
  formatNetLineFullRub,
  formatRub,
  formatRubCompactK,
} from "./formatMoney.js";
import { buildTelegramPost } from "./telegramExport.js";

const DOW_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const MONTH_SHORT = [
  "янв",
  "фев",
  "мар",
  "апр",
  "май",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
];

function pad2(n) {
  return String(n).padStart(2, "0");
}

function toKey(y, m, d) {
  return `${y}-${pad2(m)}-${pad2(d)}`;
}

function parseISODate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s).trim());
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (!y || mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  const dt = new Date(y, mo - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d)
    return null;
  return { y, m: mo, d };
}

/**
 * @typedef {{ cy: number; cm: number; cd: number; inMonth: boolean }} CalendarCell
 * @param {string} monthKey YYYY-MM
 */
function monthMatrix(monthKey) {
  const [ys, ms] = monthKey.split("-");
  const y = Number(ys);
  const m = Number(ms);
  const first = new Date(y, m - 1, 1);
  const startDow = (first.getDay() + 6) % 7;
  const daysInMonth = new Date(y, m, 0).getDate();
  /** @type {CalendarCell[]} */
  const cells = [];
  const prevLast = new Date(y, m - 1, 0);
  const pY = prevLast.getFullYear();
  const pM = prevLast.getMonth() + 1;
  const pDom = prevLast.getDate();
  for (let i = 0; i < startDow; i++) {
    const cd = pDom - startDow + i + 1;
    cells.push({ cy: pY, cm: pM, cd, inMonth: false });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ cy: y, cm: m, cd: d, inMonth: true });
  }
  let ty = y;
  let tm = m + 1;
  if (tm > 12) {
    tm = 1;
    ty += 1;
  }
  let nDay = 1;
  while (cells.length % 7 !== 0) {
    cells.push({ cy: ty, cm: tm, cd: nDay, inMonth: false });
    nDay += 1;
  }
  return { y, m, cells, daysInMonth };
}

function monthLabel(monthKey) {
  const [y, m] = monthKey.split("-").map(Number);
  const names = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
  ];
  return `${names[m - 1]} ${y}`;
}

const money = formatRub;
const moneyK = formatRubCompactK;

function dataUrlToBase64(dataUrl) {
  const i = dataUrl.indexOf("base64,");
  if (i === -1) {
    const comma = dataUrl.indexOf(",");
    return comma === -1 ? "" : dataUrl.slice(comma + 1);
  }
  return dataUrl.slice(i + "base64,".length);
}

function parseMoneyInput(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return 0;
  const normalized = raw
    .replace(/\s+/g, "")
    .replace(",", ".")
    .replace(/[^\d.-]/g, "");
  const num = Number(normalized);
  if (!Number.isFinite(num)) return 0;
  return Math.max(0, num);
}

function aggregateMonth(monthKey, records) {
  const { y, m, daysInMonth } = monthMatrix(monthKey);
  let dep = 0;
  let w = 0;
  let fix = 0;
  let net = 0;
  let netNoFix = 0;
  for (let d = 1; d <= daysInMonth; d++) {
    const key = toKey(y, m, d);
    const r = records[key];
    if (!r || !hasData(r) || r.noStream) continue;
    dep += Number(r.deposit) || 0;
    w += Number(r.withdraw) || 0;
    fix += Number(r.fix) || 0;
    net += dayNet(r);
    netNoFix += dayNetNoFix(r);
  }
  const pct = dep > 0 ? (net / dep) * 100 : null;
  const pctNoFix = dep > 0 ? (netNoFix / dep) * 100 : null;
  return { dep, w, fix, net, netNoFix, pct, pctNoFix };
}

function aggregateAll(records) {
  let dep = 0;
  let w = 0;
  let fix = 0;
  let net = 0;
  let netNoFix = 0;
  for (const r of Object.values(records)) {
    if (!hasData(r) || r.noStream) continue;
    dep += Number(r.deposit) || 0;
    w += Number(r.withdraw) || 0;
    fix += Number(r.fix) || 0;
    net += dayNet(r);
    netNoFix += dayNetNoFix(r);
  }
  const pct = dep > 0 ? (net / dep) * 100 : null;
  const pctNoFix = dep > 0 ? (netNoFix / dep) * 100 : null;
  return { dep, w, fix, net, netNoFix, pct, pctNoFix };
}

/** Последний календарный день месяца, который уже «наступил» (для графика). */
function lastPastDayInMonth(monthKey) {
  const { daysInMonth } = monthMatrix(monthKey);
  const t = new Date();
  const cur = `${t.getFullYear()}-${pad2(t.getMonth() + 1)}`;
  if (monthKey.localeCompare(cur) > 0) return 0;
  if (monthKey === cur) return Math.min(daysInMonth, t.getDate());
  return daysInMonth;
}

function niceYStep(span, targetSteps) {
  const raw = span / Math.max(1, targetSteps);
  const p = 10 ** Math.floor(Math.log10(Math.max(Math.abs(raw), 1e-9)));
  const f = raw / p;
  const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
  return nf * p;
}

function yTickList(minV, maxV) {
  const span = maxV - minV;
  if (span <= 0) return [minV];
  const step = niceYStep(span, 4);
  const start = Math.floor(minV / step) * step;
  const ticks = [];
  for (let v = start; v <= maxV + step * 1e-6; v += step) {
    ticks.push(v);
    if (ticks.length > 8) break;
  }
  if (ticks.length === 0) return [minV, maxV];
  return ticks;
}

const PMT_GLOW_GREEN =
  "drop-shadow(0 0 7px rgba(45, 212, 191, 0.55)) drop-shadow(0 0 14px rgba(16, 185, 129, 0.25))";
const PMT_GLOW_RED =
  "drop-shadow(0 0 8px rgba(220, 38, 38, 0.55)) drop-shadow(0 0 16px rgba(127, 29, 29, 0.35))";
const PMT_GLOW_NEUTRAL =
  "drop-shadow(0 0 5px rgba(15, 23, 42, 0.92)) drop-shadow(0 0 12px rgba(148, 163, 184, 0.28))";
const PMT_GLOW_ZERO =
  "drop-shadow(0 0 5px rgba(148, 163, 184, 0.35))";

/**
 * Свечение линии: только по знаку итога (не по позиции внутри min…max —
 * иначе «менее минусовой» финал давал бы зелёное свечение при красном графике).
 */
function chartLineGlowFilterForPath(lastCum, _minV, _maxV, cums) {
  const cumMin = Math.min(...cums);
  if (cumMin < 0 && lastCum > 0) {
    return PMT_GLOW_NEUTRAL;
  }
  if (lastCum > 0) return PMT_GLOW_GREEN;
  if (lastCum < 0) return PMT_GLOW_RED;
  return PMT_GLOW_ZERO;
}

/**
 * Вертикальный градиент области: зелёный сверху (плюс) → бордо снизу (минус),
 * плавная зона вокруг нуля по положению zeroY на холсте.
 */
function chartAreaGradientStops(tzNorm) {
  const z = Math.min(0.93, Math.max(0.07, tzNorm));
  const band = 0.09;
  const raw = [
    { off: 0, color: "rgba(5, 150, 105, 0.46)" },
    { off: Math.max(0, z - band * 2.5), color: "rgba(16, 185, 129, 0.36)" },
    { off: Math.max(0, z - band * 1.1), color: "rgba(110, 231, 183, 0.2)" },
    { off: z, color: "rgba(148, 163, 184, 0.14)" },
    { off: Math.min(1, z + band * 1.1), color: "rgba(251, 113, 133, 0.23)" },
    { off: Math.min(1, z + band * 2.5), color: "rgba(185, 28, 28, 0.38)" },
    { off: 1, color: "rgba(50, 6, 16, 0.58)" },
  ];
  const out = [];
  let prev = -0.001;
  for (const s of raw) {
    const o = Math.min(1, Math.max(0, s.off));
    if (o >= prev + 0.002) {
      out.push({
        offset: `${(o * 100).toFixed(2)}%`,
        color: s.color,
      });
      prev = o;
    }
  }
  return out;
}

/** Та же карта «плюс сверху / минус снизу», непрозрачные цвета — для обводки линии. */
function chartLineGradientStops(tzNorm) {
  const z = Math.min(0.93, Math.max(0.07, tzNorm));
  const band = 0.09;
  const raw = [
    { off: 0, color: "#047857" },
    { off: Math.max(0, z - band * 2.5), color: "#059669" },
    { off: Math.max(0, z - band * 1.1), color: "#34d399" },
    { off: z, color: "#94a3b8" },
    { off: Math.min(1, z + band * 1.1), color: "#f87171" },
    { off: Math.min(1, z + band * 2.5), color: "#dc2626" },
    { off: 1, color: "#450a0a" },
  ];
  const out = [];
  let prev = -0.001;
  for (const s of raw) {
    const o = Math.min(1, Math.max(0, s.off));
    if (o >= prev + 0.002) {
      out.push({
        offset: `${(o * 100).toFixed(2)}%`,
        color: s.color,
      });
      prev = o;
    }
  }
  return out;
}

/** Кумулятив с фиксой по дням (noStream / без данных — шаг 0; будущие дни не включаем). */
function buildPosterMonthChartModel(monthKey, records) {
  const { y, m, daysInMonth } = monthMatrix(monthKey);
  const lastD = lastPastDayInMonth(monthKey);
  const monthShort = MONTH_SHORT[m - 1];

  if (lastD <= 0) {
    return {
      empty: true,
      emptyReason: "future",
      monthShort,
      w: 440,
      h: 144,
    };
  }

  const cums = [];
  let cum = 0;
  for (let d = 1; d <= lastD; d++) {
    const key = toKey(y, m, d);
    const r = records[key];
    if (r && hasData(r) && !r.noStream) cum += dayNet(r);
    cums.push(cum);
  }
  const n = cums.length;

  const w = 440;
  const h = 144;
  const gutter = 48;
  const padT = 10;
  const padB = 34;
  const plotLeft = gutter;
  const plotRight = w - gutter;
  const innerW = plotRight - plotLeft;
  const plotH = h - padT - padB;

  const pointCount = n + 1; // day 0 + all calendar days
  const xPoint = (i) =>
    plotLeft + (pointCount <= 1 ? innerW / 2 : (i / (pointCount - 1)) * innerW);
  const xs = (i) => xPoint(i + 1); // day i is plotted after day 0

  let minV = Math.min(0, ...cums);
  let maxV = Math.max(0, ...cums);
  if (Math.abs(maxV - minV) < 1e-9) {
    maxV = minV + 1;
  }
  const span = maxV - minV;
  const yScale = (v) => padT + (1 - (v - minV) / span) * plotH;
  const yTicks = yTickList(minV, maxV);

  let lineD = `M ${xPoint(0)} ${yScale(0)}`;
  for (let i = 0; i < n; i++) {
    const xi = xs(i);
    const yi = yScale(cums[i]);
    lineD += ` L ${xi} ${yi}`;
  }
  const bottomY = h - padB;
  const areaD = `${lineD} L ${xs(n - 1)} ${bottomY} L ${xPoint(0)} ${bottomY} Z`;
  const zeroY = yScale(0);
  const showZero = minV < 0 && maxV > 0;
  const lastCum = cums[n - 1] ?? 0;
  const tickDays = [
    ...new Set([1, 5, 10, 15, 20, 25, 30, n].filter((d) => d >= 1 && d <= n)),
  ].sort((a, b) => a - b);
  const xTickLabels = tickDays.map((d) => ({
    day: d,
    label: `${d} ${monthShort}`,
  }));

  const gradLen = bottomY - padT;
  const tzNorm = gradLen > 1e-6 ? (zeroY - padT) / gradLen : 0.5;
  const areaGradStops = chartAreaGradientStops(tzNorm);
  const lineGradStops = chartLineGradientStops(tzNorm);
  const lineGlowFilter = chartLineGlowFilterForPath(lastCum, minV, maxV, cums);

  return {
    empty: false,
    w,
    h,
    lineD,
    areaD,
    zeroY,
    showZero,
    lastCum,
    tickDays,
    xTickLabels,
    n,
    xs,
    plotLeft,
    plotRight,
    padT,
    bottomY,
    yTicks,
    yScale,
    minV,
    maxV,
    lastShownDay: lastD,
    monthShort,
    areaGradStops,
    lineGradStops,
    lineGlowFilter,
  };
}

function PosterMonthNetChart({ monthKey, records }) {
  const uid = useId().replace(/:/g, "");
  const model = useMemo(
    () => buildPosterMonthChartModel(monthKey, records),
    [monthKey, records]
  );

  if (model.empty) {
    return (
      <div
        className="pmt-chart pmt-chart--empty"
        aria-label="График: месяц ещё не наступил"
      />
    );
  }

  const gradId = `${uid}-pmt-area`;
  const lineGradId = `${uid}-pmt-line`;
  const {
    w,
    h,
    lineD,
    areaD,
    zeroY,
    showZero,
    tickDays,
    xTickLabels,
    xs,
    plotLeft,
    plotRight,
    padT,
    bottomY,
    yTicks,
    yScale,
    lastShownDay,
    monthShort,
    areaGradStops,
    lineGradStops,
    lineGlowFilter,
  } = model;

  const diagPatId = `${uid}-diag`;
  const plotClipId = `${uid}-plotclip`;

  return (
    <div
      className="pmt-chart pmt-chart--valence"
      aria-label={`Кумулятив с фиксой по дням до ${lastShownDay} ${monthShort}`}
    >
      <div className="pmt-chart__grain" aria-hidden />
      <svg
        className="pmt-chart__svg"
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        aria-hidden
      >
        <defs>
          <pattern
            id={diagPatId}
            width="5"
            height="5"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(-32)"
          >
            <line
              x1="0"
              y1="5"
              x2="5"
              y2="0"
              stroke="rgba(255, 255, 255, 0.055)"
              strokeWidth="0.85"
              strokeLinecap="round"
            />
          </pattern>
          <clipPath id={plotClipId}>
            <rect
              x={plotLeft}
              y={padT}
              width={plotRight - plotLeft}
              height={bottomY - padT}
            />
          </clipPath>
          <linearGradient
            id={gradId}
            gradientUnits="userSpaceOnUse"
            x1="0"
            y1={padT}
            x2="0"
            y2={bottomY}
          >
            {areaGradStops.map((s, i) => (
              <stop key={i} offset={s.offset} stopColor={s.color} />
            ))}
          </linearGradient>
          <linearGradient
            id={lineGradId}
            gradientUnits="userSpaceOnUse"
            x1="0"
            y1={padT}
            x2="0"
            y2={bottomY}
          >
            {lineGradStops.map((s, i) => (
              <stop key={`ln-${i}`} offset={s.offset} stopColor={s.color} />
            ))}
          </linearGradient>
        </defs>
        <g clipPath={`url(#${plotClipId})`}>
          <rect
            x={plotLeft}
            y={padT}
            width={plotRight - plotLeft}
            height={bottomY - padT}
            fill={`url(#${diagPatId})`}
            opacity={0.85}
          />
        </g>
        {yTicks.map((yv) => {
          const yy = yScale(yv);
          return (
            <g key={`yh-${yv}`}>
              <line
                x1={plotLeft}
                y1={yy}
                x2={plotRight}
                y2={yy}
                className="pmt-chart__grid-h"
              />
              <text
                x={plotLeft - 8}
                y={yy}
                textAnchor="end"
                dominantBaseline="middle"
                className="pmt-chart__y-label"
                fill="#f8fafc"
              >
                {moneyK(yv)}
              </text>
            </g>
          );
        })}
        {tickDays.map((d) => {
          const i = d - 1;
          const x = xs(i);
          return (
            <line
              key={d}
              x1={x}
              y1={padT}
              x2={x}
              y2={bottomY}
              className="pmt-chart__grid-v"
            />
          );
        })}
        {showZero && (
          <line
            x1={plotLeft}
            y1={zeroY}
            x2={plotRight}
            y2={zeroY}
            className="pmt-chart__zero"
          />
        )}
        <path d={areaD} fill={`url(#${gradId})`} className="pmt-chart__area" />
        <path
          d={lineD}
          fill="none"
          stroke={`url(#${lineGradId})`}
          strokeWidth="2.35"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="pmt-chart__line"
          style={{ filter: lineGlowFilter }}
        />
        {xTickLabels.map(({ day, label }) => {
          const x = xs(day - 1);
          return (
            <text
              key={`t-${day}`}
              x={x}
              y={h - 9}
              textAnchor="middle"
              className="pmt-chart__tick"
              fill="#f8fafc"
            >
              {label}
            </text>
          );
        })}
      </svg>
    </div>
  );
}

async function copyText(text) {
  if (typeof window !== "undefined" && window.electronAPI?.writeClipboard) {
    await window.electronAPI.writeClipboard(text);
    return;
  }
  await navigator.clipboard.writeText(text);
}

export default function App() {
  const now = new Date();
  const initialMonth = `${now.getFullYear()}-${pad2(now.getMonth() + 1)}`;

  const [records, setRecords] = useState({});
  const [recordsReady, setRecordsReady] = useState(false);
  const [monthKey, setMonthKey] = useState(initialMonth);
  const [selected, setSelected] = useState(() =>
    toKey(now.getFullYear(), now.getMonth() + 1, now.getDate())
  );
  const [search, setSearch] = useState("");
  const [toast, setToast] = useState("");
  const [exporting, setExporting] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const isMac =
    typeof navigator !== "undefined" &&
    /mac|iphone|ipad|ipod/i.test(navigator.platform || "");
  const [exportAspect, setExportAspect] = useState(() => {
    try {
      const v = localStorage.getItem("dep-cal-export-aspect");
      if (v === "square" || v === "portrait34") return v;
    } catch (_) {}
    return "square";
  });
  const exportCaptureRef = useRef(null);
  const exportScalerRef = useRef(null);
  const exportPosterRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    loadAll().then((data) => {
      if (!cancelled) {
        setRecords(data);
        setRecordsReady(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!recordsReady) return;
    void saveAll(records);
  }, [records, recordsReady]);

  useEffect(() => {
    try {
      localStorage.setItem("dep-cal-export-aspect", exportAspect);
    } catch (_) {}
  }, [exportAspect]);

  const showToast = useCallback((msg) => {
    setToast(msg);
    setTimeout(() => setToast(""), 2200);
  }, []);

  const { y, m, cells } = useMemo(() => monthMatrix(monthKey), [monthKey]);

  const todayKeyStr = toKey(
    new Date().getFullYear(),
    new Date().getMonth() + 1,
    new Date().getDate()
  );

  const filteredKeys = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return null;
    return Object.keys(records).filter((k) => {
      if (!hasData(records[k])) return false;
      if (k.includes(q)) return true;
      const n = (records[k].notes || "").toLowerCase();
      return n.includes(q);
    });
  }, [search, records]);

  const monthStats = useMemo(
    () => aggregateMonth(monthKey, records),
    [monthKey, records]
  );
  const allStats = useMemo(() => aggregateAll(records), [records]);

  const selectedRecord = records[selected] || {
    deposit: 0,
    withdraw: 0,
    fix: 0,
    notes: "",
    noStream: false,
  };

  const setField = (field, value) => {
    setRecords((prev) => {
      const next = { ...prev };
      const cur = { ...(next[selected] || {}) };
      if (field === "notes") cur.notes = value;
      else if (field === "noStream") cur.noStream = Boolean(value);
      else cur[field] = parseMoneyInput(value);
      next[selected] = {
        deposit: Number(cur.deposit) || 0,
        withdraw: Number(cur.withdraw) || 0,
        fix: Number(cur.fix) || 0,
        notes: cur.notes ?? "",
        noStream: !!cur.noStream,
      };
      return next;
    });
  };

  const clearDay = () => {
    setRecords((prev) => {
      const next = { ...prev };
      delete next[selected];
      return next;
    });
    showToast("Запись удалена");
  };

  const shiftMonth = (delta) => {
    const d = new Date(y, m - 1 + delta, 1);
    setMonthKey(`${d.getFullYear()}-${pad2(d.getMonth() + 1)}`);
  };

  const onExportTG = async () => {
    const text = buildTelegramPost(monthKey, records);
    try {
      await copyText(text);
      showToast("Пост скопирован в буфер обмена");
    } catch {
      showToast("Не удалось скопировать");
    }
  };

  const capturePosterDataUrl = useCallback(async () => {
    const host = exportCaptureRef.current;
    const scaler = exportScalerRef.current;
    const poster = exportPosterRef.current;
    if (!host || !scaler || !poster) throw new Error("Нет области для снимка");

    if (document.fonts?.ready) {
      try {
        await document.fonts.ready;
      } catch (_) {}
    }
    await new Promise((r) =>
      requestAnimationFrame(() => requestAnimationFrame(r))
    );

    const TW = exportAspect === "square" ? 1080 : 900;
    const TH = exportAspect === "square" ? 1080 : 1200;
    const pad = 44;

    const snapHost = host.style.cssText;
    const snapScaler = scaler.style.cssText;
    const snapPoster = poster.style.cssText;

    const opts = {
      pixelRatio: 2,
      cacheBust: true,
      backgroundColor: "#0c0e12",
    };

    const hideGrains = () => {
      /** @type {HTMLElement[]} */
      const nodes = [...host.querySelectorAll(".day-card__grain")].map(
        (n) => /** @type {HTMLElement} */ (n)
      );
      const grainSnap = nodes.map((n) => n.style.cssText);
      nodes.forEach((n) => {
        n.style.cssText =
          "display:none !important;visibility:hidden !important;";
      });
      return () => {
        nodes.forEach((n, i) => {
          n.style.cssText = grainSnap[i] ?? "";
        });
      };
    };

    const runPng = () => toPng(host, opts);

    try {
      host.style.cssText = `${snapHost};width:${TW}px;height:${TH}px;max-width:none;margin:0 auto;box-sizing:border-box;padding:${pad}px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#0c0e12`;
      poster.style.cssText = `${snapPoster};width:920px;max-width:none;margin:0;display:block`;
      scaler.style.cssText = `${snapScaler};flex-shrink:0`;

      await new Promise((r) => requestAnimationFrame(r));
      const W = poster.offsetWidth;
      const H = poster.offsetHeight;
      const aw = TW - pad * 2;
      const ah = TH - pad * 2;
      const s = Math.min(aw / W, ah / H, 1);
      scaler.style.width = `${W * s}px`;
      scaler.style.height = `${H * s}px`;
      scaler.style.overflow = "hidden";
      scaler.style.position = "relative";
      poster.style.height = `${H}px`;
      poster.style.transform = `scale(${s})`;
      poster.style.transformOrigin = "top left";

      await new Promise((r) => requestAnimationFrame(r));

      try {
        return await runPng();
      } catch (first) {
        console.warn(
          "toPng: первая попытка не удалась, повтор без слоя зерна",
          first
        );
        const restoreGrain = hideGrains();
        try {
          return await runPng();
        } finally {
          restoreGrain();
        }
      }
    } finally {
      host.style.cssText = snapHost;
      scaler.style.cssText = snapScaler;
      poster.style.cssText = snapPoster;
    }
  }, [exportAspect]);

  const onShowPosterImage = async () => {
    setExporting(true);
    try {
      const dataUrl = await capturePosterDataUrl();
      setPreviewUrl(dataUrl);
    } catch (e) {
      console.error(e);
      showToast(
        "Не удалось создать картинку. Если открыта консоль разработчика — пришлите текст ошибки."
      );
    } finally {
      setExporting(false);
    }
  };

  const onExportPng = async () => {
    setExporting(true);
    try {
      const dataUrl = await capturePosterDataUrl();
      const base64 = dataUrlToBase64(dataUrl);
      const fname = `dep-calendar-${monthKey}.png`;
      if (window.electronAPI?.savePngDialog) {
        const res = await window.electronAPI.savePngDialog({
          defaultPath: fname,
          base64,
        });
        if (res?.ok) showToast("Картинка сохранена");
        else if (res?.error) showToast("Ошибка: " + res.error);
        else showToast("Отменено");
      } else {
        const a = document.createElement("a");
        a.href = dataUrl;
        a.download = fname;
        a.click();
        showToast("Файл скачан");
      }
    } catch (e) {
      console.error(e);
      showToast(
        "Не удалось сохранить PNG. Попробуйте «Показать картинку» или откройте консоль (View → Toggle Developer Tools)."
      );
    } finally {
      setExporting(false);
    }
  };

  const onSaveBackup = async () => {
    const json = exportJson(records);
    if (window.electronAPI?.saveBackupDialog) {
      const res = await window.electronAPI.saveBackupDialog(json);
      if (res?.ok) showToast("Резервная копия сохранена");
      else if (!res?.ok && res?.error) showToast("Ошибка: " + res.error);
      else showToast("Отменено");
    } else {
      try {
        await copyText(json);
        showToast("JSON скопирован (режим браузера)");
      } catch {
        showToast("Не удалось экспортировать");
      }
    }
  };

  const onLoadBackup = async () => {
    if (window.electronAPI?.loadBackupDialog) {
      const res = await window.electronAPI.loadBackupDialog();
      if (!res?.ok) {
        if (res?.error) showToast("Ошибка: " + res.error);
        return;
      }
      const imp = importJson(res.text);
      if (!imp.ok) {
        showToast(imp.error);
        return;
      }
      if (!confirm("Заменить все текущие данные данными из файла?")) return;
      setRecords(imp.data);
      showToast("Данные восстановлены");
    } else {
      const t = prompt("Вставьте JSON резервной копии:");
      if (!t) return;
      const imp = importJson(t);
      if (!imp.ok) {
        showToast(imp.error);
        return;
      }
      if (!confirm("Заменить все текущие данные?")) return;
      setRecords(imp.data);
      showToast("Данные восстановлены");
    }
  };

  const jumpToSearchFirst = () => {
    if (!search.trim()) {
      showToast("Введите дату или текст заметки");
      return;
    }
    if (!filteredKeys?.length) {
      showToast("Ничего не найдено");
      return;
    }
    const k = [...filteredKeys].sort()[0];
    const p = parseISODate(k);
    if (!p) return;
    setMonthKey(`${p.y}-${pad2(p.m)}`);
    setSelected(k);
  };

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1 className="app-title">Dep Calendar</h1>
          <p className="app-sub">Депозиты, выводы и фикса — по дням</p>
        </div>
        <div className="toolbar">
          <input
            className="search"
            type="search"
            placeholder="Поиск: 2026-04 или заметка"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") jumpToSearchFirst();
            }}
          />
          <button type="button" className="btn" onClick={jumpToSearchFirst}>
            Найти день
          </button>
          <button type="button" className="btn" onClick={onSaveBackup}>
            Сохранить бэкап
          </button>
          <button type="button" className="btn" onClick={onLoadBackup}>
            Загрузить бэкап
          </button>
        </div>
      </header>

      <div className="layout">
        <div className="card">
          <div className="month-nav">
            <button type="button" className="btn" onClick={() => shiftMonth(-1)}>
              ←
            </button>
            <span className="month-label">{monthLabel(monthKey)}</span>
            <button type="button" className="btn" onClick={() => shiftMonth(1)}>
              →
            </button>
            <span className="month-nav__spacer" aria-hidden />
            <button
              type="button"
              className="btn btn-primary month-export-btn"
              onClick={onShowPosterImage}
              disabled={exporting}
            >
              {exporting ? "…" : "Показать картинку"}
            </button>
            <button
              type="button"
              className="btn month-export-btn"
              onClick={onExportPng}
              disabled={exporting}
            >
              Сохранить PNG
            </button>
          </div>

          <div className="export-format" role="group" aria-label="Формат картинки">
            <span className="export-format-label">Формат PNG</span>
            <button
              type="button"
              className={`btn btn-aspect${exportAspect === "square" ? " btn-aspect--on" : ""}`}
              onClick={() => setExportAspect("square")}
            >
              1∶1
            </button>
            <button
              type="button"
              className={`btn btn-aspect${exportAspect === "portrait34" ? " btn-aspect--on" : ""}`}
              onClick={() => setExportAspect("portrait34")}
            >
              3∶4
            </button>
          </div>

          <div ref={exportCaptureRef} className="export-capture-host">
            <div ref={exportScalerRef} className="export-capture-scaler">
              <div ref={exportPosterRef} className="month-poster-surface">
            <div className="poster-hero">
              <div className="poster-hero__kicker">Dep Calendar</div>
              <h2 className="poster-hero__title">{monthLabel(monthKey)}</h2>
            </div>

            <div className="day-cards-grid day-cards-grid--week">
              {DOW_SHORT.map((d) => (
                <div key={d} className="day-cards-dow">
                  {d}
                </div>
              ))}
              {cells.map((cell, i) => {
                const cellKey = toKey(cell.cy, cell.cm, cell.cd);
                if (!cell.inMonth) {
                  const gk = grainLayerProps(`pad-${cellKey}-${i}`);
                  return (
                    <div
                      key={`other-${i}-${cellKey}`}
                      className="day-card day-card--empty day-card--othermonth"
                      aria-label={`Дата вне месяца: ${cell.cd} ${MONTH_SHORT[cell.cm - 1]}`}
                    >
                      <span className="day-card__grain" aria-hidden style={gk} />
                      <span className="day-card__glow" aria-hidden />
                      <div className="day-card__body">
                        <div className="day-card__header">
                          <span className="day-card__badge" aria-hidden>
                            <span className="day-card__badge-num">{cell.cd}</span>
                            <span className="day-card__badge-month">
                              {MONTH_SHORT[cell.cm - 1]}
                            </span>
                          </span>
                        </div>
                        <div className="day-card__sheet">
                          <span
                            className="day-card__future-watermark day-card__future-watermark--cross"
                            aria-hidden
                          >
                            ×
                          </span>
                        </div>
                        <div className="day-card__footer" aria-hidden />
                      </div>
                    </div>
                  );
                }

                const key = cellKey;
                const r = records[key];
                const hd = !!(r && hasData(r));
                const noStreamDay = !!(r && r.noStream);
                const countInTotals = hd && !noStreamDay;
                const net = countInTotals && r ? dayNet(r) : 0;
                const dep = r ? Number(r.deposit) || 0 : 0;
                const wv = r ? Number(r.withdraw) || 0 : 0;
                const fx = r ? Number(r.fix) || 0 : 0;
                const isFutureDay = key > todayKeyStr;

                let tone = "day-card--empty";
                if (noStreamDay) tone = "day-card--nostream";
                else if (countInTotals && r) {
                  if (net > 0) tone = "day-card--profit";
                  else if (net < 0) tone = "day-card--loss";
                  else tone = "day-card--flat";
                }

                const grain = grainLayerProps(key);

                return (
                  <button
                    key={key}
                    type="button"
                    className={`day-card ${tone}${key === selected ? " day-card--selected" : ""}${isFutureDay ? " day-card--future" : ""}`}
                    onClick={() => setSelected(key)}
                  >
                    <span
                      className="day-card__grain"
                      aria-hidden
                      style={grain}
                    />
                    <span className="day-card__glow" aria-hidden />
                    <div className="day-card__body">
                      <div className="day-card__header">
                        <span className="day-card__badge" aria-hidden>
                          <span className="day-card__badge-num">{cell.cd}</span>
                          <span className="day-card__badge-month">
                            {MONTH_SHORT[cell.cm - 1]}
                          </span>
                        </span>
                      </div>
                      <div className="day-card__sheet">
                        {noStreamDay && (
                          <span
                            className="day-card__future-watermark day-card__future-watermark--cross"
                            aria-hidden
                          >
                            ×
                          </span>
                        )}
                        {!noStreamDay && isFutureDay && (
                          <span
                            className="day-card__future-watermark"
                            aria-hidden
                          >
                            ?
                          </span>
                        )}
                        {!isFutureDay && (
                          <div className="day-card__kv">
                            <div className="day-card__kv-row">
                              <span className="day-card__k">ДЕП:</span>
                              <span className="day-card__v">
                                {hd ? moneyK(dep) : "—"}
                              </span>
                            </div>
                            <div className="day-card__kv-row">
                              <span className="day-card__k">ВЫВОД:</span>
                              <span className="day-card__v">
                                {hd ? moneyK(wv) : "—"}
                              </span>
                            </div>
                            <div className="day-card__kv-row">
                              <span className="day-card__k">ФИКСА:</span>
                              <span className="day-card__v">
                                {hd ? moneyK(fx) : "—"}
                              </span>
                            </div>
                          </div>
                        )}
                      </div>
                      {noStreamDay ? (
                        <div className="day-card__footer">
                          <span className="day-card__chip is-nostream">
                            Не было стрима
                          </span>
                        </div>
                      ) : hd ? (
                        <div className="day-card__footer">
                          <span
                            className={`day-card__chip ${
                              net > 0 ? "is-pos" : net < 0 ? "is-neg" : "is-flat"
                            }`}
                          >
                            {formatNetLineFullRub(net)}
                          </span>
                        </div>
                      ) : (
                        <div className="day-card__footer day-card__footer--ghost">
                          <span className="day-card__ghost">Нет данных</span>
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            <footer className="poster-month-total">
              <div className="poster-month-total__line" />
              <div className="poster-month-total__grid poster-month-total__grid--top">
                <div className="pmt-cell">
                  <span className="pmt-label">Депозиты</span>
                  <strong className="pmt-value">{money(monthStats.dep)}</strong>
                </div>
                <div className="pmt-cell">
                  <span className="pmt-label">Выводы</span>
                  <strong className="pmt-value">{money(monthStats.w)}</strong>
                </div>
                <div className="pmt-cell">
                  <span className="pmt-label">Фикса</span>
                  <strong className="pmt-value">{money(monthStats.fix)}</strong>
                </div>
              </div>
              <div className="poster-month-total__split">
                <div className="pmt-summary pmt-cell--double-net">
                  <span className="pmt-label">Итог с фиксой</span>
                  <strong
                    className={`pmt-balance ${
                      monthStats.net >= 0 ? "is-pos" : "is-neg"
                    }`}
                  >
                    {monthStats.net >= 0 ? "+" : ""}
                    {money(monthStats.net)}
                  </strong>
                  <span className="pmt-label pmt-label--stack">Без фиксы</span>
                  <strong
                    className={`pmt-balance pmt-balance--secondary ${
                      monthStats.netNoFix >= 0 ? "is-pos" : "is-neg"
                    }`}
                  >
                    {monthStats.netNoFix >= 0 ? "+" : ""}
                    {money(monthStats.netNoFix)}
                  </strong>
                  <span className="pmt-sub">
                    {monthStats.pct === null
                      ? "— % к депозиту"
                      : `% с фиксой: ${monthStats.pct >= 0 ? "+" : ""}${monthStats.pct.toFixed(1)}%`}
                    {monthStats.pctNoFix === null
                      ? ""
                      : monthStats.pct === null
                        ? ""
                        : ` · без фиксы: ${monthStats.pctNoFix >= 0 ? "+" : ""}${monthStats.pctNoFix.toFixed(1)}%`}
                  </span>
                </div>
                <PosterMonthNetChart monthKey={monthKey} records={records} />
              </div>
            </footer>
              </div>
            </div>
          </div>

          <div style={{ marginTop: "1rem" }}>
            <h2 className="section-heading">За всё время</h2>
            <div className="stats-grid">
              <div className="stat-box">
                <span>Депозит</span>
                <strong>{money(allStats.dep)}</strong>
              </div>
              <div className="stat-box">
                <span>Вывод</span>
                <strong>{money(allStats.w)}</strong>
              </div>
              <div className="stat-box">
                <span>Фикса</span>
                <strong>{money(allStats.fix)}</strong>
              </div>
              <div
                className={`stat-box ${allStats.net >= 0 ? "pos" : "neg"}`}
              >
                <span>Баланс (с фиксой)</span>
                <strong>{money(allStats.net)}</strong>
              </div>
              <div
                className={`stat-box ${allStats.netNoFix >= 0 ? "pos" : "neg"}`}
              >
                <span>Без фиксы</span>
                <strong>{money(allStats.netNoFix)}</strong>
              </div>
              <div className="stat-box" style={{ gridColumn: "1 / -1" }}>
                <span>% к депозиту</span>
                <strong>
                  {allStats.pct === null
                    ? "—"
                    : `с фиксой ${allStats.pct >= 0 ? "+" : ""}${allStats.pct.toFixed(1)}%`}
                  {allStats.pctNoFix === null
                    ? ""
                    : ` · без ${allStats.pctNoFix >= 0 ? "+" : ""}${allStats.pctNoFix.toFixed(1)}%`}
                </strong>
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <h2>День {selected.split("-").reverse().join(".")}</h2>
          <p className="hint">
            Итог за день: вывод + фикса − депозит. Зелёный день — в плюсе, красный — в минусе.
          </p>
          <div className="form-grid" style={{ marginTop: "0.75rem" }}>
            <div className="form-row">
              <label htmlFor="dep">Депозит, ₽</label>
              <input
                id="dep"
                inputMode="decimal"
                type="number"
                min={0}
                step="0.01"
                value={selectedRecord.deposit || ""}
                placeholder="0"
                onChange={(e) => setField("deposit", e.target.value)}
              />
            </div>
            <div className="form-row">
              <label htmlFor="w">Вывод, ₽</label>
              <input
                id="w"
                inputMode="decimal"
                type="number"
                min={0}
                step="0.01"
                value={selectedRecord.withdraw || ""}
                placeholder="0"
                onChange={(e) => setField("withdraw", e.target.value)}
              />
            </div>
            <div className="form-row">
              <label htmlFor="fix">Фикса, ₽</label>
              <input
                id="fix"
                inputMode="decimal"
                type="number"
                min={0}
                step="0.01"
                value={selectedRecord.fix || ""}
                placeholder="0"
                onChange={(e) => setField("fix", e.target.value)}
              />
            </div>
            <div className="form-row">
              <label htmlFor="notes">Заметка (необязательно)</label>
              <textarea
                id="notes"
                rows={3}
                value={selectedRecord.notes || ""}
                placeholder="Стрим, слот, договорённости…"
                onChange={(e) => setField("notes", e.target.value)}
              />
            </div>
            <div className="form-row form-row--checkbox">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={!!selectedRecord.noStream}
                  onChange={(e) =>
                    setField("noStream", e.target.checked)
                  }
                />
                <span>Не было стрима — день не входит в итоги</span>
              </label>
            </div>
          </div>

          <div
            style={{
              marginTop: "0.75rem",
              padding: "0.65rem",
              borderRadius: "8px",
              background: "var(--bg-elevated)",
              border: "1px solid var(--border)",
            }}
          >
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Итог за день
            </div>
            <div
              style={{
                fontSize: "1.15rem",
                fontWeight: 700,
                color:
                  dayNet(selectedRecord) > 0
                    ? "var(--profit)"
                    : dayNet(selectedRecord) < 0
                      ? "var(--loss)"
                      : "var(--text-muted)",
              }}
            >
              {selectedRecord.noStream
                ? "— (не в итогах)"
                : formatNetLineFullRub(dayNet(selectedRecord))}
            </div>
          </div>

          <div
            className="toolbar"
            style={{ marginTop: "1rem", flexWrap: "wrap" }}
          >
            <button type="button" className="btn btn-primary" onClick={onExportTG}>
              Экспортировать для TG
            </button>
            <button type="button" className="btn btn-danger" onClick={clearDay}>
              Удалить день
            </button>
          </div>
        </div>
      </div>

      {toast && <div className="toast">{toast}</div>}

      {previewUrl && (
        <div
          className="image-preview-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="Предпросмотр картинки месяца"
          onClick={() => setPreviewUrl(null)}
        >
          <div
            className="image-preview-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="image-preview-head">
              <span>Предпросмотр — можно сделать скрин</span>
              <button
                type="button"
                className="btn"
                onClick={() => setPreviewUrl(null)}
              >
                Закрыть
              </button>
            </div>
            <p className="image-preview-hint">
              {isMac ? (
                <>
                  На Mac: выделите область — <kbd>⌘</kbd> + <kbd>⇧</kbd> +{" "}
                  <kbd>4</kbd>. Окно приложения — <kbd>⌘</kbd> + <kbd>⇧</kbd> +{" "}
                  <kbd>4</kbd>, затем пробел, клик по окну.
                </>
              ) : (
                <>
                  На Windows: выделите область — <kbd>Win</kbd> + <kbd>Shift</kbd>{" "}
                  + <kbd>S</kbd>.
                </>
              )}
            </p>
            <div className="image-preview-frame">
              <img src={previewUrl} alt="Сводка месяца" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
