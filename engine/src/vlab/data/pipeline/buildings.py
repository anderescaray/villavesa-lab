"""Building floor area and use class.

Geometry and number of floors come from the foral cadastre of Navarra (every
building volume with its height label, e.g. ``S+V+T``: basement + 5 floors +
roof terrace). The use (residential or not) is not published in that layer, so
it is inferred from OpenStreetMap with explicit rules, in priority order:

1. the OSM building polygon containing the volume (``building=apartments`` ...),
2. OSM facility areas (hospital, school, university, ...) containing it,
3. an official industrial estate (IDENA) containing it,
4. the OSM land use containing it (``landuse=residential|industrial|...``),
5. otherwise ``unknown``.
"""

from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import numpy.typing as npt
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry

from vlab.data.pipeline.common import UTM30, log

RESIDENTIAL = "residential"
NON_RESIDENTIAL = "non_residential"
UNKNOWN = "unknown"
EXCLUDED = "excluded"

OSM_RESIDENTIAL = frozenset(
    {
        "apartments", "residential", "house", "detached", "semidetached_house", "terrace",
        "dormitory", "bungalow", "cabin", "farm", "flats", "home", "semi", "townhouse",
    }
)  # fmt: skip
OSM_NON_RESIDENTIAL = frozenset(
    {
        "industrial", "commercial", "retail", "office", "warehouse", "school", "university",
        "college", "hospital", "church", "chapel", "cathedral", "mosque", "religious",
        "civic", "public", "sports_centre", "sports_hall", "stadium", "government",
        "kindergarten", "train_station", "transportation", "hotel", "supermarket",
        "manufacture", "factory", "service", "fire_station", "clinic", "museum", "library",
        "conference_centre", "grandstand", "pavilion", "data_center", "bank", "kiosk",
        "monastery", "convent", "theatre", "cinema",
    }
)  # fmt: skip
OSM_EXCLUDED = frozenset(
    {
        "garage", "garages", "shed", "roof", "carport", "hut", "ruins", "construction",
        "greenhouse", "farm_auxiliary", "barn", "stable", "parking", "bunker", "tank",
        "silo", "storage_tank", "transformer_tower", "toilets", "cowshed", "sty",
        "collapsed", "damaged", "demolished", "abandoned", "no", "container", "bridge",
    }
)  # fmt: skip
NON_RES_AMENITY = frozenset(
    {
        "school", "university", "college", "hospital", "clinic", "townhall", "place_of_worship",
        "library", "police", "fire_station", "community_centre", "theatre", "cinema",
        "marketplace", "bus_station", "courthouse", "kindergarten", "social_facility",
    }
)  # fmt: skip
MIN_FOOTPRINT_M2 = 15.0

_ROMAN = re.compile(r"^[IVXLC]+$")
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman_to_int(s: str) -> int:
    """Value of a Roman numeral (``"VIII"`` -> 8)."""
    total = 0
    prev = 0
    for ch in reversed(s):
        v = _ROMAN_VALUES[ch]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def floors_above_ground(label: str | None) -> int:
    """Full floors above ground in a cadastre height label.

    Labels are ``+``-separated tokens; Roman numerals are floors above ground,
    other tokens (``S``/``SS``/``2S`` basements, ``T`` terrace, ``P`` porch,
    ``E`` mezzanine, ``PAV`` paving, ``PISCINA`` ...) are not counted. Returns 0
    for volumes with no floor above ground.
    """
    if not label:
        return 0
    best = 0
    for tok in str(label).upper().replace(" ", "").split("+"):
        if _ROMAN.match(tok):
            best = max(best, roman_to_int(tok))
    return min(best, 40)


def read_cadastre_buildings(
    polygons_zip: Path, labels_zip: Path, area: BaseGeometry
) -> gpd.GeoDataFrame:
    """Cadastre volumes intersecting ``area`` with footprint, floors and floor area."""
    bbox = tuple(area.bounds)
    poly = gpd.read_file(f"zip://{polygons_zip}", bbox=bbox, columns=["FEATURE"])
    lab = gpd.read_file(f"zip://{labels_zip}", bbox=bbox, columns=["CADTEXT"])
    for g in (poly, lab):
        if g.crs is None or g.crs.to_epsg() != 25830:
            raise ValueError("cadastre layers are expected in EPSG:25830")
    poly = poly[poly.geometry.notna()].reset_index(drop=True)
    lab = lab[lab.geometry.notna()].reset_index(drop=True)
    lab["floors"] = lab["CADTEXT"].map(floors_above_ground).astype(np.int16)
    joined = gpd.sjoin(
        lab[["floors", "CADTEXT", "geometry"]], poly[["geometry"]], predicate="within"
    )
    # One label per volume in >98% of cases; otherwise keep the tallest label.
    per_poly = joined.sort_values("floors", ascending=False).groupby("index_right").first()
    poly["floors"] = per_poly["floors"].reindex(poly.index).fillna(0).astype(np.int16)
    poly["label"] = per_poly["CADTEXT"].reindex(poly.index)
    poly["footprint_m2"] = poly.geometry.area
    poly = poly[poly["footprint_m2"] >= MIN_FOOTPRINT_M2]
    poly = poly[shapely.intersects(poly.geometry.values, area)].reset_index(drop=True)
    poly["floor_area_m2"] = poly["footprint_m2"] * poly["floors"]
    log.info(
        "  cadastre: %d volumes, %.2f km2 footprint, %.2f km2 floor area above ground; "
        "%.1f%% of footprint without a floor label",
        len(poly), poly.footprint_m2.sum() / 1e6, poly.floor_area_m2.sum() / 1e6,
        100.0 * poly.loc[poly.floors == 0, "footprint_m2"].sum() / poly.footprint_m2.sum(),
    )  # fmt: skip
    return poly[["floors", "label", "footprint_m2", "floor_area_m2", "geometry"]]


