/** Colour helpers: parsing, WCAG contrast, readable text on GTFS line colours. */

export type RGB = [number, number, number];
export type RGBA = [number, number, number, number];

export function parseHex(hex: string): RGB {
  let h = hex.trim().replace(/^#/, '');
  if (h.length === 3) h = [...h].map((c) => c + c).join('');
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return [128, 128, 128];
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

export const toHex = ([r, g, b]: RGB) =>
  `#${[r, g, b]
    .map((v) =>
      Math.round(Math.min(255, Math.max(0, v)))
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')}`;

const channel = (v: number) => {
  const c = v / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};

/** WCAG 2.x relative luminance. */
export function luminance(hex: string): number {
  const [r, g, b] = parseHex(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG 2.x contrast ratio (1..21). */
export function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * Text colour for a line badge. Keeps the operator's GTFS `route_text_color` when it reaches
 * WCAG AA (4.5:1) on the line colour; otherwise picks whichever of near-black / white reads best.
 */
export function readableTextOn(bg: string, preferred?: string): string {
  if (preferred && contrastRatio(bg, preferred) >= 4.5) return preferred.toUpperCase();
  const dark = '#0F1216';
  const light = '#FFFFFF';
  const best = contrastRatio(bg, dark) >= contrastRatio(bg, light) ? dark : light;
  // mid-tones (e.g. slate #607C8C) only reach AA with pure black
  if (contrastRatio(bg, best) < 4.5 && contrastRatio(bg, '#000000') > contrastRatio(bg, best)) {
    return '#000000';
  }
  return best;
}

export function mix(a: string, b: string, t: number): string {
  const ca = parseHex(a);
  const cb = parseHex(b);
  return toHex([0, 1, 2].map((i) => ca[i]! + (cb[i]! - ca[i]!) * t) as RGB);
}

/**
 * Same hue, nudged lighter/darker until it reaches `min` contrast against the map background.
 * Used for lines and buses drawn on the map so that, e.g., navy lines stay visible in dark mode
 * (badges always keep the exact GTFS colour).
 */
export function ensureContrast(color: string, background: string, min = 1.8): string {
  if (contrastRatio(color, background) >= min) return color;
  const towards = luminance(background) < 0.2 ? '#FFFFFF' : '#000000';
  for (let t = 0.05; t <= 0.8; t += 0.05) {
    const c = mix(color, towards, t);
    if (contrastRatio(c, background) >= min) return c;
  }
  return mix(color, towards, 0.8);
}

export function rgba(hex: string, alpha = 255): RGBA {
  const [r, g, b] = parseHex(hex);
  return [r, g, b, alpha];
}
