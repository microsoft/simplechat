// test_v2_workflow_change_tracking_logic.ts
// Behavioural checks for workflow editor change tracking: diff, attribution, revert, and assist.
//
// Version: 0.261.203
// Implemented in: 0.261.203
//
// The V2 interface has no unit test runner, so this follows test_v2_chart_editor_logic.ts:
// bundled with the esbuild Vite already brings in, run under node by
// test_v2_workflow_change_tracking.py, and skipped when the front-end toolchain is not installed.
//
// The properties worth most here: a change is keyed by a stable ID, so a reorder is one change
// and not an edit to every task; attribution always agrees with the history, through undo, redo,
// coalescing and eviction; and a revert is a new, undoable entry that never discards later work.

import fixture from './fixtures/workflow_flow_authoring.json';
import {
    buildWorkflowKeyRevert,
    diffWorkflowChanges,
    nextWorkflowAttribution,
    parseWorkflowChangeKey,
    planWorkflowTurnRevert,
    sameWorkflowKeyValue,
    workflowChangeAuthors,
    workflowChangedKeys,
    workflowChangeKeyLabel,
    workflowChangeStamp,
    workflowKeyValue,
    workflowNodeKey,
    workflowRegionKey,
    workflowRunAsConsequence,
    workflowSaveNeedsConfirmation,
    workflowTaskKey,
    EMPTY_WORKFLOW_ATTRIBUTION,
    WORKFLOW_TASK_ORDER_KEY,
    type WorkflowAttribution,
} from '../application/v2_ui/src/lib/workflowChangeTracking';
import {
    ASSIST_FORBIDDEN_FIELDS,
    WORKFLOW_AUTHORED_FIELDS,
    WorkflowAuthoringSession,
} from '../application/v2_ui/src/components/workflows/WorkflowAuthoringHistory';
import { applyWorkflowEdit } from '../application/v2_ui/src/lib/workflowAuthoring';
import { WORKFLOW_ALERT_FIELDS } from '../application/v2_ui/src/lib/workflowAlerts';
import type { WorkflowDefinition, WorkflowEditorOptions } from '../application/v2_ui/src/lib/workflowEditor';

let failures = 0;
export function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail === undefined ? '' : JSON.stringify(detail, null, 1)?.slice(0, 2000));
    }
}
export function failureCount() {
    return failures;
}

type Row = Record<string, any>;
export function structured(): WorkflowDefinition {
    return structuredClone(fixture.initial) as unknown as WorkflowDefinition;
}

export function classic(count = 4): WorkflowDefinition {
    const tasks = Array.from({ length: count }, (_, index) => ({
        id: `t${index + 1}`, type: 'instructions', name: `Task ${index + 1}`, instructions: `Step ${index + 1}.`,
        order: index + 1, runner: { type: 'inherit' }, document_action: { type: 'none' }, reference_ids: [], inputs: [],
    }));
    return {
        id: 'classic-workflow', user_id: 'offline-owner', definition_version: 2, name: 'Classic', description: '',
        runner_type: 'model', trigger_type: 'interval', schedule: { unit: 'hours', value: 1 }, is_enabled: false,
        reference_inputs: [
            { id: 'r1', name: 'Policy', document_id: 'doc-1', scope_type: 'personal' },
            { id: 'r2', name: 'Guide', document_id: 'doc-2', scope_type: 'personal' },
        ],
        tasks,
    } as unknown as WorkflowDefinition;
}

function tasksOf(definition: WorkflowDefinition): Row[] {
    return (definition as Row).tasks as Row[];
}

function withTasks(definition: WorkflowDefinition, tasks: Row[]): WorkflowDefinition {
    return { ...definition, tasks: tasks.map((task, index) => ({ ...task, order: index + 1 })) } as WorkflowDefinition;
}

function rootNodes(definition: WorkflowDefinition): Row[] {
    return ((definition as Row).flow as Row).nodes as Row[];
}

function withRootNodes(definition: WorkflowDefinition, nodes: Row[]): WorkflowDefinition {
    return { ...definition, flow: { ...(definition as Row).flow, nodes } } as WorkflowDefinition;
}

function keys(definition: WorkflowDefinition, draft: WorkflowDefinition): string[] {
    return diffWorkflowChanges(definition, draft).changes.map((change) => change.key);
}

