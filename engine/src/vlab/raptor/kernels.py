"""Numba kernels of the round-based RAPTOR algorithm (Delling, Pajor & Werneck 2012).

Semantics (exactly what the kernels compute, and what the reference implementation in
the tests reproduces):

- A journey is: walk access to a source stop (given offset) → ride → [one optional
  footpath] → ride → [footpath] ... with at most ``max_rounds`` rides.
- Boarding a trip at stop ``s`` requires ``dep(trip, s) >= arrival_at(s) + board_slack``
  for every boarding (including the first one).
- Footpaths (transfer table) are relaxed once after each round, only from stops reached
  *by a ride* in that round (no footpath chains, no footpath right after access unless
  ``foot_round0``).

Two labels per (round k, stop s) make this exact even though the transfer table is not
transitively closed:

- ``T[k, s]``: earliest arrival at ``s`` alighting from a ride in round ``k`` (only
  these labels may start a footpath);
- ``A[k, s]``: earliest arrival at ``s`` with at most ``k`` rides by any means (only
  these labels are used to board in round ``k+1``).

Pruning: a ride arrival is kept only if it improves the best *ride* arrival so far
(``tbest``); ``A`` labels only if they improve ``best`` (local pruning), and every label
must be <= ``max_arrival`` (target/time pruning).
"""

from __future__ import annotations

import numba as nb
import numpy as np

INF = np.int32(2**31 - 1)

KIND_NONE = 0  # label inherited from round k-1 (or unreachable)
KIND_RIDE = 1
KIND_FOOT = 2
KIND_ACCESS = 3

# Kernels are compiled by numba; line coverage cannot trace them (``pragma: no cover``).


