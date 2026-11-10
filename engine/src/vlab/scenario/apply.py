"""Apply scenario edits to a baseline network.

Every edit is a pure transformation of the timetable (plus, when stops change,
of the walking tables). Semantics are documented per function and in
docs/engine.md. All modelling constants are module-level and overridable.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace

import numpy as np
import numpy.typing as npt

from vlab.gtfs import to_xy
from vlab.gtfs.geometry import cumulative_length, project_monotone
from vlab.gtfs.stats import PEAK, mean_headways, network_speed_kmh
from vlab.gtfs.timetable import (
    PatternBlock,
    PatternInfo,
    RouteInfo,
    Timetable,
    assemble,
    blocks_of,
    normalize_block,
)
from vlab.model.world import Model, NetworkState
from vlab.scenario.edits import (
    AddRoute,
    AddStop,
    ChangeLog,
    Edit,
    MoveStop,
    RemoveRoute,
    RemoveStop,
    ScaleFrequency,
    ScenarioError,
    SetHeadway,
    SpeedUp,
)
from vlab.walk import WalkGraph

#: Time saved downstream when a stop is removed (deceleration + dwell + acceleration).
STOP_TIME_SAVING_S = 20
#: Time added downstream when a stop is inserted.
STOP_TIME_PENALTY_S = 20
#: Minimum scheduled time between consecutive stops of a new route.
MIN_SEGMENT_S = 20
#: A moved stop further than this from its old position triggers a warning.
MOVE_WARN_M = 300.0
#: Stops within this distance of a drawn path are proposed as its stops.
NEARBY_STOP_M = 40.0
DAY_END_S = 48 * 3600

F64 = npt.NDArray[np.float64]


@dataclass(frozen=True, eq=False)
class ScenarioNetwork:
    """A scenario applied to one day type."""

    state: NetworkState
    changes: ChangeLog


@dataclass(frozen=True)
class SnappedPath:
    coords: F64  # [n, 2] lon/lat
    length_m: float
    warnings: tuple[str, ...]


# ====================================================================== public API


def apply(model: Model, day: str, edits: tuple[Edit, ...]) -> ScenarioNetwork:
    """Apply ``edits`` in order to the baseline of ``day``."""
    base = model.baseline(day)
    log = ChangeLog()
    if not edits:
        return ScenarioNetwork(base, log)
    tt = base.timetable
    stops_changed = False
    for e in edits:
        if isinstance(e, SetHeadway | ScaleFrequency):
            tt = _frequency(tt, e, log)
        elif isinstance(e, SpeedUp):
            tt = _speed_up(tt, e, log)
        elif isinstance(e, RemoveStop):
            tt = _remove_stop(tt, e, log)
        elif isinstance(e, MoveStop):
            tt = _move_stop(tt, e, log)
            stops_changed = True
        elif isinstance(e, AddStop):
            tt = _add_stop(tt, e, log)
            stops_changed = True
        elif isinstance(e, RemoveRoute):
            tt = _remove_route(tt, e, log)
        elif isinstance(e, AddRoute):
            n_before = tt.n_stops
            tt = _add_route(model, tt, e, log, _default_speed(model))
            stops_changed |= tt.n_stops != n_before
        else:  # pragma: no cover - exhaustive
            raise ScenarioError(f"unsupported edit {e!r}")
    if stops_changed:
        state = model.state_for(tt)
    else:
        state = NetworkState(tt, base.transfers, base.access, base.egress)
    return ScenarioNetwork(state, log)


def snap_path(graph: WalkGraph, waypoints: npt.ArrayLike) -> SnappedPath:
    """Street-following polyline through ``waypoints`` on a (directed) graph.

    A leg that cannot be routed (off-network point, disconnected one-way) falls
    back to a straight segment and is reported in ``warnings``.
    """
    wp = np.asarray(waypoints, dtype=np.float64).reshape(-1, 2)
    if len(wp) < 2:
        raise ScenarioError("need at least two waypoints")
    parts: list[F64] = []
    warnings: list[str] = []
    for i in range(len(wp) - 1):
        a, b = (float(wp[i, 0]), float(wp[i, 1])), (float(wp[i + 1, 0]), float(wp[i + 1, 1]))
        res = graph.shortest_path(a, b, snap_max_m=300.0)
        straight = _dist_m(a, b)
        if not res.found or res.length_m > 6.0 * straight + 1500.0:
            coords = np.array([a, b], dtype=np.float64)
            warnings.append(
                f"leg {i + 1} could not be snapped to the street network; drawn as a straight line"
            )
        else:
            coords = res.coords[1:-1] if len(res.coords) > 3 else res.coords
        parts.append(coords if i == 0 else coords[1:] if len(coords) > 1 else coords)
    line = _dedupe(np.vstack(parts))
    x, y = to_xy(line[:, 0], line[:, 1])
    return SnappedPath(line, float(cumulative_length(x, y)[-1]), tuple(warnings))


def nearby_stops(
    tt: Timetable, path: F64, max_m: float = NEARBY_STOP_M
) -> list[tuple[int, float, float]]:
    """Existing stops within ``max_m`` of a path: ``(stop_idx, offset_m, distance_m)``
    ordered along the path."""
    px, py = to_xy(path[:, 0], path[:, 1])
    cum = cumulative_length(px, py)
    out: list[tuple[int, float, float]] = []
    lo_x, hi_x, lo_y, hi_y = px.min() - max_m, px.max() + max_m, py.min() - max_m, py.max() + max_m
    cand = np.flatnonzero(
        (tt.stop_x >= lo_x) & (tt.stop_x <= hi_x) & (tt.stop_y >= lo_y) & (tt.stop_y <= hi_y)
    )
    ax, ay = px[:-1], py[:-1]
    dx, dy = np.diff(px), np.diff(py)
    seg2 = np.maximum(dx * dx + dy * dy, 1e-9)
    for s in cand:
        t = np.clip(((tt.stop_x[s] - ax) * dx + (tt.stop_y[s] - ay) * dy) / seg2, 0.0, 1.0)
        d = np.hypot(tt.stop_x[s] - (ax + t * dx), tt.stop_y[s] - (ay + t * dy))
        k = int(np.argmin(d))
        if d[k] <= max_m:
            out.append((int(s), float(cum[k] + t[k] * math.sqrt(seg2[k])), float(d[k])))
    out.sort(key=lambda r: r[1])
    return out


# ========================================================================= helpers


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    x, y = to_xy(np.array([a[0], b[0]]), np.array([a[1], b[1]]))
    return float(math.hypot(x[1] - x[0], y[1] - y[0]))


def _dedupe(line: F64) -> F64:
    keep = np.ones(len(line), dtype=bool)
    keep[1:] = np.any(np.abs(np.diff(line, axis=0)) > 1e-9, axis=1)
    return line[keep]


def _default_speed(model: Model) -> float:
    """Mean commercial speed of day lines on the weekday baseline (km/h, includes dwell)."""
    cached = getattr(model, "_default_speed_kmh", None)
    if cached is None:
        cached = float(network_speed_kmh(model.baseline("weekday").timetable))
        object.__setattr__(model, "_default_speed_kmh", cached)
    return float(cached)


def _route_idx(tt: Timetable, route_id: str) -> int:
    try:
        return tt.route_index[route_id]
    except KeyError:
        raise ScenarioError(f"unknown route_id {route_id!r}") from None


def _stop_idx(tt: Timetable, stop_id: str) -> int:
    try:
        return tt.stop_index[stop_id]
    except KeyError:
        raise ScenarioError(f"unknown stop_id {stop_id!r}") from None


def _rebuild(tt: Timetable, blocks: list[PatternBlock], changed: set[int]) -> Timetable:
    """Assemble blocks, normalising (sort + FIFO split) only the changed ones."""
    out: list[PatternBlock] = []
    for i, b in enumerate(blocks):
        if i in changed:
            if b.arr.shape[0] == 0 and len(b.stops) >= 2:
                out.append(b)
            else:
                out.extend(normalize_block(b))
        else:
            out.append(b)
    # sub-pattern keys created by a previous split may collide with new splits
    seen: dict[str, int] = {}
    for b in out:
        k = b.info.key
        if k in seen:
            seen[k] += 1
            b.info = replace(b.info, key=f"{k}~r{seen[k]}")
        else:
            seen[k] = 0
    return assemble(tt, out, normalize=False)


# ======================================================================= frequency


def _resample_starts(t: npt.NDArray[np.int64], n_new: int) -> npt.NDArray[np.int64]:
    """``n_new`` start times spread like the ``len(t)`` sorted old ones (same span and
    time-of-day density)."""
    n = len(t)
    if n_new <= 0 or n == 0:
        return np.zeros(0, dtype=np.int64)
    if n == 1:
        half = 900.0
        knots_y = np.array([t[0] - half, t[0], t[0] + half])
        knots_x = np.array([0.0, 0.5, 1.0])
    else:
        h0, h1 = float(t[1] - t[0]), float(t[-1] - t[-2])
        knots_x = np.concatenate([[0.0], (np.arange(n) + 0.5) / n, [1.0]])
        knots_y = np.concatenate([[t[0] - h0 / 2], t.astype(np.float64), [t[-1] + h1 / 2]])
    q = (np.arange(n_new) + 0.5) / n_new
    out: npt.NDArray[np.int64] = np.round(np.interp(q, knots_x, knots_y)).astype(np.int64)
    return out


def _retime_group(
    blocks: list[PatternBlock],
    group: list[int],
    sels: list[npt.NDArray[np.bool_]],
    n_new: int,
) -> None:
    """Replace the selected own-day trips of the patterns of one direction by
    ``n_new`` trips, in place.

    The combined start times of the direction are resampled together, so the
    combined headway stays regular; each new trip copies the pattern and the
    running times of the old trip closest in departure time (short-turn
    variants therefore keep their share and their time of day), and a later bus
    never overtakes an earlier one of the same pattern (it is held).
    """
    old_t = np.concatenate(
        [blocks[i].dep[sel, 0].astype(np.int64) for i, sel in zip(group, sels, strict=True)]
    )
    old_g = np.concatenate([np.full(int(sel.sum()), j) for j, sel in enumerate(sels)])
    old_row = np.concatenate([np.flatnonzero(sel) for sel in sels])
    order = np.argsort(old_t, kind="stable")
    old_t, old_g, old_row = old_t[order], old_g[order], old_row[order]
    new_t = _resample_starts(old_t, n_new)
    near = np.clip(np.searchsorted(old_t, new_t), 0, len(old_t) - 1)
    left = np.clip(near - 1, 0, len(old_t) - 1)
    near = np.where(np.abs(old_t[left] - new_t) <= np.abs(old_t[near] - new_t), left, near)
    for j, (i, sel) in enumerate(zip(group, sels, strict=True)):
        if not sel.any():
            continue
        b = blocks[i]
        arr, dep = b.arr.astype(np.int64), b.dep.astype(np.int64)
        mine = old_g[near] == j
        t = new_t[mine]
        proto = old_row[near[mine]]
        new_arr = t[:, None] + (arr[proto] - dep[proto, :1])
        new_dep = t[:, None] + (dep[proto] - dep[proto, :1])
        if len(t) > 1:
            new_arr = np.maximum.accumulate(new_arr, axis=0)
            new_dep = np.maximum.accumulate(np.maximum(new_dep, new_arr), axis=0)
        keep = ~sel
        blocks[i] = PatternBlock(
            b.info,
            b.stops,
            np.vstack([arr[keep], new_arr]).astype(np.int32),
            np.vstack([dep[keep], new_dep]).astype(np.int32),
            b.offsets,
            np.concatenate([b.trip_source[keep], np.full(len(t), -1, np.int32)]),
            np.concatenate([b.trip_prev_day[keep], np.zeros(len(t), np.bool_)]),
        )


def _period_chunks(period: str) -> list[tuple[int, int]]:
    if period == "peak":
        return [PEAK]
    if period == "offpeak":
        return [(-DAY_END_S, PEAK[0]), (PEAK[1], DAY_END_S)]
    return [(-DAY_END_S, DAY_END_S)]


def _frequency(tt: Timetable, e: SetHeadway | ScaleFrequency, log: ChangeLog) -> Timetable:
    """Change a route's frequency in a period.

    Trips of every pattern of the route that start in the period are replaced
    by ``round(n * factor)`` trips per direction, spread over the same span
    (see :func:`_retime_group`). For ``set_headway`` the factor is
    ``current mean headway / target`` (:func:`vlab.gtfs.stats.mean_headways`:
    busiest direction; peak 07-09 h; off-peak measured 10-13 h and applied
    outside the peak).
    Overnight copies of the previous day's trips are left untouched.
    """
    r = _route_idx(tt, e.route_id)
    blocks = blocks_of(tt)
    mine = [i for i, b in enumerate(blocks) if b.info.route_idx == r and b.arr.shape[0] > 0]
    if not mine:
        raise ScenarioError(f"route {e.route_id!r} has no trips on this day")
    chunks = _period_chunks(e.period)
    if isinstance(e, ScaleFrequency):
        factor = float(e.factor)
    else:
        current = mean_headways(tt, r)[e.period]
        if current is None:
            raise ScenarioError(
                f"route {e.route_id!r} has fewer than two trips in the {e.period} period; "
                "its headway cannot be changed"
            )
        factor = current / float(e.headway)
    changed: set[int] = set()
    for lo, hi in chunks:
        for d in sorted({blocks[i].info.direction for i in mine}):
            group = [i for i in mine if blocks[i].info.direction == d]
            sels = []
            for i in group:
                t0 = blocks[i].dep[:, 0]
                sels.append((t0 >= lo) & (t0 < hi) & ~blocks[i].trip_prev_day)
            total = sum(int(sel.sum()) for sel in sels)
            if total == 0:
                continue
            target = max(1, round(total * factor)) if factor > 0 else 0
            if target == total:
                continue
            _retime_group(blocks, group, sels, target)
            changed.update(i for i, sel in zip(group, sels, strict=True) if sel.any())
    if not changed:
        log.warnings.append(f"route {e.route_id}: frequency change had no effect")
        return tt
    log.modified_routes.add(e.route_id)
    return _rebuild(tt, blocks, changed)


# ============================================================================ speed


def _speed_up(tt: Timetable, e: SpeedUp, log: ChangeLog) -> Timetable:
    """Divide the running time between the given consecutive stops by ``factor``
    (bus priority). Dwell times are unchanged; everything downstream shifts earlier."""
    ids = [_stop_idx(tt, s) for s in e.stop_ids]
    pairs = set(itertools.pairwise(ids))
    r = _route_idx(tt, e.route_id) if e.route_id is not None else None
    blocks = blocks_of(tt)
    changed: set[int] = set()
    for i, b in enumerate(blocks):
        if (r is not None and b.info.route_idx != r) or b.arr.shape[0] == 0:
            continue
        s = b.stops
        mask = np.fromiter(
            ((int(s[k]), int(s[k + 1])) in pairs for k in range(len(s) - 1)), bool, len(s) - 1
        )
        if not mask.any():
            continue
        arr, dep = b.arr.astype(np.int64), b.dep.astype(np.int64)
        run = arr[:, 1:] - dep[:, :-1]
        saving = np.where(mask[None, :], run - np.round(run / e.factor).astype(np.int64), 0)
        shift = np.cumsum(saving, axis=1)
        arr[:, 1:] -= shift
        dep[:, 1:] -= shift
        blocks[i] = PatternBlock(
            b.info,
            b.stops,
            arr.astype(np.int32),
            dep.astype(np.int32),
            b.offsets,
            b.trip_source,
            b.trip_prev_day,
        )
        changed.add(i)
        log.modified_routes.add(tt.routes[b.info.route_idx].route_id)
    if not changed:
        raise ScenarioError(
            "speed_up: no route runs between the given consecutive stops"
            + (f" on route {e.route_id!r}" if e.route_id else "")
        )
    return _rebuild(tt, blocks, changed)


# ============================================================================ stops


def _remove_stop(tt: Timetable, e: RemoveStop, log: ChangeLog) -> Timetable:
    """Drop a stop from every pattern (or from one route). Each removal saves
    ``STOP_TIME_SAVING_S`` downstream; removing a terminal shortens the pattern."""
    s = _stop_idx(tt, e.stop_id)
    r = _route_idx(tt, e.route_id) if e.route_id is not None else None
    blocks = blocks_of(tt)
    out: list[PatternBlock] = []
    changed: set[int] = set()
    hit = False
    for b in blocks:
        if (r is not None and b.info.route_idx != r) or s not in b.stops:
            out.append(b)
            continue
        hit = True
        log.modified_routes.add(tt.routes[b.info.route_idx].route_id)
        stops = b.stops.copy()
        arr, dep = b.arr.astype(np.int64), b.dep.astype(np.int64)
        off = b.offsets.copy()
        for k in sorted(np.flatnonzero(stops == s).tolist(), reverse=True):
            last = len(stops) - 1
            if 0 < k < last and arr.shape[0]:
                total = arr[:, k + 1] - dep[:, k - 1]
                saving = np.minimum(STOP_TIME_SAVING_S, total // 2)
                # the bus no longer dwells: it runs straight through
                arr[:, k + 1 :] -= saving[:, None]
                dep[:, k + 1 :] -= saving[:, None]
            stops = np.delete(stops, k)
            arr = np.delete(arr, k, axis=1)
            dep = np.delete(dep, k, axis=1)
            off = np.delete(off, k)
        if len(stops) < 2:
            log.warnings.append(
                f"pattern {b.info.key} has fewer than two stops left and was removed"
            )
            continue
        dep = np.maximum(dep, arr)
        changed.add(len(out))
        out.append(
            PatternBlock(
                b.info,
                stops.astype(np.int32),
                arr.astype(np.int32),
                dep.astype(np.int32),
                off,
                b.trip_source,
                b.trip_prev_day,
            )
        )
    if not hit:
        raise ScenarioError(
            f"stop {e.stop_id!r} is not served"
            + (f" by route {e.route_id!r}" if e.route_id else " by any route")
            + " on this day"
        )
    still = any(s in b.stops for b in out)
    if not still:
        log.removed_stops.add(e.stop_id)
    else:
        log.modified_stops.add(e.stop_id)
    return _rebuild(tt, out, changed)


def _move_stop(tt: Timetable, e: MoveStop, log: ChangeLog) -> Timetable:
    """Move a stop. Walking tables are rebuilt; bus running times are unchanged."""
    from vlab.gtfs import with_stops_moved

    s = _stop_idx(tt, e.stop_id)
    d = _dist_m((float(tt.stop_lon[s]), float(tt.stop_lat[s])), (e.lon, e.lat))
    if d > MOVE_WARN_M:
        log.warnings.append(
            f"stop {e.stop_id} moved {d:.0f} m: bus paths and running times are not rerouted"
        )
    log.modified_stops.add(e.stop_id)
    for p in range(tt.n_patterns):
        if s in tt.pattern_stop_seq(p):
            log.modified_routes.add(tt.routes[tt.patterns[p].route_idx].route_id)
    return with_stops_moved(tt, [s], [e.lon], [e.lat])


def _add_stop(tt: Timetable, e: AddStop, log: ChangeLog) -> Timetable:
    """Insert a new stop after ``after_stop_id`` in the patterns of a route/direction.

    The arrival time is interpolated by distance; the detour (extra distance
    over the direct segment, at the pattern's mean speed) plus
    ``STOP_TIME_PENALTY_S`` are added downstream.
    """
    from vlab.gtfs import with_stops_added

    if e.stop_id in tt.stop_index:
        raise ScenarioError(f"stop_id {e.stop_id!r} already exists")
    r = _route_idx(tt, e.route_id)
    after = _stop_idx(tt, e.after_stop_id)
    tt = with_stops_added(tt, [e.stop_id], [e.name or e.stop_id], [e.lon], [e.lat])
    new = tt.stop_index[e.stop_id]
    blocks = blocks_of(tt)
    changed: set[int] = set()
    nx, ny = float(tt.stop_x[new]), float(tt.stop_y[new])
    for i, b in enumerate(blocks):
        if b.info.route_idx != r or b.info.direction != e.direction or after not in b.stops:
            continue
        k = int(np.flatnonzero(b.stops == after)[0])
        arr, dep = b.arr.astype(np.int64), b.dep.astype(np.int64)
        off = b.offsets
        length = max(float(off[-1] - off[0]), 1.0)
        run_total = float(np.median(arr[:, -1] - dep[:, 0])) if arr.shape[0] else 0.0
        v = length / run_total if run_total > 0 else 3.4  # m/s
        d1 = math.hypot(nx - tt.stop_x[b.stops[k]], ny - tt.stop_y[b.stops[k]])
        if k < len(b.stops) - 1:
            nxt = b.stops[k + 1]
            d2 = math.hypot(nx - tt.stop_x[nxt], ny - tt.stop_y[nxt])
            d0 = math.hypot(
                tt.stop_x[nxt] - tt.stop_x[b.stops[k]], tt.stop_y[nxt] - tt.stop_y[b.stops[k]]
            )
            f = d1 / (d1 + d2) if d1 + d2 > 0 else 0.5
            extra = round(max(0.0, d1 + d2 - d0) / v)
            run = arr[:, k + 1] - dep[:, k]
            new_arr = dep[:, k] + np.round(f * (run + extra)).astype(np.int64)
            arr[:, k + 1 :] += extra + STOP_TIME_PENALTY_S
            dep[:, k + 1 :] += extra + STOP_TIME_PENALTY_S
            new_off = float(off[k] + f * (off[k + 1] - off[k]))
            if extra > 60:
                log.warnings.append(
                    f"new stop {e.stop_id} is a detour of about {extra} s on route {e.route_id}"
                )
        else:
            new_arr = dep[:, k] + round(1.3 * d1 / v) + STOP_TIME_PENALTY_S
            new_off = float(off[k] + 1.3 * d1)
            log.warnings.append(
                f"route {e.route_id} extended to {e.stop_id}: the extension is not snapped "
                "to streets"
            )
        blocks[i] = PatternBlock(
            b.info,
            np.insert(b.stops, k + 1, new).astype(np.int32),
            np.insert(arr, k + 1, new_arr, axis=1).astype(np.int32),
            np.insert(dep, k + 1, new_arr, axis=1).astype(np.int32),
            np.insert(off, k + 1, new_off),
            b.trip_source,
            b.trip_prev_day,
        )
        changed.add(i)
    if not changed:
        raise ScenarioError(
            f"route {e.route_id!r} direction {e.direction} does not serve stop "
            f"{e.after_stop_id!r} on this day"
        )
    log.added_stops.add(e.stop_id)
    log.modified_routes.add(e.route_id)
    return _rebuild(tt, blocks, changed)


# =========================================================================== routes


def _remove_route(tt: Timetable, e: RemoveRoute, log: ChangeLog) -> Timetable:
    from vlab.gtfs import with_route_removed

    _route_idx(tt, e.route_id)
    served_before = {int(s) for s in tt.pattern_stops}
    out = with_route_removed(tt, e.route_id)
    served_after = {int(s) for s in out.pattern_stops}
    for s in served_before - served_after:
        log.removed_stops.add(tt.stop_ids[s])
    log.removed_routes.add(e.route_id)
    return out


def _with_shape(tt: Timetable, shape_id: str, coords: F64) -> tuple[Timetable, int]:
    x, y = to_xy(coords[:, 0], coords[:, 1])
    cum = cumulative_length(x, y)
    new = replace(
        tt,
        shape_ids=(*tt.shape_ids, shape_id),
        shape_ptr=np.append(tt.shape_ptr, tt.shape_ptr[-1] + len(coords)).astype(
            tt.shape_ptr.dtype
        ),
        shape_lon=np.concatenate([tt.shape_lon, coords[:, 0]]),
        shape_lat=np.concatenate([tt.shape_lat, coords[:, 1]]),
        shape_cum_m=np.concatenate([tt.shape_cum_m, cum]),
    )
    return new, len(tt.shape_ids)


def _add_route(
    model: Model, tt: Timetable, e: AddRoute, log: ChangeLog, default_speed_kmh: float
) -> Timetable:
    """Add a line. The path follows the bus-drivable street graph through the
    waypoints (or through the stops when no waypoints are given); stops are
    placed along it and scheduled at ``speed_kmh`` (default: the network's mean
    commercial speed, which includes dwell). A bidirectional line gets a second
    pattern routed in the opposite direction through the same stops reversed."""
    from vlab.gtfs import with_stops_added

    if e.route_id in tt.route_index:
        raise ScenarioError(f"route_id {e.route_id!r} already exists")
    new_ids: list[str] = []
    new_names: list[str] = []
    new_lon: list[float] = []
    new_lat: list[float] = []
    seq_ids: list[str] = []
    for n, s in enumerate(e.stops):
        if s.stop_id is not None and s.stop_id in tt.stop_index:
            seq_ids.append(s.stop_id)
        elif s.lon is not None and s.lat is not None:
            sid = s.stop_id or f"{e.route_id}:s{n}"
            if sid in new_ids:
                raise ScenarioError(f"duplicate new stop id {sid!r}")
            new_ids.append(sid)
            new_names.append(s.name or f"{e.short_name or e.route_id} {n + 1}")
            new_lon.append(float(s.lon))
            new_lat.append(float(s.lat))
            seq_ids.append(sid)
        else:
            raise ScenarioError(f"unknown stop_id {s.stop_id!r}")
    if any(a == b for a, b in itertools.pairwise(seq_ids)):
        raise ScenarioError("a route cannot serve the same stop twice in a row")
    if new_ids:
        tt = with_stops_added(tt, new_ids, new_names, new_lon, new_lat)
        log.added_stops.update(new_ids)
    seq = np.array([tt.stop_index[s] for s in seq_ids], dtype=np.int32)
    tt = assemble(
        tt,
        blocks_of(tt),
        routes=(
            *tt.routes,
            RouteInfo(
                route_id=e.route_id,
                short_name=e.short_name or e.route_id,
                long_name=f"{tt.stop_names[seq[0]]} - {tt.stop_names[seq[-1]]}",
                color=e.color,
                text_color="#FFFFFF",
                kind="day",
            ),
        ),
        normalize=False,
    )
    r = tt.route_index[e.route_id]
    v = (e.speed_kmh or default_speed_kmh) / 3.6
    stop_pts = np.column_stack([tt.stop_lon[seq], tt.stop_lat[seq]])
    wps = np.asarray(e.waypoints, dtype=np.float64).reshape(-1, 2)
    directions = [(0, seq, wps if len(wps) >= 2 else stop_pts)]
    if e.bidirectional:
        directions.append((1, seq[::-1].copy(), (wps if len(wps) >= 2 else stop_pts)[::-1]))
    blocks = blocks_of(tt)
    for d, stops, through in directions:
        path = snap_path(model.drive, through)
        for w in path.warnings:
            log.warnings.append(f"route {e.route_id} direction {d}: {w}")
        tt, shape_idx = _with_shape(tt, f"{e.route_id}:{d}", path.coords)
        px, py = to_xy(path.coords[:, 0], path.coords[:, 1])
        off, dist = project_monotone(px, py, tt.stop_x[stops], tt.stop_y[stops])
        if float(dist.max(initial=0.0)) > 150.0:
            log.warnings.append(
                f"route {e.route_id} direction {d}: a stop is {dist.max():.0f} m from the path"
            )
        t = np.round((off - off[0]) / v).astype(np.int64)
        for k in range(1, len(t)):
            t[k] = max(t[k], t[k - 1] + MIN_SEGMENT_S)
        first = e.first_dep + (e.headway // 2 if d == 1 else 0)
        starts = np.arange(first, e.last_dep + 1, e.headway, dtype=np.int64)
        times = (starts[:, None] + t[None, :]).astype(np.int32)
        info = PatternInfo(
            key=f"{e.route_id}:{d}:0",
            route_idx=r,
            direction=d,
            headsign=tt.stop_names[int(stops[-1])],
            shape_idx=shape_idx,
        )
        blocks.append(
            PatternBlock(
                info,
                stops.astype(np.int32),
                times,
                times.copy(),
                off.astype(np.float64),
                np.full(len(starts), -1, np.int32),
                np.zeros(len(starts), np.bool_),
            )
        )
    log.added_routes.add(e.route_id)
    return assemble(tt, blocks, normalize=False)
