// test_v2_global_identities_logic.ts
//
// Runtime test for the global scope of the V2 identities workbench: the administrator's
// deployment-wide identities, created, edited and deleted from Admin Settings.
// Version: 0.261.445
// Implemented in: 0.261.445
//
// The global admin routes are the older family. A record carries no etag and no identity_actions,
// and a delete refused because actions still use the identity answers 409 with identity_in_use.
// What is worth executing is the transport and the gates: which URL each operation calls, what
// body it sends (an etag only when the record has one), how a 409 or a 412 reads, that 400/403/404
// are never swallowed or mistaken for a conflict, that a record from another scope is refused, and
// that nothing changed for the personal, group and public scopes that share the workbench.
//
// Run by test_v2_global_identities.py, which bundles this with esbuild and executes it under node,
// skipping when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ApiError } from '../application/v2_ui/src/lib/apiClient';
import {
    GLOBAL_IDENTITY_AUTH_TYPES,
    GLOBAL_IDENTITY_SCOPE_ID,
    GLOBAL_IDENTITY_WORKBENCH,
    IDENTITY_OPERATIONS,
    IdentityConflictError,
    IdentityInUseError,
    createGlobalIdentityWorkbench,
    createGroupIdentityWorkbench,
    createPublicIdentityWorkbench,
    identityOperationAllowed,
    type IdentityScope,
} from '../application/v2_ui/src/lib/identityWorkbench';
import {
    allowedAuthTypes,
    buildIdentityWrite,
    draftFromIdentity,
    emptyIdentityDraft,
} from '../application/v2_ui/src/lib/identityFields';
import { IdentityWorkbenchSection } from '../application/v2_ui/src/components/identities/IdentityWorkbenchSection';
import { GlobalIdentitiesList } from '../application/v2_ui/src/components/admin/GlobalIdentitiesList';
import type { WorkspaceIdentity } from '../application/v2_ui/src/lib/types';

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
    checks.push([name, fn]);
}

const BASE = '/api/admin/workspace-identities/global/identities';

interface Call {
    method: string;
    url: string;
    body?: Record<string, unknown>;
    hasBody: boolean;
}

function stubFetch(answer: (call: Call) => { status?: number; json?: unknown }): { calls: Call[]; restore: () => void } {
    const original = globalThis.fetch;
    const calls: Call[] = [];
    globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
        const call: Call = {
            method: init.method ?? 'GET',
            url: String(input),
            body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
            hasBody: init.body !== undefined,
        };
        calls.push(call);
        const reply = answer(call);
        return new Response(JSON.stringify(reply.json ?? {}), {
            status: reply.status ?? 200,
            headers: { 'content-type': 'application/json' },
        });
    }) as typeof fetch;
    return { calls, restore: () => { globalThis.fetch = original; } };
}

/** A global identity as sanitize_workspace_identity serves it: no etag, no identity_actions. */
function globalRecord(overrides: Record<string, unknown> = {}): WorkspaceIdentity {
    return {
        id: 'g1',
        identity_id: 'g1',
        type: 'workspace_identity',
        scope_type: 'global',
        global_id: 'global',
        name: 'Reporting API key',
        description: 'Used by the ticket action.',
        provider: 'action',
        source_type: 'action',
        usage_contexts: ['action'],
        supported_source_types: ['action'],
        metadata: {},
        created_at: '2026-10-06T12:00:00+00:00',
        updated_at: '2026-10-06T12:00:00+00:00',
        credentials: {
            auth_type: 'api_key', username: '', domain: '', identity: '', tenant_id: '',
            managed_identity_client_id: '', password_stored: false, secret_stored: true,
            password: '', secret: 'Stored_In_KeyVault',
        },
        ...overrides,
    } as WorkspaceIdentity;
}

const WRITE = { name: 'Renamed key', description: 'x', credentials: { auth_type: 'api_key', secret: '' } };

const ALL_OPERATIONS = new Set(IDENTITY_OPERATIONS);
const GLOBAL: IdentityScope = { kind: 'global' };

// ---------------------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------------------

