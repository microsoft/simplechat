// test_v2_admin_governance_logic.ts
//
// Runtime test for the rules the V2 Admin Settings governance editors apply.
// Version: 0.261.260
// Implemented in: 0.261.260
//
// The governance API stores whatever it is sent, so the mistakes worth catching are the
// ones that save cleanly and then mean something else: an Allow all policy sent with its
// allow lists still attached, which the server reads as restricted; an "inverse" that lets
// nobody through; a destination pattern such as `transport:streamable-http` that can never
// match; a governance switch shown as enforced while the feature it governs is off. None
// of these show up in a screenshot, so they are executed here.
//
// Run by test_v2_admin_governance_parity.py, which bundles this with the esbuild Vite
// already brings in and executes it under node. When that runner passes the schema's
// governance prerequisites in GOVERNANCE_SCHEMA_EXPECTATIONS, the enforcement badges are
// also checked against them, so the badges and the schema's notices cannot drift apart.

import assert from 'node:assert/strict';
import { ApiError } from '../application/v2_ui/src/lib/apiClient';
import {
    DEFAULT_MCP_TRANSPORTS,
    EMPTY_PRINCIPALS,
    GOVERNANCE_ENTITY_TYPES,
    GOVERNANCE_FEATURES,
    actionTypeLabel,
    allowsNobody,
    applyPrincipalImport,
    buildMcpDestinationItemId,
    cachedPrincipal,
    checkMcpDestinationPattern,
    describeFeatureEnforcement,
    draftFromItemPolicy,
    duplicateItemPolicy,
    fetchItemPolicyPage,
    governanceErrorMessage,
    inboundSourceOptions,
    inverseItemPolicy,
    itemPolicyPayload,
    mcpScopeOf,
    newItemPolicyDraft,
    normalizeActionType,
    normalizeEntityType,
    normalizePolicyState,
    parseMcpDestinationItemId,
    principalsForSave,
    readItemPolicy,
    resolvePrincipals,
    saveFeaturePolicy,
    summarizeAllowed,
    summarizeBlocked,
    validateItemPolicyDraft,
    type GovernanceItemPolicy,
    type McpPatternParts,
} from '../application/v2_ui/src/lib/governance';
import { useGovernanceStore } from '../application/v2_ui/src/stores/governanceStore';

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
    checks.push([name, fn]);
}

function itemPolicy(overrides: Partial<GovernanceItemPolicy> = {}): GovernanceItemPolicy {
    return {
        entity_type: 'global_agent',
        item_id: 'agent-1',
        policy_id: 'policy-1',
        policy_name: 'Research agent',
        resource_label: 'Research',
        system_managed: false,
        managed_reason: '',
        ...EMPTY_PRINCIPALS,
        ...overrides,
    };
}

interface RecordedRequest {
    url: string;
    method: string;
    body: unknown;
}

/** Answer API calls from a handler, recording what was asked. */
function stubFetch(handler: (request: RecordedRequest) => { status: number; body?: unknown }): RecordedRequest[] {
    const requests: RecordedRequest[] = [];
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
        const recorded = {
            url: String(input),
            method: String(init?.method ?? 'GET'),
            body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
        };
        requests.push(recorded);
        const { status, body } = handler(recorded);
        return new Response(body === undefined ? null : JSON.stringify(body), {
            status,
            headers: { 'content-type': 'application/json' },
        });
    }) as typeof fetch;
    return requests;
}

/* -------------------------------------------------------------------------- */
/* Principals                                                                  */
/* -------------------------------------------------------------------------- */

check('allow all with people listed is read as the restricted policy the server stores', () => {
    const normalized = normalizePolicyState({
        allow_all: true,
        allowed_users: [' ada ', 'ada', ''],
        allowed_groups: [],
        denied_users: ['bob', 'bob'],
        denied_groups: [],
    });
    assert.equal(normalized.allow_all, false);
    assert.deepEqual(normalized.allowed_users, ['ada']);
    assert.deepEqual(normalized.denied_users, ['bob']);

    const open = normalizePolicyState({ ...EMPTY_PRINCIPALS, allow_all: true });
    assert.equal(open.allow_all, true);
    assert.deepEqual(open.allowed_users, []);
});

