"""Shared constants and helpers for the pipeline steps."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np
import numpy.typing as npt
from pyproj import Transformer

log = logging.getLogger("vlab.data")

WGS84 = "EPSG:4326"
UTM30 = "EPSG:25830"

STUDY_AREA_BUFFER_M = 1500.0
CELL_SIZE_M = 200
MAX_EDGE_M = 60.0

_TO_UTM = Transformer.from_crs(WGS84, UTM30, always_xy=True)
_TO_WGS = Transformer.from_crs(UTM30, WGS84, always_xy=True)

FloatArray = npt.NDArray[np.float64]


def to_utm(lon: npt.ArrayLike, lat: npt.ArrayLike) -> tuple[FloatArray, FloatArray]:
    """Project WGS84 lon/lat to EPSG:25830 x/y (metres)."""
    x, y = _TO_UTM.transform(np.asarray(lon, dtype=np.float64), np.asarray(lat, dtype=np.float64))
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)


def to_wgs(x: npt.ArrayLike, y: npt.ArrayLike) -> tuple[FloatArray, FloatArray]:
    """Unproject EPSG:25830 x/y to WGS84 lon/lat."""
    lon, lat = _TO_WGS.transform(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))
    return np.asarray(lon, dtype=np.float64), np.asarray(lat, dtype=np.float64)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Hex sha256 of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()
