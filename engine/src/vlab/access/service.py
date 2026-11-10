"""Accessibility service: travel-time matrices, KPI bundles and the evaluator.

Everything here is a thin, cached orchestration of :mod:`vlab.raptor`,
:mod:`vlab.access.metrics`, :mod:`vlab.demand` and :mod:`vlab.cost` around a
:class:`vlab.model.Model`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from vlab.access import metrics as M
from vlab.cost.model import NetworkCost, network_cost
from vlab.demand.gravity import DEFAULT_BETA_PER_MIN, GravityDemand, build_gravity_demand
from vlab.model.world import ESSENTIAL_CATEGORIES, Model, NetworkState, Window
from vlab.raptor import travel_time_matrix
from vlab.walk import WalkTable

DEPARTURE_STEP_S = 600
DEFAULT_THRESHOLD_S = 1800
UNREACHABLE = np.uint16(65535)


def travel_times(
    model: Model,
    state: NetworkState,
    window: Window,
    origins: npt.NDArray[np.int64] | None = None,
) -> npt.NDArray[np.uint16]:
    """Zone-to-zone door-to-door travel times (uint16 s, 65535 = unreachable).

    Mean over departures every 10 minutes of the window of walk + transit + walk,
    never worse than walking directly (decisions D-006 and D-010). ``origins``
    restricts the rows to a subset of zones (used by the optimizer's sampling).
    """
    access = state.access if origins is None else subset_rows(state.access, origins)
    direct = model.direct_walk if origins is None else model.direct_walk[origins]
    return travel_time_matrix(
        state.timetable,
        state.transfers,
        access,
        state.egress,
        window.departures(DEPARTURE_STEP_S),
        np.ascontiguousarray(direct),
    )


def subset_rows(table: WalkTable, rows: npt.NDArray[np.int64]) -> WalkTable:
    """Rows ``rows`` of a CSR walking table, in that order."""
    counts = (table.indptr[rows + 1] - table.indptr[rows]).astype(np.int64)
    ptr = np.zeros(len(rows) + 1, dtype=np.int64)
    np.cumsum(counts, out=ptr[1:])
    take = np.concatenate(
        [np.arange(table.indptr[r], table.indptr[r + 1]) for r in rows]
        or [np.zeros(0, dtype=np.int64)]
    ).astype(np.int64)
    return WalkTable(ptr, table.indices[take], table.seconds[take], table.n_cols)


@dataclass(frozen=True, eq=False)
class AccessSummary:
    """All accessibility indicators of one travel-time matrix."""

    threshold: int
    categories: dict[str, M.CategoryAccess]
    jobs: npt.NDArray[np.float32]  # cumulative activity share within threshold, per zone
    hansen: npt.NDArray[np.float32]  # gravity accessibility per zone, 0..1
    zone_mean_time: npt.NDArray[np.float32]  # demand-weighted mean travel time per zone
    mean_travel_time: float
    objective: float  # population-weighted Hansen accessibility, 0..1
    jobs_mean: float
    underserved_population: float


def summarise(
    model: Model,
    tt: npt.NDArray[np.uint16],
    demand: GravityDemand,
    threshold: int = DEFAULT_THRESHOLD_S,
) -> AccessSummary:
    pop = model.population
    cats = {
        c: M.category_access(c, tt, pop, zones, threshold, model.category_counts.get(c))
        for c, zones in model.category_zones.items()
    }
    jobs = M.cumulative_opportunities(tt, model.attraction, threshold)
    hansen = M.gravity_accessibility(tt, model.attraction, demand.beta_per_min)
    fail = np.zeros(len(pop), dtype=np.bool_)
    for c in ESSENTIAL_CATEGORIES:
        if c in cats:
            fail |= cats[c].time > threshold
    return AccessSummary(
        threshold=threshold,
        categories=cats,
        jobs=jobs,
        hansen=hansen,
        zone_mean_time=demand.zone_mean_travel_time(tt),
        mean_travel_time=demand.mean_travel_time(tt),
        objective=M.population_weighted(hansen, pop),
        jobs_mean=M.population_weighted(jobs, pop),
        underserved_population=float(pop[fail].sum()),
    )


@dataclass(frozen=True)
class EquityGroup:
    q: int
    income_min: float
    income_max: float
    population: float
    share_within: dict[str, float]
    mean_time: dict[str, float]


def equity(model: Model, summary: AccessSummary) -> tuple[list[EquityGroup], dict[str, float]]:
    """Access by population-weighted income quintile and concentration indices.

    The concentration index is computed on the indicator "reaches the category
    within the threshold": positive means access is concentrated among
    higher-income residents.
    """
    pop = model.population
    groups = M.income_quantile_groups(model.income, pop, 5)
    out: list[EquityGroup] = []
    for g in groups:
        w = pop[g.zone_mask]
        share: dict[str, float] = {}
        mean: dict[str, float] = {}
        for c, ca in summary.categories.items():
            t = ca.time[g.zone_mask]
            within = t <= summary.threshold
            share[c] = float(w[within].sum() / w.sum()) if w.sum() > 0 else float("nan")
            reach = t != UNREACHABLE
            mean[c] = (
                float((t[reach].astype(np.float64) * w[reach]).sum() / w[reach].sum())
                if w[reach].sum() > 0
                else float("nan")
            )
        out.append(EquityGroup(g.q, g.income_min, g.income_max, g.population, share, mean))
    ci = {
        c: M.concentration_index(
            (ca.time <= summary.threshold).astype(np.float64), model.income, pop
        )
        for c, ca in summary.categories.items()
    }
    return out, ci


@dataclass(frozen=True, eq=False)
class EvalResult:
    """Outcome of evaluating one network on one window."""

    objective: float
    mean_travel_time: float
    cost: NetworkCost
    summary: AccessSummary | None  # None for sampled (fast) evaluations
    tt: npt.NDArray[np.uint16] | None


@dataclass(eq=False)
class Evaluator:
    """Evaluates networks on one analysis window against a fixed baseline.

    The gravity demand weights and the origin sample are fixed on the baseline
    so that results of different networks are comparable. ``sample`` > 0 turns on
    the fast mode used inside the optimizer: only a population-weighted sample
    of origin zones is routed and the objective is a weighted estimate.
    """

    model: Model
    window: Window
    threshold: int = DEFAULT_THRESHOLD_S
    beta_per_min: float = DEFAULT_BETA_PER_MIN
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _base_tt: npt.NDArray[np.uint16] | None = None
    _demand: GravityDemand | None = None
    _base_summary: AccessSummary | None = None

    @property
    def baseline_state(self) -> NetworkState:
        return self.model.baseline(self.window.day)

    @property
    def baseline_tt(self) -> npt.NDArray[np.uint16]:
        with self._lock:
            if self._base_tt is None:
                self._base_tt = travel_times(self.model, self.baseline_state, self.window)
            return self._base_tt

    @property
    def demand(self) -> GravityDemand:
        base = self.baseline_tt
        with self._lock:
            if self._demand is None:
                self._demand = build_gravity_demand(
                    self.model.population, self.model.attraction, base, self.beta_per_min
                )
            return self._demand

    @property
    def baseline_summary(self) -> AccessSummary:
        base, demand = self.baseline_tt, self.demand
        with self._lock:
            if self._base_summary is None:
                self._base_summary = summarise(self.model, base, demand, self.threshold)
            return self._base_summary

    def summary_at(self, threshold: int) -> AccessSummary:
        if threshold == self.threshold:
            return self.baseline_summary
        return summarise(self.model, self.baseline_tt, self.demand, threshold)

    def evaluate(self, state: NetworkState, threshold: int | None = None) -> EvalResult:
        """Exact evaluation on all zones."""
        tt = travel_times(self.model, state, self.window)
        summary = summarise(self.model, tt, self.demand, threshold or self.threshold)
        return EvalResult(
            objective=summary.objective,
            mean_travel_time=summary.mean_travel_time,
            cost=network_cost(state.timetable, self.model.cost_params),
            summary=summary,
            tt=tt,
        )

    def sample_origins(self, n: int, seed: int = 0) -> npt.NDArray[np.int64]:
        """Population-weighted sample of origin zones without replacement (sorted)."""
        pop = self.model.population
        candidates = np.flatnonzero(pop > 0)
        if n >= len(candidates):
            return candidates
        rng = np.random.default_rng(seed)
        p = pop[candidates] / pop[candidates].sum()
        return np.sort(rng.choice(candidates, size=n, replace=False, p=p))

    def evaluate_sampled(
        self, state: NetworkState, origins: npt.NDArray[np.int64]
    ) -> tuple[float, float]:
        """Fast estimate ``(objective, mean_travel_time)`` on a sample of origins.

        Sampling is proportional to population without replacement, so the plain
        mean over sampled zones estimates the population-weighted mean (exactly
        so for small sampling fractions); the same sample is used for every
        candidate, which is what matters for ranking them.
        """
        tt = travel_times(self.model, state, self.window, origins)
        hansen = M.gravity_accessibility(tt, self.model.attraction, self.beta_per_min)
        w = self.demand.weights[origins]
        t = tt.astype(np.float32)
        t[tt == UNREACHABLE] = 7200.0
        den = w.sum(axis=1, dtype=np.float64)
        zone_mean = np.divide(
            (w * t).sum(axis=1, dtype=np.float64), den, out=np.zeros_like(den), where=den > 0
        )
        return float(hansen.mean()), float(zone_mean.mean())
