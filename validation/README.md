# Router validation against OpenTripPlanner

Independent check of the from-scratch RAPTOR router (`engine/src/vlab/raptor`) against
**OpenTripPlanner 2.8.1** on the same GTFS and OpenStreetMap data. Results and analysis:
[`docs/validation.md`](../docs/validation.md). OTP is **not** a project dependency: it only
lives in `validation/.cache/` and `validation/work/` (git-ignored); the repo commits the
scripts and the compact results (`results/`, < 1 MB), so the statistics can be recomputed
without Java. `engine/tests/test_validation_otp.py` re-runs our router against the committed
OTP answers in CI.

## Reproduce the reference results

Requirements: Java 21, `osmium` (osmium-tool), `uv`, network access to Maven Central, the
Navarra OSM extract in `data/raw/osm/` and `make data` done (zones, walk graph).

```bash
# 1. sample (fixed seed): 600 population-weighted zone pairs + 200 stop pairs
uv run python validation/sample_ods.py                      # -> results/ods.csv

# 2. OTP graph (clips OSM to the study area + 2 km, downloads the jar, builds) and server
validation/build_otp.sh serve &                             # OTP on http://localhost:8080
# wait for "Grizzly server running", then:
python3 validation/run_otp.py results/otp_main.csv                      # nominal alignment
python3 validation/run_otp.py results/otp_calib.csv --speed 1.307       # walk speed calibrated
python3 validation/run_otp.py results/otp_nocap.csv --max-transfers -1  # no transfer cap
python3 validation/run_otp.py results/otp_slow.csv --speed 1.20         # noise floor (-4 %)
python3 validation/run_otp.py results/otp_fast.csv --speed 1.30         # noise floor (+4 %)
kill %1                                                     # stop the server

# 3. our router on the same ODs
uv run python validation/run_ours.py results/ours_main.csv
uv run python validation/run_ours.py results/ours_wide.csv --access-m 3400 --transfer-m 1000
uv run python validation/run_ours.py results/ours_accwide.csv --access-m 3400
uv run python validation/run_ours.py results/ours_xferwide.csv --transfer-m 1000

# 4. statistics and figures
A="uv run --with matplotlib --with scipy python validation/analyze.py"; R=validation/results
$A --tag main --merged --img                                # headline run (+ docs/img/validation_*.png)
$A --tag calib      --ours $R/ours_main.csv --otp $R/otp_calib.csv
$A --tag wide       --ours $R/ours_wide.csv --otp $R/otp_main.csv
$A --tag wide_calib --ours $R/ours_wide.csv --otp $R/otp_calib.csv --img
$A --tag accwide    --ours $R/ours_accwide.csv  --otp $R/otp_main.csv
$A --tag xferwide   --ours $R/ours_xferwide.csv --otp $R/otp_main.csv
$A --tag nocap      --ours $R/ours_main.csv --otp $R/otp_nocap.csv
$A --tag noise_slow --ours $R/otp_slow.csv --ours-is-otp --otp $R/otp_main.csv
$A --tag noise_fast --ours $R/otp_fast.csv --ours-is-otp --otp $R/otp_main.csv
```

Only steps 3 and 4 are needed to recompute everything from the committed OTP answers
(`results/otp_*.csv`). Inspect individual discrepancies (OTP server running) with
`uv run python validation/diagnose.py 741 545 --access-m 3400 --transfer-m 1000`.

## Files

| File | Purpose |
| --- | --- |
| `sample_ods.py` | draws the OD sample (seed 20261111) |
| `clip_osm.py`, `build_otp.sh`, `otp-config/` | OSM clip, OTP graph build and server |
| `run_otp.py` | queries the OTP GraphQL API (`planConnection`), keeps the earliest arrival |
| `run_ours.py` | same OD/time through `vlab` (access, RAPTOR, egress, min with direct walk) |
| `analyze.py` | merge, statistics (`results/stats_<tag>.json`), figures |
| `diagnose.py` | side-by-side itineraries of selected ODs |
| `results/` | `ods.csv`, `otp_*.csv`, `ours_*.csv`, `stats_*.json`, `merged_main.csv` |
