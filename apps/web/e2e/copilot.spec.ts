import { test, expect } from '@playwright/test';

/**
 * WP-04 Task 9 mandatory E2E test: test_copilot_suggest_and_apply.
 *
 * Scenario (per WP-04 §3 Task 9):
 *   1. Open the app
 *   2. Select a project + flow
 *   3. Type "Add validation" in the co-pilot panel
 *   4. Click "Suggest"
 *   5. The plan approval dialog appears with a numbered plan
 *   6. Click "Approve & Execute"
 *   7. The patch preview dialog appears showing the applied changes
 *   8. The flow canvas shows the new validator node
 *
 * Prerequisites:
 *   - The Python API server (apps/server-python-prototype) must be
 *     running on localhost:8000.
 *   - The OIW_WORKSPACE env var must point to a directory containing
 *     the `order-to-s4` example project (with a git repo initialized
 *     so baseRevision validation passes — WP-04 Task 6).
 *
 * The tests are serial because they mutate the project state; running
 * them in parallel would cause baseRevision conflicts.
 */

test.describe.configure({ mode: 'serial' });

test('test_copilot_suggest_and_apply', async ({ page }) => {
  // 1. Open the app
  await page.goto('/');

  // Wait for the project list to load (the "Projects" section)
  const projectsSection = page.locator('.sidebar__section:has(.sidebar__title:has-text("Projects"))');
  await projectsSection.waitFor({ state: 'visible', timeout: 15_000 });
  await projectsSection.locator('.project-list__item').first().click();

  // Wait for the Flows section to populate, then click the first flow
  const flowsSection = page.locator('.sidebar__section:has(.sidebar__title:has-text("Flows"))');
  await flowsSection.locator('.project-list__item').first().waitFor({ state: 'visible', timeout: 15_000 });
  await flowsSection.locator('.project-list__item').first().click();

  // Wait for the canvas to render
  await page.waitForSelector('.react-flow__node', { timeout: 15_000 });

  // 3. Find the co-pilot panel and type a requirement
  const copilotInput = page.locator('.copilot-panel__input');
  await copilotInput.waitFor({ state: 'visible', timeout: 15_000 });
  await copilotInput.fill('Add validation to the order flow');

  // 4. Click "Suggest"
  const suggestButton = page.locator('.copilot-panel__submit');
  await suggestButton.click();

  // 5. The plan approval dialog should appear
  const planDialog = page.locator('.dialog--plan-approval');
  await planDialog.waitFor({ state: 'visible', timeout: 15_000 });

  // Verify the dialog has the expected structure
  await expect(planDialog.locator('.dialog__title')).toContainText('Proposed Plan');
  await expect(planDialog.locator('.plan-requirement')).toBeVisible();
  await expect(planDialog.locator('.plan-steps')).toBeVisible();

  // The plan should have at least one step
  const stepCount = await planDialog.locator('.plan-step').count();
  expect(stepCount).toBeGreaterThan(0);

  // 6. Click "Approve & Execute"
  const approveButton = planDialog.locator('button:has-text("Approve & Execute")');
  await approveButton.click();

  // 7. The patch preview dialog should appear
  const patchDialog = page.locator('.dialog--patch-preview');
  await patchDialog.waitFor({ state: 'visible', timeout: 15_000 });

  // Verify the patch dialog shows the changes
  await expect(patchDialog.locator('.dialog__title')).toContainText('Changes Applied');
  await expect(patchDialog.locator('.patch-summary')).toBeVisible();

  // 8. Close the patch dialog and verify the canvas updated
  await patchDialog.locator('.dialog__close').click();
  await patchDialog.waitFor({ state: 'hidden', timeout: 15_000 });

  // Wait for the canvas to refresh (the CoPilotPanel calls onApplied=refreshFlow)
  await page.waitForTimeout(1500);

  // Verify a validator node now exists on the canvas.
  // The fallback planner adds a node with id "validate-input" of type
  // "validator.json-schema". ReactFlow renders the node label from
  // the node data, which includes the step type.
  const validatorNode = page.locator('.react-flow__node:has-text("validate")');
  const validatorCount = await validatorNode.count();
  expect(validatorCount).toBeGreaterThan(0);
});

test('test_copilot_reject_plan', async ({ page }) => {
  // Verify the reject path: when the user clicks Reject, no patch
  // is applied and the dialog closes.
  await page.goto('/');

  const projectsSection = page.locator('.sidebar__section:has(.sidebar__title:has-text("Projects"))');
  await projectsSection.waitFor({ state: 'visible', timeout: 15_000 });
  await projectsSection.locator('.project-list__item').first().click();

  const flowsSection = page.locator('.sidebar__section:has(.sidebar__title:has-text("Flows"))');
  await flowsSection.locator('.project-list__item').first().waitFor({ state: 'visible', timeout: 15_000 });
  await flowsSection.locator('.project-list__item').first().click();
  await page.waitForSelector('.react-flow__node', { timeout: 15_000 });

  // Count nodes before
  const beforeCount = await page.locator('.react-flow__node').count();

  // Type + suggest
  await page.locator('.copilot-panel__input').fill('Add validation to the order flow');
  await page.locator('.copilot-panel__submit').click();

  const planDialog = page.locator('.dialog--plan-approval');
  await planDialog.waitFor({ state: 'visible', timeout: 15_000 });

  // Click Reject
  await planDialog.locator('button:has-text("Reject")').click();
  await planDialog.waitFor({ state: 'hidden', timeout: 15_000 });

  // Verify no new nodes were added
  const afterCount = await page.locator('.react-flow__node').count();
  expect(afterCount).toBe(beforeCount);
});