def osm_building_class(tags: dict[str, str]) -> str:
    """Use class of an OSM building from its tags."""
    b = tags.get("building", "yes")
    if b in OSM_RESIDENTIAL:
        return RESIDENTIAL
    if b in OSM_NON_RESIDENTIAL:
        return NON_RESIDENTIAL
    if b in OSM_EXCLUDED:
        return EXCLUDED
    if tags.get("amenity") in NON_RES_AMENITY or "office" in tags or "industrial" in tags:
        return NON_RESIDENTIAL
    if "craft" in tags or tags.get("tourism") in {"hotel", "hostel", "museum"}:
        return NON_RESIDENTIAL
    return UNKNOWN


def _first_containing(
    points: gpd.GeoSeries, polys: gpd.GeoDataFrame, col: str
) -> npt.NDArray[np.object_]:
    """Value of ``col`` of the smallest polygon containing each point (``None`` if none)."""
    out = np.full(len(points), None, dtype=object)
    if polys.empty or len(points) == 0:
        return out
    pts = gpd.GeoDataFrame({"_pos": np.arange(len(points))}, geometry=points.values, crs=points.crs)
    cand = polys[[col, "geometry"]].assign(_a=polys.geometry.area)
    j = gpd.sjoin(pts, cand, predicate="within")
    j = j.sort_values(["_pos", "_a"]).drop_duplicates("_pos")
    out[j["_pos"].to_numpy()] = j[col].to_numpy()
    return out


LANDUSE_CLASS = {
    "residential": RESIDENTIAL,
    "industrial": NON_RESIDENTIAL,
    "commercial": NON_RESIDENTIAL,
    "retail": NON_RESIDENTIAL,
}


def classify_buildings(
    buildings: gpd.GeoDataFrame,
    osm_buildings: gpd.GeoDataFrame,
    facility_areas: gpd.GeoDataFrame,
    industrial_estates: gpd.GeoDataFrame,
    landuse: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Add ``use`` (residential / non_residential / unknown / excluded) and ``use_source``.

    All inputs in EPSG:25830; ``osm_buildings`` needs an ``osm_class`` column and
    ``landuse`` a ``landuse`` column.
    """
    pts = buildings.geometry.representative_point()
    n = len(buildings)
    use = _first_containing(pts, osm_buildings, "osm_class")
    source = np.where(pd.notna(use), "osm_building", "none").astype(object)

    def resolve(values: npt.NDArray[np.object_], tag: str) -> None:
        todo = np.flatnonzero(pd.isna(use) | (use == UNKNOWN))
        if todo.size == 0:
            return
        got = values[todo]
        hit = pd.notna(got)
        use[todo[hit]] = got[hit]
        source[todo[hit]] = tag

    def contained(polys: gpd.GeoDataFrame, col: str) -> npt.NDArray[np.object_]:
        return _first_containing(pts, polys, col)

    if not facility_areas.empty:
        resolve(contained(facility_areas.assign(c=NON_RESIDENTIAL), "c"), "osm_facility")
    if not industrial_estates.empty:
        resolve(contained(industrial_estates.assign(c=NON_RESIDENTIAL), "c"), "industrial_estate")
    if not landuse.empty:
        lu = contained(landuse, "landuse")
        lu_class = np.array([LANDUSE_CLASS.get(v) if v is not None else None for v in lu],
                            dtype=object)  # fmt: skip
        resolve(lu_class, "osm_landuse")
    use[pd.isna(use)] = UNKNOWN
    out = buildings.copy()
    out["use"] = use.astype(str) if n else np.array([], dtype=str)
    out["use_source"] = source.astype(str) if n else np.array([], dtype=str)
    total = max(1.0, float(out["floor_area_m2"].sum()))
    shares = out.groupby("use")["floor_area_m2"].sum() / total
    log.info("  building floor area by use: %s", {k: round(float(v), 3) for k, v in shares.items()})
    src = out.groupby("use_source")["floor_area_m2"].sum() / total
    log.info("  use decided by: %s", {k: round(float(v), 3) for k, v in src.items()})
    return out


def osm_buildings_frame(wkb: list[str], tags: list[dict[str, str]]) -> gpd.GeoDataFrame:
    """OSM building polygons (EPSG:25830) with their use class."""
    g = gpd.GeoDataFrame(
        {"osm_class": [osm_building_class(t) for t in tags]},
        geometry=shapely.from_wkb(wkb),
        crs="EPSG:4326",
    ).to_crs(UTM30)
    g = g[g.geometry.notna() & g.is_valid]
    return g
