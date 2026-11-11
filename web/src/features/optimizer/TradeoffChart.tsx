import { useMemo, useState } from 'react';
import type { TradeoffPoint, TradeoffResult } from '@/api/optimizer';
import { useApp } from '@/app/store';
import { useT } from '@/i18n';
import { formatNumber, formatPercent } from '@/lib/format';
import { formatMin1, formatSigned, formatSignedPct } from './fmt';
import { linearScale, niceTicks, yDomain } from './model';
import s from './Optimizer.module.css';

const W = 328;
const H = 196;
const M = { l: 46, r: 12, t: 16, b: 30 };

export interface TradeoffChartProps {
  result: TradeoffResult;
  /** budget of the previewed point, if any */
  selected: number | null;
  onSelect: (budget: number) => void;
}

/**
 * Accessibility gain versus budget. x = fleet (or bus-hours), y = change versus today in %,
 * so today's network is the red point at (today's budget, 0). The dashed bracket at today's
 * budget is the "same buses, better network" gap.
 */
const TIP_W = 188;
/** Side of the point the tooltip sits on. The curve rises to the right, so a tooltip to the right
 * goes below the point and one to the left goes above it; near both edges it centres above. */
function tipSide(px: number, py: number): 'right' | 'left' | 'above' | 'below' {
  if (px + 12 + TIP_W <= W) return 'right';
  if (px - 12 - TIP_W >= 0) return 'left';
  return py < H * 0.5 ? 'below' : 'above';
}

export function TradeoffChart({ result, selected, onSelect }: TradeoffChartProps) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const [hover, setHover] = useState<number | null>(null);
  const pts = useMemo(
    () => [...result.points].sort((a, b) => a.budget - b.budget),
    [result.points],
  );
  const today = result.baseline.budget;
  const geo = useMemo(() => {
    const xs = pts.map((p) => p.budget).concat(today);
    const x0 = Math.min(...xs);
    const x1 = Math.max(...xs);
    const pad = (x1 - x0) * 0.04 || 1;
    const x = linearScale([x0 - pad, x1 + pad], [M.l, W - M.r]);
    const [lo, hi] = yDomain(pts.map((p) => p.objective_pct));
    const y = linearScale([lo, hi], [H - M.b, M.t]);
    return { x, y, yTicks: niceTicks(lo, hi, 4) };
  }, [pts, today]);
  const { x, y } = geo;
  const same = pts.find((p) => Math.abs(p.budget - today) < 1e-6);
  const kind = result.budget_kind;
  const fmtBudget = (n: number) => formatNumber(n, lang, kind === 'fleet' ? 0 : 0);
  const path = pts
    .map((p, i) => `${i ? 'L' : 'M'}${x(p.budget).toFixed(1)},${y(p.objective_pct).toFixed(1)}`)
    .join('');
  const hovered = hover !== null ? pts[hover] : null;
  const label = (p: TradeoffPoint) =>
    `${kind === 'fleet' ? t('opt.tipBudgetFleet', { n: fmtBudget(p.budget) }) : t('opt.tipBudgetHours', { n: fmtBudget(p.budget) })}: ${t('opt.tipAcc', { pct: formatSignedPct(p.objective_pct, lang) })}`;
  const xLabels = [pts[0]!.budget, today, pts[pts.length - 1]!.budget].filter(
    (v, i, a) => a.indexOf(v) === i,
  );

  return (
    <div className={s.chartWrap} onMouseLeave={() => setHover(null)}>
      <svg
        className={s.chart}
        viewBox={`0 0 ${W} ${H}`}
        role="group"
        aria-label={t('opt.tradeAria')}
        data-testid="tradeoff-chart"
      >
        {geo.yTicks.map((v) => (
          <g key={v}>
            <line
              className={v === 0 ? s.axisZero : s.axis}
              x1={M.l}
              x2={W - M.r}
              y1={y(v)}
              y2={y(v)}
            />
            <text className={s.tick} x={M.l - 6} y={y(v) + 3.5} textAnchor="end">
              {`${formatSigned(v, lang, Number.isInteger(v) ? 0 : 1)}\u00a0%`}
            </text>
          </g>
        ))}
        {xLabels.map((v) => (
          <text
            key={v}
            className={s.tick}
            x={x(v)}
            y={H - M.b + 16}
            textAnchor="middle"
            style={v === today ? { fill: 'var(--text)', fontWeight: 600 } : undefined}
          >
            {fmtBudget(v)}
          </text>
        ))}
        <text className={s.tick} x={W - M.r} y={H - 2} textAnchor="end">
          {kind === 'fleet' ? t('opt.tradeXFleet') : t('opt.tradeXHours')}
        </text>
        {same && same.objective_pct > 0.05 ? (
          <g>
            <line
              className={s.gap}
              x1={x(today)}
              x2={x(today)}
              y1={y(0)}
              y2={y(same.objective_pct)}
            />
            <text
              className={s.gapLabel}
              x={x(today) + 6}
              y={(y(0) + y(same.objective_pct)) / 2 + 3}
            >
              {formatSignedPct(same.objective_pct, lang)}
            </text>
          </g>
        ) : null}
        <path className={s.chartLine} d={path} />
        {pts.map((p, i) => {
          const active = selected === p.budget;
          return (
            <g
              key={p.budget}
              className={s.point}
              data-active={active}
              data-testid="tradeoff-point"
              role="button"
              tabIndex={0}
              aria-label={label(p)}
              aria-pressed={active}
              onMouseEnter={() => setHover(i)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              onClick={() => onSelect(p.budget)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelect(p.budget);
                }
              }}
            >
              <circle className={s.pointHit} cx={x(p.budget)} cy={y(p.objective_pct)} r={14} />
              <circle className={s.pointRing} cx={x(p.budget)} cy={y(p.objective_pct)} r={8} />
              <circle
                className={s.pointDot}
                cx={x(p.budget)}
                cy={y(p.objective_pct)}
                r={hover === i || active ? 5 : 4}
              />
            </g>
          );
        })}
        <circle className={s.todayDot} cx={x(today)} cy={y(0)} r={5} data-testid="tradeoff-today" />
      </svg>
      {hovered ? (
        <div
          className={s.tip}
          data-side={tipSide(x(hovered.budget), y(hovered.objective_pct))}
          role="status"
          style={{
            left: `${(x(hovered.budget) / W) * 100}%`,
            top: `${(y(hovered.objective_pct) / H) * 100}%`,
          }}
        >
          <strong>
            {kind === 'fleet'
              ? t('opt.tipBudgetFleet', { n: fmtBudget(hovered.budget) })
              : t('opt.tipBudgetHours', { n: fmtBudget(hovered.budget) })}
          </strong>
          <span>{t('opt.tipAcc', { pct: formatSignedPct(hovered.objective_pct, lang) })}</span>
          <span>{t('opt.tipTime', { t: formatMin1(hovered.mean_travel_time, lang) })}</span>
          {hovered.share_within.hospital !== undefined ? (
            <span>
              {t('opt.tipHospital', { share: formatPercent(hovered.share_within.hospital, lang) })}
            </span>
          ) : null}
        </div>
      ) : null}
      <div className={s.legendRow} aria-hidden>
        <span>
          <i className={`${s.key} ${s.keyToday}`} />
          {t('opt.tradeToday')}
        </span>
        <span>
          <i className={`${s.key} ${s.keyOpt}`} />
          {t('opt.tradeOpt')}
        </span>
      </div>
    </div>
  );
}
