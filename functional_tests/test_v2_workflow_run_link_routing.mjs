// test_v2_workflow_run_link_routing.mjs
// Version: 0.261.445
// Implemented in: 0.261.251
// Workflow activity opens in V2 as of: 0.261.445
// Executes where V2 opens a workflow run from a link: the run deep link (workflowRunHref and
// v2WorkflowRunPath) in personal and group workspaces, the bell's reading of 6b-1's notices about a
// chat-started run, and the workflow alert card's Open run. A classic `/workflow-activity` link opens
// the V2 workflow-activity page with the query it carries, whatever the notice says about itself,
// a Microsoft 365 notice included, and one whose ids or scope the page cannot read is reported rather
// than opened. A notice that carries no link opens its run in the Workflows section only when its own
// metadata names the workspace, the workflow and the run; a Microsoft 365 notice, a notice that names
// its workspace only through `group_id`, an unknown workspace and an id a path can't carry get no link,
// never a guessed V2 address. The notice shapes are pinned against the server modules that write them.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import './test_support/tsResolve.mjs';

function refuseNetwork() {
    throw new Error('Link routing never reaches the network.');
}

globalThis.fetch = refuseNetwork;

// The repository resolver must be registered before extensionless TypeScript imports load.
const { normalizeNotification } = await import('../application/v2_ui/src/lib/notifications.ts');
const { resolveNotificationLink, v2WorkflowRunPath } = await import('../application/v2_ui/src/lib/notificationLinks.ts');
const { readWorkflowRunLink, workflowRunHref } = await import('../application/v2_ui/src/lib/workflowRunLink.ts');
const {
    readWorkflowAlert,
    workflowAlertOpenRunPath,
    workflowAlertWorkflowPath,
} = await import('../application/v2_ui/src/lib/workflowAlertNotices.ts');

const ORIGIN = 'https://simplechat.test';
const PERSONAL = { type: 'personal' };
const GROUP = { type: 'group', groupId: 'grp-1' };
const PERSONAL_RUN = '/workspace/workflows?workflow_id=wf-1&run_id=run-1';
const GROUP_RUN = '/groups/grp-1/workflows?workflow_id=wf-1&run_id=run-1';
// The V2 workflow-activity page, as 6b-1's own link and the server's group links name it.
const PERSONAL_ACTIVITY = '/workflow-activity?workflowId=wf-1&runId=run-1&scope=personal';
const GROUP_ACTIVITY = '/workflow-activity?workflowId=wf-1&runId=run-1&scope=group&groupId=grp-1';
const NO_LINK = { target: null, error: null };
const INVALID_LINK = 'This notification has an invalid link. Open the destination directly.';

// Ids a path segment or a query must not carry: requireWorkspaceId refuses each of them.
const BAD_IDS = ['', ' wf-1', 'wf-1 ', 'wf/1', 'wf\\1', 'wf?1', 'wf#1', '.', '..', 'wf\u00001', 'wf\n1', 'wf\u007f1'];

function serverSource(name) {
    return readFileSync(new URL(name, new URL('../application/single_app/', import.meta.url)), 'utf8')
        .replace(/\r\n/g, '\n');
}

function serverFunction(source, name) {
    const start = source.indexOf(`\ndef ${name}(`);
    assert.ok(start >= 0, `The server no longer defines ${name}.`);
    const end = source.indexOf('\ndef ', start + 1);
    return source.slice(start, end < 0 ? undefined : end);
}

/** The classic workflow-activity link exactly as 6b-1 writes it (workflow_run_notice_link). */
function activityLink(workflowId, runId, extra = {}) {
    return `/workflow-activity?${new URLSearchParams({ workflowId, runId, scope: 'personal', ...extra })}`;
}

