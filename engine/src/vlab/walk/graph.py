"""Pedestrian network: loading, snapping, distances, paths and walking tables."""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt
from scipy.spatial import cKDTree

from vlab.gtfs._cache import arrays_digest, default_cache_dir
from vlab.gtfs.geometry import to_xy
from vlab.walk.dijkstra import many_to_many, shortest_path_nodes

F64 = npt.NDArray[np.float64]
I32 = npt.NDArray[np.int32]
I64 = npt.NDArray[np.int64]

#: Walking speed (m/s). 1.25 m/s = 4.5 km/h, the usual planning value.
WALK_SPEED_MPS = 1.25
#: Max straight-line distance from a point to the network for snapping (m).
SNAP_MAX_M = 250.0
#: Number of candidate nodes a point is attached to (multi-source snapping).
SNAP_K = 3
#: Detour factor applied to straight-line distance for points that do not snap.
DETOUR_FACTOR = 1.3
#: Stops closer than this (straight line) are considered at the same place: the
#: transfer uses the straight-line distance instead of the network detour.
SAME_PLACE_M = 30.0

_CACHE_VERSION = 2


def seconds(dist_m: npt.ArrayLike, speed: float = WALK_SPEED_MPS) -> I32:
    """Walking time in whole seconds (rounded up)."""
    return np.ceil(np.asarray(dist_m, dtype=np.float64) / speed - 1e-9).astype(np.int32)


@dataclass(frozen=True, eq=False)
class WalkTable:
    """Sparse walking times: row ``i`` → ``(indices[indptr[i]:indptr[i+1]], seconds[...])``.

    Used for stop→stop transfers, origin→stop access and stop→destination egress.
    Within a row, ``indices`` are sorted ascending.
    """

    indptr: I64
    indices: I32
    seconds: I32
    n_cols: int

    @property
    def n_rows(self) -> int:
        return len(self.indptr) - 1

    @property
    def nnz(self) -> int:
        return int(self.indptr[-1])

    def row(self, i: int) -> tuple[I32, I32]:
        a, b = self.indptr[i], self.indptr[i + 1]
        return self.indices[a:b], self.seconds[a:b]

    def transpose(self) -> WalkTable:
        """Swap rows and columns (e.g. access points→stops into egress stops→points)."""
        rows = np.repeat(np.arange(self.n_rows, dtype=np.int32), np.diff(self.indptr))
        order = np.lexsort((rows, self.indices))
        counts = np.bincount(self.indices, minlength=self.n_cols)
        ptr = np.zeros(self.n_cols + 1, dtype=np.int64)
        np.cumsum(counts, out=ptr[1:])
        return WalkTable(ptr, rows[order], self.seconds[order], self.n_rows)

    def to_dense(self, fill: int = -1) -> I32:
        out = np.full((self.n_rows, self.n_cols), fill, dtype=np.int32)
        rows = np.repeat(np.arange(self.n_rows), np.diff(self.indptr))
        out[rows, self.indices] = self.seconds
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.npz")
        np.savez(
            tmp,
            indptr=self.indptr,
            indices=self.indices,
            seconds=self.seconds,
            n_cols=np.int64(self.n_cols),
        )
        tmp.replace(path)

    @staticmethod
    def load(path: Path) -> WalkTable:
        with np.load(path) as z:
            return WalkTable(
                z["indptr"].astype(np.int64),
                z["indices"].astype(np.int32),
                z["seconds"].astype(np.int32),
                int(z["n_cols"]),
            )

    @staticmethod
    def from_rows(rows: list[tuple[npt.ArrayLike, npt.ArrayLike]], n_cols: int) -> WalkTable:
        """Build from a list of ``(indices, seconds)`` rows."""
        ptr = np.zeros(len(rows) + 1, dtype=np.int64)
        idx_parts, sec_parts = [], []
        for i, (ix, sec) in enumerate(rows):
            ix_a = np.asarray(ix, dtype=np.int32)
            sec_a = np.asarray(sec, dtype=np.int32)
            order = np.argsort(ix_a, kind="stable")
            idx_parts.append(ix_a[order])
            sec_parts.append(sec_a[order])
            ptr[i + 1] = ptr[i] + len(ix_a)
        return WalkTable(
            ptr,
            np.concatenate(idx_parts) if idx_parts else np.zeros(0, np.int32),
            np.concatenate(sec_parts) if sec_parts else np.zeros(0, np.int32),
            n_cols,
        )


