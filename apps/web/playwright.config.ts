import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for the OIW web app (WP-04 Task 9).
 *
 * The E2E test starts the Vite dev server (port 5173) and expects the
 * Python API server (apps/server-python-prototype) to be running on
 * port 8000. The dev server proxies /api/* to the API server
 * (see vite.config.ts).
 *
 * For CI: the workflow should start both servers before running
 * `npx playwright test`. For local dev: run `oiw-server` in one
 * terminal, `npm run dev` in another, then `npx playwright test`.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,        // tests mutate shared state (the project)
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,                  // single worker — tests share the workspace
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
