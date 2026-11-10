import { Target, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useApp } from '@/app/store';
import { Button, IconButton, LineBadge, Surface } from '@/components/ui';
import { clock } from '@/features/time/clock';
import { snapIsoStart } from '@/features/isochrone/useIsochroneRequest';
import { useT } from '@/i18n';
import { useMapContext } from '@/map/MapContext';
import { useBusHover } from './BusesLayer';
import { headsignForTrip, useNetworkModel, useVehicleModel } from './model';
import s from './MapPopovers.module.css';

/** Popover anchored to the selected stop; follows the map while panning. */
export function StopPopover() {
  const t = useT();
  const { map } = useMapContext();
  const stopId = useApp((st) => st.selectedStopId);
  const view = useApp((st) => st.view);
  const { model } = useNetworkModel();
  const ref = useRef<HTMLDivElement>(null);
  const stop = stopId ? model?.stopById.get(stopId) : undefined;

  useEffect(() => {
    if (!map || !stop) return;
    const place = () => {
      const p = map.project([stop.lon, stop.lat]);
      if (ref.current) ref.current.style.transform = `translate(${p.x}px, ${p.y}px)`;
    };
    place();
    map.on('move', place);
    return () => {
      map.off('move', place);
    };
  }, [map, stop]);

  if (!stop || !model || view !== 'network') return null;
  const routes = stop.routes
    .map((id) => model.routeById.get(id))
    .filter((r): r is NonNullable<typeof r> => Boolean(r));

  return (
    <div className={s.anchor} ref={ref}>
      <Surface className={s.stop} role="dialog" aria-label={stop.name} data-testid="stop-popover">
        <div className={s.stopHeader}>
          <div>
            <div className={s.stopName}>{stop.name}</div>
            <div className={s.stopId}>{t('stop.label', { id: stop.id })}</div>
          </div>
          <IconButton label={t('common.close')} size="sm" onClick={() => useApp.getState().selectStop(null)}>
            <X strokeWidth={1.5} />
          </IconButton>
        </div>
        <div className={s.badges} aria-label={t('stop.lines')}>
          {routes.map((r) => (
            <button
              key={r.id}
              type="button"
              className={s.badgeButton}
              aria-label={`${r.short_name} ${r.long_name}`}
              onClick={() => useApp.getState().selectRoute(r.id)}
              onMouseEnter={() => useApp.getState().hoverRoute(r.id)}
              onMouseLeave={() => useApp.getState().hoverRoute(null)}
            >
              <LineBadge shortName={r.short_name} color={r.color} textColor={r.text_color} />
            </button>
          ))}
        </div>
        <div className={s.stopFoot}>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              useApp.getState().setIsoOrigin([stop.lon, stop.lat], snapIsoStart(clock.getState().time))
            }
          >
            <Target strokeWidth={1.75} />
            {t('stop.isochroneFrom')}
          </Button>
        </div>
      </Surface>
    </div>
  );
}

/** Tooltip for the hovered bus: line badge + headsign. */
export function BusTooltip() {
  const t = useT();
  const hover = useBusHover((st) => st.hover);
  const { model } = useNetworkModel();
  const { model: vehicles } = useVehicleModel();
  if (!hover || !model || !vehicles) return null;
  const route = model.routeById.get(hover.route);
  if (!route) return null;
  const headsign = headsignForTrip(model, vehicles, hover.trip);
  return (
    <div className={s.tooltip} style={{ left: hover.x, top: hover.y }} role="tooltip" data-testid="bus-tooltip">
      <LineBadge shortName={route.short_name} color={route.color} textColor={route.text_color} />
      {headsign ? t('bus.towards', { headsign }) : route.long_name}
    </div>
  );
}
