# HTTP API contract

Base path `/api`. JSON everywhere (`application/json`, gzip). Errors:
`{"detail": "<message>"}` with a 4xx/5xx status. OpenAPI at `/api/docs`.

Conventions: coordinates are `[lon, lat]` WGS84; times are seconds since local
midnight; durations are seconds; `null` means unreachable / not available.

A **scenario** is always passed by value as a list of edits (see below). The server
is stateless with respect to scenarios: results are cached by the hash of the
canonical edit list. `scenario: null` or `[]` means the baseline (today's network).

An **analysis window** is `{ "day": "weekday" | "saturday" | "sunday", "start": 28800, "duration": 3600 }`.
The server maps `day` to a representative service date of the feed.

---

## Meta

### `GET /api/health` → `{ "status": "ok" }`

### `GET /api/meta`

```jsonc
{
  "feed": { "agency": "TCC Pamplona", "start_date": "2026-11-10", "end_date": "2026-11-30",
            "n_routes": 54, "n_stops": 563 },
  "days": { "weekday": "2026-11-11", "saturday": "2026-11-14", "sunday": "2026-11-15" },
  "bbox": [minLon, minLat, maxLon, maxLat],
  "center": [lon, lat],
  "population": 371000,              // residents inside the study area
  "n_zones": 3200,
  "poi_categories": [ { "id": "hospital", "count": 5 }, ... ],
  "default_window": { "day": "weekday", "start": 28800, "duration": 3600 },
  "cost_params": { "eur_per_bus_hour": .., "eur_per_km": .., "eur_per_bus_year": .. , "source": "..." },
  "data_notes": [ "Demand is a gravity model ...", ... ]   // limitations to surface in the UI
}
```

## Network

### `POST /api/network`  body `{ "scenario": Edit[] | null, "day": "weekday" }`

(`GET /api/network?day=weekday` is the baseline shortcut.)

```jsonc
{
  "routes": [ {
      "id": "4", "short_name": "L04", "long_name": "Barañáin - Villava",
      "color": "#E3051B", "text_color": "#FFFFFF",
      "kind": "day" | "night" | "special",
      "patterns": [ {                 // one per direction (the dominant stop sequence)
          "id": "4:0", "direction": 0, "headsign": "Villava",
          "stop_ids": ["12", "13", ...],
          "path": [[lon, lat], ...],                 // street-following polyline
          "stop_offsets": [0, 312.5, ...]            // metres along `path` for each stop
      } ],
      "stats": {                      // for the requested day
          "trips": 142, "first_dep": 23400, "last_dep": 81000,
          "headway_peak": 600, "headway_offpeak": 720,     // seconds, null if < 2 trips
          "length_km": 11.2, "run_time": 2580,             // one direction, peak
          "speed_kmh": 13.1,
          "fleet": 9, "bus_hours": 148.2, "km": 3180.0, "cost_eur": 9300.0   // per day
      },
      "modified": false, "added": false
  } ],
  "stops": [ { "id": "12", "name": "Paseo Sarasate", "lon": -1.64, "lat": 42.81,
               "routes": ["4", "9"], "boardings_weight": 1234.0,
               "modified": false, "added": false, "removed": false } ],
  "totals": { "fleet": 140, "bus_hours": 2100.0, "km": 30000.0, "cost_eur": 150000.0, "trips": 3084 }
}
```

### `POST /api/vehicles`  body `{ "scenario": Edit[] | null, "day": "weekday" }`

Compact data to animate every bus for the whole day. The client interpolates.

```jsonc
{
  "shapes": [ { "id": 0, "path": [[lon, lat], ...], "cum_m": [0, 35.2, ...] } ],
  "trips": [ {
      "route": "4", "shape": 0,
      "t": [23400, 23460, ...],         // time at each waypoint (seconds, non-decreasing)
      "d": [0, 312.5, ...]              // metres along the shape at each waypoint (stops)
  } ]
}
```

## Routing

### `POST /api/isochrone`

Body `{ "origin": [lon, lat], "window": Window, "cutoffs": [900, 1800, 2700], "scenario": Edit[] | null, "mode": "transit" | "walk" }`

```jsonc
{
  "origin": [lon, lat],
  "isochrones": [ { "cutoff": 900, "geometry": { "type": "MultiPolygon", ... },
                    "population": 12000, "area_km2": 3.1,
                    "pois": { "hospital": 1, "health_centre": 3, ... } } ],   // sorted by cutoff asc
  "reached_stops": [ { "id": "12", "time": 420 } ]
}
```

Isochrones are nested (larger cutoff contains the smaller ones).

### `POST /api/journey`

Body `{ "origin": [lon, lat], "destination": [lon, lat], "depart": 28800, "day": "weekday", "scenario": Edit[] | null }`

```jsonc
{ "duration": 1560, "depart": 28800, "arrive": 30360,
  "legs": [ { "mode": "walk", "from": [lon,lat], "to": [lon,lat], "duration": 240, "path": [[lon,lat],...] },
            { "mode": "bus", "route": "4", "headsign": "Villava", "from_stop": "12", "to_stop": "40",
              "depart": 29100, "arrive": 29940, "path": [[lon,lat],...] } ] }
```

## Accessibility

### `POST /api/accessibility`

Body `{ "window": Window, "scenario": Edit[] | null, "threshold": 1800 }`

```jsonc
{
  "window": Window, "threshold": 1800, "population": 371000,
  "categories": [ {
      "id": "hospital", "n_pois": 5,
      "pop_within": 250000, "share_within": 0.674,       // residents reaching >=1 POI within threshold
      "median_time": 1320, "mean_time": 1500,            // population-weighted, to the nearest POI
      "curve": [ [300, 0.02], [600, 0.11], ... ]         // cumulative share by minutes (5-min steps to 60)
  } ],
  "zones": {                                             // column-oriented, aligned by index
      "id": [0, 1, ...], "population": [...],
      "time": { "hospital": [1320, null, ...], ... },    // seconds to nearest POI of each category
      "jobs_30": [...],                                  // gravity/cumulative opportunities index 0..1
      "income": [14500, ...], "section_id": ["31201..."]
  },
  "equity": {
      "quintiles": [ { "q": 1, "income_min": .., "income_max": .., "population": ..,
                       "share_within": { "hospital": 0.6, ... }, "mean_time": { "hospital": 1400, ... } } ],
      "concentration_index": { "hospital": -0.03, ... }
  },
  "summary": { "mean_travel_time": 1620, "underserved_population": 42000 }  // demand-weighted mean; residents failing >= 1 essential category
}
```

### `GET /api/zones` → GeoJSON FeatureCollection of the zone cells (`id`, `population`), static, cacheable.

### `GET /api/sections` → GeoJSON FeatureCollection of census sections (`section_id`, `municipality`, `population`, `income_per_capita`).

### `GET /api/pois` → `{ "pois": [ { "id", "category", "name", "lon", "lat" } ] }`

## Scenarios

`Edit` is a tagged union (`"type"` discriminator):

```jsonc
{ "type": "set_headway", "route_id": "4", "headway": 480, "period": "all" | "peak" | "offpeak" }
{ "type": "scale_frequency", "route_id": "4", "factor": 1.25 }
{ "type": "speed_up", "route_id": "4" | null, "stop_ids": ["12","13","14"], "factor": 1.2 }   // bus priority between consecutive stops
{ "type": "remove_stop", "stop_id": "12" }
{ "type": "move_stop", "stop_id": "12", "lon": .., "lat": .. }
{ "type": "add_stop", "stop_id": "new-1", "name": "..", "lon": .., "lat": .., "route_id": "4", "direction": 0, "after_stop_id": "12" }
{ "type": "remove_route", "route_id": "23" }
{ "type": "add_route", "route_id": "new-A", "short_name": "A", "color": "#1F6FEB",
  "waypoints": [[lon,lat], ...],            // snapped to streets server-side
  "stops": [ { "stop_id": "12" } | { "lon": .., "lat": .., "name": ".." } ],
  "headway": 600, "bidirectional": true, "speed_kmh": null }
```

### `POST /api/scenario/snap`  body `{ "waypoints": [[lon,lat],...] }` → `{ "path": [[lon,lat],...], "length_m": 4200, "nearby_stops": [ { "id", "offset_m", "distance_m" } ] }`

Street-snapped polyline through the waypoints (used while drawing a line).

### `POST /api/scenario/evaluate`

Body `{ "scenario": Edit[], "window": Window, "threshold": 1800 }`

```jsonc
{
  "valid": true, "warnings": ["..."],
  "baseline": Kpis, "scenario": Kpis,
  "delta": {
     "fleet": +2, "bus_hours": +31.0, "km": .., "cost_eur_day": .., "cost_eur_year": ..,
     "mean_travel_time": -42.0,
     "people_gaining": 5200, "people_losing": 300,      // residents whose access time to >=1 essential category crosses the threshold, or whose mean time changes by > 60 s
     "categories": { "hospital": { "pop_within": +3200, "share_within": +0.009 }, ... }
  },
  "zones": { "id": [...], "delta_time": [...],            // seconds, scenario - baseline, demand-weighted mean travel time
             "delta_jobs_30": [...] },
  "routes": [ { "id": "4", "fleet": [9, 11], "bus_hours": [148, 180], "headway_peak": [600, 480] } ],  // [baseline, scenario], changed routes only
  "elapsed_ms": 1840
}
```

`Kpis = { "fleet", "bus_hours", "km", "cost_eur_day", "mean_travel_time", "categories": { id: { "pop_within", "share_within", "mean_time" } }, "jobs_30_mean" }`

## Optimizer

### `POST /api/optimize`

Body:

```jsonc
{ "window": Window,
  "budget": { "kind": "fleet" | "bus_hours", "value": 140 },      // null value = same as baseline
  "moves": ["frequency", "stops", "new_lines"],
  "objective": "accessibility" | "travel_time",
  "base_scenario": Edit[] | null, "seed": 0, "time_limit_s": 60 }
```

→ `{ "job_id": "..." }`

### `GET /api/optimize/{job_id}`

```jsonc
{ "status": "queued" | "running" | "done" | "error", "progress": 0.42, "stage": "frequency MILP",
  "log": [ { "t": 3.2, "msg": "MILP solved: objective +3.1%" } ],
  "history": [ { "iter": 12, "objective": 0.612, "fleet": 140 } ],
  "result": {                       // when done
     "scenario": Edit[],            // the proposal, directly usable in every other endpoint
     "evaluation": <same shape as /api/scenario/evaluate>,
     "explanation": [ { "kind": "frequency", "route_id": "4", "text_key": "...", "params": {...},
                        "delta_objective": 0.004 } ],
     "objective": { "baseline": 0.590, "optimized": 0.612 } } }
```

### `POST /api/optimize/tradeoff`

Body `{ "window": Window, "budget_kind": "fleet", "values": [120, 130, 140, 150, 160], "moves": [...] }` → `{ "job_id" }`;
result: `{ "points": [ { "budget": 120, "objective": .., "mean_travel_time": .., "share_within": {...}, "scenario": Edit[] } ], "baseline": { "budget": 140, "objective": .. } }`

## Report

### `POST /api/report`  body `{ "scenario": Edit[], "window": Window, "lang": "es" | "en", "title": "..." }` → `text/html`

Self-contained HTML report (print-friendly; the browser's print dialog produces the PDF).

---

## Additions made while implementing (all additive)

- `GET /api/health` returns `{"status": "ok" | "loading" | "error", "detail"}`; every other
  endpoint answers `503` while the engine is loading.
- `/api/meta`: `data_notes` is a list of `{ "key", "text" }` (stable keys for translation);
  also `essential_categories` and `feed.n_stops_served_weekday`.
- `/api/network`: `day`, `removed_routes`, `warnings`; `stats.headway` (mean all-day headway).
  `headway_peak` / `headway_offpeak` are **mean** headways of the busiest direction
  (07-09 h and 10-13 h), `null` with fewer than two trips. `boardings_weight` is residents
  within a 5-minute walk shared between the stops in reach, not observed boardings.
  Only routes with trips on the requested day are listed.
- `/api/vehicles` (also `GET ?day=`): trips carry `headsign` and `direction`.
- `/api/isochrone`: `mode` echoed; `reached_stops` covers the largest cutoff.
- `/api/accessibility`: zones add `access_index` and `mean_time`; summary adds `objective`
  and `jobs_30_mean`.
- `/api/scenario/evaluate`: Kpis add `cost_eur_year`, `objective`,
  `underserved_population`; delta adds `objective`, `objective_pct`,
  `underserved_population`; zones add `delta_access_index`; routes add `trips`.
- `/api/scenario/snap`: `nearby_stops` carry `name`; `warnings`.
- Edits: `remove_stop` accepts an optional `route_id`; `scale_frequency` accepts `period`;
  `add_route` accepts `first_dep` / `last_dep`.
- `/api/optimize`: body also takes `threshold`; the result adds `budget {kind, value, used}`,
  `objective.change_pct` and `elapsed_s`. Jobs run one at a time.
- `/api/optimize/tradeoff`: points add `used` and `objective_pct`; `baseline` adds
  `mean_travel_time` and `share_within`.
- `/api/report`: body also takes `threshold`; `scenario` may be empty.
- `/api/vehicles` includes the previous service day's trips that run past midnight, shifted
  by -24 h, so their times can be negative; this keeps the animation continuous at night.
- GeoJSON features of `/api/zones` and `/api/sections` carry a top-level `id`; for zones it is
  the zone index used by every zone-aligned array. `/api/pois` ids are integers.