function stableIdDiffing() {
    const base = classic();
    const renamed = { ...base, name: 'Classic, renamed' } as WorkflowDefinition;
    const nameChange = diffWorkflowChanges(base, renamed).byKey.get('name');
    check('a name edit is one workflow field change', keys(base, renamed).join() === 'name', keys(base, renamed));
    check('the name change reads before and after as plain text',
        nameChange?.before === 'Classic' && nameChange.after === 'Classic, renamed' && nameChange.kind === 'field', nameChange);

    const rescheduled = { ...base, schedule: { unit: 'hours', value: 6 } } as WorkflowDefinition;
    check('a schedule edit is the schedule key', keys(base, rescheduled).join() === 'schedule', keys(base, rescheduled));
    const retriggered = { ...base, trigger_type: 'manual' } as WorkflowDefinition;
    check('the trigger and the schedule share one key', keys(base, retriggered).join() === 'schedule', keys(base, retriggered));

    const edited = withTasks(base, tasksOf(base).map((task) => task.id === 't2' ? { ...task, instructions: 'Changed.' } : task));
    check('a task edit is keyed by task ID and field', keys(base, edited).join() === workflowTaskKey('t2', 'instructions'), keys(base, edited));

    const reordered = withTasks(base, [tasksOf(base)[3], ...tasksOf(base).slice(0, 3)]);
    check('a reorder is one order change, not an edit to every task',
        keys(base, reordered).join() === WORKFLOW_TASK_ORDER_KEY, keys(base, reordered));
    const reorderChange = diffWorkflowChanges(base, reordered).byKey.get(WORKFLOW_TASK_ORDER_KEY);
    check('the order change lists the task names in order',
        reorderChange?.before === 'Task 1 → Task 2 → Task 3 → Task 4' && reorderChange.after === 'Task 4 → Task 1 → Task 2 → Task 3', reorderChange);

    const added = withTasks(base, [...tasksOf(base).slice(0, 2), { id: 't9', type: 'instructions', name: 'Inserted', instructions: 'New.' }, ...tasksOf(base).slice(2)]);
    const addedChanges = diffWorkflowChanges(base, added);
    check('an insertion is one added task, and the others did not move relative to each other',
        keys(base, added).join() === workflowTaskKey('t9'), keys(base, added));
    check('fields inside an added task point at the added task', addedChanges.added.get(workflowTaskKey('t9')) === workflowTaskKey('t9'));

    const removed = withTasks(base, tasksOf(base).filter((task) => task.id !== 't3'));
    const removal = diffWorkflowChanges(base, removed).byKey.get(workflowTaskKey('t3'));
    check('a removal is one removed task', keys(base, removed).join() === workflowTaskKey('t3'), keys(base, removed));
    check('a removed task remembers where it was', removal?.kind === 'removed' && removal.anchor?.afterId === 't2', removal);

    const renamedReference = { ...base, reference_inputs: [{ ...(base as Row).reference_inputs[0], name: 'Policy v2' }, (base as Row).reference_inputs[1]] } as WorkflowDefinition;
    check('a reference rename is keyed by reference ID', keys(base, renamedReference).join() === 'reference:r1:name', keys(base, renamedReference));

    const parsed = parseWorkflowChangeKey(workflowTaskKey('a:b%c', 'instructions'));
    check('IDs with separators survive a key round trip', parsed.scope === 'task' && 'id' in parsed && parsed.id === 'a:b%c' && parsed.field === 'instructions', parsed);
    check('the same definition has no changes', diffWorkflowChanges(base, base).changes.length === 0);
    check('an equal copy has no changes', diffWorkflowChanges(base, structuredClone(base)).changes.length === 0);
}

function structuredDiffing() {
    const base = structured();
    const nodes = rootNodes(base);
    const swapped = withRootNodes(base, [nodes[0], nodes[2], nodes[1], ...nodes.slice(3)]);
    check('a block move in the flow is one region order change',
        keys(base, swapped).join() === workflowRegionKey('root', 'order'), keys(base, swapped));

    const withoutChoice = withRootNodes(base, nodes.filter((node) => node.id !== 'choice'));
    const trimmed = { ...withoutChoice, tasks: tasksOf(base).filter((task) => task.id !== 'yes-task' && task.id !== 'no-task') } as WorkflowDefinition;
    const removed = diffWorkflowChanges(base, trimmed);
    const choice = removed.byKey.get(workflowNodeKey('choice'));
    check('removing a branch block is one removed block', removed.changes.filter((change) => change.kind === 'removed').length === 1, removed.changes.map((change) => change.key));
    check('the removed block carries the tasks inside it',
        choice?.kind === 'removed' && ['task:yes-task', 'task:no-task'].every((key) => choice.descendantKeys?.includes(key)), choice);
    check('the removed block remembers its region and earlier sibling', choice?.anchor?.regionId === 'root' && choice.anchor.afterId === 'seed-node', choice?.anchor);
    check('tasks inside the removed block map to it', removed.removed.get('task:yes-task') === workflowNodeKey('choice'));

    const renamedTask = { ...base, tasks: tasksOf(base).map((task) => task.id === 'yes-task' ? { ...task, instructions: 'Accept loudly.' } : task) } as WorkflowDefinition;
    const nested = diffWorkflowChanges(base, renamedTask).byKey.get(workflowTaskKey('yes-task', 'instructions'));
    check('a task inside a branch is keyed by its ID', Boolean(nested) && nested?.target.nodeId === 'yes-node', nested);

    const retuned = withRootNodes(base, nodes.map((node) => node.id === 'repeat-node' ? { ...node, max_iterations: 30 } : node));
    check('a block setting is keyed by node ID and field', keys(base, retuned).join() === workflowNodeKey('repeat-node', 'max_iterations'), keys(base, retuned));
    check('the definition field for a block setting is the flow', workflowChangeKeyLabel(workflowNodeKey('repeat-node', 'max_iterations'), base).length > 0);
}

