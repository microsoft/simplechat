// test_v2_workflow_activity_logic.mjs
// Version: 0.261.448
// Implemented in: 0.261.448
// Executes the V2 Workflow Activity page's rules: the address it reads and builds, what it makes of a
// snapshot, which activity is selected after a new one lands, when it listens for live updates, how
// a failed read is worded, how the activity stream is read, and where a notification or a Support
// shortcut that names workflow activity leads. The snapshots in WORKFLOW_ACTIVITY_SNAPSHOTS are built
// by the server's own `build_workflow_activity_snapshot` (see test_v2_workflow_activity.py), so the
// page is checked against the shape the server really sends, not one this file describes.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import './test_support/tsResolve.mjs';

globalThis.fetch = () => {
    throw new Error('The workflow activity rules never reach the network.');
};

// The repository resolver must be registered before extensionless TypeScript imports load.
const activity = await import('../application/v2_ui/src/lib/workflowActivity.ts');
const snapshots = await import('../application/v2_ui/src/lib/workflowActivitySnapshot.ts');
const streams = await import('../application/v2_ui/src/lib/workflowActivityStream.ts');
const { normalizeNotification } = await import('../application/v2_ui/src/lib/notifications.ts');
const { resolveNotificationLink } = await import('../application/v2_ui/src/lib/notificationLinks.ts');
const shortcuts = await import('../application/v2_ui/src/lib/latestFeatureShortcuts.ts');

const ORIGIN = 'https://simplechat.test';

function read(search) {
    return activity.readWorkflowActivityQuery(search);
}

function queryOf(search) {
    const result = read(search);
    assert.ok(result.ok, `${search} should be readable`);
    return result.query;
}

function serverSnapshots() {
    const file = process.env.WORKFLOW_ACTIVITY_SNAPSHOTS;
    assert.ok(file, 'WORKFLOW_ACTIVITY_SNAPSHOTS names the file of snapshots the server built.');
    return JSON.parse(readFileSync(file, 'utf8'));
}

function activityRecord(overrides = {}) {
    return {
        id: 'a-1', title: 'Step', summary: 'Did a step', detail: '', status: 'completed', kind: 'thought',
        lane_label: 'Main', lane_index: 0, started_at: '2025-01-01T00:00:00+00:00', duration_ms: null, events: [],
        ...overrides,
    };
}

function normalized(...records) {
    return snapshots.normalizeWorkflowActivitySnapshot({
        workflow: { id: 'wf-1', name: 'Digest' },
        run: { id: 'run-12345678-abcd', status: 'running', trigger_source: 'manual' },
        activities: records,
        live: true,
    });
}

/* ------------------------------------- the address ------------------------------------- */

test('the page reads the five parameters the classic page reads', () => {
    assert.deepEqual(queryOf('?conversationId=c-1&workflowId=w-1&runId=r-1'), {
        conversationId: 'c-1', workflowId: 'w-1', runId: 'r-1', scope: 'personal', groupId: '',
    });
    assert.deepEqual(queryOf('?runId=r-1&scope=group&groupId=g-1'), {
        conversationId: '', workflowId: '', runId: 'r-1', scope: 'group', groupId: 'g-1',
    });
    // A group named for a personal link is not carried; the scope decides.
    assert.equal(queryOf('?runId=r-1&scope=personal&groupId=g-1').groupId, '');
    // Case and padding in the scope are forgiven, as classic forgives them.
    assert.equal(queryOf('?runId=r-1&scope=%20GROUP%20').scope, 'group');
    // Nothing named is a page with nothing to show, not a refused link.
    for (const search of ['', '?', '?scope=group', '?conversationId=&workflowId=', '?other=1']) {
        const query = queryOf(search);
        assert.equal(activity.hasWorkflowActivityIdentifier(query), false, search);
    }
    assert.equal(activity.hasWorkflowActivityIdentifier(queryOf('?workflowId=w-1')), true);
    // Either spelling of the input.
    assert.deepEqual(read(new URLSearchParams('runId=r-1')), read('runId=r-1'));
});

test('a link with an id or a scope the page cannot carry is refused whole', () => {
    const badIds = ['a/b', 'a\\b', 'a?b', 'a#b', '..', '.', ' r-1', 'r-1 ', 'r\u00001', 'r\n1', 'r\u007f1', 'x'.repeat(257)];
    for (const id of badIds) {
        for (const field of ['conversationId', 'workflowId', 'runId', 'groupId']) {
            const search = `?${new URLSearchParams({ runId: 'ok-1', [field]: id })}`;
            assert.deepEqual(read(search), { ok: false, reason: activity.WORKFLOW_ACTIVITY_INVALID_LINK }, `${field}=${JSON.stringify(id)}`);
        }
    }
    for (const scope of ['public', 'groups', 'all', 'personal2']) {
        assert.equal(read(`?runId=r-1&scope=${scope}`).ok, false, scope);
    }
    assert.equal(activity.isWorkflowActivityIdentifier('x'.repeat(256)), true);
    for (const value of [null, undefined, 7, {}, '']) {
        assert.equal(activity.isWorkflowActivityIdentifier(value), false, String(value));
    }
});

