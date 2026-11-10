# Decision log

Each entry: context → options → choice → why.

## D-001 Single working branch, sequential PRs

- **Context**: the brief asks for one branch + one PR per milestone; the execution
  environment only allows pushing to one designated branch.
- **Choice**: every milestone is developed on the designated session branch,
  opened as its own PR, squash-merged, and the branch is then reset onto the new
  `main` for the next milestone.
- **Why**: keeps PRs small and reviewable (one per milestone) while respecting
  the environment's push restriction.

## D-002 Repository layout: one Python project, two packages

- **Options**: separate `engine/` and `api/` projects with their own lockfiles; or
  one root `pyproject.toml` with two import packages.
- **Choice**: one root project managed by `uv`; `engine/src/vlab` (pure engine,
  no web dependencies imported) and `api/src/vlab_api` (FastAPI layer).
- **Why**: one lockfile, one virtualenv, one CI job; the import boundary is still
  enforced (engine never imports the API).

## D-003 Analysis zones: 200 m grid with dasymetric population

- **Context**: INE publishes population on a 1 km grid and per census section.
  1 km cells are far too coarse for walk access to bus stops (typical 300–500 m).
- **Choice**: 200 m cells in EPSG:25830. Section population (INE) is distributed
  to cells proportionally to residential building floor area from OSM
  (dasymetric mapping); section totals are preserved exactly.
- **Why**: resolution adequate for stop-level effects, still small enough
  (a few thousand populated cells) for a full matrix recompute in seconds.
  Caveat documented in `docs/data.md`: within-section distribution is modelled.

## D-004 Compact processed data is committed

- **Context**: `docker compose up` must work from a clean clone; raw downloads are
  large, slow and depend on third-party servers being up.
- **Choice**: raw downloads stay git-ignored and reproducible via `make data`;
  the compact processed bundle in `data/processed/` (a few MB) is committed.
- **Why**: reproducibility *and* a clean-clone experience that does not depend on
  INE/OSM mirrors being reachable. CI also uses the committed bundle.

## D-005 OSM source mirror

- **Context**: Geofabrik (suggested in the brief) is not reachable from the build
  environment.
- **Choice**: download the Navarra extract from `download.openstreetmap.fr`
  (same OSM data, daily extracts); Geofabrik URL kept as a fallback in the script.

## D-006 Travel time definition

- **Choice**: travel time between two zones for an analysis window is the mean
  over departures sampled across the window (default every 10 min over 60 min) of
  walk-access + RAPTOR + walk-egress, capped by the direct walking time.
- **Why**: single-departure times are noisy for low-frequency lines (phase
  artefacts) and would make headway changes look erratic; sampling a window is
  what R5 and most accessibility tools do, which also makes validation fair.

## D-007 Checkpoint commits of in-progress work

- **Context**: the build container is ephemeral and several workstreams run in
  parallel in one working tree on one branch.
- **Choice**: in-progress work is pushed to the session branch as `wip:` checkpoint
  commits so nothing is lost; a milestone PR is opened only when its part is
  complete and green, and is squash-merged, so `main` history stays one commit
  per milestone. The branch is never force-pushed: after a squash merge, `main`
  is merged back into the branch instead.
