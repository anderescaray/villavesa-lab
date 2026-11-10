# villavesa-lab

Interactive planning tool for Pamplona's urban bus network (TUC / "villavesas").
Users see who can reach what by public transport today, edit the network (stops,
lines, frequencies) and see the impact instantly; an optimizer proposes better
networks under a fixed budget (fleet / bus-hours).

## Product (what "done" means)

A web app (`docker compose up` → http://localhost:3000) with:

1. **Today's network** — map of all lines and stops from the official GTFS; click any
   point → isochrone map (where can I get in 15/30/45 min, walk + bus).
2. **Accessibility dashboard** — % of population reaching key destinations
   (hospitals, health centres, UPNA/UNAV, industrial estates, city centre) within
   30 min at a chosen time of day; maps of under-served areas; equity view
   (by income per census section if available).
3. **Scenario editor** — add/move/remove stops, draw a new line snapped to streets,
   change headways, speed up a corridor (bus priority). Every change shows a diff
   vs. baseline: people gaining/losing access, avg travel time, fleet and bus-hours
   needed (computed from cycle time / headway), cost.
4. **Optimizer** — "given N buses / X bus-hours, maximise population-weighted
   accessibility": frequency reallocation, stop consolidation and new-line
   proposals. Show the proposal, the trade-off curve (budget vs. benefit) and why.
5. **Scenario comparison + exportable report** (PDF/HTML) for a planner or journalist.

UI language: Spanish. Code, docs and README: English.

## Data (all public)

- GTFS of TUC Pamplona — Spain's National Access Point (nap.transportes.gob.es, file 1177).
- INE Census 2021: population on 1 km² grid + census-section boundaries (and
  population per section). INE household income atlas per section for equity.
- OpenStreetMap Navarra extract (Geofabrik) — walking network + destinations (POIs).
- IDENA (Gobierno de Navarra) — line shapes, administrative limits.

If the sandbox cannot download a source, check `data/raw/` first (the owner may
have committed it). Never invent data. Every dataset gets a loader with schema
validation and a note in `docs/data.md` (source, licence, date, known caveats).

## Architecture (suggested, you may change it — record why in docs/decisions.md)

- `engine/` (Python): GTFS ingestion, walking graph, **RAPTOR router implemented
  from scratch** (round-based, with transfers + walking), travel-time matrices,
  accessibility metrics, cost model, optimizer (MILP via OR-Tools/PuLP + metaheuristic
  e.g. ALNS for line design). Must be fast: full-city matrix for a scenario in
  seconds (numpy/numba, caching, incremental recompute).
- `api/`: FastAPI serving scenarios, isochrones, metrics, optimizer jobs.
- `web/`: React + MapLibre GL / deck.gl.
- Demand: no official OD matrix exists publicly → gravity model from population and
  destinations; state this limitation clearly in UI and README.

## Quality bar

- Router validated against an independent reference (r5py or OpenTripPlanner) on a
  random sample of OD pairs; report error stats in README.
- Baseline sanity checks vs. reality (e.g. line travel times vs. GTFS schedule,
  reported avg commercial speed ~13 km/h).
- Tests for every engine module (pytest), API tests, a few Playwright e2e tests for
  the UI. CI in GitHub Actions must be green before merging.
- Type hints, ruff, mypy (engine), eslint + prettier (web).

## Workflow rules

- Plan first: keep `docs/PLAN.md` (milestones + status) up to date.
- One branch + one PR per feature/milestone, small and reviewable, with a clear
  description, screenshots for UI changes, and test evidence. Merge it yourself
  once CI is green. Never push directly to `main`.
- Record every non-trivial technical decision in `docs/decisions.md` (context,
  options, choice, why).
- Subagents are allowed for parallel work (research, tests, UI pieces, reviews),
  but always with `model: "opus"` or `model: "sonnet"` — never Fable.
- Before closing a milestone, have a fresh subagent review the PR critically.

## Finish line

Not done until: all milestones merged, CI green, `docker compose up` works from a
clean clone, and the README is portfolio-grade: one-paragraph pitch, GIF/video of
the app, architecture diagram, how the router and optimizer work, validation
results, a "findings" section (e.g. "N people in the Comarca cannot reach a
health centre in 30 min; this scenario fixes X% of that with 0 extra buses"),
limitations, and how to reproduce.