check('an allow all save never carries the allow lists the editor keeps for undo', () => {
    const payload = principalsForSave({
        allow_all: true,
        allowed_users: ['ada'],
        allowed_groups: ['research'],
        denied_users: ['bob'],
        denied_groups: [' contractors '],
    });
    assert.deepEqual(payload, {
        allow_all: true,
        allowed_users: [],
        allowed_groups: [],
        denied_users: ['bob'],
        denied_groups: ['contractors'],
    });

    const restricted = principalsForSave({ ...EMPTY_PRINCIPALS, allow_all: false, allowed_users: ['ada'] });
    assert.deepEqual(restricted.allowed_users, ['ada']);
});

check('summaries say who passes, including the nobody case', () => {
    const nobody = { ...EMPTY_PRINCIPALS, allow_all: false };
    assert.equal(allowsNobody(nobody), true);
    assert.equal(summarizeAllowed(nobody), 'Nobody');
    assert.equal(summarizeAllowed(EMPTY_PRINCIPALS), 'Everyone');
    assert.equal(
        summarizeAllowed({ ...nobody, allowed_users: ['a', 'b'], allowed_groups: ['g'] }),
        '2 people · 1 group',
    );
    assert.equal(summarizeBlocked(EMPTY_PRINCIPALS), null);
    assert.equal(summarizeBlocked({ ...EMPTY_PRINCIPALS, denied_users: ['a'] }), '1 person');
});

check('pasted ids merge or replace, split on lines, commas, and semicolons', () => {
    assert.deepEqual(applyPrincipalImport(['a'], 'b\nc, a;d', 'merge'), ['a', 'b', 'c', 'd']);
    assert.deepEqual(applyPrincipalImport(['a'], ' b \r\n\r\nb', 'replace'), ['b']);
    assert.deepEqual(applyPrincipalImport(['a'], '', 'replace'), []);
});

/* -------------------------------------------------------------------------- */
/* Feature enforcement                                                         */
/* -------------------------------------------------------------------------- */

function feature(key: string) {
    const found = GOVERNANCE_FEATURES.find((entry) => entry.key === key);
    assert.ok(found, `GOVERNANCE_FEATURES is missing ${key}`);
    return found;
}

check('the nine feature policies are each described once', () => {
    const keys = GOVERNANCE_FEATURES.map((entry) => entry.key);
    assert.equal(new Set(keys).size, 9);
    assert.deepEqual([...new Set(GOVERNANCE_FEATURES.map((entry) => entry.scope))], ['personal', 'group', 'global']);
});

check('a governance switch is only enforced while the feature it governs is on', () => {
    const groupAgents = feature('governance_group_agents');
    assert.deepEqual(describeFeatureEnforcement(groupAgents, {}, {}), { state: 'off' });
    assert.deepEqual(
        describeFeatureEnforcement(groupAgents, { governance_group_agents: true, allow_group_agents: false }, {}),
        { state: 'waiting' },
    );
    assert.deepEqual(
        describeFeatureEnforcement(groupAgents, { governance_group_agents: true, allow_group_agents: true }, {}),
        { state: 'enforced' },
    );
});

check('an unsaved change is reported as pending rather than as the live state', () => {
    const groupAgents = feature('governance_group_agents');
    assert.deepEqual(
        describeFeatureEnforcement(
            groupAgents,
            { governance_group_agents: true, allow_group_agents: false },
            { allow_group_agents: true },
        ),
        { state: 'waiting', pending: 'enforced' },
    );
    assert.deepEqual(
        describeFeatureEnforcement(groupAgents, { governance_group_agents: true, allow_group_agents: true }, { governance_group_agents: false }),
        { state: 'enforced', pending: 'off' },
    );
});

check('global endpoints are enforced whatever the settings say', () => {
    const globalEndpoints = feature('governance_global_endpoints');
    assert.deepEqual(
        describeFeatureEnforcement(globalEndpoints, { governance_global_endpoints: false }, {}),
        { state: 'enforced' },
    );
});

check('enforcement badges name the same prerequisites as the schema notices', () => {
    const raw = process.env.GOVERNANCE_SCHEMA_EXPECTATIONS;
    if (!raw) {
        console.log('       (schema expectations not supplied; run through the Python runner to include)');
        return;
    }
    const expected = JSON.parse(raw) as Record<string, { key: string; section: string } | null>;
    assert.deepEqual(
        GOVERNANCE_FEATURES.map((entry) => entry.key).sort(),
        Object.keys(expected).sort(),
        'GOVERNANCE_FEATURES and the schema disagree on which governance switches exist',
    );
    for (const entry of GOVERNANCE_FEATURES) {
        const requirement = expected[entry.key];
        if (requirement === null) {
            assert.equal(entry.alwaysEnforced, true, `${entry.key} has no prerequisite, so it must be always enforced`);
            continue;
        }
        assert.ok(entry.primary, `${entry.key} needs a primary feature`);
        assert.equal(entry.primary.key, requirement.key, `${entry.key} waits on a different setting than the schema`);
        assert.equal(entry.primary.section, requirement.section, `${entry.key} links to a different section than the schema`);
    }
});

