import { useCallback } from 'react';
import { useApp } from '@/app/store';
import type { DataNote } from '@/api/types';
import { dictionaries, type Lang, type MessageKey } from './dict';

export type { Lang, MessageKey } from './dict';
export { LANGS } from './dict';

export type Params = Record<string, string | number>;

export function translate(lang: Lang, key: MessageKey, params?: Params): string {
  const template = dictionaries[lang][key] ?? dictionaries.es[key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (m, name: string) =>
    name in params ? String(params[name]) : m,
  );
}

export type TFunction = (key: MessageKey, params?: Params) => string;

/** Typed translation hook: `t('network.every', { min: 10 })`. */
export function useT(): TFunction {
  const lang = useApp((s) => s.lang);
  return useCallback((key, params) => translate(lang, key, params), [lang]);
}

export const isMessageKey = (k: string): k is MessageKey => k in dictionaries.es;

/** Label for a POI category id coming from the API; falls back to a humanised id. */
export function poiLabel(t: TFunction, id: string): string {
  const key = `poi.${id}`;
  return isMessageKey(key) ? t(key) : id.replace(/_/g, ' ');
}

/** A data limitation from `/api/meta.data_notes`, translated by key (English API text fallback). */
export function noteText(t: TFunction, note: DataNote): string {
  const key = `note.${note.key}`;
  return isMessageKey(key) ? t(key) : note.text;
}
