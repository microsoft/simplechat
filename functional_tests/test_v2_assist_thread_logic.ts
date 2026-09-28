// test_v2_assist_thread_logic.ts
// Behavioural checks for the shared AI-assist thread.
//
// Version: 0.261.196
// Implemented in: 0.261.196
//
// The V2 interface has no unit test runner, so this follows test_v2_diagram_editor_logic.ts:
// bundled with the esbuild Vite already brings in, run under node by test_v2_assist_thread.py,
// and skipped when the front-end toolchain is not installed.
//
// The thread's promise is that pressing Send never waits on the server: the message is in the
// thread and the input is empty before the request starts. The client submission id is what
// makes that safe. Every request carries it, Retry reuses it so the server replays rather than
// repeats, and the stored chat is matched against it so an exchange never shows twice.

import {
    CANCELLED_MESSAGE,
    EARLIER_APPLIED_MESSAGE,
    STALE_MESSAGE,
    blockThreadKey,
    cancelAssistExchange,
    describeDraftProblem,
    editAssistExchange,
    hasActiveAssistRequest,
    imageThreadKey,
    makeSubmissionId,
    planThreadKey,
    reconcileStoredExchanges,
    retryAssistExchange,
    settleExchange,
    submitAssistDraft,
    type AssistSendRequest,
    type AssistSendResult,
    type AssistThreadMode,
} from '../application/v2_ui/src/lib/assistThread';
import { ASSIST_INSTRUCTION_LIMITS } from '../application/v2_ui/src/lib/assistLimits';
import {
    MAX_SENT_PLAN_SUBMISSIONS,
    choosePlanSubmissionId,
    rememberPlanSubmission,
    resetPlanSubmissions,
    sentPlanSubmission,
} from '../application/v2_ui/src/lib/planSubmissionIds';
import {
    MAX_ABANDONED_IDS,
    MAX_DONE_EXCHANGES,
    MAX_SENT_IDS,
    MAX_THREADS,
    blankDraft,
    capAbandonedIds,
    capDoneExchanges,
    exchangeRetryId,
    exchangeSubmissionIds,
    isThreadIdle,
    newThread,
    pruneThreads,
    useAssistThreadStore,
    withSentId,
    type AssistExchange,
    type AssistThreadRecord,
} from '../application/v2_ui/src/stores/assistThreadStore';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail ?? '');
    }
}

const SUBMISSION_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const CONVERSATION = 'conv-1';
const LIMIT = ASSIST_INSTRUCTION_LIMITS.block;

const diagramKey = blockThreadKey(CONVERSATION, 'mermaid', 'msg-1', 0);
const chartKey = blockThreadKey(CONVERSATION, 'chart', 'msg-1', 0);
const imageKey = imageThreadKey(CONVERSATION, 'msg-1');
const planKey = planThreadKey(CONVERSATION, 'turn-1');

function draftOf(text: string) {
    return { ...blankDraft(), text };
}

function thread(key: string): AssistThreadRecord {
    const record = useAssistThreadStore.getState().threads[key];
    if (!record) {
        throw new Error(`there is no thread ${key}`);
    }
    return record;
}

function typeInto(key: string, text: string) {
    useAssistThreadStore.getState().updateThread(key, CONVERSATION, (record) => ({ ...record, draft: draftOf(text) }));
}

function reset() {
    useAssistThreadStore.getState().resetThreads();
}

