// test_v2_access_restriction_and_safety_warning_logic.mjs
// Version: 0.261.297
// Implemented in: 0.261.297
// Executes the real V2 modules (lib/apiClient.ts, lib/accessRestriction.ts, lib/safetyWarnings.ts
// and stores/safetyWarningStore.ts) against controlled HTTP. Pins that a 403 from the server's
// access gate sends the tab to the Access restricted page once, without looping on that page;
// that the restriction and warning payloads are read defensively; and that the warning store
// keeps a warning until it is acknowledged, drops one the server no longer has, never brings
// back one acknowledged while an older read was in flight, still shows a newer warning sent on
// the same violation, and reads the newer warning when the one on screen was replaced.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const apiClient = await import('../application/v2_ui/src/lib/apiClient.ts');
const { parseAccessRestrictionStatus, formatRestoreTime } = await import('../application/v2_ui/src/lib/accessRestriction.ts');
const {
    describeSafetyWarningCategories,
    parsePendingSafetyWarnings,
} = await import('../application/v2_ui/src/lib/safetyWarnings.ts');
const { useSafetyWarningStore, SAFETY_WARNING_ACKNOWLEDGE_ERROR } = await import('../application/v2_ui/src/stores/safetyWarningStore.ts');

const { ApiError, isAccessRestricted, requestWithStatus, V2_ACCESS_RESTRICTED_PATH } = apiClient;

let answer = () => new Response(null, { status: 204 });
const requests = [];
globalThis.fetch = async (url, init) => {
    const request = { url: String(url), method: init?.method ?? 'GET' };
    if (init?.body !== undefined) {
        request.body = JSON.parse(init.body);
    }
    requests.push(request);
    return answer(String(url), init);
};

const assigned = [];
globalThis.window = {
    location: {
        pathname: '/v2/chat',
        search: '',
        hash: '',
        assign: (url) => assigned.push(url),
    },
};

function json(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const RESTRICTED = {
    error: 'access_restricted',
    message: 'Your access to this application has been blocked by an administrator.',
    restriction: { kind: 'blocked', until: null, title: 'Blocked', message: 'Blocked.', reference_id: 'log-1' },
    restricted_url: '/v2/access-restricted',
};

let checks = 0;
async function check(name, run) {
    await run();
    checks += 1;
    console.log(`ok ${name}`);
}

async function failure(send) {
    try {
        await send();
    } catch (error) {
        return error;
    }
    assert.fail('The request unexpectedly succeeded.');
}

await check('only the access gate counts as a restriction', () => {
    assert.equal(isAccessRestricted(403, RESTRICTED), true);
    assert.equal(isAccessRestricted(403, { error: 'Forbidden' }), false);
    assert.equal(isAccessRestricted(403, { error: 'Access Denied' }), false);
    assert.equal(isAccessRestricted(401, RESTRICTED), false);
    assert.equal(isAccessRestricted(403, 'access_restricted'), false);
    assert.equal(V2_ACCESS_RESTRICTED_PATH, '/v2/access-restricted');
});

await check('a refused call sends the tab to the Access restricted page', async () => {
    answer = () => json(RESTRICTED, 403);
    const error = await failure(() => requestWithStatus('/api/v2/bootstrap'));
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 403);
    assert.equal(error.message, RESTRICTED.message);
    assert.deepEqual(error.payload, RESTRICTED);
    assert.deepEqual(assigned, ['/v2/access-restricted']);
});

await check('a refused call on the page itself does not loop', async () => {
    assigned.length = 0;
    window.location.pathname = '/v2/access-restricted';
    answer = () => json(RESTRICTED, 403);
    await failure(() => requestWithStatus('/api/notifications/count'));
    assert.deepEqual(assigned, []);
    window.location.pathname = '/v2/chat';
});