test('the page address is written in one order, and only from ids a link can carry', () => {
    assert.equal(activity.buildWorkflowActivityPath({}), '/workflow-activity');
    assert.equal(
        activity.buildWorkflowActivityPath({ runId: 'r-1', workflowId: 'w-1', conversationId: 'c-1' }),
        '/workflow-activity?conversationId=c-1&workflowId=w-1&runId=r-1',
    );
    assert.equal(
        activity.buildWorkflowActivityPath({ runId: 'r-1', scope: 'group', groupId: 'g-1' }),
        '/workflow-activity?runId=r-1&scope=group&groupId=g-1',
    );
    // A group with no id asks for the reader's active group; the personal default is not written.
    assert.equal(activity.buildWorkflowActivityPath({ runId: 'r-1', scope: 'group' }), '/workflow-activity?runId=r-1&scope=group');
    assert.equal(activity.buildWorkflowActivityPath({ runId: 'r-1', scope: 'personal', groupId: 'g-1' }), '/workflow-activity?runId=r-1');
    assert.equal(activity.buildWorkflowActivityPath({ runId: 'a b&c=d' }), '/workflow-activity?runId=a+b%26c%3Dd');
    assert.equal(activity.buildWorkflowActivityPath({}, { requireIdentifier: true }), null);
    assert.equal(activity.buildWorkflowActivityPath({ scope: 'group', groupId: 'g-1' }, { requireIdentifier: true }), null);
    for (const id of ['a/b', ' r', '..', 'r?x']) {
        assert.equal(activity.buildWorkflowActivityPath({ runId: id }), null, id);
        assert.equal(activity.buildWorkflowActivityPath({ runId: 'r-1', scope: 'group', groupId: id }), null, id);
    }
    // What is written reads back as what was meant, with a group only for a group.
    for (const query of [
        { conversationId: 'c-1', workflowId: 'w-1', runId: 'r-1', scope: 'personal', groupId: '' },
        { conversationId: '', workflowId: 'w 1', runId: '', scope: 'group', groupId: 'g/2'.replace('/', '-') },
    ]) {
        const path = activity.buildWorkflowActivityPath(query);
        assert.deepEqual(queryOf(path.slice(path.indexOf('?'))), query);
    }
});

test('the router allowlist accepts the page address only in the builder\'s own form', () => {
    for (const path of [
        '/workflow-activity',
        '/workflow-activity?runId=r-1',
        '/workflow-activity?conversationId=c-1&workflowId=w-1&runId=r-1&scope=group&groupId=g-1',
    ]) {
        assert.equal(activity.isWorkflowActivityRoute(path), true, path);
    }
    for (const path of [
        '/workflow-activity?runId=r-1&scope=personal', // the personal default is never written
        '/workflow-activity?runId=r-1&extra=1',
        '/workflow-activity?runId=r-1&workflowId=w-1', // not the builder's order
        '/workflow-activity?runId=a/b',
        '/workflow-activity?runId=..',
        '/workflow-activity?scope=public',
        '/workflow-activity/?runId=r-1',
        '/workflow-activity#top',
        '/workflow-activityx',
        '//evil.example/workflow-activity',
        'https://evil.example/workflow-activity?runId=r-1',
        '/other?runId=r-1',
        '',
    ]) {
        assert.equal(activity.isWorkflowActivityRoute(path), false, path);
    }
});

test('entry points link only to a run, a workflow or a conversation they can name', () => {
    const group = { type: 'group', groupId: 'grp-1' };
    assert.equal(
        activity.workflowActivityHref({ conversationId: 'c-1', workflowId: 'w-1', runId: 'r-1' }),
        '/workflow-activity?conversationId=c-1&workflowId=w-1&runId=r-1',
    );
    assert.equal(
        activity.workflowActivityHref({ scope: group, conversationId: 'c-1', workflowId: 'w-1', runId: 'r-1' }),
        '/workflow-activity?conversationId=c-1&workflowId=w-1&runId=r-1&scope=group&groupId=grp-1',
    );
    assert.equal(activity.workflowActivityHref({ scope: { type: 'personal' }, runId: ' r-1 ' }), '/workflow-activity?runId=r-1');
    // Nothing to open, an id a link cannot carry, or a group that cannot be named.
    assert.equal(activity.workflowActivityHref({}), null);
    assert.equal(activity.workflowActivityHref({ runId: null, workflowId: undefined, conversationId: 3 }), null);
    assert.equal(activity.workflowActivityHref({ runId: 'a/b' }), null);
    assert.equal(activity.workflowActivityHref({ scope: { type: 'group', groupId: '' }, runId: 'r-1' }), null);
    assert.equal(activity.workflowActivityHref({ scope: { type: 'group', groupId: 'a/b' }, runId: 'r-1' }), null);
    assert.deepEqual(
        activity.workflowActivityScope(queryOf('?runId=r-1&scope=group&groupId=g-1')),
        { type: 'group', groupId: 'g-1' },
    );
    assert.deepEqual(activity.workflowActivityScope(queryOf('?runId=r-1')), { type: 'personal' });
});

test('the run link beside the title names the run in the workspace the page was opened for', () => {
    const open = (search, workflowId = 'w-1', runId = 'r-1') => snapshots.activityRunHref(queryOf(search), workflowId, runId);
    assert.equal(open('?runId=r-1'), '/workspace/workflows?workflow_id=w-1&run_id=r-1');
    assert.equal(open('?runId=r-1&scope=group&groupId=g-1'), '/groups/g-1/workflows?workflow_id=w-1&run_id=r-1');
    // No run or workflow to name, or a group the link did not name, gets no link, never a guessed one.
    assert.equal(open('?runId=r-1', '', 'r-1'), null);
    assert.equal(open('?runId=r-1', 'w-1', ''), null);
    assert.equal(open('?runId=r-1&scope=group'), null);
    // Ids from the server's own snapshot are encoded for the query, never read as structure.
    assert.equal(open('?runId=r-1', 'w/1'), '/workspace/workflows?workflow_id=w%2F1&run_id=r-1');
});

