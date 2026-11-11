"""Run OUR router (vlab) on every OD in ods.csv: earliest arrival = min(transit, direct walk).

usage: uv run python validation/run_ours.py OUT.csv [--access-m 1000] [--transfer-m 400]
                                            [--rounds 4] [--slack 60] [--speed 1.25]

Same semantics as ``vlab.raptor.travel_time_matrix`` (door to door: access table origin ->
stops, RAPTOR, egress stops -> destination, min with the direct walk), but one OD at a
time so that journeys can be reconstructed.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import math
from pathlib import Path

import numpy as np

from vlab.gtfs import build_timetable, load_feed
from vlab.raptor import INF, raptor_from_access, reconstruct_journey
from vlab.walk import WalkGraph, build_access, build_transfers

REPO = Path(__file__).resolve().parents[1]
BIG = np.iinfo(np.int64).max


def run(
    rows: list[dict[str, str]],
    *,
    access_m: float = 1000.0,
    transfer_m: float = 400.0,
    rounds: int = 4,
    slack: int = 60,
    speed: float = 1.25,
    graph_path: Path | str = REPO / "data/processed/walk_graph.npz",
    gtfs: Path | str = REPO / "data/raw/gtfs_tuc_pamplona.zip",
) -> list[dict[str, object]]:
    tt = build_timetable(load_feed(gtfs), datetime.date(2026, 11, 11))
    graph = WalkGraph.load(graph_path)
    stops = (tt.stop_lon, tt.stop_lat)
    tr = build_transfers(graph, stops, transfer_m, speed=speed)
    out: list[dict[str, object]] = []
    for r in rows:
        t0 = int(r["dep_s"])
        o = (float(r["o_lon"]), float(r["o_lat"]))
        d = (float(r["d_lon"]), float(r["d_lat"]))
        acc = build_access(graph, ([o[0]], [o[1]]), stops, access_m, speed=speed)
        egr = build_access(graph, ([d[0]], [d[1]]), stops, access_m, speed=speed)
        es, esec = egr.row(0)
        eg = np.full(tt.n_stops, -1, np.int64)
        eg[es] = esec
        res = raptor_from_access(tt, tr, acc, 0, t0, max_rounds=rounds, board_slack=slack)
        arr = res.arrival.astype(np.int64)
        tot = np.where((arr < INF) & (eg >= 0), arr + eg, BIG)
        s_best = int(np.argmin(tot))
        transit_arr = int(tot[s_best]) if tot[s_best] < BIG else None
        pr = graph.shortest_path(o, d)
        direct = math.ceil(pr.length_m / speed - 1e-9) if pr.found else None
        rec: dict[str, object] = dict(
            od=r["od"],
            ours_transit_arr_s="",
            ours_direct_walk_s="" if direct is None else direct,
            ours_arr_s="",
            ours_tt_s="",
            ours_rides="",
            ours_walk_s="",
            ours_routes="",
            ours_used="",
        )
        if transit_arr is not None:
            rec["ours_transit_arr_s"] = transit_arr
            legs = reconstruct_journey(tt, res, s_best) or []
            rides = [lg for lg in legs if lg.mode == "ride"]
            walk = sum(lg.duration for lg in legs if lg.mode in ("access", "walk"))
            rec["ours_rides"] = len(rides)
            rec["ours_walk_s"] = int(walk + eg[s_best])
            rec["ours_routes"] = "+".join(
                tt.routes[int(tt.pattern_route[lg.pattern])].short_name for lg in rides
            )
        cands: list[tuple[int, str]] = []
        if transit_arr is not None:
            cands.append((transit_arr - t0, "transit"))
        if direct is not None:
            cands.append((direct, "walk"))
        if cands:
            best_t, used = min(cands)
            rec.update(ours_arr_s=t0 + best_t, ours_tt_s=best_t, ours_used=used)
        out.append(rec)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--ods", default=str(REPO / "validation/results/ods.csv"))
    ap.add_argument("--access-m", type=float, default=1000.0)
    ap.add_argument("--transfer-m", type=float, default=400.0)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--slack", type=int, default=60)
    ap.add_argument("--speed", type=float, default=1.25)
    ap.add_argument("--graph", default=str(REPO / "data/processed/walk_graph.npz"))
    a = ap.parse_args()
    with open(a.ods) as f:
        rows = list(csv.DictReader(f))
    out = run(
        rows,
        access_m=a.access_m,
        transfer_m=a.transfer_m,
        rounds=a.rounds,
        slack=a.slack,
        speed=a.speed,
        graph_path=a.graph,
    )
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, list(out[0]))
        w.writeheader()
        w.writerows(out)
    n_ok = sum(1 for x in out if x["ours_tt_s"] != "")
    print(f"{len(out)} ODs, {n_ok} reachable -> {a.out}")


if __name__ == "__main__":
    main()
