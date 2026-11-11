import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { contrastRatio, ensureContrast, luminance, parseHex, readableTextOn } from './color';

// Line colours of the TUC Pamplona GTFS (routes.txt) with their declared text colours.
const GTFS_ROUTES: [string, string][] = [
  ['004631', 'FFFFFF'],
  ['8D363B', 'FFFFFF'],
  ['00AA86', 'FFFFFF'],
  ['BC9DD6', 'FFFFFF'],
  ['00A8E1', 'FFFFFF'],
  ['77B800', '000000'],
  ['0063BE', 'FFFFFF'],
  ['E86DB2', '000000'],
  ['EF8200', '000000'],
  ['A32B8C', 'FFFFFF'],
  ['009A3D', 'FFFFFF'],
  ['B56F7E', 'FFFFFF'],
  ['002596', 'FFFFFF'],
  ['DC291E', 'FFFFFF'],
  ['CA0083', 'FFFFFF'],
  ['872434', 'FFFFFF'],
  ['9C9100', 'FFFFFF'],
  ['C97683', '000000'],
  ['4DC5E2', '000000'],
  ['FFD451', '000000'],
  ['682145', 'FFFFFF'],
  ['BFB800', '000000'],
  ['607C8C', 'FFFFFF'],
  ['A05324', '000000'],
  ['0098AA', 'FFFFFF'],
  ['3074F1', 'FFFFFF'],
  ['A4024A', 'FFFFFF'],
  ['2282BB', 'FFFFFF'],
  ['9FA2A2', '000000'],
  ['4BA99B', 'FFFFFF'],
  ['964143', 'FFFFFF'],
  ['DE7477', '000000'],
  ['690383', 'FFFFFF'],
  ['978A7B', '000000'],
  ['D12E94', 'FFFFFF'],
  ['E3CD04', '000000'],
  ['13B3FF', 'FFFFFF'],
  ['B17CD1', 'FFFFFF'],
  ['00B75B', '000000'],
  ['CEB380', '000000'],
  ['FF0000', 'FFFFFF'],
  ['FF8000', '000000'],
  ['9C7761', 'FFFFFF'],
  ['5398AC', 'FFFFFF'],
  ['85C9A7', '000000'],
];

describe('contrast maths', () => {
  it('matches WCAG reference values', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 5);
    expect(contrastRatio('#777777', '#FFFFFF')).toBeCloseTo(4.48, 2);
    expect(luminance('#FFFFFF')).toBeCloseTo(1);
  });
  it('parses short and invalid hex safely', () => {
    expect(parseHex('#fff')).toEqual([255, 255, 255]);
    expect(parseHex('nope')).toEqual([128, 128, 128]);
  });
});

describe('line badges', () => {
  it('every GTFS line badge reaches WCAG AA (4.5:1) text contrast', () => {
    for (const [bg, fg] of GTFS_ROUTES) {
      const text = readableTextOn(`#${bg}`, `#${fg}`);
      expect(contrastRatio(`#${bg}`, text), `line #${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it('keeps the operator text colour when it already passes', () => {
    expect(readableTextOn('#002596', '#FFFFFF')).toBe('#FFFFFF');
  });
  it('overrides it when it fails (white on olive L01)', () => {
    expect(readableTextOn('#9C9100', '#FFFFFF')).toBe('#0F1216');
  });
});

describe('map line colours', () => {
  it('lifts dark lines to stay visible on the dark basemap', () => {
    const c = ensureContrast('#002596', '#0e0f11', 2.2);
    expect(contrastRatio(c, '#0e0f11')).toBeGreaterThanOrEqual(2.2);
  });
  it('leaves already-visible colours unchanged', () => {
    expect(ensureContrast('#DC291E', '#f3f4f5', 1.5)).toBe('#DC291E');
  });
});

describe('design tokens (tokens.css)', () => {
  const css = readFileSync(resolve(__dirname, '../styles/tokens.css'), 'utf8');
  const block = (selector: RegExp) => {
    const m = selector.exec(css);
    return m ? css.slice(m.index, css.indexOf('\n}', m.index)) : '';
  };
  const tokens = (text: string) =>
    Object.fromEntries(
      [...text.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]),
    );
  const light = tokens(block(/^:root \{/m));
  const dark = { ...light, ...tokens(block(/^:root\[data-theme='dark'\] \{/m)) };

  for (const [name, t] of [
    ['light', light],
    ['dark', dark],
  ] as const) {
    it(`${name}: text roles reach WCAG AA on surfaces`, () => {
      for (const fg of ['text', 'text-secondary', 'text-tertiary', 'accent-text']) {
        for (const bg of ['bg', 'surface', 'surface-raised']) {
          expect(contrastRatio(t[fg]!, t[bg]!), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
        }
      }
    });
    it(`${name}: primary button text reaches AA on the accent`, () => {
      expect(contrastRatio(t['accent-fg']!, t.accent!)).toBeGreaterThanOrEqual(4.5);
    });
  }
});
