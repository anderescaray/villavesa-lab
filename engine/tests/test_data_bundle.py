"""Checks on the committed processed data bundle (``data/processed``)."""

from __future__ import annotations

from functools import cache

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from scipy import sparse
from scipy.sparse.csgraph import connected_components

from vlab.data import (
    POI_CATEGORIES,
    WalkGraphData,
    load_manifest,
    load_pois,
    load_sections,
    load_study_area,
    load_walk_graph_arrays,
    load_zone_sections,
    load_zones,
)
from vlab.data.paths import processed_dir

pytestmark = pytest.mark.skipif(
    not (processed_dir() / "manifest.json").is_file(), reason="processed bundle not built"
)


@cache
def zones() -> gpd.GeoDataFrame:
    return load_zones()


@cache
def sections() -> gpd.GeoDataFrame:
    return load_sections()


@cache
def pois() -> pd.DataFrame:
    return load_pois()


@cache
def graph() -> WalkGraphData:
    return load_walk_graph_arrays()


def test_all_contract_files_present() -> None:
    names = {p.name for p in processed_dir().iterdir()}
    for f in (
        "study_area.geojson",
        "sections.parquet",
        "zones.parquet",
        "zone_sections.parquet",
        "pois.parquet",
        "walk_graph.npz",
        "drive_graph.npz",
        "manifest.json",
    ):
        assert f in names


def test_bundle_is_compact() -> None:
    total = sum(p.stat().st_size for p in processed_dir().iterdir() if p.is_file())
    assert total < 15e6


def test_population_conserved_per_section() -> None:
    zs = load_zone_sections()
    sec = sections().set_index("section_id")
    by_sec = zs.groupby("section_id")["population"].sum()
    assert set(by_sec.index) <= set(sec.index)
    expected = sec["population_in_study_area"]
    got = by_sec.reindex(expected.index).fillna(0).astype(np.int64)
    assert (got == expected).all()
    # Sections fully inside the study area keep their whole population.
    area = load_study_area()
    inside = sec[sec.geometry.within(area)]
    assert len(inside) > 100
    assert (inside["population_in_study_area"] == inside["population"]).all()


def test_population_conserved_in_total() -> None:
    zs = load_zone_sections()
    z = zones()
    assert int(zs["population"].sum()) == int(z["population"].sum())
    per_zone = zs.groupby("zone_id")["population"].sum()
    assert (per_zone == z.set_index("zone_id")["population"].reindex(per_zone.index)).all()
    assert int(z["population"].sum()) == int(sections()["population_in_study_area"].sum())


def test_population_plausible() -> None:
    total = int(zones()["population"].sum())
    assert 350_000 <= total <= 390_000
    by_muni = sections().groupby("municipality")["population_in_study_area"].sum()
    pamplona = by_muni[by_muni.index.str.startswith("Pamplona")].sum()
    assert 195_000 <= pamplona <= 215_000
    for prefix, lo, hi in (
        ("Barañáin", 17_000, 22_000),
        ("Burlada", 17_000, 23_000),
        ("Zizur Mayor", 13_000, 18_000),
        ("Villava", 9_000, 11_500),
        ("Berriozar", 9_000, 12_500),
    ):
        v = by_muni[by_muni.index.str.startswith(prefix)].sum()
        assert lo <= v <= hi, (prefix, v)


def test_income_covers_sections() -> None:
    s = sections()
    assert s["income_per_capita"].notna().mean() > 0.95
    inc = s["income_per_capita"].dropna()
    assert inc.between(5_000, 60_000).all()
    hh = s["income_per_household"].dropna()
    assert (hh.to_numpy() > inc.reindex(hh.index).fillna(0).to_numpy()).all()


def test_zones_grid_and_ids() -> None:
    z = zones()
    assert z["zone_id"].is_unique
    assert not z[["x", "y", "lon", "lat", "population", "activity_weight"]].isna().any().any()
    # Cell geometry matches the stated centre.
    c = z.geometry.to_crs("EPSG:25830").centroid
    assert np.allclose(c.x, z["x"], atol=0.05) and np.allclose(c.y, z["y"], atol=0.05)
    assert np.allclose(z.geometry.to_crs("EPSG:25830").area, 40_000, rtol=1e-4)
    assert (z["activity_weight"] > 0).sum() > 100
    assert int(z["n_pois"].sum()) == len(pois())


def test_every_poi_category_non_empty() -> None:
    p = pois()
    counts = p["category"].value_counts()
    for cat in POI_CATEGORIES:
        assert counts.get(cat, 0) > 0, cat
    assert counts["city_centre"] == 1
    assert 2 <= counts["hospital"] <= 8
    assert counts["health_centre"] >= 20
    assert (p["weight"] > 0).all()
    names = " | ".join(p.loc[p["category"] == "hospital", "name"])
    assert "Hospital Universitario de Navarra" in names
    assert "Clínica Universidad de Navarra" in names
    unis = " | ".join(p.loc[p["category"] == "university", "name"])
    assert "Universidad Pública de Navarra" in unis and "Universidad de Navarra" in unis


def test_coordinates_inside_study_area() -> None:
    area = load_study_area()
    p = pois()
    assert shapely.contains_xy(area, p["lon"], p["lat"]).all()
    g = graph()
    # Graph nodes come from segments clipped to the area (tiny tolerance for reprojection).
    assert shapely.contains_xy(area.buffer(1e-5), g.node_lon, g.node_lat).all()
    z = zones()
    assert z.intersects(area).all()


def test_walk_graph_symmetric_and_connected() -> None:
    g = graph()
    n = g.n_nodes
    assert n > 30_000
    m = sparse.csr_matrix((g.length_m, g.indices, g.indptr), shape=(n, n))
    diff = abs(m - m.T)
    assert diff.max() < 1e-3
    assert m.diagonal().max() == 0
    n_comp, _ = connected_components(m, directed=False)
    assert n_comp == 1
    assert float(g.length_m.max()) <= 60.0 + 1e-3
    assert float(g.length_m.min()) > 0


def test_walk_graph_lengths_are_metric() -> None:
    g = graph()
    rows = np.repeat(np.arange(g.n_nodes), np.diff(g.indptr))
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)
    x, y = tr.transform(g.node_lon, g.node_lat)
    straight = np.hypot(x[rows] - x[g.indices], y[rows] - y[g.indices])
    # A walked edge is never shorter than the straight line between its ends.
    assert (g.length_m + 0.05 >= straight).all()
    # ... and mostly close to it (edges are short).
    assert np.median(g.length_m / np.maximum(straight, 1e-6)) < 1.05


def test_manifest_matches_bundle() -> None:
    m = load_manifest()
    keys = {s["key"] for s in m["sources"]}
    assert {"osm", "ine_sections", "ine_adrh_income", "ine_adrh_demography", "gtfs"} <= keys
    for s in m["sources"]:
        assert len(s["sha256"]) == 64 and s["licence"]
    c = m["counts"]
    assert c["zones"] == len(zones())
    assert c["population_in_study_area"] == int(zones()["population"].sum())
    assert c["walk_nodes"] == graph().n_nodes
    assert sum(c["pois"].values()) == len(pois())