/** A notice as the panel holds it, defaulting to 6b-1's notice for a run it couldn't post. */
function notice(overrides = {}) {
    const normalized = normalizeNotification({
        id: 'n-1',
        notification_type: 'workflow_chat_delivery',
        title: 'Results from "Weekly digest" are ready',
        message: "The chat that started this run can't show it anymore. Open the run in Workflows to see the details.",
        created_at: '2026-01-05T09:05:00Z',
        is_read: false,
        link_url: activityLink('wf-1', 'run-1'),
        link_context: {},
        metadata: { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'personal', delivery_status: 'undeliverable' },
        type_config: { icon: 'bi-activity', color: 'info' },
        ...overrides,
    });
    assert.ok(normalized, 'The fixture is not a notice the panel keeps.');
    return normalized;
}

function resolve(overrides) {
    return resolveNotificationLink(notice(overrides), ORIGIN);
}

function routeTo(path) {
    return { target: { kind: 'route', path }, error: null };
}

function alert(metadata) {
    const read = readWorkflowAlert({
        id: 'alert-1',
        notification_type: 'workflow_priority_alert',
        title: 'Weekly digest needs attention',
        message: 'Three items matched.',
        created_at: '2026-01-05T09:05:00Z',
        is_read: false,
        link_url: '',
        link_context: {},
        metadata: { workflow_name: 'Weekly digest', ...metadata },
        type_config: { icon: 'bi-bell', color: 'secondary' },
    });
    assert.ok(read, 'The fixture is not an alert the card reads.');
    return read;
}

test("6b-1's notices are the shapes the bell reads", () => {
    const delivery = serverSource('functions_workflow_chat_delivery.py');
    assert.match(delivery, /^NOTIFICATION_TYPE = 'workflow_chat_delivery'$/m);
    assert.match(delivery, /^WORKFLOW_SCOPE = 'personal'$/m);
    assert.ok(serverFunction(delivery, 'workflow_run_notice_link').includes(
        "return '/workflow-activity?' + urlencode({'workflowId': workflow_id, 'runId': run_id, 'scope': WORKFLOW_SCOPE})",
    ));
    assert.ok(serverFunction(delivery, 'notice_metadata').includes(
        "return {'workflow_id': workflow_id, 'run_id': run_id, 'workflow_scope': WORKFLOW_SCOPE, "
        + "'delivery_status': delivery_status}",
    ));

    // The undeliverable and expired notices carry that link and that metadata, and nothing else.
    const sendNotice = serverFunction(serverSource('functions_workflow_chat_delivery_worker.py'), '_send_notice');
    for (const line of [
        'notification_type=NOTIFICATION_TYPE,',
        'link_url=workflow_run_notice_link(delivery.workflow_id, delivery.run_id),',
        'metadata=notice_metadata(delivery.workflow_id, delivery.run_id, delivery_status),',
    ]) {
        assert.ok(sendNotice.includes(line), line);
    }
    assert.doesNotMatch(sendNotice, /link_context=/);

    // A delivered result is announced with the ordinary reply notice, which opens the chat.
    const reply = serverFunction(serverSource('functions_notifications.py'), 'create_chat_response_notification');
    assert.ok(reply.includes("notification_type='chat_response_complete',"));
    assert.ok(reply.includes("link_url=f'/chats?conversationId={conversation_id}',"));
});

