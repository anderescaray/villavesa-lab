/**
 * Live diff vs. baseline (floating surface, right of the map): people gaining / losing access,
 * travel time, accessibility index, fleet, bus-hours, cost, under-served residents and the
 * per-destination change; plus the delta-map toggle and legend. Previous numbers stay visible
 * (dimmed) while the next evaluation computes.
 */
import { ArrowDownRight, ArrowUpRight, CloudOff, TriangleAlert } from 'lucide-react';
import { useCallback } from 'react';
import { useApp } from '@/app/store';
import { AnimatedNumber, Select, Skeleton, Stat, Surface, Switch } from '@/components/ui';
import { useScenario } from '@/features/scenario/store';
import { poiLabel, useT } from '@/i18n';
import { formatClock, formatCurrency, formatNumber, formatPercent } from '@/lib/format';
import { DIVERGING } from '@/lib/palettes';
import { DELTA_EDGES } from './EditorLayers';
import { useEditor } from './state';
import { EVAL_WINDOWS, EVAL_WINDOW_S, useLiveEvaluation } from './useLiveEvaluation';
import s from './Editor.module.css';

const sign = (n: number) => (n > 0 ? '+' : n < 0 ? '−' : '±');

export function ImpactCard() {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const theme = useApp((st) => st.theme);
  const active = useApp((st) => st.view === 'scenario');
  const hasEdits = useScenario((st) => st.edits.length > 0);
  const peek = useScenario((st) => st.peekBaseline);
  const showDelta = useEditor((st) => st.showDelta);
  const windowStart = useEditor((st) => st.windowStart);
  const setEd = useEditor((st) => st.set);
  const { data, stale, computing, error, threshold } = useLiveEvaluation();

  const fmtInt = useCallback((n: number) => formatNumber(Math.round(n), lang), [lang]);
  const fmtSigned = useCallback(
    (n: number) => `${sign(Math.round(n))}${formatNumber(Math.abs(Math.round(n)), lang)}`,
    [lang],
  );
  const fmtSignedSec = useCallback(
    (n: number) =>
      Math.abs(n) >= 90
        ? `${sign(n)}${formatNumber(Math.abs(n) / 60, lang, 1)} min`
        : `${sign(Math.round(n))}${formatNumber(Math.abs(Math.round(n)), lang)} s`,
    [lang],
  );
  const fmtSigned1 = useCallback(
    (n: number) => `${sign(n)}${formatNumber(Math.abs(n), lang, 1)}`,
    [lang],
  );
  const fmtPct = useCallback(
    (n: number) => `${sign(n)}${formatNumber(Math.abs(n), lang, 1)} %`,
    [lang],
  );
  const fmtEur = useCallback(
    (n: number) => `${sign(Math.round(n))}${formatCurrency(Math.abs(n), lang)}`,
    [lang],
  );

  if (!active || !hasEdits || peek) return null;
  const d = data?.delta;
  const pal = DIVERGING[theme];
  const ramp = [...pal.pos].reverse().concat([...pal.neg].reverse());

  return (
    <Surface className={s.impact} data-testid="impact-card" aria-busy={computing}>
      <div className={s.impactHead}>
        <span className={s.impactTitle}>{t('editor.impact.title')}</span>
        <Select<`${number}`>
          size="sm"
          variant="ghost"
          label={t('editor.impact.window')}
          value={`${windowStart}`}
          onChange={(v) => setEd({ windowStart: Number(v) })}
          options={EVAL_WINDOWS.map((w) => ({
            value: `${w}` as `${number}`,
            label: `${formatClock(w)}–${formatClock(w + EVAL_WINDOW_S)}`,
          }))}
        />
      </div>
      <div className={s.impactScroll}>
        {error ? (
          <div className={s.notice} role="alert" data-testid="impact-error">
            <CloudOff strokeWidth={1.75} />
            <span>
              {t('editor.impact.error')} <span className={s.error}>{error.message}</span>
            </span>
          </div>
        ) : null}
        {!d ? (
          error ? null : <ImpactSkeleton />
        ) : (
          <div className={s.impactBody} data-stale={stale}>
            <div className={s.people}>
              <div>
                <span className={s.label}>{t('editor.impact.gaining')}</span>
                <span className={`${s.bigNum}`} data-testid="people-gaining">
                  <ArrowUpRight className={s.gain} strokeWidth={2} aria-hidden />
                  <AnimatedNumber value={d.people_gaining} format={fmtInt} />
                </span>
              </div>
              <div>
                <span className={s.label}>{t('editor.impact.losing')}</span>
                <span className={s.bigNum} data-testid="people-losing">
                  <ArrowDownRight className={s.loss} strokeWidth={2} aria-hidden />
                  <AnimatedNumber value={d.people_losing} format={fmtInt} />
                </span>
              </div>
            </div>
            <div className={s.statGrid}>
              <Stat
                size="sm"
                label={t('editor.impact.travelTime')}
                value={d.mean_travel_time}
                format={fmtSignedSec}
                delta={null}
              />
              <Stat
                size="sm"
                label={t('editor.impact.access')}
                value={d.objective_pct}
                format={fmtPct}
              />
              <Stat size="sm" label={t('editor.impact.fleet')} value={d.fleet} format={fmtSigned} />
              <Stat
                size="sm"
                label={t('editor.impact.busHours')}
                value={d.bus_hours}
                format={fmtSigned1}
              />
              <Stat
                size="sm"
                label={t('editor.impact.costYear')}
                value={d.cost_eur_year}
                format={fmtEur}
              />
              <Stat
                size="sm"
                label={t('editor.impact.underserved')}
                value={d.underserved_population}
                format={fmtSigned}
              />
            </div>
            <div className={s.cats}>
              <div className={s.catRow}>
                <span className={s.eyebrow}>
                  {t('editor.impact.within', { min: threshold / 60 })}
                </span>
                <span />
                <span className={s.tag}>{t('editor.impact.residents')}</span>
              </div>
              {Object.entries(d.categories)
                .sort((a, b) => Math.abs(b[1].pop_within) - Math.abs(a[1].pop_within))
                .map(([id, c]) => (
                  <CatRow key={id} label={poiLabel(t, id)} value={c.pop_within} share={c.share_within} fmt={fmtSigned} lang={lang} />
                ))}
            </div>
            {data.warnings.length ? (
              <div className={s.notice} style={{ marginTop: 12 }} role="status">
                <TriangleAlert strokeWidth={1.75} />
                <span>{data.warnings.slice(0, 3).join(' · ')}</span>
              </div>
            ) : null}
          </div>
        )}
        <div style={{ marginTop: 16 }}>
          <Switch checked={showDelta} onChange={(v) => setEd({ showDelta: v })}>
            <span className={s.label}>{t('editor.impact.mapToggle')}</span>
          </Switch>
          {showDelta ? (
            <div aria-label={t('editor.impact.legend')} role="img">
              <div className={s.legendRamp}>
                {ramp.map((c) => (
                  <span key={c} style={{ background: c }} />
                ))}
              </div>
              <div className={s.legendLabels}>
                <span>
                  {t('editor.impact.faster')} −{DELTA_EDGES[2] / 60} min
                </span>
                <span>±{DELTA_EDGES[0]} s</span>
                <span>
                  +{DELTA_EDGES[2] / 60} min {t('editor.impact.slower')}
                </span>
              </div>
            </div>
          ) : null}
        </div>
      </div>
      <div className={s.foot}>
        <span>{computing ? t('editor.impact.computing') : t('editor.impact.vsBaseline')}</span>
        {data ? <span>{formatNumber(data.elapsed_ms, lang)} ms</span> : null}
      </div>
    </Surface>
  );
}

