const { test, expect } = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

async function openApp(page) {
  await page.goto('/');
  await expect(page.locator('#runBtn')).toBeEnabled();
  await expect(page.locator('#modeBanner')).toContainText(/offline/i);
}

async function screen(page) {
  await page.locator('#topK').selectOption('1');
  const pending = page.waitForResponse(
    (r) => r.url().endsWith('/screen') && r.request().method() === 'POST',
  );
  await page.locator('#runBtn').click();
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.headers()['x-request-id']).toMatch(/^[a-f0-9]{32}$/);
  const data = await response.json();
  expect(data.result_status).toBe('OK');
  await expect(page.locator('#results')).toBeVisible();
  await page
    .locator('.trial-card > details > summary')
    .filter({ hasText: 'Criteria & evidence' })
    .first()
    .click();
  return data;
}

async function editFirst(
  page,
  reason = 'Reviewed the synthetic source record for this demonstration.',
) {
  const criterion = page.locator('.criterion').first();
  await criterion.locator('.human-review > summary').click();
  const original = await criterion.locator('.human-decision').inputValue();
  const decision = original === 'MET' ? 'NOT_MET' : 'MET';
  await criterion.getByLabel('Your assessment', { exact: true }).selectOption(decision);
  await criterion.getByLabel('Reason for review', { exact: true }).fill(reason);
  await criterion.getByRole('button', { name: 'Apply local review', exact: true }).click();
  return { criterion, original, decision };
}

test('real backend: review export preserves the original response and evidence', async ({
  page,
}) => {
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  await openApp(page);
  const source = await screen(page);
  const reason = 'Source reviewed: <img src=x onerror="alert(1)"> is literal annotation text.';
  const { criterion, original, decision } = await editFirst(page, reason);
  await expect(criterion.locator('.human-review-status')).toContainText(
    `Human assessment: ${decision}`,
  );
  await expect(criterion.locator('.criterion-head .status')).toContainText(original);
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  await expect(page.locator('.human-review-count')).toHaveText(
    '1 criterion review(s) applied locally',
  );
  await expect(page.locator('.human-review-banner')).toContainText('Not saved to the server');

  await page.locator('#responseJson').click();
  expect(JSON.parse(await page.locator('#jsonPreview').innerText())).toEqual(source);
  await page.locator('#closeDialog').click();
  await page.getByRole('button', { name: 'Export human review', exact: true }).click();
  const review = JSON.parse(await page.locator('#jsonPreview').innerText());
  expect(review.source_run_id).toBe(source.run_id);
  expect(review.persistence).toBe('local_export_only');
  expect(review.criterion_reviews).toHaveLength(1);
  expect(review.criterion_reviews[0]).toMatchObject({
    trial_id: source.candidate_trials[0].trial_id,
    criterion_id: source.candidate_trials[0].criteria_assessments[0].criterion_id,
    original_decision: original,
    reviewed_decision: decision,
    reason,
  });
  const downloading = page.waitForEvent('download');
  await page.locator('#downloadBtn').click();
  const download = await downloading;
  expect(JSON.parse(await fs.readFile(await download.path(), 'utf8'))).toEqual(review);
  await page.locator('#closeDialog').click();
  await criterion.locator('.human-review').screenshot({
    path: path.join(process.env.REPORT_DIR || '/reports', 'human-review.png'),
  });
  expect(pageErrors).toEqual([]);
});

test('real backend: reason is required and restoring retains local change history', async ({
  page,
}) => {
  await openApp(page);
  await screen(page);
  const criterion = page.locator('.criterion').first();
  await criterion.locator('.human-review > summary').click();
  await criterion.getByRole('button', { name: 'Apply local review', exact: true }).click();
  await expect(criterion.getByRole('alert')).toContainText('Add a reason');
  await expect(
    page.getByRole('button', { name: 'Export human review', exact: true }),
  ).toBeDisabled();
  await criterion
    .getByLabel('Reason for review', { exact: true })
    .fill('Human review of synthetic evidence.');
  await criterion.getByRole('button', { name: 'Apply local review', exact: true }).click();
  await criterion.getByRole('button', { name: 'Restore original assessment', exact: true }).click();
  await expect(page.locator('.human-review-count')).toHaveText('No human edits');
  await expect(criterion.locator('.human-review-status')).toBeEmpty();
  await page.getByRole('button', { name: 'Export human review', exact: true }).click();
  const review = JSON.parse(await page.locator('#jsonPreview').innerText());
  expect(review.criterion_reviews).toEqual([]);
  expect(review.review_history.map((row) => row.action)).toEqual(['apply', 'restore']);
});

test('real backend: a new screening starts a separate review session', async ({ page }) => {
  await openApp(page);
  const first = await screen(page);
  await editFirst(page);
  const second = await screen(page);
  expect(second.run_id).not.toBe(first.run_id);
  await expect(page.locator('.human-review-count')).toHaveText('No human edits');
  await expect(
    page.getByRole('button', { name: 'Export human review', exact: true }),
  ).toBeDisabled();
});

