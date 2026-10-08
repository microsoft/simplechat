// test_v2_access_restriction_and_safety_warning_logic.mjs
// Version: 0.261.297
// Implemented in: 0.261.297
// Executes the real V2 modules (lib/apiClient.ts, lib/accessRestriction.ts, lib/safetyWarnings.ts
// and stores/safetyWarningStore.ts) against controlled HTTP. Pins that a 403 from the server's
// access gate sends the tab to the Access restricted page once, without looping on that page;
// that the restriction and warning payloads are read defensively; and that the warning store
// keeps a warning until it is acknowledged, drops one the server no longer has, and never brings
// back one acknowledged while an older read was in flight.

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
    requests.push({ url: String(url), method: init?.method ?? 'GET' });
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
        { id: 'log-1', title: 'First', message: 'First warning.' },
        { id: 'log-2', title: 'Second', message: 'Second warning.' },
    ],
});

await check('a warning stays until it is acknowledged, and an old read cannot bring it back', async () => {
    const store = useSafetyWarningStore;
    store.getState().reset();
    store.getState().receive(WARNINGS);
    assert.deepEqual(store.getState().warnings.map((warning) => warning.id), ['log-1', 'log-2']);

    requests.length = 0;
    answer = () => json({ success: true, already_acknowledged: false, warning: {} });
    assert.equal(await store.getState().acknowledge('log-1'), true);
    assert.deepEqual(requests, [{ url: '/api/safety/warnings/log-1/acknowledge', method: 'POST' }]);
    assert.deepEqual(store.getState().warnings.map((warning) => warning.id), ['log-2']);

    // A read that left before the acknowledgment landed still lists it.
    store.getState().receive(WARNINGS);
    assert.deepEqual(store.getState().warnings.map((warning) => warning.id), ['log-2']);
});

await check('a failed acknowledgment keeps the warning and says so', async () => {
    const store = useSafetyWarningStore;
    answer = () => json({ error: 'Your acknowledgment could not be saved. Try again.' }, 500);
    assert.equal(await store.getState().acknowledge('log-2'), false);
    assert.equal(store.getState().error, SAFETY_WARNING_ACKNOWLEDGE_ERROR);
    assert.equal(store.getState().acknowledgingId, null);
    assert.deepEqual(store.getState().warnings.map((warning) => warning.id), ['log-2']);
});

await check('a warning the server no longer has is dropped', async () => {
    const store = useSafetyWarningStore;
    answer = () => json({ error: 'Warning not found.' }, 404);
    assert.equal(await store.getState().acknowledge('log-2'), true);
    assert.deepEqual(store.getState().warnings, []);
    assert.equal(store.getState().error, null);
});

console.log(`${checks} checks passed`);
