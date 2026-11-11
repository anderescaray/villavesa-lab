"""Scenario edits applied to the real weekday network."""

from __future__ import annotations

import numpy as np
import pytest

from vlab.access.service import Evaluator
from vlab.cost import network_cost
from vlab.gtfs import Timetable, validate_timetable
from vlab.gtfs.stats import mean_headways
from vlab.model import Model
from vlab.scenario import (
    STOP_TIME_SAVING_S,
    ScenarioError,
    apply,
    edit_to_dict,
    nearby_stops,
    parse_edit,
    parse_edits,
    scenario_hash,
    snap_path,
)


def _main_pattern(tt: Timetable, route_id: str) -> int:
    return max(tt.patterns_of_route(route_id), key=tt.n_pattern_trips)


def _run(model: Model, raw: list[dict]) -> Timetable:
    sn = apply(model, "weekday", parse_edits(raw))
    validate_timetable(sn.state.timetable)
    return sn.state.timetable


@pytest.fixture(scope="module")
def base(model: Model) -> Timetable:
    return model.baseline("weekday").timetable


def test_empty_scenario_is_the_baseline(model: Model) -> None:
    sn = apply(model, "weekday", ())
    assert sn.state is model.baseline("weekday")
    assert not sn.changes.modified_routes


@pytest.mark.parametrize(
    ("route", "headway", "period"),
    [("4", 180, "all"), ("4", 480, "all"), ("1", 900, "peak"), ("9", 600, "offpeak")],
)
def test_set_headway_hits_the_target(
    model: Model, base: Timetable, route: str, headway: int, period: str
) -> None:
    tt = _run(
        model, [{"type": "set_headway", "route_id": route, "headway": headway, "period": period}]
    )
    got = mean_headways(tt, route)[period]
    assert got == pytest.approx(headway, rel=0.08)
    other = {"peak": "offpeak", "offpeak": "peak"}.get(period)
    if other:
        assert mean_headways(tt, route)[other] == mean_headways(base, route)[other]
    # other routes are untouched
    assert mean_headways(tt, "2") == mean_headways(base, "2")


def test_scale_frequency_changes_trips_fleet_and_hours(model: Model, base: Timetable) -> None:
    b = network_cost(base).routes["2"]
    up = network_cost(_run(model, [{"type": "scale_frequency", "route_id": "2", "factor": 2.0}]))
    down = network_cost(_run(model, [{"type": "scale_frequency", "route_id": "2", "factor": 0.5}]))
    assert up.routes["2"].trips == pytest.approx(2 * b.trips, abs=2)
    assert down.routes["2"].trips == pytest.approx(b.trips / 2, abs=2)
    assert up.routes["2"].fleet > b.fleet > down.routes["2"].fleet
    assert up.routes["2"].bus_hours == pytest.approx(2 * b.bus_hours, rel=0.05)
    assert up.routes["4"] == network_cost(base).routes["4"]


def test_speed_up_shortens_run_times_only_on_the_segments(model: Model, base: Timetable) -> None:
    p = _main_pattern(base, "4")
    seq = [base.stop_ids[s] for s in base.pattern_stop_seq(p)]
    key = base.patterns[p].key
    tt = _run(model, [{"type": "speed_up", "route_id": "4", "stop_ids": seq[3:9], "factor": 1.25}])
    q = tt.pattern_index[key]
    a0, d0 = base.arrivals(p).astype(int), base.departures(p).astype(int)
    a1, d1 = tt.arrivals(q).astype(int), tt.departures(q).astype(int)
    run0, run1 = a0[:, 1:] - d0[:, :-1], a1[:, 1:] - d1[:, :-1]
    assert np.array_equal(run1[:, :3], run0[:, :3])
    assert np.array_equal(run1[:, 8:], run0[:, 8:])
    assert np.array_equal(run1[:, 3:8], np.round(run0[:, 3:8] / 1.25).astype(int))
    assert np.array_equal(d1 - a1, d0 - a0)  # dwell unchanged
    assert np.array_equal(d1[:, 0], d0[:, 0])  # departures from the terminal unchanged