test('real backend: reviews stay attached to the selected trial and criterion', async ({
  page,
}) => {
  await openApp(page);
  await page.locator('#topK').selectOption('3');
  const pending = page.waitForResponse(
    (r) => r.url().endsWith('/screen') && r.request().method() === 'POST',
  );
  await page.locator('#runBtn').click();
  const source = await (await pending).json();
  expect(source.candidate_trials).toHaveLength(3);
  const card = page.locator('.trial-card').nth(1);
  await card
    .locator(':scope > details > summary')
    .filter({ hasText: 'Criteria & evidence' })
    .click();
  const criterion = card.locator('.criterion').first();
  await criterion.locator('.human-review > summary').click();
  await criterion.getByLabel('Your assessment', { exact: true }).selectOption('UNKNOWN');
  await criterion
    .getByLabel('Reason for review', { exact: true })
    .fill('The second trial needs additional evidence.');
  await criterion.getByRole('button', { name: 'Apply local review', exact: true }).click();
  await expect(page.locator('.trial-card').first().locator('.trial-review-count')).toHaveText(
    'No human edits for this trial',
  );
  await expect(card.locator('.trial-review-count')).toContainText('1 of');
  await page.getByRole('button', { name: 'Export human review', exact: true }).click();
  const review = JSON.parse(await page.locator('#jsonPreview').innerText());
  expect(review.criterion_reviews).toHaveLength(1);
  expect(review.criterion_reviews[0]).toMatchObject({
    trial_id: source.candidate_trials[1].trial_id,
    criterion_id: source.candidate_trials[1].criteria_assessments[0].criterion_id,
    reviewed_decision: 'UNKNOWN',
  });
});

test('real backend: patient change clears old results and unmatched search disables screening', async ({
  page,
}) => {
  await openApp(page);
  await screen(page);
  await editFirst(page);
  const second = await page.locator('#patientSelect option').nth(1).getAttribute('value');
  await page.locator('#patientSelect').selectOption(second);
  await expect(page.locator('#runBtn')).toBeEnabled();
  await expect(page.locator('#results')).toBeHidden();
  await expect(page.locator('.human-review-banner')).toHaveCount(0);
  await page.locator('#patientSearch').fill('no-such-synthetic-patient');
  await expect(page.locator('#patientCard')).toHaveText('No patient matches your search.');
  await expect(page.locator('#runBtn')).toBeDisabled();
  await page.locator('#patientSearch').fill('060e72d3');
  await expect(page.locator('#runBtn')).toBeEnabled();
});

test('real backend: review controls remain usable on a narrow light-theme page', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openApp(page);
  await page.getByRole('button', { name: 'Light', exact: true }).click();
  await screen(page);
  const { criterion } = await editFirst(page);
  await expect(criterion.locator('.human-review-status')).toContainText('Human assessment:');
  const viewport = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: innerWidth,
  }));
  expect(viewport.scroll).toBeLessThanOrEqual(viewport.width + 1);
  await criterion.locator('.human-review').screenshot({
    path: path.join(process.env.REPORT_DIR || '/reports', 'human-review-mobile.png'),
  });
});

// Controlled failure injection only; success/review tests above call the real API.
test('injected empty response: show an explicit empty result without trial cards', async ({
  page,
}) => {
  await openApp(page);
  const source = await screen(page);
  await page.route('**/screen', (route) =>
    route.fulfill({
      status: 200,
      json: { ...source, candidate_trials: [], answer: 'No candidates returned for this test.' },
    }),
  );
  await page.locator('#runBtn').click();
  await expect(page.locator('#results')).toContainText('No candidate trials returned');
  await expect(page.locator('.trial-card')).toHaveCount(0);
  await expect(page.locator('#runBtn')).toBeEnabled();
  await expect(
    page.getByRole('button', { name: 'Export human review', exact: true }),
  ).toBeDisabled();
});

test('injected provider failure: show error, restore controls, and do not retry POST', async ({
  page,
}) => {
  await openApp(page);
  let calls = 0;
  await page.route('**/screen', async (route) => {
    calls++;
    await route.fulfill({
      status: 503,
      json: { detail: { code: 'PROVIDER_UNAVAILABLE', message: 'Test provider failure' } },
    });
  });
  await page.locator('#runBtn').click();
  await expect(page.locator('#error')).toContainText('HTTP 503');
  await expect(page.locator('#error')).toContainText('PROVIDER_UNAVAILABLE');
  await expect(page.locator('#runBtn')).toBeEnabled();
  await expect(page.locator('#progress')).toBeHidden();
  await expect(page.locator('#results')).toBeHidden();
  expect(calls).toBe(1);
});

for (const action of ['cancel', 'timeout']) {
  test(`injected pending request: ${action} displays feedback and restores controls`, async ({
    page,
  }) => {
    await openApp(page);
    if (action === 'timeout') await page.clock.install();
    let release;
    const held = new Promise((resolve) => {
      release = resolve;
    });
    let arrived;
    const requestArrived = new Promise((resolve) => {
      arrived = resolve;
    });
    await page.route('**/screen', async (route) => {
      arrived();
      await held;
      await route
        .fulfill({ status: 503, json: { detail: 'Injected slow response' } })
        .catch(() => {});
    });
    await page.locator('#runBtn').click();
    await requestArrived;
    await expect(page.locator('#progress')).toBeVisible();
    await expect(page.locator('#runBtn')).toBeDisabled();
    await expect(page.locator('#patientSelect')).toBeDisabled();
    if (action === 'cancel') await page.locator('#cancelBtn').click();
    else await page.clock.fastForward(300001);
    await expect(page.locator('#error')).toContainText(
      action === 'cancel' ? 'Request cancelled.' : 'Request timed out after five minutes.',
    );
    await expect(page.locator('#runBtn')).toBeEnabled();
    await expect(page.locator('#patientSelect')).toBeEnabled();
    await expect(page.locator('#progress')).toBeHidden();
    release();
  });
}