function attributionAndSave() {
    const base = classic();
    const ai = workflowChangeStamp('ai', 'turn-1');
    const user = workflowChangeStamp('user');
    const renamed = { ...base, name: 'AI name' } as WorkflowDefinition;
    let attribution: WorkflowAttribution = nextWorkflowAttribution(EMPTY_WORKFLOW_ATTRIBUTION, base, renamed, base, () => ai);
    check('an assist edit is attributed to the turn', attribution.get('name')?.author === 'ai' && attribution.get('name')?.turnId === 'turn-1', [...attribution]);
    const changes = diffWorkflowChanges(base, renamed).changes;
    check('an AI change needs the Confirm and save step', workflowSaveNeedsConfirmation(changes, attribution));
    const described = { ...renamed, description: 'Mine' } as WorkflowDefinition;
    attribution = nextWorkflowAttribution(attribution, renamed, described, base, () => user);
    check('a later user edit keeps the earlier AI author on its own key', attribution.get('name')?.author === 'ai' && attribution.get('description')?.author === 'user');
    const back = nextWorkflowAttribution(attribution, described, { ...described, name: 'Classic' } as WorkflowDefinition, base, () => user);
    check('a key back at its baseline value loses its author', !back.has('name'));
    const userOnly = nextWorkflowAttribution(EMPTY_WORKFLOW_ATTRIBUTION, base, described, base, () => user);
    check('user-only edits save in one click', !workflowSaveNeedsConfirmation(diffWorkflowChanges(base, described).changes, userOnly));
    const same = nextWorkflowAttribution(userOnly, described, described, base, () => ai);
    check('a no-op keeps the same attribution instance', same === userOnly);

    const removed = withTasks(base, tasksOf(base).filter((task) => task.id !== 't2'));
    const removal = nextWorkflowAttribution(EMPTY_WORKFLOW_ATTRIBUTION, base, removed, base, () => ai);
    const change = diffWorkflowChanges(base, removed).byKey.get('task:t2');
    check('a removal by an assist turn is attributed to it', change !== undefined && workflowChangeAuthors(change, removal)[0]?.author === 'ai', [...removal]);

    const runAs = { ...base, m365_run_as_user_id: 'owner-oid' } as WorkflowDefinition;
    const runAsDraft = { ...runAs, name: 'Renamed' } as WorkflowDefinition;
    check('a name change does not re-approve Run as', !workflowRunAsConsequence(runAs, runAsDraft, diffWorkflowChanges(runAs, runAsDraft).changes));
    const runAsTasks = withTasks(runAs, tasksOf(runAs).map((task) => task.id === 't1' ? { ...task, instructions: 'x' } : task));
    check('a task change re-approves Run as', workflowRunAsConsequence(runAs, runAsTasks, diffWorkflowChanges(runAs, runAsTasks).changes));
    check('without Run as there is nothing to re-approve', !workflowRunAsConsequence(base, withTasks(base, tasksOf(base).slice(1)), diffWorkflowChanges(base, withTasks(base, tasksOf(base).slice(1))).changes));
    const rescheduled = { ...runAs, schedule: { unit: 'hours', value: 2 } } as WorkflowDefinition;
    check('a schedule change re-approves Run as', workflowRunAsConsequence(runAs, rescheduled, diffWorkflowChanges(runAs, rescheduled).changes));
    const alerted = { ...runAs, description: 'x' } as WorkflowDefinition;
    check('a description change does not re-approve Run as', !workflowRunAsConsequence(runAs, alerted, diffWorkflowChanges(runAs, alerted).changes));
}

export function runLibraryChecks() {
    stableIdDiffing();
    structuredDiffing();
    attributionAndSave();
}

function reverts() {
    const base = classic();
    const renamed = { ...base, name: 'Other', description: 'Kept' } as WorkflowDefinition;
    const nameBack = buildWorkflowKeyRevert(renamed, base, ['name']).candidate;
    check('revertKey takes one field back and leaves the rest', nameBack.name === 'Classic' && nameBack.description === 'Kept', nameBack);

    const removed = withTasks(base, tasksOf(base).filter((task) => task.id !== 't3'));
    const moved = withTasks(removed, [tasksOf(removed)[2], ...tasksOf(removed).slice(0, 2)]);
    const restored = buildWorkflowKeyRevert(moved, base, ['task:t3']).candidate;
    check('a restored task goes back after its previous surviving sibling',
        tasksOf(restored).map((task) => task.id).join() === 't4,t1,t2,t3', tasksOf(restored).map((task) => task.id));
    check('restored classic tasks are renumbered', tasksOf(restored).every((task, index) => task.order === index + 1));
    check('a restore leaves the order change for the user', keys(base, restored).join() === WORKFLOW_TASK_ORDER_KEY, keys(base, restored));
    const firstRemoved = withTasks(base, tasksOf(base).slice(1));
    const firstBack = buildWorkflowKeyRevert(firstRemoved, base, ['task:t1']).candidate;
    check('a restored first task goes back to the start', tasksOf(firstBack)[0].id === 't1' && keys(base, firstBack).length === 0, keys(base, firstBack));

    const added = withTasks(base, [...tasksOf(base), { id: 't9', type: 'instructions', name: 'New', instructions: '' }]);
    const addedGone = buildWorkflowKeyRevert(added, base, ['task:t9']).candidate;
    check('reverting an added task removes it', keys(base, addedGone).length === 0, keys(base, addedGone));

    const reordered = withTasks(added, [tasksOf(added)[4], tasksOf(added)[3], ...tasksOf(added).slice(0, 3)]);
    const orderBack = buildWorkflowKeyRevert(reordered, base, [WORKFLOW_TASK_ORDER_KEY]).candidate;
    check('reverting the order keeps an added task in its slot',
        tasksOf(orderBack).map((task) => task.id).join() === 't9,t1,t2,t3,t4', tasksOf(orderBack).map((task) => task.id));

    const edited = withTasks(base, tasksOf(base).map((task) => task.id === 't2' ? { ...task, instructions: 'Changed.', name: 'Renamed' } : task));
    const fieldBack = buildWorkflowKeyRevert(edited, base, [workflowTaskKey('t2', 'instructions')]).candidate;
    check('a task field reverts alone', keys(base, fieldBack).join() === workflowTaskKey('t2', 'name'), keys(base, fieldBack));
    check('a task field revert copies nothing else', tasksOf(fieldBack)[0] === tasksOf(edited)[0]);

    const flow = structured();
    const nodes = rootNodes(flow);
    const trimmed = {
        ...withRootNodes(flow, nodes.filter((node) => node.id !== 'choice')),
        tasks: tasksOf(flow).filter((task) => task.id !== 'yes-task' && task.id !== 'no-task'),
    } as WorkflowDefinition;
    const blockBack = buildWorkflowKeyRevert(trimmed, flow, [workflowNodeKey('choice')]);
    check('a removed block comes back with its tasks, where it was',
        blockBack.failed.size === 0 && keys(flow, blockBack.candidate).length === 0, [...blockBack.failed, keys(flow, blockBack.candidate)]);

    const nestedGone = { ...flow, tasks: tasksOf(flow).filter((task) => task.id !== 'yes-task') } as WorkflowDefinition;
    const noYesNode = withRootNodes(nestedGone, nodes.map((node) => node.id === 'choice'
        ? { ...node, then: { ...node.then, nodes: [] } } : node));
    const nestedBack = buildWorkflowKeyRevert(noYesNode, flow, ['task:yes-task']);
    check('a task removed from a branch goes back into the branch',
        nestedBack.failed.size === 0 && keys(flow, nestedBack.candidate).length === 0, [...nestedBack.failed, keys(flow, nestedBack.candidate)]);

    const outer = buildWorkflowKeyRevert(trimmed, flow, ['task:yes-task']);
    check('a task inside a removed block asks for the block first', outer.failed.has('task:yes-task'), [...outer.failed]);

    const conversion = { ...base, definition_version: 3 } as WorkflowDefinition;
    const format = buildWorkflowKeyRevert(conversion, base, ['definition_version']);
    check('the format cannot be reverted on its own', format.failed.has('definition_version') && format.candidate === conversion);

    check('an unchanged revert returns the same definition', buildWorkflowKeyRevert(base, base, ['name', 'task:t1']).candidate === base);
}

