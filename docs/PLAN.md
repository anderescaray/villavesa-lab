# Plan

Living document. Updated at every milestone boundary so work can resume after a
context reset. See `docs/architecture.md` for contracts and `docs/decisions.md`
for the reasoning behind choices.

## Status legend

`done` merged to main · `wip` in progress · `todo` not started

## Milestones

| #   | Milestone                                                                  | Status | PR  |
| --- | -------------------------------------------------------------------------- | ------ | --- |
| M0  | Scaffold: plan, architecture contracts, tooling, CI skeleton               | done   | #1  |
| M1  | Data pipeline: GTFS loader, OSM walk graph, INE population/income, POIs    | done   | #2  |
| M2  | RAPTOR router (numba) + walking access/egress/transfers + baseline checks  | done   | #2  |
| M3  | Accessibility engine: travel-time matrix, metrics, isochrones, gravity     | done   | #2  |
| M4  | Scenario model + cost model (fleet, bus-hours, cost) + diff vs baseline    | done   | #2  |
| M5  | API (FastAPI): network, trips, isochrones, metrics, scenarios              | done   | #2  |
| M6  | Web: design system, map, animated buses, isochrones                        | done   | #2  |
| M7  | Web: accessibility dashboard + equity view (and mock -> real API)          | done   | #2  |
| M8  | Web: scenario editor with live diff                                        | done   | #2  |
| M9  | Optimizer: frequency MILP, stop consolidation, new lines (ALNS), trade-off | done   | #2  |
| M10 | Web: optimizer view, scenario comparison (swipe), exportable report        | done   | #2  |
| M11 | Router validation against OpenTripPlanner                                  | done   | #2  |
| M12 | Docker compose, e2e tests, screenshots, demo GIF                           | done   | #2  |
| M13 | README (portfolio grade), findings with real numbers                       | done   | #2  |
| M14 | Design-review fixes (independent critique of the final screenshots)        | wip    | #3  |

M1-M13 landed in one squash-merged PR instead of one PR each: the session could
only push to one branch and was interrupted repeatedly, so milestones were
developed as checkpoint commits (decision D-007) and merged when everything was
green together.

## Current step

Everything is merged to `main` and CI is green (ruff, mypy strict, 260+ pytest
tests; eslint, prettier, strict TypeScript, 81 unit tests, 21 Playwright tests
against the real API). `docker compose up` was verified: both images build, the
stack serves the app on :3000 through nginx, and the API image built from a
clean clone of `main` comes up healthy in ~25 s.

In progress (PR #3): fixes from an independent design review of the final
screenshots: trade-off chart labels and tooltip, translated engine warnings,
compare side labels, tablet isochrone card, new-line rows in the optimizer
result, sticky footer in the draw-line inspector, one shared number formatter.

Possible next steps, none required for the finish line: a hover tooltip on the
delta maps; per-direction stop lists for new bidirectional lines (the engine
reuses one list reversed, which can warn about stops far from the reverse
path); include the UPNA campus bus loop in the drive graph; evenly re-spaced
timetables as an alternative frequency model (today's is conservative).

## Working agreements

- One PR per milestone from the session branch (see decision D-001); squash-merge
  when CI is green; restart the branch from `main` afterwards.
- Subagents work in disjoint directories of the same working tree; the lead
  integrates, reviews, commits and opens the PRs.
- Every merged milestone gets a fresh-subagent review before merge.
