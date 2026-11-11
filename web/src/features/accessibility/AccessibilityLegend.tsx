import { ACC_METRICS, useApp, type AccMetric } from '@/app/store';
import { Select, Skeleton, Surface } from '@/components/ui';
import { isMessageKey, useT, type TFunction } from '@/i18n';
import { formatNumber } from '@/lib/format';
import type { Lang } from '@/i18n';
import { INCOME_EDGES, JOBS_EDGES, TIME_EDGES, metricScale } from './model';
import { useAccessibility } from './useAccessibility';
import s from './Accessibility.module.css';

function legendDest(t: TFunction, id: string) {
  const key = `acc.legendDest.${id}`;
  return isMessageKey(key) ? t(key) : id.replace(/_/g, ' ');
}

function edgeLabels(metric: AccMetric, lang: Lang): string[] {
  switch (metric) {
    case 'time':
      return TIME_EDGES.map((e) => String(e / 60));
    case 'jobs':
      return JOBS_EDGES.map((e) =>
        formatNumber(e * 100, lang, e * 100 < 10 && (e * 100) % 1 ? 1 : 0),
      );
    case 'income':
      return INCOME_EDGES.map((e) => formatNumber(e / 1000, lang, e % 1000 ? 1 : 0));
    case 'gap':
      return [];
  }
}

/** Floating legend (bottom-left of the map) with the map-metric selector. */
export function AccessibilityLegend() {
  const t = useT();
  const view = useApp((st) => st.view);
  const lang = useApp((st) => st.lang);
  const theme = useApp((st) => st.theme);
  const metric = useApp((st) => st.accMetric);
  const category = useApp((st) => st.accCategory);
  const threshold = useApp((st) => st.accThreshold);
  const set = useApp((st) => st.set);
  const { data } = useAccessibility();
  if (view !== 'accessibility') return null;

  const scale = metricScale(metric, theme, threshold);
  const values = scale.bins.filter((b) => b.kind === 'value');
  const none = scale.bins.find((b) => b.kind === 'none');
  const labels = edgeLabels(metric, lang);
  const subtitle =
    metric === 'time'
      ? t('acc.legend.time', { dest: legendDest(t, category) })
      : metric === 'gap'
        ? t('acc.legend.gap', { min: threshold / 60 })
        : t(`acc.legend.${metric}`);
  const unit =
    metric === 'time' ? 'min' : metric === 'jobs' ? '%' : metric === 'income' ? 'k€' : '';

  return (
    <Surface
      className={s.legend}
      role="group"
      aria-label={t('acc.metricLabel')}
      data-testid="acc-legend"
    >
      <div className={s.legendHead}>
        <Select<AccMetric>
          size="sm"
          variant="ghost"
          side="top"
          label={t('acc.metricLabel')}
          value={metric}
          onChange={(m) => set({ accMetric: m })}
          options={ACC_METRICS.map((m) => ({ value: m, label: t(`acc.metric.${m}`) }))}
        />
      </div>
      <p className={s.legendSub}>{subtitle}</p>
      {!data ? (
        <Skeleton height={28} />
      ) : metric === 'gap' ? (
        <ul className={s.swatches}>
          {scale.bins.map((b, i) => (
            <li key={i}>
              <span className={s.swatch} style={{ background: b.color }} />
              {i === 0
                ? t('acc.legend.within')
                : i === scale.bins.length - 1
                  ? t('acc.legend.overMax')
                  : t('acc.legend.over', { n: i * 10 })}
            </li>
          ))}
        </ul>
      ) : (
        <div className={s.rampWrap}>
          <div className={s.rampRow}>
            <div className={s.ramp} aria-hidden>
              {values.map((b, i) => (
                <span key={i} style={{ background: b.color }} />
              ))}
            </div>
            {none ? (
              <span className={s.noneSwatch} style={{ background: none.color }} aria-hidden />
            ) : null}
          </div>
          <div className={s.rampLabels} data-none={!!none}>
            <div className={s.rampEdges}>
              {labels.map((l, i) => (
                <span key={i} style={{ left: `${((i + 1) / values.length) * 100}%` }}>
                  {l}
                </span>
              ))}
              <span className={s.rampUnit}>{unit}</span>
            </div>
            {none ? (
              <span className={s.noneLabel}>
                {metric === 'time' ? t('acc.unreachable') : t('acc.legend.noData')}
              </span>
            ) : null}
          </div>
        </div>
      )}
      <p className={s.legendNote}>{t('acc.legend.weight')}</p>
    </Surface>
  );
}
