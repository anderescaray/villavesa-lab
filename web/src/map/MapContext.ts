import type { Map as MlMap } from 'maplibre-gl';
import { createContext, useContext } from 'react';

export interface MapContextValue {
  map: MlMap | null;
  /** increments every time a (re-)themed style finished loading; layers re-add on change */
  styleVersion: number;
  /** basemap layer id our data layers are inserted below */
  anchor: string | undefined;
}

export const MapContext = createContext<MapContextValue>({ map: null, styleVersion: 0, anchor: undefined });

export const useMapContext = () => useContext(MapContext);
