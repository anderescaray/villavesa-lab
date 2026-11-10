# Router: GTFS timetable, walking layer and RAPTOR

This document covers milestone M2: how the official TUC GTFS becomes RAPTOR-ready
arrays (`vlab.gtfs`), how walking is modelled (`vlab.walk`), the from-scratch RAPTOR
router (`vlab.raptor`), how it is tested, how fast it is, and what the timetable says
about the real network.

## 1. Data model

### Feed (`vlab.gtfs.load_feed`)

`load_feed(path) -> Feed` reads the zip with pyarrow's CSV reader (UTF-8 BOM stripped,
every column read as a string, then typed explicitly) and validates it:

- required files and columns (`agency`, `routes`, `stops`, `trips`, `stop_times`, plus
  `calendar.txt` and/or `calendar_dates.txt`);
- unique ids; referential integrity trips→routes / services / shapes and
  stop_times→trips / stops;
- times `H:MM:SS` with hours > 23 allowed, departure ≥ arrival, non-decreasing along
  each trip, no duplicated `stop_sequence`, ≥ 2 stops per trip; missing intermediate
  times are interpolated by stop position (none in this feed);
- coordinates inside WGS84 ranges and not `(0, 0)`.

Errors raise `FeedValidationError` with counts and examples. `stop_times` is stored with
dense integer keys (`trip_idx`, `stop_idx`) and `int32` seconds. A parsed copy is cached
as parquet in `data/cache/gtfs/<zip sha256>-v<version>/` (git-ignored; override with
`$VLAB_CACHE_DIR`): cold load 1.1 s, warm load 65 ms.

### Service days (`vlab.gtfs.calendar`)

