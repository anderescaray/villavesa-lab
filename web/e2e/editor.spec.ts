import { expect, test, type Page } from '@playwright/test';

// Scenario editor (M8) against the real engine: frequency edit + live impact, undo/redo, the
// global scenario chip, bus priority from the stop list, and drawing a street-snapped line.

interface VlabWindow {
  __vlabMap: {
    project: (p: [number, number]) => { x: number; y: number };
    jumpTo: (o: { center: [number, number]; zoom: number }) => void;
  };
}

async function open(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('vlab.prefs', JSON.stringify({ themePref: 'light', lang: 'es' }));
    localStorage.setItem('vlab.isoHintSeen', '1');
    if (!sessionStorage.getItem('vlab.e2e.init')) {
      localStorage.removeItem('vlab.scenario.v1');
      sessionStorage.setItem('vlab.e2e.init', '1');
    }
  });
  await page.goto('/#/scenario?day=weekday&t=0800&play=0&lang=es');
  await expect(page.getByTestId('view-scenario')).toBeVisible();
}

async function clickLonLat(page: Page, lon: number, lat: number) {
  const box = (await page.getByTestId('map').boundingBox())!;
  const p = await page.evaluate(
    ([x, y]) => (globalThis as unknown as VlabWindow).__vlabMap.project([x!, y!]),
    [lon, lat],
  );
  await page.mouse.click(box.x + p.x, box.y + p.y);
}

test('frequency edit shows the live impact, the scenario chip and supports undo/redo', async ({
  page,
}) => {
  await open(page);
  await expect(page.getByTestId('editor-entries')).toBeVisible();
  await expect(page.getByTestId('tool-palette')).toBeVisible();
  await page.keyboard.press('f');
  await expect(page.getByTestId('tool-hint')).toContainText('frecuencia');
  await page.getByTestId('line-picker').getByRole('button', { name: /^L04/ }).click();
  await expect(page.getByTestId('frequency-inspector')).toBeVisible();
  const input = page.getByTestId('headway-input');
  await input.fill('4');
  await input.press('Enter');
  await expect(page.getByTestId('change-row')).toHaveCount(1);
  await expect(page.getByTestId('change-row').first()).toContainText('cada 4 min');
  await expect(page.getByTestId('scenario-chip')).toContainText('1 cambio');
  await expect(page.getByTestId('impact-card')).toBeVisible();
  await expect
    .poll(async () =>
      Number((await page.getByTestId('people-gaining').textContent())?.replace(/\D/g, '')),
    )
    .toBeGreaterThan(0);
  await expect(page.getByTestId('route-resources')).toContainText('→');

  await page.getByTestId('map').click({ position: { x: 900, y: 120 } }); // blur inputs
  await page.keyboard.press('Control+z');
  await expect(page.getByTestId('change-row')).toHaveCount(0);
  await expect(page.getByTestId('scenario-chip')).toHaveCount(0);
  await page.keyboard.press('Control+Shift+z');
  await expect(page.getByTestId('change-row')).toHaveCount(1);

  // the scenario persists across a reload and is shown in other views
  await page.reload();
  await expect(page.getByTestId('change-row')).toHaveCount(1);
  await page.keyboard.press('1');
  await expect(page.getByTestId('scenario-chip')).toBeVisible();
  await page.getByTestId('scenario-peek').click();
  await expect(page.getByTestId('scenario-chip')).toContainText('red actual');
});

test('bus priority between two stops of a line', async ({ page }) => {
  await open(page);
  await page.getByTestId('tool-priority').click();
  await page.getByTestId('line-picker').getByRole('button', { name: /^L16/ }).click();
  const stops = page.getByTestId('priority-inspector').getByRole('listitem');
  await stops.nth(2).click();
  await stops.nth(8).click();
  await expect(page.getByTestId('priority-inspector')).toContainText('6 tramos');
  await page.getByTestId('priority-apply').click();
  await expect(page.getByTestId('change-row').first()).toContainText('Prioridad');
  await expect(page.getByTestId('impact-error')).toHaveCount(0);
});

test('draws a new line snapped to streets with proposed stops', async ({ page }) => {
  await open(page);
  await page.keyboard.press('l');
  await expect(page.getByTestId('draw-inspector')).toBeVisible();
  await page.evaluate(() =>
    (globalThis as unknown as VlabWindow).__vlabMap.jumpTo({ center: [-1.637, 42.812], zoom: 14 }),
  );
  await clickLonLat(page, -1.6447, 42.8169);
  await clickLonLat(page, -1.635, 42.812);
  await clickLonLat(page, -1.63, 42.805);
  await expect(page.getByTestId('draft-length')).toContainText('km');
  await expect(page.getByTestId('draft-stops').getByRole('listitem').nth(1)).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('change-row').first()).toContainText('Línea A');
  await expect(page.getByTestId('impact-error')).toHaveCount(0);
  await expect
    .poll(async () => (await page.getByTestId('people-gaining').textContent()) ?? '')
    .toMatch(/\d/);
});