def test_speed_up_requires_a_matching_segment(model: Model, base: Timetable) -> None:
    with pytest.raises(ScenarioError, match="no route runs"):
        apply(
            model,
            "weekday",
            parse_edits(
                [
                    {
                        "type": "speed_up",
                        "stop_ids": [base.stop_ids[0], base.stop_ids[0]],
                        "factor": 1.2,
                    }
                ]
            ),
        )


def test_remove_stop_saves_time_downstream(model: Model, base: Timetable) -> None:
    p = _main_pattern(base, "4")
    seq = base.pattern_stop_seq(p)
    key = base.patterns[p].key
    sid = base.stop_ids[int(seq[5])]
    sn = apply(model, "weekday", parse_edits([{"type": "remove_stop", "stop_id": sid}]))
    tt = sn.state.timetable
    validate_timetable(tt)
    q = tt.pattern_index[key]
    assert len(tt.pattern_stop_seq(q)) == len(seq) - 1
    assert int(seq[5]) not in tt.pattern_stop_seq(q)
    assert np.array_equal(tt.arrivals(q)[:, :5], base.arrivals(p)[:, :5])
    assert np.array_equal(tt.arrivals(q)[:, -1], base.arrivals(p)[:, -1] - STOP_TIME_SAVING_S)
    assert sid in sn.changes.removed_stops | sn.changes.modified_stops
    assert "4" in sn.changes.modified_routes


def test_remove_stop_from_one_route_only(model: Model, base: Timetable) -> None:
    p = _main_pattern(base, "4")
    sid = base.stop_ids[int(base.pattern_stop_seq(p)[5])]
    sn = apply(
        model, "weekday", parse_edits([{"type": "remove_stop", "stop_id": sid, "route_id": "4"}])
    )
    assert sn.changes.modified_routes == {"4"}


def test_add_stop_inserts_and_delays_downstream(model: Model, base: Timetable) -> None:
    p = _main_pattern(base, "4")
    seq = base.pattern_stop_seq(p)
    a, b = int(seq[5]), int(seq[6])
    edit = {
        "type": "add_stop",
        "stop_id": "new-1",
        "name": "New stop",
        "lon": float((base.stop_lon[a] + base.stop_lon[b]) / 2),
        "lat": float((base.stop_lat[a] + base.stop_lat[b]) / 2),
        "route_id": "4",
        "direction": int(base.patterns[p].direction),
        "after_stop_id": base.stop_ids[a],
    }
    sn = apply(model, "weekday", parse_edits([edit]))
    tt = sn.state.timetable
    validate_timetable(tt)
    q = tt.pattern_index[base.patterns[p].key]
    new = tt.stop_index["new-1"]
    assert int(tt.pattern_stop_seq(q)[6]) == new
    assert (tt.arrivals(q)[:, -1] >= base.arrivals(p)[:, -1] + 20).all()
    # walking tables include the new stop
    assert sn.state.access.n_cols == tt.n_stops == base.n_stops + 1
    assert sn.state.transfers.n_rows == tt.n_stops
    assert len(sn.state.egress.row(new)[0]) > 0
    with pytest.raises(ScenarioError, match="already exists"):
        apply(model, "weekday", parse_edits([edit, edit]))


def test_move_stop_updates_walk_tables(model: Model, base: Timetable) -> None:
    s = int(base.pattern_stop_seq(_main_pattern(base, "4"))[5])
    sn = apply(
        model,
        "weekday",
        parse_edits(
            [
                {
                    "type": "move_stop",
                    "stop_id": base.stop_ids[s],
                    "lon": float(base.stop_lon[s]) + 0.006,
                    "lat": float(base.stop_lat[s]),
                }
            ]
        ),
    )
    assert sn.state.timetable.stop_lon[s] == pytest.approx(base.stop_lon[s] + 0.006)
    assert sn.changes.warnings  # moved ~490 m: paths are not rerouted
    assert not np.array_equal(sn.state.egress.row(s)[0], model.baseline("weekday").egress.row(s)[0])