function CatRow({
  label,
  value,
  share,
  fmt,
  lang,
}: {
  label: string;
  value: number;
  share: number;
  fmt: (n: number) => string;
  lang: 'es' | 'en' | 'eu';
}) {
  const w = Math.min(50, Math.abs(share) * 100 * 25); // 2 % of the population fills half
  return (
    <div className={s.catRow} title={formatPercent(share, lang, 2)}>
      <span className={s.stopName}>{label}</span>
      <span className={s.bar} aria-hidden>
        {value !== 0 ? (
          <span
            className={s.barFill}
            style={{
              left: value > 0 ? '50%' : `${50 - w}%`,
              width: `${Math.max(w, 2)}%`,
              background: value > 0 ? 'var(--positive)' : 'var(--negative)',
            }}
          />
        ) : null}
      </span>
      <span>{value === 0 ? '0' : fmt(value)}</span>
    </div>
  );
}

function ImpactSkeleton() {
  return (
    <div data-testid="impact-skeleton" style={{ display: 'grid', gap: 12 }}>
      <div className={s.people}>
        <Skeleton height={44} />
        <Skeleton height={44} />
      </div>
      <Skeleton height={14} />
      <Skeleton height={14} width="80%" />
      <Skeleton height={14} width="60%" />
    </div>
  );
}
