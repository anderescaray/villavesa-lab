"""GTFS loading: parsing, validation errors, caching, service-day helpers."""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pytest

from vlab.gtfs import (
    Feed,
    FeedValidationError,
    active_services,
    classify_dates,
    load_feed,
    representative_dates,
    route_kinds,
    service_dates,
    trip_counts,
)
from vlab.gtfs.feed import parse_gtfs_time


def test_parse_time_beyond_midnight() -> None:
    secs = parse_gtfs_time(pa.array(["00:00:00", "7:05:09", "24:15:00", "27:59:59", ""]))
    assert secs.tolist() == [0, 7 * 3600 + 5 * 60 + 9, 87300, 27 * 3600 + 59 * 60 + 59, -1]


@pytest.mark.parametrize("bad", ["08:00", "08:61:00", "aa:00:00"])
def test_parse_time_rejects_malformed(bad: str) -> None:
    with pytest.raises(FeedValidationError):
        parse_gtfs_time(pa.array([bad]))


def test_mini_feed_parses(make_gtfs_zip: Any, tmp_path: Path) -> None:
    f = load_feed(make_gtfs_zip(), cache_dir=tmp_path / "c")
    assert list(f.routes["route_id"]) == ["A", "N"]
    assert f.routes.loc[1, "route_color"] == "808080"  # default colour filled
    assert f.stops["stop_id"].tolist() == ["s1", "s2", "s3"]  # BOM stripped from header
    st = f.stop_times
    assert st["arrival"].dtype == np.int32
    # sorted by trip then sequence, dense keys
    t1 = st[st["trip_idx"] == 0]
    assert t1["stop_idx"].tolist() == [0, 1, 2]
    assert t1["departure"].tolist() == [28800, 28800 + 360, 29400]
    n1 = st[st["trip_idx"] == f.trips.index[f.trips["trip_id"] == "n1"][0]]
    assert n1["arrival"].tolist() == [85800, 87000]
    ptr = f.trip_ptr()
    assert ptr[-1] == len(st) and np.all(np.diff(ptr) >= 2)


def test_cache_roundtrip(make_gtfs_zip: Any, tmp_path: Path, mini_gtfs: dict[str, str]) -> None:
    path = make_gtfs_zip()
    cold = load_feed(path, cache_dir=tmp_path / "c")
    assert any((tmp_path / "c" / "gtfs").iterdir())
    warm = load_feed(path, cache_dir=tmp_path / "c")
    for name in ("routes", "stops", "trips", "stop_times", "calendar_dates", "shapes"):
        a, b = getattr(cold, name), getattr(warm, name)
        assert a.columns.tolist() == b.columns.tolist(), name
        assert a.equals(b) or a.astype(str).equals(b.astype(str)), name
    # a different zip never reuses the cache
    other = load_feed(
        make_gtfs_zip(**{"stops.txt": mini_gtfs["stops.txt"].replace("One", "Uno")}),
        cache_dir=tmp_path / "c",
    )
    assert other.stops.loc[0, "stop_name"] == "Uno"


def _expect_error(make: Any, tmp_path: Path, match: str, **files: str | None) -> None:
    with pytest.raises(FeedValidationError, match=match):
        load_feed(make(**files), cache_dir=tmp_path / "c", use_cache=False)


def test_missing_file_and_columns(make_gtfs_zip: Any, tmp_path: Path) -> None:
    _expect_error(make_gtfs_zip, tmp_path, "missing required file stops.txt", stops=None)
    _expect_error(
        make_gtfs_zip,
        tmp_path,
        "missing required column",
        stops="stop_id,stop_name,stop_lat\ns1,One,42.8\n",
    )
    _expect_error(make_gtfs_zip, tmp_path, "calendar", calendar_dates=None)