function turnPlans() {
    const base = classic();
    const turn1 = { ...base, name: 'AI name', description: 'AI description' } as WorkflowDefinition;
    const turn2 = withTasks(turn1, tasksOf(turn1).map((task) => task.id === 't1' ? { ...task, instructions: 'AI step.' } : task));
    const later = { ...turn2, description: 'User rewrote it' } as WorkflowDefinition;
    const entries = [{ before: base, after: turn1 }, { before: turn1, after: turn2 }];
    const plan = planWorkflowTurnRevert(later, entries);
    check('a turn revert keeps keys changed later', plan.skipped.join() === 'description', plan.skipped);
    check('a turn revert reverts the keys it still owns',
        [...plan.keys].sort().join() === ['name', workflowTaskKey('t1', 'instructions')].sort().join(), plan.keys);
    const result = buildWorkflowKeyRevert(later, (key) => entries[plan.entryFor(key)].before, plan.keys).candidate;
    check('the turn revert candidate leaves later work alone',
        result.name === 'Classic' && result.description === 'User rewrote it' && tasksOf(result)[0].instructions === 'Step 1.', result);

    const undone = { ...later, name: 'Classic' } as WorkflowDefinition;
    const secondPlan = planWorkflowTurnRevert(undone, entries);
    check('a key already back before the turn is neither reverted nor skipped',
        !secondPlan.keys.includes('name') && !secondPlan.skipped.includes('name'), secondPlan);

    const addedByTurn = withTasks(base, [...tasksOf(base), { id: 't9', type: 'instructions', name: 'AI task', instructions: 'Do.' }]);
    const editedLater = withTasks(addedByTurn, tasksOf(addedByTurn).map((task) => task.id === 't9' ? { ...task, instructions: 'Mine.' } : task));
    const itemPlan = planWorkflowTurnRevert(editedLater, [{ before: base, after: addedByTurn }]);
    check('an added task edited later is skipped as a whole', itemPlan.skipped.join() === 'task:t9' && itemPlan.keys.length === 0, itemPlan);
    const itemPlan2 = planWorkflowTurnRevert(addedByTurn, [{ before: base, after: addedByTurn }]);
    check('an untouched added task reverts as one item', itemPlan2.keys.join() === 'task:t9', itemPlan2);

    check('an equal value is equal for its key', sameWorkflowKeyValue('name', workflowKeyValue(base, 'name'), 'Classic'));
    check('changed keys are available without the summaries', workflowChangedKeys(base, turn1).size === 2);
}

export function runRevertChecks() {
    reverts();
    turnPlans();
}

// ---------------------------------------------------------------------------------------------
// Session: assist, reverts, restores, and attribution through the real history
// ---------------------------------------------------------------------------------------------

interface SessionState {
    session: WorkflowAuthoringSession;
    errors: string[];
}

const fixtureOptions = () => structuredClone(fixture.options) as unknown as WorkflowEditorOptions;

function openSession(draft: WorkflowDefinition = structured(), readOnly = false): SessionState {
    const session = new WorkflowAuthoringSession(draft);
    const errors: string[] = [];
    session.configure({
        options: fixtureOptions(), readOnly, saving: false, commandPending: false, selectionId: 'seed-node',
        onError: (message: string) => { if (message) errors.push(message); },
        onRestore: () => {},
        onRollback: () => {},
    });
    return { session, errors };
}

const snapshotOf = (state: SessionState) => state.session.getSnapshot();
const authorOf = (state: SessionState, key: string) => snapshotOf(state).attribution.get(key);
const unsavedOf = (state: SessionState) => diffWorkflowChanges(snapshotOf(state).baseline, snapshotOf(state).draft);
const lastStep = (state: SessionState) => snapshotOf(state).steps.at(-1);

function taskOf(definition: WorkflowDefinition, id: string): Row | undefined {
    return tasksOf(definition).find((task) => task.id === id);
}

function withTask(definition: WorkflowDefinition, id: string, patch: Row): WorkflowDefinition {
    return withTasks(definition, tasksOf(definition).map((task) => task.id === id ? { ...task, ...patch } : task));
}

function rename(state: SessionState, name: string, group?: string) {
    return state.session.changeDraft((current) => ({ ...current, name }), { label: 'Workflow name', ...(group ? { group } : {}) });
}