test('the chat header offers activity for a workflow conversation, as classic does', () => {
    const open = (sources, flags = {}) => activity.workflowConversationActivityHref({
        conversationId: 'c-1', sources, personalWorkflowsEnabled: true, groupWorkspacesEnabled: false, ...flags,
    });
    assert.equal(open([{ chat_type: 'workflow', workflow_id: 'w-1' }]), '/workflow-activity?conversationId=c-1&workflowId=w-1');
    // Either marker is enough, from either source, and the run's provenance names the workflow.
    assert.equal(open([null, { chat_type: 'workflow' }]), '/workflow-activity?conversationId=c-1');
    assert.equal(open([{ workflow_id: 'w-2' }, undefined]), '/workflow-activity?conversationId=c-1&workflowId=w-2');
    assert.equal(
        open([{ workflow_provenance: { workflow_id: 'w-3', run_id: 'r-3' } }]),
        '/workflow-activity?conversationId=c-1&workflowId=w-3',
    );
    // An ordinary conversation, no conversation, nothing loaded, and workflows off for the reader get none.
    assert.equal(open([{ chat_type: 'personal_single_user' }, {}]), null);
    assert.equal(open([null, undefined]), null);
    assert.equal(open([{ chat_type: 'workflow' }], { personalWorkflowsEnabled: false }), null);
    assert.equal(activity.workflowConversationActivityHref({
        conversationId: null, sources: [{ chat_type: 'workflow' }], personalWorkflowsEnabled: true, groupWorkspacesEnabled: true,
    }), null);
    // A conversation a group workflow made opens the group's page, where classic asks for the personal one.
    const groupRow = { chat_type: 'workflow', workflow_id: 'w-9', workspace_type: 'group', group_id: 'grp-1' };
    assert.equal(
        open([{ chat_type: 'workflow' }, groupRow], { groupWorkspacesEnabled: true }),
        '/workflow-activity?conversationId=c-1&workflowId=w-9&scope=group&groupId=grp-1',
    );
    assert.equal(open([groupRow], { groupWorkspacesEnabled: false }), null);
    assert.equal(open([{ ...groupRow, group_id: 'a/b' }], { groupWorkspacesEnabled: true }), null);
});

test('the endpoints are the ones the server serves, with the query it reads', () => {
    assert.equal(activity.workflowActivityApiPath('personal'), '/api/user/workflows/activity');
    assert.equal(activity.workflowActivityApiPath('group', true), '/api/group/workflows/activity/stream');
    assert.equal(
        activity.workflowActivityApiUrl(queryOf('?conversationId=c-1&workflowId=w-1&runId=r-1')),
        '/api/user/workflows/activity?conversation_id=c-1&workflow_id=w-1&run_id=r-1',
    );
    assert.equal(
        activity.workflowActivityApiUrl(queryOf('?runId=r%2B1&scope=group&groupId=g-1'), true),
        '/api/group/workflows/activity/stream?run_id=r%2B1&group_id=g-1',
    );
    // A group left out is the server's to resolve; a personal read never names one.
    assert.equal(activity.workflowActivityApiUrl(queryOf('?runId=r-1&scope=group')), '/api/group/workflows/activity?run_id=r-1');
    assert.equal(activity.workflowActivityApiUrl(queryOf('?runId=r-1&groupId=g-1')), '/api/user/workflows/activity?run_id=r-1');
});

test('the live states are the ones the server and the classic page follow', () => {
    const server = readFileSync(new URL('../application/single_app/functions_m365_workflow_binding.py', import.meta.url), 'utf8');
    const waiting = [...server.match(/M365_WAITING_STATES = frozenset\(\{([^}]*)\}\)/)[1].matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
    const expected = new Set(['running', 'cancelling', ...waiting, 'ready_to_resume', 'resuming']);
    assert.deepEqual(new Set(activity.WORKFLOW_ACTIVITY_ACTIVE_STATUSES), expected);

    const classic = readFileSync(new URL('../application/single_app/static/js/workflow/workflow-activity.js', import.meta.url), 'utf8');
    const classicSet = new Set([...classic.match(/WORKFLOW_ACTIVE_STATUSES = new Set\(\[([^\]]*)\]\)/)[1].matchAll(/"([a-z_]+)"/g)].map((match) => match[1]));
    assert.deepEqual(classicSet, expected);

    for (const status of expected) {
        assert.equal(activity.isWorkflowActivityActive(status), true, status);
        assert.equal(activity.isWorkflowActivityActive(` ${status.toUpperCase()} `), true, status);
    }
    for (const status of ['completed', 'failed', 'cancelled', 'queued', 'idle', '', null, undefined]) {
        assert.equal(activity.isWorkflowActivityActive(status), false, String(status));
    }
});

test('a failed read says what the server said, and the status when it said nothing', () => {
    const failure = (status, message, payload) => Object.assign(new Error(message), { status, payload });
    // Personal workflows refused for the missing role: the sentence is under `message`.
    assert.equal(
        activity.describeWorkflowActivityFailure(failure(403, 'Forbidden', { error: 'Forbidden', message: 'Personal workflows require the WorkflowUser app role.' })),
        'Personal workflows require the WorkflowUser app role.',
    );
    assert.equal(activity.describeWorkflowActivityFailure(failure(403, 'This group is not assigned to use workflows.', { error: 'This group is not assigned to use workflows.' })), 'This group is not assigned to use workflows.');
    assert.equal(activity.describeWorkflowActivityFailure(failure(400, 'Workflow run not found.', {})), 'Workflow run not found.');
    assert.equal(activity.describeWorkflowActivityFailure(failure(404, 'Request failed with status 404', '')), 'This workflow activity was not found.');
    assert.equal(activity.describeWorkflowActivityFailure(failure(403, 'Request failed with status 403', {})), 'You do not have access to this workflow activity.');
    assert.equal(activity.describeWorkflowActivityFailure(failure(500, 'Unable to load workflow activity right now.', {})), 'Unable to load workflow activity right now.');
    assert.equal(activity.describeWorkflowActivityFailure(failure(502, 'Request failed with status 502', '')), activity.WORKFLOW_ACTIVITY_SERVER_ERROR);
    // A call that never got an answer is the browser's wording, which is not shown.
    assert.equal(activity.describeWorkflowActivityFailure(new TypeError('Failed to fetch')), activity.WORKFLOW_ACTIVITY_OFFLINE_ERROR);
    assert.equal(activity.describeWorkflowActivityFailure(new TypeError('Failed to fetch'), 'Unable to cancel the workflow run.'), 'Unable to cancel the workflow run.');
    assert.equal(activity.describeWorkflowActivityFailure(failure(500, 'Request failed with status 500', {}), 'Unable to cancel the workflow run.'), 'Unable to cancel the workflow run.');
    // A body that was not JSON -- a gateway's error page, a bare `{}` served as text -- is the API
    // client's text, not the server's sentence, and is never shown.
    assert.equal(activity.describeWorkflowActivityFailure(failure(502, '<html><h1>Bad gateway</h1></html>', '<html><h1>Bad gateway</h1></html>')), activity.WORKFLOW_ACTIVITY_SERVER_ERROR);
    assert.equal(activity.describeWorkflowActivityFailure(failure(404, '{}', '{}')), 'This workflow activity was not found.');
    assert.equal(activity.describeWorkflowActivityFailure(failure(403, 'Denied by policy', 'Denied by policy')), 'You do not have access to this workflow activity.');
    assert.equal(activity.describeWorkflowActivityFailure(failure(500, 'Proxy error', 'Proxy error'), 'Unable to cancel the workflow run.'), 'Unable to cancel the workflow run.');
    for (const junk of [null, undefined, 'x', 7, {}]) {
        assert.equal(typeof activity.describeWorkflowActivityFailure(junk), 'string');
    }
});

