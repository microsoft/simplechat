// test_v2_legacy_document_upgrade_logic.ts
//
// Runtime test for the V2 "update older documents" logic: the list flag, the three upgrade routes,
// and the receipts they answer.
// Version: 0.261.445
// Implemented in: 0.261.445
//
// The judgement calls here do not show in a screenshot: that the flag the explorer reads is the one
// every list route sets, that a group or public workspace is upgraded through a route naming its
// own workspace (never the saved active one), that only a viewer the server lets edit metadata is
// offered the update, and that a receipt for another workspace, or one that cannot add up, is
// refused rather than shown as this workspace's result. Each is executed here against a stubbed
// fetch, so what the browser would send and accept is exactly what is asserted.
//
// Run by test_v2_legacy_document_upgrade.py, which bundles this with the esbuild Vite already
// brings in and executes it under node.

import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { LegacyUpgradeBanner } from '../application/v2_ui/src/components/documents/LegacyUpgradeBanner';
import { ApiError } from '../application/v2_ui/src/lib/apiClient';
import {
    canUpgradeLegacyDocuments,
    inspectLegacyUpgrade,
    legacyUpdateNeeded,
    legacyUpgradeCopy,
    legacyUpgradePath,
} from '../application/v2_ui/src/lib/documentLegacyUpgrade';
import {
    createGroupDocumentOperations,
    createPublicDocumentOperations,
    PERSONAL_DOCUMENT_OPERATIONS,
} from '../application/v2_ui/src/lib/documentOperations';
import {
    createGroupDocumentReader,
    createPublicDocumentReader,
    PERSONAL_DOCUMENT_READER,
} from '../application/v2_ui/src/lib/documentReadAdapter';

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
    checks.push([name, fn]);
}

interface Call {
    url: string;
    method: string;
    body: string | undefined;
}

/** Replaces fetch for one check, recording each request and answering it from `reply`. */
function stubFetch(reply: (call: Call) => { status?: number; body: unknown }): Call[] {
    const calls: Call[] = [];
    globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
        const call: Call = {
            url: String(input),
            method: init.method ?? 'GET',
            body: typeof init.body === 'string' ? init.body : undefined,
        };
        calls.push(call);
        const answer = reply(call);
        return new Response(JSON.stringify(answer.body), {
            status: answer.status ?? 200,
            headers: { 'content-type': 'application/json' },
        });
    }) as typeof fetch;
    return calls;
}

const GROUP = { kind: 'group', id: 'group-a', name: 'Group A' } as const;
const PUBLIC = { kind: 'public', id: 'public-a', name: 'Public A' } as const;
const PERSONAL = { kind: 'personal' } as const;
const MANAGER_HINT = {
    schema_version: 1,
    operations: ['upload', 'edit_metadata', 'tag_documents', 'manage_tags', 'delete', 'reprocess'],
};
const READER_HINT = { schema_version: 1, operations: ['download'] };
const CAPABILITIES = { sort_fields: ['_ts', 'file_name'], facets: true, places: true };

const groupReceipt = (overrides: Record<string, unknown> = {}) => ({
    message: 'Upgraded 2 group document(s) to the new format.',
    upgraded_count: 2, remaining: false, errors: [], group_id: 'group-a', ...overrides,
});
const publicReceipt = (overrides: Record<string, unknown> = {}) => ({
    message: 'Upgraded 3 public workspace document(s) to the new format.',
    upgraded_count: 3, remaining: false, errors: [], public_workspace_id: 'public-a', ...overrides,
});

async function rejection(promise: Promise<unknown>): Promise<Error> {
    try {
        await promise;
    } catch (cause) {
        return cause as Error;
    }
    throw new assert.AssertionError({ message: 'Expected the promise to reject.' });
}

/* ------------------------------------------------------------------------ The list flag */

check('only the boolean the server writes counts as a legacy flag', () => {
    assert.equal(legacyUpdateNeeded({ needs_legacy_update_check: true }), true);
    for (const value of [false, undefined, null, 'true', 1, {}]) {
        assert.equal(
            legacyUpdateNeeded({ needs_legacy_update_check: value as unknown as boolean }), false,
            `a ${typeof value} flag must not offer the update`,
        );
    }
    assert.equal(legacyUpdateNeeded({}), false, 'an older server sends no flag');
    assert.equal(legacyUpdateNeeded(null), false);
    assert.equal(legacyUpdateNeeded(undefined), false);
});

