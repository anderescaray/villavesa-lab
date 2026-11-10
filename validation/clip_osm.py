"""Clip the Navarra OSM extract to the study area (+ margin) with pyosmium's
extract-by-bbox of a buffered study-area polygon. Output: validation/work/study.osm.pbf."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

REPO = Path(__file__).resolve().parents[1]
MARGIN_M = 2000.0


def main() -> None:
    gj = json.loads((REPO / "data/processed/study_area.geojson").read_text())
    geom = shape(gj["features"][0]["geometry"])
    fwd = Transformer.from_crs(4326, 25830, always_xy=True).transform
    inv = Transformer.from_crs(25830, 4326, always_xy=True).transform
    buf = transform(inv, transform(fwd, geom).buffer(MARGIN_M).simplify(50))
    work = REPO / "validation/work"
    work.mkdir(exist_ok=True)
    poly = work / "clip.geojson"
    poly.write_text(json.dumps({"type": "Feature", "properties": {}, "geometry": mapping(buf)}))
    src = REPO / "data/raw/osm/navarra-latest.osm.pbf"
    out = work / "study.osm.pbf"
    subprocess.run(["osmium", "extract", "-p", str(poly), "-s", "complete_ways", "--overwrite",
                    "-o", str(out), str(src)], check=True)
    print(out, out.stat().st_size)

if __name__ == "__main__":
    sys.exit(main())
