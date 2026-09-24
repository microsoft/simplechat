// test_v2_group_workspace_context_logic.mjs
// Version: 0.261.155
// Implemented in: 0.261.126
// Shared shell navigation and revalidation: 0.261.127
// Members section validation (M7B): 0.261.155
// Executes the real context API and stores with controlled HTTP ordering.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    GROUP_WORKSPACE_SECTION_IDS, isGroupWorkspaceContext, workspaceScopeKey,
    workspaceBasePath, requireWorkspaceId,
} = await import('../application/v2_ui/src/lib/workspaceContext.ts');
const { useBootstrapStore } = await import('../application/v2_ui/src/stores/bootstrapStore.ts');
const { resolveWorkspaceSections } = await import('../application/v2_ui/src/lib/workspaceSections.ts');
const { useGroupWorkspaceStore, WorkspaceRequestSuperseded } =
    await import('../application/v2_ui/src/stores/groupWorkspaceStore.ts');
const { groupWorkspaceNavigationAvailability, groupWorkspacePath, classicGroupSectionLabel } =
    await import('../application/v2_ui/src/lib/groupWorkspaceNavigation.ts');
const { GROUP_WORKSPACES } = await import('../application/v2_ui/src/lib/workspaces.ts');

const originalFetch = globalThis.fetch;
let calls = [];
let activeGroup = 'group-a';
let serverViewer = 'viewer';
let handler;
let checks = 0;

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
    return { promise, resolve, reject };
}

function context(id, viewer = serverViewer) {
    return {
        schema_version: 1, enabled: true, viewer_id: viewer, scope: { kind: 'group', id },
        workspace: {
            name: `Name ${id}`, description: `Description ${id}`,
            owner: { display_name: 'Owner', email: 'owner@example.test' },
            hero_color: '#0078d4', logo_url: null,
        },
        role: 'Owner', status: 'active', can_manage_workspace: true,
        sections: Object.fromEntries(GROUP_WORKSPACE_SECTION_IDS.map((id) => [
            id, {
                enabled: true, can_manage: true, reason: null,
                group: ['documents', 'tags', 'prompts', 'sync'].includes(id) ? 'knowledge'
                    : ['identities', 'endpoints'].includes(id) ? 'connections' : 'automation',
            },
        ])),
        document_permissions: {
            can_view: true, can_chat: true, can_upload: true, can_edit: true,
            can_delete: true, can_download: true,
        },
        document_queries: { sort_fields: ['_ts', 'file_name', 'title'], facets: false, places: false },
    };
}

function bootstrap(viewer = serverViewer, active = activeGroup) {
    return {
        user: { id: viewer, display_name: viewer, roles: ['User'], is_admin: false },
        scope: { active_group_id: active, groups: [], public_workspaces: [] },
        features: {},
    };
}

