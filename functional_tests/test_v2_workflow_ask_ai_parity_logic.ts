// test_v2_workflow_ask_ai_parity_logic.ts
// The Ask AI tab's half of a round trip through the AI workflow assistant.
//
// Version: 0.261.213
// Implemented in: 0.261.213
//
// test_v2_workflow_ask_ai_parity.py bundles this with esbuild and runs it under node twice, each
// time with the JSON file WORKFLOW_ASK_AI_PARITY_FIXTURE names:
//
// * Phase "requests" builds each case's request with the tab's real buildWorkflowAssistRequest, from
//   the draft the editor holds, the # documents as the picker makes them and a thread history, and
//   prints the exact text the browser POSTs. The Python side parses that text with the assistant's
//   own checks and answers it with a scripted model.
// * Phase "responses" replays each answer as the tab does: parseWorkflowAssistResponse reads it,
//   rebaseAssistCandidate lays the candidate over the live draft, the editor's own diff must find
//   exactly the changes, Jump to targets and wording the server reported, and applyAssist applies it.

import { readFileSync } from 'node:fs';
import { PERSONAL_SCOPE, documentContextItem, groupScope, type ContextItem } from '../application/v2_ui/src/lib/chatContext';
import type { WorkspaceDocument, WorkspaceRef } from '../application/v2_ui/src/lib/types';
import {
    buildWorkflowAssistRequest,
    jsonEquivalent,
    parseWorkflowAssistResponse,
    rebaseAssistCandidate,
    verifyAssistChanges,
    workflowAssistChangeSummary,
    workflowAssistReplay,
    workflowAssistTurnLabel,
    type WorkflowAssistHistoryView,
    type WorkflowAssistReplayExchange,
    type WorkflowAssistTurnRecord,
    type WorkflowAssistVerifiedChange,
} from '../application/v2_ui/src/lib/workflowAssist';
import { WorkflowAuthoringSession, workflowAssistViolation } from '../application/v2_ui/src/components/workflows/WorkflowAuthoringHistory';
import { isWorkflowHistoryTurnId } from '../application/v2_ui/src/lib/workflowAuthoringHistory';
import { diffWorkflowChanges } from '../application/v2_ui/src/lib/workflowChangeTracking';
import { flowTaskNodeId } from '../application/v2_ui/src/lib/workflowFlow';
import {
    newWorkflowDefinition,
    normalizeWorkflowDefinition,
    workflowScheduleTimezones,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowScope,
} from '../application/v2_ui/src/lib/workflowEditor';

type Row = Record<string, any>;

interface ReferenceSpec {
    kind: string;
    id: string;
    label: string;
    scope: { kind: string; id?: string; name?: string };
}

interface ParityCase {
    name: string;
    /** Where the editor's draft comes from: a saved workflow, a chat proposal, a given draft, or New workflow. */
    live: 'stored' | 'proposal' | 'draft' | 'new';
    stored: Row | null;
    source: Row | null;
    instruction: string;
    references: ReferenceSpec[];
    /** The task Ask AI about this task scoped the turn to, or null. */
    focus_task: string | null;
    replay: boolean;
    submission_id: string;
    request_text?: string;
    response?: Row;
}

interface ReplaySpec {
    done: string[];
    replies: string[];
    failed: string;
    cancelled: string;
}

interface ParityFixture {
    phase: 'requests' | 'responses';
    options: Row;
    time_zone: string;
    replay: ReplaySpec;
    cases: ParityCase[];
}

const PERSONAL: WorkflowScope = { type: 'personal' };
const EPOCH = 'epoch-current';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail === undefined ? '' : JSON.stringify(detail, null, 1)?.slice(0, 3000));
    }
}

