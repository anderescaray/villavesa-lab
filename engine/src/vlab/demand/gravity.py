"""Singly-constrained gravity demand model.

There is no public origin-destination matrix for the Comarca de Pamplona, so
demand is *modelled*: every resident produces the same number of trips, and the
trips of a zone are distributed over destination zones proportionally to the
destination's attraction and a negative-exponential function of travel time::

    T_ij = P_i * A_j * exp(-beta * t_ij) / sum_k(A_k * exp(-beta * t_ik))

The matrix is row-normalised (sum_j T_ij = P_i), i.e. it is expressed in
"residents" rather than trips. It is computed once on the baseline travel times
and then held fixed when scenarios are compared, so that a change in the mean
travel time reflects the service change and not a redistribution of trips.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

UNREACHABLE = np.uint16(65535)

#: Decay parameter per minute of travel time. 0.07/min halves the weight every
#: ~10 minutes, in the range commonly reported for urban trips; it is an
#: assumption (it cannot be calibrated without observed trips) and is exposed
#: as a parameter everywhere.
DEFAULT_BETA_PER_MIN = 0.07


def decay(
    tt: npt.NDArray[np.uint16], beta_per_min: float = DEFAULT_BETA_PER_MIN
) -> npt.NDArray[np.float32]:
    """exp(-beta * minutes) with 0 for unreachable pairs."""
    minutes = tt.astype(np.float32) / np.float32(60.0)
    out = np.exp(-np.float32(beta_per_min) * minutes, dtype=np.float32)
    out[tt == UNREACHABLE] = 0.0
    return out


@dataclass(frozen=True)
class GravityDemand:
    """Fixed OD weights. ``weights[i, j]`` = residents of zone i travelling to zone j."""

    weights: npt.NDArray[np.float32]
    beta_per_min: float

    @property
    def total(self) -> float:
        return float(self.weights.sum(dtype=np.float64))

    def mean_travel_time(self, tt: npt.NDArray[np.uint16], penalty_s: float = 7200.0) -> float:
        """Demand-weighted mean travel time in seconds.

        Pairs that are unreachable in ``tt`` but carry demand are charged
        ``penalty_s`` so that cutting a connection can never look like an
        improvement.
        """
        t = tt.astype(np.float32)
        t[tt == UNREACHABLE] = np.float32(penalty_s)
        total = self.total
        if total <= 0:
            return float("nan")
        return float((self.weights * t).sum(dtype=np.float64) / total)

    def zone_mean_travel_time(
        self, tt: npt.NDArray[np.uint16], penalty_s: float = 7200.0
    ) -> npt.NDArray[np.float32]:
        """Per-origin demand-weighted mean travel time (seconds); NaN if no demand."""
        t = tt.astype(np.float32)
        t[tt == UNREACHABLE] = np.float32(penalty_s)
        num = (self.weights * t).sum(axis=1, dtype=np.float64)
        den = self.weights.sum(axis=1, dtype=np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.where(den > 0, num / den, np.nan)
        return out.astype(np.float32)


def build_gravity_demand(
    population: npt.NDArray[np.floating],
    attraction: npt.NDArray[np.floating],
    tt: npt.NDArray[np.uint16],
    beta_per_min: float = DEFAULT_BETA_PER_MIN,
    exclude_intrazonal: bool = True,
) -> GravityDemand:
    """Build the production-constrained OD weights from baseline travel times."""
    n_o, n_d = tt.shape
    if population.shape != (n_o,) or attraction.shape != (n_d,):
        raise ValueError("population/attraction do not match the travel-time matrix shape")
    if (population < 0).any() or (attraction < 0).any():
        raise ValueError("population and attraction must be non-negative")
    f = decay(tt, beta_per_min)
    f *= attraction.astype(np.float32)[None, :]
    if exclude_intrazonal and n_o == n_d:
        np.fill_diagonal(f, 0.0)
    row = f.sum(axis=1, dtype=np.float64)
    scale = np.divide(
        population.astype(np.float64), row, out=np.zeros(n_o, dtype=np.float64), where=row > 0
    )
    f *= scale.astype(np.float32)[:, None]
    return GravityDemand(weights=f, beta_per_min=beta_per_min)
