/**
 * New-line draft: debounced street snapping of the waypoints, the proposed stops along the
 * snapped path (existing stops, de-duplicated across the two kerbs of a street) and the
 * resulting `add_route` edit.
 */
import { useEffect, useMemo, useState } from 'react';
import { useSnap, type AddRouteEdit, type ScenarioEdit, type SnapResponse } from '@/api/scenario';
import type { LonLat } from '@/api/types';
import { useNetworkModel } from '@/features/network/model';
import { distanceM, newRouteId, project } from './model';
import { useEditor, type Draft, type DraftStop } from './state';

const SNAP_DEBOUNCE_MS = 180;
/** opposite-kerb stops of the same name within this distance count as one */
const PAIR_M = 80;

function useDebouncedWaypoints(waypoints: LonLat[]): LonLat[] {
  const [v, setV] = useState(waypoints);
  useEffect(() => {
    const id = window.setTimeout(() => setV(waypoints), SNAP_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [waypoints]);
  return v;
}

export function useDraftSnap() {
  const draft = useEditor((s) => s.draft);
  const waypoints = useMemo(() => draft?.waypoints ?? [], [draft?.waypoints]);
  const debounced = useDebouncedWaypoints(waypoints);
  const q = useSnap(debounced);
  const data = waypoints.length >= 2 ? q.data : undefined;
  return { data, query: q, pending: debounced !== waypoints || q.isFetching };
}

/** Existing stops proposed along the path: one per name/kerb pair, ordered along the path. */
export function proposedStops(snap: SnapResponse | undefined): SnapResponse['nearby_stops'] {
  if (!snap) return [];
  const out: SnapResponse['nearby_stops'] = [];
  for (const s of snap.nearby_stops) {
    const twin = out.findIndex(
      (o) =>
        o.name.trim().toLowerCase() === s.name.trim().toLowerCase() &&
        Math.abs(o.offset_m - s.offset_m) < PAIR_M,
    );
    if (twin < 0) out.push(s);
    else if (s.distance_m < out[twin]!.distance_m) out[twin] = s;
  }
  return out.sort((a, b) => a.offset_m - b.offset_m);
}

export interface DraftStopRow extends DraftStop {
  existing: boolean;
  included: boolean;
}

/** All stops of the draft (proposed existing + user-placed), ordered along the snapped path. */
export function useDraftStops(): { rows: DraftStopRow[]; snap: SnapResponse | undefined } {
  const draft = useEditor((s) => s.draft);
  const { data: snap } = useDraftSnap();
  const { model } = useNetworkModel();
  const rows = useMemo(() => {
    if (!draft) return [];
    const proposed: DraftStopRow[] = proposedStops(snap).map((s) => {
      const st = model?.stopById.get(s.id);
      return {
        key: s.id,
        stopId: s.id,
        lon: st?.lon ?? 0,
        lat: st?.lat ?? 0,
        name: st?.name ?? s.name,
        offset: s.offset_m,
        existing: true,
        included: !draft.excluded.includes(s.id),
      };
    });
    const placed: DraftStopRow[] = draft.newStops.map((s) => ({
      ...s,
      offset: snap?.path.length ? project(snap.path, [s.lon, s.lat]).offset : s.offset,
      existing: false,
      included: true,
    }));
    return [...proposed, ...placed].sort((a, b) => a.offset - b.offset);
  }, [draft, snap, model]);
  return { rows, snap };
}

/** Map features of the draft for the overlay source. */
export function useDraftGeometry(): GeoJSON.Feature[] | null {
  const draft = useEditor((s) => s.draft);
  const { rows, snap } = useDraftStops();
  return useMemo(() => {
    if (!draft || !draft.waypoints.length) return null;
    const color = draft.color;
    const f: GeoJSON.Feature[] = [];
    if (draft.waypoints.length >= 2) {
      // raw guide while the snap is in flight / when it fails
      f.push({
        type: 'Feature',
        properties: { kind: 'raw', color },
        geometry: { type: 'LineString', coordinates: draft.waypoints },
      });
    }
    if (snap?.path.length) {
      f.push({
        type: 'Feature',
        properties: { kind: 'draft', color },
        geometry: { type: 'LineString', coordinates: snap.path },
      });
    }
    for (const w of draft.waypoints)
      f.push({
        type: 'Feature',
        properties: { kind: 'waypoint', color },
        geometry: { type: 'Point', coordinates: w },
      });
    for (const r of rows)
      f.push({
        type: 'Feature',
        properties: {
          kind: r.existing ? (r.included ? 'proposed' : 'excluded') : 'newstop',
          color,
          key: r.key,
        },
        geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
      });
    return f;
  }, [draft, rows, snap]);
}

/** The `add_route` edit for the current draft, or null when it is not complete. */
export function buildAddRoute(
  draft: Draft,
  rows: DraftStopRow[],
  edits: ScenarioEdit[],
): AddRouteEdit | null {
  const stops = rows.filter((r) => r.included);
  if (stops.length < 2 || draft.waypoints.length < 2) return null;
  // two consecutive identical stops are invalid; also drop exact duplicates
  const seq = stops.filter((s, i) => i === 0 || distanceM([s.lon, s.lat], [stops[i - 1]!.lon, stops[i - 1]!.lat]) > 1);
  return {
    type: 'add_route',
    route_id: newRouteId(draft.shortName, edits),
    short_name: draft.shortName.trim() || 'A',
    color: draft.color,
    waypoints: draft.waypoints.map((p) => [round5(p[0]), round5(p[1])] as LonLat),
    stops: seq.map((s) =>
      s.stopId ? { stop_id: s.stopId } : { lon: round5(s.lon), lat: round5(s.lat), name: s.name },
    ),
    headway: draft.headway,
    bidirectional: draft.bidirectional,
    speed_kmh: null,
  };
}

const round5 = (n: number) => Math.round(n * 1e5) / 1e5;