/** One labelled line of JSON; U+0085, U+2028 and U+2029 are escaped so the line stays one line. */
function emit(label: string, value: unknown) {
    const line = JSON.stringify(value).replace(
        /[\u0085\u2028\u2029]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`,
    );
    console.log(`${label} ${line}`);
}

/** A JSON value with its object keys sorted, so two values compare as text. */
function canonical(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(canonical);
    if (value !== null && typeof value === 'object') {
        const record = value as Row;
        return Object.fromEntries(Object.keys(record).sort().map((key) => [key, canonical(record[key])]));
    }
    return value;
}

function sameJson(left: unknown, right: unknown): boolean {
    return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

/** The draft the editor holds for a case, and the baseline it opened. */
function editorDraft(item: ParityCase, sent?: Row): { baseline: WorkflowDefinition; live: WorkflowDefinition } {
    switch (item.live) {
        case 'stored': {
            // WorkflowsSection opens a saved workflow this way.
            const live = normalizeWorkflowDefinition(structuredClone(item.stored), PERSONAL);
            return { baseline: live, live };
        }
        case 'proposal': {
            // The proposal card's Edit opens the proposal's draft this way.
            const live = normalizeWorkflowDefinition(structuredClone(item.source), PERSONAL);
            return { baseline: live, live };
        }
        case 'draft': {
            const live = structuredClone(item.source) as WorkflowDefinition;
            const baseline = item.stored ? normalizeWorkflowDefinition(structuredClone(item.stored), PERSONAL) : live;
            return { baseline, live };
        }
        default: {
            // New workflow's task ids are random, so the replay reads back the draft that was sent.
            const live = sent ? structuredClone(sent) as WorkflowDefinition : newWorkflowDefinition(PERSONAL);
            return { baseline: live, live };
        }
    }
}

/** The # documents as the picker makes them. */
function contextItems(references: readonly ReferenceSpec[]): ContextItem[] {
    const items: ContextItem[] = [];
    for (const reference of references) {
        const scope = reference.scope.kind === 'personal' ? PERSONAL_SCOPE
            : groupScope({ id: reference.scope.id, name: reference.scope.name } as WorkspaceRef);
        const document = { id: reference.id, file_name: reference.label } as WorkspaceDocument;
        items.push(documentContextItem(document, scope, items, 'user', 'mention'));
    }
    return items;
}

/** The value Ask AI about this task sends: the task's id, or its flow block's id on a flow. */
function focusValue(draft: WorkflowDefinition, taskId: string | null): string | null {
    if (!taskId) return null;
    return draft.definition_version === 3 ? flowTaskNodeId(draft, taskId) || taskId : taskId;
}

/**
 * A thread history as the tab holds it: completed turns with a failed and a cancelled one among
 * them, the exchange being sent, and the records and history steps the replay reads.
 */
function replayHistory(spec: ReplaySpec, sending: ParityCase) {
    const exchanges: WorkflowAssistReplayExchange[] = [];
    const records: Record<string, WorkflowAssistTurnRecord> = {};
    const steps: { origin: string; turnId?: string; applied: boolean }[] = [];
    spec.done.forEach((text, index) => {
        const id = `replayed-turn-${index + 1}`;
        exchanges.push({ id, status: 'done', text, reply: spec.replies[index] });
        const changed = index % 3 !== 2;
        const change = { key: 'name', summary: 'Workflow: Name', reported: true } as unknown as WorkflowAssistVerifiedChange;
        records[id] = {
            threadKey: 'workflow:personal:parity', epoch: index === 1 ? 'epoch-earlier' : EPOCH, instruction: text,
            outcome: changed ? 'changed' : 'explained', reply: spec.replies[index],
            changes: changed ? [change] : [], warnings: [], contextDocuments: [],
            apply: changed ? 'applied' : 'none', undoSequence: 0,
        };
        if (changed && index % 2 === 0) steps.push({ origin: 'ai', turnId: id, applied: true });
        if (index === 4) {
            exchanges.push({ id: 'failed-turn', status: 'failed', text: spec.failed });
            exchanges.push({ id: 'cancelled-turn', status: 'cancelled', text: spec.cancelled });
        }
    });
    exchanges.push({ id: sending.submission_id, status: 'pending', text: sending.instruction });
    const view: WorkflowAssistHistoryView = { steps, attribution: new Map(), pending: null };
    return workflowAssistReplay(exchanges, (id) => records[id], view, EPOCH, sending.submission_id);
}

function buildRequests(fixture: ParityFixture) {
    const zones = workflowScheduleTimezones(fixture.options as WorkflowEditorOptions);
    return fixture.cases.map((item) => {
        const { baseline, live } = editorDraft(item);
        try {
            const request = buildWorkflowAssistRequest({
                submissionId: item.submission_id,
                instruction: item.instruction,
                baseline,
                draft: live,
                contextItems: contextItems(item.references),
                conversation: item.replay ? replayHistory(fixture.replay, item) : [],
                focus: focusValue(live, item.focus_task),
                timeZone: fixture.time_zone,
                timeZones: zones,
            });
            // postWorkflowAssist sends exactly this text.
            return { name: item.name, text: JSON.stringify(request) };
        } catch (problem) {
            return { name: item.name, refused: problem instanceof Error ? problem.message : String(problem) };
        }
    });
}

function openSession(draft: WorkflowDefinition, options: Row) {
    const session = new WorkflowAuthoringSession(draft);
    const errors: string[] = [];
    session.configure({
        options: structuredClone(options) as unknown as WorkflowEditorOptions,
        readOnly: false, saving: false, commandPending: false, selectionId: null,
        onError: (message: string) => { if (message) errors.push(message); },
        onRestore: () => {},
        onRollback: () => {},
    });
    return { session, errors };
}

function serverDiff(changes: readonly Row[]) {
    return changes.map((change) => ({
        key: change.key, kind: change.kind, label: change.label, owner_label: change.owner_label,
        focus_key: change.target?.focus_key, node_id: change.target?.node_id ?? null,
    }));
}

function replayResponse(item: ParityCase, options: Row) {
    const name = item.name;
    const response = item.response as Row;
    const sent = JSON.parse(item.request_text as string) as Row;
    const { live } = editorDraft(item, sent.draft);
    check(`${name}: the live draft is the draft the tab sent`, jsonEquivalent(live, sent.draft));

    const parsed = parseWorkflowAssistResponse(structuredClone(response), item.submission_id);
    check(`${name}: the tab reads the assistant's answer`, parsed !== null && parsed.outcome === response.outcome,
        { outcome: response.outcome, parsed: parsed?.outcome ?? null });
    check(`${name}: the answer's warnings and documents read as context reach the card`,
        parsed !== null
        && sameJson(parsed.warnings.map((warning) => warning.code), response.warnings.map((warning: Row) => warning.code))
        && sameJson(parsed.contextDocuments, response.context_documents),
        { warnings: response.warnings, context: response.context_documents, parsed: parsed?.contextDocuments });
    if (!parsed) return;

    if (response.outcome !== 'changed') {
        check(`${name}: an answer that changes nothing carries no candidate`,
            parsed.candidate === null && parsed.changes.length === 0 && response.candidate === null);
        return;
    }

    const rebased = rebaseAssistCandidate(live, parsed.candidate as WorkflowDefinition);
    check(`${name}: laying the candidate over the live draft changes nothing JSON can see`,
        jsonEquivalent(rebased, response.candidate));
    const violation = workflowAssistViolation(live, rebased);
    check(`${name}: the editor accepts the candidate`, violation === '', violation);

    const own = diffWorkflowChanges(live, rebased).changes.map((change) => ({
        key: change.key, kind: change.kind, label: change.label, owner_label: change.ownerLabel,
        focus_key: change.target.focusKey, node_id: change.target.nodeId ?? null,
    }));
    check(`${name}: the editor's own diff finds the changes and Jump to targets the server reported`,
        sameJson(own, serverDiff(response.changes)), { editor: own, server: serverDiff(response.changes) });

    const verification = verifyAssistChanges(live, rebased, parsed.changes);
    check(`${name}: every reported change is verified and none is left over`,
        verification.unverified.length === 0 && verification.changes.length === response.changes.length
        && verification.changes.every((change) => change.reported),
        { unverified: verification.unverified, keys: verification.changes.map((change) => change.key) });

    const wording = verification.changes.map((change) => workflowAssistChangeSummary(change.change));
    const serverWording = response.changes.map((change: Row) => String(change.summary).replace(/\s+/g, ' ').trim());
    check(`${name}: the editor words each change as the server does`, sameJson(wording, serverWording),
        { editor: wording, server: serverWording });

    const applying = openSession(live, options);
    const turnId = item.submission_id;
    const result = applying.session.applyAssist(rebased, {
        turnId, label: workflowAssistTurnLabel('Ask AI', item.instruction),
    });
    if (result.status === 'confirmation_required') {
        console.log(`      (${name}: the editor asked to confirm the change first)`);
        applying.session.confirm();
    }
    check(`${name}: applyAssist applies the answer under the turn's id`,
        isWorkflowHistoryTurnId(turnId) && (result.status === 'applied'
            || result.status === 'confirmation_required' && applying.session.getSnapshot().pending === null),
        { result, errors: applying.errors });
    check(`${name}: the applied draft is the assistant's candidate`,
        jsonEquivalent(applying.session.draft, response.candidate) && applying.errors.length === 0,
        { errors: applying.errors });
}

const fixturePath = process.env.WORKFLOW_ASK_AI_PARITY_FIXTURE;
if (!fixturePath) {
    throw new Error('Set WORKFLOW_ASK_AI_PARITY_FIXTURE to the file test_v2_workflow_ask_ai_parity.py writes.');
}
const fixture = JSON.parse(readFileSync(fixturePath, 'utf-8')) as ParityFixture;

if (fixture.phase === 'requests') {
    emit('REQUESTS', buildRequests(fixture));
} else {
    fixture.cases.forEach((item) => replayResponse(item, fixture.options));
    console.log(`\n${fixture.cases.length} answers replayed; ${failures ? `${failures} FAILED` : 'all passed'}`);
}
if (failures) process.exitCode = 1;
