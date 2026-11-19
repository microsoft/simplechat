// test_v2_admin_parity_logic.ts
//
// Runtime test for the decisions behind the V2 admin links, the Control Center refresh strip,
// Duplicate on the global agent and action lists, and managing File Sync sources on behalf of
// another workspace.
// Version: 0.261.448
// Implemented in: 0.261.448
//
// Each of these used to send an administrator to the classic page or leave out an operation the
// classic page had. What is worth executing is the wording and the routing: a link that leaves V2
// must name the classic tab that holds the section (the classic page reads the address fragment as
// a tab id, so a section id there finds nothing), a refresh that skipped people must not read as a
// clean one, a copy of a record must never carry the original's stored credentials, and the
// administrator File Sync adapter must send the requests the administrator routes accept.
//
// Run by test_v2_admin_parity.py, which bundles this with esbuild and executes it under node,
// skipping when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ApiError } from '../application/v2_ui/src/lib/apiClient';
import {
    formatInstant,
    formatRelative,
    resolveAdminSectionLink,
    safeClassicAdminTabHref,
} from '../application/v2_ui/src/lib/adminOperations';
import {
    resolveAdminActionTarget,
    safeClassicAdminTabHref as shortcutClassicTabHref,
} from '../application/v2_ui/src/lib/latestFeatures';
import {
    describeAutoRefresh,
    describeLastRefresh,
    describeRefreshOutcome,
    readRefreshOutcome,
    readRefreshStatus,
} from '../application/v2_ui/src/lib/controlCenterRefresh';
import {
    describeDuplicate,
    duplicateActionDraft,
    duplicateAgentDraft,
    duplicateDisplayName,
    duplicateName,
    withoutSecretPaths,
} from '../application/v2_ui/src/lib/adminDuplicate';
import {
    adminSourceFromResponse,
    adminSourcesFromResponse,
    createAdminFileSourceWorkbench,
    describeCandidate,
    parseTargetCandidates,
    targetIdFrom,
    targetSearchQuery,
    targetSearchUrl,
    unavailableReason,
} from '../application/v2_ui/src/lib/adminFileSyncTargets';
import { FileSourceWriteConflictError } from '../application/v2_ui/src/lib/fileSourceWorkbench';
import { GLOBAL_ACTION_WORKBENCH } from '../application/v2_ui/src/lib/actionWorkbench';
import { GLOBAL_AGENT_WORKBENCH } from '../application/v2_ui/src/lib/agentWorkbench';
import { newAgentDraft } from '../application/v2_ui/src/lib/workspaceAgentAuthoring';
import { createActionDraft } from '../application/v2_ui/src/lib/workspaceActionLogic';
import {
    clearWorkspaceEditorDrafts,
    seedDuplicateEditorDraft,
    useWorkspaceEditorDraft,
} from '../application/v2_ui/src/lib/workspaceEditorDrafts';
import type { ActionConfiguration, AgentConfiguration, AuthoringResource } from '../application/v2_ui/src/lib/workspaceAuthoring';
import type { AdminNavGroup } from '../application/v2_ui/src/lib/types';
import { ChatModeNotice } from '../application/v2_ui/src/components/admin/ChatModeNotice';
import { RelatedSectionLink } from '../application/v2_ui/src/components/admin/RelatedSectionLink';

const checks: [string, () => void | Promise<void>][] = [];
function check(name: string, fn: () => void | Promise<void>) {
    checks.push([name, fn]);
}

const NOW = new Date('2026-10-06T12:00:00Z');

const NAV: AdminNavGroup[] = [
    {
        id: 'ai',
        label: 'AI',
        tabs: [
            {
                id: 'model-endpoints',
                label: 'AI Models',
                sections: [
                    { id: 'multi-endpoint-configuration', label: 'AI Connections' },
                    { id: 'standard-citations-section', label: 'Standard citations' },
                ],
            },
        ],
    },
    {
        id: 'agents-actions',
        label: 'Agents & Actions',
        tabs: [
            { id: 'agents', label: 'Agents', sections: [
                { id: 'agents-config', label: 'Agent Runtime' },
                { id: 'organization-agents-section', label: 'Global Agents' },
            ] },
            { id: 'actions', label: 'Actions', sections: [
                { id: 'actions-config', label: 'Global Actions' },
            ] },
        ],
    },
    {
        id: 'knowledge',
        label: 'Knowledge',
        tabs: [
            { id: 'workspaces', label: 'Workspaces', sections: [
                { id: 'workspace-identities-section', label: 'Workspace Identities' },
            ] },
        ],
    },
];

// ---------------------------------------------------------------------------------------
// Links that leave V2
// ---------------------------------------------------------------------------------------

