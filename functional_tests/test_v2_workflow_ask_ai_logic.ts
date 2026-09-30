// test_v2_workflow_ask_ai_logic.ts
// Behavioural checks for the workflow editor's Ask AI tab: the request it builds, the answer it
// accepts, the failures it explains, and how an answer is laid over the draft before it applies.
//
// Version: 0.261.211
// Implemented in: 0.261.211
//
// The V2 interface has no unit test runner, so this follows test_v2_workflow_change_tracking_logic.ts:
// bundled with the esbuild Vite already brings in, run under node by test_v2_workflow_ask_ai.py,
// and skipped when the front-end toolchain is not installed.
//
// The properties worth most here: the request is exactly 3b's contract (strict keys, limits in
// code points, no id on a new draft, only completed turns replayed); nothing the server says is
// trusted (the change list is the editor's own diff, and every string stays plain text); and the
// candidate is laid over the live draft, so untouched values keep their identity.

import fixture from './fixtures/workflow_flow_authoring.json';
import { codePointLength, codePointPrefix } from '../application/v2_ui/src/lib/codePoints';
import {
    assistTextLength,
    describeDraftProblem,
    makeSubmissionId,
    submitAssistDraft,
    type AssistSendRequest,
    type AssistSendResult,
} from '../application/v2_ui/src/lib/assistThread';
import {
    blankDraft,
    holdAssistThread,
    newThread,
    pruneThreads,
    useAssistThreadStore,
    type AssistExchange,
    type AssistThreadRecord,
} from '../application/v2_ui/src/stores/assistThreadStore';
import { MAX_WORKFLOW_ASSIST_TURNS, useWorkflowAssistStore } from '../application/v2_ui/src/stores/workflowAssistStore';
import {
    MISSING_REVISION_MESSAGE,
    REFERENCE_LIMIT_MESSAGE,
    TAGS_UNSUPPORTED_MESSAGE,
    UNREADABLE_ANSWER_MESSAGE,
    WORKFLOW_ASSIST_DEADLINE_MS,
    WORKFLOW_ASSIST_PATH,
    WORKFLOW_DRAFT_INSTRUCTIONS_PATH,
    WORKSPACE_REFERENCE_MESSAGE,
    WorkflowAssistRequestError,
    assistDraftUnchanged,
    buildWorkflowAssistRequest,
    describeWorkflowAssistError,
    jsonEquivalent,
    parseWorkflowAssistResponse,
    postWorkflowAssist,
    rebaseAssistCandidate,
    requestDraftInstructions,
    verifyAssistChanges,
    withDraftedInstructions,
    workflowAssistChangeSummary,
    workflowAssistConversation,
    workflowAssistFocusValid,
    workflowAssistReplay,
    workflowAssistRetryAfter,
    workflowAssistText,
    workflowAssistTurnLabel,
    workflowAssistTurnState,
    type WorkflowAssistHistoryView,
    type WorkflowAssistReplayState,
    type WorkflowAssistReportedChange,
    type WorkflowAssistRequestInput,
    type WorkflowAssistTurnRecord,
} from '../application/v2_ui/src/lib/workflowAssist';
import { WorkflowAuthoringSession, workflowAssistViolation } from '../application/v2_ui/src/components/workflows/WorkflowAuthoringHistory';
import { isWorkflowHistoryTurnId } from '../application/v2_ui/src/lib/workflowAuthoringHistory';
import { diffWorkflowChanges, workflowTaskKey } from '../application/v2_ui/src/lib/workflowChangeTracking';
import {
    WORKFLOW_TASK_INSTRUCTIONS_LIMIT,
    newWorkflowDefinition,
    normalizeWorkflowDefinition,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowScope,
} from '../application/v2_ui/src/lib/workflowEditor';
import type { ContextItem } from '../application/v2_ui/src/lib/chatContext';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail === undefined ? '' : JSON.stringify(detail, null, 1)?.slice(0, 2000));
    }
}

type Row = Record<string, any>;

const PERSONAL: WorkflowScope = { type: 'personal' };
const CONVERSATION = 'workflow-editor';
const EMOJI = '\u{1F600}';
const emoji = (count: number) => EMOJI.repeat(count);
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;

function structured(): WorkflowDefinition {
    return normalizeWorkflowDefinition(structuredClone(fixture.initial), PERSONAL);
}

function classic(count = 3): WorkflowDefinition {
    return normalizeWorkflowDefinition({
        id: 'classic-workflow', user_id: 'offline-owner', definition_version: 2, definition_revision: 'rev-classic-1',
        name: 'Classic', description: 'Summarize new documents.', runner_type: 'model', trigger_type: 'manual',
        is_enabled: false, reference_inputs: [{ id: 'r1', name: 'Policy', document_id: 'doc-1', scope_type: 'personal' }],
        tasks: Array.from({ length: count }, (_, index) => ({
            id: `t${index + 1}`, type: 'instructions', name: `Step ${index + 1}`, instructions: `Do step ${index + 1}.`,
            order: index + 1, runner: { type: 'inherit' },
        })),
    }, PERSONAL);
}

/** A proposal draft as Phase 4 serves it: the server's own fields, the id among them, stripped. */
function proposalDraft(): WorkflowDefinition {
    const workflow: Row = structuredClone(fixture.initial);
    for (const field of ['id', 'user_id', 'definition_revision']) delete workflow[field];
    return normalizeWorkflowDefinition(workflow, PERSONAL);
}

const wire = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

function withTask(definition: WorkflowDefinition, id: string, patch: Row): WorkflowDefinition {
    return { ...definition, tasks: definition.tasks.map((task) => task.id === id ? { ...task, ...patch } : task) };
}

function draftOf(text: string) {
    return { ...blankDraft(), text };
}

function documentItem(id: string, label = `Document ${id}`, scope: Row = { kind: 'personal', id: null, name: 'Personal' }): ContextItem {
    return {
        key: `document:${scope.kind}:${scope.id ?? ''}:${id}`, kind: 'document', id, label, token: `#${label}`,
        attachment: 'mention', scope, origin: 'picker',
    } as unknown as ContextItem;
}

function tagItem(name: string): ContextItem {
    return {
        key: `tag:personal::${name}`, kind: 'tag', id: name, label: name, token: `#${name}`,
        attachment: 'mention', scope: { kind: 'personal', id: null, name: 'Personal' }, origin: 'picker',
    } as unknown as ContextItem;
}

function scopeItem(): ContextItem {
    return {
        key: 'scope:group:group-1', kind: 'scope', id: 'group-1', label: 'Team', token: '#Team',
        attachment: 'mention', scope: { kind: 'group', id: 'group-1', name: 'Team' }, origin: 'picker',
    } as unknown as ContextItem;
}

const ZONES: ReadonlySet<string> = new Set(['America/New_York', 'UTC']);

