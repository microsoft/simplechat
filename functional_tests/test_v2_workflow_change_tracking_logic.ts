// test_v2_workflow_change_tracking_logic.ts
// Behavioural checks for workflow editor change tracking: diff, attribution, revert, and assist.
//
// Version: 0.261.201
// Implemented in: 0.261.201
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
import type { WorkflowDefinition } from '../application/v2_ui/src/lib/workflowEditor';

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

runLibraryChecks();
runRevertChecks();
console.log(`\n${failures ? `${failures} FAILED` : 'all passed'}`);
if (failures) process.exitCode = 1;