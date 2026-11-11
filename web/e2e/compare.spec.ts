import { expect, test, type Page } from '@playwright/test';

// Compare / report view against the real engine, with a small hand-made scenario in the store.

const SCENARIO = [
  { type: 'scale_frequency', route_id: '1', factor: 1.5, period: 'all' },
  { type: 'scale_frequency', route_id: '10', factor: 0.67, period: 'all' },
];

async function open(page: Page, withScenario: boolean) {
  await page.addInitScript(
    ([edits, seed]) => {
      localStorage.setItem('vlab.prefs', JSON.stringify({ themePref: 'light', lang: 'es' }));
      localStorage.setItem('vlab.isoHintSeen', '1');
      if (seed)
        localStorage.setItem(
          'vlab.scenario.v1',
          JSON.stringify({ state: { edits, name: 'Prueba de comparación' }, version: 1 }),
        );
    },
    [SCENARIO, withScenario] as const,
  );
  await page.goto('/#/compare?day=weekday&t=0800&play=0');
}

test('without a scenario it shows a designed empty state with two entry points', async ({
  page,
}) => {
  await open(page, false);
  await expect(page.getByTestId('compare-empty')).toBeVisible({ timeout: 60_000 });
  await page.getByTestId('compare-open-optimizer').click();
  await expect(page.getByTestId('view-optimizer')).toBeVisible();
});

test('shows the before/after table and a keyboard-operable swipe divider', async ({ page }) => {
  await open(page, true);
  await expect(page.getByTestId('compare-title')).toContainText('Prueba de comparación', {
    timeout: 60_000,
  });
  await expect(page.getByTestId('compare-table')).toBeVisible({ timeout: 90_000 });
  await expect(page.getByTestId('row-fleet')).toBeVisible();
  await expect(page.getByTestId('row-meanTime')).toBeVisible();
  await expect(page.getByTestId('compare-people')).toContainText(/ganan acceso/i);
  await expect(page.getByTestId('compare-routes')).toBeVisible();

  const divider = page.getByTestId('compare-divider');
  await expect(divider).toBeVisible();
  await expect(page.getByTestId('compare-label-before')).toHaveText('Hoy');
  await expect(page.getByTestId('compare-label-after')).toHaveText('Prueba de comparación');
  const before = Number(await divider.getAttribute('aria-valuenow'));
  await divider.focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect(divider).toHaveAttribute('aria-valuenow', String(before + 4));
  await page.keyboard.press('Home');
  await expect(divider).toHaveAttribute('aria-valuenow', '2');

  // modes
  await page.getByRole('radio', { name: 'Diferencia' }).click();
  await expect(page.getByTestId('compare-stage')).toHaveAttribute('data-mode', 'delta');
  await expect(page.getByTestId('compare-divider')).toHaveCount(0);
});

test('the report request returns self-contained HTML containing the title', async ({ page }) => {
  await open(page, true);
  await expect(page.getByTestId('compare-table')).toBeVisible({ timeout: 90_000 });
  await page.getByTestId('report-title').fill('Informe de prueba e2e');
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith('/api/report') && r.request().method() === 'POST',
      { timeout: 90_000 },
    ),
    page.getByTestId('report-download').click(),
  ]);
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toContain('text/html');
  const html = await response.text();
  expect(html).toContain('Informe de prueba e2e');
  expect(html.toLowerCase()).toContain('<html');
});
