/**
 * Data-viz palettes (source of truth for map + legends). Validated with the dataviz palette
 * validator (ordinal mode: single hue, monotone lightness, visible step gaps, end step ≥ 2:1 vs
 * the surface) — see docs/design.md. Single-hue ramps stay readable under every colour-vision
 * deficiency because they encode order by lightness, not hue.
 */
import type { Theme } from '@/app/store';

/** Isochrone bands, index 0 = shortest cutoff (most accessible). */
export const ISO_COLORS: Record<Theme, [string, string, string]> = {
  light: ['#1c5cab', '#3987e5', '#86b6ef'],
  dark: ['#5598e7', '#2a78d6', '#184f95'],
};

export const ISO_FILL_OPACITY: Record<Theme, [number, number, number]> = {
  light: [0.26, 0.2, 0.2],
  dark: [0.3, 0.26, 0.26],
};

/** Sequential (magnitude) ramp for choropleths, light → dark; reserved for M7. */
export const SEQUENTIAL_BLUE = [
  '#cde2fb',
  '#9ec5f4',
  '#6da7ec',
  '#3987e5',
  '#256abf',
  '#184f95',
  '#0d366b',
] as const;

/** Diverging (gain/loss) ramp with a neutral grey midpoint; reserved for M8/M10. */
export const DIVERGING: Record<Theme, { neg: string[]; mid: string; pos: string[] }> = {
  light: {
    neg: ['#b3262f', '#e0605f', '#f2a7a2'],
    mid: '#eceef0',
    pos: ['#9ec5f4', '#3987e5', '#1c5cab'],
  },
  dark: {
    neg: ['#e66767', '#b84345', '#6e2a2c'],
    mid: '#2a2d32',
    pos: ['#184f95', '#2a78d6', '#6da7ec'],
  },
};
