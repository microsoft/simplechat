// staging-chat-smoke.spec.js
/*
UI smoke test for staging chat deployment through Microsoft Playwright Workspaces.
Version: 0.241.018
Implemented in: 0.241.017; 0.241.018

This test validates the same authenticated chat path as the Python staging
smoke test, but runs through Azure-hosted browsers in Playwright Workspaces.
*/

import { existsSync } from 'node:fs';

import { expect, test } from '@playwright/test';

const baseUrl = (process.env.SIMPLECHAT_UI_BASE_URL ?? '').replace(/\/$/, '');
const storageState = process.env.SIMPLECHAT_UI_STORAGE_STATE
    || process.env.SIMPLECHAT_UI_ADMIN_STORAGE_STATE
    || '';
const accessToken = process.env.SIMPLECHAT_UI_ACCESS_TOKEN || '';
const smokePrompt = process.env.SIMPLECHAT_UI_SMOKE_PROMPT
    || 'CI smoke test. Reply with one short greeting.';
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

        await expect(page.locator('#user-input')).toBeVisible({ timeout: 30000 });
        await expect(page.locator('#send-btn')).toBeAttached({ timeout: 30000 });

        await page.locator('#new-conversation-btn').click();
        await page.locator('#user-input').fill(smokePrompt);
        await page.locator('#send-btn').click();

        await expect(page.locator('.user-message .message-text').filter({ hasText: smokePrompt })).toBeVisible({ timeout: 15000 });

        await page.waitForFunction(() => Array.from(document.querySelectorAll('.ai-message .message-text')).some((element) => {
            const text = (element.textContent || '').trim();
            const messageElement = element.closest('.ai-message');
            return Boolean(
                text
                && !text.includes('Streaming...')
                && !text.includes('Reconnecting')
                && messageElement
                && !messageElement.querySelector('.streaming-cursor, .spinner-border'),
            );
        }), null, { timeout: responseTimeoutMs });

        const assistantText = ((await page.locator('.ai-message .message-text').last().textContent()) || '').trim();
        expect(assistantText, 'Expected the assistant response to contain text.').not.toHaveLength(0);

        conversationId = await page.evaluate(() => window.chatConversations?.getCurrentConversationId?.()
            || window.currentConversationId
            || null);
        expect(conversationId, 'Expected the staging smoke test to create or select a conversation.').toBeTruthy();

        await expect(page.locator('.toast.show .text-bg-danger, .toast.show.bg-danger, .toast.show .alert-danger')).toHaveCount(0);
    }
    finally {
        if (conversationId) {
            await page.context().request.delete(`${baseUrl}/api/conversations/${conversationId}`, { timeout: 30000 }).catch(() => {});
        }
    }
});