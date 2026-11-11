"""Application service: turns engine objects into the JSON shapes of docs/api.md.

One :class:`Service` wraps a loaded :class:`vlab.model.Model` and caches the
expensive intermediate results (scenario networks, evaluations) keyed by the
canonical hash of the edit list.
"""

from __future__ import annotations

import functools
import json
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any, TypeVar

import numpy as np
import shapely
from shapely.geometry import mapping

from vlab.access import isochrone as iso
from vlab.access import journey as jr
from vlab.access import metrics as M
from vlab.access.service import (
    AccessSummary,
    EvalResult,
    Evaluator,
    equity,
)
from vlab.cost.model import NetworkCost, annual_cost, network_cost
from vlab.gtfs import to_xy
from vlab.gtfs.geometry import cumulative_length
from vlab.gtfs.stats import mean_headways
from vlab.gtfs.timetable import Timetable
from vlab.model.world import DAY_TYPES, ESSENTIAL_CATEGORIES, Model, NetworkState, Window
from vlab.optimize import Budget, Optimizer, Progress
from vlab.scenario import (
    Edit,
    ScenarioNetwork,
    apply,
    edit_to_dict,
    nearby_stops,
    scenario_hash,
    snap_path,
)
from vlab_api import report

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])

#: numba's default threading layer is not safe to enter from several Python
#: threads at once, and FastAPI runs sync endpoints in a thread pool. Every
#: compute entry point therefore runs under this one lock; each request already
#: uses all cores inside the kernels, so serialising requests costs nothing.
ENGINE_LOCK = threading.RLock()


def locked[F: Callable[..., Any]](fn: F) -> F:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with ENGINE_LOCK:
            return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


DATA_NOTES: list[dict[str, str]] = [
    {
        "key": "demand_gravity",
        "text": "Demand is modelled, not observed: there is no public origin-destination "
        "matrix, so trips follow a gravity model built from population and activity.",
    },
    {
        "key": "population_dasymetric",
        "text": "Population per 200 m cell is estimated by spreading each census section's "
        "residents over its residential floor area (INE 2024, Navarra cadastre).",
    },
    {
        "key": "activity_proxy",
        "text": "Activity is non-residential floor area, a proxy for jobs and services, "
        "not actual employment.",
    },
    {
        "key": "schedule_based",
        "text": "Travel times come from the published timetable: no delays, crowding or "
        "fares; access to stops is on foot only.",
    },
    {
        "key": "cost_tariff",
        "text": "Costs use the operator tariff of the pre-2024 concession (2023 prices); "
        "the current contract's unit prices are not public.",
    },
    {
        "key": "stop_weight",
        "text": "Stop weights are residents within a 5-minute walk, not observed boardings.",
    },
]


