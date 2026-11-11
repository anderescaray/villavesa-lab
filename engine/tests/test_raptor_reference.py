"""RAPTOR vs an obviously-correct reference on the REAL feed.

The reference is built straight from the feed's ``stop_times`` (not from the Timetable,
so pattern grouping and FIFO splitting are validated too) and computes, round by
round and by brute force over every trip:

- ``T_k(s)`` = min arrival at ``s`` over every trip and every alighting position after
  the first position where the trip is boardable (``A_{k-1}(stop) + slack <= dep``);
- ``A_k(s)`` = min(``A_{k-1}(s)``, ``T_k(s)``, min over footpaths ``T_k(s') + d(s', s)``).

These are exactly the semantics documented in ``vlab.raptor.kernels``; per-round labels
must match exactly.
"""

from __future__ import annotations

import datetime as dt
import itertools

import numpy as np
import numpy.typing as npt
import pytest

from vlab.gtfs import Feed, Timetable, trips_mask
from vlab.raptor import INF, raptor, reconstruct_journey
from vlab.walk import WalkTable

I64 = npt.NDArray[np.int64]
BIG = np.int64(INF)


class Reference:
    def __init__(self, feed: Feed, date: dt.date, transfers: WalkTable, n_stops: int) -> None:
        ptr = feed.trip_ptr()
        st = feed.stop_times
        today = np.flatnonzero(trips_mask(feed, date))
        prev = np.flatnonzero(trips_mask(feed, date - dt.timedelta(days=1)))
        last_arr = st["arrival"].to_numpy()[ptr[1:] - 1]
        prev = prev[last_arr[prev] >= 86400]  # carried over past midnight
        trips = np.r_[today, prev]
        shift = np.r_[np.zeros(len(today)), np.full(len(prev), 86400)].astype(np.int64)
        lens = (ptr[trips + 1] - ptr[trips]).astype(np.int64)
        rows = np.concatenate([np.arange(ptr[t], ptr[t + 1]) for t in trips])
        self.stop = st["stop_idx"].to_numpy()[rows].astype(np.int64)
        sh = np.repeat(shift, lens)
        self.arr = st["arrival"].to_numpy()[rows].astype(np.int64) - sh
        self.dep = st["departure"].to_numpy()[rows].astype(np.int64) - sh
        self.trip_start = np.repeat(np.r_[0, np.cumsum(lens)[:-1]], lens)
        self.n_stops = n_stops
        self.fsrc = np.repeat(np.arange(transfers.n_rows), np.diff(transfers.indptr))
        self.fdst = transfers.indices.astype(np.int64)
        self.fsec = transfers.seconds.astype(np.int64)

    def run(self, sources: I64, times: I64, rounds: int, slack: int, foot0: bool = False) -> I64:
        A = np.full(self.n_stops, BIG, dtype=np.int64)
        np.minimum.at(A, sources, times)
        if foot0:
            src_mask = A < BIG
            ok = src_mask[self.fsrc] & ~src_mask[self.fdst]
            np.minimum.at(A, self.fdst[ok], A[self.fsrc[ok]] + self.fsec[ok])
        out = [A.copy()]
        for _ in range(rounds):
            a_at = A[self.stop]
            boardable = (a_at < BIG) & (a_at + slack <= self.dep)
            cs = np.cumsum(boardable) - boardable  # boardable rows strictly before
            before = cs - cs[self.trip_start]
            ride = before > 0
            T = np.full(self.n_stops, BIG, dtype=np.int64)
            np.minimum.at(T, self.stop[ride], self.arr[ride])
            new = np.minimum(A, T)
            ok = T[self.fsrc] < BIG
            np.minimum.at(new, self.fdst[ok], T[self.fsrc[ok]] + self.fsec[ok])
            A = new
            out.append(A.copy())
        return np.vstack(out)


@pytest.fixture(scope="module")
def reference(feed: Feed, tt_weekday: Timetable, transfers_weekday: WalkTable) -> Reference:
    assert tt_weekday.date is not None
    return Reference(feed, tt_weekday.date, transfers_weekday, tt_weekday.n_stops)


