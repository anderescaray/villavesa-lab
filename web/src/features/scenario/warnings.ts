/**
 * Translates the engine's scenario warnings (English strings with internal ids, see
 * `engine/src/vlab/scenario/apply.py`) into the UI language with user-facing names. Unknown
 * patterns fall back to the original text.
 */
import type { ScenarioEdit } from '@/api/scenario';
import type { NetworkModel } from '@/features/network/model';
import type { TFunction } from '@/i18n';
import { displayName } from '@/lib/format';

export interface WarningNames {
  route: (id: string) => string;
  stop: (id: string) => string;
}

/** Name lookup from network models (first hit wins) plus the edits that create routes / stops. */
export function warningNames(
  models: (NetworkModel | null | undefined)[],
  edits: readonly ScenarioEdit[] = [],
): WarningNames {
  const routes = new Map<string, string>();
  const stops = new Map<string, string>();
  for (const e of edits) {
    if (e.type === 'add_route') routes.set(e.route_id, e.short_name);
    if (e.type === 'add_stop') stops.set(e.stop_id, e.name);
  }
  return {
    route: (id) => {
      const own = routes.get(id);
      if (own) return own;
      for (const m of models) {
        const r = m?.routeById.get(id);
        if (r) return r.short_name;
      }
      return id;
    },
    stop: (id) => {
      const own = stops.get(id);
      if (own) return displayName(own);
      for (const m of models) {
        const st = m?.stopById.get(id);
        if (st) return displayName(st.name);
      }
      return id;
    },
  };
}

const num = (s: string) => String(Math.round(Number(s)));

export function translateWarning(w: string, t: TFunction, names: WarningNames): string {
  let text = w.trim();
  let prefix = '';
  const day = /^(weekday|saturday|sunday):\s+(.*)$/s.exec(text);
  if (day) {
    prefix = `${t(`warn.day.${day[1] as 'weekday' | 'saturday' | 'sunday'}`)} · `;
    text = day[2]!;
  }
  let m: RegExpExecArray | null;
  const route = /^route (\S+) direction (\d+): (.*)$/s.exec(text);
  if (route) {
    const line = names.route(route[1]!);
    const inner = route[3]!;
    if ((m = /^a stop is (\d+(?:\.\d+)?) m from the path$/.exec(inner)))
      return prefix + t('warn.stopFarFromPath', { line, m: num(m[1]!) });
    if ((m = /^leg (\d+) could not be snapped/.exec(inner)))
      return prefix + t('warn.legNotSnapped', { line, k: m[1]! });
    return w;
  }
  if ((m = /^stop (\S+) moved (\d+(?:\.\d+)?) m:/.exec(text)))
    return prefix + t('warn.stopMoved', { stop: names.stop(m[1]!), m: num(m[2]!) });
  if ((m = /^new stop (\S+) is a detour of about (\d+) s on route (\S+)$/.exec(text)))
    return (
      prefix + t('warn.detour', { stop: names.stop(m[1]!), s: m[2]!, line: names.route(m[3]!) })
    );
  if ((m = /^route (\S+) extended to (\S+): the extension is not snapped/.exec(text)))
    return prefix + t('warn.extension', { line: names.route(m[1]!), stop: names.stop(m[2]!) });
  if (/^pattern \S+ has fewer than two stops left and was removed$/.test(text))
    return prefix + t('warn.patternRemoved');
  if ((m = /^route (\S+): frequency change had no effect$/.exec(text)))
    return prefix + t('warn.noEffect', { line: names.route(m[1]!) });
  return w;
}
