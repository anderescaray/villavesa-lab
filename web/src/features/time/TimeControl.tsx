import { Pause, Play } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, type KeyboardEvent, type PointerEvent } from 'react';
import { DAY_TYPES, type DayType } from '@/api/types';
import { useApp } from '@/app/store';
import { AnimatedNumber, SegmentedControl, Select, Skeleton, Surface } from '@/components/ui';
import { useNetworkModel, useVehicleModel } from '@/features/network/model';
import { useT } from '@/i18n';
import { formatClock, formatNumber, isNextDay } from '@/lib/format';
import { activeCount } from '@/lib/vehicles';
import { SPEEDS, clock, clockActions, useClock, useClockMinute, type Speed } from './clock';
import s from './TimeControl.module.css';

const HIST_W = 600;
const HIST_H = 22;

function Histogram({ series, max }: { series: number[]; max: number }) {
  const n = series.length;
  const bw = HIST_W / Math.max(1, n);
  return (
    <svg width="100%" height={HIST_H} viewBox={`0 0 ${HIST_W} ${HIST_H}`} preserveAspectRatio="none" aria-hidden>
      {series.map((v, i) => {
        const h = v > 0 ? Math.max(1, (v / max) * HIST_H) : 0;
        return <rect key={i} x={i * bw + 0.5} y={HIST_H - h} width={Math.max(0.5, bw - 1)} height={h} fill="currentColor" />;
      })}
    </svg>
  );
}

export function TimeControl() {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const day = useApp((st) => st.day);
  const set = useApp((st) => st.set);
  const playing = useClock((st) => st.playing);
  const speed = useClock((st) => st.speed);
  const minute = useClockMinute();
  const { model: vehicles, query } = useVehicleModel();
  useNetworkModel();

  const domain = useMemo<[number, number]>(
    () => (vehicles ? [vehicles.from, vehicles.to] : [5 * 3600, 25 * 3600]),
    [vehicles],
  );
  useEffect(() => {
    if (vehicles) clockActions.setDomain([vehicles.from, vehicles.to]);
  }, [vehicles]);

  const inService = vehicles ? activeCount(vehicles.index, minute * 60 + 30) : null;
  const max = useMemo(() => (vehicles ? Math.max(1, ...vehicles.series) : 1), [vehicles]);

  // playhead follows the clock every frame without React
  const headRef = useRef<HTMLDivElement>(null);
  const playedRef = useRef<HTMLDivElement>(null);
  const scrubRef = useRef<HTMLDivElement>(null);
  const playedInnerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const apply = (time: number) => {
      const el = scrubRef.current;
      if (!el) return;
      const p = (time - domain[0]) / Math.max(1, domain[1] - domain[0]);
      const w = el.clientWidth;
      if (headRef.current) headRef.current.style.transform = `translateX(${p * w}px)`;
      if (playedRef.current) playedRef.current.style.width = `${p * w}px`;
      if (playedInnerRef.current) playedInnerRef.current.style.width = `${w}px`;
    };
    apply(clock.getState().time);
    const unsub = clock.subscribe((st) => apply(st.time));
    const ro = new ResizeObserver(() => apply(clock.getState().time));
    if (scrubRef.current) ro.observe(scrubRef.current);
    return () => {
      unsub();
      ro.disconnect();
    };
  }, [domain, vehicles]);

  const timeAt = useCallback(
    (clientX: number) => {
      const el = scrubRef.current;
      if (!el) return domain[0];
      const r = el.getBoundingClientRect();
      const p = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
      return Math.round((domain[0] + p * (domain[1] - domain[0])) / 60) * 60;
    },
    [domain],
  );

  const dragging = useRef(false);
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    clockActions.seek(timeAt(e.clientX));
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (dragging.current) clockActions.seek(timeAt(e.clientX));
  };
  const onPointerUp = () => {
    dragging.current = false;
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 60 : 300;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') clockActions.step(-step);
    else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') clockActions.step(step);
    else if (e.key === 'Home') clockActions.seek(domain[0]);
    else if (e.key === 'End') clockActions.seek(domain[1]);
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const ticks = useMemo(() => {
    const out: { label: string; p: number }[] = [];
    const first = Math.ceil(domain[0] / 10800) * 10800;
    for (let h = first; h < domain[1]; h += 10800) {
      out.push({ label: formatClock(h), p: (h - domain[0]) / (domain[1] - domain[0]) });
    }
    return out;
  }, [domain]);

  const time = minute * 60;
  const formatCount = useCallback((n: number) => formatNumber(Math.round(n), lang), [lang]);

  return (
    <Surface className={s.bar} role="group" aria-label={t('time.scrubber')} data-testid="time-control">
      <button
        type="button"
        className={s.play}
        onClick={clockActions.toggle}
        aria-label={playing ? t('time.pause') : t('time.play')}
        aria-keyshortcuts="Space"
        data-testid="play-toggle"
      >
        {playing ? <Pause strokeWidth={0} /> : <Play strokeWidth={0} style={{ marginLeft: 2 }} />}
      </button>

      <div className={s.readout}>
        <span className={s.time} data-testid="clock">
          {formatClock(time)}
          {isNextDay(time) ? <span className={s.nextDay}>{t('time.nextDay')}</span> : null}
        </span>
        <span className={s.count} data-testid="bus-count">
          {vehicles ? (
            <>
              <strong>
                <AnimatedNumber value={inService} format={formatCount} duration={300} />
              </strong>{' '}
              {t('time.inService')}
            </>
          ) : (
            <Skeleton width={72} height={10} />
          )}
        </span>
      </div>

      <div
        ref={scrubRef}
        className={s.scrubber}
        role="slider"
        tabIndex={0}
        aria-label={t('time.scrubber')}
        aria-valuemin={domain[0]}
        aria-valuemax={domain[1]}
        aria-valuenow={time}
        aria-valuetext={formatClock(time)}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
        data-testid="scrubber"
      >
        {vehicles ? (
          <>
            <div className={s.hist} title={t('time.histogramLabel')}>
              <Histogram series={vehicles.series} max={max} />
            </div>
            <div className={s.played} ref={playedRef}>
              <div ref={playedInnerRef}>
                <Histogram series={vehicles.series} max={max} />
              </div>
            </div>
          </>
        ) : query.isError ? null : (
          <Skeleton height={20} style={{ position: 'absolute', top: 6 }} />
        )}
        <div className={s.baseline} />
        <div className={s.ticks}>
          {ticks.map((tk) => (
            <span key={tk.label + tk.p} style={{ left: `${tk.p * 100}%` }}>
              {tk.label}
            </span>
          ))}
        </div>
        <div className={s.head} ref={headRef} />
      </div>

      <div className={s.controls}>
        <SegmentedControl<`${Speed}`>
          size="sm"
          label={t('time.speed')}
          value={`${speed}`}
          onChange={(v) => clockActions.setSpeed(Number(v) as Speed)}
          options={SPEEDS.map((sp) => ({ value: `${sp}` as `${Speed}`, label: `${sp}×` }))}
        />
        <span className={s.divider} />
        <Select<DayType>
          size="sm"
          variant="ghost"
          side="top"
          label={t('time.day')}
          value={day}
          onChange={(d) => set({ day: d })}
          options={DAY_TYPES.map((d) => ({ value: d, label: t(`day.${d}`) }))}
        />
      </div>
    </Surface>
  );
}
