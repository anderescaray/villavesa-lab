"""Print the OTP and vlab itineraries of selected ODs side by side (for outlier diagnosis).

usage: uv run python validation/diagnose.py OD [OD ...] [--max-transfers 3]
Needs the OTP server running (see validation/README.md).
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import sys
import urllib.request
from datetime import timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from run_otp import DAY0, QUERY

from vlab.gtfs import build_timetable, load_feed
from vlab.raptor import INF, raptor_from_access, reconstruct_journey
from vlab.walk import WalkGraph, build_access, build_transfers

REPO = Path(__file__).resolve().parents[1]
FULL = QUERY.replace(
    "legs { mode duration distance route{shortName} }",
    "legs { mode duration distance route{shortName} start{scheduledTime} end{scheduledTime} from{name stop{gtfsId}} to{name stop{gtfsId}} }",
)


def hms(s: float) -> str:
    s = int(s)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("od", nargs="+", type=int)
    ap.add_argument("--access-m", type=float, default=1000.0)
    ap.add_argument("--transfer-m", type=float, default=400.0)
    a = ap.parse_args()
    rows = {int(r["od"]): r for r in csv.DictReader(open(REPO / "validation/results/ods.csv"))}
    tt = build_timetable(
        load_feed(REPO / "data/raw/gtfs_tuc_pamplona.zip"), datetime.date(2026, 11, 11)
    )
    g = WalkGraph.load(REPO / "data/processed/walk_graph.npz")
    stops = (tt.stop_lon, tt.stop_lat)
    tr = build_transfers(g, stops, a.transfer_m)
    for od in a.od:
        r = rows[od]
        t0 = int(r["dep_s"])
        print(f"\n=== OD {od} ({r['kind']}) depart {hms(t0)}  straight {r['straight_m']} m")
        q = FULL % dict(
            olat=r["o_lat"],
            olon=r["o_lon"],
            dlat=r["d_lat"],
            dlon=r["d_lon"],
            dep=(DAY0 + timedelta(seconds=t0)).isoformat(),
            first=100,
            speed=1.25,
            maxtr=", maximumTransfers:3",
        )
        resp = json.load(
            urllib.request.urlopen(
                urllib.request.Request(
                    "http://localhost:8080/otp/gtfs/v1",
                    json.dumps({"query": q}).encode(),
                    {"Content-Type": "application/json"},
                )
            )
        )
        edges = [e["node"] for e in resp["data"]["planConnection"]["edges"]]
        arr = lambda n: (datetime.datetime.fromisoformat(n["end"]) - DAY0).total_seconds()
        best = min(edges, key=arr)
        print(f"OTP best arrival {hms(arr(best))} ({arr(best) - t0:.0f} s)")
        for l in best["legs"]:
            nm = lambda x: x["name"] + (" [" + x["stop"]["gtfsId"] + "]" if x.get("stop") else "")
            print(
                f"  {l['mode']:5s} {(l['route'] or {}).get('shortName', ''):4s} {l['start']['scheduledTime'][11:19]}-{l['end']['scheduledTime'][11:19]} {l['distance']:.0f} m  {nm(l['from'])} -> {nm(l['to'])}"
            )
        o = (float(r["o_lon"]), float(r["o_lat"]))
        d = (float(r["d_lon"]), float(r["d_lat"]))
        acc = build_access(g, ([o[0]], [o[1]]), stops, a.access_m)
        egr = build_access(g, ([d[0]], [d[1]]), stops, a.access_m)
        es, esec = egr.row(0)
        eg = np.full(tt.n_stops, -1)
        eg[es] = esec
        res = raptor_from_access(tt, tr, acc, 0, t0)
        tot = np.where((res.arrival < INF) & (eg >= 0), res.arrival.astype(np.int64) + eg, 10**12)
        s = int(np.argmin(tot))
        print(f"vlab best transit arrival {hms(tot[s])} ({tot[s] - t0} s)")
        for lg in reconstruct_journey(tt, res, s) or []:
            nm = lambda i: f"{tt.stop_names[i]} [{tt.stop_ids[i]}]" if i >= 0 else "origin"
            rt = (
                tt.routes[int(tt.pattern_route[lg.pattern])].short_name if lg.mode == "ride" else ""
            )
            print(
                f"  {lg.mode:6s} {rt:4s} {hms(lg.depart)}-{hms(lg.arrive)}  {nm(lg.from_stop)} -> {nm(lg.to_stop)}"
            )
        print(f"  egress {eg[s]} s")


if __name__ == "__main__":
    main()
