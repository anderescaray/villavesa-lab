/**
 * Shareable URL state (hash router): `#/<view>?line=4&dir=0&stop=12&day=weekday&t=0830&lang=en
 * &iso=-1.64,42.81&mode=walk&play=0`. Parsed once on load, then kept in sync with replaceState.
 */
import { DAY_TYPES, type DayType, type IsochroneMode, type LonLat } from '@/api/types';
import { clock } from '@/features/time/clock';
import { LANGS, type Lang } from '@/i18n/dict';
import { VIEWS, useApp, type AppState, type ViewId } from './store';

export interface UrlState {
  route: ViewId | 'dev';
  line?: string;
  dir?: number;
  stop?: string;
  day?: DayType;
  t?: number;
  lang?: Lang;
  iso?: LonLat;
  isoT?: number;
  mode?: IsochroneMode;
  play?: boolean;
}

const hhmm = (sec: number) => {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${String(h).padStart(2, '0')}${String(m).padStart(2, '0')}`;
};
const parseHhmm = (v: string | null): number | undefined => {
  if (!v || !/^\d{3,4}$/.test(v)) return undefined;
  const n = v.padStart(4, '0');
  const h = Number(n.slice(0, 2));
  const m = Number(n.slice(2));
  return h <= 30 && m < 60 ? h * 3600 + m * 60 : undefined;
};

export function parseHash(hash: string): UrlState {
  const [pathPart, query = ''] = hash.replace(/^#\/?/, '').split('?');
  const seg = (pathPart ?? '').split('/')[0] ?? '';
  const q = new URLSearchParams(query);
  const route: UrlState['route'] = seg === 'dev' ? 'dev' : VIEWS.includes(seg as ViewId) ? (seg as ViewId) : 'network';
  const out: UrlState = { route };
  const line = q.get('line');
  if (line) out.line = line;
  const dir = q.get('dir');
  if (dir === '0' || dir === '1') out.dir = Number(dir);
  const stop = q.get('stop');
  if (stop) out.stop = stop;
  const day = q.get('day');
  if (day && DAY_TYPES.includes(day as DayType)) out.day = day as DayType;
  const t = parseHhmm(q.get('t'));
  if (t !== undefined) out.t = t;
  const lang = q.get('lang');
  if (lang && LANGS.includes(lang as Lang)) out.lang = lang as Lang;
  const iso = q.get('iso')?.split(',').map(Number);
  if (iso && iso.length === 2 && iso.every(Number.isFinite)) out.iso = [iso[0]!, iso[1]!];
  const isoT = parseHhmm(q.get('isot'));
  if (isoT !== undefined) out.isoT = isoT;
  const mode = q.get('mode');
  if (mode === 'walk' || mode === 'transit') out.mode = mode;
  const play = q.get('play');
  if (play === '0' || play === '1') out.play = play === '1';
  return out;
}

export function buildHash(s: AppState, time: number, playing: boolean): string {
  const q = new URLSearchParams();
  if (s.selectedRouteId) {
    q.set('line', s.selectedRouteId);
    if (s.selectedDirection) q.set('dir', String(s.selectedDirection));
  }
  if (s.selectedStopId) q.set('stop', s.selectedStopId);
  q.set('day', s.day);
  q.set('t', hhmm(time));
  q.set('lang', s.lang);
  if (s.isoOrigin) {
    q.set('iso', `${s.isoOrigin[0].toFixed(5)},${s.isoOrigin[1].toFixed(5)}`);
    q.set('isot', hhmm(s.isoStart));
    if (s.isoMode !== 'transit') q.set('mode', s.isoMode);
  }
  if (!playing) q.set('play', '0');
  return `#/${s.view}?${q.toString().replace(/%2C/g, ',')}`;
}

/** Apply a parsed URL to the stores. Returns the requested initial time (if any). */
export function applyUrl(u: UrlState): void {
  const patch: Partial<AppState> = {};
  if (u.route !== 'dev') patch.view = u.route;
  if (u.line) patch.selectedRouteId = u.line;
  if (u.dir !== undefined) patch.selectedDirection = u.dir;
  if (u.stop) patch.selectedStopId = u.stop;
  if (u.day) patch.day = u.day;
  if (u.lang) patch.lang = u.lang;
  if (u.iso) patch.isoOrigin = u.iso;
  if (u.isoT !== undefined) patch.isoStart = u.isoT;
  if (u.mode) patch.isoMode = u.mode;
  useApp.setState(patch);
}

/** Keep the URL in sync (throttled while the clock plays). */
export function startUrlSync(): () => void {
  let timer = 0;
  let lastWrite = 0;
  const write = () => {
    timer = 0;
    lastWrite = performance.now();
    if (window.location.hash.startsWith('#/dev')) return;
    const { time, playing } = clock.getState();
    const next = buildHash(useApp.getState(), time, playing);
    if (next !== window.location.hash) window.history.replaceState(null, '', next);
  };
  const schedule = (delay: number) => {
    if (!timer) timer = window.setTimeout(write, delay);
  };
  const unsubApp = useApp.subscribe(() => schedule(150));
  const unsubClock = clock.subscribe((s, prev) => {
    if (s.playing !== prev.playing) schedule(50);
    else if (!s.playing && s.time !== prev.time) schedule(300);
    else if (s.playing && performance.now() - lastWrite > 2000) schedule(0);
  });
  return () => {
    unsubApp();
    unsubClock();
    window.clearTimeout(timer);
  };
}
