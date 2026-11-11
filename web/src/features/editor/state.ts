/**
 * Transient UI state of the scenario editor (not persisted, not in the URL): the active map
 * tool, the line/stop being edited, the bus-priority corridor and the new-line draft.
 * The edit list itself lives in `features/scenario/store.ts`.
 */
import { create } from 'zustand';
import type { LonLat } from '@/api/types';
import type { Period } from '@/api/scenario';

export type Tool = 'select' | 'frequency' | 'priority' | 'stop' | 'draw';
export const TOOLS: readonly Tool[] = ['select', 'frequency', 'priority', 'stop', 'draw'];
export const TOOL_KEYS: Record<Tool, string> = {
  select: 'V',
  frequency: 'F',
  priority: 'P',
  stop: 'S',
  draw: 'L',
};

export interface DraftStop {
  /** existing stop id, or a generated id for a new point */
  key: string;
  stopId: string | null;
  lon: number;
  lat: number;
  name: string;
  /** metres along the snapped path (for ordering) */
  offset: number;
}

export interface Draft {
  waypoints: LonLat[];
  /** new stops placed by the user (Alt/⌥-click or "add stop here") */
  newStops: DraftStop[];
  /** existing stops proposed along the path that the user switched off */
  excluded: string[];
  shortName: string;
  color: string;
  headway: number;
  bidirectional: boolean;
  /** "stops" sub-mode: clicks place new stops instead of waypoints */
  placeStops: boolean;
}

export const emptyDraft = (shortName: string, color: string): Draft => ({
  waypoints: [],
  newStops: [],
  excluded: [],
  shortName,
  color,
  headway: 600,
  bidirectional: true,
  placeStops: false,
});

export interface Corridor {
  start: string | null;
  end: string | null;
  factor: number;
  allLines: boolean;
}

export interface PendingStop {
  lon: number;
  lat: number;
  routeId: string;
  direction: number;
  afterStopId: string;
  name: string;
}

export interface StopDrag {
  stopId: string;
  from: LonLat;
  to: LonLat;
}

export interface EditorState {
  tool: Tool;
  /** line under edit (frequency, priority, add stop) */
  routeId: string | null;
  direction: number;
  period: Period;
  /** stop inspector */
  stopId: string | null;
  /** add-stop sub-mode of the stop tool: the next map click inserts a stop on `routeId` */
  addingStop: boolean;
  corridor: Corridor;
  /** add-stop: the insertion point chosen on the map, waiting for a name */
  pendingStop: PendingStop | null;
  draft: Draft | null;
  drag: StopDrag | null;
  /** index of the change-list row being edited inline */
  editing: number | null;
  showDelta: boolean;
  /** analysis window start (s) for the live evaluation */
  windowStart: number;
}

export interface EditorActions {
  set: (patch: Partial<EditorState>) => void;
  setTool: (tool: Tool) => void;
  pickRoute: (id: string | null) => void;
  setCorridor: (patch: Partial<Corridor>) => void;
  setDraft: (patch: Partial<Draft>) => void;
  /** Esc: one layer at a time. Returns true when something was cleared. */
  escape: () => boolean;
}

const NO_CORRIDOR: Corridor = { start: null, end: null, factor: 1.2, allLines: false };

export const useEditor = create<EditorState & EditorActions>()((set, get) => ({
  tool: 'select',
  routeId: null,
  direction: 0,
  period: 'all',
  stopId: null,
  addingStop: false,
  corridor: NO_CORRIDOR,
  pendingStop: null,
  draft: null,
  drag: null,
  editing: null,
  showDelta: true,
  windowStart: 8 * 3600,

  set: (patch) => set(patch),
  setTool: (tool) =>
    set((s) => ({
      tool,
      addingStop: false,
      pendingStop: null,
      editing: null,
      stopId: tool === 'stop' ? s.stopId : null,
      corridor: tool === 'priority' ? s.corridor : { ...s.corridor, start: null, end: null },
      draft: tool === 'draw' ? s.draft : null,
    })),
  pickRoute: (id) =>
    set((s) => ({
      routeId: id,
      direction: id === s.routeId ? s.direction : 0,
      corridor: id === s.routeId ? s.corridor : { ...s.corridor, start: null, end: null },
      addingStop: false,
      editing: null,
    })),
  setCorridor: (patch) => set((s) => ({ corridor: { ...s.corridor, ...patch } })),
  setDraft: (patch) => set((s) => (s.draft ? { draft: { ...s.draft, ...patch } } : {})),
  escape: () => {
    const s = get();
    if (s.drag) set({ drag: null });
    else if (s.pendingStop) set({ pendingStop: null });
    else if (s.addingStop) set({ addingStop: false });
    else if (s.editing !== null) set({ editing: null });
    else if (s.draft && s.draft.waypoints.length) set({ draft: null, tool: 'select' });
    else if (s.corridor.end || s.corridor.start)
      set({ corridor: { ...s.corridor, start: null, end: null } });
    else if (s.stopId) set({ stopId: null });
    else if (s.tool !== 'select') set({ tool: 'select', draft: null });
    else if (s.routeId) set({ routeId: null });
    else return false;
    return true;
  },
}));