/* ------------------------------------- the snapshot ------------------------------------- */

test('a snapshot is read defensively, and only ever as text', () => {
    for (const junk of [null, undefined, 'x', 7, [], {}, { activities: 'no', run: 3, workflow: [], conversation: 'c', live: 'yes' }]) {
        const snapshot = snapshots.normalizeWorkflowActivitySnapshot(junk);
        assert.equal(snapshot.run, null);
        assert.deepEqual([...snapshot.activities], []);
        assert.equal(snapshot.live, false);
        assert.equal(snapshots.activityTitle(snapshot), 'Workflow activity');
    }
    const snapshot = snapshots.normalizeWorkflowActivitySnapshot({
        workflow: { id: ' wf-1 ', name: '<img src=x onerror=alert(1)>' },
        conversation: { id: 'c-1', title: 'Chat' },
        run: { id: 7, status: ' RUNNING ', task_results: [null, 'x', { task_name: 'Draft', workflow_result: { task_completeness: { version: 2, status: 'complete' } } }] },
        activities: [
            null, 'x', 3,
            { id: '', title: ' T ', status: ' Failed ', lane_index: '2', duration_ms: '450', events: [null, { content: 'c', detail: 5, timestamp: 't' }, 'x'] },
            { id: 'b', lane_index: -4, duration_ms: -1, pending_action: { type: 'other', id: 'x' } },
            { id: 'c', lane_index: 99, duration_ms: 'x', pending_action: { type: 'msgraph_pending_action', id: 'act-1', status: 'pending' } },
            { id: 'd', pending_action: { type: 'msgraph_pending_action', id: '..' } },
        ],
        live: true,
    });
    assert.equal(snapshot.workflowId, 'wf-1');
    assert.equal(snapshot.workflowName, '<img src=x onerror=alert(1)>');
    assert.equal(snapshot.run.id, '7');
    assert.equal(snapshot.run.status, 'running');
    assert.equal(snapshot.run.tasks.length, 1);
    const [first, second, third, fourth] = snapshot.activities;
    assert.equal(snapshot.activities.length, 4);
    assert.deepEqual([first.id, first.title, first.status, first.laneIndex, first.durationMs], ['activity-3', 'T', 'failed', 2, 450]);
    assert.deepEqual([...first.events], [{ content: 'c', detail: '5', timestamp: 't' }]);
    assert.deepEqual([second.laneIndex, second.durationMs, second.pendingAction], [0, null, null]);
    assert.equal(third.laneIndex, 8, 'a lane is never drawn deeper than eight');
    assert.equal(third.pendingAction.id, 'act-1');
    assert.equal(fourth.pendingAction, null, 'an action id a path cannot carry is not a card');
});

test('what the server builds is what the page reads', () => {
    const built = serverSnapshots();

    const finished = snapshots.normalizeWorkflowActivitySnapshot(built.finished);
    assert.equal(finished.workflowName, 'Security Events');
    assert.equal(finished.live, false);
    assert.equal(finished.activities.length, 2);
    const stats = snapshots.activityStats(finished);
    assert.deepEqual([stats.run, stats.activities, stats.toolCalls], ['run-123'.slice(0, 8), 2, 1]);
    assert.equal(snapshots.activityCaption(finished), 'manual run completed.');
    const tool = finished.activities.find((item) => item.kind === 'tool_invocation');
    assert.deepEqual([tool.status, tool.laneIndex, tool.durationMs, tool.events.length], ['completed', 1, 450, 2]);
    assert.equal(snapshots.activityConversationId(finished), 'conversation-xyz');
    assert.equal(snapshots.activityCancel(finished, queryOf('?runId=run-123')).visible, false);
    assert.deepEqual(snapshots.activityResponse(finished.run), { heading: 'Response Preview', text: 'Security events workflow completed.' });

    const running = snapshots.normalizeWorkflowActivitySnapshot(built.running);
    assert.equal(running.live, true);
    assert.equal(snapshots.activityCaption(running), 'manual run running using Security Agent.');
    const cancel = snapshots.activityCancel(running, queryOf('?runId=running-run-1'));
    assert.deepEqual([cancel.visible, cancel.disabled, cancel.label, cancel.workflowId, cancel.runId], [true, false, 'Cancel run', 'workflow-abc', 'running-run-1']);
    assert.equal(snapshots.shouldListenForUpdates(queryOf('?runId=running-run-1'), running, true), true);

    const withAction = snapshots.normalizeWorkflowActivitySnapshot(built.withAction);
    const card = withAction.activities.find((item) => item.pendingAction);
    assert.equal(card.kind, 'msgraph_pending_action');
    assert.equal(card.title, 'Calendar invite delayed send');
    assert.equal(card.laneLabel, 'Microsoft Graph');
    assert.equal(card.laneIndex, 1);
    assert.equal(card.pendingAction.id, 'pending-calendar-1');
    assert.equal(card.pendingAction.can_send_now, true);
    assert.equal(withAction.live, true);

    const legacy = snapshots.normalizeWorkflowActivitySnapshot(built.legacy);
    assert.equal(legacy.activities.length, 1);
    assert.deepEqual([legacy.activities[0].status, legacy.activities[0].summary], ['failed', 'Workflow run summary']);
    assert.deepEqual(snapshots.activityResponse(legacy.run), { heading: 'Run Error', text: 'Workflow agent timed out.' });
    assert.equal(snapshots.activityStatusView(legacy.run.status).tone, 'danger');

    const empty = snapshots.normalizeWorkflowActivitySnapshot(built.conversationOnly);
    assert.equal(empty.run, null);
    assert.equal(snapshots.activityCaption(empty), 'Waiting for a captured workflow run.');
    assert.equal(snapshots.activityStats(empty).run, 'Pending');
    assert.equal(snapshots.activityTitle(empty), 'Workflow: Security Events');
});