await check('the terms gate still wins its own redirect', async () => {
    assigned.length = 0;
    answer = () => json({ error: 'terms_of_use_required', message: 'Accept the terms.' }, 403);
    await failure(() => requestWithStatus('/api/v2/bootstrap'));
    assert.equal(assigned.length, 1);
    assert.ok(assigned[0].startsWith('/v2/terms-of-use?'), assigned[0]);
    assigned.length = 0;
    answer = () => json({ error: 'Forbidden', message: 'Insufficient permissions' }, 403);
    await failure(() => requestWithStatus('/api/v2/bootstrap'));
    assert.deepEqual(assigned, [], 'An ordinary 403 navigated away');
});

await check('the restriction status is read defensively', () => {
    assert.deepEqual(parseAccessRestrictionStatus({ restricted: false, branding: { app_title: 'Contoso' } }), {
        restricted: false,
        restriction: null,
        branding: { app_title: 'Contoso' },
    });
    const suspended = parseAccessRestrictionStatus({
        restricted: true,
        restriction: { kind: 'suspended', until: '2026-10-08T14:00:00+00:00', title: ' Suspended ', message: 'Wait.', reference_id: 'log-9' },
    });
    assert.deepEqual(suspended.restriction, {
        kind: 'suspended',
        until: '2026-10-08T14:00:00+00:00',
        title: 'Suspended',
        message: 'Wait.',
        referenceId: 'log-9',
    });
    // A suspension without a restore time can't say when access returns: shown as a block.
    const noUntil = parseAccessRestrictionStatus({ restricted: true, restriction: { kind: 'suspended', title: '', message: '' } });
    assert.equal(noUntil.restriction.kind, 'blocked');
    assert.equal(noUntil.restriction.until, null);
    assert.equal(noUntil.restriction.title, 'Your access has been blocked');
    assert.equal(noUntil.restriction.referenceId, null);
    assert.equal(parseAccessRestrictionStatus(null).restricted, false);
    assert.equal(formatRestoreTime('not a date'), null);
    assert.equal(formatRestoreTime(null), null);
    assert.equal(typeof formatRestoreTime('2026-10-08T14:00:00+00:00', 'en-US'), 'string');
});

await check('pending warnings are read defensively, oldest first as sent', () => {
    const warnings = parsePendingSafetyWarnings({
        warnings: [
            {
                id: 'log-1', title: 'Warning', message: 'Please review the policy.', issued_at: '2026-10-07T12:00:00+00:00',
                triggered_categories: [{ category: 'Hate', severity: 4 }, { category: 'Violence' }, { severity: 2 }, 'x'],
            },
            { id: 'log-2', message: 'No title.' },
            { id: '', message: 'No id.' },
            { id: 'log-3', message: '' },
            null,
        ],
    });
    assert.deepEqual(warnings.map((warning) => warning.id), ['log-1', 'log-2']);
    assert.deepEqual(warnings[0].categories, [{ category: 'Hate', severity: 4 }, { category: 'Violence', severity: null }]);
    assert.equal(warnings[1].title, 'Safety Violation Warning');
    assert.equal(warnings[1].issuedAt, null);
    assert.equal(describeSafetyWarningCategories(warnings[0].categories), 'Hate (severity 4), Violence');
    assert.throws(() => parsePendingSafetyWarnings({ error: 'nope' }), /invalid/);
});

const WARNINGS = parsePendingSafetyWarnings({
    warnings: [
        { id: 'log-1', title: 'First', message: 'First warning.', issued_at: '2026-10-01T09:00:00+00:00' },
        { id: 'log-2', title: 'Second', message: 'Second warning.' },
    ],
});
const ids = () => useSafetyWarningStore.getState().warnings.map((warning) => warning.id);

await check('a warning stays until it is acknowledged, and an old read cannot bring it back', async () => {
    const store = useSafetyWarningStore;
    store.getState().reset();
    store.getState().receive(WARNINGS);
    assert.deepEqual(ids(), ['log-1', 'log-2']);

    requests.length = 0;
    answer = () => json({ success: true, already_acknowledged: false, warning: {} });
    assert.equal(await store.getState().acknowledge(WARNINGS[0]), true);
    // The server is told which warning was read, so it can refuse one since replaced.
    assert.deepEqual(requests, [{
        url: '/api/safety/warnings/log-1/acknowledge',
        method: 'POST',
        body: { issued_at: '2026-10-01T09:00:00+00:00' },
    }]);
    assert.deepEqual(ids(), ['log-2']);

    // A read that left before the acknowledgment landed still lists it.
    store.getState().receive(WARNINGS);
    assert.deepEqual(ids(), ['log-2']);
});