class HasStopCoords(Protocol):
    @property
    def stop_lon(self) -> F64: ...
    @property
    def stop_lat(self) -> F64: ...


StopsLike = HasStopCoords | tuple[npt.ArrayLike, npt.ArrayLike]


def _coords(stops: StopsLike) -> tuple[F64, F64]:
    if isinstance(stops, tuple):
        return np.asarray(stops[0], dtype=np.float64), np.asarray(stops[1], dtype=np.float64)
    return np.asarray(stops.stop_lon, dtype=np.float64), np.asarray(
        stops.stop_lat, dtype=np.float64
    )


@dataclass(frozen=True)
class Snap:
    """Candidate network nodes of a set of points (CSR) with straight-line offsets.

    ``ptr`` has one entry per point + 1; points with no candidate within the snap radius
    have an empty row (``ok[i]`` is False).
    """

    ptr: I64
    nodes: I64
    offset_m: F64

    @property
    def ok(self) -> npt.NDArray[np.bool_]:
        return np.diff(self.ptr) > 0

    def nearest(self) -> tuple[I64, F64]:
        """Nearest node and distance per point (-1 / inf if not snapped)."""
        n = len(self.ptr) - 1
        node = np.full(n, -1, dtype=np.int64)
        dist = np.full(n, np.inf)
        ok = self.ok
        node[ok] = self.nodes[self.ptr[:-1][ok]]
        dist[ok] = self.offset_m[self.ptr[:-1][ok]]
        return node, dist


@dataclass(frozen=True)
class PathResult:
    """A walking path: ``coords`` ``[n, 2]`` lon/lat (including the off-network
    straight segments at both ends) and its length in metres (inf if unreachable)."""

    coords: F64
    length_m: float
    nodes: I64

    @property
    def found(self) -> bool:
        return math.isfinite(self.length_m)


