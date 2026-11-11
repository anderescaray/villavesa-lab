#!/usr/bin/env node
/**
 * Design-review screenshots of the scenario editor → docs/screenshots/editor-*.png, against the
 * real engine and the real basemap (1440×900 @2x).
 *
 * Usage: BASE_URL=http://localhost:3300 node scripts/screenshots-editor.mjs
 *        (BASE_URL must be a Vite dev server proxying /api to a running engine)
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, '../../docs/screenshots');
mkdirSync(out, { recursive: true });
const base = process.env.BASE_URL ?? 'http://localhost:3300';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch(
  process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
);
const written = [];

async function session(theme = 'light') {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  await ctx.addInitScript((th) => {
    localStorage.setItem('vlab.prefs', JSON.stringify({ themePref: th, lang: 'es' }));
    localStorage.setItem('vlab.isoHintSeen', '1');
  }, theme);
  const page = await ctx.newPage();
  await page.goto(`${base}/#/scenario?day=weekday&t=0815&play=0&lang=es`);
  await page.getByTestId('view-scenario').waitFor();
  await page.evaluate(() => localStorage.removeItem('vlab.scenario.v1'));
  await page.reload();
  await page.getByTestId('view-scenario').waitFor();
  await page.waitForFunction(() => window.__vlabMap?.loaded());
  await sleep(1500);
  return { ctx, page };
}

async function shot(page, name) {
  await page.mouse.move(1430, 600);
  await sleep(900);
  const path = resolve(out, `editor-${name}.png`);
  await page.screenshot({ path });
  written.push(path);
  console.log('  wrote', path);
}

async function idle(page) {
  await page.getByTestId('impact-card').waitFor();
  await page.waitForFunction(
    () =>
      document.querySelector('[data-testid="impact-card"]')?.getAttribute('aria-busy') === 'false',
    null,
    { timeout: 30_000 },
  );
}

const lonlat = async (page, lon, lat) => {
  const box = await page.getByTestId('map').boundingBox();
  const p = await page.evaluate(([x, y]) => window.__vlabMap.project([x, y]), [lon, lat]);
  return [box.x + p.x, box.y + p.y];
};

async function frequency(page) {
  await page.keyboard.press('f');
  await page.getByTestId('line-picker').getByRole('button', { name: /^L04/ }).click();
  await page.getByTestId('headway-input').fill('4');
  await page.getByTestId('headway-input').press('Enter');
  await page.evaluate(() => document.activeElement?.blur());
  await idle(page);
}

// 1. empty state
{
  const { ctx, page } = await session();
  await shot(page, '01-empty');
  // 2. frequency edit + impact
  await frequency(page);
  await shot(page, '02-frequency');
  // 3. priority corridor selected
  await page.keyboard.press('p');
  await page
    .getByTestId('priority-inspector')
    .getByRole('button', { name: 'Elegir otra línea' })
    .click();
  await page.getByTestId('line-picker').getByRole('button', { name: /^L16/ }).click();
  const stops = page.getByTestId('priority-inspector').getByRole('listitem');
  await stops.nth(2).click();
  await stops.nth(9).click();
  await sleep(600);
  await shot(page, '03-priority');
  await page.getByTestId('priority-apply').click();
  await idle(page);
  // 4. new line mid-drawing
  await page.keyboard.press('l');
  await page.evaluate(() => window.__vlabMap.jumpTo({ center: [-1.636, 42.811], zoom: 14 }));
  await sleep(500);
  for (const [lon, lat] of [
    [-1.6447, 42.8169],
    [-1.635, 42.812],
    [-1.63, 42.805],
  ]) {
    const [x, y] = await lonlat(page, lon, lat);
    await page.mouse.click(x, y);
    await sleep(250);
  }
  await page.getByTestId('draft-length').filter({ hasText: 'km' }).waitFor();
  await sleep(600);
  await shot(page, '04-draw');
  await page.keyboard.press('Enter');
  await idle(page);
  // 5. delta choropleth after 3 edits
  await page.keyboard.press('v');
  await page.evaluate(() => window.__vlabMap.jumpTo({ center: [-1.648, 42.81], zoom: 12.4 }));
  await shot(page, '05-delta');
  await ctx.close();
}
// 6. dark mode
{
  const { ctx, page } = await session('dark');
  await frequency(page);
  await page.keyboard.press('v');
  await page.evaluate(() => window.__vlabMap.jumpTo({ center: [-1.648, 42.81], zoom: 12.4 }));
  await shot(page, '06-dark');
  await ctx.close();
}
await browser.close();

const py = spawnSync('python3', [resolve(here, 'compress-png.py'), ...written], {
  stdio: 'inherit',
});
if (py.status !== 0) console.warn('compression skipped (Pillow missing?)');