/* -------------------------------------------------------------------------- */
/* Delegated item policies                                                     */
/* -------------------------------------------------------------------------- */

check('every server entity type is offered, and the legacy endpoint alias resolves', () => {
    assert.equal(GOVERNANCE_ENTITY_TYPES.length, 10);
    assert.equal(normalizeEntityType('endpoint'), 'global_endpoint');
    assert.equal(normalizeEntityType(' MCP_GROUP_DESTINATION '), 'mcp_group_destination');
    assert.equal(normalizeEntityType('mcp_destination'), null);
});

check('the inverse of "everyone except A" is "only A", and back again', () => {
    const everyoneButBob = itemPolicy({ allow_all: true, denied_users: ['bob'] });
    const onlyBob = inverseItemPolicy(everyoneButBob);
    assert.equal(onlyBob.allow_all, false);
    assert.deepEqual(onlyBob.allowed_users, ['bob']);
    assert.deepEqual(onlyBob.denied_users, []);
    assert.equal(allowsNobody(onlyBob), false);

    const everyoneButAda = inverseItemPolicy(itemPolicy({ allow_all: false, allowed_users: ['ada'] }));
    assert.equal(everyoneButAda.allow_all, true, 'the classic inverse produced a policy nobody passes here');
    assert.deepEqual(everyoneButAda.denied_users, ['ada']);
    assert.deepEqual(everyoneButAda.allowed_users, []);
});

check('an inverse or a duplicate is a new policy on the same target', () => {
    const source = itemPolicy({ allow_all: false, allowed_groups: ['research'] });
    for (const [draft, suffix] of [[duplicateItemPolicy(source), '(copy)'], [inverseItemPolicy(source), '(inverse)']] as const) {
        assert.equal(draft.policy_id, '');
        assert.equal(draft.original, undefined, 'a copy must not move the original');
        assert.equal(draft.item_id, 'agent-1');
        assert.ok(draft.policy_name.endsWith(suffix));
    }
    const edit = draftFromItemPolicy(source);
    assert.deepEqual(edit.original, { entity_type: 'global_agent', item_id: 'agent-1', policy_id: 'policy-1' });
});

check('an edited policy is sent with its original target so a change moves it', () => {
    const draft = { ...draftFromItemPolicy(itemPolicy()), item_id: 'agent-2', allow_all: true, allowed_users: ['ada'] };
    const payload = itemPolicyPayload(draft);
    assert.equal(payload.original_item_id, 'agent-1');
    assert.equal(payload.original_entity_type, 'global_agent');
    assert.deepEqual(payload.allowed_users, []);

    const created = itemPolicyPayload(newItemPolicyDraft({ entity_type: 'mcp_personal_destination', item_id: ' *.contoso.com ' }));
    assert.equal(created.item_id, '*.contoso.com');
    assert.equal(created.resource_label, '*.contoso.com');
    assert.equal(created.policy_name, '*.contoso.com MCP Personal Destination Policy');
    assert.equal('original_item_id' in created, false);
});

check('a draft without a target, or with a changed policy id, is refused before saving', () => {
    assert.equal(
        validateItemPolicyDraft(newItemPolicyDraft({ entity_type: 'mcp_global_destination' })),
        'Enter the destination pattern this policy allows.',
    );
    assert.equal(
        validateItemPolicyDraft(newItemPolicyDraft({ entity_type: 'global_action' })),
        'Choose the item this policy applies to.',
    );
    const renamed = { ...draftFromItemPolicy(itemPolicy()), policy_id: 'other' };
    assert.equal(validateItemPolicyDraft(renamed), 'A saved policy keeps its policy ID.');
    assert.equal(validateItemPolicyDraft(draftFromItemPolicy(itemPolicy())), null);
});

check('a stored policy is read with defaults the classic page also applies', () => {
    const read = readItemPolicy({ entity_type: 'endpoint', item_id: 'conn-1', allowed_users: ['ada'] });
    assert.ok(read);
    assert.equal(read.entity_type, 'global_endpoint');
    assert.equal(read.allow_all, false, 'a listed person makes the policy restricted');
    assert.equal(read.policy_name, 'conn-1 Global Endpoint Policy');
    assert.equal(readItemPolicy({ entity_type: 'global_agent' }), null);
});

