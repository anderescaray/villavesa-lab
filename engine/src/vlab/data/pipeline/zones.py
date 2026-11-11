"""200 m analysis grid with dasymetric population.

Each census section's population is distributed to the grid cells it overlaps
in proportion to a weight, with tiered fallbacks:

1. floor area of buildings that are not non-residential (residential + unknown use),
2. floor area of all buildings (sections with only non-residential floor area),
3. area of the section inside each cell (sections with no building at all).

Integer people are allocated with the largest-remainder method, so section
totals are preserved exactly. The allocation runs over the *whole* section;
cells outside the study area are dropped afterwards, and each section records
the population that falls inside the study area.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import numpy.typing as npt
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry

from vlab.data.pipeline.buildings import NON_RESIDENTIAL
from vlab.data.pipeline.common import CELL_SIZE_M, UTM30, log, to_wgs


def largest_remainder(total: int, weights: npt.ArrayLike) -> npt.NDArray[np.int64]:
    """Split integer ``total`` proportionally to ``weights`` preserving the sum exactly.

    Ties are broken by position (deterministic).
    """
    w = np.asarray(weights, dtype=np.float64)
    if total < 0:
        raise ValueError("total must be non-negative")
    if w.size == 0:
        if total:
            raise ValueError("cannot allocate a positive total over no cells")
        return np.zeros(0, dtype=np.int64)
    if np.any(w < 0) or not np.isfinite(w).all():
        raise ValueError("weights must be finite and non-negative")
    s = w.sum()
    if s <= 0:
        w = np.ones_like(w)
        s = w.sum()
    quota = total * w / s
    base = np.floor(quota).astype(np.int64)
    rest = int(total - base.sum())
    if rest:
        frac = quota - base
        order = np.lexsort((np.arange(len(w)), -frac))
        base[order[:rest]] += 1
    return base


def cell_index(
    x: npt.ArrayLike, y: npt.ArrayLike, size: int = CELL_SIZE_M
) -> npt.NDArray[np.int64]:
    """Encode the cell containing (x, y) as ``col * 2**32 + row`` (cells aligned to ``size``)."""
    col = np.floor(np.asarray(x) / size).astype(np.int64)
    row = np.floor(np.asarray(y) / size).astype(np.int64)
    return col * (1 << 32) + row


def cell_xy(code: npt.ArrayLike, size: int = CELL_SIZE_M) -> tuple[np.ndarray, np.ndarray]:
    """Lower-left corner of the cell ``code`` (inverse of :func:`cell_index`)."""
    c = np.asarray(code, dtype=np.int64)
    return (c >> 32) * size, (c & 0xFFFFFFFF) * size


def section_cell_pieces(sections: gpd.GeoDataFrame, size: int = CELL_SIZE_M) -> pd.DataFrame:
    """Every (section, cell) overlap with its area (m²)."""
    rows: list[pd.DataFrame] = []
    for sid, geom in zip(sections["section_id"], sections.geometry, strict=True):
        x0, y0, x1, y1 = geom.bounds
        cols = np.arange(np.floor(x0 / size), np.ceil(x1 / size)).astype(np.int64)
        rws = np.arange(np.floor(y0 / size), np.ceil(y1 / size)).astype(np.int64)
        grid_c, grid_r = np.meshgrid(cols, rws)
        cc, rr = grid_c.ravel(), grid_r.ravel()
        boxes = shapely.box(cc * size, rr * size, (cc + 1) * size, (rr + 1) * size)
        shapely.prepare(geom)
        hit = shapely.intersects(geom, boxes)
        inter = shapely.area(shapely.intersection(boxes[hit], geom))
        ok = inter > 1e-6
        rows.append(
            pd.DataFrame(
                {
                    "section_id": sid,
                    "cell": (cc[hit][ok] * (1 << 32) + rr[hit][ok]),
                    "area_m2": inter[ok],
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


@dataclass(frozen=True)
class ZoneBuild:
    zones: gpd.GeoDataFrame  # EPSG:4326 cells
    zone_sections: pd.DataFrame  # zone_id, section_id, population
    section_population_in_area: pd.Series  # by section_id
    fallback_counts: dict[str, int]


def build_zones(
    sections: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    pois: pd.DataFrame,
    study_area: BaseGeometry,
    size: int = CELL_SIZE_M,
) -> ZoneBuild:
    """Dasymetric grid. ``sections``/``buildings`` in EPSG:25830; ``pois`` has ``x``/``y``."""
    pieces = section_cell_pieces(sections, size)

    # Buildings -> (section, cell) by representative point.
    pts = buildings.geometry.representative_point()
    b = gpd.GeoDataFrame(
        {
            "floor_area_m2": buildings["floor_area_m2"].to_numpy(),
            "nonres": (buildings["use"] == NON_RESIDENTIAL).to_numpy(),
        },
        geometry=pts.values,
        crs=UTM30,
    )
    b = gpd.sjoin(b, sections[["section_id", "geometry"]], predicate="within", how="inner")
    b["cell"] = cell_index(b.geometry.x, b.geometry.y, size)
    b["w_res"] = np.where(b["nonres"], 0.0, b["floor_area_m2"])
    agg = b.groupby(["section_id", "cell"]).agg(
        w_res=("w_res", "sum"), w_all=("floor_area_m2", "sum")
    )
    pieces = pieces.join(agg, on=["section_id", "cell"]).fillna({"w_res": 0.0, "w_all": 0.0})

    pop_by_section = sections.set_index("section_id")["population"].astype(np.int64)
    alloc = np.zeros(len(pieces), dtype=np.int64)
    fallbacks = {"residential_floor_area": 0, "all_floor_area": 0, "uniform_area": 0}
    for sid, idx in pieces.groupby("section_id").indices.items():
        p = pieces.iloc[idx]
        if p["w_res"].sum() > 0:
            w, tier = p["w_res"].to_numpy(), "residential_floor_area"
        elif p["w_all"].sum() > 0:
            w, tier = p["w_all"].to_numpy(), "all_floor_area"
        else:
            w, tier = p["area_m2"].to_numpy(), "uniform_area"
        fallbacks[tier] += 1
        alloc[idx] = largest_remainder(int(pop_by_section[sid]), w)
    pieces["population"] = alloc
    if (
        pieces.groupby("section_id")["population"].sum()
        != pop_by_section.reindex(pieces["section_id"].unique())
    ).any():  # pragma: no cover - guarded by largest_remainder
        raise AssertionError("dasymetric allocation does not preserve section totals")
    log.info("  dasymetric weights used per section: %s", fallbacks)

    # Cells of the study area.
    cx0, cy0 = cell_xy(pieces["cell"].to_numpy(), size)
    boxes = shapely.box(cx0, cy0, cx0 + size, cy0 + size)
    shapely.prepare(study_area)
    pieces["in_area"] = shapely.intersects(study_area, boxes)
    inside = pieces[pieces["in_area"]].copy()
    pop_in_area = (
        inside.groupby("section_id")["population"].sum().reindex(pop_by_section.index).fillna(0)
    ).astype(np.int64)

    # Per-cell attributes.
    cells = inside.groupby("cell").agg(population=("population", "sum"))
    dom = (
        inside.sort_values(
            ["cell", "population", "area_m2", "section_id"], ascending=[True, False, False, True]
        )
        .groupby("cell")
        .first()
    )
    cells["section_id"] = dom["section_id"]
    act = b[b["nonres"]].groupby("cell")["floor_area_m2"].sum()
    cells["activity_weight"] = act.reindex(cells.index).fillna(0.0)
    poi_cells = pd.Series(cell_index(pois["x"].to_numpy(), pois["y"].to_numpy(), size))
    cells["n_pois"] = poi_cells.value_counts().reindex(cells.index).fillna(0).astype(np.int32)
    n_poi_out = int((~poi_cells.isin(cells.index)).sum())
    if n_poi_out:
        log.warning("  %d POIs fall in no study-area cell", n_poi_out)
    keep = (cells["population"] > 0) | (cells["activity_weight"] > 0) | (cells["n_pois"] > 0)
    cells = cells[keep]

    # Deterministic dense ids: south to north, then west to east.
    x0, y0 = cell_xy(cells.index.to_numpy(), size)
    order = np.lexsort((x0, y0))
    cells = cells.iloc[order]
    x0, y0 = x0[order], y0[order]
    cx, cy = x0 + size / 2.0, y0 + size / 2.0
    lon, lat = to_wgs(cx, cy)
    muni = sections.set_index("section_id")["municipality"]
    zones = gpd.GeoDataFrame(
        {
            "zone_id": np.arange(len(cells), dtype=np.int32),
            "x": cx.astype(np.float64),
            "y": cy.astype(np.float64),
            "lon": lon,
            "lat": lat,
            "population": cells["population"].to_numpy().astype(np.int32),
            "activity_weight": cells["activity_weight"].to_numpy().astype(np.float32),
            "n_pois": cells["n_pois"].to_numpy().astype(np.int32),
            "section_id": cells["section_id"].to_numpy(),
            "municipality": muni.reindex(cells["section_id"]).to_numpy(),
        },
        geometry=shapely.box(x0, y0, x0 + size, y0 + size),
        crs=UTM30,
    ).to_crs("EPSG:4326")
    zone_of_cell = pd.Series(zones["zone_id"].to_numpy(), index=cells.index)
    zs = inside[inside["population"] > 0].copy()
    zs["zone_id"] = zone_of_cell.reindex(zs["cell"]).to_numpy()
    if zs["zone_id"].isna().any():  # pragma: no cover - populated cells are always kept
        raise AssertionError("populated piece without a zone")
    zone_sections = (
        zs[["zone_id", "section_id", "population"]]
        .astype({"zone_id": np.int32, "population": np.int32})
        .sort_values(["zone_id", "section_id"])
        .reset_index(drop=True)
    )
    log.info(
        "  zones: %d cells kept (%d populated), population in study area %d",
        len(zones), int((zones.population > 0).sum()), int(zones.population.sum()),
    )  # fmt: skip
    return ZoneBuild(zones, zone_sections, pop_in_area, fallbacks)
