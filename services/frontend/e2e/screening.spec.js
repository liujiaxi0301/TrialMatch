const { test, expect } = require('@playwright/test');

// Real browser -> Nginx -> FastAPI -> offline screening. No intercepted APIs.
test('patient selection, screening and evidence review', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('#runBtn')).toBeEnabled();
  await expect(page.locator('#modeBanner')).toContainText(/offline/i);
  const patientId = await page.locator('#patientSelect').inputValue();
  expect(patientId).not.toBe('');
  await page.locator('#question').fill('Which type 2 diabetes trials may suit this patient?');
  await page.locator('#topK').selectOption('3');
  const responsePromise = page.waitForResponse(
    response => response.url().endsWith('/screen') && response.request().method() === 'POST'
  );
  await page.locator('#runBtn').click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.mode).toBe('offline');
  expect(body.candidate_trials).toHaveLength(3);
  await expect(page.locator('#results')).toBeVisible();
  for (const trial of body.candidate_trials) {
    await expect(page.locator('#results')).toContainText(trial.trial_id);
    expect(trial.criteria_assessments.length).toBeGreaterThan(0);
  }
  await page.locator('summary').filter({ hasText: 'Criteria & evidence' }).first().click();
  await expect(page.locator('.criterion').first()).toBeVisible();
  await page.locator('#responseJson').click();
  await expect(page.locator('#dataDialog')).toBeVisible();
  const exported = JSON.parse(await page.locator('#jsonPreview').innerText());
  expect(exported.run_id).toBe(body.run_id);
  expect(exported.candidate_trials).toEqual(body.candidate_trials);
  await page.locator('#closeDialog').click();
  await page.locator('summary').filter({ hasText: 'Criteria & evidence' }).first().click();
  await page.screenshot({ path: '/reports/screening.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('empty question is explained before submitting', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#runBtn')).toBeEnabled();
  let submissions = 0;
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/screen')) submissions++;
  });
  await page.locator('#question').fill('');
  await page.locator('#runBtn').click();
  await expect(page.locator('#error')).toHaveText('Enter a screening question.');
  expect(submissions).toBe(0);
});

test('frontend proxy preserves API validation errors', async ({ request }) => {
  const response = await request.post('/screen', {
    data: { patient_id: 'not-a-patient', question: 'Trial screening', top_k: 99 },
  });
  expect(response.status()).toBe(422);
  expect((await response.json()).detail).toBeTruthy();
});
