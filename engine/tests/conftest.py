"""Shared fixtures: the real TUC Pamplona feed, its weekday timetable, transfer tables
and the walking graph when available."""

from __future__ import annotations

from pathlib import Path

import pytest

from vlab.gtfs import Feed, Timetable, build_timetable, load_feed, representative_dates
from vlab.walk import WalkGraph, WalkTable, build_transfers, euclidean_table

REPO = Path(__file__).resolve().parents[2]
GTFS_ZIP = REPO / "data" / "raw" / "gtfs_tuc_pamplona.zip"
WALK_NPZ = REPO / "data" / "processed" / "walk_graph.npz"

requires_gtfs = pytest.mark.skipif(not GTFS_ZIP.is_file(), reason="GTFS zip not present")
requires_walk_graph = pytest.mark.skipif(
    not WALK_NPZ.is_file(), reason="data/processed/walk_graph.npz not built yet"
)


MINI_GTFS: dict[str, str] = {
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n1,Mini,http://x,Europe/Madrid\n",
    "routes.txt": (
        "route_id,agency_id,route_short_name,route_long_name,route_type,route_color\n"
        "A,1,L01,Line A,3,E3051B\nN,1,N01,Night,3,\n"
    ),
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "s1,One,42.80,-1.65\ns2,Two,42.81,-1.64\ns3,Three,42.82,-1.63\n"
    ),
    "calendar_dates.txt": (
        "service_id,date,exception_type\nWD,20261111,1\nWD2,20261112,1\nSA,20261114,1\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id,trip_headsign,shape_id,direction_id\n"
        "A,WD,t1,Three,sh1,0\nA,WD,t2,Three,sh1,0\nA,WD2,t3,Three,sh1,0\nN,WD,n1,One,,1\n"
        "A,SA,t4,Three,sh1,0\n"
    ),
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "t1,08:00:00,08:00:00,s1,1\nt1,08:05:00,08:06:00,s2,2\nt1,08:10:00,08:10:00,s3,3\n"
        "t2,08:30:00,08:30:00,s1,1\nt2,08:35:00,08:35:00,s2,2\nt2,08:40:00,08:40:00,s3,3\n"
        "t3,09:00:00,09:00:00,s1,1\nt3,09:05:00,09:05:00,s2,2\nt3,09:10:00,09:10:00,s3,3\n"
        "t4,10:00:00,10:00:00,s1,1\nt4,10:05:00,10:05:00,s2,2\nt4,10:10:00,10:10:00,s3,3\n"
        "n1,23:50:00,23:50:00,s3,0\nn1,24:10:00,24:10:00,s1,1\n"
    ),
    "shapes.txt": (
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
        "sh1,42.80,-1.65,1\nsh1,42.81,-1.64,2\nsh1,42.82,-1.63,3\n"
    ),
}


@pytest.fixture
def make_gtfs_zip(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Factory writing a small GTFS zip (UTF-8 BOM, like the real feed).

    ``make_gtfs_zip(**{"trips.txt": "...", "shapes.txt": None})`` overrides or drops
    files.
    """
    import zipfile

    counter = {"n": 0}

    def make(**overrides: str | None) -> Path:
        files = dict(MINI_GTFS)
        for name, content in overrides.items():
            key = name if name.endswith(".txt") else f"{name}.txt"
            if content is None:
                files.pop(key, None)
            else:
                files[key] = content
        counter["n"] += 1
        path = tmp_path / f"gtfs{counter['n']}.zip"
        with zipfile.ZipFile(path, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, b"\xef\xbb\xbf" + content.encode("utf-8"))
        return path

    return make


@pytest.fixture
def mini_gtfs() -> dict[str, str]:
    """Contents of the files of the mini GTFS feed (see ``make_gtfs_zip``)."""
    return dict(MINI_GTFS)


@pytest.fixture(scope="session")
def gtfs_zip() -> Path:
    if not GTFS_ZIP.is_file():
        pytest.skip("GTFS zip not present")
    return GTFS_ZIP


@pytest.fixture(scope="session")
def feed() -> Feed:
    if not GTFS_ZIP.is_file():
        pytest.skip("GTFS zip not present")
    return load_feed(GTFS_ZIP)


@pytest.fixture(scope="session")
def rep_dates(feed: Feed) -> dict[str, object]:
    return dict(representative_dates(feed))


@pytest.fixture(scope="session")
def tt_weekday(feed: Feed) -> Timetable:
    return build_timetable(feed, representative_dates(feed)["weekday"])


@pytest.fixture(scope="session")
def walk_graph() -> WalkGraph:
    if not WALK_NPZ.is_file():
        pytest.skip("walk graph not built yet")
    return WalkGraph.load(WALK_NPZ)


@pytest.fixture(scope="session")
def transfers_weekday(tt_weekday: Timetable) -> WalkTable:
    """Network footpaths if the walk graph exists, else straight line x 1.3 (400 m)."""
    if WALK_NPZ.is_file():
        return build_transfers(WalkGraph.load(WALK_NPZ), tt_weekday, 400.0)
    coords = (tt_weekday.stop_lon, tt_weekday.stop_lat)
    return euclidean_table(coords, coords, 400.0, exclude_self=True)
