/**
 * Wire types — mirror docs/api.md exactly. Do not "improve" names here; change the contract
 * first. Coordinates are [lon, lat]; times are seconds since local midnight (may exceed 86400);
 * durations in seconds; `null` = unreachable / not available.
 */

export type LonLat = [number, number];
export type DayType = 'weekday' | 'saturday' | 'sunday';
export const DAY_TYPES: readonly DayType[] = ['weekday', 'saturday', 'sunday'];

export interface AnalysisWindow {
  day: DayType;
  start: number;
  duration: number;
}

// ---------------------------------------------------------------- meta

/** `loading` while the engine is still building its graphs (the API then answers 503). */
export interface Health {
  status: 'ok' | 'loading' | 'error';
  detail?: string | null;
}

export interface PoiCategoryCount {
  id: string;
  count: number;
}

export interface CostParams {
  eur_per_bus_hour: number;
  eur_per_km: number;
  eur_per_bus_year: number;
  source: string;
}

export interface Meta {
  feed: {
    agency: string;
    start_date: string;
    end_date: string;
    n_routes: number;
    n_stops: number;
    n_stops_served_weekday: number;
  };
  days: Record<DayType, string>;
  bbox: [number, number, number, number];
  center: LonLat;
  population: number;
  n_zones: number;
  poi_categories: PoiCategoryCount[];
  default_window: AnalysisWindow;
  cost_params: CostParams;
  /** Categories whose lack of access counts as under-served (hospital, health centre, centre) */
  essential_categories: string[];
  data_notes: DataNote[];
}

/** `key` is translated by the UI (`note.<key>`); `text` is the English fallback. */
export interface DataNote {
  key: string;
  text: string;
}

// ---------------------------------------------------------------- scenario edits

export type Edit =
  | { type: 'set_headway'; route_id: string; headway: number; period: 'all' | 'peak' | 'offpeak' }
  | { type: 'scale_frequency'; route_id: string; factor: number }
  | { type: 'speed_up'; route_id: string | null; stop_ids: string[]; factor: number }
  | { type: 'remove_stop'; stop_id: string }
  | { type: 'move_stop'; stop_id: string; lon: number; lat: number }
  | {
      type: 'add_stop';
      stop_id: string;
      name: string;
      lon: number;
      lat: number;
      route_id: string;
      direction: number;
      after_stop_id: string;
    }
  | { type: 'remove_route'; route_id: string }
  | {
      type: 'add_route';
      route_id: string;
      short_name: string;
      color: string;
      waypoints: LonLat[];
      stops: ({ stop_id: string } | { lon: number; lat: number; name: string })[];
      headway: number;
      bidirectional: boolean;
      speed_kmh: number | null;
    };

export type Scenario = Edit[] | null;

// ---------------------------------------------------------------- network

export type RouteKind = 'day' | 'night' | 'special';

export interface Pattern {
  id: string;
  direction: number;
  headsign: string;
  stop_ids: string[];
  path: LonLat[];
  stop_offsets: number[];
}

export interface RouteStats {
  trips: number;
  first_dep: number;
  last_dep: number;
  headway_peak: number | null;
  headway_offpeak: number | null;
  /** mean all-day headway of the busiest direction */
  headway: number | null;
  length_km: number;
  run_time: number;
  speed_kmh: number;
  fleet: number;
  bus_hours: number;
  km: number;
  cost_eur: number;
}

export interface Route {
  id: string;
  short_name: string;
  long_name: string;
  color: string;
  text_color: string;
  kind: RouteKind;
  patterns: Pattern[];
  stats: RouteStats;
  modified: boolean;
  added: boolean;
}

export interface Stop {
  id: string;
  name: string;
  lon: number;
  lat: number;
  routes: string[];
  boardings_weight: number;
  modified: boolean;
  added: boolean;
  removed: boolean;
}

export interface NetworkTotals {
  fleet: number;
  bus_hours: number;
  km: number;
  cost_eur: number;
  trips: number;
}

export interface Network {
  day: DayType;
  routes: Route[];
  stops: Stop[];
  removed_routes: string[];
  totals: NetworkTotals;
  warnings: string[];
}

export interface NetworkRequest {
  scenario: Scenario;
  day: DayType;
}

// ---------------------------------------------------------------- vehicles

export interface VehicleShape {
  id: number;
  path: LonLat[];
  cum_m: number[];
}

export interface VehicleTrip {
  route: string;
  shape: number;
  headsign: string;
  direction: number;
  t: number[];
  d: number[];
}

export interface Vehicles {
  day: DayType;
  shapes: VehicleShape[];
  trips: VehicleTrip[];
}

