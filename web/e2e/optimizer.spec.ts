import { expect, test, type Page } from '@playwright/test';

// Optimizer view against the real engine: a short frequency-only run (10 s budget) reaches a
// result, "Apply as scenario" fills the scenario store, and the settings behave.

declare global {
  interface Window {
    __vlabOptimizer?: {
      getState: () => {
        setSettings: (p: Record<string, unknown>) => void;
        last: { result: { scenario: unknown[] } } | null;
      };
    };
  }
}

async function open(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('vlab.prefs', JSON.stringify({ themePref: 'light', lang: 'es' }));
    localStorage.setItem('vlab.isoHintSeen', '1');
  });
  await page.goto('/#/optimizer?day=weekday&t=0800&play=0');
  await expect(page.getByTestId('opt-question')).toBeVisible({ timeout: 60_000 });
}

test('setup states the question in plain language and the analysis window', async ({ page }) => {
  await open(page);
  await expect(page.getByTestId('opt-question')).toContainText(/Con los mismos \d+ buses/);
  await expect(page.getByTestId('opt-window')).toContainText('Laborable, 08:00–09:00');
  await expect(page.getByTestId('opt-budget-value')).toHaveText('Igual que hoy');
  // frequencies on by default, new lines off
  await expect(page.getByRole('switch').first()).toBeChecked();
  // the budget slider changes the question
  const slider = page.getByRole('slider', { name: /presupuesto/i });
  await slider.focus();
  await page.keyboard.press('ArrowLeft');
  await expect(page.getByTestId('opt-question')).toContainText(/^Con \d+ buses/);
  // at least one move is required
  await page.getByRole('switch').first().click();
  await expect(page.getByTestId('opt-run')).toBeDisabled();
});

test('a frequency-only run reaches a result and can be applied as a scenario', async ({ page }) => {
  test.setTimeout(180_000);
  await open(page);
  await page.evaluate(() =>
    (
      globalThis as unknown as {
        __vlabOptimizer: { getState: () => { setSettings: (p: object) => void } };
      }
    ).__vlabOptimizer
      .getState()
      .setSettings({ timeLimit: 10 }),
  );
  await page.getByTestId('opt-run').click();
  await expect(page.getByTestId('opt-running')).toBeVisible();
  await expect(page.getByTestId('opt-result')).toBeVisible({ timeout: 150_000 });

  // headline in plain language with the budget, the key deltas and the explanation
  await expect(page.getByTestId('opt-headline')).toContainText(/accesibilidad|mejor/i);
  await expect(page.getByTestId('opt-kpis')).toContainText('Tiempo medio de viaje');
  await expect(page.getByTestId('opt-lines').locator('button').first()).toBeVisible();
  await expect(page.getByTestId('opt-legend')).toBeVisible();

  // hovering an explanation item highlights the line on the map (store focus)
  await page.getByTestId('opt-lines').locator('button').first().hover();

  await page.getByTestId('opt-apply').click();
  const edits = await page.evaluate(
    () =>
      (
        JSON.parse(localStorage.getItem('vlab.scenario.v1') ?? '{}') as {
          state?: { edits?: unknown[]; name?: string };
        }
      ).state,
  );
  expect(edits?.edits?.length).toBeGreaterThan(0);
  expect(edits?.name).toMatch(/Optimizado/);

  // the result survives a reload
  await page.reload();
  await expect(page.getByTestId('opt-result')).toBeVisible({ timeout: 30_000 });
});
