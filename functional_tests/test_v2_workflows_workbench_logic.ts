// test_v2_workflows_workbench_logic.ts
//
// Runtime test for the decisions the V2 Workflows workbench and editor cards make.
// Version: 0.261.271
// Implemented in: 0.261.271
//
// The Workflows section now draws the way Admin Settings does: a workbench of one-line rows beside
// a detail pane, and an editor of distinct cards that each carry Admin's status chip. Which status
// a card shows, what a row says, and which workflows a filter keeps are judgements that a
// screenshot can't check -- a card that reads Configured over a missing agent looks exactly like a
// correct one. So they are executed here, against the real modules.
//
// Run by test_v2_workflows_admin_design_language.py, which bundles this with the esbuild Vite
// already brings in and executes it under node, skipping when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import { presentSectionStatus } from '../application/v2_ui/src/components/admin/sectionStatusPresentation';
import { newWorkflowAlertRule } from '../application/v2_ui/src/lib/workflowAlerts';
import {
    createWorkflowTask,
    newWorkflowDefinition,
    WORKFLOW_TASK_INSTRUCTIONS_LIMIT,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
} from '../application/v2_ui/src/lib/workflowEditor';
import {
    workflowEditorSections,
    type WorkflowEditorSectionContext,
    type WorkflowEditorSectionId,
} from '../application/v2_ui/src/lib/workflowEditorSections';
import {
    DEFAULT_WORKFLOW_WORKBENCH_FILTERS,
    filterWorkflows,
    workflowDetailMeta,
    workflowFiltersApplied,
    workflowLastOutcome,
    workflowNeedsAttention,
    workflowOverviewFacts,
    workflowRowMeta,
    workflowRunState,
    workflowStatusLabel,
    type WorkflowWorkbenchFilters,
} from '../application/v2_ui/src/lib/workflowWorkbench';

let passed = 0;

function check(name: string, run: () => void): void {
    run();
    passed += 1;
    console.log(`  ok  ${name}`);
}

const AGENT = { id: 'agent-1', name: 'reviewer', display_name: 'Workspace reviewer', is_global: false, is_group: false };

const OPTIONS: WorkflowEditorSectionContext['options'] = {
    agents: [AGENT],
    models: [{ endpoint_id: 'endpoint-1', model_id: 'gpt', label: 'Workspace GPT', provider: 'aoai' }],
    default_model: { label: 'App default', valid: true },
} as Pick<WorkflowEditorOptions, 'agents' | 'models' | 'default_model' | 'schedule'>;

function context(overrides: Partial<WorkflowEditorSectionContext> = {}): WorkflowEditorSectionContext {
    return { options: OPTIONS, scopeType: 'personal', ...overrides };
}

function draft(overrides: Partial<WorkflowDefinition> = {}): WorkflowDefinition {
    const base = newWorkflowDefinition({ type: 'personal' });
    const task = { ...base.tasks[0], instructions: 'Review the documents.' };
    return { ...base, name: 'Quarterly review', tasks: [task], ...overrides };
}

function section(workflow: WorkflowDefinition, id: WorkflowEditorSectionId, ctx = context()) {
    const found = workflowEditorSections(workflow, ctx).find((item) => item.id === id);
    assert.ok(found, `expected a ${id} card`);
    return found;
}

console.log('Workflow editor cards');

check('a list draft shows every card but Limits, in reading order', () => {
    const ids = workflowEditorSections(draft(), context()).map((item) => item.id);
    assert.deepEqual(ids, ['basics', 'trigger', 'file-sync', 'execution', 'references', 'tasks', 'alerts']);
});

check('a structured draft adds Limits before its tasks and names the task card by surface', () => {
    const structured = draft({ definition_version: 3 });
    const sections = workflowEditorSections(structured, context({ structuredSurface: 'flow' }));
    assert.deepEqual(sections.map((item) => item.id),
        ['basics', 'trigger', 'file-sync', 'execution', 'references', 'limits', 'tasks', 'alerts']);
    assert.equal(sections.find((item) => item.id === 'tasks')?.label, 'Structured Flow');
    assert.equal(section(structured, 'tasks', context({ structuredSurface: 'list' })).label, 'Structured List');
    const limits = section(structured, 'limits');
    assert.equal(limits.status, 'none');
    assert.match(limits.meta, /^Up to \d[\d,]* execution admissions? · [\d,]+ second deadline$/);
});

