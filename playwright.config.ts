import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 0, // No timeout for long validation runs
  use: {
    baseURL: 'http://localhost:3000',
    screenshot: 'off',
    video: 'off',
  },
  retries: 0,
  workers: 1, // Serial execution required
});
