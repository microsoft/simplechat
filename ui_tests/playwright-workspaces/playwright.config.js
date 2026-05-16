// playwright.config.js
import { defineConfig } from '@playwright/test';

export default defineConfig({
    testDir: '.',
    testMatch: /.*\.spec\.js/,
    timeout: Number(process.env.PLAYWRIGHT_TEST_TIMEOUT_MS ?? 180000),
    expect: {
        timeout: 30000,
    },
    fullyParallel: false,
    reporter: [
        ['list'],
        ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ],
    use: {
        baseURL: process.env.SIMPLECHAT_UI_BASE_URL,
        screenshot: 'only-on-failure',
        trace: 'retain-on-failure',
        video: 'retain-on-failure',
        viewport: { width: 1440, height: 900 },
    },
});