// test_workflow_configuration.ts
// Functional contract, serialization and Python editor parity checks.
// Version: 0.261.343
// Implemented in: 0.261.343

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
    newWorkflowDefinition, normalizeWorkflowChatExecution, normalizeWorkflowResultsDelivery,
    resolveWorkflowChatExecution, workflowForSave, workflowValidationErrors,
    type WorkflowChatExecution, type WorkflowEditorOptions, type WorkflowScope,
} from '../application/v2_ui/src/lib/workflowEditor';

const fixture = JSON.parse(readFileSync(0, 'utf8'));
const automatic = fixture.automatic as WorkflowChatExecution;
const selected = fixture.selected as WorkflowChatExecution;
const off = fixture.off as WorkflowChatExecution;
const personal: WorkflowScope = { type: 'personal' };
const group: WorkflowScope = { type: 'group', groupId: 'group-alpha' };
const baseOptions = fixture.options as WorkflowEditorOptions;
const options: WorkflowEditorOptions = {
    ...baseOptions,
    chat_execution: {
        modes: [
            { id: 'orchestration', label: 'Orchestration', available: true },
            { id: 'selected', label: 'Selected', available: true },
            { id: 'off', label: 'Off', available: true },
        ],
        capabilities: [{ id: 'web_search', label: 'Web search', available: false }],
        visual_requirements: [{ id: 'chart', label: 'Chart', available: true }],
        default: automatic,
    },
};
const legacy = newWorkflowDefinition(personal);
assert.equal(legacy.chat_execution, undefined);
assert.equal(legacy.chat_capabilities_enabled, true);
assert.equal(legacy.results_delivery?.conversation_type, 'personal');
assert.equal(newWorkflowDefinition(group).results_delivery?.conversation_type, 'group');
assert.deepEqual(normalizeWorkflowChatExecution(selected), selected);
assert.deepEqual(resolveWorkflowChatExecution({ chat_execution: selected }, { chat_execution: off }), off);
assert.equal(resolveWorkflowChatExecution({}), undefined);
assert.throws(() => normalizeWorkflowChatExecution({ ...selected, required_capabilities: [] , visual_requirements: [] }));
assert.throws(() => normalizeWorkflowChatExecution({ ...automatic, required_capabilities: ['web_search'] }));
assert.throws(() => normalizeWorkflowChatExecution({ ...selected, required_capabilities: null }));
for (const capability of ['workflow_propose', 'workflow_run', 'workflow_results', 'workflow_handoff']) {
    assert.throws(() => normalizeWorkflowChatExecution({ ...selected, required_capabilities: [capability] }));
}
assert.throws(() => normalizeWorkflowResultsDelivery({
    version: 1, mode: 'conversation', conversation_type: 'group', recipient_ids: [], all_group_members: false,
}, personal));
assert.throws(() => normalizeWorkflowResultsDelivery({
    version: 1, mode: 'conversation', conversation_type: 'group_shared', recipient_ids: [fixture.recipient],
    all_group_members: false, group_id: 'different-group',
}, group));
const canonical = normalizeWorkflowResultsDelivery({
    version: 1, mode: 'conversation', conversation_type: 'shared',
    recipient_ids: [fixture.recipient.toUpperCase(), fixture.recipient], all_group_members: false,
}, personal);
assert.deepEqual(canonical.recipient_ids, [fixture.recipient]);

const projections: Record<string, unknown> = {};
for (const scope of [personal, group]) {
    const draft = newWorkflowDefinition(scope, options);
    draft.name = 'Digest';
    draft.tasks[0] = { ...draft.tasks[0], id: 'research', instructions: 'Research it.', chat_execution: selected };
    projections[scope.type] = JSON.parse(JSON.stringify(workflowForSave(draft, null, scope)));
    const invalid = workflowValidationErrors(draft, options);
    assert.ok(invalid.some((error) => error.includes('Web search') && error.includes('unavailable')));
    delete draft.tasks[0].chat_execution;
    const inherited = workflowForSave(draft, null, scope);
    assert.equal(inherited.tasks[0].chat_execution, undefined);
    draft.chat_execution = selected;
    const invalidDefault = workflowValidationErrors(draft, options);
    assert.ok(invalidDefault.some((error) => error.includes('Workflow chat capabilities') && error.includes('unavailable')));
}
process.stdout.write(JSON.stringify(projections));
