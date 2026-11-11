/**
 * Before/after swipe. Two MapLibre maps (today on the left, the scenario on the right) fill the
 * map area; the right one is clipped by the divider with `clip-path`. Cameras are kept in sync
 * with the main map (the master: its zoom buttons and "fit" control keep working) through a
 * re-entrancy lock, so a drag on either stage map moves all three.
 *
 * The divider is a keyboard-operable slider (arrows, Shift for big steps, Home/End).
 */
import maplibregl, { type ExpressionSpecification, type Map as MlMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { ChevronsLeftRight } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Accessibility, Network, ZonesGeoJSON } from '@/api/types';
import { useApp, type Theme } from '@/app/store';
import { residentWeight, rgba, zoneColors } from '@/features/accessibility/model';
import { TIME_EDGES, metricScale } from '@/features/accessibility/model';
import type { NetworkModel } from '@/features/network/model';
import { DELTA_LEGEND_STEPS, deltaTimeColor } from '@/features/optimizer/model';
import { clockActions } from '@/features/time/clock';
import { useT } from '@/i18n';
import { DIVERGING } from '@/lib/palettes';
import { BASEMAP_PALETTES, blankStyle, dataLayerAnchor, loadBasemapStyle } from '@/map/basemap';
import { fitBounds } from '@/map/camera';
import { useMapContext } from '@/map/MapContext';
import { ensureLayer, setGeoJSON } from '@/map/maplibreLayers';
import { useCompare } from './store';
import { maxTripsOf, nextSplit, splitFromPointer, tripWidth } from './model';
import { useCompareData } from './useCompareData';
import { useMeta } from '@/api/queries';
import { Skeleton, Surface } from '@/components/ui';
import { formatNumber } from '@/lib/format';
import s from './Compare.module.css';

const SRC_ZONES = 'cmp-zones';
const SRC_LINES = 'cmp-lines';
const L_FILL = 'cmp-fill';
const L_CASING = 'cmp-casing';
const L_LINE = 'cmp-line';

// ------------------------------------------------------------------------------ camera sync

interface Camera {
  center: [number, number];
  zoom: number;
  bearing: number;
  pitch: number;
}
const cameraOf = (m: MlMap): Camera => ({
  center: m.getCenter().toArray() as [number, number],
  zoom: m.getZoom(),
  bearing: m.getBearing(),
  pitch: m.getPitch(),
});

/** Keep a set of maps on the same camera. Any map may drive; a lock stops echo loops. */
class CameraSync {
  private maps = new Map<MlMap, () => void>();
  private locked = false;
  add(map: MlMap) {
    if (this.maps.has(map)) return;
    const handler = () => this.drive(map);
    map.on('move', handler);
    this.maps.set(map, handler);
  }
  remove(map: MlMap) {
    const h = this.maps.get(map);
    if (h) map.off('move', h);
    this.maps.delete(map);
  }
  drive(source: MlMap) {
    if (this.locked) return;
    this.locked = true;
    try {
      const cam = cameraOf(source);
      for (const m of this.maps.keys()) if (m !== source) m.jumpTo(cam);
    } finally {
      this.locked = false;
    }
  }
  dispose() {
    for (const [m, h] of this.maps) m.off('move', h);
    this.maps.clear();
  }
}

// ------------------------------------------------------------------------------ one map

const zoomWidth = (f: (k: number) => ExpressionSpecification): ExpressionSpecification => [
  'interpolate',
  ['exponential', 1.5],
  ['zoom'],
  10,
  f(0.8),
  12,
  f(1.6),
  14,
  f(2.6),
  16,
  f(4.5),
  18,
  f(8),
];

function linesOf(model: NetworkModel | null, theme: Theme, maxTrips: number): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  if (model)
    for (const r of model.routes)
      for (const p of r.patterns)
        features.push({
          type: 'Feature',
          properties: {
            route_id: r.id,
            color: model.mapColor(r.id, theme),
            w: tripWidth(r.stats.trips, maxTrips),
            sort: r.stats.trips,
          },
          geometry: { type: 'LineString', coordinates: p.path },
        });
  return { type: 'FeatureCollection', features };
}