test('the run deep link is the Workflows section of the workspace the workflow lives in', () => {
    assert.equal(workflowRunHref('wf-1', 'run-1'), PERSONAL_RUN);
    assert.equal(workflowRunHref('wf-1', 'run-1', PERSONAL), PERSONAL_RUN);
    assert.equal(workflowRunHref('wf-1', 'run-1', GROUP), GROUP_RUN);

    // The group id is a path segment, encoded the way the server quotes it; the ids are query values.
    const href = workflowRunHref('wf 1&x=2', 'run+2', { type: 'group', groupId: "team (a)'s" });
    assert.equal(href, '/groups/team%20%28a%29%27s/workflows?workflow_id=wf+1%26x%3D2&run_id=run%2B2');
    const url = new URL(href, ORIGIN);
    assert.equal(decodeURIComponent(url.pathname), "/groups/team (a)'s/workflows");
    assert.deepEqual(readWorkflowRunLink(url.search), { workflowId: 'wf 1&x=2', runId: 'run+2' });
    assert.deepEqual(readWorkflowRunLink(new URL(GROUP_RUN, ORIGIN).searchParams), { workflowId: 'wf-1', runId: 'run-1' });

    // A group id a path segment can't carry is refused rather than built into another path.
    for (const groupId of ['', 'a/b', 'a\\b', ' grp', '..', 'g?x', 'g#x']) {
        assert.throws(() => workflowRunHref('wf-1', 'run-1', { type: 'group', groupId }), /Invalid workspace identifier/, groupId);
    }
});

test('v2WorkflowRunPath opens a run only in a known workspace, with ids a link can carry', () => {
    assert.equal(v2WorkflowRunPath(PERSONAL, 'wf-1', 'run-1'), PERSONAL_RUN);
    assert.equal(v2WorkflowRunPath(GROUP, 'wf-1', 'run-1'), GROUP_RUN);
    assert.equal(
        v2WorkflowRunPath(PERSONAL, 'wf 1&x=2', 'run=2'),
        '/workspace/workflows?workflow_id=wf+1%26x%3D2&run_id=run%3D2',
    );

    // An unknown workspace is never read as a personal one.
    for (const scope of [null, undefined, { type: 'public', groupId: 'grp-1' }, { type: '' }, { type: 'Personal' }]) {
        assert.equal(v2WorkflowRunPath(scope, 'wf-1', 'run-1'), null, JSON.stringify(scope));
    }
    for (const groupId of ['', 'a/b', ' grp-1', '..', undefined]) {
        assert.equal(v2WorkflowRunPath({ type: 'group', groupId }, 'wf-1', 'run-1'), null, String(groupId));
    }
    for (const id of [...BAD_IDS, null, undefined, 7, { id: 'wf-1' }]) {
        assert.equal(v2WorkflowRunPath(PERSONAL, id, 'run-1'), null, `workflow ${JSON.stringify(id)}`);
        assert.equal(v2WorkflowRunPath(PERSONAL, 'wf-1', id), null, `run ${JSON.stringify(id)}`);
        assert.equal(v2WorkflowRunPath(GROUP, id, 'run-1'), null, `group workflow ${JSON.stringify(id)}`);
    }
});

test("6b-1's notice about a run it couldn't post opens the run's activity in V2", () => {
    assert.deepEqual(resolve({}), routeTo(PERSONAL_ACTIVITY));
    // The expired notice is the same link with another title and delivery status.
    assert.deepEqual(resolve({
        title: '"Weekly digest" didn\'t finish in time to post to chat',
        metadata: { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'personal', delivery_status: 'expired' },
    }), routeTo(PERSONAL_ACTIVITY));
    // The page reads the link's own query, so extra parameters ride along and the fragment and the
    // trailing slash, which it does not read, do not.
    assert.deepEqual(
        resolve({ link_url: `/workflow-activity/?${new URLSearchParams({ workflowId: 'wf-1', runId: 'run-1', scope: 'personal', tab: 'x' })}#top` }),
        routeTo(`${PERSONAL_ACTIVITY}&tab=x`),
    );
    // Ids the link encodes stay encoded as it wrote them.
    assert.deepEqual(resolve({
        link_url: activityLink('wf 1&x', 'run=1'),
        metadata: { workflow_id: 'wf 1&x', run_id: 'run=1', workflow_scope: 'personal' },
    }), routeTo('/workflow-activity?workflowId=wf+1%26x&runId=run%3D1&scope=personal'));
    // What the notice wrote about itself does not decide where its link goes.
    assert.deepEqual(resolve({ metadata: { workflow_scope: 'personal' } }), routeTo(PERSONAL_ACTIVITY));
    assert.deepEqual(resolve({
        link_context: { group_id: 'grp-9' },
        metadata: { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'personal', group_id: 'grp-9' },
    }), routeTo(PERSONAL_ACTIVITY));
});