check('every operation calls the admin route that names the global scope, and nothing else', async () => {
    const stub = stubFetch((call) => {
        if (call.method === 'GET') return { json: { identities: [globalRecord()] } };
        if (call.method === 'POST') return { status: 201, json: { identity: globalRecord({ id: 'g2' }) } };
        if (call.method === 'PATCH') return { json: { identity: globalRecord({ name: 'Renamed key' }) } };
        return { json: { message: 'Workspace identity deleted', delete_result: { identity_id: 'g1' } } };
    });
    try {
        const adapter = createGlobalIdentityWorkbench();
        const listed = await adapter.list();
        assert.deepEqual(listed.map((identity) => identity.id), ['g1']);
        const created = await adapter.create(WRITE);
        assert.equal(created.id, 'g2');
        const updated = await adapter.update(listed[0], WRITE);
        assert.equal(updated.name, 'Renamed key');
        await adapter.remove(listed[0]);

        assert.deepEqual(stub.calls.map((call) => `${call.method} ${call.url}`), [
            `GET ${BASE}`, `POST ${BASE}`, `PATCH ${BASE}/g1`, `DELETE ${BASE}/g1`,
        ]);
    } finally {
        stub.restore();
    }
});

check('a write carries only the documented fields, shaped as the classic editor sends them', async () => {
    const stub = stubFetch(() => ({ status: 201, json: { identity: globalRecord() } }));
    try {
        const draft = {
            ...emptyIdentityDraft(),
            name: '  Reporting API key ',
            description: 'Used by the ticket action.',
            capabilities: ['action', 'file_sync'],
        };
        draft.credentials = { ...draft.credentials, authType: 'api_key', secret: 'fixture-only-secret' };
        await createGlobalIdentityWorkbench().create(buildIdentityWrite(draft));

        assert.equal(stub.calls.length, 1);
        const body = stub.calls[0].body ?? {};
        assert.deepEqual(Object.keys(body).sort(), [
            'credentials', 'description', 'name', 'provider', 'source_type', 'supported_source_types', 'usage_contexts',
        ]);
        assert.equal(body.name, 'Reporting API key');
        assert.deepEqual(body.usage_contexts, ['action', 'file_sync']);
        assert.equal(body.provider, 'action');
        assert.deepEqual(body.credentials, {
            auth_type: 'api_key', username: '', domain: '', identity: '', client_id: '', secret: 'fixture-only-secret',
        });
        assert.ok(!('expected_etag' in body) && !('auth' in body), 'a create carries no version marker and no auth block');
    } finally {
        stub.restore();
    }
});

check('an edit and a delete send an etag only when the record has one', async () => {
    const stub = stubFetch((call) => (call.method === 'PATCH'
        ? { json: { identity: globalRecord() } }
        : { json: { message: 'Workspace identity deleted' } }));
    try {
        const adapter = createGlobalIdentityWorkbench();

        await adapter.update(globalRecord(), WRITE);
        await adapter.remove(globalRecord());
        assert.ok(!('expected_etag' in (stub.calls[0].body ?? {})), 'the routes version nothing today, so nothing is sent');
        assert.equal(stub.calls[1].hasBody, false, 'a delete without an etag has no body');

        await adapter.update(globalRecord({ etag: ' "etag-7" ' }), WRITE);
        await adapter.remove(globalRecord({ etag: ' "etag-7" ' }));
        assert.equal(stub.calls[2].body?.expected_etag, '"etag-7"');
        assert.deepEqual(stub.calls[3].body, { expected_etag: '"etag-7"' });

        await adapter.remove(globalRecord({ etag: '   ' }));
        assert.equal(stub.calls[4].hasBody, false, 'a blank etag is no etag');
    } finally {
        stub.restore();
    }
});

