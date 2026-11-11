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
| M1  | Data pipeline: GTFS loader, OSM walk graph, INE population/income, POIs    | built  | #2  |
| M2  | RAPTOR router (numba) + walking access/egress/transfers + baseline checks  | built  | #2  |
| M3  | Accessibility engine: travel-time matrix, metrics, isochrones, gravity     | built  | #2  |
| M4  | Scenario model + cost model (fleet, bus-hours, cost) + diff vs baseline    | built  | #2  |
| M5  | API (FastAPI): network, trips, isochrones, metrics, scenarios              | built  | #2  |
| M6  | Web: design system, map, animated buses, isochrones                        | built  | #2  |
| M7  | Web: accessibility dashboard + equity view (and mock -> real API)          | wip    |     |
| M8  | Web: scenario editor with live diff                                        | wip    |     |
| M9  | Optimizer: frequency MILP, stop consolidation, new lines (ALNS), trade-off | built  | #2  |
| M10 | Web: optimizer view, scenario comparison (swipe), exportable report        | todo   |     |
| M11 | Router validation against OpenTripPlanner                                  | built  | #2  |
| M12 | Docker compose, e2e tests, design review loop, screenshots                 | wip    |     |
| M13 | README (portfolio grade), findings with real numbers, final QA             | todo   |     |

`built` = implemented, tested and on the session branch, waiting for its PR to merge.

## Current step

The engine, API, optimizer, report endpoint and router validation are complete
and tested (PR #2, which also carries the web foundation). Two web workstreams
are in progress in `web/`: M7 (accessibility dashboard + removal of the mock
API, e2e against the real API) and M8 (scenario editor, shared scenario store in
`web/src/features/scenario`). PR #2 merges as soon as the web job is green.

Next: M10 (optimizer view: run job, animated reveal of the proposal, trade-off
curve; compare view with before/after swipe; report export via `/api/report`),
then Docker verification, final screenshots/GIF, README with findings.

Numbers for the README (weekday 08-09 h, 30 min): 365,400 residents; hospital
71.2%, health centre 99.1%, university 49.9%, city centre 75.6% within 30 min;
141,766 residents miss an essential destination; mean door-to-door time 27.5
min. Optimizer at the same 162 buses: accessibility +3.2% (frequency only, 32 s)
or +3.7% (with 10 stops consolidated and one new line), about 6,100-9,200 fewer
under-served residents. OTP validation: median error -0.4 min, MAE 2.1 min,
90% within 5 min (800 pairs).

## Working agreements

- One PR per milestone from the session branch (see decision D-001); squash-merge
  when CI is green; restart the branch from `main` afterwards.
- Subagents work in disjoint directories of the same working tree; the lead
  integrates, reviews, commits and opens the PRs.
- Every merged milestone gets a fresh-subagent review before merge.
