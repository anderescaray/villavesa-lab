/**
 * Animated buses (deck.gl). Each frame: clock → computeFrame (typed arrays, no allocation of
 * per-bus objects) → two IconLayers (halo + body) with binary attributes. Runs from a store
 * subscription, never through React render.
 */
import { IconLayer } from '@deck.gl/layers';
import { useEffect } from 'react';
import { create } from 'zustand';
import { useApp } from '@/app/store';
import { clock } from '@/features/time/clock';
import { parseHex } from '@/lib/color';
import { computeFrame, createFrame, type Frame } from '@/lib/vehicles';
import { DECK_ORDER, deckRegistry } from '@/map/deckRegistry';
import { useNetworkModel, useVehicleModel, type NetworkModel, type VehicleModel } from './model';

export const BUS_LAYER_ID = 'buses';
const HALO_LAYER_ID = 'buses-halo';

/** Hovered bus, for the tooltip. */
export interface BusHover {
  x: number;
  y: number;
  trip: number;
  route: string;
}
export const useBusHover = create<{ hover: BusHover | null }>()(() => ({ hover: null }));

// Icon atlas: a disc with a short pointed nose (points north at angle 0), plus a dilated halo.
const ICON = 64;
function makeAtlas(): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = ICON * 2;
  c.height = ICON;
  const g = c.getContext('2d');
  if (!g) return c;
  const shape = (ox: number, grow: number) => {
    const cx = ox + ICON / 2;
    const cy = ICON / 2 + 5;
    const r = 19 + grow;
    g.beginPath();
    // nose: tangent lines from the tip to the circle
    const tipY = cy - r - 8 - grow * 0.4;
    const a = Math.acos(r / (cy - tipY));
    const start = -Math.PI / 2 + a;
    const end = -Math.PI / 2 - a + 2 * Math.PI;
    g.moveTo(cx, tipY);
    g.lineTo(cx + r * Math.cos(start), cy + r * Math.sin(start));
    g.arc(cx, cy, r, start, end);
    g.closePath();
    g.fillStyle = '#ffffff';
    g.fill();
  };
  shape(0, 0);
  shape(ICON, 5);
  return c;
}

const ICON_MAPPING = {
  body: { x: 0, y: 0, width: ICON, height: ICON, anchorY: ICON / 2 + 5, mask: true },
  halo: { x: ICON, y: 0, width: ICON, height: ICON, anchorY: ICON / 2 + 5, mask: true },
};

let atlas: HTMLCanvasElement | null = null;

interface BusRenderState {
  network: NetworkModel | null;
  vehicles: VehicleModel | null;
  frame: Frame;
  colors: Uint8Array;
  haloColors: Uint8Array;
  angles: Float32Array;
  /** rgba per route index of the vehicle model */
  routeColors: Uint8Array;
  haloColor: [number, number, number, number];
}

function rebuildRouteColors(st: BusRenderState) {
  const { network, vehicles } = st;
  if (!network || !vehicles) return;
  const { theme, hoveredRouteId, selectedRouteId } = useApp.getState();
  const highlight = hoveredRouteId ?? selectedRouteId;
  const ids = vehicles.index.routeIds;
  st.routeColors = new Uint8Array(ids.length * 4);
  ids.forEach((id, i) => {
    const [r, g, b] = parseHex(network.mapColor(id, theme));
    st.routeColors.set([r, g, b, !highlight || highlight === id ? 255 : 40], i * 4);
  });
  st.haloColor = theme === 'dark' ? [14, 15, 17, 255] : [255, 255, 255, 255];
}