function requestInput(overrides: Partial<WorkflowAssistRequestInput> = {}): WorkflowAssistRequestInput {
    const draft = overrides.draft ?? classic();
    return {
        submissionId: 'submission-1',
        instruction: 'Run this at 7 AM on weekdays and only alert me when something is urgent',
        baseline: overrides.baseline ?? draft,
        draft,
        contextItems: [],
        conversation: [],
        focus: null,
        timeZone: 'America/New_York',
        timeZones: ZONES,
        ...overrides,
    };
}

function refusalOf(input: WorkflowAssistRequestInput): unknown {
    try {
        buildWorkflowAssistRequest(input);
        return null;
    } catch (problem) {
        return problem;
    }
}

function sameKeys(value: object, keys: readonly string[]): boolean {
    return Object.keys(value).sort().join() === [...keys].sort().join();
}

// ---------------------------------------------------------------------------------------------
// Code points
// ---------------------------------------------------------------------------------------------

function codePointChecks() {
    check('an emoji is one code point and two UTF-16 units', codePointLength(EMOJI) === 1 && EMOJI.length === 2);
    check('2,000 emoji are 2,000 code points and 4,000 units', codePointLength(emoji(2000)) === 2000 && emoji(2000).length === 4000);
    check('a lone surrogate counts once, as the server counts it', codePointLength('\ud83d') === 1 && codePointLength('a\ude00b') === 3);
    check('a code point prefix never splits a pair',
        codePointPrefix(emoji(3), 2) === emoji(2) && codePointPrefix(`a${EMOJI}b`, 2) === `a${EMOJI}`);
    check('the thread counts UTF-16 units unless asked for code points',
        assistTextLength(emoji(2)) === 4 && assistTextLength(emoji(2), true) === 2);
    check('by default the thread still refuses 1,001 emoji against 2,000',
        describeDraftProblem(draftOf(emoji(1001)), 2000) === 'too_long');
    check('counting code points, 2,000 emoji fit and 2,001 do not',
        describeDraftProblem(draftOf(emoji(2000)), 2000, true) === null
        && describeDraftProblem(draftOf(emoji(2001)), 2000, true) === 'too_long');
    check('blank text is empty whichever way it is counted', describeDraftProblem(draftOf(' \n\t'), 2000, true) === 'empty');
}

// ---------------------------------------------------------------------------------------------
// The request
// ---------------------------------------------------------------------------------------------

function requestChecks() {
    const saved = classic();
    const body = buildWorkflowAssistRequest(requestInput({ draft: saved, baseline: saved }));
    check('a saved workflow sends its id and the revision the editor opened',
        body.base?.workflow_id === 'classic-workflow' && body.base.definition_revision === 'rev-classic-1', body.base);
    check('the draft sent is the session draft itself, so the answer is compared with it', body.draft === saved);
    check('the request carries exactly the contract keys', sameKeys(body,
        ['base', 'conversation', 'draft', 'focus', 'instruction', 'references', 'submission_id', 'time_zone']), Object.keys(body));
    check('the submission id is sent as given', body.submission_id === 'submission-1');
    check('the instruction is sent trimmed', body.instruction === requestInput().instruction);

    const fresh = newWorkflowDefinition(PERSONAL);
    const freshWire = wire(buildWorkflowAssistRequest(requestInput({ draft: fresh, baseline: fresh })));
    check('a new draft sends base null and a draft without an id',
        freshWire.base === null && !Object.hasOwn(freshWire.draft, 'id'), freshWire.draft);

    const proposal = proposalDraft();
    const proposalWire = wire(buildWorkflowAssistRequest(requestInput({ draft: proposal, baseline: proposal })));
    check('a proposal draft sends base null and a draft without an id',
        proposalWire.base === null && !Object.hasOwn(proposalWire.draft, 'id') && proposalWire.draft.definition_version === 3,
        proposalWire.base);

    const edited = { ...saved, name: 'Edited' };
    const editedBody = buildWorkflowAssistRequest(requestInput({ draft: edited, baseline: saved }));
    check('an edited saved workflow sends the current draft against the opened base',
        editedBody.draft === edited && editedBody.base?.workflow_id === 'classic-workflow');

    const noRevision = { ...saved, definition_revision: undefined };
    const missing = refusalOf(requestInput({ draft: noRevision, baseline: noRevision }));
    check('a saved workflow without a revision is refused before sending',
        missing instanceof WorkflowAssistRequestError && missing.message === MISSING_REVISION_MESSAGE, String(missing));
    const claimed = refusalOf(requestInput({ draft: saved, baseline: fresh }));
    check('a draft with an id and no saved base is refused before sending',
        claimed instanceof WorkflowAssistRequestError && claimed.message === MISSING_REVISION_MESSAGE, String(claimed));

    // The time zone
    const zone = (timeZone: string | null, timeZones: ReadonlySet<string> | null) =>
        buildWorkflowAssistRequest(requestInput({ timeZone, timeZones })).time_zone;
    check('the browser time zone is sent when the schedule editor offers it', zone('America/New_York', ZONES) === 'America/New_York');
    check('a zone the schedule editor does not offer is not sent',
        zone('Mars/Olympus_Mons', ZONES) === undefined && !Object.hasOwn(buildWorkflowAssistRequest(requestInput({ timeZone: 'Mars/Base' })), 'time_zone'));
    check('no zone is sent when the editor has no zone list or the browser has no zone',
        zone('UTC', null) === undefined && zone(null, ZONES) === undefined);

    // The focus
    const focus = (draft: WorkflowDefinition, value: string | null) =>
        buildWorkflowAssistRequest(requestInput({ draft, baseline: draft, focus: value })).focus;
    const flow = structured();
    check('a task focus is sent as the task id', focus(saved, 't2') === 't2');
    check('a focus the draft no longer has is sent as null', focus(saved, 'gone-task') === null && focus(saved, null) === null);
    check('a structured draft can focus a flow block, nested ones too',
        focus(flow, 'seed-node') === 'seed-node' && focus(flow, 'yes-node') === 'yes-node' && focus(flow, 'report-task') === 'report-task');
    check('a classic draft cannot focus a flow block', !workflowAssistFocusValid(saved, 'seed-node'));

    // The instruction
    const cleaned = buildWorkflowAssistRequest(requestInput({ instruction: '  Run\u0000 at 7\tAM\nplease\u0007\u007f  ' }));
    check('control characters are stripped and tab and newline kept', cleaned.instruction === 'Run at 7\tAM\nplease', cleaned.instruction);
    const blank = refusalOf(requestInput({ instruction: ' \u0001\u0002 ' }));
    check('an instruction that is blank once cleaned is refused', blank instanceof WorkflowAssistRequestError);
    check('an instruction of exactly 2,000 emoji is sent whole',
        buildWorkflowAssistRequest(requestInput({ instruction: emoji(2000) })).instruction === emoji(2000));
    const tooLong = refusalOf(requestInput({ instruction: emoji(2001) }));
    check('an instruction of 2,001 emoji is refused', tooLong instanceof WorkflowAssistRequestError
        && tooLong.message.startsWith('Shorten the message'), String(tooLong));
    check('a lone surrogate is replaced rather than sent',
        workflowAssistText('a\ud83db') === 'a\ufffdb' && !LONE_SURROGATE.test(workflowAssistText('\ude00x\ud83d')));

    // The references
    const withRefs = (contextItems: ContextItem[]) => refusalOf(requestInput({ contextItems }));
    const tag = withRefs([documentItem('doc-1'), tagItem('finance')]);
    check('a # tag is refused with the tags message', tag instanceof WorkflowAssistRequestError
        && tag.code === 'tags_unsupported' && tag.message === TAGS_UNSUPPORTED_MESSAGE, String(tag));
    const scope = withRefs([scopeItem()]);
    check('a whole workspace is refused', scope instanceof WorkflowAssistRequestError && scope.message === WORKSPACE_REFERENCE_MESSAGE);
    const many = Array.from({ length: 21 }, (_, index) => documentItem(`doc-${String(index).padStart(2, '0')}`));
    const limit = withRefs(many);
    check('21 documents are refused with the limit', limit instanceof WorkflowAssistRequestError
        && limit.code === 'reference_limit' && limit.message === REFERENCE_LIMIT_MESSAGE, String(limit));
    const twenty = buildWorkflowAssistRequest(requestInput({ contextItems: many.slice(0, 20).reverse() })).references;
    check('20 documents are sent, sorted, in the shape the server authorizes', twenty.length === 20
        && twenty[0].id === 'doc-00' && twenty.every((item) => item.kind === 'document' && item.scope.kind === 'personal'
            && item.scope.id === null && item.label?.startsWith('Document')), twenty.slice(0, 2));
    const duplicated = buildWorkflowAssistRequest(requestInput({ contextItems: [documentItem('doc-1'), documentItem('doc-1', 'Again')] })).references;
    check('a document picked twice is sent once, with its first label', duplicated.length === 1 && duplicated[0].label === 'Document doc-1');
    const group = buildWorkflowAssistRequest(requestInput({
        contextItems: [documentItem('doc-g', 'Guide', { kind: 'group', id: 'group-7', name: 'Team' })],
    })).references;
    check('a group document keeps its workspace', group[0]?.scope.kind === 'group' && group[0].scope.id === 'group-7');
}

