import { describe, expect, it } from 'vitest';
import { buildHash, parseHash } from './url';
import { useApp } from './store';

describe('URL state', () => {
  it('parses a full hash', () => {
    const u = parseHash(
      '#/network?line=4&dir=1&day=saturday&t=0830&lang=en&iso=-1.64,42.81&isot=0815&mode=walk&play=0',
    );
    expect(u).toMatchObject({
      route: 'network',
      line: '4',
      dir: 1,
      day: 'saturday',
      t: 30600,
      lang: 'en',
      iso: [-1.64, 42.81],
      isoT: 29700,
      mode: 'walk',
      play: false,
    });
  });
  it('ignores invalid values', () => {
    const u = parseHash('#/nowhere?day=monday&lang=fr&t=9999&iso=a,b');
    expect(u).toEqual({ route: 'network' });
  });
  it('round-trips app state', () => {
    const s = {
      ...useApp.getState(),
      view: 'accessibility' as const,
      selectedRouteId: '9',
      lang: 'eu' as const,
    };
    const hash = buildHash(s, 25 * 3600 + 60, false);
    expect(hash.startsWith('#/accessibility?')).toBe(true);
    const u = parseHash(hash);
    expect(u).toMatchObject({
      route: 'accessibility',
      line: '9',
      lang: 'eu',
      t: 25 * 3600 + 60,
      play: false,
    });
  });
});
