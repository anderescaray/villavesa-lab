# Engine: accessibility, scenarios, cost and optimizer

How the layers above the router work. The router itself is in
[`router.md`](router.md); data in [`data.md`](data.md); validation in
[`validation.md`](validation.md).

## World model (`vlab.model`)

`Model.load()` reads the processed bundle and the GTFS once: 1,794 zones (200 m
cells) with residents, activity and income; POIs mapped to their zone; the
pedestrian and bus-drivable graphs; and a zone-to-zone direct-walk matrix (up to
60 min). A `NetworkState` is a timetable plus the walking tables that match its
stops (stop-to-stop transfers up to 400 m, zone-to-stop access up to 1 km). The
baseline state of each day type (weekday, Saturday, Sunday: the feed's most
typical date of each) is built lazily.

An **analysis window** is a day type and a departure interval (default weekday
08:00-09:00).

## Travel times and indicators (`vlab.access`)

- **Travel time** between two zones = mean over departures every 10 minutes of
  the window of walk + RAPTOR + walk, never worse than walking directly. A
  departure with no journey under 2 h counts as 2 h, and a pair is reachable only
  if at least half of its departures are (a *censored mean*, so that cutting
  service can never lower a reported time). The full matrix takes ~0.5 s.
- **Nearest-destination time** per zone and category (hospital, health centre,
  university, industrial estate, city centre, secondary school, supermarket):
  the minimum over the zones that contain a POI of that category. From it:
  residents within a threshold, population-weighted median and mean, and the
  cumulative curve.
- **Under-served residents**: residents who miss at least one *essential*
  category (hospital, health centre, city centre) within the threshold.
- **Activity within 30 min** (`jobs_30`): share of all non-residential floor area
  reachable within the threshold. A proxy for jobs and services, not employment.
