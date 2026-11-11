"""New-line candidates from unmet demand.

Candidates connect pairs of hubs (well-used existing stops spread over the
area) for which the gravity demand is high and the current transit time is
poor compared with a direct bus. Each candidate follows the bus-drivable street
graph between the hubs and serves the existing stops along the way.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from vlab.gtfs.timetable import Timetable
from vlab.model.world import Model, NetworkState
from vlab.scenario.apply import nearby_stops, snap_path

MIN_LINE_M = 2500.0
MAX_LINE_M = 14_000.0
MIN_STOP_SPACING_M = 280.0
DIRECT_SPEED_MPS = 12.3 / 3.6
#: Lines longer than this multiple of the straight distance are discarded.
MAX_DETOUR = 1.7


@dataclass(frozen=True)
class LineCandidate:
    key: str
    hub_a: int  # zone index
    hub_b: int
    stop_ids: tuple[str, ...]
    length_m: float
    score: float  # person-seconds of excess travel time the line could address


def pick_hubs(model: Model, state: NetworkState, n_hubs: int = 28) -> npt.NDArray[np.int64]:
    """Zones used as line termini: greedy farthest-point sampling weighted by
    residents + activity, restricted to zones with a stop within 300 s walk."""
    acc = state.access
    has_stop = np.zeros(model.n_zones, dtype=bool)
    for z in range(model.n_zones):
        _, secs = acc.row(z)
        has_stop[z] = bool(len(secs)) and int(secs.min()) <= 300
    w = model.population / max(model.population.sum(), 1.0) + model.attraction
    w = np.where(has_stop, w, 0.0)
    xs = model.zones["x"].to_numpy(np.float64)
    ys = model.zones["y"].to_numpy(np.float64)
    # aggregate weight within 600 m so a hub represents its neighbourhood
    order = np.argsort(-w)
    hubs: list[int] = []
    for z in order:
        if w[z] <= 0 or len(hubs) >= n_hubs:
            break
        if all(np.hypot(xs[z] - xs[h], ys[z] - ys[h]) > 1100.0 for h in hubs):
            hubs.append(int(z))
    return np.asarray(hubs, dtype=np.int64)


def _catchment(model: Model, hub: int, radius_m: float = 700.0) -> npt.NDArray[np.int64]:
    xs = model.zones["x"].to_numpy(np.float64)
    ys = model.zones["y"].to_numpy(np.float64)
    return np.flatnonzero(np.hypot(xs - xs[hub], ys - ys[hub]) <= radius_m)


def _stops_along(tt: Timetable, path: npt.NDArray[np.float64]) -> tuple[str, ...]:
    out: list[tuple[int, float]] = []
    for s, off, _ in nearby_stops(tt, path, 35.0):
        if not out or off - out[-1][1] >= MIN_STOP_SPACING_M:
            out.append((s, off))
    return tuple(tt.stop_ids[s] for s, _ in out)


def generate_candidates(
    model: Model,
    state: NetworkState,
    tt_matrix: npt.NDArray[np.uint16],
    demand_weights: npt.NDArray[np.float32],
    max_candidates: int = 24,
) -> list[LineCandidate]:
    """Rank hub pairs by excess person-time and build a street-following line for
    the best ones."""
    hubs = pick_hubs(model, state)
    xs = model.zones["x"].to_numpy(np.float64)
    ys = model.zones["y"].to_numpy(np.float64)
    catch = [_catchment(model, int(h)) for h in hubs]
    t = tt_matrix.astype(np.float32)
    t[tt_matrix == 65535] = 7200.0
    scored: list[tuple[float, int, int]] = []
    for i in range(len(hubs)):
        for j in range(i + 1, len(hubs)):
            d = float(np.hypot(xs[hubs[i]] - xs[hubs[j]], ys[hubs[i]] - ys[hubs[j]]))
            if not MIN_LINE_M <= 1.3 * d <= MAX_LINE_M:
                continue
            direct = 1.3 * d / DIRECT_SPEED_MPS + 420.0  # ride + walk/wait allowance
            a, b = catch[i], catch[j]
            w = demand_weights[np.ix_(a, b)].astype(np.float64)
            w_back = demand_weights[np.ix_(b, a)].astype(np.float64)
            excess = np.maximum(t[np.ix_(a, b)] - direct, 0.0)
            excess_back = np.maximum(t[np.ix_(b, a)] - direct, 0.0)
            score = float((w * excess).sum() + (w_back * excess_back).sum())
            if score > 0:
                scored.append((score, i, j))
    scored.sort(reverse=True)
    out: list[LineCandidate] = []
    tt = state.timetable
    lon, lat = model.zone_lon, model.zone_lat
    for score, i, j in scored[: 3 * max_candidates]:
        za, zb = int(hubs[i]), int(hubs[j])
        path = snap_path(model.drive, [[lon[za], lat[za]], [lon[zb], lat[zb]]])
        straight = float(np.hypot(xs[za] - xs[zb], ys[za] - ys[zb]))
        if path.warnings or path.length_m > MAX_DETOUR * straight + 300.0:
            continue
        stops = _stops_along(tt, path.coords)
        if len(stops) < 4:
            continue
        out.append(LineCandidate(f"{za}-{zb}", za, zb, stops, path.length_m, score))
        if len(out) >= max_candidates:
            break
    return out
