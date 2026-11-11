/**
 * The simulation clock. Lives outside React: a vanilla zustand store advanced by a single
 * requestAnimationFrame loop. Map layers subscribe directly (per frame); React components select
 * coarse values (e.g. the current minute) so they re-render at most once per simulated minute.
 */
import { useStore } from 'zustand';
import { createStore } from 'zustand/vanilla';

export const SPEEDS = [30, 60, 120, 300] as const;
export type Speed = (typeof SPEEDS)[number];

export interface ClockState {
  /** seconds since service-day midnight (may exceed 86400) */
  time: number;
  playing: boolean;
  speed: Speed;
  /** service-day domain [start, end] in seconds */
  domain: [number, number];
}

export const clock = createStore<ClockState>()(() => ({
  time: 8 * 3600,
  playing: false,
  speed: 60,
  domain: [5 * 3600, 25 * 3600],
}));

export const clampTime = (t: number, [a, b]: [number, number]) => Math.min(b, Math.max(a, t));

export const clockActions = {
  play: () => clock.setState({ playing: true }),
  pause: () => clock.setState({ playing: false }),
  toggle: () => clock.setState((s) => ({ playing: !s.playing })),
  seek: (t: number) => clock.setState((s) => ({ time: clampTime(t, s.domain) })),
  step: (delta: number) => clock.setState((s) => ({ time: clampTime(s.time + delta, s.domain) })),
  setSpeed: (speed: Speed) => clock.setState({ speed }),
  cycleSpeed: () =>
    clock.setState((s) => ({ speed: SPEEDS[(SPEEDS.indexOf(s.speed) + 1) % SPEEDS.length]! })),
  setDomain: (domain: [number, number]) =>
    clock.setState((s) => ({ domain, time: clampTime(s.time, domain) })),
};

let rafId = 0;
let last = 0;
function tick(now: number) {
  const s = clock.getState();
  if (s.playing) {
    const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
    let t = s.time + dt * s.speed;
    if (t > s.domain[1]) t = s.domain[0]; // loop the service day
    clock.setState({ time: t });
  }
  last = now;
  rafId = requestAnimationFrame(tick);
}

/** Start the single rAF loop (idempotent). Returns a stop function. */
export function startClock(): () => void {
  if (!rafId) {
    last = 0;
    rafId = requestAnimationFrame(tick);
  }
  return () => {
    cancelAnimationFrame(rafId);
    rafId = 0;
  };
}

export function useClock<T>(selector: (s: ClockState) => T): T {
  return useStore(clock, selector);
}

/** Current simulated minute (re-renders once per simulated minute). */
export const useClockMinute = () => useClock((s) => Math.floor(s.time / 60));
