import type { Lang } from '@/i18n/dict';

const LOCALES: Record<Lang, string> = { es: 'es-ES', en: 'en-GB', eu: 'eu-ES' };
export const localeOf = (lang: Lang) => LOCALES[lang];

const pad = (n: number) => String(n).padStart(2, '0');

/** Seconds since service-day midnight → "HH:MM" (wraps past 24 h: 25:10 → "01:10"). */
export function formatClock(seconds: number, opts: { wrap?: boolean; withSeconds?: boolean } = {}) {
  const { wrap = true, withSeconds = false } = opts;
  const s = Math.max(0, Math.floor(seconds));
  let h = Math.floor(s / 3600);
  if (wrap) h %= 24;
  const m = Math.floor((s % 3600) / 60);
  const base = `${pad(h)}:${pad(m)}`;
  return withSeconds ? `${base}:${pad(s % 60)}` : base;
}

/** True when a service-day time falls after midnight (shown with a "+1" marker). */
export const isNextDay = (seconds: number) => seconds >= 86400;

/** Parse "HH:MM" or "HHMM" (also > 24 h) → seconds; null when malformed. */
export function parseClock(text: string): number | null {
  const m = /^(\d{1,2}):?(\d{2})$/.exec(text.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (min > 59 || h > 30) return null;
  return h * 3600 + min * 60;
}

/** Duration in seconds → "12 min", "1 h 05 min" (rounded to minutes). */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const total = Math.round(seconds / 60);
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m === 0 ? `${h} h` : `${h} h ${pad(m)} min`;
}

/** Headway in seconds → minutes as a short number string ("7.5" → "7,5" in es). */
export function formatMinutes(seconds: number | null | undefined, lang: Lang): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const m = seconds / 60;
  return new Intl.NumberFormat(localeOf(lang), {
    maximumFractionDigits: m < 10 && m % 1 !== 0 ? 1 : 0,
  }).format(m);
}

export function formatNumber(n: number | null | undefined, lang: Lang, digits = 0): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  return new Intl.NumberFormat(localeOf(lang), {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(n);
}

/** Compact population-like numbers: 12 345 → "12,3 mil" / "12.3k". */
export function formatCompact(n: number | null | undefined, lang: Lang): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  if (Math.abs(n) < 10_000) return formatNumber(n, lang);
  return new Intl.NumberFormat(localeOf(lang), {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(n);
}

export function formatPercent(share: number | null | undefined, lang: Lang, digits = 0): string {
  if (share === null || share === undefined || !Number.isFinite(share)) return '—';
  return new Intl.NumberFormat(localeOf(lang), {
    style: 'percent',
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(share);
}

export function formatCurrency(eur: number, lang: Lang): string {
  return new Intl.NumberFormat(localeOf(lang), {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(eur);
}

/** Current time of day in Europe/Madrid, as seconds since local midnight. */
export function madridSecondsNow(now: Date = new Date()): number {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Madrid',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? 0);
  return get('hour') * 3600 + get('minute') * 60 + get('second');
}

/** Day type of a date in Europe/Madrid (holidays are not considered). */
export function madridDayType(now: Date = new Date()): 'weekday' | 'saturday' | 'sunday' {
  const wd = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Madrid', weekday: 'short' })
    .format(now)
    .slice(0, 3);
  return wd === 'Sat' ? 'saturday' : wd === 'Sun' ? 'sunday' : 'weekday';
}

/**
 * Map a wall-clock time of day into a service-day domain [start, end] (which may extend past
 * 24 h). Times before the start are tried +24 h (after-midnight service), then clamped.
 */
export function clampIntoService(tod: number, start: number, end: number): number {
  if (tod >= start && tod <= end) return tod;
  if (tod + 86400 >= start && tod + 86400 <= end) return tod + 86400;
  return tod < start ? start : Math.min(Math.max(tod, start), end);
}
