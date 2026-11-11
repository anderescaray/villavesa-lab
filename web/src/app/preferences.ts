/** Persisted per-browser preferences (language, theme) and theme resolution. */
import { useEffect } from 'react';
import { LANGS, type Lang } from '@/i18n/dict';
import { useApp, type ThemePref } from './store';

const KEY = 'vlab.prefs';

export function loadPrefs(): { lang?: Lang; themePref?: ThemePref } {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '{}') as {
      lang?: string;
      themePref?: string;
    };
    return {
      lang: LANGS.includes(raw.lang as Lang) ? (raw.lang as Lang) : undefined,
      themePref: ['light', 'dark', 'system'].includes(raw.themePref ?? '')
        ? (raw.themePref as ThemePref)
        : undefined,
    };
  } catch {
    return {};
  }
}

export function resolveTheme(pref: ThemePref): 'light' | 'dark' {
  if (pref !== 'system') return pref;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/** Applies theme + lang to <html>, follows the OS theme in "system" mode, persists prefs. */
export function usePreferenceEffects() {
  const themePref = useApp((s) => s.themePref);
  const lang = useApp((s) => s.lang);
  useEffect(() => {
    const apply = () => {
      const theme = resolveTheme(themePref);
      document.documentElement.dataset.theme = theme;
      if (useApp.getState().theme !== theme) useApp.setState({ theme });
    };
    apply();
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    mq?.addEventListener('change', apply);
    return () => mq?.removeEventListener('change', apply);
  }, [themePref]);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ lang, themePref }));
    } catch {
      /* storage unavailable */
    }
  }, [lang, themePref]);
}
