"""Typed scenario edits (the wire format is documented in docs/api.md)."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from typing import Any, ClassVar, Literal

Period = Literal["all", "peak", "offpeak"]

MIN_HEADWAY_S = 120
MAX_HEADWAY_S = 7200
MIN_FACTOR = 0.1
MAX_FACTOR = 5.0
MAX_SPEED_FACTOR = 2.0


class ScenarioError(ValueError):
    """An edit is invalid (unknown id, out-of-range value, impossible operation)."""


@dataclass(frozen=True)
class SetHeadway:
    type: ClassVar[str] = "set_headway"
    route_id: str
    headway: int
    period: Period = "all"

    def validate(self) -> None:
        if not MIN_HEADWAY_S <= self.headway <= MAX_HEADWAY_S:
            raise ScenarioError(
                f"headway must be between {MIN_HEADWAY_S} and {MAX_HEADWAY_S} s, got {self.headway}"
            )
        _check_period(self.period)


@dataclass(frozen=True)
class ScaleFrequency:
    type: ClassVar[str] = "scale_frequency"
    route_id: str
    factor: float
    period: Period = "all"

    def validate(self) -> None:
        if not MIN_FACTOR <= self.factor <= MAX_FACTOR:
            raise ScenarioError(f"factor must be between {MIN_FACTOR} and {MAX_FACTOR}")
        _check_period(self.period)


@dataclass(frozen=True)
class SpeedUp:
    type: ClassVar[str] = "speed_up"
    stop_ids: tuple[str, ...]
    factor: float
    route_id: str | None = None

    def validate(self) -> None:
        if len(self.stop_ids) < 2:
            raise ScenarioError("speed_up needs at least two consecutive stops")
        if not 1.0 <= self.factor <= MAX_SPEED_FACTOR:
            raise ScenarioError(f"speed factor must be between 1.0 and {MAX_SPEED_FACTOR}")


@dataclass(frozen=True)
class RemoveStop:
    type: ClassVar[str] = "remove_stop"
    stop_id: str
    route_id: str | None = None

    def validate(self) -> None:
        return None


@dataclass(frozen=True)
class MoveStop:
    type: ClassVar[str] = "move_stop"
    stop_id: str
    lon: float
    lat: float

    def validate(self) -> None:
        _check_lonlat(self.lon, self.lat)


@dataclass(frozen=True)
class AddStop:
    type: ClassVar[str] = "add_stop"
    stop_id: str
    lon: float
    lat: float
    route_id: str
    after_stop_id: str
    direction: int = 0
    name: str = ""

    def validate(self) -> None:
        _check_lonlat(self.lon, self.lat)
        if not self.stop_id:
            raise ScenarioError("add_stop needs a stop_id")


@dataclass(frozen=True)
class RemoveRoute:
    type: ClassVar[str] = "remove_route"
    route_id: str

    def validate(self) -> None:
        return None


@dataclass(frozen=True)
class RouteStop:
    """A stop of a new route: an existing ``stop_id`` or a new point."""

    stop_id: str | None = None
    lon: float | None = None
    lat: float | None = None
    name: str = ""


@dataclass(frozen=True)
class AddRoute:
    type: ClassVar[str] = "add_route"
    route_id: str
    stops: tuple[RouteStop, ...]
    headway: int
    short_name: str = ""
    color: str = "#1F6FEB"
    waypoints: tuple[tuple[float, float], ...] = ()
    bidirectional: bool = True
    speed_kmh: float | None = None
    first_dep: int = 6 * 3600 + 1800
    last_dep: int = 22 * 3600 + 1800

    def validate(self) -> None:
        if not self.route_id:
            raise ScenarioError("add_route needs a route_id")
        if len(self.stops) < 2:
            raise ScenarioError("a new route needs at least two stops")
        if not MIN_HEADWAY_S <= self.headway <= MAX_HEADWAY_S:
            raise ScenarioError(
                f"headway must be between {MIN_HEADWAY_S} and {MAX_HEADWAY_S} s, got {self.headway}"
            )
        if self.speed_kmh is not None and not 5.0 <= self.speed_kmh <= 60.0:
            raise ScenarioError("speed_kmh must be between 5 and 60")
        if not 0 <= self.first_dep < self.last_dep <= 30 * 3600:
            raise ScenarioError("invalid service span")
        for s in self.stops:
            if s.stop_id is None:
                if s.lon is None or s.lat is None:
                    raise ScenarioError("a route stop needs a stop_id or lon/lat")
                _check_lonlat(s.lon, s.lat)
        for lon, lat in self.waypoints:
            _check_lonlat(lon, lat)


Edit = (
    SetHeadway | ScaleFrequency | SpeedUp | RemoveStop | MoveStop | AddStop | RemoveRoute | AddRoute
)

_TYPES: dict[str, type[Any]] = {
    c.type: c
    for c in (
        SetHeadway,
        ScaleFrequency,
        SpeedUp,
        RemoveStop,
        MoveStop,
        AddStop,
        RemoveRoute,
        AddRoute,
    )
}


def _check_period(p: str) -> None:
    if p not in ("all", "peak", "offpeak"):
        raise ScenarioError(f"unknown period {p!r}")


def _check_lonlat(lon: float, lat: float) -> None:
    if not (-2.2 <= lon <= -1.1 and 42.5 <= lat <= 43.2):
        raise ScenarioError(f"coordinates ({lon}, {lat}) are outside the study region")


_NUMERIC = {
    "headway": int,
    "factor": float,
    "lon": float,
    "lat": float,
    "direction": int,
    "speed_kmh": float,
    "first_dep": int,
    "last_dep": int,
}
_STRINGS = ("route_id", "stop_id", "after_stop_id", "name", "short_name", "color", "period")


def _number(name: str, value: Any, kind: type) -> Any:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ScenarioError(f"{name} must be a number, got {value!r}")
    if kind is int:
        if float(value) != int(value):
            raise ScenarioError(f"{name} must be a whole number, got {value!r}")
        return int(value)
    return float(value)


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    for k, kind in _NUMERIC.items():
        if k in data:
            data[k] = _number(k, data[k], kind)
    for k in _STRINGS:
        if k in data and not isinstance(data[k], str):
            raise ScenarioError(f"{k} must be a string, got {data[k]!r}")
    return data


def parse_edit(raw: Mapping[str, Any]) -> Edit:
    """Build a validated edit from its wire dict. Any malformed input raises
    :class:`ScenarioError` (never a bare ``TypeError``/``KeyError``)."""
    if not isinstance(raw, Mapping):
        raise ScenarioError(f"an edit must be an object, got {type(raw).__name__}")
    kind = raw.get("type")
    cls = _TYPES.get(str(kind))
    if cls is None:
        raise ScenarioError(f"unknown edit type {kind!r}")
    names = {f.name for f in fields(cls)}
    data = _clean({k: v for k, v in raw.items() if k in names and v is not None})
    try:
        if cls is SpeedUp:
            ids = data.get("stop_ids", ())
            if not isinstance(ids, list | tuple) or not all(isinstance(s, str) for s in ids):
                raise ScenarioError("stop_ids must be a list of stop ids")
            data["stop_ids"] = tuple(ids)
        if cls is AddRoute:
            stops = data.get("stops", ())
            if not isinstance(stops, list | tuple) or not all(
                isinstance(s, Mapping) for s in stops
            ):
                raise ScenarioError("stops must be a list of objects")
            data["stops"] = tuple(
                RouteStop(
                    **_clean(
                        {
                            k: v
                            for k, v in s.items()
                            if k in ("stop_id", "lon", "lat", "name") and v is not None
                        }
                    )
                )
                for s in stops
            )
            data["waypoints"] = tuple(
                (_number("waypoint", w[0], float), _number("waypoint", w[1], float))
                for w in data.get("waypoints", ())
            )
            if not isinstance(data.get("bidirectional", True), bool):
                raise ScenarioError("bidirectional must be true or false")
        edit: Edit = cls(**data)
        edit.validate()
    except ScenarioError:
        raise
    except (TypeError, AttributeError, IndexError, KeyError, ValueError) as exc:
        raise ScenarioError(f"invalid {kind} edit: {exc}") from exc
    return edit


def parse_edits(raw: Iterable[Mapping[str, Any]] | None) -> tuple[Edit, ...]:
    return tuple(parse_edit(r) for r in (raw or ()))


def edit_to_dict(edit: Edit) -> dict[str, Any]:
    d = asdict(edit)
    out: dict[str, Any] = {"type": edit.type}
    for k, v in d.items():
        if isinstance(v, tuple):
            v = [list(x) if isinstance(x, tuple) else x for x in v]
        out[k] = v
    return out


def scenario_hash(edits: Sequence[Edit]) -> str:
    """Stable hash of an edit list (order matters: edits are applied in sequence)."""
    payload = json.dumps([edit_to_dict(e) for e in edits], sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode(), usedforsecurity=False).hexdigest()[:20]


@dataclass
class ChangeLog:
    """What a scenario touched, for the UI."""

    modified_routes: set[str] = field(default_factory=set)
    added_routes: set[str] = field(default_factory=set)
    removed_routes: set[str] = field(default_factory=set)
    modified_stops: set[str] = field(default_factory=set)
    added_stops: set[str] = field(default_factory=set)
    removed_stops: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