check('an identity id is encoded into the path, and one that could change the path is refused before any request', async () => {
    const stub = stubFetch(() => ({ json: { identity: globalRecord({ id: 'a b' }) } }));
    try {
        const adapter = createGlobalIdentityWorkbench();
        await adapter.update(globalRecord({ id: 'a b' }), WRITE);
        assert.equal(stub.calls[0].url, `${BASE}/a%20b`);

        for (const id of ['a/b', '../x', 'a?b', ' a', '']) {
            await assert.rejects(adapter.update(globalRecord({ id }), WRITE), /Invalid workspace identifier/);
            await assert.rejects(adapter.remove(globalRecord({ id })), /Invalid workspace identifier/);
        }
        assert.equal(stub.calls.length, 1, 'no request was made for a refused id');
    } finally {
        stub.restore();
    }
});

// ---------------------------------------------------------------------------------------
// Refusals
// ---------------------------------------------------------------------------------------

check('a refused delete is read as in use, with the references the server names', async () => {
    const stub = stubFetch(() => ({
        status: 409,
        json: {
            error: 'This workspace identity is still used by one or more File Sync sources or actions',
            error_code: 'identity_in_use',
            references: [
                { kind: 'action', id: 'action-1', name: 'Ticket search' },
                { kind: 'action', id: 'action-3', name: 'Roadmap' },
                'not a reference',
            ],
        },
    }));
    try {
        await assert.rejects(createGlobalIdentityWorkbench().remove(globalRecord()), (error: unknown) => {
            assert.ok(error instanceof IdentityInUseError);
            assert.equal(error.message, 'This workspace identity is still used by one or more File Sync sources or actions');
            assert.deepEqual(error.references, [
                { kind: 'action', id: 'action-1', name: 'Ticket search' },
                { kind: 'action', id: 'action-3', name: 'Roadmap' },
            ]);
            return true;
        });
    } finally {
        stub.restore();
    }
});

check('a 409 or a 412 that is not an in-use refusal is a conflict, and the server\u2019s words are kept', async () => {
    let answer: { status: number; json: unknown } = { status: 409, json: { error: 'Someone else saved this.', error_code: 'etag_conflict' } };
    const stub = stubFetch(() => answer);
    try {
        const adapter = createGlobalIdentityWorkbench();
        await assert.rejects(adapter.update(globalRecord(), WRITE), (error: unknown) =>
            error instanceof IdentityConflictError && error.message === 'Someone else saved this.');
        answer = { status: 412, json: {} };
        await assert.rejects(adapter.update(globalRecord(), WRITE), (error: unknown) =>
            error instanceof IdentityConflictError && /was modified/.test(error.message));
        await assert.rejects(adapter.remove(globalRecord()), (error: unknown) => error instanceof IdentityConflictError);
    } finally {
        stub.restore();
    }
});

check('validation, permission and missing-record answers are never swallowed or mistaken for a conflict', async () => {
    let answer: { status: number; json: unknown } = { status: 400, json: { error: 'Username/password identities require a password' } };
    const stub = stubFetch(() => answer);
    try {
        const adapter = createGlobalIdentityWorkbench();
        // The message is whatever ApiError reads from the answer: the server's sentence, or for the
        // admin guard's 403 its short code, with the full sentence still on the payload.
        const expectations: Array<[number, unknown, string]> = [
            [400, { error: 'Username/password identities require a password' }, 'Username/password identities require a password'],
            [403, { error: 'Forbidden', message: 'Insufficient permissions (Admin role required)' }, 'Forbidden'],
            [404, { error: 'Workspace identity not found' }, 'Workspace identity not found'],
            [500, { error: 'boom' }, 'boom'],
        ];
        for (const [status, json, message] of expectations) {
            answer = { status, json };
            for (const run of [() => adapter.update(globalRecord(), WRITE), () => adapter.remove(globalRecord()), () => adapter.create(WRITE)]) {
                await assert.rejects(run(), (error: unknown) => {
                    assert.ok(error instanceof ApiError, `${status} stays an ApiError`);
                    assert.equal(error.status, status);
                    assert.equal(error.message, message);
                    assert.deepEqual(error.payload, json);
                    assert.ok(!(error instanceof IdentityConflictError) && !(error instanceof IdentityInUseError));
                    return true;
                });
            }
        }
        answer = { status: 403, json: { error: 'Forbidden', message: 'Insufficient permissions (Admin role required)' } };
        await assert.rejects(adapter.list(), (error: unknown) => error instanceof ApiError && error.status === 403);
    } finally {
        stub.restore();
    }
});

