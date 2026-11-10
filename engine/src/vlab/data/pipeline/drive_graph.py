"""Directed street graph a 12 m bus can plausibly use (for snapping new lines).

Rules (explicit, documented in ``docs/data.md``):

* drivable classes: motorway, trunk, primary, secondary, tertiary, unclassified,
  residential, living_street and the ``*_link`` variants; ``highway=busway`` and
  ``bus_guideway``; ``highway=service`` only with ``bus``/``psv`` in
  ``yes|designated``;
* ``access``/``motor_vehicle``/``vehicle`` = ``no|private`` excludes the way unless
  ``bus``/``psv`` allows it;
* direction: ``oneway=yes|true|1`` forward only, ``-1`` backward only; roundabouts
  (``junction=roundabout|circular``) and motorways are implied one-way; contraflow
  for buses with ``oneway:bus=no``, ``oneway:psv=no`` or ``busway*=opposite_lane``;
* speed: ``maxspeed`` (or the direction-specific tag) when parseable, else the
  Spanish urban legal default of the class (:data:`DEFAULT_SPEED_KMH`).

Nodes are way intersections and ends plus interpolated nodes so that no edge
exceeds :data:`~vlab.data.pipeline.common.MAX_EDGE_M`; only the largest strongly
connected component is kept. Output is CSR by origin node.
"""

from __future__ import annotations

import csv
import io
import itertools
import math
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import shapely
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from shapely.geometry.base import BaseGeometry

from vlab.data.pipeline.common import MAX_EDGE_M, log, to_utm

HIGHWAY_CLASSES: tuple[str, ...] = (
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street", "service", "busway", "bus_guideway",
)  # fmt: skip
CLASS_INDEX = {c: i for i, c in enumerate(HIGHWAY_CLASSES)}
# Default speed (km/h) when maxspeed is absent: Spanish limits (RD 970/2020: 50 km/h on
# urban roads with 2+ lanes per direction, 30 with one lane, 20 on shared-level streets);
# interurban classes use the usual posted limits around Pamplona. These are limits,
# not bus running speeds.
DEFAULT_SPEED_KMH: dict[str, float] = {
    "motorway": 100.0, "motorway_link": 60.0, "trunk": 80.0, "trunk_link": 50.0,
    "primary": 50.0, "primary_link": 40.0, "secondary": 50.0, "secondary_link": 40.0,
    "tertiary": 50.0, "tertiary_link": 40.0, "unclassified": 30.0, "residential": 30.0,
    "living_street": 20.0, "service": 20.0, "busway": 50.0, "bus_guideway": 50.0,
}  # fmt: skip
BUS_SERVICE_OK = frozenset({"yes", "designated"})
BUS_ALLOW = frozenset({"yes", "designated", "permissive"})
NO_ACCESS = frozenset({"no", "private"})
ONEWAY_YES = frozenset({"yes", "true", "1"})
_ES_ZONES = {"es:urban": 50.0, "es:zone30": 30.0, "es:zone20": 20.0, "es:living_street": 20.0}


def bus_allowed(tags: Mapping[str, str]) -> bool:
    return tags.get("bus") in BUS_ALLOW or tags.get("psv") in BUS_ALLOW


def is_drivable(tags: Mapping[str, str]) -> bool:
    """Whether a 12 m bus can plausibly use the way."""
    hw = tags.get("highway", "")
    if hw == "service":
        if not (tags.get("bus") in BUS_SERVICE_OK or tags.get("psv") in BUS_SERVICE_OK):
            return False
    elif hw not in CLASS_INDEX:
        return False
    if tags.get("area") == "yes":
        return False
    restricted = any(tags.get(k) in NO_ACCESS for k in ("access", "motor_vehicle", "vehicle"))
    return not (restricted and not bus_allowed(tags))


def directions(tags: Mapping[str, str]) -> tuple[bool, bool]:
    """(forward, backward) usable by a bus along the way's node order."""
    ow = tags.get("oneway", "")
    implied = tags.get("junction") in {"roundabout", "circular"} or tags.get("highway") in {
        "motorway",
        "motorway_link",
    }
    if ow == "-1":
        fwd, bwd = False, True
    elif ow in ONEWAY_YES or (implied and ow != "no"):
        fwd, bwd = True, False
    else:
        fwd, bwd = True, True
    contraflow = (
        tags.get("oneway:bus") == "no"
        or tags.get("oneway:psv") == "no"
        or any(
            tags.get(k) == "opposite_lane"
            for k in ("busway", "busway:left", "busway:right", "busway:both")
        )
    )
    if contraflow:
        fwd, bwd = True, True
    return fwd, bwd


