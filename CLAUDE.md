# villavesa-lab

Interactive planning tool for Pamplona's urban bus network (TUC / "villavesas").
Users see who can reach what by public transport today, edit the network (stops,
lines, frequencies) and see the impact instantly; an optimizer proposes better
networks under a fixed budget (fleet / bus-hours).

You have full ownership and creative freedom over this project. The spec below is
the minimum, not the ceiling: add features, analyses or polish whenever they make
the product more useful or more impressive — as long as everything stays honest
(real data, measured claims, documented limitations) and professional.

## Autonomy (read this first)

- Work fully autonomously until the Finish line. **Never stop to ask the owner a
  question or wait for confirmation** — nobody will answer during the run. When
  something is ambiguous, pick the most sensible option, record it in
  `docs/decisions.md`, and keep going.
- If something is blocked (a download fails, a library doesn't work), try
  alternatives, and if it's still blocked, design around it, document the
  limitation and move on to the next milestone. Never end the session early
  because of one blocker.
- Ending your turn = the work stops. Only end it when the Finish line is met.
- Keep `docs/PLAN.md` always current (milestones, status, next step) so work can
  resume cleanly after context compaction or a new session.
- Use subagents freely to parallelise and to get independent reviews (research,
  data loaders, tests, UI components, design critique, QA, code review), always
  with `model: "opus"` or `model: "sonnet"` — never Fable.

## Product (what "done" means)

A web app (`docker compose up` → http://localhost:3000) with:

1. **Today's network** — full-bleed map of all lines and stops from the official
   GTFS, with buses animated along their routes according to the timetable
   (time slider / play button). Click any point → isochrone (15/30/45 min, walk + bus).
2. **Accessibility dashboard** — % of population reaching key destinations
   (hospitals, health centres, UPNA/UNAV, industrial estates, city centre) within
   30 min at a chosen day/time; maps of under-served areas; equity view by income
   per census section.
3. **Scenario editor** — add/move/remove stops, draw a new line snapped to streets,
   change headways, speed up a corridor (bus priority). Every change shows a diff
   vs. baseline: people gaining/losing access, avg travel time, fleet and bus-hours
   needed (from cycle time / headway), cost.
4. **Optimizer** — "given N buses / X bus-hours, maximise population-weighted
   accessibility": frequency reallocation, stop consolidation, new-line proposals.
   Show the proposal, the budget-vs-benefit trade-off curve and an explanation.
5. **Scenario comparison** (before/after) + exportable report (PDF/HTML) for a
   planner or journalist.

Language: everything in the repo is English — code, comments, commit messages,
PR titles/descriptions, docs, README. The UI is bilingual with an i18n toggle:
Spanish by default (local users), English one click away (international
reviewers); Basque (euskera) as a bonus if time allows.

## Design direction (important)

The UI must feel like a polished product from a top product company — think
Google Maps / Google's Material 3 at its most restrained, Linear, Apple Maps.
Elegant, minimal, clean, confident; it should impress through precision and
smooth interaction, not decoration.

- **Avoid the generic "AI-generated" look**: no cream/beige backgrounds, no
  serif display headings, no orange/terracotta accents, no emoji in the UI, no
  gradient blobs, no card-grid-everything dashboards, no oversized rounded
  pastel boxes.
- **Layout**: the map is the hero, edge to edge. Controls live in a slim side
  panel and small floating surfaces over the map. Generous whitespace, 8px grid,
  clear hierarchy, one primary action per view.
- **Colour**: neutral white/greys (and a true dark mode), a single strong accent
  (villavesa red is a good candidate), line colours from the GTFS used
  consistently. Data-viz palettes must be perceptually sound and colour-blind safe.
- **Type**: one clean sans (e.g. Inter or Geist), tight type scale, tabular
  numbers for metrics.
- **Motion**: subtle and purposeful, 150–250 ms easing; isochrones that grow
  smoothly, animated number transitions, smooth camera moves. No gratuitous animation.
- **Quality details**: skeleton loaders instead of spinners, empty states,
  keyboard shortcuts, responsive down to tablet, accessible contrast (WCAG AA),
  fast (60 fps map, instant feedback when editing).
- **Wow moments** (tasteful): live animated buses on load; before/after swipe
  comparison of scenarios; optimizer result revealed as an animated diff on the map.
- **Self-review loop**: capture Playwright screenshots of every main view and have
  a fresh subagent critique them against this section; iterate until they would
  pass a senior product designer's review. Put the final screenshots in `docs/`.

## Data (all public)

- `data/raw/gtfs_tuc_pamplona.zip` — official GTFS of TUC Pamplona (TCC), from
  Spain's National Access Point (feed 1177). 54 routes, ~563 stops, ~60k trips,
  service 2026-11-10 → 2026-11-30. Uses `calendar_dates.txt` only (no `calendar.txt`).
- INE Census 2021: population on 1 km² grid + census-section boundaries and
  population per section; INE household income atlas per section (equity).
- OpenStreetMap Navarra extract (Geofabrik) — walking network + destinations (POIs).
- IDENA (Gobierno de Navarra) — line shapes, administrative limits.

Download what you need with reproducible scripts (`make data`); don't commit large
downloaded files (gitignore `data/raw/*` except the GTFS). Never invent data. Every
dataset gets a loader with schema validation and a note in `docs/data.md`
(source, licence, date, caveats).

## Architecture (suggested — change it if you have a better idea, and say why in docs/decisions.md)

- `engine/` (Python): GTFS ingestion, walking graph, **RAPTOR router implemented
  from scratch** (round-based, transfers + walking), travel-time matrices,
  accessibility metrics, cost model, optimizer (MILP via OR-Tools/PuLP + a
  metaheuristic such as ALNS for line design). Must be fast: a full-city
  scenario recompute in seconds (numpy/numba, caching, incremental recompute).
- `api/`: FastAPI serving scenarios, isochrones, metrics, optimizer jobs.
- `web/`: React + TypeScript + MapLibre GL + deck.gl.
- Demand: no public OD matrix exists → gravity model from population and
  destinations; state this limitation clearly in the UI and README.

## Quality bar

- Router validated against an independent reference (r5py or OpenTripPlanner) on
  a random sample of OD pairs; report error stats in the README.
- Baseline sanity checks vs. reality (line travel times vs. GTFS schedule,
  reported average commercial speed ~13 km/h).
- pytest for every engine module, API tests, Playwright e2e tests for the main UI
  flows. GitHub Actions CI must be green before merging.
- Type hints, ruff, mypy (engine); eslint + prettier + strict TS (web).

## Workflow rules

- Plan first: write `docs/PLAN.md` (milestones + status) and keep it updated.
- One branch + one PR per feature/milestone (`gh pr create`), small and
  reviewable, with a clear description, screenshots for UI changes, and test
  evidence. Merge it yourself once CI is green (`gh pr merge --squash`), update
  `main`, and continue immediately. Never push directly to `main`.
- Before merging a milestone, have a fresh subagent review the PR critically and
  address its findings.
- Record every non-trivial technical decision in `docs/decisions.md`
  (context, options, choice, why).

## Finish line

Not done until: all milestones merged, CI green, `docker compose up` works from a
clean clone, and the README is portfolio-grade: one-paragraph pitch, hero
screenshot + GIF/video of the app, architecture diagram, how the router and
optimizer work, validation results, a "findings" section with real numbers
(e.g. "N people in the Comarca cannot reach a health centre in 30 min; this
scenario fixes X% of that with 0 extra buses"), limitations, and how to reproduce.
