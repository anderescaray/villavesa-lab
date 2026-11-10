"""Points of interest (accessibility destinations), curated with explicit rules.

Official registers are preferred where they exist (Gobierno de Navarra via
IDENA); OpenStreetMap fills the categories without an official list.

=====================  ===========================================================
category               rule
=====================  ===========================================================
``hospital``           SNS specialised-care register (IDENA ``DOTACI_Sym_SNSEspecial``),
                       entries named "Hospital ..." / "Clínica ...", one point per
                       name; mental-health-only centres listed in
                       :data:`NON_GENERAL_HOSPITALS` excluded.
``health_centre``      SNS primary-care register (``DOTACI_Sym_SNSPrimaria``): every
                       public centro de salud / consultorio.
``university``         OSM ``amenity=university`` features with a name, grouped by
                       institution (name before " - ") and clustered into campuses
                       (features within 300 m merge); one point per campus at the
                       largest feature.
``industrial_estate``  Official industrial estates (``DOTACI_Pol_PolInd``), polygons
                       with the same name dissolved, of at least 5 ha; weight = area
                       in m².
``city_centre``        OSM feature named "Plaza del Castillo" (one point).
``secondary_school``   Education register (``DOTACI_Sym_Ctroseduca``) centres teaching
                       ESO or Bachillerato.
``supermarket``        OSM ``shop=supermarket``, duplicates (same name within 75 m
                       or any within 15 m) merged.
=====================  ===========================================================

Only POIs inside the study area are kept.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry

from vlab.data.loaders import POI_CATEGORIES
from vlab.data.pipeline.common import UTM30, log, to_wgs

CATEGORIES = POI_CATEGORIES
MIN_INDUSTRIAL_AREA_M2 = 50_000.0
CAMPUS_MERGE_M = 300.0
# Specialised-care register entries that are not general hospitals (documented curation).
NON_GENERAL_HOSPITALS = frozenset({"clinica arcangel san miguel, s.a."})
CITY_CENTRE_NAMES = ("Plaza del Castillo", "Gazteluko plaza")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def read_wfs_geojson(path: Path) -> gpd.GeoDataFrame:
    """Read an IDENA WFS GeoJSON response (EPSG:25830) and check it is complete."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("type") != "FeatureCollection":
        raise ValueError(f"{path.name}: not a GeoJSON FeatureCollection")
    matched = raw.get("numberMatched", raw.get("totalFeatures"))
    feats = raw.get("features", [])
    if isinstance(matched, int) and matched != len(feats):
        raise ValueError(f"{path.name}: truncated WFS response ({len(feats)} of {matched})")
    gdf = gpd.GeoDataFrame.from_features(feats, crs=UTM30)
    return gdf


def _frame(
    category: str,
    names: list[str],
    geoms: list[BaseGeometry] | np.ndarray,
    weights: list[float] | np.ndarray,
    source: str,
    source_ids: list[str],
) -> pd.DataFrame:
    pts = shapely.points(np.array([shapely.get_coordinates(g)[0] for g in geoms]).reshape(-1, 2))
    x = shapely.get_x(pts)
    y = shapely.get_y(pts)
    lon, lat = to_wgs(x, y)
    return pd.DataFrame(
        {
            "category": category,
            "name": names,
            "x": x,
            "y": y,
            "lon": lon,
            "lat": lat,
            "weight": np.asarray(weights, dtype=np.float64),
            "source": source,
            "source_id": source_ids,
        }
    )


def hospitals(special: gpd.GeoDataFrame, area: BaseGeometry) -> pd.DataFrame:
    g = special[special.within(area)].copy()
    g["n"] = g["CENSAN"].map(_norm)
    g = g[g["n"].str.match(r"^(hospital|clinica) ") & ~g["n"].isin(NON_GENERAL_HOSPITALS)]
    g = g.sort_values("IDCENSAN").drop_duplicates("n")
    return _frame(
        "hospital", g["CENSAN"].tolist(), g.geometry.values, np.ones(len(g)),
        "IDENA DOTACI_Sym_SNSEspecial", ("SNS:" + g["IDCENSAN"]).tolist(),
    )  # fmt: skip