check('a classic link names the tab, encoded, never a section', () => {
    assert.equal(safeClassicAdminTabHref('model-endpoints'), '/admin/settings?ui=classic#model-endpoints');
    assert.equal(safeClassicAdminTabHref('a b'), '/admin/settings?ui=classic#a%20b');
    assert.equal(safeClassicAdminTabHref('a"><script>'), '/admin/settings?ui=classic#a%22%3E%3Cscript%3E');
    // The shortcuts' helper is the same builder, so there is one place the address is made.
    assert.equal(shortcutClassicTabHref, safeClassicAdminTabHref);
});

check('a classic link carries the escape pair, so it still opens classic once the redirect to V2 is on', () => {
    // The pair is `ui=classic`; without it a server that selected the modern interface redirects the
    // classic address straight back to V2. Whatever the tab id holds, the result stays a same-site
    // path whose query is the pair alone and whose fragment is the tab id the classic page reads.
    const origin = 'http://simplechat.test';
    for (const tab of ['backup', 'workspace-identities', 'a/b', '//evil.example', 'x?ui=modern', 'x#y', '\\evil', 'a b', '']) {
        const href = safeClassicAdminTabHref(tab);
        assert.ok(href.startsWith('/admin/settings?ui=classic#'), href);
        assert.ok(!href.startsWith('//') && !href.includes('\\') && !/\s/.test(href), href);
        const url = new URL(href, origin);
        assert.equal(url.origin, origin);
        assert.equal(url.pathname, '/admin/settings');
        assert.equal(url.search, '?ui=classic');
        assert.equal(decodeURIComponent(url.hash.slice(1)), tab);
    }
});

check('a section V2 draws is linked within the page, even where a condition hides it', () => {
    const native = new Set(['multi-endpoint-configuration']);
    assert.deepEqual(resolveAdminSectionLink(NAV, 'multi-endpoint-configuration', native), {
        kind: 'section',
        sectionId: 'multi-endpoint-configuration',
    });
});

check('a section V2 never draws opens the classic tab that holds it', () => {
    const link = resolveAdminSectionLink(NAV, 'standard-citations-section', new Set());
    assert.deepEqual(link, { kind: 'classic', tabId: 'model-endpoints', tabLabel: 'AI Models' });
});

check('a section the navigation does not name yields no link at all', () => {
    assert.equal(resolveAdminSectionLink(NAV, 'no-such-section', new Set(['agents-config'])), null);
});

check('a related-section link moves within the page when V2 draws the section', () => {
    const location = { groupLabel: 'Knowledge', tabId: 'workspaces', tabLabel: 'Workspaces', sectionLabel: 'Workspace Identities' };
    const inPage = renderToStaticMarkup(
        createElement(RelatedSectionLink, { label: 'Workspace Identities', location, onNavigate: () => undefined }),
    );
    assert.match(inPage, /<button/);
    assert.doesNotMatch(inPage, /href=/);

    const classic = renderToStaticMarkup(createElement(RelatedSectionLink, { label: 'Workspace Identities', location }));
    assert.match(classic, /href="\/admin\/settings\?ui=classic#workspaces"/);
    assert.match(classic, /target="_blank"/);
    assert.match(classic, /rel="noopener noreferrer"/);
    assert.match(classic, /\(opens in a new tab\)/);

    assert.equal(renderToStaticMarkup(createElement(RelatedSectionLink, { label: 'x', location: null })), '');
});

check('the chat mode notice points at the connections section and at the classic endpoint tab', () => {
    const classic = renderToStaticMarkup(createElement(ChatModeNotice, { enabled: false, onNavigate: () => undefined }));
    assert.match(classic, /Go to AI Connections/);
    assert.match(classic, /href="\/admin\/settings\?ui=classic#model-endpoints"/);
    assert.match(classic, /target="_blank"/);
    assert.match(classic, /Use AI Connections for chat/);

    // On connections the classic endpoint is not consulted, so nothing links to it.
    const connections = renderToStaticMarkup(createElement(ChatModeNotice, { enabled: true, onNavigate: () => undefined }));
    assert.doesNotMatch(connections, /href=/);
    assert.doesNotMatch(connections, /Go to AI Connections/);
});

// ---------------------------------------------------------------------------------------
// Latest Features shortcuts
// ---------------------------------------------------------------------------------------