def test_remove_route(model: Model, base: Timetable) -> None:
    sn = apply(model, "weekday", parse_edits([{"type": "remove_route", "route_id": "4"}]))
    tt = sn.state.timetable
    assert all(tt.n_pattern_trips(p) == 0 for p in tt.patterns_of_route("4"))
    assert network_cost(tt).routes["4"].trips == 0
    assert sn.changes.removed_routes == {"4"}


def test_add_route_snaps_to_streets_and_schedules_both_directions(
    model: Model, base: Timetable
) -> None:
    edit = {
        "type": "add_route",
        "route_id": "new-A",
        "short_name": "A",
        "stops": [
            {"lon": -1.6100, "lat": 42.8350, "name": "East end"},
            {"stop_id": base.stop_ids[int(base.pattern_stop_seq(_main_pattern(base, "4"))[8])]},
            {"lon": -1.6765, "lat": 42.8010, "name": "West end"},
        ],
        "headway": 600,
    }
    sn = apply(model, "weekday", parse_edits([edit]))
    tt = sn.state.timetable
    validate_timetable(tt)
    pats = tt.patterns_of_route("new-A")
    assert len(pats) == 2
    for p in pats:
        off = tt.pattern_offsets(p)
        assert (np.diff(off) > 0).all()
        straight = np.hypot(
            tt.stop_x[tt.pattern_stop_seq(p)[-1]] - tt.stop_x[tt.pattern_stop_seq(p)[0]],
            tt.stop_y[tt.pattern_stop_seq(p)[-1]] - tt.stop_y[tt.pattern_stop_seq(p)[0]],
        )
        assert straight < off[-1] < 2.5 * straight  # follows streets, no absurd detour
        assert tt.n_pattern_trips(p) == pytest.approx(16 * 6, abs=2)
        assert len(tt.pattern_path(p)) > 20
        run = tt.arrivals(p)[0, -1] - tt.departures(p)[0, 0]
        assert 10.0 < (off[-1] / 1000) / (run / 3600) < 14.5  # network commercial speed
    assert sn.changes.added_routes == {"new-A"}
    assert len(sn.changes.added_stops) == 2
    cost = network_cost(tt).routes["new-A"]
    assert cost.fleet >= 6 and cost.km > 1000


def test_add_route_validation(model: Model) -> None:
    with pytest.raises(ScenarioError, match="at least two stops"):
        parse_edit(
            {"type": "add_route", "route_id": "x", "stops": [{"stop_id": "1"}], "headway": 600}
        )
    with pytest.raises(ScenarioError, match="unknown stop_id"):
        apply(
            model,
            "weekday",
            parse_edits(
                [
                    {
                        "type": "add_route",
                        "route_id": "x",
                        "stops": [{"stop_id": "nope"}, {"stop_id": "1"}],
                        "headway": 600,
                    }
                ]
            ),
        )
    with pytest.raises(ScenarioError, match="already exists"):
        apply(
            model,
            "weekday",
            parse_edits(
                [
                    {
                        "type": "add_route",
                        "route_id": "4",
                        "stops": [{"stop_id": "1"}, {"stop_id": "5"}],
                        "headway": 600,
                    }
                ]
            ),
        )


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "nope"},
        {"type": "set_headway", "route_id": "4", "headway": 30},
        {"type": "set_headway", "route_id": "4", "headway": 600, "period": "night"},
        {"type": "scale_frequency", "route_id": "4", "factor": 50},
        {"type": "speed_up", "stop_ids": ["1"], "factor": 1.2},
        {"type": "speed_up", "stop_ids": ["1", "5"], "factor": 3.0},
        {"type": "move_stop", "stop_id": "1", "lon": 2.0, "lat": 41.0},
        {"type": "set_headway", "route_id": "4"},
    ],
)
def test_invalid_edits_are_rejected(raw: dict) -> None:
    with pytest.raises(ScenarioError):
        parse_edit(raw)


