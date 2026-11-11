"""Optimizer orchestration.

"Given N buses (or X bus-hours), maximise population-weighted accessibility."

Pipeline (each stage is optional, see ``moves``):

1. **stops** - greedy stop consolidation: closely spaced stops with a small
   catchment are removed when the measured effect on the score is positive
   (through riders save time, a few residents walk further).
2. **frequency** - probe every line (two sampled evaluations), build the
   separable waiting-time model, solve the multiple-choice knapsack exactly
   (CP-SAT), verify the budget on the real timetable and repair/improve by
   pairwise local search with the real router.
3. **new_lines** - ALNS over a pool of street-following candidate lines built
   from unmet demand. Whatever a set of new lines costs is paid for by
   re-solving the frequency knapsack with the remaining budget, so every
   solution visited respects the budget.

All inner-loop evaluations use the same population-weighted sample of origin
zones; the final proposal is re-evaluated exactly on every zone.
"""

from __future__ import annotations

import contextlib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from vlab.access.service import EvalResult, Evaluator
from vlab.cost.model import NetworkCost, network_cost
from vlab.gtfs.stats import mean_headways
from vlab.model.world import Model, NetworkState
from vlab.optimize import frequency as fq
from vlab.optimize.lines import LineCandidate, generate_candidates
from vlab.scenario import Edit, ScenarioError, apply, edit_to_dict, parse_edits, scenario_hash

BudgetKind = Literal["fleet", "bus_hours"]
Objective = Literal["accessibility", "travel_time"]
Move = Literal["frequency", "stops", "new_lines"]

SAMPLE_ORIGINS = 350
MIN_TRIPS_ELIGIBLE = 20
MAX_STOP_CANDIDATES = 24
MAX_STOPS_REMOVED = 10
#: A stop is a consolidation candidate when, after removing it, its neighbours on the
#: line are still closer than this, and another stop is within STOP_NEIGHBOUR_S of walking.
STOP_MAX_GAP_M = 450.0
STOP_NEIGHBOUR_S = 200
LINE_HEADWAYS: tuple[int, ...] = (600, 900, 1200)
MAX_NEW_LINES = 3
NEW_LINE_COLORS: tuple[str, ...] = ("#1F6FEB", "#0E9F6E", "#8250DF")


@dataclass(frozen=True)
class Budget:
    kind: BudgetKind = "fleet"
    value: float | None = None  # None: same as the baseline


@dataclass(frozen=True)
class Explanation:
    kind: str  # "frequency" | "stop" | "new_line"
    text_key: str
    params: dict[str, Any]
    delta_objective: float
    route_id: str | None = None


@dataclass(frozen=True)
class TradeoffPoint:
    budget: float
    used: float
    objective: float
    mean_travel_time: float
    share_within: dict[str, float]
    scenario: list[dict[str, Any]]


@dataclass(frozen=True, eq=False)
class OptimizeResult:
    edits: tuple[Edit, ...]
    scenario: list[dict[str, Any]]
    baseline: EvalResult
    optimized: EvalResult
    budget_kind: str
    budget: float
    used: float
    explanation: list[Explanation]
    history: list[dict[str, float]]
    elapsed_s: float


@dataclass
class Progress:
    """Mutable progress record shared with the caller (e.g. the API job)."""

    progress: float = 0.0
    stage: str = "queued"
    log: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, float]] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)

    def say(self, msg: str) -> None:
        self.log.append({"t": round(time.perf_counter() - self.started, 1), "msg": msg})

    def at(self, progress: float, stage: str | None = None) -> None:
        self.progress = max(self.progress, min(progress, 0.999))
        if stage:
            self.stage = stage


