"""Cost model: fleet, bus-hours, km and money."""

from __future__ import annotations

import numpy as np
import pytest

from vlab.cost import CostParams, annual_cost, cycle_fleet, layover_s, network_cost
from vlab.gtfs import RunningProfile, Timetable, synthesize_trips, synthetic_timetable
from vlab.model import DAY_TYPES, Model


def _line(headway: int, run: int = 2400, n_stops: int = 5) -> Timetable:
    """A regular two-way line: both directions depart every ``headway`` for 6 hours."""
    offsets = np.linspace(0, run, n_stops).astype(np.int32)
    prof = RunningProfile.constant(offsets)
    arr, dep = synthesize_trips(prof, 6 * 3600, 12 * 3600, headway)
    lon = -1.65 + 0.005 * np.arange(n_stops)
    lat = np.full(n_stops, 42.81)
    return synthetic_timetable(
        lon,
        lat,
        [(list(range(n_stops)), arr, dep), (list(range(n_stops))[::-1], arr, dep)],
        route_of_pattern=[0, 0],
    )


def test_layover_rule() -> None:
    p = CostParams()
    assert layover_s(600, p) == p.layover_min_s
    assert layover_s(6000, p) == 600


@pytest.mark.parametrize("headway", [300, 600, 900, 1200])
def test_fleet_matches_cycle_time_over_headway(headway: int) -> None:
    tt = _line(headway)
    cost = network_cost(tt)
    # two directions, each needs ceil((run + layover) / headway) buses
    assert cost.fleet == 2 * cycle_fleet(2400, headway)
    n_trips = 2 * (6 * 3600 // headway + 1)
    assert cost.trips == n_trips
    assert cost.bus_hours == pytest.approx(n_trips * 2400 / 3600)


def test_cost_is_linear_in_hours_and_km() -> None:
    tt = _line(600)
    p = CostParams()
    cost = network_cost(tt, p)
    assert cost.cost_eur == pytest.approx(
        p.eur_per_bus_hour * cost.bus_hours + p.eur_per_km * cost.km
    )
    double = network_cost(tt, CostParams(eur_per_bus_hour=2 * p.eur_per_bus_hour, eur_per_km=0))
    assert double.cost_eur == pytest.approx(2 * p.eur_per_bus_hour * cost.bus_hours)


def test_baseline_matches_reported_reality(model: Model) -> None:
    """Sourced 2023 actuals (docs/reference_facts.md): 159 buses, 624,817 service
    hours, 7,985,316 km. The 2026 feed should be the same order of magnitude."""
    by = {d: network_cost(model.baseline(d).timetable, model.cost_params) for d in DAY_TYPES}
    assert 140 <= by["weekday"].fleet <= 185
    assert by["weekday"].fleet > by["saturday"].fleet > by["sunday"].fleet
    year = annual_cost(by, model.cost_params)
    assert 0.9 < year["bus_hours"] / 624_817 < 1.25
    assert 0.9 < year["km"] / 7_985_316 < 1.25
    assert 30e6 < year["operating_eur"] < 48e6
    assert year["total_eur"] == pytest.approx(year["operating_eur"] + year["capital_eur"])
    # the network fleet is the peak of the summed curve, never above the sum of peaks
    assert by["weekday"].fleet <= sum(r.fleet for r in by["weekday"].routes.values())
    assert by["weekday"].in_use_at(8 * 3600) > by["weekday"].in_use_at(4 * 3600)


def test_annual_cost_requires_all_day_types(model: Model) -> None:
    c = network_cost(model.baseline("weekday").timetable)
    with pytest.raises(ValueError):
        annual_cost({"weekday": c})
