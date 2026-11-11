"""Self-contained HTML report of a scenario (print-friendly: the browser's print
dialog produces the PDF). No external assets, no scripts."""

from __future__ import annotations

import html
from typing import Any

import numpy as np

STRINGS: dict[str, dict[str, str]] = {
    "es": {
        "subtitle": "Informe de escenario · red de transporte urbano comarcal de Pamplona",
        "window": "Periodo analizado",
        "weekday": "Laborable",
        "saturday": "Sábado",
        "sunday": "Domingo y festivo",
        "summary": "Resumen",
        "baseline": "Red actual",
        "scenario": "Escenario",
        "change": "Cambio",
        "fleet": "Flota en hora punta (buses)",
        "bus_hours": "Horas-bus al día",
        "km": "Kilómetros al día",
        "cost_day": "Coste de operación al día (EUR)",
        "cost_year": "Coste anual con amortización (EUR)",
        "mean_tt": "Tiempo medio de viaje puerta a puerta (min)",
        "access": "Índice de accesibilidad (red actual = 100)",
        "underserved": "Residentes sin acceso a algún destino esencial",
        "gain": "personas ganan acceso",
        "lose": "personas pierden acceso",
        "destinations": "Población que llega en {min} min o menos",
        "destination": "Destino",
        "changes": "Cambios propuestos",
        "no_changes": "El escenario no modifica la red actual.",
        "routes": "Líneas afectadas",
        "route": "Línea",
        "trips": "Expediciones",
        "headway": "Frecuencia punta (min)",
        "map": "Dónde cambia el tiempo de viaje",
        "map_note": "Cada celda es de 200 m. Azul: viajes más cortos; rojo: más largos. "
        "Solo celdas con residentes y un cambio superior a 30 s.",
        "faster": "más rápido",
        "slower": "más lento",
        "method": "Método y limitaciones",
        "warnings": "Avisos",
        "generated": "Generado con villavesa-lab",
        "hospital": "Hospitales",
        "health_centre": "Centros de salud",
        "university": "Universidades",
        "industrial_estate": "Polígonos industriales",
        "city_centre": "Centro de la ciudad",
        "secondary_school": "Institutos",
        "supermarket": "Supermercados",
        "e_set_headway": "Línea {route}: una expedición cada {min} min ({period})",
        "e_scale_frequency": "Línea {route}: frecuencia ×{factor}",
        "e_speed_up": "Prioridad bus en {n} tramos{route}: ×{factor} más rápido",
        "e_remove_stop": "Se suprime la parada {stop}",
        "e_move_stop": "Se desplaza la parada {stop}",
        "e_add_stop": "Nueva parada «{name}» en la línea {route}",
        "e_remove_route": "Se suprime la línea {route}",
        "e_add_route": "Nueva línea {route}: {n} paradas, cada {min} min",
        "p_all": "todo el día",
        "p_peak": "hora punta",
        "p_offpeak": "hora valle",
        "on_route": " de la línea {route}",
    },
    "en": {
        "subtitle": "Scenario report · Pamplona urban bus network",
        "window": "Analysis window",
        "weekday": "Weekday",
        "saturday": "Saturday",
        "sunday": "Sunday and holidays",
        "summary": "Summary",
        "baseline": "Today",
        "scenario": "Scenario",
        "change": "Change",
        "fleet": "Peak fleet (buses)",
        "bus_hours": "Bus-hours per day",
        "km": "Kilometres per day",
        "cost_day": "Operating cost per day (EUR)",
        "cost_year": "Yearly cost incl. capital (EUR)",
        "mean_tt": "Mean door-to-door travel time (min)",
        "access": "Accessibility index (today = 100)",
        "underserved": "Residents missing an essential destination",
        "gain": "people gain access",
        "lose": "people lose access",
        "destinations": "Population reaching each destination within {min} min",
        "destination": "Destination",
        "changes": "Proposed changes",
        "no_changes": "The scenario does not change today's network.",
        "routes": "Lines affected",
        "route": "Line",
        "trips": "Trips",
        "headway": "Peak headway (min)",
        "map": "Where travel time changes",
        "map_note": "Each cell is 200 m. Blue: shorter trips; red: longer. "
        "Only cells with residents and a change above 30 s.",
        "faster": "faster",
        "slower": "slower",
        "method": "Method and limitations",
        "warnings": "Warnings",
        "generated": "Generated with villavesa-lab",
        "hospital": "Hospitals",
        "health_centre": "Health centres",
        "university": "Universities",
        "industrial_estate": "Industrial estates",
        "city_centre": "City centre",
        "secondary_school": "Secondary schools",
        "supermarket": "Supermarkets",
        "e_set_headway": "Line {route}: a trip every {min} min ({period})",
        "e_scale_frequency": "Line {route}: frequency ×{factor}",
        "e_speed_up": "Bus priority on {n} segments{route}: ×{factor} faster",
        "e_remove_stop": "Stop {stop} removed",
        "e_move_stop": "Stop {stop} moved",
        "e_add_stop": "New stop “{name}” on line {route}",
        "e_remove_route": "Line {route} removed",
        "e_add_route": "New line {route}: {n} stops, every {min} min",
        "p_all": "all day",
        "p_peak": "peak",
        "p_offpeak": "off-peak",
        "on_route": " on line {route}",
    },
}