function assistChecks() {
    check('assist can never change enablement or Run as',
        ASSIST_FORBIDDEN_FIELDS.includes('is_enabled') && ASSIST_FORBIDDEN_FIELDS.includes('m365_run_as_user_id'));
    check('the editor authors File Sync and every alert field',
        WORKFLOW_AUTHORED_FIELDS.includes('file_sync') && WORKFLOW_ALERT_FIELDS.every((field) => WORKFLOW_AUTHORED_FIELDS.includes(field)));

    const state = openSession();
    const { session } = state;
    const original = session.draft;
    const candidate = withTask({ ...original, name: 'AI name' }, 'seed-task', { instructions: 'AI instructions.' });
    const applied = session.applyAssist(candidate, { turnId: 'turn-1', label: 'Tighten the seed task' });
    const step = snapshotOf(state).steps[0];
    check('an assist candidate applies as one history entry', applied.status === 'applied' && snapshotOf(state).steps.length === 1, applied);
    check('the assist entry carries its origin, turn, and label',
        step?.origin === 'ai' && step.turnId === 'turn-1' && step.label === 'Tighten the seed task' && snapshotOf(state).undoLabel === step.label, step);
    check('assist-changed keys are AI-authored for the turn',
        authorOf(state, 'name')?.author === 'ai' && authorOf(state, workflowTaskKey('seed-task', 'instructions'))?.turnId === 'turn-1',
        [...snapshotOf(state).attribution]);
    check('unsaved AI changes make Save ask first', workflowSaveNeedsConfirmation(unsavedOf(state).changes, snapshotOf(state).attribution));

    const current = session.draft;
    const rejected: [string, WorkflowDefinition][] = [
        ...ASSIST_FORBIDDEN_FIELDS.filter((field) => field !== 'definition_version')
            .map((field): [string, WorkflowDefinition] => [field, { ...current, [field]: `changed-${field}` } as WorkflowDefinition]),
        ['definition_version', { ...current, definition_version: 2 } as WorkflowDefinition],
        ['revision', { ...current, revision: 'other' } as unknown as WorkflowDefinition],
        ['approval', withTask(current, 'seed-task', { approval: { required: true, message: 'Check it.' } })],
        ['root', { ...current, flow: { ...(current.flow as unknown as Row), id: 'other-root' } } as unknown as WorkflowDefinition],
    ];
    for (const [field, value] of rejected) {
        const outcome = session.applyAssist(value, { turnId: 'turn-2', label: 'Bad' });
        check(`an assist candidate cannot change ${field}`, outcome.status === 'rejected' && outcome.message.includes(field) &&
            session.draft === current && snapshotOf(state).steps.length === 1, outcome);
    }
    const badTurns = ['', 'x'.repeat(257)].map((turnId) => session.applyAssist({ ...current, name: 'Other' }, { turnId, label: 'x' }).status);
    check('an assist needs a valid turn ID', badTurns.every((status) => status === 'rejected') && session.draft === current, badTurns);

    const large = openSession();
    (large.session as unknown as { history: { record: () => unknown } }).history.record = () => ({ status: 'overflow' });
    const proposal = large.session.applyAssist({ ...large.session.draft, name: 'Huge' }, { turnId: 'turn-9', label: 'Huge edit' });
    check('an assist over the history budget asks before clearing history', proposal.status === 'confirmation_required' &&
        snapshotOf(large).pending?.kind === 'overflow' && large.session.draft.name !== 'Huge', proposal);
    large.session.confirm();
    check('confirming the overflow applies the assist, still AI-attributed', large.session.draft.name === 'Huge' &&
        authorOf(large, 'name')?.author === 'ai' && snapshotOf(large).trimmed && snapshotOf(large).steps.length === 0);

    const impact = openSession();
    const start = impact.session.draft;
    let removal: { nodeId: string; workflow: WorkflowDefinition } | null = null;
    for (const node of rootNodes(start)) {
        const first = applyWorkflowEdit(start, { type: 'remove', nodeId: node.id }, fixtureOptions(), false);
        const confirmed = first.status === 'confirmation_required'
            ? applyWorkflowEdit(start, { type: 'remove', nodeId: node.id }, fixtureOptions(), true) : null;
        if (confirmed?.status === 'applied') {
            removal = { nodeId: node.id, workflow: confirmed.workflow };
            break;
        }
    }
    check('the fixture has a block whose removal affects outside references', removal !== null);
    if (removal) {
        const outcome = impact.session.applyAssist(removal.workflow, { turnId: 'turn-4', label: 'Remove a block' });
        check('an assist that breaks references asks first, like Undo', outcome.status === 'confirmation_required' &&
            snapshotOf(impact).pending?.kind === 'change' && impact.session.draft === start, outcome);
        impact.session.confirm();
        const removedNode = rootNodes(start).find((node) => node.id === removal?.nodeId);
        const removedKey = removedNode?.kind === 'task' ? workflowTaskKey(String(removedNode.task_id)) : workflowNodeKey(removal.nodeId);
        check('confirming applies the assist removal as an AI change', impact.session.draft === removal.workflow &&
            authorOf(impact, removedKey)?.turnId === 'turn-4', [removedKey, ...snapshotOf(impact).attribution]);
    }
}

