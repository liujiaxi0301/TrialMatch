const { defineConfig } = require('@playwright/test');
const path = require('node:path');
const reportDir = process.env.REPORT_DIR || '/reports';

module.exports = defineConfig({
  testDir: '.',
  testMatch: '*.spec.js',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60000,
  expect: { timeout: 15000 },
  outputDir: path.join(reportDir, 'browser-results'),
  reporter: [
    ['list'],
    ['html', { outputFolder: path.join(reportDir, 'playwright-report'), open: 'never' }],
    ['junit', { outputFile: path.join(reportDir, 'browser-results.xml') }],
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:8080',
    browserName: 'chromium',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
