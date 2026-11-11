"""Tests for accessibility metrics and the gravity demand model."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from vlab.access import metrics as m
from vlab.demand import build_gravity_demand, decay

U = 65535


def tt_matrix() -> np.ndarray:
    return np.array(
        [[0, 600, 1800, U], [600, 0, 1200, U], [1800, 1200, 0, 900], [U, U, 900, 0]],
        dtype=np.uint16,
    )


def test_nearest_time_and_category_access() -> None:
    tt = tt_matrix()
    pop = np.array([100.0, 200.0, 300.0, 400.0])
    ca = m.category_access("hospital", tt, pop, np.array([1, 1]), threshold_s=900)
    assert ca.time.tolist() == [600, 0, 1200, U]
    assert ca.pop_within == 300.0
    assert ca.share_within == pytest.approx(0.3)
    assert ca.n_pois == 1
    # mean over those who can reach: (100*600 + 0 + 300*1200) / 600
    assert ca.mean_time == pytest.approx(700.0)
    # 40% of residents cannot reach -> the median resident is in zone 2
    assert ca.median_time == 1200.0
    assert ca.curve[0] == (300, pytest.approx(0.2))
    assert ca.curve[-1] == (3600, pytest.approx(0.6))
    shares = [s for _, s in ca.curve]
    assert shares == sorted(shares)


def test_category_without_destinations_is_unreachable() -> None:
    ca = m.category_access("x", tt_matrix(), np.ones(4), np.array([], dtype=np.int64), 1800)
    assert (ca.time == U).all()
    assert ca.pop_within == 0.0
    assert np.isinf(ca.median_time)
    assert np.isnan(ca.mean_time)


def test_cumulative_and_gravity_accessibility_bounds() -> None:
    tt = tt_matrix()
    a = np.array([1.0, 1.0, 2.0, 0.0])
    cum = m.cumulative_opportunities(tt, a, 1200)
    assert cum.tolist() == pytest.approx([0.5, 1.0, 0.75, 0.5])
    g = m.gravity_accessibility(tt, a, 0.07)
    assert ((g >= 0) & (g <= 1)).all()
    faster = tt.copy()
    faster[0, 2] = 600
    assert m.gravity_accessibility(faster, a)[0] > g[0]


def test_decay_unreachable_is_zero() -> None:
    d = decay(tt_matrix(), 0.07)
    assert d[0, 3] == 0.0
    assert d[0, 0] == 1.0
    assert d[0, 1] == pytest.approx(np.exp(-0.7), rel=1e-5)


def test_gravity_demand_conserves_population() -> None:
    tt = tt_matrix()
    pop = np.array([100.0, 200.0, 300.0, 400.0])
    att = np.array([5.0, 1.0, 1.0, 1.0])
    dem = build_gravity_demand(pop, att, tt)
    assert dem.weights.sum(axis=1) == pytest.approx(pop, rel=1e-5)
    assert np.diag(dem.weights).sum() == 0.0
    assert dem.weights[0, 3] == 0.0
    # closer and more attractive destinations draw more
    assert dem.weights[2, 3] > dem.weights[2, 1]
    base = dem.mean_travel_time(tt)
    worse = tt.copy()
    worse[2, 3] = U
    assert dem.mean_travel_time(worse) > base
    assert dem.zone_mean_travel_time(tt).shape == (4,)


def test_gravity_demand_validates_shapes() -> None:
    with pytest.raises(ValueError):
        build_gravity_demand(np.ones(3), np.ones(4), tt_matrix())
    with pytest.raises(ValueError):
        build_gravity_demand(-np.ones(4), np.ones(4), tt_matrix())


def test_weighted_quantile() -> None:
    v = np.array([1.0, 2.0, 3.0, np.nan])
    w = np.array([1.0, 1.0, 2.0, 5.0])
    assert m.weighted_quantile(v, w, 0.5) == 2.0
    assert m.weighted_quantile(v, w, 0.9) == 3.0
    assert np.isnan(m.weighted_quantile(v, np.zeros(4), 0.5))


def test_income_groups_are_balanced_and_ordered() -> None:
    rng = np.random.default_rng(0)
    income = rng.uniform(8000, 30000, 500)
    income[:20] = np.nan
    pop = rng.uniform(0, 300, 500)
    groups = m.income_quantile_groups(income, pop, 5)
    assert [g.q for g in groups] == [1, 2, 3, 4, 5]
    total = pop[20:].sum()
    for g in groups:
        assert g.population == pytest.approx(total / 5, rel=0.05)
        assert not g.zone_mask[:20].any()
    for a, b in itertools.pairwise(groups):
        assert a.income_max <= b.income_min
    assert (
        sum(g.zone_mask.sum() for g in groups) == np.isfinite(income).sum() - (pop[20:] <= 0).sum()
    )


def test_concentration_index_sign() -> None:
    income = np.arange(1.0, 101.0)
    pop = np.ones(100)
    assert m.concentration_index(income, income, pop) > 0.3
    assert m.concentration_index(income[::-1].copy(), income, pop) < -0.3
    assert m.concentration_index(np.ones(100), income, pop) == pytest.approx(0.0, abs=1e-12)


def test_people_gaining_losing() -> None:
    pop = np.array([10.0, 20.0, 30.0, 40.0])
    base = {"hospital": np.array([2000, 1000, 1000, U], dtype=np.uint16)}
    scen = {"hospital": np.array([1500, 2500, 1000, U], dtype=np.uint16)}
    base_mean = np.array([1000.0, 1000.0, 1000.0, 1000.0])
    scen_mean = np.array([1000.0, 1000.0, 900.0, 1030.0])
    gain, lose = m.people_gaining_losing(base, scen, base_mean, scen_mean, pop, 1800, ["hospital"])
    assert gain == 10.0 + 30.0  # zone 0 crosses the threshold, zone 2 is > 60 s faster
    assert lose == 20.0  # zone 1 loses the hospital; zone 3 changes by < 60 s
