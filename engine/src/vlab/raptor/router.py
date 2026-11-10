"""Python API over the RAPTOR kernels: queries, batches, matrices, journeys."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

import numpy as np
import numpy.typing as npt

from vlab.gtfs.timetable import Timetable
from vlab.raptor import kernels as _k
from vlab.raptor.kernels import INF, KIND_ACCESS, KIND_FOOT, KIND_NONE, KIND_RIDE
from vlab.walk.graph import WalkTable

I32 = npt.NDArray[np.int32]

# numba dispatchers, typed loosely for mypy
raptor_query = cast(Callable[..., Any], _k.raptor_query)
raptor_many = cast(Callable[..., Any], _k.raptor_many)
travel_time_kernel = cast(Callable[..., Any], _k.travel_time_kernel)

#: Unreachable marker in uint16 travel-time matrices.
UNREACHABLE_U16 = 65535
DEFAULT_MAX_ROUNDS = 4
DEFAULT_BOARD_SLACK = 60


def empty_transfers(n_stops: int) -> WalkTable:
    """A transfer table with no footpaths (only same-stop transfers)."""
    return WalkTable(
        np.zeros(n_stops + 1, np.int64), np.zeros(0, np.int32), np.zeros(0, np.int32), n_stops
    )


def _transfer_arrays(tt: Timetable, transfers: WalkTable | None) -> tuple[np.ndarray, ...]:
    tr = transfers if transfers is not None else empty_transfers(tt.n_stops)
    if tr.n_rows != tt.n_stops:
        raise ValueError(
            f"transfer table has {tr.n_rows} rows but the timetable has {tt.n_stops} stops "
            "(rebuild transfers after adding stops)"
        )
    return tr.indptr, tr.indices, tr.seconds


@dataclass(frozen=True, eq=False)
class RaptorResult:
    """Labels of one RAPTOR query.

    ``arrival[s]``: earliest arrival at stop ``s`` (INF = unreachable). ``rounds[k, s]``
    (= ``A``): best arrival with at most ``k`` rides; ``ride[k, s]`` (= ``T``): best
    arrival alighting in round ``k``. Parent arrays allow journey reconstruction.
    """

    dep_time: int
    arrival: I32
    rounds: I32
    ride: I32
    a_kind: npt.NDArray[np.int8]
    a_from: I32
    t_pat: I32
    t_trip: I32
    t_board: I32
    t_alight: I32
    last_round: int

    def reached(self) -> npt.NDArray[np.int64]:
        return np.flatnonzero(self.arrival < INF)

    def travel_time(self) -> npt.NDArray[np.int64]:
        """Seconds from ``dep_time`` to arrival at each stop (-1 if unreachable)."""
        out = self.arrival.astype(np.int64) - self.dep_time
        out[self.arrival == INF] = -1
        return out


def raptor(
    tt: Timetable,
    transfers: WalkTable | None,
    sources: npt.ArrayLike,
    dep_time: int,
    offsets: npt.ArrayLike | None = None,
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    board_slack: int = DEFAULT_BOARD_SLACK,
    max_duration: int | None = None,
    foot_round0: bool = False,
) -> RaptorResult:
    """One-to-all earliest-arrival RAPTOR.

    Args:
        tt: timetable.
        transfers: stop→stop footpaths (``None`` = no footpaths).
        sources: source stop indices.
        dep_time: departure time from the origin (s since midnight).
        offsets: per-source access walking time (s); default 0.
        max_rounds: maximum number of rides (4 = up to 3 transfers).
        board_slack: seconds required at a stop before every boarding.
        max_duration: prune labels later than ``dep_time + max_duration``.
        foot_round0: also allow a footpath right after the access walk.
    """
    src = np.atleast_1d(np.asarray(sources, dtype=np.int32))
    off = (
        np.zeros(len(src), np.int64)
        if offsets is None
        else np.atleast_1d(np.asarray(offsets, dtype=np.int64))
    )
    if len(off) != len(src):
        raise ValueError("offsets must align with sources")
    if len(src) and (src.min() < 0 or src.max() >= tt.n_stops):
        raise ValueError("source stop index out of range")
    times = (off + int(dep_time)).astype(np.int32)
    limit = int(INF) - 1 if max_duration is None else int(dep_time) + int(max_duration)
    res = raptor_query(
        *tt.raptor_arrays(),
        *_transfer_arrays(tt, transfers),
        src,
        times,
        int(max_rounds),
        int(board_slack),
        min(limit, int(INF) - 1),
        bool(foot_round0),
    )
    best, A, T, a_kind, a_from, t_pat, t_trip, t_board, t_alight, last = res
    return RaptorResult(
        int(dep_time), best, A, T, a_kind, a_from, t_pat, t_trip, t_board, t_alight, int(last)
    )


def raptor_from_access(
    tt: Timetable,
    transfers: WalkTable | None,
    access: WalkTable,
    row: int,
    dep_time: int,
    **kw: int | bool | None,
) -> RaptorResult:
    """RAPTOR from one row of an access table (origin → stops, seconds)."""
    stops, secs = access.row(row)
    return raptor(tt, transfers, stops, dep_time, secs, **kw)  # type: ignore[arg-type]


def raptor_batch(
    tt: Timetable,
    transfers: WalkTable | None,
    access: WalkTable,
    dep_times: npt.ArrayLike,
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    board_slack: int = DEFAULT_BOARD_SLACK,
    max_duration: int = 4 * 3600,
    foot_round0: bool = False,
) -> I32:
    """Parallel RAPTOR for every access row x departure time.

    Returns arrival int32 ``[n_origins, n_dep, n_stops]`` (INF = unreachable). Memory is
    ``4 · n_origins · n_dep · n_stops`` bytes; for accessibility use
    :func:`travel_time_matrix`, which reduces in-kernel.
    """
    if access.n_cols != tt.n_stops:
        raise ValueError("access table columns must be the timetable's stops")
    deps = np.asarray(dep_times, dtype=np.int64)
    out: I32 = raptor_many(
        *tt.raptor_arrays(),
        *_transfer_arrays(tt, transfers),
        access.indptr,
        access.indices,
        access.seconds.astype(np.int64),
        deps,
        int(max_rounds),
        int(board_slack),
        int(max_duration),
        bool(foot_round0),
    )
    return out


def travel_time_matrix(
    tt: Timetable,
    transfers: WalkTable | None,
    access: WalkTable,
    egress: WalkTable,
    dep_times: npt.ArrayLike,
    direct_walk: npt.NDArray[np.uint16] | None = None,
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    board_slack: int = DEFAULT_BOARD_SLACK,
    cap: int = 7200,
    min_reachable_frac: float = 0.5,
    foot_round0: bool = False,
) -> npt.NDArray[np.uint16]:
    """Door-to-door travel time (s) origins x destinations, averaged over departures.

    Args:
        access: origins → stops walking table (``n_origins x n_stops``).
        egress: stops → destinations walking table (``n_stops x n_dest``), e.g.
            ``build_access(graph, dests, stops).transpose()``.
        dep_times: departure times sampled over the analysis window (decision D-006).
        direct_walk: optional ``uint16 [n_origins, n_dest]`` walking-only times
            (65535 = no walk); combined per sample by element-wise minimum.
        cap: a sample is unreachable if its door-to-door time exceeds ``cap`` (s).
        min_reachable_frac: an OD is reachable iff at least
            ``ceil(min_reachable_frac · n_dep)`` samples are (minimum 1).

    Returns:
        ``uint16 [n_origins, n_dest]``: for reachable ODs, the mean over ALL samples
        where unreachable samples count as ``cap`` (a censored mean, monotone in service
        quality); 65535 for unreachable ODs.
    """
    if access.n_cols != tt.n_stops or egress.n_rows != tt.n_stops:
        raise ValueError("access columns and egress rows must be the timetable's stops")
    if not 0 < cap < UNREACHABLE_U16:
        raise ValueError("cap must be in (0, 65535)")
    deps = np.asarray(dep_times, dtype=np.int64)
    if len(deps) == 0:
        raise ValueError("need at least one departure time")
    n_dest = egress.n_cols
    if direct_walk is not None:
        dw = np.ascontiguousarray(direct_walk, dtype=np.uint16)
        if dw.shape != (access.n_rows, n_dest):
            raise ValueError(f"direct_walk must be {(access.n_rows, n_dest)}, got {dw.shape}")
    else:
        dw = np.zeros((1, 1), np.uint16)
    min_reach = max(1, math.ceil(min_reachable_frac * len(deps) - 1e-9))
    out: npt.NDArray[np.uint16] = travel_time_kernel(
        *tt.raptor_arrays(),
        *_transfer_arrays(tt, transfers),
        access.indptr,
        access.indices,
        access.seconds.astype(np.int64),
        egress.indptr,
        egress.indices,
        egress.seconds.astype(np.int64),
        int(n_dest),
        deps,
        dw,
        direct_walk is not None,
        int(max_rounds),
        int(board_slack),
        int(cap),
        int(min_reach),
        bool(foot_round0),
    )
    return out


def departure_samples(start: int, duration: int, step: int = 600) -> npt.NDArray[np.int64]:
    """Departure times ``start, start+step, ... < start+duration`` (D-006 default:
    every 10 min over the window)."""
    return np.arange(int(start), int(start) + int(duration), int(step), dtype=np.int64)


# ======================================================================== journeys


@dataclass(frozen=True)
class Leg:
    """One leg of a journey.

    ``mode``: ``"access"`` (origin → first stop), ``"walk"`` (footpath between stops) or
    ``"ride"``. ``from_stop`` is -1 for the access leg. For rides, ``pattern`` and
    ``trip`` (row within the pattern) identify the vehicle, ``board_pos``/``alight_pos``
    the positions in the pattern; ``depart`` is the vehicle departure (waiting before
    it is implicit).
    """

    mode: Literal["access", "walk", "ride"]
    from_stop: int
    to_stop: int
    depart: int
    arrive: int
    pattern: int = -1
    trip: int = -1
    board_pos: int = -1
    alight_pos: int = -1

    @property
    def duration(self) -> int:
        return self.arrive - self.depart


def best_round(res: RaptorResult, stop: int) -> int:
    """Fewest rides achieving the earliest arrival at ``stop`` (-1 if unreachable)."""
    if res.arrival[stop] == INF:
        return -1
    ks = np.flatnonzero(res.rounds[:, stop] == res.arrival[stop])
    return int(ks[0])


def reconstruct_journey(tt: Timetable, res: RaptorResult, target_stop: int) -> list[Leg] | None:
    """Legs of the earliest-arrival (then fewest-rides) journey to ``target_stop``."""
    k = best_round(res, target_stop)
    if k < 0:
        return None
    legs: list[Leg] = []
    s = int(target_stop)
    for _ in range(4 * (res.rounds.shape[0] + 1)):
        while k > 0 and res.a_kind[k, s] == KIND_NONE:
            k -= 1
        kind = int(res.a_kind[k, s])
        if kind == KIND_ACCESS:
            legs.append(Leg("access", -1, s, res.dep_time, int(res.rounds[0, s])))
            legs.reverse()
            return legs
        if kind == KIND_FOOT:
            src = int(res.a_from[k, s])
            start = int(res.ride[k, src]) if k > 0 else int(res.rounds[0, src])
            legs.append(Leg("walk", src, s, start, int(res.rounds[k, s])))
            s = src
            if k == 0:
                continue  # access label at (0, src)
        elif kind != KIND_RIDE:
            raise RuntimeError(f"inconsistent labels at round {k}, stop {s}")
        # ride label T[k, s]
        p = int(res.t_pat[k, s])
        trip = int(res.t_trip[k, s])
        bpos = int(res.t_board[k, s])
        apos = int(res.t_alight[k, s])
        seq = tt.pattern_stop_seq(p)
        board_stop = int(seq[bpos])
        legs.append(
            Leg(
                "ride",
                board_stop,
                s,
                int(tt.departures(p)[trip, bpos]),
                int(tt.arrivals(p)[trip, apos]),
                pattern=p,
                trip=trip,
                board_pos=bpos,
                alight_pos=apos,
            )
        )
        s = board_stop
        k -= 1
    raise RuntimeError("journey reconstruction did not terminate")


__all__ = [
    "DEFAULT_BOARD_SLACK",
    "DEFAULT_MAX_ROUNDS",
    "INF",
    "KIND_ACCESS",
    "KIND_FOOT",
    "KIND_NONE",
    "KIND_RIDE",
    "UNREACHABLE_U16",
    "Leg",
    "RaptorResult",
    "best_round",
    "departure_samples",
    "empty_transfers",
    "raptor",
    "raptor_batch",
    "raptor_from_access",
    "reconstruct_journey",
    "travel_time_matrix",
]
