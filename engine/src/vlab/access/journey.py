"""Door-to-door journey planning between two points (earliest arrival)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vlab.model.world import ACCESS_MAX_M, Model, NetworkState
from vlab.raptor import INF, raptor, reconstruct_journey
from vlab.walk import WALK_SPEED_MPS, build_access

MAX_WALK_ONLY_M = 6000.0

Coord = tuple[float, float]


@dataclass(frozen=True)
class JourneyLeg:
    mode: str  # "walk" | "bus"
    start: Coord
    end: Coord
    depart: int
    arrive: int
    path: list[list[float]]
    route_id: str | None = None
    headsign: str | None = None
    from_stop: str | None = None
    to_stop: str | None = None

    @property
    def duration(self) -> int:
        return self.arrive - self.depart


@dataclass(frozen=True)
class Journey:
    depart: int
    arrive: int
    legs: list[JourneyLeg] = field(default_factory=list)

    @property
    def duration(self) -> int:
        return self.arrive - self.depart


def _walk_path(model: Model, a: Coord, b: Coord) -> list[list[float]]:
    res = model.walk.shortest_path(a, b)
    coords = res.coords if res.found else np.array([a, b])
    return [[round(float(x), 6), round(float(y), 6)] for x, y in coords]


def plan(
    model: Model, state: NetworkState, origin: Coord, destination: Coord, depart: int
) -> Journey | None:
    """Earliest-arrival journey leaving ``origin`` at ``depart``; ``None`` if the
    destination cannot be reached by transit nor by a walk under 6 km."""
    tt = state.timetable
    acc = build_access(
        model.walk,
        ([origin[0], destination[0]], [origin[1], destination[1]]),
        tt,
        ACCESS_MAX_M,
        cache=False,
    )
    src, off = acc.row(0)
    dst, dst_s = acc.row(1)
    best_arr, best_stop, res = int(INF), -1, None
    if len(src) and len(dst):
        res = raptor(tt, state.transfers, src, int(depart), off)
        total = res.arrival[dst].astype(np.int64) + dst_s
        total[res.arrival[dst] >= INF] = int(INF)
        k = int(np.argmin(total))
        if total[k] < INF:
            best_arr, best_stop = int(total[k]), int(dst[k])
    direct = model.walk.shortest_path(origin, destination, max_m=MAX_WALK_ONLY_M)
    walk_arr = int(depart + np.ceil(direct.length_m / WALK_SPEED_MPS)) if direct.found else int(INF)
    if walk_arr <= best_arr:
        if walk_arr >= INF:
            return None
        leg = JourneyLeg(
            "walk",
            origin,
            destination,
            int(depart),
            walk_arr,
            [[round(float(x), 6), round(float(y), 6)] for x, y in direct.coords],
        )
        return Journey(int(depart), walk_arr, [leg])
    assert res is not None
    raw = reconstruct_journey(tt, res, best_stop)
    if raw is None:
        return None

    def pt(s: int) -> Coord:
        return (float(tt.stop_lon[s]), float(tt.stop_lat[s]))

    legs: list[JourneyLeg] = []
    for r in raw:
        if r.mode == "access":
            legs.append(
                JourneyLeg(
                    "walk",
                    origin,
                    pt(r.to_stop),
                    int(depart),
                    r.arrive,
                    _walk_path(model, origin, pt(r.to_stop)),
                    to_stop=tt.stop_ids[int(r.to_stop)],
                )
            )
        elif r.mode == "walk":
            legs.append(
                JourneyLeg(
                    "walk",
                    pt(r.from_stop),
                    pt(r.to_stop),
                    r.depart,
                    r.arrive,
                    _walk_path(model, pt(r.from_stop), pt(r.to_stop)),
                    from_stop=tt.stop_ids[r.from_stop],
                    to_stop=tt.stop_ids[r.to_stop],
                )
            )
        else:
            info = tt.patterns[r.pattern]
            path = tt.pattern_path(r.pattern, r.board_pos, r.alight_pos)
            legs.append(
                JourneyLeg(
                    "bus",
                    pt(r.from_stop),
                    pt(r.to_stop),
                    r.depart,
                    r.arrive,
                    [[round(float(x), 6), round(float(y), 6)] for x, y in path],
                    route_id=tt.routes[info.route_idx].route_id,
                    headsign=info.headsign,
                    from_stop=tt.stop_ids[r.from_stop],
                    to_stop=tt.stop_ids[r.to_stop],
                )
            )
    last = legs[-1].arrive if legs else int(depart)
    legs.append(
        JourneyLeg(
            "walk",
            pt(best_stop),
            destination,
            last,
            best_arr,
            _walk_path(model, pt(best_stop), destination),
            from_stop=tt.stop_ids[best_stop],
        )
    )
    legs = [g for g in legs if g.mode == "bus" or g.duration > 0 or len(legs) == 1]
    return Journey(int(depart), best_arr, legs)