// ---------------------------------------------------------------------------------------
// Scope validation
// ---------------------------------------------------------------------------------------

check('a record from another scope, or a malformed envelope, is refused rather than shown', async () => {
    let answer: unknown = { identities: [globalRecord(), globalRecord({ id: 'p1', scope_type: 'personal', global_id: undefined, user_id: 'u1' })] };
    const stub = stubFetch(() => ({ json: answer }));
    try {
        const adapter = createGlobalIdentityWorkbench();
        await assert.rejects(adapter.list(), /not a global identity/);

        answer = { identities: [globalRecord({ global_id: 'somewhere-else' })] };
        await assert.rejects(adapter.list(), /not a global identity/);

        answer = { identities: [globalRecord({ id: '' })] };
        await assert.rejects(adapter.list(), /not a global identity/);

        answer = { identity: globalRecord({ scope_type: 'group' }) };
        await assert.rejects(adapter.create(WRITE), /not a global identity/);

        answer = { identity: globalRecord({ id: 'another' }) };
        await assert.rejects(adapter.update(globalRecord(), WRITE), /not a global identity/);

        answer = { message: 'ok' };
        await assert.rejects(adapter.list(), /invalid identity list/);
        await assert.rejects(adapter.create(WRITE), /malformed/);
        answer = { identities: [] };
        assert.deepEqual(await adapter.list(), []);
    } finally {
        stub.restore();
    }
});

// ---------------------------------------------------------------------------------------
// Gates
// ---------------------------------------------------------------------------------------

check('the administrator-only surface is the gate, but an advertised identity_actions still wins', () => {
    const adapter = createGlobalIdentityWorkbench();
    assert.equal(adapter.scope.kind, 'global');
    assert.equal(adapter.manageable, true);
    assert.deepEqual([...adapter.supported].sort(), [...IDENTITY_OPERATIONS].sort());

    // No identity_actions on the record: every operation is available on an identity of this scope.
    assert.equal(adapter.allows('create'), true);
    assert.equal(adapter.allows('edit', globalRecord()), true);
    assert.equal(adapter.allows('delete', globalRecord()), true);
    assert.equal(adapter.allows('edit'), false, 'there is nothing to edit without a record');

    // A server that does advertise them is held to them, and a malformed value refuses.
    assert.equal(adapter.allows('edit', globalRecord({ identity_actions: ['edit'] })), true);
    assert.equal(adapter.allows('delete', globalRecord({ identity_actions: ['edit'] })), false);
    assert.equal(adapter.allows('edit', globalRecord({ identity_actions: [] })), false);
    assert.equal(adapter.allows('edit', globalRecord({ identity_actions: 'edit' })), false);
    assert.equal(adapter.allows('edit', globalRecord({ identity_actions: null })), false);

    // An identity that is not a global one is never offered an operation here.
    assert.equal(adapter.allows('edit', globalRecord({ scope_type: 'personal' })), false);
    assert.equal(adapter.allows('delete', globalRecord({ global_id: 'other' })), false);
    assert.equal(adapter.allows('edit', globalRecord({ global_id: undefined })), false);

    // A scope that supports nothing allows nothing.
    assert.equal(identityOperationAllowed(GLOBAL, new Set(), 'create'), false);
    assert.equal(identityOperationAllowed(GLOBAL, new Set(['create']), 'edit', globalRecord()), false);
    assert.equal(GLOBAL_IDENTITY_SCOPE_ID, 'global');
});