@nb.njit(cache=True)
def raptor_core(  # type: ignore[no-untyped-def]  # pragma: no cover
    ps_ptr,
    ps,
    pt_ptr,
    ptm_ptr,
    arr,
    dep,
    sp_ptr,
    sp_pat,
    sp_pos,
    tr_ptr,
    tr_to,
    tr_sec,
    src_stops,
    src_times,
    max_rounds,
    board_slack,
    max_arrival,
    foot_round0,
    A,
    T,
    a_kind,
    a_from,
    t_pat,
    t_trip,
    t_board,
    t_alight,
    best,
    tbest,
    marked,
    mark_list,
    tm_flag,
    tm_list,
    pat_first,
    pat_list,
):
    """One RAPTOR query writing into caller-provided buffers.

    Label buffers (``A``, ``T``, parents: ``[max_rounds+1, S]``; ``best``/``tbest``:
    ``[S]``) are fully (re)initialised here. Scratch buffers ``marked``/``tm_flag`` must be
    all False, ``pat_first`` all -1 on entry; they are left in that state on exit.
    Returns the number of the last round that was run.
    """
    n_stops = best.shape[0]
    for s in range(n_stops):
        best[s] = INF
        tbest[s] = INF
    for k in range(max_rounds + 1):
        for s in range(n_stops):
            A[k, s] = INF
            T[k, s] = INF
            a_kind[k, s] = KIND_NONE

    n_marked = 0
    for i in range(src_stops.shape[0]):
        s = src_stops[i]
        t = src_times[i]
        if t < A[0, s] and t <= max_arrival:
            A[0, s] = t
            best[s] = t
            a_kind[0, s] = KIND_ACCESS
            if not marked[s]:
                marked[s] = True
                mark_list[n_marked] = s
                n_marked += 1
    if foot_round0:
        n0 = n_marked
        for i in range(n0):
            s = mark_list[i]
            ts = A[0, s]
            for j in range(tr_ptr[s], tr_ptr[s + 1]):
                s2 = tr_to[j]
                v = ts + tr_sec[j]
                # source labels are never overwritten, so footpaths never chain here
                if v < best[s2] and v <= max_arrival and a_kind[0, s2] != KIND_ACCESS:
                    best[s2] = v
                    A[0, s2] = v
                    a_kind[0, s2] = KIND_FOOT
                    a_from[0, s2] = s
                    if not marked[s2]:
                        marked[s2] = True
                        mark_list[n_marked] = s2
                        n_marked += 1

    last_round = 0
    for k in range(1, max_rounds + 1):
        if n_marked == 0:
            break
        last_round = k
        for s in range(n_stops):
            A[k, s] = A[k - 1, s]
        # -- collect patterns serving marked stops, with the earliest marked position
        n_pat = 0
        for i in range(n_marked):
            s = mark_list[i]
            marked[s] = False
            for j in range(sp_ptr[s], sp_ptr[s + 1]):
                p = sp_pat[j]
                pos = sp_pos[j]
                if pat_first[p] < 0:
                    pat_first[p] = pos
                    pat_list[n_pat] = p
                    n_pat += 1
                elif pos < pat_first[p]:
                    pat_first[p] = pos
        n_marked = 0
        n_tm = 0
        # -- scan patterns
        for ip in range(n_pat):
            p = pat_list[ip]
            first = pat_first[p]
            pat_first[p] = -1
            base = ps_ptr[p]
            n_s = ps_ptr[p + 1] - base
            n_t = pt_ptr[p + 1] - pt_ptr[p]
            toff = ptm_ptr[p]
            trip = -1
            board_pos = -1
            for i in range(first, n_s):
                s = ps[base + i]
                if trip >= 0:
                    a = arr[toff + trip * n_s + i]
                    if a < tbest[s] and a <= max_arrival:
                        tbest[s] = a
                        T[k, s] = a
                        t_pat[k, s] = p
                        t_trip[k, s] = trip
                        t_board[k, s] = board_pos
                        t_alight[k, s] = i
                        if not tm_flag[s]:
                            tm_flag[s] = True
                            tm_list[n_tm] = s
                            n_tm += 1
                        if a < best[s]:
                            best[s] = a
                            A[k, s] = a
                            a_kind[k, s] = KIND_RIDE
                            if not marked[s]:
                                marked[s] = True
                                mark_list[n_marked] = s
                                n_marked += 1
                prev = A[k - 1, s]
                if prev < INF:
                    need = prev + board_slack
                    if trip < 0 or need <= dep[toff + trip * n_s + i]:
                        hi = n_t if trip < 0 else trip
                        lo = 0
                        h = hi
                        while lo < h:
                            mid = (lo + h) >> 1
                            if dep[toff + mid * n_s + i] >= need:
                                h = mid
                            else:
                                lo = mid + 1
                        if lo < hi:
                            trip = lo
                            board_pos = i
        # -- footpaths from stops reached by a ride in this round
        for i in range(n_tm):
            s = tm_list[i]
            tm_flag[s] = False
            ts = T[k, s]
            for j in range(tr_ptr[s], tr_ptr[s + 1]):
                s2 = tr_to[j]
                v = ts + tr_sec[j]
                if v < best[s2] and v <= max_arrival:
                    best[s2] = v
                    A[k, s2] = v
                    a_kind[k, s2] = KIND_FOOT
                    a_from[k, s2] = s
                    if not marked[s2]:
                        marked[s2] = True
                        mark_list[n_marked] = s2
                        n_marked += 1
    for i in range(n_marked):
        marked[mark_list[i]] = False
    # rounds not run (nothing marked): labels are those of the last round run
    for k in range(last_round + 1, max_rounds + 1):
        for s in range(n_stops):
            A[k, s] = A[last_round, s]
    return last_round


@nb.njit(cache=True)
def _alloc(n_rounds, n_stops, n_patterns):  # type: ignore[no-untyped-def]  # pragma: no cover
    shape = (n_rounds + 1, n_stops)
    return (
        np.empty(shape, np.int32),  # A
        np.empty(shape, np.int32),  # T
        np.zeros(shape, np.int8),  # a_kind
        np.full(shape, -1, np.int32),  # a_from
        np.full(shape, -1, np.int32),  # t_pat
        np.full(shape, -1, np.int32),  # t_trip
        np.full(shape, -1, np.int32),  # t_board
        np.full(shape, -1, np.int32),  # t_alight
        np.empty(n_stops, np.int32),  # best
        np.empty(n_stops, np.int32),  # tbest
        np.zeros(n_stops, np.bool_),  # marked
        np.empty(n_stops, np.int32),  # mark_list
        np.zeros(n_stops, np.bool_),  # tm_flag
        np.empty(n_stops, np.int32),  # tm_list
        np.full(n_patterns, -1, np.int32),  # pat_first
        np.empty(n_patterns, np.int32),  # pat_list
    )