class Optimizer:
    def __init__(
        self,
        model: Model,
        evaluator: Evaluator,
        *,
        base_edits: tuple[Edit, ...] = (),
        objective: Objective = "accessibility",
        seed: int = 0,
        lock: contextlib.AbstractContextManager[Any] | None = None,
        progress: Progress | None = None,
        sample: int = SAMPLE_ORIGINS,
    ) -> None:
        self.model = model
        self.ev = evaluator
        self.day = evaluator.window.day
        self.base_edits = tuple(base_edits)
        self.objective = objective
        self.rng = np.random.default_rng(seed)
        self.lock = lock if lock is not None else contextlib.nullcontext()
        self.progress = progress or Progress()
        with self.lock:
            self.origins = evaluator.sample_origins(sample, seed)
            self.start_state = self._apply(())
            self.start_cost = network_cost(self.start_state.timetable, model.cost_params)
            self.baseline_cost = network_cost(evaluator.baseline_state.timetable, model.cost_params)
        self._scores: dict[str, float] = {}
        self._n_evals = 0
        self.start_score = self._score(())

    # ------------------------------------------------------------------ plumbing
    def _apply(self, edits: tuple[Edit, ...]) -> NetworkState:
        return apply(self.model, self.day, self.base_edits + edits).state

    def _score(self, edits: tuple[Edit, ...]) -> float:
        """Sampled score of a scenario (higher is better); cached by edit hash."""
        key = scenario_hash(edits)
        hit = self._scores.get(key)
        if hit is not None:
            return hit
        with self.lock:
            obj, tt = self.ev.evaluate_sampled(self._apply(edits), self.origins)
        self._n_evals += 1
        score = obj if self.objective == "accessibility" else -tt / 3600.0
        self._scores[key] = score
        return score

    def _resource(self, cost: NetworkCost, kind: BudgetKind, route_id: str | None = None) -> float:
        if route_id is not None:
            rc = cost.routes.get(route_id)
            if rc is None:
                return 0.0
            return float(rc.fleet if kind == "fleet" else rc.bus_hours)
        return float(cost.fleet if kind == "fleet" else cost.bus_hours)

    def _cost(self, edits: tuple[Edit, ...]) -> NetworkCost:
        with self.lock:
            return network_cost(self._apply(edits).timetable, self.model.cost_params)

    def eligible_routes(self) -> list[str]:
        tt = self.start_state.timetable
        return [
            r.route_id
            for r in tt.routes
            if r.kind == "day"
            and self.start_cost.routes[r.route_id].trips >= MIN_TRIPS_ELIGIBLE
            and mean_headways(tt, r.route_id)["all"] is not None
        ]

    # ----------------------------------------------------------------- frequency
    def line_options(self, kind: BudgetKind, context: tuple[Edit, ...] = ()) -> list[fq.LineOption]:
        """Probe every eligible line and build its menu (benefit, resource) per factor."""
        tt = self.start_state.timetable
        base_score = self._score(context)
        base_cost = self._cost(context)
        routes = self.eligible_routes()
        out: list[fq.LineOption] = []
        for n, rid in enumerate(routes):
            hw = mean_headways(tt, rid)["all"]
            assert hw is not None
            factors = fq.allowed_factors(hw)
            d_dn = self._score((*context, *_scale(rid, fq.PROBE_DOWN))) - base_score
            d_up = self._score((*context, *_scale(rid, fq.PROBE_UP))) - base_score
            costs = []
            for f in factors:
                if f == 1.0:
                    costs.append(0.0)
                    continue
                c = self._cost((*context, *_scale(rid, f)))
                costs.append(self._resource(c, kind, rid) - self._resource(base_cost, kind, rid))
            out.append(
                fq.LineOption(
                    rid,
                    factors,
                    tuple(fq.wait_law_benefit(f, d_dn, d_up) for f in factors),
                    tuple(costs),
                    hw,
                )
            )
            self.progress.at(0.15 + 0.35 * (n + 1) / max(len(routes), 1))
        return out

    def _plan_edits(self, plan: dict[str, float]) -> tuple[Edit, ...]:
        return tuple(e for rid in sorted(plan) if plan[rid] != 1.0 for e in _scale(rid, plan[rid]))

    def solve_frequencies(
        self,
        options: list[fq.LineOption],
        kind: BudgetKind,
        budget: float,
        context: tuple[Edit, ...] = (),
    ) -> dict[str, float]:
        """Knapsack + verification on the real timetable (the fleet of a network is
        the peak of the summed curve, which the per-line model only approximates)."""
        ctx_used = self._resource(self._cost(context), kind)
        delta = budget - ctx_used
        plan: dict[str, float] = {}
        for _ in range(8):
            plan, _ = fq.solve_knapsack(options, delta)
            # a cut that frees no resource is pure loss: undo it
            for o in options:
                f = plan.get(o.route_id, 1.0)
                if f < 1.0 and o.cost[o.factors.index(f)] >= 0.0:
                    plan[o.route_id] = 1.0
            used = self._resource(self._cost((*context, *self._plan_edits(plan))), kind)
            if used <= budget + 1e-6:
                break
            delta -= max(used - budget, 1.0 if kind == "fleet" else 2.0)
        return plan

    def improve_frequencies(
        self,
        plan: dict[str, float],
        options: list[fq.LineOption],
        kind: BudgetKind,
        budget: float,
        deadline: float,
        context: tuple[Edit, ...] = (),
    ) -> dict[str, float]:
        """Pairwise local search with the real router: move one frequency step from
        one line to another (or spend slack) while it improves the sampled score."""
        menu = {o.route_id: o.factors for o in options}
        best = dict(plan)
        best_score = self._score((*context, *self._plan_edits(best)))
        routes = list(menu)
        improved = True
        while improved and time.perf_counter() < deadline:
            improved = False
            order = self.rng.permutation(len(routes))
            for i in order:
                if time.perf_counter() >= deadline:
                    break
                up = routes[int(i)]
                k = menu[up].index(best[up])
                if k + 1 >= len(menu[up]):
                    continue
                cands: list[dict[str, float]] = [{**best, up: menu[up][k + 1]}]
                for j in self.rng.permutation(len(routes))[:4]:
                    down = routes[int(j)]
                    kd = menu[down].index(best[down])
                    if down != up and kd > 0:
                        cands.append({**best, up: menu[up][k + 1], down: menu[down][kd - 1]})
                for cand in cands:
                    edits = (*context, *self._plan_edits(cand))
                    if self._resource(self._cost(edits), kind) > budget + 1e-6:
                        continue
                    s = self._score(edits)
                    if s > best_score + 1e-7:
                        best, best_score, improved = cand, s, True
                        self._record(best_score, self._resource(self._cost(edits), kind))
                        break
        return best

    # --------------------------------------------------------------------- stops
    def stop_candidates(self) -> list[str]:
        state = self.start_state
        tt = state.timetable
        eligible = {tt.route_index[r] for r in self.eligible_routes()}
        gap: dict[int, float] = {}
        terminal: set[int] = set()
        for p in range(tt.n_patterns):
            if tt.patterns[p].route_idx not in eligible or tt.n_pattern_trips(p) == 0:
                continue
            seq = tt.pattern_stop_seq(p)
            off = tt.pattern_offsets(p)
            terminal.update((int(seq[0]), int(seq[-1])))
            for k in range(1, len(seq) - 1):
                g = float(off[k + 1] - off[k - 1])
                s = int(seq[k])
                gap[s] = max(gap.get(s, 0.0), g)
        acc = state.access
        near = acc.seconds <= 300
        zone = np.repeat(np.arange(acc.n_rows), np.diff(acc.indptr))
        catch = np.bincount(
            acc.indices[near], weights=self.model.population[zone[near]], minlength=acc.n_cols
        )
        cands = []
        for s, g in gap.items():
            if s in terminal or g > STOP_MAX_GAP_M:
                continue
            idx, secs = state.transfers.row(s)
            if not np.any((secs <= STOP_NEIGHBOUR_S) & (idx != s)):
                continue
            cands.append((float(catch[s]) / max(g, 1.0), s))
        cands.sort()
        return [tt.stop_ids[s] for _, s in cands[:MAX_STOP_CANDIDATES]]

    def consolidate_stops(self, deadline: float) -> tuple[tuple[Edit, ...], dict[str, float]]:
        base = self.start_score
        gains: dict[str, float] = {}
        for sid in self.stop_candidates():
            if time.perf_counter() >= deadline:
                break
            try:
                gains[sid] = self._score(_remove(sid)) - base
            except ScenarioError:
                continue
        chosen: tuple[Edit, ...] = ()
        kept: dict[str, float] = {}
        score = base
        for sid, g in sorted(gains.items(), key=lambda kv: -kv[1]):
            if g <= 0 or len(kept) >= MAX_STOPS_REMOVED or time.perf_counter() >= deadline:
                break
            try:
                s = self._score((*chosen, *_remove(sid)))
            except ScenarioError:
                continue
            if s > score + 1e-7:
                kept[sid] = s - score
                chosen, score = (*chosen, *_remove(sid)), s
        return chosen, kept

    # --------------------------------------------------------------------- lines
    def line_edit(self, cand: LineCandidate, n: int, headway: int) -> tuple[Edit, ...]:
        return parse_edits(
            [
                {
                    "type": "add_route",
                    "route_id": f"opt-{n + 1}",
                    "short_name": f"N{n + 1}",
                    "color": NEW_LINE_COLORS[n % len(NEW_LINE_COLORS)],
                    "stops": [{"stop_id": s} for s in cand.stop_ids],
                    "headway": headway,
                    "bidirectional": True,
                }
            ]
        )

    def alns_lines(
        self,
        options: list[fq.LineOption],
        kind: BudgetKind,
        budget: float,
        context: tuple[Edit, ...],
        deadline: float,
    ) -> tuple[tuple[Edit, ...], dict[str, float], list[tuple[LineCandidate, int]]]:
        """Adaptive large neighbourhood search over sets of new lines.

        A solution is a list of ``(candidate, headway)``. Its frequencies are
        the knapsack optimum for the budget left after paying for the lines.
        Destroy operators remove a line; repair operators insert the best or a
        random pool line or change a headway. Operator weights adapt to their
        success; worse solutions are accepted with a simulated-annealing rule.
        """
        with self.lock:
            pool = generate_candidates(
                self.model,
                self.start_state,
                self.ev.baseline_tt,
                self.ev.demand.weights,
            )
        Sol = list[tuple[int, int]]  # (pool index, headway)

        def build(sol: Sol) -> tuple[tuple[Edit, ...], dict[str, float], float] | None:
            lines: tuple[Edit, ...] = ()
            for n, (ci, hw) in enumerate(sol):
                lines += self.line_edit(pool[ci], n, hw)
            ctx = (*context, *lines)
            try:
                if self._resource(self._cost(ctx), kind) > budget + 1e-6 - _min_floor(options):
                    return None
                plan = self.solve_frequencies(options, kind, budget, ctx)
                edits = (*ctx, *self._plan_edits(plan))
                if self._resource(self._cost(edits), kind) > budget + 1e-6:
                    return None
                return edits, plan, self._score(edits)
            except ScenarioError:
                return None

        empty = build([])
        assert empty is not None
        best_sol: Sol = []
        best = cur = empty
        cur_sol: Sol = []
        if not pool:
            self.progress.say("no viable new-line candidates were found")
            return best[0], best[1], []
        # rank the pool by the measured gain of each line alone (15 min headway)
        solo: list[tuple[float, int]] = []
        for ci in range(len(pool)):
            if time.perf_counter() >= deadline:
                break
            res = build([(ci, 900)])
            if res is not None:
                solo.append((res[2] - empty[2], ci))
                if res[2] > best[2]:
                    best, best_sol = res, [(ci, 900)]
        solo.sort(reverse=True)
        ranked = [ci for _, ci in solo]
        self.progress.say(
            f"{len(pool)} candidate lines, "
            f"{sum(1 for g, _ in solo if g > 0)} improve the score on their own"
        )
        if not ranked:
            return best[0], best[1], []
        cur, cur_sol = best, list(best_sol)
        ops = ["insert_best", "insert_random", "remove", "swap", "headway"]
        weights = dict.fromkeys(ops, 1.0)
        temp = max(1e-6, 0.3 * abs(best[2] - empty[2]) + 1e-5)
        it = 0
        while time.perf_counter() < deadline and it < 400:
            it += 1
            op = str(
                self.rng.choice(ops, p=np.array([weights[o] for o in ops]) / sum(weights.values()))
            )
            sol = list(cur_sol)
            used = {ci for ci, _ in sol}
            free = [ci for ci in ranked if ci not in used]
            if op == "insert_best" and len(sol) < MAX_NEW_LINES and free:
                sol.append((free[0], int(self.rng.choice(LINE_HEADWAYS))))
            elif op == "insert_random" and len(sol) < MAX_NEW_LINES and free:
                top = free[: max(3, len(free) // 2)]
                sol.append((int(self.rng.choice(top)), int(self.rng.choice(LINE_HEADWAYS))))
            elif op == "remove" and sol:
                sol.pop(int(self.rng.integers(len(sol))))
            elif op == "swap" and sol and free:
                k = int(self.rng.integers(len(sol)))
                top = free[: max(3, len(free) // 2)]
                sol[k] = (int(self.rng.choice(top)), sol[k][1])
            elif op == "headway" and sol:
                k = int(self.rng.integers(len(sol)))
                others = [h for h in LINE_HEADWAYS if h != sol[k][1]]
                sol[k] = (sol[k][0], int(self.rng.choice(others)))
            else:
                continue
            res = build(sol)
            reward = 0.0
            if res is not None:
                d = res[2] - cur[2]
                if d > 0 or self.rng.random() < math.exp(d / temp):
                    cur, cur_sol = res, sol
                    reward = 1.0 if d > 0 else 0.3
                if res[2] > best[2] + 1e-9:
                    best, best_sol = res, list(sol)
                    reward = 3.0
                    self._record(best[2], self._resource(self._cost(best[0]), kind))
            weights[op] = 0.8 * weights[op] + 0.2 * (0.2 + reward)
            temp *= 0.97
        self.progress.say(f"ALNS: {it} iterations, {len(best_sol)} new line(s) kept")
        return best[0], best[1], [(pool[ci], hw) for ci, hw in best_sol]

    # ----------------------------------------------------------------------- run
    def _record(self, score: float, used: float) -> None:
        self.progress.history.append(
            {"iter": float(self._n_evals), "objective": round(score, 6), "used": round(used, 1)}
        )

    def run(
        self,
        budget: Budget,
        moves: tuple[Move, ...] = ("frequency",),
        time_limit_s: float = 60.0,
    ) -> OptimizeResult:
        t0 = time.perf_counter()
        deadline = t0 + time_limit_s
        pr = self.progress
        kind = budget.kind
        base_used = self._resource(self.baseline_cost, kind)
        limit = float(budget.value) if budget.value is not None else base_used
        pr.at(0.02, "baseline")
        pr.say(
            f"baseline uses {base_used:.0f} {_unit(kind)}; budget {limit:.0f}; "
            f"{len(self.eligible_routes())} lines can change frequency"
        )
        self._record(self.start_score, self._resource(self.start_cost, kind))
        context: tuple[Edit, ...] = ()
        stop_gains: dict[str, float] = {}
        if "stops" in moves:
            pr.at(0.05, "stop consolidation")
            context, stop_gains = self.consolidate_stops(t0 + 0.25 * time_limit_s)
            pr.say(f"stop consolidation: {len(stop_gains)} stop(s) removed")
            if stop_gains:
                self._record(self._score(context), self._resource(self._cost(context), kind))
        plan: dict[str, float] = {}
        options: list[fq.LineOption] = []
        lines: list[tuple[LineCandidate, int]] = []
        edits = context
        if "frequency" in moves or "new_lines" in moves:
            pr.at(0.15, "probing lines")
            options = self.line_options(kind, context)
            if "frequency" not in moves:
                options = [_frozen(o) for o in options]
            pr.at(0.5, "frequency MILP")
            plan = self.solve_frequencies(options, kind, limit, context)
            edits = (*context, *self._plan_edits(plan))
            s = self._score(edits)
            pr.say(
                f"MILP: {sum(1 for f in plan.values() if f > 1)} lines up, "
                f"{sum(1 for f in plan.values() if f < 1)} down; sampled score "
                f"{_pct(s, self.start_score)}"
            )
            self._record(s, self._resource(self._cost(edits), kind))
        if "new_lines" in moves:
            pr.at(0.55, "new lines (ALNS)")
            edits, plan, lines = self.alns_lines(
                options, kind, limit, context, t0 + 0.85 * time_limit_s
            )
        if "frequency" in moves and options:
            pr.at(0.88, "local search")
            line_ctx = tuple(e for e in edits if e.type == "add_route")
            ctx = (*context, *line_ctx)
            better = self.improve_frequencies(plan, options, kind, limit, deadline, ctx)
            if better != plan:
                plan = better
                edits = (*ctx, *self._plan_edits(plan))
                pr.say(f"local search: sampled score {_pct(self._score(edits), self.start_score)}")
        if (
            self._score(edits) <= self.start_score
            and self._resource(self.start_cost, kind) <= limit
        ):
            pr.say("no improvement found within the budget; keeping the starting network")
            edits, plan, lines, stop_gains = (), {}, [], {}
        pr.at(0.95, "final evaluation")
        with self.lock:
            final_state = self._apply(edits)
            optimized = self.ev.evaluate(final_state)
            assert self.ev.baseline_summary is not None
            baseline = EvalResult(
                self.ev.baseline_summary.objective,
                self.ev.baseline_summary.mean_travel_time,
                self.baseline_cost,
                self.ev.baseline_summary,
                self.ev.baseline_tt,
            )
        used = self._resource(optimized.cost, kind)
        pr.say(
            f"final: accessibility {_pct(optimized.objective, baseline.objective)}, "
            f"mean travel time {optimized.mean_travel_time - baseline.mean_travel_time:+.0f} s, "
            f"{used:.0f} of {limit:.0f} {_unit(kind)}"
        )
        self._record(self._score(edits), used)
        full = self.base_edits + edits
        result = OptimizeResult(
            edits=full,
            scenario=[edit_to_dict(e) for e in full],
            baseline=baseline,
            optimized=optimized,
            budget_kind=kind,
            budget=limit,
            used=used,
            explanation=self._explain(plan, options, stop_gains, lines, optimized, kind),
            history=list(pr.history),
            elapsed_s=time.perf_counter() - t0,
        )
        pr.progress, pr.stage = 1.0, "done"
        return result

    def _explain(
        self,
        plan: dict[str, float],
        options: list[fq.LineOption],
        stop_gains: dict[str, float],
        lines: list[tuple[LineCandidate, int]],
        optimized: EvalResult,
        kind: BudgetKind,
    ) -> list[Explanation]:
        tt = self.start_state.timetable
        out: list[Explanation] = []
        by_route = {o.route_id: o for o in options}
        for rid, f in plan.items():
            if f == 1.0:
                continue
            o = by_route[rid]
            k = o.factors.index(f)
            info = tt.routes[tt.route_index[rid]]
            out.append(
                Explanation(
                    "frequency",
                    "frequency_up" if f > 1 else "frequency_down",
                    {
                        "route": info.short_name,
                        "from_headway": round(o.headway_s),
                        "to_headway": round(o.headway_s / f),
                        "factor": f,
                        "resource_delta": round(o.cost[k], 1),
                        "resource": kind,
                    },
                    o.benefit[k],
                    rid,
                )
            )
        for sid, g in stop_gains.items():
            out.append(
                Explanation(
                    "stop",
                    "stop_removed",
                    {"stop_id": sid, "name": tt.stop_names[tt.stop_index[sid]]},
                    g,
                )
            )
        for n, (cand, hw) in enumerate(lines):
            rid = f"opt-{n + 1}"
            rc = optimized.cost.routes.get(rid)
            names = [tt.stop_names[tt.stop_index[s]] for s in (cand.stop_ids[0], cand.stop_ids[-1])]
            out.append(
                Explanation(
                    "new_line",
                    "new_line",
                    {
                        "route": f"N{n + 1}",
                        "from": names[0],
                        "to": names[1],
                        "headway": hw,
                        "fleet": rc.fleet if rc else 0,
                        "length_km": round(cand.length_m / 1000, 1),
                        "n_stops": len(cand.stop_ids),
                    },
                    0.0,
                    rid,
                )
            )
        out.sort(key=lambda e: -abs(e.delta_objective))
        return out

    # ------------------------------------------------------------------ tradeoff
    def tradeoff(
        self,
        kind: BudgetKind,
        values: list[float],
        on_point: Callable[[TradeoffPoint], None] | None = None,
    ) -> list[TradeoffPoint]:
        """Budget-vs-benefit curve: the frequency plan is re-optimised for every
        budget from one shared probe of the lines (so the curve is cheap), then
        each point is evaluated exactly."""
        pr = self.progress
        pr.at(0.05, "probing lines")
        options = self.line_options(kind)
        points: list[TradeoffPoint] = []
        for n, b in enumerate(sorted(values)):
            pr.at(0.5 + 0.5 * n / max(len(values), 1), f"budget {b:.0f}")
            plan = self.solve_frequencies(options, kind, float(b))
            edits = self._plan_edits(plan)
            with self.lock:
                res = self.ev.evaluate(self._apply(edits))
            assert res.summary is not None
            point = TradeoffPoint(
                budget=float(b),
                used=self._resource(res.cost, kind),
                objective=res.objective,
                mean_travel_time=res.mean_travel_time,
                share_within={c: ca.share_within for c, ca in res.summary.categories.items()},
                scenario=[edit_to_dict(e) for e in self.base_edits + edits],
            )
            points.append(point)
            if on_point:
                on_point(point)
        pr.progress, pr.stage = 1.0, "done"
        return points


def _scale(route_id: str, factor: float) -> tuple[Edit, ...]:
    return parse_edits([{"type": "scale_frequency", "route_id": route_id, "factor": factor}])


def _remove(stop_id: str) -> tuple[Edit, ...]:
    return parse_edits([{"type": "remove_stop", "stop_id": stop_id}])


def _frozen(o: fq.LineOption) -> fq.LineOption:
    return fq.LineOption(o.route_id, (1.0,), (0.0,), (0.0,), o.headway_s)


def _min_floor(options: list[fq.LineOption]) -> float:
    """Most resource the frequency menu can free (a negative number)."""
    return float(sum(min(o.cost) for o in options))


def _unit(kind: str) -> str:
    return "buses" if kind == "fleet" else "bus-hours"


def _pct(score: float, base: float) -> str:
    return f"{100.0 * (score / base - 1.0):+.2f}%" if base else "n/a"