function turnChecks() {
    const state = openSession();
    const { session } = state;
    const original = session.draft;
    const instructions = workflowTaskKey('seed-task', 'instructions');
    session.applyAssist(withTask({ ...original, name: 'AI name', description: 'AI description' }, 'seed-task', { instructions: 'AI step.' }),
        { turnId: 'turn-1', label: 'Assist' });
    session.changeDraft((current) => ({ ...current, description: 'Mine' }), { label: 'Description' });
    const result = session.revertTurn('turn-1');
    check('a turn revert reports reverted and skipped counts',
        result.status === 'applied' && result.reverted === 2 && result.skipped === 1, result);
    check('each skipped key says why', result.status === 'applied' && result.skippedKeys[0]?.key === 'description' &&
        result.skippedKeys[0]?.reason === 'Changed after this turn.' && result.skippedKeys[0]?.label === 'Description', result);
    check('the turn revert keeps later work and reverts the rest', session.draft.name === original.name &&
        session.draft.description === 'Mine' && taskOf(session.draft, 'seed-task')?.instructions === taskOf(original, 'seed-task')?.instructions);
    check('the turn revert is a new, undoable restore entry', snapshotOf(state).steps.length === 3 &&
        lastStep(state)?.origin === 'restore' && lastStep(state)?.turnId === 'turn-1' && snapshotOf(state).undoLabel === 'Revert AI assist turn');
    check('reverted keys lose their author; later work keeps its own',
        !snapshotOf(state).attribution.has('name') && !snapshotOf(state).attribution.has(instructions) &&
        authorOf(state, 'description')?.author === 'user', [...snapshotOf(state).attribution]);
    check('reverting the same turn again has nothing to do', session.revertTurn('turn-1').status === 'noop');
    check('an unknown turn is unavailable', session.revertTurn('turn-x').status === 'unavailable');
    session.request('undo');
    check('undoing the turn revert brings the AI changes back, AI-attributed',
        session.draft.name === 'AI name' && authorOf(state, 'name')?.turnId === 'turn-1');
    session.request('undo');
    session.request('undo');
    check('a turn whose entries are all undone has nothing to revert', session.revertTurn('turn-1').status === 'noop');
}

function revertChangeChecks() {
    const state = openSession();
    const { session } = state;
    const original = session.draft;
    session.changeDraft((current) => ({ ...current, description: 'Edited' }), { label: 'Description' });
    const result = session.revertChange(['description']);
    check('Revert applies as one new restore entry', result.status === 'applied' && snapshotOf(state).steps.length === 2 &&
        lastStep(state)?.origin === 'restore' && lastStep(state)?.label === 'Revert Description', lastStep(state));
    check('the reverted key is back at its opened value with no author',
        session.draft.description === original.description && !snapshotOf(state).attribution.has('description'));
    session.request('undo');
    check('undoing a revert brings the edit and its author back',
        session.draft.description === 'Edited' && authorOf(state, 'description')?.author === 'user');
    session.request('redo');
    check('redoing the revert clears them again', session.draft.description === original.description && unsavedOf(state).changes.length === 0);

    const removal = applyWorkflowEdit(session.draft, { type: 'remove', nodeId: 'report-node' }, fixtureOptions(), true);
    if (removal.status === 'applied') session.changeDraft(removal.workflow, { label: 'Remove block', targetId: 'report-node' });
    // A task block and its task are one item, keyed by the task.
    const removed = unsavedOf(state).byKey.get(workflowTaskKey('report-task'));
    check('a removed task block is one removed change anchored after its sibling', removed?.kind === 'removed' &&
        removed.anchor?.regionId === 'root' && removed.anchor.afterId === 'constructor', removed ?? [...unsavedOf(state).byKey.keys()]);
    const restored = session.revertChange([workflowTaskKey('report-task')]);
    if (restored.status === 'confirmation_required') session.confirm();
    check('Restore puts a removed block and its task back where they were', restored.status !== 'rejected' &&
        rootNodes(session.draft).map((node) => node.id).join() === rootNodes(original).map((node) => node.id).join() &&
        JSON.stringify(taskOf(session.draft, 'report-task')) === JSON.stringify(taskOf(original, 'report-task')), restored);
    check('restoring a removed block is labelled as a restore', lastStep(state)?.label.startsWith('Restore ') === true, lastStep(state));
    check('an unchanged key has nothing to revert', session.revertChange(['limits']).status === 'noop');
}

function restoreToChecks() {
    const state = openSession();
    const { session } = state;
    const original = session.draft;
    rename(state, 'One');
    session.changeDraft((current) => ({ ...current, description: 'Two' }), { label: 'Description two' });
    session.applyAssist({ ...session.draft, name: 'Three' }, { turnId: 'turn-r', label: 'Name three' });
    const [first, , third] = snapshotOf(state).steps;
    const result = session.restoreTo(first.id);
    check('Restore to here applies that version as a new entry', result.status === 'applied' && session.draft.name === 'One' &&
        session.draft.description === original.description && snapshotOf(state).steps.length === 4, result);
    check('Restore to here keeps every later step in history',
        snapshotOf(state).steps.slice(0, 3).map((step) => step.label).join() === 'Workflow name,Description two,Name three');
    check('restored keys keep the author they had in that version', authorOf(state, 'name')?.author === 'user');
    session.restoreTo(third.id);
    check('restoring an AI version keeps it AI-authored', session.draft.name === 'Three' && authorOf(state, 'name')?.turnId === 'turn-r');
    session.restoreTo('opened');
    check('restoring the opened version leaves no unsaved change',
        unsavedOf(state).changes.length === 0 && snapshotOf(state).attribution.size === 0 && lastStep(state)?.label === 'Restore to the opened version');
    session.request('undo');
    const undone = snapshotOf(state).steps.at(-1);
    check('Restore to here is undoable', session.draft.name === 'Three' && undone?.applied === false);
    check('an undone step cannot be restored to', undone !== undefined && session.restoreTo(undone.id).status === 'rejected');
    check('a step no longer retained cannot be restored to', session.restoreTo(9999).status === 'rejected');
}