check('Basics needs a name, and a runner that can actually run', () => {
    assert.equal(section(draft({ name: '   ' }), 'basics').status, 'incomplete');
    assert.equal(section(draft(), 'basics').status, 'ready');
    assert.equal(section(draft(), 'basics').meta, 'Runner: App default model');

    const brokenDefault = context({ options: { ...OPTIONS, default_model: { valid: false } } });
    assert.equal(section(draft(), 'basics', brokenDefault).status, 'incomplete',
        'an invalid app default with no explicit model must not read as configured');
    const explicit = draft({ model_endpoint_id: 'endpoint-1', model_id: 'gpt' });
    assert.equal(section(explicit, 'basics', brokenDefault).status, 'ready');
    assert.equal(section(explicit, 'basics').meta, 'Runner: Workspace GPT');

    assert.equal(section(draft({ runner_type: 'agent' }), 'basics').status, 'incomplete');
    assert.equal(section(draft({ runner_type: 'agent' }), 'basics').meta, 'Runner: Agent not selected');
    const withAgent = draft({ runner_type: 'agent', selected_agent: AGENT });
    assert.equal(section(withAgent, 'basics').status, 'ready');
    assert.equal(section(withAgent, 'basics').meta, 'Runner: Workspace reviewer');
});

check('Trigger reads Off when the workflow is switched off, and says when it runs', () => {
    assert.equal(section(draft(), 'trigger').status, 'ready');
    assert.equal(section(draft(), 'trigger').meta, 'Manual · runs only when started');
    assert.equal(section(draft({ is_enabled: false }), 'trigger').status, 'off');
    const scheduled = draft({ trigger_type: 'interval', schedule: { unit: 'minutes', value: 45 } });
    assert.equal(section(scheduled, 'trigger').meta, 'Every 45 minutes');
});

check('File Sync is Off until used, then needs a source, and is blocked where the group turned it off', () => {
    const off = section(draft(), 'file-sync');
    assert.equal(off.status, 'off');
    assert.equal(off.meta, 'Runs without syncing first');

    const noSources = draft({ file_sync: { enabled: true, sources: [] } });
    assert.equal(section(noSources, 'file-sync').status, 'incomplete');
    assert.equal(section(noSources, 'file-sync').meta, '0 sources · synced before each run');

    const source = { scope_type: 'personal', scope_id: 'user-1', source_id: 'source-1' };
    const synced = draft({ file_sync: { enabled: true, sources: [source] } });
    assert.equal(section(synced, 'file-sync').status, 'ready');
    assert.equal(section(synced, 'file-sync').meta, '1 source · synced before each run');
    assert.equal(section(synced, 'file-sync', context({ groupFileSyncEnabled: false })).status, 'blocked');
    assert.equal(section(synced, 'file-sync', context({ groupFileSyncEnabled: null })).status, 'ready',
        'an unknown group gate must not read as blocked');

    // The Monitor trigger syncs whether or not File Sync was chosen separately.
    const monitor = draft({ trigger_type: 'file_sync', file_sync: { sources: [source] } });
    assert.equal(section(monitor, 'file-sync').status, 'ready');
    assert.equal(section(monitor, 'file-sync').meta, '1 source · checked for changes');
});

check('Execution and Shared references carry facts but never a status chip', () => {
    const halt = section(draft({ durable_execution: false }), 'execution');
    assert.equal(halt.status, 'none');
    assert.equal(halt.meta, 'Halt on failure · 0 retries');
    // New workflows run durably by default, and the card says so.
    assert.equal(section(draft(), 'execution').meta, 'Halt on failure · 0 retries · Durable execution');
    const durable = draft({ durable_execution: true, error_handling: { strategy: 'continue', retry_count: 1 } });
    assert.equal(section(durable, 'execution').meta, 'Continue after failure · 1 retry · Durable execution');

    assert.equal(section(draft(), 'references').status, 'none');
    assert.equal(section(draft(), 'references').meta, 'No shared documents');
    const references = [
        { id: 'r1', name: 'brief', document_id: 'doc-1', scope_type: 'personal' as const, scope_id: 'user-1' },
        { id: 'r2', name: 'policy', document_id: 'doc-2', scope_type: 'public' as const, scope_id: 'public-1' },
    ];
    assert.equal(section(draft({ reference_inputs: references }), 'references').meta, '2 shared documents');
});

