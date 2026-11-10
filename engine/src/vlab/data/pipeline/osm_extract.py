"""Single pass over the OSM extract with pyosmium.

Collects, inside the study-area bounding box:

* walkable highway ways (node ids + coordinates) for the pedestrian graph,
* building footprints (for dasymetric population and the activity proxy),
* land-use polygons (residential / industrial / commercial / retail),
* candidate features for the POI categories.

Geometries are kept as hex WKB strings. Only plain data leaves this module; the
classification rules live in :mod:`vlab.data.pipeline.walk_graph`,
:mod:`~vlab.data.pipeline.buildings` and :mod:`~vlab.data.pipeline.pois`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt

from vlab.data.pipeline.common import log

# Tags copied for each kind of object (everything else is dropped).
WAY_TAGS = (
    "highway", "foot", "access", "sidewalk", "sidewalk:both", "sidewalk:left",
    "sidewalk:right", "footway", "area", "service", "motorroad", "indoor", "name",
)  # fmt: skip
BUILDING_TAGS = (
    "building", "building:levels", "building:levels:underground", "height", "amenity",
    "shop", "office", "craft", "industrial", "tourism", "leisure", "healthcare", "name",
    "building:use",
)  # fmt: skip
FEATURE_TAGS = (
    "name", "official_name", "short_name", "alt_name", "operator", "operator:type",
    "amenity", "healthcare", "healthcare:speciality", "shop", "isced:level", "school",
    "school:type", "landuse", "place", "highway", "building", "brand", "emergency",
    "university", "college", "website", "disused", "abandoned", "ref",
)  # fmt: skip

FEATURE_AMENITIES = frozenset(
    {"hospital", "clinic", "doctors", "university", "college", "school", "townhall"}
)
LANDUSES = frozenset({"residential", "industrial", "commercial", "retail"})
CITY_CENTRE_NAMES = frozenset({"Plaza del Castillo", "Gazteluko plaza"})


@dataclass
class OsmExtract:
    """Raw objects pulled from the OSM file (coordinates in WGS84)."""

    way_ids: list[int] = field(default_factory=list)
    way_nodes: list[npt.NDArray[np.int64]] = field(default_factory=list)
    way_lon: list[npt.NDArray[np.float64]] = field(default_factory=list)
    way_lat: list[npt.NDArray[np.float64]] = field(default_factory=list)
    way_tags: list[dict[str, str]] = field(default_factory=list)
    building_wkb: list[str] = field(default_factory=list)
    building_tags: list[dict[str, str]] = field(default_factory=list)
    building_ids: list[str] = field(default_factory=list)
    landuse_wkb: list[str] = field(default_factory=list)
    landuse_tags: list[dict[str, str]] = field(default_factory=list)
    landuse_ids: list[str] = field(default_factory=list)
    feature_wkb: list[str] = field(default_factory=list)
    feature_tags: list[dict[str, str]] = field(default_factory=list)
    feature_ids: list[str] = field(default_factory=list)


def _pick(tags: object, keys: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k in keys:
        v = tags.get(k)  # type: ignore[attr-defined]
        if v is not None:
            out[k] = str(v)
    return out


def _is_feature(t: dict[str, str]) -> bool:
    return (
        t.get("amenity") in FEATURE_AMENITIES
        or "healthcare" in t
        or t.get("shop") == "supermarket"
        or t.get("name") in CITY_CENTRE_NAMES
    )


def extract(pbf: Path, bbox: tuple[float, float, float, float]) -> OsmExtract:
    """Scan ``pbf`` and keep the objects intersecting ``bbox`` (lon/lat min-max)."""
    import osmium  # pipeline-only dependency
    import shapely
    from osmium.osm import Area, Node, Way

    lon0, lat0, lon1, lat1 = bbox
    out = OsmExtract()
    wkb = osmium.geom.WKBFactory()
    area_keys = osmium.filter.KeyFilter(
        "building", "landuse", "amenity", "healthcare", "shop", "place", "highway", "name"
    )
    fp = (
        osmium.FileProcessor(str(pbf))
        .with_locations()
        .with_areas(area_keys)
        .with_filter(osmium.filter.EmptyTagFilter())
    )
    n_bad = 0
    for obj in fp:
        if isinstance(obj, Node):
            loc = obj.location
            if not loc.valid() or not (lon0 <= loc.lon <= lon1 and lat0 <= loc.lat <= lat1):
                continue
            t = _pick(obj.tags, FEATURE_TAGS)
            if _is_feature(t):
                out.feature_wkb.append(wkb.create_point(obj))
                out.feature_tags.append(t)
                out.feature_ids.append(f"n{obj.id}")
        elif isinstance(obj, Way):
            if "highway" not in obj.tags:
                continue
            try:
                ids = np.fromiter((n.ref for n in obj.nodes), dtype=np.int64)
                lon = np.fromiter((n.lon for n in obj.nodes), dtype=np.float64)
                lat = np.fromiter((n.lat for n in obj.nodes), dtype=np.float64)
            except osmium.InvalidLocationError:
                n_bad += 1
                continue
            if len(ids) < 2:
                continue
            inside = (lon >= lon0) & (lon <= lon1) & (lat >= lat0) & (lat <= lat1)
            if not inside.any():
                continue
            out.way_ids.append(obj.id)
            out.way_nodes.append(ids)
            out.way_lon.append(lon)
            out.way_lat.append(lat)
            out.way_tags.append(_pick(obj.tags, WAY_TAGS))
        elif isinstance(obj, Area):
            try:
                geom = wkb.create_multipolygon(obj)
            except Exception:  # broken multipolygons are skipped
                n_bad += 1
                continue
            g = shapely.from_wkb(geom)
            gx0, gy0, gx1, gy1 = g.bounds
            if gx1 < lon0 or gx0 > lon1 or gy1 < lat0 or gy0 > lat1:
                continue
            oid = f"{'w' if obj.from_way() else 'r'}{obj.orig_id()}"
            tags = obj.tags
            if "building" in tags and tags.get("building") != "no":
                out.building_wkb.append(geom)
                out.building_tags.append(_pick(tags, BUILDING_TAGS))
                out.building_ids.append(oid)
            if tags.get("landuse") in LANDUSES:
                out.landuse_wkb.append(geom)
                out.landuse_tags.append(_pick(tags, FEATURE_TAGS))
                out.landuse_ids.append(oid)
            t = _pick(tags, FEATURE_TAGS)
            if _is_feature(t):
                out.feature_wkb.append(geom)
                out.feature_tags.append(t)
                out.feature_ids.append(oid)
    log.info(
        "  OSM: %d highway ways, %d buildings, %d land-use polygons, %d POI candidates "
        "(%d objects with broken geometry skipped)",
        len(out.way_ids), len(out.building_wkb), len(out.landuse_wkb), len(out.feature_wkb), n_bad,
    )  # fmt: skip
    return out