export type VehiclesRequest = NetworkRequest;

// ---------------------------------------------------------------- routing

export type IsochroneMode = 'transit' | 'walk';

export interface IsochroneRequest {
  origin: LonLat;
  window: AnalysisWindow;
  cutoffs: number[];
  scenario: Scenario;
  mode: IsochroneMode;
}

export interface MultiPolygon {
  type: 'MultiPolygon';
  coordinates: LonLat[][][];
}

export interface Isochrone {
  cutoff: number;
  geometry: MultiPolygon;
  population: number;
  area_km2: number;
  pois: Record<string, number>;
}

export interface IsochroneResponse {
  origin: LonLat;
  mode: IsochroneMode;
  isochrones: Isochrone[];
  reached_stops: { id: string; time: number }[];
}

export interface JourneyRequest {
  origin: LonLat;
  destination: LonLat;
  depart: number;
  day: DayType;
  scenario: Scenario;
}

export type JourneyLeg =
  | { mode: 'walk'; from: LonLat; to: LonLat; duration: number; path: LonLat[] }
  | {
      mode: 'bus';
      route: string;
      headsign: string;
      from_stop: string;
      to_stop: string;
      depart: number;
      arrive: number;
      path: LonLat[];
    };

export interface Journey {
  duration: number;
  depart: number;
  arrive: number;
  legs: JourneyLeg[];
}

// ---------------------------------------------------------------- accessibility (M7+)

export interface AccessibilityRequest {
  window: AnalysisWindow;
  scenario: Scenario;
  threshold: number;
}

export interface AccessibilityCategory {
  id: string;
  n_pois: number;
  pop_within: number;
  share_within: number;
  median_time: number | null;
  mean_time: number | null;
  curve: [number, number][];
}

export interface Accessibility {
  window: AnalysisWindow;
  threshold: number;
  population: number;
  categories: AccessibilityCategory[];
  zones: {
    id: number[];
    population: number[];
    time: Record<string, (number | null)[]>;
    jobs_30: number[];
    /** demand-weighted accessibility index 0..1 */
    access_index: number[];
    /** demand-weighted mean travel time to destinations (s); null when nothing is reachable */
    mean_time: (number | null)[];
    income: (number | null)[];
    section_id: string[];
  };
  equity: {
    quintiles: {
      q: number;
      income_min: number;
      income_max: number;
      population: number;
      share_within: Record<string, number>;
      mean_time: Record<string, number>;
    }[];
    concentration_index: Record<string, number>;
  };
  summary: {
    mean_travel_time: number;
    underserved_population: number;
    objective: number;
    jobs_30_mean: number;
  };
}

export interface ZoneProps {
  id: number;
  population: number;
  municipality?: string;
}
export type ZonesGeoJSON = GeoJSON.FeatureCollection<GeoJSON.Polygon, ZoneProps>;

export interface SectionProps {
  section_id: string;
  municipality: string;
  population: number;
  income_per_capita: number | null;
  income_per_household: number | null;
}
export type SectionsGeoJSON = GeoJSON.FeatureCollection<GeoJSON.Geometry, SectionProps>;

export interface Poi {
  id: number;
  category: string;
  name: string;
  lon: number;
  lat: number;
}

// ---------------------------------------------------------------- scenario evaluation (M8)

export interface CategoryKpi {
  pop_within: number;
  share_within: number;
  mean_time: number | null;
}

export interface Kpis {
  fleet: number;
  bus_hours: number;
  km: number;
  cost_eur_day: number;
  cost_eur_year: number;
  mean_travel_time: number;
  objective: number;
  underserved_population: number;
  jobs_30_mean: number;
  categories: Record<string, CategoryKpi>;
}

export interface EvaluateRequest {
  scenario: Edit[];
  window: AnalysisWindow;
  threshold: number;
}

export interface Evaluation {
  valid: boolean;
  warnings: string[];
  baseline: Kpis;
  scenario: Kpis;
  delta: {
    fleet: number;
    bus_hours: number;
    km: number;
    cost_eur_day: number;
    cost_eur_year: number;
    mean_travel_time: number;
    objective: number;
    objective_pct: number;
    underserved_population: number;
    people_gaining: number;
    people_losing: number;
    categories: Record<string, { pop_within: number; share_within: number }>;
  };
  zones: {
    id: number[];
    delta_time: (number | null)[];
    delta_jobs_30: number[];
    delta_access_index: number[];
  };
  routes: {
    id: string;
    fleet: [number, number];
    bus_hours: [number, number];
    headway_peak: [number | null, number | null];
    trips: [number, number];
  }[];
  elapsed_ms: number;
}
