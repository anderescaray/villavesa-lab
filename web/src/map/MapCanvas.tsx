import { MapboxOverlay } from '@deck.gl/mapbox';
import maplibregl, { type Map as MlMap, type StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useApp } from '@/app/store';
import { useT } from '@/i18n';
import { blankStyle, dataLayerAnchor, loadBasemapStyle } from './basemap';
import { DEFAULT_CENTER, DEFAULT_ZOOM } from './camera';
import { deckRegistry } from './deckRegistry';
import { MapContext, type MapContextValue } from './MapContext';
import s from './MapCanvas.module.css';

declare global {
  interface Window {
    /** exposed for e2e tests and debugging */
    __vlabMap?: MlMap;
  }
}

/**
 * The single map instance. Always mounted behind every view; children (feature layers, floating
 * UI) receive it through MapContext. Theme changes reload a re-themed style; feature layers
 * re-add themselves when `styleVersion` changes.
 */
export function MapCanvas({ children }: { children?: ReactNode }) {
  const t = useT();
  const theme = useApp((st) => st.theme);
  const container = useRef<HTMLDivElement>(null);
  const [ctx, setCtx] = useState<MapContextValue>({
    map: null,
    styleVersion: 0,
    anchor: undefined,
  });
  const mapRef = useRef<MlMap | null>(null);
  const themeRef = useRef(theme);

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: blankStyle(themeRef.current),
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      minZoom: 9,
      maxZoom: 18.5,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      fadeDuration: 150,
      canvasContextAttributes: { antialias: true },
    });
    map.touchZoomRotate.disableRotation();
    map.keyboard.disable(); // app-level shortcuts own the keyboard; map keeps mouse/touch
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution:
          '<a href="https://openfreemap.org" target="_blank" rel="noreferrer">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank" rel="noreferrer">OpenMapTiles</a> Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>',
      }),
      'bottom-right',
    );
    // keep the compact attribution collapsed to its (i) button; it expands on click
    map.once('load', () =>
      container.current
        ?.querySelector('.maplibregl-ctrl-attrib')
        ?.classList.remove('maplibregl-compact-show'),
    );
    const overlay = new MapboxOverlay({ interleaved: false, layers: [], useDevicePixels: true });
    map.addControl(overlay);
    deckRegistry.attach(overlay);
    mapRef.current = map;
    window.__vlabMap = map;

    const onStyle = () => {
      const style = map.getStyle() as StyleSpecification | undefined;
      setCtx((c) => ({ map, styleVersion: c.styleVersion + 1, anchor: dataLayerAnchor(style) }));
    };
    map.on('style.load', onStyle);
    if (map.isStyleLoaded()) onStyle();

    return () => {
      deckRegistry.attach(null);
      map.off('style.load', onStyle);
      map.remove();
      mapRef.current = null;
      delete window.__vlabMap;
    };
  }, []);

  // (re)load the themed basemap
  useEffect(() => {
    themeRef.current = theme;
    let cancelled = false;
    void loadBasemapStyle(theme).then((style) => {
      if (cancelled || !mapRef.current) return;
      // Until the new style has loaded, sources and layers cannot be added ("Style is not
      // done loading"): hide the map from consumers; `style.load` publishes it again.
      setCtx((c) => ({ ...c, map: null }));
      mapRef.current.setStyle(style, { diff: false });
    });
    return () => {
      cancelled = true;
    };
  }, [theme]);

  return (
    <MapContext.Provider value={ctx}>
      <div
        className={s.map}
        ref={container}
        role="region"
        aria-label={t('map.label')}
        data-testid="map"
      />
      {children}
    </MapContext.Provider>
  );
}
