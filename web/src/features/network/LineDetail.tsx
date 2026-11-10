import { ArrowLeft } from 'lucide-react';
import { useEffect, useMemo, type CSSProperties } from 'react';
import { useApp } from '@/app/store';
import { Button, LineBadge, MiniBarChart, SegmentedControl, Skeleton } from '@/components/ui';
import { useClockMinute } from '@/features/time/clock';
import { useT } from '@/i18n';
import { displayName, formatClock, formatCurrency, formatDuration, formatMinutes, formatNumber } from '@/lib/format';
import { boundsOf, fitBounds } from '@/map/camera';
import { useMapContext } from '@/map/MapContext';
import { useNetworkModel, useVehicleModel } from './model';
import s from './LineDetail.module.css';

const CHART_FROM = 5;
const CHART_TO = 26;

export function LineDetail({ routeId }: { routeId: string }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const theme = useApp((st) => st.theme);
  const direction = useApp((st) => st.selectedDirection);
  const set = useApp((st) => st.set);
  const selectRoute = useApp((st) => st.selectRoute);
  const selectStop = useApp((st) => st.selectStop);
  const { model } = useNetworkModel();
  const { model: vehicles } = useVehicleModel();
  const { map } = useMapContext();
  const minute = useClockMinute();
  const route = model?.routeById.get(routeId);

  // camera: fit the whole line (both directions) once per selection
  useEffect(() => {
    if (!map || !route) return;
    const b = boundsOf(route.patterns.flatMap((p) => p.path));
    if (b) fitBounds(map, b);
  }, [map, route]);

  const pattern = route?.patterns.find((p) => p.direction === direction) ?? route?.patterns[0];
  const perHour = vehicles?.perHour.get(routeId);
  const chart = useMemo(() => (perHour ?? []).slice(CHART_FROM, CHART_TO), [perHour]);
  const chartLabels = useMemo(
    () => chart.map((_, i) => formatClock((i + CHART_FROM) * 3600)),
    [chart],
  );

  const back = (
    <div className={s.top}>
      <Button variant="ghost" size="sm" onClick={() => selectRoute(null)} data-testid="line-back">
        <ArrowLeft strokeWidth={1.75} />
        {t('line.back')}
      </Button>
    </div>
  );

  if (!model) {
    return (
      <div className={s.root}>
        {back}
        <div className={s.header}>
          <Skeleton width={180} height={18} />
          <Skeleton width={120} height={12} />
        </div>
      </div>
    );
  }
  if (!route || !pattern) {
    return (
      <div className={s.root}>
        {back}
        <p className={s.notice}>{t('line.notInDay')}</p>
      </div>
    );
  }

  const st = route.stats;
  const lineColor = model.mapColor(route.id, theme);
  const mins = (sec: number | null) => (sec === null ? '—' : formatMinutes(sec, lang));

  return (
    <div className={s.root} style={{ '--line-color': lineColor } as CSSProperties} data-testid="line-detail">
      {back}
      <div className={s.header}>
        <div className={s.identity}>
          <LineBadge size="lg" shortName={route.short_name} color={route.color} textColor={route.text_color} />
          <div style={{ minWidth: 0 }}>
            <h1 className={s.name}>{displayName(route.long_name)}</h1>
            <div className={s.sub}>
              {t(`line.kind.${route.kind}`)} · {t('line.nStops', { n: pattern.stop_ids.length })} ·{' '}
              {formatNumber(st.length_km, lang, 1)} {t('common.km')}
            </div>
          </div>
        </div>
        {route.patterns.length > 1 ? (
          <SegmentedControl<string>
            fullWidth
            label={t('line.direction')}
            value={String(pattern.direction)}
            onChange={(v) => set({ selectedDirection: Number(v) })}
            options={route.patterns.map((p) => ({
              value: String(p.direction),
              label: (
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {t('line.towards', { headsign: p.headsign })}
                </span>
              ),
            }))}
          />
        ) : null}
      </div>

      <section className={s.section}>
        <h2 className={s.sectionTitle}>{t('line.service')}</h2>
        <dl className={s.dl}>
          <dt>{t('line.headwayPeak')}</dt>
          <dd>
            {mins(st.headway_peak)}
            <span className={s.unit}>{t('common.min')}</span>
          </dd>
          <dt>{t('line.headwayOffpeak')}</dt>
          <dd>
            {mins(st.headway_offpeak)}
            <span className={s.unit}>{t('common.min')}</span>
          </dd>
          <dt>{t('line.firstLast')}</dt>
          <dd>
            {formatClock(st.first_dep)} – {formatClock(st.last_dep)}
          </dd>
          <dt>{t('line.runTime')}</dt>
          <dd>{formatDuration(st.run_time)}</dd>
          <dt>{t('line.speed')}</dt>
          <dd>
            {formatNumber(st.speed_kmh, lang, 1)}
            <span className={s.unit}>{t('common.kmh')}</span>
          </dd>
        </dl>
      </section>

      <section className={s.section}>
        <h2 className={s.sectionTitle}>{t('line.departures')}</h2>
        <MiniBarChart
          values={chart}
          labels={chartLabels}
          height={56}
          color={lineColor}
          highlight={Math.floor(minute / 60) - CHART_FROM}
          formatValue={(v) => formatNumber(v, lang)}
          label={t('line.departures')}
          tickEvery={4}
        />
      </section>

      <section className={s.section}>
        <h2 className={s.sectionTitle}>{t('line.operations')}</h2>
        <dl className={s.dl}>
          <dt>{t('line.fleet')}</dt>
          <dd>{t('line.buses', { n: st.fleet })}</dd>
          <dt>{t('line.busHours')}</dt>
          <dd>{formatNumber(st.bus_hours, lang, 1)}</dd>
          <dt>{t('line.trips')}</dt>
          <dd>{formatNumber(st.trips, lang)}</dd>
          <dt>{t('line.km')}</dt>
          <dd>{formatNumber(st.km, lang)}</dd>
          <dt>{t('line.cost')}</dt>
          <dd>{formatCurrency(st.cost_eur, lang)}</dd>
        </dl>
      </section>

      <section className={s.section}>
        <h2 className={s.sectionTitle}>
          {t('line.stops')} · {pattern.stop_ids.length}
        </h2>
        <ol className={s.stops} data-testid="line-stops">
          {pattern.stop_ids.map((id, i) => {
            const stop = model.stopById.get(id);
            const terminus = i === 0 || i === pattern.stop_ids.length - 1;
            const others = (stop?.routes ?? []).filter((r) => r !== route.id).slice(0, 4);
            return (
              <li
                key={`${id}-${i}`}
                className={[i === 0 && s.first, i === pattern.stop_ids.length - 1 && s.last, terminus && s.terminus]
                  .filter(Boolean)
                  .join(' ')}
              >
                <button
                  type="button"
                  className={s.stop}
                  onClick={() => {
                    selectStop(id);
                    if (map && stop) map.easeTo({ center: [stop.lon, stop.lat], zoom: Math.max(map.getZoom(), 15), duration: 500 });
                  }}
                >
                  <span className={s.track} aria-hidden>
                    <span className={s.dot} />
                  </span>
                  <span className={s.stopName}>{stop?.name ?? id}</span>
                  <span className={s.transfers}>
                    {others.map((rid) => {
                      const r = model.routeById.get(rid);
                      return r ? (
                        <LineBadge key={rid} size="sm" shortName={r.short_name} color={r.color} textColor={r.text_color} />
                      ) : null;
                    })}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}