test('the header says what the classic page says', () => {
    const caption = (run) => snapshots.activityCaption(snapshots.normalizeWorkflowActivitySnapshot({ run }));
    assert.equal(caption({ trigger_source: 'schedule', status: 'completed', agent_display_name: 'Digest agent' }), 'schedule run completed using Digest agent.');
    assert.equal(caption({ status: 'failed', agent_name: 'agent-x' }), 'manual run failed using agent-x.');
    assert.equal(caption({ status: 'cancelled', model_deployment_name: 'gpt-4o' }), 'manual run cancelled using gpt-4o.');
    assert.equal(caption({ status: 'awaiting_sign_in' }), 'manual run awaiting sign in.');
    assert.equal(caption({}), 'manual run captured.');
    assert.equal(snapshots.activityStats(snapshots.normalizeWorkflowActivitySnapshot({ run: {} })).run, 'Captured');
    // The four figures: the run's short id, every activity, tool invocations only, and the start.
    const snapshot = normalized(
        activityRecord({ id: 'a', kind: 'workflow_run' }),
        activityRecord({ id: 'b', kind: 'tool_invocation' }),
        activityRecord({ id: 'c', kind: 'tool_invocation' }),
        activityRecord({ id: 'd', kind: 'tabular_tool_invocation' }),
    );
    const stats = snapshots.activityStats(snapshot);
    assert.deepEqual([stats.run, stats.activities, stats.toolCalls], ['run-1234', 4, 2]);
    assert.equal(snapshots.activityTitle({ ...snapshot, workflowName: '', conversationTitle: 'Chat' }), 'Chat');
});

test('times and durations read as the classic page prints them', () => {
    assert.equal(snapshots.formatActivityDuration(null), '');
    assert.equal(snapshots.formatActivityDuration(0), '');
    assert.equal(snapshots.formatActivityDuration(-5), '');
    assert.equal(snapshots.formatActivityDuration('x'), '');
    assert.equal(snapshots.formatActivityDuration(450), '450 ms');
    assert.equal(snapshots.formatActivityDuration(999.6), '1000 ms');
    assert.equal(snapshots.formatActivityDuration(3200), '3.2 s');
    assert.equal(snapshots.formatActivityDuration(42000), '42 s');
    assert.equal(snapshots.formatActivityDuration(125000), '2m 5s');
    assert.equal(snapshots.formatActivityDateTime(''), '--');
    assert.equal(snapshots.formatActivityDateTime(null), '--');
    assert.equal(snapshots.formatActivityDateTime('not a date'), 'not a date');
    const formatted = snapshots.formatActivityDateTime('2025-01-05T09:05:00Z', 'en-US', 'UTC');
    assert.match(formatted, /Jan 5, 2025/);
    assert.match(formatted, /9:05\sAM/);
    assert.equal(snapshots.formatActivityDateTime('2025-01-05T09:05:00Z', 'not-a-locale-$$', 'Nowhere/Land'), '2025-01-05T09:05:00Z');
});

test('a status is drawn in words, a glyph and a tone', () => {
    const view = (status) => snapshots.activityStatusView(status);
    assert.deepEqual(view('running'), { label: 'Running', tone: 'accent', glyph: 'running' });
    assert.deepEqual(view('cancelling'), { label: 'Cancelling', tone: 'warn', glyph: 'waiting' });
    assert.deepEqual(view('awaiting_sign_in'), { label: 'Awaiting sign in', tone: 'warn', glyph: 'waiting' });
    assert.deepEqual(view('ready_to_resume'), { label: 'Ready to resume', tone: 'warn', glyph: 'waiting' });
    assert.deepEqual(view('completed'), { label: 'Completed', tone: 'ok', glyph: 'done' });
    assert.deepEqual(view('failed'), { label: 'Failed', tone: 'danger', glyph: 'failed' });
    assert.deepEqual(view('cancelled'), { label: 'Cancelled', tone: 'neutral', glyph: 'cancelled' });
    assert.deepEqual(view('canceled'), { label: 'Cancelled', tone: 'neutral', glyph: 'cancelled' });
    assert.deepEqual(view('completed_partial'), { label: 'Completed with task errors', tone: 'warn', glyph: 'failed' });
    assert.deepEqual(view(''), { label: 'Idle', tone: 'neutral', glyph: 'idle' });
    assert.deepEqual(view('idle'), { label: 'Idle', tone: 'neutral', glyph: 'idle' });
    assert.equal(view('queued').tone, 'neutral');
});

test('Cancel run is offered for a live run, and says so while it is being cancelled', () => {
    const query = queryOf('?workflowId=w-q&runId=r-q');
    const cancel = (run, workflow = { id: 'wf-1' }) => snapshots.activityCancel(
        snapshots.normalizeWorkflowActivitySnapshot({ workflow, run }), query);
    assert.deepEqual(cancel({ id: 'r-1', status: 'running' }), { visible: true, disabled: false, label: 'Cancel run', workflowId: 'wf-1', runId: 'r-1' });
    assert.deepEqual(cancel({ id: 'r-1', status: 'cancelling' }), { visible: true, disabled: true, label: 'Cancelling', workflowId: 'wf-1', runId: 'r-1' });
    assert.equal(cancel({ id: 'r-1', status: 'awaiting_approval' }).visible, true);
    for (const status of ['completed', 'failed', 'cancelled', '']) {
        assert.equal(cancel({ id: 'r-1', status }).visible, false, status);
    }
    // The page's own ids stand in for ones the snapshot lacks, and with neither there is nothing to cancel.
    assert.deepEqual(cancel({ status: 'running' }, {}), { visible: true, disabled: false, label: 'Cancel run', workflowId: 'w-q', runId: 'r-q' });
    const unnamed = snapshots.activityCancel(snapshots.normalizeWorkflowActivitySnapshot({ run: { status: 'running' } }), queryOf(''));
    assert.equal(unnamed.visible, false);
    assert.equal(snapshots.activityCancel(snapshots.EMPTY_WORKFLOW_ACTIVITY_SNAPSHOT, query).visible, false);
});

