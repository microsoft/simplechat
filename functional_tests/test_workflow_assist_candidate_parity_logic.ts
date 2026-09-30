// test_workflow_assist_candidate_parity_logic.ts
// Replays the AI workflow assistant's candidates through the V2 workflow editor.
//
// Version: 0.261.206
// Implemented in: 0.261.206
//
// test_workflow_assist_candidate_parity.py runs real assistant requests with a scripted model and
// writes each result to the JSON file WORKFLOW_ASSIST_PARITY_FIXTURE names. Bundled with esbuild and
// run under node, as test_v2_workflow_change_tracking_logic.ts is, this checks that the editor agrees
// with the server's Python port on every result: the draft the editor opens, the assist rules, the
// change list and its Jump to targets, the Run as consequence, the save payload, and applyAssist.
//
// It also prints, one JSON line per section, what the editor computes for every result and for a
// corpus of numbers, whitespace and JSON literals: the draft it opens, the payload it saves,
// Number() of each value, and what JSON.parse reads. JSON here can't tell 12 from 12.0, but the
// save route can, so the Python side compares those lines type-strictly.

import { readFileSync } from 'node:fs';
import {
    WorkflowAuthoringSession,
    workflowAssistViolation,
} from '../application/v2_ui/src/components/workflows/WorkflowAuthoringHistory';
import {
    diffWorkflowChanges,
    workflowRunAsConsequence,
    type WorkflowChange,
} from '../application/v2_ui/src/lib/workflowChangeTracking';
import {
    normalizeWorkflowDefinition,
    workflowForSave,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowScope,
} from '../application/v2_ui/src/lib/workflowEditor';

type Row = Record<string, any>;

interface RefusedCandidate {
    label: string;
    candidate: Row;
    message: string;
    exact: boolean;
}

interface ParityCase {
    name: string;
    stored: Row | null;
    original: Row | null;
    draft: Row;
    candidate: Row;
    changes: Row[];
    projection: Row;
    run_as_warning: boolean;
    refused: RefusedCandidate[];
}

interface ParityCorpus {
    numbers: unknown[];
    opens: Row[];
    saves: { stored: Row | null; draft: Row }[];
    literals: string[];
}

const PERSONAL: WorkflowScope = { type: 'personal' };

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail === undefined ? '' : JSON.stringify(detail, null, 1)?.slice(0, 3000));
    }
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