@nb.njit(cache=True)
def raptor_query(  # type: ignore[no-untyped-def]  # pragma: no cover
    ps_ptr,
    ps,
    pt_ptr,
    ptm_ptr,
    arr,
    dep,
    sp_ptr,
    sp_pat,
    sp_pos,
    tr_ptr,
    tr_to,
    tr_sec,
    src_stops,
    src_times,
    max_rounds,
    board_slack,
    max_arrival,
    foot_round0,
):
    """Allocate buffers and run one query. Returns all label/parent arrays."""
    n_stops = sp_ptr.shape[0] - 1
    n_pat = ps_ptr.shape[0] - 1
    (
        A,
        T,
        a_kind,
        a_from,
        t_pat,
        t_trip,
        t_board,
        t_alight,
        best,
        tbest,
        marked,
        mark_list,
        tm_flag,
        tm_list,
        pat_first,
        pat_list,
    ) = _alloc(max_rounds, n_stops, n_pat)
    last = raptor_core(
        ps_ptr,
        ps,
        pt_ptr,
        ptm_ptr,
        arr,
        dep,
        sp_ptr,
        sp_pat,
        sp_pos,
        tr_ptr,
        tr_to,
        tr_sec,
        src_stops,
        src_times,
        max_rounds,
        board_slack,
        max_arrival,
        foot_round0,
        A,
        T,
        a_kind,
        a_from,
        t_pat,
        t_trip,
        t_board,
        t_alight,
        best,
        tbest,
        marked,
        mark_list,
        tm_flag,
        tm_list,
        pat_first,
        pat_list,
    )
    return best, A, T, a_kind, a_from, t_pat, t_trip, t_board, t_alight, last


@nb.njit(cache=True, parallel=True)
def raptor_many(  # type: ignore[no-untyped-def]  # pragma: no cover
    ps_ptr,
    ps,
    pt_ptr,
    ptm_ptr,
    arr,
    dep,
    sp_ptr,
    sp_pat,
    sp_pos,
    tr_ptr,
    tr_to,
    tr_sec,
    acc_ptr,
    acc_stop,
    acc_sec,
    dep_times,
    max_rounds,
    board_slack,
    max_duration,
    foot_round0,
):
    """Arrival at every stop for each origin (access CSR row) x departure time.

    Returns int32 ``[n_origins, n_dep, n_stops]`` (INF = unreachable). Labels later than
    ``dep_time + max_duration`` are pruned.
    """
    n_o = acc_ptr.shape[0] - 1
    n_dep = dep_times.shape[0]
    n_stops = sp_ptr.shape[0] - 1
    n_pat = ps_ptr.shape[0] - 1
    out = np.empty((n_o, n_dep, n_stops), np.int32)
    for o in nb.prange(n_o):
        (
            A,
            T,
            a_kind,
            a_from,
            t_pat,
            t_trip,
            t_board,
            t_alight,
            best,
            tbest,
            marked,
            mark_list,
            tm_flag,
            tm_list,
            pat_first,
            pat_list,
        ) = _alloc(max_rounds, n_stops, n_pat)
        a, b = acc_ptr[o], acc_ptr[o + 1]
        stops = acc_stop[a:b]
        for d in range(n_dep):
            t0 = dep_times[d]
            times = (acc_sec[a:b] + t0).astype(np.int32)
            raptor_core(
                ps_ptr,
                ps,
                pt_ptr,
                ptm_ptr,
                arr,
                dep,
                sp_ptr,
                sp_pat,
                sp_pos,
                tr_ptr,
                tr_to,
                tr_sec,
                stops,
                times,
                max_rounds,
                board_slack,
                t0 + max_duration,
                foot_round0,
                A,
                T,
                a_kind,
                a_from,
                t_pat,
                t_trip,
                t_board,
                t_alight,
                best,
                tbest,
                marked,
                mark_list,
                tm_flag,
                tm_list,
                pat_first,
                pat_list,
            )
            out[o, d, :] = best
    return out


