// test_v2_workflow_chat_controls.mjs
// Version: 0.261.343
// Implemented in: 0.261.343
// Validates inherited execution, result audiences, scoped assist routing, additive badges,
// and the real keyed diff/revert used by the editor and its authoring history.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

const {
    newWorkflowDefinition, normalizeWorkflowDefinition, workflowForSave, workflowValidationErrors,
} = await import('../application/v2_ui/src/lib/workflowEditor.ts');
const {
    effectiveTaskChatExecution, workflowChatExecutionSummary, workflowResultsSummary,
} = await import('../application/v2_ui/src/lib/workflowChatExecution.ts');
const { diffWorkflowChanges, buildWorkflowKeyRevert, workflowTaskKey } =
    await import('../application/v2_ui/src/lib/workflowChangeTracking.ts');
const { workflowAssistPath, workflowAssistThreadKey, postWorkflowAssist } =
    await import('../application/v2_ui/src/lib/workflowAssist.ts');
const { isWorkflowConversation, workspaceBadge } = await import('../application/v2_ui/src/lib/conversationBadges.ts');

const automatic = { version: 1, mode: 'orchestration', required_capabilities: [], visual_requirements: [] };
const selected = { version: 1, mode: 'selected', required_capabilities: ['web_search'], visual_requirements: ['chart'] };
const options = {
    definition_version: 2, supported_definition_versions: [1, 2, 3], can_manage: true,
    agents: [], models: [], max_tasks: 100, default_model: { valid: true },
    scope: { type: 'personal' },
    chat_execution: {
        default: automatic,
        modes: [
            { id: 'orchestration', label: 'Orchestration', available: true },
            { id: 'selected', label: 'Selected capabilities', available: true },
            { id: 'off', label: 'Off', available: true },
        ],
        capabilities: [{ id: 'web_search', label: 'Web search', available: true }],
        visual_requirements: [{ id: 'chart', label: 'Charts', available: true }],
    },
    results_delivery: {
        default: { version: 1, mode: 'conversation', conversation_type: 'personal', recipient_ids: [], all_group_members: false },
        modes: [], conversation_types: [{ id: 'personal' }, { id: 'shared' }], recipient_choices: [], allow_all_group_members: false,
    },
};

function draft() {
    const value = newWorkflowDefinition({ type: 'personal' }, options);
    value.name = 'Current news';
    value.tasks[0].name = 'Research';
    value.tasks[0].instructions = 'Search current news and chart the findings.';
    return value;
}

test('new drafts default automatic and private, legacy drafts do not gain configuration', () => {
    const value = draft();
    assert.deepEqual(value.chat_execution, automatic);
    assert.equal(value.results_delivery.conversation_type, 'personal');
    const legacy = normalizeWorkflowDefinition({
        ...value, chat_execution: undefined, results_delivery: undefined, chat_capabilities_enabled: true,
    });
    const saved = workflowForSave(legacy, legacy, { type: 'personal' });
    assert.equal(saved.chat_execution, undefined);
    assert.equal(saved.results_delivery, undefined);
    assert.match(workflowChatExecutionSummary(undefined, true), /Legacy core/);
});

test('task override replaces requirements; removing it restores inheritance', () => {
    const value = draft();
    value.chat_execution = selected;
    const task = { ...value.tasks[0], chat_execution: { ...selected, required_capabilities: ['url_fetch'], visual_requirements: [] } };
    const effective = effectiveTaskChatExecution(value, task);
    assert.deepEqual(effective.required_capabilities, ['url_fetch']);
    delete task.chat_execution;
    const inherited = effectiveTaskChatExecution(value, task);
    assert.equal(inherited, selected);
    assert.match(workflowChatExecutionSummary(inherited, false, options), /Web search, Charts/);
});

test('new settings each get a stable change key and targeted revert leaves other edits intact', () => {
    const baseline = draft();
    const changed = structuredClone(baseline);
    changed.chat_execution = selected;
    changed.tasks[0].chat_execution = { version: 1, mode: 'off', required_capabilities: [], visual_requirements: [] };
    changed.results_delivery = { ...changed.results_delivery, mode: 'history' };
    const diff = diffWorkflowChanges(baseline, changed);
    assert.deepEqual(new Set(diff.changes.map((change) => change.key)), new Set([
        'chat_execution', 'results_delivery', workflowTaskKey(changed.tasks[0].id, 'chat_execution'),
    ]));
    assert.match(diff.byKey.get('chat_execution').after, /Required: web_search, chart/);
    const reverted = buildWorkflowKeyRevert(changed, baseline, [workflowTaskKey(changed.tasks[0].id, 'chat_execution')]);
    assert.equal(reverted.failed.size, 0);
    assert.equal(reverted.candidate.tasks[0].chat_execution, undefined);
    assert.deepEqual(reverted.candidate.chat_execution, selected);
    assert.equal(reverted.candidate.results_delivery.mode, 'history');
});