check('a shortcut naming a classic element lands on the V2 section that holds it', () => {
    const rendered = new Set(['agents-config', 'organization-agents-section', 'actions-config', 'workspace-identities-section', 'multi-endpoint-configuration']);
    const target = (section: string, tab: string) =>
        resolveAdminActionTarget({ admin_tab: tab, admin_section: section }, NAV, rendered);
    // Global Actions sits under Actions, but the announcement says Agents: the tab search
    // alone would land on the neighbouring Agent Runtime card.
    assert.deepEqual(target('plugins-table', 'agents'), { kind: 'section', sectionId: 'actions-config' });
    assert.deepEqual(target('agents-configuration', 'agents'), { kind: 'section', sectionId: 'organization-agents-section' });
    assert.deepEqual(target('model-endpoints-wrapper', 'model-endpoints'), { kind: 'section', sectionId: 'multi-endpoint-configuration' });
    assert.deepEqual(target('global-workspace-identities-root', 'workspaces'), { kind: 'section', sectionId: 'workspace-identities-section' });
});

check('a named section V2 renders wins over the alias, and an alias to an undrawn section falls back to the tab', () => {
    const direct = resolveAdminActionTarget(
        { admin_tab: 'agents', admin_section: 'agents-config' }, NAV, new Set(['agents-config', 'actions-config']),
    );
    assert.deepEqual(direct, { kind: 'section', sectionId: 'agents-config' });

    const undrawn = resolveAdminActionTarget(
        { admin_tab: 'agents', admin_section: 'plugins-table' }, NAV, new Set(['agents-config']),
    );
    assert.deepEqual(undrawn, { kind: 'section', sectionId: 'agents-config' });

    const unknown = resolveAdminActionTarget({ admin_tab: 'no-such-tab' }, NAV, new Set(['agents-config']));
    assert.deepEqual(unknown, { kind: 'classic', tab: 'no-such-tab' });
});

// ---------------------------------------------------------------------------------------
// Control Center refresh
// ---------------------------------------------------------------------------------------

check('the refresh status is read defensively', () => {
    assert.equal(readRefreshStatus(null), null);
    assert.equal(readRefreshStatus([]), null);
    const status = readRefreshStatus({
        last_refresh: '2026-10-06T10:30:00+00:00',
        auto_refresh_enabled: true,
        auto_refresh_time: '02:00',
        auto_refresh_timezone: 'America/New_York',
        auto_refresh_next_run_utc: '2026-10-07T06:00:00+00:00',
    });
    assert.ok(status);
    assert.equal(status.last.kind, 'instant');
    assert.equal(status.autoEnabled, true);
    assert.equal(status.autoTimezone, 'America/New_York');
    assert.equal(status.nextRun?.toISOString(), '2026-10-07T06:00:00.000Z');
});

check('the last refresh reads as a time, as written, as unreadable, or as never', () => {
    const at = new Date('2026-10-06T10:30:00Z');
    const instant = readRefreshStatus({ last_refresh: '2026-10-06T10:30:00+00:00' });
    assert.ok(instant);
    assert.equal(
        describeLastRefresh(instant, NOW, 'en-US'),
        `Data last refreshed ${formatInstant(at)} (${formatRelative(at, NOW, 'en-US')}).`,
    );

    // A value with no zone is shown as written, not converted on a guess.
    const legacy = readRefreshStatus({ last_refresh: '2026-10-06 10:30:00' });
    assert.ok(legacy);
    assert.equal(describeLastRefresh(legacy, NOW), 'Data last refreshed 2026-10-06 10:30:00, server time.');

    // A stored value that cannot be read is not the same as never having refreshed.
    const unreadable = readRefreshStatus({ last_refresh: '2026-13-45T00:00:00Z' });
    assert.ok(unreadable);
    assert.equal(describeLastRefresh(unreadable, NOW), 'The time of the last refresh could not be read.');

    const never = readRefreshStatus({ last_refresh: '' });
    assert.ok(never);
    assert.equal(describeLastRefresh(never, NOW), 'Data has not been refreshed yet.');
});

check('the daily schedule reads as off, as a schedule, or as a schedule with its next run', () => {
    const off = readRefreshStatus({ auto_refresh_enabled: false });
    assert.ok(off);
    assert.equal(describeAutoRefresh(off, NOW), 'Automatic refresh is off.');

    const noRun = readRefreshStatus({ auto_refresh_enabled: true, auto_refresh_time: '02:00', auto_refresh_timezone: 'UTC' });
    assert.ok(noRun);
    assert.match(describeAutoRefresh(noRun, NOW, 'en-US'), /^Automatic refresh daily at 2:00\s?AM UTC\.$/);

    const withRun = readRefreshStatus({
        auto_refresh_enabled: true,
        auto_refresh_time: '02:00',
        auto_refresh_timezone: 'UTC',
        auto_refresh_next_run_utc: '2026-10-07T02:00:00+00:00',
    });
    assert.ok(withRun);
    const next = new Date('2026-10-07T02:00:00Z');
    const schedule = describeAutoRefresh(noRun, NOW, 'en-US').replace(/\.$/, '');
    assert.equal(
        describeAutoRefresh(withRun, NOW, 'en-US'),
        `${schedule}; next ${formatInstant(next)} (${formatRelative(next, NOW, 'en-US')}).`,
    );
});

