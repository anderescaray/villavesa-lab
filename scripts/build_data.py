"""Build the processed data bundle in ``data/processed`` (entry point of ``make data``).

Steps (each implemented in :mod:`vlab.data.pipeline`):

1. download raw inputs (cached in ``data/raw``; ``--force`` re-downloads),
2. study area from the GTFS stops,
3. one pyosmium pass over the OSM extract,
4. walk graph and bus drive graph,
5. census sections + population + income (INE),
6. cadastre buildings (IDENA) classified by use,
7. POIs,
8. 200 m dasymetric grid,
9. write the bundle and ``manifest.json``.

Run: ``uv run --group data python scripts/build_data.py [--force] [--skip-download]``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from vlab.data import paths
from vlab.data.pipeline import buildings as bld
from vlab.data.pipeline.census import ADRH_YEAR, build_sections
from vlab.data.pipeline.common import (
    CELL_SIZE_M,
    MAX_EDGE_M,
    STUDY_AREA_BUFFER_M,
    UTM30,
    WGS84,
    log,
    sha256_file,
    to_utm,
    to_wgs,
)
from vlab.data.pipeline.drive_graph import (
    HIGHWAY_CLASSES,
    build_drive_graph,
    drive_graph_sanity,
    is_drivable,
)
from vlab.data.pipeline.osm_extract import extract
from vlab.data.pipeline.pois import build_pois, read_wfs_geojson
from vlab.data.pipeline.sources import SOURCES, describe, download
from vlab.data.pipeline.study_area import study_area_utm
from vlab.data.pipeline.walk_graph import build_walk_graph, is_walkable
from vlab.data.pipeline.zones import ZoneBuild, build_zones

SECTION_SIMPLIFY_M = 2.0
FACILITY_AMENITIES = frozenset({"hospital", "university", "college", "school", "clinic"})


def _step(name: str) -> float:
    log.info("== %s", name)
    return time.perf_counter()


def _done(t0: float) -> None:
    log.info("   (%.1f s)", time.perf_counter() - t0)


def run(force: bool, skip_download: bool) -> None:
    raw = paths.raw_dir()
    out = paths.processed_dir()
    out.mkdir(parents=True, exist_ok=True)

    t = _step("1. raw inputs")
    files: dict[str, Path] = {}
    for key, src in SOURCES.items():
        if skip_download:
            files[key] = raw / src.filename
            if not files[key].exists():
                raise FileNotFoundError(f"--skip-download but {files[key]} is missing")
        else:
            files[key] = download(src, raw, force=force and key != "gtfs")
    _done(t)

    t = _step("2. study area")
    area = study_area_utm(files["gtfs"])
    log.info("  convex hull of stops + %.0f m: %.1f km2", STUDY_AREA_BUFFER_M, area.area / 1e6)
    _done(t)

    t = _step("3. census sections, population and income")
    sections = build_sections(
        files["ine_sections"],
        raw / "ine" / "seccionado_2025",
        files["ine_adrh_demography"],
        files["ine_adrh_income"],
        area,
    )
    sections_union = shapely.union_all(sections.geometry.values)
    _done(t)

    t = _step("4. OSM extract")
    x0, y0, x1, y1 = sections_union.bounds
    lon, lat = to_wgs([x0, x1, x0, x1], [y0, y0, y1, y1])
    bbox = (float(lon.min()) - 0.002, float(lat.min()) - 0.002,
            float(lon.max()) + 0.002, float(lat.max()) + 0.002)  # fmt: skip
    osm = extract(files["osm"], bbox)
    _done(t)

    t = _step("5. walk graph")
    sel = [i for i, tags in enumerate(osm.way_tags) if is_walkable(tags)]
    xy = [to_utm(osm.way_lon[i], osm.way_lat[i]) for i in sel]
    graph = build_walk_graph(
        [osm.way_nodes[i] for i in sel], [p[0] for p in xy], [p[1] for p in xy], clip=area
    )
    g_lon, g_lat = to_wgs(graph.x, graph.y)
    np.savez_compressed(
        out / paths.WALK_GRAPH_FILE,
        node_lon=g_lon,
        node_lat=g_lat,
        indptr=graph.indptr,
        indices=graph.indices,
        length_m=graph.length_m,
    )
    log.info(
        "  %d walkable ways -> %d nodes, %d edges, %.0f km",
        len(sel), graph.n_nodes, graph.n_edges, float(graph.length_m.sum()) / 2000.0,
    )  # fmt: skip
    _done(t)

    t = _step("5b. drive graph (buses)")
    dsel = [i for i, tags in enumerate(osm.way_tags) if is_drivable(tags)]
    dxy = [to_utm(osm.way_lon[i], osm.way_lat[i]) for i in dsel]
    drive = build_drive_graph(
        [osm.way_nodes[i] for i in dsel],
        [p[0] for p in dxy],
        [p[1] for p in dxy],
        [osm.way_tags[i] for i in dsel],
        clip=area,
    )
    d_lon, d_lat = to_wgs(drive.x, drive.y)
    np.savez_compressed(
        out / paths.DRIVE_GRAPH_FILE,
        node_lon=d_lon,
        node_lat=d_lat,
        indptr=drive.indptr,
        indices=drive.indices,
        length_m=drive.length_m,
        speed_kmh=drive.speed_kmh,
        highway_class=drive.highway_class,
        highway_classes=np.array(HIGHWAY_CLASSES),
    )
    drive_stats = drive_graph_sanity(drive, files["gtfs"])
    drive_stats.update(
        {
            "ways": len(dsel),
            "nodes": drive.n_nodes,
            "directed_edges": drive.n_edges,
            "km_directed": round(float(drive.length_m.sum()) / 1000.0, 1),
            "highway_classes": list(HIGHWAY_CLASSES),
        }
    )
    log.info(
        "  %d drivable ways -> %d nodes, %d directed edges",
        len(dsel), drive.n_nodes, drive.n_edges,
    )  # fmt: skip
    _done(t)

    t = _step("6. buildings (cadastre + OSM use)")
    cadastre = bld.read_cadastre_buildings(
        files["idena_buildings"], files["idena_building_heights"], sections_union
    )
    osm_b = bld.osm_buildings_frame(osm.building_wkb, osm.building_tags)
    feats = gpd.GeoDataFrame(
        {"amenity": [t.get("amenity", "") for t in osm.feature_tags]},
        geometry=shapely.from_wkb(osm.feature_wkb),
        crs=WGS84,
    ).to_crs(UTM30)
    facilities = feats[feats["amenity"].isin(FACILITY_AMENITIES) & (feats.area > 0)]
    industrial = read_wfs_geojson(files["idena_industrial"])[["geometry"]]
    landuse = gpd.GeoDataFrame(
        {"landuse": [t.get("landuse", "") for t in osm.landuse_tags]},
        geometry=shapely.from_wkb(osm.landuse_wkb),
        crs=WGS84,
    ).to_crs(UTM30)
    buildings = bld.classify_buildings(
        cadastre, osm_b, facilities[["geometry"]], industrial, landuse
    )
    _done(t)

    t = _step("7. POIs")
    pois = build_pois(
        area,
        files["idena_health_primary"],
        files["idena_health_special"],
        files["idena_education"],
        files["idena_industrial"],
        osm.feature_wkb,
        osm.feature_tags,
        osm.feature_ids,
    )
    _done(t)

    t = _step("8. 200 m dasymetric grid")
    zb = build_zones(sections, buildings, pois, area, CELL_SIZE_M)
    _done(t)

    t = _step("9. write bundle")
    _write_bundle(out, area, sections, zb, pois)
    manifest = _manifest(files, out, area, sections, zb, pois, graph.n_nodes, graph.n_edges)
    manifest["drive_graph"] = drive_stats
    (out / paths.MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _summary(sections, zb, pois, out)
    _done(t)


def _write_bundle(
    out: Path,
    area: shapely.Geometry,
    sections: gpd.GeoDataFrame,
    zb: ZoneBuild,
    pois: pd.DataFrame,
) -> None:
    sa = gpd.GeoDataFrame({"name": ["study_area"]}, geometry=[area], crs=UTM30).to_crs(WGS84)
    sa["area_km2"] = round(area.area / 1e6, 3)
    sa["buffer_m"] = STUDY_AREA_BUFFER_M
    sa.geometry = shapely.set_precision(sa.geometry.values, 1e-6)
    (out / paths.STUDY_AREA_FILE).write_text(sa.to_json(drop_id=True) + "\n", encoding="utf-8")

    sec = sections.copy()
    sec["population_in_study_area"] = (
        zb.section_population_in_area.reindex(sec["section_id"]).fillna(0).to_numpy()
    )
    sec["geometry"] = sec.geometry.simplify(SECTION_SIMPLIFY_M, preserve_topology=True)
    sec = sec.to_crs(WGS84)
    sec["geometry"] = shapely.set_precision(sec.geometry.values, 1e-6)
    sec = gpd.GeoDataFrame(
        {
            "section_id": sec["section_id"].astype(str),
            "municipality_code": sec["municipality_code"].astype(str),
            "municipality": sec["municipality"].astype(str),
            "population": sec["population"].astype(np.int32),
            "population_in_study_area": sec["population_in_study_area"].astype(np.int32),
            "income_per_capita": sec["income_per_capita"].astype("float32"),
            "income_per_household": sec["income_per_household"].astype("float32"),
            "income_year": np.int16(ADRH_YEAR),
        },
        geometry=sec.geometry.values,
        crs=WGS84,
    )
    sec.to_parquet(out / paths.SECTIONS_FILE, compression="zstd", index=False)

    zones = zb.zones.copy()
    zones["geometry"] = shapely.set_precision(zones.geometry.values, 1e-7)
    zones.to_parquet(out / paths.ZONES_FILE, compression="zstd", index=False)
    zb.zone_sections.to_parquet(out / paths.ZONE_SECTIONS_FILE, compression="zstd", index=False)

    p = pois[["poi_id", "category", "name", "lon", "lat", "weight", "source", "source_id"]]
    p.to_parquet(out / paths.POIS_FILE, compression="zstd", index=False)


def _manifest(
    files: dict[str, Path],
    out: Path,
    area: shapely.Geometry,
    sections: gpd.GeoDataFrame,
    zb: ZoneBuild,
    pois: pd.DataFrame,
    n_nodes: int,
    n_edges: int,
) -> dict[str, object]:
    outputs = {}
    for f in sorted(out.iterdir()):
        if f.name == paths.MANIFEST_FILE or f.is_dir():
            continue
        outputs[f.name] = {"bytes": f.stat().st_size, "sha256": sha256_file(f)}
    return {
        "generated": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "scripts/build_data.py",
        "parameters": {
            "study_area_buffer_m": STUDY_AREA_BUFFER_M,
            "cell_size_m": CELL_SIZE_M,
            "max_walk_edge_m": MAX_EDGE_M,
            "section_simplify_m": SECTION_SIMPLIFY_M,
            "adrh_year": ADRH_YEAR,
        },
        "sources": [describe(SOURCES[k], p) for k, p in files.items()],
        "counts": {
            "study_area_km2": round(area.area / 1e6, 2),
            "sections": len(sections),
            "section_population_total": int(sections["population"].sum()),
            "population_in_study_area": int(zb.zones["population"].sum()),
            "zones": len(zb.zones),
            "zones_populated": int((zb.zones["population"] > 0).sum()),
            "zone_section_pieces": len(zb.zone_sections),
            "dasymetric_tiers": zb.fallback_counts,
            "walk_nodes": n_nodes,
            "walk_edges": n_edges,
            "pois": {k: int(v) for k, v in pois["category"].value_counts().sort_index().items()},
            "sections_without_income": int(sections["income_per_capita"].isna().sum()),
        },
        "outputs": outputs,
    }


def _summary(sections: gpd.GeoDataFrame, zb: ZoneBuild, pois: pd.DataFrame, out: Path) -> None:
    z = zb.zones
    log.info("-- summary")
    log.info("  population in study area: %d (sections total %d)",
             int(z.population.sum()), int(sections.population.sum()))  # fmt: skip
    top = z.groupby("municipality")["population"].sum().sort_values(ascending=False).head(12)
    for m, v in top.items():
        log.info("    %-32s %8d", m, v)
    for cat in ("hospital", "university"):
        log.info("  %s: %s", cat, "; ".join(pois.loc[pois.category == cat, "name"]))
    size = sum(f.stat().st_size for f in out.iterdir() if f.is_file())
    log.info("  bundle size: %.2f MB", size / 1e6)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-download every raw input")
    ap.add_argument("--skip-download", action="store_true", help="use cached raw files only")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    t0 = time.perf_counter()
    run(force=args.force, skip_download=args.skip_download)
    log.info("done in %.1f s", time.perf_counter() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