`service_dates`, `active_services`, `trips_mask`, `trip_counts`, `classify_dates`
(weekday / saturday / sunday, and `holiday` for a Mon–Sat date whose trip count is
closer to the modal Sunday count than to its own type's) and
`representative_dates()` = for each type the earliest date with the modal trip count.

| Day type | Representative date | Trips | Other dates of the type |
| --- | --- | --- | --- |
| weekday | 2026-11-11 (Wed) | 3,084 | Mon–Wed 3,084; Thu 3,243 and Fri 3,256 (extra night service); Tue 10 Nov 3,085 |
| saturday | 2026-11-14 | 2,700 | all 2,700 |
| sunday | 2026-11-15 | 1,763 | all 1,763 |

No holiday timetable appears in the feed window (10–30 Nov 2026).

### Timetable (`vlab.gtfs.build_timetable(feed, date) -> Timetable`)

An immutable dataclass of read-only numpy arrays for one service date:

| Field | Shape / type | Meaning |
| --- | --- | --- |
| `stop_ids`, `stop_names` | `tuple[str]` (S) | dense stop index ↔ GTFS id |
| `stop_lon`, `stop_lat`, `stop_x`, `stop_y` | `f64[S]` | WGS84 and EPSG:25830 |
| `routes` | `tuple[RouteInfo]` | id, short/long name, `#RRGGBB` colours, `kind` (day/night/special), route_type |
| `patterns` | `tuple[PatternInfo]` (P) | stable `key` (`route:direction:n`), `route_idx`, `direction`, `headsign`, `shape_idx`, `parent` (FIFO split) |
| `pattern_route` | `i32[P]` | route index per pattern |
| `pattern_stops_ptr` → `pattern_stops` | `i32[P+1]` → `i32` | stop sequence of each pattern |
| `pattern_stop_offset_m` | `f64` (aligned with `pattern_stops`) | metres along the shape of each stop |
| `pattern_trips_ptr` | `i32[P+1]` | global trip rows of each pattern |
| `pattern_times_ptr` → `arr`, `dep` | `i64[P+1]` → `i32` | row-major `[n_trips × n_stops]` block per pattern |
| `trip_source`, `trip_prev_day` | `i32[T]`, `bool[T]` | row in `feed.trips` (-1 = synthetic); carried over from the previous day |
| `stop_patterns_ptr` → `stop_patterns`, `stop_patterns_pos` | CSR | every (pattern, position) occurrence of a stop |
| `shape_ids`, `shape_ptr`, `shape_lon`, `shape_lat`, `shape_cum_m` | CSR polylines | shapes used on that date, cumulative metres |

Accessors: `arrivals(p)`, `departures(p)` (views), `pattern_stop_seq(p)`,
`pattern_offsets(p)`, `pattern_path(p, from_pos, to_pos)` (shape polyline between two
stops, for drawing ride legs), `stop_index`, `route_index`, `pattern_index`,
`patterns_of_route`, `raptor_arrays()`.

Construction details:

- **Patterns** are unique `(route, direction, exact stop sequence)`. Trips are sorted by
  departure at the first stop. **FIFO is guaranteed**: if a trip overtakes another at any
  stop the pattern is split greedily into non-overtaking chains (sub-pattern keys
  `<key>~i`, `parent=<key>`). On the weekday 6 patterns had one overtaking trip each
  (L04, L06, L07×2, L12, L18 — short express/variant timings).
- **Overnight**: trips of the previous service day that run past 24:00 are included,
  shifted by −24 h and flagged `trip_prev_day` (42 trips on the weekday), so a 00:30
  query sees night buses that left at 23:50 "yesterday". Statistics exclude them.
- **Stops on shapes**: each pattern's stops are projected onto its (modal) shape with a
  **monotone dynamic programme**: among all assignments with non-decreasing positions
  it minimises the sum of stop–shape distances (O(stops × segments)). This is robust to
  loops and out-and-back shapes, where a greedy nearest-segment projection jumps to the
  wrong pass. On this feed the worst stop is 1.4 m from its shape.
- `validate_timetable(tt)` checks every invariant the router relies on (sizes, FIFO,
  time monotonicity, offsets, stop→pattern index); the tests run it after every edit.

### Cheap modification (`vlab.gtfs.edit`)

All functions are pure: they return a new `Timetable` sharing unchanged stop, route and
shape arrays; per-pattern blocks are views, and only the edited pattern is re-sorted and
FIFO-checked; the flat arrays and stop→pattern index are rebuilt by concatenation
(**1.6 ms** for a one-pattern edit on the weekday).

- `with_pattern_trips(tt, p, arr, dep)`, `with_pattern_stops(tt, p, stops, arr, dep, offsets)`,
  `with_patterns_removed(tt, ps)`, `with_route_removed(tt, route_id)`,
  `with_pattern_added(tt, stop_seq, arr, dep, meta, offsets)`, `with_route_added(tt, RouteInfo)`,
  `with_stops_added(tt, ids, names, lon, lat)`, `with_stops_moved(tt, idx, lon, lat)`,
  `with_pattern_info(tt, p, **fields)`.
- `running_profile(tt, p, bin_s=3600) -> RunningProfile`: median arrival/departure offsets
  from the first departure, per departure-time bin (empty bins take the nearest one).
  `RunningProfile.scaled(factor, segments)` speeds up running time (not dwell) on some or
  all links (bus priority). `RunningProfile.constant(...)` builds one by hand.
- `synthesize_trips(profile, first_dep, last_dep, headway) -> (arr, dep)`: regular trips;
  overtaking between bins is removed by holding the later bus, so the result is FIFO.
- `scale_pattern_frequency(tt, p, factor)`: same span, headway ÷ factor.

Pattern indices can shift after removals or splits; `PatternInfo.key` is the stable
handle. A transfer table must be rebuilt after adding stops (the router checks sizes).

### Line statistics (`vlab.gtfs.stats`)

`pattern_stats(tt)` and `route_stats(tt)` (DataFrames): trips, first/last departure,
median headways in the peak (07–09), off-peak (10–13) and all day, length (shape metres
between first and last stop), median run time (peak), commercial speed, service-km and
scheduled hours. Route headways merge all patterns of the busiest direction (short-turn
variants share the trunk), so they describe the trunk frequency.
`network_speed_kmh(tt)` and `vehicles_in_service(tt, times)` feed the sanity checks.

## 2. Walking layer (`vlab.walk`)

- `WalkGraph.load(walk_graph.npz)` validates the CSR contract (symmetric; the real graph
  has 67,762 nodes, 177,732 directed edges, one connected component).
- **Snapping**: KD-tree in EPSG:25830; a point attaches to its `SNAP_K = 3` nearest nodes
  within `SNAP_MAX_M = 250 m`, each with its straight-line distance as an extra walk
  offset (a multi-source start avoids artefacts when the single nearest node is on the
  wrong side of a block). All 563 stops snap (median 11 m, max 34 m). Points that do not
  snap fall back to straight line × `DETOUR_FACTOR = 1.3`.
- **Dijkstra**: numba, binary heap with lazy deletion, multi-source with offsets, bounded
  by a cutoff, on CSR; `many_to_many` runs one bounded search per source group in
  parallel (`prange`, per-chunk scratch buffers reset only on touched nodes), and
  serially for ≤ 8 sources (a parallel launch costs more than one bounded search; on a
  loaded machine it pushed a single-point query from ~1 ms to 20–100 ms).
- `build_transfers(graph, stops, max_m=400)`: stop→stop footpaths by network distance
  (snap connectors included), symmetric, no self-loops. Stops closer than
  `SAME_PLACE_M = 30 m` use the straight-line distance (co-located stops ≈ 0 s). 3,356
  pairs on the real network (median 220 s); 10 stops have no other stop within 400 m.
- `build_access(graph, (lon, lat), stops, max_m=1000)`: points→stops seconds (CSR
  `WalkTable`). The Dijkstra runs from whichever side is smaller (identical results on
  a symmetric graph; tested). Egress = `build_access(...).transpose()`.
  1,794 zones: 80 ms; a single ad-hoc point (isochrone origin): **1.2 ms**.
- `WalkGraph.shortest_path(a, b)` / `path_through(waypoints)`: node polyline + length
  (for walking legs and for snapping drawn lines to streets — note this is the
  *pedestrian* graph).
- `WALK_SPEED_MPS = 1.25` (4.5 km/h) is the single default; every function takes a
  `speed` argument. Times are rounded up to whole seconds.
- Transfer and access tables are cached in `data/cache/walk/` keyed by a SHA-256 of the
  graph arrays, coordinates and parameters (access only for > 50 points).
- `euclidean_table(...)` builds straight-line tables (fallback without a graph; tests).

## 3. RAPTOR (`vlab.raptor`)

Implemented from scratch after Delling, Pajor & Werneck, *Round-Based Public Transit
Routing* (2012), in `@njit(cache=True)` kernels (`vlab/raptor/kernels.py`).

### Semantics (exactly what is computed)

A journey is *access walk → ride → [footpath] → ride → [footpath] → …* with at most
`max_rounds` rides (default 4 = up to 3 transfers).

- **Multi-source access**: the query takes source stops with individual access offsets
  (seconds) and a departure time; round 0 labels are `dep_time + offset`.
- **Board slack** (`board_slack`, default 60 s) is required before *every* boarding,
  including the first: `dep(trip, s) ≥ arrival(s) + slack`. A transfer at the same stop
  therefore costs the slack; a walking transfer costs footpath time + slack.
- **Footpaths** are relaxed once after each round, only from stops reached by a ride in
  that round (standard single-hop transfers; no footpath chains). The transfer table is
  *not* transitively closed, so to stay exact two labels are kept per round and stop:
  `T[k, s]` (best arrival alighting in round k — only these start footpaths) and
  `A[k, s]` (best arrival with ≤ k rides by any means — only these are used to board in
  round k+1). Pruning a ride arrival uses the best *ride* arrival so far, so a stop
  reached early on foot still lets a later ride arrival start a footpath. Optional
  `foot_round0=True` allows a footpath right after the access walk (off by default: the
  access table already contains every stop within 1 km).
- **Round k**: collect patterns serving stops improved in round k−1 with the earliest
  improved position; scan each from there, keeping the current trip; at each stop first
  try to alight (local pruning against `tbest`/`best` and against `max_arrival`), then
  check whether an *earlier* trip can be caught (binary search over the column of
  departures, valid because patterns are FIFO).
- **Pruning**: local pruning plus a time bound `max_arrival = dep_time + max_duration`
  (the matrix kernel uses `dep_time + cap`). Loop lines that revisit a stop are handled
  (every occurrence is indexed). Times past midnight are plain integers.

### API

```python
raptor(tt, transfers, sources, dep_time, offsets=None, *, max_rounds=4, board_slack=60,
       max_duration=None, foot_round0=False) -> RaptorResult
    # .arrival int32[S] (INF = 2**31-1), .rounds (A) and .ride (T) int32[K+1, S],
    # parent arrays, .travel_time(), .reached()
raptor_from_access(tt, transfers, access, row, dep_time, **kw) -> RaptorResult
reconstruct_journey(tt, result, target_stop) -> list[Leg] | None
    # Leg(mode="access"|"walk"|"ride", from_stop, to_stop, depart, arrive,
    #     pattern, trip, board_pos, alight_pos); earliest arrival, then fewest rides
raptor_batch(tt, transfers, access, dep_times, ...) -> int32[n_origins, n_dep, S]
travel_time_matrix(tt, transfers, access, egress, dep_times, direct_walk=None, *,
                   max_rounds=4, board_slack=60, cap=7200, min_reachable_frac=0.5)
    -> uint16[n_origins, n_dest]     # 65535 = unreachable
departure_samples(start, duration, step=600) -> int64[...]
```

### Travel time over a departure window (decision D-006)

`travel_time_matrix` runs entirely inside one parallel numba kernel (`prange` over
origins, buffers allocated once per origin): for each origin and departure sample `t0`,
RAPTOR from the origin's access row → best arrival per stop → min-plus with the egress
CSR (stop→destination seconds) → element-wise min with the optional direct-walk matrix
→ sample value, unreachable if > `cap` (default 7,200 s).

Aggregation per OD pair (the definition used everywhere downstream):

- **reachable** iff at least `ceil(min_reachable_frac × n_dep)` samples (default half,
  minimum 1) are reachable;
- **value** = mean over **all** samples, where unreachable samples count as `cap`
  (a censored mean), rounded to the nearest second.

Why a censored mean rather than the mean of reachable samples only: the latter is not
monotone — cutting service can make a sample unreachable and *lower* the reported mean.
With censoring, removing service never improves a value (tested), which the scenario
diff and the optimizer rely on. Arrival labels include round 0, so "walk to a stop, walk
from it" counts as a (walking) journey, bounded by access + egress radii; the caller
should still pass a proper direct-walk matrix (and 0 on the diagonal).

### Complexity

One query costs O(K · (Σ stops of scanned patterns + Σ footpaths of improved stops)),
with a binary search per boarding attempt — independent of the number of trips except
logarithmically. With S = 563, P = 209 and K = 4 that is ~10⁴ elementary steps. The
matrix kernel adds O(n_dep · Σ_s |egress(s)|) per origin for the min-plus step.

## 4. Benchmarks

`uv run python engine/benchmarks/bench_raptor.py` (4 cores, numba 0.68, warm JIT
cache; 3,000 origins = the 1,794 real zones + 1,206 random points in the stops' bbox):

| Operation | Time |
| --- | --- |
| load_feed, cold (parse zip + validate) | 1.13 s |
| load_feed, warm (parquet cache) | 65 ms |
| build_timetable (209 patterns, 3,126 trips) | 98 ms |
| with_pattern_trips (one pattern edited, full rebuild) | 1.6 ms |
| build_transfers 400 m (67,762 nodes, 3,356 pairs) | 14 ms |
| build_access 3,000 points × 1 km (30,364 pairs) | 86 ms |
| build_access, single ad-hoc point (isochrone origin) | 1.2 ms |
| raptor one-to-all, 1 source stop, 4 rounds (incl. Python call) | 141 µs |
| raptor one-to-all from a zone's access row | 100 µs |
| travel_time_matrix 3,000 × 3,000 × 6 departures | 0.78 s (≈23,000 queries/s) |
| travel_time_matrix 1,794 real zones² × 6 departures | 0.41 s |

The first call in a fresh environment compiles the kernels (~5–10 s); numba's on-disk
cache (`cache=True`) removes that on later runs. Range-RAPTOR was not needed: plain
RAPTOR × K departures already meets the "few seconds" budget with a large margin.

## 5. Tests

`uv run pytest engine/tests -k "gtfs or walk or raptor"` (~10 s warm):

- **Feed** (`test_gtfs_feed.py`): parsing (BOM, > 24 h times, defaults), every validation
  error on a synthetic mini feed, calendar.txt support, holiday detection, cache
  round-trip and a < 0.5 s warm load, real-feed counts and day types.
- **Timetable / edits** (`test_gtfs_timetable.py`, `test_gtfs_edit.py`): invariants, FIFO
  splitting, monotone projection on a loop shape, overnight carry-over, times equal to
  the feed's stop_times, shape paths; every edit validated, input untouched, < 20 ms.
- **Walk** (`test_walk_graph.py`): bounded distances equal SciPy's Dijkstra on a
  synthetic irregular grid, both access directions identical, transpose, symmetric
  transfers ≥ straight line, fallback, paths, caching, single-point < 5 ms (median), and
  the real graph when present.
- **RAPTOR toy cases** (`test_raptor_toy.py`): slack (incl. first boarding), same-stop
  and walking transfers, round limit, no footpath chains, the two-label case, overtaking
  express, past midnight and carried-over trips, multi-source offsets, pruning, loop
  lines, journey legs.
- **RAPTOR vs reference on the real feed** (`test_raptor_reference.py`): an independent
  brute-force implementation built directly from `feed.stop_times` (so it also checks
  pattern grouping, FIFO splitting and overnight handling) computes the per-round labels
  by scanning every trip. **270 random queries** (single stops at 0:00–25:00 with slack
  60 s and 0 s; multi-source with offsets, 1–5 rounds, with and without `foot_round0`)
  **match exactly in every round** with the real network footpaths. Reconstructed
  journeys (400) are checked leg by leg (chaining, slack, footpath times, positions).
  Invariants: later departure never arrives earlier; more rounds never worse; more
  slack never better; removing a route never helps.
- **Matrix** (`test_raptor_matrix.py`): `travel_time_matrix` equals a brute force built
  from single queries for three cap/fraction/direct-walk settings; censored-mean
  semantics; batch = single queries; real zones end-to-end.
- **Baseline** (`test_gtfs_baseline.py`): below.

## 6. Baseline sanity checks vs reality

| Day type | Date | Trips | Patterns | Day-line commercial speed | Max trips in motion 07–09 |
| --- | --- | --- | --- | --- | --- |
| weekday | 2026-11-11 | 3,084 | 209 | 12.3 km/h | 139 |
| saturday | 2026-11-14 | 2,700 | 165 | 12.6 km/h | 91 |
| sunday | 2026-11-15 | 1,763 | 159 | 12.6 km/h | 68 |

- **Commercial speed**: Σ shape-km / Σ scheduled run hours over day lines (`L01`–`L25`),
  terminal layovers excluded. The feed gives **12.3 km/h** on a weekday vs the ≈ 13 km/h
  the operator reports — within 6 %; the difference is plausibly definitional (the
  operator's figure is an annual average over all services and may use different
  lengths). Per line it ranges from 9.6 km/h (L05, city centre) to 15.6 km/h (L16, L22,
  L25, suburban). The test asserts 11–14.5 km/h.
- **Peak vehicles**: at most **139 trips are simultaneously in motion** in the weekday
  07–09 peak. That is a lower bound on the fleet (no layover/recovery time, no spares),
  consistent with the ≈ 140–160 buses TUC operates. The test asserts 120–170.
- **Run times**: a RAPTOR query restricted to one line, departing just before a trip,
  reproduces that trip's scheduled arrival at every stop (busiest pattern of every route).
- Service volume (weekday): 25,158 service-km and 2,048 scheduled bus-hours (in motion).

## 7. Limitations

- No fares, no vehicle capacity/crowding, no reliability: the schedule is assumed to be
  run exactly (deterministic timetable, no real-time data).
- Earliest arrival only (no Pareto set over transfers/walking; ties resolved to fewest
  rides in reconstruction). Transfer penalty = board slack only.
- Walking-only access/egress (no bike, park-and-ride); flat 4.5 km/h, no slopes,
  crossings or barriers beyond what the OSM pedestrian graph encodes.
- Footpaths are single-hop and limited to 400 m (not transitively closed) — the standard
  RAPTOR assumption, documented and reproduced exactly by the reference.
- `pickup_type`/`drop_off_type` are not modelled (all 0 in this feed); `frequencies.txt`
  is not supported (absent).
- One modal shape and headsign per pattern; trips of a pattern with another shape are
  drawn on the modal one.
- Stops that fail to snap to the walk graph (none today) are reachable from other
  points only through the straight-line fallback of the *points* side.
- Headway statistics per route merge the patterns of the busiest direction, so a route
  with interleaved short-turns shows its trunk frequency.

## 8. Decisions taken in M2 (to be recorded in `docs/decisions.md`)

- **Two labels per round (`A` and `T`)** to make single-hop footpaths exact without
  requiring a transitively closed transfer graph.
- **Board slack applied to every boarding** (60 s), including the first one.
- **Censored mean** for the departure-window travel time (unreachable samples count as
  `cap`; reachable iff ≥ half the samples), for monotonicity under service cuts.
- **Overnight carry-over** of previous-day trips into each date's timetable.
- **FIFO by splitting** in the builder and in edits; **FIFO by holding** in synthesized
  trips.
- **Monotone DP projection** of stops onto shapes.
- **Multi-node snapping** (3 nearest nodes within 250 m) and a straight-line × 1.3
  fallback; same-place (< 30 m) transfers use straight-line distance.
- No range-RAPTOR: the plain kernel already meets the performance budget.
