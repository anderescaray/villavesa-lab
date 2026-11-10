"""Timetable construction: patterns, FIFO, indexes, shapes, overnight trips."""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from vlab.gtfs import (
    Feed,
    Timetable,
    build_timetable,
    load_feed,
    project_monotone,
    synthetic_timetable,
    trips_mask,
)
from vlab.gtfs.timetable import fifo_chains, sort_trips, validate_timetable


def check_invariants(tt: Timetable) -> None:
    validate_timetable(tt)
    assert not tt.arr.flags.writeable and not tt.dep.flags.writeable
    # the stop -> pattern index lists every occurrence, and points at the right stop
    for s in range(tt.n_stops):
        for j in range(tt.stop_patterns_ptr[s], tt.stop_patterns_ptr[s + 1]):
            p, pos = int(tt.stop_patterns[j]), int(tt.stop_patterns_pos[j])
            assert tt.pattern_stop_seq(p)[pos] == s
    assert tt.stop_patterns_ptr[-1] == len(tt.pattern_stops)
    for p in range(tt.n_patterns):
        assert np.all(np.diff(tt.departures(p)[:, 0]) >= 0)


def test_validate_detects_broken_timetable() -> None:
    tt = synthetic_timetable([0, 0.001], [42.8] * 2, [([0, 1], [[0, 60]], None)])
    validate_timetable(tt)
    broken = dataclasses.replace(tt, stop_patterns_pos=np.array([1, 0], np.int32))
    with pytest.raises(ValueError, match="positions"):
        validate_timetable(broken)


def test_fifo_split_on_overtaking() -> None:
    # trip 2 departs later but arrives earlier (express): must be split off
    arr = np.array([[0, 600, 1200], [300, 700, 1100], [900, 1500, 2100]], np.int32)
    tt = synthetic_timetable([0, 0.001, 0.002], [42.8] * 3, [([0, 1, 2], arr, None)])
    check_invariants(tt)
    assert tt.n_patterns == 2
    assert tt.patterns[1].parent == tt.patterns[0].key
    assert sorted([tt.n_pattern_trips(0), tt.n_pattern_trips(1)]) == [1, 2]
    assert tt.n_trips == 3


def test_sort_and_chains_helpers() -> None:
    arr = np.array([[10, 20], [0, 30], [5, 15]], np.int32)
    order = sort_trips(arr, arr)
    assert order.tolist() == [1, 2, 0]
    chains = fifo_chains(arr[order], arr[order])
    assert [c.tolist() for c in chains] == [[0], [1, 2]]


def test_monotone_projection_on_loop() -> None:
    # A loop shape: out along y=0, back along y=10 (out-and-back on parallel streets).
    line_x = np.array([0.0, 1000.0, 1000.0, 0.0])
    line_y = np.array([0.0, 0.0, 10.0, 10.0])
    # Stops on the return leg (y≈10) but listed after outbound stops; a stop at x=500 on
    # the return leg is 4 m from the outbound line too.
    px = np.array([100.0, 600.0, 900.0, 500.0, 100.0])
    py = np.array([1.0, 1.0, 1.0, 6.0, 9.0])
    off, dist = project_monotone(line_x, line_y, px, py)
    assert np.all(np.diff(off) >= 0)
    np.testing.assert_allclose(off, [100, 600, 900, 1010 + 500, 1010 + 900], atol=1e-6)
    assert dist.max() <= 4.0 + 1e-9
    # A greedy nearest projection would put the 4th stop on the outbound leg (4 m < 4 m?)
    # — the DP keeps the order.


def test_mini_feed_timetable(make_gtfs_zip: Any, tmp_path: Path) -> None:
    f = load_feed(make_gtfs_zip(), cache_dir=tmp_path / "c")
    tt = build_timetable(f, "2026-11-11")
    check_invariants(tt)
    assert tt.date == dt.date(2026, 11, 11)
    assert [r.short_name for r in tt.routes] == ["L01", "N01"]
    assert tt.routes[0].color == "#E3051B"
    a = tt.pattern_index["A:0:0"]
    assert tt.n_pattern_trips(a) == 2
    assert tt.departures(a)[:, 0].tolist() == [28800, 30600]
    assert tt.pattern_offsets(a)[0] == pytest.approx(0.0, abs=1e-6)
    # next day: t3 runs, and the night trip n1 of the 11th is carried over
    tt2 = build_timetable(f, "2026-11-12")
    check_invariants(tt2)
    n = tt2.pattern_index["N:1:0"]
    assert tt2.trip_prev_day[tt2.pattern_trips_ptr[n]]
    assert tt2.arrivals(n)[0].tolist() == [85800 - 86400, 87000 - 86400]
    tt3 = build_timetable(f, "2026-11-12", overnight=False)
    assert "N:1:0" not in tt3.pattern_index


def test_real_timetable_matches_feed(feed: Feed, tt_weekday: Timetable) -> None:
    tt = tt_weekday
    check_invariants(tt)
    own = ~tt.trip_prev_day
    assert own.sum() == trips_mask(feed, tt.date).sum() == 3084  # type: ignore[arg-type]
    assert tt.n_stops == 563
    assert len(tt.extra["shape_warnings"]) == 0  # type: ignore[arg-type]
    # every trip's times equal the feed's stop_times (spot-check 300 trips)
    ptr = feed.trip_ptr()
    st = feed.stop_times
    rng = np.random.default_rng(1)
    for p in rng.choice(tt.n_patterns, 60):
        seq = tt.pattern_stop_seq(int(p))
        a0 = tt.pattern_trips_ptr[p]
        for r in range(min(5, tt.n_pattern_trips(int(p)))):
            t = tt.trip_source[a0 + r]
            shift = 86400 if tt.trip_prev_day[a0 + r] else 0
            rows = st.iloc[ptr[t] : ptr[t + 1]]
            assert rows["stop_idx"].tolist() == seq.tolist()
            assert (rows["arrival"].to_numpy() - shift).tolist() == tt.arrivals(int(p))[r].tolist()
    # pattern lengths are plausible bus-line lengths
    lengths = np.array(
        [tt.pattern_offsets(p)[-1] - tt.pattern_offsets(p)[0] for p in range(tt.n_patterns)]
    )
    assert lengths.max() < 40_000 and np.median(lengths) > 2_000


def test_real_stop_offsets_close_to_shape(tt_weekday: Timetable) -> None:
    tt = tt_weekday
    worst = 0.0
    for p in range(tt.n_patterns):
        si = tt.patterns[p].shape_idx
        assert si >= 0
        x, y = tt.shape_xy(si)
        seq = tt.pattern_stop_seq(p)
        off, dist = project_monotone(x, y, tt.stop_x[seq], tt.stop_y[seq])
        np.testing.assert_allclose(off, tt.pattern_offsets(p))
        worst = max(worst, float(dist.max()))
        assert tt.pattern_offsets(p)[-1] <= tt.shape_cum_m[tt.shape_ptr[si + 1] - 1] + 1e-6
    assert worst < 150.0
