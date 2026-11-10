"""Accessibility metrics computed from a zone-to-zone travel-time matrix.

All functions are pure numpy and take the ``uint16`` travel-time matrix
(seconds, 65535 = unreachable) produced by the router.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from vlab.demand.gravity import DEFAULT_BETA_PER_MIN, UNREACHABLE, decay

FloatArray = npt.NDArray[np.floating]
TTMatrix = npt.NDArray[np.uint16]

#: Cumulative-curve steps: every 5 minutes up to one hour.
CURVE_STEPS_S: tuple[int, ...] = tuple(range(300, 3601, 300))


def nearest_time(tt: TTMatrix, dest_zones: npt.NDArray[np.integer]) -> npt.NDArray[np.uint16]:
    """Travel time from every origin zone to the nearest of ``dest_zones``."""
    if dest_zones.size == 0:
        return np.full(tt.shape[0], UNREACHABLE, dtype=np.uint16)
    return tt[:, np.unique(dest_zones)].min(axis=1)


def weighted_quantile(values: FloatArray, weights: FloatArray, q: float) -> float:
    """Weighted quantile (lower interpolation). NaN when there is no weight."""
    mask = np.isfinite(values) & (weights > 0)
    if not mask.any():
        return float("nan")
    v = values[mask]
    w = weights[mask].astype(np.float64)
    order = np.argsort(v, kind="stable")
    cw = np.cumsum(w[order])
    idx = int(np.searchsorted(cw, q * cw[-1], side="left"))
    return float(v[order][min(idx, v.size - 1)])


@dataclass(frozen=True)
class CategoryAccess:
    """Access of the population to the nearest destination of one category."""

    category: str
    n_pois: int
    time: npt.NDArray[np.uint16]  # per zone, seconds, 65535 unreachable
    pop_within: float
    share_within: float
    median_time: float  # population-weighted, over ALL residents (inf if > half unreachable)
    mean_time: float  # population-weighted, over residents who can reach it
    curve: list[tuple[int, float]]


def category_access(
    category: str,
    tt: TTMatrix,
    population: FloatArray,
    dest_zones: npt.NDArray[np.integer],
    threshold_s: int,
    n_pois: int | None = None,
) -> CategoryAccess:
    time = nearest_time(tt, dest_zones)
    pop = population.astype(np.float64)
    total = float(pop.sum())
    reach = time != UNREACHABLE
    within = reach & (time <= threshold_s)
    pop_within = float(pop[within].sum())
    t = time.astype(np.float64)
    t_inf = np.where(reach, t, np.inf)
    # median over all residents: unreachable counts as +inf
    order = np.argsort(t_inf, kind="stable")
    cw = np.cumsum(pop[order])
    median = float("nan")
    if total > 0:
        idx = int(np.searchsorted(cw, 0.5 * total, side="left"))
        median = float(t_inf[order][min(idx, t.size - 1)])
    reach_pop = float(pop[reach].sum())
    mean = float((t[reach] * pop[reach]).sum() / reach_pop) if reach_pop > 0 else float("nan")
    curve = [
        (s, float(pop[reach & (time <= s)].sum() / total) if total > 0 else 0.0)
        for s in CURVE_STEPS_S
    ]
    return CategoryAccess(
        category=category,
        n_pois=int(n_pois if n_pois is not None else np.unique(dest_zones).size),
        time=time,
        pop_within=pop_within,
        share_within=pop_within / total if total > 0 else 0.0,
        median_time=median,
        mean_time=mean,
        curve=curve,
    )


def cumulative_opportunities(
    tt: TTMatrix, attraction: FloatArray, threshold_s: int
) -> npt.NDArray[np.float32]:
    """Share (0..1) of all activity reachable from each zone within the threshold."""
    total = float(attraction.sum())
    if total <= 0:
        return np.zeros(tt.shape[0], dtype=np.float32)
    mask = tt <= threshold_s  # 65535 is never <= a sane threshold
    return (mask @ attraction.astype(np.float32) / np.float32(total)).astype(np.float32)


def gravity_accessibility(
    tt: TTMatrix, attraction: FloatArray, beta_per_min: float = DEFAULT_BETA_PER_MIN
) -> npt.NDArray[np.float32]:
    """Hansen accessibility per zone, normalised to 0..1 (1 = everything at zero time)."""
    total = float(attraction.sum())
    if total <= 0:
        return np.zeros(tt.shape[0], dtype=np.float32)
    return (decay(tt, beta_per_min) @ attraction.astype(np.float32) / np.float32(total)).astype(
        np.float32
    )


def population_weighted(values: FloatArray, population: FloatArray) -> float:
    """Population-weighted mean ignoring NaNs."""
    mask = np.isfinite(values) & (population > 0)
    w = population[mask].astype(np.float64)
    if w.sum() <= 0:
        return float("nan")
    return float((values[mask].astype(np.float64) * w).sum() / w.sum())


@dataclass(frozen=True)
class IncomeGroup:
    q: int
    income_min: float
    income_max: float
    population: float
    zone_mask: npt.NDArray[np.bool_]


def income_quantile_groups(
    income: FloatArray, population: FloatArray, n_groups: int = 5
) -> list[IncomeGroup]:
    """Split zones into population-weighted income quantile groups (1 = lowest income).

    Zones without income data or population are left out of every group.
    """
    valid = np.isfinite(income) & (population > 0)
    idx = np.flatnonzero(valid)
    if idx.size == 0:
        return []
    order = idx[np.argsort(income[idx], kind="stable")]
    cw = np.cumsum(population[order].astype(np.float64))
    total = cw[-1]
    # group of each zone by the cumulative population *before* it
    before = cw - population[order]
    grp = np.minimum((before / total * n_groups).astype(np.int64), n_groups - 1)
    groups: list[IncomeGroup] = []
    for g in range(n_groups):
        members = order[grp == g]
        if members.size == 0:
            continue
        mask = np.zeros(income.shape[0], dtype=np.bool_)
        mask[members] = True
        groups.append(
            IncomeGroup(
                q=g + 1,
                income_min=float(income[members].min()),
                income_max=float(income[members].max()),
                population=float(population[members].sum()),
                zone_mask=mask,
            )
        )
    return groups


def concentration_index(outcome: FloatArray, income: FloatArray, population: FloatArray) -> float:
    """Concentration index of ``outcome`` over the income ranking, in [-1, 1].

    Positive: the outcome is concentrated among higher-income residents;
    negative: among lower-income residents; 0: equally distributed. Computed
    with the population-weighted covariance formula ``2 cov(y, r) / mean(y)``
    where ``r`` is the fractional income rank.
    """
    valid = np.isfinite(outcome) & np.isfinite(income) & (population > 0)
    if valid.sum() < 2:
        return float("nan")
    y = outcome[valid].astype(np.float64)
    inc = income[valid].astype(np.float64)
    w = population[valid].astype(np.float64)
    order = np.argsort(inc, kind="stable")
    y, w = y[order], w[order]
    w = w / w.sum()
    rank = np.cumsum(w) - 0.5 * w
    mean_y = float((w * y).sum())
    if mean_y == 0:
        return float("nan")
    cov = float((w * (y - mean_y) * (rank - 0.5)).sum())
    return 2.0 * cov / mean_y


def people_gaining_losing(
    base_times: Mapping[str, npt.NDArray[np.uint16]],
    scen_times: Mapping[str, npt.NDArray[np.uint16]],
    base_mean: FloatArray,
    scen_mean: FloatArray,
    population: FloatArray,
    threshold_s: int,
    essential: Sequence[str],
    min_delta_s: float = 60.0,
) -> tuple[float, float]:
    """Residents who gain / lose access between baseline and scenario.

    A zone *gains* when an essential category crosses the threshold in its
    favour (and none crosses against it), or — with no crossing at all — when
    its demand-weighted mean travel time improves by more than ``min_delta_s``.
    *Loses* is the mirror image. A zone with crossings in both directions is
    classified by its mean travel time change.
    """
    n = population.shape[0]
    up = np.zeros(n, dtype=np.bool_)
    down = np.zeros(n, dtype=np.bool_)
    for cat in essential:
        if cat not in base_times or cat not in scen_times:
            continue
        b = base_times[cat] <= threshold_s
        s = scen_times[cat] <= threshold_s
        up |= ~b & s
        down |= b & ~s
    d = scen_mean.astype(np.float64) - base_mean.astype(np.float64)
    d = np.where(np.isfinite(d), d, 0.0)
    faster = d < -min_delta_s
    slower = d > min_delta_s
    gain = (up & ~down) | (~(up ^ down) & faster)
    lose = (down & ~up) | (~(up ^ down) & slower)
    pop = population.astype(np.float64)
    return float(pop[gain].sum()), float(pop[lose].sum())