@dataclass(frozen=True, eq=False)
class WalkGraph:
    """Symmetric pedestrian graph in CSR form (edge weights = length in metres)."""

    node_lon: F64
    node_lat: F64
    indptr: I64
    indices: I32
    length_m: npt.NDArray[np.float32]

    @classmethod
    def load(cls, path: str | Path) -> WalkGraph:
        """Load ``walk_graph.npz`` (contract in docs/architecture.md) and validate it."""
        with np.load(Path(path)) as z:
            missing = {"node_lon", "node_lat", "indptr", "indices", "length_m"} - set(z.files)
            if missing:
                raise ValueError(f"{path}: missing arrays {sorted(missing)}")
            return cls.from_arrays(
                z["node_lon"], z["node_lat"], z["indptr"], z["indices"], z["length_m"]
            )

    @classmethod
    def from_arrays(
        cls,
        node_lon: npt.ArrayLike,
        node_lat: npt.ArrayLike,
        indptr: npt.ArrayLike,
        indices: npt.ArrayLike,
        length_m: npt.ArrayLike,
    ) -> WalkGraph:
        lon = np.ascontiguousarray(node_lon, dtype=np.float64)
        lat = np.ascontiguousarray(node_lat, dtype=np.float64)
        ptr = np.ascontiguousarray(indptr, dtype=np.int64)
        idx = np.ascontiguousarray(indices, dtype=np.int32)
        w = np.ascontiguousarray(length_m, dtype=np.float32)
        n = len(lon)
        if len(lat) != n or len(ptr) != n + 1 or ptr[0] != 0 or ptr[-1] != len(idx):
            raise ValueError("walk graph: inconsistent CSR sizes")
        if len(w) != len(idx):
            raise ValueError("walk graph: length_m must align with indices")
        if np.any(np.diff(ptr) < 0) or (len(idx) and (idx.min() < 0 or idx.max() >= n)):
            raise ValueError("walk graph: invalid CSR indices")
        if np.any(~np.isfinite(w)) or np.any(w < 0):
            raise ValueError("walk graph: edge lengths must be finite and >= 0")
        return cls(lon, lat, ptr, idx, w)

    @property
    def n_nodes(self) -> int:
        return len(self.node_lon)

    @property
    def n_edges(self) -> int:
        return len(self.indices)

    @cached_property
    def node_xy(self) -> tuple[F64, F64]:
        return to_xy(self.node_lon, self.node_lat)

    @cached_property
    def _tree(self) -> cKDTree:
        x, y = self.node_xy
        return cKDTree(np.column_stack([x, y]))

    @cached_property
    def digest(self) -> str:
        return arrays_digest(self.node_lon, self.node_lat, self.indptr, self.indices, self.length_m)

    # ------------------------------------------------------------------ snapping
    def snap(
        self, lon: npt.ArrayLike, lat: npt.ArrayLike, max_m: float = SNAP_MAX_M, k: int = SNAP_K
    ) -> Snap:
        """Attach points to up to ``k`` nearest nodes within ``max_m`` (straight line)."""
        x, y = to_xy(np.atleast_1d(lon), np.atleast_1d(lat))
        return self.snap_xy(x, y, max_m, k)

    def snap_xy(self, x: F64, y: F64, max_m: float = SNAP_MAX_M, k: int = SNAP_K) -> Snap:
        n = len(x)
        k = max(1, min(k, self.n_nodes))
        if n == 0:
            return Snap(np.zeros(1, np.int64), np.zeros(0, np.int64), np.zeros(0))
        d, i = self._tree.query(np.column_stack([x, y]), k=k, distance_upper_bound=max_m)
        d = np.asarray(d).reshape(n, k)
        i = np.asarray(i).reshape(n, k)
        ok = np.isfinite(d)
        ptr = np.zeros(n + 1, dtype=np.int64)
        np.cumsum(ok.sum(axis=1), out=ptr[1:])
        return Snap(ptr, i[ok].astype(np.int64), d[ok].astype(np.float64))

    # ------------------------------------------------------------------ distances
    def distances(
        self,
        src: Snap,
        tgt: Snap,
        cutoff_m: float,
        *,
        exclude_self: bool = False,
    ) -> tuple[I64, I32, F64]:
        """Network distances (CSR) from each source point to targets within cutoff.

        Includes the snap offsets at both ends. Returns ``(ptr, target, dist_m)``.
        """
        n_tgt = len(tgt.ptr) - 1
        tgt_point = np.repeat(np.arange(n_tgt, dtype=np.int64), np.diff(tgt.ptr))
        order = np.argsort(tgt.nodes, kind="stable")
        counts = np.bincount(tgt.nodes, minlength=self.n_nodes)
        node_ptr = np.zeros(self.n_nodes + 1, dtype=np.int64)
        np.cumsum(counts, out=node_ptr[1:])
        res: tuple[I64, I32, F64] = many_to_many(
            self.indptr,
            self.indices,
            self.length_m,
            src.ptr,
            src.nodes,
            src.offset_m,
            node_ptr,
            tgt_point[order],
            tgt.offset_m[order],
            n_tgt,
            float(cutoff_m),
            exclude_self,
        )
        return res

    def shortest_path(
        self,
        a: tuple[float, float],
        b: tuple[float, float],
        *,
        max_m: float = 50_000.0,
        snap_max_m: float = 1000.0,
    ) -> PathResult:
        """Shortest walking path between two lon/lat points (coords include the
        straight connectors to the network)."""
        sa = self.snap([a[0]], [a[1]], snap_max_m)
        sb = self.snap([b[0]], [b[1]], snap_max_m)
        if not (sa.ok[0] and sb.ok[0]):
            return PathResult(np.array([a, b], dtype=np.float64), math.inf, np.zeros(0, np.int64))
        length, end, pred = shortest_path_nodes(
            self.indptr,
            self.indices,
            self.length_m,
            sa.nodes,
            sa.offset_m,
            sb.nodes,
            sb.offset_m,
            float(max_m),
        )
        if end < 0:
            return PathResult(np.array([a, b], dtype=np.float64), math.inf, np.zeros(0, np.int64))
        nodes = [int(end)]
        while pred[nodes[-1]] >= 0:
            nodes.append(int(pred[nodes[-1]]))
        node_arr = np.asarray(nodes[::-1], dtype=np.int64)
        coords = np.vstack(
            [
                np.asarray([a], dtype=np.float64),
                np.column_stack([self.node_lon[node_arr], self.node_lat[node_arr]]),
                np.asarray([b], dtype=np.float64),
            ]
        )
        return PathResult(coords, float(length), node_arr)

    def path_through(self, waypoints: npt.ArrayLike, **kw: float) -> PathResult:
        """Concatenate shortest paths through consecutive ``[lon, lat]`` waypoints."""
        wp = np.asarray(waypoints, dtype=np.float64)
        if len(wp) < 2:
            raise ValueError("need at least two waypoints")
        parts: list[F64] = []
        nodes: list[I64] = []
        total = 0.0
        for i in range(len(wp) - 1):
            r = self.shortest_path((wp[i, 0], wp[i, 1]), (wp[i + 1, 0], wp[i + 1, 1]), **kw)
            total += r.length_m
            parts.append(r.coords if i == 0 else r.coords[1:])
            nodes.append(r.nodes)
        return PathResult(np.vstack(parts), total, np.concatenate(nodes))


