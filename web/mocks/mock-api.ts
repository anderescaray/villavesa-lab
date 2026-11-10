/**
 * MOCK API (temporary). A Vite dev/preview middleware that serves docs/api.md endpoints from
 * fixtures built by `npm run fixtures` (real GTFS) and a clearly synthetic isochrone.
 *
 * Enabled with VITE_MOCK_API=1. Delete `web/mocks/` and the plugin line in vite.config.ts once
 * the FastAPI backend is available — the app only talks to `/api` through `src/api/client.ts`.
 */
import { existsSync, readFileSync } from 'node:fs';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { contours } from 'd3-contour';
import type { Connect, Plugin } from 'vite';

const here = dirname(fileURLToPath(import.meta.url));
const fixturesDir = resolve(here, 'fixtures');

type Day = 'weekday' | 'saturday' | 'sunday';
interface GraphPattern {
  route: string;
  stops: string[];
  offsets: number[];
  headway: number;
  speed: number;
}
interface Graph {
  stops: Record<string, [number, number, number]>;
  days: Record<Day, GraphPattern[]>;
  pois: { id: string; category: string; name: string; lon: number; lat: number }[];
  bbox: [number, number, number, number];
}

const cache = new Map<string, string>();
function fixture(name: string): string {
  let s = cache.get(name);
  if (s === undefined) {
    const path = resolve(fixturesDir, name);
    if (!existsSync(path)) {
      throw new Error(`Mock fixture ${name} missing — run \`npm run fixtures\` in web/.`);
    }
    s = readFileSync(path, 'utf8');
    cache.set(name, s);
  }
  return s;
}
let graphCache: Graph | null = null;
const graph = (): Graph => (graphCache ??= JSON.parse(fixture('graph.json')) as Graph);

const DAYS: readonly Day[] = ['weekday', 'saturday', 'sunday'];
const asDay = (d: unknown): Day => (DAYS.includes(d as Day) ? (d as Day) : 'weekday');

// ---------------------------------------------------------------- synthetic isochrone
const LAT0 = 42.81;
const MX = 111320 * Math.cos((LAT0 * Math.PI) / 180);
const MY = 110540;
const WALK = 1.25; // m/s
const DETOUR = 1.3; // crow-fly → network factor
const CELL = 80; // metres

function isochrone(body: {
  origin: [number, number];
  window?: { day?: Day; start?: number };
  cutoffs?: number[];
  mode?: 'transit' | 'walk';
}) {
  const g = graph();
  const [olon, olat] = body.origin;
  const cutoffs = (body.cutoffs ?? [900, 1800, 2700]).slice().sort((a, b) => a - b);
  const maxCut = cutoffs[cutoffs.length - 1] ?? 2700;
  const ox = olon * MX;
  const oy = olat * MY;
  const ids = Object.keys(g.stops);
  const index = new Map(ids.map((id, i) => [id, i]));
  const sx = new Float64Array(ids.length);
  const sy = new Float64Array(ids.length);
  ids.forEach((id, i) => {
    const s = g.stops[id];
    if (!s) return;
    sx[i] = s[0] * MX;
    sy[i] = s[1] * MY;
  });
  const t = new Float64Array(ids.length).fill(Infinity);
  if (body.mode !== 'walk') {
    for (let i = 0; i < ids.length; i++) {
      const w = (Math.hypot((sx[i] ?? 0) - ox, (sy[i] ?? 0) - oy) * DETOUR) / WALK;
      if (w <= 900) t[i] = w;
    }
    const patterns = g.days[asDay(body.window?.day)] ?? [];
    // Bellman-Ford style relaxation (a handful of rounds = transfers).
    for (let round = 0; round < 4; round++) {
      let changed = false;
      for (const p of patterns) {
        let best = Infinity;
        let bestOff = 0;
        p.stops.forEach((sid, k) => {
          const i = index.get(sid);
          if (i === undefined) return;
          const off = p.offsets[k] ?? 0;
          if (best < Infinity) {
            const arr = best + (off - bestOff) / Math.max(p.speed, 2);
            if (arr < (t[i] ?? Infinity)) {
              t[i] = arr;
              changed = true;
            }
          }
          const board = (t[i] ?? Infinity) + Math.min(p.headway / 2, 900);
          const projected = best + (off - bestOff) / Math.max(p.speed, 2);
          if (board < projected) {
            best = board;
            bestOff = off;
          }
        });
      }
      // walking transfers ≤ 350 m
      for (let i = 0; i < ids.length; i++) {
        const ti = t[i] ?? Infinity;
        if (!Number.isFinite(ti)) continue;
        for (let j = 0; j < ids.length; j++) {
          const d = Math.hypot((sx[i] ?? 0) - (sx[j] ?? 0), (sy[i] ?? 0) - (sy[j] ?? 0));
          if (d > 350) continue;
          const tj = ti + (d * DETOUR) / WALK + 60;
          if (tj < (t[j] ?? Infinity)) {
            t[j] = tj;
            changed = true;
          }
        }
      }
      if (!changed) break;
    }
  }

  const [minLon, minLat, maxLon, maxLat] = g.bbox;
  const x0 = (minLon - 0.03) * MX;
  const y0 = (minLat - 0.03) * MY;
  const nx = Math.ceil(((maxLon + 0.03) * MX - x0) / CELL);
  const ny = Math.ceil(((maxLat + 0.03) * MY - y0) / CELL);
  const values = new Float64Array(nx * ny);
  const reached: number[] = [];
  for (let i = 0; i < ids.length; i++) if ((t[i] ?? Infinity) < maxCut) reached.push(i);
  // synthetic density: kernel around stops weighted by service level
  const density = new Float64Array(nx * ny);
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const x = x0 + (i + 0.5) * CELL;
      const y = y0 + (j + 0.5) * CELL;
      let v = (Math.hypot(x - ox, y - oy) * DETOUR) / WALK;
      for (const k of reached) {
        const d = Math.hypot(x - (sx[k] ?? 0), y - (sy[k] ?? 0));
        if (d > 1200) continue;
        const c = (t[k] ?? Infinity) + (d * DETOUR) / WALK;
        if (c < v) v = c;
      }
      values[j * nx + i] = -v;
    }
  }
  for (const id of ids) {
    const s = g.stops[id];
    if (!s) continue;
    const ci = Math.floor((s[0] * MX - x0) / CELL);
    const cj = Math.floor((s[1] * MY - y0) / CELL);
    for (let dj = -4; dj <= 4; dj++)
      for (let di = -4; di <= 4; di++) {
        const ii = ci + di;
        const jj = cj + dj;
        if (ii < 0 || jj < 0 || ii >= nx || jj >= ny) continue;
        density[jj * nx + ii] += Math.sqrt(s[2]) * Math.exp(-(di * di + dj * dj) / 8);
      }
  }
  let densityTotal = 0;
  for (const v of density) densityTotal += v;
  const popScale = 371000 / Math.max(densityTotal, 1);

  const gen = contours()
    .size([nx, ny])
    .thresholds(cutoffs.map((c) => -c));
  const result = gen(Array.from(values)).map((c, k) => {
    const cutoff = cutoffs[k] ?? 0;
    const coordinates = c.coordinates.map((poly) =>
      poly.map((ring) =>
        ring.map(([gx, gy]) => [
          Math.round(((x0 + (gx ?? 0) * CELL) / MX) * 1e6) / 1e6,
          Math.round(((y0 + (gy ?? 0) * CELL) / MY) * 1e6) / 1e6,
        ]),
      ),
    );
    let cells = 0;
    let pop = 0;
    for (let q = 0; q < values.length; q++) {
      if (-(values[q] ?? 0) <= cutoff) {
        cells++;
        pop += (density[q] ?? 0) * popScale;
      }
    }
    const pois: Record<string, number> = {};
    for (const p of g.pois) {
      const ci = Math.floor((p.lon * MX - x0) / CELL);
      const cj = Math.floor((p.lat * MY - y0) / CELL);
      const v = -(values[cj * nx + ci] ?? -Infinity);
      pois[p.category] = (pois[p.category] ?? 0) + (v <= cutoff ? 1 : 0);
    }
    return {
      cutoff,
      geometry: { type: 'MultiPolygon', coordinates },
      population: Math.round(pop / 10) * 10,
      area_km2: Math.round(((cells * CELL * CELL) / 1e6) * 10) / 10,
      pois,
    };
  });
  return {
    origin: body.origin,
    isochrones: result,
    reached_stops: reached
      .filter((i) => (t[i] ?? Infinity) <= maxCut)
      .map((i) => ({ id: ids[i], time: Math.round(t[i] ?? 0) })),
  };
}

