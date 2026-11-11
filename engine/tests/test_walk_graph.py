"""Walking layer: snapping, bounded Dijkstra, transfers, access, paths, caching."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra

from vlab.gtfs import Timetable, to_lonlat, to_xy
from vlab.walk import (
    SAME_PLACE_M,
    WALK_SPEED_MPS,
    WalkGraph,
    WalkTable,
    build_access,
    build_transfers,
    euclidean_table,
    seconds,
)

X0, Y0 = 610_000.0, 4_740_000.0  # near Pamplona, EPSG:25830


def grid_graph(n: int = 40, step: float = 50.0, drop: float = 0.15, seed: int = 0) -> WalkGraph:
    """nxn grid (``step`` m) with a fraction of edges removed (irregular streets)."""
    rng = np.random.default_rng(seed)
    ii, jj = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    x = (X0 + jj * step).ravel().astype(np.float64)
    y = (Y0 + ii * step).ravel().astype(np.float64)
    edges = []
    for i in range(n):
        for j in range(n):
            a = i * n + j
            if j + 1 < n:
                edges.append((a, a + 1))
            if i + 1 < n:
                edges.append((a, a + n))
    e = np.array(edges)
    keep = rng.random(len(e)) > drop
    keep[: n - 1] = True  # keep the first row connected
    e = e[keep]
    src = np.r_[e[:, 0], e[:, 1]]
    dst = np.r_[e[:, 1], e[:, 0]]
    order = np.lexsort((dst, src))
    src, dst = src[order], dst[order]
    lon, lat = to_lonlat(x, y)
    xs, ys = to_xy(lon, lat)
    w = np.hypot(xs[src] - xs[dst], ys[src] - ys[dst]).astype(np.float32)
    ptr = np.zeros(n * n + 1, np.int64)
    np.cumsum(np.bincount(src, minlength=n * n), out=ptr[1:])
    return WalkGraph.from_arrays(lon, lat, ptr, dst.astype(np.int32), w)


def scipy_matrix(g: WalkGraph) -> sp.csr_matrix:
    rows = np.repeat(np.arange(g.n_nodes), np.diff(g.indptr))
    return sp.csr_matrix((g.length_m.astype(np.float64), (rows, g.indices)), (g.n_nodes,) * 2)


def random_points(g: WalkGraph, n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x, y = g.node_xy
    px = rng.uniform(x.min(), x.max(), n)
    py = rng.uniform(y.min(), y.max(), n)
    return to_lonlat(px, py)


@pytest.fixture(scope="module")
def grid() -> WalkGraph:
    return grid_graph()


def test_graph_validation() -> None:
    with pytest.raises(ValueError, match="CSR"):
        WalkGraph.from_arrays([0.0, 1.0], [0.0, 1.0], [0, 1], [1], [1.0])
    with pytest.raises(ValueError, match="lengths"):
        WalkGraph.from_arrays([0.0, 1.0], [0.0, 1.0], [0, 1, 2], [1, 0], [1.0, -1.0])


def test_load_roundtrip(grid: WalkGraph, tmp_path: Path) -> None:
    path = tmp_path / "g.npz"
    np.savez(
        path,
        node_lon=grid.node_lon,
        node_lat=grid.node_lat,
        indptr=grid.indptr.astype(np.int32),
        indices=grid.indices,
        length_m=grid.length_m,
    )
    g2 = WalkGraph.load(path)
    assert g2.digest == grid.digest
    np.savez(tmp_path / "bad.npz", node_lon=grid.node_lon)
    with pytest.raises(ValueError, match="missing"):
        WalkGraph.load(tmp_path / "bad.npz")


def test_snap(grid: WalkGraph) -> None:
    x, y = grid.node_xy
    lon, lat = to_lonlat([x[5] + 3.0, X0 - 1000.0], [y[5] + 4.0, Y0])
    s = grid.snap(lon, lat, max_m=250, k=3)
    node, dist = s.nearest()
    assert node[0] == 5 and dist[0] == pytest.approx(5.0, abs=0.01)
    assert node[1] == -1 and not s.ok[1]
    assert np.diff(s.ptr).tolist() == [3, 0]
    assert np.all(np.diff(s.offset_m[:3]) >= 0)


def test_bounded_distances_match_scipy(grid: WalkGraph) -> None:
    full = dijkstra(scipy_matrix(grid), directed=False, indices=[0, 77, 500])
    nodes = np.array([0, 77, 500])
    lon, lat = grid.node_lon[nodes], grid.node_lat[nodes]
    # source and target = the nodes themselves (k=1, zero offsets)
    src = grid.snap(lon, lat, k=1)
    tgt = grid.snap(grid.node_lon, grid.node_lat, k=1)
    ptr, t, d = grid.distances(src, tgt, 600.0)
    for i in range(3):
        row_t, row_d = t[ptr[i] : ptr[i + 1]], d[ptr[i] : ptr[i + 1]]
        expect = np.flatnonzero(full[i] <= 600.0)
        assert row_t.tolist() == expect.tolist()
        np.testing.assert_allclose(row_d, full[i, expect], rtol=1e-5)


def test_transfers(grid: WalkGraph) -> None:
    lon, lat = random_points(grid, 80, 1)
    # two co-located stops
    lon = np.r_[lon, lon[0] + 1e-5]
    lat = np.r_[lat, lat[0]]
    tr = build_transfers(grid, (lon, lat), 400.0, cache=False)
    assert tr.n_rows == tr.n_cols == 81
    dense = tr.to_dense()
    assert np.all(np.diag(dense) == -1)  # no self loops
    np.testing.assert_array_equal(dense, dense.T)  # symmetric
    assert dense[0, 80] <= 1 and SAME_PLACE_M > 1  # same place → ~0 s
    assert tr.seconds.max() <= np.ceil(400 / WALK_SPEED_MPS)
    # network >= straight line
    eu = euclidean_table((lon, lat), (lon, lat), 400.0, detour=1.0, exclude_self=True).to_dense()
    both = (dense >= 0) & (eu >= 0)
    assert np.all(dense[both] >= eu[both] - 1)


def test_access_both_directions_agree(grid: WalkGraph) -> None:
    stops = random_points(grid, 30, 2)
    many = random_points(grid, 200, 3)  # more points than stops: Dijkstra from stops
    a = build_access(grid, many, stops, 700.0, cache=False)
    rows = [
        build_access(grid, (many[0][i : i + 1], many[1][i : i + 1]), stops, 700.0).row(0)
        for i in range(200)
    ]
    b = WalkTable.from_rows(rows, 30)  # type: ignore[arg-type]
    np.testing.assert_array_equal(a.to_dense(), b.to_dense())
    assert a.nnz > 200
    eg = a.transpose()
    assert eg.n_rows == 30 and eg.n_cols == 200
    np.testing.assert_array_equal(eg.to_dense(), a.to_dense().T)
    np.testing.assert_array_equal(eg.transpose().to_dense(), a.to_dense())


def test_access_values_match_scipy(grid: WalkGraph) -> None:
    x, y = grid.node_xy
    # points exactly on nodes, stops 20 m east of nodes; k=1 snapping is implied by
    # exact positions only for the points, so compare against the min over candidates
    full = dijkstra(scipy_matrix(grid), directed=False, indices=[10, 400])
    plon, plat = to_lonlat(x[[10, 400]], y[[10, 400]])
    slon, slat = to_lonlat(x[[12, 450, 900]], y[[12, 450, 900]])
    a = build_access(grid, (plon, plat), (slon, slat), 1000.0, cache=False).to_dense()
    for i in range(2):
        for j, node in enumerate([12, 450, 900]):
            d = full[i, node]
            if d <= 1000.0:
                assert a[i, j] == seconds(d)
            else:
                assert a[i, j] == -1


def test_unsnapped_points_fall_back_to_straight_line(grid: WalkGraph) -> None:
    x, y = grid.node_xy
    far_lon, far_lat = to_lonlat([x.min() - 400.0], [y.min()])
    stop_lon, stop_lat = to_lonlat([x.min()], [y.min()])
    a = build_access(grid, (far_lon, far_lat), (stop_lon, stop_lat), 1000.0, cache=False)
    assert a.row(0)[0].tolist() == [0]
    assert a.row(0)[1][0] == seconds(400.0 * 1.3)


def test_single_point_access_is_fast(grid: WalkGraph) -> None:
    stops = random_points(grid, 60, 4)
    pts = random_points(grid, 50, 5)
    build_access(grid, (pts[0][:1], pts[1][:1]), stops)  # JIT warm-up
    times = []
    for i in range(50):
        t = time.perf_counter()
        build_access(grid, (pts[0][i : i + 1], pts[1][i : i + 1]), stops)
        times.append(time.perf_counter() - t)
    assert np.median(times) < 0.005  # median: robust to a busy CI machine


def test_shortest_path(grid: WalkGraph) -> None:
    x, y = grid.node_xy
    a = to_lonlat([x[0] + 10.0], [y[0]])
    b = to_lonlat([x[-1]], [y[-1] + 5.0])
    p = grid.shortest_path((a[0][0], a[1][0]), (b[0][0], b[1][0]))
    assert p.found
    full = dijkstra(scipy_matrix(grid), directed=False, indices=[0])[0]
    # path via the nearest nodes; candidate snapping may find something no longer
    assert p.length_m <= full[-1] + 10.0 + 5.0 + 1e-3
    assert p.coords.shape[1] == 2 and len(p.coords) == len(p.nodes) + 2
    seg = np.hypot(*np.diff(np.column_stack(to_xy(p.coords[:, 0], p.coords[:, 1])), axis=0).T)
    assert seg.sum() == pytest.approx(p.length_m, rel=1e-4)
    through = grid.path_through(
        [[a[0][0], a[1][0]], [p.coords[5, 0], p.coords[5, 1]], [b[0][0], b[1][0]]]
    )
    assert through.length_m == pytest.approx(p.length_m, rel=0.05)
    far = grid.shortest_path((a[0][0], a[1][0]), (b[0][0], b[1][0]), max_m=100.0)
    assert not far.found


def test_tables_are_cached(grid: WalkGraph, tmp_path: Path) -> None:
    stops = random_points(grid, 20, 6)
    pts = random_points(grid, 60, 7)
    t1 = build_transfers(grid, stops, cache_dir=tmp_path)
    assert len(list((tmp_path / "walk").glob("transfers-*.npz"))) == 1
    t2 = build_transfers(grid, stops, cache_dir=tmp_path)
    np.testing.assert_array_equal(t1.to_dense(), t2.to_dense())
    a1 = build_access(grid, pts, stops, cache_dir=tmp_path)
    a2 = build_access(grid, pts, stops, cache_dir=tmp_path)
    assert len(list((tmp_path / "walk").glob("access-*.npz"))) == 1
    np.testing.assert_array_equal(a1.to_dense(), a2.to_dense())
    build_transfers(grid, stops, max_m=300, cache_dir=tmp_path)  # new key
    assert len(list((tmp_path / "walk").glob("transfers-*.npz"))) == 2


# ----------------------------------------------------------------- real walk graph


def test_real_walk_graph(walk_graph: WalkGraph, tt_weekday: Timetable) -> None:
    g = walk_graph
    m = scipy_matrix(g)
    assert abs(m - m.T).max() == 0  # symmetric, as the contract says
    snap = g.snap(tt_weekday.stop_lon, tt_weekday.stop_lat)
    assert snap.ok.all()
    _, d = snap.nearest()
    assert d.max() < 100.0
    tr = build_transfers(g, tt_weekday)
    assert tr.nnz > 1000
    # per stop, network transfer distance >= straight line (minus the same-place rule)
    eu = euclidean_table(
        (tt_weekday.stop_lon, tt_weekday.stop_lat),
        (tt_weekday.stop_lon, tt_weekday.stop_lat),
        400.0,
        detour=1.0,
        exclude_self=True,
    ).to_dense()
    dense = tr.to_dense()
    both = (dense >= 0) & (eu >= 0)
    assert np.all(dense[both] >= eu[both] - 1)
    build_access(g, ([tt_weekday.stop_lon[0]], [tt_weekday.stop_lat[0]]), tt_weekday)
    times = []
    for i in range(20):
        lon = tt_weekday.stop_lon[i] + 0.002
        t = time.perf_counter()
        a = build_access(g, ([lon], [tt_weekday.stop_lat[i]]), tt_weekday)
        times.append(time.perf_counter() - t)
        assert a.nnz > 0
    assert np.median(times) < 0.005
