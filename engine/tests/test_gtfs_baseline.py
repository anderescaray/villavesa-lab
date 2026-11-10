"""Baseline sanity checks of the timetable against reality (numbers in docs/router.md)."""

from __future__ import annotations

import numpy as np
import pytest

from vlab.gtfs import (
    Feed,
    Timetable,
    build_timetable,
    network_speed_kmh,
    pattern_stats,
    representative_dates,
    route_stats,
    vehicles_in_service,
    with_patterns_removed,
)
from vlab.raptor import raptor


def test_commercial_speed_plausible(tt_weekday: Timetable) -> None:
    # TUC reports an average commercial speed of about 13 km/h. The feed gives
    # Σ shape-km / Σ scheduled run hours over day lines (terminal layovers excluded).
    v = network_speed_kmh(tt_weekday)
    assert 11.0 <= v <= 14.5, v
    rs = route_stats(tt_weekday)
    day = rs[rs["kind"] == "day"]
    assert day["speed_kmh"].between(8.0, 20.0).all()
    assert len(day) >= 23


def test_peak_vehicles_plausible(tt_weekday: Timetable) -> None:
    # TUC operates roughly 140-160 buses; trips in motion at the AM peak are a lower
    # bound (layovers and spares excluded).
    t = np.arange(7 * 3600, 9 * 3600 + 1, 60)
    v = vehicles_in_service(tt_weekday, t)
    assert 120 <= v.max() <= 170, v.max()
    assert vehicles_in_service(tt_weekday, [3 * 3600])[0] == 0


def test_trips_per_day_type(feed: Feed) -> None:
    rep = representative_dates(feed)
    own = {}
    for kind, d in rep.items():
        tt = build_timetable(feed, d)
        own[kind] = int((~tt.trip_prev_day).sum())
    assert own == {"weekday": 3084, "saturday": 2700, "sunday": 1763}


def test_raptor_reproduces_scheduled_run_times(tt_weekday: Timetable) -> None:
    """A query along a single line (only that pattern in the timetable) arrives exactly
    when the scheduled trip does: in-vehicle time = scheduled run time."""
    tt = tt_weekday
    ps = pattern_stats(tt)
    busiest = ps.sort_values("trips", ascending=False).groupby("route_id").head(1)
    rng = np.random.default_rng(0)
    for p in busiest["pattern"].astype(int):
        only = with_patterns_removed(tt, [q.key for i, q in enumerate(tt.patterns) if i != p])
        seq = only.pattern_stop_seq(0)
        arr, dep = only.arrivals(0), only.departures(0)
        trip = int(rng.integers(0, arr.shape[0]))
        r = raptor(only, None, [int(seq[0])], int(dep[trip, 0]) - 60, max_rounds=1)
        for i in range(1, len(seq)):
            if np.count_nonzero(seq == seq[i]) > 1:
                continue  # loop lines revisit stops; skip ambiguous ones
            assert r.arrival[seq[i]] == arr[trip, i]
        run = int(arr[trip, -1] - dep[trip, 0])
        assert 60 <= run <= 2.5 * 3600


def test_line_stats_consistent(tt_weekday: Timetable) -> None:
    rs = route_stats(tt_weekday).set_index("short_name")
    l4 = rs.loc["L04"]  # trunk line Barañáin - Villava, the busiest
    assert l4["trips"] == rs["trips"].max()
    assert l4["headway_peak"] <= 600
    assert 8.0 <= l4["length_km"] <= 20.0
    assert rs["first_dep"].min() >= 5 * 3600
    ps = pattern_stats(tt_weekday)
    assert ps["trips"].sum() == 3084
    assert (ps["length_km"] > 0).all()
    assert ps.loc[ps["trips"] >= 2, "headway_all"].notna().all()
    assert pytest.approx(ps["service_km"].sum(), rel=1e-9) == rs["service_km"].sum()