await check('a failed acknowledgment keeps the warning and says so', async () => {
    const store = useSafetyWarningStore;
    requests.length = 0;
    answer = () => json({ error: 'Your acknowledgment could not be saved. Try again.' }, 500);
    assert.equal(await store.getState().acknowledge(WARNINGS[1]), false);
    // Without a send time, the acknowledgment names only the violation.
    assert.deepEqual(requests[0].body, {});
    assert.equal(store.getState().error, SAFETY_WARNING_ACKNOWLEDGE_ERROR);
    assert.equal(store.getState().acknowledgingKey, null);
    assert.deepEqual(ids(), ['log-2']);
});

await check('a warning the server no longer has is dropped', async () => {
    const store = useSafetyWarningStore;
    answer = () => json({ error: 'Warning not found.' }, 404);
    assert.equal(await store.getState().acknowledge(WARNINGS[1]), true);
    assert.deepEqual(store.getState().warnings, []);
    assert.equal(store.getState().error, null);
});

const RESENT = parsePendingSafetyWarnings({
    warnings: [{ id: 'log-1', title: 'Again', message: 'A second warning.', issued_at: '2026-10-05T09:00:00+00:00' }],
});

await check('a newer warning on the same violation shows after the earlier one was acknowledged', () => {
    const store = useSafetyWarningStore;
    // log-1 was acknowledged above. A reviewer then warned about the same violation again.
    store.getState().receive([...WARNINGS, ...RESENT]);
    assert.deepEqual(store.getState().warnings.map((warning) => warning.title), ['Again']);

    // The same goes for one sent again after the earlier warning was withdrawn (log-2 above).
    const again = parsePendingSafetyWarnings({
        warnings: [{ id: 'log-2', title: 'Second again', message: 'Sent again.', issued_at: '2026-10-06T09:00:00+00:00' }],
    });
    store.getState().receive(again);
    assert.deepEqual(store.getState().warnings.map((warning) => warning.title), ['Second again']);
});

await check('a warning replaced while on screen is dropped and the newer one is read', async () => {
    const store = useSafetyWarningStore;
    store.getState().reset();
    const onScreen = parsePendingSafetyWarnings({
        warnings: [{ id: 'log-7', title: 'Old', message: 'Old text.', issued_at: '2026-10-01T09:00:00+00:00' }],
    });
    const newer = { id: 'log-7', title: 'New', message: 'New text.', issued_at: '2026-10-02T09:00:00+00:00' };
    store.getState().receive(onScreen);

    requests.length = 0;
    answer = (url, init) => {
        if (init?.method === 'POST') {
            return json({ error: 'A newer warning replaced this one.', code: 'safety_warning_replaced' }, 409);
        }
        return json({ warnings: [newer], count: 1 });
    };
    assert.equal(await store.getState().acknowledge(onScreen[0]), true);
    assert.deepEqual(requests.map((request) => `${request.method} ${request.url}`), [
        'POST /api/safety/warnings/log-7/acknowledge',
        'GET /api/safety/warnings/pending',
    ]);
    assert.deepEqual(requests[0].body, { issued_at: '2026-10-01T09:00:00+00:00' });
    assert.deepEqual(store.getState().warnings.map((warning) => warning.title), ['New']);
    assert.equal(store.getState().error, null);

    // Any other 409 is a failure to try again, not a replacement.
    answer = () => json({ error: 'Conflict.' }, 409);
    assert.equal(await store.getState().acknowledge(store.getState().warnings[0]), false);
    assert.equal(store.getState().error, SAFETY_WARNING_ACKNOWLEDGE_ERROR);
    assert.deepEqual(store.getState().warnings.map((warning) => warning.title), ['New']);
});

console.log(`${checks} checks passed`);