@nb.njit(cache=True, parallel=True)
def travel_time_kernel(  # type: ignore[no-untyped-def]  # pragma: no cover
    ps_ptr,
    ps,
    pt_ptr,
    ptm_ptr,
    arr,
    dep,
    sp_ptr,
    sp_pat,
    sp_pos,
    tr_ptr,
    tr_to,
    tr_sec,
    acc_ptr,
    acc_stop,
    acc_sec,
    egr_ptr,
    egr_dst,
    egr_sec,
    n_dest,
    dep_times,
    direct,
    use_direct,
    max_rounds,
    board_slack,
    cap,
    min_reachable,
    foot_round0,
):
    """Mean door-to-door travel time over departure samples, origins x destinations.

    For each origin ``o`` and departure ``t0``: RAPTOR from the access row → best arrival
    per stop → ``min_s(arr[s] - t0 + egress[s, d])`` → optionally ``min`` with the
    direct-walk time ``direct[o, d]`` → sample value (unreachable if > ``cap``).
    Aggregation per OD: reachable iff at least ``min_reachable`` samples are reachable;
    value = mean over ALL samples with unreachable samples counted as ``cap``
    (censored mean). Unreachable ODs are 65535. Output uint16 ``[n_origins, n_dest]``.
    """
    n_o = acc_ptr.shape[0] - 1
    n_dep = dep_times.shape[0]
    n_stops = sp_ptr.shape[0] - 1
    n_pat = ps_ptr.shape[0] - 1
    out = np.empty((n_o, n_dest), np.uint16)
    for o in nb.prange(n_o):
        (
            A,
            T,
            a_kind,
            a_from,
            t_pat,
            t_trip,
            t_board,
            t_alight,
            best,
            tbest,
            marked,
            mark_list,
            tm_flag,
            tm_list,
            pat_first,
            pat_list,
        ) = _alloc(max_rounds, n_stops, n_pat)
        sums = np.zeros(n_dest, np.int64)
        cnt = np.zeros(n_dest, np.int32)
        sample = np.empty(n_dest, np.int32)
        a, b = acc_ptr[o], acc_ptr[o + 1]
        stops = acc_stop[a:b]
        for d in range(n_dep):
            t0 = dep_times[d]
            times = (acc_sec[a:b] + t0).astype(np.int32)
            raptor_core(
                ps_ptr,
                ps,
                pt_ptr,
                ptm_ptr,
                arr,
                dep,
                sp_ptr,
                sp_pat,
                sp_pos,
                tr_ptr,
                tr_to,
                tr_sec,
                stops,
                times,
                max_rounds,
                board_slack,
                t0 + cap,
                foot_round0,
                A,
                T,
                a_kind,
                a_from,
                t_pat,
                t_trip,
                t_board,
                t_alight,
                best,
                tbest,
                marked,
                mark_list,
                tm_flag,
                tm_list,
                pat_first,
                pat_list,
            )
            for z in range(n_dest):
                sample[z] = cap + 1
            if use_direct:
                for z in range(n_dest):
                    w = direct[o, z]
                    if w < sample[z]:
                        sample[z] = w
            for s in range(n_stops):
                bs = best[s]
                if bs == INF:
                    continue
                el = bs - t0
                if el > cap:
                    continue
                for j in range(egr_ptr[s], egr_ptr[s + 1]):
                    v = el + egr_sec[j]
                    z = egr_dst[j]
                    if v < sample[z]:
                        sample[z] = v
            for z in range(n_dest):
                v = sample[z]
                if v <= cap:
                    sums[z] += v
                    cnt[z] += 1
                else:
                    sums[z] += cap
        for z in range(n_dest):
            if cnt[z] >= min_reachable:
                out[o, z] = np.uint16((sums[z] + n_dep // 2) // n_dep)
            else:
                out[o, z] = np.uint16(65535)
    return out