# =============================================================================== tables


def _straight_fallback(
    px: F64, py: F64, rows: npt.NDArray[np.int64], sx: F64, sy: F64, max_m: float
) -> dict[int, tuple[I32, F64]]:
    """Straight-line x DETOUR_FACTOR distances for points that did not snap."""
    out: dict[int, tuple[I32, F64]] = {}
    if len(rows) == 0:
        return out
    tree = cKDTree(np.column_stack([sx, sy]))
    for r in rows:
        idx = tree.query_ball_point([px[r], py[r]], max_m / DETOUR_FACTOR)
        idx_a = np.asarray(sorted(idx), dtype=np.int32)
        d = np.hypot(sx[idx_a] - px[r], sy[idx_a] - py[r]) * DETOUR_FACTOR
        out[int(r)] = (idx_a, d)
    return out


def _merge_fallback(
    ptr: I64, tgt: I32, dist: F64, extra: dict[int, tuple[I32, F64]]
) -> tuple[I64, I32, F64]:
    if not extra:
        return ptr, tgt, dist
    rows: list[tuple[I32, F64]] = []
    for i in range(len(ptr) - 1):
        a, b = ptr[i], ptr[i + 1]
        t, d = tgt[a:b], dist[a:b]
        if i in extra:
            et, ed = extra[i]
            t = np.concatenate([t, et])
            d = np.concatenate([d, ed])
            # keep the min per target, sorted
            order = np.lexsort((d, t))
            t, d = t[order], d[order]
            first = np.ones(len(t), dtype=bool)
            first[1:] = t[1:] != t[:-1]
            t, d = t[first], d[first]
        rows.append((t, d))
    new_ptr = np.zeros(len(rows) + 1, dtype=np.int64)
    np.cumsum([len(r[0]) for r in rows], out=new_ptr[1:])
    return (
        new_ptr,
        np.concatenate([r[0] for r in rows]).astype(np.int32),
        np.concatenate([r[1] for r in rows]).astype(np.float64),
    )


def euclidean_table(
    src: tuple[npt.ArrayLike, npt.ArrayLike],
    dst: tuple[npt.ArrayLike, npt.ArrayLike],
    max_m: float,
    *,
    detour: float = DETOUR_FACTOR,
    speed: float = WALK_SPEED_MPS,
    exclude_self: bool = False,
) -> WalkTable:
    """Walking table from straight-line distance x ``detour`` (no network).

    A fallback for when no pedestrian graph is available, and a convenience for tests.
    ``exclude_self`` drops the diagonal (for stop→stop transfers).
    """
    sx, sy = to_xy(np.atleast_1d(src[0]), np.atleast_1d(src[1]))
    dx, dy = to_xy(np.atleast_1d(dst[0]), np.atleast_1d(dst[1]))
    tree = cKDTree(np.column_stack([dx, dy]))
    rows: list[tuple[npt.ArrayLike, npt.ArrayLike]] = []
    for i, cand in enumerate(tree.query_ball_point(np.column_stack([sx, sy]), max_m / detour)):
        c = np.sort(np.asarray(cand, dtype=np.int32))
        if exclude_self:
            c = c[c != i]
        d = np.hypot(dx[c] - sx[i], dy[c] - sy[i]) * detour
        rows.append((c, seconds(d, speed)))
    return WalkTable.from_rows(rows, len(dx))


def _cache_file(kind: str, digest: str, cache_dir: Path | None) -> Path:
    return (cache_dir or default_cache_dir()) / "walk" / f"{kind}-{digest[:32]}.npz"


