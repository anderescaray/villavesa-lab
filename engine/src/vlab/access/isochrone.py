"""Isochrones from an arbitrary point.

Method: an ad-hoc access table from the origin to nearby stops, one RAPTOR query
per sampled departure, then a multi-source Dijkstra on the pedestrian graph
seeded with the arrival time at every stop (and time 0 at the origin). This
gives a door-to-door time at every street node for each departure; the node
value is the same censored mean over departures used by the zone matrix
(decision D-010), so isochrones and dashboard numbers are consistent.

Polygons are obtained by rasterising node times on a regular grid in
EPSG:25830, dilating them by a short walking buffer and contouring.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any

import contourpy
import numba as nb
import numpy as np
import numpy.typing as npt
import shapely
from scipy import ndimage
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from vlab.gtfs import to_lonlat, to_xy
from vlab.model.world import ACCESS_MAX_M, Model, NetworkState, Window
from vlab.raptor import INF, raptor
from vlab.walk import WALK_SPEED_MPS, build_access

CELL_M = 30.0
#: Street nodes "paint" their surroundings up to this distance (half a block).
BUFFER_M = 75.0
MIN_AREA_M2 = 4_000.0
MIN_HOLE_M2 = 30_000.0
SIMPLIFY_M = 12.0
CAP_S = 7200
BIG = np.float32(1e9)


class OriginError(ValueError):
    """The requested origin cannot be attached to the street network."""


@nb.njit(cache=True)
def _node_times(indptr, indices, length_m, seed_nodes, seed_t, cutoff, speed):  # type: ignore[no-untyped-def]  # pragma: no cover
    """Multi-source Dijkstra (seconds) on the walk graph, bounded by ``cutoff``."""
    n = len(indptr) - 1
    dist = np.full(n, np.inf)
    heap = [(0.0, np.int64(-1))]
    heap.pop()
    for i in range(len(seed_nodes)):
        u = seed_nodes[i]
        if seed_t[i] < dist[u] and seed_t[i] <= cutoff:
            dist[u] = seed_t[i]
            heapq.heappush(heap, (seed_t[i], u))
    while len(heap) > 0:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for e in range(indptr[u], indptr[u + 1]):
            v = indices[e]
            nd = d + length_m[e] / speed
            if nd < dist[v] and nd <= cutoff:
                dist[v] = nd
                heapq.heappush(heap, (nd, np.int64(v)))
    return dist


@dataclass(frozen=True, eq=False)
class TimeField:
    """Door-to-door time (s) from an origin to every pedestrian-graph node."""

    origin: tuple[float, float]
    node_time: npt.NDArray[np.float32]  # inf = not reached within the horizon
    stop_time: npt.NDArray[np.float32]  # mean travel time to each stop (inf = unreached)


def time_field(
    model: Model,
    state: NetworkState,
    origin: tuple[float, float],
    window: Window,
    horizon_s: int,
    mode: str = "transit",
    step_s: int = 600,
) -> TimeField:
    walk = model.walk
    tt = state.timetable
    snap = walk.snap([origin[0]], [origin[1]], max_m=400.0)
    if not snap.ok[0]:
        raise OriginError("the origin is too far from the street network")
    o_nodes = snap.nodes.astype(np.int64)
    o_secs = snap.offset_m / WALK_SPEED_MPS
    edge_len = walk.length_m
    deps = window.departures(step_s) if mode == "transit" else np.zeros(1, dtype=np.int64)
    stop_snap = _stop_snap(model, state)
    acc = build_access(walk, ([origin[0]], [origin[1]]), tt, ACCESS_MAX_M, cache=False)
    src, off = acc.row(0)
    total = np.zeros(walk.n_nodes, dtype=np.float64)
    reach = np.zeros(walk.n_nodes, dtype=np.int32)
    stop_total = np.zeros(tt.n_stops, dtype=np.float64)
    stop_reach = np.zeros(tt.n_stops, dtype=np.int32)
    for dep in deps:
        seeds_n = [o_nodes]
        seeds_t = [o_secs]
        if mode == "transit" and len(src):
            res = raptor(tt, state.transfers, src, int(dep), off, max_duration=horizon_s)
            ok = res.arrival < INF
            t_stop = np.where(ok, res.arrival.astype(np.float64) - float(dep), np.inf)
            stop_total += np.where(ok, t_stop, CAP_S)
            stop_reach += ok
            s_ptr, s_nodes, s_off = stop_snap
            counts = np.diff(s_ptr)
            per = np.repeat(t_stop, counts) + s_off / WALK_SPEED_MPS
            keep = np.isfinite(per)
            seeds_n.append(s_nodes[keep])
            seeds_t.append(per[keep])
        d = _node_times(
            walk.indptr,
            walk.indices,
            edge_len,
            np.concatenate(seeds_n),
            np.concatenate(seeds_t),
            float(horizon_s),
            WALK_SPEED_MPS,
        )
        ok_n = np.isfinite(d)
        total += np.where(ok_n, d, CAP_S)
        reach += ok_n
    need = max(1, math.ceil(0.5 * len(deps) - 1e-9))
    node_time = np.where(reach >= need, total / len(deps), np.inf).astype(np.float32)
    stop_time = np.where(stop_reach >= need, stop_total / len(deps), np.inf).astype(np.float32)
    return TimeField(origin, node_time, stop_time)


def _stop_snap(model: Model, state: NetworkState) -> tuple[Any, Any, Any]:
    """Snap of the state's stops to walk nodes, cached per stop-coordinate array.

    Derived timetables inherit ``extra`` from their base, so the cache entry is
    tied to the identity of the coordinate arrays: timetables that share the
    stops share the snap, and any stop edit (which allocates new arrays)
    invalidates it.
    """
    tt = state.timetable
    cached = tt.extra.get("_iso_stop_snap")
    if (
        isinstance(cached, tuple)
        and len(cached) == 3
        and cached[0] is tt.stop_lon
        and cached[1] is tt.stop_lat
    ):
        return cached[2]  # type: ignore[no-any-return]
    snap = model.walk.snap(tt.stop_lon, tt.stop_lat)
    value = (snap.ptr, snap.nodes.astype(np.int64), snap.offset_m)
    tt.extra["_iso_stop_snap"] = (tt.stop_lon, tt.stop_lat, value)
    return value


def point_times(model: Model, field: TimeField, which: str) -> npt.NDArray[np.float32]:
    """Time from the origin to every zone (``which="zones"``) or POI (``"pois"``)."""
    snap = model.zone_snap if which == "zones" else model.poi_snap
    n = len(snap.ptr) - 1
    out = np.full(n, np.inf, dtype=np.float32)
    per = field.node_time[snap.nodes] + (snap.offset_m / WALK_SPEED_MPS).astype(np.float32)
    idx = np.repeat(np.arange(n), np.diff(snap.ptr))
    np.minimum.at(out, idx, per)
    return out


def polygons(model: Model, field: TimeField, cutoffs: list[int]) -> dict[int, BaseGeometry]:
    """Nested isochrone polygons (WGS84) for each cutoff."""
    walk = model.walk
    x, y = walk.node_xy
    t = field.node_time
    cutoffs = sorted(cutoffs)
    ok = t <= cutoffs[-1]
    if not ok.any():
        return {c: MultiPolygon() for c in cutoffs}
    pad = BUFFER_M + 3 * CELL_M
    x0, y0 = float(x[ok].min() - pad), float(y[ok].min() - pad)
    nx = int((x[ok].max() + pad - x0) / CELL_M) + 1
    ny = int((y[ok].max() + pad - y0) / CELL_M) + 1
    grid = np.full((ny, nx), BIG, dtype=np.float32)
    ix = ((x[ok] - x0) / CELL_M).astype(np.int64)
    iy = ((y[ok] - y0) / CELL_M).astype(np.int64)
    np.minimum.at(grid, (iy, ix), t[ok])
    # dilate: every cell takes the best nearby node time plus the walk to reach it
    r = int(BUFFER_M / CELL_M)
    best = grid.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            dist = math.hypot(dx, dy) * CELL_M
            if (dx == 0 and dy == 0) or dist > BUFFER_M + 1e-6:
                continue
            shifted = np.full_like(grid, BIG)
            ys = slice(max(dy, 0), ny + min(dy, 0))
            xs = slice(max(dx, 0), nx + min(dx, 0))
            yo = slice(max(-dy, 0), ny + min(-dy, 0))
            xo = slice(max(-dx, 0), nx + min(-dx, 0))
            shifted[ys, xs] = grid[yo, xo] + np.float32(dist / WALK_SPEED_MPS)
            np.minimum(best, shifted, out=best)
    capped = np.minimum(best, np.float32(cutoffs[-1] + 900))
    smooth = ndimage.gaussian_filter(capped, sigma=0.8)
    smooth = np.minimum(smooth, capped + 60.0)
    gen = contourpy.contour_generator(
        x=x0 + (np.arange(nx) + 0.5) * CELL_M,
        y=y0 + (np.arange(ny) + 0.5) * CELL_M,
        z=smooth,
        fill_type=contourpy.FillType.OuterOffset,
    )
    out: dict[int, BaseGeometry] = {}
    prev: BaseGeometry | None = None
    for c in cutoffs:
        filled: Any = gen.filled(-1.0, float(c))
        pts, offs = filled[0], filled[1]
        polys: list[Polygon] = []
        for p, o in zip(pts, offs, strict=True):
            rings = [p[o[i] : o[i + 1]] for i in range(len(o) - 1)]
            if len(rings[0]) < 4:
                continue
            holes = [h for h in rings[1:] if len(h) >= 4 and Polygon(h).area >= MIN_HOLE_M2]
            poly = Polygon(rings[0], holes)
            if poly.area >= MIN_AREA_M2:
                polys.append(poly)
        geom: BaseGeometry = shapely.unary_union(polys) if polys else MultiPolygon()
        geom = geom.simplify(SIMPLIFY_M, preserve_topology=True)
        if not geom.is_valid:
            geom = shapely.make_valid(geom)
        if prev is not None and not prev.is_empty:
            geom = shapely.unary_union([geom, prev])  # guarantee nesting
        prev = geom
        out[c] = geom
    return {c: _to_wgs84(g) for c, g in out.items()}


def _to_wgs84(geom: BaseGeometry) -> BaseGeometry:
    if geom.is_empty:
        return MultiPolygon()

    def tr(coords: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        lon, lat = to_lonlat(coords[:, 0], coords[:, 1])
        return np.column_stack([np.round(lon, 6), np.round(lat, 6)])

    g = shapely.transform(geom, tr)
    polys = [p for p in getattr(g, "geoms", [g]) if isinstance(p, Polygon) and not p.is_empty]
    return MultiPolygon(polys)


def area_km2(geom_wgs84: BaseGeometry) -> float:
    if geom_wgs84.is_empty:
        return 0.0

    def tr(coords: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        px, py = to_xy(coords[:, 0], coords[:, 1])
        return np.column_stack([px, py])

    return float(shapely.transform(geom_wgs84, tr).area / 1e6)