test("6b-1's delivered-result notice still opens the chat it posted into", () => {
    const resolved = resolve({
        notification_type: 'chat_response_complete',
        title: 'AI responded in Planning',
        message: 'Results from "Weekly digest" are in your chat',
        link_url: '/chats?conversationId=conv-1',
        link_context: { workspace_type: 'personal', conversation_id: 'conv-1' },
        metadata: { conversation_id: 'conv-1', message_id: 'assistant_workflow_delivery_abc' },
        type_config: { icon: 'bi-chat-dots', color: 'success' },
    });
    assert.deepEqual(resolved, { target: { kind: 'conversation', conversationId: 'conv-1' }, error: null });
});

test("a group run's link opens the group's activity page, and the group the link names is the one it reads", () => {
    const groupLink = activityLink('wf-1', 'run-1', { scope: 'group', groupId: 'grp-1' });
    const groupMetadata = { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'group', workflow_group_id: 'grp-1' };
    assert.deepEqual(resolve({ link_url: groupLink, metadata: groupMetadata }), routeTo(GROUP_ACTIVITY));
    // A link names its own group; what the notice says about another one does not move it.
    for (const metadata of [
        { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'group', workflow_group_id: 'grp-2' },
        { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'group', group_id: 'grp-1' },
        { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'personal' },
    ]) {
        assert.deepEqual(resolve({ link_url: groupLink, metadata }), routeTo(GROUP_ACTIVITY), JSON.stringify(metadata));
    }
    // A group the link leaves out is the reader's active group, which the server resolves.
    const unnamedGroup = activityLink('wf-1', 'run-1', { scope: 'group' });
    assert.deepEqual(resolve({ link_url: unnamedGroup, metadata: groupMetadata }), routeTo(unnamedGroup));
    // A group id the page cannot carry is reported, not opened.
    const badGroup = activityLink('wf-1', 'run-1', { scope: 'group', groupId: 'grp/1' });
    assert.deepEqual(resolve({ link_url: badGroup, metadata: { ...groupMetadata, workflow_group_id: 'grp/1' } }), { target: null, error: INVALID_LINK });
});

test('a workflow-activity link is judged by its own query, and the page reads whatever it names', () => {
    // A workspace, a workflow or a run left out, or the personal default spelled out or not, is still the page.
    for (const link of [
        `/workflow-activity?${new URLSearchParams({ workflowId: 'wf-1', runId: 'run-1' })}`,
        `/workflow-activity?${new URLSearchParams({ workflowId: 'wf-1', scope: 'personal' })}`,
        `/workflow-activity?${new URLSearchParams({ runId: 'run-1', scope: 'personal' })}`,
        activityLink('wf-1', 'run-1', { scope: '' }),
        '/workflow-activity',
    ]) {
        assert.deepEqual(resolve({ link_url: link }), routeTo(link), link);
    }
    // Whatever the notice says about another workspace, workflow or run, its link decides.
    for (const metadata of [
        { workflow_id: 'wf-1', run_id: 'run-1' },
        { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'public' },
        { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'group', workflow_group_id: 'grp-1' },
        { workflow_id: 'wf-2', run_id: 'run-1', workflow_scope: 'personal' },
        { workflow_id: 'wf-1', run_id: 'run-2', workflow_scope: 'personal' },
    ]) {
        assert.deepEqual(resolve({ link_url: PERSONAL_ACTIVITY, metadata }), routeTo(PERSONAL_ACTIVITY), JSON.stringify(metadata));
    }
    // A scope the page does not know, or an id a link must not carry, is reported.
    for (const link of [
        activityLink('wf-1', 'run-1', { scope: 'public' }),
        activityLink('wf/1', 'run-1'),
        activityLink('wf-1', ' run-1'),
        activityLink('wf-1', 'run-1', { groupId: 'grp\\1' }),
    ]) {
        assert.deepEqual(resolve({ link_url: link }), { target: null, error: INVALID_LINK }, link);
    }
});