interface ComparedMapProps {
  sync: CameraSync;
  lines: GeoJSON.FeatureCollection;
  zones: ZonesGeoJSON | null;
  /** colour per zone feature id (null = none) */
  colors: (string | null)[] | null;
  theme: Theme;
  testId: string;
}

function ComparedMap({ sync, lines, zones, colors, theme, testId }: ComparedMapProps) {
  const { map: main } = useMapContext();
  const box = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MlMap | null>(null);
  const [version, setVersion] = useState(0);
  const themeRef = useRef(theme);

  useEffect(() => {
    if (!box.current || !main) return;
    const m = new maplibregl.Map({
      container: box.current,
      style: blankStyle(themeRef.current),
      center: main.getCenter(),
      zoom: main.getZoom(),
      minZoom: 9,
      maxZoom: 18.5,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      fadeDuration: 150,
    });
    m.touchZoomRotate.disableRotation();
    m.keyboard.disable();
    const onStyle = () => setVersion((v) => v + 1);
    m.on('style.load', onStyle);
    sync.add(m);
    setMap(m);
    return () => {
      sync.remove(m);
      m.off('style.load', onStyle);
      m.remove();
      setMap(null);
    };
  }, [main, sync]);

  useEffect(() => {
    themeRef.current = theme;
    if (!map) return;
    let cancelled = false;
    void loadBasemapStyle(theme).then((style) => {
      if (!cancelled) map.setStyle(style, { diff: false });
    });
    return () => {
      cancelled = true;
    };
  }, [map, theme]);

  // sources + layers (idempotent; rebuilt after every style load)
  useEffect(() => {
    if (!map || !version) return;
    const anchor = dataLayerAnchor(map.getStyle() as Parameters<typeof dataLayerAnchor>[0]);
    const bg = BASEMAP_PALETTES[theme].background;
    setGeoJSON(map, SRC_ZONES, zones ?? { type: 'FeatureCollection', features: [] });
    setGeoJSON(map, SRC_LINES, lines);
    ensureLayer(
      map,
      {
        id: L_FILL,
        type: 'fill',
        source: SRC_ZONES,
        paint: {
          'fill-color': ['to-color', ['coalesce', ['feature-state', 'c'], 'rgba(0,0,0,0)']],
          'fill-antialias': false,
        },
      },
      anchor,
    );
    ensureLayer(
      map,
      {
        id: L_CASING,
        type: 'line',
        source: SRC_LINES,
        layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'sort'] },
        paint: {
          'line-color': bg,
          'line-width': zoomWidth((k) => ['+', ['*', k, ['get', 'w']], 1.6]),
          'line-opacity': 0.7,
        },
      },
      anchor,
    );
    ensureLayer(
      map,
      {
        id: L_LINE,
        type: 'line',
        source: SRC_LINES,
        layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'sort'] },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': zoomWidth((k) => ['*', k, ['get', 'w']]),
          'line-opacity': 0.95,
        },
      },
      anchor,
    );
  }, [map, version, zones, lines, theme]);

  // zone colours
  useEffect(() => {
    if (!map || !version || !zones || !map.getSource(SRC_ZONES)) return;
    map.removeFeatureState({ source: SRC_ZONES });
    if (!colors) return;
    for (let i = 0; i < colors.length; i++) {
      const c = colors[i];
      if (c) map.setFeatureState({ source: SRC_ZONES, id: i }, { c });
    }
  }, [map, version, zones, colors]);

  return <div ref={box} className={s.map} data-testid={testId} />;
}

// ------------------------------------------------------------------------------ colours

function accessColors(acc: Accessibility | undefined, category: string, theme: Theme) {
  if (!acc) return null;
  return zoneColors(acc, 'time', category, theme);
}

// ------------------------------------------------------------------------------ stage