// ---------------------------------------------------------------- middleware
async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  const raw = Buffer.concat(chunks).toString('utf8');
  return raw ? (JSON.parse(raw) as unknown) : {};
}

function send(res: ServerResponse, status: number, body: string) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('X-Mock-Api', '1');
  res.end(body);
}

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

const middleware: Connect.NextHandleFunction = (req, res, next) => {
  const url = new URL(req.url ?? '/', 'http://localhost');
  if (!url.pathname.startsWith('/api/')) {
    next();
    return;
  }
  const path = url.pathname.slice(4);
  void (async () => {
    try {
      // Opt-in failure injection for testing error states: ?mock_fail=1 on the page URL is
      // forwarded by the client as the `x-mock-fail` header.
      if (req.headers['x-mock-fail'] === '1') {
        send(res, 503, JSON.stringify({ detail: 'Mock failure injected' }));
        return;
      }
      if (path === '/health') return send(res, 200, '{"status":"ok"}');
      if (path === '/meta') return send(res, 200, fixture('meta.json'));
      if (path === '/pois') return send(res, 200, fixture('pois.json'));
      if (path === '/network' && req.method === 'GET') {
        return send(res, 200, fixture(`network-${asDay(url.searchParams.get('day'))}.json`));
      }
      if (path === '/network' && req.method === 'POST') {
        const body = (await readBody(req)) as { day?: Day };
        return send(res, 200, fixture(`network-${asDay(body.day)}.json`));
      }
      if (path === '/vehicles' && req.method === 'POST') {
        const body = (await readBody(req)) as { day?: Day };
        return send(res, 200, fixture(`vehicles-${asDay(body.day)}.json`));
      }
      if (path === '/isochrone' && req.method === 'POST') {
        const body = (await readBody(req)) as Parameters<typeof isochrone>[0];
        await delay(250); // let the skeleton state be visible, like a real request
        return send(res, 200, JSON.stringify(isochrone(body)));
      }
      send(res, 404, JSON.stringify({ detail: `Mock API: ${req.method} ${path} not implemented` }));
    } catch (err) {
      send(res, 500, JSON.stringify({ detail: String(err) }));
    }
  })();
};

export function mockApi(): Plugin {
  return {
    name: 'villavesa-mock-api',
    configureServer(server) {
      server.middlewares.use(middleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware);
    },
  };
}
