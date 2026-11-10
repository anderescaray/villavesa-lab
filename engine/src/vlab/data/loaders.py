"""Typed loaders with schema validation for the processed data bundle.

Every loader fails loudly with :class:`DataSchemaError` (naming the file and the
violated rule) instead of returning silently malformed data. The bundle is
produced by ``make data`` (``scripts/build_data.py``); see ``docs/data.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import numpy.typing as npt
import pandas as pd
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from vlab.data import paths

POI_CATEGORIES: tuple[str, ...] = (
    "hospital",
    "health_centre",
    "university",
    "industrial_estate",
    "city_centre",
    "secondary_school",
    "supermarket",
)
# Generous bounding box around the Comarca de Pamplona (lon/lat), a sanity guard; rural
# census sections that touch the study area extend well beyond it.
BBOX = (-2.0, 42.6, -1.3, 43.1)


class DataSchemaError(ValueError):
    """A processed file does not match its contract (``docs/architecture.md``)."""


@dataclass(frozen=True)
class Col:
    """Expected column: dtype kind (``i`` int, ``f`` float, ``s`` string), nullability, range."""

    name: str
    kind: str
    nullable: bool = False
    min: float | None = None
    max: float | None = None


def _fail(path: Path, msg: str) -> DataSchemaError:
    return DataSchemaError(
        f"{path}: {msg}. The processed bundle is stale or corrupt; "
        "rebuild it with `make data` (see docs/data.md)."
    )


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise _fail(path, "file not found")


def _check_columns(df: pd.DataFrame, cols: tuple[Col, ...], path: Path) -> None:
    missing = [c.name for c in cols if c.name not in df.columns]
    if missing:
        raise _fail(path, f"missing columns {missing} (has {list(df.columns)})")
    for c in cols:
        s = df[c.name]
        if c.kind == "i" and not pd.api.types.is_integer_dtype(s):
            raise _fail(path, f"column {c.name!r} must be integer, got {s.dtype}")
        if c.kind == "f" and not pd.api.types.is_float_dtype(s):
            raise _fail(path, f"column {c.name!r} must be float, got {s.dtype}")
        if c.kind == "s" and not (
            pd.api.types.is_string_dtype(s) or pd.api.types.is_object_dtype(s)
        ):
            raise _fail(path, f"column {c.name!r} must be string, got {s.dtype}")
        nulls = int(s.isna().sum())
        if nulls and not c.nullable:
            raise _fail(path, f"column {c.name!r} has {nulls} null values")
        if c.kind in "if":
            v = s.dropna().to_numpy(dtype=np.float64)
            if not np.isfinite(v).all():
                raise _fail(path, f"column {c.name!r} has non-finite values")
            if c.min is not None and v.size and v.min() < c.min:
                raise _fail(path, f"column {c.name!r} has values below {c.min} ({v.min()})")
            if c.max is not None and v.size and v.max() > c.max:
                raise _fail(path, f"column {c.name!r} has values above {c.max} ({v.max()})")


def _check_lonlat(lon: npt.ArrayLike, lat: npt.ArrayLike, path: Path) -> None:
    lo = np.asarray(lon, dtype=np.float64)
    la = np.asarray(lat, dtype=np.float64)
    ok = (lo >= BBOX[0]) & (lo <= BBOX[2]) & (la >= BBOX[1]) & (la <= BBOX[3])
    if not ok.all():
        raise _fail(path, f"{int((~ok).sum())} coordinates outside the expected bbox {BBOX}")


def _check_geometry(gdf: gpd.GeoDataFrame, path: Path, types: tuple[str, ...]) -> None:
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        raise _fail(path, f"geometry CRS must be EPSG:4326, got {gdf.crs}")
    if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
        raise _fail(path, "null or empty geometries")
    bad = ~gdf.geom_type.isin(types)
    if bad.any():
        raise _fail(path, f"unexpected geometry types {sorted(set(gdf.geom_type[bad]))}")
    x0, y0, x1, y1 = gdf.total_bounds
    _check_lonlat([x0, x1], [y0, y1], path)


def _dense_ids(s: pd.Series, name: str, path: Path) -> None:
    if not np.array_equal(s.to_numpy(), np.arange(len(s))):
        raise _fail(path, f"{name} must be dense 0..N-1 in row order")


SECTION_COLUMNS = (
    Col("section_id", "s"),
    Col("municipality_code", "s"),
    Col("municipality", "s"),
    Col("population", "i", min=0),
    Col("population_in_study_area", "i", min=0),
    Col("income_per_capita", "f", nullable=True, min=0),
    Col("income_per_household", "f", nullable=True, min=0),
    Col("income_year", "i", min=2015, max=2100),
)
ZONE_COLUMNS = (
    Col("zone_id", "i", min=0),
    Col("x", "f"),
    Col("y", "f"),
    Col("lon", "f"),
    Col("lat", "f"),
    Col("population", "i", min=0),
    Col("activity_weight", "f", min=0),
    Col("n_pois", "i", min=0),
    Col("section_id", "s"),
    Col("municipality", "s"),
)
ZONE_SECTION_COLUMNS = (
    Col("zone_id", "i", min=0),
    Col("section_id", "s"),
    Col("population", "i", min=1),
)
POI_COLUMNS = (
    Col("poi_id", "i", min=0),
    Col("category", "s"),
    Col("name", "s"),
    Col("lon", "f"),
    Col("lat", "f"),
    Col("weight", "f", min=0),
    Col("source", "s"),
    Col("source_id", "s"),
)


def _dir(data_dir: Path | None) -> Path:
    return (data_dir / "processed") if data_dir is not None else paths.processed_dir()


def load_sections(data_dir: Path | None = None) -> gpd.GeoDataFrame:
    """Census sections intersecting the study area (EPSG:4326)."""
    path = _dir(data_dir) / paths.SECTIONS_FILE
    _require_file(path)
    gdf = gpd.read_parquet(path)
    _check_columns(gdf, SECTION_COLUMNS, path)
    _check_geometry(gdf, path, ("Polygon", "MultiPolygon"))
    if gdf["section_id"].duplicated().any():
        raise _fail(path, "duplicate section_id")
    if not gdf["section_id"].str.fullmatch(r"31\d{8}").all():
        raise _fail(path, "section_id must be a 10-digit Navarra CUSEC (31...)")
    if (gdf["population_in_study_area"] > gdf["population"]).any():
        raise _fail(path, "population_in_study_area exceeds population")
    return gdf


def load_zones(data_dir: Path | None = None) -> gpd.GeoDataFrame:
    """200 m analysis cells (geometry EPSG:4326; ``x``/``y`` are EPSG:25830 centres)."""
    path = _dir(data_dir) / paths.ZONES_FILE
    _require_file(path)
    gdf = gpd.read_parquet(path)
    _check_columns(gdf, ZONE_COLUMNS, path)
    _check_geometry(gdf, path, ("Polygon",))
    _dense_ids(gdf["zone_id"], "zone_id", path)
    _check_lonlat(gdf["lon"], gdf["lat"], path)
    for c in ("x", "y"):
        off = np.mod(gdf[c].to_numpy() - 100.0, 200.0)
        if not np.allclose(np.minimum(off, 200.0 - off), 0.0, atol=1e-6):
            raise _fail(path, f"{c} must be the centre of a 200 m cell aligned to multiples of 200")
    empty = (gdf["population"] == 0) & (gdf["activity_weight"] == 0) & (gdf["n_pois"] == 0)
    if empty.any():
        raise _fail(path, f"{int(empty.sum())} zones with no population, activity or POI")
    return gdf


def load_zone_sections(data_dir: Path | None = None) -> pd.DataFrame:
    """Crosswalk zone x section with the population each section puts in each zone."""
    path = _dir(data_dir) / paths.ZONE_SECTIONS_FILE
    _require_file(path)
    df = pd.read_parquet(path)
    _check_columns(df, ZONE_SECTION_COLUMNS, path)
    if df.duplicated(["zone_id", "section_id"]).any():
        raise _fail(path, "duplicate (zone_id, section_id) pairs")
    return df


def load_pois(data_dir: Path | None = None) -> pd.DataFrame:
    """Destinations (``poi_id``, ``category``, ``name``, ``lon``, ``lat``, ``weight``, ...)."""
    path = _dir(data_dir) / paths.POIS_FILE
    _require_file(path)
    df = pd.read_parquet(path)
    _check_columns(df, POI_COLUMNS, path)
    _dense_ids(df["poi_id"], "poi_id", path)
    unknown = set(df["category"]) - set(POI_CATEGORIES)
    if unknown:
        raise _fail(path, f"unknown POI categories {sorted(unknown)}")
    _check_lonlat(df["lon"], df["lat"], path)
    return df


@dataclass(frozen=True)
class WalkGraphData:
    """Raw arrays of ``walk_graph.npz`` (symmetric CSR, lengths in metres)."""

    node_lon: npt.NDArray[np.float64]
    node_lat: npt.NDArray[np.float64]
    indptr: npt.NDArray[np.int32]
    indices: npt.NDArray[np.int32]
    length_m: npt.NDArray[np.float32]

    @property
    def n_nodes(self) -> int:
        return int(self.node_lon.shape[0])

    @property
    def n_edges(self) -> int:
        """Undirected edge count (each edge is stored in both directions)."""
        return int(self.indices.shape[0] // 2)


def load_walk_graph_arrays(data_dir: Path | None = None) -> WalkGraphData:
    """Load and validate the pedestrian graph."""
    path = _dir(data_dir) / paths.WALK_GRAPH_FILE
    _require_file(path)
    with np.load(path) as z:
        expected = {"node_lon": np.float64, "node_lat": np.float64, "indptr": np.int32,
                    "indices": np.int32, "length_m": np.float32}  # fmt: skip
        arrays: dict[str, Any] = {}
        for key, dtype in expected.items():
            if key not in z.files:
                raise _fail(path, f"missing array {key!r} (has {z.files})")
            a = z[key]
            if a.dtype != dtype or a.ndim != 1:
                raise _fail(
                    path, f"array {key!r} must be 1-D {np.dtype(dtype)}, got {a.ndim}-D {a.dtype}"
                )
            arrays[key] = a
    g = WalkGraphData(**arrays)
    n = g.n_nodes
    if g.node_lat.shape[0] != n or g.indptr.shape[0] != n + 1:
        raise _fail(path, "inconsistent node / indptr lengths")
    if g.indptr[0] != 0 or g.indptr[-1] != g.indices.shape[0] or np.any(np.diff(g.indptr) < 0):
        raise _fail(path, "malformed indptr")
    if g.length_m.shape[0] != g.indices.shape[0]:
        raise _fail(path, "length_m and indices differ in length")
    if g.indices.size and (g.indices.min() < 0 or g.indices.max() >= n):
        raise _fail(path, "indices out of range")
    if not (np.isfinite(g.length_m).all() and (g.length_m > 0).all()):
        raise _fail(path, "edge lengths must be finite and positive")
    _check_lonlat(g.node_lon, g.node_lat, path)
    return g


def load_study_area(data_dir: Path | None = None) -> BaseGeometry:
    """Study-area polygon (EPSG:4326)."""
    path = _dir(data_dir) / paths.STUDY_AREA_FILE
    _require_file(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    feats = raw.get("features", [])
    if raw.get("type") != "FeatureCollection" or len(feats) != 1:
        raise _fail(path, "must be a FeatureCollection with exactly one feature")
    geom = shape(feats[0]["geometry"])
    if geom.geom_type != "Polygon" or not geom.is_valid:
        raise _fail(path, f"must hold one valid Polygon, got {geom.geom_type}")
    x0, y0, x1, y1 = geom.bounds
    _check_lonlat([x0, x1], [y0, y1], path)
    return geom


def load_manifest(data_dir: Path | None = None) -> dict[str, Any]:
    """Provenance manifest (sources, licences, counts, checksums)."""
    path = _dir(data_dir) / paths.MANIFEST_FILE
    _require_file(path)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for key in ("sources", "counts", "outputs"):
        if key not in data:
            raise _fail(path, f"missing key {key!r}")
    return data
