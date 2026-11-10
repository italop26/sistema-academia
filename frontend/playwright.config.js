import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  outputDir: '/tmp/playwright-results',
  workers: 1,
  retries: 0,
  reporter: 'list',
  timeout: 30000,
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5174',
    browserName: 'chromium',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
});