check('action types use the server aliases and labels', () => {
    assert.equal(normalizeActionType('Model Context Protocol'), 'mcp');
    assert.equal(actionTypeLabel('model_context_protocol'), 'MCP');
    assert.equal(normalizeActionType('sql_query'), 'sql');
    assert.equal(actionTypeLabel('custom_thing'), 'Custom Thing');
});

check('inbound sources offer * alone until the allowlist names sources', () => {
    assert.deepEqual(inboundSourceOptions({}).map((option) => option.value), ['*']);
    assert.deepEqual(inboundSourceOptions({ inbound_mcp_allow_all_source_ids: true }).map((option) => option.value), ['*']);
    const listed = inboundSourceOptions({
        inbound_mcp_allow_all_source_ids: false,
        inbound_mcp_allowed_source_entries: [
            { value: '*', description: 'everything' },
            { value: 'vscode', description: 'Editor' },
            { value: 'vscode', description: 'duplicate' },
            { value: 'cli' },
        ],
    });
    assert.deepEqual(listed.map((option) => option.value), ['*', 'vscode', 'cli']);
    assert.equal(listed[1].label, 'Editor');
    assert.equal(listed[1].detail, 'vscode');
});

check('failed governance requests read as sentences', () => {
    assert.match(governanceErrorMessage(new ApiError('x', 409, null), 'f'), /already governs a different item/);
    assert.match(governanceErrorMessage(new ApiError('x', 403, null), 'f'), /System-managed/);
    assert.match(governanceErrorMessage(new ApiError('x', 404, null), 'f'), /no longer exists/);
    assert.equal(governanceErrorMessage(new ApiError('Bad input', 400, null), 'f'), 'Bad input');
    assert.equal(governanceErrorMessage('nope', 'fallback'), 'fallback');
});

/* -------------------------------------------------------------------------- */
/* MCP destination patterns                                                    */
/* -------------------------------------------------------------------------- */

check('destination patterns round-trip through the builder', () => {
    const cases: [string, string, McpPatternParts][] = [
        ['mcp_personal_destination', '*', { kind: 'any', value: '' }],
        ['mcp_personal_destination', 'preconfiguration:microsoft_learn', { kind: 'preconfiguration', value: 'microsoft_learn' }],
        ['mcp_global_destination', 'preset:generic', { kind: 'preset', value: 'generic' }],
        ['mcp_global_destination', 'transport:sse', { kind: 'transport', value: 'sse' }],
        ['mcp_personal_destination', '*.contoso.com', { kind: 'host', value: '*.contoso.com' }],
        ['mcp_personal_destination', 'https://mcp.contoso.com/mcp*', { kind: 'url', value: 'https://mcp.contoso.com/mcp*' }],
        ['mcp_group_destination', 'group:g-1::preconfiguration:github', { kind: 'preconfiguration', value: 'github', groupId: 'g-1' }],
    ];
    for (const [entityType, itemId, parts] of cases) {
        assert.deepEqual(parseMcpDestinationItemId(itemId, entityType), parts, itemId);
        assert.equal(buildMcpDestinationItemId(parts, entityType), itemId, itemId);
    }
});

check('a group target only applies to group destination policies', () => {
    // Read as a host pattern in personal scope, exactly as the server matcher reads it.
    assert.deepEqual(parseMcpDestinationItemId('group:g-1::x', 'mcp_personal_destination'), {
        kind: 'host',
        value: 'group:g-1::x',
    });
    assert.equal(buildMcpDestinationItemId({ kind: 'host', value: 'a.com', groupId: 'g-1' }, 'mcp_personal_destination'), 'a.com');
    assert.equal(mcpScopeOf('mcp_group_destination'), 'group');
    assert.equal(mcpScopeOf('global_agent'), null);
});

check('the hyphenated transport the classic examples suggested is caught', () => {
    const result = checkMcpDestinationPattern({ kind: 'transport', value: 'streamable-http' });
    assert.equal(result.error, 'Use transport:streamable_http. The hyphenated form never matches.');
    assert.deepEqual(checkMcpDestinationPattern({ kind: 'transport', value: 'streamable_http' }), {});
    assert.match(checkMcpDestinationPattern({ kind: 'transport', value: 'stdio' }).error ?? '', /Choose one of: sse, streamable_http, websocket/);
    assert.deepEqual([...DEFAULT_MCP_TRANSPORTS], ['sse', 'streamable_http', 'websocket']);
});

