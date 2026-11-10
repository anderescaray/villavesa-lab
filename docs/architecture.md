# Architecture and contracts

```
data/raw (GTFS, OSM, INE)  --scripts/build_data.py-->  data/processed (compact, committed)
                                                              |
engine/src/vlab  (GTFS timetable, walk graph, RAPTOR, accessibility, cost, scenarios, optimizer)
                                                              |
api/src/vlab_api (FastAPI: loads the engine once, serves JSON under /api)
                                                              |
web/ (React + TS + MapLibre GL + deck.gl; talks only to /api)
```

Conventions used everywhere:

- Coordinates on the wire: WGS84 `[lon, lat]`. Metric computations: EPSG:25830.
- Times: seconds since local midnight (GTFS style, may exceed 86400). Durations in seconds.
- IDs: GTFS ids are strings. Internal indices are dense `int32`.
- Unreachable travel time: `65535` in `uint16` matrices; `null` on the wire.

## Processed data bundle (`data/processed/`)

| File                 | Content                                                                                                                                                                                                                         |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `study_area.geojson` | One polygon: convex hull of GTFS stops buffered 1.5 km.                                                                                                                                                                         |
| `sections.parquet`   | GeoParquet, census sections intersecting the study area: `section_id` (CUSEC), `municipality`, `population`, `income_per_capita`, `income_per_household` (nullable), `geometry`.                                                |
| `zones.parquet`      | GeoParquet, 200 m cells (EPSG:25830 grid, geometry stored in 4326): `zone_id` (0..N-1 dense), `x`, `y` (cell centre, 25830), `lon`, `lat`, `population`, `activity_weight` (non-residential floor area, m², a proxy for jobs/activity), `n_pois`, `section_id`, `municipality`, `geometry`. Only cells with population > 0, activity or a POI. |
| `pois.parquet`       | `poi_id`, `category`, `name`, `lon`, `lat`, `weight`, `source`. Categories: `hospital`, `health_centre`, `university`, `industrial_estate`, `city_centre`, `secondary_school`, `supermarket`.                                    |
| `walk_graph.npz`     | Pedestrian network clipped to the study area: `node_lon`, `node_lat` (float64), `indptr`, `indices` (int32), `length_m` (float32) — symmetric CSR.                                                                              |
| `manifest.json`      | Source URLs, download dates, licences, row counts, checksums.                                                                                                                                                                   |

The GTFS zip is read directly from `data/raw/gtfs_tuc_pamplona.zip`.

## Engine public surface (`vlab`)

- `vlab.gtfs`: `load_feed(path) -> Feed` (validated tables), `build_timetable(feed, date) -> Timetable`
  (RAPTOR arrays: patterns, stop sequences, trip times, shapes).
- `vlab.walk`: `WalkGraph.load(path)`, snapping, bounded Dijkstra, `build_transfers`, `build_access`.
- `vlab.raptor`: `raptor(timetable, sources, dep_time, ...) -> arrival per stop` (numba), journey reconstruction.
- `vlab.access`: travel-time matrix zones x zones for an analysis window, cumulative
  accessibility metrics, isochrones.
- `vlab.demand`: gravity model.
- `vlab.cost`: fleet, bus-hours, km, cost per line and network.
- `vlab.scenario`: `Scenario` = list of typed edits over the baseline; `apply(baseline, scenario) -> Network`; `diff`.
- `vlab.optimize`: frequency reallocation (MILP), stop consolidation, new lines (ALNS), trade-off curve.

## HTTP API

See `docs/api.md` (the contract the web app is built against). OpenAPI is served at `/api/docs`.
