/** Small idempotent helpers for MapLibre sources/layers that survive style reloads. */
import type { GeoJSONSource, LayerSpecification, Map as MlMap } from 'maplibre-gl';

export function setGeoJSON(map: MlMap, id: string, data: GeoJSON.GeoJSON, promoteId?: string) {
  const src = map.getSource(id) as GeoJSONSource | undefined;
  if (src) src.setData(data);
  else map.addSource(id, { type: 'geojson', data, ...(promoteId ? { promoteId } : {}) });
}

export function ensureLayer(map: MlMap, layer: LayerSpecification, beforeId?: string) {
  if (map.getLayer(layer.id)) return;
  map.addLayer(layer, beforeId && map.getLayer(beforeId) ? beforeId : undefined);
}

export function removeLayers(map: MlMap, ids: string[]) {
  for (const id of ids) if (map.getLayer(id)) map.removeLayer(id);
}

export function setPaint(map: MlMap, layer: string, prop: string, value: unknown) {
  if (!map.getLayer(layer)) return;
  map.setPaintProperty(layer, prop, value);
}

export function setFilter(map: MlMap, layer: string, filter: unknown) {
  if (!map.getLayer(layer)) return;
  map.setFilter(layer, filter as Parameters<MlMap['setFilter']>[1]);
}
