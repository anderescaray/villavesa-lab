import { RotateCw, X } from 'lucide-react';
import { useCallback } from 'react';
import type { IsochroneMode } from '@/api/types';
import { useApp } from '@/app/store';
import {
  AnimatedNumber,
  Button,
  IconButton,
  SegmentedControl,
  Skeleton,
  Surface,
} from '@/components/ui';
import { poiLabel, useT } from '@/i18n';
import { formatClock, formatCompact, formatNumber } from '@/lib/format';
import { ISO_COLORS } from '@/lib/palettes';
import { CUTOFFS, ISO_WINDOW, useIsochroneResult } from './useIsochroneRequest';
import s from './IsochroneCard.module.css';

const POI_ORDER = [
  'hospital',
  'health_centre',
  'university',
  'industrial_estate',
  'city_centre',
  'secondary_school',
  'supermarket',
];

export function IsochroneCard() {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const theme = useApp((st) => st.theme);
  const origin = useApp((st) => (st.view === 'accessibility' || st.view === 'scenario' ? null : st.isoOrigin));
  const day = useApp((st) => st.day);
  const start = useApp((st) => st.isoStart);
  const mode = useApp((st) => st.isoMode);
  const set = useApp((st) => st.set);
  const { data, query } = useIsochroneResult();
  const fmtPop = useCallback((n: number) => formatCompact(Math.round(n), lang), [lang]);
  const fmtArea = useCallback((n: number) => formatNumber(n, lang, 1), [lang]);

  if (!origin) return null;
  const loading = !data && query.isFetching;
  const error = query.isError && !query.isFetching;
  const colors = ISO_COLORS[theme];
  const categories = data
    ? POI_ORDER.filter((c) => data.isochrones.some((i) => c in i.pois)).concat(
        Object.keys(data.isochrones.at(-1)?.pois ?? {}).filter((c) => !POI_ORDER.includes(c)),
      )
    : [];

  return (
    <Surface
      className={s.card}
      role="region"
      aria-label={t('iso.title')}
      data-testid="iso-card"
      aria-busy={query.isFetching}
    >
      <div className={s.header}>
        <div>
          <h2 className={s.title}>{t('iso.title')}</h2>
          <div className={s.subtitle}>
            {t('iso.subtitle', { day: t(`day.${day}`), time: formatClock(start) })}
          </div>
        </div>
        <IconButton
          label={t('iso.close')}
          shortcut="Esc"
          size="sm"
          onClick={() => set({ isoOrigin: null })}
        >
          <X strokeWidth={1.5} />
        </IconButton>
      </div>
      <div className={s.mode}>
        <SegmentedControl<IsochroneMode>
          fullWidth
          size="sm"
          label={t('iso.modeLabel')}
          value={mode}
          onChange={(m) => set({ isoMode: m })}
          options={[
            { value: 'transit', label: t('iso.transit') },
            { value: 'walk', label: t('iso.walk') },
          ]}
        />
      </div>

      {error ? (
        <div className={s.error} role="alert">
          {t('iso.error')}
          <Button size="sm" onClick={() => void query.refetch()}>
            <RotateCw strokeWidth={1.75} />
            {t('iso.retry')}
          </Button>
        </div>
      ) : (
        <>
          <ul className={s.bands} aria-label={t('iso.legend')}>
            {CUTOFFS.map((cut, k) => {
              const iso = data?.isochrones.find((i) => i.cutoff === cut);
              return (
                <li key={cut} className={s.band} data-testid={`iso-band-${cut / 60}`}>
                  <span className={s.cut}>
                    <span className={s.swatch} style={{ background: colors[k] }} aria-hidden />
                    {cut / 60} {t('common.min')}
                  </span>
                  <span className={s.metric}>
                    <span className={s.metricLabel}>{t('iso.population')}</span>
                    {loading ? (
                      <Skeleton width={56} height={14} />
                    ) : (
                      <AnimatedNumber
                        className={s.metricValue}
                        value={iso?.population}
                        format={fmtPop}
                      />
                    )}
                  </span>
                  <span className={s.metric}>
                    <span className={s.metricLabel}>{t('iso.area')}</span>
                    {loading ? (
                      <Skeleton width={48} height={14} />
                    ) : (
                      <span className={s.metricValue}>
                        <AnimatedNumber value={iso?.area_km2} format={fmtArea} />
                        <span className={s.metricUnit}>{t('common.km2')}</span>
                      </span>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
          <div className={s.section}>
            <h3 className={s.sectionTitle}>{t('iso.destinations')}</h3>
            {loading || !data ? (
              <div style={{ display: 'grid', gap: 8 }}>
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} height={12} />
                ))}
              </div>
            ) : (
              <table className={s.table}>
                <thead>
                  <tr>
                    <th scope="col">
                      <span className="sr-only">{t('iso.destinations')}</span>
                    </th>
                    {CUTOFFS.map((c) => (
                      <th key={c} scope="col">
                        {c / 60}′
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {categories.map((cat) => (
                    <tr key={cat}>
                      <td>{poiLabel(t, cat)}</td>
                      {CUTOFFS.map((c) => {
                        const v = data.isochrones.find((i) => i.cutoff === c)?.pois[cat] ?? 0;
                        return (
                          <td key={c} className={v === 0 ? s.zero : undefined}>
                            {formatNumber(v, lang)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <p className={s.foot}>
            {data ? `${t('iso.reachedStops', { n: data.reached_stops.length })}. ` : ''}
            {t('iso.method', { from: formatClock(start), to: formatClock(start + ISO_WINDOW) })}
          </p>
        </>
      )}
    </Surface>
  );
}
