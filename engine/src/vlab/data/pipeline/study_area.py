"""Study area: convex hull of the GTFS stops buffered by 1.5 km."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry

from vlab.data.pipeline.common import STUDY_AREA_BUFFER_M, to_utm


def read_stop_coords(gtfs_zip: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (lon, lat) of the physical stops in ``stops.txt`` (no GTFS library needed)."""
    with zipfile.ZipFile(gtfs_zip) as zf, zf.open("stops.txt") as fh:
        reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig"))
        lon: list[float] = []
        lat: list[float] = []
        for row in reader:
            if row.get("location_type", "0") not in ("", "0"):
                continue
            lon.append(float(row["stop_lon"]))
            lat.append(float(row["stop_lat"]))
    if not lon:
        raise ValueError(f"no stops in {gtfs_zip}")
    lo, la = np.asarray(lon), np.asarray(lat)
    if not (np.all((lo > -2.2) & (lo < -1.2)) and np.all((la > 42.5) & (la < 43.1))):
        raise ValueError("GTFS stops fall outside the expected Pamplona region")
    return lo, la


def study_area_utm(gtfs_zip: Path, buffer_m: float = STUDY_AREA_BUFFER_M) -> BaseGeometry:
    """Convex hull of the stops in EPSG:25830, buffered by ``buffer_m``."""
    lon, lat = read_stop_coords(gtfs_zip)
    x, y = to_utm(lon, lat)
    hull = shapely.convex_hull(shapely.multipoints(np.column_stack([x, y])))
    return shapely.buffer(hull, buffer_m, quad_segs=16)
