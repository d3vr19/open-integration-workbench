import { test, expect } from '@playwright/test';

/**
 * WP-09 Track C: E2E Hardening & Critical Journeys (C-001).
 *
 * Automates:
 *   - Critical Journey #4 / #6: Validate and Test Runner execution and result panels.
 *   - Critical Journey #7: Monaco Resource Editor view, metadata, and close navigation.
 *
 * Runs serial against fixture copy at /tmp/oiw-ui-workspace/order-to-s4.
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
