// test_v2_plan_references_logic.ts
// Behavioural checks for `#` documents and tags in the plan editor's Ask AI.
//
// Version: 0.261.201
// Implemented in: 0.261.201
//
// Bundled with the esbuild Vite already brings in and run under node by
// test_v2_plan_editor_references.py, like test_v2_assist_thread_logic.ts.
//
// Three things are checked. The browser's canonical form of a request's references is exactly the
// server's, case for case, from the fixture both sides read. That form is what decides whether a
// submission id is reused: a reordered or repeated selection is the same request, and a changed one
// is a new request under a new id. And the chips a message was sent with are never lost: Edit and
// resend brings them back, and so does a planner reply that did not use them.

import fixture from './fixtures/plan_reference_canonicalization.json';
import {
    REFERENCE_LABEL_LIMIT,
    REQUEST_REFERENCE_LIMIT,
    REQUEST_REFERENCE_RAW_LIMIT,
    PlanReferenceError,
    canonicalPlanReference,
    canonicalPlanReferences,
    planDraftReferences,
    sanitizeReferenceLabel,
    scopeNoticeText,
    storedTurnReferences,
    type PlanReference,
} from '../application/v2_ui/src/lib/planReferences';
import {
    choosePlanSubmissionId,
    rememberPlanSubmission,
    resetPlanSubmissions,
} from '../application/v2_ui/src/lib/planSubmissionIds';
import {
    editAssistExchange,
    planThreadKey,
    restoreAssistContext,
    settleExchange,
    submitAssistDraft,
    type AssistSendRequest,
    type AssistSendResult,
} from '../application/v2_ui/src/lib/assistThread';
import {
    blankDraft,
    useAssistThreadStore,
    type AssistThreadRecord,
} from '../application/v2_ui/src/stores/assistThreadStore';
import {
    PERSONAL_SCOPE,
    contextKey,
    groupScope,
    publicScope,
    scopeContextItem,
    type ContextAttachment,
    type ContextItem,
    type ContextScopeRef,
} from '../application/v2_ui/src/lib/chatContext';
import { buildContextToken } from '../application/v2_ui/src/lib/chatContextTokens';
import { ASSIST_INSTRUCTION_LIMITS } from '../application/v2_ui/src/lib/assistLimits';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail ?? '');
    }
}

function same(left: unknown, right: unknown): boolean {
    return JSON.stringify(left) === JSON.stringify(right);
}

/** Order-independent structural equality, for the fixture's expected objects. */
function equal(left: unknown, right: unknown): boolean {
    if (Array.isArray(left) || Array.isArray(right)) {
        return Array.isArray(left) && Array.isArray(right) && left.length === right.length
            && left.every((item, index) => equal(item, right[index]));
    }
    if (left && right && typeof left === 'object' && typeof right === 'object') {
        const a = left as Record<string, unknown>;
        const b = right as Record<string, unknown>;
        const keys = Object.keys(a);
        return keys.length === Object.keys(b).length && keys.every((key) => key in b && equal(a[key], b[key]));
    }
    return left === right;
}

interface RequestCase {
    name: string;
    input?: unknown;
    repeat?: { count: number; item: unknown };
    expected?: unknown;
    error?: { code: string; message: string };
}

function caseInput(entry: RequestCase): unknown {
    return entry.repeat ? Array.from({ length: entry.repeat.count }, () => entry.repeat!.item) : entry.input;
}

function outcome(run: () => unknown): { value?: unknown; error?: { code: string; message: string } } {
    try {
        return { value: run() };
    } catch (problem) {
        if (problem instanceof PlanReferenceError) {
            return { error: { code: problem.code, message: problem.message } };
        }
        throw problem;
    }
}

const CONVERSATION = 'conv-1';
const TURN = 'turn-1';
const planKey = planThreadKey(CONVERSATION, TURN);
const PLAN_LIMIT = ASSIST_INSTRUCTION_LIMITS.plan;
const TEAM = groupScope({ id: 'group-1', name: 'Team' });
const HANDBOOK = publicScope({ id: 'public-1', name: 'Handbook' });

function item(
    kind: 'document' | 'tag',
    id: string,
    label: string,
    scope: ContextScopeRef = PERSONAL_SCOPE,
    attachment: ContextAttachment = 'selection',
): ContextItem {
    return {
        key: contextKey(kind, id, scope),
        kind,
        id,
        label,
        token: buildContextToken(label),
        attachment,
        scope,
        origin: 'user',
    };
}

/** How the controller fingerprints an Ask request. Kept in step with orchestrationController.ts. */
function askFingerprint(references: readonly PlanReference[], instruction = 'Use these', version = 3): string {
    const action = { action: 'ask', instruction, ...(references.length ? { references } : {}) };
    return JSON.stringify({ runId: 'run-1', version, edits: undefined, action });
}

