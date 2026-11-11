"""HTTP API tests against the real model (contract in docs/api.md)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vlab.model import Model
from vlab_api import main
from vlab_api.service import LRU, Service, num

CENTRE = [-1.6440, 42.8169]
L4_FASTER = [{"type": "set_headway", "route_id": "4", "headway": 240}]


@pytest.fixture(scope="module")
def client(model: Model) -> Iterator[TestClient]:
    main.STATE.service = Service(model)
    main.STATE.error = None
    with TestClient(main.app) as c:
        yield c
    main.STATE.service = None


def post(client: TestClient, path: str, body: dict[str, Any], status: int = 200) -> Any:
    r = client.post(path, json=body)
    assert r.status_code == status, r.text
    return r.json()


def test_health_and_meta(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    m = client.get("/api/meta").json()
    assert m["feed"]["agency"] == "TCC Pamplona"
    assert m["feed"]["start_date"] == "2026-11-10" and m["feed"]["end_date"] == "2026-11-30"
    assert m["feed"]["n_routes"] == 54 and m["feed"]["n_stops"] == 563
    assert set(m["days"]) == {"weekday", "saturday", "sunday"}
    assert 350_000 < m["population"] < 390_000
    assert len(m["bbox"]) == 4 and m["bbox"][0] < m["center"][0] < m["bbox"][2]
    assert {c["id"] for c in m["poi_categories"]} >= {"hospital", "health_centre", "university"}
    assert m["cost_params"]["eur_per_bus_hour"] == 43.15
    assert {n["key"] for n in m["data_notes"]} >= {"demand_gravity", "cost_tariff"}


def test_openapi_is_served(client: TestClient) -> None:
    spec = client.get("/api/openapi.json").json()
    assert "/api/scenario/evaluate" in spec["paths"]


def test_network_baseline_shape(client: TestClient) -> None:
    n = client.get("/api/network", params={"day": "weekday"}).json()
    assert len(n["routes"]) > 20 and len(n["stops"]) > 500
    r = next(x for x in n["routes"] if x["id"] == "4")
    assert r["short_name"] == "L04" and r["kind"] == "day" and r["color"].startswith("#")
    assert not r["modified"] and not r["added"]
    for p in r["patterns"]:
        assert len(p["stop_ids"]) == len(p["stop_offsets"]) >= 2
        assert p["stop_offsets"][0] == 0 and p["stop_offsets"] == sorted(p["stop_offsets"])
        assert len(p["path"]) > 10 and len(p["path"][0]) == 2
    st = r["stats"]
    assert st["trips"] > 100 and st["fleet"] > 5 and 8 < st["speed_kmh"] < 20
    assert st["first_dep"] < st["last_dep"]
    assert st["headway_peak"] and st["headway_offpeak"]
    t = n["totals"]
    assert 140 <= t["fleet"] <= 185 and t["trips"] == sum(x["stats"]["trips"] for x in n["routes"])
    s = n["stops"][0]
    assert {"id", "name", "lon", "lat", "routes", "boardings_weight", "removed"} <= set(s)
    # weekend has less service
    sun = client.get("/api/network", params={"day": "sunday"}).json()
    assert sun["totals"]["trips"] < t["trips"]
    assert client.get("/api/network", params={"day": "friday"}).status_code == 422


def test_network_with_scenario_flags_changes(client: TestClient) -> None:
    base = client.get("/api/network").json()
    n = post(client, "/api/network", {"scenario": [{"type": "remove_route", "route_id": "4"}]})
    assert "4" not in {r["id"] for r in n["routes"]}
    assert n["removed_routes"] == ["4"]
    assert n["totals"]["fleet"] < base["totals"]["fleet"]
    n = post(client, "/api/network", {"scenario": L4_FASTER})
    r = next(x for x in n["routes"] if x["id"] == "4")
    assert r["modified"] and r["stats"]["headway"] == pytest.approx(240, rel=0.08)


def test_vehicles_payload(client: TestClient) -> None:
    v = client.get("/api/vehicles").json()
    assert len(v["trips"]) > 3000
    shapes = {s["id"]: s for s in v["shapes"]}
    for trip in v["trips"][:: len(v["trips"]) // 50]:
        sh = shapes[trip["shape"]]
        assert len(trip["t"]) == len(trip["d"]) >= 2
        assert trip["t"] == sorted(trip["t"]) and trip["d"] == sorted(trip["d"])
        assert trip["d"][0] == 0 and trip["d"][-1] <= sh["cum_m"][-1] + 1.0
        assert len(sh["path"]) == len(sh["cum_m"])
    starts = [t["t"][0] for t in v["trips"]]
    assert starts == sorted(starts)
    v2 = post(client, "/api/vehicles", {"scenario": [{"type": "remove_route", "route_id": "4"}]})
    assert len(v2["trips"]) < len(v["trips"]) and all(t["route"] != "4" for t in v2["trips"])


def test_isochrone(client: TestClient) -> None:
    r = post(client, "/api/isochrone", {"origin": CENTRE})
    iso = r["isochrones"]
    assert [i["cutoff"] for i in iso] == [900, 1800, 2700]
    assert iso[0]["population"] < iso[1]["population"] < iso[2]["population"]
    assert iso[0]["area_km2"] < iso[1]["area_km2"] < iso[2]["area_km2"]
    assert iso[1]["population"] > 150_000  # most of the city is within 30 min of the centre
    assert iso[2]["pois"]["hospital"] >= 2 and iso[0]["pois"]["city_centre"] == 1
    assert iso[0]["geometry"]["type"] == "MultiPolygon" and iso[0]["geometry"]["coordinates"]
    assert r["reached_stops"] and r["reached_stops"][0]["time"] <= r["reached_stops"][-1]["time"]
    walk = post(client, "/api/isochrone", {"origin": CENTRE, "mode": "walk", "cutoffs": [1800]})
    assert walk["isochrones"][0]["population"] < iso[1]["population"]
    assert not walk["reached_stops"]
    post(client, "/api/isochrone", {"origin": [-1.95, 42.99]}, 422)
    post(client, "/api/isochrone", {"origin": [1]}, 422)
    post(client, "/api/isochrone", {"origin": CENTRE, "cutoffs": [10]}, 422)


def test_journey(client: TestClient) -> None:
    j = post(client, "/api/journey", {"origin": [-1.61, 42.835], "destination": [-1.663, 42.805]})
    assert j["arrive"] - j["depart"] == j["duration"] > 600
    assert {leg["mode"] for leg in j["legs"]} == {"walk", "bus"}
    bus = next(leg for leg in j["legs"] if leg["mode"] == "bus")
    assert bus["route"] and bus["from_stop"] and bus["to_stop"] and len(bus["path"]) > 2
    post(client, "/api/journey", {"origin": CENTRE, "destination": [-1.95, 42.99]}, 404)


def test_accessibility(client: TestClient) -> None:
    a = post(client, "/api/accessibility", {})
    cats = {c["id"]: c for c in a["categories"]}
    assert cats["health_centre"]["share_within"] > cats["hospital"]["share_within"] > 0.4
    assert cats["hospital"]["pop_within"] <= a["population"]
    assert len(cats["hospital"]["curve"]) == 12
    z = a["zones"]
    n = len(z["id"])
    assert (
        n == len(z["population"]) == len(z["jobs_30"]) == len(z["income"]) == len(z["section_id"])
    )
    assert all(len(v) == n for v in z["time"].values())
    assert None in z["time"]["hospital"]  # some zones cannot reach a hospital
    assert [q["q"] for q in a["equity"]["quintiles"]] == [1, 2, 3, 4, 5]
    assert set(a["equity"]["concentration_index"]) == set(cats)
    assert a["summary"]["underserved_population"] > 0 and a["summary"]["mean_travel_time"] > 600
    wide = post(client, "/api/accessibility", {"threshold": 2700})
    assert wide["summary"]["underserved_population"] < a["summary"]["underserved_population"]
    sat = post(client, "/api/accessibility", {"window": {"day": "sunday", "start": 36000}})
    assert sat["window"]["day"] == "sunday"
    post(client, "/api/accessibility", {"threshold": 5}, 422)
    post(client, "/api/accessibility", {"window": {"day": "someday"}}, 422)


def test_static_layers(client: TestClient) -> None:
    z = client.get("/api/zones")
    assert "max-age" in z.headers["cache-control"]
    zj = z.json()
    assert zj["type"] == "FeatureCollection" and len(zj["features"]) > 1500
    assert zj["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    s = client.get("/api/sections").json()
    assert len(s["features"]) > 200 and "income_per_capita" in s["features"][0]["properties"]
    p = client.get("/api/pois").json()["pois"]
    assert {"id", "category", "name", "lon", "lat"} <= set(p[0]) and len(p) > 200


def test_snap(client: TestClient) -> None:
    r = post(
        client,
        "/api/scenario/snap",
        {"waypoints": [[-1.645, 42.817], [-1.66, 42.81], [-1.6765, 42.801]]},
    )
    assert 3000 < r["length_m"] < 6000 and len(r["path"]) > 20 and r["nearby_stops"]
    assert {"id", "name", "offset_m", "distance_m"} <= set(r["nearby_stops"][0])
    post(client, "/api/scenario/snap", {"waypoints": [[-1.645, 42.817]]}, 422)


def test_evaluate_round_trip_and_cache(client: TestClient) -> None:
    e = post(client, "/api/scenario/evaluate", {"scenario": L4_FASTER})
    assert e["valid"] and e["routes"][0]["id"] == "4"
    d = e["delta"]
    assert d["fleet"] > 0 and d["bus_hours"] > 0 and d["cost_eur_year"] > d["cost_eur_day"] > 0
    assert d["mean_travel_time"] < 0 and d["objective"] > 0
    assert d["people_gaining"] > d["people_losing"] >= 0
    assert e["scenario"]["fleet"] - e["baseline"]["fleet"] == d["fleet"]
    assert set(e["baseline"]["categories"]) == set(d["categories"])
    n = len(e["zones"]["id"])
    assert len(e["zones"]["delta_time"]) == len(e["zones"]["delta_jobs_30"]) == n
    assert e["routes"][0]["fleet"][1] > e["routes"][0]["fleet"][0]
    again = post(client, "/api/scenario/evaluate", {"scenario": L4_FASTER})
    assert again["delta"] == d and again["elapsed_ms"] < 500
    empty = post(client, "/api/scenario/evaluate", {"scenario": []})
    assert empty["delta"]["fleet"] == 0 and empty["delta"]["people_gaining"] == 0


@pytest.mark.parametrize(
    "edit",
    [
        {"type": "scale_frequency", "route_id": "2", "factor": 1.5},
        {"type": "remove_route", "route_id": "23"},
        {"type": "remove_stop", "stop_id": "5"},
        {"type": "move_stop", "stop_id": "5", "lon": -1.6630, "lat": 42.8053},
        {
            "type": "add_route",
            "route_id": "new-A",
            "short_name": "A",
            "stops": [
                {"lon": -1.61, "lat": 42.835},
                {"stop_id": "5"},
                {"lon": -1.6765, "lat": 42.801},
            ],
            "headway": 900,
        },
    ],
)
def test_every_edit_type_evaluates(client: TestClient, edit: dict[str, Any]) -> None:
    e = post(client, "/api/scenario/evaluate", {"scenario": [edit]})
    assert e["valid"] and e["elapsed_ms"] < 20_000
    n = post(client, "/api/network", {"scenario": [edit]})
    assert n["routes"]


def test_scenario_errors_are_422_with_detail(client: TestClient) -> None:
    for scenario in (
        [{"type": "remove_route", "route_id": "zz"}],
        [{"type": "set_headway", "route_id": "4", "headway": 5}],
        [{"type": "teleport"}],
    ):
        r = post(client, "/api/scenario/evaluate", {"scenario": scenario}, 422)
        assert isinstance(r["detail"], str) and r["detail"]


def test_not_ready_returns_503(client: TestClient) -> None:
    saved = main.STATE.service
    main.STATE.service = None
    try:
        r = client.get("/api/meta")
        assert r.status_code == 503 and "loading" in r.json()["detail"]
        assert client.get("/api/health").json()["status"] == "loading"
        main.STATE.error = "boom"
        assert client.get("/api/meta").status_code == 500
    finally:
        main.STATE.service = saved
        main.STATE.error = None


def test_concurrent_requests_are_safe(client: TestClient) -> None:
    """Sync endpoints run in a thread pool; the engine must tolerate that."""
    from concurrent.futures import ThreadPoolExecutor

    def call(i: int) -> int:
        body = {"origin": [CENTRE[0] + 0.002 * i, CENTRE[1]], "cutoffs": [900]}
        return client.post("/api/isochrone", json=body).status_code

    with ThreadPoolExecutor(6) as pool:
        assert list(pool.map(call, range(12))) == [200] * 12


def test_helpers() -> None:
    assert num(float("nan")) is None and num(float("inf")) is None and num(None) is None
    assert num(1.26, 1) == 1.3
    cache = LRU(2)
    calls = []
    for k in (1, 2, 1, 3, 2):
        cache.get(k, lambda k=k: calls.append(k) or k)
    assert calls == [1, 2, 3, 2] and cache.hits == 1


# ------------------------------------------------------------- optimizer + report


def _wait(client: TestClient, job_id: str, timeout_s: float = 240.0) -> dict[str, Any]:
    import time

    t0 = time.time()
    while time.time() - t0 < timeout_s:
        j = client.get(f"/api/optimize/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.5)
    raise AssertionError("optimizer job did not finish")


def test_optimize_job_improves_accessibility_within_budget(client: TestClient) -> None:
    job_id = post(client, "/api/optimize", {"moves": ["frequency"], "time_limit_s": 30})["job_id"]
    first = client.get(f"/api/optimize/{job_id}").json()
    assert first["status"] in ("queued", "running", "done") and 0 <= first["progress"] <= 1
    j = _wait(client, job_id)
    assert j["status"] == "done", j["error"]
    assert j["progress"] == 1.0 and j["log"] and j["history"]
    res = j["result"]
    assert res["objective"]["optimized"] > res["objective"]["baseline"]
    assert res["budget"]["used"] <= res["budget"]["value"]
    ev = res["evaluation"]
    assert ev["delta"]["fleet"] <= 0 and ev["delta"]["objective"] > 0
    assert all(e["type"] == "scale_frequency" for e in res["scenario"])
    assert res["explanation"] and {e["text_key"] for e in res["explanation"]} <= {
        "frequency_up",
        "frequency_down",
    }
    # the proposal is directly usable in every other endpoint
    net = post(client, "/api/network", {"scenario": res["scenario"]})
    assert any(r["modified"] for r in net["routes"])


def test_tradeoff_curve_is_monotone(client: TestClient) -> None:
    base = client.get("/api/network").json()["totals"]["fleet"]
    values = [base - 20, base, base + 20]
    job_id = post(client, "/api/optimize/tradeoff", {"values": values})["job_id"]
    j = _wait(client, job_id)
    assert j["status"] == "done", j["error"]
    pts = j["result"]["points"]
    assert [p["budget"] for p in pts] == values
    assert all(p["used"] <= p["budget"] for p in pts)
    objs = [p["objective"] for p in pts]
    assert objs == sorted(objs)
    assert pts[1]["objective"] >= j["result"]["baseline"]["objective"]


def test_optimize_validation_and_unknown_job(client: TestClient) -> None:
    post(client, "/api/optimize", {"moves": []}, 422)
    post(client, "/api/optimize", {"moves": ["teleport"]}, 422)
    post(client, "/api/optimize", {"base_scenario": [{"type": "nope"}]}, 422)
    assert client.get("/api/optimize/nope").status_code == 404


def test_report_html(client: TestClient) -> None:
    for lang, word in (("es", "Resumen"), ("en", "Summary")):
        r = client.post(
            "/api/report",
            json={"scenario": L4_FASTER, "lang": lang, "title": "Refuerzo <L4>"},
        )
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        page = r.text
        assert word in page and "Refuerzo &lt;L4&gt;" in page and "<svg" in page
        assert "<script" not in page and "L04" in page
    empty = client.post("/api/report", json={"scenario": []})
    assert empty.status_code == 200 and "no modifica" in empty.text