def health_centres(primary: gpd.GeoDataFrame, area: BaseGeometry) -> pd.DataFrame:
    g = primary[primary.within(area)].sort_values("IDCENSAN")
    # Two register entries at the same spot are one destination.
    key = (
        g.geometry.x.round(-1).astype(int).astype(str)
        + "_"
        + g.geometry.y.round(-1).astype(int).astype(str)
    )
    g = g[~key.duplicated()]
    return _frame(
        "health_centre", g["CENSAN"].tolist(), g.geometry.values, np.ones(len(g)),
        "IDENA DOTACI_Sym_SNSPrimaria", ("SNS:" + g["IDCENSAN"]).tolist(),
    )  # fmt: skip


def secondary_schools(edu: gpd.GeoDataFrame, area: BaseGeometry) -> pd.DataFrame:
    g = edu[edu.within(area)]
    g = g[(g["ESO"].fillna(0).astype(int) == 1) | (g["BACHILLER"].fillna(0).astype(int) == 1)]
    g = g.sort_values("IDCENTRO").drop_duplicates("IDCENTRO")
    names = g["CENTROAB"].fillna(g["CENTRO"]).tolist()
    return _frame(
        "secondary_school", names, g.geometry.values, np.ones(len(g)),
        "IDENA DOTACI_Sym_Ctroseduca", ("EDU:" + g["IDCENTRO"].astype(str)).tolist(),
    )  # fmt: skip


def industrial_estates(polind: gpd.GeoDataFrame, area: BaseGeometry) -> pd.DataFrame:
    g = polind[polind.intersects(area)]
    # Estates mapped as several polygons with the same name are one destination.
    g = g.dissolve(by="NOMBRE", aggfunc={"CODAAE": "min"}, as_index=False)
    g["a"] = g.geometry.area
    g = g[g["a"] >= MIN_INDUSTRIAL_AREA_M2]
    pts = g.geometry.representative_point()
    inside = pts.within(area)
    g, pts = g[inside], pts[inside]
    order = np.argsort(-g["a"].to_numpy(), kind="stable")
    g, pts = g.iloc[order], pts.iloc[order]
    return _frame(
        "industrial_estate", g["NOMBRE"].fillna("Industrial estate").tolist(), pts.values,
        g["a"].round().to_numpy(), "IDENA DOTACI_Pol_PolInd",
        ("POLIND:" + g["CODAAE"].astype(str)).tolist(),
    )  # fmt: skip


def _osm_frame(wkb: list[str], tags: list[dict[str, str]], ids: list[str]) -> gpd.GeoDataFrame:
    g = gpd.GeoDataFrame(
        {"tags": tags, "osm_id": ids}, geometry=shapely.from_wkb(wkb), crs="EPSG:4326"
    ).to_crs(UTM30)
    g["name"] = [t.get("name", "") for t in tags]
    g["amenity"] = [t.get("amenity", "") for t in tags]
    g["shop"] = [t.get("shop", "") for t in tags]
    return g


def universities(osm: gpd.GeoDataFrame, area: BaseGeometry) -> pd.DataFrame:
    g = osm[(osm["amenity"] == "university") & (osm["name"] != "")]
    g = g[g.intersects(area)].copy()
    g["a"] = g.geometry.area
    # The institution is the name before " - " (faculty suffixes are dropped).
    g["inst"] = g["name"].map(lambda n: _norm(n.split(" - ")[0]))
    names, geoms, ids = [], [], []
    for _, members_all in g.groupby("inst", sort=True):
        # Features of one institution within CAMPUS_MERGE_M of each other form one campus.
        blobs = shapely.unary_union(members_all.geometry.buffer(CAMPUS_MERGE_M / 2).values)
        for part in getattr(blobs, "geoms", [blobs]):
            members = members_all[members_all.intersects(part)]
            top = members.sort_values(["a", "osm_id"], ascending=[False, True]).iloc[0]
            rp = top.geometry.representative_point() if top["a"] > 0 else top.geometry
            if not rp.within(area):
                continue
            names.append(str(top["name"]))
            geoms.append(rp)
            ids.append("OSM:" + str(top["osm_id"]))
    order = np.argsort(names, kind="stable")
    return _frame(
        "university", [names[i] for i in order], [geoms[i] for i in order],
        np.ones(len(order)), "OpenStreetMap amenity=university", [ids[i] for i in order],
    )  # fmt: skip