check('host patterns match host names only', () => {
    assert.deepEqual(checkMcpDestinationPattern({ kind: 'host', value: '*.contoso.com' }), {});
    assert.match(checkMcpDestinationPattern({ kind: 'host', value: 'mcp.contoso.com:8443' }).error ?? '', /host name only/);
    assert.match(checkMcpDestinationPattern({ kind: 'host', value: 'contoso.com/mcp' }).error ?? '', /host name only/);
    assert.deepEqual(checkMcpDestinationPattern({ kind: 'host', value: 'mcp_server.internal' }), {});
    assert.match(checkMcpDestinationPattern({ kind: 'host', value: 'contoso!.com' }).error ?? '', /letters, numbers/);
});

check('URL patterns only take a * at the end of the path', () => {
    assert.deepEqual(checkMcpDestinationPattern({ kind: 'url', value: 'https://mcp.contoso.com/mcp*' }), {});
    assert.deepEqual(checkMcpDestinationPattern({ kind: 'url', value: 'https://*.contoso.com/mcp' }), {});
    assert.match(checkMcpDestinationPattern({ kind: 'url', value: 'https://mcp.contoso.com/*/mcp' }).error ?? '', /only works at the end/);
    assert.match(checkMcpDestinationPattern({ kind: 'url', value: 'https://mcp.contoso.com/mcp?x=1' }).error ?? '', /Query strings/);
    assert.match(checkMcpDestinationPattern({ kind: 'url', value: 'ftp://mcp.contoso.com/' }).error ?? '', /http, https, ws, or wss/);
    assert.match(checkMcpDestinationPattern({ kind: 'url', value: 'mcp.contoso.com' }).error ?? '', /full URL/);
});

check('catalog ids, blank values, spaces, and unpicked groups are refused', () => {
    assert.deepEqual(checkMcpDestinationPattern({ kind: 'preconfiguration', value: 'Microsoft_Learn' }), {});
    assert.match(checkMcpDestinationPattern({ kind: 'preset', value: 'bad!' }).error ?? '', /lowercase letters/);
    assert.equal(checkMcpDestinationPattern({ kind: 'host', value: ' ' }).error, 'Enter a host name pattern, such as *.contoso.com.');
    assert.equal(checkMcpDestinationPattern({ kind: 'preconfiguration', value: '' }).error, 'Choose a preconfigured server.');
    assert.equal(checkMcpDestinationPattern({ kind: 'host', value: 'a b' }).error, 'Patterns cannot contain spaces.');
    assert.equal(
        checkMcpDestinationPattern({ kind: 'any', value: '', groupId: '' }, DEFAULT_MCP_TRANSPORTS, true).error,
        'Choose the group this policy applies to.',
    );
    assert.ok(checkMcpDestinationPattern({ kind: 'any', value: '' }).warning, '* saves, with a warning');
});

/* -------------------------------------------------------------------------- */
/* API calls                                                                   */
/* -------------------------------------------------------------------------- */

check('the review list asks for several types, one item, and a page in one request', async () => {
    const requests = stubFetch(() => ({
        status: 200,
        body: {
            item_policies: [{ entity_type: 'mcp_group_destination', item_id: '*', policy_id: 'p1' }, { item_id: 'no-type' }],
            pagination: { page: 2, per_page: 10, total_items: 11, total_pages: 2, has_prev: true, has_next: false },
        },
    }));
    const page = await fetchItemPolicyPage({
        entityTypes: ['mcp_personal_destination', 'mcp_group_destination'],
        itemId: 'conn-1',
        search: '  Ada ',
        page: 2,
        perPage: 10,
    });
    const url = new URL(requests[0].url, 'http://localhost');
    assert.equal(url.pathname, '/api/admin/governance/item-policies/review');
    assert.equal(url.searchParams.get('entity_type'), 'mcp_personal_destination,mcp_group_destination');
    assert.equal(url.searchParams.get('item_id'), 'conn-1');
    assert.equal(url.searchParams.get('search'), 'Ada');
    assert.equal(url.searchParams.get('page'), '2');
    assert.equal(url.searchParams.get('per_page'), '10');
    assert.equal(page.policies.length, 1, 'a row without a type is dropped');
    assert.equal(page.pagination.total_items, 11);
});

