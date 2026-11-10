"""Line statistics from a timetable: trips, headways, run times, lengths, speeds."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pandas as pd

from vlab.gtfs.timetable import Timetable

PEAK = (7 * 3600, 9 * 3600)
OFFPEAK = (10 * 3600, 13 * 3600)


def _median_headway(t0: npt.NDArray[np.int64], window: tuple[int, int] | None) -> float | None:
    t = np.sort(t0)
    if window is not None:
        t = t[(t >= window[0]) & (t < window[1])]
    if len(t) < 2:
        return None
    return float(np.median(np.diff(t)))


def _own_day(tt: Timetable, p: int) -> npt.NDArray[np.bool_]:
    a, b = tt.pattern_trips_ptr[p], tt.pattern_trips_ptr[p + 1]
    return ~tt.trip_prev_day[a:b]


def pattern_length_m(tt: Timetable, p: int) -> float:
    """Distance along the shape from first to last stop of pattern ``p``."""
    off = tt.pattern_offsets(p)
    return float(off[-1] - off[0])


def pattern_stats(tt: Timetable) -> pd.DataFrame:
    """One row per pattern (trips of the service day itself; carried-over trips from the
    previous day are excluded).

    Columns: ``pattern``, ``key``, ``route_id``, ``direction``, ``headsign``, ``n_stops``,
    ``trips``, ``first_dep``, ``last_dep``, ``headway_peak``, ``headway_offpeak``,
    ``headway_all`` (median s, NaN if < 2 trips in the window), ``length_km``,
    ``run_time`` (median first-departure → last-arrival, s), ``run_time_peak``,
    ``speed_kmh`` (length / median run time), ``service_km``, ``service_h``.
    """
    rows = []
    for p, info in enumerate(tt.patterns):
        own = _own_day(tt, p)
        arr = tt.arrivals(p)[own].astype(np.int64)
        dep = tt.departures(p)[own].astype(np.int64)
        length_m = pattern_length_m(tt, p)
        n = arr.shape[0]
        t0 = dep[:, 0] if n else np.zeros(0, np.int64)
        run = arr[:, -1] - dep[:, 0] if n else np.zeros(0, np.int64)
        peak = (t0 >= PEAK[0]) & (t0 < PEAK[1])
        run_med = float(np.median(run)) if n else np.nan
        run_peak = float(np.median(run[peak])) if peak.any() else run_med
        hp = _median_headway(t0, PEAK)
        ho = _median_headway(t0, OFFPEAK)
        ha = _median_headway(t0, None)
        rows.append(
            {
                "pattern": p,
                "key": info.key,
                "route_id": tt.routes[info.route_idx].route_id,
                "direction": info.direction,
                "headsign": info.headsign,
                "n_stops": arr.shape[1] if n else len(tt.pattern_stop_seq(p)),
                "trips": n,
                "first_dep": int(t0.min()) if n else None,
                "last_dep": int(t0.max()) if n else None,
                "headway_peak": hp if hp is not None else np.nan,
                "headway_offpeak": ho if ho is not None else np.nan,
                "headway_all": ha if ha is not None else np.nan,
                "length_km": length_m / 1000.0,
                "run_time": run_med,
                "run_time_peak": run_peak,
                "speed_kmh": (length_m / 1000.0) / (run_med / 3600.0)
                if n and run_med > 0
                else np.nan,
                "service_km": n * length_m / 1000.0,
                "service_h": float(run.sum()) / 3600.0,
            }
        )
    return pd.DataFrame(rows)


def route_stats(tt: Timetable) -> pd.DataFrame:
    """One row per route.

    - ``trips``: all trips of the day (both directions);
    - headways: median interval between consecutive departures from the first stop of
      the route's busiest direction (all its patterns merged, since short-turn variants
      share the trunk), in the peak (07-09), off-peak (10-13) and all day;
    - ``length_km`` / ``run_time`` (peak median): busiest pattern of the busiest
      direction;
    - ``speed_kmh``: service-km weighted commercial speed over all patterns
      (Σ km / Σ scheduled hours).
    """
    ps = pattern_stats(tt)
    rows = []
    for r, info in enumerate(tt.routes):
        sub = ps[ps["route_id"] == info.route_id]
        sub = sub[sub["trips"] > 0]
        if sub.empty:
            continue
        by_dir = sub.groupby("direction")["trips"].sum()
        main_dir = int(by_dir.index.to_numpy()[int(np.argmax(by_dir.to_numpy()))])
        t0_parts = []
        for p in sub.loc[sub["direction"] == main_dir, "pattern"]:
            own = _own_day(tt, int(p))
            t0_parts.append(tt.departures(int(p))[own][:, 0].astype(np.int64))
        t0 = np.concatenate(t0_parts)
        main = sub[sub["direction"] == main_dir].sort_values("trips", ascending=False).iloc[0]
        hours = sub["service_h"].sum()
        rows.append(
            {
                "route_idx": r,
                "route_id": info.route_id,
                "short_name": info.short_name,
                "kind": info.kind,
                "trips": int(sub["trips"].sum()),
                "first_dep": int(sub["first_dep"].min()),
                "last_dep": int(sub["last_dep"].max()),
                "headway_peak": _median_headway(t0, PEAK),
                "headway_offpeak": _median_headway(t0, OFFPEAK),
                "headway_all": _median_headway(t0, None),
                "length_km": float(main["length_km"]),
                "run_time": float(main["run_time_peak"]),
                "speed_kmh": float(sub["service_km"].sum() / hours) if hours > 0 else np.nan,
                "service_km": float(sub["service_km"].sum()),
                "service_h": float(hours),
            }
        )
    return pd.DataFrame(rows)


def network_speed_kmh(tt: Timetable, kinds: tuple[str, ...] = ("day",)) -> float:
    """Service-km weighted commercial speed (Σ shape km / Σ scheduled run hours) over
    routes of the given kinds. Excludes terminal layovers, as operators usually do."""
    rs = route_stats(tt)
    rs = rs[rs["kind"].isin(kinds)]
    return float(rs["service_km"].sum() / rs["service_h"].sum())


def vehicles_in_service(tt: Timetable, times: npt.ArrayLike) -> npt.NDArray[np.int64]:
    """Number of trips in motion (first departure <= t < last arrival) at each time.

    A lower bound on the fleet: excludes layover/recovery at terminals and spare buses.
    """
    t = np.asarray(times, dtype=np.int64)
    starts, ends = [], []
    for p in range(tt.n_patterns):
        starts.append(tt.departures(p)[:, 0])
        ends.append(tt.arrivals(p)[:, -1])
    s = np.sort(np.concatenate(starts).astype(np.int64))
    e = np.sort(np.concatenate(ends).astype(np.int64))
    return (np.searchsorted(s, t, side="right") - np.searchsorted(e, t, side="right")).astype(
        np.int64
    )


def mean_headways(tt: Timetable, route: int | str) -> dict[str, float | None]:
    """Mean headways (s) of a route in its busiest direction: ``peak`` (07-09 h),
    ``offpeak`` (10-13 h) and ``all`` (first to last departure).

    Defined as period length / trips started in the period, pooling every
    pattern of the direction. Unlike a median of gaps this is well defined for
    lines with branches and short-turn variants, and it is the quantity that
    ``set_headway`` edits target. ``None`` when fewer than two trips.
    """
    r = tt.route_index[route] if isinstance(route, str) else int(route)
    best: npt.NDArray[np.int64] = np.zeros(0, dtype=np.int64)
    by_dir: dict[int, list[npt.NDArray[np.int64]]] = {}
    for p in tt.patterns_of_route(r):
        t0 = tt.departures(p)[:, 0].astype(np.int64)[_own_day(tt, p)]
        by_dir.setdefault(tt.patterns[p].direction, []).append(t0)
    for parts in by_dir.values():
        t = np.sort(np.concatenate(parts))
        if len(t) > len(best):
            best = t
    out: dict[str, float | None] = {"peak": None, "offpeak": None, "all": None}
    if len(best) >= 2:
        out["all"] = float(best[-1] - best[0]) / (len(best) - 1)
    for name, (lo, hi) in (("peak", PEAK), ("offpeak", OFFPEAK)):
        n = int(((best >= lo) & (best < hi)).sum())
        if n >= 2:
            out[name] = float(hi - lo) / n
    return out
