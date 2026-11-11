"""Benchmark of the GTFS / walk / RAPTOR layers on the real Pamplona data.

Usage: ``uv run python engine/benchmarks/bench_raptor.py [--origins 3000]``

Prints a Markdown table (copied into docs/router.md). Timings are medians after JIT
warm-up unless stated otherwise.
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numba
import numpy as np
import pandas as pd

from vlab.gtfs import (
    build_timetable,
    load_feed,
    network_speed_kmh,
    representative_dates,
    vehicles_in_service,
    with_pattern_trips,
)
from vlab.raptor import departure_samples, raptor, travel_time_matrix
from vlab.walk import WalkGraph, build_access, build_transfers, euclidean_table

REPO = Path(__file__).resolve().parents[2]
GTFS = REPO / "data" / "raw" / "gtfs_tuc_pamplona.zip"
WALK = REPO / "data" / "processed" / "walk_graph.npz"
ZONES = REPO / "data" / "processed" / "zones.parquet"


def timeit(fn: Callable[[], Any], repeat: int = 5) -> tuple[float, Any]:
    times = []
    out = None
    for _ in range(repeat):
        t = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t)
    return float(np.median(times)), out


def fmt(sec: float) -> str:
    if sec < 1e-3:
        return f"{sec * 1e6:.0f} us"
    if sec < 1:
        return f"{sec * 1e3:.1f} ms"
    return f"{sec:.2f} s"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origins", type=int, default=3000)
    ap.add_argument("--departures", type=int, default=6)
    args = ap.parse_args()
    rows: list[tuple[str, str]] = []
    print(f"threads: {numba.get_num_threads()} (cpu_count {os.cpu_count()})")

    cold, feed = timeit(lambda: load_feed(GTFS, use_cache=False), repeat=1)
    rows.append(("load_feed, cold (parse zip + validate)", fmt(cold)))
    warm, feed = timeit(lambda: load_feed(GTFS))
    rows.append(("load_feed, warm (parquet cache)", fmt(warm)))
    day = representative_dates(feed)["weekday"]
    build_timetable(feed, day)
    t_build, tt = timeit(lambda: build_timetable(feed, day), repeat=3)
    rows.append((f"build_timetable ({tt.n_patterns} patterns, {tt.n_trips} trips)", fmt(t_build)))
    p = int(np.argmax([tt.n_pattern_trips(i) for i in range(tt.n_patterns)]))
    t_edit, _ = timeit(
        lambda: with_pattern_trips(tt, p, tt.arrivals(p)[::2], tt.departures(p)[::2]), repeat=20
    )
    rows.append(("with_pattern_trips (one pattern edited, full rebuild)", fmt(t_edit)))

    if WALK.is_file():
        graph = WalkGraph.load(WALK)
        build_transfers(graph, tt, cache=False)
        t_tr, transfers = timeit(lambda: build_transfers(graph, tt, cache=False))
        rows.append(
            (f"build_transfers 400 m ({graph.n_nodes} nodes, {transfers.nnz} pairs)", fmt(t_tr))
        )
    else:
        graph = None
        coords = (tt.stop_lon, tt.stop_lat)
        transfers = euclidean_table(coords, coords, 400.0, exclude_self=True)
        rows.append(("transfers: straight-line fallback (no walk graph)", "-"))

    zones = pd.read_parquet(ZONES) if ZONES.is_file() else None
    rng = np.random.default_rng(0)
    if zones is not None and len(zones) >= args.origins:
        zlon, zlat = (
            zones["lon"].to_numpy()[: args.origins],
            zones["lat"].to_numpy()[: args.origins],
        )
    else:
        # real zones (if any) + random points in the stops' bbox to reach --origins
        zlon = rng.uniform(tt.stop_lon.min(), tt.stop_lon.max(), args.origins)
        zlat = rng.uniform(tt.stop_lat.min(), tt.stop_lat.max(), args.origins)
        if zones is not None:
            n = len(zones)
            zlon[:n], zlat[:n] = zones["lon"].to_numpy(), zones["lat"].to_numpy()
    pts = (zlon, zlat)
    if graph is not None:
        t_acc, access = timeit(lambda: build_access(graph, pts, tt, cache=False), repeat=3)
        rows.append((f"build_access {len(zlon)} points x 1 km ({access.nnz} pairs)", fmt(t_acc)))
        build_access(graph, (zlon[:1], zlat[:1]), tt)
        one = [
            timeit(lambda i=i: build_access(graph, (zlon[i : i + 1], zlat[i : i + 1]), tt), 1)[0]
            for i in range(100)
        ]
        rows.append(
            ("build_access, single ad-hoc point (isochrone origin)", fmt(float(np.median(one))))
        )
    else:
        access = euclidean_table(pts, (tt.stop_lon, tt.stop_lat), 1000.0)
    egress = access.transpose()

    raptor(tt, transfers, [0], 8 * 3600)
    q = []
    for _ in range(500):
        s = int(rng.integers(0, tt.n_stops))
        t = time.perf_counter()
        raptor(tt, transfers, [s], 8 * 3600)
        q.append(time.perf_counter() - t)
    rows.append(
        ("raptor one-to-all, 1 source stop, 4 rounds (Python call incl.)", fmt(float(np.median(q))))
    )
    q = []
    for i in range(500):
        s, sec = access.row(i % access.n_rows)
        t = time.perf_counter()
        raptor(tt, transfers, s, 8 * 3600, sec)
        q.append(time.perf_counter() - t)
    rows.append(("raptor one-to-all from a zone's access row", fmt(float(np.median(q)))))

    deps = departure_samples(8 * 3600, 3600, 3600 // args.departures)
    travel_time_matrix(tt, transfers, access, egress, deps[:1])
    t_m, m = timeit(lambda: travel_time_matrix(tt, transfers, access, egress, deps), repeat=3)
    reach = float((m < 65535).mean())
    rows.append(
        (
            f"travel_time_matrix {access.n_rows} x {egress.n_cols} x {len(deps)} departures",
            f"{fmt(t_m)} ({access.n_rows * len(deps) / t_m:,.0f} queries/s; "
            f"{reach:.0%} OD reachable)",
        )
    )

    print("\n| Operation | Time |\n| --- | --- |")
    for name, val in rows:
        print(f"| {name} | {val} |")

    print(
        "\n| Day type | Date | Trips | Patterns | Day-line speed (km/h) "
        "| Max trips in motion 07-09 |"
    )
    print("| --- | --- | --- | --- | --- | --- |")
    for kind, d in representative_dates(feed).items():
        t2 = build_timetable(feed, d)
        v = vehicles_in_service(t2, np.arange(7 * 3600, 9 * 3600 + 1, 60))
        print(
            f"| {kind} | {d} | {int((~t2.trip_prev_day).sum())} | {t2.n_patterns} | "
            f"{network_speed_kmh(t2):.1f} | {int(v.max())} |"
        )


if __name__ == "__main__":
    main()
