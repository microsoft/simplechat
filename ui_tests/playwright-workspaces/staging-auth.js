// staging-auth.js
/*
Pinned, CI-identity-only onboarding for staging browser tests.
Version: 0.261.401
Implemented in: 0.261.401
*/

import { createHash } from 'node:crypto';

function stagingOrigin(baseUrl) {
    const target = new URL(baseUrl);
    if (!['https:', 'http:'].includes(target.protocol) || target.username || target.password) {
        throw new Error('Terms onboarding requires a valid HTTP(S) origin without credentials.');
    }
    return target.origin;
}

export async function prepareStagingBrowser(context, baseUrl) {
    await context.addInitScript((origin) => {
        if (window.location.origin === origin) {
            window.localStorage.setItem('chatTutorialDismissed', 'dismissed');
        }
    }, stagingOrigin(baseUrl));
}

export async function completeStagingTermsOnboarding(page, { baseUrl, accessToken = '', termsSha256 = '' }) {
    const current = new URL(page.url());
    if (current.pathname !== '/terms-of-use') {
        return false;
    }

    const targetOrigin = stagingOrigin(baseUrl);
    if (current.origin !== targetOrigin) {
        throw new Error('Terms onboarding must remain on the configured staging origin.');
    }
    if (!accessToken) {
        throw new Error('Automatic terms onboarding is limited to the dedicated CI bearer identity.');
    }

    const expectedHash = termsSha256.trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(expectedHash)) {
        throw new Error('The CI identity needs a reviewed SIMPLECHAT_UI_TERMS_SHA256 before onboarding.');
    }

    const message = page.locator('.terms-message');
    await message.waitFor({ state: 'visible', timeout: 30000 });
    const text = (await message.innerText()).replace(/[ \t\r\n\f\v]+/g, ' ').replace(/^ +| +$/g, '');
    const actualHash = createHash('sha256').update(text, 'utf8').digest('hex');
    if (actualHash !== expectedHash) {
        throw new Error('Staging terms changed; review and pin their content before CI accepts them.');
    }
    const activeContentCount = await message.locator('a,script,iframe,form').count();
    if (activeContentCount) {
        throw new Error('Terms with links or active content require manual review.');
    }

    await page.getByRole('button', { name: 'Accept and continue', exact: true }).click();
    await page.waitForURL((value) => value.pathname !== '/terms-of-use', { timeout: 30000 });
    if (new URL(page.url()).origin !== targetOrigin) {
        throw new Error('Terms onboarding returned outside the configured staging origin.');
    }
    return true;
}
