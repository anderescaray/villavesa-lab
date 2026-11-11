#!/usr/bin/env node
/**
 * Design-review screenshots of the Optimizer and Compare views → docs/screenshots/optimizer-*.png
 * and compare-*.png, against the REAL engine (a real optimizer run) and the real basemap.
 *
 * Usage: BASE_URL=http://localhost:3000 node scripts/screenshots-optimizer.mjs
 *        (starts its own Vite on :3210 against API_URL / :8000 when BASE_URL is not set)
 *        ONLY=result node scripts/screenshots-optimizer.mjs      (only shots whose name contains "result")
 *        TIME_LIMIT=30 (seconds of the optimizer run; default 30)
 */
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, '../../docs/screenshots');
mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const children = [];
const api = process.env.API_URL ?? 'http://localhost:8000';

let base = process.env.BASE_URL;
if (!base) {
  base = 'http://localhost:3210';
  children.push(
    spawn('npx', ['vite', '--port', '3210', '--strictPort'], {
      cwd: resolve(here, '..'),
      env: { ...process.env, VITE_API_PROXY: api },
      stdio: 'ignore',
    }),
  );
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`${base}/api/health`)).ok) break;
    } catch {
      /* not up yet */
    }
    await sleep(500);
  }
}

const only = process.env.ONLY;
const want = (name) => !only || name.includes(only);
const timeLimit = Number(process.env.TIME_LIMIT ?? 30);
const browser = await chromium.launch();
const VIEWPORT = { width: 1440, height: 900 };

const newContext = async (theme, storageState) => {
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2, storageState });
  await ctx.addInitScript(
    ([t]) => {
      const prefs = JSON.stringify({ themePref: t, lang: 'es' });
      localStorage.setItem('vlab.prefs', prefs);
      localStorage.setItem('vlab.isoHintSeen', '1');
    },
    [theme],
  );
  return ctx;
};
const settle = (page, ms = 900) => page.waitForTimeout(ms);
const save = async (page, name) => {
  if (!want(name)) return;
  await page.screenshot({ path: `${out}/${name}.png` });
  console.log('  saved', name);
};

try {
  // ------------------------------------------------------------------ light: setup → run → result
  const ctx = await newContext('light');
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log('  pageerror:', e.message));
  page.on('console', (m) => m.type() === 'error' && console.log('  console.error:', m.text().slice(0, 160)));
  await page.goto(`${base}/#/optimizer?day=weekday&t=0800&play=0`);
  await page.getByTestId('opt-question').waitFor({ timeout: 90_000 });
  await settle(page, 1500);
  await save(page, 'optimizer-setup');

  await page.evaluate((s) => {
    window.__vlabOptimizer.getState().setSettings({
      timeLimit: s,
      moves: { frequency: true, stops: true, new_lines: true },
    });
  }, timeLimit);
  await page.getByTestId('opt-run').click();
  await page.getByTestId('opt-running').waitFor();
  await page.waitForFunction(
    () => document.querySelector('[data-testid="opt-history"]') || document.querySelectorAll('[data-testid="opt-log"] li').length > 1,
    null,
    { timeout: 60_000 },
  ).catch(() => {});
  await settle(page, 4000);
  await save(page, 'optimizer-running');

  await page.getByTestId('opt-result').waitFor({ timeout: 240_000 });
  await settle(page, 3200);
  await save(page, 'optimizer-result');
  // explanation scrolled into view
  await page.getByTestId('opt-explanation').scrollIntoViewIfNeeded();
  await page.evaluate(() => document.querySelector('[data-testid="opt-explanation"]').scrollIntoView({ block: 'start' }));
  const firstLine = page.getByTestId('opt-lines').locator('button').first();
  await firstLine.hover();
  await settle(page, 700);
  await save(page, 'optimizer-explanation');

  // trade-off
  if (want('tradeoff') || !only) {
    await page.getByTestId('opt-trade-run').click();
    await page.getByTestId('tradeoff-chart').waitFor({ timeout: 240_000 });
    await page.getByTestId('opt-tradeoff').scrollIntoViewIfNeeded();
    await page.evaluate(() => document.querySelector('[data-testid="opt-tradeoff"]').scrollIntoView({ block: 'start' }));
    await page.getByTestId('tradeoff-point').nth(4).hover();
    await settle(page, 600);
    await save(page, 'optimizer-tradeoff');
  }

  // compare (the optimizer's proposal): swipe at the middle
  await page.evaluate(() => window.__vlabOptimizer.getState().setPreview({ kind: 'result' }));
  await page.getByTestId('nav-compare').click();
  await page.getByTestId('compare-table').waitFor({ timeout: 120_000 });
  await settle(page, 3500);
  await save(page, 'compare-swipe');
  await page.getByTestId('compare-divider').focus();
  for (let i = 0; i < 6; i++) await page.keyboard.press('ArrowRight');
  await page.getByRole('radio', { name: /Diferencia/ }).click();
  await settle(page, 2500);
  await save(page, 'compare-delta');
  await page.getByRole('radio', { name: /Accesibilidad/ }).click();
  await page.getByTestId('compare-divider').waitFor();
  await settle(page, 9000);
  await save(page, 'compare-access');

  const state = await ctx.storageState();
  await ctx.close();

  // ------------------------------------------------------------------ dark: result
  if (want('dark')) {
    const dark = await newContext('dark', state);
    const dp = await dark.newPage();
    await dp.goto(`${base}/#/optimizer?day=weekday&t=0800&play=0`);
    await dp.getByTestId('opt-result').waitFor({ timeout: 90_000 });
    await settle(dp, 4000);
    await save(dp, 'optimizer-result-dark');
    await dp.getByTestId('nav-compare').click();
    await dp.getByTestId('compare-table').waitFor({ timeout: 90_000 });
    await settle(dp, 3500);
    await save(dp, 'compare-swipe-dark');
    await dark.close();
  }
} finally {
  await browser.close();
  for (const c of children) c.kill();
}
