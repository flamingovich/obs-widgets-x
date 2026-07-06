const intSpace = (n) =>
  new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 0,
    minimumFractionDigits: 0,
  }).format(Math.round(Number(n) || 0));

/** Дробная часть до 3 знаков, запятая, без лишних нулей. */
function fmtK(val) {
  const r = Math.round(Number(val) * 1000) / 1000;
  if (Number.isInteger(r)) return String(r);
  let s = r.toFixed(3).replace(".", ",");
  s = s.replace(/0+$/, "");
  if (s.endsWith(",")) s = s.slice(0, -1);
  return s;
}

/**
 * Кратко: 100 000 → «100к», 1 000 000 → «1кк». До 999 — полное целое с пробелами.
 * Отрицательные — с минусом «−».
 */
export function formatRubCompactK(n) {
  const x = Number(n) || 0;
  const sign = x < 0 ? "−" : "";
  const v = Math.abs(x);
  if (v < 1000) return sign + intSpace(v);
  if (v < 1_000_000) return sign + fmtK(v / 1000) + "к";
  return sign + fmtK(v / 1_000_000) + "кк";
}

/** Итог строкой: «+200 000 ₽», «−15 000 ₽», «0 ₽». */
export function formatNetLineFullRub(n) {
  const x = Number(n) || 0;
  const num = intSpace(Math.abs(x));
  if (x > 0) return `+${num} ₽`;
  if (x < 0) return `−${num} ₽`;
  return `0 ₽`;
}

/** Сумма в рублях для отображения (₽), полный формат — для итогов и форм. */
export function formatRub(n) {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(Number(n) || 0);
}