check('only an answer that says it succeeded counts as a refresh', () => {
    assert.equal(readRefreshOutcome(null), null);
    assert.equal(readRefreshOutcome({ success: false, error: 'x' }), null);
    assert.equal(readRefreshOutcome({ message: 'ok' }), null);
    assert.deepEqual(readRefreshOutcome({ success: true, refreshed_users: '3', refreshed_groups: 2, failed_users: -1, failed_groups: 'x' }), {
        users: 3, groups: 2, failedUsers: 0, failedGroups: 0,
    });
    assert.deepEqual(readRefreshOutcome({ success: true }), { users: 0, groups: 0, failedUsers: 0, failedGroups: 0 });
});

check('a refresh that skipped anyone is a warning, never a clean success', () => {
    assert.deepEqual(describeRefreshOutcome({ users: 5, groups: 2, failedUsers: 0, failedGroups: 0 }), {
        tone: 'success', text: 'Data refreshed. Updated 5 users and 2 groups.',
    });
    assert.deepEqual(describeRefreshOutcome({ users: 1, groups: 1, failedUsers: 0, failedGroups: 0 }), {
        tone: 'success', text: 'Data refreshed. Updated 1 user and 1 group.',
    });
    assert.deepEqual(describeRefreshOutcome({ users: 5, groups: 2, failedUsers: 1, failedGroups: 3 }), {
        tone: 'warning',
        text: 'Data refreshed with problems. Updated 5 users and 2 groups; 1 user and 3 groups could not be refreshed.',
    });
    assert.equal(describeRefreshOutcome({ users: 4, groups: 0, failedUsers: 0, failedGroups: 2 }).tone, 'warning');
});

// ---------------------------------------------------------------------------------------
// Duplicate a global agent or action
// ---------------------------------------------------------------------------------------

const MASK = '***REDACTED***';

check('a copy is named after the original and never reuses a name, ignoring case', () => {
    assert.equal(duplicateName('Research_Bot', []), 'Research_Bot_copy');
    assert.equal(duplicateName('Research_Bot', ['research_bot_copy']), 'Research_Bot_copy_2');
    assert.equal(duplicateName('Research_Bot', ['Research_Bot_copy', 'RESEARCH_BOT_COPY_2']), 'Research_Bot_copy_3');
    // A name has to stay inside the characters and length the server accepts.
    assert.equal(duplicateName('Research Bot', []), 'Research-Bot_copy');
    assert.equal(duplicateName('', []), 'copy_copy');
    const long = 'a'.repeat(100);
    assert.equal(duplicateName(long, []).length, 100);
    assert.ok(duplicateName(long, []).endsWith('_copy'));
    assert.equal(duplicateName(long, [duplicateName(long, [])]).length, 100);
    assert.ok(duplicateName(long, [duplicateName(long, [])]).endsWith('_copy_2'));
});

check('a copy takes a display name of its own', () => {
    assert.equal(duplicateDisplayName('Research Bot', 'Research_Bot'), 'Research Bot Copy');
    assert.equal(duplicateDisplayName('', 'Research_Bot'), 'Research_Bot Copy');
    assert.equal(duplicateDisplayName('  ', ''), 'Untitled Copy');
    assert.ok(duplicateDisplayName('x'.repeat(300), 'n').length <= 200);
});

check('removing secret paths leaves the original intact and keeps array positions', () => {
    const original = {
        auth: { type: 'key', key: MASK },
        additionalFields: { connection_string: MASK, list: ['a', MASK, 'c'] },
        metadata: { 'a/b': MASK, keep: 'yes' },
    };
    const cleaned = withoutSecretPaths(original, [
        '/auth/key', '/additionalFields/connection_string', '/additionalFields/list/1', '/metadata/a~1b',
        'not-a-pointer', '/missing/deep/path', '/additionalFields/list/9',
    ]);
    assert.deepEqual(cleaned, {
        auth: { type: 'key' },
        additionalFields: { list: ['a', '', 'c'] },
        metadata: { keep: 'yes' },
    });
    assert.equal(original.auth.key, MASK, 'The original must not be changed.');
    assert.equal(original.additionalFields.list[1], MASK);
});

