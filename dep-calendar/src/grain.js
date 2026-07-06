/** @param {string} s */
export function hashStr(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/**
 * Уникальная «плёнка» на карточку: стабильна для ключа даты, не моргает при ререндере.
 * @param {string} dateKey YYYY-MM-DD
 */
export function grainLayerProps(dateKey) {
  const h = hashStr(dateKey);
  const seed = (h % 900) + 1;
  const bf1 = 0.55 + (h % 55) / 220;
  const bf2 = 0.5 + ((h >>> 5) % 60) / 220;
  const oct = 3 + (h % 2);
  const opacity = 0.11 + (h % 13) / 160;
  const size = 128 + (h % 88);
  const posX = (h % 97) - 48;
  const posY = ((h >>> 9) % 97) - 48;

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" preserveAspectRatio="none"><filter id="n" x="-20%" y="-20%" width="140%" height="140%"><feTurbulence type="fractalNoise" baseFrequency="${bf1.toFixed(4)} ${bf2.toFixed(4)}" numOctaves="${oct}" seed="${seed}" stitchTiles="stitch"/></filter><rect width="100%" height="100%" filter="url(#n)"/></svg>`;

  return {
    backgroundImage: `url("data:image/svg+xml,${encodeURIComponent(svg)}")`,
    opacity,
    backgroundSize: `${size}px ${size}px`,
    backgroundPosition: `${posX}px ${posY}px`,
  };
}
