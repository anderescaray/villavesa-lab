"""Numba kernels: bounded multi-source Dijkstra on a CSR graph (binary heap).

All kernels take the graph as ``(indptr, indices, weight)`` with float32/float64 edge
weights in metres. A *source group* is a set of start nodes with initial offsets (the
straight-line distance from an off-network point to its candidate snap nodes); a
*target* likewise maps to several nodes with offsets, and its distance is the minimum
over them.
"""

from __future__ import annotations

import numba as nb
import numpy as np

# The kernels below are excluded from coverage: numba compiles them, so line tracing
# never sees them execute. They are exercised by the walk tests.


@nb.njit(cache=True, inline="always")
def _heap_push(hk, hv, size, key, val):  # type: ignore[no-untyped-def]  # pragma: no cover
    i = size
    hk[i] = key
    hv[i] = val
    while i > 0:
        parent = (i - 1) >> 1
        if hk[parent] <= hk[i]:
            break
        hk[parent], hk[i] = hk[i], hk[parent]
        hv[parent], hv[i] = hv[i], hv[parent]
        i = parent
    return size + 1


@nb.njit(cache=True, inline="always")
def _heap_pop(hk, hv, size):  # type: ignore[no-untyped-def]  # pragma: no cover
    key = hk[0]
    val = hv[0]
    size -= 1
    hk[0] = hk[size]
    hv[0] = hv[size]
    i = 0
    while True:
        left = 2 * i + 1
        if left >= size:
            break
        child = left
        right = left + 1
        if right < size and hk[right] < hk[left]:
            child = right
        if hk[i] <= hk[child]:
            break
        hk[i], hk[child] = hk[child], hk[i]
        hv[i], hv[child] = hv[child], hv[i]
        i = child
    return key, val, size


@nb.njit(cache=True)
def dijkstra_scratch(  # type: ignore[no-untyped-def]  # pragma: no cover
    indptr, indices, weight, src_nodes, src_off, cutoff, dist, touched, hk, hv, pred, use_pred
):
    """Bounded multi-source Dijkstra using caller-provided scratch buffers.

    ``dist`` must be +inf everywhere on entry; on exit it holds the distances of the
    ``n`` returned nodes ``touched[:n]`` (all with dist <= cutoff, settled or not).
    The caller must reset ``dist[touched[:n]] = inf`` before reusing the buffers.
    ``hk``/``hv`` need capacity >= len(indices) + len(src_nodes).
    """
    n_touched = 0
    size = 0
    for i in range(len(src_nodes)):
        u = src_nodes[i]
        d = src_off[i]
        if d <= cutoff and d < dist[u]:
            if dist[u] == np.inf:
                touched[n_touched] = u
                n_touched += 1
            dist[u] = d
            if use_pred:
                pred[u] = -1
            size = _heap_push(hk, hv, size, d, u)
    while size > 0:
        d, u, size = _heap_pop(hk, hv, size)
        if d > dist[u]:
            continue
        for e in range(indptr[u], indptr[u + 1]):
            v = indices[e]
            nd = d + weight[e]
            if nd <= cutoff and nd < dist[v]:
                if dist[v] == np.inf:
                    touched[n_touched] = v
                    n_touched += 1
                dist[v] = nd
                if use_pred:
                    pred[v] = u
                size = _heap_push(hk, hv, size, nd, v)
    return n_touched


@nb.njit(cache=True)
def _collect(  # type: ignore[no-untyped-def]  # pragma: no cover
    dist, touched, n_touched, node_tgt_ptr, node_tgt, node_tgt_off, best, best_list, cutoff
):
    """Min distance to each target reached; returns number of distinct targets."""
    n_best = 0
    for i in range(n_touched):
        u = touched[i]
        du = dist[u]
        for j in range(node_tgt_ptr[u], node_tgt_ptr[u + 1]):
            t = node_tgt[j]
            d = du + node_tgt_off[j]
            if d <= cutoff and d < best[t]:
                if best[t] == np.inf:
                    best_list[n_best] = t
                    n_best += 1
                best[t] = d
    return n_best


@nb.njit(cache=True)
def _m2m_chunk(  # type: ignore[no-untyped-def]  # pragma: no cover
    c,
    n_chunks,
    fill,
    indptr,
    indices,
    weight,
    src_ptr,
    src_nodes,
    src_off,
    node_tgt_ptr,
    node_tgt,
    node_tgt_off,
    n_targets,
    cutoff,
    exclude_self,
    counts,
    ptr,
    out_t,
    out_d,
):
    """Sources ``c, c + n_chunks, ...``: count results (``fill=False``) or write them."""
    n_src = len(src_ptr) - 1
    n_nodes = len(indptr) - 1
    cap = len(indices) + len(src_nodes) + 1
    dist = np.full(n_nodes, np.inf)
    touched = np.empty(n_nodes, dtype=np.int64)
    hk = np.empty(cap, dtype=np.float64)
    hv = np.empty(cap, dtype=np.int64)
    pred = np.empty(1, dtype=np.int64)
    best = np.full(n_targets, np.inf)
    best_list = np.empty(n_targets, dtype=np.int64)
    for s in range(c, n_src, n_chunks):
        a, b = src_ptr[s], src_ptr[s + 1]
        nt = dijkstra_scratch(
            indptr,
            indices,
            weight,
            src_nodes[a:b],
            src_off[a:b],
            cutoff,
            dist,
            touched,
            hk,
            hv,
            pred,
            False,
        )
        n_best = _collect(
            dist, touched, nt, node_tgt_ptr, node_tgt, node_tgt_off, best, best_list, cutoff
        )
        if fill:
            sel = np.sort(best_list[:n_best])
            w = ptr[s]
            for k in range(n_best):
                t = sel[k]
                if not (exclude_self and t == s):
                    out_t[w] = t
                    out_d[w] = best[t]
                    w += 1
                best[t] = np.inf
        else:
            cnt = n_best
            for k in range(n_best):
                t = best_list[k]
                if exclude_self and t == s:
                    cnt -= 1
                best[t] = np.inf
            counts[s] = cnt
        for k in range(nt):
            dist[touched[k]] = np.inf


