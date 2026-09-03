import { test, expect } from '@playwright/test';

/**
 * WP-09 & WP-10 E2E Journey Suite (OW-012 completion: 10/10 Journeys).
 *
 * Automates:
 *   - Critical Journey #4 / #6: Validate and Test Runner execution and result panels.
 *   - Critical Journey #7: Monaco Resource Editor view, metadata, and close navigation.
 *   - Critical Journey #8: Canvas node selection and Node Properties panel mounting.
 *   - Critical Journey #9: Dirty state indicator + Save -> PATCH round-trip.
 *   - Critical Journey #10: Track D Experiments, Laws Registry, and Tenant-MPL Comparison (UI == API truth).
 *
 * Runs serial against fixture copy at /tmp/oiw-ui-workspace.
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

test('test_journey_validation_and_test_runner', async ({ page }) => {
  await selectFirstProjectAndFlow(page);

  // 1. Validate Journey
  const validateBtn = page.locator('button:has-text("Validate")');
  await expect(validateBtn).toBeEnabled();
  await validateBtn.click();

  const validationSection = page.locator('.sidebar__section:has(.sidebar__title:has-text("Validation"))');
  await validationSection.waitFor({ state: 'visible', timeout: 15_000 });
  const badge = validationSection.locator('.sidebar__title .badge');
  const badgeText = await badge.innerText();
  expect(['PASS', 'FAIL']).toContain(badgeText);
  if (badgeText === 'FAIL') {
    await expect(validationSection.locator('.validation-item--error').first()).toBeVisible();
  }

  // 2. Test Runner Journey
  const runTestsBtn = page.locator('button:has-text("Run Tests")');
  await expect(runTestsBtn).toBeEnabled();
  await runTestsBtn.click();

  const testsSection = page.locator('.sidebar__section:has(.sidebar__title:has-text("Tests"))');
  await testsSection.waitFor({ state: 'visible', timeout: 15_000 });
  const testItems = testsSection.locator('.test-item');
  await expect(testItems.first()).toBeVisible();
  const testCount = await testItems.count();
  expect(testCount).toBeGreaterThan(0);
});

test('test_journey_resource_editor', async ({ page }) => {
  await selectFirstProjectAndFlow(page);

  // Locate Resources section in Left Sidebar
  const resourcesSection = page.locator('.sidebar__section:has(.sidebar__title:has-text("Resources"))');
  await resourcesSection.waitFor({ state: 'visible', timeout: 15_000 });

  // Click groovy script resource item
  const groovyItem = resourcesSection.locator('.resource-list__item:has-text("normalizeOrder.groovy")');
  await expect(groovyItem).toBeVisible();
  await groovyItem.click();

  // Resource Editor mounts in main canvas area
  const resourceEditor = page.locator('.resource-editor');
  await resourceEditor.waitFor({ state: 'visible', timeout: 15_000 });
  await expect(resourceEditor.locator('.resource-editor__name')).toHaveText('normalizeOrder.groovy');
  await expect(resourceEditor.locator('.badge--mono')).toHaveText('groovy');

  // Close resource editor and return to canvas
  const closeBtn = resourceEditor.locator('button:has-text("Close")');
  await closeBtn.click();
  await expect(resourceEditor).not.toBeVisible();
  await expect(page.locator('.canvas-container')).toBeVisible();
});

test('test_journey_node_selection_and_properties', async ({ page }) => {
  await selectFirstProjectAndFlow(page);

  // Click the first canvas node
  const node = page.locator('.react-flow__node').first();
  await expect(node).toBeVisible();
  await node.click({ force: true });

  // Assert Node Properties panel opens in Right Sidebar
  const propertiesPanel = page.locator('.sidebar__section:has(.sidebar__title:has-text("Node Properties"))');
  await propertiesPanel.waitFor({ state: 'visible', timeout: 10_000 });

  const idInput = propertiesPanel.locator('.properties__input');
  await expect(idInput).toBeVisible();
  const idValue = await idInput.inputValue();
  expect(idValue.length).toBeGreaterThan(0);
});

test('test_journey_dirty_state_and_save_patch', async ({ page }) => {
  await selectFirstProjectAndFlow(page);

  // Click node to open Properties
  const node = page.locator('.react-flow__node').first();
  await node.click({ force: true });

  const propertiesPanel = page.locator('.sidebar__section:has(.sidebar__title:has-text("Node Properties"))');
  await propertiesPanel.waitFor({ state: 'visible', timeout: 10_000 });

  const configInput = propertiesPanel.locator('.config-editor__input').first();
  await configInput.waitFor({ state: 'visible', timeout: 5000 });
  const originalVal = await configInput.inputValue();

  // Modify config to trigger dirty state and pending op
  await configInput.fill(`${originalVal}-mod`);

  // Assert dirty badge and Save button appear in header
  const dirtyBadge = page.locator('.app__header .badge--warn:has-text("unsaved changes")');
  await expect(dirtyBadge).toBeVisible();

  const saveBtn = page.locator('.app__header button:has-text("Save")');
  await expect(saveBtn).toBeVisible();
  await expect(saveBtn).toBeEnabled();

  // Save changes via PATCH
  await saveBtn.click();

  // Assert dirty badge clears
  await expect(dirtyBadge).not.toBeVisible({ timeout: 10_000 });
});

test('test_journey_track_d_experiments_and_laws', async ({ page, request }) => {
  await selectFirstProjectAndFlow(page);

  // 1. Assert Experiments panel matches API truth
  const expResp = await request.get('/api/v1/experiments');
  expect(expResp.ok()).toBeTruthy();
  const experiments = await expResp.json();

  const expPanel = page.locator('[data-testid="experiments-panel"]');
  await expPanel.waitFor({ state: 'visible', timeout: 15_000 });

  if (experiments.length > 0) {
    const campaignList = expPanel.locator('[data-testid="experiment-campaign-list"]');
    await expect(campaignList).toBeVisible();
    await expect(expPanel.locator('[data-testid="experiment-id"]').first()).toHaveText(experiments[0].experimentId);
    await expect(expPanel.locator('[data-testid="baseline-verdict-badge"]').first()).toHaveText(experiments[0].baselineVerdict);
    await expect(expPanel.locator('[data-testid="tally-green"]').first()).toContainText(`${experiments[0].greenCount} green`);

    // Verify rung evidence stamped with targetType
    const detail = expPanel.locator('[data-testid="experiment-detail"]');
    await expect(detail).toBeVisible();
    const rungs = detail.locator('[data-testid="rungs-list"]');
    await expect(rungs).toBeVisible();
    const targetTypeChip = detail.locator('[data-testid="evidence-target-type"]').first();
    if (await targetTypeChip.isVisible()) {
      await expect(targetTypeChip).toContainText('target:');
    }
  } else {
    await expect(expPanel.locator('[data-testid="experiments-empty"]')).toBeVisible();
  }

  // 2. Assert Law Registry panel matches API truth
  const lawsResp = await request.get('/api/v1/laws');
  expect(lawsResp.ok()).toBeTruthy();
  const laws = await lawsResp.json();

  const lawPanel = page.locator('[data-testid="law-registry-panel"]');
  await lawPanel.waitFor({ state: 'visible', timeout: 15_000 });

  if (laws.length > 0) {
    const lawCards = lawPanel.locator('[data-testid="laws-list"] [data-testid^="law-card-"]');
    await expect(lawCards.first()).toBeVisible();
    expect(await lawCards.count()).toBe(laws.length);

    // Filter test
    const ratifiedFilter = lawPanel.locator('[data-testid="filter-status-ratified"]');
    await ratifiedFilter.click();
    const ratifiedLaws = laws.filter((l: any) => l.status === 'ratified');
    await expect(lawPanel.locator('[data-testid="law-count-badge"]')).toContainText(`${ratifiedLaws.length}`);
  }

  // 3. Tenant MPL comparison view interaction against committed calibration fixture
  const compareBtn = page.locator('[data-testid="btn-open-mpl-compare"]');
  await expect(compareBtn).toBeVisible();
  await compareBtn.click();
  const mplView = page.locator('[data-testid="mpl-comparison-view"]');
  await expect(mplView).toBeVisible();
  await expect(page.locator('[data-testid="mpl-col-local"]')).toBeVisible();
  await expect(page.locator('[data-testid="mpl-col-tenant"]')).toBeVisible();
  await expect(page.locator('[data-testid="mpl-epoch-boundary"]')).toBeVisible();
  await expect(page.locator('[data-testid="tenant-final-status"]')).toHaveText('STARTED');
  await expect(page.locator('[data-testid="mpl-row-current"]').first()).toBeVisible();
  await page.locator('[data-testid="mpl-close-btn"]').click();
  await expect(mplView).not.toBeVisible();
});
