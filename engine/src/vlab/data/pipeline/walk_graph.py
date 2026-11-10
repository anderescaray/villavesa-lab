"""Pedestrian graph from OSM ways.

Graph nodes are way intersections and way ends, plus interpolated nodes so that
no edge is longer than :data:`~vlab.data.pipeline.common.MAX_EDGE_M`. Edge
lengths are the true polyline lengths in EPSG:25830. Only the largest connected
component is kept. The output is a symmetric CSR adjacency.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import shapely
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from shapely.geometry.base import BaseGeometry

from vlab.data.pipeline.common import MAX_EDGE_M, log

WALKABLE_HIGHWAYS = frozenset(
    {
        "footway", "path", "pedestrian", "steps", "residential", "living_street", "service",
        "tertiary", "tertiary_link", "secondary", "secondary_link", "primary", "primary_link",
        "unclassified", "track", "cycleway", "road", "bridleway", "corridor", "crossing",
        "elevator",
    }
)  # fmt: skip
# Roads that are walkable only with explicit pedestrian provisions.
FAST_ROADS = frozenset({"motorway", "motorway_link", "trunk", "trunk_link"})
FOOT_YES = frozenset({"yes", "designated", "permissive", "official", "destination"})
NO_ACCESS = frozenset({"no", "private"})
SIDEWALK_YES = frozenset({"both", "left", "right", "yes", "separate"})


def is_walkable(tags: Mapping[str, str]) -> bool:
    """Whether an OSM way with these tags can be walked on (explicit, documented rules)."""
    hw = tags.get("highway", "")
    foot = tags.get("foot", "")
    if foot == "no" or tags.get("indoor") == "yes":
        return False
    if hw in FAST_ROADS or tags.get("motorroad") == "yes":
        sidewalk = tags.get("sidewalk", tags.get("sidewalk:both", ""))
        # A separately mapped sidewalk is already its own footway: do not walk the carriageway.
        return foot in FOOT_YES or (sidewalk in SIDEWALK_YES and sidewalk != "separate")
    if hw not in WALKABLE_HIGHWAYS:
        return False
    return not (tags.get("access") in NO_ACCESS and foot not in FOOT_YES)


@dataclass(frozen=True)
class WalkGraphArrays:
    """Symmetric CSR pedestrian graph (coordinates in EPSG:25830 and WGS84)."""

    x: npt.NDArray[np.float64]
    y: npt.NDArray[np.float64]
    indptr: npt.NDArray[np.int32]
    indices: npt.NDArray[np.int32]
    length_m: npt.NDArray[np.float32]

    @property
    def n_nodes(self) -> int:
        return int(self.x.shape[0])

    @property
    def n_edges(self) -> int:
        """Undirected edges (each stored twice in the CSR)."""
        return int(self.indices.shape[0] // 2)


def build_walk_graph(
    way_nodes: Sequence[npt.NDArray[np.int64]],
    way_x: Sequence[npt.NDArray[np.float64]],
    way_y: Sequence[npt.NDArray[np.float64]],
    clip: BaseGeometry | None = None,
    max_edge_m: float = MAX_EDGE_M,
) -> WalkGraphArrays:
    """Build the graph from walkable ways (node ids and projected coordinates).

    ``clip`` (EPSG:25830) drops every OSM segment that is not fully inside it.
    """
    # 1. Graph nodes: way ends and nodes shared by several ways (or repeated in one).
    all_ids = np.concatenate(way_nodes)
    uniq, counts = np.unique(all_ids, return_counts=True)
    shared = set(uniq[counts >= 2].tolist())
    for ids in way_nodes:
        shared.add(int(ids[0]))
        shared.add(int(ids[-1]))

    if clip is not None:
        shapely.prepare(clip)
        inside_flat = shapely.contains_xy(clip, np.concatenate(way_x), np.concatenate(way_y))
        splits = np.cumsum([len(a) for a in way_nodes])[:-1]
        inside_per_way = np.split(inside_flat, splits)
    else:
        inside_per_way = [np.ones(len(a), dtype=bool) for a in way_nodes]

    osm_index: dict[int, int] = {}
    node_x: list[float] = []
    node_y: list[float] = []

    def node_of(osm_id: int, x: float, y: float) -> int:
        idx = osm_index.get(osm_id)
        if idx is None:
            idx = len(node_x)
            osm_index[osm_id] = idx
            node_x.append(x)
            node_y.append(y)
        return idx

    eu: list[int] = []
    ev: list[int] = []
    el: list[float] = []

    # 2. Split each way at graph nodes, drop pieces leaving the clip, densify.
    for ids, xs_w, ys_w, inside in zip(way_nodes, way_x, way_y, inside_per_way, strict=True):
        start = 0
        n = len(ids)
        for k in range(1, n):
            if int(ids[k]) not in shared and k != n - 1:
                continue
            seg = slice(start, k + 1)
            sx, sy = xs_w[seg], ys_w[seg]
            ok = bool(inside[seg].all())
            a_id, b_id = int(ids[start]), int(ids[k])
            start = k
            if not ok or (a_id == b_id and len(sx) < 3):
                continue
            step = np.hypot(np.diff(sx), np.diff(sy))
            total = float(step.sum())
            if total <= 0.0:
                continue
            u = node_of(a_id, float(sx[0]), float(sy[0]))
            v = node_of(b_id, float(sx[-1]), float(sy[-1]))
            pieces = max(1, math.ceil(total / max_edge_m - 1e-9))
            if pieces == 1:
                eu.append(u)
                ev.append(v)
                el.append(total)
                continue
            cum = np.concatenate([[0.0], np.cumsum(step)])
            targets = np.linspace(0.0, total, pieces + 1)[1:-1]
            ix = np.interp(targets, cum, sx)
            iy = np.interp(targets, cum, sy)
            chain = [u]
            for px, py in zip(ix, iy, strict=True):
                chain.append(len(node_x))
                node_x.append(float(px))
                node_y.append(float(py))
            chain.append(v)
            piece = total / pieces
            for p, q in itertools.pairwise(chain):
                eu.append(p)
                ev.append(q)
                el.append(piece)

    if not eu:
        raise ValueError("no walkable edges inside the clip area")
    x = np.asarray(node_x)
    y = np.asarray(node_y)
    u_arr = np.asarray(eu, dtype=np.int64)
    v_arr = np.asarray(ev, dtype=np.int64)
    l_arr = np.asarray(el, dtype=np.float64)

    # 3. Drop self loops, keep the shortest of parallel edges.
    keep = u_arr != v_arr
    u_arr, v_arr, l_arr = u_arr[keep], v_arr[keep], l_arr[keep]
    lo, hi = np.minimum(u_arr, v_arr), np.maximum(u_arr, v_arr)
    order = np.lexsort((l_arr, hi, lo))
    lo, hi, l_arr = lo[order], hi[order], l_arr[order]
    first = np.ones(len(lo), dtype=bool)
    first[1:] = (lo[1:] != lo[:-1]) | (hi[1:] != hi[:-1])
    lo, hi, l_arr = lo[first], hi[first], l_arr[first]

    # 4. Largest connected component.
    n_all = len(x)
    adj = sparse.coo_matrix((np.ones(len(lo)), (lo, hi)), shape=(n_all, n_all)).tocsr()
    n_comp, labels = connected_components(adj, directed=False)
    used = np.zeros(n_all, dtype=bool)
    used[lo] = True
    used[hi] = True
    sizes = np.bincount(labels[used], minlength=n_comp)
    main = int(np.argmax(sizes))
    keep_node = used & (labels == main)
    log.info(
        "  walk graph: %d components, largest has %d of %d nodes (%.1f%%)",
        n_comp - int((~used).sum()), int(keep_node.sum()), int(used.sum()),
        100.0 * keep_node.sum() / max(1, used.sum()),
    )  # fmt: skip

    # 5. Deterministic spatial ordering (rows of 200 m, then x) and reindexing.
    old = np.flatnonzero(keep_node)
    order_nodes = np.lexsort((x[old], np.floor(y[old] / 200.0)))
    old = old[order_nodes]
    new_of_old = np.full(n_all, -1, dtype=np.int64)
    new_of_old[old] = np.arange(len(old))
    e_keep = keep_node[lo] & keep_node[hi]
    a = new_of_old[lo[e_keep]]
    b = new_of_old[hi[e_keep]]
    w = l_arr[e_keep]
    n = len(old)
    rows = np.concatenate([a, b])
    cols = np.concatenate([b, a])
    vals = np.concatenate([w, w])
    csr = sparse.csr_matrix((vals, (rows, cols)), shape=(n, n))
    csr.sort_indices()
    return WalkGraphArrays(
        x=x[old],
        y=y[old],
        indptr=csr.indptr.astype(np.int32),
        indices=csr.indices.astype(np.int32),
        length_m=csr.data.astype(np.float32),
    )
