"""RAPTOR-ready timetable for one service date.

All arrays are immutable numpy arrays. Trips are grouped into *patterns* (unique route,
direction and exact stop sequence); each pattern owns a contiguous row-major block of
the flat ``arr``/``dep`` arrays of shape ``[n_trips, n_stops]``, with trips sorted by
departure at the first stop and no overtaking (FIFO) — patterns whose trips overtake are
split into sub-patterns, as RAPTOR requires.

Layout (``P`` patterns, ``S`` stops, ``T`` trips)::

    pattern_stops_ptr[P+1]  → pattern_stops[...]      (stop idx, in visiting order)
                              pattern_stop_offset_m    (metres along the shape, aligned)
    pattern_trips_ptr[P+1]  → trip rows (global trip idx) trip_source[T], trip_prev_day[T]
    pattern_times_ptr[P+1]  → arr[...], dep[...]       (int32 s, block n_t × n_s)
    stop_patterns_ptr[S+1]  → stop_patterns, stop_patterns_pos  (each occurrence)

Times are seconds since midnight of the service date (may exceed 86400; trips carried
over from the previous service day can start before 0).
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cached_property
from typing import Literal

import numpy as np
import numpy.typing as npt

from vlab.gtfs.calendar import to_date, trips_mask
from vlab.gtfs.feed import Feed
from vlab.gtfs.geometry import cumulative_length, project_monotone, to_xy

I32 = npt.NDArray[np.int32]
I64 = npt.NDArray[np.int64]
F64 = npt.NDArray[np.float64]
RouteKind = Literal["day", "night", "special"]

DAY_S = 86400


@dataclass(frozen=True)
class RouteInfo:
    """Per-route metadata (one entry per GTFS route present in the timetable)."""

    route_id: str
    short_name: str
    long_name: str
    color: str  # "#RRGGBB"
    text_color: str
    kind: RouteKind
    route_type: int = 3


@dataclass(frozen=True)
class PatternInfo:
    """Per-pattern metadata.

    ``key`` is a stable, human-readable id (``"<route_id>:<direction>:<n>"``) that
    survives edits which renumber patterns; ``parent`` is the key of the pattern a FIFO
    sub-pattern was split from (``""`` otherwise).
    """

    key: str
    route_idx: int
    direction: int
    headsign: str
    shape_idx: int  # -1: no shape
    parent: str = ""


@dataclass(frozen=True, eq=False)
class Timetable:
    """Immutable RAPTOR arrays for one service date. See module docstring."""

    date: dt.date | None
    # stops
    stop_ids: tuple[str, ...]
    stop_names: tuple[str, ...]
    stop_lon: F64
    stop_lat: F64
    stop_x: F64
    stop_y: F64
    # routes / patterns metadata
    routes: tuple[RouteInfo, ...]
    patterns: tuple[PatternInfo, ...]
    pattern_route: I32
    # pattern stop sequences
    pattern_stops_ptr: I32
    pattern_stops: I32
    pattern_stop_offset_m: F64
    # trips
    pattern_trips_ptr: I32
    pattern_times_ptr: I64
    arr: I32
    dep: I32
    trip_source: I32
    trip_prev_day: npt.NDArray[np.bool_]
    # stop → patterns
    stop_patterns_ptr: I32
    stop_patterns: I32
    stop_patterns_pos: I32
    # shapes
    shape_ids: tuple[str, ...]
    shape_ptr: I32
    shape_lon: F64
    shape_lat: F64
    shape_cum_m: F64
    extra: dict[str, object] = field(default_factory=dict, compare=False)

    # ------------------------------------------------------------------ sizes
    @property
    def n_stops(self) -> int:
        return len(self.stop_ids)

    @property
    def n_patterns(self) -> int:
        return len(self.patterns)

    @property
    def n_trips(self) -> int:
        return int(self.pattern_trips_ptr[-1])

    @property
    def n_routes(self) -> int:
        return len(self.routes)

    # ------------------------------------------------------------------ lookups
    @cached_property
    def stop_index(self) -> dict[str, int]:
        return {s: i for i, s in enumerate(self.stop_ids)}

    @cached_property
    def route_index(self) -> dict[str, int]:
        return {r.route_id: i for i, r in enumerate(self.routes)}

    @cached_property
    def pattern_index(self) -> dict[str, int]:
        return {p.key: i for i, p in enumerate(self.patterns)}

    def pattern_stop_seq(self, p: int) -> I32:
        """Stop indices of pattern ``p`` in visiting order (view)."""
        return self.pattern_stops[self.pattern_stops_ptr[p] : self.pattern_stops_ptr[p + 1]]

    def pattern_offsets(self, p: int) -> F64:
        """Metres along the shape of each stop of pattern ``p`` (view)."""
        a, b = self.pattern_stops_ptr[p], self.pattern_stops_ptr[p + 1]
        return self.pattern_stop_offset_m[a:b]

    def n_pattern_trips(self, p: int) -> int:
        return int(self.pattern_trips_ptr[p + 1] - self.pattern_trips_ptr[p])

    def _block(self, flat: I32, p: int) -> I32:
        n_s = int(self.pattern_stops_ptr[p + 1] - self.pattern_stops_ptr[p])
        a, b = int(self.pattern_times_ptr[p]), int(self.pattern_times_ptr[p + 1])
        return flat[a:b].reshape(-1, n_s)

    def arrivals(self, p: int) -> I32:
        """``[n_trips, n_stops]`` arrival times of pattern ``p`` (read-only view)."""
        return self._block(self.arr, p)

    def departures(self, p: int) -> I32:
        """``[n_trips, n_stops]`` departure times of pattern ``p`` (read-only view)."""
        return self._block(self.dep, p)

    def patterns_of_route(self, route: int | str) -> list[int]:
        r = self.route_index[route] if isinstance(route, str) else route
        return [int(i) for i in np.flatnonzero(self.pattern_route == r)]

    def shape_xy(self, shape_idx: int) -> tuple[F64, F64]:
        a, b = self.shape_ptr[shape_idx], self.shape_ptr[shape_idx + 1]
        return to_xy(self.shape_lon[a:b], self.shape_lat[a:b])

    def shape_coords(self, shape_idx: int) -> F64:
        """``[n, 2]`` lon/lat of a shape."""
        a, b = self.shape_ptr[shape_idx], self.shape_ptr[shape_idx + 1]
        return np.column_stack([self.shape_lon[a:b], self.shape_lat[a:b]])

    def raptor_arrays(self) -> tuple[I32, I32, I32, I64, I32, I32, I32, I32, I32]:
        """The arrays the numba kernels consume, in kernel argument order."""
        return (
            self.pattern_stops_ptr,
            self.pattern_stops,
            self.pattern_trips_ptr,
            self.pattern_times_ptr,
            self.arr,
            self.dep,
            self.stop_patterns_ptr,
            self.stop_patterns,
            self.stop_patterns_pos,
        )


# ============================================================================ assembly


def _ro(a: np.ndarray) -> np.ndarray:  # type: ignore[type-arg]
    a = np.ascontiguousarray(a)
    if a.flags.writeable and a.base is None:
        a.setflags(write=False)
    elif a.flags.writeable:
        a = a.copy()
        a.setflags(write=False)
    return a


def is_fifo(arr: I32, dep: I32) -> bool:
    """True if no trip overtakes the previous one at any stop (rows sorted)."""
    if arr.shape[0] < 2:
        return True
    return bool(np.all(np.diff(arr, axis=0) >= 0) and np.all(np.diff(dep, axis=0) >= 0))


def sort_trips(arr: I32, dep: I32) -> I64:
    """Row order by departure at first stop, then lexicographically by the rest."""
    keys = [dep[:, j] for j in range(dep.shape[1] - 1, -1, -1)]
    return np.lexsort(keys).astype(np.int64)


def fifo_chains(arr: I32, dep: I32) -> list[I64]:
    """Split sorted trips into FIFO chains (greedy first-fit; rows must be sorted)."""
    chains: list[list[int]] = []
    for t in range(arr.shape[0]):
        for ch in chains:
            last = ch[-1]
            if np.all(arr[t] >= arr[last]) and np.all(dep[t] >= dep[last]):
                ch.append(t)
                break
        else:
            chains.append([t])
    return [np.asarray(c, dtype=np.int64) for c in chains]


@dataclass
class PatternBlock:
    """Mutable per-pattern bundle used while assembling a :class:`Timetable`."""

    info: PatternInfo
    stops: I32
    arr: I32  # [n_trips, n_stops]
    dep: I32
    offsets: F64
    trip_source: I32
    trip_prev_day: npt.NDArray[np.bool_]


def blocks_of(tt: Timetable) -> list[PatternBlock]:
    """Per-pattern views of a timetable (no copies)."""
    out = []
    for p in range(tt.n_patterns):
        a, b = tt.pattern_trips_ptr[p], tt.pattern_trips_ptr[p + 1]
        out.append(
            PatternBlock(
                info=tt.patterns[p],
                stops=tt.pattern_stop_seq(p),
                arr=tt.arrivals(p),
                dep=tt.departures(p),
                offsets=tt.pattern_offsets(p),
                trip_source=tt.trip_source[a:b],
                trip_prev_day=tt.trip_prev_day[a:b],
            )
        )
    return out


def normalize_block(block: PatternBlock, *, check_sorted: bool = True) -> list[PatternBlock]:
    """Sort trips and split into FIFO sub-patterns if trips overtake.

    The first chain keeps ``block.info``; further chains get keys ``<key>~<i>`` and
    ``parent=<key>``.
    """
    arr = np.asarray(block.arr, dtype=np.int32)
    dep = np.asarray(block.dep, dtype=np.int32)
    if arr.ndim != 2 or arr.shape != dep.shape or arr.shape[1] != len(block.stops):
        raise ValueError(
            f"pattern {block.info.key}: times must be [n_trips, {len(block.stops)}], "
            f"got arr {arr.shape} dep {dep.shape}"
        )
    if len(block.stops) < 2:
        raise ValueError(f"pattern {block.info.key}: needs at least 2 stops")
    if np.any(dep < arr) or np.any(arr[:, 1:] < dep[:, :-1]):
        raise ValueError(f"pattern {block.info.key}: times decrease along a trip")
    if check_sorted and arr.shape[0] > 1:
        order = sort_trips(arr, dep)
        if np.any(order != np.arange(len(order))):
            arr, dep = arr[order], dep[order]
            block = PatternBlock(
                block.info,
                block.stops,
                arr,
                dep,
                block.offsets,
                np.asarray(block.trip_source)[order],
                np.asarray(block.trip_prev_day)[order],
            )
    if is_fifo(arr, dep):
        return [block]
    out = []
    for i, ch in enumerate(fifo_chains(arr, dep)):
        info = block.info
        if i > 0:
            info = PatternInfo(
                key=f"{block.info.key}~{i}",
                route_idx=info.route_idx,
                direction=info.direction,
                headsign=info.headsign,
                shape_idx=info.shape_idx,
                parent=block.info.key,
            )
        out.append(
            PatternBlock(
                info,
                block.stops,
                arr[ch],
                dep[ch],
                block.offsets,
                np.asarray(block.trip_source)[ch],
                np.asarray(block.trip_prev_day)[ch],
            )
        )
    return out


def stop_pattern_index(
    n_stops: int, pattern_stops_ptr: I32, pattern_stops: I32
) -> tuple[I32, I32, I32]:
    """CSR stop → (pattern, position) over every occurrence of the stop."""
    n_pat = len(pattern_stops_ptr) - 1
    lens = np.diff(pattern_stops_ptr)
    pat = np.repeat(np.arange(n_pat, dtype=np.int32), lens)
    pos = (np.arange(len(pattern_stops)) - np.repeat(pattern_stops_ptr[:-1], lens)).astype(np.int32)
    order = np.lexsort((pos, pat, pattern_stops))
    counts = np.bincount(pattern_stops, minlength=n_stops)
    ptr = np.zeros(n_stops + 1, dtype=np.int32)
    np.cumsum(counts, out=ptr[1:])
    return ptr, pat[order].astype(np.int32), pos[order].astype(np.int32)


def assemble(
    base: Timetable,
    blocks: Sequence[PatternBlock],
    *,
    routes: tuple[RouteInfo, ...] | None = None,
    stops: tuple[tuple[str, ...], tuple[str, ...], F64, F64, F64, F64] | None = None,
    normalize: bool = True,
) -> Timetable:
    """Build a new :class:`Timetable` from pattern blocks, sharing ``base``'s stop,
    route and shape arrays unless replaced. Rebuild cost is O(total stop-times)."""
    if normalize:
        norm: list[PatternBlock] = []
        for b in blocks:
            norm.extend(normalize_block(b))
        blocks = norm
    stop_ids, stop_names, slon, slat, sx, sy = (
        stops
        if stops is not None
        else (base.stop_ids, base.stop_names, base.stop_lon, base.stop_lat, base.stop_x, base.stop_y)
    )
    routes = routes if routes is not None else base.routes
    n_stops = len(stop_ids)
    keys = [b.info.key for b in blocks]
    if len(set(keys)) != len(keys):
        dup = [k for k, c in Counter(keys).items() if c > 1]
        raise ValueError(f"duplicate pattern key(s): {dup[:5]}")
    for b in blocks:
        if len(b.stops) and (b.stops.min() < 0 or b.stops.max() >= n_stops):
            raise ValueError(f"pattern {b.info.key}: stop index out of range")
        if not 0 <= b.info.route_idx < len(routes):
            raise ValueError(f"pattern {b.info.key}: route index out of range")
    n_s = np.array([len(b.stops) for b in blocks], dtype=np.int64)
    n_t = np.array([b.arr.shape[0] for b in blocks], dtype=np.int64)
    ps_ptr = np.zeros(len(blocks) + 1, dtype=np.int32)
    np.cumsum(n_s, out=ps_ptr[1:])
    pt_ptr = np.zeros(len(blocks) + 1, dtype=np.int32)
    np.cumsum(n_t, out=pt_ptr[1:])
    tm_ptr = np.zeros(len(blocks) + 1, dtype=np.int64)
    np.cumsum(n_s * n_t, out=tm_ptr[1:])

    def cat(parts: list[np.ndarray], dtype: type) -> np.ndarray:  # type: ignore[type-arg]
        return np.concatenate(parts).astype(dtype, copy=False) if parts else np.zeros(0, dtype)

    pattern_stops = cat([np.asarray(b.stops) for b in blocks], np.int32)
    offsets = cat([np.asarray(b.offsets, dtype=np.float64) for b in blocks], np.float64)
    arr = cat([np.asarray(b.arr).ravel() for b in blocks], np.int32)
    dep = cat([np.asarray(b.dep).ravel() for b in blocks], np.int32)
    src = cat([np.asarray(b.trip_source) for b in blocks], np.int32)
    prev = cat([np.asarray(b.trip_prev_day) for b in blocks], np.bool_)
    sp_ptr, sp_pat, sp_pos = stop_pattern_index(n_stops, ps_ptr, pattern_stops)
    return Timetable(
        date=base.date,
        stop_ids=stop_ids,
        stop_names=stop_names,
        stop_lon=_ro(slon),
        stop_lat=_ro(slat),
        stop_x=_ro(sx),
        stop_y=_ro(sy),
        routes=routes,
        patterns=tuple(b.info for b in blocks),
        pattern_route=_ro(np.array([b.info.route_idx for b in blocks], dtype=np.int32)),
        pattern_stops_ptr=_ro(ps_ptr),
        pattern_stops=_ro(pattern_stops),
        pattern_stop_offset_m=_ro(offsets),
        pattern_trips_ptr=_ro(pt_ptr),
        pattern_times_ptr=_ro(tm_ptr),
        arr=_ro(arr),
        dep=_ro(dep),
        trip_source=_ro(src),
        trip_prev_day=_ro(prev),
        stop_patterns_ptr=_ro(sp_ptr),
        stop_patterns=_ro(sp_pat),
        stop_patterns_pos=_ro(sp_pos),
        shape_ids=base.shape_ids,
        shape_ptr=base.shape_ptr,
        shape_lon=base.shape_lon,
        shape_lat=base.shape_lat,
        shape_cum_m=base.shape_cum_m,
        extra=dict(base.extra),
    )


# ============================================================================ from GTFS

_DAY_RE = re.compile(r"^L\d+$")


def route_kinds(feed: Feed) -> dict[str, RouteKind]:
    """Classify routes as ``day`` / ``night`` / ``special``.

    - short name starting with ``N`` → night; ``R`` (event reinforcements) → special;
    - ``L<number>`` → day, unless >= 80 % of its trips start between 22:00 and 05:00
      (→ night);
    - anything else (``L6S``, ``L11N``... seasonal/event variants) → special.
    """
    ptr = feed.trip_ptr()
    first_dep = feed.stop_times["departure"].to_numpy()[ptr[:-1]] % DAY_S
    night_start = (first_dep >= 22 * 3600) | (first_dep < 5 * 3600)
    by_route: dict[str, list[bool]] = {}
    for rid, ns in zip(feed.trips["route_id"].tolist(), night_start.tolist(), strict=True):
        by_route.setdefault(rid, []).append(ns)
    out: dict[str, RouteKind] = {}
    for rid, short in zip(feed.routes["route_id"], feed.routes["route_short_name"], strict=True):
        s = str(short).strip().upper()
        if s.startswith("N"):
            out[rid] = "night"
        elif s.startswith("R"):
            out[rid] = "special"
        elif _DAY_RE.match(s):
            flags = by_route.get(rid, [])
            out[rid] = "night" if flags and np.mean(flags) >= 0.8 else "day"
        else:
            out[rid] = "special"
    return out


def build_timetable(
    feed: Feed,
    date: dt.date | str | int,
    *,
    overnight: bool = True,
    max_stop_shape_m: float = 150.0,
) -> Timetable:
    """Build the RAPTOR timetable of one service date.

    Args:
        feed: validated feed.
        date: service date.
        overnight: also include trips of the previous service day that run past
            midnight (times ≥ 24:00), shifted by −24 h and flagged in ``trip_prev_day``
            (so a 00:30 query sees the night buses that left at 23:50 "yesterday").
        max_stop_shape_m: stops farther than this from their pattern's shape are
            reported in ``extra["shape_warnings"]``.
    """
    d = to_date(date)
    st = feed.stop_times
    ptr = feed.trip_ptr()
    st_stop = st["stop_idx"].to_numpy()
    st_arr = st["arrival"].to_numpy()
    st_dep = st["departure"].to_numpy()

    today = np.flatnonzero(trips_mask(feed, d))
    selected: list[tuple[int, bool]] = [(int(t), False) for t in today]
    if overnight:
        prev_mask = trips_mask(feed, d - dt.timedelta(days=1))
        last_arr = st_arr[ptr[1:] - 1]
        for t in np.flatnonzero(prev_mask & (last_arr >= DAY_S)):
            selected.append((int(t), True))

    route_ids = feed.trips["route_id"].to_numpy()
    directions = feed.trips["direction_id"].to_numpy()
    headsigns = feed.trips["trip_headsign"].to_numpy()
    shape_of = feed.trips["shape_id"].to_numpy()

    groups: dict[tuple[str, int, tuple[int, ...]], list[tuple[int, bool]]] = {}
    for t, prev in selected:
        key = (str(route_ids[t]), int(directions[t]), tuple(st_stop[ptr[t] : ptr[t + 1]].tolist()))
        groups.setdefault(key, []).append((t, prev))

    # Routes present, in GTFS order.
    kinds = route_kinds(feed)
    present = {k[0] for k in groups}
    routes: list[RouteInfo] = []
    for row in feed.routes.itertuples(index=False):
        if row.route_id in present:
            routes.append(
                RouteInfo(
                    route_id=str(row.route_id),
                    short_name=str(row.route_short_name),
                    long_name=str(row.route_long_name),
                    color="#" + str(row.route_color),
                    text_color="#" + str(row.route_text_color),
                    kind=kinds[str(row.route_id)],
                    route_type=int(row.route_type),
                )
            )
    routes.sort(key=lambda r: (_route_sort_key(r.short_name), r.route_id))
    r_index = {r.route_id: i for i, r in enumerate(routes)}

    # Shapes used by the selected trips.
    used_shapes = sorted({str(shape_of[t]) for t, _ in selected if shape_of[t]})
    shp = feed.shapes
    shp = shp[shp["shape_id"].isin(used_shapes)]
    shape_ids = tuple(used_shapes)
    s_index = {s: i for i, s in enumerate(shape_ids)}
    counts = shp.groupby("shape_id", sort=True).size().reindex(list(shape_ids)).to_numpy()
    shape_ptr = np.zeros(len(shape_ids) + 1, dtype=np.int32)
    if len(shape_ids):
        np.cumsum(counts, out=shape_ptr[1:])
    shp = shp.set_index("shape_id").loc[list(shape_ids)] if len(shape_ids) else shp
    shape_lon = shp["shape_pt_lon"].to_numpy(dtype=np.float64)
    shape_lat = shp["shape_pt_lat"].to_numpy(dtype=np.float64)
    shx, shy = to_xy(shape_lon, shape_lat)
    shape_cum = np.zeros(len(shape_lon))
    for i in range(len(shape_ids)):
        a, b = shape_ptr[i], shape_ptr[i + 1]
        shape_cum[a:b] = cumulative_length(shx[a:b], shy[a:b])

    stops_df = feed.stops
    slon = stops_df["stop_lon"].to_numpy(dtype=np.float64)
    slat = stops_df["stop_lat"].to_numpy(dtype=np.float64)
    sx, sy = to_xy(slon, slat)

    ordered = sorted(
        groups.items(), key=lambda kv: (r_index[kv[0][0]], kv[0][1], -len(kv[1]), kv[0][2])
    )
    blocks: list[PatternBlock] = []
    per_route_dir: Counter[tuple[str, int]] = Counter()
    warnings: list[str] = []
    for (rid, direction, stop_seq), members in ordered:
        n = per_route_dir[(rid, direction)]
        per_route_dir[(rid, direction)] += 1
        key = f"{rid}:{direction}:{n}"
        tids = np.array([t for t, _ in members], dtype=np.int64)
        prev = np.array([p for _, p in members], dtype=np.bool_)
        idx = ptr[tids][:, None] + np.arange(len(stop_seq))[None, :]
        arr = st_arr[idx].astype(np.int32)
        dep = st_dep[idx].astype(np.int32)
        shift = np.where(prev, DAY_S, 0).astype(np.int32)[:, None]
        arr, dep = arr - shift, dep - shift
        shape_id = Counter(str(shape_of[t]) for t in tids).most_common(1)[0][0]
        headsign = Counter(str(headsigns[t]) for t in tids).most_common(1)[0][0]
        stops_arr = np.asarray(stop_seq, dtype=np.int32)
        if shape_id:
            si = s_index[shape_id]
            a, b = shape_ptr[si], shape_ptr[si + 1]
            off, dist = project_monotone(shx[a:b], shy[a:b], sx[stops_arr], sy[stops_arr])
            if dist.max() > max_stop_shape_m:
                warnings.append(f"{key}: stop {dist.argmax()} is {dist.max():.0f} m from shape")
        else:
            si = -1
            off = cumulative_length(sx[stops_arr], sy[stops_arr])
        blocks.append(
            PatternBlock(
                info=PatternInfo(key, r_index[rid], direction, headsign, si),
                stops=stops_arr,
                arr=arr,
                dep=dep,
                offsets=off,
                trip_source=tids.astype(np.int32),
                trip_prev_day=prev,
            )
        )

    base = Timetable(
        date=d,
        stop_ids=tuple(stops_df["stop_id"].astype(str)),
        stop_names=tuple(stops_df["stop_name"].astype(str)),
        stop_lon=slon,
        stop_lat=slat,
        stop_x=sx,
        stop_y=sy,
        routes=tuple(routes),
        patterns=(),
        pattern_route=np.zeros(0, np.int32),
        pattern_stops_ptr=np.zeros(1, np.int32),
        pattern_stops=np.zeros(0, np.int32),
        pattern_stop_offset_m=np.zeros(0),
        pattern_trips_ptr=np.zeros(1, np.int32),
        pattern_times_ptr=np.zeros(1, np.int64),
        arr=np.zeros(0, np.int32),
        dep=np.zeros(0, np.int32),
        trip_source=np.zeros(0, np.int32),
        trip_prev_day=np.zeros(0, np.bool_),
        stop_patterns_ptr=np.zeros(len(stops_df) + 1, np.int32),
        stop_patterns=np.zeros(0, np.int32),
        stop_patterns_pos=np.zeros(0, np.int32),
        shape_ids=shape_ids,
        shape_ptr=_ro(shape_ptr),
        shape_lon=_ro(shape_lon),
        shape_lat=_ro(shape_lat),
        shape_cum_m=_ro(shape_cum),
        extra={"shape_warnings": warnings, "feed_sha256": feed.source_sha256},
    )
    tt = assemble(base, blocks)
    n_split = sum(1 for p in tt.patterns if p.parent)
    tt.extra["fifo_splits"] = n_split
    return tt


def _route_sort_key(short_name: str) -> tuple[str, int, str]:
    m = re.match(r"^([A-Za-z]*)(\d*)(.*)$", short_name)
    if not m:
        return (short_name, 0, "")
    prefix, num, rest = m.groups()
    return (prefix.upper(), int(num) if num else 0, rest)