test('the response panel shows the run error, else the preview, and the checks tasks saved', () => {
    const run = (extra) => snapshots.normalizeWorkflowActivitySnapshot({ run: { id: 'r', ...extra } }).run;
    assert.equal(snapshots.activityResponse(null), null);
    assert.equal(snapshots.activityResponse(run({})), null);
    assert.deepEqual(snapshots.activityResponse(run({ response_preview: ' Done. ' })), { heading: 'Response Preview', text: 'Done.' });
    assert.deepEqual(snapshots.activityResponse(run({ response_preview: 'Done.', error: 'Boom' })), { heading: 'Run Error', text: 'Boom' });
    assert.equal(snapshots.responseToggleLabel(false, 'Response Preview'), 'Show response preview');
    assert.equal(snapshots.responseToggleLabel(true, 'Response Preview'), 'Hide response preview');
    assert.equal(snapshots.responseToggleLabel(false, 'Run Error'), 'Show run error');
    assert.equal(snapshots.responseToggleLabel(true, ''), 'Hide response preview');

    const checks = snapshots.activityChecks(run({
        task_results: [
            { task_name: 'Draft', workflow_result: { task_completeness: { version: 2, status: 'complete', corrections: 1 } } },
            { task_name: '', workflow_result: { task_completeness: { version: 1, status: 'incomplete' } } },
            { task_name: 'No report', workflow_result: {} },
            { task_name: 'Odd status', workflow_result: { task_completeness: { version: 2, status: 'unheard_of' } } },
            { task_name: 'Old version', workflow_result: { task_completeness: { version: 9, status: 'complete' } } },
            { task_name: 'Not a record', workflow_result: { task_completeness: 'complete' } },
        ],
    }));
    assert.deepEqual(checks.map((check) => check.name), ['Draft', 'Task']);
    assert.equal(snapshots.activityChecks(null).length, 0);

    // Every status the check list draws is one the details component has words for.
    const component = readFileSync(new URL('../application/v2_ui/src/components/ui/TaskCompletenessDetails.tsx', import.meta.url), 'utf8');
    const labelled = [...component.match(/const labels: Record<string, string> = \{([^}]*)\}/)[1].matchAll(/^\s+([a-z_]+):/gm)].map((match) => match[1]);
    for (const status of labelled) {
        assert.equal(snapshots.activityChecks(run({ task_results: [{ task_name: 'T', workflow_result: { task_completeness: { version: 2, status } } }] })).length, 1, status);
    }
});

/* ---------------------------- selection and following ---------------------------- */

test('selection follows the newest activity until the reader picks another', () => {
    const records = (...ids) => normalized(...ids.map((id, index) => activityRecord({ id, status: index === ids.length - 1 ? 'running' : 'completed' }))).activities;
    const initial = snapshots.INITIAL_ACTIVITY_SELECTION;
    assert.deepEqual(initial, { selectedId: '', followLatest: true });

    // Nothing to select leaves the selection alone.
    assert.equal(snapshots.resolveActivitySelection(initial, []), initial);
    // Following, the newest is selected, and a newer one takes over.
    const one = snapshots.resolveActivitySelection(initial, records('a'));
    assert.deepEqual(one, { selectedId: 'a', followLatest: true });
    assert.equal(snapshots.resolveActivitySelection(one, records('a')), one);
    assert.deepEqual(snapshots.resolveActivitySelection(one, records('a', 'b')), { selectedId: 'b', followLatest: true });

    // Picking an older one stops the following; picking the newest resumes it.
    const picked = snapshots.pickActivity(records('a', 'b', 'c'), 'a');
    assert.deepEqual(picked, { selectedId: 'a', followLatest: false });
    assert.equal(snapshots.resolveActivitySelection(picked, records('a', 'b', 'c', 'd')), picked);
    assert.deepEqual(snapshots.pickActivity(records('a', 'b', 'c'), 'c'), { selectedId: 'c', followLatest: true });
    assert.deepEqual(snapshots.pickActivity([], 'x'), { selectedId: 'x', followLatest: false });

    // A pick that has gone is replaced by the running activity, else the newest, without following again.
    const gone = { selectedId: 'gone', followLatest: false };
    assert.deepEqual(snapshots.resolveActivitySelection(gone, records('a', 'b')), { selectedId: 'b', followLatest: false });
    const withRunning = normalized(
        activityRecord({ id: 'a', status: 'running' }), activityRecord({ id: 'b', status: 'completed' }),
    ).activities;
    assert.deepEqual(snapshots.resolveActivitySelection(gone, withRunning), { selectedId: 'a', followLatest: false });
    const done = normalized(activityRecord({ id: 'a', status: 'completed' }), activityRecord({ id: 'b', status: 'failed' })).activities;
    assert.deepEqual(snapshots.resolveActivitySelection(gone, done), { selectedId: 'b', followLatest: false });

    assert.equal(snapshots.selectedActivity({ selectedId: 'b', followLatest: false }, done).id, 'b');
    assert.equal(snapshots.selectedActivity({ selectedId: 'zzz', followLatest: false }, done), null);
    assert.equal(snapshots.selectedActivity(initial, []), null);
});

test('the timeline follows the bottom only while the reader is within a few pixels of it', () => {
    const near = (scrollTop) => snapshots.isScrolledNearBottom({ scrollHeight: 1000, clientHeight: 400, scrollTop });
    assert.equal(snapshots.TIMELINE_BOTTOM_THRESHOLD_PX, 24);
    assert.equal(near(600), true);
    assert.equal(near(576), true);
    assert.equal(near(575), false);
    assert.equal(near(0), false);
    assert.equal(snapshots.isScrolledNearBottom({ scrollHeight: 300, clientHeight: 400, scrollTop: 0 }), true);
    assert.equal(snapshots.isScrolledNearBottom({ scrollHeight: 1000, clientHeight: 400, scrollTop: 500 }, 100), true);
});

