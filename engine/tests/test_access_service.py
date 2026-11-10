"""Accessibility service, isochrones and journeys on the real network."""

from __future__ import annotations

import numpy as np
import pytest
import shapely

from vlab.access import isochrone as iso
from vlab.access.journey import plan
from vlab.access.service import Evaluator, equity, subset_rows, summarise, travel_times
from vlab.model import Model, Window

CENTRE = (-1.6440, 42.8169)  # Plaza del Castillo
EDGE = (-1.6100, 42.8350)  # Sarriguren


def test_model_basics(model: Model) -> None:
    assert model.n_zones == len(model.zones) > 1500
    assert 350_000 < model.population.sum() < 390_000
    assert model.attraction.sum() == pytest.approx(1.0)
    assert set(model.category_zones) == set(model.categories)
    assert (model.direct_walk.diagonal() == 0).all()
    # income known for every populated zone
    assert np.isfinite(model.income[model.population > 0]).all()
    # few residents live beyond 1 km walk of any stop
    state = model.baseline("weekday")
    no_stop = np.diff(state.access.indptr) == 0
    assert model.population[no_stop].sum() < 0.03 * model.population.sum()


def test_window_validation() -> None:
    assert len(Window().departures()) == 6
    with pytest.raises(ValueError):
        Window(day="monday")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Window(duration=60)


def test_travel_times_are_bounded_by_walking(model: Model, evaluator: Evaluator) -> None:
    tt = evaluator.baseline_tt
    assert tt.shape == (model.n_zones, model.n_zones)
    walk = model.direct_walk
    both = (walk != 65535) & (tt != 65535)
    assert (tt[both] <= walk[both]).all()
    assert (tt[walk != 65535] != 65535).all()
    assert (tt.diagonal() == 0).all()


def test_subset_rows_matches_full_matrix(model: Model, evaluator: Evaluator) -> None:
    rows = np.array([10, 500, 1200, 1700], dtype=np.int64)
    state = model.baseline("weekday")
    sub = subset_rows(state.access, rows)
    for i, r in enumerate(rows):
        assert np.array_equal(sub.row(i)[0], state.access.row(int(r))[0])
    part = travel_times(model, state, evaluator.window, rows)
    assert np.array_equal(part, evaluator.baseline_tt[rows])


def test_baseline_summary_is_plausible(model: Model, evaluator: Evaluator) -> None:
    s = evaluator.baseline_summary
    cats = s.categories
    # nearly everyone has a health centre within 30 min; fewer reach a hospital
    assert cats["health_centre"].share_within > 0.95
    assert 0.5 < cats["hospital"].share_within < 0.9
    assert cats["hospital"].share_within < cats["health_centre"].share_within
    assert 15 * 60 < s.mean_travel_time < 45 * 60
    assert 0 < s.objective < 1
    assert 0 < s.underserved_population < model.population.sum()
    for ca in cats.values():
        shares = [v for _, v in ca.curve]
        assert shares == sorted(shares)
    # a longer threshold can only help
    wide = summarise(model, evaluator.baseline_tt, evaluator.demand, 2700)
    assert wide.underserved_population <= s.underserved_population
    assert (wide.jobs >= s.jobs).all()


def test_equity_groups(model: Model, evaluator: Evaluator) -> None:
    groups, ci = equity(model, evaluator.baseline_summary)
    assert [g.q for g in groups] == [1, 2, 3, 4, 5]
    assert sum(g.population for g in groups) == pytest.approx(model.population.sum(), rel=0.01)
    assert all(-1 <= v <= 1 for v in ci.values())
    assert all(0 <= g.share_within["hospital"] <= 1 for g in groups)


def test_sampled_evaluation_ranks_like_the_exact_one(model: Model, evaluator: Evaluator) -> None:
    from vlab.scenario import apply, parse_edits

    origins = evaluator.sample_origins(300, seed=1)
    assert len(origins) == 300 and (model.population[origins] > 0).all()
    base_obj, base_t = evaluator.evaluate_sampled(evaluator.baseline_state, origins)
    cut = apply(model, "weekday", parse_edits([{"type": "remove_route", "route_id": "4"}])).state
    cut_obj, cut_t = evaluator.evaluate_sampled(cut, origins)
    assert cut_obj < base_obj and cut_t > base_t
    exact = evaluator.baseline_summary
    assert base_t == pytest.approx(exact.mean_travel_time, rel=0.15)


# ----------------------------------------------------------------------- isochrones


@pytest.mark.parametrize("origin", [CENTRE, EDGE])
def test_isochrones_are_nested_valid_and_bigger_by_bus(model: Model, origin: tuple) -> None:
    state = model.baseline("weekday")
    cutoffs = [900, 1800, 2700]
    transit = iso.time_field(model, state, origin, Window(), 2700, "transit")
    walk = iso.time_field(model, state, origin, Window(), 2700, "walk")
    assert (transit.node_time <= walk.node_time + 1e-3).all()
    pt, pw = iso.polygons(model, transit, cutoffs), iso.polygons(model, walk, cutoffs)
    areas = [iso.area_km2(pt[c]) for c in cutoffs]
    assert areas == sorted(areas) and areas[0] > 0.5
    for c in cutoffs:
        assert pt[c].is_valid and not pt[c].is_empty
        assert pt[c].contains(shapely.Point(origin))
        assert iso.area_km2(pt[c]) >= 0.95 * iso.area_km2(pw[c])
    assert pt[1800].buffer(1e-6).contains(pt[900])
    assert pt[2700].buffer(1e-6).contains(pt[1800])
    assert iso.area_km2(pt[2700]) > 1.3 * iso.area_km2(pw[2700])
    # walking 15 min at 4.5 km/h cannot cover more than a 1.125 km disc
    assert iso.area_km2(pw[900]) < np.pi * 1.2**2
    zt = iso.point_times(model, transit, "zones")
    assert model.population[zt <= 2700].sum() > model.population[zt <= 900].sum() > 0


def test_isochrone_far_from_streets_fails(model: Model) -> None:
    with pytest.raises(ValueError, match="street network"):
        iso.time_field(model, model.baseline("weekday"), (-1.95, 42.99), Window(), 1800)


# ------------------------------------------------------------------------- journeys


def test_journey_by_bus(model: Model) -> None:
    j = plan(model, model.baseline("weekday"), EDGE, (-1.6630, 42.8050), 8 * 3600)
    assert j is not None and j.depart == 8 * 3600
    assert any(g.mode == "bus" for g in j.legs)
    assert 15 * 60 < j.duration < 75 * 60
    for a, b in zip(j.legs[:-1], j.legs[1:], strict=True):
        assert a.arrive <= b.depart
    assert j.legs[0].start == EDGE and j.legs[-1].arrive == j.arrive
    assert all(len(g.path) >= 2 for g in j.legs)


def test_short_journey_is_walked(model: Model) -> None:
    j = plan(model, model.baseline("weekday"), CENTRE, (-1.6460, 42.8180), 8 * 3600)
    assert j is not None and [g.mode for g in j.legs] == ["walk"] and j.duration < 600


def test_journey_unreachable(model: Model) -> None:
    assert plan(model, model.baseline("weekday"), CENTRE, (-1.95, 42.99), 8 * 3600) is None
