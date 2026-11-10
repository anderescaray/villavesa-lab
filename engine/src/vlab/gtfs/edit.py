"""Pure, cheap timetable modifications for the scenario layer and the optimizer.

Every function returns a NEW :class:`~vlab.gtfs.timetable.Timetable`; the input is never
mutated. Unchanged stop, route and shape arrays are shared; the flat trip-time arrays
and the stop→pattern index are rebuilt by concatenating per-pattern views, which takes
~1-3 ms on the full Pamplona day (≈60k stop-times).

Pattern indices may change after removals or FIFO splits; use ``PatternInfo.key`` /
``tt.pattern_index[key]`` as a stable handle.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

import numpy as np
import numpy.typing as npt

from vlab.gtfs.geometry import cumulative_length, to_xy
from vlab.gtfs.timetable import (
    F64,
    I32,
    PatternBlock,
    PatternInfo,
    RouteInfo,
    Timetable,
    assemble,
    blocks_of,
    normalize_block,
)


def _block(
    info: PatternInfo,
    stops: npt.ArrayLike,
    arr: npt.ArrayLike,
    dep: npt.ArrayLike | None,
    offsets: npt.ArrayLike | None,
    tt: Timetable,
) -> PatternBlock:
    s = np.asarray(stops, dtype=np.int32)
    a = np.atleast_2d(np.asarray(arr, dtype=np.int32))
    d = a.copy() if dep is None else np.atleast_2d(np.asarray(dep, dtype=np.int32))
    if a.shape[0] == 0:
        a = a.reshape(0, len(s))
        d = d.reshape(0, len(s))
    off = (
        cumulative_length(tt.stop_x[s], tt.stop_y[s])
        if offsets is None
        else np.asarray(offsets, dtype=np.float64)
    )
    if len(off) != len(s):
        raise ValueError("offsets must have one value per stop")
    n = a.shape[0]
    return PatternBlock(
        info, s, a, d, off, np.full(n, -1, dtype=np.int32), np.zeros(n, dtype=np.bool_)
    )


def with_pattern_trips(
    tt: Timetable, pattern: int | str, arr: npt.ArrayLike, dep: npt.ArrayLike | None = None
) -> Timetable:
    """Replace all trips of one pattern (``arr``/``dep``: ``[n_trips, n_stops]`` seconds;
    ``dep`` defaults to ``arr``). Trips are re-sorted; if they overtake, the pattern is
    split into FIFO sub-patterns (keys ``<key>~i``). Zero trips is allowed."""
    p = tt.pattern_index[pattern] if isinstance(pattern, str) else int(pattern)
    old = tt.patterns[p]
    a, b = tt.pattern_stops_ptr[p], tt.pattern_stops_ptr[p + 1]
    new = _block(old, tt.pattern_stops[a:b], arr, dep, tt.pattern_stop_offset_m[a:b], tt)
    return _replace_pattern(tt, p, new)


def with_pattern_stops(
    tt: Timetable,
    pattern: int | str,
    stops: npt.ArrayLike,
    arr: npt.ArrayLike,
    dep: npt.ArrayLike | None = None,
    offsets: npt.ArrayLike | None = None,
) -> Timetable:
    """Replace the stop sequence AND trips of a pattern (stop insertion/removal).

    ``offsets`` (metres along the pattern's shape) default to straight-line cumulative
    distances between stops.
    """
    p = tt.pattern_index[pattern] if isinstance(pattern, str) else int(pattern)
    return _replace_pattern(tt, p, _block(tt.patterns[p], stops, arr, dep, offsets, tt))


def _replace_pattern(tt: Timetable, p: int, new: PatternBlock) -> Timetable:
    """Swap pattern ``p`` (and its FIFO sub-patterns) for ``new``, normalising only the
    new block: unchanged blocks are already sorted and FIFO."""
    key = tt.patterns[p].key
    blocks: list[PatternBlock] = []
    for b in blocks_of(tt):
        if b.info.key == key:
            blocks.extend(normalize_block(new))
        elif b.info.parent != key:
            blocks.append(b)
    return assemble(tt, blocks, normalize=False)


def with_patterns_removed(tt: Timetable, patterns: Iterable[int | str]) -> Timetable:
    """Remove patterns (by index or key) together with their FIFO sub-patterns."""
    keys = {tt.patterns[p].key if isinstance(p, int | np.integer) else p for p in patterns}
    unknown = keys - set(tt.pattern_index)
    if unknown:
        raise KeyError(f"unknown pattern(s): {sorted(unknown)[:5]}")
    blocks = [b for b in blocks_of(tt) if b.info.key not in keys and b.info.parent not in keys]
    return assemble(tt, blocks, normalize=False)


def with_route_removed(tt: Timetable, route_id: str) -> Timetable:
    """Remove every pattern of a route (the route metadata entry is kept)."""
    r = tt.route_index[route_id]
    return with_patterns_removed(tt, [p.key for p in tt.patterns if p.route_idx == r])


def with_pattern_added(
    tt: Timetable,
    stop_seq: npt.ArrayLike,
    arr: npt.ArrayLike,
    dep: npt.ArrayLike | None,
    meta: PatternInfo,
    offsets: npt.ArrayLike | None = None,
) -> Timetable:
    """Append a new pattern (``meta.key`` must be unused). Returns the new timetable;
    the new pattern is at ``result.pattern_index[meta.key]``."""
    if meta.key in tt.pattern_index:
        raise ValueError(f"pattern key {meta.key!r} already exists")
    blocks = blocks_of(tt)
    blocks.extend(normalize_block(_block(meta, stop_seq, arr, dep, offsets, tt)))
    return assemble(tt, blocks, normalize=False)


def with_route_added(tt: Timetable, route: RouteInfo) -> Timetable:
    """Append a route metadata entry (its index is ``result.route_index[route_id]``)."""
    if route.route_id in tt.route_index:
        raise ValueError(f"route {route.route_id!r} already exists")
    return assemble(tt, blocks_of(tt), routes=(*tt.routes, route), normalize=False)


def with_stops_added(
    tt: Timetable,
    stop_ids: Sequence[str],
    names: Sequence[str],
    lon: npt.ArrayLike,
    lat: npt.ArrayLike,
) -> Timetable:
    """Append stops; existing stop indices are unchanged, new ones follow."""
    ids = [str(s) for s in stop_ids]
    clash = set(ids) & set(tt.stop_ids)
    if clash or len(set(ids)) != len(ids):
        raise ValueError(f"duplicate stop id(s): {sorted(clash)[:5] or ids}")
    lon_a = np.asarray(lon, dtype=np.float64).ravel()
    lat_a = np.asarray(lat, dtype=np.float64).ravel()
    if not len(ids) == len(names) == len(lon_a) == len(lat_a):
        raise ValueError("stop_ids, names, lon and lat must have the same length")
    x, y = to_xy(lon_a, lat_a)
    stops = (
        (*tt.stop_ids, *ids),
        (*tt.stop_names, *[str(n) for n in names]),
        np.concatenate([tt.stop_lon, lon_a]),
        np.concatenate([tt.stop_lat, lat_a]),
        np.concatenate([tt.stop_x, x]),
        np.concatenate([tt.stop_y, y]),
    )
    return assemble(tt, blocks_of(tt), stops=stops, normalize=False)


def with_stops_moved(
    tt: Timetable, stops: Sequence[int], lon: npt.ArrayLike, lat: npt.ArrayLike
) -> Timetable:
    """Change the coordinates of existing stops (indices unchanged)."""
    idx = np.asarray(stops, dtype=np.int64)
    lon_n, lat_n = tt.stop_lon.copy(), tt.stop_lat.copy()
    lon_n[idx] = np.asarray(lon, dtype=np.float64)
    lat_n[idx] = np.asarray(lat, dtype=np.float64)
    x, y = to_xy(lon_n, lat_n)
    new = (tt.stop_ids, tt.stop_names, lon_n, lat_n, x, y)
    return assemble(tt, blocks_of(tt), stops=new, normalize=False)


def with_pattern_info(tt: Timetable, pattern: int | str, **changes: object) -> Timetable:
    """Replace metadata fields of a pattern (e.g. ``headsign``)."""
    p = tt.pattern_index[pattern] if isinstance(pattern, str) else int(pattern)
    blocks = blocks_of(tt)
    blocks[p].info = replace(blocks[p].info, **changes)  # type: ignore[arg-type]
    return assemble(tt, blocks, normalize=False)


# =============================================================== running-time profiles


@dataclass(frozen=True)
class RunningProfile:
    """Running times of a pattern by time of day.

    ``arr_offset[b, i]`` / ``dep_offset[b, i]`` are seconds after the departure from the
    first stop, for trips departing in bin ``b`` = ``[bin_start[b], bin_start[b+1])``
    (the last bin is open-ended). ``dep_offset[:, 0] == 0``.
    """

    bin_start: I32
    arr_offset: I32
    dep_offset: I32

    @property
    def n_stops(self) -> int:
        return int(self.arr_offset.shape[1])

    def bin_of(self, t: npt.ArrayLike) -> npt.NDArray[np.int64]:
        return np.clip(np.searchsorted(self.bin_start, t, side="right") - 1, 0, None)

    def run_time(self, b: int = 0) -> int:
        return int(self.arr_offset[b, -1])

    @staticmethod
    def constant(
        arr_offset: npt.ArrayLike, dep_offset: npt.ArrayLike | None = None
    ) -> RunningProfile:
        """A single all-day profile from 1-D offsets."""
        a = np.asarray(arr_offset, dtype=np.int32)[None, :]
        d = a.copy() if dep_offset is None else np.asarray(dep_offset, dtype=np.int32)[None, :]
        return RunningProfile(np.zeros(1, dtype=np.int32), a, d)

    def scaled(self, factor: float, segments: slice | None = None) -> RunningProfile:
        """Divide running (not dwell) times by ``factor`` (> 1 = faster), optionally only
        on the segments ``segments`` (indices of inter-stop links ``i → i+1``)."""
        run = self.arr_offset[:, 1:] - self.dep_offset[:, :-1]
        dwell = self.dep_offset - self.arr_offset
        mask = np.zeros(run.shape[1], dtype=bool)
        mask[segments if segments is not None else slice(None)] = True
        run = np.where(mask[None, :], np.round(run / factor), run).astype(np.int64)
        arr = np.zeros_like(self.arr_offset, dtype=np.int64)
        dep = np.zeros_like(self.dep_offset, dtype=np.int64)
        dep[:, 0] = dwell[:, 0]
        for i in range(1, arr.shape[1]):
            arr[:, i] = dep[:, i - 1] + run[:, i - 1]
            dep[:, i] = arr[:, i] + dwell[:, i]
        shift = dep[:, :1]  # keep departure from first stop at offset 0
        return RunningProfile(
            self.bin_start, (arr - shift).astype(np.int32), (dep - shift).astype(np.int32)
        )


def running_profile(
    tt: Timetable, pattern: int | str, bin_s: int = 3600, *, min_trips: int = 1
) -> RunningProfile:
    """Median running-time profile of a pattern's trips, by departure-time bins.

    Bins with fewer than ``min_trips`` trips take the nearest populated bin's profile.
    Bins cover the day of the pattern's first to last departure.
    """
    p = tt.pattern_index[pattern] if isinstance(pattern, str) else int(pattern)
    arr = tt.arrivals(p).astype(np.int64)
    dep = tt.departures(p).astype(np.int64)
    if arr.shape[0] == 0:
        raise ValueError(f"pattern {tt.patterns[p].key} has no trips")
    t0 = dep[:, 0]
    first = int(t0.min() // bin_s * bin_s)
    starts = np.arange(first, int(t0.max()) + 1, bin_s, dtype=np.int64)
    b_of = (t0 - first) // bin_s
    a_off = np.zeros((len(starts), arr.shape[1]), dtype=np.int64)
    d_off = np.zeros_like(a_off)
    have = np.zeros(len(starts), dtype=bool)
    for b in range(len(starts)):
        sel = b_of == b
        if sel.sum() >= min_trips:
            a_off[b] = np.round(np.median(arr[sel] - t0[sel, None], axis=0))
            d_off[b] = np.round(np.median(dep[sel] - t0[sel, None], axis=0))
            have[b] = True
    if not have.any():
        have[:] = False
        a_off[:] = np.round(np.median(arr - t0[:, None], axis=0))
        d_off[:] = np.round(np.median(dep - t0[:, None], axis=0))
    else:
        idx = np.flatnonzero(have)
        for empty in np.flatnonzero(~have):
            nearest = int(idx[np.argmin(np.abs(idx - empty))])
            a_off[empty], d_off[empty] = a_off[nearest], d_off[nearest]
    # medians are taken per column; enforce consistency along the trip
    d_off = np.maximum(d_off, a_off)
    d_off[:, 0] = 0
    a_off[:, 0] = np.minimum(a_off[:, 0], 0)
    for i in range(1, a_off.shape[1]):
        a_off[:, i] = np.maximum(a_off[:, i], d_off[:, i - 1])
        d_off[:, i] = np.maximum(d_off[:, i], a_off[:, i])
    return RunningProfile(starts.astype(np.int32), a_off.astype(np.int32), d_off.astype(np.int32))


def synthesize_trips(
    profile: RunningProfile, first_dep: int, last_dep: int, headway: int
) -> tuple[I32, I32]:
    """Regular-headway trips ``first_dep, first_dep+headway, ... <= last_dep``.

    Each trip uses the profile bin of its departure time. Overtaking (a later trip
    running faster than the earlier one) is removed by holding the later bus
    (``arr[t] = max(arr[t], arr[t-1])`` per stop), so the result is FIFO.

    Returns ``(arr, dep)`` of shape ``[n_trips, n_stops]``.
    """
    if headway <= 0:
        raise ValueError("headway must be positive")
    t0 = np.arange(int(first_dep), int(last_dep) + 1, int(headway), dtype=np.int64)
    b = profile.bin_of(t0)
    arr = t0[:, None] + profile.arr_offset[b].astype(np.int64)
    dep = t0[:, None] + profile.dep_offset[b].astype(np.int64)
    if len(t0) > 1:
        arr = np.maximum.accumulate(arr, axis=0)
        dep = np.maximum.accumulate(np.maximum(dep, arr), axis=0)
    return arr.astype(np.int32), dep.astype(np.int32)


def scale_pattern_frequency(tt: Timetable, pattern: int | str, factor: float) -> tuple[I32, I32]:
    """Trips for a pattern with its headway divided by ``factor`` over the same span,
    using its own running profile. Returns ``(arr, dep)`` for :func:`with_pattern_trips`."""
    p = tt.pattern_index[pattern] if isinstance(pattern, str) else int(pattern)
    dep = tt.departures(p)
    if dep.shape[0] < 2:
        return tt.arrivals(p).copy(), dep.copy()
    t0 = dep[:, 0]
    hw = float(np.median(np.diff(t0)))
    hw = max(60, round(hw / factor))
    return synthesize_trips(running_profile(tt, p), int(t0.min()), int(t0.max()), int(hw))


def offsets_on_shape(tt: Timetable, shape_idx: int, stops: npt.ArrayLike) -> F64:
    """Monotone offsets (m) of ``stops`` along shape ``shape_idx``."""
    from vlab.gtfs.geometry import project_monotone

    s = np.asarray(stops, dtype=np.int64)
    x, y = tt.shape_xy(shape_idx)
    off, _ = project_monotone(x, y, tt.stop_x[s], tt.stop_y[s])
    return off
