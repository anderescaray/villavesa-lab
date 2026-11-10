#!/usr/bin/env node
/**
 * MOCK API fixture builder (temporary — delete `web/mocks/` once the real backend lands).
 *
 * Reads the official TUC Pamplona GTFS (`data/raw/gtfs_tuc_pamplona.zip`) and writes JSON
 * fixtures that follow docs/api.md for:
 *   GET  /api/meta
 *   GET  /api/network?day=…      (network-<day>.json)
 *   POST /api/vehicles {day}     (vehicles-<day>.json)
 * plus `graph.json`, a compact stop/pattern graph used by the mock isochrone handler.
 *
 * Routes, colours, stops, shapes and trips are the genuine timetable of the representative
 * service dates. Derived stats (fleet, bus-hours, cost) are simple estimates computed here and
 * are NOT the engine's numbers. Population and POIs are placeholders (see data_notes).
 *
 * Usage: node mocks/build-fixtures.mjs [path/to/gtfs.zip]
 */
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { unzipSync, strFromU8 } from 'fflate';

const here = dirname(fileURLToPath(import.meta.url));
const zipPath = resolve(process.argv[2] ?? resolve(here, '../../data/raw/gtfs_tuc_pamplona.zip'));
const outDir = resolve(here, 'fixtures');

const DAYS = { weekday: '2026-11-11', saturday: '2026-11-14', sunday: '2026-11-15' };
const PEAK = [7 * 3600, 9.5 * 3600];
const OFFPEAK = [10 * 3600, 13 * 3600];

// ---------------------------------------------------------------- CSV
function parseCsv(text) {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else inQuotes = false;
      } else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ',') {
      row.push(field);
      field = '';
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field);
      field = '';
      if (row.length > 1 || row[0] !== '') rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== '' || row.length) {
    row.push(field);
    rows.push(row);
  }
  const header = rows.shift().map((h) => h.trim());
  return { header, rows, col: (name) => header.indexOf(name) };
}

/** Fast line-based parser for the 70 MB stop_times.txt (no quoted fields there). */
function* simpleLines(text) {
  let start = text.charCodeAt(0) === 0xfeff ? 1 : 0;
  while (start < text.length) {
    let end = text.indexOf('\n', start);
    if (end === -1) end = text.length;
    let line = text.slice(start, end);
    if (line.endsWith('\r')) line = line.slice(0, -1);
    if (line) yield line;
    start = end + 1;
  }
}

const hms = (s) => {
  const [h, m, sec] = s.split(':').map(Number);
  return h * 3600 + m * 60 + (sec || 0);
};

