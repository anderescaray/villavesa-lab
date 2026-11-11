#!/usr/bin/env node
/**
 * Design-review screenshots of every main view → docs/screenshots/*.png, against the REAL engine
 * and the real basemap tiles.
 *
 * Usage: npm run screenshots                         (uses the API at :8000, or starts one on :8200)
 *        API_URL=http://localhost:8100 npm run screenshots
 *        BASE_URL=http://localhost:3000 npm run screenshots   (reuse a running web server)
 *        ONLY=08 npm run screenshots                         (only shots whose name contains "08")
 *        BASEMAP=none npm run screenshots                    (offline, blank basemap)
 */
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, '../../docs/screenshots');
mkdirSync(out, { recursive: true });

const children = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function healthy(url) {
  try {
    const r = await fetch(url);
    return r.ok && (await r.json()).status === 'ok';
  } catch {
    return false;
  }
}

let api = process.env.API_URL ?? 'http://localhost:8000';
if (!process.env.BASE_URL && !(await healthy(`${api}/api/health`))) {
  api = 'http://localhost:8200';
  console.log('starting the engine on :8200 (first load can take a minute)…');
  children.push(
    spawn('uv', ['run', 'uvicorn', 'vlab_api.main:app', '--port', '8200'], {
      cwd: resolve(here, '../..'),
      env: { ...process.env, VLAB_SYNC_LOAD: '1' },
      stdio: 'ignore',
    }),
  );
  for (let i = 0; i < 240 && !(await healthy(`${api}/api/health`)); i++) await sleep(1000);
}

const PORT = 3200;
let base = process.env.BASE_URL;
if (!base) {
  base = `http://localhost:${PORT}`;
  children.push(
    spawn('npx', ['vite', '--port', String(PORT), '--strictPort'], {
      cwd: resolve(here, '..'),
      env: { ...process.env, VITE_API_PROXY: api, VITE_BASEMAP: process.env.BASEMAP ?? '' },
      stdio: 'ignore',
    }),
  );
  for (let i = 0; i < 60 && !(await healthy(`${base}/api/health`)); i++) await sleep(500);
}
const only = process.env.ONLY;

const launchOptions = process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {};
const browser = await chromium.launch(launchOptions);

const DESKTOP = { width: 1440, height: 900 };
const TABLET = { width: 820, height: 1180 };

async function shot(
  name,
  { hash, theme = 'light', lang = 'es', viewport = DESKTOP, before, after },
) {
  if (only && !name.includes(only)) return;
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2 });
  await ctx.addInitScript(
    ([t, l]) => {
      localStorage.setItem('vlab.prefs', JSON.stringify({ themePref: t, lang: l }));
      localStorage.setItem('vlab.isoHintSeen', '1');
    },
    [theme, lang],
  );
  const page = await ctx.newPage();
  if (before) await before(page);
  await page.goto(`${base}/${hash}`);
  await page.waitForSelector('[data-testid="time-control"], h1');
  await page
    .waitForFunction(
      () => window.__vlabMap?.isStyleLoaded() && window.__vlabMap?.areTilesLoaded(),
      null,
      {
        timeout: 20000,
      },
    )
    .catch(() => undefined);
  if (hash.startsWith('#/accessibility')) {
    await page.waitForSelector('[data-testid="acc-headline"]', { timeout: 60000 });
  }
  await page.waitForTimeout(1200);
  if (after) await after(page);
  await page
    .waitForFunction(
      () => window.__vlabMap?.areTilesLoaded() && !window.__vlabMap?.isMoving(),
      null,
      {
        timeout: 15000,
      },
    )
    .catch(() => undefined);
  await page.waitForTimeout(900);
  await page.screenshot({ path: resolve(out, `${name}.png`) });
  await ctx.close();
  console.log(`  ✓ ${name}`);
}