// ---------------------------------------------------------------------------------------------
// The conversation replayed
// ---------------------------------------------------------------------------------------------

function replayTurn(state: WorkflowAssistReplayState, changes: string[] = ['Schedule: Run at', 'Alerts: Alert mode'], reply = 'Done.') {
    return { instruction: 'Do it', reply, state, changes };
}

function conversationChecks() {
    const turns = Array.from({ length: 12 }, (_, index) => replayTurn('none', [], `Answer ${index + 1}`))
        .map((turn, index) => ({ ...turn, instruction: `Ask ${index + 1}` }));
    const items = workflowAssistConversation(turns);
    check('a replay keeps the last ten exchanges as twenty items', items.length === 20
        && items[0].text === 'Ask 3' && items[19].text === 'Answer 12', items.map((item) => item.text));
    check('a replay starts with the user and alternates', items.every((item, index) => item.role === (index % 2 ? 'assistant' : 'user')));

    const assistantText = (state: WorkflowAssistReplayState, changes?: string[]) =>
        workflowAssistConversation([replayTurn(state, changes)])[1]?.text ?? '';
    check('an applied turn replays its reply and the changes applied',
        assistantText('applied') === 'Done.\n\nChanges applied: Schedule: Run at; Alerts: Alert mode.', assistantText('applied'));
    check('a partly undone turn says some were undone', assistantText('partly_undone').endsWith('The user later undid some of them.'));
    check('an undone turn says its changes were undone', assistantText('undone').startsWith('Done.\n\nThese changes were applied and later undone:'));
    check('a turn awaiting confirmation says so', assistantText('pending').includes("waiting for the user's confirmation and are not applied yet"));
    check('a declined turn says nothing was applied', assistantText('declined') === 'Done.\n\nNo changes were applied.');
    check('a turn from an earlier session says it may not have been saved', assistantText('earlier').includes('earlier editing session'));
    check('a turn with no change replays its reply alone', assistantText('none') === 'Done.');
    const fifteen = Array.from({ length: 15 }, (_, index) => `Change ${index + 1}`);
    check('a long change list is summarized', assistantText('applied', fifteen).endsWith('Change 12; and 3 more.'), assistantText('applied', fifteen));

    const huge = workflowAssistConversation([replayTurn('applied', ['Name'], emoji(4000))])[1]?.text ?? '';
    check('an assistant item is capped at 4,000 code points without splitting a pair',
        codePointLength(huge) === 4000 && !LONE_SURROGATE.test(huge), codePointLength(huge));
    check('a turn with no text is left out', workflowAssistConversation([{ instruction: ' ', reply: '', state: 'none', changes: [] }]).length === 0);
    const controls = workflowAssistConversation([{ instruction: 'A\u0000B', reply: 'C\u0007D', state: 'none', changes: [] }]);
    check('replayed text is cleaned like the instruction', controls[0].text === 'AB' && controls[1].text === 'CD');

    const exchanges = [
        { id: 'a', status: 'done', text: 'First', reply: 'One' },
        { id: 'b', status: 'failed', text: 'Failed' },
        { id: 'c', status: 'cancelled', text: 'Cancelled' },
        { id: 'd', status: 'pending', text: 'Pending' },
        { id: 'e', status: 'done', text: 'Resent', reply: 'Two' },
    ];
    const view: WorkflowAssistHistoryView = { steps: [], attribution: new Map(), pending: null };
    const replay = workflowAssistReplay(exchanges, () => undefined, view, 'epoch', 'e');
    check('only completed turns are replayed, never the one being sent',
        replay.length === 1 && replay[0].instruction === 'First' && replay[0].reply === 'One', replay);
    const recorded = workflowAssistReplay(exchanges, (id) => id === 'a' ? turnRecord({ instruction: 'First, cleaned', reply: 'One, cleaned' }) : undefined, view, 'epoch');
    check('a recorded turn replays what was sent and answered', recorded[0].instruction === 'First, cleaned'
        && recorded[0].reply === 'One, cleaned' && recorded.length === 2, recorded);

    const request = buildWorkflowAssistRequest(requestInput({ conversation: [replayTurn('applied')] }));
    check('the request replays through the same rules', request.conversation.length === 2
        && request.conversation[1].text.startsWith('Done.\n\nChanges applied'));
}

// ---------------------------------------------------------------------------------------------
// Where a turn stands, read from a real authoring session
// ---------------------------------------------------------------------------------------------

const fixtureOptions = () => structuredClone(fixture.options) as unknown as WorkflowEditorOptions;

function openSession(draft: WorkflowDefinition) {
    const session = new WorkflowAuthoringSession(draft);
    const errors: string[] = [];
    session.configure({
        options: fixtureOptions(), readOnly: false, saving: false, commandPending: false, selectionId: null,
        onError: (message: string) => { if (message) errors.push(message); },
        onRestore: () => {},
        onRollback: () => {},
    });
    return { session, errors };
}