def build_transfers(
    graph: WalkGraph,
    stops: StopsLike,
    max_m: float = 400.0,
    *,
    speed: float = WALK_SPEED_MPS,
    cache: bool = True,
    cache_dir: Path | None = None,
) -> WalkTable:
    """Stop→stop footpaths within ``max_m`` of network walking (seconds).

    Distances are network distances including the snap connectors at both ends; stops
    within :data:`SAME_PLACE_M` of each other use the straight-line distance instead
    (so co-located stops get a ~0 s transfer). Self-loops are excluded. The relation is
    symmetric but NOT transitively closed (A-B and B-C within 400 m does not imply A-C);
    RAPTOR applies a single footpath after each ride (see docs/router.md).
    """
    lon, lat = _coords(stops)
    digest = arrays_digest(lon, lat, extra=f"{graph.digest}|{max_m}|{speed}|{_CACHE_VERSION}")
    path = _cache_file("transfers", digest, cache_dir)
    if cache and path.is_file():
        return WalkTable.load(path)
    x, y = to_xy(lon, lat)
    snap = graph.snap_xy(x, y)
    ptr, tgt, dist = graph.distances(snap, snap, max_m, exclude_self=True)
    unsnapped = np.flatnonzero(~snap.ok)
    extra = _straight_fallback(x, y, unsnapped, x, y, max_m)
    for r, (t, d) in list(extra.items()):
        keep = t != r
        extra[r] = (t[keep], d[keep])
    # symmetric fallback: snapped stops near an unsnapped one
    if len(unsnapped):
        for u in unsnapped:
            for t, d in zip(*extra[int(u)], strict=True):
                et, ed = extra.get(int(t), (np.zeros(0, np.int32), np.zeros(0)))
                extra[int(t)] = (np.r_[et, np.int32(u)].astype(np.int32), np.r_[ed, d])
    ptr, tgt, dist = _merge_fallback(ptr, tgt, dist, extra)
    rows = np.repeat(np.arange(len(ptr) - 1), np.diff(ptr))
    euclid = np.hypot(x[rows] - x[tgt], y[rows] - y[tgt])
    dist = np.where(euclid <= SAME_PLACE_M, euclid, dist)
    table = WalkTable(ptr, tgt.astype(np.int32), seconds(dist, speed), len(lon))
    if cache:
        with contextlib.suppress(OSError):
            table.save(path)
    return table


def build_access(
    graph: WalkGraph,
    points: tuple[npt.ArrayLike, npt.ArrayLike],
    stops: StopsLike,
    max_m: float = 1000.0,
    *,
    speed: float = WALK_SPEED_MPS,
    cache: bool | None = None,
    cache_dir: Path | None = None,
) -> WalkTable:
    """Points→stops walking times (seconds) within ``max_m`` network metres.

    ``points`` is ``(lon, lat)``. The Dijkstra runs from whichever side has fewer
    elements (the graph is symmetric, so the result is identical). Points that do not
    snap within :data:`SNAP_MAX_M` fall back to straight line x :data:`DETOUR_FACTOR`.
    For egress (stops→points) use ``build_access(...).transpose()``.

    ``cache`` defaults to True for more than 50 points (a single isochrone origin is
    cheaper to compute than to hash and load).
    """
    plon = np.atleast_1d(np.asarray(points[0], dtype=np.float64))
    plat = np.atleast_1d(np.asarray(points[1], dtype=np.float64))
    slon, slat = _coords(stops)
    use_cache = cache if cache is not None else len(plon) > 50
    digest = ""
    if use_cache:
        digest = arrays_digest(
            plon, plat, slon, slat, extra=f"{graph.digest}|{max_m}|{speed}|{_CACHE_VERSION}"
        )
        path = _cache_file("access", digest, cache_dir)
        if path.is_file():
            return WalkTable.load(path)
    px, py = to_xy(plon, plat)
    sx, sy = to_xy(slon, slat)
    psnap = graph.snap_xy(px, py)
    ssnap = graph.snap_xy(sx, sy)
    if len(plon) <= len(slon):
        ptr, tgt, dist = graph.distances(psnap, ssnap, max_m)
    else:
        sptr, stgt, sdist = graph.distances(ssnap, psnap, max_m)
        t = WalkTable(sptr, stgt, np.zeros(len(stgt), np.int32), len(plon)).transpose()
        # carry float distances through the same permutation
        rows = np.repeat(np.arange(len(slon), dtype=np.int32), np.diff(sptr))
        order = np.lexsort((rows, stgt))
        ptr, tgt, dist = t.indptr, t.indices, sdist[order]
    extra = _straight_fallback(px, py, np.flatnonzero(~psnap.ok), sx, sy, max_m)
    ptr, tgt, dist = _merge_fallback(ptr, tgt, dist, extra)
    table = WalkTable(ptr, tgt.astype(np.int32), seconds(dist, speed), len(slon))
    if use_cache:
        with contextlib.suppress(OSError):
            table.save(_cache_file("access", digest, cache_dir))
    return table
