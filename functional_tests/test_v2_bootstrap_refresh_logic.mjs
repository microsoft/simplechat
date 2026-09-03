// test_v2_bootstrap_refresh_logic.mjs
//
// Runtime test for the V2 bootstrap store's refresh action.
// Version: 0.261.046
// Implemented in: 0.261.046
//
// The companion test, test_v2_admin_settings_live_shell_refresh.py, asserts that the pieces
// are wired together. Those are source assertions: they prove the call exists, not that it
// behaves. This file executes the real store, because the two ways this can go quietly wrong
// both look fine in the source.
//
// The first is that a background refetch must never drive `loading` or `error`. App.tsx
// replaces the entire interface with the boot screen while `loading` is set, and with the
// boot error when `error` is, so an administrator mid-edit would lose the page and the
// unsaved draft with it. Asserting on the final state would miss it -- the flag only has to
// be set transiently to blank the screen -- so every intermediate state is recorded here.
//
// The second is ordering. Two saves in a row issue two refetches, and nothing guarantees the
// responses return in the order the requests left. The stale one winning is invisible except
// at the moment it happens.
//
// Run directly with `node functional_tests/test_v2_bootstrap_refresh_logic.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real module is imported
// rather than a copy.

import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';

// The V2 source imports without file extensions, which Vite resolves and Node's ESM
// resolver does not. Resolving them here is what lets this test execute the real store
// rather than a transcription of it that could drift from what ships.
registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier.startsWith('.') && !/\.[cm]?[jt]s$/.test(specifier)) {
            try {
                return nextResolve(`${specifier}.ts`, context);
            } catch {
                /* Not a TypeScript module; fall through to the default resolution. */
            }
        }
        return nextResolve(specifier, context);
    },
});

const STORE_URL = new URL(
    '../application/v2_ui/src/stores/bootstrapStore.ts',
    import.meta.url,
);

/** Swapped per test; every request the store makes lands here. */
let fetchImpl = () => {
    throw new Error('No fetch behaviour was installed for this test');
};

globalThis.fetch = (...args) => fetchImpl(...args);

const { useBootstrapStore } = await import(STORE_URL);

/** A minimal Response the api client is happy to read. */
function jsonResponse(body, status = 200) {
    return {
        ok: status >= 200 && status < 300,
        status,
        headers: { get: () => 'application/json' },
        json: async () => body,
        text: async () => JSON.stringify(body),
    };
}

/** A bootstrap payload carrying the classification banner in a given state. */
function payloadWithBanner(banner) {
    return {
        version: '0.261.046',
        user: { id: 'u1', display_name: 'Tester', is_admin: true, roles: ['Admin'] },
        branding: {
            app_title: 'SimpleChat',
            hide_app_title: false,
            show_logo: false,
            logo_url: null,
            logo_dark_url: null,
            classification_banner: banner,
        },
        features: {},
    };
}

const BANNER_OFF = null;
const BANNER_ON = {
    enabled: true,
    text: 'UNCLASSIFIED',
    color: '#ffc107',
    text_color: '#ffffff',
};

/** Reset the store to a resolved load carrying `banner`, and return its state. */
async function loadWith(banner) {
    fetchImpl = async () => jsonResponse(payloadWithBanner(banner));
    await useBootstrapStore.getState().load();
    return useBootstrapStore.getState();
}

/** Record every state the store passes through while `run` executes. */
async function recordStates(run) {
    const seen = [];
    const unsubscribe = useBootstrapStore.subscribe((state) => {
        seen.push({ loading: state.loading, error: state.error, authExpired: state.authExpired });
    });
    try {
        await run();
    } finally {
        unsubscribe();
    }
    return seen;
}

async function testRefreshAppliesTheNewPayload() {
    console.log('Testing that a refresh applies the new payload...');

    await loadWith(BANNER_OFF);
    assert.equal(
        useBootstrapStore.getState().data.branding.classification_banner,
        null,
        'The banner starts off, as it would before an administrator enabled it',
    );

    fetchImpl = async () => jsonResponse(payloadWithBanner(BANNER_ON));
    await useBootstrapStore.getState().refresh();

    assert.deepEqual(
        useBootstrapStore.getState().data.branding.classification_banner,
        BANNER_ON,
        'A refresh must replace the payload the shell reads, or enabling the banner stays '
            + 'invisible until the browser is reloaded',
    );

    // The same mechanism has to work in reverse, or a banner cannot be turned off either.
    fetchImpl = async () => jsonResponse(payloadWithBanner(BANNER_OFF));
    await useBootstrapStore.getState().refresh();

    assert.equal(
        useBootstrapStore.getState().data.branding.classification_banner,
        null,
        'Turning the banner off must reach the shell just as immediately',
    );

    console.log('Refresh payload test passed!');
}