function viewOf(session: WorkflowAuthoringSession): WorkflowAssistHistoryView {
    const snapshot = session.getSnapshot();
    return { steps: snapshot.steps, attribution: snapshot.attribution, pending: snapshot.pending };
}

function turnRecord(patch: Partial<WorkflowAssistTurnRecord> = {}): WorkflowAssistTurnRecord {
    return {
        threadKey: 'workflow:personal:m5b-offline-authoring', epoch: 'epoch-1', instruction: 'Rename it', outcome: 'changed',
        reply: 'Done.', changes: [], warnings: [], contextDocuments: [], apply: 'applied', undoSequence: 0, ...patch,
    };
}

function turnStateChecks() {
    const { session } = openSession(structured());
    const start = session.draft;
    const candidate = withTask({ ...start, name: 'AI name' }, 'seed-task', { instructions: 'Decide with care.' });
    const verified = verifyAssistChanges(start, candidate, []);
    const applied = session.applyAssist(candidate, { turnId: 'turn-a', label: workflowAssistTurnLabel('Ask AI', 'Rename it') });
    const record = turnRecord({ changes: verified.changes });
    const stateOf = (value: WorkflowAssistTurnRecord, epoch = 'epoch-1', turnId = 'turn-a') =>
        workflowAssistTurnState(turnId, value, viewOf(session), epoch);
    check('an applied turn reads as applied', applied.status === 'applied' && stateOf(record) === 'applied', applied);
    check('a turn from an earlier editing session reads as earlier', stateOf(record, 'epoch-2') === 'earlier');
    check('a turn with nothing to apply reads as none', stateOf(turnRecord({ apply: 'none' })) === 'none'
        && stateOf(turnRecord({ apply: 'noop', changes: verified.changes })) === 'none'
        && stateOf(turnRecord({ outcome: 'question', changes: verified.changes })) === 'none');
    check('a turn the editor refused reads as declined', stateOf(turnRecord({ apply: 'rejected', changes: verified.changes }), 'epoch-1', 'turn-z') === 'declined');

    session.request('undo');
    check('Undo in the editor reads as undone', stateOf(record) === 'undone');
    session.request('redo');
    check('Redo reads as applied again', stateOf(record) === 'applied');

    // A later edit to one of the turn's fields, then Undo this change.
    session.changeDraft((draft) => ({ ...draft, name: 'My own name' }), { label: 'Workflow name' });
    const undo = session.revertTurn('turn-a');
    const skippedName = undo.status === 'applied' ? undo.skippedKeys.find((item) => item.key === 'name') : undefined;
    check('Undo this change reverts what was not edited later and skips the rest', undo.status === 'applied'
        && undo.reverted === 1 && undo.skipped === 1 && skippedName?.reason === 'Changed after this turn.'
        && session.draft.name === 'My own name'
        && session.draft.tasks.find((task) => task.id === 'seed-task')?.instructions === start.tasks.find((task) => task.id === 'seed-task')?.instructions,
        undo);
    check('a partly undone turn reads as partly undone', stateOf({ ...record, undo }) === 'partly_undone');
    check('a fully undone turn reads as undone', stateOf({ ...record, undo: { ...(undo as Row), skipped: 0 } as WorkflowAssistTurnRecord['undo'] }) === 'undone');
    check('Undo again has nothing left to undo', session.revertTurn('turn-a').status === 'noop');
    session.saved(session.draft);
    check('after Save the turn can no longer be undone', session.revertTurn('turn-a').status === 'unavailable');

    // A candidate that needs confirming first, declined and then confirmed.
    const large = openSession(structured());
    (large.session as unknown as { history: { record: () => unknown } }).history.record = () => ({ status: 'overflow' });
    const hugeCandidate = { ...large.session.draft, name: 'Huge' };
    const hugeChanges = verifyAssistChanges(large.session.draft, hugeCandidate, []).changes;
    const proposal = large.session.applyAssist(hugeCandidate, { turnId: 'turn-p', label: 'Huge' });
    const pendingRecord = turnRecord({ apply: 'pending', changes: hugeChanges });
    check('a turn waiting for confirmation reads as pending', proposal.status === 'confirmation_required'
        && workflowAssistTurnState('turn-p', pendingRecord, viewOf(large.session), 'epoch-1') === 'pending', proposal);
    large.session.cancel();
    check('a declined confirmation reads as declined', workflowAssistTurnState('turn-p', pendingRecord, viewOf(large.session), 'epoch-1') === 'declined');
    large.session.applyAssist(hugeCandidate, { turnId: 'turn-p', label: 'Huge' });
    large.session.confirm();
    check('a confirmed turn reads as applied through its attribution',
        large.session.draft.name === 'Huge' && workflowAssistTurnState('turn-p', pendingRecord, viewOf(large.session), 'epoch-1') === 'applied');

    check('a submission id is a valid history turn id', isWorkflowHistoryTurnId(makeSubmissionId()));
    const label = workflowAssistTurnLabel('Ask AI', `  ${'word '.repeat(60)}\u0000`);
    check('a turn label is short and clean', label.startsWith('Ask AI: word') && codePointLength(label) <= 'Ask AI: '.length + 80
        && label.endsWith('…') && !label.includes('\u0000'), label);
}

// ---------------------------------------------------------------------------------------------
// The answer
// ---------------------------------------------------------------------------------------------

function answer(patch: Row = {}): Row {
    return {
        submission_id: 'submission-1', outcome: 'explained', reply: 'It runs every weekday.', candidate: null,
        changes: [], warnings: [], context_documents: [], ...patch,
    };
}

