"""RAPTOR on hand-built timetables with known answers."""

from __future__ import annotations

import numpy as np
import pytest

from vlab.gtfs import Timetable, synthetic_timetable
from vlab.raptor import INF, raptor, reconstruct_journey
from vlab.walk import WalkTable

LAT = [42.8] * 8
LON = [-1.65 + 0.001 * i for i in range(8)]


def foot(pairs: dict[tuple[int, int], int], n: int = 8) -> WalkTable:
    rows: list[tuple[list[int], list[int]]] = [([], []) for _ in range(n)]
    for (a, b), sec in pairs.items():
        rows[a][0].append(b)
        rows[a][1].append(sec)
    return WalkTable.from_rows(rows, n)  # type: ignore[arg-type]


def tt_of(*patterns: tuple[list[int], list[list[int]]]) -> Timetable:
    return synthetic_timetable(LON, LAT, [(s, a, None) for s, a in patterns])


def test_single_line_and_board_slack() -> None:
    tt = tt_of(([0, 1, 2], [[100, 200, 300], [400, 500, 600]]))
    r = raptor(tt, None, [0], 40, board_slack=60)
    assert r.arrival.tolist()[:3] == [40, 200, 300]
    r = raptor(tt, None, [0], 41, board_slack=60)  # 41 + 60 > 100: next trip
    assert r.arrival.tolist()[:3] == [41, 500, 600]
    r = raptor(tt, None, [0], 100, board_slack=0)  # boarding at the departure second
    assert r.arrival[2] == 300
    assert r.arrival[3] == INF  # stop 3 is not served


def test_transfer_same_stop_needs_slack() -> None:
    tt = tt_of(([0, 1], [[0, 100]]), ([1, 2], [[150, 250], [300, 400]]))
    assert raptor(tt, None, [0], 0, board_slack=0).arrival[2] == 250
    # slack applies to every boarding, the first one included
    assert raptor(tt, None, [0], 0, board_slack=50).arrival[2] == INF
    assert raptor(tt, None, [0], -50, board_slack=50).arrival[2] == 250  # 100+50 <= 150
    assert raptor(tt, None, [0], -51, board_slack=51).arrival[2] == 400


def test_round_limit() -> None:
    tt = tt_of(([0, 1], [[0, 100]]), ([1, 2], [[200, 300]]), ([2, 3], [[400, 500]]))
    assert raptor(tt, None, [0], 0, max_rounds=3, board_slack=0).arrival[3] == 500
    assert raptor(tt, None, [0], 0, max_rounds=2, board_slack=0).arrival[3] == INF
    r = raptor(tt, None, [0], 0, max_rounds=3, board_slack=0)
    assert r.rounds[:, 3].tolist() == [INF, INF, INF, 500]
    assert r.rounds[:, 2].tolist() == [INF, INF, 300, 300]


def test_footpaths_single_hop_and_after_ride_only() -> None:
    tt = tt_of(([0, 1], [[0, 100]]), ([2, 3], [[300, 400]]), ([4, 5], [[600, 700]]))
    # 1 -> 2 walk 120 s: transfer works
    tr = foot({(1, 2): 120})
    assert raptor(tt, tr, [0], -60, board_slack=60).arrival[3] == 400  # 220 + 60 <= 300
    assert raptor(tt, foot({(1, 2): 141}), [0], -60, board_slack=60).arrival[3] == INF
    # 1 -> 2 -> 4 chain of footpaths is not allowed (no transitive closure)
    tr2 = foot({(1, 2): 60, (2, 4): 60})
    r = raptor(tt, tr2, [0], 0, board_slack=0)
    assert r.arrival[2] == 160 and r.arrival[4] == INF
    # footpath right after the access walk only with foot_round0
    tr3 = foot({(0, 2): 60})
    assert raptor(tt, tr3, [0], 200, board_slack=0).arrival[3] == INF
    assert raptor(tt, tr3, [0], 200, board_slack=0, foot_round0=True).arrival[3] == 400