function agentResource(): AuthoringResource<AgentConfiguration> {
    return {
        record: {
            id: 'agent-1',
            name: 'Research_Bot',
            display_name: 'Research Bot',
            description: 'Finds sources',
            instructions: 'Be brief',
            agent_type: 'local',
            actions_to_load: ['search'],
            other_settings: { depth: 2 },
            max_completion_tokens: 2000,
            azure_openai_gpt_key: MASK,
            azure_agent_apim_gpt_subscription_key: MASK,
            is_global: true,
            is_enabled: true,
            user_id: 'someone',
            last_updated: '2026-01-01T00:00:00Z',
            scope: 'global',
            _etag: 'abc',
        } as AgentConfiguration,
        revision: 'rev-1',
        secret_paths: ['/azure_openai_gpt_key', '/azure_agent_apim_gpt_subscription_key'],
        read_only: false,
    };
}

check('a copied agent carries its settings but none of its credentials, and starts disabled', () => {
    const copy = duplicateAgentDraft(agentResource(), ['Research_Bot']);
    const draft = copy.draft as Record<string, unknown>;
    assert.equal(copy.omittedSecrets, 2);
    assert.equal(draft.id, '');
    assert.equal(draft.name, 'Research_Bot_copy');
    assert.equal(draft.display_name, 'Research Bot Copy');
    assert.equal(draft.is_enabled, false);
    assert.equal(draft.instructions, 'Be brief');
    assert.deepEqual(draft.actions_to_load, ['search']);
    assert.deepEqual(draft.other_settings, { depth: 2 });
    assert.equal(draft.max_completion_tokens, 2000);
    assert.ok(!JSON.stringify(draft).includes('REDACTED'), 'No placeholder for a stored secret may reach the copy.');
    for (const stamped of ['user_id', 'last_updated', 'scope', '_etag', 'is_global']) {
        assert.ok(!(stamped in draft) || draft[stamped] === false, `${stamped} belongs to the original, not the copy`);
    }
});

check('a copied action carries its configuration but none of its credentials, and starts disabled', () => {
    const source: AuthoringResource<ActionConfiguration> = {
        record: {
            id: 'action-1',
            name: 'Blob_Reader',
            displayName: 'Blob Reader',
            description: 'Reads blobs',
            type: 'blob_storage',
            endpoint: 'https://example.blob.core.windows.net',
            auth: { type: 'key', key: MASK },
            additionalFields: { container: 'reports', sas: MASK },
            metadata: {},
            is_enabled: true,
            created_at: '2026-01-01T00:00:00Z',
        } as ActionConfiguration,
        revision: 'rev-2',
        secret_paths: ['/auth/key', '/additionalFields/sas'],
        read_only: false,
    };
    const copy = duplicateActionDraft(source, ['Blob_Reader_copy']);
    const draft = copy.draft as unknown as Record<string, unknown>;
    assert.equal(copy.omittedSecrets, 2);
    assert.equal(draft.id, '');
    assert.equal(draft.name, 'Blob_Reader_copy_2');
    assert.equal(draft.displayName, 'Blob Reader Copy');
    assert.equal(draft.is_enabled, false);
    assert.equal(draft.endpoint, 'https://example.blob.core.windows.net');
    assert.deepEqual(draft.auth, { type: 'key' });
    assert.deepEqual(draft.additionalFields, { container: 'reports' });
    assert.ok(!('created_at' in draft));
    assert.ok(!JSON.stringify(draft).includes('REDACTED'));
});

check('the notice says what was left out and that the copy is off', () => {
    assert.equal(
        describeDuplicate('Research Bot', 0),
        'Editing a copy of Research Bot. It starts disabled; enable it from the list once it is ready.',
    );
    assert.match(describeDuplicate('Research Bot', 1), /The stored credential was not copied, so enter new ones before saving\.$/);
    assert.match(describeDuplicate('Research Bot', 3), /The 3 stored credentials were not copied/);
});

/** What the editor's draft hook holds for the new-record key, as the editor pages build it. */
function agentEditorDraft(scope: typeof GLOBAL_AGENT_WORKBENCH.draftScope | undefined): string {
    function Probe() {
        const { draft, dirty, restored } = useWorkspaceEditorDraft<AgentConfiguration>(
            'agents', `${'personal'}:${'new'}`, newAgentDraft, scope,
        );
        return createElement('p', null, `${draft.name}|${dirty}|${restored}`);
    }
    return renderToStaticMarkup(createElement(Probe)).replace(/<\/?p>/g, '');
}

function actionEditorDraft(scope: typeof GLOBAL_ACTION_WORKBENCH.draftScope | undefined): string {
    function Probe() {
        const { draft, dirty, restored } = useWorkspaceEditorDraft<ActionConfiguration>(
            'actions', JSON.stringify(['personal', 'new', null]), createActionDraft, scope,
        );
        return createElement('p', null, `${draft.name}|${dirty}|${restored}`);
    }
    return renderToStaticMarkup(createElement(Probe)).replace(/<\/?p>/g, '');
}

