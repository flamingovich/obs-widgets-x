import { formatRub, formatRubCompactK } from "./formatMoney.js";
import { dayNet, dayNetNoFix, hasData } from "./storage.js";

const moneyFull = formatRub;
const moneyK = formatRubCompactK;

/**
 * @param {string} monthKey YYYY-MM
 * @param {Record<string, import('./storage.js').DayRecord>} all
 */
export function buildTelegramPost(monthKey, all) {
  const [y, m] = monthKey.split("-").map(Number);
  const monthNames = [
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
  const lines = [
    `📅 ${monthNames[m - 1]} ${y}`,
    "",
    "```",
    "Дата   Деп   Выв   Фикс   Итог (к)",
    "──────────────────────────────────────",
  ];

  const daysInMonth = new Date(y, m, 0).getDate();
  let tDep = 0;
  let tW = 0;
  let tFix = 0;
  let tNet = 0;
  let tNetNoFix = 0;
  let count = 0;

  for (let d = 1; d <= daysInMonth; d++) {
    const date = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const r = all[date];
    if (!r || !hasData(r) || r.noStream) continue;
    count++;
    const net = dayNet(r);
    tDep += Number(r.deposit) || 0;
    tW += Number(r.withdraw) || 0;
    tFix += Number(r.fix) || 0;
    tNet += net;
    tNetNoFix += dayNetNoFix(r);
    const dd = `${String(d).padStart(2, "0")}.${String(m).padStart(2, "0")}`;
    const netLabel = net > 0 ? `+${moneyK(net)}` : moneyK(net);
    lines.push(
      `${dd}  ${moneyK(r.deposit)}  ${moneyK(r.withdraw)}  ${moneyK(r.fix)}  ${netLabel}`
    );
  }

  if (count === 0) {
    lines.push("(нет записей за месяц)");
  }

  lines.push("```");
  lines.push("");

  const pct =
    tDep > 0 ? ((tNet / tDep) * 100).toFixed(1) : tNet !== 0 ? null : "0";
  const signEmoji = tNet > 0 ? "🟢" : tNet < 0 ? "🔴" : "⚪";

  lines.push("📊 Итого за месяц");
  lines.push(`💵 Депозит: ${moneyFull(tDep)}`);
  lines.push(`💸 Вывод: ${moneyFull(tW)}`);
  lines.push(`🎁 Фикса: ${moneyFull(tFix)}`);
  lines.push(`${signEmoji} Баланс (с фиксой): ${moneyFull(tNet)}`);
  lines.push(`⚪ Баланс без фиксы: ${moneyFull(tNetNoFix)}`);
  const pctNoFix =
    tDep > 0 ? ((tNetNoFix / tDep) * 100).toFixed(1) : tNetNoFix !== 0 ? null : "0";
  if (pct === null) {
    lines.push("📐 % к депозиту (с фиксой): —");
  } else {
    const p = Number(pct);
    lines.push(
      `📐 % к депозиту (с фиксой): ${p >= 0 ? "+" : ""}${pct}%`
    );
  }
  if (pctNoFix === null) {
    lines.push("📐 % к депозиту (без фиксы): —");
  } else {
    const p2 = Number(pctNoFix);
    lines.push(
      `📐 % к депозиту (без фиксы): ${p2 >= 0 ? "+" : ""}${pctNoFix}%`
    );
  }
  lines.push("");
  lines.push("🎰 Dep Calendar");

  return lines.join("\n");
}
