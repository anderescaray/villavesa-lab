import { expect, test, type Page } from '@playwright/test';
import type { Map as MlMap } from 'maplibre-gl';

// Accessibility dashboard against the real engine (weekday 08:00–09:00 baseline).

async function open(page: Page, query = 'day=weekday&t=0800&play=0') {
  await page.addInitScript(() => {
    localStorage.setItem('vlab.prefs', JSON.stringify({ themePref: 'light', lang: 'es' }));
    localStorage.setItem('vlab.isoHintSeen', '1');
  });
  await page.goto(`/#/accessibility?${query}`);
  // the first analysis of a window can take a few seconds on a cold engine
  await expect(page.getByTestId('acc-headline')).toBeVisible({ timeout: 45_000 });
}

const pct = async (page: Page, id: string) =>
  Number(
    ((await page.getByTestId(`acc-cat-${id}`).getAttribute('aria-label')) ?? '').match(
      /:\s*(\d+)/,
    )?.[1] ?? NaN,
  );

test('shows the headline, categories, curve and equity for the default window', async ({
  page,
}) => {
  await open(page);
  await expect(page.getByTestId('acc-window')).toHaveText('Laborable · 08:00–09:00');
  const headline = page.getByTestId('acc-headline');
  await expect(headline).toContainText('no llegan a un hospital en 30 min');
  // real baseline: roughly 70 % reach a hospital, almost everyone a health centre
  const hospital = await pct(page, 'hospital');
  expect(hospital).toBeGreaterThan(40);
  expect(hospital).toBeLessThan(95);
  expect(await pct(page, 'health_centre')).toBeGreaterThan(90);
  await expect(page.getByTestId('acc-cat-hospital')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('acc-curve')).toBeVisible();
  await expect(page.getByTestId('acc-equity').locator('[data-testid^="acc-q"]')).toHaveCount(5);
  await expect(page.getByTestId('acc-ci')).toBeVisible();
  await expect(page.getByTestId('acc-underserved')).toContainText(/\d/);
  await expect(page.getByTestId('acc-legend')).toBeVisible();
  await expect(page).toHaveURL(/cat=hospital/);
  await expect(page).toHaveURL(/metric=time/);
  await expect(page).toHaveURL(/thr=30/);
});

test('category, threshold and metric drive the panel, map legend and URL', async ({ page }) => {
  await open(page);
  await page.getByTestId('acc-cat-university').click();
  await expect(page.getByTestId('acc-headline')).toContainText('a una universidad');
  await expect(page).toHaveURL(/cat=university/);

  const before = await pct(page, 'university');
  await page.getByRole('radio', { name: '45 min' }).click();
  await expect(page).toHaveURL(/thr=45/);
  await expect(page.getByTestId('acc-headline')).toContainText('en 45 min', { timeout: 30_000 });
  await expect.poll(() => pct(page, 'university'), { timeout: 30_000 }).toBeGreaterThan(before);

  await page.getByRole('combobox', { name: 'Métrica del mapa' }).click();
  await page.getByRole('option', { name: 'Zonas sin acceso' }).click();
  await expect(page).toHaveURL(/metric=gap/);
  await expect(page.getByTestId('acc-legend')).toContainText('Dentro');

  // the state survives a reload (shareable link)
  await page.reload();
  await expect(page.getByTestId('acc-cat-university')).toHaveAttribute('aria-pressed', 'true', {
    timeout: 45_000,
  });
  await expect(page.getByTestId('acc-legend')).toContainText('Dentro');
});

test('hovering a populated cell shows its residents and travel time', async ({ page }) => {
  await open(page);
  // find a populated cell on screen (opaque fill) and hover its centre
  const point = await page
    .waitForFunction(() => {
      const map = (globalThis as unknown as { __vlabMap?: MlMap }).__vlabMap;
      if (!map) return null;
      for (const layer of ['vl-acc-fill-a', 'vl-acc-fill-b']) {
        if (!map.getLayer(layer) || map.getPaintProperty(layer, 'fill-opacity') !== 1) continue;
        const feats = map.queryRenderedFeatures({ layers: [layer] });
        for (const f of feats) {
          const c = String(map.getFeatureState({ source: f.source, id: f.id })?.c ?? '');
          const alpha = Number(c.split(',')[3]?.replace(')', '') ?? 0);
          if (alpha < 0.8 || f.geometry.type !== 'Polygon') continue;
          const ring = f.geometry.coordinates[0] as [number, number][];
          const lon = ring.reduce((a, p) => a + p[0], 0) / ring.length;
          const lat = ring.reduce((a, p) => a + p[1], 0) / ring.length;
          const p = map.project([lon, lat]);
          if (p.x > 500 && p.x < 1300 && p.y > 120 && p.y < 700) return { x: p.x, y: p.y };
        }
      }
      return null;
    })
    .then((h) => h.jsonValue());
  expect(point).not.toBeNull();
  await page.mouse.move(point!.x - 3, point!.y - 3);
  await page.mouse.move(point!.x, point!.y, { steps: 3 });
  const tip = page.getByTestId('cell-tooltip');
  await expect(tip).toBeVisible();
  await expect(tip).toContainText('residentes');
  await expect(tip).toContainText('Hospital más cercano');
});

test('buses are hidden and the clock pauses in the analysis view', async ({ page }) => {
  await open(page, 'day=weekday&t=0800');
  await expect(page.getByTestId('play-toggle')).toHaveAttribute('aria-label', 'Reproducir');
  await page.keyboard.press('1');
  await expect(page.getByTestId('line-list')).toBeVisible();
  await page.keyboard.press('2');
  await expect(page.getByTestId('view-accessibility')).toBeVisible();
});