function attributionChecks() {
    const state = openSession();
    const { session } = state;
    for (const name of ['a', 'ab', 'abc']) rename(state, name, 'workflow.name');
    check('coalesced typing is one user entry', snapshotOf(state).steps.length === 1 && authorOf(state, 'name')?.author === 'user');
    session.applyAssist({ ...session.draft, name: 'AI' }, { turnId: 'turn-a', label: 'Rename' });
    check('an assist never coalesces into typing', snapshotOf(state).steps.length === 2 && authorOf(state, 'name')?.author === 'ai');
    rename(state, 'AI!', 'workflow.name');
    check('typing after an assist starts a new user entry', snapshotOf(state).steps.length === 3 && authorOf(state, 'name')?.author === 'user');
    session.request('undo');
    check('undo restores the AI author', session.draft.name === 'AI' && authorOf(state, 'name')?.turnId === 'turn-a');
    session.request('undo');
    check('undo restores the earlier user author', session.draft.name === 'abc' && authorOf(state, 'name')?.origin === 'user');
    session.request('redo');
    session.request('redo');
    check('redo restores the later authors', session.draft.name === 'AI!' && authorOf(state, 'name')?.author === 'user');

    const netZero = openSession();
    const openedName = netZero.session.draft.name;
    rename(netZero, 'temporary', 'workflow.name');
    rename(netZero, openedName, 'workflow.name');
    check('typing back to the opened value leaves no entry and no author',
        snapshotOf(netZero).steps.length === 0 && snapshotOf(netZero).attribution.size === 0, snapshotOf(netZero).steps);

    const evicting = openSession();
    evicting.session.changeDraft((current) => ({ ...current, description: 'First' }), { label: 'Description' });
    for (let index = 0; index <= 100; index++) {
        evicting.session.applyAssist({ ...evicting.session.draft, name: `AI ${index}` }, { turnId: `turn-${index}`, label: `Rename ${index}` });
    }
    const steps = snapshotOf(evicting).steps;
    check('eviction drops the oldest steps and marks history trimmed',
        steps.length === 100 && snapshotOf(evicting).trimmed && steps[0].label === 'Rename 1', steps.slice(0, 2));
    check('eviction keeps the authors of evicted steps', authorOf(evicting, 'description')?.author === 'user' &&
        authorOf(evicting, 'name')?.turnId === 'turn-100');
    check('a turn whose entries were evicted is unavailable', evicting.session.revertTurn('turn-0').status === 'unavailable');
    check('a turn whose keys changed later reverts nothing', evicting.session.revertTurn('turn-1').status === 'noop');
    while (snapshotOf(evicting).undoLabel) evicting.session.request('undo');
    check('undoing to the oldest retained step keeps the evicted author', evicting.session.draft.name === 'AI 0' &&
        authorOf(evicting, 'description')?.author === 'user' && authorOf(evicting, 'name')?.turnId === 'turn-0');
}

function saveAndAccessChecks() {
    const state = openSession();
    const { session } = state;
    rename(state, 'Mine');
    check('Save stays one click for your own edits', !workflowSaveNeedsConfirmation(unsavedOf(state).changes, snapshotOf(state).attribution));
    session.applyAssist(withTask(session.draft, 'seed-task', { instructions: 'AI.' }), { turnId: 'turn-s', label: 'Assist' });
    check('unsaved AI changes need confirmation', workflowSaveNeedsConfirmation(unsavedOf(state).changes, snapshotOf(state).attribution));
    session.revertTurn('turn-s');
    check('reverting the AI turn makes Save one click again', !workflowSaveNeedsConfirmation(unsavedOf(state).changes, snapshotOf(state).attribution));
    session.saved(session.draft);
    const saved = snapshotOf(state);
    check('Save makes the saved version the new baseline', saved.baseline === session.draft && saved.attribution.size === 0 &&
        saved.steps.length === 0 && !saved.trimmed && unsavedOf(state).changes.length === 0, saved);

    const readOnly = openSession(structured(), true);
    const outcomes = [
        readOnly.session.applyAssist({ ...readOnly.session.draft, name: 'x' }, { turnId: 'turn-ro', label: 'x' }).status,
        readOnly.session.revertChange(['name']).status,
        readOnly.session.restoreTo('opened').status,
    ];
    check('a read-only editor refuses assist, revert, and restore', outcomes.every((status) => status === 'rejected') &&
        readOnly.session.getSnapshot().steps.length === 0, outcomes);

    const plain = openSession(classic());
    rename(plain, 'Classic renamed');
    check('classic drafts record history for tracking but offer no Undo', snapshotOf(plain).steps.length === 1 &&
        snapshotOf(plain).undoLabel === '' && authorOf(plain, 'name')?.author === 'user', snapshotOf(plain).steps);
    plain.session.changeDraft((current) => withTasks(current, tasksOf(current).filter((task) => task.id !== 't2')), { label: 'Remove task' });
    const removed = unsavedOf(plain).byKey.get(workflowTaskKey('t2'));
    check('a removed classic task is one revertable removed change', removed?.kind === 'removed' && removed.revertable, removed);
    const restored = plain.session.revertChange([workflowTaskKey('t2')]);
    check('Restore puts a classic task back in its place', restored.status === 'applied' &&
        tasksOf(plain.session.draft).map((task) => `${task.id}@${task.order}`).join() === 't1@1,t2@2,t3@3,t4@4', tasksOf(plain.session.draft));
    plain.session.applyAssist({ ...plain.session.draft, description: 'AI summary' }, { turnId: 'turn-c', label: 'Describe' });
    const turn = plain.session.revertTurn('turn-c');
    check('classic drafts take an assist and revert its turn', turn.status === 'applied' && turn.reverted === 1 &&
        plain.session.draft.description === '', turn);
}

