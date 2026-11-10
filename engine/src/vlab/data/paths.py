"""Resolution of the data directories.

The data root defaults to ``<repo>/data`` and can be overridden with the
``VLAB_DATA_DIR`` environment variable (used by Docker and tests).
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "VLAB_DATA_DIR"

# engine/src/vlab/data/paths.py -> parents[4] is the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[4]


def repo_root() -> Path:
    """Repository root (only meaningful for a source checkout)."""
    return _REPO_ROOT


def data_dir() -> Path:
    """Root of the data tree (``raw/`` and ``processed/`` live below it)."""
    env = os.environ.get(ENV_VAR)
    return Path(env).expanduser().resolve() if env else _REPO_ROOT / "data"


def raw_dir() -> Path:
    """Directory holding downloaded raw inputs (git-ignored except the GTFS zip)."""
    return data_dir() / "raw"


def processed_dir() -> Path:
    """Directory holding the compact committed processed bundle."""
    return data_dir() / "processed"


def gtfs_path() -> Path:
    """Path of the official TUC GTFS feed."""
    return raw_dir() / "gtfs_tuc_pamplona.zip"


ZONES_FILE = "zones.parquet"
ZONE_SECTIONS_FILE = "zone_sections.parquet"
SECTIONS_FILE = "sections.parquet"
POIS_FILE = "pois.parquet"
WALK_GRAPH_FILE = "walk_graph.npz"
STUDY_AREA_FILE = "study_area.geojson"
MANIFEST_FILE = "manifest.json"
DRIVE_GRAPH_FILE = "drive_graph.npz"