function responseChecks() {
    const parse = (value: unknown) => parseWorkflowAssistResponse(value, 'submission-1');
    const explained = parse(answer());
    check('an explained answer is read', explained?.outcome === 'explained' && explained.reply === 'It runs every weekday.'
        && explained.candidate === null);
    check('a question is read', parse(answer({ outcome: 'question', reply: 'Which task?' }))?.outcome === 'question');
    const draft = classic();
    const changed = parse(answer({ outcome: 'changed', candidate: wire(draft) }));
    check('a changed answer carries its candidate', changed?.outcome === 'changed' && Array.isArray(changed.candidate?.tasks));

    const refused: [string, unknown][] = [
        ['another submission id', answer({ submission_id: 'submission-2' })],
        ['an unknown outcome', answer({ outcome: 'deleted' })],
        ['a changed answer without a candidate', answer({ outcome: 'changed', candidate: null })],
        ['a candidate without tasks', answer({ outcome: 'changed', candidate: { name: 'x' } })],
        ['a candidate on an explained answer', answer({ candidate: wire(draft) })],
        ['a reply that is not text', answer({ reply: { text: 'hi' } })],
        ['changes that are not a list', answer({ changes: {} })],
        ['warnings missing', answer({ warnings: undefined })],
        ['context documents missing', answer({ context_documents: null })],
        ['not an object', [answer()]],
    ];
    for (const [label, value] of refused) {
        check(`an answer with ${label} is refused`, parse(value) === null);
    }

    const hostile = '<img src=x onerror="alert(1)"> [click](javascript:alert(1)) **bold** <script>alert(2)</script>';
    check('a hostile reply is kept as literal text', parse(answer({ reply: hostile }))?.reply === hostile);
    check('control characters leave the reply, lone surrogates are replaced',
        parse(answer({ reply: 'a\u0000b\u0007c\ud83d' }))?.reply === 'abc\ufffd');
    const long = parse(answer({ reply: emoji(1600) }))?.reply ?? '';
    check('a reply over 1,500 code points is clipped', codePointLength(long) === 1500 && long.endsWith('…') && !LONE_SURROGATE.test(long));

    const parsed = parse(answer({
        changes: [
            { key: 'name', kind: 'modified', label: 'Name', owner_label: 'Workflow', target: { focus_key: 'name' }, summary: 'Workflow: Name' },
            { key: 'task:t1:instructions', label: 'Instructions', owner_label: 'Step 1', target: { focus_key: 'k', node_id: 'n-1' }, summary: 'x' },
            { key: 'bad', label: 'No target', owner_label: 'x', summary: 'x' },
            { key: 'bad-2', label: 7, owner_label: 'x', target: { focus_key: 'k' }, summary: 'x' },
            'not a change',
        ],
        warnings: [
            { code: 'run_as_reapproval', message: 'Saving requires re-approving Run as.' },
            { code: 'email_requires_m365_agent', message: 'Email needs an agent.', target: { focus_key: 'task:t1:runner', node_id: 'n-1' } },
            { code: 'Bad Code', message: 'x' },
            { code: 'draft_has_errors', message: '' },
        ],
        context_documents: ['Security checklist.pdf', 7, '', ...Array.from({ length: 25 }, (_, index) => `Doc ${index}`)],
    }));
    check('malformed change entries are dropped and good ones kept', parsed?.changes.map((change) => change.key).join() === 'name,task:t1:instructions'
        && parsed.changes[1].nodeId === 'n-1' && parsed.changes[0].focusKey === 'name', parsed?.changes);
    check('warnings need a known-looking code and a message', parsed?.warnings.map((warning) => warning.code).join() === 'run_as_reapproval,email_requires_m365_agent'
        && parsed.warnings[1].focusKey === 'task:t1:runner' && parsed.warnings[1].nodeId === 'n-1', parsed?.warnings);
    check('context documents are text labels, at most 20', parsed?.contextDocuments[0] === 'Security checklist.pdf'
        && (parsed?.contextDocuments.length ?? 0) <= 20 && parsed?.contextDocuments.every((label) => typeof label === 'string' && label), parsed?.contextDocuments);
    const longLabel = parse(answer({ context_documents: [`${'x'.repeat(300)}.pdf`] }))?.contextDocuments[0] ?? '';
    check('a long document label is clipped', codePointLength(longLabel) === 200 && longLabel.endsWith('…'));
}

// ---------------------------------------------------------------------------------------------
// Failures
// ---------------------------------------------------------------------------------------------

function failureChecks() {
    const describe = describeWorkflowAssistError;
    const tags = describe(400, { error: 'Workflows use documents, not tags.', code: 'tags_unsupported' });
    check('a 400 shows the server message and code', tags.message === 'Workflows use documents, not tags.' && tags.code === 'tags_unsupported'
        && tags.retryAfterSeconds === null && !tags.reload);
    check('a 400 without a body has a fallback', describe(400, null).message.includes('Nothing was changed'));
    check('a 400 for time zones and oversize input keeps its code',
        describe(400, { error: 'Choose a time zone.', code: 'time_zone_invalid' }).code === 'time_zone_invalid'
        && describe(400, { error: 'Too large.', code: 'assistant_input_too_large' }).code === 'assistant_input_too_large');
    check('a 403 explains Ask AI is not available', describe(403, { code: 'workflow_assistant_disabled' }).message === "Ask AI isn't available to you right now.");
    check('a 404 says the workflow could not be found', describe(404, { code: 'workflow_not_found' }).message.includes("couldn't be found"));
    const conflict = describe(409, { error: 'The workflow changed.', code: 'workflow_definition_conflict' });
    check('a definition conflict offers a reload', conflict.reload && conflict.code === 'workflow_definition_conflict');
    const deleted = describe(409, { error: 'The workflow was deleted.', code: 'workflow_deleted' });
    check('a deleted workflow keeps the draft and offers no reload', !deleted.reload
        && deleted.message === 'The workflow was deleted. Your draft is still in the editor.', deleted.message);
    check('a 409 without a code still says the draft was kept', describe(409, null).message.includes('Your draft was kept'));
    check('a 413 suggests a smaller change', describe(413, { code: 'request_too_large' }).message.includes('smaller change'));
    check('a 500 and a 502 change nothing and offer no wait', [500, 502].every((status) => {
        const failure = describe(status, { error: 'x', code: status === 500 ? 'assistant_failed' : 'assistant_output_invalid' });
        return failure.retryAfterSeconds === null && !failure.reload;
    }));
    check('an unknown status says which', describe(418, null).message.includes('(status 418)'));

    const busy = describe(429, { error: 'Busy.', code: 'assistant_busy', rate_limited: true, retry_after_seconds: 1 }, '1');
    check('a busy 429 waits the header seconds', busy.retryAfterSeconds === 1 && busy.code === 'assistant_busy');
    const markdown = '**Slow down.** <b>Wait</b> [a bit](https://example.com) <img src=x onerror=alert(1)>';
    const limited = describe(429, { error: markdown, code: 'assistant_rate_limited', rate_limited: true, retry_after_seconds: 540 }, '540');
    check('the rate limit message stays literal text', limited.message === markdown && limited.retryAfterSeconds === 540, limited.message);
    check('the Retry-After header wins over the body', describe(429, { retry_after_seconds: 30 }, '12').retryAfterSeconds === 12);
    check('the body is read when there is no header', describe(429, { retry_after_seconds: 45 }).retryAfterSeconds === 45);
    check('a 429 with no wait at all waits a second', describe(429, null).retryAfterSeconds === 1);
    const now = Date.parse('2026-01-01T00:00:00Z');
    check('an HTTP date header is read', workflowAssistRetryAfter('Thu, 01 Jan 2026 00:00:30 GMT', null, now) === 30);
    check('a huge wait is clamped to an hour', workflowAssistRetryAfter('999999', null) === 3600);
    check('a throttled 503 waits what the provider asked', describe(503, { code: 'assistant_unavailable' }, '10').retryAfterSeconds === 10);
    check('a 503 without Retry-After asks no wait', describe(503, { code: 'assistant_timeout' }).retryAfterSeconds === null);
    check('a code that is not a code is dropped', describe(400, { error: 'x', code: 'Not A Code' }).code === '');
    check('an error that is not text falls back', describe(400, { error: 42 }).message.includes('Nothing was changed'));
}

