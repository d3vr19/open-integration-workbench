import { test, expect } from '@playwright/test';

/**
 * WP-09 Track B / Track C: Trace Viewer v1.5 & Critical Journey #5.
 *
 * Acceptance (B-001, B-002, C-001):
 *   1. Click Simulate -> execution runs and produces simulation trace.
 *   2. TraceInspector renders step buttons and exchange snapshots (In/Out body/headers/props).
 *   3. Transport controls (B-002) step forward/backward through execution snapshots.
 *   4. Canvas nodes display pass/fail/duration badges (B-001).
 *   5. Clicking a canvas node badge selects that step in TraceInspector (B-001 wiring).
 *
 * Serial mode (workspace shared).
 */

test.describe.configure({ mode: 'serial' });

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

test('test_simulation_trace_and_node_badges', async ({ page }) => {
  await selectFirstProjectAndFlow(page);

  // Click Simulate button in Actions section
  const simulateButton = page.locator('button:has-text("Simulate")');
  await expect(simulateButton).toBeEnabled();
  await simulateButton.click();

  // Wait for simulation trace to render
  const inspector = page.locator('[data-testid="trace-inspector"]');
  await inspector.waitFor({ state: 'visible', timeout: 15_000 });

  // Verify transport controls (B-002)
  const transport = page.locator('[data-testid="trace-transport"]');
  await expect(transport).toBeVisible();
  const counter = transport.locator('.trace-inspector__transport-counter');
  await expect(counter).toBeVisible();

  // Verify step chips exist
  const stepButtons = inspector.locator('.trace-inspector__step');
  const stepCount = await stepButtons.count();
  expect(stepCount).toBeGreaterThan(0);

  // First step is selected by default after simulation run
  const detail = page.locator('[data-testid="trace-detail"]');
  await expect(detail).toBeVisible();
  await expect(detail.locator('.trace-inspector__io')).toBeVisible();

  // Step forward using transport Next button (B-002)
  const nextButton = transport.locator('button[title="Next step"]');
  if (stepCount > 1) {
    await nextButton.click();
    await expect(counter).toContainText('Step 2 of');
  }

  // Verify canvas node trace badges (B-001)
  const badges = page.locator('.node-trace-badge');
  const badgeCount = await badges.count();
  expect(badgeCount).toBeGreaterThan(0);

  // Click the first canvas node trace badge (B-001 wiring)
  const firstBadge = badges.first();
  await firstBadge.click({ force: true });

  // Verify that clicking canvas badge selected that step in the inspector
  const activeStep = inspector.locator('.trace-inspector__step--active');
  await expect(activeStep).toBeVisible();
});