def test_unknown_ids_raise(model: Model) -> None:
    for raw in (
        {"type": "remove_route", "route_id": "zz"},
        {"type": "remove_stop", "stop_id": "zz"},
        {"type": "set_headway", "route_id": "zz", "headway": 600},
    ):
        with pytest.raises(ScenarioError, match="unknown"):
            apply(model, "weekday", parse_edits([raw]))


def test_lenient_mode_skips_impossible_edits(model: Model) -> None:
    edits = parse_edits([{"type": "remove_route", "route_id": "zz"}])
    sn = apply(model, "sunday", edits, strict=False)
    assert sn.changes.warnings and sn.state.timetable is model.baseline("sunday").timetable


def test_hash_and_round_trip() -> None:
    raw = [
        {"type": "set_headway", "route_id": "4", "headway": 300, "period": "peak"},
        {
            "type": "add_route",
            "route_id": "n",
            "stops": [{"stop_id": "1"}, {"lon": -1.64, "lat": 42.81, "name": "x"}],
            "waypoints": [[-1.64, 42.81], [-1.65, 42.82]],
            "headway": 600,
        },
    ]
    edits = parse_edits(raw)
    again = parse_edits([edit_to_dict(e) for e in edits])
    assert again == edits
    assert scenario_hash(edits) == scenario_hash(again)
    assert scenario_hash(edits) != scenario_hash(edits[::-1])
    assert scenario_hash(()) == scenario_hash(parse_edits(None))


def test_snap_path_and_nearby_stops(model: Model, base: Timetable) -> None:
    sp = snap_path(model.drive, [[-1.6450, 42.8170], [-1.6600, 42.8100], [-1.6765, 42.8010]])
    assert not sp.warnings
    assert 3000 < sp.length_m < 6000
    near = nearby_stops(base, sp.coords)
    assert len(near) >= 5
    offs = [o for _, o, _ in near]
    assert offs == sorted(offs)
    assert all(d <= 40 for _, _, d in near)
    # an unroutable leg falls back to a straight line with a warning
    far = snap_path(model.drive, [[-1.6450, 42.8170], [-1.95, 42.99]])
    assert far.warnings and len(far.coords) == 2
    with pytest.raises(ScenarioError):
        snap_path(model.drive, [[-1.6450, 42.8170]])


# ------------------------------------------------------------------ monotonicity


def test_more_service_never_hurts_less_never_helps(model: Model, evaluator: Evaluator) -> None:
    base = evaluator.baseline_summary

    def ev(raw: list[dict]) -> tuple[float, float]:
        r = evaluator.evaluate(apply(model, "weekday", parse_edits(raw)).state)
        return r.objective, r.mean_travel_time

    obj, t = ev([{"type": "scale_frequency", "route_id": "4", "factor": 2.0}])
    assert obj > base.objective and t < base.mean_travel_time
    obj, t = ev([{"type": "remove_route", "route_id": "4"}])
    assert obj < base.objective and t > base.mean_travel_time
    p = _main_pattern(model.baseline("weekday").timetable, "4")
    tt = model.baseline("weekday").timetable
    seq = [tt.stop_ids[s] for s in tt.pattern_stop_seq(p)]
    obj, t = ev([{"type": "speed_up", "route_id": "4", "stop_ids": seq, "factor": 1.3}])
    assert obj > base.objective and t < base.mean_travel_time


# ------------------------------------------------------- regressions from review


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "set_headway", "route_id": "4", "headway": "300"},
        {"type": "set_headway", "route_id": ["4"], "headway": 300},
        {"type": "move_stop", "stop_id": "1", "lon": "a", "lat": 42.8},
        {"type": "add_route", "route_id": "x", "stops": ["a", "b"], "headway": 600},
        {
            "type": "add_route",
            "route_id": "x",
            "stops": [{"stop_id": "1"}, {"stop_id": "5"}],
            "waypoints": [[]],
            "headway": 600,
        },
        {"type": "scale_frequency", "route_id": "4", "factor": float("nan")},
        {"type": "set_headway", "route_id": "4", "headway": True},
        "not an object",
    ],
)
def test_malformed_edits_raise_scenario_error(raw: object) -> None:
    with pytest.raises(ScenarioError):
        parse_edit(raw)  # type: ignore[arg-type]