def test_footpath_from_ride_label_even_if_stop_reached_earlier_by_walking() -> None:
    # Stop 2 is reached early by a footpath (round 1); a later ride also reaches stop 2
    # (round 2) and only *that* ride arrival may start the footpath 2 -> 5.
    tt = tt_of(([0, 1], [[0, 10]]), ([1, 3], [[20, 30]]), ([3, 2], [[40, 50]]))
    tr = foot({(1, 2): 5, (2, 5): 30})
    r = raptor(tt, tr, [0], 0, board_slack=0)
    assert r.arrival[2] == 15  # walked from stop 1
    assert r.arrival[5] == 80  # ride 3 -> 2 at 50, then walk 30 s


def test_overtaking_express_is_used() -> None:
    # A slow trip departs at 0, an express departs at 60 and arrives first.
    tt = tt_of(([0, 1, 2], [[0, 600, 1200], [60, 300, 500]]))
    assert tt.n_patterns == 2  # FIFO split
    r = raptor(tt, None, [0], 0, board_slack=0)
    assert r.arrival[2] == 500
    assert raptor(tt, None, [0], 61, board_slack=0).arrival[2] == INF


def test_past_midnight() -> None:
    tt = tt_of(([0, 1], [[86700, 87300]]))  # 24:05 -> 24:15
    r = raptor(tt, None, [0], 86100)  # 23:55
    assert r.arrival[1] == 87300
    tt_prev = tt_of(([0, 1], [[-600, 300]]))  # carried over from the previous day
    assert raptor(tt_prev, None, [0], -700, board_slack=0).arrival[1] == 300


def test_multi_source_offsets_and_pruning() -> None:
    tt = tt_of(([0, 2], [[100, 500]]), ([1, 2], [[200, 400]]))
    r = raptor(tt, None, [0, 1], 0, [0, 150], board_slack=0)
    assert r.arrival[2] == 400
    r = raptor(tt, None, [0, 1], 0, [0, 250], board_slack=0)  # misses the 200 departure
    assert r.arrival[2] == 500
    r = raptor(tt, None, [0, 1], 0, [0, 250], board_slack=0, max_duration=450)
    assert r.arrival[2] == INF
    with pytest.raises(ValueError):
        raptor(tt, None, [0, 9], 0)


def test_loop_pattern_with_repeated_stop() -> None:
    # circular line 0 -> 1 -> 2 -> 0 -> 1
    tt = tt_of(([0, 1, 2, 0, 1], [[0, 100, 200, 300, 400]]))
    r = raptor(tt, None, [2], 150, board_slack=0)
    assert r.arrival[0] == 300 and r.arrival[1] == 400
    j = reconstruct_journey(tt, r, 1)
    assert j is not None and [leg.mode for leg in j] == ["access", "ride"]
    assert (j[1].board_pos, j[1].alight_pos) == (2, 4)


def test_journey_reconstruction_toy() -> None:
    tt = tt_of(([0, 1], [[0, 100]]), ([2, 3], [[300, 400]]))
    tr = foot({(1, 2): 120})
    r = raptor(tt, tr, [0], -30, [10], board_slack=0)
    legs = reconstruct_journey(tt, r, 3)
    assert legs is not None
    assert [(lg.mode, lg.from_stop, lg.to_stop, lg.depart, lg.arrive) for lg in legs] == [
        ("access", -1, 0, -30, -20),
        ("ride", 0, 1, 0, 100),
        ("walk", 1, 2, 100, 220),
        ("ride", 2, 3, 300, 400),
    ]
    assert reconstruct_journey(tt, r, 7) is None
    assert legs[1].duration == 100


def test_more_rounds_never_worse_and_slack_monotone() -> None:
    rng = np.random.default_rng(3)
    pats = []
    for _ in range(12):
        seq = rng.choice(8, size=4, replace=False).tolist()
        base = np.sort(rng.integers(0, 3000, size=3))
        pats.append((seq, [[int(b) + 120 * i for i in range(4)] for b in base]))
    tt = tt_of(*pats)
    tr = foot({(i, (i + 1) % 8): 90 for i in range(8)})
    for src in range(8):
        prev = None
        for k in range(1, 6):
            a = raptor(tt, tr, [src], 0, max_rounds=k).arrival.astype(np.int64)
            if prev is not None:
                assert np.all(a <= prev)
            prev = a
        loose = raptor(tt, tr, [src], 0, board_slack=0).arrival
        strict = raptor(tt, tr, [src], 0, board_slack=120).arrival
        assert np.all(loose <= strict)
