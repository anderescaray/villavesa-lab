import { describe, expect, it } from 'vitest';
import { dictionaries, es, LANGS } from './dict';
import { translate } from './index';

const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe('i18n dictionaries', () => {
  const keys = Object.keys(es).sort();
  for (const lang of LANGS) {
    it(`${lang} has exactly the same keys as es`, () => {
      expect(Object.keys(dictionaries[lang]).sort()).toEqual(keys);
    });
    it(`${lang} has no empty strings and the same placeholders`, () => {
      for (const k of keys) {
        const v = dictionaries[lang][k as keyof typeof es];
        expect(v.trim(), `${lang}:${k}`).not.toBe('');
        expect(placeholders(v), `${lang}:${k}`).toEqual(placeholders(es[k as keyof typeof es]));
      }
    });
  }
  it('interpolates params and leaves unknown placeholders visible', () => {
    expect(translate('en', 'network.every', { min: 7 })).toBe('every 7 min');
    expect(translate('es', 'network.every', { min: '7,5' })).toBe('cada 7,5 min');
    expect(translate('en', 'network.every')).toBe('every {min} min');
  });
  it('uses no emoji anywhere in the UI copy', () => {
    const emoji = /\p{Emoji_Presentation}/u;
    for (const lang of LANGS)
      for (const v of Object.values(dictionaries[lang])) expect(emoji.test(v), v).toBe(false);
  });
});
