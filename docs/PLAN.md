# Plan

Living document. Updated at every milestone boundary so work can resume after a
context reset. See `docs/architecture.md` for contracts and `docs/decisions.md`
for the reasoning behind choices.

## Status legend

`done` merged to main · `wip` in progress · `todo` not started

## Milestones

| #   | Milestone                                                                  | Status | PR  |
| --- | -------------------------------------------------------------------------- | ------ | --- |
| M0  | Scaffold: plan, architecture contracts, tooling, CI skeleton               | wip    |     |
| M1  | Data pipeline: GTFS loader, OSM walk graph, INE population/income, POIs    | todo   |     |
| M2  | RAPTOR router (numba) + walking access/egress/transfers + baseline checks  | todo   |     |
| M3  | Accessibility engine: travel-time matrix, metrics, isochrones, gravity     | todo   |     |
| M4  | Scenario model + cost model (fleet, bus-hours, cost) + diff vs baseline    | todo   |     |
| M5  | API (FastAPI): network, trips, isochrones, metrics, scenarios              | todo   |     |
| M6  | Web: design system, map, animated buses, isochrones                        | todo   |     |
| M7  | Web: accessibility dashboard + equity view                                 | todo   |     |
| M8  | Web: scenario editor with live diff                                        | todo   |     |
| M9  | Optimizer: frequency MILP, stop consolidation, new lines (ALNS), trade-off | todo   |     |
| M10 | Web: optimizer view, scenario comparison (swipe), exportable report        | todo   |     |
| M11 | Router validation against an independent reference (r5py / OTP)            | todo   |     |
| M12 | Docker compose, e2e tests, design review loop, screenshots                 | todo   |     |
| M13 | README (portfolio grade), findings with real numbers, final QA             | todo   |     |

## Current step

M0 — writing scaffold and contracts; data, engine and web agents start in parallel
right after.

## Working agreements

- One PR per milestone from the session branch (see decision D-001); squash-merge
  when CI is green; restart the branch from `main` afterwards.
- Subagents work in disjoint directories of the same working tree; the lead
  integrates, reviews, commits and opens the PRs.
- Every merged milestone gets a fresh-subagent review before merge.