check('a copy reaches the global new-record editors, and no other editor sees it', () => {
    clearWorkspaceEditorDrafts();
    const agent = duplicateAgentDraft(agentResource(), ['Research_Bot']);
    assert.equal(seedDuplicateEditorDraft('agents', agent.draft, newAgentDraft(), GLOBAL_AGENT_WORKBENCH.draftScope), true);
    // The editor reads the copy as an unsaved draft, so leaving it asks before discarding.
    assert.equal(agentEditorDraft(GLOBAL_AGENT_WORKBENCH.draftScope), 'Research_Bot_copy|true|true');
    // A personal editor, or one for another scope, starts empty: a copy never crosses scopes.
    assert.equal(agentEditorDraft(undefined), '|false|false');

    const action = duplicateActionDraft(
        {
            record: { id: 'a1', name: 'Blob_Reader', displayName: 'Blob Reader', description: '', type: 'x', endpoint: '',
                auth: { type: 'key' }, metadata: {}, additionalFields: {} } as ActionConfiguration,
            revision: 'r', secret_paths: [], read_only: false,
        },
        [],
    );
    assert.equal(seedDuplicateEditorDraft('actions', action.draft, createActionDraft(), GLOBAL_ACTION_WORKBENCH.draftScope), true);
    assert.equal(actionEditorDraft(GLOBAL_ACTION_WORKBENCH.draftScope), 'Blob_Reader_copy|true|true');
    assert.equal(actionEditorDraft(undefined), '|false|false');
    clearWorkspaceEditorDrafts();
});

check('a copy never replaces a new record someone is already writing', () => {
    clearWorkspaceEditorDrafts();
    const first = duplicateAgentDraft(agentResource(), []);
    const scope = GLOBAL_AGENT_WORKBENCH.draftScope;
    assert.equal(seedDuplicateEditorDraft('agents', first.draft, newAgentDraft(), scope), true);
    const second = duplicateAgentDraft({ ...agentResource(), record: { ...agentResource().record, name: 'Other' } }, []);
    assert.equal(seedDuplicateEditorDraft('agents', second.draft, newAgentDraft(), scope), false);
    assert.equal(agentEditorDraft(scope), 'Research_Bot_copy|true|true', 'The draft in progress must be kept.');

    // Once it is discarded, or was never changed, a copy can be started.
    clearWorkspaceEditorDrafts();
    assert.equal(seedDuplicateEditorDraft('agents', second.draft, newAgentDraft(), scope), true);
    clearWorkspaceEditorDrafts();
});

// ---------------------------------------------------------------------------------------
// File Sync sources managed for another workspace
// ---------------------------------------------------------------------------------------

check('a search shorter than the server answers is not sent', () => {
    assert.deepEqual(targetSearchQuery(' a '), { error: 'Type at least 2 characters to search.' });
    assert.deepEqual(targetSearchQuery('  ab '), { query: 'ab' });
    assert.equal(targetSearchUrl('group', 'a b&c'), '/api/admin/file-sync/groups/search?q=a%20b%26c');
    assert.equal(targetSearchUrl('personal', 'jane'), '/api/admin/file-sync/users/search?q=jane');
    assert.equal(targetSearchUrl('public', 'pol'), '/api/admin/file-sync/public-workspaces/search?q=pol');
});

check('search results without an id are dropped, and a changed response is an error, not "no matches"', () => {
    assert.deepEqual(
        parseTargetCandidates('personal', {
            users: [
                { id: 'u1', displayName: 'Jane Doe', email: 'jane@contoso.test' },
                { displayName: 'Nobody' },
                { id: 'u2', email: 'k@contoso.test' },
            ],
        }),
        [
            { id: 'u1', title: 'Jane Doe', subtitle: 'jane@contoso.test' },
            { id: 'u2', title: 'k@contoso.test', subtitle: 'k@contoso.test' },
        ],
    );
    assert.deepEqual(
        parseTargetCandidates('group', { groups: [{ id: 'g1', name: 'Finance', description: 'Team' }, { id: 'g2' }] }),
        [{ id: 'g1', title: 'Finance', subtitle: 'Team' }, { id: 'g2', title: 'g2', subtitle: '' }],
    );
    assert.deepEqual(parseTargetCandidates('public', { workspaces: [] }), []);
    assert.throws(() => parseTargetCandidates('group', { users: [] }), /malformed/);
    assert.throws(() => parseTargetCandidates('group', null), /malformed/);
    assert.equal(describeCandidate({ id: 'g1', title: 'Finance', subtitle: 'Team' }), 'Finance (Team)');
    assert.equal(describeCandidate({ id: 'u2', title: 'k@x', subtitle: 'k@x' }), 'k@x');
});

