"""Regression test against the committed OpenTripPlanner reference results (M11).

``validation/results/otp_main.csv`` holds OpenTripPlanner 2.8.1 earliest arrivals for the
sampled ODs (``validation/README.md`` explains how to regenerate them; OTP itself is NOT
needed here). The test re-runs OUR router on a deterministic subset of the sample and checks
(1) it still reproduces the committed ``ours_main.csv`` exactly and (2) its agreement with
OTP has not degraded beyond generous bounds (full-sample values: MAE 2.07 min, 89.8 % within
5 min, Spearman 0.979, see docs/validation.md).
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
RES = REPO / "validation" / "results"
NEEDED = [
    RES / "ods.csv",
    RES / "otp_main.csv",
    RES / "ours_main.csv",
    REPO / "data" / "raw" / "gtfs_tuc_pamplona.zip",
    REPO / "data" / "processed" / "walk_graph.npz",
]
pytestmark = pytest.mark.skipif(
    not all(p.is_file() for p in NEEDED), reason="validation results or data not present"
)


def _read(path: Path) -> list[dict[str, str]]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _run_ours(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    spec = importlib.util.spec_from_file_location(
        "validation_run_ours", REPO / "validation/run_ours.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.run(rows)  # type: ignore[no-any-return]


def test_router_agrees_with_otp_on_committed_sample() -> None:
    ods = _read(RES / "ods.csv")[::8]  # 100 pairs, zone and stop pairs in sample proportion
    ours = _run_ours(ods)
    committed = {r["od"]: r for r in _read(RES / "ours_main.csv")}
    otp = {r["od"]: r for r in _read(RES / "otp_main.csv")}

    # (1) exact regression against the committed run of our router
    for rec in ours:
        ref = committed[str(rec["od"])]
        assert str(rec["ours_tt_s"]) == ref["ours_tt_s"], f"OD {rec['od']} changed"
        assert str(rec["ours_rides"]) == ref["ours_rides"]

    # (2) agreement with the independent reference
    err = []
    ref_tt = []
    for rec in ours:
        o = otp[str(rec["od"])]["otp_tt_s"]
        if o and rec["ours_tt_s"] != "":
            err.append((int(rec["ours_tt_s"]) - int(float(o))) / 60.0)  # type: ignore[arg-type]
            ref_tt.append(float(o) / 60.0)
    e = np.asarray(err)
    assert len(e) >= 90
    assert np.abs(e).mean() < 3.0
    assert (np.abs(e) <= 5).mean() > 0.80
    assert abs(e.mean()) < 1.5
    ours_tt = e + np.asarray(ref_tt)
    rho = np.corrcoef(np.argsort(np.argsort(ours_tt)), np.argsort(np.argsort(ref_tt)))[0, 1]
    assert rho > 0.93