// ---------------------------------------------------------------------------------------------
// The browser request
// ---------------------------------------------------------------------------------------------

type FetchStub = (url: string | URL | Request, init?: RequestInit) => Promise<Response>;

async function withFetch<T>(stub: FetchStub, run: () => Promise<T>): Promise<T> {
    const real = globalThis.fetch;
    globalThis.fetch = stub as typeof fetch;
    try {
        return await run();
    } finally {
        globalThis.fetch = real;
    }
}

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
}

// Like the browser's fetch: a signal that is already aborted rejects at once.
const waitForAbort: FetchStub = (_url, init) => new Promise<Response>((_resolve, reject) => {
    const signal = init?.signal;
    const fail = () => reject(new DOMException('Aborted', 'AbortError'));
    if (signal?.aborted) fail();
    else signal?.addEventListener('abort', fail, { once: true });
});

async function fetchChecks() {
    const request = buildWorkflowAssistRequest(requestInput());
    let seen: { url: string; init: RequestInit } | null = null;
    const ok = await withFetch(async (url, init) => {
        seen = { url: String(url), init: init ?? {} };
        return jsonResponse(200, answer());
    }, () => postWorkflowAssist(request, new AbortController().signal));
    const sent = seen as { url: string; init: RequestInit } | null;
    const headers = new Headers(sent?.init.headers);
    check('an answer that fits the contract is returned', ok.ok && ok.response.reply === 'It runs every weekday.');
    check('the request is a same-origin JSON POST to the assist route', Boolean(sent?.url.endsWith(WORKFLOW_ASSIST_PATH))
        && sent?.init.method === 'POST' && sent.init.credentials === 'same-origin'
        && headers.get('Content-Type') === 'application/json' && headers.get('Accept') === 'application/json', sent?.url);
    check('the body is the request, exactly', sent?.init.body === JSON.stringify(request));
    check('the browser waits about 170 seconds', WORKFLOW_ASSIST_DEADLINE_MS === 170_000);

    const failureOf = async (stub: FetchStub, deadline?: number) => {
        const result = await withFetch(stub, () => postWorkflowAssist(request, new AbortController().signal, deadline));
        return !result.ok && !result.aborted ? result.failure : null;
    };
    const html = await failureOf(async () => new Response('<html>Sign in</html>', { status: 200, headers: { 'Content-Type': 'text/html' } }));
    check('a 200 that is not JSON is unreadable, and nothing is applied', html?.code === 'unreadable' && html.message === UNREADABLE_ANSWER_MESSAGE);
    const other = await failureOf(async () => jsonResponse(200, answer({ submission_id: 'someone-else' })));
    check('an answer to another submission is unreadable', other?.code === 'unreadable');
    const limited = await failureOf(async () => jsonResponse(429, { error: 'Busy.', code: 'assistant_busy', retry_after_seconds: 1 }, { 'Retry-After': '7' }));
    check('a 429 carries the Retry-After header', limited?.status === 429 && limited.retryAfterSeconds === 7);
    const conflict = await failureOf(async () => jsonResponse(409, { error: 'Changed.', code: 'workflow_definition_conflict' }));
    check('a 409 conflict offers the reload', conflict?.reload === true);
    const unreadableError = await failureOf(async () => new Response('Bad gateway', { status: 502 }));
    check('a failure without JSON uses the status message', unreadableError?.status === 502 && unreadableError.message.includes('Nothing was changed'));
    const timeout = await failureOf(waitForAbort, 20);
    check('the browser deadline is a failure the reader can retry', timeout?.code === 'browser_timeout' && timeout.message.includes('took too long'));
    const network = await failureOf(async () => { throw new TypeError('Failed to fetch'); });
    check('a lost connection is a failure the reader can retry', network?.code === 'network_error');

    const controller = new AbortController();
    const running = withFetch(waitForAbort, () => postWorkflowAssist(request, controller.signal));
    controller.abort();
    const cancelled = await running;
    check('Cancel is an abort, not a failure', !cancelled.ok && cancelled.aborted === true);
    const before = new AbortController();
    before.abort();
    const early = await withFetch(waitForAbort, () => postWorkflowAssist(request, before.signal));
    check('an already cancelled turn never waits', !early.ok && early.aborted === true);
    const late = new AbortController();
    const settled = await withFetch(async () => {
        late.abort();
        return jsonResponse(200, answer());
    }, () => postWorkflowAssist(request, late.signal));
    check('an answer that lands after Cancel is not used', !settled.ok && settled.aborted === true);

    // Draft with AI
    const workflow = { ...classic(), name: 'Daily digest', description: 'Summarize new documents.' };
    let drafted: { url: string; body: Row } | null = null;
    const text = await withFetch(async (url, init) => {
        drafted = { url: String(url), body: JSON.parse(String(init?.body)) };
        return jsonResponse(200, { instructions: '  Summarize each new document in three bullets.  ' });
    }, () => requestDraftInstructions(workflow, 'Summarize', new AbortController().signal));
    const draftedRequest = drafted as { url: string; body: Row } | null;
    check('Draft with AI asks the draft-instructions route for a personal workflow',
        Boolean(draftedRequest?.url.endsWith(WORKFLOW_DRAFT_INSTRUCTIONS_PATH)) && draftedRequest !== null
        && sameKeys(draftedRequest.body, ['workflow_scope', 'name', 'description', 'brief'])
        && draftedRequest.body.workflow_scope === 'personal' && draftedRequest.body.brief === 'Summarize', draftedRequest?.body);
    check('drafted instructions are trimmed text', text === 'Summarize each new document in three bullets.');
    const draftFailure = async (stub: FetchStub) => {
        try {
            await withFetch(stub, () => requestDraftInstructions(workflow, 'Summarize', new AbortController().signal));
            return '';
        } catch (problem) {
            return problem instanceof Error ? problem.message : String(problem);
        }
    };
    check('a refused draft shows the server message', await draftFailure(async () => jsonResponse(400, { error: 'Personal workflows are off.' }))
        === 'Personal workflows are off.');
    check('an empty draft is a failure', (await draftFailure(async () => jsonResponse(200, { instructions: '  ' }))).includes("didn't return"));
    check('a draft over the task limit is not added', (await draftFailure(async () => jsonResponse(200, {
        instructions: 'x'.repeat(WORKFLOW_TASK_INSTRUCTIONS_LIMIT + 1),
    }))).includes('longer than'));
    const empty = withTask(classic(), 't2', { instructions: '' });
    const filled = withDraftedInstructions(empty, 't2', 'Drafted.');
    check('drafted instructions fill only the empty task', filled?.tasks[1].instructions === 'Drafted.'
        && filled.tasks[0] === empty.tasks[0] && withDraftedInstructions(classic(), 't2', 'x') === null
        && withDraftedInstructions(empty, 'gone', 'x') === null);
}

// ---------------------------------------------------------------------------------------------
// Laying the candidate over the live draft, and the editor's own diff
// ---------------------------------------------------------------------------------------------

