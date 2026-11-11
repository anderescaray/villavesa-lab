import { describe, expect, it } from 'vitest';
import { translate } from '@/i18n';
import { translateWarning, type WarningNames } from './warnings';

const names: WarningNames = {
  route: (id) => (id === 'new-A' ? 'A' : id === 'r9' ? '9' : id),
  stop: (id) => (id === 's1' ? 'Plaza del Castillo' : id),
};
const es = (w: string) => translateWarning(w, (k, p) => translate('es', k, p), names);
const en = (w: string) => translateWarning(w, (k, p) => translate('en', k, p), names);

describe('translateWarning', () => {
  it('translates stop far from path with the line short name', () => {
    expect(es('route new-A direction 1: a stop is 353 m from the path')).toBe(
      'Línea A: una parada queda a 353 m del trazado.',
    );
  });
  it('translates unsnapped legs', () => {
    expect(
      en(
        'route new-A direction 0: leg 2 could not be snapped to the street network; drawn as a straight line',
      ),
    ).toContain('Line A: leg 2');
  });
  it('uses stop names', () => {
    expect(en('stop s1 moved 120 m: bus paths and running times are not rerouted')).toContain(
      'Plaza del Castillo',
    );
    expect(en('new stop s1 is a detour of about 75 s on route r9')).toContain('line 9');
    expect(en('route r9 extended to s1: the extension is not snapped to streets')).toContain(
      'Plaza del Castillo',
    );
  });
  it('handles removed patterns, no-effect and day prefixes', () => {
    expect(en('pattern 12 has fewer than two stops left and was removed')).toContain(
      'fewer than two',
    );
    expect(en('route r9: frequency change had no effect')).toBe(
      'Line 9: the frequency change had no effect.',
    );
    expect(en('sunday: route r9: frequency change had no effect')).toMatch(/^Sunday · Line 9/);
  });
  it('falls back to the original text', () => {
    expect(es('something unexpected')).toBe('something unexpected');
  });
});
