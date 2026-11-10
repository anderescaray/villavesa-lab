"""Query a local OpenTripPlanner server for every OD in ods.csv (stdlib only).

usage: python run_otp.py OUT.csv [--variant NAME] [--max-transfers N] [--url URL]

For each OD we request up to 30 itineraries in a 2 h search window (walk + bus only,
walk reluctance 1, board slack 60 s, alight/transfer slack 0, walk speed 1.25 m/s) and
keep the EARLIEST ARRIVAL among them (itineraries are not trusted to be sorted).
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=1))  # CET on 2026-11-11 (DST ended 2026-10-25)
FIRST = 100
DAY0 = datetime(2026, 11, 11, 0, 0, 0, tzinfo=TZ)

QUERY = """
{ planConnection(
    origin:{location:{coordinate:{latitude:%(olat)s, longitude:%(olon)s}}},
    destination:{location:{coordinate:{latitude:%(dlat)s, longitude:%(dlon)s}}},
    dateTime:{earliestDeparture:"%(dep)s"},
    modes:{direct:[WALK], transit:{transit:[{mode:BUS}]}},
    searchWindow:"PT2H", first:%(first)s,
    preferences:{
      street:{walk:{speed:1.25, reluctance:1.0, boardCost:0}},
      transit:{board:{slack:"PT60S"}, alight:{slack:"PT0S"},
               transfer:{slack:"PT0S", cost:0 %(maxtr)s}}
    }) {
  edges { node { start end duration numberOfTransfers walkTime waitingTime
    legs { mode duration route{shortName} } } } } }
"""


def query(url: str, row: dict, max_transfers: int | None) -> dict:
    dep = (DAY0 + timedelta(seconds=int(row["dep_s"]))).isoformat()
    q = QUERY % dict(olat=row["o_lat"], olon=row["o_lon"], dlat=row["d_lat"], dlon=row["d_lon"],
                     dep=dep, first=FIRST, maxtr="" if max_transfers is None else f", maximumTransfers:{max_transfers}")
    req = urllib.request.Request(url, json.dumps({"query": q}).encode(),
                                 {"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.load(r)
            break
        except Exception as e:  # noqa: BLE001
            resp = {"errors": [str(e)]}
            time.sleep(1)
    out = dict(od=row["od"], otp_arr_s="", otp_tt_s="", otp_transfers="", otp_walk_s="",
               otp_wait_s="", otp_routes="", otp_walk_only_s="", otp_transit_tt_s="", n_itin=0,
               error="")
    if "errors" in resp or not resp.get("data"):
        out["error"] = json.dumps(resp.get("errors"))[:200]
        return out
    edges = [e["node"] for e in resp["data"]["planConnection"]["edges"]]
    out["n_itin"] = len(edges)
    if not edges:
        return out
    t_dep0 = int(row["dep_s"])

    def arr_s(n: dict) -> int:
        return int((datetime.fromisoformat(n["end"]) - DAY0).total_seconds())

    best = min(edges, key=lambda n: (arr_s(n), n["numberOfTransfers"]))
    out.update(otp_arr_s=arr_s(best), otp_tt_s=arr_s(best) - t_dep0,
               otp_transfers=best["numberOfTransfers"], otp_walk_s=int(best["walkTime"]),
               otp_wait_s=int(best["waitingTime"]),
               otp_routes="+".join(l["route"]["shortName"] for l in best["legs"] if l["route"]))
    walk_only = [n for n in edges if all(l["mode"] == "WALK" for l in n["legs"])]
    if walk_only:
        out["otp_walk_only_s"] = min(int(n["duration"]) for n in walk_only)
    tr = [n for n in edges if any(l["mode"] != "WALK" for l in n["legs"])]
    if tr:
        out["otp_transit_tt_s"] = min(arr_s(n) for n in tr) - t_dep0
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--url", default="http://localhost:8080/otp/gtfs/v1")
    ap.add_argument("--max-transfers", type=int, default=3)
    ap.add_argument("--ods", default=str(REPO / "validation/results/ods.csv"))
    ap.add_argument("--first", type=int, default=100)
    a = ap.parse_args()
    global FIRST
    FIRST = a.first
    rows = list(csv.DictReader(open(a.ods)))
    t0 = time.time()
    mt = None if a.max_transfers < 0 else a.max_transfers
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(lambda r: query(a.url, r, mt), rows))
    cols = list(res[0].keys())
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(res)
    bad = sum(1 for r in res if r["error"])
    print(f"{len(res)} queries in {time.time()-t0:.0f}s, {bad} errors, "
          f"{sum(1 for r in res if r['otp_arr_s']!='')} with an itinerary -> {a.out}")


if __name__ == "__main__":
    main()