function rebaseChecks() {
    const live = { ...structured(), probe_undefined: undefined } as unknown as WorkflowDefinition;
    const sent = wire(live);
    check('JSON dropping an undefined key is still the same draft', jsonEquivalent(live, sent) && !Object.hasOwn(sent, 'probe_undefined'));
    check('an unchanged candidate is the live draft itself', rebaseAssistCandidate(live, sent) === live);

    const renamed = rebaseAssistCandidate(live, { ...sent, name: 'Renamed' }) as unknown as Row;
    check('the changed value comes from the candidate', renamed.name === 'Renamed' && renamed !== live);
    check('an undefined key the JSON dropped is kept', Object.hasOwn(renamed, 'probe_undefined') && renamed.probe_undefined === undefined);
    check('untouched parts keep their live identity', renamed.flow === live.flow && renamed.tasks === live.tasks
        && renamed.reference_inputs === live.reference_inputs);
    const withoutDescription: Row = { ...sent };
    delete withoutDescription.description;
    check('a key the model removed is not put back', !Object.hasOwn(rebaseAssistCandidate(live, withoutDescription as WorkflowDefinition), 'description'));
    const added = rebaseAssistCandidate(live, { ...sent, alert_mode: 'rules' } as WorkflowDefinition) as unknown as Row;
    check('a key the model added is taken', added.alert_mode === 'rules');

    const tasks = rebaseAssistCandidate(live, withTask(sent, 'seed-task', { instructions: 'Decide with care.' }));
    const seed = (definition: WorkflowDefinition) => definition.tasks.find((task) => task.id === 'seed-task');
    check('only the changed task is a new object', seed(tasks) !== seed(live) && seed(tasks)?.instructions === 'Decide with care.'
        && tasks.tasks.filter((task) => task.id !== 'seed-task').every((task) => live.tasks.includes(task)) && tasks.flow === live.flow);

    const four = classic(4);
    const reordered = wire(four);
    reordered.tasks = [reordered.tasks[2], reordered.tasks[0], reordered.tasks[1], reordered.tasks[3]];
    const moved = rebaseAssistCandidate(four, reordered);
    check('reordered tasks are matched by id and keep their live objects', moved.tasks.map((task) => task.id).join() === 't3,t1,t2,t4'
        && moved.tasks[0] === four.tasks[2] && moved.tasks[1] === four.tasks[0] && moved.tasks[3] === four.tasks[3]);

    const twin = { ...four, tasks: [four.tasks[0], { ...four.tasks[1], id: 't1' }] } as WorkflowDefinition;
    const twinWire = wire(twin);
    twinWire.tasks[0] = { ...twinWire.tasks[0], name: 'First' };
    const byIndex = rebaseAssistCandidate(twin, twinWire);
    check('items with duplicate ids are matched by position', byIndex.tasks[1] === twin.tasks[1] && byIndex.tasks[0].name === 'First');

    const nan = { ...four, error_handling: { strategy: 'halt', retry_count: Number.NaN } } as WorkflowDefinition;
    const nanRebased = rebaseAssistCandidate(nan, { ...wire(nan), name: 'Other' });
    check('a value JSON cannot carry is kept when the candidate did not change it',
        nanRebased.error_handling === nan.error_handling && Number.isNaN(nanRebased.error_handling.retry_count));
    check('jsonEquivalent reads undefined array items and non-finite numbers as null',
        jsonEquivalent([undefined, Number.POSITIVE_INFINITY], [null, null]) && !jsonEquivalent({ a: 1 }, { a: 1, b: 2 })
        && !jsonEquivalent({ a: 1 }, { a: '1' }));

    const enabled = rebaseAssistCandidate(four, { ...wire(four), is_enabled: !four.is_enabled });
    check('a forbidden change survives the rebase, so the editor still refuses it',
        enabled.is_enabled !== four.is_enabled && workflowAssistViolation(four, enabled) !== '');
    const { session } = openSession(four);
    const refused = session.applyAssist(enabled, { turnId: 'turn-bad', label: 'Enable it' });
    check('applyAssist refuses the forbidden change and the draft is unchanged', refused.status === 'rejected' && session.draft === four);

    check('the draft a turn was sent with is recognized, even as an equal copy', assistDraftUnchanged(four, four)
        && assistDraftUnchanged(four, structuredClone(four)) && assistDraftUnchanged(four, { ...four, tasks: [...four.tasks] })
        && !assistDraftUnchanged(four, { ...four, name: 'Changed while waiting' }));
}

function reported(key: string, patch: Partial<WorkflowAssistReportedChange> = {}): WorkflowAssistReportedChange {
    return { key, label: 'Label', ownerLabel: 'Owner', summary: `Server: ${key}`, focusKey: key, ...patch };
}

function verifyChecks() {
    const sent = classic(3);
    const candidate = wire(sent);
    candidate.name = 'Nightly review';
    candidate.tasks[1] = { ...candidate.tasks[1], instructions: 'Check each document.' };
    const rebased = rebaseAssistCandidate(sent, candidate);
    const t2 = workflowTaskKey('t2', 'instructions');
    const verification = verifyAssistChanges(sent, rebased, [reported('name', { summary: 'Workflow name' }), reported('task:ghost:name')]);
    const keys = verification.changes.map((change) => change.key);
    check('the change list is the editor diff, exactly', keys.join() === diffWorkflowChanges(sent, rebased).changes.map((change) => change.key).join()
        && keys.includes('name') && keys.includes(t2), keys);
    check('a key the server claimed that the diff did not produce is never shown',
        !keys.includes('task:ghost:name') && verification.unverified.join() === 'task:ghost:name', verification.unverified);
    const name = verification.changes.find((change) => change.key === 'name');
    const own = verification.changes.find((change) => change.key === t2);
    check('the server wording is used for a key the diff also produced', name?.summary === 'Workflow name' && name.reported);
    check('a change the server did not report is still shown, in the editor wording',
        own !== undefined && !own.reported && own.summary === workflowAssistChangeSummary(own.change), own?.summary);
    check('an answer that changes nothing shows nothing', verifyAssistChanges(sent, rebaseAssistCandidate(sent, wire(sent)), [reported('name')]).changes.length === 0);

    const flowSent = structured();
    const flowCandidate = rebaseAssistCandidate(flowSent, withTask(wire(flowSent), 'seed-task', { instructions: 'Decide with care.' }));
    const key = workflowTaskKey('seed-task', 'instructions');
    const editorChange = diffWorkflowChanges(flowSent, flowCandidate).byKey.get(key);
    const ghost = verifyAssistChanges(flowSent, flowCandidate, [reported(key, { focusKey: 'elsewhere', nodeId: 'ghost-node' })]).changes[0];
    check('a flow block the draft does not have is never used for Jump to',
        ghost?.change.target.nodeId === editorChange?.target.nodeId && ghost?.change.target.focusKey === editorChange?.target.focusKey, ghost?.change.target);
    const real = verifyAssistChanges(flowSent, flowCandidate, [reported(key, { nodeId: 'report-node' })]).changes[0];
    check('a flow block that exists is used for Jump to', real?.change.target.nodeId === 'report-node'
        && real.change.target.focusKey === editorChange?.target.focusKey);
}

