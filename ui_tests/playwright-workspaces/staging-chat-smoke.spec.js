// staging-chat-smoke.spec.js
/*
UI smoke test for staging chat deployment.
Version: 0.261.402
Implemented in: 0.241.017; 0.241.018

This test validates the same authenticated chat path as the Python staging
smoke test. The default command uses runner-local Chromium; the separate Azure
command retains optional Playwright Workspaces execution.
*/

import { existsSync } from 'node:fs';
import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

import { completeStagingTermsOnboarding, prepareStagingBrowser } from './staging-auth.js';

const baseUrl = (process.env.SIMPLECHAT_UI_BASE_URL ?? '').replace(/\/$/, '');
const storageState = process.env.SIMPLECHAT_UI_STORAGE_STATE
    || process.env.SIMPLECHAT_UI_ADMIN_STORAGE_STATE
    || '';
const accessToken = process.env.SIMPLECHAT_UI_ACCESS_TOKEN || '';
const termsSha256 = process.env.SIMPLECHAT_UI_TERMS_SHA256 || '';
const customPrompt = process.env.SIMPLECHAT_UI_SMOKE_PROMPT || '';
const expectedResponse = customPrompt ? '' : `SIMPLECHAT_CI_${randomUUID().replaceAll('-', '')}`;
const smokePrompt = customPrompt || `CI smoke test. Reply with exactly this text: ${expectedResponse}`;
const responseTimeoutMs = Number(process.env.SIMPLECHAT_UI_SMOKE_RESPONSE_TIMEOUT_MS ?? 180000);

test.skip(!baseUrl, 'Set SIMPLECHAT_UI_BASE_URL to run this staging UI smoke test.');
test.skip(!accessToken && (!storageState || !existsSync(storageState)), 'Set SIMPLECHAT_UI_ACCESS_TOKEN or a valid SIMPLECHAT_UI_STORAGE_STATE/SIMPLECHAT_UI_ADMIN_STORAGE_STATE file.');

if (accessToken) {
    test.use({ extraHTTPHeaders: { Authorization: `Bearer ${accessToken}` } });
}
else if (storageState) {
    test.use({ storageState });
}

test('staging chat can create conversation and receive response', async ({ page }) => {
    let conversationId = null;

    try {
        await prepareStagingBrowser(page.context(), baseUrl);
        if (accessToken) {
            const sessionResponse = await page.context().request.post(`${baseUrl}/ci-auth/session`, {
                headers: { Authorization: `Bearer ${accessToken}` },
                timeout: 30000,
            });
            expect(sessionResponse.ok(), `Expected CI bearer session setup to succeed, got HTTP ${sessionResponse.status()}.`).toBeTruthy();
        }

        const response = await page.goto(`${baseUrl}/chats`, { waitUntil: 'networkidle', timeout: 60000 });
        expect(response, 'Expected a navigation response when loading /chats.').not.toBeNull();
        expect([401, 403], 'Authenticated storage state was rejected by the staging chat page.').not.toContain(response.status());
        expect(response.ok(), `Expected /chats to load successfully, got HTTP ${response.status()}.`).toBeTruthy();

        await completeStagingTermsOnboarding(page, { baseUrl, accessToken, termsSha256 });
        await expect(page.locator('#user-input')).toBeVisible({ timeout: 30000 });
        await expect(page.locator('#send-btn')).toBeAttached({ timeout: 30000 });

        const newChat = page.locator('#new-conversation-btn:visible, #sidebar-new-chat-btn:visible').first();
        await expect(newChat).toBeVisible({ timeout: 30000 });
        await newChat.click();
        await page.locator('#user-input').fill(smokePrompt);
        await page.locator('#send-btn').click();

        await expect(page.locator('.user-message .message-text').filter({ hasText: smokePrompt })).toBeVisible({ timeout: 15000 });

        conversationId = await page.evaluate(() => window.chatConversations?.getCurrentConversationId?.()
            || window.currentConversationId
            || null);
        expect(conversationId, 'Expected the staging smoke test to create or select a conversation.').toBeTruthy();

        await page.waitForFunction((expectedResponseText) => Array.from(document.querySelectorAll('.ai-message .message-text')).some((element) => {
            const text = (element.textContent || '').trim();
            const messageElement = element.closest('.ai-message');
            return Boolean(
                text
                && (!expectedResponseText || text.includes(expectedResponseText))
                && text !== 'Thinking'
                && !text.includes('Streaming...')
                && !text.includes('Reconnecting')
                && messageElement
                && !messageElement.querySelector('.streaming-cursor, .spinner-border'),
            );
        }), expectedResponse, { timeout: responseTimeoutMs });

        const assistantText = ((await page.locator('.ai-message .message-text').last().textContent()) || '').trim();
        expect(assistantText, 'Expected the assistant response to contain text.').not.toHaveLength(0);
        if (expectedResponse) {
            expect(assistantText, 'Expected the model to return the unique CI response marker.').toContain(expectedResponse);
        }

        await expect(page.locator('.toast.show .text-bg-danger, .toast.show.bg-danger, .toast.show .alert-danger')).toHaveCount(0);
    }
    finally {
        if (conversationId) {
            const cleanup = await page.context().request.delete(`${baseUrl}/api/conversations/${conversationId}`, { timeout: 30000 });
            expect(cleanup.ok() || cleanup.status() === 404, `CI conversation cleanup failed with HTTP ${cleanup.status()}.`).toBeTruthy();
        }
    }
});