def test_referential_integrity(
    make_gtfs_zip: Any, tmp_path: Path, mini_gtfs: dict[str, str]
) -> None:
    trips = mini_gtfs["trips.txt"]
    _expect_error(make_gtfs_zip, tmp_path, "route_id", trips=trips.replace("A,WD,t1", "Z,WD,t1"))
    _expect_error(make_gtfs_zip, tmp_path, "service_id", trips=trips.replace("A,WD,t1", "A,XX,t1"))
    _expect_error(
        make_gtfs_zip, tmp_path, "shape_id", trips=trips.replace("t1,Three,sh1", "t1,Three,nope")
    )
    st = mini_gtfs["stop_times.txt"]
    _expect_error(
        make_gtfs_zip, tmp_path, "trip_id", stop_times=st + "ghost,08:00:00,08:00:00,s1,1\n"
    )
    _expect_error(
        make_gtfs_zip,
        tmp_path,
        "stop_id",
        stop_times=st.replace("t1,08:05:00,08:06:00,s2", "t1,08:05:00,08:06:00,s9"),
    )
    _expect_error(
        make_gtfs_zip,
        tmp_path,
        "duplicated id",
        stops=mini_gtfs["stops.txt"] + "s1,Dup,42.8,-1.6\n",
    )


def test_times_and_coordinates(
    make_gtfs_zip: Any, tmp_path: Path, mini_gtfs: dict[str, str]
) -> None:
    st = mini_gtfs["stop_times.txt"]
    _expect_error(
        make_gtfs_zip,
        tmp_path,
        "decrease",
        stop_times=st.replace("t1,08:10:00,08:10:00,s3", "t1,07:10:00,07:10:00,s3"),
    )
    _expect_error(
        make_gtfs_zip,
        tmp_path,
        "departure before arrival",
        stop_times=st.replace("t1,08:05:00,08:06:00", "t1,08:05:00,08:04:00"),
    )
    _expect_error(
        make_gtfs_zip,
        tmp_path,
        "coordinates",
        stops=mini_gtfs["stops.txt"].replace("42.81,-1.64", "142.81,-1.64"),
    )
    _expect_error(
        make_gtfs_zip,
        tmp_path,
        "duplicated stop_sequence",
        stop_times=st.replace("t1,08:10:00,08:10:00,s3,3", "t1,08:10:00,08:10:00,s3,2"),
    )


def test_missing_intermediate_times_are_interpolated(
    make_gtfs_zip: Any, tmp_path: Path, mini_gtfs: dict[str, str]
) -> None:
    st = mini_gtfs["stop_times.txt"].replace("t1,08:05:00,08:06:00,s2", "t1,,,s2")
    f = load_feed(make_gtfs_zip(stop_times=st), cache_dir=tmp_path / "c", use_cache=False)
    t1 = f.stop_times[f.stop_times["trip_idx"] == 0]
    assert t1["arrival"].tolist() == [28800, 29100, 29400]


def test_service_days_mini(make_gtfs_zip: Any, tmp_path: Path) -> None:
    f = load_feed(make_gtfs_zip(), cache_dir=tmp_path / "c")
    assert service_dates(f) == [dt.date(2026, 11, 11), dt.date(2026, 11, 12), dt.date(2026, 11, 14)]
    assert active_services(f, "2026-11-11") == {"WD"}
    assert active_services(f, 20261113) == set()
    assert trip_counts(f)[dt.date(2026, 11, 11)] == 3
    kinds = route_kinds(f)
    assert kinds == {"A": "day", "N": "night"}


def test_calendar_txt_supported(make_gtfs_zip: Any, tmp_path: Path) -> None:
    cal = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "WD,1,1,1,1,1,0,0,20261109,20261120\nSA,0,0,0,0,0,1,0,20261109,20261120\n"
        "WD2,0,0,0,0,0,0,0,20261109,20261109\n"
    )
    cd = "service_id,date,exception_type\nWD,20261112,2\n"
    f = load_feed(make_gtfs_zip(calendar=cal, calendar_dates=cd), cache_dir=tmp_path / "c")
    assert active_services(f, "2026-11-11") == {"WD"}
    assert active_services(f, "2026-11-12") == set()  # removed by exception
    assert active_services(f, "2026-11-14") == {"SA"}


