"""Bus drive graph: rule unit tests and checks on the committed ``drive_graph.npz``."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import shapely
from scipy import sparse
from scipy.sparse.csgraph import connected_components

from vlab.data import DataSchemaError, load_drive_graph_arrays, load_manifest, load_study_area
from vlab.data.paths import processed_dir
from vlab.data.pipeline.drive_graph import (
    build_drive_graph,
    directions,
    is_drivable,
    parse_maxspeed,
    way_speeds,
)

requires_bundle = pytest.mark.skipif(
    not (processed_dir() / "drive_graph.npz").is_file(), reason="drive graph not built"
)


@pytest.mark.parametrize(
    ("tags", "ok"),
    [
        ({"highway": "residential"}, True),
        ({"highway": "primary_link"}, True),
        ({"highway": "motorway"}, True),
        ({"highway": "service"}, False),
        ({"highway": "service", "bus": "yes"}, True),
        ({"highway": "service", "psv": "designated"}, True),
        ({"highway": "busway"}, True),
        ({"highway": "footway"}, False),
        ({"highway": "pedestrian"}, False),
        ({"highway": "pedestrian", "bus": "yes"}, False),
        ({"highway": "residential", "access": "private"}, False),
        ({"highway": "residential", "motor_vehicle": "no", "bus": "yes"}, True),
        ({"highway": "tertiary", "access": "no", "psv": "yes"}, True),
    ],
)
def test_is_drivable(tags: dict[str, str], ok: bool) -> None:
    assert is_drivable(tags) is ok


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"highway": "residential"}, (True, True)),
        ({"highway": "residential", "oneway": "yes"}, (True, False)),
        ({"highway": "residential", "oneway": "-1"}, (False, True)),
        ({"highway": "primary", "junction": "roundabout"}, (True, False)),
        ({"highway": "motorway"}, (True, False)),
        ({"highway": "motorway", "oneway": "no"}, (True, True)),
        ({"highway": "tertiary", "oneway": "yes", "oneway:bus": "no"}, (True, True)),
        ({"highway": "tertiary", "oneway": "yes", "oneway:psv": "no"}, (True, True)),
        ({"highway": "tertiary", "oneway": "yes", "busway:left": "opposite_lane"}, (True, True)),
    ],
)
def test_directions(tags: dict[str, str], expected: tuple[bool, bool]) -> None:
    assert directions(tags) == expected


def test_speeds() -> None:
    assert parse_maxspeed("50") == 50
    assert parse_maxspeed("ES:zone30") == 30
    assert parse_maxspeed("20 mph") == pytest.approx(32.19, abs=0.01)
    assert parse_maxspeed("signals") is None and parse_maxspeed(None) is None
    assert way_speeds({"highway": "residential"}) == (30.0, 30.0)
    assert way_speeds({"highway": "primary", "maxspeed": "40", "maxspeed:backward": "30"}) == (
        40.0,
        30.0,
    )


def test_build_drive_graph_toy() -> None:
    # Two-way street A-B-C (200 m) with a one-way loop B-D-E-B; dead one-way stub C-F.
    ways = [
        ([1, 2, 3], [0, 100, 200], [0, 0, 0], {"highway": "residential"}),
        (
            [2, 4, 5, 2],
            [100, 100, 150, 100],
            [0, 50, 50, 0],
            {"highway": "residential", "oneway": "yes"},
        ),
        ([3, 6], [200, 300], [0, 0], {"highway": "residential", "oneway": "yes"}),
    ]
    g = build_drive_graph(
        [np.array(w[0]) for w in ways],
        [np.array(w[1], dtype=float) for w in ways],
        [np.array(w[2], dtype=float) for w in ways],
        [w[3] for w in ways],
    )
    n = g.n_nodes
    m = sparse.csr_matrix((g.length_m, g.indices, g.indptr), shape=(n, n))
    assert connected_components(m, directed=True, connection="strong")[0] == 1
    # The stub towards (300, 0) is not strongly connected -> dropped.
    assert float(g.x.max()) == pytest.approx(200.0)
    assert g.length_m.max() <= 60.0 + 1e-6
    # One-way loop edges exist in one direction only.
    asym = abs(m - m.T)
    assert asym.nnz > 0
    assert (g.speed_kmh == 30).all()


@requires_bundle
def test_drive_graph_bundle() -> None:
    g = load_drive_graph_arrays()
    assert g.n_nodes > 10_000 and g.n_edges > g.n_nodes
    n = g.n_nodes
    m = sparse.csr_matrix((g.length_m, g.indices, g.indptr), shape=(n, n))
    assert connected_components(m, directed=True, connection="strong")[0] == 1
    assert m.diagonal().max() == 0
    assert float(g.length_m.max()) <= 60.0 + 1e-3
    names = set(g.edge_class_names().tolist())
    assert {"primary", "secondary", "residential"} <= names
    assert not names & {"footway", "pedestrian", "path"}
    area = load_study_area()
    assert shapely.contains_xy(area.buffer(1e-5), g.node_lon, g.node_lat).all()
    # Some one-way streets exist, so the graph is not symmetric.
    assert abs(m - m.T).nnz > 0


@requires_bundle
def test_drive_graph_matches_gtfs() -> None:
    s = load_manifest()["drive_graph"]
    assert s["stops_within_50m_share"] >= 0.98
    assert s["shape_vertices_within_15m_share"] >= 0.95
    assert s["nodes"] == load_drive_graph_arrays().n_nodes


@requires_bundle
def test_drive_loader_rejects_bad_class(tmp_path: Path) -> None:
    dst = tmp_path / "processed"
    shutil.copytree(processed_dir(), dst)
    p = dst / "drive_graph.npz"
    with np.load(p) as z:
        arrays = {k: z[k] for k in z.files}
    arrays["highway_class"] = arrays["highway_class"].copy()
    arrays["highway_class"][0] = 200
    np.savez(p, **arrays)
    with pytest.raises(DataSchemaError, match="highway_class"):
        load_drive_graph_arrays(tmp_path)
    assert json.loads((dst / "manifest.json").read_text())["drive_graph"]