@nb.njit(cache=True, parallel=True)
def _m2m_parallel(n_chunks, fill, *args):  # type: ignore[no-untyped-def]  # pragma: no cover
    for c in nb.prange(n_chunks):
        _m2m_chunk(c, n_chunks, fill, *args)


@nb.njit(cache=True)
def _m2m_serial(n_chunks, fill, *args):  # type: ignore[no-untyped-def]  # pragma: no cover
    for c in range(n_chunks):
        _m2m_chunk(c, n_chunks, fill, *args)


def many_to_many(
    indptr: np.ndarray,
    indices: np.ndarray,
    weight: np.ndarray,
    src_ptr: np.ndarray,
    src_nodes: np.ndarray,
    src_off: np.ndarray,
    node_tgt_ptr: np.ndarray,
    node_tgt: np.ndarray,
    node_tgt_off: np.ndarray,
    n_targets: int,
    cutoff: float,
    exclude_self: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bounded network distances from every source group to every target.

    Sources: group ``i`` = nodes ``src_nodes[src_ptr[i]:src_ptr[i+1]]`` with offsets.
    Targets: per-node CSR ``node_tgt_ptr`` (len n_nodes+1) -> target ids and offsets.
    Returns CSR ``(ptr int64, tgt int32, dist float64)`` sorted by target within a row.
    ``exclude_self`` drops target ``i`` from row ``i``. Two passes (count, fill); small
    batches run serially (a parallel launch costs more than a single bounded search,
    especially on a busy machine).
    """
    n_src = len(src_ptr) - 1
    n_chunks = max(1, min(n_src, 64))
    run = _m2m_parallel if n_src > 8 else _m2m_serial
    counts = np.zeros(max(n_src, 1), dtype=np.int64)
    dummy_t = np.empty(0, dtype=np.int32)
    dummy_d = np.empty(0, dtype=np.float64)
    ptr = np.zeros(n_src + 1, dtype=np.int64)
    common = (
        indptr,
        indices,
        weight,
        src_ptr,
        src_nodes,
        src_off,
        node_tgt_ptr,
        node_tgt,
        node_tgt_off,
        n_targets,
        cutoff,
        exclude_self,
    )
    if n_src == 0:
        return ptr, dummy_t, dummy_d
    run(n_chunks, False, *common, counts, ptr, dummy_t, dummy_d)
    np.cumsum(counts[:n_src], out=ptr[1:])
    out_t = np.empty(int(ptr[-1]), dtype=np.int32)
    out_d = np.empty(int(ptr[-1]), dtype=np.float64)
    run(n_chunks, True, *common, counts, ptr, out_t, out_d)
    return ptr, out_t, out_d


@nb.njit(cache=True)
def shortest_path_nodes(  # type: ignore[no-untyped-def]  # pragma: no cover
    indptr, indices, weight, src_nodes, src_off, tgt_nodes, tgt_off, cutoff
):
    """Shortest path between two node groups. Returns ``(length, end_node, pred)``;
    ``end_node == -1`` when unreachable within ``cutoff``. Follow ``pred`` from
    ``end_node`` back to a source node (pred == -1)."""
    n_nodes = len(indptr) - 1
    dist = np.full(n_nodes, np.inf)
    pred = np.full(n_nodes, -1, dtype=np.int64)
    is_tgt = np.full(n_nodes, np.inf)
    for i in range(len(tgt_nodes)):
        is_tgt[tgt_nodes[i]] = min(is_tgt[tgt_nodes[i]], tgt_off[i])
    cap = len(indices) + len(src_nodes) + 1
    hk = np.empty(cap, dtype=np.float64)
    hv = np.empty(cap, dtype=np.int64)
    size = 0
    for i in range(len(src_nodes)):
        u = src_nodes[i]
        if src_off[i] < dist[u]:
            dist[u] = src_off[i]
            size = _heap_push(hk, hv, size, src_off[i], u)
    best = np.inf
    best_node = -1
    while size > 0:
        d, u, size = _heap_pop(hk, hv, size)
        if d > dist[u]:
            continue
        if d >= best or d > cutoff:
            break
        if is_tgt[u] < np.inf and d + is_tgt[u] < best:
            best = d + is_tgt[u]
            best_node = u
        for e in range(indptr[u], indptr[u + 1]):
            v = indices[e]
            nd = d + weight[e]
            if nd < dist[v]:
                dist[v] = nd
                pred[v] = u
                size = _heap_push(hk, hv, size, nd, v)
    return best, best_node, pred
