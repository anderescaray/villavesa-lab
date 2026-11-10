"""Processed data bundle: paths and validated loaders.

>>> from vlab.data import load_zones, load_pois
>>> zones = load_zones()  # doctest: +SKIP

The bundle is built by ``scripts/build_data.py`` (``make data``) with the
pipeline steps in :mod:`vlab.data.pipeline`; see ``docs/data.md``.
"""

from vlab.data.loaders import (
    POI_CATEGORIES,
    DataSchemaError,
    DriveGraphData,
    WalkGraphData,
    load_drive_graph_arrays,
    load_manifest,
    load_pois,
    load_sections,
    load_study_area,
    load_walk_graph_arrays,
    load_zone_sections,
    load_zones,
)
from vlab.data.paths import data_dir, gtfs_path, processed_dir, raw_dir

__all__ = [
    "POI_CATEGORIES",
    "DataSchemaError",
    "DriveGraphData",
    "WalkGraphData",
    "data_dir",
    "gtfs_path",
    "load_drive_graph_arrays",
    "load_manifest",
    "load_pois",
    "load_sections",
    "load_study_area",
    "load_walk_graph_arrays",
    "load_zone_sections",
    "load_zones",
    "processed_dir",
    "raw_dir",
]