NOTES: dict[str, list[str]] = {
    "es": [
        "Los tiempos de viaje se calculan con un algoritmo RAPTOR propio sobre el horario "
        "oficial (GTFS), con acceso a pie por la red peatonal de OpenStreetMap, y son la media "
        "de las salidas cada 10 minutos del periodo analizado.",
        "La demanda es un modelo gravitatorio: no existe una matriz origen-destino pública.",
        "La población por celda de 200 m se estima repartiendo la de cada sección censal "
        "(INE 2024) según la superficie residencial del catastro.",
        "Los costes usan la tarifa del operador de la concesión anterior a 2024 (precios de "
        "2023): 43,15 EUR por hora-bus y 1,25 EUR por km, más 25.300 EUR por bus y año.",
        "No se modelan retrasos, ocupación ni tarifas.",
    ],
    "en": [
        "Travel times come from an in-house RAPTOR router on the official timetable (GTFS) "
        "with walking access on the OpenStreetMap pedestrian network, averaged over "
        "departures every 10 minutes of the analysis window.",
        "Demand is a gravity model: no public origin-destination matrix exists.",
        "Population per 200 m cell is estimated by spreading each census section (INE 2024) "
        "over residential floor area from the cadastre.",
        "Costs use the operator tariff of the pre-2024 concession (2023 prices): EUR 43.15 "
        "per bus-hour and EUR 1.25 per km, plus EUR 25,300 per bus and year.",
        "Delays, crowding and fares are not modelled.",
    ],
}

CSS = """
*{box-sizing:border-box}
body{font:13px/1.5 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#14171a;
margin:0;background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}
main{max-width:860px;margin:0 auto;padding:48px 40px 64px}
h1{font-size:26px;line-height:1.2;margin:0 0 4px;letter-spacing:-.02em;font-weight:650}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:#5b6570;font-weight:600;
margin:36px 0 10px;padding-bottom:6px;border-bottom:1px solid #e3e6ea}
.sub{color:#5b6570;margin:0}.meta{color:#5b6570;margin:14px 0 0;font-variant-numeric:tabular-nums}
.mark{display:inline-block;width:10px;height:10px;border-radius:2px;background:#d0142c;margin-right:8px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:7px 0;border-bottom:1px solid #eef0f2;text-align:right}
th:first-child,td:first-child{text-align:left}
th{font-weight:500;color:#5b6570;font-size:12px}
.pos{color:#0b6e4f}.neg{color:#b42318}.mut{color:#5b6570}
.kpis{display:flex;gap:32px;margin:18px 0 6px}
.kpi b{display:block;font-size:22px;font-weight:650;letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.kpi span{color:#5b6570;font-size:12px}
ul{margin:0;padding-left:18px}li{margin:3px 0}
.badge{display:inline-block;min-width:34px;text-align:center;border-radius:4px;padding:1px 6px;
font-size:11px;font-weight:600;color:#fff;background:#5b6570}
.legend{display:flex;gap:16px;color:#5b6570;font-size:12px;margin-top:6px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
footer{margin-top:40px;color:#8a939c;font-size:11px}
svg{width:100%;height:auto;border:1px solid #eef0f2;border-radius:6px;background:#fafbfc}
@media print{main{padding:0}h2{break-after:avoid}table,svg{break-inside:avoid}@page{margin:16mm}}
"""


def _fmt(v: float | None, digits: int = 0, lang: str = "es") -> str:
    if v is None:
        return "–"
    s = f"{v:,.{digits}f}"
    if lang == "es":
        s = s.replace(",", " ").replace(".", ",")
    return s


def _delta(v: float | None, digits: int, lang: str, good_when_negative: bool) -> str:
    if v is None:
        return '<td class="mut">–</td>'
    if abs(v) < 0.5 * 10**-digits:
        return '<td class="mut">0</td>'
    good = (v < 0) == good_when_negative
    sign = "+" if v > 0 else "−"
    return f'<td class="{"pos" if good else "neg"}">{sign}{_fmt(abs(v), digits, lang)}</td>'


