import { Search, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef } from 'react';
import type { Route, RouteKind } from '@/api/types';
import { useApp } from '@/app/store';
import { Kbd, LineBadge, Skeleton, SparkBars, Stat } from '@/components/ui';
import { useClockMinute } from '@/features/time/clock';
import { useT } from '@/i18n';
import { displayName, formatMinutes, formatNumber } from '@/lib/format';
import { headwayAround } from '@/lib/vehicles';
import { LineDetail } from './LineDetail';
import { matchRoute, routeInService, useNetworkModel, useVehicleModel } from './model';
import { NetworkError } from './NetworkError';
import s from './NetworkPanel.module.css';

const KINDS: RouteKind[] = ['day', 'night', 'special'];
const SPARK_FROM = 5;
const SPARK_TO = 26;

export function NetworkPanel() {
  const selected = useApp((st) => st.selectedRouteId);
  return selected ? <LineDetail routeId={selected} /> : <LineList />;
}

function LineList() {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const search = useApp((st) => st.search);
  const kinds = useApp((st) => st.kinds);
  const set = useApp((st) => st.set);
  const toggleKind = useApp((st) => st.toggleKind);
  const { model, query } = useNetworkModel();
  const { model: vehicles } = useVehicleModel();
  const minute = useClockMinute();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const focus = () => inputRef.current?.focus();
    window.addEventListener('vlab:focus-search', focus);
    return () => window.removeEventListener('vlab:focus-search', focus);
  }, []);

  const counts = useMemo(() => {
    const c: Record<RouteKind, number> = { day: 0, night: 0, special: 0 };
    model?.routes.forEach((r) => (c[r.kind] += 1));
    return c;
  }, [model]);

  const groups = useMemo(() => {
    if (!model) return [];
    return KINDS.filter((k) => kinds[k])
      .map((k) => ({
        kind: k,
        routes: model.routes.filter((r) => r.kind === k && matchRoute(r, search, model.stopById)),
      }))
      .filter((g) => g.routes.length);
  }, [model, kinds, search]);

  const sparkMax = useMemo(() => {
    let m = 1;
    vehicles?.perHour.forEach((v) => v.forEach((x) => (m = Math.max(m, x))));
    return m;
  }, [vehicles]);

  if (query.isError && !model) return <NetworkError onRetry={() => void query.refetch()} />;

  const time = minute * 60;
  const nf = (n: number) => formatNumber(n, lang);

  return (
    <div className={s.root}>
      <div className={s.header}>
        <div className={s.titleRow}>
          <h1 className={s.title}>{t('network.title')}</h1>
          {model ? (
            <span className={s.summary}>
              {t('network.summary', {
                routes: model.routes.length,
                stops: formatNumber(model.network.stops.length, lang),
              })}
            </span>
          ) : (
            <Skeleton width={110} height={12} />
          )}
        </div>
        <div className={s.totals} aria-label={t('network.perDay')}>
          <Stat size="sm" label={t('network.totalsFleet')} value={model?.network.totals.fleet} format={nf} />
          <Stat
            size="sm"
            label={t('network.totalsBusHours')}
            value={model?.network.totals.bus_hours}
            format={nf}
          />
          <Stat size="sm" label={t('network.totalsTrips')} value={model?.network.totals.trips} format={nf} />
        </div>
        <div className={s.search}>
          <Search strokeWidth={1.75} />
          <input
            ref={inputRef}
            type="search"
            className={s.input}
            placeholder={t('network.search')}
            aria-label={t('network.search')}
            value={search}
            onChange={(e) => set({ search: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                if (search) set({ search: '' });
                else e.currentTarget.blur();
                e.stopPropagation();
              }
              if (e.key === 'Enter' && groups[0]?.routes[0]) {
                useApp.getState().selectRoute(groups[0].routes[0].id);
              }
            }}
            data-testid="line-search"
          />
          <span className={s.searchEnd}>
            {search ? (
              <button type="button" className={s.clear} aria-label={t('network.clearSearch')} onClick={() => set({ search: '' })}>
                <X size={14} strokeWidth={1.75} />
              </button>
            ) : (
              <Kbd>/</Kbd>
            )}
          </span>
        </div>
        <div className={s.filters} role="group" aria-label={t('network.listLabel')}>
          {KINDS.filter((k) => counts[k] > 0).map((k) => (
            <button key={k} type="button" className={s.chip} aria-pressed={kinds[k]} onClick={() => toggleKind(k)}>
              {t(`network.kind.${k}`)}
              <span className={s.chipCount}>{counts[k]}</span>
            </button>
          ))}
        </div>
      </div>

      <ul className={s.list} aria-label={t('network.listLabel')} data-testid="line-list">
        {!model
          ? Array.from({ length: 9 }, (_, i) => (
              <li key={i} className={s.skelRow}>
                <Skeleton width={34} height={20} />
                <span className={s.skelText}>
                  <Skeleton width={`${60 + ((i * 17) % 30)}%`} height={10} />
                  <Skeleton width={64} height={8} />
                </span>
                <Skeleton width={56} height={14} />
              </li>
            ))
          : null}
        {model && groups.length === 0 ? (
          <li className={s.empty}>{t('network.noResults', { query: search })}</li>
        ) : null}
        {groups.map((g) => (
          <li key={g.kind}>
            {groups.length > 1 || g.kind !== 'day' ? (
              <div className={s.groupLabel}>{t(`network.kind.${g.kind}`)}</div>
            ) : null}
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {g.routes.map((r) => (
                <LineRow
                  key={r.id}
                  route={r}
                  time={time}
                  perHour={vehicles?.perHour.get(r.id)}
                  sparkMax={sparkMax}
                />
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}

function LineRow({
  route,
  time,
  perHour,
  sparkMax,
}: {
  route: Route;
  time: number;
  perHour: number[] | undefined;
  sparkMax: number;
}) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const hovered = useApp((st) => st.hoveredRouteId === route.id);
  const hoverRoute = useApp((st) => st.hoverRoute);
  const selectRoute = useApp((st) => st.selectRoute);
  const active = routeInService(route, time);
  const headway = active ? headwayAround(perHour, time, route.patterns.length) : null;
  const spark = useMemo(() => (perHour ?? []).slice(SPARK_FROM, SPARK_TO), [perHour]);
  const onLeave = useCallback(() => {
    if (useApp.getState().hoveredRouteId === route.id) hoverRoute(null);
  }, [hoverRoute, route.id]);
  return (
    <li>
      <button
        type="button"
        className={s.row}
        data-hovered={hovered}
        data-off={!active}
        onMouseEnter={() => hoverRoute(route.id)}
        onMouseLeave={onLeave}
        onFocus={() => hoverRoute(route.id)}
        onBlur={onLeave}
        onClick={() => {
          hoverRoute(null);
          selectRoute(route.id);
        }}
        data-testid={`line-row-${route.short_name}`}
      >
        <LineBadge shortName={route.short_name} color={route.color} textColor={route.text_color} />
        <span className={s.rowText}>
          <span className={s.rowName}>{displayName(route.long_name)}</span>
          <span className={s.rowMeta}>
            {headway
              ? t('network.every', { min: formatMinutes(Math.round(headway / 60) * 60, lang) })
              : t('network.notRunning')}
          </span>
        </span>
        <SparkBars
          className={s.spark}
          values={spark}
          width={56}
          height={18}
          max={sparkMax}
          highlight={Math.floor(time / 3600) - SPARK_FROM}
          label={t('network.sparklineLabel')}
        />
      </button>
    </li>
  );
}