@pytest.mark.parametrize("slack", [60, 0])
def test_single_stop_queries_match_reference(
    tt_weekday: Timetable, transfers_weekday: WalkTable, reference: Reference, slack: int
) -> None:
    rng = np.random.default_rng(20261111 + slack)
    n = 150 if slack else 60
    stops = rng.integers(0, tt_weekday.n_stops, n)
    times = rng.integers(4 * 3600, 25 * 3600, n)
    times[:5] = [0, 3600, 86000, 87000, 5 * 3600]  # night + previous-day carry-over
    for s, t in zip(stops, times, strict=True):
        r = raptor(tt_weekday, transfers_weekday, [s], int(t), board_slack=slack)
        ref = reference.run(np.array([s]), np.array([t]), 4, slack)
        np.testing.assert_array_equal(r.rounds.astype(np.int64), ref, err_msg=f"stop {s} t {t}")


def test_multi_source_queries_match_reference(
    tt_weekday: Timetable, transfers_weekday: WalkTable, reference: Reference
) -> None:
    rng = np.random.default_rng(7)
    for i in range(60):
        k = int(rng.integers(1, 8))
        src = rng.choice(tt_weekday.n_stops, k, replace=False)
        off = rng.integers(0, 900, k)
        t = int(rng.integers(6 * 3600, 21 * 3600))
        rounds = int(rng.integers(1, 6))
        foot0 = bool(i % 3 == 0)
        r = raptor(tt_weekday, transfers_weekday, src, t, off, max_rounds=rounds, foot_round0=foot0)
        ref = reference.run(src.astype(np.int64), off + t, rounds, 60, foot0)
        np.testing.assert_array_equal(r.rounds.astype(np.int64), ref)


def test_journeys_are_consistent(tt_weekday: Timetable, transfers_weekday: WalkTable) -> None:
    tt, tr = tt_weekday, transfers_weekday
    rng = np.random.default_rng(11)
    walk = {
        (int(a), int(b)): int(s)
        for a, b, s in zip(
            np.repeat(np.arange(tr.n_rows), np.diff(tr.indptr)), tr.indices, tr.seconds, strict=True
        )
    }
    checked = 0
    for _ in range(40):
        src = int(rng.integers(0, tt.n_stops))
        t0 = int(rng.integers(6 * 3600, 20 * 3600))
        r = raptor(tt, tr, [src], t0)
        for target in rng.choice(r.reached(), 10):
            legs = reconstruct_journey(tt, r, int(target))
            assert legs is not None
            assert legs[0].mode == "access" and legs[0].to_stop == src
            assert legs[-1].to_stop == target and legs[-1].arrive == r.arrival[target]
            assert sum(lg.mode == "ride" for lg in legs) <= 4
            clock = legs[0].arrive
            for prev, lg in itertools.pairwise(legs):
                assert lg.from_stop == prev.to_stop
                if lg.mode == "ride":
                    assert lg.depart >= clock + 60  # board slack
                    seq = tt.pattern_stop_seq(lg.pattern)
                    assert seq[lg.board_pos] == lg.from_stop and seq[lg.alight_pos] == lg.to_stop
                    assert lg.board_pos < lg.alight_pos
                else:
                    assert lg.mode == "walk" and prev.mode == "ride"
                    assert lg.depart == clock
                    assert lg.arrive - lg.depart == walk[(lg.from_stop, lg.to_stop)]
                clock = lg.arrive
            checked += 1
    assert checked == 400


def test_later_departure_never_arrives_earlier(
    tt_weekday: Timetable, transfers_weekday: WalkTable
) -> None:
    rng = np.random.default_rng(5)
    for s in rng.integers(0, tt_weekday.n_stops, 20):
        prev = None
        for t in range(7 * 3600, 9 * 3600, 300):
            a = raptor(tt_weekday, transfers_weekday, [s], t).arrival.astype(np.int64)
            if prev is not None:
                assert np.all(a >= prev)
            prev = a


def test_removing_service_never_helps(tt_weekday: Timetable, transfers_weekday: WalkTable) -> None:
    from vlab.gtfs import with_route_removed

    reduced = with_route_removed(tt_weekday, tt_weekday.routes[3].route_id)
    rng = np.random.default_rng(9)
    for s in rng.integers(0, tt_weekday.n_stops, 20):
        full = raptor(tt_weekday, transfers_weekday, [s], 8 * 3600).arrival
        less = raptor(reduced, transfers_weekday, [s], 8 * 3600).arrival
        assert np.all(less.astype(np.int64) >= full)
