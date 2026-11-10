#!/usr/bin/env node
/**
 * Design-review screenshots of every main view → docs/screenshots/*.png
 *
 * Usage: npm run screenshots            (starts a mock-API dev server on :3200)
 *        BASE_URL=http://localhost:3000 npm run screenshots   (reuse a running server)
 *        BASEMAP=none npm run screenshots                     (offline, blank basemap)
 */
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, '../../docs/screenshots');
mkdirSync(out, { recursive: true });

const PORT = 3200;
let server = null;
let base = process.env.BASE_URL;
if (!base) {
  base = `http://localhost:${PORT}`;
  server = spawn('npx', ['vite', '--port', String(PORT), '--strictPort'], {
    cwd: resolve(here, '..'),
    env: { ...process.env, VITE_MOCK_API: '1', VITE_BASEMAP: process.env.BASEMAP ?? '' },
    stdio: 'ignore',
  });
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`${base}/api/health`);
      if (r.ok) break;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
}

const launchOptions = process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {};
const browser = await chromium.launch(launchOptions);

const DESKTOP = { width: 1440, height: 900 };
const TABLET = { width: 820, height: 1180 };

async function shot(
  name,
  { hash, theme = 'light', lang = 'es', viewport = DESKTOP, before, after },
) {
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
await shot('08-accessibility-empty', { hash: `#/accessibility?${q()}` });
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
server?.kill();

// palette-quantise to keep docs/ light (optional: needs python3 + Pillow)
const pngs = readdirSync(out)
  .filter((f) => f.endsWith('.png'))
  .map((f) => resolve(out, f));
const res = spawnSync('python3', [resolve(here, 'compress-png.py'), ...pngs], { stdio: 'ignore' });
console.log(
  res.status === 0 ? 'compressed PNGs' : 'PNG compression skipped (python3 + Pillow not found)',
);
