import { expect, test, type Page } from '@playwright/test';

// Runs against the mock API with a blank basemap (VITE_MOCK_API=1, VITE_BASEMAP=none): no
// dependency on external tiles or the Python backend.

async function open(page: Page, hash = '#/network?day=weekday&t=0800&play=0&lang=es') {
  await page.addInitScript(() => {
    localStorage.setItem('vlab.prefs', JSON.stringify({ themePref: 'light', lang: 'es' }));
    localStorage.setItem('vlab.isoHintSeen', '1');
  });
  await page.goto(`/${hash}`);
  await expect(page.getByTestId('line-list').getByRole('button').first()).toBeVisible();
}

test('loads the map, the line list and buses in service', async ({ page }) => {
  await open(page);
  await expect(page.getByTestId('map')).toBeVisible();
  await expect(page.locator('.maplibregl-canvas')).toBeVisible();
  await expect(page.getByTestId('line-row-L04')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Red actual' })).toBeVisible();
  await expect(page.getByTestId('clock')).toHaveText('08:00');
  await expect
    .poll(async () =>
      Number((await page.getByTestId('bus-count').textContent())?.replace(/\D/g, '')),
    )
    .toBeGreaterThan(50);
});

test('play and pause drive the clock', async ({ page }) => {
  await open(page);
  const clock = page.getByTestId('clock');
  await expect(clock).toHaveText('08:00');
  await page.getByTestId('play-toggle').click();
  await expect(clock).not.toHaveText('08:00', { timeout: 5000 });
  await page.getByTestId('play-toggle').click();
  const paused = await clock.textContent();
  await page.waitForTimeout(1500);
  await expect(clock).toHaveText(paused ?? '');
  // keyboard: arrow steps 5 minutes when paused
  await page.keyboard.press('ArrowRight');
  await expect(clock).not.toHaveText(paused ?? '');
});

test('selecting a line shows its details and stops', async ({ page }) => {
  await open(page);
  await page.getByTestId('line-row-L04').click();
  const detail = page.getByTestId('line-detail');
  await expect(detail).toBeVisible();
  await expect(detail.getByRole('heading', { name: /Barañáin - Villava/ })).toBeVisible();
  await expect(detail.getByText('Velocidad comercial')).toBeVisible();
  await expect(page.getByTestId('line-stops').locator('li')).not.toHaveCount(0);
  await expect(page).toHaveURL(/line=4/);
  await page.getByTestId('line-back').click();
  await expect(page.getByTestId('line-list')).toBeVisible();
});

test('search filters the line list', async ({ page }) => {
  await open(page);
  await page.keyboard.press('/');
  await expect(page.getByTestId('line-search')).toBeFocused();
  await page.keyboard.type('mendillorri');
  await expect(page.getByTestId('line-row-L12')).toBeVisible();
  await expect(page.getByTestId('line-row-L01')).toHaveCount(0);
});

test('clicking the map shows an isochrone card; Esc dismisses it', async ({ page }) => {
  await open(page);
  // hide all lines so the click lands on empty map, not on a line
  await page.getByRole('button', { name: /Diurnas/ }).click();
  await page.getByRole('button', { name: /Nocturnas/ }).click();
  const box = (await page.getByTestId('map').boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.62, box.y + box.height * 0.45);
  const card = page.getByTestId('iso-card');
  await expect(card).toBeVisible();
  await expect(card.getByText('Hasta dónde llegas')).toBeVisible();
  await expect(page.getByTestId('iso-band-30')).toContainText(/\d/);
  await expect(card.getByText('Hospitales')).toBeVisible();
  await expect(page.getByTestId('iso-pin')).toBeVisible();
  await expect(page).toHaveURL(/iso=/);
  await card.getByRole('radio', { name: 'A pie', exact: true }).click();
  await expect(page).toHaveURL(/mode=walk/);
  await page.keyboard.press('Escape');
  await expect(card).toHaveCount(0);
});

test('language toggle switches the copy', async ({ page }) => {
  await open(page);
  await page.getByRole('radio', { name: 'English' }).click();
  await expect(page.getByRole('heading', { name: "Today's network" })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await page.getByRole('radio', { name: 'Euskara' }).click();
  await expect(page.getByRole('heading', { name: 'Gaurko sarea' })).toBeVisible();
});

test('theme toggle switches to dark and back', async ({ page }) => {
  await open(page);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.getByRole('radio', { name: 'Oscuro' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.keyboard.press('t'); // dark → system
  await page.getByRole('radio', { name: 'Claro' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});

test('other views show designed empty states; shortcuts dialog opens with ?', async ({ page }) => {
  await open(page);
  await page.keyboard.press('2');
  await expect(page.getByTestId('view-accessibility')).toBeVisible();
  await page.getByTestId('nav-optimizer').click();
  await expect(page.getByTestId('view-optimizer')).toContainText('presupuesto');
  await page.getByRole('button', { name: 'Explorar la red actual' }).click();
  await expect(page.getByTestId('line-list')).toBeVisible();
  await page.keyboard.press('?');
  await expect(page.getByTestId('shortcuts-dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('shortcuts-dialog')).toHaveCount(0);
});

test('API errors show a calm inline message with retry', async ({ page }) => {
  await open(page, '#/network?day=weekday&t=0800&play=0');
  await page.goto('/#/network?day=sunday&t=0800&play=0&mock_fail=1');
  await page.reload();
  await expect(page.getByTestId('network-error')).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole('button', { name: 'Reintentar' })).toBeVisible();
});