function render(st: BusRenderState) {
  const { vehicles } = st;
  if (!vehicles || !st.network) {
    deckRegistry.remove(BUS_LAYER_ID);
    deckRegistry.remove(HALO_LAYER_ID);
    return;
  }
  const { kinds, view } = useApp.getState();
  if (view === 'accessibility' || useApp.getState().diffActive) {
    // the analysis view is about the timetable as a whole: no moving buses competing with data
    deckRegistry.remove(BUS_LAYER_ID);
    deckRegistry.remove(HALO_LAYER_ID);
    return;
  }
  const time = clock.getState().time;
  const n = computeFrame(vehicles.index, time, st.frame);
  // filter by line kind (night/special toggles) in place
  let m = 0;
  for (let i = 0; i < n; i++) {
    const routeIdx = st.frame.route[i]!;
    const id = vehicles.index.routeIds[routeIdx]!;
    const kind = st.network.routeById.get(id)?.kind ?? 'day';
    if (!kinds[kind]) continue;
    if (m !== i) {
      st.frame.positions[2 * m] = st.frame.positions[2 * i]!;
      st.frame.positions[2 * m + 1] = st.frame.positions[2 * i + 1]!;
      st.frame.bearings[m] = st.frame.bearings[i]!;
      st.frame.trip[m] = st.frame.trip[i]!;
      st.frame.route[m] = routeIdx;
    }
    st.angles[m] = -st.frame.bearings[m]!;
    st.colors.set(st.routeColors.subarray(routeIdx * 4, routeIdx * 4 + 4), m * 4);
    st.haloColors.set(st.haloColor, m * 4);
    st.haloColors[m * 4 + 3] = st.routeColors[routeIdx * 4 + 3]!;
    m++;
  }
  st.frame.count = m;
  atlas ??= makeAtlas();
  const dim = view !== 'network' ? 0.75 : 1;
  const common = {
    iconAtlas: atlas as unknown as string,
    iconMapping: ICON_MAPPING,
    sizeUnits: 'meters' as const,
    sizeMinPixels: 15,
    sizeMaxPixels: 30,
    billboard: false,
    opacity: dim,
    parameters: { depthTest: false },
  };
  const positions = { value: st.frame.positions.subarray(0, m * 2), size: 2 };
  const angles = { value: st.angles.subarray(0, m), size: 1 };
  const halo = new IconLayer({
    ...common,
    id: HALO_LAYER_ID,
    data: {
      length: m,
      attributes: {
        getPosition: positions,
        getAngle: angles,
        getColor: { value: st.haloColors.subarray(0, m * 4), size: 4, normalized: true },
      },
    },
    getIcon: () => 'halo',
    getSize: 70,
    pickable: false,
  });
  const body = new IconLayer({
    ...common,
    id: BUS_LAYER_ID,
    data: {
      length: m,
      attributes: {
        getPosition: positions,
        getAngle: angles,
        getColor: { value: st.colors.subarray(0, m * 4), size: 4, normalized: true },
      },
    },
    getIcon: () => 'body',
    getSize: 70,
    pickable: true,
    autoHighlight: false,
    onHover: (info) => {
      if (info.index >= 0 && st.vehicles) {
        const trip = st.frame.trip[info.index]!;
        const route = st.vehicles.index.routeIds[st.vehicles.index.routeOf[trip]!]!;
        useBusHover.setState({ hover: { x: info.x, y: info.y, trip, route } });
      } else if (useBusHover.getState().hover) {
        useBusHover.setState({ hover: null });
      }
    },
  });
  deckRegistry.set(HALO_LAYER_ID, halo, DECK_ORDER.busHalo);
  deckRegistry.set(BUS_LAYER_ID, body, DECK_ORDER.bus, true);
}

/** Look up the frame-local trip index of a picked bus. */
export function useBusesLayer() {
  const { model: network } = useNetworkModel();
  const { model: vehicles } = useVehicleModel();

  useEffect(() => {
    if (!vehicles || !network) return;
    const cap = Math.max(64, vehicles.index.n);
    const st: BusRenderState = {
      network,
      vehicles,
      frame: createFrame(cap),
      colors: new Uint8Array(cap * 4),
      haloColors: new Uint8Array(cap * 4),
      angles: new Float32Array(cap),
      routeColors: new Uint8Array(0),
      haloColor: [255, 255, 255, 255],
    };
    rebuildRouteColors(st);
    render(st);
    let lastTime = clock.getState().time;
    const unsubClock = clock.subscribe((s) => {
      if (s.time !== lastTime) {
        lastTime = s.time;
        render(st);
      }
    });
    const unsubApp = useApp.subscribe((s, prev) => {
      if (
        s.theme !== prev.theme ||
        s.hoveredRouteId !== prev.hoveredRouteId ||
        s.selectedRouteId !== prev.selectedRouteId
      ) {
        rebuildRouteColors(st);
        render(st);
      } else if (
        s.kinds !== prev.kinds ||
        s.view !== prev.view ||
        s.diffActive !== prev.diffActive
      ) {
        render(st);
      }
    });
    return () => {
      unsubClock();
      unsubApp();
      deckRegistry.remove(BUS_LAYER_ID);
      deckRegistry.remove(HALO_LAYER_ID);
    };
  }, [network, vehicles]);
}

export function BusesLayer() {
  useBusesLayer();
  return null;
}