/** The value the server reads: this one after a JSON round trip. */
function asJson(value: unknown): unknown {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

interface Difference {
    path: string;
    editor: unknown;
    server: unknown;
}

/** The first path where the editor's JSON value differs from the server's, or null when they match. */
function difference(editor: unknown, server: unknown, path = '$'): Difference | null {
    if (JSON.stringify(canonical(editor)) === JSON.stringify(canonical(server))) return null;
    if (Array.isArray(editor) && Array.isArray(server)) {
        if (editor.length !== server.length) return { path: `${path}.length`, editor: editor.length, server: server.length };
        for (let index = 0; index < editor.length; index += 1) {
            const found = difference(editor[index], server[index], `${path}[${index}]`);
            if (found) return found;
        }
    } else if (
        editor !== null && server !== null && typeof editor === 'object' && typeof server === 'object'
        && !Array.isArray(editor) && !Array.isArray(server)
    ) {
        const left = editor as Row;
        const right = server as Row;
        for (const key of [...new Set([...Object.keys(left), ...Object.keys(right)])].sort()) {
            const found = difference(left[key], right[key], `${path}.${key}`);
            if (found) return found;
        }
    }
    return { path, editor, server };
}

function editorChanges(changes: readonly WorkflowChange[]) {
    return changes.map((change) => ({
        key: change.key, kind: change.kind, label: change.label, owner_label: change.ownerLabel,
        focus_key: change.target.focusKey, node_id: change.target.nodeId ?? null,
    }));
}

function serverChanges(changes: readonly Row[]) {
    return changes.map((change) => ({
        key: change.key, kind: change.kind, label: change.label, owner_label: change.owner_label,
        focus_key: change.target?.focus_key, node_id: change.target?.node_id ?? null,
    }));
}

function editorPayload(candidate: WorkflowDefinition, original: WorkflowDefinition | null): unknown {
    try {
        return asJson(workflowForSave(candidate, original, PERSONAL));
    } catch (error) {
        return { editor_refused_to_save: error instanceof Error ? error.message : String(error) };
    }
}

function openStored(stored: Row): unknown {
    try {
        return asJson(normalizeWorkflowDefinition(structuredClone(stored), PERSONAL));
    } catch (error) {
        return { editor_refused: error instanceof Error ? error.message : String(error) };
    }
}

/** A number as JSON can carry it: NaN, the infinities and negative zero by name. */
function describeNumber(value: number): unknown {
    if (Number.isNaN(value)) return 'NaN';
    if (value === Infinity) return 'Infinity';
    if (value === -Infinity) return '-Infinity';
    if (Object.is(value, -0)) return '-0';
    return value;
}

function hasNonFinite(value: unknown): boolean {
    if (typeof value === 'number') return !Number.isFinite(value);
    if (Array.isArray(value)) return value.some(hasNonFinite);
    if (value !== null && typeof value === 'object') return Object.values(value as Row).some(hasNonFinite);
    return false;
}

/** What the browser reads from a JSON text: refused when JSON.parse throws or yields a non-finite number. */
function readLiteral(literal: string): unknown {
    let value: unknown;
    try {
        value = JSON.parse(literal);
    } catch {
        return { refused: 'not JSON' };
    }
    return hasNonFinite(value) ? { refused: 'not finite' } : { value: asJson(value) };
}

/** One labelled line of JSON; U+0085, U+2028 and U+2029 are escaped so the line stays one line. */
function emit(label: string, value: unknown) {
    const line = JSON.stringify(value).replace(
        /[\u0085\u2028\u2029]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`,
    );
    console.log(`${label} ${line}`);
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

function checkCase(item: ParityCase, options: Row, turn: number) {
    const name = item.name;
    const draft = item.draft as WorkflowDefinition;
    const candidate = item.candidate as WorkflowDefinition;
    const original = item.stored ? normalizeWorkflowDefinition(structuredClone(item.stored), PERSONAL) : null;

    if (item.stored) {
        const opened = difference(asJson(original), item.original);
        check(`${name}: the editor opens the saved workflow as the server's port does`, opened === null, opened);
    }

    const violation = workflowAssistViolation(draft, candidate);
    check(`${name}: the editor accepts the candidate`, violation === '', violation);

    const changes = diffWorkflowChanges(draft, candidate).changes;
    const listed = difference(editorChanges(changes), serverChanges(item.changes));
    check(`${name}: the editor lists the changes and Jump to targets the server reports`, listed === null, listed);

    const runAs = workflowRunAsConsequence(draft, candidate, changes);
    check(`${name}: the editor asks to re-approve Run as exactly when the server warns`,
        runAs === item.run_as_warning, { editor: runAs, server: item.run_as_warning });

    const saved = difference(editorPayload(candidate, original), item.projection);
    check(`${name}: the editor saves the payload the server validated`, saved === null, saved);

    const applying = openSession(structuredClone(draft), options);
    const result = applying.session.applyAssist(structuredClone(candidate), { turnId: `assist-turn-${turn}`, label: 'AI assist' });
    if (result.status === 'confirmation_required') {
        console.log(`      (${name}: the editor asked to confirm the change first, as it does for Undo)`);
        applying.session.confirm();
    }
    check(`${name}: applyAssist applies the candidate`,
        result.status === 'applied' || result.status === 'confirmation_required' && applying.session.getSnapshot().pending === null,
        { result, errors: applying.errors });
    const applied = difference(asJson(applying.session.getSnapshot().draft), asJson(candidate));
    check(`${name}: the applied draft is the candidate, unchanged`, applied === null && applying.errors.length === 0,
        { applied, errors: applying.errors });

    const refusing = openSession(structuredClone(draft), options);
    item.refused.forEach((bad, index) => {
        const message = workflowAssistViolation(draft, bad.candidate as WorkflowDefinition);
        check(`${name}: the editor refuses a candidate that changes ${bad.label}`,
            bad.exact ? message === bad.message : message !== '', { editor: message, server: bad.message });
        const before = refusing.session.draft;
        const outcome = refusing.session.applyAssist(
            structuredClone(bad.candidate) as WorkflowDefinition, { turnId: `refused-turn-${turn}-${index + 1}`, label: 'AI assist' },
        );
        check(`${name}: applyAssist refuses the candidate that changes ${bad.label} and keeps the draft`,
            outcome.status === 'rejected' && refusing.session.draft === before, outcome);
    });
}

const fixturePath = process.env.WORKFLOW_ASSIST_PARITY_FIXTURE;
if (!fixturePath) {
    throw new Error('Set WORKFLOW_ASSIST_PARITY_FIXTURE to the file test_workflow_assist_candidate_parity.py writes.');
}
const fixture = JSON.parse(readFileSync(fixturePath, 'utf-8')) as { options: Row; cases: ParityCase[]; corpus: ParityCorpus };

// Printed before the checks run, from fresh copies, so nothing a check does can change them.
emit('RESULTS', fixture.cases.map((item) => {
    const original = item.stored ? normalizeWorkflowDefinition(structuredClone(item.stored), PERSONAL) : null;
    return {
        name: item.name,
        original: original ? asJson(original) : null,
        payload: editorPayload(structuredClone(item.candidate) as WorkflowDefinition, original),
    };
}));
emit('NUMBERS', fixture.corpus.numbers.map((value) => describeNumber(Number(value))));
emit('OPENS', fixture.corpus.opens.map(openStored));
emit('SAVES', fixture.corpus.saves.map(({ stored, draft }) => editorPayload(
    structuredClone(draft) as WorkflowDefinition,
    stored ? normalizeWorkflowDefinition(structuredClone(stored), PERSONAL) : null,
)));
emit('LITERALS', fixture.corpus.literals.map(readLiteral));

fixture.cases.forEach((item, index) => checkCase(item, fixture.options, index + 1));
console.log(`\n${fixture.cases.length} assistant results replayed; ${failures ? `${failures} FAILED` : 'all passed'}`);
if (failures) process.exitCode = 1;