test('a Microsoft 365 notice about a workflow run opens the activity page that draws its saved action', () => {
    const link = activityLink('wf-1', 'run-1');
    const metadata = { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'personal' };
    for (const value of ['act-1', '', null]) {
        assert.deepEqual(
            resolve({ link_url: link, metadata: { ...metadata, m365_pending_action_id: value } }),
            routeTo(PERSONAL_ACTIVITY),
            `metadata ${JSON.stringify(value)}`,
        );
        assert.deepEqual(
            resolve({ link_url: link, metadata, link_context: { m365_pending_action_id: value } }),
            routeTo(PERSONAL_ACTIVITY),
            `link context ${JSON.stringify(value)}`,
        );
    }
    // The group it names is no longer made active on the way: V2 pages name their own workspace.
    assert.deepEqual(
        resolve({ link_url: link, metadata, link_context: { m365_pending_action_id: 'act-1', group_id: 'grp-3' } }),
        routeTo(PERSONAL_ACTIVITY),
    );
    // The server's own link for a workflow action names the run and the group it ran in, as the page reads it.
    const runtime = serverSource('functions_m365_runtime.py');
    const start = runtime.indexOf('    def notify_delivery(action):');
    assert.ok(start >= 0, 'The server no longer defines notify_delivery.');
    const delivery = runtime.slice(start, runtime.indexOf('@contextmanager', start));
    for (const line of [
        '"workflowId": action["workflow_id"], "runId": action["run_id"],',
        '"scope": "group" if context.get("group_id") else "personal",',
        'query["groupId"] = context["group_id"]',
        'link_url = f"/workflow-activity?{urlencode(query)}"',
    ]) {
        assert.ok(delivery.includes(line), line);
    }
    assert.deepEqual(
        resolve({ link_url: GROUP_ACTIVITY, metadata: { ...metadata, workflow_scope: 'group', m365_pending_action_id: 'act-1' } }),
        routeTo(GROUP_ACTIVITY),
    );
});

test('a chat link to a Microsoft 365 action opens the V2 conversation and names the action', () => {
    // V2 chat renders the saved action's card, so this no longer goes through classic.
    assert.deepEqual(resolve({
        notification_type: 'm365_approval_requested',
        link_url: '/chats?conversationId=conv-1&m365_pending_action=act-1',
        metadata: { m365_pending_action_id: 'act-1' },
    }), { target: { kind: 'conversation', conversationId: 'conv-1', pendingActionId: 'act-1' }, error: null });
    // An action id a link must not carry opens the conversation without it.
    assert.deepEqual(resolve({
        link_url: '/chats?conversationId=conv-1&m365_pending_action=act%2F1',
        metadata: { m365_pending_action_id: 'act-1' },
    }), { target: { kind: 'conversation', conversationId: 'conv-1' }, error: null });
});