check('a pasted id is checked before it can name a route', () => {
    assert.deepEqual(targetIdFrom(''), { error: 'Choose a search result or enter an ID.' });
    assert.deepEqual(targetIdFrom(' user-9 '), { id: 'user-9' });
    for (const bad of ['a/b', 'a\\b', '..', 'a?b', 'a#b', 'a\u0000b']) {
        assert.ok('error' in targetIdFrom(bad), `${JSON.stringify(bad)} must be refused`);
    }
});

check('a kind of workspace is offered only while the saved settings turn it on', () => {
    const all = { fileSync: true, redis: true, personal: true, group: true, public: true };
    assert.equal(unavailableReason('group', all), null);
    assert.match(unavailableReason('group', { ...all, fileSync: false }) ?? '', /^File Sync is not on in the saved settings/);
    // The server treats File Sync as off without Redis, so a manager it would refuse is not offered.
    assert.match(unavailableReason('group', { ...all, redis: false }) ?? '', /^Redis Cache is off in the saved settings/);
    assert.match(unavailableReason('public', { ...all, public: false }) ?? '', /^Public workspaces is off in the saved settings/);
    assert.match(unavailableReason('personal', { ...all, personal: false }) ?? '', /manage user sources/);
});

check('administrator list and write envelopes are read, and every row is offered every operation', () => {
    const sources = adminSourcesFromResponse({ sources: [{ id: 's1', name: 'One' }, { id: 's2' }] });
    assert.equal(sources.length, 2);
    assert.deepEqual(sources[0].source_actions, ['edit', 'delete', 'sync', 'test']);
    assert.equal(adminSourceFromResponse({ source: { id: 's3' } }).id, 's3');
    assert.throws(() => adminSourcesFromResponse({ file_sources: [] }), /malformed/);
    assert.throws(() => adminSourcesFromResponse({ sources: [{ name: 'no id' }] }), /malformed/);
    assert.throws(() => adminSourceFromResponse({ file_source: { id: 's1' } }), /malformed/);
});

interface Call {
    method: string;
    url: string;
    body: unknown;
}

