/**
 * App/UI state (zustand). Server state lives in TanStack Query; the animation clock lives in
 * `features/time/clock.ts` (transient, outside React). Everything shareable is mirrored to the
 * URL by `app/url.ts`.
 */
import { create } from 'zustand';
import type { DayType, IsochroneMode, LonLat, RouteKind } from '@/api/types';
import type { Lang } from '@/i18n/dict';

export type ViewId = 'network' | 'accessibility' | 'scenario' | 'optimizer' | 'compare';
export const VIEWS: readonly ViewId[] = [
  'network',
  'accessibility',
  'scenario',
  'optimizer',
  'compare',
];
export type ThemePref = 'light' | 'dark' | 'system';
export type Theme = 'light' | 'dark';

export interface AppState {
  view: ViewId;
  lang: Lang;
  themePref: ThemePref;
  theme: Theme;
  panelOpen: boolean;
  day: DayType;
  kinds: Record<RouteKind, boolean>;
  search: string;
  selectedRouteId: string | null;
  selectedDirection: number;
  hoveredRouteId: string | null;
  selectedStopId: string | null;
  isoOrigin: LonLat | null;
  /** departure time (s) of the isochrone window, frozen when the origin is set */
  isoStart: number;
  isoMode: IsochroneMode;
  shortcutsOpen: boolean;
  aboutOpen: boolean;
}

export interface AppActions {
  set: (patch: Partial<AppState>) => void;
  setView: (view: ViewId) => void;
  selectRoute: (id: string | null) => void;
  hoverRoute: (id: string | null) => void;
  selectStop: (id: string | null) => void;
  setIsoOrigin: (origin: LonLat | null, start?: number) => void;
  toggleKind: (kind: RouteKind) => void;
  /** Esc: peel one layer of selection at a time. Returns true when something was cleared. */
  clearTop: () => boolean;
}

export const useApp = create<AppState & AppActions>()((set, get) => ({
  view: 'network',
  lang: 'es',
  themePref: 'system',
  theme: 'light',
  panelOpen: true,
  day: 'weekday',
  kinds: { day: true, night: true, special: true },
  search: '',
  selectedRouteId: null,
  selectedDirection: 0,
  hoveredRouteId: null,
  selectedStopId: null,
  isoOrigin: null,
  isoStart: 8 * 3600,
  isoMode: 'transit',
  shortcutsOpen: false,
  aboutOpen: false,

  set: (patch) => set(patch),
  setView: (view) => set({ view }),
  selectRoute: (id) =>
    set((s) => ({
      selectedRouteId: id,
      selectedDirection: id === s.selectedRouteId ? s.selectedDirection : 0,
      view: id ? 'network' : s.view,
      panelOpen: id ? true : s.panelOpen,
    })),
  hoverRoute: (id) => {
    if (get().hoveredRouteId !== id) set({ hoveredRouteId: id });
  },
  selectStop: (id) => set({ selectedStopId: id }),
  setIsoOrigin: (origin, start) =>
    set((s) => ({ isoOrigin: origin, isoStart: start ?? s.isoStart, selectedStopId: null })),
  toggleKind: (kind) => set((s) => ({ kinds: { ...s.kinds, [kind]: !s.kinds[kind] } })),
  clearTop: () => {
    const s = get();
    if (s.selectedStopId) set({ selectedStopId: null });
    else if (s.isoOrigin) set({ isoOrigin: null });
    else if (s.selectedRouteId) set({ selectedRouteId: null });
    else if (s.search) set({ search: '' });
    else return false;
    return true;
  },
}));