test('selected empty and unavailable requirements fail save validation', () => {
    const value = draft();
    value.chat_execution = { ...selected, required_capabilities: [], visual_requirements: [] };
    const emptyErrors = workflowValidationErrors(value, options);
    assert.match(emptyErrors.join('\n'), /requires at least one/);
    value.chat_execution = selected;
    const disabled = structuredClone(options);
    disabled.chat_execution.capabilities[0].available = false;
    const unavailableErrors = workflowValidationErrors(value, disabled);
    assert.match(unavailableErrors.join('\n'), /unavailable|not available/);
});

test('group audiences stay group-bound and display all-member versus named delivery', () => {
    const value = draft();
    value.group_id = 'group-one';
    value.results_delivery = { version: 1, mode: 'conversation', conversation_type: 'group_shared', recipient_ids: [], all_group_members: true };
    assert.equal(workflowResultsSummary(value), 'Shared with all current group members');
    value.results_delivery = { ...value.results_delivery, all_group_members: false, recipient_ids: ['00000000-0000-4000-8000-000000000001'] };
    assert.match(workflowResultsSummary(value), /1 named recipient$/);
    value.results_delivery = { ...value.results_delivery, conversation_type: 'shared' };
    const errors = workflowValidationErrors(value, { ...options, scope: { type: 'group', id: 'group-one' } });
    assert.match(errors.join('\n'), /own scope/);
});

test('group assist URL and thread keys are scoped even when saved records omit scope', async () => {
    const value = draft();
    const personalKey = workflowAssistThreadKey(value, 'same-id');
    assert.equal(workflowAssistPath(value), '/api/user/workflows/assist');
    value.group_id = 'group/one';
    assert.equal(workflowAssistPath(value), '/api/groups/group%2Fone/workflows/assist');
    assert.notEqual(workflowAssistThreadKey(value, 'same-id'), personalKey);
    const firstGroupKey = workflowAssistThreadKey(value, 'same-id');
    value.group_id = 'group-two';
    assert.notEqual(workflowAssistThreadKey(value, 'same-id'), firstGroupKey);
    const previousFetch = globalThis.fetch;
    let requested;
    globalThis.fetch = async (url) => {
        requested = url;
        return new Response(JSON.stringify({
            submission_id: 'test', outcome: 'explained', reply: 'Unchanged.', candidate: null,
            changes: [], warnings: [], context_documents: [],
        }), { status: 200 });
    };
    try {
        const result = await postWorkflowAssist({ submission_id: 'test', draft: value }, new AbortController().signal);
        assert.equal(result.ok, true);
        assert.equal(requested, '/api/groups/group-two/workflows/assist');
    } finally {
        globalThis.fetch = previousFetch;
    }
});

test('workflow provenance adds a badge without replacing shared or group labels or inspecting titles', () => {
    assert.equal(isWorkflowConversation({ title: 'Workflow: misleading title', chat_type: 'personal_single_user' }), false);
    assert.equal(isWorkflowConversation({ chat_type: 'workflow' }), true);
    for (const chatType of ['personal_multi_user', 'group_multi_user']) {
        const metadata = { chat_type: chatType, workflow_id: 'workflow-one', context: [{ type: 'primary', scope: 'group', name: 'Policy team' }] };
        assert.equal(isWorkflowConversation(metadata), true);
        assert.equal(workspaceBadge(metadata).label, chatType === 'personal_multi_user' ? 'shared' : 'Policy team');
    }
    assert.equal(isWorkflowConversation({ workflow_provenance: { workflow_id: 'workflow-one', run_id: 'run-one' } }), true);
    assert.equal(isWorkflowConversation({ workflow_provenance: '<script>bad</script>' }), false);
    assert.equal(workspaceBadge({
        chat_type: 'workflow', context: [{ type: 'primary', scope: 'group', name: 'Audit group' }],
    }).label, 'Audit group');
});
