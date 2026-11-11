"""Service-day helpers: active services per date, day-type classification."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Literal

import numpy as np
import numpy.typing as npt

from vlab.gtfs.feed import Feed

DayType = Literal["weekday", "saturday", "sunday", "holiday"]
_WEEKDAY_COLS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def to_date(value: dt.date | str | int) -> dt.date:
    """Accept a ``date``, ``"YYYY-MM-DD"``, ``"YYYYMMDD"`` or ``YYYYMMDD`` int."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = str(value).replace("-", "")
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _ymd(d: dt.date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def active_services(feed: Feed, date: dt.date | str | int) -> set[str]:
    """Service ids running on ``date`` (calendar.txt rules + calendar_dates exceptions)."""
    d = to_date(date)
    ymd = _ymd(d)
    cal = feed.calendar
    active: set[str] = set()
    if len(cal):
        col = _WEEKDAY_COLS[d.weekday()]
        sel = (cal["start_date"] <= ymd) & (cal["end_date"] >= ymd) & cal[col].astype(bool)
        active.update(cal.loc[sel, "service_id"])
    cd = feed.calendar_dates
    rows = cd[cd["date"] == ymd]
    active.update(rows.loc[rows["exception_type"] == 1, "service_id"])
    active.difference_update(rows.loc[rows["exception_type"] == 2, "service_id"])
    return active


def trips_mask(feed: Feed, date: dt.date | str | int) -> npt.NDArray[np.bool_]:
    """Boolean mask over ``feed.trips`` of trips whose service runs on ``date``."""
    return feed.trips["service_id"].isin(active_services(feed, date)).to_numpy()


def service_dates(feed: Feed) -> list[dt.date]:
    """All dates with at least one active service, sorted."""
    candidates: set[int] = set(feed.calendar_dates["date"].tolist())
    starts = feed.calendar["start_date"].tolist()
    ends = feed.calendar["end_date"].tolist()
    for start, stop in zip(starts, ends, strict=True):
        d = to_date(int(start))
        end = to_date(int(stop))
        while d <= end:
            candidates.add(_ymd(d))
            d += dt.timedelta(days=1)
    out = [to_date(c) for c in sorted(candidates)]
    return [d for d in out if active_services(feed, d)]


def trip_counts(feed: Feed) -> dict[dt.date, int]:
    """Number of scheduled trips per service date."""
    per_service = Counter(feed.trips["service_id"].tolist())
    return {d: sum(per_service[s] for s in active_services(feed, d)) for d in service_dates(feed)}


def classify_dates(feed: Feed) -> dict[dt.date, DayType]:
    """Day type of each service date.

    Calendar weekday gives ``weekday``/``saturday``/``sunday``. A Monday-Saturday date is
    re-labelled ``holiday`` when its trip count is closer to the modal Sunday count than
    to the modal count of its own calendar type (a holiday timetable).
    """
    counts = trip_counts(feed)
    base: dict[dt.date, DayType] = {
        d: ("saturday" if d.weekday() == 5 else "sunday" if d.weekday() == 6 else "weekday")
        for d in counts
    }
    modal: dict[str, int] = {}
    for kind in ("weekday", "saturday", "sunday"):
        vals = [counts[d] for d in counts if base[d] == kind]
        if vals:
            modal[kind] = Counter(vals).most_common(1)[0][0]
    out = dict(base)
    if "sunday" in modal:
        for d, kind in base.items():
            if kind in ("weekday", "saturday") and kind in modal:
                n = counts[d]
                if abs(n - modal["sunday"]) < abs(n - modal[kind]):
                    out[d] = "holiday"
    return out


def representative_dates(feed: Feed) -> dict[str, dt.date]:
    """The most typical date of each day type: ``{"weekday", "saturday", "sunday"}``.

    Among dates of a type, pick those whose trip count equals the modal count (ties
    broken by the most frequent count, then the earliest date). Holidays are never
    representative. Raises ``ValueError`` if a day type has no service date.
    """
    counts = trip_counts(feed)
    kinds = classify_dates(feed)
    out: dict[str, dt.date] = {}
    for kind in ("weekday", "saturday", "sunday"):
        dates = sorted(d for d, k in kinds.items() if k == kind)
        if not dates:
            raise ValueError(f"feed has no {kind} service date")
        freq = Counter(counts[d] for d in dates)
        best = max(freq.items(), key=lambda kv: (kv[1], kv[0]))[0]
        out[kind] = next(d for d in dates if counts[d] == best)
    return out