def parse_maxspeed(value: str | None) -> float | None:
    """km/h from an OSM maxspeed value; None when absent or unparseable."""
    if not value:
        return None
    v = value.strip().lower()
    if v in _ES_ZONES:
        return _ES_ZONES[v]
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mph|km/h|kmh)?$", v)
    if not m:
        return None
    speed = float(m.group(1)) * (1.609344 if m.group(2) == "mph" else 1.0)
    return speed if 5.0 <= speed <= 130.0 else None


def way_speeds(tags: Mapping[str, str]) -> tuple[float, float]:
    """(forward, backward) speed in km/h."""
    base = parse_maxspeed(tags.get("maxspeed"))
    default = DEFAULT_SPEED_KMH[tags.get("highway", "residential")]
    fwd = parse_maxspeed(tags.get("maxspeed:forward")) or base or default
    bwd = parse_maxspeed(tags.get("maxspeed:backward")) or base or default
    return fwd, bwd


@dataclass(frozen=True)
class DriveGraphArrays:
    """Directed CSR street graph (row = origin node)."""

    x: npt.NDArray[np.float64]
    y: npt.NDArray[np.float64]
    indptr: npt.NDArray[np.int32]
    indices: npt.NDArray[np.int32]
    length_m: npt.NDArray[np.float32]
    speed_kmh: npt.NDArray[np.float32]
    highway_class: npt.NDArray[np.uint8]

    @property
    def n_nodes(self) -> int:
        return int(self.x.shape[0])

    @property
    def n_edges(self) -> int:
        """Directed edges."""
        return int(self.indices.shape[0])


def build_drive_graph(
    way_nodes: Sequence[npt.NDArray[np.int64]],
    way_x: Sequence[npt.NDArray[np.float64]],
    way_y: Sequence[npt.NDArray[np.float64]],
    way_tags: Sequence[Mapping[str, str]],
    clip: BaseGeometry | None = None,
    max_edge_m: float = MAX_EDGE_M,
) -> DriveGraphArrays:
    """Build the directed graph from drivable ways (projected coordinates)."""
    all_ids = np.concatenate(way_nodes)
    uniq, counts = np.unique(all_ids, return_counts=True)
    shared = set(uniq[counts >= 2].tolist())
    for ids in way_nodes:
        shared.add(int(ids[0]))
        shared.add(int(ids[-1]))
    if clip is not None:
        shapely.prepare(clip)
        inside_flat = shapely.contains_xy(clip, np.concatenate(way_x), np.concatenate(way_y))
        inside_per_way = np.split(inside_flat, np.cumsum([len(a) for a in way_nodes])[:-1])
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
    es: list[float] = []
    ec: list[int] = []
    for ids, xs_w, ys_w, inside, tags in zip(
        way_nodes, way_x, way_y, inside_per_way, way_tags, strict=True
    ):
        fwd, bwd = directions(tags)
        sp_f, sp_b = way_speeds(tags)
        cls = CLASS_INDEX[tags["highway"]]
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
            chain = [u]
            if pieces > 1:
                cum = np.concatenate([[0.0], np.cumsum(step)])
                targets = np.linspace(0.0, total, pieces + 1)[1:-1]
                for px, py in zip(
                    np.interp(targets, cum, sx), np.interp(targets, cum, sy), strict=True
                ):
                    chain.append(len(node_x))
                    node_x.append(float(px))
                    node_y.append(float(py))
            chain.append(v)
            piece = total / pieces
            for p, q in itertools.pairwise(chain):
                if fwd:
                    eu.append(p)
                    ev.append(q)
                    el.append(piece)
                    es.append(sp_f)
                    ec.append(cls)
                if bwd:
                    eu.append(q)
                    ev.append(p)
                    el.append(piece)
                    es.append(sp_b)
                    ec.append(cls)
    if not eu:
        raise ValueError("no drivable edges inside the clip area")
    x = np.asarray(node_x)
    y = np.asarray(node_y)
    u_a = np.asarray(eu, dtype=np.int64)
    v_a = np.asarray(ev, dtype=np.int64)
    l_a = np.asarray(el)
    s_a = np.asarray(es)
    c_a = np.asarray(ec, dtype=np.int64)
    keep = u_a != v_a
    u_a, v_a, l_a, s_a, c_a = u_a[keep], v_a[keep], l_a[keep], s_a[keep], c_a[keep]
    # Parallel directed edges: keep the shortest.
    order = np.lexsort((l_a, v_a, u_a))
    u_a, v_a, l_a, s_a, c_a = u_a[order], v_a[order], l_a[order], s_a[order], c_a[order]
    first = np.ones(len(u_a), dtype=bool)
    first[1:] = (u_a[1:] != u_a[:-1]) | (v_a[1:] != v_a[:-1])
    u_a, v_a, l_a, s_a, c_a = u_a[first], v_a[first], l_a[first], s_a[first], c_a[first]

    n_all = len(x)
    adj = sparse.csr_matrix((np.ones(len(u_a)), (u_a, v_a)), shape=(n_all, n_all))
    n_comp, labels = connected_components(adj, directed=True, connection="strong")
    used = np.zeros(n_all, dtype=bool)
    used[u_a] = True
    used[v_a] = True
    sizes = np.bincount(labels[used], minlength=n_comp)
    main = int(np.argmax(sizes))
    keep_node = used & (labels == main)
    log.info(
        "  drive graph: largest strongly connected component has %d of %d nodes (%.1f%%)",
        int(keep_node.sum()), int(used.sum()), 100.0 * keep_node.sum() / max(1, used.sum()),
    )  # fmt: skip

    old = np.flatnonzero(keep_node)
    old = old[np.lexsort((x[old], np.floor(y[old] / 200.0)))]
    new_of_old = np.full(n_all, -1, dtype=np.int64)
    new_of_old[old] = np.arange(len(old))
    e_keep = keep_node[u_a] & keep_node[v_a]
    a = new_of_old[u_a[e_keep]]
    b = new_of_old[v_a[e_keep]]
    eorder = np.lexsort((b, a))
    a, b = a[eorder], b[eorder]
    n = len(old)
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(a, minlength=n), out=indptr[1:])
    return DriveGraphArrays(
        x=x[old],
        y=y[old],
        indptr=indptr.astype(np.int32),
        indices=b.astype(np.int32),
        length_m=l_a[e_keep][eorder].astype(np.float32),
        speed_kmh=s_a[e_keep][eorder].astype(np.float32),
        highway_class=c_a[e_keep][eorder].astype(np.uint8),
    )