const iso = 'iso=-1.64180,42.81780&isot=0830';
const q = (extra = '') => `day=weekday&t=0832&play=0${extra ? `&${extra}` : ''}`;

console.log(`screenshots → ${out}`);
await shot('01-network-light', { hash: `#/network?${q()}` });
await shot('02-network-dark', { hash: `#/network?${q()}`, theme: 'dark' });
await shot('03-line-selected', { hash: `#/network?${q('line=4')}` });
await shot('04-isochrone', { hash: `#/network?${q(iso)}` });
await shot('05-isochrone-dark', { hash: `#/network?${q(iso)}`, theme: 'dark' });
await shot('06-midday-zoomed', {
  hash: `#/network?day=weekday&t=1305&play=0`,
  after: async (page) => {
    await page.evaluate(() => window.__vlabMap?.jumpTo({ center: [-1.6436, 42.8155], zoom: 14.6 }));
    await page.hover('[data-testid="line-row-L04"]');
  },
});
await shot('07-stop-popover', {
  hash: `#/network?${q('stop=13')}`,
  after: async (page) => {
    await page.evaluate(() => window.__vlabMap?.jumpTo({ center: [-1.6392, 42.8129], zoom: 15.2 }));
  },
});
const acc = (extra = '') => `#/accessibility?day=weekday&t=0800&play=0${extra ? `&${extra}` : ''}`;
await shot('08-accessibility-light', { hash: acc('cat=hospital&metric=time&thr=30') });
await shot('08-accessibility-dark', {
  hash: acc('cat=hospital&metric=time&thr=30'),
  theme: 'dark',
});
await shot('08-accessibility-underserved', { hash: acc('cat=hospital&metric=gap&thr=30') });
await shot('08-accessibility-income', { hash: acc('cat=university&metric=income&thr=30') });
await shot('08-accessibility-hover', {
  hash: acc('cat=hospital&metric=time&thr=30'),
  after: async (page) => {
    const p = await page.evaluate(() => {
      const map = window.__vlabMap;
      return map ? map.project([-1.6205, 42.8215]) : null;
    });
    if (p) {
      await page.mouse.move(p.x - 4, p.y - 4);
      await page.mouse.move(p.x, p.y, { steps: 3 });
    }
  },
});
await shot('08-accessibility-tablet', {
  hash: acc('cat=health_centre&metric=time&thr=15'),
  viewport: TABLET,
  after: async (page) => {
    await page.keyboard.press('[');
  },
});
await shot('09-scenario-empty', { hash: `#/scenario?${q()}` });
await shot('10-optimizer-empty', { hash: `#/optimizer?${q()}` });
await shot('11-compare-empty', { hash: `#/compare?${q()}` });
await shot('12-shortcuts', {
  hash: `#/network?${q()}`,
  after: async (page) => {
    await page.keyboard.press('?');
  },
});
await shot('13-network-en', { hash: `#/network?${q('line=9')}`, lang: 'en' });
await shot('14-about-data', {
  hash: `#/network?${q()}`,
  lang: 'en',
  after: async (page) => {
    await page.click('[data-testid="open-about"]');
  },
});
await shot('15-tablet', { hash: `#/network?${q(iso)}`, viewport: TABLET });
await shot('16-night', { hash: `#/network?day=saturday&t=2350&play=0`, theme: 'dark' });
await shot('17-components-light', { hash: '#/dev/components' });
await shot('18-components-dark', { hash: '#/dev/components', theme: 'dark' });

await browser.close();
for (const c of children) c.kill();

// palette-quantise to keep docs/ light (optional: needs python3 + Pillow)
const pngs = readdirSync(out)
  .filter((f) => f.endsWith('.png'))
  .map((f) => resolve(out, f));
const res = spawnSync('python3', [resolve(here, 'compress-png.py'), ...pngs], { stdio: 'ignore' });
console.log(
  res.status === 0 ? 'compressed PNGs' : 'PNG compression skipped (python3 + Pillow not found)',
);
