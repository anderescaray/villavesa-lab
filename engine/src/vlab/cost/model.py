"""Fleet, bus-hours, kilometres and cost of a timetable.

Definitions (all parameters live in :class:`CostParams`):

* **bus-hours** are revenue hours: first departure to last arrival of every trip.
  The operator's tariff is defined on *useful* hours, and the feed's in-motion
  hours annualise to within ~10% of the reported service hours, so terminal
  layover is not charged (it still drives the fleet).
* **km** is the length of each trip along its shape.
* **fleet** is the peak number of simultaneously committed vehicles, where a trip
  commits a bus from its first departure until its last arrival plus a layover of
  ``max(layover_min_s, layover_frac * run_time)``. For a regular line this equals
  the textbook ``ceil(cycle_time / headway)`` (see :func:`cycle_fleet`) and it
  generalises to real timetables with short-turns and uneven headways. The
  network fleet is the peak of the summed curve (lines peak at different times),
  not the sum of the per-route peaks.
* **cost** per day = ``eur_per_bus_hour * bus_hours + eur_per_km * km``; the
  yearly figure adds ``eur_per_bus_year * fleet`` of capital.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass

import numpy as np
import numpy.typing as npt

from vlab.gtfs.timetable import Timetable

_RES_S = 60  # resolution of the vehicles-in-use curve
_HORIZON_S = 36 * 3600
_OFFSET_S = 6 * 3600  # trips of the previous service day start before midnight


@dataclass(frozen=True)
class CostParams:
    """Cost-model parameters (sources in docs/reference_facts.md, decision D-009)."""

    eur_per_bus_hour: float = 43.15
    eur_per_km: float = 1.25
    eur_per_bus_year: float = 25_300.0
    layover_min_s: int = 240
    layover_frac: float = 0.10
    #: days of each type in a year (251 working days, 52 Saturdays, 62 Sundays/holidays)
    days_weekday: int = 251
    days_saturday: int = 52
    days_sunday: int = 62
    source: str = (
        "MCP X Plan 2023 two-part operator tariff (EUR per useful bus-hour and per km, "
        "2023 prices) and contract amortisation + financing per bus; pre-2024 concession"
    )

    def days(self) -> dict[str, int]:
        return {
            "weekday": self.days_weekday,
            "saturday": self.days_saturday,
            "sunday": self.days_sunday,
        }

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def layover_s(run_time_s: npt.ArrayLike, params: CostParams) -> npt.NDArray[np.int64]:
    run = np.asarray(run_time_s, dtype=np.float64)
    return np.maximum(params.layover_min_s, np.ceil(params.layover_frac * run)).astype(np.int64)


def cycle_fleet(run_time_s: float, headway_s: float, params: CostParams | None = None) -> int:
    """Textbook fleet for ONE direction of a regular line: ``ceil((run + layover) / headway)``.

    A two-way line needs the sum over both directions (= cycle time / headway).
    """
    p = params or CostParams()
    lay = float(layover_s(run_time_s, p))
    return max(1, math.ceil((run_time_s + lay) / headway_s - 1e-9))


@dataclass(frozen=True)
class RouteCost:
    route_id: str
    trips: int
    fleet: int
    bus_hours: float
    km: float
    cost_eur: float  # per day, operating


@dataclass(frozen=True)
class NetworkCost:
    routes: dict[str, RouteCost]
    fleet: int
    bus_hours: float
    km: float
    cost_eur: float  # per day, operating
    trips: int
    in_use: npt.NDArray[np.int32]  # vehicles committed per minute, from -6 h

    def in_use_at(self, t_s: int) -> int:
        i = (int(t_s) + _OFFSET_S) // _RES_S
        return int(self.in_use[i]) if 0 <= i < len(self.in_use) else 0


def network_cost(tt: Timetable, params: CostParams | None = None) -> NetworkCost:
    """Cost of one service day. Overnight copies of the previous day's trips are
    excluded from hours/km/trips (they belong to that day) but do occupy buses."""
    p = params or CostParams()
    n_bins = _HORIZON_S // _RES_S
    n_routes = len(tt.routes)
    diff = np.zeros((n_routes, n_bins + 1), dtype=np.int32)
    hours = np.zeros(n_routes)
    km = np.zeros(n_routes)
    trips = np.zeros(n_routes, dtype=np.int64)
    for pi in range(tt.n_patterns):
        a, b = int(tt.pattern_trips_ptr[pi]), int(tt.pattern_trips_ptr[pi + 1])
        if a == b:
            continue
        r = int(tt.pattern_route[pi])
        dep0 = tt.departures(pi)[:, 0].astype(np.int64)
        arr1 = tt.arrivals(pi)[:, -1].astype(np.int64)
        run = arr1 - dep0
        own = ~tt.trip_prev_day[a:b]
        off = tt.pattern_offsets(pi)
        length_km = float(off[-1] - off[0]) / 1000.0
        hours[r] += float(run[own].sum()) / 3600.0
        km[r] += length_km * int(own.sum())
        trips[r] += int(own.sum())
        start = np.clip((dep0 + _OFFSET_S) // _RES_S, 0, n_bins)
        end = np.clip(-(-(arr1 + layover_s(run, p) + _OFFSET_S) // _RES_S), 0, n_bins)
        np.add.at(diff[r], start, 1)
        np.add.at(diff[r], end, -1)
    curves = np.cumsum(diff[:, :-1], axis=1)
    total_curve = curves.sum(axis=0).astype(np.int32)
    routes: dict[str, RouteCost] = {}
    for r, info in enumerate(tt.routes):
        cost = p.eur_per_bus_hour * hours[r] + p.eur_per_km * km[r]
        routes[info.route_id] = RouteCost(
            route_id=info.route_id,
            trips=int(trips[r]),
            fleet=int(curves[r].max()) if trips[r] or curves[r].any() else 0,
            bus_hours=float(hours[r]),
            km=float(km[r]),
            cost_eur=float(cost),
        )
    return NetworkCost(
        routes=routes,
        fleet=int(total_curve.max()) if total_curve.size else 0,
        bus_hours=float(hours.sum()),
        km=float(km.sum()),
        cost_eur=float(p.eur_per_bus_hour * hours.sum() + p.eur_per_km * km.sum()),
        trips=int(trips.sum()),
        in_use=total_curve,
    )


def annual_cost(
    by_day: Mapping[str, NetworkCost], params: CostParams | None = None
) -> dict[str, float]:
    """Annualise per-day costs (keys: weekday / saturday / sunday).

    Returns bus-hours, km, operating cost, capital cost and total per year. The
    fleet is the largest daily peak.
    """
    p = params or CostParams()
    days = p.days()
    missing = set(days) - set(by_day)
    if missing:
        raise ValueError(f"missing day types: {sorted(missing)}")
    hours = sum(by_day[d].bus_hours * n for d, n in days.items())
    km = sum(by_day[d].km * n for d, n in days.items())
    operating = sum(by_day[d].cost_eur * n for d, n in days.items())
    fleet = max(by_day[d].fleet for d in days)
    capital = p.eur_per_bus_year * fleet
    return {
        "bus_hours": float(hours),
        "km": float(km),
        "operating_eur": float(operating),
        "capital_eur": float(capital),
        "total_eur": float(operating + capital),
        "fleet": float(fleet),
    }
