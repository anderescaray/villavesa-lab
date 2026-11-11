"""Optimizer: knapsack model, candidates and end-to-end behaviour."""

from __future__ import annotations

import itertools

import pytest

from vlab.access.service import Evaluator
from vlab.model import Model
from vlab.optimize import Budget, Optimizer, Progress
from vlab.optimize import frequency as fq
from vlab.optimize.lines import generate_candidates, pick_hubs
from vlab.scenario import apply


def test_wait_law_is_anchored_on_the_probes_and_concave() -> None:
    assert fq.wait_law_benefit(1.0, -2.0, 1.0) == 0.0
    assert fq.wait_law_benefit(fq.PROBE_DOWN, -2.0, 1.0) == pytest.approx(-2.0)
    assert fq.wait_law_benefit(fq.PROBE_UP, -2.0, 1.0) == pytest.approx(1.0)
    ups = [fq.wait_law_benefit(f, -2.0, 1.0) for f in (1.25, 1.5, 2.0)]
    assert ups == sorted(ups)
    assert ups[1] - ups[0] > ups[2] - ups[1] - 1e-12 or ups[2] - ups[1] < 2 * (ups[1] - ups[0])
    # noisy probes with the wrong sign are clamped: more service never predicts a loss
    assert fq.wait_law_benefit(2.0, 0.5, -0.5) == 0.0
    assert fq.wait_law_benefit(0.5, 0.5, -0.5) == 0.0


def test_allowed_factors_respect_headway_bounds() -> None:
    assert 2.0 not in fq.allowed_factors(300.0)  # would be 2.5 min
    assert 0.5 not in fq.allowed_factors(2400.0)  # would be 80 min
    assert 1.0 in fq.allowed_factors(10.0)


def _brute(options: list[fq.LineOption], budget: float) -> float:
    best = float("-inf")
    for combo in itertools.product(*(range(len(o.factors)) for o in options)):
        cost = sum(o.cost[k] for o, k in zip(options, combo, strict=True))
        if cost <= budget + 1e-9:
            best = max(best, sum(o.benefit[k] for o, k in zip(options, combo, strict=True)))
    return best


def test_knapsack_matches_brute_force() -> None:
    opts = [
        fq.LineOption("a", (0.5, 1.0, 1.5, 2.0), (-0.004, 0.0, 0.002, 0.003), (-4, 0, 3, 6), 600),
        fq.LineOption("b", (0.5, 1.0, 1.5), (-0.001, 0.0, 0.0005), (-3, 0, 2), 900),
        fq.LineOption(
            "c", (0.67, 1.0, 1.5, 2.0), (-0.0002, 0.0, 0.003, 0.0045), (-1, 0, 2, 5), 1200
        ),
        fq.LineOption("d", (0.5, 1.0), (-0.0001, 0.0), (-5, 0), 1800),
    ]
    for budget in (-13, -4, 0, 3, 7, 100):
        plan, total = fq.solve_knapsack(opts, budget)
        assert total == pytest.approx(_brute(opts, budget), abs=1e-9)
        cost = sum(o.cost[o.factors.index(plan[o.route_id])] for o in opts)
        assert cost <= budget + 1e-9
    # impossible budget: everything takes its cheapest option
    plan, _ = fq.solve_knapsack(opts, -1000)
    assert plan == {"a": 0.5, "b": 0.5, "c": 0.67, "d": 0.5}
    assert fq.solve_knapsack([], 0) == ({}, 0.0)


def test_line_candidates_follow_streets_and_serve_existing_stops(
    model: Model, evaluator: Evaluator
) -> None:
    state = evaluator.baseline_state
    hubs = pick_hubs(model, state)
    assert 10 <= len(hubs) <= 28 and len(set(hubs.tolist())) == len(hubs)
    cands = generate_candidates(model, state, evaluator.baseline_tt, evaluator.demand.weights, 8)
    assert cands
    tt = state.timetable
    for c in cands:
        assert len(c.stop_ids) >= 4 and all(s in tt.stop_index for s in c.stop_ids)
        assert len(set(c.stop_ids)) == len(c.stop_ids)
        assert 2000 < c.length_m < 15_000 and c.score > 0
    assert [c.score for c in cands] == sorted((c.score for c in cands), reverse=True)


@pytest.fixture(scope="module")
def frequency_result(model: Model, evaluator: Evaluator):  # type: ignore[no-untyped-def]
    progress = Progress()
    opt = Optimizer(model, evaluator, progress=progress, seed=0)
    return opt, opt.run(Budget("fleet", None), ("frequency",), time_limit_s=35), progress


def test_frequency_optimisation_improves_within_the_same_fleet(frequency_result) -> None:  # type: ignore[no-untyped-def]
    _, res, progress = frequency_result
    assert res.used <= res.budget == res.baseline.cost.fleet
    assert res.optimized.objective > 1.005 * res.baseline.objective
    assert res.optimized.mean_travel_time < res.baseline.mean_travel_time
    assert progress.progress == 1.0 and progress.stage == "done" and progress.log
    ups = [e for e in res.explanation if e.text_key == "frequency_up"]
    downs = [e for e in res.explanation if e.text_key == "frequency_down"]
    assert ups and downs  # a reallocation: some lines pay for others
    assert all(e.params["resource_delta"] <= 0 for e in downs)  # a cut never costs buses
    assert all(e["type"] == "scale_frequency" for e in res.scenario)


def test_result_is_reproducible_from_its_edits(
    model: Model, evaluator: Evaluator, frequency_result
) -> None:  # type: ignore[no-untyped-def]
    _, res, _ = frequency_result
    again = evaluator.evaluate(apply(model, "weekday", res.edits).state)
    assert again.objective == pytest.approx(res.optimized.objective)
    assert again.cost.fleet == res.optimized.cost.fleet


def test_smaller_budget_is_respected(model: Model, evaluator: Evaluator) -> None:
    opt = Optimizer(model, evaluator, seed=1)
    base = opt.baseline_cost.fleet
    res = opt.run(Budget("fleet", base - 15), ("frequency",), time_limit_s=20)
    assert res.used <= base - 15
    hours = Optimizer(model, evaluator, seed=1).run(
        Budget("bus_hours", 0.95 * opt.baseline_cost.bus_hours), ("frequency",), time_limit_s=20
    )
    assert hours.used <= 0.95 * opt.baseline_cost.bus_hours + 1e-6


def test_stop_candidates_are_closely_spaced_non_terminals(
    model: Model, evaluator: Evaluator
) -> None:
    opt = Optimizer(model, evaluator)
    cands = opt.stop_candidates()
    assert 0 < len(cands) <= 24
    tt = evaluator.baseline_state.timetable
    assert all(s in tt.stop_index for s in cands)