def city_centre(osm: gpd.GeoDataFrame, area: BaseGeometry) -> pd.DataFrame:
    g = osm[osm["name"].isin(CITY_CENTRE_NAMES) & osm.intersects(area)].copy()
    if g.empty:
        raise ValueError("Plaza del Castillo not found in the OSM extract")
    g["a"] = g.geometry.area
    top = g.sort_values(["a", "osm_id"], ascending=[False, True]).iloc[0]
    rp = top.geometry.representative_point() if top["a"] > 0 else top.geometry
    return _frame(
        "city_centre", ["Plaza del Castillo"], [rp], [1.0], "OpenStreetMap",
        ["OSM:" + str(top["osm_id"])],
    )  # fmt: skip


def supermarkets(osm: gpd.GeoDataFrame, area: BaseGeometry) -> pd.DataFrame:
    g = osm[osm["shop"] == "supermarket"]
    g = g[g.intersects(area)].copy()
    g["pt"] = g.geometry.representative_point()
    g = g[gpd.GeoSeries(g["pt"], crs=UTM30).within(area)]
    g["brand"] = [_norm(t.get("brand") or t.get("name") or "") for t in g["tags"]]
    # Areas first (a mapped shop polygon is better than a node), then by id.
    g["is_area"] = g.geometry.area > 0
    g = g.sort_values(["is_area", "osm_id"], ascending=[False, True]).reset_index(drop=True)
    xy = np.column_stack([shapely.get_x(g["pt"].values), shapely.get_y(g["pt"].values)])
    keep = np.ones(len(g), dtype=bool)
    for i in range(len(g)):
        if not keep[i]:
            continue
        d = np.hypot(*(xy[i + 1 :] - xy[i]).T)
        same = (g["brand"].to_numpy()[i + 1 :] == g["brand"].iloc[i]) & (g["brand"].iloc[i] != "")
        dup = (d < 15.0) | (same & (d < 75.0))
        keep[i + 1 :] &= ~dup
    g = g[keep]
    names = [t.get("name") or t.get("brand") or "Supermarket" for t in g["tags"]]
    return _frame(
        "supermarket", names, g["pt"].values, np.ones(len(g)),
        "OpenStreetMap shop=supermarket", ("OSM:" + g["osm_id"]).tolist(),
    )  # fmt: skip


def build_pois(
    area: BaseGeometry,
    health_primary: Path,
    health_special: Path,
    education: Path,
    industrial: Path,
    osm_wkb: list[str],
    osm_tags: list[dict[str, str]],
    osm_ids: list[str],
) -> pd.DataFrame:
    """All POI categories, with a dense ``poi_id`` (sorted by category, then name)."""
    osm = _osm_frame(osm_wkb, osm_tags, osm_ids)
    frames = [
        hospitals(read_wfs_geojson(health_special), area),
        health_centres(read_wfs_geojson(health_primary), area),
        universities(osm, area),
        industrial_estates(read_wfs_geojson(industrial), area),
        city_centre(osm, area),
        secondary_schools(read_wfs_geojson(education), area),
        supermarkets(osm, area),
    ]
    pois = pd.concat(frames, ignore_index=True)
    pois["category"] = pd.Categorical(pois["category"], categories=CATEGORIES)
    pois = pois.sort_values(["category", "name", "source_id"], kind="stable").reset_index(drop=True)
    pois["category"] = pois["category"].astype(str)
    pois.insert(0, "poi_id", np.arange(len(pois), dtype=np.int32))
    counts = pois["category"].value_counts().reindex(CATEGORIES).fillna(0).astype(int)
    log.info("  POIs: %s", counts.to_dict())
    for cat in CATEGORIES:
        if counts[cat] == 0:
            raise ValueError(f"POI category {cat!r} is empty")
    return pois