/** Every pending microtask, then one more turn, so a settled request has updated its thread. */
function settle(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

interface Call {
    request: AssistSendRequest;
    answer: (result: AssistSendResult) => void;
    fail: (error: unknown) => void;
}

/** A send the checks answer by hand. Like fetch, it stops waiting when its signal aborts. */
function manualSend() {
    const calls: Call[] = [];
    const send = (request: AssistSendRequest) => new Promise<AssistSendResult>((resolve, reject) => {
        calls.push({ request, answer: resolve, fail: reject });
        request.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    });
    return { calls, send };
}

function submit(
    key: string,
    send: (request: AssistSendRequest) => Promise<AssistSendResult>,
    mode: AssistThreadMode = 'stored',
) {
    return submitAssistDraft({ key, conversationId: CONVERSATION, mode, maxLength: LIMIT, send });
}

function exchangeOf(id: string, text = 'Change it', extra: Partial<AssistExchange> = {}): AssistExchange {
    return { id, text, draft: draftOf(text), status: 'pending', startedAt: 1, ...extra };
}

function recordOf(exchanges: AssistExchange[], draft = '', abandonedIds: string[] = []): AssistThreadRecord {
    return { ...newThread(CONVERSATION, 1), exchanges, draft: draftOf(draft), abandonedIds };
}

async function main() {
    /* ---- what can be sent ---- */

    check('an empty message is refused', describeDraftProblem(draftOf(''), LIMIT) === 'empty');
    check('a message of only whitespace is refused', describeDraftProblem(draftOf('  \n\t '), LIMIT) === 'empty');
    check('a message exactly at the limit is accepted', describeDraftProblem(draftOf('x'.repeat(LIMIT)), LIMIT) === null);
    check(
        'a message one character over the limit is refused',
        describeDraftProblem(draftOf('x'.repeat(LIMIT + 1)), LIMIT) === 'too_long',
    );
    check(
        'every editor has a positive whole-number limit',
        Object.values(ASSIST_INSTRUCTION_LIMITS).every((value) => Number.isInteger(value) && value > 0),
    );

    /* ---- submission ids and thread keys ---- */

    const ids = Array.from({ length: 50 }, () => makeSubmissionId());
    check(
        'a submission id is in the form the server accepts',
        ids.every((id) => SUBMISSION_ID.test(id)),
        ids.find((id) => !SUBMISSION_ID.test(id)),
    );
    check('submission ids do not repeat', new Set(ids).size === ids.length);
    check(
        'each edited thing has a thread of its own',
        new Set([
            diagramKey,
            chartKey,
            imageKey,
            planKey,
            blockThreadKey(CONVERSATION, 'mermaid', 'msg-1', 1),
            blockThreadKey('conv-2', 'mermaid', 'msg-1', 0),
            imageThreadKey(CONVERSATION, 'msg-2'),
            planThreadKey(CONVERSATION, 'turn-2'),
        ]).size === 8,
    );

    /* ---- sending never waits on the server ---- */

    reset();
    {
        const { calls, send } = manualSend();
        typeInto(diagramKey, '  Make the boxes blue  ');
        const id = submit(diagramKey, send);
        const record = thread(diagramKey);
        const exchange = record.exchanges[0];

        check('sending returns the exchange id', typeof id === 'string' && SUBMISSION_ID.test(id));
        check(
            'the message joins the thread before the server answers',
            record.exchanges.length === 1 && exchange?.status === 'pending' && exchange.id === id,
        );
        check('the input clears before the server answers', record.draft.text === '');
        check(
            'the message is sent trimmed',
            exchange?.text === 'Make the boxes blue' && calls[0]?.request.text === 'Make the boxes blue',
        );
        check(
            'the request carries the exchange id as its submission id',
            calls.length === 1 && calls[0].request.submissionId === id,
        );
        check(
            'the request carries no transcript, so the model only sees what the server stored',
            Object.keys(calls[0]?.request ?? {}).sort().join()
                === 'draft,earlierSubmissionIds,ownSubmissionIds,signal,submissionId,text',
            Object.keys(calls[0]?.request ?? {}),
        );
        check(
            'a first request names only its own id as its own',
            calls[0]?.request.ownSubmissionIds.join() === id,
        );
        check('the request is in flight', hasActiveAssistRequest(id ?? ''));
        check('a pending exchange records when it started', (exchange?.startedAt ?? 0) > 0);

        typeInto(diagramKey, 'And make them round');
        const second = submit(diagramKey, send);
        check('a second message waits while one is pending', second === null && calls.length === 1);
        check('the message that waits stays in the input', thread(diagramKey).draft.text === 'And make them round');

        calls[0].answer({ ok: true });
        await settle();
        check('a stored thread leaves a finished exchange to the stored chat', thread(diagramKey).exchanges.length === 0);
        check('a finished request is no longer in flight', !hasActiveAssistRequest(id ?? ''));
        check('what the reader typed meanwhile is kept', thread(diagramKey).draft.text === 'And make them round');
    }

    /* ---- over the limit ---- */

    reset();
    {
        const { calls, send } = manualSend();
        const long = 'x'.repeat(LIMIT + 1);
        typeInto(diagramKey, long);
        const id = submit(diagramKey, send);
        check('an over-limit message is not sent', id === null && calls.length === 0);
        check('an over-limit message is kept whole, not cut short', thread(diagramKey).draft.text === long);
        check('an over-limit message does not join the thread', thread(diagramKey).exchanges.length === 0);

        typeInto(diagramKey, '   ');
        check('a blank message is not sent', submit(diagramKey, send) === null && calls.length === 0);
        check('nothing is sent to a thread that does not exist', submit('block:none:mermaid:x:0', send) === null);
    }

    /* ---- a thread the server does not store ---- */

    reset();
    {
        const { calls, send } = manualSend();
        typeInto(imageKey, 'Add a hat');
        const first = submit(imageKey, send, 'local');
        calls[0].answer({ ok: true, reply: 'Added a hat.' });
        await settle();
        let exchanges = thread(imageKey).exchanges;
        check(
            'a local thread keeps a finished exchange',
            exchanges.length === 1 && exchanges[0].id === first && exchanges[0].status === 'done',
        );
        check('a local thread shows what the assistant said', exchanges[0]?.reply === 'Added a hat.');

        typeInto(imageKey, 'Now a scarf');
        const second = submit(imageKey, send, 'local');
        check('a finished exchange does not hold up the next one', second !== null && calls.length === 2);
        exchanges = thread(imageKey).exchanges;
        check('the transcript keeps its order', exchanges.map((item) => item.id).join() === [first, second].join());
        calls[1].answer({ ok: true });
        await settle();
        check('a reply without text is kept as an empty reply', thread(imageKey).exchanges[1]?.reply === '');
    }

    /* ---- failure and retry ---- */

    reset();
    {
        const { calls, send } = manualSend();
        typeInto(chartKey, 'Make it a bar chart');
        const id = submit(chartKey, send) ?? '';
        calls[0].answer({ ok: false, error: 'The model is busy.' });
        await settle();
        let exchange = thread(chartKey).exchanges[0];
        check(
            'a failed exchange stays in the thread',
            exchange?.status === 'failed' && exchange.text === 'Make it a bar chart',
        );
        check('a failed exchange says why', exchange?.error === 'The model is busy.');
        check('a failure does not refill the input', thread(chartKey).draft.text === '');

        check('retry is accepted for a failed exchange', retryAssistExchange(chartKey, id, 'stored', send));
        exchange = thread(chartKey).exchanges[0];
        check('retry makes the exchange pending again', exchange?.status === 'pending' && exchange.error === undefined);
        check(
            'retry sends the same submission id, so the server replays instead of repeating',
            calls.length === 2 && calls[1].request.submissionId === id,
        );
        check(
            'retry is refused while the exchange is pending',
            !retryAssistExchange(chartKey, id, 'stored', send) && calls.length === 2,
        );

        calls[1].fail(new Error('Network down'));
        await settle();
        exchange = thread(chartKey).exchanges[0];
        check('a request that throws fails with its message', exchange?.status === 'failed' && exchange.error === 'Network down');

        retryAssistExchange(chartKey, id, 'stored', send);
        calls[2].fail('not an error object');
        await settle();
        check(
            'a request that throws something else still says it failed',
            thread(chartKey).exchanges[0]?.error === 'The request failed. Try again.',
        );

        retryAssistExchange(chartKey, id, 'stored', send);
        calls[3].answer({ ok: false, error: '' });
        await settle();
        check(
            'a failure without a reason still says it failed',
            thread(chartKey).exchanges[0]?.error === 'The request failed. Try again.',
        );

        retryAssistExchange(chartKey, id, 'stored', send);
        calls[4].answer({ ok: true });
        await settle();
        check('a successful retry leaves the stored chat to show the exchange', thread(chartKey).exchanges.length === 0);
    }

    /* ---- an id the editor chose ---- */

    reset();
    {
        const { calls, send } = manualSend();
        typeInto(planKey, 'Add a review step');
        const id = submit(planKey, send) ?? '';
        calls[0].answer({ ok: false, error: 'Try again.', submissionId: 'server-held-id' });
        await settle();
        check(
            'an id the editor sent instead is remembered',
            thread(planKey).exchanges[0]?.sentIds?.join() === [id, 'server-held-id'].join(),
            thread(planKey).exchanges[0]?.sentIds,
        );

        retryAssistExchange(planKey, id, 'stored', send);
        check('retry resends the id the server knows', calls[1]?.request.submissionId === 'server-held-id');
        check(
            'retry names every id the server may know the exchange by',
            calls[1]?.request.ownSubmissionIds.join() === [id, 'server-held-id'].join(),
        );
        check(
            'an id of the exchange itself is never named as an earlier one',
            !calls[1]?.request.earlierSubmissionIds.some((value) => value === id || value === 'server-held-id'),
        );

        // The plan changed under the failed request, so the editor had to send the retry fresh.
        calls[1].answer({ ok: false, error: 'Still busy.', submissionId: 'fresh-id' });
        await settle();
        check(
            'every id an exchange went out under is remembered, oldest first',
            thread(planKey).exchanges[0]?.sentIds?.join() === [id, 'server-held-id', 'fresh-id'].join(),
            thread(planKey).exchanges[0]?.sentIds,
        );
        retryAssistExchange(planKey, id, 'stored', send);
        check('a later retry sends the id it last went out under', calls[2]?.request.submissionId === 'fresh-id');
        calls[2].answer({ ok: false, error: 'Still busy.', submissionId: 'fresh-id' });
        await settle();
        check(
            'resending under the same id does not repeat it',
            thread(planKey).exchanges[0]?.sentIds?.join() === [id, 'server-held-id', 'fresh-id'].join(),
        );

        for (const earlier of ['server-held-id', id]) {
            const reconciled = reconcileStoredExchanges(thread(planKey), new Set([earlier]), 'stored');
            check(`the stored chat recognises an exchange by an earlier id (${earlier === id ? 'its own' : 'one it replaced'})`,
                reconciled.exchanges.length === 0);
        }

        retryAssistExchange(planKey, id, 'stored', send);
        cancelAssistExchange(planKey, id);
        await settle();
        typeInto(planKey, 'Something else');
        submit(planKey, send);
        check(
            'moving on remembers every id of the exchange left behind',
            [id, 'server-held-id', 'fresh-id'].every((value) => thread(planKey).abandonedIds.includes(value)),
            thread(planKey).abandonedIds,
        );
    }

    /* ---- how many ids an exchange remembers ---- */

    {
        let exchange = exchangeOf('first-id');
        for (let index = 0; index < MAX_SENT_IDS + 5; index += 1) {
            exchange = { ...exchange, sentIds: withSentId(exchange, `id-${index}`) };
        }
        check(
            'an exchange remembers a bounded number of ids',
            exchange.sentIds?.length === MAX_SENT_IDS
                && exchange.sentIds[MAX_SENT_IDS - 1] === `id-${MAX_SENT_IDS + 4}`,
            exchange.sentIds,
        );
        check('a retry sends the newest of them', exchangeRetryId(exchange) === `id-${MAX_SENT_IDS + 4}`);
        check(
            'the exchange is always known by its own id',
            exchangeSubmissionIds(exchange)[0] === 'first-id'
                && new Set(exchangeSubmissionIds(exchange)).size === exchangeSubmissionIds(exchange).length,
        );
        const plain = exchangeOf('plain-id');
        check('an exchange sent under its own id records nothing extra', withSentId(plain, 'plain-id') === undefined);
        check('an exchange without a reported id records nothing extra', withSentId(plain, undefined) === undefined);
        check('an exchange sent under its own id retries under it', exchangeRetryId(plain) === 'plain-id');
    }

    /* ---- the id a plan request is sent under ---- */

    resetPlanSubmissions();
    {
        let minted = 0;
        const mint = () => `minted-${++minted}`;
        const first = JSON.stringify({ runId: 'run-1', version: 1, action: { action: 'ask', instruction: 'A' } });
        const moved = JSON.stringify({ runId: 'run-1', version: 2, action: { action: 'ask', instruction: 'A' } });

        check(
            'a thread id this page never sent is used as it is',
            choosePlanSubmissionId(first, null, 'thread-id', mint) === 'thread-id' && minted === 0,
        );
        rememberPlanSubmission('thread-id', first);
        check('the request an id went out with is remembered', sentPlanSubmission('thread-id') === first);
        check(
            'the same request again keeps its id, so the server replays it',
            choosePlanSubmissionId(first, null, 'thread-id', mint) === 'thread-id' && minted === 0,
        );
        check(
            'a different request never reuses an id the server holds to another, which it would refuse for good',
            choosePlanSubmissionId(moved, null, 'thread-id', mint) === 'minted-1',
        );
        check(
            'the request the editor holds keeps its own id',
            choosePlanSubmissionId(first, { id: 'held-id', fingerprint: first }, 'thread-id', mint) === 'held-id',
        );
        check(
            'a held id for a different request is not reused',
            choosePlanSubmissionId(moved, { id: 'held-id', fingerprint: first }, undefined, mint) === 'minted-2',
        );
        check(
            'a held id for a different request gives way to the thread id',
            choosePlanSubmissionId(moved, { id: 'held-id', fingerprint: first }, 'new-thread-id', mint) === 'new-thread-id',
        );
        check('with no id to use, a fresh one is minted', choosePlanSubmissionId(first, null, undefined, mint) === 'minted-3');

        rememberPlanSubmission('thread-id', moved);
        check('an id sent again is remembered with its latest request', sentPlanSubmission('thread-id') === moved);

        resetPlanSubmissions();
        for (let index = 0; index <= MAX_SENT_PLAN_SUBMISSIONS; index += 1) {
            rememberPlanSubmission(`sent-${index}`, first);
        }
        check(
            'the page remembers a bounded number of sent ids, forgetting the oldest',
            sentPlanSubmission('sent-0') === undefined
                && sentPlanSubmission(`sent-${MAX_SENT_PLAN_SUBMISSIONS}`) === first
                && sentPlanSubmission('sent-1') === first,
        );
        resetPlanSubmissions();
    }

    /* ---- cancel ---- */

    reset();
    {
        const { calls, send } = manualSend();
        typeInto(diagramKey, 'A slow change');
        const id = submit(diagramKey, send) ?? '';
        const signal = calls[0].request.signal;
        cancelAssistExchange(diagramKey, id);
        const exchange = thread(diagramKey).exchanges[0];
        check('cancel shows at once', exchange?.status === 'cancelled' && exchange.error === CANCELLED_MESSAGE);
        check('cancel aborts the browser request at once', signal.aborted);
        check(
            'a cancelled id is remembered, since the server may still finish it',
            thread(diagramKey).abandonedIds.includes(id),
        );
        await settle();
        check('the aborted request is no longer in flight', !hasActiveAssistRequest(id));
        check(
            'the aborted request does not overwrite the cancelled turn',
            thread(diagramKey).exchanges[0]?.status === 'cancelled',
        );

        check('retry is accepted for a cancelled exchange', retryAssistExchange(diagramKey, id, 'stored', send));
        check('a retried id is no longer treated as abandoned', !thread(diagramKey).abandonedIds.includes(id));
        check('a retried request does not name itself as an earlier one', !calls[1].request.earlierSubmissionIds.includes(id));
        cancelAssistExchange(diagramKey, id);
        await settle();

        typeInto(diagramKey, 'Something else');
        const next = submit(diagramKey, send) ?? '';
        const record = thread(diagramKey);
        check(
            'sending again moves the cancelled exchange out of the thread',
            record.exchanges.length === 1 && record.exchanges[0].id === next,
        );
        check(
            'the next request names the cancelled one, so a late result is recognised as the reader\'s',
            calls[2].request.earlierSubmissionIds.includes(id),
        );
        check('the next request does not name itself', !calls[2].request.earlierSubmissionIds.includes(next));

        // A shared chat can deliver the stored turns before this page's own reply arrives.
        useAssistThreadStore.getState().updateThread(
            diagramKey,
            CONVERSATION,
            (current) => reconcileStoredExchanges(current, new Set([id, next]), 'stored'),
        );
        const after = thread(diagramKey);
        check('a stored id is no longer treated as unanswered', !after.abandonedIds.includes(id));
        check(
            'a pending exchange stays until its own reply lands, even once the stored chat has it',
            after.exchanges.length === 1 && after.exchanges[0].status === 'pending',
        );
        calls[2].answer({ ok: true });
        await settle();
        check('its reply then settles it', thread(diagramKey).exchanges.length === 0);
    }

    /* ---- a cancel the server carries out ---- */

    reset();
    {
        const { calls, send } = manualSend();
        let cancels = 0;
        let finishCancel: () => void = () => undefined;
        const cancel = () => {
            cancels += 1;
            return new Promise<void>((resolve) => {
                finishCancel = resolve;
            });
        };
        typeInto(planKey, 'Remove step two');
        const id = submit(planKey, send) ?? '';
        cancelAssistExchange(planKey, id, cancel);
        await settle();
        let exchange = thread(planKey).exchanges[0];
        check(
            'a server cancel keeps the exchange pending until it is answered',
            exchange?.status === 'pending' && exchange.cancelling === true,
        );
        check('the server cancel is asked for once', cancels === 1);
        cancelAssistExchange(planKey, id, cancel);
        await settle();
        check('a second cancel while one is under way is ignored', cancels === 1);
        check('a server cancel leaves the request to end on its own', !calls[0].request.signal.aborted);

        typeInto(planKey, 'Typed while waiting');
        calls[0].answer({ ok: false, error: 'dropped', stale: true });
        await settle();
        exchange = thread(planKey).exchanges[0];
        check(
            'a request the reader cancelled reads as cancelled, not failed',
            exchange?.status === 'cancelled' && exchange.error === CANCELLED_MESSAGE,
        );
        check('what the reader typed meanwhile is kept', thread(planKey).draft.text === 'Typed while waiting');
        finishCancel();
        await settle();
        check('the finished cancel leaves the settled exchange alone', thread(planKey).exchanges[0]?.status === 'cancelled');
    }

    reset();
    {
        const { calls, send } = manualSend();
        typeInto(planKey, 'Rename the plan');
        const id = submit(planKey, send) ?? '';
        cancelAssistExchange(planKey, id, () => Promise.reject(new Error('cancel failed')));
        await settle();
        const exchange = thread(planKey).exchanges[0];
        check(
            'a server cancel that fails lets the reader cancel again',
            exchange?.status === 'pending' && !exchange.cancelling,
        );
        calls[0].answer({ ok: true });
        await settle();
    }

    reset();
    {
        const { calls, send } = manualSend();
        typeInto(planKey, 'Merge the last two steps');
        const id = submit(planKey, send) ?? '';
        cancelAssistExchange(planKey, id, () => Promise.resolve());
        calls[0].answer({ ok: false, error: 'dropped', stale: true });
        await settle();
        check(
            'a cancelled request goes back into an empty input',
            thread(planKey).exchanges.length === 0 && thread(planKey).draft.text === 'Merge the last two steps',
        );
    }

    /* ---- edit and resend ---- */

    reset();
    {
        const { calls, send } = manualSend();
        typeInto(chartKey, 'Use a log scale');
        const id = submit(chartKey, send) ?? '';
        check('a pending exchange cannot be edited', !editAssistExchange(chartKey, id));
        calls[0].answer({ ok: false, error: 'No.' });
        await settle();

        check('edit and resend is accepted for a failed exchange', editAssistExchange(chartKey, id));
        const record = thread(chartKey);
        check('edit and resend takes the exchange out of the thread', record.exchanges.length === 0);
        check('edit and resend puts the text back in the input', record.draft.text === 'Use a log scale');
        check(
            'its id is remembered, in case the failed request was applied after all',
            record.abandonedIds.includes(id),
        );

        const again = submit(chartKey, send) ?? '';
        check(
            'the edited message is sent under a new submission id',
            again !== id && calls[1]?.request.submissionId === again,
        );
        check('... and names the one it replaces', calls[1]?.request.earlierSubmissionIds.includes(id));
        calls[1].answer({ ok: false, error: 'Still no.' });
        await settle();
        typeInto(chartKey, 'and label the axes');
        editAssistExchange(chartKey, again);
        check(
            'edit and resend keeps what is already in the input',
            thread(chartKey).draft.text === 'Use a log scale\nand label the axes',
        );
    }

    /* ---- how an exchange ends ---- */

    {
        const base = recordOf([exchangeOf('a')]);
        check('settling an unknown exchange changes nothing', settleExchange(base, 'missing', { ok: true }, 'stored') === base);

        const recorded = settleExchange(base, 'a', { ok: false, error: '', stale: true, recorded: true }, 'stored');
        check('a dropped request the server recorded leaves the thread', recorded.exchanges.length === 0);

        const staleEmpty = settleExchange(base, 'a', { ok: false, error: '', stale: true }, 'stored');
        check(
            'a dropped request goes back into an empty input',
            staleEmpty.exchanges.length === 0 && staleEmpty.draft.text === 'Change it',
        );

        const staleTyped = settleExchange(recordOf([exchangeOf('a')], 'new words'), 'a', {
            ok: false, error: '', stale: true,
        }, 'stored');
        check(
            'a dropped request stays in the thread when the input is in use',
            staleTyped.exchanges[0]?.status === 'failed'
                && staleTyped.exchanges[0].error === STALE_MESSAGE
                && staleTyped.draft.text === 'new words',
        );

        const staleCancelling = settleExchange(
            recordOf([exchangeOf('a', 'Change it', { cancelling: true })], 'new words'),
            'a',
            { ok: false, error: '', stale: true },
            'stored',
        );
        check(
            'a dropped request the reader cancelled reads as cancelled',
            staleCancelling.exchanges[0]?.status === 'cancelled'
                && staleCancelling.exchanges[0].error === CANCELLED_MESSAGE,
        );

        const earlierEmpty = settleExchange(base, 'a', { ok: false, error: '', earlierApplied: true }, 'stored');
        check(
            'when a cancelled change landed first, the refused message returns to the input with a notice',
            earlierEmpty.exchanges.length === 0
                && earlierEmpty.draft.text === 'Change it'
                && earlierEmpty.notice === EARLIER_APPLIED_MESSAGE,
        );

        const earlierTyped = settleExchange(recordOf([exchangeOf('a')], 'new words'), 'a', {
            ok: false, error: '', earlierApplied: true,
        }, 'stored');
        check(
            '... and stays in the thread when the input is in use',
            earlierTyped.exchanges[0]?.status === 'failed'
                && earlierTyped.exchanges[0].error === EARLIER_APPLIED_MESSAGE
                && earlierTyped.draft.text === 'new words',
        );

        const cancelled = exchangeOf('a', 'Change it', { status: 'cancelled', error: CANCELLED_MESSAGE });
        const succeeded = settleExchange(recordOf([cancelled], '', ['a']), 'a', { ok: true }, 'stored');
        check(
            'a cancelled request that succeeds anyway is settled and no longer abandoned',
            succeeded.exchanges.length === 0 && !succeeded.abandonedIds.includes('a'),
        );

        const abortedAfterCancel = recordOf([cancelled]);
        check(
            'an abort after a cancel changes nothing',
            settleExchange(abortedAfterCancel, 'a', { ok: false, error: '', aborted: true }, 'stored') === abortedAfterCancel,
        );

        const aborted = settleExchange(base, 'a', { ok: false, error: '', aborted: true }, 'stored');
        check(
            'an abort shows as cancelled',
            aborted.exchanges[0]?.status === 'cancelled' && aborted.exchanges[0].error === CANCELLED_MESSAGE,
        );

        const localDone = settleExchange(base, 'a', { ok: true, reply: 'Done.', submissionId: 'other-id' }, 'local');
        check(
            'a local success records the reply and the id the editor sent',
            localDone.exchanges[0]?.status === 'done'
                && localDone.exchanges[0].reply === 'Done.'
                && localDone.exchanges[0].sentIds?.join() === 'a,other-id',
        );
    }

    /* ---- the stored chat ---- */

    {
        const failed = exchangeOf('f', 'x', { status: 'failed', error: 'e' });
        const cancelled = exchangeOf('c', 'x', { status: 'cancelled', error: CANCELLED_MESSAGE });
        const pending = exchangeOf('p');
        const done = exchangeOf('d', 'x', { status: 'done', reply: 'r' });
        const record = recordOf([failed, cancelled, pending], '', ['c', 'older']);

        check('nothing stored changes nothing', reconcileStoredExchanges(record, new Set(), 'stored') === record);
        check(
            'stored ids of other exchanges change nothing',
            reconcileStoredExchanges(record, new Set(['someone-else']), 'stored') === record,
        );

        const stored = reconcileStoredExchanges(record, new Set(['f', 'c', 'p']), 'stored');
        check('a failed exchange the server stored after all leaves the thread', !stored.exchanges.some((item) => item.id === 'f'));
        check('a cancelled exchange the server stored leaves the thread', !stored.exchanges.some((item) => item.id === 'c'));
        check('a pending exchange waits for its own reply', stored.exchanges.some((item) => item.id === 'p'));
        check('a stored id is no longer abandoned', stored.abandonedIds.join() === 'older');

        const local = reconcileStoredExchanges(recordOf([done, failed], '', ['f']), new Set(['d', 'f']), 'local');
        check('a local thread keeps its transcript', local.exchanges.length === 2);
        check('a local thread still forgets abandoned ids the server stored', local.abandonedIds.length === 0);
    }

    /* ---- what is kept in memory ---- */

    {
        const done = Array.from({ length: MAX_DONE_EXCHANGES + 5 }, (_, index) =>
            exchangeOf(`d${index}`, 'x', { status: 'done', reply: '' }));
        const failed = exchangeOf('f', 'x', { status: 'failed', error: 'e' });
        const capped = capDoneExchanges([...done.slice(0, 3), failed, ...done.slice(3)]);
        check(
            'only the most recent finished exchanges are kept',
            capped.filter((item) => item.status === 'done').length === MAX_DONE_EXCHANGES
                && capped.some((item) => item.id === `d${MAX_DONE_EXCHANGES + 4}`)
                && !capped.some((item) => item.id === 'd0'),
        );
        check('an exchange that needs attention is never dropped', capped.some((item) => item.id === 'f'));
        const few = done.slice(0, 3);
        check('a short transcript is left as it is', capDoneExchanges(few) === few);

        const manyIds = Array.from({ length: MAX_ABANDONED_IDS + 3 }, (_, index) => `id${index}`);
        const cappedIds = capAbandonedIds(manyIds);
        check(
            'abandoned ids are capped, keeping the latest',
            cappedIds.length === MAX_ABANDONED_IDS
                && cappedIds[cappedIds.length - 1] === `id${MAX_ABANDONED_IDS + 2}`
                && !cappedIds.includes('id0'),
        );
        check('abandoned ids are not repeated', capAbandonedIds(['a', 'a', 'b']).join() === 'a,b');

        check('a thread with only finished exchanges is idle', isThreadIdle(recordOf([done[0]])));
        check('a thread with unsent text is not idle', !isThreadIdle(recordOf([], 'unsent')));
        check('a thread with a notice is not idle', !isThreadIdle({ ...recordOf([]), notice: EARLIER_APPLIED_MESSAGE }));
        check('a thread with a failed exchange is not idle', !isThreadIdle(recordOf([failed])));

        const threads: Record<string, AssistThreadRecord> = {
            'image:old:m': { ...newThread('old', 1), exchanges: [done[0]] },
            'block:old:mermaid:m:0': { ...newThread('old', 2), draft: draftOf('unsent') },
            'block:old:chart:m:0': { ...newThread('old', 3), exchanges: [exchangeOf('p')] },
            'block:old:chart:m:1': { ...newThread('old', 4), exchanges: [failed] },
            'block:conv-1:mermaid:m:0': newThread(CONVERSATION, 5),
        };
        const pruned = pruneThreads(threads, 'block:conv-1:mermaid:m:0', CONVERSATION);
        check('an idle thread of another conversation is dropped', !('image:old:m' in pruned));
        check('unsent text in another conversation is kept', 'block:old:mermaid:m:0' in pruned);
        check('a request in flight in another conversation is kept', 'block:old:chart:m:0' in pruned);
        check('a failed exchange in another conversation is kept', 'block:old:chart:m:1' in pruned);
        check('the thread in use is kept', 'block:conv-1:mermaid:m:0' in pruned);

        const crowded: Record<string, AssistThreadRecord> = {};
        for (let index = 0; index < MAX_THREADS + 5; index += 1) {
            crowded[`t${index}`] = {
                ...newThread(CONVERSATION, index),
                draft: draftOf('keep'),
                exchanges: index < 3 ? [exchangeOf(`p${index}`)] : [],
            };
        }
        const trimmed = pruneThreads(crowded, `t${MAX_THREADS + 4}`, CONVERSATION);
        check('past the cap, threads are dropped down to it', Object.keys(trimmed).length === MAX_THREADS);
        check('a thread with a request in flight is never dropped', ['t0', 't1', 't2'].every((key) => key in trimmed));
        check(
            'the least recently used threads go first',
            !('t3' in trimmed) && !('t7' in trimmed) && 't8' in trimmed,
        );
        const calm = { a: newThread(CONVERSATION, 1) };
        check('a store with nothing to drop is left as it is', pruneThreads(calm, 'a', CONVERSATION) === calm);
    }

    /* ---- the store ---- */

    reset();
    {
        useAssistThreadStore.getState().updateThread('nothing', CONVERSATION, (record) => record);
        check('a change that changes nothing creates no thread', !('nothing' in useAssistThreadStore.getState().threads));
        typeInto(diagramKey, 'hello');
        const before = useAssistThreadStore.getState().threads;
        useAssistThreadStore.getState().updateThread(diagramKey, CONVERSATION, (record) => record);
        check('a change that changes nothing leaves the store alone', useAssistThreadStore.getState().threads === before);
        reset();
        check('resetting forgets every thread', Object.keys(useAssistThreadStore.getState().threads).length === 0);
    }
}

main().then(
    () => {
        console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} check(s) failed.`);
        process.exit(failures === 0 ? 0 : 1);
    },
    (error) => {
        console.log('FAIL  the checks stopped early', error);
        process.exit(1);
    },
);