check('Tasks need at least one task, and count the tasks that show a problem', () => {
    assert.equal(section(draft({ tasks: [] }), 'tasks').status, 'incomplete');
    assert.equal(section(draft({ tasks: [] }), 'tasks').meta, '0 tasks');
    assert.equal(section(draft(), 'tasks').status, 'ready');
    assert.equal(section(draft(), 'tasks').meta, '1 task');

    const tooLong = { ...createWorkflowTask(1), instructions: 'x'.repeat(WORKFLOW_TASK_INSTRUCTIONS_LIMIT + 1) };
    const withProblem = draft({ tasks: [draft().tasks[0], tooLong] });
    assert.equal(section(withProblem, 'tasks').status, 'incomplete');
    assert.equal(section(withProblem, 'tasks').meta, '2 tasks · 1 needs attention');
});

check('Alerts read Off, ready, or incomplete exactly as the rule checks say', () => {
    assert.equal(section(draft(), 'alerts').status, 'off');
    assert.equal(section(draft(), 'alerts').meta, 'Never notify me');
    assert.equal(section(draft({ alert_mode: 'every_run' }), 'alerts').status, 'ready');
    assert.equal(section(draft({ alert_mode: 'every_run' }), 'alerts').meta, 'On every run');

    const noRules = draft({ alert_mode: 'rules', alert_rules: [] });
    assert.equal(section(noRules, 'alerts').status, 'incomplete');
    assert.equal(section(noRules, 'alerts').meta, 'Only when a condition is met · 0 rules');
    const oneRule = draft({ alert_mode: 'rules', alert_rules: [newWorkflowAlertRule()] });
    assert.equal(section(oneRule, 'alerts').status, 'ready');
    assert.equal(section(oneRule, 'alerts').meta, 'Only when a condition is met · 1 rule');

    // Alerting the whole group is a group workflow's choice only.
    const groupAudience = draft({ alert_mode: 'rules', alert_rules: [{ ...newWorkflowAlertRule(), audience: 'group' }] });
    assert.equal(section(groupAudience, 'alerts').status, 'incomplete');
    assert.equal(section(groupAudience, 'alerts', context({ scopeType: 'group' })).status, 'ready');
});

check('every status a card can show is one Admin draws a chip for, or none at all', () => {
    const drafts = [
        draft(), draft({ name: '' }), draft({ is_enabled: false }), draft({ definition_version: 3 }),
        draft({ file_sync: { enabled: true, sources: [] } }), draft({ alert_mode: 'rules', alert_rules: [] }),
    ];
    const statuses = new Set(drafts.flatMap((item) =>
        workflowEditorSections(item, context({ groupFileSyncEnabled: false })).map((card) => card.status)));
    for (const status of statuses) {
        const chip = presentSectionStatus(status);
        if (status === 'none') {
            assert.equal(chip, null, 'a card without a status draws no chip');
        } else {
            assert.ok(chip?.label, `Admin has no chip for ${status}`);
        }
    }
    assert.equal(presentSectionStatus('incomplete')?.label, 'Needs configuration');
    assert.equal(presentSectionStatus('blocked')?.label, 'Prerequisite missing');
});

console.log('Workflows workbench');

function listed(overrides: Partial<WorkflowDefinition>): WorkflowDefinition {
    return draft({ id: String(overrides.name ?? 'workflow').toLowerCase().replace(/\s+/g, '-'), ...overrides });
}

// The first five keep an outcome in `status`, as older records and the editor fixture do; the last
// three have the server's own shape -- `status` for the run in progress, idle once it has ended,
// and the outcome in `last_run_status`.
const WORKFLOWS = [
    listed({ name: 'Quarterly review', description: 'Runs the recurring review.', status: 'completed' }),
    listed({ name: 'Nightly sync', trigger_type: 'interval', schedule: { unit: 'hours', value: 24 }, status: 'failed' }),
    listed({ name: 'Live import', status: 'running', active_run_id: 'run-9' }),
    listed({ name: 'Retired audit', is_enabled: false, status: 'cancelled' }),
    listed({ name: 'Monitor drops', trigger_type: 'file_sync', schedule: { unit: 'minutes', value: 15 }, status: 'failed', active_run_id: 'run-2' }),
    listed({ name: 'Approval gate', status: 'awaiting_approval', active_run_id: 'run-5', last_run_status: 'completed' }),
    listed({ name: 'Weekly digest', status: 'idle', last_run_status: 'completed_partial' }),
    listed({ name: 'Daily report', status: 'idle', last_run_status: 'completed' }),
];