check('the personal list adapter passes the flag through', async () => {
    const calls = stubFetch(() => ({
        body: { documents: [], page: 1, page_size: 10, total_count: 0, needs_legacy_update_check: true },
    }));
    const response = await PERSONAL_DOCUMENT_READER.list({});
    assert.equal(legacyUpdateNeeded(response), true);
    assert.ok(calls[0].url.startsWith('/api/documents?'), calls[0].url);
});

check('the group list adapter reads the explicit-group list and passes the flag through', async () => {
    const calls = stubFetch(() => ({
        body: { documents: [], page: 1, page_size: 10, total_count: 0, needs_legacy_update_check: true },
    }));
    const reader = createGroupDocumentReader('group-a', 'Group A', CAPABILITIES as never);
    assert.equal(legacyUpdateNeeded(await reader.list({})), true);
    const url = new URL(calls[0].url, 'http://localhost');
    assert.equal(url.pathname, '/api/group_documents');
    assert.equal(url.searchParams.get('group_id'), 'group-a', 'the list must name its group, not use the active one');
    assert.equal(url.searchParams.has('group_ids'), false);
});

check('the public list adapter reads the explicit-workspace list and passes the flag through', async () => {
    const calls = stubFetch(() => ({
        body: { documents: [], page: 1, page_size: 10, total_count: 0, needs_legacy_update_check: true },
    }));
    const reader = createPublicDocumentReader('public-a', 'Public A', CAPABILITIES as never);
    assert.equal(legacyUpdateNeeded(await reader.list({})), true);
    assert.equal(new URL(calls[0].url, 'http://localhost').pathname, '/api/public-workspaces/public-a/documents');
});

check('a list that says nothing is legacy offers no update in any scope', async () => {
    stubFetch(() => ({ body: { documents: [], page: 1, page_size: 10, total_count: 0, needs_legacy_update_check: false } }));
    const group = createGroupDocumentReader('group-a', 'Group A', CAPABILITIES as never);
    const pub = createPublicDocumentReader('public-a', 'Public A', CAPABILITIES as never);
    for (const reader of [PERSONAL_DOCUMENT_READER, group, pub]) {
        assert.equal(legacyUpdateNeeded(await reader.list({})), false);
    }
});

/* ------------------------------------------------------------------- Who is offered it */

check('only a workspace whose operations include a metadata edit offers the update', () => {
    assert.equal(canUpgradeLegacyDocuments(new Set(['edit_metadata'])), true);
    assert.equal(canUpgradeLegacyDocuments(new Set(['download', 'delete', 'upload'])), false);
    assert.equal(canUpgradeLegacyDocuments(new Set()), false);
    assert.equal(createGroupDocumentOperations(GROUP, MANAGER_HINT).canUpgradeLegacy, true);
    assert.equal(createGroupDocumentOperations(GROUP, READER_HINT).canUpgradeLegacy, false, 'a reader is not offered it');
    assert.equal(createGroupDocumentOperations(GROUP, undefined).canUpgradeLegacy, false, 'a missing hint offers nothing');
    assert.equal(createPublicDocumentOperations(PUBLIC, MANAGER_HINT).canUpgradeLegacy, true);
    assert.equal(createPublicDocumentOperations(PUBLIC, { schema_version: 2, operations: ['edit_metadata'] }).canUpgradeLegacy, false);
    assert.equal(PERSONAL_DOCUMENT_OPERATIONS.canUpgradeLegacy, true, 'a user always manages their own documents');
});

check('a viewer who is not offered the update cannot send it', async () => {
    const calls = stubFetch(() => ({ body: groupReceipt() }));
    const reader = createGroupDocumentOperations(GROUP, READER_HINT);
    const error = await rejection(reader.upgradeLegacy());
    assert.match(error.message, /not available for this workspace/);
    assert.equal(calls.length, 0, 'no request may be made for a workspace the viewer cannot update');
});

/* ------------------------------------------------------------------- The three routes */

check('each scope calls its own upgrade route, never the saved active workspace', () => {
    assert.equal(legacyUpgradePath(PERSONAL), '/api/documents/upgrade_legacy');
    assert.equal(legacyUpgradePath(GROUP), '/api/groups/group-a/documents/upgrade_legacy');
    assert.equal(legacyUpgradePath(PUBLIC), '/api/public-workspaces/public-a/documents/upgrade_legacy');
    assert.equal(
        legacyUpgradePath({ kind: 'group', id: 'group 1%', name: 'x' }),
        '/api/groups/group%201%25/documents/upgrade_legacy', 'an id is encoded into its path segment',
    );
    for (const id of ['a/b', 'a?x=1', '..', ' a', 'a#b']) {
        assert.throws(() => legacyUpgradePath({ kind: 'public', id, name: 'x' }), /Invalid workspace identifier/,
            `${JSON.stringify(id)} could change which route the request reaches`);
    }
    for (const scope of [GROUP, PUBLIC]) {
        assert.ok(!legacyUpgradePath(scope).includes('group_documents'), 'the classic active-group route is not used');
        assert.ok(!legacyUpgradePath(scope).includes('public_documents'), 'the classic active-workspace route is not used');
    }
});

