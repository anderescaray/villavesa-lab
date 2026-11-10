import { useMemo, useState } from 'react';

export interface SparkBarsProps {
  values: number[];
  width: number;
  height: number;
  color?: string;
  /** index to emphasise (e.g. the current hour) */
  highlight?: number;
  label: string;
  className?: string;
  /** Domain maximum (shared scale across rows); defaults to max(values). */
  max?: number;
  gap?: number;
}

/** Tiny bar chart (one bar per bucket). Pure SVG; meaning is in the aria-label. */
export function SparkBars({
  values,
  width,
  height,
  color = 'currentColor',
  highlight,
  label,
  className,
  max,
  gap = 1,
}: SparkBarsProps) {
  const m = max ?? Math.max(1, ...values);
  const n = Math.max(1, values.length);
  const bw = Math.max(1, (width - gap * (n - 1)) / n);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className={className}>
      {values.map((v, i) => {
        const h = v > 0 ? Math.max(1.5, (v / m) * height) : 0;
        return (
          <rect
            key={i}
            x={i * (bw + gap)}
            y={height - h}
            width={bw}
            height={h}
            rx={Math.min(1, bw / 2)}
            fill={color}
            opacity={highlight === undefined || highlight === i ? 1 : 0.38}
          />
        );
      })}
    </svg>
  );
}

export interface BarChartProps {
  values: number[];
  labels: string[];
  height?: number;
  color?: string;
  highlight?: number;
  formatValue: (v: number) => string;
  label: string;
  /** label every N ticks */
  tickEvery?: number;
}

/**
 * Small column chart with hover tooltip and sparse x labels (hairline baseline, no grid).
 * Bars have 4 px rounded tops anchored on the baseline and a 2 px surface gap.
 */
export function MiniBarChart({
  values,
  labels,
  height = 64,
  color = 'var(--text)',
  highlight,
  formatValue,
  label,
  tickEvery = 6,
}: BarChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const max = useMemo(() => Math.max(1, ...values), [values]);
  const n = values.length;
  const W = 100;
  const bw = W / n;
  const active = hover ?? highlight;
  return (
    <div style={{ position: 'relative' }}>
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={label}
        onMouseLeave={() => setHover(null)}
        style={{ display: 'block', overflow: 'visible' }}
      >
        {values.map((v, i) => {
          const h = v > 0 ? Math.max(1.5, (v / max) * (height - 2)) : 0;
          return (
            <g key={i} onMouseEnter={() => setHover(i)}>
              <rect x={i * bw} y={0} width={bw} height={height} fill="transparent" />
              <rect
                x={i * bw + bw * 0.12}
                y={height - h}
                width={bw * 0.76}
                height={h}
                fill={color}
                opacity={active === undefined || active === null || active === i ? 0.9 : 0.32}
              />
            </g>
          );
        })}
        <line x1={0} x2={W} y1={height - 0.5} y2={height - 0.5} stroke="var(--border-strong)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      </svg>
      <div
        aria-hidden
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${n}, 1fr)`,
          marginTop: 4,
          color: 'var(--text-tertiary)',
          fontSize: 'var(--text-11)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {labels.map((l, i) => (
          <span key={i} style={{ whiteSpace: 'nowrap', overflow: 'visible' }}>
            {i % tickEvery === 0 ? l : ''}
          </span>
        ))}
      </div>
      {active !== null && active !== undefined && hover !== null ? (
        <div
          role="tooltip"
          style={{
            position: 'absolute',
            left: `${((active + 0.5) / n) * 100}%`,
            top: -30,
            transform: 'translateX(-50%)',
            padding: '3px 6px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--text)',
            color: 'var(--bg)',
            fontSize: 'var(--text-11)',
            fontWeight: 500,
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {labels[active]} · {formatValue(values[active] ?? 0)}
        </div>
      ) : null}
    </div>
  );
}
