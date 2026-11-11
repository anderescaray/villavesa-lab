"""Frequency reallocation as a multiple-choice knapsack (MILP).

For every eligible line we choose one frequency factor from a discrete menu.
The benefit of a factor is approximated as separable across lines and follows
the waiting-time law: accessibility gains scale with ``1 - 1/f`` (half the
headway is the expected wait), calibrated per line with two measured
evaluations (``f = 0.5`` and ``f = 1.5``) on a sample of origins. The resource
used by a factor (buses or bus-hours) is *measured* by applying the edit to the
timetable. The MILP is solved exactly with CP-SAT; the optimizer then verifies
the combined plan with the real router and repairs it by local search, which
accounts for the interactions the separable model ignores.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from ortools.sat.python import cp_model

FACTORS: tuple[float, ...] = (0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0)
PROBE_DOWN = 0.5
PROBE_UP = 1.5
MIN_HEADWAY_S = 180.0
MAX_HEADWAY_S = 3600.0
_SCALE = 10_000_000  # objective scaling to integers for CP-SAT
_COST_SCALE = 100


@dataclass(frozen=True)
class LineOption:
    """Menu of one line: for each allowed factor, its benefit and resource use."""

    route_id: str
    factors: tuple[float, ...]
    benefit: tuple[float, ...]  # change of the score vs factor 1.0 (separable estimate)
    cost: tuple[float, ...]  # change of the budgeted resource vs factor 1.0
    headway_s: float  # current mean headway


def wait_law_benefit(factor: float, d_down: float, d_up: float) -> float:
    """Benefit of ``factor`` from the two probes (``d_down`` at 0.5, ``d_up`` at 1.5)."""
    if factor == 1.0:
        return 0.0
    if factor < 1.0:
        return min(d_down, 0.0) * (1.0 / factor - 1.0) / (1.0 / PROBE_DOWN - 1.0)
    return max(d_up, 0.0) * (1.0 - 1.0 / factor) / (1.0 - 1.0 / PROBE_UP)


def allowed_factors(headway_s: float) -> tuple[float, ...]:
    return tuple(f for f in FACTORS if f == 1.0 or MIN_HEADWAY_S <= headway_s / f <= MAX_HEADWAY_S)


def solve_knapsack(
    options: list[LineOption], budget_delta: float, time_limit_s: float = 5.0
) -> tuple[dict[str, float], float]:
    """Pick one factor per line maximising total benefit with
    ``sum(cost) <= budget_delta``. Returns ``({route_id: factor}, predicted benefit)``.

    Always feasible when ``budget_delta >= sum(min cost)``; otherwise every line
    takes its cheapest option.
    """
    if not options:
        return {}, 0.0
    floor = sum(min(o.cost) for o in options)
    if budget_delta < floor:
        pick = {o.route_id: o.factors[int(np.argmin(o.cost))] for o in options}
        return pick, sum(o.benefit[int(np.argmin(o.cost))] for o in options)
    model = cp_model.CpModel()
    x: list[list[cp_model.IntVar]] = []
    for i, o in enumerate(options):
        row = [model.new_bool_var(f"x_{i}_{k}") for k in range(len(o.factors))]
        model.add_exactly_one(row)
        x.append(row)
    model.add(
        sum(
            round(c * _COST_SCALE) * x[i][k]
            for i, o in enumerate(options)
            for k, c in enumerate(o.cost)
        )
        <= int(np.floor(budget_delta * _COST_SCALE + 1e-6))
    )
    model.maximize(
        sum(
            round(b * _SCALE) * x[i][k]
            for i, o in enumerate(options)
            for k, b in enumerate(o.benefit)
        )
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_workers = 1
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):  # pragma: no cover - defensive
        return {o.route_id: 1.0 for o in options}, 0.0
    chosen: dict[str, float] = {}
    total = 0.0
    for i, o in enumerate(options):
        for k, f in enumerate(o.factors):
            if solver.value(x[i][k]):
                chosen[o.route_id] = f
                total += o.benefit[k]
    return chosen, total