/** Answers every request from `answer`, recording what was sent. */
function stubFetch(answer: (call: Call) => { status?: number; json?: unknown }): { calls: Call[]; restore: () => void } {
    const original = globalThis.fetch;
    const calls: Call[] = [];
    globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
        const call: Call = {
            method: init.method ?? 'GET',
            url: String(input),
            body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
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

const SOURCE = { id: 's1', name: 'Quarterly share' };
const DELETE_RESULT = { associated_files_requested: true, documents_deleted: 2, documents_skipped: 0, documents_failed: 0 };

check('the administrator adapter sends each operation to the route that names the target', async () => {
    const stub = stubFetch((call) => {
        if (call.url.endsWith('/sources') && call.method === 'GET') return { json: { sources: [SOURCE] } };
        if (call.url.endsWith('/sources') && call.method === 'POST') return { status: 201, json: { source: { id: 's2' } } };
        if (call.method === 'PATCH') return { json: { source: { id: 's1', name: 'Renamed' } } };
        if (call.method === 'DELETE') return { json: { delete_result: DELETE_RESULT } };
        if (call.url.endsWith('/source-options')) {
            return { json: {
                source_types: [{ value: 'smb', label: 'SMB Share', visible: true }],
                eligible_identity_ids: { smb: [] },
                schedule: { min_interval_minutes: 15, max_interval_minutes: 10080 },
                limits: { max_sources: 10 },
                recursive_allowed: true,
            } };
        }
        if (call.url.endsWith('/identities')) return { json: { identities: [{ id: 'i1' }] } };
        if (call.url.endsWith('/runs')) return { json: { runs: [{ id: 'r1', status: 'completed' }] } };
        if (call.url.endsWith('/sync')) return { status: 202, json: { run: { id: 'r2', status: 'queued' } } };
        if (call.url.endsWith('/test-connection')) return { json: { connection: { success: true, entries_checked: 1 } } };
        if (call.url.endsWith('/browse')) return { json: { browse: { path: '', entries: [{ name: 'a', type: 'folder' }] } } };
        throw new Error(`Unexpected request ${call.method} ${call.url}`);
    });
    try {
        const adapter = createAdminFileSourceWorkbench({ scope: 'group', id: 'group-1', label: 'Finance' });
        const base = '/api/admin/file-sync/group/group-1';
        assert.deepEqual(adapter.scope, { kind: 'group', id: 'group-1', name: 'Finance' });
        assert.equal(adapter.manageable, true);
        assert.equal(adapter.allows('edit', undefined), true);

        const listed = await adapter.list();
        assert.equal(listed[0].id, 's1');

        const write = { name: 'n', source_type: 'smb' };
        assert.equal((await adapter.create(write)).id, 's2');
        const updated = await adapter.update(listed[0], write);
        assert.equal(updated.name, 'Renamed');
        assert.equal((await adapter.remove(listed[0], true)).documents_deleted, 2);
        assert.equal((await adapter.options())?.limits.max_sources, 10);
        assert.equal((await adapter.identities())[0].id, 'i1');
        assert.equal((await adapter.runs('s1'))[0].id, 'r1');
        assert.equal((await adapter.sync('s1'))?.id, 'r2');
        assert.equal((await adapter.testConnection(null, write)).success, true);
        await adapter.testConnection(listed[0], null);
        assert.equal((await adapter.browse(null, write, 'a')).entries.length, 1);
        assert.deepEqual(await adapter.tags(), []);

        const sent = stub.calls.map((call) => `${call.method} ${call.url}`);
        assert.deepEqual(sent, [
            `GET ${base}/sources`,
            `POST ${base}/sources`,
            `PATCH ${base}/sources/s1`,
            `DELETE ${base}/sources/s1`,
            `GET ${base}/source-options`,
            'GET /api/admin/workspace-identities/group/group-1/identities',
            `GET ${base}/sources/s1/runs`,
            `POST ${base}/sources/s1/sync`,
            `POST ${base}/sources/test-connection`,
            `POST ${base}/sources/s1/test-connection`,
            `POST ${base}/sources/browse`,
        ]);

        // The administrator routes take no config revision: a write is unconditional.
        assert.deepEqual(stub.calls[1].body, write);
        assert.deepEqual(stub.calls[2].body, write);
        assert.deepEqual(stub.calls[3].body, { delete_associated_files: true });
        assert.equal(stub.calls[9].body, undefined, 'A saved source is tested from the server copy.');
        assert.deepEqual(stub.calls[10].body, { ...write, browse_path: 'a' });
    } finally {
        stub.restore();
    }
});

check('the administrator adapter names a user or public workspace on its own route family', async () => {
    const stub = stubFetch(() => ({ json: { sources: [] } }));
    try {
        const user = createAdminFileSourceWorkbench({ scope: 'personal', id: 'user-9', label: 'Jane' });
        assert.deepEqual(user.scope, { kind: 'personal' });
        await user.list();
        const pub = createAdminFileSourceWorkbench({ scope: 'public', id: 'a b', label: 'Policies' });
        assert.deepEqual(pub.scope, { kind: 'public', id: 'a b', name: 'Policies' });
        await pub.list();
        assert.deepEqual(stub.calls.map((call) => call.url), [
            '/api/admin/file-sync/personal/user-9/sources',
            '/api/admin/file-sync/public/a%20b/sources',
        ]);
    } finally {
        stub.restore();
    }
    assert.throws(() => createAdminFileSourceWorkbench({ scope: 'group', id: 'a/b', label: 'x' }), /Invalid workspace identifier/);
});

check('a source is re-read from the list, and ignoring a path says it is not available', async () => {
    const stub = stubFetch(() => ({ json: { sources: [SOURCE] } }));
    try {
        const adapter = createAdminFileSourceWorkbench({ scope: 'group', id: 'group-1', label: 'Finance' });
        const found = await adapter.read({ id: 's1' });
        assert.equal(found.name, 'Quarterly share');
        await assert.rejects(adapter.read({ id: 'gone' }), (error: unknown) => error instanceof ApiError && error.status === 404);
        await assert.rejects(adapter.ignorePath('s1', 'a', true), /not available/);
    } finally {
        stub.restore();
    }
});

check('a refused write keeps the server\u2019s reason, and a save race becomes a plain retry', async () => {
    let status = 403;
    const stub = stubFetch(() => status === 403
        ? { status: 403, json: { error: 'You do not have permission to perform this File Sync operation.' } }
        : { status: 409, json: { error: 'This File Sync item changed while it was being saved. Try saving again.', error_code: 'write_conflict' } });
    try {
        const adapter = createAdminFileSourceWorkbench({ scope: 'group', id: 'group-1', label: 'Finance' });
        await assert.rejects(adapter.update(SOURCE, { name: 'x' }), /You do not have permission to perform this File Sync operation\./);
        status = 409;
        await assert.rejects(adapter.update(SOURCE, { name: 'x' }), (error: unknown) => error instanceof FileSourceWriteConflictError);
    } finally {
        stub.restore();
    }
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
