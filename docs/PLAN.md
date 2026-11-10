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
| M1  | Data pipeline: GTFS loader, OSM walk graph, INE population/income, POIs    | wip    | #2  |
| M2  | RAPTOR router (numba) + walking access/egress/transfers + baseline checks  | wip    | #2  |
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

M1 + M2 (data bundle, GTFS, walk layer, RAPTOR) are complete and in PR #2.
Next: M3-M5 (accessibility service, scenarios, cost, API) built on
`vlab.raptor.travel_time_matrix`; router validation (M11) runs in parallel; the
web foundation (M6) is being built against the API contract with a mock.

Key facts so far: 1,794 zones / 365,400 residents; weekday 3,084 trips, 12.3 km/h
day-line commercial speed, 139 buses in motion at the AM peak; full matrix in ~0.4 s.

## Working agreements

- One PR per milestone from the session branch (see decision D-001); squash-merge
  when CI is green; restart the branch from `main` afterwards.
- Subagents work in disjoint directories of the same working tree; the lead
  integrates, reviews, commits and opens the PRs.
- Every merged milestone gets a fresh-subagent review before merge.
