#!/usr/bin/env bash
# Build the OpenTripPlanner graph (OSM clip + official GTFS) and optionally serve it.
#   validation/build_otp.sh          # clip OSM, download OTP jar if missing, build graph
#   validation/build_otp.sh serve    # additionally start the server on :8080 (foreground)
# Needs Java 21 (OTP 2.8.1 is the newest release that runs on it; 2.9/2.10 need Java 25),
# osmium-tool, and `uv`. Everything lands in validation/.cache and validation/work (git-ignored).
set -euo pipefail
cd "$(dirname "$0")/.."
V=2.8.1
JAR=validation/.cache/otp/otp-shaded-$V.jar
URL=https://repo1.maven.org/maven2/org/opentripplanner/otp-shaded/$V/otp-shaded-$V.jar
mkdir -p validation/.cache/otp validation/work/otp
if [ ! -s "$JAR" ]; then
  curl -fsS -o "$JAR" "$URL"
  curl -fsS -o "$JAR.sha1" "$URL.sha1"
  echo "$(cat "$JAR.sha1")  $JAR" | sha1sum -c -
fi
uv run python validation/clip_osm.py
cp validation/work/study.osm.pbf validation/work/otp/
cp data/raw/gtfs_tuc_pamplona.zip validation/work/otp/tuc-gtfs.zip
cp validation/otp-config/*.json validation/work/otp/
( cd validation/work/otp && java -Xmx4g -jar "../../../$JAR" --build --save . )
if [ "${1:-}" = "serve" ]; then
  cd validation/work/otp && exec java -Xmx4g -jar "../../../$JAR" --load --serve .
fi
