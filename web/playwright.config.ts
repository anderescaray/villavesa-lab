import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

// End-to-end tests run against the REAL backend: Playwright starts the FastAPI engine (uvicorn,
// repo root, synchronous load) and a Vite dev server that proxies /api to it. The basemap is
// blank (VITE_BASEMAP=none) so tests never depend on external tiles.
const port = Number(process.env.E2E_PORT ?? 3100);
const apiPort = Number(process.env.E2E_API_PORT ?? 8100);
const repoRoot = fileURLToPath(new URL('..', import.meta.url));

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${port}`,
    viewport: { width: 1440, height: 900 },
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  webServer: [
    {
      command: `uv run uvicorn vlab_api.main:app --port ${apiPort}`,
      cwd: repoRoot,
      url: `http://localhost:${apiPort}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      env: { VLAB_SYNC_LOAD: '1' },
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      command: `npx vite --port ${port} --strictPort`,
      url: `http://localhost:${port}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { VITE_BASEMAP: 'none', VITE_API_PROXY: `http://localhost:${apiPort}` },
    },
  ],
});