check('a group update posts with no body and reads the receipt', async () => {
    const calls = stubFetch(() => ({ body: groupReceipt() }));
    const outcome = await createGroupDocumentOperations(GROUP, MANAGER_HINT).upgradeLegacy();
    assert.deepEqual(calls.map((call) => [call.method, call.url, call.body]), [
        ['POST', '/api/groups/group-a/documents/upgrade_legacy', undefined],
    ]);
    assert.deepEqual(outcome, {
        message: 'Upgraded 2 group document(s) to the new format.', upgraded: 2, remaining: false, failures: [],
    });
});

check('a public update posts to the workspace named in the path', async () => {
    const calls = stubFetch(() => ({ body: publicReceipt() }));
    const outcome = await createPublicDocumentOperations(PUBLIC, MANAGER_HINT).upgradeLegacy();
    assert.deepEqual(calls.map((call) => [call.method, call.url]), [
        ['POST', '/api/public-workspaces/public-a/documents/upgrade_legacy'],
    ]);
    assert.equal(outcome.upgraded, 3);
});

check('a personal update posts to the personal route and reads only its sentence', async () => {
    const calls = stubFetch(() => ({ body: { message: 'Upgraded 4 document(s) to the new format.' } }));
    const outcome = await PERSONAL_DOCUMENT_OPERATIONS.upgradeLegacy();
    assert.deepEqual(calls.map((call) => [call.method, call.url, call.body]), [
        ['POST', '/api/documents/upgrade_legacy', undefined],
    ]);
    assert.deepEqual(outcome, {
        message: 'Upgraded 4 document(s) to the new format.', upgraded: null, remaining: false, failures: [],
    });
});

/* ---------------------------------------------------------------------- The receipts */

check('a partial result names each document the server could not update', async () => {
    stubFetch(() => ({
        status: 207,
        body: groupReceipt({
            message: 'Upgraded 1 group document(s) to the new format. 1 could not be updated.',
            upgraded_count: 1,
            errors: [
                { document_id: 'doc-1', file_name: 'Brief.pdf', error: 'legacy_upgrade_failed', message: 'Unable to update this document.' },
                { document_id: 'doc-2', message: '   ' },
            ],
        }),
    }));
    const outcome = await createGroupDocumentOperations(GROUP, MANAGER_HINT).upgradeLegacy();
    assert.equal(outcome.upgraded, 1);
    assert.deepEqual(outcome.failures, [
        { document_id: 'doc-1', file_name: 'Brief.pdf', message: 'Unable to update this document.' },
        { document_id: 'doc-2', file_name: null, message: 'This document could not be updated.' },
    ]);
});

check('a 207 that lists no failure is not accepted as a result', async () => {
    stubFetch(() => ({ status: 207, body: groupReceipt() }));
    const error = await rejection(createGroupDocumentOperations(GROUP, MANAGER_HINT).upgradeLegacy());
    assert.match(error.message, /did not return a complete operation receipt/);
});

check('a receipt that says older documents remain is carried through', async () => {
    stubFetch(() => ({
        body: groupReceipt({ upgraded_count: 500, remaining: true, message: 'Upgraded 500 group document(s) to the new format. More older documents remain; update again to continue.' }),
    }));
    const outcome = await createGroupDocumentOperations(GROUP, MANAGER_HINT).upgradeLegacy();
    assert.equal(outcome.remaining, true);
    assert.match(outcome.message, /More older documents remain/);
});