// ---------------------------------------------------------------- geometry
const LAT0 = 42.81;
const MX = 111320 * Math.cos((LAT0 * Math.PI) / 180);
const MY = 110540;
const toXY = ([lon, lat]) => [lon * MX, lat * MY];
function haversine(a, b) {
  const R = 6371008.8;
  const toRad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * toRad;
  const dLon = (b[0] - a[0]) * toRad;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a[1] * toRad) * Math.cos(b[1] * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

function projectOnSegment(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  let t = len2 > 0 ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  const x = a[0] + t * dx;
  const y = a[1] + t * dy;
  return { t, dist: Math.hypot(p[0] - x, p[1] - y) };
}

/**
 * Project an ordered stop sequence onto a shape, monotonically.
 * For each stop we take the first segment (from the cursor on) that is within 30 m and is a
 * local minimum; otherwise the global minimum after the cursor.
 */
function projectStops(shapeXY, cum, stopXYs) {
  const out = [];
  let cursor = 0;
  let cursorT = 0;
  for (const p of stopXYs) {
    let best = null;
    let firstClose = null;
    for (let i = cursor; i < shapeXY.length - 1; i++) {
      const r = projectOnSegment(p, shapeXY[i], shapeXY[i + 1]);
      if (i === cursor && r.t < cursorT) r.t = cursorT;
      const cand = { i, t: r.t, dist: r.dist };
      if (!best || cand.dist < best.dist) best = cand;
      if (firstClose) {
        if (cand.dist < firstClose.dist) firstClose = cand;
        else if (cand.dist > firstClose.dist + 60) break;
      } else if (cand.dist < 30) firstClose = cand;
    }
    const pick = firstClose ?? best ?? { i: shapeXY.length - 2, t: 1 };
    cursor = pick.i;
    cursorT = pick.t;
    const segLen = cum[pick.i + 1] - cum[pick.i];
    out.push(cum[pick.i] + pick.t * segLen);
  }
  for (let i = 1; i < out.length; i++) if (out[i] < out[i - 1]) out[i] = out[i - 1];
  return out;
}

const median = (xs) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const r1 = (x) => Math.round(x * 10) / 10;
const r6 = (x) => Math.round(x * 1e6) / 1e6;

// ---------------------------------------------------------------- load
console.log(`[fixtures] reading ${zipPath}`);
const files = unzipSync(readFileSync(zipPath));
const txt = (name) => strFromU8(files[name]);

const routesCsv = parseCsv(txt('routes.txt'));
const stopsCsv = parseCsv(txt('stops.txt'));
const tripsCsv = parseCsv(txt('trips.txt'));
const calCsv = parseCsv(txt('calendar_dates.txt'));
const shapesCsv = parseCsv(txt('shapes.txt'));
const agencyCsv = parseCsv(txt('agency.txt'));

const routes = new Map();
for (const r of routesCsv.rows) {
  const g = (n) => r[routesCsv.col(n)];
  const short = g('route_short_name');
  const kind = /^N\d/.test(short)
    ? 'night'
    : /^R\d/.test(short) || short === 'L60'
      ? 'special'
      : 'day';
  routes.set(g('route_id'), {
    id: g('route_id'),
    short_name: short,
    long_name: g('route_long_name').trim().replace(/\s+/g, ' '),
    color: `#${(g('route_color') || '666666').toUpperCase()}`,
    text_color: `#${(g('route_text_color') || 'FFFFFF').toUpperCase()}`,
    kind,
  });
}

const stops = new Map();
for (const r of stopsCsv.rows) {
  const g = (n) => r[stopsCsv.col(n)];
  stops.set(g('stop_id'), {
    id: g('stop_id'),
    name: g('stop_name').trim().replace(/\s+/g, ' '),
    lon: Number(g('stop_lon')),
    lat: Number(g('stop_lat')),
  });
}

const servicesByDate = new Map();
for (const r of calCsv.rows) {
  if (r[calCsv.col('exception_type')] !== '1') continue;
  const d = r[calCsv.col('date')];
  const iso = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;
  if (!servicesByDate.has(iso)) servicesByDate.set(iso, new Set());
  servicesByDate.get(iso).add(r[calCsv.col('service_id')]);
}

const trips = new Map();
for (const r of tripsCsv.rows) {
  const g = (n) => r[tripsCsv.col(n)];
  trips.set(g('trip_id'), {
    id: g('trip_id'),
    route: g('route_id'),
    service: g('service_id'),
    headsign: g('trip_headsign').trim(),
    shape: g('shape_id'),
    direction: Number(g('direction_id') || 0),
  });
}

const neededServices = new Set(
  Object.values(DAYS).flatMap((d) => [...(servicesByDate.get(d) ?? [])]),
);
const neededTrips = new Set(
  [...trips.values()].filter((t) => neededServices.has(t.service)).map((t) => t.id),
);

console.log('[fixtures] parsing stop_times…');
const stText = txt('stop_times.txt');
const stLines = simpleLines(stText);
const stHeader = stLines.next().value.split(',');
const cTrip = stHeader.indexOf('trip_id');
const cArr = stHeader.indexOf('arrival_time');
const cDep = stHeader.indexOf('departure_time');
const cStop = stHeader.indexOf('stop_id');
const cSeq = stHeader.indexOf('stop_sequence');
const stopTimes = new Map();
for (const line of stLines) {
  const f = line.split(',');
  const tripId = f[cTrip];
  if (!neededTrips.has(tripId)) continue;
  let arr = stopTimes.get(tripId);
  if (!arr) stopTimes.set(tripId, (arr = []));
  arr.push({
    seq: Number(f[cSeq]),
    stop: f[cStop],
    arr: hms(f[cArr] || f[cDep]),
    dep: hms(f[cDep] || f[cArr]),
  });
}
for (const arr of stopTimes.values()) arr.sort((a, b) => a.seq - b.seq);

const shapePts = new Map();
for (const r of shapesCsv.rows) {
  const id = r[shapesCsv.col('shape_id')];
  let arr = shapePts.get(id);
  if (!arr) shapePts.set(id, (arr = []));
  arr.push([
    Number(r[shapesCsv.col('shape_pt_sequence')]),
    Number(r[shapesCsv.col('shape_pt_lon')]),
    Number(r[shapesCsv.col('shape_pt_lat')]),
  ]);
}
const shapes = new Map();
for (const [id, pts] of shapePts) {
  pts.sort((a, b) => a[0] - b[0]);
  const path = [];
  for (const [, lon, lat] of pts) {
    const prev = path[path.length - 1];
    if (prev && prev[0] === lon && prev[1] === lat) continue;
    path.push([lon, lat]);
  }
  const cum = [0];
  for (let i = 1; i < path.length; i++) cum.push(cum[i - 1] + haversine(path[i - 1], path[i]));
  shapes.set(id, { path, cum, xy: path.map(toXY) });
}

// ---------------------------------------------------------------- per-day build
const projCache = new Map();
function offsetsFor(shapeId, stopIds) {
  const key = `${shapeId}|${stopIds.join(',')}`;
  let res = projCache.get(key);
  if (!res) {
    const sh = shapes.get(shapeId);
    const stopXY = stopIds.map((s) => toXY([stops.get(s).lon, stops.get(s).lat]));
    res = projectStops(sh.xy, sh.cum, stopXY);
    projCache.set(key, res);
  }
  return res;
}

function medianGap(deps, [a, b]) {
  const ds = deps.filter((t) => t >= a && t < b).sort((x, y) => x - y);
  if (ds.length < 2) return null;
  const gaps = [];
  for (let i = 1; i < ds.length; i++) gaps.push(ds[i] - ds[i - 1]);
  return Math.round(median(gaps));
}

function maxConcurrent(intervals) {
  const ev = [];
  for (const [s, e] of intervals) ev.push([s, 1], [e, -1]);
  ev.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let cur = 0;
  let best = 0;
  for (const [, d] of ev) best = Math.max(best, (cur += d));
  return best;
}

const COST = { eur_per_bus_hour: 60, eur_per_km: 1.2, eur_per_bus_year: 45000 };

function buildDay(day, date) {
  const services = servicesByDate.get(date) ?? new Set();
  const dayTrips = [...trips.values()].filter(
    (t) => services.has(t.service) && stopTimes.has(t.id),
  );
  const byRoute = new Map();
  for (const t of dayTrips) {
    if (!byRoute.has(t.route)) byRoute.set(t.route, []);
    byRoute.get(t.route).push(t);
  }

  const vehShapes = [];
  const vehShapeIdx = new Map();
  const vehTrips = [];
  const outRoutes = [];
  const stopRoutes = new Map();
  const stopDeps = new Map();
  const graphPatterns = [];

  const routeIds = [...byRoute.keys()].sort((a, b) => {
    const ra = routes.get(a);
    const rb = routes.get(b);
    const kindOrder = { day: 0, special: 1, night: 2 };
    return (
      kindOrder[ra.kind] - kindOrder[rb.kind] ||
      ra.short_name.localeCompare(rb.short_name, 'en', { numeric: true })
    );
  });

  for (const routeId of routeIds) {
    const rTrips = byRoute.get(routeId);
    const route = routes.get(routeId);
    // group by direction + stop sequence
    const groups = new Map();
    for (const t of rTrips) {
      const st = stopTimes.get(t.id);
      const key = `${t.direction}|${st.map((s) => s.stop).join(',')}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(t);
    }
    const patterns = [];
    for (const dir of [0, 1]) {
      const cands = [...groups.entries()].filter(([k]) => k.startsWith(`${dir}|`));
      if (!cands.length) continue;
      cands.sort((a, b) => b[1].length - a[1].length);
      const [key, gTrips] = cands[0];
      const stopIds = key.split('|')[1].split(',');
      const shapeCount = new Map();
      for (const t of gTrips) shapeCount.set(t.shape, (shapeCount.get(t.shape) ?? 0) + 1);
      const shapeId = [...shapeCount.entries()].sort((a, b) => b[1] - a[1])[0][0];
      const sh = shapes.get(shapeId);
      const offs = offsetsFor(shapeId, stopIds);
      const headsignCount = new Map();
      for (const t of gTrips)
        headsignCount.set(t.headsign, (headsignCount.get(t.headsign) ?? 0) + 1);
      patterns.push({
        id: `${routeId}:${dir}`,
        direction: dir,
        headsign: [...headsignCount.entries()].sort((a, b) => b[1] - a[1])[0][0],
        stop_ids: stopIds,
        path: sh.path.map(([x, y]) => [r6(x), r6(y)]),
        stop_offsets: offs.map(r1),
        _trips: gTrips.length,
      });
    }

    // vehicles + stats
    const intervals = [];
    let busSeconds = 0;
    let meters = 0;
    const depsByDir = [[], []];
    const durByDir = [[], []];
    for (const t of rTrips) {
      const st = stopTimes.get(t.id);
      const offs = offsetsFor(
        t.shape,
        st.map((s) => s.stop),
      );
      if (!vehShapeIdx.has(t.shape)) {
        vehShapeIdx.set(t.shape, vehShapes.length);
        const sh = shapes.get(t.shape);
        vehShapes.push({
          id: vehShapes.length,
          path: sh.path.map(([x, y]) => [r6(x), r6(y)]),
          cum_m: sh.cum.map(r1),
        });
      }
      const tt = [];
      const dd = [];
      st.forEach((s, i) => {
        if (s.arr !== s.dep) {
          tt.push(s.arr);
          dd.push(r1(offs[i]));
        }
        tt.push(s.dep);
        dd.push(r1(offs[i]));
      });
      for (let i = 1; i < tt.length; i++) if (tt[i] < tt[i - 1]) tt[i] = tt[i - 1];
      vehTrips.push({
        route: routeId,
        shape: vehShapeIdx.get(t.shape),
        headsign: t.headsign,
        t: tt,
        d: dd,
      });
      const start = tt[0];
      const end = tt[tt.length - 1];
      intervals.push([start, end]);
      busSeconds += end - start;
      meters += dd[dd.length - 1] - dd[0];
      depsByDir[t.direction]?.push(start);
      if (start >= PEAK[0] && start < PEAK[1]) durByDir[t.direction]?.push(end - start);
      for (const s of st) {
        if (!stopRoutes.has(s.stop)) stopRoutes.set(s.stop, new Set());
        stopRoutes.get(s.stop).add(routeId);
        stopDeps.set(s.stop, (stopDeps.get(s.stop) ?? 0) + 1);
      }
    }
    const mainDir = depsByDir[0].length >= depsByDir[1].length ? 0 : 1;
    const mainPattern = patterns.find((p) => p.direction === mainDir) ?? patterns[0];
    const lengthM =
      mainPattern.stop_offsets[mainPattern.stop_offsets.length - 1] - mainPattern.stop_offsets[0];
    const allDur = rTrips.map((t) => {
      const st = stopTimes.get(t.id);
      return st[st.length - 1].arr - st[0].dep;
    });
    const runTime = Math.round(median(durByDir[mainDir]) ?? median(allDur));
    const allDeps = [...depsByDir[0], ...depsByDir[1]];
    const busHours = busSeconds / 3600;
    const km = meters / 1000;
    outRoutes.push({
      id: routeId,
      short_name: route.short_name,
      long_name: route.long_name,
      color: route.color,
      text_color: route.text_color,
      kind: route.kind,
      patterns: patterns.map(({ _trips, ...p }) => p),
      stats: {
        trips: rTrips.length,
        first_dep: Math.min(...allDeps),
        last_dep: Math.max(...allDeps),
        headway_peak: medianGap(depsByDir[mainDir], PEAK),
        headway_offpeak: medianGap(depsByDir[mainDir], OFFPEAK),
        length_km: r1(lengthM / 1000),
        run_time: runTime,
        speed_kmh: runTime > 0 ? r1(lengthM / 1000 / (runTime / 3600)) : null,
        fleet: maxConcurrent(intervals),
        bus_hours: r1(busHours),
        km: r1(km),
        cost_eur: Math.round(busHours * COST.eur_per_bus_hour + km * COST.eur_per_km),
      },
      modified: false,
      added: false,
    });

    for (const p of patterns) {
      const hw = medianGap(depsByDir[p.direction], [6 * 3600, 22 * 3600]) ?? 3600;
      graphPatterns.push({
        route: routeId,
        stops: p.stop_ids,
        offsets: p.stop_offsets,
        headway: hw,
        speed: lengthM / Math.max(runTime, 60),
      });
    }
  }

  const outStops = [...stopRoutes.keys()]
    .map((id) => stops.get(id))
    .filter(Boolean)
    .sort((a, b) => a.id.localeCompare(b.id, 'en', { numeric: true }))
    .map((s) => ({
      id: s.id,
      name: s.name,
      lon: r6(s.lon),
      lat: r6(s.lat),
      routes: [...stopRoutes.get(s.id)],
      boardings_weight: stopDeps.get(s.id) ?? 0,
      modified: false,
      added: false,
      removed: false,
    }));

  const totals = outRoutes.reduce(
    (acc, r) => ({
      fleet: acc.fleet + r.stats.fleet,
      bus_hours: r1(acc.bus_hours + r.stats.bus_hours),
      km: r1(acc.km + r.stats.km),
      cost_eur: acc.cost_eur + r.stats.cost_eur,
      trips: acc.trips + r.stats.trips,
    }),
    { fleet: 0, bus_hours: 0, km: 0, cost_eur: 0, trips: 0 },
  );

  vehTrips.sort((a, b) => a.t[0] - b.t[0]);
  return {
    network: { routes: outRoutes, stops: outStops, totals },
    vehicles: { shapes: vehShapes, trips: vehTrips.map(({ headsign, ...t }) => t) },
    graph: { patterns: graphPatterns },
  };
}

// ---------------------------------------------------------------- mock POIs (from real stop names)
const POI_RULES = [
  ['hospital', /hospital|clínica/i],
  ['health_centre', /centro de salud|consultorio/i],
  ['university', /universidad/i],
  ['industrial_estate', /pol[ií]gono/i],
  ['city_centre', /plaza del castillo|pza\. del castillo|paseo (de )?sarasate|merindades/i],
  ['secondary_school', /instituto|ikastetxe|\bies\b/i],
];
function mockPois() {
  const out = [];
  for (const s of stops.values()) {
    const rule = POI_RULES.find(([, re]) => re.test(s.name));
    if (!rule) continue;
    const near = out.find(
      (p) => p.category === rule[0] && haversine([p.lon, p.lat], [s.lon, s.lat]) < 350,
    );
    if (near) continue;
    out.push({
      id: `mock-${out.length}`,
      category: rule[0],
      name: s.name,
      lon: r6(s.lon),
      lat: r6(s.lat),
    });
  }
  return out;
}

// ---------------------------------------------------------------- write
mkdirSync(outDir, { recursive: true });
const write = (name, obj) => {
  const s = JSON.stringify(obj);
  writeFileSync(resolve(outDir, name), s);
  console.log(`[fixtures] ${name.padEnd(24)} ${(s.length / 1024).toFixed(0).padStart(6)} KB`);
};

const graph = { stops: {}, days: {} };
for (const [day, date] of Object.entries(DAYS)) {
  const { network, vehicles, graph: g } = buildDay(day, date);
  write(`network-${day}.json`, network);
  write(`vehicles-${day}.json`, vehicles);
  graph.days[day] = g.patterns;
  for (const s of network.stops) graph.stops[s.id] = [s.lon, s.lat, s.boardings_weight];
}

const lons = [...stops.values()].map((s) => s.lon);
const lats = [...stops.values()].map((s) => s.lat);
const bbox = [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)].map(r6);
const pois = mockPois();
graph.pois = pois;
graph.bbox = bbox;
write('graph.json', graph);
write('pois.json', { pois });

const cats = [
  'hospital',
  'health_centre',
  'university',
  'industrial_estate',
  'city_centre',
  'secondary_school',
];
const agencyName = agencyCsv.rows[0][agencyCsv.col('agency_name')];
write('meta.json', {
  feed: {
    agency: agencyName,
    start_date: [...servicesByDate.keys()].sort()[0],
    end_date: [...servicesByDate.keys()].sort().at(-1),
    n_routes: routes.size,
    n_stops: stops.size,
  },
  days: DAYS,
  bbox,
  center: [r6((bbox[0] + bbox[2]) / 2), r6((bbox[1] + bbox[3]) / 2)],
  population: 371000,
  n_zones: 3200,
  poi_categories: cats.map((id) => ({ id, count: pois.filter((p) => p.category === id).length })),
  default_window: { day: 'weekday', start: 28800, duration: 3600 },
  cost_params: {
    ...COST,
    source: 'MOCK placeholder values (not sourced) — replaced by the engine cost model.',
  },
  data_notes: [
    'MOCK API: isochrones, population and POI counts are synthetic placeholders until the routing engine is connected.',
    'Routes, stops, shapes and timetables come from the official TUC Pamplona GTFS (NAP feed 1177).',
    'Demand is a gravity model from population and destinations: no public origin–destination matrix exists.',
    'Fleet is estimated as the peak number of simultaneous trips; layover and depot time are not included.',
  ],
});
console.log('[fixtures] done');
