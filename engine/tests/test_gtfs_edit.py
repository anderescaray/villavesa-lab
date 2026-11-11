"""Cheap pure timetable edits and trip synthesis."""

from __future__ import annotations

import time

import numpy as np
import pytest

from vlab.gtfs import (
    PatternInfo,
    RouteInfo,
    RunningProfile,
    Timetable,
    running_profile,
    scale_pattern_frequency,
    synthesize_trips,
    synthetic_timetable,
    with_pattern_added,
    with_pattern_info,
    with_pattern_stops,
    with_pattern_trips,
    with_patterns_removed,
    with_route_added,
    with_route_removed,
    with_stops_added,
    with_stops_moved,
)
from vlab.gtfs.timetable import validate_timetable
from vlab.raptor import INF, raptor


def _busiest(tt: Timetable) -> int:
    return int(np.argmax([tt.n_pattern_trips(p) for p in range(tt.n_patterns)]))


def test_with_pattern_trips_is_pure_and_fast(tt_weekday: Timetable) -> None:
    tt = tt_weekday
    p = _busiest(tt)
    arr = tt.arrivals(p)[::2].copy()
    dep = tt.departures(p)[::2].copy()
    before = tt.arr.copy()
    t = time.perf_counter()
    for _ in range(20):
        new = with_pattern_trips(tt, p, arr, dep)
    elapsed = (time.perf_counter() - t) / 20
    assert elapsed < 0.02, f"rebuild took {elapsed * 1000:.1f} ms"
    validate_timetable(new)
    assert np.array_equal(tt.arr, before)  # input untouched
    q = new.pattern_index[tt.patterns[p].key]
    assert new.n_pattern_trips(q) == len(arr)
    # FIFO sub-patterns split from p are part of the replaced logical pattern
    children = [i for i, pi in enumerate(tt.patterns) if pi.parent == tt.patterns[p].key]
    replaced = tt.n_pattern_trips(p) + sum(tt.n_pattern_trips(c) for c in children)
    assert new.n_trips == tt.n_trips - replaced + len(arr)
    assert new.stop_lon is tt.stop_lon and new.shape_lon is tt.shape_lon  # shared
    # other patterns unchanged
    other = next(i for i in range(tt.n_patterns) if i != p and i not in children)
    k = tt.patterns[other].key
    assert np.array_equal(new.arrivals(new.pattern_index[k]), tt.arrivals(other))


def test_remove_and_add_patterns(tt_weekday: Timetable) -> None:
    tt = tt_weekday
    keys = [tt.patterns[0].key, tt.patterns[5].key]
    new = with_patterns_removed(tt, keys)
    validate_timetable(new)
    assert new.n_patterns == tt.n_patterns - 2
    assert not set(keys) & set(new.pattern_index)
    with pytest.raises(KeyError):
        with_patterns_removed(tt, ["nope"])
    rid = tt.routes[3].route_id
    gone = with_route_removed(tt, rid)
    assert not gone.patterns_of_route(rid)

    seq = tt.pattern_stop_seq(0)[:4].copy()
    profile = RunningProfile.constant([0, 120, 240, 360])
    arr, dep = synthesize_trips(profile, 7 * 3600, 9 * 3600, 600)
    t2 = with_route_added(tt, RouteInfo("X", "LX", "New", "#1F6FEB", "#FFFFFF", "day"))
    meta = PatternInfo("X:0:0", t2.route_index["X"], 0, "Somewhere", -1)
    added = with_pattern_added(t2, seq, arr, dep, meta)
    validate_timetable(added)
    q = added.pattern_index["X:0:0"]
    assert added.n_pattern_trips(q) == 13
    assert added.pattern_offsets(q)[0] == 0 and added.pattern_offsets(q)[-1] > 0
    with pytest.raises(ValueError):
        with_pattern_added(added, seq, arr, dep, meta)


def test_added_line_is_routable() -> None:
    lon = [-1.65, -1.64, -1.63, -1.62]
    lat = [42.8] * 4
    tt = synthetic_timetable(lon, lat, [([0, 1], [[100, 200]], None)])
    assert raptor(tt, None, [0], 0).arrival[3] == INF
    tt2 = with_pattern_added(tt, [1, 2, 3], [[300, 400, 500]], None, PatternInfo("n", 0, 0, "", -1))
    r = raptor(tt2, None, [0], 0, board_slack=0)
    assert r.arrival[3] == 500


