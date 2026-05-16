// playwright.service.config.js
import { DefaultAzureCredential } from '@azure/identity';
import { createAzurePlaywrightConfig, ServiceOS } from '@azure/playwright';
import { defineConfig } from '@playwright/test';

import baseConfig from './playwright.config.js';

if (!process.env.PLAYWRIGHT_SERVICE_URL) {
    throw new Error('Set PLAYWRIGHT_SERVICE_URL to run tests in Microsoft Playwright Workspaces.');
}

export default defineConfig(
    baseConfig,
    createAzurePlaywrightConfig(baseConfig, {
        connectTimeout: 3 * 60 * 1000,
        credential: new DefaultAzureCredential(),
        os: ServiceOS.LINUX,
    }),
);