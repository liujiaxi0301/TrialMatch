const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '.',
  testMatch: '*.spec.js',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60000,
  expect: { timeout: 15000 },
  outputDir: '/reports/browser-results',
  reporter: [
    ['list'],
    ['html', { outputFolder: '/reports/playwright-report', open: 'never' }],
    ['junit', { outputFile: '/reports/browser-results.xml' }],
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:8080',
    browserName: 'chromium',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