function thread(): AssistThreadRecord {
    const record = useAssistThreadStore.getState().threads[planKey];
    if (!record) {
        throw new Error('there is no plan thread');
    }
    return record;
}

function setDraft(text: string, contextItems: ContextItem[] = []) {
    useAssistThreadStore.getState().updateThread(planKey, CONVERSATION, (record) => ({
        ...record,
        draft: { ...blankDraft(), text, contextItems },
    }));
}

function settle(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

async function main() {
    /* ---- the canonical form matches the server's ---- */

    check('the label limit is the server\'s', REFERENCE_LABEL_LIMIT === fixture.label_limit);
    check('the request limit is the server\'s', REQUEST_REFERENCE_LIMIT === fixture.request_limit);
    check('a raw list is bounded before duplicates go', REQUEST_REFERENCE_RAW_LIMIT === 100);

    for (const entry of fixture.labels as { name: string; input: unknown; expected: string }[]) {
        const label = sanitizeReferenceLabel(entry.input);
        check(`label: ${entry.name}`, label === entry.expected, { label, expected: entry.expected });
    }

    let succeeded = 0;
    for (const entry of fixture.requests as RequestCase[]) {
        const result = outcome(() => canonicalPlanReferences(caseInput(entry)));
        if (entry.error) {
            check(`request: ${entry.name}`, equal(result.error, entry.error), result);
            continue;
        }
        succeeded += 1;
        check(`request: ${entry.name}`, !result.error && equal(result.value, entry.expected), result);
        const again = outcome(() => canonicalPlanReferences(result.value));
        check(`request: ${entry.name} is already canonical`, same(again.value, result.value), again);
    }
    check('the fixture has both accepted and refused requests', succeeded > 5 && succeeded < fixture.requests.length);

    /* ---- one selection, one request ---- */

    const pricing = { kind: 'document', id: 'doc-1', label: 'Pricing', scope: { kind: 'personal', id: null } };
    const roadmap = { kind: 'document', id: 'doc-2', label: 'Roadmap', scope: { kind: 'group', id: 'group-1', name: 'Team' } };
    const finance = { kind: 'tag', id: 'finance', label: 'finance', scope: { kind: 'public', id: 'public-1' } };
    const forward = canonicalPlanReferences([pricing, roadmap, finance]);
    const backward = canonicalPlanReferences([finance, roadmap, pricing, roadmap]);
    check('a reordered, repeated selection has one canonical form', same(forward, backward), { forward, backward });
    check(
        'the canonical form keeps no workspace names',
        forward.every((reference) => !('name' in reference.scope)),
    );
    check(
        'keys come out in one order whatever order they went in',
        same(canonicalPlanReference({ scope: { id: null, kind: 'personal' }, label: 'Pricing', id: 'doc-1', kind: 'document' }),
            canonicalPlanReference(pricing)),
    );
    check('the first label of a repeated reference is kept', canonicalPlanReferences([
        pricing, { ...pricing, label: 'Pricing (old)' },
    ])[0].label === 'Pricing');

    resetPlanSubmissions();
    {
        const mint = (() => {
            let next = 0;
            return () => `fresh-${(next += 1)}`;
        })();
        const sent = askFingerprint(forward);
        rememberPlanSubmission('sub-1', sent);
        check(
            'a retry with the chips reordered reuses its id',
            choosePlanSubmissionId(askFingerprint(backward), null, 'sub-1', mint) === 'sub-1',
        );
        check(
            'the held request keeps its id when the chips are reordered',
            choosePlanSubmissionId(askFingerprint(backward), { id: 'sub-1', fingerprint: sent }, 'other', mint) === 'sub-1',
        );
        const fewer = canonicalPlanReferences([pricing, finance]);
        const fewerId = choosePlanSubmissionId(askFingerprint(fewer), null, 'sub-1', mint);
        check('a chip removed before a retry means a fresh id', fewerId.startsWith('fresh-'), fewerId);
        const renamed = canonicalPlanReferences([{ ...pricing, label: 'Pricing v2' }, roadmap, finance]);
        const renamedId = choosePlanSubmissionId(askFingerprint(renamed), null, 'sub-1', mint);
        check('another label for the same document is another request', renamedId.startsWith('fresh-'), renamedId);
        const bareId = choosePlanSubmissionId(askFingerprint([]), null, 'sub-1', mint);
        check('dropping every chip is another request', bareId.startsWith('fresh-'), bareId);
        check(
            'no references and an empty list are the same request',
            askFingerprint(canonicalPlanReferences(undefined)) === askFingerprint(canonicalPlanReferences([])),
        );
        check(
            'an ask without chips carries no references field',
            !('references' in JSON.parse(askFingerprint([])).action),
        );
    }
    resetPlanSubmissions();

    /* ---- the draft's chips, as a request sends them ---- */

    {
        const chips = [
            item('document', 'doc-1', 'Pricing', PERSONAL_SCOPE, 'mention'),
            item('document', 'doc-2', 'Roadmap', TEAM),
            item('tag', 'finance', 'finance', HANDBOOK),
        ];
        const wire = planDraftReferences({ contextItems: chips });
        check('every chip is sent, mentions and selections alike', wire.length === 3);
        check(
            'a chip is sent with its kind, id, label and workspace',
            same(wire[1], { kind: 'document', id: 'doc-2', label: 'Roadmap', scope: { kind: 'group', id: 'group-1', name: 'Team' } }),
            wire[1],
        );
        check(
            'the sent chips canonicalize to the selection',
            same(canonicalPlanReferences(wire), canonicalPlanReferences([pricing, roadmap, finance])),
        );

        const workspace = scopeContextItem(TEAM);
        const refused = outcome(() => canonicalPlanReferences(planDraftReferences({ contextItems: [...chips, workspace] })));
        check(
            'a whole workspace is refused with a message, not dropped',
            refused.error?.message === 'Only documents and tags from your workspaces can be attached here.',
            refused,
        );
        const many = Array.from({ length: REQUEST_REFERENCE_LIMIT + 1 }, (_, index) => item('document', `doc-${index}`, `Doc ${index}`));
        const tooMany = outcome(() => canonicalPlanReferences(planDraftReferences({ contextItems: many })));
        check(
            'more chips than a request takes are refused',
            tooMany.error?.code === 'reference_limit'
                && tooMany.error.message === `Attach at most ${REQUEST_REFERENCE_LIMIT} documents or tags.`,
            tooMany,
        );
    }

    /* ---- what the thread shows, as text ---- */

    {
        const hostile = '<img src=x onerror=alert(1)>';
        const chips = storedTurnReferences([
            { kind: 'document', id: 'doc-1', label: hostile, scope: { kind: 'personal', id: null } },
            { kind: 'tag', id: 'finance', label: '![x](https://example.invalid/p.png)', scope: { kind: 'group', id: 'g' } },
            { kind: 'document', id: 'doc-2', label: '\u202eevil\u202c', scope: { kind: 'personal', id: null } },
            { kind: 'document', id: 'doc-3', scope: { kind: 'personal', id: null } },
            { kind: 'tag', id: 'blank', label: '   ', scope: { kind: 'personal', id: null } },
            { kind: 'scope', id: 'group-1', label: 'Team' },
            'not a chip',
            null,
        ]);
        check('stored chips of the right kinds are shown', chips.length === 5, chips);
        check('a label that looks like HTML is kept as text', chips[0]?.label === hostile);
        check('a label that looks like markdown is kept as text', chips[1]?.label === '![x](https://example.invalid/p.png)');
        check('a label cannot reorder the text around it', chips[2]?.label === 'evil');
        check('a chip with no label still says what it is', chips[3]?.label === 'Selected document' && chips[4]?.label === 'Selected tag');
        check('chip keys are unique', new Set(chips.map((chip) => chip.key)).size === chips.length);
        check('a stored list is bounded', storedTurnReferences(Array.from({ length: 50 }, (_, index) => ({
            kind: 'document', id: `d${index}`, label: `D${index}`,
        }))).length === REQUEST_REFERENCE_LIMIT);
        check('anything but a list shows no chips', storedTurnReferences({ kind: 'document' }).length === 0);

        check(
            'a first narrowing is explained',
            scopeNoticeText({ kind: 'search_limited', documents: ['Pricing', 'Roadmap'], tags: ['finance'], more: 0 })
                === 'Searches in this plan now look only at what you attached: Pricing, Roadmap and tag finance.',
        );
        check(
            'a long list says how many more',
            scopeNoticeText({ kind: 'search_limited', documents: ['Pricing'], tags: [], more: 4 })
                === 'Searches in this plan now look only at what you attached: Pricing and 4 more.',
        );
        check(
            'a notice label is text too',
            scopeNoticeText({ kind: 'search_limited', documents: [hostile], tags: [], more: 0 })?.includes(hostile) === true,
        );
        check('an unknown notice says nothing', scopeNoticeText({ kind: 'other', documents: ['A'] }) === null);
        check('an empty notice says nothing', scopeNoticeText({ kind: 'search_limited', documents: [], tags: [], more: 3 }) === null);
        check(
            'an implausible count is ignored',
            scopeNoticeText({ kind: 'search_limited', documents: ['A'], tags: [], more: 1e9 })
                === 'Searches in this plan now look only at what you attached: A.',
        );
    }

    /* ---- chips are never lost ---- */

    useAssistThreadStore.getState().resetThreads();
    {
        const calls: { request: AssistSendRequest; answer: (result: AssistSendResult) => void }[] = [];
        const send = (request: AssistSendRequest) => new Promise<AssistSendResult>((resolve) => {
            calls.push({ request, answer: resolve });
        });
        const pricingChip = item('document', 'doc-1', 'Pricing', PERSONAL_SCOPE, 'mention');
        const financeChip = item('tag', 'finance', 'finance', HANDBOOK);
        setDraft(`Compare ${pricingChip.token} with last year`, [pricingChip, financeChip]);
        const id = submitAssistDraft({
            key: planKey, conversationId: CONVERSATION, mode: 'stored', maxLength: PLAN_LIMIT, send,
        }) ?? '';
        check('a message with chips is sent', Boolean(id) && calls.length === 1);
        check('the request carries the chips it was sent with', calls[0]?.request.draft.contextItems.length === 2);
        check('sending clears the chips from the input', thread().draft.contextItems.length === 0);
        calls[0].answer({ ok: false, error: 'This document is no longer available. Remove "Pricing" and try again.' });
        await settle();

        check('edit and resend is offered for a refused reference', editAssistExchange(planKey, id));
        const restored = thread().draft;
        check('edit and resend restores the text', restored.text === `Compare ${pricingChip.token} with last year`);
        check(
            'edit and resend restores the chips',
            same(restored.contextItems.map((chip) => [chip.key, chip.attachment]), [
                [pricingChip.key, 'mention'], [financeChip.key, 'selection'],
            ]),
            restored.contextItems,
        );

        const again = submitAssistDraft({
            key: planKey, conversationId: CONVERSATION, mode: 'stored', maxLength: PLAN_LIMIT, send,
        }) ?? '';
        calls[1].answer({ ok: false, error: 'Still refused.' });
        await settle();
        const roadmapChip = item('document', 'doc-2', 'Roadmap', TEAM);
        setDraft('and the roadmap', [roadmapChip, financeChip]);
        editAssistExchange(planKey, again);
        const merged = thread().draft;
        check(
            'edit and resend keeps what is already in the input',
            merged.text === `Compare ${pricingChip.token} with last year\nand the roadmap`,
            merged.text,
        );
        check(
            '... and its chips, without repeating one',
            same(merged.contextItems.map((chip) => chip.key), [roadmapChip.key, financeChip.key, pricingChip.key]),
            merged.contextItems.map((chip) => chip.key),
        );

        setDraft('', [roadmapChip]);
        const chipsOnly = submitAssistDraft({
            key: planKey, conversationId: CONVERSATION, mode: 'stored', maxLength: PLAN_LIMIT, send,
        });
        check('chips alone are not a message', chipsOnly === null && calls.length === 2);
    }

    useAssistThreadStore.getState().resetThreads();
    {
        const notice = 'Your documents and tags are back in the input.';
        restoreAssistContext(planKey, CONVERSATION, [], notice);
        check('restoring nothing changes nothing', !useAssistThreadStore.getState().threads[planKey]);

        const typed = item('document', 'doc-2', 'Roadmap', TEAM, 'mention');
        setDraft(`Now ${typed.token}`, [typed]);
        restoreAssistContext(planKey, CONVERSATION, [
            item('document', 'doc-1', 'Pricing', PERSONAL_SCOPE, 'mention'),
            item('document', 'doc-2', 'Roadmap', TEAM, 'selection'),
        ], notice);
        const record = thread();
        check('restored chips join what the input holds', record.draft.contextItems.length === 2, record.draft.contextItems);
        check('the typed text is left alone', record.draft.text === `Now ${typed.token}`);
        check(
            'a restored chip comes back as a selection, since its # text does not',
            record.draft.contextItems.find((chip) => chip.id === 'doc-1')?.attachment === 'selection',
        );
        check(
            'a chip already in the input is not repeated',
            record.draft.contextItems.find((chip) => chip.id === 'doc-2')?.attachment === 'both',
        );
        check('the reader is told why', record.notice === notice);

        const settled = settleExchange(
            { ...record, exchanges: [{ id: 'x', text: 'Use it', draft: blankDraft(), status: 'pending', startedAt: 1 }] },
            'x',
            { ok: true },
            'stored',
        );
        check(
            'the answered exchange leaves without taking the restored chips or notice',
            settled.exchanges.length === 0 && settled.draft.contextItems.length === 2 && settled.notice === notice,
        );
    }

    if (failures) {
        console.log(`\n${failures} check(s) failed`);
        process.exit(1);
    }
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