def test_isochrone_after_stop_edits_uses_fresh_snap(model: Model, base: Timetable) -> None:
    """Derived timetables inherit ``extra``; the stop-snap cache must not go stale."""
    from vlab.access import isochrone as iso
    from vlab.model import Window

    centre = (-1.6440, 42.8169)
    iso.time_field(model, model.baseline("weekday"), centre, Window(), 1800)  # fills the cache
    p = _main_pattern(base, "4")
    seq = base.pattern_stop_seq(p)
    a, b = int(seq[5]), int(seq[6])
    added = apply(
        model,
        "weekday",
        parse_edits(
            [
                {
                    "type": "add_stop",
                    "stop_id": "new-iso",
                    "lon": float((base.stop_lon[a] + base.stop_lon[b]) / 2),
                    "lat": float((base.stop_lat[a] + base.stop_lat[b]) / 2),
                    "route_id": "4",
                    "direction": int(base.patterns[p].direction),
                    "after_stop_id": base.stop_ids[a],
                }
            ]
        ),
    ).state
    field = iso.time_field(model, added, centre, Window(), 1800)
    assert len(field.stop_time) == base.n_stops + 1
    moved = apply(
        model,
        "weekday",
        parse_edits(
            [{"type": "move_stop", "stop_id": base.stop_ids[a], "lon": -1.60, "lat": 42.78}]
        ),
    ).state
    snap = iso._stop_snap(model, moved)
    fresh = model.walk.snap(moved.timetable.stop_lon, moved.timetable.stop_lat)
    assert np.array_equal(snap[1], fresh.nodes)


def test_night_route_all_day_change_scales_overnight_copies(model: Model, base: Timetable) -> None:
    night = next(
        r.route_id
        for r in base.routes
        if r.kind == "night"
        and any(
            base.trip_prev_day[base.pattern_trips_ptr[p] : base.pattern_trips_ptr[p + 1]].any()
            for p in base.patterns_of_route(r.route_id)
        )
    )

    def spill(tt: Timetable) -> int:
        return sum(
            int(tt.trip_prev_day[tt.pattern_trips_ptr[p] : tt.pattern_trips_ptr[p + 1]].sum())
            for p in tt.patterns_of_route(night)
        )

    half = _run(model, [{"type": "scale_frequency", "route_id": night, "factor": 0.5}])
    assert spill(half) < spill(base)


def test_set_headway_is_accurate_across_routes(model: Model, base: Timetable) -> None:
    worst = 0.0
    for rid in ("2", "3", "9", "16", "20"):
        for period, target in (("all", 600), ("peak", 600), ("offpeak", 900)):
            if mean_headways(base, rid)[period] is None:
                continue
            tt = _run(
                model,
                [{"type": "set_headway", "route_id": rid, "headway": target, "period": period}],
            )
            got = mean_headways(tt, rid)[period]
            assert got is not None
            worst = max(worst, abs(got / target - 1))
    assert worst < 0.15


def test_small_factor_keeps_every_branch(model: Model, base: Timetable) -> None:
    tt = _run(model, [{"type": "scale_frequency", "route_id": "3", "factor": 0.1}])
    had = {base.patterns[p].key for p in base.patterns_of_route("3") if base.n_pattern_trips(p)}
    has = {tt.patterns[p].key for p in tt.patterns_of_route("3") if tt.n_pattern_trips(p)}
    assert {k.split("~")[0] for k in had} == {k.split("~")[0] for k in has}


def test_degenerate_new_route_is_rejected(model: Model) -> None:
    with pytest.raises(ScenarioError, match="200 m"):
        apply(
            model,
            "weekday",
            parse_edits(
                [
                    {
                        "type": "add_route",
                        "route_id": "tiny",
                        "stops": [
                            {"lon": -1.6440, "lat": 42.8169},
                            {"lon": -1.6441, "lat": 42.8169},
                        ],
                        "headway": 600,
                    }
                ]
            ),
        )
