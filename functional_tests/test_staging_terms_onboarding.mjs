// test_staging_terms_onboarding.mjs
/*
Verify pinned, CI-only staging onboarding without bypassing consent changes.
Version: 0.261.401
Implemented in: 0.261.401
*/

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import vm from 'node:vm';

import { completeStagingTermsOnboarding, prepareStagingBrowser } from '../ui_tests/playwright-workspaces/staging-auth.js';

const text = 'Reviewed staging notice';
const pin = createHash('sha256').update(text).digest('hex');
const baseUrl = 'https://stage.example.test';

for (const origin of [baseUrl, 'https://other.example.test']) {
    test(`tutorial preference remains scoped to the test origin: ${origin}`, async () => {
        const values = {};
        const context = {
            async addInitScript(callback, expectedOrigin) {
                vm.runInNewContext(`(${callback.toString()})(origin)`, {
                    origin: expectedOrigin,
                    window: {
                        location: { origin },
                        localStorage: { setItem: (key, value) => { values[key] = value; } },
                    },
                });
            },
        };
        await prepareStagingBrowser(context, baseUrl);
        assert.deepEqual(values, origin === baseUrl ? { chatTutorialDismissed: 'dismissed' } : {});
    });
}

class Page {
    constructor(path = '/terms-of-use', content = text, activeContent = 0) {
        this.currentUrl = baseUrl + path;
        this.content = content;
        this.activeContent = activeContent;
        this.clicks = 0;
        this.destination = baseUrl + '/chats';
    }

    url() {
        return this.currentUrl;
    }

    locator() {
        return this;
    }

    async waitFor() {}

    async innerText() {
        return this.content;
    }

    async count() {
        return this.activeContent;
    }

    getByRole(role, options) {
        assert.equal(role, 'button');
        assert.deepEqual(options, { name: 'Accept and continue', exact: true });
        return this;
    }

    async click() {
        this.clicks += 1;
        this.currentUrl = this.destination;
    }

    async waitForURL(predicate) {
        assert.equal(predicate(new URL(this.currentUrl)), true);
    }
}

test('only the current pinned content is accepted for CI', async () => {
    const page = new Page('/terms-of-use', ' Reviewed \n staging notice ');
    const completed = await completeStagingTermsOnboarding(page, {
        baseUrl, accessToken: 'ci-test-token', termsSha256: pin,
    });
    assert.equal(completed, true);
    assert.equal(page.clicks, 1);
    assert.equal(page.url(), baseUrl + '/chats');
});

test('existing onboarding does not need another consent', async () => {
    const page = new Page('/chats');
    const completed = await completeStagingTermsOnboarding(page, { baseUrl });
    assert.equal(completed, false);
    assert.equal(page.clicks, 0);
});

test('default port and host case use the same origin', async () => {
    const page = new Page();
    const completed = await completeStagingTermsOnboarding(page, {
        baseUrl: 'https://STAGE.example.test:443', accessToken: 'ci-test-token', termsSha256: pin,
    });
    assert.equal(completed, true);
    assert.equal(page.clicks, 1);
});

test('non-ASCII content is preserved in the reviewed digest', async () => {
    const page = new Page('/terms-of-use', '\u00a0Reviewed staging notice\u00a0');
    const digest = createHash('sha256').update(page.content, 'utf8').digest('hex');
    const completed = await completeStagingTermsOnboarding(page, {
        baseUrl, accessToken: 'ci-test-token', termsSha256: digest,
    });
    assert.equal(completed, true);
});

test('origins containing credentials are rejected', async () => {
    const page = new Page();
    const completion = completeStagingTermsOnboarding(page, {
        baseUrl: 'https://name:password@stage.example.test',
        accessToken: 'ci-test-token', termsSha256: pin,
    });
    await assert.rejects(completion, /without credentials/);
    assert.equal(page.clicks, 0);
});

for (const value of ['', 'invalid', 'a'.repeat(63)]) {
    test(`missing or invalid pin is rejected: ${value || 'empty'}`, async () => {
        const page = new Page();
        const completion = completeStagingTermsOnboarding(page, {
            baseUrl, accessToken: 'ci-test-token', termsSha256: value,
        });
        await assert.rejects(completion, /reviewed SIMPLECHAT_UI_TERMS_SHA256/);
        assert.equal(page.clicks, 0);
    });
}

test('changed terms cannot reuse a previous pin', async () => {
    const page = new Page('/terms-of-use', 'Different terms');
    const completion = completeStagingTermsOnboarding(page, {
        baseUrl, accessToken: 'ci-test-token', termsSha256: pin,
    });
    await assert.rejects(completion, /terms changed/);
    assert.equal(page.clicks, 0);
});

test('human browser state is not autoaccepted', async () => {
    const page = new Page();
    const completion = completeStagingTermsOnboarding(page, { baseUrl, termsSha256: pin });
    await assert.rejects(completion, /dedicated CI bearer identity/);
    assert.equal(page.clicks, 0);
});

test('foreign terms origins are rejected', async () => {
    const page = new Page();
    page.currentUrl = 'https://other.example.test/terms-of-use';
    const completion = completeStagingTermsOnboarding(page, {
        baseUrl, accessToken: 'ci-test-token', termsSha256: pin,
    });
    await assert.rejects(completion, /configured staging origin/);
    assert.equal(page.clicks, 0);
});

test('linked or active content requires manual review', async () => {
    const page = new Page('/terms-of-use', text, 1);
    const completion = completeStagingTermsOnboarding(page, {
        baseUrl, accessToken: 'ci-test-token', termsSha256: pin,
    });
    await assert.rejects(completion, /manual review/);
    assert.equal(page.clicks, 0);
});

test('a foreign post-consent redirect is not success', async () => {
    const page = new Page();
    page.destination = 'https://other.example.test/chats';
    const completion = completeStagingTermsOnboarding(page, {
        baseUrl, accessToken: 'ci-test-token', termsSha256: pin,
    });
    await assert.rejects(completion, /returned outside/);
});