function json(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function defaultResponse(call) {
    if (call.path.startsWith('/api/v2/workspaces/group/')) {
        return json(context(decodeURIComponent(call.path.split('/').at(-1))));
    }
    if (call.path === '/api/groups/setActive' && call.method === 'PATCH') {
        activeGroup = call.body.groupId;
        return json({ message: 'Active group updated' });
    }
    if (call.path === '/api/v2/bootstrap') return json(bootstrap());
    throw new Error(`Unexpected request: ${call.method} ${call.path}`);
}

function reset() {
    useGroupWorkspaceStore.getState().clear();
    calls = [];
    activeGroup = 'group-a';
    serverViewer = 'viewer';
    handler = defaultResponse;
    useBootstrapStore.setState({ data: bootstrap(), authExpired: false, error: null, loading: false });
}

async function run(name, check) {
    reset();
    await check();
    checks += 1;
    console.log(`ok ${name}`);
}

globalThis.fetch = async (path, options = {}) => {
    const call = { path: String(path), method: options.method ?? 'GET', body: options.body ? JSON.parse(options.body) : null, signal: options.signal };
    calls.push(call);
    return handler(call);
};

try {
    await run('scope keys distinguish viewer, kind and workspace; paths encode identifiers', async () => {
        const keys = [
            workspaceScopeKey('viewer', { kind: 'personal', id: 'same' }),
            workspaceScopeKey('viewer', { kind: 'group', id: 'same' }),
            workspaceScopeKey('viewer', { kind: 'public', id: 'same' }),
            workspaceScopeKey('other', { kind: 'group', id: 'same' }),
        ];
        assert.equal(new Set(keys).size, 4);
        assert.equal(workspaceBasePath({ kind: 'group', id: 'a b' }), '/groups/a%20b');
        assert.equal(workspaceBasePath({ kind: 'public', id: 'a b' }), '/public/a%20b');
        assert.equal(workspaceBasePath({ kind: 'group', id: "a!'()*" }), '/groups/a%21%27%28%29%2A');
        assert.equal(workspaceBasePath({ kind: 'personal', id: 'viewer' }), '/workspace');
        for (const id of ['', '.', '..', ' leading', 'trailing ', 'a/b', 'a\\b', 'a?b', 'a#b', 'a\nb']) {
            assert.throws(() => requireWorkspaceId(id));
        }
    });
    await run('invalid context, foreign identities and unsafe asset URLs fail closed', async () => {
        const valid = context('group-a');
        assert.equal(isGroupWorkspaceContext(valid, 'viewer', 'group-a'), true);
        const punctuation = context("a!'()*");
        punctuation.workspace.logo_url = '/api/groups/a%21%27%28%29%2A/logo?v=3';
        assert.equal(isGroupWorkspaceContext(punctuation, 'viewer', "a!'()*"), true);
        const resolved = resolveWorkspaceSections(
            GROUP_WORKSPACE_SECTION_IDS.map((id) => ({ id, group: valid.sections[id].group })),
            valid,
        );
        assert.equal(resolved.length, GROUP_WORKSPACE_SECTION_IDS.length);
        assert.ok(resolved.every((entry) => entry.enabled));
        for (const mutate of [
            (value) => { value.enabled = 'true'; },
            (value) => { value.viewer_id = 'other'; },
            (value) => { value.scope.id = 'group-b'; },
            (value) => { value.scope.kind = 'personal'; },
            (value) => { value.role = ['Owner']; },
            (value) => { value.status = ['active']; },
            (value) => { delete value.sections.documents; },
            (value) => { value.sections.documents.group = 'unsupported'; },
            (value) => { value.sections.documents = { enabled: false, can_manage: true, reason: 'Denied' }; },
            (value) => { value.workspace.logo_url = 'https://external.example.test/logo.js'; },
            (value) => { value.workspace.hero_color = 'url(https://external.example.test)'; },
            (value) => { value.document_permissions.can_upload = 'true'; },
        ]) {
            const changed = structuredClone(valid);
            mutate(changed);
            assert.equal(isGroupWorkspaceContext(changed, 'viewer', 'group-a'), false);
        }
    });
    await run('a reported Members section must be a valid manage section; an absent one stays unavailable', async () => {
        const valid = context('group-a');
        assert.equal(isGroupWorkspaceContext(valid, 'viewer', 'group-a'), true, 'A context without it is still valid.');
        const withMembers = structuredClone(valid);
        withMembers.sections.members = { enabled: true, can_manage: true, reason: null, group: 'manage' };
        assert.equal(isGroupWorkspaceContext(withMembers, 'viewer', 'group-a'), true);
        for (const members of [
            { enabled: true, can_manage: true, reason: null, group: 'knowledge' },
            { enabled: false, can_manage: true, reason: 'Denied', group: 'manage' },
            { enabled: false, can_manage: false, reason: ' ', group: 'manage' },
            { enabled: 'true', can_manage: false, reason: null, group: 'manage' },
            null,
        ]) {
            const changed = structuredClone(valid);
            changed.sections.members = members;
            assert.equal(isGroupWorkspaceContext(changed, 'viewer', 'group-a'), false);
        }
        const misfiled = structuredClone(withMembers);
        misfiled.sections.documents.group = 'manage';
        assert.equal(isGroupWorkspaceContext(misfiled, 'viewer', 'group-a'), false, 'A content section never claims the manage group.');
        const missing = resolveWorkspaceSections([{ id: 'members', group: 'manage' }], valid);
        assert.deepEqual(missing.map((entry) => entry.enabled), [false], 'An unreported section is unavailable, never assumed.');
        const reported = resolveWorkspaceSections([{ id: 'members', group: 'manage' }], withMembers);
        assert.deepEqual(reported.map((entry) => entry.enabled), [true]);
        assert.equal(groupWorkspacePath('group-a', 'members'), '/groups/group-a/members');
        assert.equal(groupWorkspacePath('group-a', 'settings'), '/groups/group-a');
    });
    await run('explicit reads work without paging or changing the saved active group', async () => {
        const result = await useGroupWorkspaceStore.getState().load('group-1001');
        assert.equal(result.scope.id, 'group-1001');
        assert.equal(activeGroup, 'group-a');
        assert.deepEqual(calls.map((call) => call.path), ['/api/v2/workspaces/group/group-1001']);
        const punctuated = await useGroupWorkspaceStore.getState().load("a!'()*");
        assert.equal(punctuated.scope.id, "a!'()*");
        assert.equal(calls.at(-1).path, '/api/v2/workspaces/group/a%21%27%28%29%2A');
    });
    await run('an earlier successful response cannot populate a later scope', async () => {
        const slow = deferred();
        handler = (call) => call.path.endsWith('/group-a') ? slow.promise : defaultResponse(call);
        const first = useGroupWorkspaceStore.getState().load('group-a');
        const ignored = assert.rejects(first, WorkspaceRequestSuperseded);
        const second = await useGroupWorkspaceStore.getState().load('group-b');
        slow.resolve(json(context('group-a')));
        await ignored;
        assert.equal(second.scope.id, 'group-b');
        assert.equal(useGroupWorkspaceStore.getState().context.scope.id, 'group-b');
    });
    await run('read errors are not empty successful workspaces', async () => {
        handler = () => json({ error: 'private provider diagnostic' }, 503);
        const loading = useGroupWorkspaceStore.getState().load('group-a');
        await assert.rejects(loading, /Could not load/);
        assert.equal(useGroupWorkspaceStore.getState().context, null);
        assert.equal(useGroupWorkspaceStore.getState().loading, false);
        assert.ok(!useGroupWorkspaceStore.getState().error.includes('private'));
    });
    await run('malformed scoped data never installs context', async () => {
        handler = () => json(context('group-b'));
        const loading = useGroupWorkspaceStore.getState().load('group-a');
        await assert.rejects(loading);
        assert.equal(useGroupWorkspaceStore.getState().context, null);
    });
    await run('activation confirms drafts, authorization, persistence, catalogs and fresh context in order', async () => {
        await useGroupWorkspaceStore.getState().load('group-a');
        calls = [];
        let confirmed = false;
        handler = (call) => {
            assert.equal(confirmed, true);
            return defaultResponse(call);
        };
        const result = await useGroupWorkspaceStore.getState().activate('group-b', () => { confirmed = true; return true; });
        assert.equal(result.status, 'activated');
        assert.equal(result.context.scope.id, 'group-b');
        assert.deepEqual(calls.map(({ method, path }) => `${method} ${path}`), [
            'GET /api/v2/workspaces/group/group-b', 'PATCH /api/groups/setActive',
            'GET /api/v2/bootstrap', 'GET /api/v2/workspaces/group/group-b',
        ]);
        assert.deepEqual(calls[1].body, { groupId: 'group-b' });
        assert.equal(useBootstrapStore.getState().data.scope.active_group_id, 'group-b');
    });
    await run('cancelled draft guard performs no request and preserves prior context', async () => {
        const previous = await useGroupWorkspaceStore.getState().load('group-a');
        calls = [];
        const result = await useGroupWorkspaceStore.getState().activate('group-b', async () => false);
        assert.deepEqual(result, { status: 'cancelled' });
        assert.equal(useGroupWorkspaceStore.getState().context, previous);
        assert.equal(useGroupWorkspaceStore.getState().activating, false);
        assert.equal(calls.length, 0);
    });
    await run('activation writes are serialized, not cancelled by another selection', async () => {
        const confirmation = deferred();
        const first = useGroupWorkspaceStore.getState().activate('group-b', () => confirmation.promise);
        const second = useGroupWorkspaceStore.getState().activate('group-c', () => true);
        await assert.rejects(second, /already in progress/);
        confirmation.resolve(true);
        await first;
        assert.equal(calls.filter((call) => call.method === 'PATCH').length, 1);
        assert.equal(activeGroup, 'group-b');
    });
    for (const stage of ['preflight', 'write']) {
        await run(`${stage} rejection preserves the previous selection without a fake switch`, async () => {
            const previous = await useGroupWorkspaceStore.getState().load('group-a');
            calls = [];
            handler = (call) => (stage === 'preflight' || call.method === 'PATCH')
                ? json({ error: 'denied' }, 403) : defaultResponse(call);
            const switching = useGroupWorkspaceStore.getState().activate('group-b', () => true);
            await assert.rejects(switching, /permission/);
            assert.equal(useGroupWorkspaceStore.getState().context, previous);
            assert.equal(useGroupWorkspaceStore.getState().needsReconciliation, false);
            assert.equal(activeGroup, 'group-a');
            assert.equal(calls.some((call) => call.path === '/api/v2/bootstrap'), false);
        });
    }
    await run('lost write acknowledgement requires read-only reconciliation, never a replay', async () => {
        await useGroupWorkspaceStore.getState().load('group-a');
        handler = (call) => {
            const response = defaultResponse(call);
            if (call.method === 'PATCH') throw new TypeError('connection lost after commit');
            return response;
        };
        const switching = useGroupWorkspaceStore.getState().activate('group-b', () => true);
        await assert.rejects(switching, /could not be confirmed/);
        assert.equal(useGroupWorkspaceStore.getState().context, null);
        assert.equal(useGroupWorkspaceStore.getState().needsReconciliation, true);
        const blocked = useGroupWorkspaceStore.getState().load('group-a');
        await assert.rejects(blocked, /reconcile/);
        handler = defaultResponse;
        const recovered = await useGroupWorkspaceStore.getState().reconcile();
        assert.equal(recovered.scope.id, 'group-b');
        assert.equal(calls.filter((call) => call.method === 'PATCH').length, 1);
        assert.equal(useGroupWorkspaceStore.getState().needsReconciliation, false);
    });
    await run('failed mandatory refresh cannot reuse cached bootstrap authorization', async () => {
        handler = (call) => call.path === '/api/v2/bootstrap'
            ? json({ error: 'unavailable' }, 503) : defaultResponse(call);
        const switching = useGroupWorkspaceStore.getState().activate('group-b', () => true);
        await assert.rejects(switching, /could not be confirmed/);
        assert.equal(activeGroup, 'group-b');
        assert.equal(useBootstrapStore.getState().data.scope.active_group_id, 'group-a');
        assert.equal(useGroupWorkspaceStore.getState().context, null);
        const recovery = useGroupWorkspaceStore.getState().reconcile();
        await assert.rejects(recovery);
        assert.equal(useGroupWorkspaceStore.getState().needsReconciliation, true);
    });
    await run('revoked access after activation cannot leave stale editable details', async () => {
        let reads = 0;
        handler = (call) => {
            if (call.path.endsWith('/group-b') && ++reads > 1) return json({ error: 'revoked' }, 403);
            return defaultResponse(call);
        };
        const switching = useGroupWorkspaceStore.getState().activate('group-b', () => true);
        await assert.rejects(switching, /could not be confirmed/);
        assert.equal(useGroupWorkspaceStore.getState().context, null);
        assert.equal(useGroupWorkspaceStore.getState().needsReconciliation, true);
    });
    await run('a competing tab selection is reported rather than overwritten or hidden', async () => {
        handler = (call) => {
            if (call.path === '/api/v2/bootstrap') activeGroup = 'group-c';
            return defaultResponse(call);
        };
        const switching = useGroupWorkspaceStore.getState().activate('group-b', () => true);
        await assert.rejects(switching, /could not be confirmed/);
        assert.equal(useGroupWorkspaceStore.getState().context, null);
        const recovered = await useGroupWorkspaceStore.getState().reconcile();
        assert.equal(recovered.scope.id, 'group-c');
        assert.equal(calls.filter((call) => call.method === 'PATCH').length, 1);
    });
    await run('bootstrap changes during the final context read are detected', async () => {
        let reads = 0;
        const finalRead = deferred();
        const entered = deferred();
        handler = (call) => {
            if (call.path.endsWith('/group-b') && ++reads === 2) {
                entered.resolve();
                return finalRead.promise;
            }
            return defaultResponse(call);
        };
        const switching = useGroupWorkspaceStore.getState().activate('group-b', () => true);
        const rejected = assert.rejects(switching, /could not be confirmed/);
        await entered.promise;
        useBootstrapStore.setState({ data: bootstrap('viewer', 'group-c') });
        finalRead.resolve(json(context('group-b')));
        await rejected;
        assert.equal(useGroupWorkspaceStore.getState().context, null);
    });
    await run('a sign-in change discards pending read data from the previous viewer', async () => {
        const slow = deferred();
        handler = () => slow.promise;
        const reading = useGroupWorkspaceStore.getState().load('group-a');
        const rejected = assert.rejects(reading, WorkspaceRequestSuperseded);
        useBootstrapStore.setState({ data: bootstrap('other') });
        slow.resolve(json(context('group-a', 'viewer')));
        await rejected;
        assert.equal(useGroupWorkspaceStore.getState().context, null);
        assert.equal(useBootstrapStore.getState().data.user.id, 'other');
    });
    await run('missing bootstrap identity clears rather than retaining scoped permissions', async () => {
        await useGroupWorkspaceStore.getState().load('group-a');
        useBootstrapStore.setState({ data: { scope: { active_group_id: 'group-a' } } });
        assert.equal(useGroupWorkspaceStore.getState().context, null);
        const loading = useGroupWorkspaceStore.getState().load('group-a');
        await assert.rejects(loading, /Sign in again/);
    });
    await run('identity-bound refresh cannot restore another account after sign-in changes', async () => {
        const refresh = deferred();
        const entered = deferred();
        handler = (call) => {
            if (call.path === '/api/v2/bootstrap') {
                entered.resolve();
                return refresh.promise;
            }
            return defaultResponse(call);
        };
        const switching = useGroupWorkspaceStore.getState().activate('group-b', () => true);
        const rejected = assert.rejects(switching, WorkspaceRequestSuperseded);
        await entered.promise;
        useBootstrapStore.setState({ data: bootstrap('other', 'group-c') });
        refresh.resolve(json(bootstrap('viewer', 'group-b')));
        await rejected;
        assert.equal(useBootstrapStore.getState().data.user.id, 'other');
        assert.equal(useGroupWorkspaceStore.getState().context, null);
    });
    await run('reset does not unlock an in-flight server mutation', async () => {
        const write = deferred();
        const entered = deferred();
        handler = (call) => {
            if (call.method === 'PATCH') {
                entered.resolve();
                return write.promise;
            }
            return defaultResponse(call);
        };
        const first = useGroupWorkspaceStore.getState().activate('group-b', () => true);
        const rejected = assert.rejects(first, WorkspaceRequestSuperseded);
        await entered.promise;
        useGroupWorkspaceStore.getState().clear();
        const second = useGroupWorkspaceStore.getState().activate('group-c', () => true);
        await assert.rejects(second, /already in progress/);
        write.resolve(json({ message: 'Saved' }));
        await rejected;
        assert.equal(calls.filter((call) => call.method === 'PATCH').length, 1);
    });
    await run('reconciliation can report that no authorized active group remains', async () => {
        activeGroup = null;
        const result = await useGroupWorkspaceStore.getState().reconcile();
        assert.equal(result, null);
        assert.equal(useGroupWorkspaceStore.getState().needsReconciliation, false);
        assert.deepEqual(calls.map((call) => call.path), ['/api/v2/bootstrap']);
    });
    await run('native delegation remains navigable without claiming full action authoring is enabled', async () => {
        const value = context('group-a');
        value.sections.actions = { group: 'automation', enabled: false, reason: 'Full authoring is disabled.', can_manage: false };
        value.native_delegation = { group: 'automation', enabled: true, reason: null, can_manage: false };
        const navigation = groupWorkspaceNavigationAvailability(value);
        assert.equal(navigation.sections.actions.enabled, true);
        assert.equal(navigation.sections.actions.can_manage, false);
        assert.equal(value.sections.actions.enabled, false);
        assert.equal(groupWorkspacePath('group-b', 'workflows'), '/groups/group-b/workflows');
        assert.equal(groupWorkspacePath('group-b', 'unrecognized'), '/groups/group-b');
        assert.equal(classicGroupSectionLabel('tags', 'Tags'), 'Documents, then Manage Tags');
        assert.equal(classicGroupSectionLabel('sync', 'File sources'), 'Sync');
    });
    await run('list requests search server-side and preserve cancellation', async () => {
        handler = () => json({ groups: [{ id: 'group-z', name: 'Billing' }], total_count: 1001, page: 2, page_size: 25 });
        const controller = new AbortController();
        const result = await GROUP_WORKSPACES.list(2, 25, 'Billing & ops', controller.signal);
        assert.equal(result.totalCount, 1001);
        assert.equal(result.page, 2);
        assert.match(calls[0].path, /search=Billing\+%26\+ops/);
        assert.equal(calls[0].signal, controller.signal);
        handler = () => json({ error: 'not a workspace list' });
        const invalid = GROUP_WORKSPACES.list(1, 25, '');
        await assert.rejects(invalid, /invalid data/);
    });
    await run('revalidation keeps context while loading and retains drafts on transient failure', async () => {
        const previous = await useGroupWorkspaceStore.getState().load('group-a');
        const pending = deferred();
        handler = () => pending.promise;
        const refreshing = useGroupWorkspaceStore.getState().revalidate('group-a');
        const rejected = assert.rejects(refreshing, /Your changes are kept/);
        assert.equal(useGroupWorkspaceStore.getState().context, previous);
        assert.equal(useGroupWorkspaceStore.getState().refreshing, true);
        pending.resolve(json({ error: 'temporarily unavailable' }, 503));
        await rejected;
        assert.equal(useGroupWorkspaceStore.getState().context, previous);
        assert.equal(useGroupWorkspaceStore.getState().needsRevalidation, true);
        handler = defaultResponse;
        await useGroupWorkspaceStore.getState().revalidate('group-a');
        assert.equal(useGroupWorkspaceStore.getState().needsRevalidation, false);
        assert.equal(calls.some((call) => call.method === 'PATCH'), false);
    });
    await run('revoked revalidation removes stale permission and resource context', async () => {
        await useGroupWorkspaceStore.getState().load('group-a');
        handler = () => json({ error: 'revoked' }, 403);
        const refreshing = useGroupWorkspaceStore.getState().revalidate('group-a');
        await assert.rejects(refreshing, /permission/);
        assert.equal(useGroupWorkspaceStore.getState().context, null);
        assert.equal(useGroupWorkspaceStore.getState().refreshing, false);
    });
    await run('switching supersedes an older refocus revalidation', async () => {
        await useGroupWorkspaceStore.getState().load('group-a');
        const old = deferred();
        handler = (call) => call.path.endsWith('/group-a') ? old.promise : defaultResponse(call);
        const refreshing = useGroupWorkspaceStore.getState().revalidate('group-a');
        const superseded = assert.rejects(refreshing, WorkspaceRequestSuperseded);
        await useGroupWorkspaceStore.getState().activate('group-b', () => true);
        old.resolve(json(context('group-a')));
        await superseded;
        assert.equal(useGroupWorkspaceStore.getState().context.scope.id, 'group-b');
        assert.equal(useGroupWorkspaceStore.getState().refreshing, false);
    });
} finally {
    useGroupWorkspaceStore.getState().clear();
    globalThis.fetch = originalFetch;
}

console.log(`${checks} group workspace context checks passed.`);