// ---------------------------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------------------------

function settle(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

function threadOf(key: string): AssistThreadRecord | undefined {
    return useAssistThreadStore.getState().threads[key];
}

function doneExchange(id: string): AssistExchange {
    return { id, text: 'Make it blue', draft: draftOf('Make it blue'), status: 'done', startedAt: 1, reply: 'Done.' };
}

async function storeChecks() {
    const turns = useWorkflowAssistStore.getState();
    turns.reset();
    for (let index = 0; index < MAX_WORKFLOW_ASSIST_TURNS + 5; index += 1) {
        useWorkflowAssistStore.getState().record(`turn-${index}`, turnRecord({ instruction: `Turn ${index}` }));
    }
    const kept = useWorkflowAssistStore.getState();
    check('turn records are capped, oldest first', kept.order.length === MAX_WORKFLOW_ASSIST_TURNS
        && Object.keys(kept.turns).length === MAX_WORKFLOW_ASSIST_TURNS && !kept.turns['turn-4'] && Boolean(kept.turns['turn-5']));
    const before = useWorkflowAssistStore.getState().turns;
    useWorkflowAssistStore.getState().update('turn-9', (record) => record);
    useWorkflowAssistStore.getState().update('missing', (record) => ({ ...record, reply: 'x' }));
    check('an update that changes nothing leaves the store alone', useWorkflowAssistStore.getState().turns === before);
    useWorkflowAssistStore.getState().update('turn-9', (record) => ({ ...record, undoSequence: record.undoSequence + 1 }));
    check('an update changes one record', useWorkflowAssistStore.getState().turns['turn-9'].undoSequence === 1);
    useWorkflowAssistStore.getState().waitUntil(5000);
    useWorkflowAssistStore.getState().waitUntil(3000);
    check('a wait only ever moves later', useWorkflowAssistStore.getState().retryUntil === 5000);
    useWorkflowAssistStore.getState().reset();
    check('reset forgets everything', useWorkflowAssistStore.getState().order.length === 0 && useWorkflowAssistStore.getState().retryUntil === 0);

    // The thread's opt-ins, which default to what every other editor does.
    const store = useAssistThreadStore.getState();
    store.resetThreads();
    const key = 'workflow:new:check';
    const sends: AssistSendRequest[] = [];
    const send = async (request: AssistSendRequest): Promise<AssistSendResult> => {
        sends.push(request);
        return { ok: true, reply: 'Fine.' };
    };
    const typeInto = (text: string) => useAssistThreadStore.getState().updateThread(key, CONVERSATION, (record) => ({ ...record, draft: draftOf(text) }));
    const submit = (options: { countCodePoints?: boolean; text?: string } = {}) =>
        submitAssistDraft({ key, conversationId: CONVERSATION, mode: 'local', maxLength: 2000, send, ...options });
    typeInto(emoji(2001));
    check('2,001 emoji are not sent when counting code points', submit({ countCodePoints: true }) === null && threadOf(key)?.draft.text === emoji(2001));
    typeInto(emoji(1001));
    check('by default 1,001 emoji are still too long', submit() === null);
    typeInto(emoji(2000));
    const sentId = submit({ countCodePoints: true });
    check('2,000 emoji are sent when counting code points, and the input clears',
        sentId !== null && threadOf(key)?.draft.text === '' && threadOf(key)?.exchanges.at(-1)?.text === emoji(2000));
    await settle();
    typeInto('Keep this');
    const quick = submit({ text: 'Explain this workflow', countCodePoints: true });
    await settle();
    check('a quick action is its own message and leaves the input alone', quick !== null
        && threadOf(key)?.exchanges.at(-1)?.text === 'Explain this workflow' && threadOf(key)?.draft.text === 'Keep this'
        && sends.at(-1)?.text === 'Explain this workflow');

    // A thread an editor held never sweeps the chat's idle threads, even after it lets go.
    store.resetThreads();
    const image = 'image:conv-1:msg-1';
    const put = (target: string, conversationId: string, change: (record: AssistThreadRecord) => AssistThreadRecord) =>
        useAssistThreadStore.getState().updateThread(target, conversationId, change);
    const idleImage = () => put(image, 'conv-1', (record) => ({ ...record, exchanges: [doneExchange('img-1')] }));
    const unit = pruneThreads({ w: newThread(CONVERSATION, 1), [image]: { ...newThread('conv-1', 1), exchanges: [doneExchange('x')] } },
        'w', CONVERSATION);
    check('by default, touching a thread sweeps idle threads of other conversations', !unit[image]);
    const quiet = pruneThreads({ w: newThread(CONVERSATION, 1), [image]: { ...newThread('conv-1', 1), exchanges: [doneExchange('x')] } },
        'w', CONVERSATION, undefined, new Set(['w']));
    check('touching a quiet thread sweeps nothing', Boolean(quiet[image]));
    idleImage();
    const release = holdAssistThread('workflow:new:held');
    put('workflow:new:held', CONVERSATION, (record) => ({ ...record, draft: draftOf('typing') }));
    check('a held workflow thread does not sweep the chat image thread', Boolean(threadOf(image)));
    release();
    release();
    put('workflow:new:held', CONVERSATION, (record) => ({ ...record, exchanges: [doneExchange('late')], draft: blankDraft() }));
    check('an answer landing after the editor let go does not sweep it either', Boolean(threadOf(image)));
    const twice = holdAssistThread('workflow:new:twice');
    const again = holdAssistThread('workflow:new:twice');
    twice();
    put('workflow:new:twice', CONVERSATION, (record) => ({ ...record, draft: draftOf('x') }));
    check('a thread held twice stays held after one release', Boolean(threadOf(image)));
    again();
    put('workflow:new:plain', CONVERSATION, (record) => ({ ...record, draft: draftOf('x') }));
    check('a thread no editor held still sweeps as before', !threadOf(image));
    idleImage();
    check('the image editor still sweeps the idle released workflow thread', !threadOf('workflow:new:held') && Boolean(threadOf(image)));
    put('workflow:new:held', CONVERSATION, (record) => ({ ...record, draft: draftOf('back') }));
    check('once swept, the workflow thread is forgotten as quiet', !threadOf(image));
    store.resetThreads();
}

async function main() {
    codePointChecks();
    requestChecks();
    conversationChecks();
    turnStateChecks();
    responseChecks();
    failureChecks();
    await fetchChecks();
    rebaseChecks();
    verifyChecks();
    await storeChecks();
    if (failures) {
        console.log(`\n${failures} check(s) failed`);
        process.exitCode = 1;
    }
}

main().catch((error) => {
    console.log('FAIL  the checks threw', error instanceof Error ? error.stack : error);
    process.exitCode = 1;
});