def _read_csv(gtfs_zip: Path, name: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(gtfs_zip) as zf, zf.open(name) as fh:
        return list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")))


def drive_graph_sanity(g: DriveGraphArrays, gtfs_zip: Path) -> dict[str, object]:
    """Distance from GTFS stops to graph nodes and share of shape vertices on the graph."""
    tree = cKDTree(np.column_stack([g.x, g.y]))
    stops = [
        r for r in _read_csv(gtfs_zip, "stops.txt") if r.get("location_type", "0") in ("", "0")
    ]
    sx, sy = to_utm([float(r["stop_lon"]) for r in stops], [float(r["stop_lat"]) for r in stops])
    d_stop = np.asarray(tree.query(np.column_stack([sx, sy]))[0], dtype=np.float64)
    shapes = _read_csv(gtfs_zip, "shapes.txt")
    px, py = to_utm(
        [float(r["shape_pt_lon"]) for r in shapes], [float(r["shape_pt_lat"]) for r in shapes]
    )
    rows = np.repeat(np.arange(g.n_nodes), np.diff(g.indptr))
    segs = shapely.linestrings(
        np.stack(
            [np.column_stack([g.x[rows], g.y[rows]]),
             np.column_stack([g.x[g.indices], g.y[g.indices]])], axis=1
        )
    )  # fmt: skip
    st = shapely.STRtree(segs)
    pts = shapely.points(px, py)
    hit = st.query(pts, predicate="dwithin", distance=15.0)
    on = np.zeros(len(pts), dtype=bool)
    on[np.unique(hit[0])] = True
    q = [50, 90, 95, 99, 100]
    stats: dict[str, object] = {
        "stops": len(stops),
        "stop_to_node_m_percentiles": {
            f"p{p}": round(float(v), 1) for p, v in zip(q, np.percentile(d_stop, q), strict=True)
        },
        "stops_within_50m_share": round(float((d_stop <= 50.0).mean()), 4),
        "shape_vertices": len(pts),
        "shape_vertices_within_15m_share": round(float(on.mean()), 4),
    }
    log.info("  drive graph sanity: %s", stats)
    return stats