function names(filters: Partial<WorkflowWorkbenchFilters>): string[] {
    return filterWorkflows(WORKFLOWS, { ...DEFAULT_WORKFLOW_WORKBENCH_FILTERS, ...filters }).map((item) => item.name);
}

check('stored statuses read as words, and the readable ones stay as the server wrote them', () => {
    assert.equal(workflowStatusLabel('completed_partial'), 'Completed with task errors');
    assert.equal(workflowStatusLabel('awaiting_approval'), 'Awaiting approval');
    assert.equal(workflowStatusLabel('CANCELED'), 'Cancelled');
    assert.equal(workflowStatusLabel(''), '');
    assert.equal(workflowStatusLabel(undefined), '');
});

check('an active run always reads as running, and no status is never guessed', () => {
    assert.deepEqual(workflowRunState(listed({ name: 'A', status: 'completed', active_run_id: 'run-1' })),
        { label: 'Running', tone: 'warn', status: 'running' });
    assert.deepEqual(workflowRunState(listed({ name: 'B', status: 'queued', active_run_id: 'run-1' })),
        { label: 'Queued', tone: 'warn', status: 'queued' });
    assert.deepEqual(workflowRunState(listed({ name: 'B2', status: 'cancelling', active_run_id: 'run-1' })),
        { label: 'Cancelling', tone: 'warn', status: 'cancelling' });
    assert.equal(workflowRunState(listed({ name: 'C' })), null);
    assert.equal(workflowRunState(listed({ name: 'C2', status: 'idle' })), null);
    assert.equal(workflowRunState(listed({ name: 'D', status: 'failed' }))?.tone, 'danger');
});

check('a finished run reads from last_run_status once the server sets the workflow back to idle', () => {
    const failed = listed({ name: 'E', status: 'idle', last_run_status: 'failed' });
    assert.equal(workflowLastOutcome(failed), 'failed');
    assert.deepEqual(workflowRunState(failed), { label: 'Failed', tone: 'danger', status: 'failed' });
    assert.deepEqual(workflowRunState(listed({ name: 'F', status: 'idle', last_run_status: 'completed_partial' })),
        { label: 'Completed with task errors', tone: 'warn', status: 'completed_partial' });
    // The recorded outcome wins over an outcome an older record kept in status.
    assert.equal(workflowLastOutcome(listed({ name: 'G', status: 'failed', last_run_status: 'completed' })), 'completed');
    // A run in progress is never mistaken for an outcome.
    assert.equal(workflowLastOutcome(listed({ name: 'H', status: 'running' })), '');
    assert.equal(workflowLastOutcome(listed({ name: 'I', status: 'awaiting_sign_in' })), '');
});

check('a run waiting on a person says what it waits for, however the previous run ended', () => {
    const waiting = listed({ name: 'J', status: 'awaiting_approval', active_run_id: 'run-3', last_run_status: 'failed' });
    assert.deepEqual(workflowRunState(waiting), { label: 'Awaiting approval', tone: 'warn', status: 'awaiting_approval' });
    assert.equal(workflowRunState(listed({ name: 'K', status: 'awaiting_sign_in' }))?.label, 'Awaiting sign in');
});

check('a workflow needs attention while it waits on a person, or until a run that went wrong runs again', () => {
    assert.deepEqual(WORKFLOWS.filter(workflowNeedsAttention).map((item) => item.name),
        ['Nightly sync', 'Retired audit', 'Approval gate', 'Weekly digest']);
});