export function CompareStage() {
  const view = useApp((st) => st.view);
  const active = view === 'compare';
  const data = useCompareData(active);
  const show = active && !!data.scenario;
  const theme = useApp((st) => st.theme);
  const { map: main } = useMapContext();
  const mode = useCompare((st) => st.mode);
  const category = useCompare((st) => st.category);
  const split = useCompare((st) => st.split);
  const setSplit = useCompare((st) => st.setSplit);
  const t = useT();
  const sync = useMemo(() => new CameraSync(), []);
  const track = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => () => sync.dispose(), [sync]);
  useEffect(() => {
    if (!main || !show) return;
    sync.add(main);
    return () => sync.remove(main);
  }, [main, show, sync]);

  // the analysis window follows the clock: stop the animation here, and hide the main map's buses
  useEffect(() => {
    if (!active) return;
    clockActions.pause();
  }, [active]);
  useEffect(() => {
    useApp.setState({ diffActive: show });
    return () => useApp.setState({ diffActive: false });
  }, [show]);

  const maxTrips = useMemo(
    () => maxTripsOf(data.today?.routes ?? [], data.proposal?.routes ?? []),
    [data.today, data.proposal],
  );
  const beforeLines = useMemo(() => linesOf(data.today, theme, maxTrips), [data.today, theme, maxTrips]);
  const afterLines = useMemo(() => linesOf(data.proposal, theme, maxTrips), [data.proposal, theme, maxTrips]);

  const ev = data.evaluation.data;
  const zones = data.zones ?? null;
  const beforeColors = useMemo(
    () => (mode === 'access' ? accessColors(data.accToday.data, category, theme) : null),
    [mode, data.accToday.data, category, theme],
  );
  const afterColors = useMemo(() => {
    if (mode === 'access') return accessColors(data.accScenario.data, category, theme);
    if (mode === 'delta' && ev && zones) {
      const out: (string | null)[] = new Array(zones.features.length).fill(null);
      ev.zones.id.forEach((zid, i) => {
        const pop = zones.features[zid]?.properties.population ?? 0;
        const c = deltaTimeColor(ev.zones.delta_time[i] ?? null, theme);
        if (c && pop > 0) out[zid] = rgba(c, residentWeight(pop) * (theme === 'dark' ? 0.78 : 0.74));
      });
      return out;
    }
    return null;
  }, [mode, data.accScenario.data, category, theme, ev, zones]);

  // initial framing: the service area, once the maps exist
  const { data: meta } = useMeta();
  const framed = useRef(false);
  useEffect(() => {
    if (!show) framed.current = false;
    if (!show || framed.current || !main || !meta) return;
    framed.current = true;
    fitBounds(main, [
      [meta.bbox[0], meta.bbox[1]],
      [meta.bbox[2], meta.bbox[3]],
    ]);
  }, [show, main, meta]);

  const onPointer = useCallback(
    (e: React.PointerEvent) => {
      const r = track.current?.getBoundingClientRect();
      if (!r) return;
      setSplit(splitFromPointer(e.clientX, r.left, r.right));
    },
    [setSplit],
  );

  if (!show) return null;
  const single = mode === 'delta';
  const loading =
    data.evaluation.isLoading ||
    (mode === 'access' && (data.accToday.isLoading || data.accScenario.isLoading));
  const accNow = mode === 'access';
  const pct = Math.round(split * 100);

  return (
    <div
      className={s.stage}
      style={{ ['--split' as string]: single ? 0 : split }}
      data-testid="compare-stage"
      data-mode={mode}
    >
      <div ref={track} className={s.track} aria-hidden />
      {!single ? (
        <ComparedMap
          sync={sync}
          lines={beforeLines}
          zones={zones}
          colors={beforeColors}
          theme={theme}
          testId="compare-map-before"
        />
      ) : null}
      <div className={s.afterClip} data-single={single}>
        <ComparedMap
          sync={sync}
          lines={afterLines}
          zones={zones}
          colors={afterColors}
          theme={theme}
          testId="compare-map-after"
        />
      </div>
      {!single ? (
        <>
          <span className={`${s.label} ${s.labelLeft}`} data-testid="compare-label-before">
            {t('cmp.today')}
          </span>
          <span className={`${s.label} ${s.labelRight}`} data-testid="compare-label-after">
            {data.name}
          </span>
          <div
            className={s.divider}
            role="slider"
            tabIndex={0}
            aria-label={t('cmp.swipe')}
            aria-orientation="horizontal"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
            aria-valuetext={`${pct} %`}
            data-dragging={dragging}
            data-testid="compare-divider"
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              setDragging(true);
              onPointer(e);
            }}
            onPointerMove={(e) => dragging && onPointer(e)}
            onPointerUp={(e) => {
              e.currentTarget.releasePointerCapture(e.pointerId);
              setDragging(false);
            }}
            onPointerCancel={() => setDragging(false)}
            onKeyDown={(e) => {
              const n = nextSplit(split, e.key, e.shiftKey);
              if (n !== null) {
                e.preventDefault();
                e.stopPropagation();
                setSplit(n);
              }
            }}
          >
            <span className={s.dividerLine} />
            <span className={s.handle}>
              <ChevronsLeftRight strokeWidth={1.75} aria-hidden />
            </span>
          </div>
        </>
      ) : (
        <span className={`${s.label} ${s.labelSingle}`}>{data.name}</span>
      )}
      {loading ? (
        <div className={s.loading} aria-live="polite">
          <Skeleton height={10} width={120} />
        </div>
      ) : null}
      <CompareLegend mode={mode} category={category} accNow={accNow} />
    </div>
  );
}