test('a workflow notice without a link opens the run its metadata names, and nothing else does', () => {
    const personal = { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'personal' };
    const group = { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'group', workflow_group_id: 'grp-1' };
    for (const type of ['workflow_chat_delivery', 'workflow_priority_alert']) {
        assert.deepEqual(resolve({ notification_type: type, link_url: '', metadata: personal }), routeTo(PERSONAL_RUN), type);
        assert.deepEqual(resolve({ notification_type: type, link_url: '', metadata: group }), routeTo(GROUP_RUN), type);
        assert.deepEqual(resolve({ notification_type: type, link_url: undefined, metadata: personal }), routeTo(PERSONAL_RUN), type);
    }

    // Another notice type that happens to name a run has no link.
    for (const type of ['chat_response_complete', 'system_announcement', 'm365_approval_requested', 'workflow_chat_delivery_extra', '']) {
        assert.deepEqual(resolve({ notification_type: type, link_url: '', metadata: personal }), NO_LINK, type);
    }

    const unplaced = [
        // Microsoft 365, wherever the action id was written.
        [{ ...personal, m365_pending_action_id: 'act-1' }, {}],
        [personal, { m365_pending_action_id: 'act-1' }],
        // A group named only through `group_id`, which classic reads as the group to make active.
        [{ workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'group', group_id: 'grp-1' }, {}],
        [{ workflow_id: 'wf-1', run_id: 'run-1', group_id: 'grp-1' }, {}],
        [{ workflow_id: 'wf-1', run_id: 'run-1' }, { group_id: 'grp-1', workspace_type: 'group' }],
        // No workspace, or one V2 doesn't know.
        [{ workflow_id: 'wf-1', run_id: 'run-1' }, {}],
        [{ ...personal, workflow_scope: 'public' }, {}],
        [{ ...personal, workflow_scope: ['personal'] }, {}],
        [{ ...group, workflow_group_id: 'grp/1' }, {}],
        // A missing id, or one a link must not carry.
        [{ ...personal, run_id: undefined }, {}],
        [{ ...personal, workflow_id: 'wf/1' }, {}],
        [{ ...personal, run_id: 'run-1 ' }, {}],
        [{ ...personal, run_id: 42 }, {}],
    ];
    for (const type of ['workflow_chat_delivery', 'workflow_priority_alert']) {
        for (const [metadata, linkContext] of unplaced) {
            const resolved = resolve({ notification_type: type, link_url: '', metadata, link_context: linkContext });
            assert.deepEqual(resolved, NO_LINK, `${type} ${JSON.stringify({ metadata, linkContext })}`);
        }
    }

    // A link that is present but blank is still reported, not replaced by the run.
    assert.deepEqual(resolve({ link_url: '   ', metadata: personal }), { target: null, error: INVALID_LINK });
});

test("the alert card's Open run is the run in the workflow's own workspace, or nothing", () => {
    const personal = alert({ workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'personal' });
    assert.equal(workflowAlertOpenRunPath(personal), PERSONAL_RUN);
    assert.equal(workflowAlertWorkflowPath(personal), PERSONAL_RUN);

    const group = alert({ workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'group', workflow_group_id: 'grp-1' });
    assert.equal(workflowAlertOpenRunPath(group), GROUP_RUN);
    assert.equal(workflowAlertWorkflowPath(group), GROUP_RUN);

    // Without a run, the card keeps Open workflow.
    const noRun = alert({ workflow_id: 'wf-1', workflow_scope: 'personal' });
    assert.equal(workflowAlertOpenRunPath(noRun), null);
    assert.equal(workflowAlertWorkflowPath(noRun), '/workspace/workflows?workflow_id=wf-1');

    // An alert it can't place offers neither: `group_id` alone never places it.
    for (const metadata of [
        { workflow_id: 'wf-1', run_id: 'run-1' },
        { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'group', group_id: 'grp-1' },
        { workflow_id: 'wf-1', run_id: 'run-1', workflow_scope: 'group', workflow_group_id: 'grp/1' },
    ]) {
        const unplaced = alert(metadata);
        assert.equal(workflowAlertOpenRunPath(unplaced), null, JSON.stringify(metadata));
        assert.equal(workflowAlertWorkflowPath(unplaced), null, JSON.stringify(metadata));
    }

    // An id a link must not carry leaves the run out rather than building another address.
    const badRun = alert({ workflow_id: 'wf-1', run_id: 'run/1', workflow_scope: 'personal' });
    assert.equal(workflowAlertOpenRunPath(badRun), null);
    assert.equal(workflowAlertWorkflowPath(badRun), '/workspace/workflows?workflow_id=wf-1');
});