test('the page listens for updates while a run is live or yet to begin, and not once it has settled', () => {
    const query = queryOf('?runId=r-1');
    const snapshot = (run, live = false) => snapshots.normalizeWorkflowActivitySnapshot({ run, live });
    assert.equal(snapshots.shouldListenForUpdates(query, null, true), false, 'nothing is read yet');
    assert.equal(snapshots.shouldListenForUpdates(query, snapshot(null), true), true, 'a run may be about to begin');
    assert.equal(snapshots.shouldListenForUpdates(query, snapshot({ status: 'running' }), true), true);
    assert.equal(snapshots.shouldListenForUpdates(query, snapshot({ status: 'awaiting_sign_in' }), true), true);
    assert.equal(snapshots.shouldListenForUpdates(query, snapshot({ status: 'completed' }, true), true), true, 'a pending action keeps it live');
    assert.equal(snapshots.shouldListenForUpdates(query, snapshot({ status: 'completed' }), true), false);
    assert.equal(snapshots.shouldListenForUpdates(query, snapshot({ status: 'failed' }), true), false);
    assert.equal(snapshots.shouldListenForUpdates(query, snapshot({ status: 'running' }), false), false, 'no EventSource');
    assert.equal(snapshots.shouldListenForUpdates(queryOf(''), snapshot({ status: 'running' }), true), false, 'nothing named');
});

test('a card that learned something newer asks for the snapshot again, and one that did not does not', () => {
    const action = (extra = {}) => ({ type: 'msgraph_pending_action', id: 'act-1', version: 'v1', status: 'pending', updated_at: '2025-01-01T00:00:00Z', ...extra });
    assert.equal(snapshots.pendingActionMoved(action(), action()), false);
    assert.equal(snapshots.pendingActionMoved(action(), action({ version: 'v2' })), true);
    assert.equal(snapshots.pendingActionMoved(action(), action({ status: 'sent' })), true);
    assert.equal(snapshots.pendingActionMoved(action(), action({ updated_at: '2025-01-01T00:00:05Z' })), true);
    assert.equal(snapshots.pendingActionMoved(action(), action({ id: 'act-2' })), true);
    assert.equal(snapshots.pendingActionMoved(undefined, action()), true);
    assert.equal(snapshots.pendingActionMoved(null, action()), true);
});

/* ------------------------------------ the stream ------------------------------------ */

class FakeEventSource {
    static instances = [];

    constructor(url, init) {
        this.url = url;
        this.init = init;
        this.closed = false;
        this.listeners = new Map();
        this.onmessage = null;
        FakeEventSource.instances.push(this);
    }

    addEventListener(type, listener) {
        this.listeners.set(type, listener);
    }

    close() {
        this.closed = true;
    }

    emit(type, event) {
        if (type === 'message') {
            this.onmessage?.(event);
        } else {
            this.listeners.get(type)?.(event);
        }
    }
}

test('the stream delivers whole snapshots, skips a bad frame, and ends on the server\'s own refusal', () => {
    const previous = globalThis.EventSource;
    globalThis.EventSource = FakeEventSource;
    try {
        const seen = [];
        const unavailable = [];
        const detach = streams.subscribeToWorkflowActivity(queryOf('?conversationId=c-1&scope=group&groupId=g-1'), {
            onSnapshot: (snapshot) => seen.push(snapshot),
            onUnavailable: (message) => unavailable.push(message),
        });
        const source = FakeEventSource.instances.at(-1);
        assert.equal(source.url, '/api/group/workflows/activity/stream?conversation_id=c-1&group_id=g-1');
        assert.equal(source.init.withCredentials, false, 'same-origin sends the cookie without it');

        source.emit('message', { data: JSON.stringify({ live: true, activities: [] }) });
        source.emit('message', { data: '{not json' });
        source.emit('message', { data: '' });
        source.emit('message', null);
        assert.deepEqual(seen, [{ live: true, activities: [] }]);

        // The connection's own failures carry no data and are left to reconnect.
        source.emit('error', new Event('error'));
        assert.deepEqual(unavailable, []);
        assert.equal(source.closed, false);

        // The server's refusal is a named event with a JSON body: the page is told, and the stream ends.
        source.emit('error', new MessageEvent('error', { data: '{"error":"Workflow activity is no longer available.","code":"activity_unavailable"}' }));
        assert.deepEqual(unavailable, ['Workflow activity is no longer available.']);
        assert.equal(source.closed, true);

        const other = streams.subscribeToWorkflowActivity(queryOf('?runId=r-1'), { onSnapshot() {}, onUnavailable: (message) => unavailable.push(message) });
        const second = FakeEventSource.instances.at(-1);
        assert.equal(second.url, '/api/user/workflows/activity/stream?run_id=r-1');
        second.emit('error', new MessageEvent('error', { data: 'not json' }));
        assert.equal(unavailable.at(-1), streams.WORKFLOW_ACTIVITY_UNAVAILABLE);
        other();
        assert.equal(second.closed, true);

        detach();
        assert.equal(source.closed, true);

        // The page can leave without a stream it never opened.
        delete globalThis.EventSource;
        assert.equal(typeof streams.subscribeToWorkflowActivity(queryOf('?runId=r-1'), { onSnapshot() {}, onUnavailable() {} }), 'function');
    } finally {
        if (previous === undefined) {
            delete globalThis.EventSource;
        } else {
            globalThis.EventSource = previous;
        }
    }
});

/* ---------------------------- the links that lead to the page ---------------------------- */

function notice(overrides = {}) {
    const result = normalizeNotification({
        id: 'n-1', notification_type: 'system_announcement', title: 'Title', message: 'Message',
        created_at: '2025-01-01T00:00:00Z', is_read: false, link_url: '', link_context: {}, metadata: {}, type_config: {},
        ...overrides,
    });
    assert.ok(result, 'The fixture is not a notice the panel keeps.');
    return result;
}

