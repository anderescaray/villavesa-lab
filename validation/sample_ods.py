"""Draw the validation sample: population-weighted zone-to-zone pairs + stop-to-stop pairs.

Output: validation/results/ods.csv (fixed seed => identical on every run).

* zone pairs: origin and destination zone drawn with probability proportional to
  population (``data/processed/zones.parquet``), zone centroids as coordinates, rejecting
  pairs closer than 500 m straight line (trivial walks).
* stop pairs: two distinct GTFS stops drawn uniformly, rejecting pairs closer than 500 m.
* each pair gets one departure time from 08:00, 08:20, 08:40, 12:00 on 2026-11-11.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from vlab.data import load_zones
from vlab.gtfs import build_timetable, load_feed
from vlab.gtfs.geometry import to_xy

REPO = Path(__file__).resolve().parents[1]
SEED = 20261111
N_ZONE, N_STOP = 600, 200
DEPS = (8 * 3600, 8 * 3600 + 1200, 8 * 3600 + 2400, 12 * 3600)
MIN_DIST_M = 500.0


def main() -> None:
    rng = np.random.default_rng(SEED)
    z = load_zones()
    z = z[z["population"] > 0].reset_index(drop=True)
    p = z["population"].to_numpy(float)
    p /= p.sum()
    zx, zy = to_xy(z["lon"].to_numpy(), z["lat"].to_numpy())
    rows = []
    while sum(r["kind"] == "zone" for r in rows) < N_ZONE:
        o, d = rng.choice(len(z), 2, p=p)
        dist = float(np.hypot(zx[o] - zx[d], zy[o] - zy[d]))
        if o == d or dist < MIN_DIST_M:
            continue
        rows.append(dict(kind="zone", o_id=int(z["zone_id"][o]), d_id=int(z["zone_id"][d]),
                         o_lon=z["lon"][o], o_lat=z["lat"][o], d_lon=z["lon"][d],
                         d_lat=z["lat"][d], straight_m=dist))
    feed = load_feed(REPO / "data/raw/gtfs_tuc_pamplona.zip")
    tt = build_timetable(feed, __import__("datetime").date(2026, 11, 11))
    sx, sy = tt.stop_x, tt.stop_y
    n_stop = 0
    while n_stop < N_STOP:
        o, d = rng.choice(tt.n_stops, 2, replace=False)
        dist = float(np.hypot(sx[o] - sx[d], sy[o] - sy[d]))
        if dist < MIN_DIST_M:
            continue
        rows.append(dict(kind="stop", o_id=int(o), d_id=int(d), o_lon=tt.stop_lon[o],
                         o_lat=tt.stop_lat[o], d_lon=tt.stop_lon[d], d_lat=tt.stop_lat[d],
                         straight_m=dist))
        n_stop += 1
    df = pd.DataFrame(rows)
    df.insert(0, "od", np.arange(len(df)))
    df["dep_s"] = rng.choice(DEPS, len(df))
    for c in ("o_lon", "o_lat", "d_lon", "d_lat"):
        df[c] = df[c].round(6)
    df["straight_m"] = df["straight_m"].round(1)
    out = REPO / "validation/results/ods.csv"
    df.to_csv(out, index=False)
    print(out, len(df), df.groupby("kind").straight_m.describe().round(0).to_string())


if __name__ == "__main__":
    main()
