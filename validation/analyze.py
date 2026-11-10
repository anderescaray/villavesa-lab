"""Merge ours + OTP results, compute error statistics, draw figures, list outliers.

usage: uv run --with matplotlib python validation/analyze.py [--tag main] [--img]
Reads results/ours_<tag>.csv, results/otp_<tag>.csv (override with --ours/--otp);
writes results/merged_<tag>.csv, results/stats_<tag>.json (and docs/img/validation_*.png
with --img).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "validation/results"


def summarize(df: pd.DataFrame) -> dict:
    ours_ok = df.ours_tt_s.notna()
    ref_ok = df.otp_tt_s.notna()
    both = ours_ok & ref_ok
    out = dict(n=int(len(df)), both=int(both.sum()), only_ours=int((ours_ok & ~ref_ok).sum()),
               only_otp=int((~ours_ok & ref_ok).sum()), neither=int((~ours_ok & ~ref_ok).sum()))
    e = (df.ours_tt_s - df.otp_tt_s)[both].to_numpy(float) / 60.0  # minutes, ours - ref
    ref = df.otp_tt_s[both].to_numpy(float) / 60.0
    ours = df.ours_tt_s[both].to_numpy(float) / 60.0
    ae = np.abs(e)
    out.update(
        mean_err_min=e.mean(), median_err_min=float(np.median(e)), mae_min=ae.mean(),
        rmse_min=float(np.sqrt((e**2).mean())), p90_abs_min=float(np.percentile(ae, 90)),
        p95_abs_min=float(np.percentile(ae, 95)), max_abs_min=ae.max(),
        within_30s=float((ae <= 0.5).mean()), within_1=float((ae <= 1).mean()),
        within_2=float((ae <= 2).mean()), within_5=float((ae <= 5).mean()),
        pearson=float(stats.pearsonr(ours, ref)[0]), spearman=float(stats.spearmanr(ours, ref)[0]),
        mean_ref_min=ref.mean(), mean_ours_min=ours.mean(),
        mean_rel_err_pct=float((e / ref).mean() * 100),
        same_transfers=float((df.ours_rides[both] - 1 == df.otp_transfers[both]).mean()),
    )
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="main")
    ap.add_argument("--ours")
    ap.add_argument("--otp")
    ap.add_argument("--img", action="store_true")
    a = ap.parse_args()
    ods = pd.read_csv(RES / "ods.csv")
    ours = pd.read_csv(a.ours or RES / f"ours_{a.tag}.csv")
    otp = pd.read_csv(a.otp or RES / f"otp_{a.tag}.csv")
    df = ods.merge(ours, on="od").merge(otp, on="od")
    df["err_s"] = df.ours_tt_s - df.otp_tt_s
    df.to_csv(RES / f"merged_{a.tag}.csv", index=False)
    summ = {k: summarize(g) for k, g in df.groupby("kind")}
    summ["all"] = summarize(df)
    # walking-only comparison (network check): OTP walk-only vs ours direct walk
    w = df.dropna(subset=["otp_walk_only_s", "ours_direct_walk_s"])
    ratio = (w.ours_direct_walk_s / w.otp_walk_only_s).to_numpy()
    summ["walk_only"] = dict(n=int(len(w)), median_ratio=float(np.median(ratio)),
                             mean_ratio=float(ratio.mean()), p5=float(np.percentile(ratio, 5)),
                             p95=float(np.percentile(ratio, 95)),
                             within_5pct=float((np.abs(ratio - 1) <= 0.05).mean()),
                             mean_diff_s=float((w.ours_direct_walk_s - w.otp_walk_only_s).mean()))
    # composition of the best journeys
    both = df.dropna(subset=["ours_tt_s", "otp_tt_s"])
    summ["transit_share"] = dict(ours=float((both.ours_used == "transit").mean()),
                                 otp=float((both.otp_routes.fillna("") != "").mean()))
    (RES / f"stats_{a.tag}.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))
    if a.img:
        figures(df)


def figures(df: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ACC, GREY = "#D7263D", "#6B6B6B"
    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": GREY, "axes.labelcolor": GREY,
                         "xtick.color": GREY, "ytick.color": GREY, "text.color": "#222222",
                         "axes.spines.top": False, "axes.spines.right": False})
    b = df.dropna(subset=["ours_tt_s", "otp_tt_s"])
    img = REPO / "docs/img"
    img.mkdir(exist_ok=True)
    fig, axs = plt.subplots(1, 2, figsize=(9, 4.2), dpi=160, sharex=True, sharey=True)
    for ax, kind, title in zip(axs, ("zone", "stop"), ("Zone to zone", "Stop to stop")):
        g = b[b.kind == kind]
        ax.scatter(g.otp_tt_s / 60, g.ours_tt_s / 60, s=9, color=ACC, alpha=0.55, linewidths=0)
        lim = max(g.otp_tt_s.max(), g.ours_tt_s.max()) / 60 + 3
        ax.plot([0, lim], [0, lim], color=GREY, lw=0.8)
        ax.set_xlim(0, lim); ax.set_ylim(0, lim); ax.set_aspect("equal")
        ax.set_title(f"{title} (n={len(g)})", loc="left", fontsize=10)
        ax.set_xlabel("OpenTripPlanner travel time (min)")
    axs[0].set_ylabel("vlab travel time (min)")
    fig.tight_layout(); fig.savefig(img / "validation_scatter.png", facecolor="white"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=160)
    e = (b.err_s / 60).clip(-10, 10)
    ax.hist(e, bins=np.arange(-10, 10.01, 0.5), color=ACC, alpha=0.9, edgecolor="white", linewidth=0.5)
    ax.axvline(0, color=GREY, lw=0.8)
    ax.set_xlabel("vlab minus OpenTripPlanner (min; clipped at ±10)")
    ax.set_ylabel("OD pairs")
    fig.tight_layout(); fig.savefig(img / "validation_error_hist.png", facecolor="white"); plt.close(fig)


if __name__ == "__main__":
    main()