function resolve(link, overrides = {}) {
    return resolveNotificationLink(notice({ link_url: link, ...overrides }), ORIGIN);
}

test('a classic workflow-activity link opens the V2 page with the query it carries', () => {
    const route = (path) => ({ target: { kind: 'route', path }, error: null });
    for (const link of [
        '/workflow-activity?workflowId=wf-1&runId=run-1&scope=personal',
        '/workflow-activity?workflowId=wf-1&runId=run-1',
        '/workflow-activity?conversationId=conv-1',
        '/workflow-activity?runId=run-1&scope=group&groupId=grp-1',
        '/workflow-activity?workflowId=wf%201%26x&runId=run%3D1&scope=personal',
        '/workflow-activity?runId=run-1&scope=Group',
        '/workflow-activity?runId=run-1&extra=kept',
        '/workflow-activity',
    ]) {
        assert.deepEqual(resolve(link), route(link), link);
    }
    // The trailing slash and the fragment, which the page does not read, are not carried.
    assert.deepEqual(resolve('/workflow-activity/?runId=run-1#top'), route('/workflow-activity?runId=run-1'));
    // Whatever the notice says about itself, the link decides, a Microsoft 365 notice included.
    const m365 = { metadata: { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'personal', m365_pending_action_id: 'act-1' } };
    assert.deepEqual(resolve('/workflow-activity?workflowId=wf-1&runId=run-1&scope=personal', m365), route('/workflow-activity?workflowId=wf-1&runId=run-1&scope=personal'));
    assert.deepEqual(
        resolve('/workflow-activity?workflowId=wf-1&runId=run-1&scope=group&groupId=grp-3', { link_context: { m365_pending_action_id: 'act-1', group_id: 'grp-3' } }),
        route('/workflow-activity?workflowId=wf-1&runId=run-1&scope=group&groupId=grp-3'),
    );
    assert.deepEqual(
        resolve('/workflow-activity?workflowId=wf-1&runId=run-1', { metadata: { workflow_id: 'wf-2', run_id: 'run-9' } }),
        route('/workflow-activity?workflowId=wf-1&runId=run-1'),
    );
    // The absolute address of this site is the same link.
    assert.deepEqual(resolve(`${ORIGIN}/workflow-activity?runId=run-1`), route('/workflow-activity?runId=run-1'));
});

test('a workflow-activity link with an id or scope the page cannot read is reported, not opened', () => {
    const invalid = 'This notification has an invalid link. Open the destination directly.';
    for (const query of [
        'runId=a%2Fb', 'workflowId=a%5Cb', 'runId=a%3Fb', 'runId=a%23b', 'runId=..', 'runId=%2E', 'runId=%20run-1',
        'runId=run-1%20', 'conversationId=a%00b', 'runId=a%0Ab', 'runId=a%7Fb', `runId=${'x'.repeat(257)}`,
        'runId=run-1&scope=public', 'runId=run-1&scope=all', 'runId=run-1&scope=group&groupId=g%2F1',
    ]) {
        assert.deepEqual(resolve(`/workflow-activity?${query}`), { target: null, error: invalid }, query);
    }
    // Off-site and non-page links stay refused before the path is read.
    for (const link of [
        'https://evil.example/workflow-activity?runId=run-1', '//evil.example/workflow-activity?runId=run-1',
        '/.//evil.example/workflow-activity', '/api/user/workflows/activity?run_id=run-1',
    ]) {
        const resolved = resolve(link);
        assert.equal(resolved.target, null, link);
        assert.ok(resolved.error, link);
    }
});

test('a notice that names a run but carries no link still opens the run in Workflows, and Microsoft 365 notices stay unlinked', () => {
    const personal = { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'personal' };
    const run = '/workspace/workflows?workflow_id=wf-1&run_id=run-1';
    assert.deepEqual(resolve('', { notification_type: 'workflow_chat_delivery', metadata: personal }), { target: { kind: 'route', path: run }, error: null });
    assert.deepEqual(resolve('', { notification_type: 'workflow_chat_delivery', metadata: { ...personal, m365_pending_action_id: 'act-1' } }), { target: null, error: null });
});

test('a Support shortcut to workflow activity opens the V2 page, rebuilt from ids the page can read', () => {
    const target = (href) => shortcuts.resolveLatestFeatureShortcut(href);
    // The catalogue's own shortcut names no run.
    assert.deepEqual(target('/workflow-activity'), { kind: 'route', path: '/workflow-activity' });
    assert.deepEqual(target('/workflow-activity/'), { kind: 'route', path: '/workflow-activity' });
    assert.deepEqual(
        target('/workflow-activity?runId=r-1&workflowId=w-1&scope=personal&feature_action=x#top'),
        { kind: 'route', path: '/workflow-activity?workflowId=w-1&runId=r-1' },
    );
    assert.deepEqual(
        target('/workflow-activity?conversationId=c-1&scope=group&groupId=g-1'),
        { kind: 'route', path: '/workflow-activity?conversationId=c-1&scope=group&groupId=g-1' },
    );
    // Ids the page could not read leave the page to open as written, which any page V2 cannot vouch for does.
    for (const href of ['/workflow-activity?runId=a%2Fb', '/workflow-activity?runId=r-1&scope=public']) {
        assert.deepEqual(target(href), { kind: 'page', href }, href);
    }
    // The router is only ever given an allowlisted path, or the workflow-activity address in its one form.
    for (const path of ['/workflow-activity', '/workflow-activity?runId=r-1', '/workflow-activity?conversationId=c-1&scope=group&groupId=g-1']) {
        assert.equal(shortcuts.safeShortcutRouteHref(path), path, path);
    }
    for (const path of ['/workflow-activity?runId=a%2Fb', '/workflow-activity?runId=r-1&x=1', '/workflow-activity?runId=r-1&scope=personal']) {
        assert.notEqual(shortcuts.safeShortcutRouteHref(path), path, path);
    }
});
