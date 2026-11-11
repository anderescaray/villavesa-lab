import { describe, expect, it } from 'vitest';
import {
  clampIntoService,
  displayName,
  formatClock,
  formatCompact,
  formatDuration,
  formatMinutes,
  isNextDay,
  madridDayType,
  madridSecondsNow,
  parseClock,
} from './format';

describe('clock formatting', () => {
  it('formats seconds as HH:MM and wraps past midnight', () => {
    expect(formatClock(0)).toBe('00:00');
    expect(formatClock(8 * 3600 + 5 * 60 + 59)).toBe('08:05');
    expect(formatClock(25 * 3600 + 10 * 60)).toBe('01:10');
    expect(formatClock(25 * 3600, { wrap: false })).toBe('25:00');
    expect(formatClock(3661, { withSeconds: true })).toBe('01:01:01');
    expect(isNextDay(86400)).toBe(true);
  });
  it('parses HH:MM and rejects garbage', () => {
    expect(parseClock('08:30')).toBe(30600);
    expect(parseClock('0830')).toBe(30600);
    expect(parseClock('25:15')).toBe(90900);
    expect(parseClock('8:75')).toBeNull();
    expect(parseClock('hello')).toBeNull();
  });
});

describe('durations and numbers', () => {
  it('formats durations in minutes / hours', () => {
    expect(formatDuration(0)).toBe('0 min');
    expect(formatDuration(59 * 60)).toBe('59 min');
    expect(formatDuration(3600)).toBe('1 h');
    expect(formatDuration(3900)).toBe('1 h 05 min');
    expect(formatDuration(null)).toBe('—');
  });
  it('formats headway minutes per locale', () => {
    expect(formatMinutes(450, 'es')).toBe('7,5');
    expect(formatMinutes(450, 'en')).toBe('7.5');
    expect(formatMinutes(600, 'en')).toBe('10');
    expect(formatMinutes(null, 'en')).toBe('—');
  });
  it('compacts large numbers only', () => {
    expect(formatCompact(9999, 'en')).toBe('9,999');
    expect(formatCompact(47230, 'en')).toMatch(/^47\.2k$/i);
  });
});

describe('Europe/Madrid time', () => {
  it('converts an instant to local seconds since midnight (CET, UTC+1 in November)', () => {
    expect(madridSecondsNow(new Date('2026-11-10T07:30:00Z'))).toBe(8 * 3600 + 30 * 60);
  });
  it('honours summer time (CEST, UTC+2)', () => {
    expect(madridSecondsNow(new Date('2026-07-01T06:00:00Z'))).toBe(8 * 3600);
  });
  it('classifies the day type', () => {
    expect(madridDayType(new Date('2026-11-11T12:00:00Z'))).toBe('weekday');
    expect(madridDayType(new Date('2026-11-14T12:00:00Z'))).toBe('saturday');
    expect(madridDayType(new Date('2026-11-15T12:00:00Z'))).toBe('sunday');
  });
  it('clamps a time of day into the service day, using +24 h for after-midnight service', () => {
    const [a, b] = [6 * 3600, 25 * 3600];
    expect(clampIntoService(10 * 3600, a, b)).toBe(10 * 3600);
    expect(clampIntoService(0.5 * 3600, a, b)).toBe(24.5 * 3600);
    expect(clampIntoService(3 * 3600, a, b)).toBe(a);
  });
});

describe('displayName', () => {
  it('title-cases names typed in capitals, keeping particles and abbreviations', () => {
    expect(displayName('CIZUR MENOR-UNIVERSIDADES')).toBe('Cizur Menor-Universidades');
    expect(displayName('PZA. PRÍNCIPE DE VIANA - GORRÁIZ - C.C. ITAROA')).toBe(
      'Pza. Príncipe de Viana - Gorráiz - C.C. Itaroa',
    );
  });
  it('leaves mixed-case names untouched', () => {
    expect(displayName('Barañáin - Villava')).toBe('Barañáin - Villava');
  });
});
