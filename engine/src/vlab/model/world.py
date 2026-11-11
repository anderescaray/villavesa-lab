"""World model loaded once at start-up.

:class:`Model` holds everything that does not depend on a scenario: the GTFS
feed, the analysis zones and their attributes, destinations, the pedestrian and
bus-drivable graphs and the zone-to-zone direct-walk matrix. A
:class:`NetworkState` is a timetable plus the walking tables that match its
stops; the baseline state of each day type is built lazily and cached, and the
scenario layer derives modified states from it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt
import pandas as pd

from vlab.cost.model import CostParams
from vlab.data import (
    load_drive_graph_arrays,
    load_pois,
    load_sections,
    load_zone_sections,
    load_zones,
)
from vlab.data import paths as data_paths
from vlab.gtfs import Feed, Timetable, build_timetable, load_feed, representative_dates
from vlab.walk import WALK_SPEED_MPS, Snap, WalkGraph, WalkTable, build_access, build_transfers

log = logging.getLogger(__name__)

DayType = Literal["weekday", "saturday", "sunday"]
DAY_TYPES: tuple[DayType, ...] = ("weekday", "saturday", "sunday")

#: Direct walking between zones is considered up to this many seconds.
MAX_DIRECT_WALK_S = 3600
ACCESS_MAX_M = 1000.0
TRANSFER_MAX_M = 400.0
#: Categories every resident should reach within the threshold.
ESSENTIAL_CATEGORIES: tuple[str, ...] = ("hospital", "health_centre", "city_centre")
UNREACHABLE = np.uint16(65535)


@dataclass(frozen=True)
class Window:
    """Analysis window: a day type and a departure interval (seconds)."""

    day: DayType = "weekday"
    start: int = 8 * 3600
    duration: int = 3600

    def __post_init__(self) -> None:
        if self.day not in DAY_TYPES:
            raise ValueError(f"unknown day type {self.day!r}")
        if not 0 <= self.start < 30 * 3600:
            raise ValueError("window start must be within the service day (0-30 h)")
        if not 600 <= self.duration <= 4 * 3600:
            raise ValueError("window duration must be between 10 minutes and 4 hours")

    def departures(self, step: int = 600) -> npt.NDArray[np.int64]:
        return np.arange(self.start, self.start + self.duration, step, dtype=np.int64)

    def key(self) -> tuple[str, int, int]:
        return (self.day, self.start, self.duration)


@dataclass(frozen=True, eq=False)
class NetworkState:
    """A timetable with walking tables consistent with its stops."""

    timetable: Timetable
    transfers: WalkTable
    access: WalkTable  # zones -> stops
    egress: WalkTable  # stops -> zones


@dataclass(eq=False)
class Model:
    """Scenario-independent state. Build with :meth:`Model.load`."""

    feed: Feed
    dates: dict[str, dt.date]
    zones: pd.DataFrame
    pois: pd.DataFrame
    sections: pd.DataFrame
    walk: WalkGraph
    drive: WalkGraph
    drive_speed_kmh: npt.NDArray[np.float32]
    zone_lon: npt.NDArray[np.float64]
    zone_lat: npt.NDArray[np.float64]
    population: npt.NDArray[np.float64]
    attraction: npt.NDArray[np.float64]
    income: npt.NDArray[np.float64]
    poi_zone: npt.NDArray[np.int64]
    direct_walk: npt.NDArray[np.uint16]
    cache_dir: Path
    cost_params: CostParams = field(default_factory=CostParams)
    _baseline: dict[str, NetworkState] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, data_dir: Path | None = None, cache_dir: Path | None = None) -> Model:
        t0 = time.perf_counter()
        base = Path(data_dir) if data_dir is not None else data_paths.data_dir()
        processed = base / "processed"
        cache = Path(cache_dir) if cache_dir is not None else base / "cache"
        cache.mkdir(parents=True, exist_ok=True)

        feed = load_feed(base / "raw" / "gtfs_tuc_pamplona.zip", cache_dir=cache / "gtfs")
        dates = representative_dates(feed)
        zones = pd.DataFrame(load_zones(base))
        pois = load_pois(base)
        sections = pd.DataFrame(load_sections(base))
        zone_sections = load_zone_sections(base)
        walk = WalkGraph.load(processed / data_paths.WALK_GRAPH_FILE)
        dg = load_drive_graph_arrays(base)
        drive = WalkGraph.from_arrays(dg.node_lon, dg.node_lat, dg.indptr, dg.indices, dg.length_m)

        zone_lon = zones["lon"].to_numpy(np.float64)
        zone_lat = zones["lat"].to_numpy(np.float64)
        population = zones["population"].to_numpy(np.float64)
        activity = zones["activity_weight"].to_numpy(np.float64)
        attraction = activity / activity.sum() if activity.sum() > 0 else activity
        income = _zone_income(len(zones), zone_sections, sections)
        poi_zone = _nearest_zone(zones, pois)
        direct = _direct_walk(walk, zone_lon, zone_lat, cache)
        model = cls(
            feed=feed,
            dates=dates,
            zones=zones,
            pois=pois,
            sections=sections,
            walk=walk,
            drive=drive,
            drive_speed_kmh=np.asarray(dg.speed_kmh, dtype=np.float32),
            zone_lon=zone_lon,
            zone_lat=zone_lat,
            population=population,
            attraction=attraction,
            income=income,
            poi_zone=poi_zone,
            direct_walk=direct,
            cache_dir=cache,
        )
        log.info("model loaded in %.2f s", time.perf_counter() - t0)
        return model

    # ------------------------------------------------------------------ helpers
    @property
    def n_zones(self) -> int:
        return len(self.zone_lon)

    @cached_property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted(self.pois["category"].unique()))

    @cached_property
    def category_zones(self) -> dict[str, npt.NDArray[np.int64]]:
        cat = self.pois["category"].to_numpy()
        return {c: np.unique(self.poi_zone[cat == c]) for c in self.categories}

    @cached_property
    def category_counts(self) -> dict[str, int]:
        return {str(k): int(v) for k, v in self.pois["category"].value_counts().items()}

    @cached_property
    def zone_snap(self) -> Snap:
        return self.walk.snap(self.zone_lon, self.zone_lat)

    @cached_property
    def poi_snap(self) -> Snap:
        return self.walk.snap(self.pois["lon"].to_numpy(), self.pois["lat"].to_numpy())

    @cached_property
    def bbox(self) -> tuple[float, float, float, float]:
        return (
            float(self.walk.node_lon.min()),
            float(self.walk.node_lat.min()),
            float(self.walk.node_lon.max()),
            float(self.walk.node_lat.max()),
        )

    def baseline(self, day: str) -> NetworkState:
        """Baseline network of a day type (built once, then cached)."""
        with self._lock:
            state = self._baseline.get(day)
            if state is None:
                if day not in self.dates:
                    raise ValueError(f"unknown day type {day!r}")
                tt = build_timetable(self.feed, self.dates[day])
                state = self.state_for(tt, cache=True)
                self._baseline[day] = state
            return state

    def state_for(self, tt: Timetable, *, cache: bool = False) -> NetworkState:
        """Walking tables for a timetable's stops. Cheap (~0.1 s); scenario stop
        edits simply rebuild them."""
        transfers = build_transfers(
            self.walk, tt, TRANSFER_MAX_M, cache=cache, cache_dir=self.cache_dir / "walk"
        )
        access = build_access(
            self.walk,
            (self.zone_lon, self.zone_lat),
            tt,
            ACCESS_MAX_M,
            cache=cache,
            cache_dir=self.cache_dir / "walk",
        )
        return NetworkState(tt, transfers, access, access.transpose())


def _zone_income(
    n_zones: int, zone_sections: pd.DataFrame, sections: pd.DataFrame
) -> npt.NDArray[np.float64]:
    """Resident-weighted mean income per person of each zone (NaN without residents)."""
    inc = sections.set_index("section_id")["income_per_capita"]
    zs = zone_sections.copy()
    zs["income"] = zs["section_id"].map(inc)
    zs = zs[zs["income"].notna() & (zs["population"] > 0)]
    num = np.bincount(zs["zone_id"], weights=zs["income"] * zs["population"], minlength=n_zones)
    den = np.bincount(zs["zone_id"], weights=zs["population"], minlength=n_zones)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def _nearest_zone(zones: pd.DataFrame, pois: pd.DataFrame) -> npt.NDArray[np.int64]:
    from scipy.spatial import cKDTree

    from vlab.gtfs import to_xy

    px, py = to_xy(pois["lon"].to_numpy(), pois["lat"].to_numpy())
    tree = cKDTree(np.column_stack([zones["x"].to_numpy(), zones["y"].to_numpy()]))
    _, idx = tree.query(np.column_stack([px, py]))
    return np.asarray(idx, dtype=np.int64)


def _direct_walk(
    walk: WalkGraph, lon: npt.NDArray[np.float64], lat: npt.NDArray[np.float64], cache: Path
) -> npt.NDArray[np.uint16]:
    """Zone-to-zone walking times (s) up to MAX_DIRECT_WALK_S; 0 on the diagonal."""
    h = hashlib.sha256()
    h.update(walk.digest.encode())
    h.update(np.ascontiguousarray(lon).tobytes())
    h.update(np.ascontiguousarray(lat).tobytes())
    h.update(f"{MAX_DIRECT_WALK_S}:{WALK_SPEED_MPS}:v1".encode())
    path = cache / "walk" / f"direct_{h.hexdigest()[:16]}.npy"
    if path.exists():
        return np.asarray(np.load(path), dtype=np.uint16)
    snap = walk.snap(lon, lat)
    ptr, tgt, dist = walk.distances(snap, snap, MAX_DIRECT_WALK_S * WALK_SPEED_MPS)
    n = len(lon)
    out = np.full((n, n), UNREACHABLE, dtype=np.uint16)
    rows = np.repeat(np.arange(n), np.diff(ptr))
    secs = np.minimum(np.ceil(dist / WALK_SPEED_MPS), 65534).astype(np.uint16)
    out[rows, tgt] = secs
    np.fill_diagonal(out, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, out)
    return out