async function testRefreshNeverBlanksTheInterface() {
    console.log('Testing that a refresh never blanks the interface...');

    await loadWith(BANNER_OFF);

    fetchImpl = async () => jsonResponse(payloadWithBanner(BANNER_ON));
    const seen = await recordStates(() => useBootstrapStore.getState().refresh());

    assert.ok(seen.length > 0, 'The refresh should have produced at least one state update');
    for (const state of seen) {
        assert.equal(
            state.loading,
            false,
            'A refresh must never set `loading`, even transiently: App.tsx swaps the whole '
                + 'interface for the boot screen while it is set, so the page being edited '
                + 'would be torn down and its unsaved draft lost',
        );
        assert.equal(state.error, null, 'A successful refresh must not report an error');
    }

    console.log('Interface blanking test passed!');
}

async function testAFailedRefreshIsAdvisory() {
    console.log('Testing that a failed refresh is advisory...');

    const before = (await loadWith(BANNER_ON)).data;

    fetchImpl = async () => jsonResponse({ error: 'Failed to load application bootstrap' }, 500);
    const seen = await recordStates(() => useBootstrapStore.getState().refresh());

    const after = useBootstrapStore.getState();
    assert.equal(
        after.data,
        before,
        'A failed refresh must leave the payload alone; the write it follows already '
            + 'succeeded, so the previous state is still the best available',
    );
    assert.equal(
        after.error,
        null,
        'A failed refresh must not set `error`: App.tsx replaces the whole interface with '
            + 'the boot error when it is set, so a page whose save had just succeeded would '
            + 'be thrown away over a background refetch nobody asked for',
    );
    assert.equal(after.authExpired, false, 'A failed refresh must not claim the session expired');
    assert.equal(after.loading, false, 'A failed refresh must not leave the store loading');

    for (const state of seen) {
        assert.equal(state.loading, false, 'A failing refresh must not blank the interface either');
        assert.equal(state.error, null, 'A failing refresh must not surface an error state');
    }

    console.log('Failed refresh test passed!');
}

async function testARejectedRefreshDoesNotEscape() {
    console.log('Testing that a refresh never rejects...');

    await loadWith(BANNER_ON);

    // A network-level failure rather than an HTTP error response.
    fetchImpl = async () => {
        throw new TypeError('Failed to fetch');
    };

    await assert.doesNotReject(
        () => useBootstrapStore.getState().refresh(),
        'Callers fire the refresh without awaiting it, so a rejection would surface as an '
            + 'unhandled promise rejection rather than being reported anywhere useful',
    );

    console.log('Rejection test passed!');
}

async function testAStaleRefreshCannotOverwriteANewerOne() {
    console.log('Testing the refresh ordering guard...');

    await loadWith(BANNER_OFF);

    const slowBanner = { ...BANNER_ON, text: 'FROM THE FIRST SAVE' };
    const fastBanner = { ...BANNER_ON, text: 'FROM THE SECOND SAVE' };

    let releaseSlow;
    const slowArrived = new Promise((resolve) => {
        releaseSlow = () => resolve(jsonResponse(payloadWithBanner(slowBanner)));
    });

    // The first refresh hangs; the second is served immediately.
    fetchImpl = () => slowArrived;
    const first = useBootstrapStore.getState().refresh();

    fetchImpl = async () => jsonResponse(payloadWithBanner(fastBanner));
    await useBootstrapStore.getState().refresh();

    assert.equal(
        useBootstrapStore.getState().data.branding.classification_banner.text,
        fastBanner.text,
        'The newer refresh should have been applied',
    );

    // Now let the older request finish. It must be discarded.
    releaseSlow();
    await first;

    assert.equal(
        useBootstrapStore.getState().data.branding.classification_banner.text,
        fastBanner.text,
        'A slower earlier refresh must not overwrite a newer one, or two saves in quick '
            + 'succession leave the interface showing the state from before the second',
    );

    console.log('Refresh ordering test passed!');
}

const tests = [
    testRefreshAppliesTheNewPayload,
    testRefreshNeverBlanksTheInterface,
    testAFailedRefreshIsAdvisory,
    testARejectedRefreshDoesNotEscape,
    testAStaleRefreshCannotOverwriteANewerOne,
];

let passed = 0;
for (const test of tests) {
    console.log(`\nRunning ${test.name}...`);
    try {
        await test();
        passed += 1;
    } catch (error) {
        console.error(`Test failed: ${error.message}`);
        console.error(error);
    }
}

console.log(`\nResults: ${passed}/${tests.length} tests passed`);
process.exit(passed === tests.length ? 0 : 1);