def test_holiday_detection(make_gtfs_zip: Any, tmp_path: Path) -> None:
    # Weekday dates with 3 trips, Sundays with 1; a Monday with 1 trip is a holiday.
    trips = ["route_id,service_id,trip_id,trip_headsign,shape_id,direction_id"]
    stop_times = ["trip_id,arrival_time,departure_time,stop_id,stop_sequence"]
    cal = ["service_id,date,exception_type"]
    plan = {
        "20261110": 3,
        "20261111": 3,
        "20261112": 3,
        "20261115": 1,
        "20261116": 1,
        "20261114": 2,
        "20261122": 1,
    }
    for date, n in plan.items():
        cal.append(f"S{date},{date},1")
        for i in range(n):
            tid = f"t{date}_{i}"
            trips.append(f"A,S{date},{tid},x,,0")
            stop_times += [f"{tid},08:0{i}:00,08:0{i}:00,s1,1", f"{tid},08:1{i}:00,08:1{i}:00,s2,2"]
    f = load_feed(
        make_gtfs_zip(
            trips="\n".join(trips) + "\n",
            stop_times="\n".join(stop_times) + "\n",
            calendar_dates="\n".join(cal) + "\n",
        ),
        cache_dir=tmp_path / "c",
    )
    kinds = classify_dates(f)
    assert kinds[dt.date(2026, 11, 16)] == "holiday"
    assert kinds[dt.date(2026, 11, 10)] == "weekday"
    assert kinds[dt.date(2026, 11, 14)] == "saturday"
    rep = representative_dates(f)
    assert rep == {
        "weekday": dt.date(2026, 11, 10),
        "saturday": dt.date(2026, 11, 14),
        "sunday": dt.date(2026, 11, 15),
    }


# ----------------------------------------------------------------------------- real feed


def test_real_feed_shape(feed: Feed) -> None:
    assert len(feed.routes) == 54
    assert len(feed.stops) == 563
    assert len(feed.trips) == 60643
    assert len(feed.stop_times) == 1_275_348
    assert feed.calendar.empty and len(feed.calendar_dates) == 21
    assert feed.stop_times["arrival"].max() > 86400  # times past midnight are kept
    assert feed.stops["stop_lat"].between(42.7, 42.9).all()
    assert feed.stops["stop_lon"].between(-1.8, -1.5).all()


def test_real_feed_warm_load_fast(feed: Feed, gtfs_zip: Path) -> None:
    load_feed(gtfs_zip)  # ensure the cache exists
    t = time.perf_counter()
    load_feed(gtfs_zip)
    assert time.perf_counter() - t < 0.5


def test_real_service_days(feed: Feed) -> None:
    dates = service_dates(feed)
    assert dates[0] == dt.date(2026, 11, 10) and dates[-1] == dt.date(2026, 11, 30)
    assert len(dates) == 21
    kinds = classify_dates(feed)
    assert "holiday" not in kinds.values()
    assert representative_dates(feed) == {
        "weekday": dt.date(2026, 11, 11),
        "saturday": dt.date(2026, 11, 14),
        "sunday": dt.date(2026, 11, 15),
    }
    counts = trip_counts(feed)
    assert counts[dt.date(2026, 11, 11)] == 3084
    assert counts[dt.date(2026, 11, 14)] == 2700
    assert counts[dt.date(2026, 11, 15)] == 1763


def test_real_route_kinds(feed: Feed) -> None:
    kinds = route_kinds(feed)
    names = dict(zip(feed.routes["route_id"], feed.routes["route_short_name"], strict=True))
    for rid, kind in kinds.items():
        n = names[rid]
        if n.startswith("N"):
            assert kind == "night", n
        if n.startswith("R"):
            assert kind == "special", n
    assert kinds["4"] == "day" and kinds["101"] == "night"
    assert sum(k == "day" for k in kinds.values()) >= 24