def describe_edit(
    e: dict[str, Any], names: dict[str, str], stops: dict[str, str], t: dict[str, str]
) -> str:
    kind = e["type"]
    route = names.get(str(e.get("route_id")), str(e.get("short_name") or e.get("route_id") or ""))
    if kind == "set_headway":
        return t["e_set_headway"].format(
            route=route, min=_fmt(e["headway"] / 60, 1), period=t[f"p_{e.get('period', 'all')}"]
        )
    if kind == "scale_frequency":
        return t["e_scale_frequency"].format(route=route, factor=f"{e['factor']:g}")
    if kind == "speed_up":
        on = t["on_route"].format(route=route) if e.get("route_id") else ""
        return t["e_speed_up"].format(n=len(e["stop_ids"]) - 1, route=on, factor=f"{e['factor']:g}")
    if kind in ("remove_stop", "move_stop"):
        return t[f"e_{kind}"].format(stop=stops.get(str(e["stop_id"]), str(e["stop_id"])))
    if kind == "add_stop":
        return t["e_add_stop"].format(name=e.get("name") or e["stop_id"], route=route)
    if kind == "remove_route":
        return t["e_remove_route"].format(route=route)
    if kind == "add_route":
        return t["e_add_route"].format(
            route=e.get("short_name") or e["route_id"],
            n=len(e["stops"]),
            min=_fmt(e["headway"] / 60, 0),
        )
    return str(kind)


def _map_svg(
    lon: np.ndarray,
    lat: np.ndarray,
    population: np.ndarray,
    delta: list[float | None],
    paths: list[tuple[str, list[list[float]]]],
) -> str:
    """Small static map: network in grey, cells coloured by travel-time change."""
    d = np.array([np.nan if v is None else v for v in delta], dtype=np.float64)
    x0, x1 = float(lon.min()), float(lon.max())
    y0, y1 = float(lat.min()), float(lat.max())
    k = np.cos(np.radians((y0 + y1) / 2))
    w = 820.0
    scale = w / ((x1 - x0) * k)
    h = (y1 - y0) * scale

    def px(a: float, b: float) -> tuple[float, float]:
        return ((a - x0) * k * scale, (y1 - b) * scale)

    out = [f'<svg viewBox="0 0 {w:.0f} {h:.0f}" role="img">']
    for _, path in paths:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (px(p[0], p[1]) for p in path[::3]))
        out.append(f'<polyline points="{pts}" fill="none" stroke="#c9cfd6" stroke-width="0.8"/>')
    cell = max(200.0 * scale / 111_320.0, 2.2)
    show = np.flatnonzero(np.isfinite(d) & (np.abs(d) > 30) & (population > 0))
    for i in show[np.argsort(np.abs(d[show]))]:
        x, y = px(float(lon[i]), float(lat[i]))
        m = min(abs(d[i]) / 300.0, 1.0)
        base = (33, 102, 172) if d[i] < 0 else (178, 24, 43)
        col = tuple(round(255 - (255 - c) * (0.35 + 0.65 * m)) for c in base)
        out.append(
            f'<rect x="{x - cell / 2:.1f}" y="{y - cell / 2:.1f}" width="{cell:.1f}" '
            f'height="{cell:.1f}" fill="rgb({col[0]},{col[1]},{col[2]})"/>'
        )
    out.append("</svg>")
    return "".join(out)


