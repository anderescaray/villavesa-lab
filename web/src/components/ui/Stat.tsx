import { ArrowDownRight, ArrowUpRight } from 'lucide-react';
import { cx } from './Button';
import { AnimatedNumber } from './AnimatedNumber';
import s from './Stat.module.css';

export interface StatProps {
  label: string;
  value: number | null | undefined;
  format: (n: number) => string;
  unit?: string;
  /** Signed change vs baseline. */
  delta?: number | null;
  formatDelta?: (n: number) => string;
  /** Whether a positive delta is good (green) — e.g. false for travel time. */
  higherIsBetter?: boolean;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function Stat({
  label,
  value,
  format,
  unit,
  delta,
  formatDelta,
  higherIsBetter = true,
  size = 'md',
  className,
}: StatProps) {
  const hasDelta = delta !== null && delta !== undefined && Number.isFinite(delta);
  const good = hasDelta && (higherIsBetter ? delta > 0 : delta < 0);
  const tone = !hasDelta || delta === 0 ? s.flat : good ? s.up : s.down;
  return (
    <div className={cx(s.stat, s[size], className)}>
      <span className={s.label}>{label}</span>
      <span className={s.valueRow}>
        <AnimatedNumber className={s.value} value={value} format={format} />
        {unit ? <span className={s.unit}>{unit}</span> : null}
        {hasDelta ? (
          <span className={cx(s.delta, tone)}>
            {delta > 0 ? (
              <ArrowUpRight size={12} strokeWidth={2} aria-hidden />
            ) : delta < 0 ? (
              <ArrowDownRight size={12} strokeWidth={2} aria-hidden />
            ) : null}
            {(formatDelta ?? format)(Math.abs(delta))}
          </span>
        ) : null}
      </span>
    </div>
  );
}