- **Accessibility index** (the optimizer's objective): population-weighted Hansen
  accessibility, `sum_j A_j exp(-beta t_ij) / sum_j A_j` with `beta = 0.07/min`
  (the weight halves every ~10 minutes), between 0 and 1. It is smooth, so small
  service changes move it, and it does not depend on an arbitrary threshold.
- **Demand-weighted mean travel time**: weights from a production-constrained
  gravity model, `T_ij = P_i A_j f(t_ij) / sum_k A_k f(t_ik)`, computed once on
  the baseline and held fixed, so a scenario's change reflects the service and
  not a redistribution of trips. There is no public OD matrix; this is a model.
- **Equity**: the same indicators by population-weighted income quintile
  (INE household income per person, by census section) and a concentration index
  of "reaches the category within the threshold" over the income ranking
  (positive: access is concentrated among higher incomes).
- **People gaining / losing**: residents of zones where an essential category
  crosses the threshold, or, failing that, whose demand-weighted mean travel time
  changes by more than 60 s.

### Isochrones

From any point: an ad-hoc access table to nearby stops, one RAPTOR query per
sampled departure, then a multi-source Dijkstra on the pedestrian graph seeded
with the arrival time at every stop (and 0 at the origin). Node times use the
same censored mean as the matrix. Polygons come from rasterising node times on
a 30 m grid with a 75 m walking buffer and contouring; they are nested by
construction. About 50 ms per request.

## Scenarios (`vlab.scenario`)

A scenario is an ordered list of typed edits applied to the baseline timetable
(pure functions; a few milliseconds each). When stops change, the walking
tables are rebuilt (~0.2 s).

| Edit | Semantics |
| --- | --- |
| `set_headway`, `scale_frequency` | The number of trips starting in the period changes, pattern by pattern, **keeping existing departures**: more service inserts trips in the middle of the widest gaps (with running times interpolated between its neighbours), less service removes the trips that leave the narrowest gaps. More service is therefore a superset of today's timetable — nobody loses a connection — and less service a subset. Branches and short-turn variants keep their share (largest remainder, at least one trip each). `set_headway` targets the **mean headway of the busiest direction** (period length / trips; peak 07-09 h, off-peak measured 10-13 h and applied outside the peak). |
| `speed_up` | Running time between the given consecutive stops divided by the factor (1.0-2.0); dwell unchanged; downstream times shift earlier. |
| `remove_stop` | The stop is dropped from every pattern (or one route); each removal saves 20 s downstream (deceleration + dwell + acceleration). |
| `move_stop` | New coordinates; walking tables rebuilt; bus paths are not rerouted (warning beyond 300 m). |
| `add_stop` | Inserted after a given stop; arrival interpolated by distance; the detour at the pattern's mean speed plus 20 s are added downstream. |
| `remove_route` | All its trips disappear. |
| `add_route` | Path snapped to the bus-drivable street graph (respecting one-ways) through the waypoints or stops; stops projected on it; run times at the network's mean commercial speed (12.3 km/h, which already includes dwell) unless given; regular headway over a default 06:30-22:30 span; optional reverse direction. A leg that cannot follow streets falls back to a straight segment with a warning. |

Caveats: cost for the year applies the scenario to every day type and skips
edits that do not apply on a day (e.g. a line that does not run on Sundays).

## Cost model (`vlab.cost`)

- **Bus-hours**: revenue hours (first departure to last arrival). The operator's
  tariff is defined on useful hours, so layover is not charged.
- **Km**: trip length along its shape.
- **Fleet**: peak number of simultaneously committed buses, each trip holding a
  bus from its first departure until its last arrival plus a layover of
  `max(4 min, 10% of the run)`. For a regular line this is exactly
  `ceil(cycle time / headway)`; the network fleet is the peak of the summed
  curve, not the sum of per-line peaks.
- **Cost**: `43.15 EUR x bus-hours + 1.25 EUR x km` per day (the operator tariff
  of the pre-2024 concession, 2023 prices), plus `25,300 EUR` of capital per bus
  and year. A year is 251 working days, 52 Saturdays and 62 Sundays/holidays.

**Check against reality** (2023 actuals, `reference_facts.md`): the 2026 feed
gives a peak fleet of 162 buses (159 owned in 2023), 673,000 bus-hours a year
(+7.7% vs 624,817) and 8.34 M km (+4.4% vs 7.99 M; 8.12 M in 2024), i.e.
EUR 39.5 M of operating cost against EUR 34.7-37.0 M reported for 2023.

## Optimizer (`vlab.optimize`)

*Given N buses or X bus-hours, maximise population-weighted accessibility.*

1. **Stop consolidation** (optional). Candidates are non-terminal stops whose
   neighbours on the line would still be under 450 m apart and which have
   another stop within a 200 s walk, ranked by the smallest catchment. Each is
   evaluated with the real router; removals are kept greedily while the measured
   score improves (through riders save 20 s; a few residents walk further).
2. **Frequency reallocation** as a multiple-choice knapsack. Every line picks one
   factor from `{0.5, 0.67, 0.8, 1, 1.25, 1.5, 2}` (headways kept within 3-60
   min). The **benefit** of a factor is separable across lines and follows the
   waiting-time law, `benefit ∝ 1 - 1/f` (expected wait is half the headway),
   calibrated per line with two measured evaluations (`f = 0.5` and `f = 1.5`).
   The **resource** used by each factor (buses or bus-hours) is measured by
   applying the edit. The MILP is solved to optimality with OR-Tools CP-SAT in
   milliseconds; the plan is then checked on the real timetable (network fleet
   is a peak, which the per-line model only approximates) and tightened until
   it fits the budget.
3. **New lines** (optional) by ALNS. A pool of candidates connects pairs of hubs
   (zones with the most residents + activity, spread at least 1.1 km apart)
   ranked by excess person-time: gravity demand between their catchments times
   how much slower today's network is than a direct bus. Each candidate follows
   the street graph and serves the existing stops along it. A solution is a set
   of up to three lines with headways of 10/15/20 min; whatever they cost is
   paid for by re-solving the knapsack with the remaining budget, so every
   solution visited is feasible. Destroy/repair operators (insert best, insert
   random, remove, swap, change headway) are chosen with adaptive weights and
   accepted with a simulated-annealing rule.
4. **Local search** with the real router: move one frequency step from one line
   to another (or spend slack) while the score improves. This corrects the
   interactions the separable model ignores.
5. The proposal is **re-evaluated exactly** on all zones. If nothing beats the
   starting network, the starting network is returned.

Inner-loop evaluations use a fixed population-weighted sample of 350 origin
zones (~0.25 s each); final numbers use every zone. The **trade-off curve**
re-solves the knapsack for each budget from one shared probe of the lines and
evaluates each point exactly.

The result is an ordinary edit list, usable in every other endpoint, plus an
explanation: per line, the headway change, the buses it frees or uses and its
estimated contribution.

Limitations: the objective is measured on one analysis window (default the
weekday AM peak) while frequency factors apply all day; benefits are estimated
from a sample; new lines reuse existing stops; no vehicle capacity or crowding.