check('the authentication methods the global editor offers leave out anonymous, as the classic pane does', () => {
    assert.deepEqual([...GLOBAL_IDENTITY_AUTH_TYPES], [
        'username_password', 'api_key', 'bearer_token', 'client_secret', 'connection_string', 'managed_identity',
    ]);
    assert.deepEqual(allowedAuthTypes(['action'], GLOBAL_IDENTITY_AUTH_TYPES), [
        'api_key', 'bearer_token', 'client_secret', 'connection_string', 'username_password', 'managed_identity',
    ]);
    assert.deepEqual(allowedAuthTypes(['file_sync'], GLOBAL_IDENTITY_AUTH_TYPES), [
        'username_password', 'managed_identity', 'client_secret', 'connection_string',
    ]);
    assert.deepEqual(allowedAuthTypes(['file_sync', 'action'], GLOBAL_IDENTITY_AUTH_TYPES), [
        'username_password', 'managed_identity', 'client_secret', 'connection_string', 'api_key', 'bearer_token',
    ]);
    assert.deepEqual(allowedAuthTypes(['file_sync'], ['anonymous', 'api_key']), ['anonymous']);
    assert.deepEqual(allowedAuthTypes(['action'], ['anonymous']), ['username_password'], 'a form always has a method');
    assert.equal(createGlobalIdentityWorkbench().authTypes, GLOBAL_IDENTITY_AUTH_TYPES);
    assert.equal(GLOBAL_IDENTITY_WORKBENCH.scope.kind, 'global');
});

check('the editor opens an existing global identity the way classic does', () => {
    const draft = draftFromIdentity(globalRecord({
        usage_contexts: ['action', 'file_sync'],
        credentials: {
            auth_type: 'client_secret', username: '', domain: '', identity: 'app-client', tenant_id: 'tenant-1',
            managed_identity_client_id: '', password_stored: false, secret_stored: true, password: '', secret: 'Stored_In_KeyVault',
        },
    }));
    assert.deepEqual(draft.capabilities, ['file_sync', 'action']);
    assert.equal(draft.credentials.authType, 'client_secret');
    assert.equal(draft.credentials.clientId, 'app-client');
    assert.equal(draft.secretStored, true);
    assert.equal(draft.credentials.secret, '', 'a stored secret never reaches the form');
    const write = buildIdentityWrite(draft);
    assert.deepEqual(write.usage_contexts, ['file_sync', 'action']);
    assert.deepEqual(write.credentials, {
        auth_type: 'client_secret', username: '', domain: '', identity: 'app-client', client_id: 'app-client', secret: '',
    });
});

// ---------------------------------------------------------------------------------------
// The other scopes are unchanged
// ---------------------------------------------------------------------------------------

check('personal, group and public gates are exactly as strict as before', () => {
    const group: IdentityScope = { kind: 'group', id: 'group-1', name: 'Finance' };
    const publicScope: IdentityScope = { kind: 'public', id: 'pub-1', name: 'Library' };
    const personal: IdentityScope = { kind: 'personal', id: 'user-1' };

    // Without identity_actions nothing but create is offered; the global exemption does not leak.
    assert.equal(identityOperationAllowed(group, ALL_OPERATIONS, 'edit', { id: 'i', group_id: 'group-1' } as WorkspaceIdentity), false);
    assert.equal(identityOperationAllowed(publicScope, ALL_OPERATIONS, 'delete', { id: 'i', public_workspace_id: 'pub-1' } as WorkspaceIdentity), false);
    assert.equal(identityOperationAllowed(personal, ALL_OPERATIONS, 'edit', { id: 'i', scope_type: 'personal', user_id: 'user-1' } as WorkspaceIdentity), false);

    const advertised = ['edit', 'delete'];
    assert.equal(identityOperationAllowed(group, ALL_OPERATIONS, 'edit', { id: 'i', group_id: 'group-1', identity_actions: advertised } as WorkspaceIdentity), true);
    assert.equal(identityOperationAllowed(group, ALL_OPERATIONS, 'edit', { id: 'i', group_id: 'group-2', identity_actions: advertised } as WorkspaceIdentity), false);
    assert.equal(identityOperationAllowed(publicScope, ALL_OPERATIONS, 'delete', { id: 'i', public_workspace_id: 'pub-1', identity_actions: advertised } as WorkspaceIdentity), true);
    assert.equal(identityOperationAllowed(personal, ALL_OPERATIONS, 'edit', { id: 'i', scope_type: 'global', user_id: 'user-1', identity_actions: advertised } as WorkspaceIdentity), false);
    assert.equal(identityOperationAllowed(group, new Set(), 'create'), false, 'an absent hint still refuses a create');

    // A global record is not editable through another scope's gate.
    assert.equal(identityOperationAllowed(group, ALL_OPERATIONS, 'edit', globalRecord({ identity_actions: advertised })), false);

    // Only the global scope reads a 412 as a conflict; the strict scopes still read 409 alone.
    assert.throws(() => createGroupIdentityWorkbench({ kind: 'global' } as never, null), /explicit group scope/);
    assert.throws(() => createPublicIdentityWorkbench({ kind: 'global' } as never, null), /explicit public scope/);
});

