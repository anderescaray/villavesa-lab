"""FastAPI application implementing docs/api.md."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse, Response
from pydantic import BaseModel, Field

from vlab.model.world import Model, Window
from vlab.scenario import Edit, ScenarioError, parse_edits
from vlab_api.service import ENGINE_LOCK, Service

log = logging.getLogger("vlab_api")

Day = Literal["weekday", "saturday", "sunday"]
LonLat = Annotated[list[float], Field(min_length=2, max_length=2)]
EditList = list[dict[str, Any]] | None


class WindowIn(BaseModel):
    day: Day = "weekday"
    start: int = Field(default=8 * 3600, ge=0, lt=30 * 3600)
    duration: int = Field(default=3600, ge=600, le=4 * 3600)

    def to_window(self) -> Window:
        return Window(self.day, self.start, self.duration)


class NetworkIn(BaseModel):
    scenario: EditList = None
    day: Day = "weekday"


class IsochroneIn(BaseModel):
    origin: LonLat
    window: WindowIn = Field(default_factory=WindowIn)
    cutoffs: list[Annotated[int, Field(ge=300, le=5400)]] = Field(
        default=[900, 1800, 2700], min_length=1, max_length=6
    )
    scenario: EditList = None
    mode: Literal["transit", "walk"] = "transit"


class JourneyIn(BaseModel):
    origin: LonLat
    destination: LonLat
    depart: int = Field(default=8 * 3600, ge=0, lt=30 * 3600)
    day: Day = "weekday"
    scenario: EditList = None


class AccessibilityIn(BaseModel):
    window: WindowIn = Field(default_factory=WindowIn)
    scenario: EditList = None
    threshold: int = Field(default=1800, ge=300, le=5400)


class SnapIn(BaseModel):
    waypoints: list[LonLat] = Field(min_length=2, max_length=60)


class EvaluateIn(BaseModel):
    scenario: list[dict[str, Any]]
    window: WindowIn = Field(default_factory=WindowIn)
    threshold: int = Field(default=1800, ge=300, le=5400)


class State:
    service: Service | None = None
    error: str | None = None
    started: float = 0.0


STATE = State()


def _load() -> None:
    try:
        t0 = time.perf_counter()
        data_dir = os.environ.get("VLAB_DATA_DIR")
        with ENGINE_LOCK:
            svc = Service(Model.load(Path(data_dir) if data_dir else None))
            svc.warm_up()
        STATE.service = svc
        log.info("engine ready in %.1f s", time.perf_counter() - t0)
    except Exception as exc:  # pragma: no cover - start-up failure path
        log.exception("engine failed to load")
        STATE.error = f"{type(exc).__name__}: {exc}"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    STATE.started = time.time()
    if STATE.service is None:
        if os.environ.get("VLAB_SYNC_LOAD") == "1":
            _load()
        else:
            threading.Thread(target=_load, name="vlab-load", daemon=True).start()
    yield


app = FastAPI(
    title="villavesa-lab API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


def svc() -> Service:
    if STATE.service is None:
        if STATE.error:
            raise HTTPException(500, f"engine failed to load: {STATE.error}")
        raise HTTPException(503, "engine is still loading; retry in a few seconds")
    return STATE.service


def edits_of(raw: EditList) -> tuple[Edit, ...]:
    try:
        return parse_edits(raw)
    except ScenarioError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.exception_handler(ScenarioError)
async def scenario_error(_: Request, exc: ScenarioError) -> ORJSONResponse:
    return ORJSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError) -> ORJSONResponse:
    return ORJSONResponse({"detail": str(exc)}, status_code=422)


# ----------------------------------------------------------------------------- meta


@app.get("/api/health")
def health() -> dict[str, Any]:
    status = "ok" if STATE.service is not None else ("error" if STATE.error else "loading")
    return {"status": status, "detail": STATE.error}


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    return svc().meta()


# -------------------------------------------------------------------------- network


@app.get("/api/network")
def network_get(day: Day = "weekday") -> dict[str, Any]:
    return svc().network((), day)


@app.post("/api/network")
def network_post(body: NetworkIn) -> dict[str, Any]:
    return svc().network(edits_of(body.scenario), body.day)


@app.get("/api/vehicles")
def vehicles_get(day: Day = "weekday") -> dict[str, Any]:
    return svc().vehicles((), day)


@app.post("/api/vehicles")
def vehicles_post(body: NetworkIn) -> dict[str, Any]:
    return svc().vehicles(edits_of(body.scenario), body.day)


# -------------------------------------------------------------------------- routing


@app.post("/api/isochrone")
def isochrone(body: IsochroneIn) -> dict[str, Any]:
    return svc().isochrone(
        (body.origin[0], body.origin[1]),
        body.window.to_window(),
        body.cutoffs,
        edits_of(body.scenario),
        body.mode,
    )


@app.post("/api/journey")
def journey(body: JourneyIn) -> dict[str, Any]:
    res = svc().journey(
        (body.origin[0], body.origin[1]),
        (body.destination[0], body.destination[1]),
        body.depart,
        body.day,
        edits_of(body.scenario),
    )
    if res is None:
        raise HTTPException(404, "no journey found between these points at this time")
    return res


# -------------------------------------------------------------------- accessibility


@app.post("/api/accessibility")
def accessibility(body: AccessibilityIn) -> dict[str, Any]:
    return svc().accessibility(body.window.to_window(), edits_of(body.scenario), body.threshold)


def _static(payload: bytes) -> Response:
    return Response(
        payload,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/zones")
def zones() -> Response:
    return _static(svc().zones_geojson())


@app.get("/api/sections")
def sections() -> Response:
    return _static(svc().sections_geojson())


@app.get("/api/pois")
def pois() -> Response:
    return _static(svc().pois())


# ------------------------------------------------------------------------ scenarios


@app.post("/api/scenario/snap")
def scenario_snap(body: SnapIn) -> dict[str, Any]:
    return svc().snap(body.waypoints)


@app.post("/api/scenario/evaluate")
def scenario_evaluate(body: EvaluateIn) -> dict[str, Any]:
    return svc().evaluate(edits_of(body.scenario), body.window.to_window(), body.threshold)