class LRU:
    """Small thread-safe LRU cache with single-flight computation per key."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._data: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()
        self._key_locks: dict[Hashable, threading.Lock] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable, compute: Callable[[], T]) -> T:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]  # type: ignore[no-any-return]
            klock = self._key_locks.setdefault(key, threading.Lock())
        with klock:
            with self._lock:
                if key in self._data:
                    self.hits += 1
                    return self._data[key]  # type: ignore[no-any-return]
            try:
                value = compute()
            except BaseException:
                with self._lock:
                    self._key_locks.pop(key, None)
                raise
            with self._lock:
                self.misses += 1
                self._data[key] = value
                self._data.move_to_end(key)
                while len(self._data) > self._size:
                    self._data.popitem(last=False)
                self._key_locks.pop(key, None)
            return value


def num(x: float | None, digits: int = 1) -> float | None:
    """JSON-safe number: NaN/inf become ``None``."""
    if x is None:
        return None
    f = float(x)
    if not math.isfinite(f):
        return None
    return round(f, digits)


def _coords(arr: Any) -> list[list[float]]:
    a = np.round(np.asarray(arr, dtype=np.float64), 6)
    return a.tolist()  # type: ignore[no-any-return]


def _times(a: np.ndarray) -> list[int | None]:
    return [None if v == 65535 else int(v) for v in a.tolist()]


class Service:
    def __init__(self, model: Model) -> None:
        self.model = model
        self._scenarios = LRU(48)
        self._evals = LRU(12)
        self._evaluators = LRU(6)
        self._payloads = LRU(24)
        self._static: dict[str, Any] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ plumbing
    def scenario(
        self, edits: tuple[Edit, ...], day: str, *, strict: bool = True
    ) -> ScenarioNetwork:
        key = (scenario_hash(edits), day, strict)
        return self._scenarios.get(key, lambda: apply(self.model, day, edits, strict=strict))

    def evaluator(self, window: Window) -> Evaluator:
        return self._evaluators.get(window.key(), lambda: Evaluator(self.model, window))

    def evaluation(self, edits: tuple[Edit, ...], window: Window) -> EvalResult:
        ev = self.evaluator(window)
        if not edits:
            return self._evals.get(
                ("base", window.key()),
                lambda: EvalResult(
                    ev.baseline_summary.objective,
                    ev.baseline_summary.mean_travel_time,
                    network_cost(ev.baseline_state.timetable, self.model.cost_params),
                    ev.baseline_summary,
                    ev.baseline_tt,
                ),
            )
        key = (scenario_hash(edits), window.key())
        return self._evals.get(key, lambda: ev.evaluate(self.scenario(edits, window.day).state))

    @locked
    def warm_up(self) -> None:
        """Compile the kernels and compute the default-window baseline."""
        w = Window()
        self.evaluation((), w)
        self.isochrone(tuple(self.meta()["center"]), w, [900, 1800, 2700], (), "transit")

    # ---------------------------------------------------------------------- meta
    def meta(self) -> dict[str, Any]:
        m = self.model
        feed_dates = sorted(m.feed.calendar_dates["date"].unique().tolist())
        tt = m.baseline("weekday").timetable
        served = {int(s) for s in tt.pattern_stops}
        b = m.bbox

        def iso_date(v: Any) -> str:
            s = str(v)
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s[:10]

        return {
            "feed": {
                "agency": str(m.feed.agency["agency_name"].iloc[0]),
                "start_date": iso_date(feed_dates[0]),
                "end_date": iso_date(feed_dates[-1]),
                "n_routes": len(m.feed.routes),
                "n_stops": len(m.feed.stops),
                "n_stops_served_weekday": len(served),
            },
            "days": {d: m.dates[d].isoformat() for d in DAY_TYPES},
            "bbox": [round(v, 5) for v in b],
            "center": [-1.6440, 42.8169],
            "population": int(m.population.sum()),
            "n_zones": m.n_zones,
            "poi_categories": [{"id": c, "count": m.category_counts[c]} for c in m.categories],
            "essential_categories": list(ESSENTIAL_CATEGORIES),
            "default_window": {"day": "weekday", "start": 8 * 3600, "duration": 3600},
            "cost_params": m.cost_params.as_dict(),
            "data_notes": DATA_NOTES,
        }

    # ------------------------------------------------------------------- network
    @locked
    def network(self, edits: tuple[Edit, ...], day: str) -> dict[str, Any]:
        key = ("network", scenario_hash(edits), day)
        return self._payloads.get(key, lambda: self._network(edits, day))

    def _catchment(self, state: NetworkState) -> np.ndarray:
        """Residents within a 5-minute walk of each stop, shared equally between the
        stops in reach (a transparent proxy; NOT observed boardings)."""
        acc = state.access
        near = acc.seconds <= 300
        zone = np.repeat(np.arange(acc.n_rows), np.diff(acc.indptr))
        cnt = np.bincount(zone[near], minlength=acc.n_rows)
        w = np.divide(self.model.population, cnt, out=np.zeros(acc.n_rows), where=cnt > 0)
        return np.bincount(acc.indices[near], weights=w[zone[near]], minlength=acc.n_cols)

    def _network(self, edits: tuple[Edit, ...], day: str) -> dict[str, Any]:
        sn = self.scenario(edits, day)
        tt = sn.state.timetable
        ch = sn.changes
        cost = network_cost(tt, self.model.cost_params)
        routes = []
        stop_routes: dict[int, list[str]] = {}
        for r, info in enumerate(tt.routes):
            pats = [p for p in tt.patterns_of_route(r) if tt.n_pattern_trips(p) > 0]
            if not pats:
                continue
            for p in pats:
                for s in tt.pattern_stop_seq(p):
                    lst = stop_routes.setdefault(int(s), [])
                    if info.route_id not in lst:
                        lst.append(info.route_id)
            main: dict[int, int] = {}
            for p in pats:
                d = tt.patterns[p].direction
                cur = main.get(d)
                if cur is None or (tt.n_pattern_trips(p), len(tt.pattern_stop_seq(p))) > (
                    tt.n_pattern_trips(cur),
                    len(tt.pattern_stop_seq(cur)),
                ):
                    main[d] = p
            patterns = []
            for d in sorted(main):
                p = main[d]
                off = tt.pattern_offsets(p)
                patterns.append(
                    {
                        "id": f"{info.route_id}:{d}",
                        "direction": int(d),
                        "headsign": tt.patterns[p].headsign,
                        "stop_ids": [tt.stop_ids[int(s)] for s in tt.pattern_stop_seq(p)],
                        "path": _coords(tt.pattern_path(p)),
                        "stop_offsets": np.round(off - off[0], 1).tolist(),
                    }
                )
            p0 = main[min(main)]
            starts = np.concatenate(
                [
                    tt.departures(p)[:, 0][
                        ~tt.trip_prev_day[tt.pattern_trips_ptr[p] : tt.pattern_trips_ptr[p + 1]]
                    ]
                    for p in pats
                ]
            )
            run = float(np.median(tt.arrivals(p0)[:, -1] - tt.departures(p0)[:, 0]))
            off0 = tt.pattern_offsets(p0)
            length_km = float(off0[-1] - off0[0]) / 1000.0
            hw = mean_headways(tt, r)
            rc = cost.routes[info.route_id]
            routes.append(
                {
                    "id": info.route_id,
                    "short_name": info.short_name,
                    "long_name": info.long_name,
                    "color": info.color,
                    "text_color": info.text_color,
                    "kind": info.kind,
                    "patterns": patterns,
                    "stats": {
                        "trips": rc.trips,
                        "first_dep": int(starts.min()) if len(starts) else None,
                        "last_dep": int(starts.max()) if len(starts) else None,
                        "headway_peak": num(hw["peak"], 0),
                        "headway_offpeak": num(hw["offpeak"], 0),
                        "headway": num(hw["all"], 0),
                        "length_km": round(length_km, 2),
                        "run_time": int(run),
                        "speed_kmh": num(length_km / (run / 3600.0), 1) if run > 0 else None,
                        "fleet": rc.fleet,
                        "bus_hours": round(rc.bus_hours, 1),
                        "km": round(rc.km, 1),
                        "cost_eur": round(rc.cost_eur, 0),
                    },
                    "modified": info.route_id in ch.modified_routes,
                    "added": info.route_id in ch.added_routes,
                }
            )
        weight = self._catchment(sn.state)
        base_served = (
            {int(s) for s in self.model.baseline(day).timetable.pattern_stops} if edits else set()
        )
        stops = []
        for s in sorted(set(stop_routes) | base_served):
            sid = tt.stop_ids[s]
            stops.append(
                {
                    "id": sid,
                    "name": tt.stop_names[s],
                    "lon": round(float(tt.stop_lon[s]), 6),
                    "lat": round(float(tt.stop_lat[s]), 6),
                    "routes": stop_routes.get(s, []),
                    "boardings_weight": round(float(weight[s]), 1),
                    "modified": sid in ch.modified_stops,
                    "added": sid in ch.added_stops,
                    "removed": s not in stop_routes,
                }
            )
        return {
            "day": day,
            "routes": routes,
            "stops": stops,
            "removed_routes": sorted(ch.removed_routes),
            "totals": _totals(cost),
            "warnings": list(ch.warnings),
        }

    # ------------------------------------------------------------------ vehicles
    @locked
    def vehicles(self, edits: tuple[Edit, ...], day: str) -> dict[str, Any]:
        key = ("vehicles", scenario_hash(edits), day)
        return self._payloads.get(key, lambda: self._vehicles(edits, day))

    def _vehicles(self, edits: tuple[Edit, ...], day: str) -> dict[str, Any]:
        tt = self.scenario(edits, day).state.timetable
        shapes: list[dict[str, Any]] = []
        shape_of: dict[tuple[int, int, int, int], tuple[int, float]] = {}
        trips: list[dict[str, Any]] = []
        for p in range(tt.n_patterns):
            n = tt.n_pattern_trips(p)
            if n == 0:
                continue
            off = tt.pattern_offsets(p)
            si = tt.patterns[p].shape_idx
            key = (si if si >= 0 else -1 - p, round(float(off[0])), round(float(off[-1])), 0)
            if key not in shape_of:
                path = tt.pattern_path(p)
                x, y = to_xy(path[:, 0], path[:, 1])
                cum = cumulative_length(x, y)
                shape_of[key] = (len(shapes), float(cum[-1]))
                shapes.append(
                    {"id": len(shapes), "path": _coords(path), "cum_m": np.round(cum, 1).tolist()}
                )
            sid, length = shape_of[key]
            span = float(off[-1] - off[0])
            d = np.round((off - off[0]) * (length / span if span > 0 else 0.0), 1).tolist()
            info = tt.patterns[p]
            route = tt.routes[info.route_idx].route_id
            arr = tt.arrivals(p)
            dep0 = tt.departures(p)[:, 0]
            for k in range(n):
                t = arr[k].tolist()
                t[0] = int(dep0[k])
                trips.append(
                    {
                        "route": route,
                        "shape": sid,
                        "headsign": info.headsign,
                        "direction": int(info.direction),
                        "t": t,
                        "d": d,
                    }
                )
        trips.sort(key=lambda tr: tr["t"][0])
        return {"day": day, "shapes": shapes, "trips": trips}

    # ------------------------------------------------------------------- routing
    @locked
    def isochrone(
        self,
        origin: tuple[float, float],
        window: Window,
        cutoffs: list[int],
        edits: tuple[Edit, ...],
        mode: str,
    ) -> dict[str, Any]:
        m = self.model
        state = self.scenario(edits, window.day).state
        cutoffs = sorted(set(cutoffs))
        field = iso.time_field(m, state, origin, window, cutoffs[-1], mode)
        polys = iso.polygons(m, field, cutoffs)
        zt = iso.point_times(m, field, "zones")
        pt = iso.point_times(m, field, "pois")
        cats = m.pois["category"].to_numpy()
        out = []
        for c in cutoffs:
            reached = pt <= c
            out.append(
                {
                    "cutoff": c,
                    "geometry": mapping(polys[c]),
                    "population": int(m.population[zt <= c].sum()),
                    "area_km2": round(iso.area_km2(polys[c]), 2),
                    "pois": {k: int((reached & (cats == k)).sum()) for k in m.categories},
                }
            )
        tt = state.timetable
        st = field.stop_time
        idx = np.flatnonzero(st <= cutoffs[-1])
        return {
            "origin": [round(origin[0], 6), round(origin[1], 6)],
            "mode": mode,
            "isochrones": out,
            "reached_stops": [
                {"id": tt.stop_ids[int(s)], "time": int(st[s])} for s in idx[np.argsort(st[idx])]
            ],
        }

    @locked
    def journey(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        depart: int,
        day: str,
        edits: tuple[Edit, ...],
    ) -> dict[str, Any] | None:
        j = jr.plan(self.model, self.scenario(edits, day).state, origin, destination, depart)
        if j is None:
            return None
        legs = []
        for g in j.legs:
            leg: dict[str, Any] = {
                "mode": g.mode,
                "from": [round(g.start[0], 6), round(g.start[1], 6)],
                "to": [round(g.end[0], 6), round(g.end[1], 6)],
                "depart": g.depart,
                "arrive": g.arrive,
                "duration": g.duration,
                "path": g.path,
            }
            if g.mode == "bus":
                leg.update(route=g.route_id, headsign=g.headsign)
            if g.from_stop:
                leg["from_stop"] = g.from_stop
            if g.to_stop:
                leg["to_stop"] = g.to_stop
            legs.append(leg)
        return {"duration": j.duration, "depart": j.depart, "arrive": j.arrive, "legs": legs}

    # ------------------------------------------------------------- accessibility
    def _summary(self, edits: tuple[Edit, ...], window: Window, threshold: int) -> AccessSummary:
        res = self.evaluation(edits, window)
        assert res.summary is not None and res.tt is not None
        if threshold == res.summary.threshold:
            return res.summary
        from vlab.access.service import summarise

        key = ("summary", scenario_hash(edits), window.key(), threshold)
        ev = self.evaluator(window)
        tt = res.tt
        return self._payloads.get(key, lambda: summarise(self.model, tt, ev.demand, threshold))

    @locked
    def accessibility(
        self, window: Window, edits: tuple[Edit, ...], threshold: int
    ) -> dict[str, Any]:
        m = self.model
        s = self._summary(edits, window, threshold)
        groups, ci = equity(m, s)
        return {
            "window": {"day": window.day, "start": window.start, "duration": window.duration},
            "threshold": threshold,
            "population": int(m.population.sum()),
            "categories": [
                {
                    "id": c,
                    "n_pois": ca.n_pois,
                    "pop_within": round(ca.pop_within),
                    "share_within": round(ca.share_within, 4),
                    "median_time": num(ca.median_time, 0),
                    "mean_time": num(ca.mean_time, 0),
                    "curve": [[t, round(v, 4)] for t, v in ca.curve],
                }
                for c, ca in s.categories.items()
            ],
            "zones": {
                "id": list(range(m.n_zones)),
                "population": m.population.astype(int).tolist(),
                "time": {c: _times(ca.time) for c, ca in s.categories.items()},
                "jobs_30": np.round(s.jobs, 4).tolist(),
                "access_index": np.round(s.hansen, 5).tolist(),
                "mean_time": [num(v, 0) for v in s.zone_mean_time.tolist()],
                "income": [num(v, 0) for v in m.income.tolist()],
                "section_id": m.zones["section_id"].tolist(),
            },
            "equity": {
                "quintiles": [
                    {
                        "q": g.q,
                        "income_min": round(g.income_min),
                        "income_max": round(g.income_max),
                        "population": round(g.population),
                        "share_within": {k: num(v, 4) for k, v in g.share_within.items()},
                        "mean_time": {k: num(v, 0) for k, v in g.mean_time.items()},
                    }
                    for g in groups
                ],
                "concentration_index": {k: num(v, 4) for k, v in ci.items()},
            },
            "summary": {
                "mean_travel_time": num(s.mean_travel_time, 0),
                "underserved_population": round(s.underserved_population),
                "objective": round(s.objective, 6),
                "jobs_30_mean": round(s.jobs_mean, 4),
            },
        }

    # -------------------------------------------------------------------- static
    def zones_geojson(self) -> bytes:
        return self._static_json("zones", self._zones_geojson)

    def sections_geojson(self) -> bytes:
        return self._static_json("sections", self._sections_geojson)

    def pois(self) -> bytes:
        return self._static_json("pois", self._pois)

    def _static_json(self, key: str, build: Callable[[], Any]) -> bytes:
        with self._lock:
            if key not in self._static:
                self._static[key] = json.dumps(build(), separators=(",", ":")).encode()
            return self._static[key]  # type: ignore[no-any-return]

    def _zones_geojson(self) -> dict[str, Any]:
        z = self.model.zones
        feats = []
        for i, geom in enumerate(z["geometry"]):
            g = shapely.set_precision(geom, 1e-6)
            feats.append(
                {
                    "type": "Feature",
                    "id": i,
                    "properties": {
                        "id": i,
                        "population": int(z["population"].iloc[i]),
                        "municipality": str(z["municipality"].iloc[i]),
                    },
                    "geometry": mapping(g),
                }
            )
        return {"type": "FeatureCollection", "features": feats}

    def _sections_geojson(self) -> dict[str, Any]:
        s = self.model.sections
        feats = []
        for i, geom in enumerate(s["geometry"]):
            row = s.iloc[i]
            feats.append(
                {
                    "type": "Feature",
                    "id": i,
                    "properties": {
                        "section_id": str(row["section_id"]),
                        "municipality": str(row["municipality"]),
                        "population": int(row["population"]),
                        "income_per_capita": num(row["income_per_capita"], 0),
                        "income_per_household": num(row["income_per_household"], 0),
                    },
                    "geometry": mapping(shapely.set_precision(geom, 1e-5)),
                }
            )
        return {"type": "FeatureCollection", "features": feats}

    def _pois(self) -> dict[str, Any]:
        p = self.model.pois
        ids = p["poi_id"].to_numpy()
        cat = p["category"].to_numpy()
        name = p["name"].to_numpy()
        lon = p["lon"].to_numpy(np.float64)
        lat = p["lat"].to_numpy(np.float64)
        return {
            "pois": [
                {
                    "id": int(ids[i]),
                    "category": str(cat[i]),
                    "name": str(name[i]),
                    "lon": round(float(lon[i]), 6),
                    "lat": round(float(lat[i]), 6),
                }
                for i in range(len(p))
            ]
        }

    # ----------------------------------------------------------------- scenarios
    @locked
    def snap(self, waypoints: list[list[float]]) -> dict[str, Any]:
        sp = snap_path(self.model.drive, waypoints)
        tt = self.model.baseline("weekday").timetable
        near = nearby_stops(tt, sp.coords)
        return {
            "path": _coords(sp.coords),
            "length_m": round(sp.length_m, 1),
            "nearby_stops": [
                {
                    "id": tt.stop_ids[s],
                    "name": tt.stop_names[s],
                    "offset_m": round(o, 1),
                    "distance_m": round(d, 1),
                }
                for s, o, d in near
            ],
            "warnings": list(sp.warnings),
        }

    def _annual(self, edits: tuple[Edit, ...]) -> dict[str, float]:
        key = ("annual", scenario_hash(edits))

        def build() -> dict[str, float]:
            by: dict[str, NetworkCost] = {
                d: network_cost(
                    self.scenario(edits, d, strict=False).state.timetable, self.model.cost_params
                )
                for d in DAY_TYPES
            }
            return annual_cost(by, self.model.cost_params)

        return self._payloads.get(key, build)

    def _kpis(
        self, res: EvalResult, summary: AccessSummary, annual: dict[str, float]
    ) -> dict[str, Any]:
        return {
            "fleet": res.cost.fleet,
            "bus_hours": round(res.cost.bus_hours, 1),
            "km": round(res.cost.km, 1),
            "cost_eur_day": round(res.cost.cost_eur, 0),
            "cost_eur_year": round(annual["total_eur"], 0),
            "mean_travel_time": num(summary.mean_travel_time, 1),
            "objective": round(summary.objective, 6),
            "jobs_30_mean": round(summary.jobs_mean, 4),
            "underserved_population": round(summary.underserved_population),
            "categories": {
                c: {
                    "pop_within": round(ca.pop_within),
                    "share_within": round(ca.share_within, 4),
                    "mean_time": num(ca.mean_time, 0),
                }
                for c, ca in summary.categories.items()
            },
        }

    @locked
    def evaluate(self, edits: tuple[Edit, ...], window: Window, threshold: int) -> dict[str, Any]:
        t0 = time.perf_counter()
        m = self.model
        sn = self.scenario(edits, window.day)
        base_res = self.evaluation((), window)
        scen_res = self.evaluation(edits, window)
        base = self._summary((), window, threshold)
        scen = self._summary(edits, window, threshold)
        b = self._kpis(base_res, base, self._annual(()))
        s = self._kpis(scen_res, scen, self._annual(edits))
        gain, lose = M.people_gaining_losing(
            {c: ca.time for c, ca in base.categories.items()},
            {c: ca.time for c, ca in scen.categories.items()},
            base.zone_mean_time,
            scen.zone_mean_time,
            m.population,
            threshold,
            ESSENTIAL_CATEGORIES,
        )
        d_time = scen.zone_mean_time.astype(np.float64) - base.zone_mean_time.astype(np.float64)
        ch = sn.changes
        base_tt = m.baseline(window.day).timetable
        scen_tt = sn.state.timetable
        routes = []
        for rid in sorted(ch.modified_routes | ch.added_routes | ch.removed_routes):
            bc = base_res.cost.routes.get(rid)
            sc = scen_res.cost.routes.get(rid)
            bh = mean_headways(base_tt, rid)["peak"] if rid in base_tt.route_index else None
            sh = mean_headways(scen_tt, rid)["peak"] if rid in scen_tt.route_index else None
            routes.append(
                {
                    "id": rid,
                    "fleet": [bc.fleet if bc else 0, sc.fleet if sc else 0],
                    "bus_hours": [
                        round(bc.bus_hours, 1) if bc else 0.0,
                        round(sc.bus_hours, 1) if sc else 0.0,
                    ],
                    "trips": [bc.trips if bc else 0, sc.trips if sc else 0],
                    "headway_peak": [num(bh, 0), num(sh, 0)],
                }
            )
        return {
            "valid": True,
            "warnings": list(ch.warnings),
            "baseline": b,
            "scenario": s,
            "delta": {
                "fleet": s["fleet"] - b["fleet"],
                "bus_hours": round(s["bus_hours"] - b["bus_hours"], 1),
                "km": round(s["km"] - b["km"], 1),
                "cost_eur_day": round(s["cost_eur_day"] - b["cost_eur_day"], 0),
                "cost_eur_year": round(s["cost_eur_year"] - b["cost_eur_year"], 0),
                "mean_travel_time": num(scen.mean_travel_time - base.mean_travel_time, 1),
                "objective": round(scen.objective - base.objective, 6),
                "objective_pct": num(100.0 * (scen.objective / base.objective - 1.0), 2)
                if base.objective > 0
                else None,
                "underserved_population": s["underserved_population"] - b["underserved_population"],
                "people_gaining": round(gain),
                "people_losing": round(lose),
                "categories": {
                    c: {
                        "pop_within": s["categories"][c]["pop_within"]
                        - b["categories"][c]["pop_within"],
                        "share_within": round(
                            s["categories"][c]["share_within"] - b["categories"][c]["share_within"],
                            4,
                        ),
                    }
                    for c in b["categories"]
                },
            },
            "zones": {
                "id": list(range(m.n_zones)),
                "delta_time": [num(v, 0) for v in d_time.tolist()],
                "delta_jobs_30": np.round(scen.jobs - base.jobs, 4).tolist(),
                "delta_access_index": np.round(scen.hansen - base.hansen, 5).tolist(),
            },
            "routes": routes,
            "elapsed_ms": round(1000 * (time.perf_counter() - t0)),
        }


# ---------------------------------------------------------------- optimizer + report


def run_optimize(
    svc: Service,
    progress: Progress,
    *,
    window: Window,
    budget: Budget,
    moves: tuple[str, ...],
    objective: str,
    base_edits: tuple[Edit, ...],
    seed: int,
    time_limit_s: float,
    threshold: int,
) -> dict[str, Any]:
    """Body of an optimizer job: runs outside the request, taking ENGINE_LOCK only
    around each engine call so that other requests stay responsive."""
    ev = svc.evaluator(window)
    opt = Optimizer(
        svc.model,
        ev,
        base_edits=base_edits,
        objective=objective,  # type: ignore[arg-type]
        seed=seed,
        lock=ENGINE_LOCK,
        progress=progress,
    )
    res = opt.run(budget, moves, time_limit_s)  # type: ignore[arg-type]
    evaluation = svc.evaluate(res.edits, window, threshold)
    return {
        "scenario": res.scenario,
        "evaluation": evaluation,
        "explanation": [
            {
                "kind": e.kind,
                "route_id": e.route_id,
                "text_key": e.text_key,
                "params": e.params,
                "delta_objective": round(e.delta_objective, 6),
            }
            for e in res.explanation
        ],
        "objective": {
            "baseline": round(res.baseline.objective, 6),
            "optimized": round(res.optimized.objective, 6),
            "change_pct": num(100.0 * (res.optimized.objective / res.baseline.objective - 1.0), 2)
            if res.baseline.objective
            else None,
        },
        "budget": {"kind": res.budget_kind, "value": res.budget, "used": res.used},
        "elapsed_s": round(res.elapsed_s, 1),
    }


def run_tradeoff(
    svc: Service,
    progress: Progress,
    *,
    window: Window,
    budget_kind: str,
    values: list[float],
    seed: int,
) -> dict[str, Any]:
    ev = svc.evaluator(window)
    opt = Optimizer(svc.model, ev, seed=seed, lock=ENGINE_LOCK, progress=progress)
    points = opt.tradeoff(budget_kind, values)  # type: ignore[arg-type]
    with ENGINE_LOCK:
        base = svc.evaluation((), window)
    assert base.summary is not None
    used = float(base.cost.fleet if budget_kind == "fleet" else base.cost.bus_hours)
    return {
        "budget_kind": budget_kind,
        "points": [
            {
                "budget": p.budget,
                "used": p.used,
                "objective": round(p.objective, 6),
                "objective_pct": num(100.0 * (p.objective / base.objective - 1.0), 2),
                "mean_travel_time": num(p.mean_travel_time, 1),
                "share_within": {c: round(v, 4) for c, v in p.share_within.items()},
                "scenario": p.scenario,
            }
            for p in points
        ],
        "baseline": {
            "budget": used,
            "objective": round(base.objective, 6),
            "mean_travel_time": num(base.mean_travel_time, 1),
            "share_within": {
                c: round(ca.share_within, 4) for c, ca in base.summary.categories.items()
            },
        },
    }


def render_report(
    svc: Service, edits: tuple[Edit, ...], window: Window, threshold: int, lang: str, title: str
) -> str:
    evaluation = svc.evaluate(edits, window, threshold)
    net = svc.network(edits, window.day)
    base_net = svc.network((), window.day)
    names = {r["id"]: r["short_name"] for r in base_net["routes"] + net["routes"]}
    colors = {r["id"]: r["color"] for r in base_net["routes"] + net["routes"]}
    stops = {s["id"]: s["name"] for s in base_net["stops"] + net["stops"]}
    paths = [(r["id"], p["path"]) for r in net["routes"] for p in r["patterns"][:1]]
    m = svc.model
    return report.render(
        title=title,
        lang=lang,
        window={"day": window.day, "start": window.start, "duration": window.duration},
        threshold=threshold,
        evaluation=evaluation,
        edits=[edit_to_dict(e) for e in edits],
        route_names=names,
        route_colors=colors,
        stop_names=stops,
        zone_lon=m.zone_lon,
        zone_lat=m.zone_lat,
        population=m.population,
        paths=paths,
        date=m.dates[window.day].isoformat(),
    )


def _totals(cost: NetworkCost) -> dict[str, Any]:
    return {
        "fleet": cost.fleet,
        "bus_hours": round(cost.bus_hours, 1),
        "km": round(cost.km, 1),
        "cost_eur": round(cost.cost_eur, 0),
        "trips": cost.trips,
    }


def timetable_of(svc: Service, edits: tuple[Edit, ...], day: str) -> Timetable:
    return svc.scenario(edits, day).state.timetable
