"""Unit tests of the data-pipeline building blocks and of loader validation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from scipy import sparse
from scipy.sparse.csgraph import connected_components

from vlab.data import DataSchemaError, load_pois, load_walk_graph_arrays, load_zones
from vlab.data.paths import ENV_VAR, data_dir, processed_dir
from vlab.data.pipeline.buildings import floors_above_ground, osm_building_class, roman_to_int
from vlab.data.pipeline.census import _spanish_number
from vlab.data.pipeline.walk_graph import build_walk_graph, is_walkable
from vlab.data.pipeline.zones import build_zones, cell_index, cell_xy, largest_remainder

# ---------------------------------------------------------------- dasymetric allocation


@pytest.mark.parametrize(
    ("total", "weights"),
    [
        (10, [1, 1, 1]),
        (7, [0.2, 0.5, 0.3]),
        (1000, [3.3, 0.0, 9.1, 1e-9]),
        (0, [1, 2]),
        (5, [0, 0]),
    ],
)
def test_largest_remainder_preserves_total(total: int, weights: list[float]) -> None:
    out = largest_remainder(total, weights)
    assert out.sum() == total
    assert (out >= 0).all()
    w = np.asarray(weights, dtype=float)
    if w.sum() > 0:
        assert (np.abs(out - total * w / w.sum()) < 1.0 + 1e-9).all()


def test_largest_remainder_random() -> None:
    rng = np.random.default_rng(0)
    for _ in range(200):
        w = rng.random(rng.integers(1, 50)) * (rng.random() < 0.9)
        total = int(rng.integers(0, 5000))
        assert largest_remainder(total, w).sum() == total


def test_largest_remainder_rejects_bad_weights() -> None:
    with pytest.raises(ValueError):
        largest_remainder(3, [1, -1])
    with pytest.raises(ValueError):
        largest_remainder(3, [])


def test_cell_codes_roundtrip() -> None:
    x = np.array([604_123.0, 610_000.0, 610_199.9])
    y = np.array([4_730_001.0, 4_740_000.0, 4_740_399.0])
    x0, y0 = cell_xy(cell_index(x, y))
    assert np.array_equal(x0, [604_000, 610_000, 610_000])
    assert np.array_equal(y0, [4_730_000, 4_740_000, 4_740_200])


def _toy_sections() -> gpd.GeoDataFrame:
    # Two sections side by side, 600 x 400 m each, plus one without buildings.
    return gpd.GeoDataFrame(
        {
            "section_id": ["3120101001", "3120101002", "3120101003"],
            "municipality": ["A", "A", "B"],
            "population": [1001, 333, 50],
        },
        geometry=[
            shapely.box(600_000, 4_740_000, 600_600, 4_740_400),
            shapely.box(600_600, 4_740_000, 601_200, 4_740_400),
            shapely.box(600_000, 4_740_400, 600_350, 4_740_700),
        ],
        crs="EPSG:25830",
    )


def _toy_buildings() -> gpd.GeoDataFrame:
    geoms = [
        shapely.box(600_050, 4_740_050, 600_090, 4_740_090),  # residential, section 1
        shapely.box(600_450, 4_740_250, 600_500, 4_740_300),  # residential, section 1
        shapely.box(600_700, 4_740_100, 600_760, 4_740_160),  # non-residential, section 2
        shapely.box(600_900, 4_740_100, 600_960, 4_740_160),  # non-residential, section 2
    ]
    fa = [1600.0 * 3, 2500.0 * 6, 3600.0, 3600.0 * 2]
    return gpd.GeoDataFrame(
        {
            "floor_area_m2": fa,
            "use": ["residential", "residential", "non_residential", "non_residential"],
        },
        geometry=geoms,
        crs="EPSG:25830",
    )


def test_build_zones_conserves_and_falls_back() -> None:
    sec = _toy_sections()
    pois = pd.DataFrame({"x": [600_910.0], "y": [4_740_110.0]})
    area = shapely.box(599_000, 4_739_000, 602_000, 4_741_000)
    zb = build_zones(sec, _toy_buildings(), pois, area)
    zs = zb.zone_sections
    by_sec = zs.groupby("section_id")["population"].sum()
    assert by_sec.to_dict() == {"3120101001": 1001, "3120101002": 333, "3120101003": 50}
    assert int(zb.zones["population"].sum()) == 1384
    # Section 1: residential floor area only in two cells -> all its people there.
    s1_cells = zs.loc[zs.section_id == "3120101001", "zone_id"]
    assert len(s1_cells) == 2
    # Fallback tiers: section 2 has only non-residential floor area; section 3 none.
    assert zb.fallback_counts == {
        "residential_floor_area": 1,
        "all_floor_area": 1,
        "uniform_area": 1,
    }
    assert float(zb.zones["activity_weight"].sum()) == pytest.approx(3600.0 * 3)
    assert int(zb.zones["n_pois"].sum()) == 1
    assert np.array_equal(zb.zones["zone_id"], np.arange(len(zb.zones)))
    x = zb.zones["x"].to_numpy()
    assert np.allclose(np.mod(x - 100, 200), 0)


def test_build_zones_clips_to_study_area() -> None:
    sec = _toy_sections()
    pois = pd.DataFrame({"x": [600_050.0], "y": [4_740_050.0]})
    area = shapely.box(600_000, 4_740_000, 600_200, 4_740_200)  # one cell
    zb = build_zones(sec, _toy_buildings(), pois, area)
    assert len(zb.zones) == 1
    in_area = zb.section_population_in_area
    assert in_area["3120101001"] == int(zb.zones["population"].sum())
    assert in_area["3120101001"] < 1001
    assert in_area["3120101003"] == 0


# ---------------------------------------------------------------- buildings


@pytest.mark.parametrize(
    ("label", "floors"),
    [
        ("I", 1),
        ("S+V+T", 5),
        ("2S+VIII", 8),
        ("SS+IV", 4),
        ("P+I", 1),
        ("XIV", 14),
        ("PAV", 0),
        ("S", 0),
        ("PISCINA", 0),
        (None, 0),
        ("", 0),
    ],
)
def test_floors_above_ground(label: str | None, floors: int) -> None:
    assert floors_above_ground(label) == floors


def test_roman() -> None:
    assert [roman_to_int(s) for s in ("IV", "IX", "XII", "XL")] == [4, 9, 12, 40]


def test_osm_building_class() -> None:
    assert osm_building_class({"building": "apartments"}) == "residential"
    assert osm_building_class({"building": "industrial"}) == "non_residential"
    assert osm_building_class({"building": "garage"}) == "excluded"
    assert osm_building_class({"building": "yes", "amenity": "school"}) == "non_residential"
    assert osm_building_class({"building": "yes"}) == "unknown"


# ---------------------------------------------------------------- census parsing


def test_spanish_number() -> None:
    s = pd.Series(["206.464", "50,2", ".", "", "1.187", "17.016"])
    out = _spanish_number(s).tolist()
    assert out[0] == 206464 and out[1] == pytest.approx(50.2)
    assert pd.isna(out[2]) and pd.isna(out[3])
    assert out[4] == 1187 and out[5] == 17016


# ---------------------------------------------------------------- walk graph


@pytest.mark.parametrize(
    ("tags", "ok"),
    [
        ({"highway": "residential"}, True),
        ({"highway": "footway"}, True),
        ({"highway": "motorway"}, False),
        ({"highway": "trunk"}, False),
        ({"highway": "trunk", "sidewalk": "both"}, True),
        ({"highway": "trunk", "sidewalk": "separate"}, False),
        ({"highway": "primary", "foot": "no"}, False),
        ({"highway": "service", "access": "private"}, False),
        ({"highway": "service", "access": "private", "foot": "yes"}, True),
        ({"highway": "busway"}, False),
        ({"highway": "proposed"}, False),
    ],
)
def test_is_walkable(tags: dict[str, str], ok: bool) -> None:
    assert is_walkable(tags) is ok


def test_build_walk_graph_toy() -> None:
    # A 200 m street crossed in its middle by a 100 m street, plus an isolated way.
    ways = [
        (np.array([1, 2, 3]), np.array([0.0, 100.0, 200.0]), np.array([0.0, 0.0, 0.0])),
        (np.array([4, 2]), np.array([100.0, 100.0]), np.array([100.0, 0.0])),
        (np.array([7, 8]), np.array([5000.0, 5010.0]), np.array([5000.0, 5000.0])),
    ]
    g = build_walk_graph([w[0] for w in ways], [w[1] for w in ways], [w[2] for w in ways])
    n = g.n_nodes
    m = sparse.csr_matrix((g.length_m, g.indices, g.indptr), shape=(n, n))
    assert abs(m - m.T).max() == 0
    assert connected_components(m, directed=False)[0] == 1
    assert g.length_m.max() <= 60.0 + 1e-6
    # Total length: 200 + 100 m (isolated component dropped), each edge stored twice.
    assert float(g.length_m.sum()) / 2 == pytest.approx(300.0)
    # Intersection node 2 exists with degree 3.
    deg = np.diff(g.indptr)
    j = np.flatnonzero((np.abs(g.x - 100) < 1e-9) & (np.abs(g.y) < 1e-9))
    assert len(j) == 1 and deg[j[0]] == 3


def test_build_walk_graph_clip() -> None:
    # Way 1-2-3 is split at node 2 (shared with way 2-4); only segments fully inside stay.
    ways = [
        (np.array([1, 2, 3]), np.array([0.0, 50.0, 100.0]), np.array([0.0, 0.0, 0.0])),
        (np.array([2, 4]), np.array([50.0, 50.0]), np.array([0.0, 40.0])),
    ]
    clip = shapely.box(-10, -10, 75, 60)
    g = build_walk_graph([w[0] for w in ways], [w[1] for w in ways], [w[2] for w in ways], clip)
    assert float(g.x.max()) <= 75.0
    assert float(g.length_m.sum()) / 2 == pytest.approx(90.0)
    with pytest.raises(ValueError, match="no walkable edges"):
        build_walk_graph([ways[0][0]], [ways[0][1]], [ways[0][2]], shapely.box(-10, -10, 75, 10))


# ---------------------------------------------------------------- loaders


def _copy_bundle(tmp_path: Path) -> Path:
    src = processed_dir()
    dst = tmp_path / "processed"
    shutil.copytree(src, dst)
    return tmp_path


requires_bundle = pytest.mark.skipif(
    not (processed_dir() / "manifest.json").is_file(), reason="processed bundle not built"
)


def test_data_dir_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    assert data_dir() == tmp_path.resolve()
    assert processed_dir() == tmp_path.resolve() / "processed"
    with pytest.raises(DataSchemaError, match="not found"):
        load_pois()


@requires_bundle
def test_loader_rejects_bad_poi_category(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)
    p = root / "processed" / "pois.parquet"
    df = pd.read_parquet(p)
    df.loc[0, "category"] = "casino"
    df.to_parquet(p)
    with pytest.raises(DataSchemaError, match="unknown POI categories"):
        load_pois(root)


@requires_bundle
def test_loader_rejects_missing_column(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)
    p = root / "processed" / "zones.parquet"
    gpd.read_parquet(p).drop(columns=["population"]).to_parquet(p)
    with pytest.raises(DataSchemaError, match="missing columns"):
        load_zones(root)


@requires_bundle
def test_loader_rejects_bad_graph(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path)
    p = root / "processed" / "walk_graph.npz"
    with np.load(p) as z:
        arrays = {k: z[k] for k in z.files}
    arrays["length_m"] = arrays["length_m"].astype(np.float64)
    np.savez(p, **arrays)
    with pytest.raises(DataSchemaError, match="length_m"):
        load_walk_graph_arrays(root)


@requires_bundle
def test_manifest_is_json() -> None:
    m = json.loads((processed_dir() / "manifest.json").read_text(encoding="utf-8"))
    assert m["generator"] == "scripts/build_data.py"