check('group writes keep their strict contract: an etag is required and only 409 is a conflict', async () => {
    const scope = { kind: 'group', id: 'group-1', name: 'Finance' } as const;
    const operations = { schema_version: 1, operations: ['create', 'edit', 'delete'] };
    const record = { id: 'i1', group_id: 'group-1', etag: '"e1"', identity_actions: ['edit', 'delete'] } as WorkspaceIdentity;
    let status = 412;
    const stub = stubFetch(() => ({ status, json: { error: 'precondition' } }));
    try {
        const adapter = createGroupIdentityWorkbench(scope, operations);
        await assert.rejects(adapter.update({ ...record, etag: '' }, { name: 'x' }), /missing its version marker/);
        await assert.rejects(adapter.remove({ ...record, etag: undefined }), /missing its version marker/);
        assert.equal(stub.calls.length, 0);

        await assert.rejects(adapter.update(record, { name: 'x' }), (error: unknown) =>
            error instanceof ApiError && error.status === 412 && !(error instanceof IdentityConflictError));
        status = 409;
        await assert.rejects(adapter.update(record, { name: 'x' }), (error: unknown) => error instanceof IdentityConflictError);
        assert.equal(stub.calls[1].url, '/api/groups/group-1/identities/i1');
        assert.equal(stub.calls[1].body?.expected_etag, '"e1"');
        assert.ok(!stub.calls.some((call) => call.url.includes('/api/admin/')), 'a group never reaches the admin routes');
    } finally {
        stub.restore();
    }
});

// ---------------------------------------------------------------------------------------
// What the section draws
// ---------------------------------------------------------------------------------------

check('the administrator\u2019s card shows its own help beside New identity, and no classic hand-off', () => {
    const help = 'Credentials saved once and reused by File Sync sources and Actions.';
    const markup = renderToStaticMarkup(createElement(GlobalIdentitiesList, { help }));
    assert.match(markup, /data-testid="global-identities-list"/);
    assert.ok(markup.includes(help), 'the schema help text is shown as it is');
    assert.match(markup, /New identity/);
    assert.doesNotMatch(markup, /classic admin/i);
    assert.doesNotMatch(markup, /<h2/, 'the card is already titled, so the section adds no heading');
    assert.doesNotMatch(markup, /Used by /, 'the workspace wording is left out');
    assert.doesNotMatch(markup, /href=/, 'nothing here leaves V2');
});

check('a workspace section is drawn exactly as before', () => {
    const adapter = createGroupIdentityWorkbench(
        { kind: 'group', id: 'group-1', name: 'Finance' },
        { schema_version: 1, operations: ['create', 'edit', 'delete'] },
    );
    const markup = renderToStaticMarkup(createElement(IdentityWorkbenchSection, {
        adapter, syncEnabled: true, actionsEnabled: true,
    }));
    assert.match(markup, /<h2[^>]*>Identities<\/h2>/);
    assert.match(markup, /Sign-in details this group saves once and reuses\./);
    assert.match(markup, /Used by file sources and actions in this group\./);
    assert.match(markup, /Create one here to reuse it across the group\u2019s file sources and actions\./);
    assert.match(markup, /New identity/);
});

let passed = 0;
for (const [name, fn] of checks) {
    try {
        await fn();
        console.log(`  ok  ${name}`);
        passed += 1;
    } catch (error) {
        console.error(`  FAIL ${name}`);
        console.error(`       ${(error as Error).message}`);
    }
}

console.log(`\nResults: ${passed}/${checks.length} checks passed`);
process.exit(passed === checks.length ? 0 : 1);