check('search reads names and descriptions, and filters keep the list order', () => {
    assert.deepEqual(names({ query: 'RECURRING' }), ['Quarterly review']);
    assert.deepEqual(names({ query: '  sync ' }), ['Nightly sync']);
    assert.deepEqual(names({ trigger: 'interval' }), ['Nightly sync']);
    assert.deepEqual(names({ trigger: 'file_sync' }), ['Monitor drops']);
    assert.deepEqual(names({ status: 'running' }), ['Live import', 'Monitor drops', 'Approval gate']);
    assert.deepEqual(names({ status: 'attention' }), ['Nightly sync', 'Retired audit', 'Approval gate', 'Weekly digest']);
    assert.deepEqual(names({ status: 'completed' }), ['Quarterly review', 'Daily report']);
    assert.deepEqual(names({ status: 'disabled' }), ['Retired audit']);
    assert.deepEqual(names({ status: 'attention', trigger: 'manual' }), ['Retired audit', 'Approval gate', 'Weekly digest']);
    assert.deepEqual(names({ query: 'absent' }), []);
});

check('only Status and Trigger count as applied filters; search is its own control', () => {
    assert.equal(workflowFiltersApplied(DEFAULT_WORKFLOW_WORKBENCH_FILTERS), 0);
    assert.equal(workflowFiltersApplied({ query: 'x', status: 'all', trigger: 'all' }), 0);
    assert.equal(workflowFiltersApplied({ query: '', status: 'running', trigger: 'manual' }), 2);
});

check('a row leads with how the workflow stands, then its trigger in a word or two; the detail says it in full', () => {
    const [quarterly, nightly, , retired, monitor, approval, digest] = WORKFLOWS;
    assert.equal(workflowRowMeta(quarterly), 'Completed · Manual');
    assert.equal(workflowDetailMeta(quarterly), 'Manual · runs only when started');
    assert.equal(workflowRowMeta(nightly), 'Failed · Every 24 hours');
    assert.equal(workflowRowMeta(retired), 'Cancelled · Manual · Disabled');
    assert.equal(workflowDetailMeta(retired), 'Manual · runs only when started · Disabled');
    assert.equal(workflowRowMeta(monitor), 'Running · Monitor File Sync every 15 minutes');
    assert.equal(workflowRowMeta(approval), 'Awaiting approval · Manual');
    assert.equal(workflowRowMeta(digest), 'Completed with task errors · Manual');
    assert.equal(workflowRowMeta(listed({ name: 'Fresh' })), 'Manual');
});

check('Overview says when it last ran, then lists the editor cards in order, with Run as only when chosen', () => {
    const facts = workflowOverviewFacts(WORKFLOWS[0]);
    assert.deepEqual(facts.map((fact) => fact.label), [
        'Last run', 'Runner', 'Workflow enabled', 'Trigger and schedule', 'File Sync', 'Execution',
        'Shared references', 'Tasks', 'Alerts',
    ]);
    assert.equal(facts[0].value, 'Completed');
    assert.equal(workflowOverviewFacts(listed({ name: 'Fresh' }))[0].value, 'Not run yet');
    const when = '2026-09-16T12:00:00Z';
    const timed = workflowOverviewFacts(listed({ name: 'Timed', status: 'idle', last_run_status: 'failed', last_run_at: when }));
    assert.equal(timed[0].value, `Failed · ${new Date(when).toLocaleString()}`);
    assert.equal(workflowOverviewFacts(listed({ name: 'Odd', last_run_at: 'not a date' }))[0].value, 'Not run yet');
    assert.deepEqual(facts.find((fact) => fact.label === 'Runner'), { label: 'Runner', value: 'Model · App default model' });
    assert.equal(facts.find((fact) => fact.label === 'File Sync')?.value, 'Off');
    assert.equal(facts.find((fact) => fact.label === 'Tasks')?.value, '1 task');

    const agentFacts = workflowOverviewFacts(listed({
        name: 'Agent run', runner_type: 'agent', selected_agent: AGENT, m365_run_as_user_id: 'user-2',
        definition_version: 3, is_enabled: false,
    }));
    assert.equal(agentFacts.find((fact) => fact.label === 'Runner')?.value, 'Agent · Workspace reviewer');
    assert.deepEqual(agentFacts[2], { label: 'Microsoft 365 Run as', value: 'Account selected' });
    assert.equal(agentFacts.find((fact) => fact.label === 'Workflow enabled')?.value, 'Off');
    assert.ok(agentFacts.some((fact) => fact.label === 'Structured tasks'));

    const monitorFacts = workflowOverviewFacts(WORKFLOWS[4]);
    assert.equal(monitorFacts.find((fact) => fact.label === 'File Sync')?.value, '0 sources · checked for changes');
});

console.log(`\n${passed} workflow workbench logic checks passed`);