function fieldDraftChecks() {
    const state = openSession();
    const { session } = state;
    const contract = taskOf(session.draft, 'seed-task')?.output_contract as Row;
    const schema = { ...contract.schema, properties: { ...contract.schema.properties, note: { type: 'string' } } };
    const key = workflowTaskKey('seed-task', 'output_contract');
    session.edit({ label: 'Output schema', group: 'schema' }, () => {
        session.fields.field(['task', 'seed-task'], ['output', 'schema'], JSON.stringify(contract.schema, null, 2))
            .setValue(JSON.stringify(schema, null, 2));
        session.changeDraft((current) => withTask(current, 'seed-task', { output_contract: { ...contract, schema } }));
    });
    check('typed schema text is held as a field draft',
        session.fields.capture().fields.size === 1 && unsavedOf(state).byKey.has(key), [...unsavedOf(state).byKey.keys()]);
    const reverted = session.revertChange([key]);
    // A contract change can move downstream selectors, so it confirms first, exactly as Undo would.
    const confirmed = reverted.status === 'confirmation_required' && snapshotOf(state).pending?.kind === 'change';
    if (confirmed) session.confirm();
    check('a field revert with downstream impact confirms first, like Undo', confirmed, reverted);
    check('reverting a field drops its typed text so the restored value shows', snapshotOf(state).pending === null &&
        session.fields.capture().fields.size === 0 &&
        JSON.stringify(taskOf(session.draft, 'seed-task')?.output_contract) === JSON.stringify(contract), snapshotOf(state).steps);
    session.request('undo');
    if (snapshotOf(state).pending) session.confirm();
    check('undoing the revert brings the typed text back',
        session.fields.capture().fields.size === 1 && unsavedOf(state).byKey.has(key), snapshotOf(state).steps);
}

// ---------------------------------------------------------------------------------------------
// Performance: a keystroke re-diffs only the task it changed
// ---------------------------------------------------------------------------------------------

const PERFORMANCE_TASKS = 100;
const PERFORMANCE_KEYSTROKES = 200;
// Loose, so a busy machine never fails it. The read count below is the exact check: a diff that
// compared every task on every keystroke fails it however fast the machine is.
const PERFORMANCE_MS_PER_KEYSTROKE = 25;

/** Type into one task, keeping every other task object, as the editor's setTaskAt does. */
function typeInto(definition: WorkflowDefinition, id: string, text: string): WorkflowDefinition {
    return {
        ...definition,
        tasks: tasksOf(definition).map((task) => task.id === id ? { ...task, instructions: `${task.instructions}${text}` } : task),
    } as WorkflowDefinition;
}

function performanceChecks() {
    // Every task but the one typed into counts reads of anything but its ID. A read means the
    // diff or the attribution compared a task that did not change.
    const reads = new Map<string, number>();
    const watched = tasksOf(classic(PERFORMANCE_TASKS)).map((task) => task.id === 't50' ? task : new Proxy(task, {
        get(target, property, receiver) {
            if (property !== 'id') reads.set(target.id, (reads.get(target.id) ?? 0) + 1);
            return Reflect.get(target, property, receiver);
        },
    }));
    const baseline = { ...classic(PERFORMANCE_TASKS), tasks: watched } as WorkflowDefinition;
    const stamp = workflowChangeStamp('user');
    const key = workflowTaskKey('t50', 'instructions');
    let draft = baseline;
    let attribution: WorkflowAttribution = EMPTY_WORKFLOW_ATTRIBUTION;
    let changes = diffWorkflowChanges(baseline, draft);
    for (let index = 0; index < PERFORMANCE_KEYSTROKES; index += 1) {
        const next = typeInto(draft, 't50', 'x');
        attribution = nextWorkflowAttribution(attribution, draft, next, baseline, () => stamp);
        changes = diffWorkflowChanges(baseline, next);
        draft = next;
    }
    check(`typing into one of ${PERFORMANCE_TASKS} tasks is one change`,
        changes.changes.map((change) => change.key).join() === key, changes.changes.map((change) => change.key));
    check('a keystroke never compares the tasks it did not change', reads.size === 0, [...reads]);
    void (watched[0] as Row).name;
    check('the read counter sees a read of a watched task', reads.get('t1') === 1, [...reads]);
    check('the diff is memoized per baseline and draft', diffWorkflowChanges(baseline, draft) === changes);
    check('typing attributes only the edited field', attribution.size === 1 && attribution.get(key)?.author === 'user', [...attribution]);

    // The same typing through the real session: history, coalescing, attribution, and the diff the panel reads.
    const state = openSession(classic(PERFORMANCE_TASKS));
    const started = performance.now();
    for (let index = 0; index < PERFORMANCE_KEYSTROKES; index += 1) {
        state.session.changeDraft((current) => typeInto(current, 't50', 'x'), { label: 'Task instructions', group: 'task.t50.instructions' });
        diffWorkflowChanges(snapshotOf(state).baseline, snapshotOf(state).draft);
    }
    const perKeystroke = (performance.now() - started) / PERFORMANCE_KEYSTROKES;
    console.log(`      (${perKeystroke.toFixed(2)} ms per keystroke through the session with ${PERFORMANCE_TASKS} tasks)`);
    check('typing through the session is one coalesced step with one change',
        snapshotOf(state).steps.length === 1 && unsavedOf(state).changes.map((change) => change.key).join() === key, snapshotOf(state).steps);
    check(`a keystroke with ${PERFORMANCE_TASKS} tasks takes under ${PERFORMANCE_MS_PER_KEYSTROKE} ms`,
        perKeystroke < PERFORMANCE_MS_PER_KEYSTROKE, perKeystroke);
}

export function runPerformanceChecks() {
    performanceChecks();
}

export function runSessionChecks() {
    assistChecks();
    turnChecks();
    revertChangeChecks();
    restoreToChecks();
    attributionChecks();
    saveAndAccessChecks();
    fieldDraftChecks();
}

runLibraryChecks();
runRevertChecks();
runSessionChecks();
runPerformanceChecks();
console.log(`\n${failures ? `${failures} FAILED` : 'all passed'}`);
if (failures) process.exitCode = 1;