"""GTFS feed loading with schema validation and an on-disk parsed cache.

The loader reads the zip with pyarrow's CSV reader (all columns as strings, then
typed explicitly), validates the schema and referential integrity, and stores a
compact parsed copy as parquet under ``data/cache/gtfs/<zip sha256>/``. Warm loads read
only that cache.

In the parsed :class:`Feed`, ``stop_times`` is stored with dense integer keys
(``trip_idx`` into ``feed.trips`` and ``stop_idx`` into ``feed.stops``) and times in
seconds since service-day midnight, which keeps it small (~25 MB for 1.27M rows) and
fast to group.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from vlab.gtfs._cache import default_cache_dir, file_sha256

#: Bump when the parsed representation changes, to invalidate old caches.
CACHE_VERSION: Final = 3

REQUIRED_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "agency.txt": ("agency_name", "agency_timezone"),
    "routes.txt": ("route_id", "route_short_name", "route_type"),
    "stops.txt": ("stop_id", "stop_name", "stop_lat", "stop_lon"),
    "trips.txt": ("route_id", "service_id", "trip_id"),
    "stop_times.txt": ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"),
}
OPTIONAL_FILES: Final = ("calendar.txt", "calendar_dates.txt", "shapes.txt")
_TABLES: Final = (
    "agency",
    "routes",
    "stops",
    "trips",
    "stop_times",
    "calendar",
    "calendar_dates",
    "shapes",
)


class FeedValidationError(ValueError):
    """Raised when a GTFS feed violates the schema or referential integrity."""


@dataclass(frozen=True)
class Feed:
    """Validated GTFS tables.

    Columns (all ids are strings):

    - ``agency``: ``agency_name``, ``agency_timezone`` (+ optional columns).
    - ``routes``: ``route_id``, ``route_short_name``, ``route_long_name``, ``route_type``
      (int), ``route_color``, ``route_text_color`` (hex without ``#``, defaults filled).
    - ``stops``: ``stop_id``, ``stop_name``, ``stop_lat``, ``stop_lon`` (float64).
    - ``trips``: ``trip_id``, ``route_id``, ``service_id``, ``trip_headsign``,
      ``shape_id`` (``""`` if missing), ``direction_id`` (int8, 0 when missing).
    - ``stop_times``: ``trip_idx``, ``stop_idx``, ``stop_sequence``, ``arrival``,
      ``departure`` (int32; times in seconds, may exceed 86400), sorted by
      ``(trip_idx, stop_sequence)``.
    - ``calendar``: ``service_id``, ``monday``..``sunday`` (bool), ``start_date``,
      ``end_date`` (int ``YYYYMMDD``); may be empty.
    - ``calendar_dates``: ``service_id``, ``date`` (int ``YYYYMMDD``), ``exception_type``.
    - ``shapes``: ``shape_id``, ``shape_pt_lat``, ``shape_pt_lon``, ``shape_pt_sequence``,
      sorted by shape and sequence; may be empty.
    """

    agency: pd.DataFrame
    routes: pd.DataFrame
    stops: pd.DataFrame
    trips: pd.DataFrame
    stop_times: pd.DataFrame
    calendar: pd.DataFrame
    calendar_dates: pd.DataFrame
    shapes: pd.DataFrame
    source_sha256: str = ""

    def trip_ptr(self) -> npt.NDArray[np.int64]:
        """CSR pointer: rows of trip ``i`` are ``stop_times[ptr[i]:ptr[i+1]]``."""
        counts = np.bincount(
            self.stop_times["trip_idx"].to_numpy(), minlength=len(self.trips)
        ).astype(np.int64)
        ptr = np.zeros(len(self.trips) + 1, dtype=np.int64)
        np.cumsum(counts, out=ptr[1:])
        return ptr


# --------------------------------------------------------------------------- reading


def _read_csv(zf: zipfile.ZipFile, name: str) -> pa.Table:
    raw = zf.read(name)
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if not raw.strip():
        return pa.table({})
    header = raw.split(b"\n", 1)[0].decode("utf-8").strip().split(",")
    names = [h.strip().strip('"') for h in header]
    return pacsv.read_csv(
        io.BytesIO(raw),
        read_options=pacsv.ReadOptions(column_names=names, skip_rows=1),
        convert_options=pacsv.ConvertOptions(
            column_types=dict.fromkeys(names, pa.string()),
            strings_can_be_null=False,
        ),
    )


def _require(table: pa.Table, name: str, columns: tuple[str, ...]) -> None:
    missing = [c for c in columns if c not in table.column_names]
    if missing:
        raise FeedValidationError(
            f"{name}: missing required column(s) {missing}; found {table.column_names}"
        )


def _col(table: pa.Table, name: str, default: str = "") -> npt.NDArray[np.object_]:
    if name in table.column_names:
        return np.asarray(table.column(name).to_pylist(), dtype=object)
    return np.full(table.num_rows, default, dtype=object)


def _str_series(values: npt.NDArray[np.object_]) -> pd.Series:
    return pd.Series([str(v).strip() for v in values], dtype=object)


def parse_gtfs_time(values: pa.ChunkedArray | pa.Array) -> npt.NDArray[np.int32]:
    """Parse ``H:MM:SS`` strings (hours may exceed 23) to seconds. Empty → -1."""
    arr = pc.utf8_trim_whitespace(values)
    empty = pc.equal(pc.utf8_length(arr), 0).to_numpy(zero_copy_only=False)
    filled = pc.if_else(pc.equal(pc.utf8_length(arr), 0), "0:0:0", arr)
    parts = pc.split_pattern(filled, ":")
    lengths = pc.list_value_length(parts).to_numpy(zero_copy_only=False)
    if np.any(lengths != 3):
        bad = np.flatnonzero(lengths != 3)[:5]
        raise FeedValidationError(
            f"stop_times.txt: malformed time value(s) at rows {bad.tolist()}: "
            f"{[values[int(i)].as_py() for i in bad]}"
        )
    try:
        flat = pc.cast(pc.list_flatten(parts), pa.int32()).to_numpy(zero_copy_only=False)
    except pa.ArrowInvalid as exc:
        raise FeedValidationError(f"stop_times.txt: non-numeric time component ({exc})") from exc
    hms = flat.reshape(-1, 3).astype(np.int64)
    if np.any(hms[:, 1] >= 60) or np.any(hms[:, 2] >= 60) or np.any(hms < 0):
        raise FeedValidationError("stop_times.txt: minutes/seconds out of range in a time value")
    secs = hms[:, 0] * 3600 + hms[:, 1] * 60 + hms[:, 2]
    secs[empty] = -1
    return secs.astype(np.int32)


def _to_int(values: npt.NDArray[np.object_], what: str, default: int | None = None) -> np.ndarray:
    out = np.empty(len(values), dtype=np.int64)
    for i, v in enumerate(values):
        s = str(v).strip()
        if s == "":
            if default is None:
                raise FeedValidationError(f"{what}: empty value at row {i}")
            out[i] = default
            continue
        try:
            out[i] = int(s)
        except ValueError as exc:
            raise FeedValidationError(f"{what}: invalid integer {s!r} at row {i}") from exc
    return out


def _to_float(values: npt.NDArray[np.object_], what: str) -> npt.NDArray[np.float64]:
    try:
        return np.array([float(str(v).strip()) for v in values], dtype=np.float64)
    except ValueError as exc:
        raise FeedValidationError(f"{what}: invalid number ({exc})") from exc


def _check_refs(child: pd.Series, parent: pd.Series, what: str) -> None:
    missing = ~child.isin(set(parent))
    if missing.any():
        examples = sorted(set(child[missing]))[:5]
        raise FeedValidationError(f"{what}: {int(missing.sum())} unknown reference(s), e.g. {examples}")


def _check_unique(series: pd.Series, what: str) -> None:
    dup = series.duplicated()
    if dup.any():
        raise FeedValidationError(f"{what}: duplicated id(s) {sorted(set(series[dup]))[:5]}")


def _parse_zip(path: Path) -> dict[str, pd.DataFrame]:
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        for req in REQUIRED_COLUMNS:
            if req not in names:
                raise FeedValidationError(f"{path.name}: missing required file {req}")
        raw = {n: _read_csv(zf, n) for n in (*REQUIRED_COLUMNS, *OPTIONAL_FILES) if n in names}
    for n, cols in REQUIRED_COLUMNS.items():
        _require(raw[n], n, cols)
    if "calendar.txt" not in raw and "calendar_dates.txt" not in raw:
        raise FeedValidationError("feed needs calendar.txt and/or calendar_dates.txt")

    a = raw["agency.txt"]
    agency = pd.DataFrame({c: _str_series(_col(a, c)) for c in a.column_names})

    r = raw["routes.txt"]
    routes = pd.DataFrame(
        {
            "route_id": _str_series(_col(r, "route_id")),
            "route_short_name": _str_series(_col(r, "route_short_name")),
            "route_long_name": _str_series(_col(r, "route_long_name")),
            "route_type": _to_int(_col(r, "route_type"), "routes.route_type", 3),
            "route_color": _str_series(_col(r, "route_color", "")),
            "route_text_color": _str_series(_col(r, "route_text_color", "")),
        }
    )
    routes.loc[routes["route_color"] == "", "route_color"] = "808080"
    routes.loc[routes["route_text_color"] == "", "route_text_color"] = "FFFFFF"
    routes["route_color"] = routes["route_color"].str.upper()
    routes["route_text_color"] = routes["route_text_color"].str.upper()
    _check_unique(routes["route_id"], "routes.txt route_id")

    s = raw["stops.txt"]
    stops = pd.DataFrame(
        {
            "stop_id": _str_series(_col(s, "stop_id")),
            "stop_name": _str_series(_col(s, "stop_name")),
            "stop_lat": _to_float(_col(s, "stop_lat"), "stops.stop_lat"),
            "stop_lon": _to_float(_col(s, "stop_lon"), "stops.stop_lon"),
        }
    )
    _check_unique(stops["stop_id"], "stops.txt stop_id")
    bad = (
        (stops["stop_lat"].abs() > 90)
        | (stops["stop_lon"].abs() > 180)
        | ((stops["stop_lat"] == 0) & (stops["stop_lon"] == 0))
        | stops["stop_lat"].isna()
        | stops["stop_lon"].isna()
    )
    if bad.any():
        raise FeedValidationError(
            f"stops.txt: {int(bad.sum())} stop(s) with invalid coordinates, "
            f"e.g. {stops.loc[bad, 'stop_id'].head(5).tolist()}"
        )

    t = raw["trips.txt"]
    trips = pd.DataFrame(
        {
            "trip_id": _str_series(_col(t, "trip_id")),
            "route_id": _str_series(_col(t, "route_id")),
            "service_id": _str_series(_col(t, "service_id")),
            "trip_headsign": _str_series(_col(t, "trip_headsign")),
            "shape_id": _str_series(_col(t, "shape_id")),
            "direction_id": _to_int(_col(t, "direction_id"), "trips.direction_id", 0).astype(
                np.int8
            ),
        }
    )
    _check_unique(trips["trip_id"], "trips.txt trip_id")
    _check_refs(trips["route_id"], routes["route_id"], "trips.txt route_id → routes")

    cal = raw.get("calendar.txt")
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if cal is not None and cal.num_rows:
        _require(cal, "calendar.txt", ("service_id", *days, "start_date", "end_date"))
        calendar = pd.DataFrame(
            {
                "service_id": _str_series(_col(cal, "service_id")),
                **{d: _to_int(_col(cal, d), f"calendar.{d}").astype(bool) for d in days},
                "start_date": _to_int(_col(cal, "start_date"), "calendar.start_date"),
                "end_date": _to_int(_col(cal, "end_date"), "calendar.end_date"),
            }
        )
    else:
        calendar = pd.DataFrame(
            {
                "service_id": pd.Series([], dtype=object),
                **{d: pd.Series([], dtype=bool) for d in days},
                "start_date": pd.Series([], dtype=np.int64),
                "end_date": pd.Series([], dtype=np.int64),
            }
        )
    cd = raw.get("calendar_dates.txt")
    if cd is not None and cd.num_rows:
        _require(cd, "calendar_dates.txt", ("service_id", "date", "exception_type"))
        calendar_dates = pd.DataFrame(
            {
                "service_id": _str_series(_col(cd, "service_id")),
                "date": _to_int(_col(cd, "date"), "calendar_dates.date"),
                "exception_type": _to_int(
                    _col(cd, "exception_type"), "calendar_dates.exception_type"
                ).astype(np.int8),
            }
        )
        if not calendar_dates["exception_type"].isin([1, 2]).all():
            raise FeedValidationError("calendar_dates.txt: exception_type must be 1 or 2")
    else:
        calendar_dates = pd.DataFrame(
            {
                "service_id": pd.Series([], dtype=object),
                "date": pd.Series([], dtype=np.int64),
                "exception_type": pd.Series([], dtype=np.int8),
            }
        )
    known_services = pd.concat([calendar["service_id"], calendar_dates["service_id"]])
    _check_refs(trips["service_id"], known_services, "trips.txt service_id → calendar(_dates)")

    sh = raw.get("shapes.txt")
    if sh is not None and sh.num_rows:
        _require(sh, "shapes.txt", ("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"))
        shapes = pd.DataFrame(
            {
                "shape_id": _str_series(_col(sh, "shape_id")),
                "shape_pt_lat": _to_float(_col(sh, "shape_pt_lat"), "shapes.shape_pt_lat"),
                "shape_pt_lon": _to_float(_col(sh, "shape_pt_lon"), "shapes.shape_pt_lon"),
                "shape_pt_sequence": _to_int(
                    _col(sh, "shape_pt_sequence"), "shapes.shape_pt_sequence"
                ),
            }
        ).sort_values(["shape_id", "shape_pt_sequence"], kind="stable", ignore_index=True)
        if (shapes["shape_pt_lat"].abs() > 90).any() or (shapes["shape_pt_lon"].abs() > 180).any():
            raise FeedValidationError("shapes.txt: coordinates out of range")
    else:
        shapes = pd.DataFrame(
            {
                "shape_id": pd.Series([], dtype=object),
                "shape_pt_lat": pd.Series([], dtype=np.float64),
                "shape_pt_lon": pd.Series([], dtype=np.float64),
                "shape_pt_sequence": pd.Series([], dtype=np.int64),
            }
        )
    with_shape = trips["shape_id"] != ""
    _check_refs(
        trips.loc[with_shape, "shape_id"], shapes["shape_id"], "trips.txt shape_id → shapes"
    )

    stop_times = _parse_stop_times(raw["stop_times.txt"], trips, stops)
    return {
        "agency": agency,
        "routes": routes,
        "stops": stops,
        "trips": trips,
        "stop_times": stop_times,
        "calendar": calendar,
        "calendar_dates": calendar_dates,
        "shapes": shapes,
    }


def _encode(values: pa.ChunkedArray, ids: pd.Series, what: str) -> npt.NDArray[np.int32]:
    ids_arr = pa.array(ids.tolist(), type=pa.string())
    codes = pc.index_in(pc.utf8_trim_whitespace(values), value_set=ids_arr)
    if codes.null_count:
        mask = pc.is_null(codes).to_numpy(zero_copy_only=False)
        bad = sorted(set(pc.filter(values, pa.array(mask)).to_pylist()))[:5]
        raise FeedValidationError(f"{what}: {int(mask.sum())} unknown reference(s), e.g. {bad}")
    return codes.to_numpy(zero_copy_only=False).astype(np.int32)


def _parse_stop_times(st: pa.Table, trips: pd.DataFrame, stops: pd.DataFrame) -> pd.DataFrame:
    trip_idx = _encode(st.column("trip_id"), trips["trip_id"], "stop_times.txt trip_id → trips")
    stop_idx = _encode(st.column("stop_id"), stops["stop_id"], "stop_times.txt stop_id → stops")
    try:
        seq = pc.cast(pc.utf8_trim_whitespace(st.column("stop_sequence")), pa.int32()).to_numpy()
    except pa.ArrowInvalid as exc:
        raise FeedValidationError(f"stop_times.txt: invalid stop_sequence ({exc})") from exc
    arr = parse_gtfs_time(st.column("arrival_time"))
    dep = parse_gtfs_time(st.column("departure_time"))
    order = np.lexsort((seq, trip_idx))
    trip_idx, stop_idx, seq, arr, dep = (x[order] for x in (trip_idx, stop_idx, seq, arr, dep))

    same_trip = trip_idx[1:] == trip_idx[:-1]
    if np.any(same_trip & (seq[1:] == seq[:-1])):
        raise FeedValidationError("stop_times.txt: duplicated stop_sequence within a trip")
    # A missing arrival takes the departure and vice versa; fully missing times at
    # intermediate stops are interpolated linearly by stop position (no distances).
    arr = np.where(arr < 0, dep, arr)
    dep = np.where(dep < 0, arr, dep)
    if np.any(arr < 0):
        arr, dep = _interpolate_missing(trip_idx, arr, dep)
    if np.any(dep < arr):
        bad = np.flatnonzero(dep < arr)[:5]
        raise FeedValidationError(
            f"stop_times.txt: departure before arrival for trip(s) "
            f"{trips['trip_id'].iloc[trip_idx[bad]].tolist()}"
        )
    back = same_trip & (arr[1:] < dep[:-1])
    if np.any(back):
        bad = np.flatnonzero(back)[:5]
        raise FeedValidationError(
            "stop_times.txt: times decrease along trip(s) "
            f"{sorted(set(trips['trip_id'].iloc[trip_idx[bad]]))}"
        )
    counts = np.bincount(trip_idx, minlength=len(trips))
    if np.any(counts == 1):
        raise FeedValidationError(
            f"stop_times.txt: trip(s) with a single stop: "
            f"{trips['trip_id'][counts == 1].head(5).tolist()}"
        )
    return pd.DataFrame(
        {
            "trip_idx": trip_idx.astype(np.int32),
            "stop_idx": stop_idx.astype(np.int32),
            "stop_sequence": seq.astype(np.int32),
            "arrival": arr.astype(np.int32),
            "departure": dep.astype(np.int32),
        }
    )


def _interpolate_missing(
    trip_idx: npt.NDArray[np.int32], arr: npt.NDArray[np.int32], dep: npt.NDArray[np.int32]
) -> tuple[npt.NDArray[np.int32], npt.NDArray[np.int32]]:
    arr = arr.copy()
    starts = np.flatnonzero(np.r_[True, trip_idx[1:] != trip_idx[:-1]])
    ends = np.r_[starts[1:], len(trip_idx)]
    for a, b in zip(starts, ends, strict=True):
        seg = arr[a:b]
        known = seg >= 0
        if known.all():
            continue
        if not known[0] or not known[-1]:
            raise FeedValidationError("stop_times.txt: first/last stop of a trip has no time")
        x = np.arange(b - a)
        seg[~known] = np.round(np.interp(x[~known], x[known], seg[known])).astype(np.int32)
    return arr, arr.copy()


# --------------------------------------------------------------------------- caching


def _cache_path(cache_dir: Path, sha: str) -> Path:
    return cache_dir / "gtfs" / f"{sha[:24]}-v{CACHE_VERSION}"


def _write_cache(folder: Path, tables: dict[str, pd.DataFrame], sha: str) -> None:
    tmp = folder.with_name(folder.name + ".tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), tmp / f"{name}.parquet")
    (tmp / "meta.json").write_text(json.dumps({"sha256": sha, "version": CACHE_VERSION}))
    if folder.exists():  # concurrent writer won the race; keep theirs
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()
        return
    tmp.rename(folder)


def _read_cache(folder: Path) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for name in _TABLES:
        df = pq.read_table(folder / f"{name}.parquet").to_pandas()
        for col in df.columns:  # keep ids as plain python strings (object dtype)
            if df[col].dtype != object and pd.api.types.is_string_dtype(df[col].dtype):
                df[col] = df[col].astype(object)
        out[name] = df
    return out


def load_feed(path: str | Path, *, cache_dir: Path | None = None, use_cache: bool = True) -> Feed:
    """Load and validate a GTFS zip.

    Args:
        path: GTFS zip file.
        cache_dir: cache root (default :func:`default_cache_dir`). The parsed copy is
            keyed by the zip's SHA-256, so a new feed never reuses a stale cache.
        use_cache: read/write the parsed cache. ``False`` always parses the zip.

    Raises:
        FeedValidationError: missing files/columns, broken references, decreasing
            times within a trip, invalid coordinates, ...
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    sha = file_sha256(path)
    folder = _cache_path(cache_dir or default_cache_dir(), sha)
    tables: dict[str, pd.DataFrame] | None = None
    if use_cache and (folder / "meta.json").is_file():
        try:
            tables = _read_cache(folder)
        except (OSError, pa.ArrowException, KeyError):
            tables = None
    if tables is None:
        tables = _parse_zip(path)
        if use_cache:
            try:
                _write_cache(folder, tables, sha)
            except OSError:
                pass  # read-only filesystem: caching is an optimisation only
    return Feed(**tables, source_sha256=sha)