// ------------------------------------------------------------------------------ legend

function CompareLegend({ mode, category, accNow }: { mode: string; category: string; accNow: boolean }) {
  const t = useT();
  const theme = useApp((st) => st.theme);
  const lang = useApp((st) => st.lang);
  void category;
  if (mode === 'network')
    return (
      <Surface className={s.legend} data-testid="compare-legend">
        <div className={s.legendTitle}>{t('cmp.legendNetwork')}</div>
        <div className={s.legendStrokes} aria-hidden>
          <span style={{ height: 2 }} />
          <span style={{ height: 4 }} />
          <span style={{ height: 6 }} />
        </div>
      </Surface>
    );
  if (accNow) {
    const scale = metricScale('time', theme, 1800);
    const values = scale.bins.filter((b) => b.kind === 'value');
    return (
      <Surface className={s.legend} data-testid="compare-legend">
        <div className={s.legendTitle}>{t('cmp.legendAccess')}</div>
        <div className={s.ramp} aria-hidden>
          {values.map((b, i) => (
            <span key={i} style={{ background: b.color }} />
          ))}
        </div>
        <div className={s.rampLabels} aria-hidden>
          <span>{formatNumber(TIME_EDGES[0]! / 60, lang)}</span>
          <span>{formatNumber(TIME_EDGES[2]! / 60, lang)}</span>
          <span>{formatNumber(TIME_EDGES[5]! / 60, lang)}+</span>
        </div>
      </Surface>
    );
  }
  const p = DIVERGING[theme];
  const ramp = [p.pos[2]!, p.pos[1]!, p.pos[0]!, p.neg[2]!, p.neg[1]!, p.neg[0]!];
  void DELTA_LEGEND_STEPS;
  return (
    <Surface className={s.legend} data-testid="compare-legend">
      <div className={s.legendTitle}>{t('opt.legendTime')}</div>
      <div className={s.ramp} aria-hidden>
        {ramp.map((c) => (
          <span key={c} style={{ background: c }} />
        ))}
      </div>
      <div className={s.rampLabels} aria-hidden>
        <span>{t('opt.legendFaster')}</span>
        <span>{t('opt.legendSlower')}</span>
      </div>
    </Surface>
  );
}

export type { Network };
