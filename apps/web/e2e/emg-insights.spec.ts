import { test, expect } from '@playwright/test';

/**
 * WP-08 PR-10 / OW-032 mandatory E2E: the EMG panel tells the truth.
 *
 * Acceptance (per OW-032):
 *   1. The insights panel renders REAL counts that match GET /emg/stats
 *      and GET /projects/{id}/emg/insights — whatever the durable store
 *      holds (empty or seeded), UI and API must agree.
 *   2. The ⚡ EMG-hit badge is driven by the agents:plan response's `emg`
 *      block: visible iff emg.used === true. Never a hardcoded value.
 *
 * Prerequisites (same as copilot.spec.ts):
 *   - Python API server on localhost:8000 with OIW_WORKSPACE containing
 *     the order-to-s4 example.
 *
 * Serial mode shared with copilot.spec.ts (mutating tests).
 */

test.describe.configure({ mode: 'serial' });

interface EmgStatsResponse {
  totalTrajectories: number;
  approvedInsights: number;
  embeddingBackend: string;
}

async function selectFirstProjectAndFlow(page: import('@playwright/test').Page) {
  await page.goto('/');
  const projectsSection = page.locator('.sidebar__section:has(.sidebar__title:has-text("Projects"))');
  await projectsSection.waitFor({ state: 'visible', timeout: 15_000 });
  await projectsSection.locator('.project-list__item').first().click();
  const flowsSection = page.locator('.sidebar__section:has(.sidebar__title:has-text("Flows"))');
  await flowsSection.locator('.project-list__item').first().waitFor({ state: 'visible', timeout: 15_000 });
  await flowsSection.locator('.project-list__item').first().click();
  await page.waitForSelector('.react-flow__node', { timeout: 15_000 });
}

test('test_emg_panel_matches_api_truth', async ({ page, request }) => {
  await selectFirstProjectAndFlow(page);

  // The API's numbers are ground truth
  const statsResp = await request.get('/api/v1/emg/stats');
  expect(statsResp.ok()).toBeTruthy();
  const stats = (await statsResp.json()) as EmgStatsResponse;

  const panel = page.locator('.emg-panel');
  await panel.waitFor({ state: 'visible', timeout: 15_000 });

  // The trajectories chip shows exactly what /emg/stats reports
  if (stats.totalTrajectories > 0) {
    await expect(panel.locator('.emg-stats__item').first()).toContainText(
      `${stats.totalTrajectories} trajectories`,
    );
    // OW-032 honesty chips: backend + compatibility surfaced from the manifest
    if (stats.embeddingBackend) {
      await expect(panel.locator('[data-testid="emg-backend-chip"]')).toContainText(
        stats.embeddingBackend,
      );
    }
  } else {
    // Fresh workspace: the empty-state message is the honest answer
    await expect(panel.locator('p.muted')).toBeVisible();
  }

  // With no co-pilot round-trip yet, the badge must NOT be visible
  // (nothing has claimed an EMG hit in this session).
  await expect(panel.locator('[data-testid="emg-hit-badge"]')).toHaveCount(0);
});

test('test_emg_hit_badge_is_truthful_to_plan_response', async ({ page }) => {
  await selectFirstProjectAndFlow(page);

  const planResponsePromise = page.waitForResponse((resp) =>
    resp.url().includes('/agents:plan'),
  );

  await page.locator('.copilot-panel__input').fill('Add JSON schema validation to the flow');
  await page.locator('.copilot-panel__submit').click();

  const planResponse = await planResponsePromise;
  expect(planResponse.ok()).toBeTruthy();
  const body = (await planResponse.json()) as { emg?: { used: boolean } | null };
  const serverSaysUsed = body.emg?.used === true;

  // INVARIANT: badge visibility === server's claim. This passes whether
  // the workspace store is seeded (hit) or fresh (no hit) — it can only
  // fail if the UI lies about the response.
  const panel = page.locator('.emg-panel');
  const dialog = page.locator('.dialog--plan-approval');
  await dialog.waitFor({ state: 'visible', timeout: 15_000 });

  if (serverSaysUsed) {
    await expect(panel.locator('[data-testid="emg-hit-badge"]')).toBeVisible();
    await expect(panel.locator('[data-testid="emg-hit-details"]')).toBeVisible();
  } else {
    await expect(panel.locator('[data-testid="emg-hit-badge"]')).toHaveCount(0);
  }

  // Clean up: reject the plan so later serial tests start clean
  await dialog.locator('button:has-text("Reject")').click();
  await dialog.waitFor({ state: 'hidden', timeout: 15_000 });
});
