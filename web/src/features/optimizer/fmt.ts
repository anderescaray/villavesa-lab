/** Number formatting shared by the optimizer and compare views (locale-aware, signed). */
import type { Lang } from '@/i18n/dict';
import { formatNumber } from '@/lib/format';

const MINUS = '−';

/** "+3,2" / "−22" / "0": explicit sign, real minus sign, locale decimals. */
export function formatSigned(n: number | null | undefined, lang: Lang, digits = 0): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  const rounded = Number(n.toFixed(digits));
  if (rounded === 0) return formatNumber(0, lang, digits);
  return `${rounded > 0 ? '+' : MINUS}${formatNumber(Math.abs(rounded), lang, digits)}`;
}

/** Signed percentage points as text: "+3,2 %". */
export const formatSignedPct = (pct: number | null | undefined, lang: Lang, digits = 1) =>
  pct === null || pct === undefined || !Number.isFinite(pct)
    ? '—'
    : `${formatSigned(pct, lang, digits)} %`;

/** Seconds as minutes with one decimal ("13,4 min"). */
export const formatMin1 = (sec: number | null | undefined, lang: Lang) =>
  sec === null || sec === undefined || !Number.isFinite(sec)
    ? '—'
    : `${formatNumber(sec / 60, lang, 1)} min`;

/** Signed seconds: "−22 s", switching to minutes from 2 min ("+3,5 min"). */
export function formatSignedTime(sec: number | null | undefined, lang: Lang): string {
  if (sec === null || sec === undefined || !Number.isFinite(sec)) return '—';
  if (Math.abs(sec) >= 120) return `${formatSigned(sec / 60, lang, 1)} min`;
  return `${formatSigned(sec, lang, 0)} s`;
}

/** Euros without decimals, compacted from 10 000 ("811 k€" style is avoided: plain "811 mil €"). */
export function formatEuros(eur: number | null | undefined, lang: Lang): string {
  if (eur === null || eur === undefined || !Number.isFinite(eur)) return '—';
  return new Intl.NumberFormat(lang === 'es' ? 'es-ES' : lang === 'eu' ? 'eu-ES' : 'en-GB', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
    notation: Math.abs(eur) >= 100_000 ? 'compact' : 'standard',
  }).format(eur);
}