check('a feature policy save sends what the server should store', async () => {
    const requests = stubFetch(() => ({ status: 200, body: { policy: { feature_key: 'governance_user_agents', allow_all: true } } }));
    const saved = await saveFeaturePolicy('governance_user_agents', {
        allow_all: true,
        allowed_users: ['ada'],
        allowed_groups: [],
        denied_users: ['bob'],
        denied_groups: [],
    });
    assert.equal(requests[0].method, 'PUT');
    assert.match(requests[0].url, /\/api\/admin\/governance\/policies\/governance_user_agents$/);
    assert.deepEqual(requests[0].body, {
        allow_all: true,
        allowed_users: [],
        allowed_groups: [],
        denied_users: ['bob'],
        denied_groups: [],
    });
    assert.equal(saved?.feature_key, 'governance_user_agents');
});

check('a group the directory does not return is marked missing; a failed person lookup is not', async () => {
    stubFetch(({ url }) => {
        if (url.includes('/principal-groups?ids=')) {
            return { status: 200, body: { groups: [{ id: 'g-live', name: 'Research', kind: 'public_workspace' }] } };
        }
        if (url.endsWith('/api/user/info/u-gone')) {
            return { status: 404, body: { error: 'User not found' } };
        }
        if (url.endsWith('/api/user/info/u-live')) {
            return { status: 200, body: { displayName: 'Ada Lovelace', email: 'ada@contoso.com' } };
        }
        return { status: 500, body: { error: 'Graph unavailable' } };
    });
    await resolvePrincipals('groups', ['g-live', 'g-gone']);
    assert.deepEqual(cachedPrincipal('groups', 'g-live'), {
        status: 'found',
        entry: { id: 'g-live', name: 'Research', detail: undefined, kind: 'public_workspace' },
    });
    assert.deepEqual(cachedPrincipal('groups', 'g-gone'), { status: 'missing' });

    await resolvePrincipals('users', ['u-live', 'u-gone', 'u-flaky']);
    assert.equal(cachedPrincipal('users', 'u-live')?.status, 'found');
    assert.deepEqual(cachedPrincipal('users', 'u-gone'), { status: 'missing' });
    assert.equal(cachedPrincipal('users', 'u-flaky'), undefined, 'a 500 is not a deleted person');
});

/* -------------------------------------------------------------------------- */
/* Dialog store                                                                */
/* -------------------------------------------------------------------------- */

check('an editor opened from a resource access list hands back to that list', () => {
    const store = useGovernanceStore;
    const target = { entityType: 'global_endpoint' as const, itemId: 'conn-1', label: 'Primary' };
    store.getState().openEditor({ draft: newItemPolicyDraft({ entity_type: 'global_endpoint', item_id: 'conn-1' }), returnTo: target });
    const editor = store.getState().dialog;
    assert.ok(editor && editor.kind === 'editor');

    store.getState().close(editor.id);
    const access = store.getState().dialog;
    assert.ok(access && access.kind === 'access');
    assert.ok(access.id > editor.id, 'the list remounts with fresh state');
    assert.deepEqual(access.target, target);

    store.getState().close(access.id);
    assert.equal(store.getState().dialog, null);

    store.getState().openEditor({ draft: newItemPolicyDraft({ entity_type: 'global_agent' }) });
    const standalone = store.getState().dialog;
    assert.ok(standalone);
    store.getState().close(standalone.id);
    assert.equal(store.getState().dialog, null, 'an editor opened on its own just closes');

    const revision = store.getState().revision;
    store.getState().markChanged();
    assert.equal(store.getState().revision, revision + 1);
});

check('a dialog closes only itself, so a late save cannot close its replacement', () => {
    const store = useGovernanceStore;
    const target = { entityType: 'global_endpoint' as const, itemId: 'conn-1', label: 'Primary' };
    store.getState().openEditor({ draft: newItemPolicyDraft({ entity_type: 'global_agent' }) });
    const replaced = store.getState().dialog;
    assert.ok(replaced);

    store.getState().openResourceAccess(target);
    const current = store.getState().dialog;
    assert.ok(current && current.id !== replaced.id);

    // The replaced editor's save settles and asks to close.
    store.getState().close(replaced.id);
    assert.equal(store.getState().dialog, current, 'the access list stayed open');

    store.getState().close(current.id);
    assert.equal(store.getState().dialog, null);
    store.getState().close(current.id);
    assert.equal(store.getState().dialog, null, 'closing twice is harmless');
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