def render(
    *,
    title: str,
    lang: str,
    window: dict[str, Any],
    threshold: int,
    evaluation: dict[str, Any],
    edits: list[dict[str, Any]],
    route_names: dict[str, str],
    route_colors: dict[str, str],
    stop_names: dict[str, str],
    zone_lon: np.ndarray,
    zone_lat: np.ndarray,
    population: np.ndarray,
    paths: list[tuple[str, list[list[float]]]],
    date: str,
) -> str:
    lang = lang if lang in STRINGS else "es"
    t = STRINGS[lang]
    b, s, d = evaluation["baseline"], evaluation["scenario"], evaluation["delta"]
    esc = html.escape

    def hhmm(sec: int) -> str:
        return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}"

    win = (
        f"{t[window['day']]} · {hhmm(window['start'])}–{hhmm(window['start'] + window['duration'])}"
    )
    idx_s = 100.0 * s["objective"] / b["objective"] if b["objective"] else None
    rows = [
        (t["fleet"], b["fleet"], s["fleet"], 0, True),
        (t["bus_hours"], b["bus_hours"], s["bus_hours"], 0, True),
        (t["km"], b["km"], s["km"], 0, True),
        (t["cost_day"], b["cost_eur_day"], s["cost_eur_day"], 0, True),
        (t["cost_year"], b["cost_eur_year"], s["cost_eur_year"], 0, True),
        (t["mean_tt"], b["mean_travel_time"] / 60, s["mean_travel_time"] / 60, 1, True),
        (t["access"], 100.0, idx_s, 1, False),
        (t["underserved"], b["underserved_population"], s["underserved_population"], 0, True),
    ]
    summary = "".join(
        f"<tr><td>{esc(label)}</td><td>{_fmt(bv, dg, lang)}</td><td>{_fmt(sv, dg, lang)}</td>"
        f"{_delta(None if sv is None else sv - bv, dg, lang, neg_good)}</tr>"
        for label, bv, sv, dg, neg_good in rows
    )
    cats = "".join(
        f"<tr><td>{esc(t.get(c, c))}</td>"
        f"<td>{_fmt(100 * b['categories'][c]['share_within'], 1, lang)} %</td>"
        f"<td>{_fmt(100 * s['categories'][c]['share_within'], 1, lang)} %</td>"
        f"{_delta(d['categories'][c]['pop_within'], 0, lang, False)}</tr>"
        for c in b["categories"]
    )
    if edits:
        changes = (
            "<ul>"
            + "".join(
                f"<li>{esc(describe_edit(e, route_names, stop_names, t))}</li>" for e in edits
            )
            + "</ul>"
        )
    else:
        changes = f'<p class="mut">{esc(t["no_changes"])}</p>'
    routes = ""
    if evaluation["routes"]:
        body = ""
        for r in evaluation["routes"]:
            hw = [None if v is None else v / 60 for v in r["headway_peak"]]
            name = route_names.get(r["id"], r["id"])
            color = route_colors.get(r["id"], "#5b6570")
            body += (
                f'<tr><td><span class="badge" style="background:{esc(color)}">{esc(name)}</span></td>'
                f"<td>{r['trips'][0]} → {r['trips'][1]}</td>"
                f"<td>{_fmt(hw[0], 1, lang)} → {_fmt(hw[1], 1, lang)}</td>"
                f"<td>{r['fleet'][0]} → {r['fleet'][1]}</td>"
                f"<td>{_fmt(r['bus_hours'][0], 0, lang)} → {_fmt(r['bus_hours'][1], 0, lang)}</td></tr>"
            )
        routes = (
            f"<h2>{esc(t['routes'])}</h2><table><tr><th>{esc(t['route'])}</th>"
            f"<th>{esc(t['trips'])}</th><th>{esc(t['headway'])}</th><th>{esc(t['fleet'])}</th>"
            f"<th>{esc(t['bus_hours'])}</th></tr>{body}</table>"
        )
    warn = ""
    if evaluation.get("warnings"):
        warn = (
            f"<h2>{esc(t['warnings'])}</h2><ul>"
            + "".join(f"<li>{esc(w)}</li>" for w in evaluation["warnings"])
            + "</ul>"
        )
    svg = _map_svg(zone_lon, zone_lat, population, evaluation["zones"]["delta_time"], paths)
    notes = "".join(f"<li>{esc(n)}</li>" for n in NOTES[lang])
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head><body><main>
<p class="sub"><span class="mark"></span>villavesa lab</p>
<h1>{esc(title)}</h1>
<p class="sub">{esc(t["subtitle"])}</p>
<p class="meta">{esc(t["window"])}: {esc(win)} · {esc(date)}</p>
<div class="kpis">
<div class="kpi"><b>{_fmt(d["people_gaining"], 0, lang)}</b><span>{esc(t["gain"])}</span></div>
<div class="kpi"><b>{_fmt(d["people_losing"], 0, lang)}</b><span>{esc(t["lose"])}</span></div>
<div class="kpi"><b>{"+" if d["fleet"] > 0 else ""}{d["fleet"]}</b><span>{esc(t["fleet"])}</span></div>
</div>
<h2>{esc(t["summary"])}</h2>
<table><tr><th></th><th>{esc(t["baseline"])}</th><th>{esc(t["scenario"])}</th>
<th>{esc(t["change"])}</th></tr>{summary}</table>
<h2>{esc(t["destinations"].format(min=threshold // 60))}</h2>
<table><tr><th>{esc(t["destination"])}</th><th>{esc(t["baseline"])}</th>
<th>{esc(t["scenario"])}</th><th>{esc(t["change"])}</th></tr>{cats}</table>
<h2>{esc(t["changes"])}</h2>{changes}
{routes}
<h2>{esc(t["map"])}</h2>{svg}
<div class="legend"><span><i class="sw" style="background:#2166ac"></i>{esc(t["faster"])}</span>
<span><i class="sw" style="background:#b2182b"></i>{esc(t["slower"])}</span>
<span>{esc(t["map_note"])}</span></div>
{warn}
<h2>{esc(t["method"])}</h2><ul>{notes}</ul>
<footer>{esc(t["generated"])} · {esc(date)}</footer>
</main></body></html>"""