check('a receipt for another workspace is refused', async () => {
    stubFetch(() => ({ body: groupReceipt({ group_id: 'group-b' }) }));
    const group = await rejection(createGroupDocumentOperations(GROUP, MANAGER_HINT).upgradeLegacy());
    assert.match(group.message, /does not match this workspace/);
    stubFetch(() => ({ body: publicReceipt({ public_workspace_id: 'public-b' }) }));
    const pub = await rejection(createPublicDocumentOperations(PUBLIC, MANAGER_HINT).upgradeLegacy());
    assert.match(pub.message, /does not match this workspace/);
    // A group receipt cannot stand in for a public workspace's, whatever its id.
    stubFetch(() => ({ body: groupReceipt({ group_id: 'public-a' }) }));
    const crossed = await rejection(createPublicDocumentOperations(PUBLIC, MANAGER_HINT).upgradeLegacy());
    assert.match(crossed.message, /does not match this workspace/);
});

check('a receipt that cannot add up is refused', () => {
    const refuse = (response: unknown, scope = GROUP as never) =>
        assert.throws(() => inspectLegacyUpgrade(response, scope), /did not confirm the update/);
    refuse(null);
    refuse('Upgraded 2.');
    refuse({});
    refuse({ message: '   ' });
    refuse(groupReceipt({ upgraded_count: -1 }));
    refuse(groupReceipt({ upgraded_count: 1.5 }));
    refuse(groupReceipt({ upgraded_count: '2' }));
    refuse(groupReceipt({ remaining: 'no' }));
    refuse(groupReceipt({ errors: 'none' }));
    refuse(groupReceipt({ errors: [{ message: 'no id' }] }));
    refuse(groupReceipt({ errors: [null] }));
});

check('a refusal or failure reaches the person in the server\'s own words', async () => {
    stubFetch(() => ({ status: 403, body: { error: "You do not have permission to manage this group's documents." } }));
    const denied = await rejection(createGroupDocumentOperations(GROUP, MANAGER_HINT).upgradeLegacy());
    assert.ok(denied instanceof ApiError && denied.status === 403);
    assert.equal(denied.message, "You do not have permission to manage this group's documents.");

    stubFetch(() => ({ status: 500, body: { error: 'Unable to complete this public document operation.', public_workspace_id: 'public-a' } }));
    const failed = await rejection(createPublicDocumentOperations(PUBLIC, MANAGER_HINT).upgradeLegacy());
    assert.equal(failed.message, 'Unable to complete this public document operation.');

    stubFetch(() => ({ status: 500, body: { error: 'Upgrade failed' } }));
    const personal = await rejection(PERSONAL_DOCUMENT_OPERATIONS.upgradeLegacy());
    assert.equal(personal.message, 'Upgrade failed');
});

/* -------------------------------------------------------------------------- The notice */

check('each scope\'s notice says what is old and what updating restores', () => {
    for (const scope of [PERSONAL, GROUP, PUBLIC]) {
        const copy = legacyUpgradeCopy(scope);
        assert.match(copy.heading, /^Update older /);
        assert.match(copy.body, /uploaded with an older version/);
        assert.match(copy.body, /compatibility/);
    }
    assert.match(legacyUpgradeCopy(GROUP).heading, /group documents/);
    assert.match(legacyUpgradeCopy(PUBLIC).heading, /public workspace documents/);
});

check('the notice offers Update now and Maybe later, and says so while it runs', () => {
    const render = (props: { busy: boolean; incomplete: boolean }) => renderToStaticMarkup(createElement(
        LegacyUpgradeBanner, { scope: GROUP, onUpgrade: () => undefined, onDismiss: () => undefined, ...props },
    ));
    const idle = render({ busy: false, incomplete: false });
    assert.match(idle, /<section[^>]*aria-labelledby=/);
    assert.match(idle, /Update older group documents/);
    assert.match(idle, />Update now</);
    assert.match(idle, />Maybe later</);
    assert.doesNotMatch(idle, / disabled=""/);
    assert.doesNotMatch(idle, /still need updating/);

    const running = render({ busy: true, incomplete: false });
    assert.match(running, /Updating\.\.\./);
    assert.match(running, /role="status"/);
    assert.equal((running.match(/ disabled=""/g) ?? []).length, 2, 'both buttons are held while it runs');
    assert.doesNotMatch(running, />Update now</);

    const retry = render({ busy: false, incomplete: true });
    assert.match(retry, /Some older documents still need updating/);
    assert.match(retry, /role="status"/);
});

async function main() {
    let failed = 0;
    for (const [name, fn] of checks) {
        try {
            await fn();
            console.log(`  ok  ${name}`);
        } catch (error) {
            failed += 1;
            console.log(`  FAIL  ${name}`);
            console.log(error instanceof Error ? error.stack : String(error));
        }
    }
    if (failed) {
        console.log(`${failed} of ${checks.length} legacy document upgrade checks failed`);
        process.exit(1);
    }
}

void main();