def test_stops_added_and_moved(tt_weekday: Timetable) -> None:
    tt = tt_weekday
    new = with_stops_added(tt, ["new-1", "new-2"], ["A", "B"], [-1.64, -1.65], [42.81, 42.82])
    validate_timetable(new)
    assert new.n_stops == tt.n_stops + 2
    assert new.stop_index["new-1"] == tt.n_stops
    assert new.stop_patterns_ptr[-1] == tt.stop_patterns_ptr[-1]
    with pytest.raises(ValueError):
        with_stops_added(tt, [tt.stop_ids[0]], ["dup"], [0.0], [0.0])
    moved = with_stops_moved(tt, [0], [-1.6], [42.8])
    assert moved.stop_lon[0] == -1.6 and moved.stop_x[0] != tt.stop_x[0]
    assert tt.stop_lon[0] != -1.6


def test_with_pattern_stops_removes_a_stop(tt_weekday: Timetable) -> None:
    tt = tt_weekday
    p = _busiest(tt)
    keep = np.r_[0:3, 4 : len(tt.pattern_stop_seq(p))]
    new = with_pattern_stops(
        tt,
        p,
        tt.pattern_stop_seq(p)[keep],
        tt.arrivals(p)[:, keep],
        tt.departures(p)[:, keep],
        tt.pattern_offsets(p)[keep],
    )
    validate_timetable(new)
    q = new.pattern_index[tt.patterns[p].key]
    assert len(new.pattern_stop_seq(q)) == len(keep)
    renamed = with_pattern_info(tt, p, headsign="Elsewhere")
    assert renamed.patterns[p].headsign == "Elsewhere"


def test_overtaking_edit_splits(tt_weekday: Timetable) -> None:
    tt = tt_weekday
    p = _busiest(tt)
    arr = tt.arrivals(p).astype(np.int64).copy()
    # make the 2nd trip an express overtaking the 1st
    arr[1, 1:] = arr[0, 1:] - 30
    arr[1] = np.maximum.accumulate(np.maximum(arr[1], arr[1, 0]))
    new = with_pattern_trips(tt, p, arr, arr)
    validate_timetable(new)
    key = tt.patterns[p].key
    assert any(pi.parent == key for pi in new.patterns)
    # replacing the trips again drops the stale sub-pattern
    again = with_pattern_trips(new, key, tt.arrivals(p), tt.departures(p))
    assert not any(pi.parent == key for pi in again.patterns)


def test_running_profile_and_synthesis(tt_weekday: Timetable) -> None:
    tt = tt_weekday
    p = _busiest(tt)
    prof = running_profile(tt, p)
    assert prof.n_stops == len(tt.pattern_stop_seq(p))
    assert np.all(prof.dep_offset[:, 0] == 0)
    assert np.all(np.diff(prof.arr_offset, axis=1) >= 0)
    # the profile reproduces the median run time of trips in its bins
    dep = tt.departures(p)
    run = tt.arrivals(p)[:, -1] - dep[:, 0]
    b = prof.bin_of(dep[:, 0])
    for bi in np.unique(b):
        assert prof.arr_offset[bi, -1] == pytest.approx(np.median(run[b == bi]), abs=1)
    arr, dep2 = synthesize_trips(prof, 6 * 3600, 22 * 3600, 450)
    assert arr.shape == (len(range(6 * 3600, 22 * 3600 + 1, 450)), prof.n_stops)
    assert np.all(np.diff(arr, axis=0) >= 0)  # FIFO by construction
    new = with_pattern_trips(tt, p, arr, dep2)
    validate_timetable(new)
    a2, _d2 = scale_pattern_frequency(tt, p, 2.0)
    assert len(a2) >= 1.8 * tt.n_pattern_trips(p) - 2


def test_profile_scaling() -> None:
    prof = RunningProfile.constant([0, 100, 230, 300], [0, 110, 240, 300])
    fast = prof.scaled(2.0)
    # running times halved, dwell kept
    # links 100/120/60 s -> 50/60/30 s; 10 s dwells at stops 1 and 2 kept
    assert fast.arr_offset[0].tolist() == [0, 50, 120, 160]
    assert fast.dep_offset[0].tolist() == [0, 60, 130, 160]
    seg = prof.scaled(2.0, slice(1, 2))  # only link 1 -> 2
    assert seg.arr_offset[0].tolist() == [0, 100, 170, 240]
    with pytest.raises(ValueError):
        synthesize_trips(prof, 0, 100, 0)
