import { useMemo } from 'react';
import { formatPercent } from '@/lib/format';
import type { Lang } from '@/i18n';
import { curvePoints, shareAt } from './model';
import s from './Accessibility.module.css';

const W = 320;
const H = 136;
const M = { top: 12, right: 8, bottom: 20, left: 34 };
const MAX_T = 3600;

/**
 * Cumulative share of residents reached vs travel time (0–60 min), with the threshold marked.
 * Hand-rolled SVG: one line, a faint area, hairline grid at 0/50/100 %, tabular labels.
 */
export function CumulativeChart({
  curve,
  threshold,
  lang,
  label,
}: {
  curve: [number, number][];
  threshold: number;
  lang: Lang;
  label: string;
}) {
  const iw = W - M.left - M.right;
  const ih = H - M.top - M.bottom;
  const x = (t: number) => M.left + (Math.min(t, MAX_T) / MAX_T) * iw;
  const y = (v: number) => M.top + (1 - v) * ih;
  const pts = useMemo(() => curvePoints(curve).filter(([t]) => t <= MAX_T), [curve]);
  const line = pts.map(([t, v], i) => `${i ? 'L' : 'M'}${x(t).toFixed(1)},${y(v).toFixed(1)}`);
  const area = `${line.join('')}L${x(pts.at(-1)?.[0] ?? 0)},${y(0)}L${x(0)},${y(0)}Z`;
  const atThr = shareAt(curve, threshold);
  const thrX = x(threshold);
  // label in the empty quadrant: above-left while the curve is still rising, below-right once
  // it has flattened near the top (below-left at the right edge)
  const high = (atThr ?? 0) > 0.85;
  const toLeft = !high || thrX > M.left + iw * 0.8;
  return (
    <svg
      className={s.chart}
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label={label}
      data-testid="acc-curve"
    >
      {[0, 0.5, 1].map((v) => (
        <g key={v}>
          <line className={s.grid} x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} />
          <text className={s.axis} x={M.left - 6} y={y(v)} dy="0.32em" textAnchor="end">
            {formatPercent(v, lang)}
          </text>
        </g>
      ))}
      {[0, 15, 30, 45, 60].map((m) => (
        <text
          key={m}
          className={s.axis}
          x={x(m * 60)}
          y={H - 4}
          textAnchor={m === 0 ? 'start' : m === 60 ? 'end' : 'middle'}
        >
          {m === 60 ? '60 min' : m}
        </text>
      ))}
      <path className={s.area} d={area} />
      <path className={s.line} d={line.join('')} />
      <line className={s.thr} x1={thrX} x2={thrX} y1={M.top - 4} y2={y(0)} />
      {atThr !== null ? (
        <>
          <line className={s.thrH} x1={M.left} x2={thrX} y1={y(atThr)} y2={y(atThr)} />
          <circle className={s.dot} cx={thrX} cy={y(atThr)} r={3.5} />
          <text
            className={s.thrLabel}
            x={toLeft ? thrX - 8 : thrX + 8}
            y={y(atThr) + (high ? 16 : -8)}
            textAnchor={toLeft ? 'end' : 'start'}
          >
            {formatPercent(atThr, lang)}
          </text>
        </>
      ) : null}
    </svg>
  );
}
