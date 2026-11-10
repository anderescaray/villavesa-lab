"""Batched RAPTOR and the door-to-door travel-time matrix kernel."""

from __future__ import annotations

import numpy as np
import pytest

from vlab.gtfs import Timetable, synthetic_timetable
from vlab.raptor import (
    INF,
    UNREACHABLE_U16,
    departure_samples,
    raptor,
    raptor_batch,
    travel_time_matrix,
)
from vlab.walk import WalkTable, euclidean_table


def _brute_matrix(
    tt: Timetable,
    tr: WalkTable,
    acc: WalkTable,
    egr: WalkTable,
    deps: np.ndarray,
    direct: np.ndarray | None,
    cap: int,
    min_reach: int,
) -> np.ndarray:
    eg = egr.to_dense(fill=-1).astype(np.int64)  # [S, D]
    n_o, n_d = acc.n_rows, egr.n_cols
    out = np.empty((n_o, n_d), np.int64)
    for o in range(n_o):
        samples = []
        for t0 in deps:
            stops, secs = acc.row(o)
            arr = raptor(tt, tr, stops, int(t0), secs).arrival.astype(np.int64)
            best = np.full(n_d, cap + 1, np.int64)
            for s in np.flatnonzero(arr < INF):
                el = arr[s] - t0
                if el > cap:
                    continue
                ok = eg[s] >= 0
                best[ok] = np.minimum(best[ok], el + eg[s, ok])
            if direct is not None:
                best = np.minimum(best, direct[o].astype(np.int64))
            samples.append(best)
        smp = np.vstack(samples)
        reach = smp <= cap
        val = np.where(reach, smp, cap).sum(axis=0)
        mean = (val + len(deps) // 2) // len(deps)
        out[o] = np.where(reach.sum(axis=0) >= min_reach, mean, UNREACHABLE_U16)
    return out


@pytest.fixture(scope="module")
def zones(tt_weekday: Timetable) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    n = 40
    lon = rng.uniform(tt_weekday.stop_lon.min(), tt_weekday.stop_lon.max(), n)
    lat = rng.uniform(tt_weekday.stop_lat.min(), tt_weekday.stop_lat.max(), n)
    return lon, lat


def test_matrix_matches_brute_force(
    tt_weekday: Timetable, transfers_weekday: WalkTable, zones: tuple[np.ndarray, np.ndarray]
) -> None:
    stops = (tt_weekday.stop_lon, tt_weekday.stop_lat)
    acc = euclidean_table(zones, stops, 1000.0)
    egr = acc.transpose()
    deps = departure_samples(8 * 3600, 3600, 900)
    direct = euclidean_table(zones, zones, 2000.0).to_dense(fill=UNREACHABLE_U16)
    direct = direct.astype(np.uint16)
    for cap, frac, dw in ((5400, 0.5, None), (3600, 1.0, direct), (2700, 0.25, direct)):
        m = travel_time_matrix(
            tt_weekday, transfers_weekday, acc, egr, deps, dw, cap=cap, min_reachable_frac=frac
        )
        assert m.dtype == np.uint16 and m.shape == (40, 40)
        min_reach = max(1, int(np.ceil(frac * len(deps))))
        ref = _brute_matrix(tt_weekday, transfers_weekday, acc, egr, deps, dw, cap, min_reach)
        np.testing.assert_array_equal(m.astype(np.int64), ref)
        if dw is not None:
            assert np.all(np.diag(m) == 0)
        assert (m < UNREACHABLE_U16).mean() > 0.1


def test_censored_mean_semantics() -> None:
    # One trip at 100 -> 300: reachable only for the departure at t=0, not at t=200.
    tt = synthetic_timetable([-1.65, -1.64], [42.8, 42.8], [([0, 1], [[100, 300]], None)])
    acc = WalkTable.from_rows([([0], [0])], 2)
    egr = WalkTable.from_rows([([], []), ([0], [0])], 1)
    deps = np.array([0, 200])
    half = travel_time_matrix(tt, None, acc, egr, deps, board_slack=0, cap=1000)
    assert half[0, 0] == (300 + 1000) // 2  # unreachable sample counted as cap
    full = travel_time_matrix(
        tt, None, acc, egr, deps, board_slack=0, cap=1000, min_reachable_frac=1.0
    )
    assert full[0, 0] == UNREACHABLE_U16
    tight = travel_time_matrix(tt, None, acc, egr, deps[:1], board_slack=0, cap=299)
    assert tight[0, 0] == UNREACHABLE_U16  # 300 s > cap
    direct = np.array([[400]], np.uint16)
    walk = travel_time_matrix(tt, None, acc, egr, deps, direct, board_slack=0, cap=1000)
    assert walk[0, 0] == (300 + 400) // 2  # per-sample min with walking
    with pytest.raises(ValueError):
        travel_time_matrix(tt, None, acc, egr, deps, cap=70000)
    with pytest.raises(ValueError):
        travel_time_matrix(tt, None, acc, egr, deps, np.zeros((2, 2), np.uint16))


def test_batch_matches_single_queries(
    tt_weekday: Timetable, transfers_weekday: WalkTable, zones: tuple[np.ndarray, np.ndarray]
) -> None:
    acc = euclidean_table(zones, (tt_weekday.stop_lon, tt_weekday.stop_lat), 800.0)
    deps = np.array([7 * 3600, 8 * 3600 + 123])
    out = raptor_batch(tt_weekday, transfers_weekday, acc, deps, max_duration=3 * 3600)
    assert out.shape == (40, 2, tt_weekday.n_stops)
    for o in range(0, 40, 7):
        for d, t0 in enumerate(deps):
            s, sec = acc.row(o)
            r = raptor(tt_weekday, transfers_weekday, s, int(t0), sec, max_duration=3 * 3600)
            np.testing.assert_array_equal(out[o, d], r.arrival)
