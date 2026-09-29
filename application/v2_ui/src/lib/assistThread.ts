// assistThread.ts
//
// The shared AI-assist thread: what happens between pressing Send in an editor's Ask tab and the
// answer arriving, for the diagram, chart, image and plan editors alike.
//
// Pressing Send moves the message into the thread at once, clears the input and shows a pending
// reply that can be cancelled. The answer fills that reply in. A failure stays in the thread with
// Retry and Edit and resend, and nothing the reader typed is lost.
//
// Every exchange carries a client submission id. The server stores it on both turns it records,
// so a thread recognises its own exchanges in the stored chat and never shows one twice. It also
// makes Retry safe, because a retried id the server already answered is replayed rather than run
// again. The requests run here, outside React, so an answer still lands after its editor closed.

import {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    type Dispatch,
    type RefObject,
    type SetStateAction,
} from 'react';
import type { ComposerDraft } from './composerDraft';
import { addContextItem, type ContextItem } from './chatContext';
import { reconcileContextItems } from './chatContextTokens';
import {
    blankDraft,
    capAbandonedIds,
    capDoneExchanges,
    draftHasContent,
    exchangeRetryId,
    exchangeSubmissionIds,
    selectAssistThread,
    useAssistThreadStore,
    withSentId,
    type AssistExchange,
    type AssistThreadRecord,
} from '../stores/assistThreadStore';

export type { AssistExchange } from '../stores/assistThreadStore';

/**
 * How a thread relates to what the server stores.
 *
 * `stored`: the server records each exchange and the editor shows the stored chat, so a finished
 * exchange leaves the thread. `local`: the thread is the only transcript, so it keeps finished
 * exchanges until the editor's page is gone.
 */
export type AssistThreadMode = 'stored' | 'local';

/** What an editor is handed to send one exchange. */
export interface AssistSendRequest {
    /** The instruction, trimmed. */
    text: string;
    draft: ComposerDraft;
    submissionId: string;
    /** Every id the server may know this exchange by, `submissionId` among them. */
    ownSubmissionIds: readonly string[];
    signal: AbortSignal;
    /** Ids of this thread's exchanges the reader cancelled or moved on from. */
    earlierSubmissionIds: readonly string[];
}

export type AssistSendResult =
    | {
          ok: true;
          /** What the assistant said, for a local thread. */
          reply?: string;
          /** The id the editor actually sent, when it chose a different one. */
          submissionId?: string;
      }
    | {
          ok: false;
          error: string;
          /** The reader cancelled and the browser stopped waiting. */
          aborted?: boolean;
          /** The editor dropped the request, because it was cancelled or the editor moved on. */
          stale?: boolean;
          /** With `stale`: the server holds the exchange in the stored chat after all. */
          recorded?: boolean;
          /** Refused because an earlier cancelled request finished first, and is now showing. */
          earlierApplied?: boolean;
          submissionId?: string;
      };

export type AssistSend = (request: AssistSendRequest) => Promise<AssistSendResult>;

/** A stored chat turn, read only for its submission id. */
export interface AssistStoredTurn {
    submission_id?: string | null;
}

export const CANCELLED_MESSAGE =
    'Cancelled. The change may still be applied if the server had already started it.';
export const STALE_MESSAGE =
    'This request did not finish. Check the saved result, then send it again if you still want the change.';
export const EARLIER_APPLIED_MESSAGE =
    'Your earlier request finished after you cancelled it. The latest version is shown. '
    + 'Send again if you still want this change.';

const SUBMISSION_ID_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;

/** A fresh client submission id, in the form the server accepts. */
export function makeSubmissionId(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        const id = crypto.randomUUID();
        if (SUBMISSION_ID_PATTERN.test(id)) {
            return id;
        }
    }
    return `assist-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function blockThreadKey(
    conversationId: string,
    blockKind: string,
    messageId: string,
    blockIndex: number,
): string {
    return `block:${conversationId}:${blockKind}:${messageId}:${blockIndex}`;
}

export function imageThreadKey(conversationId: string, messageId: string): string {
    return `image:${conversationId}:${messageId}`;
}

export function planThreadKey(conversationId: string, turnId: string): string {
    return `plan:${conversationId}:${turnId}`;
}

/** Why a message could not be sent. */
export type AssistSendProblem = 'empty' | 'too_long' | 'pending';

export function describeDraftProblem(
    draft: ComposerDraft,
    maxLength: number,
): Exclude<AssistSendProblem, 'pending'> | null {
    if (!draft.text.trim()) {
        return 'empty';
    }
    return draft.text.length > maxLength ? 'too_long' : null;
}

/** Browser requests of this page's threads, by exchange id. */
const controllers = new Map<string, AbortController>();

function readThread(key: string): AssistThreadRecord | null {
    return selectAssistThread(useAssistThreadStore.getState(), key);
}

function updateThread(
    key: string,
    conversationId: string | null,
    change: (record: AssistThreadRecord) => AssistThreadRecord,
): void {
    useAssistThreadStore.getState().updateThread(key, conversationId, change);
}

function replaceExchange(
    record: AssistThreadRecord,
    id: string,
    change: (exchange: AssistExchange) => AssistExchange,
): AssistThreadRecord {
    let changed = false;
    const exchanges = record.exchanges.map((exchange) => {
        if (exchange.id !== id) {
            return exchange;
        }
        const next = change(exchange);
        changed = changed || next !== exchange;
        return next;
    });
    return changed ? { ...record, exchanges } : record;
}

function withoutIds(ids: string[], remove: readonly string[]): string[] {
    const next = ids.filter((id) => !remove.includes(id));
    return next.length === ids.length ? ids : next;
}

/** Put an exchange's text and chips back in the input without losing what is there now. */
function restoreDraft(current: ComposerDraft, exchange: AssistExchange): ComposerDraft {
    if (!draftHasContent(current)) {
        return exchange.draft;
    }
    const text = current.text.trim() ? `${exchange.text}\n${current.text}` : exchange.text;
    const merged = exchange.draft.contextItems.reduce<ContextItem[]>(
        (items, item) => addContextItem(items, item), [...current.contextItems],
    );
    return { ...current, text, contextItems: reconcileContextItems(text, merged) };
}

/**
 * Apply how an exchange ended to its thread. Pure, so the rules can be tested on their own.
 */
export function settleExchange(
    record: AssistThreadRecord,
    id: string,
    result: AssistSendResult,
    mode: AssistThreadMode,
): AssistThreadRecord {
    const exchange = record.exchanges.find((item) => item.id === id);
    if (!exchange) {
        return record;
    }
    const ids = result.submissionId ? [...exchangeSubmissionIds(exchange), result.submissionId]
        : exchangeSubmissionIds(exchange);
    const remove = (): AssistThreadRecord => ({
        ...record,
        exchanges: record.exchanges.filter((item) => item.id !== id),
        abandonedIds: withoutIds(record.abandonedIds, ids),
    });
    const sentIds = withSentId(exchange, result.submissionId);

    if (result.ok) {
        // A success also settles an exchange the reader cancelled: the change happened.
        if (mode === 'stored') {
            return remove();
        }
        return {
            ...record,
            abandonedIds: withoutIds(record.abandonedIds, ids),
            exchanges: capDoneExchanges(record.exchanges.map((item) => item.id === id ? {
                ...item,
                sentIds,
                status: 'done',
                reply: result.reply ?? '',
                error: undefined,
                cancelling: false,
            } : item)),
        };
    }
    if (result.aborted) {
        return exchange.status === 'cancelled' ? record : replaceExchange(record, id, (item) => ({
            ...item, sentIds, status: 'cancelled', error: CANCELLED_MESSAGE, cancelling: false,
        }));
    }
    if (result.stale) {
        if (result.recorded) {
            return remove();
        }
        if (!draftHasContent(record.draft)) {
            return { ...remove(), draft: exchange.draft };
        }
        // The reader asked for this, so it reads as cancelled rather than as a failure.
        return replaceExchange(record, id, (item) => ({
            ...item,
            sentIds,
            status: item.cancelling ? 'cancelled' : 'failed',
            error: item.cancelling ? CANCELLED_MESSAGE : STALE_MESSAGE,
            cancelling: false,
        }));
    }
    if (result.earlierApplied) {
        if (!draftHasContent(record.draft)) {
            return { ...remove(), draft: exchange.draft, notice: EARLIER_APPLIED_MESSAGE };
        }
        return replaceExchange(record, id, (item) => ({
            ...item, sentIds, status: 'failed', error: EARLIER_APPLIED_MESSAGE, cancelling: false,
        }));
    }
    return replaceExchange(record, id, (item) => ({
        ...item,
        sentIds,
        status: 'failed',
        error: result.error || 'The request failed. Try again.',
        cancelling: false,
    }));
}

/** Remove what the stored chat now holds, and stop treating stored ids as unanswered. */
export function reconcileStoredExchanges(
    record: AssistThreadRecord,
    storedIds: ReadonlySet<string>,
    mode: AssistThreadMode,
): AssistThreadRecord {
    if (!storedIds.size) {
        return record;
    }
    const abandonedIds = record.abandonedIds.filter((id) => !storedIds.has(id));
    const exchanges = mode === 'stored'
        ? record.exchanges.filter((exchange) => exchange.status === 'pending'
            || !exchangeSubmissionIds(exchange).some((value) => storedIds.has(value)))
        : record.exchanges;
    if (abandonedIds.length === record.abandonedIds.length && exchanges.length === record.exchanges.length) {
        return record;
    }
    return { ...record, abandonedIds, exchanges };
}

async function runExchange(
    key: string,
    id: string,
    mode: AssistThreadMode,
    send: AssistSend,
): Promise<void> {
    const record = readThread(key);
    const exchange = record?.exchanges.find((item) => item.id === id);
    if (!record || !exchange || exchange.status !== 'pending') {
        return;
    }
    const controller = new AbortController();
    controllers.set(id, controller);
    const submissionId = exchangeRetryId(exchange);
    const own = exchangeSubmissionIds(exchange);
    let result: AssistSendResult;
    try {
        result = await send({
            text: exchange.text,
            draft: exchange.draft,
            submissionId,
            ownSubmissionIds: own,
            signal: controller.signal,
            earlierSubmissionIds: record.abandonedIds.filter((value) => !own.includes(value)),
        });
    } catch (error) {
        result = controller.signal.aborted
            ? { ok: false, error: '', aborted: true }
            : { ok: false, error: error instanceof Error && error.message ? error.message : 'The request failed. Try again.' };
    } finally {
        if (controllers.get(id) === controller) {
            controllers.delete(id);
        }
    }
    updateThread(key, record.conversationId, (current) => settleExchange(current, id, result, mode));
}

export interface AssistSubmitOptions {
    key: string;
    conversationId: string | null;
    mode: AssistThreadMode;
    maxLength: number;
    send: AssistSend;
}

/**
 * Send what the thread's input holds.
 *
 * The message joins the thread and the input clears before the request starts. Failed and
 * cancelled exchanges leave the thread when the reader moves on, and their ids are remembered in
 * case the server finished them after all.
 */
export function submitAssistDraft(options: AssistSubmitOptions): string | null {
    const record = readThread(options.key);
    const draft = record?.draft ?? blankDraft();
    if (describeDraftProblem(draft, options.maxLength)
        || record?.exchanges.some((exchange) => exchange.status === 'pending')) {
        return null;
    }
    const id = makeSubmissionId();
    const exchange: AssistExchange = {
        id,
        text: draft.text.trim(),
        draft,
        status: 'pending',
        startedAt: Date.now(),
    };
    updateThread(options.key, options.conversationId, (current) => {
        const moving = current.exchanges.filter((item) => item.status === 'failed' || item.status === 'cancelled');
        return {
            ...current,
            conversationId: current.conversationId ?? options.conversationId,
            exchanges: [
                ...current.exchanges.filter((item) => item.status === 'done' || item.status === 'pending'),
                exchange,
            ],
            abandonedIds: capAbandonedIds([
                ...current.abandonedIds,
                ...moving.flatMap((item) => exchangeSubmissionIds(item)),
            ]),
            draft: blankDraft(),
            notice: null,
        };
    });
    void runExchange(options.key, id, options.mode, options.send);
    return id;
}

/** Send a failed or cancelled exchange again, under the same submission id. */
export function retryAssistExchange(
    key: string,
    id: string,
    mode: AssistThreadMode,
    send: AssistSend,
): boolean {
    const record = readThread(key);
    const exchange = record?.exchanges.find((item) => item.id === id);
    if (!record || !exchange || (exchange.status !== 'failed' && exchange.status !== 'cancelled')
        || record.exchanges.some((item) => item.status === 'pending')) {
        return false;
    }
    updateThread(key, record.conversationId, (current) => ({
        ...replaceExchange(current, id, (item) => ({
            ...item, status: 'pending', startedAt: Date.now(), error: undefined, cancelling: false,
        })),
        abandonedIds: withoutIds(current.abandonedIds, exchangeSubmissionIds(exchange)),
        notice: null,
    }));
    void runExchange(key, id, mode, send);
    return true;
}

/**
 * Stop waiting for a pending exchange.
 *
 * By default the browser stops waiting and the exchange shows as cancelled, because the server
 * may still finish the change. An editor that can truly cancel on the server passes its own
 * cancel, and the exchange then settles however that request ends.
 */
export function cancelAssistExchange(
    key: string,
    id: string,
    cancel?: (exchange: AssistExchange) => unknown,
): void {
    const record = readThread(key);
    const exchange = record?.exchanges.find((item) => item.id === id);
    if (!record || !exchange || exchange.status !== 'pending' || exchange.cancelling) {
        return;
    }
    if (cancel) {
        updateThread(key, record.conversationId, (current) =>
            replaceExchange(current, id, (item) => ({ ...item, cancelling: true })));
        void Promise.resolve()
            .then(() => cancel(exchange))
            .catch(() => undefined)
            .then(() => updateThread(key, record.conversationId, (current) =>
                replaceExchange(current, id, (item) =>
                    item.status === 'pending' && item.cancelling ? { ...item, cancelling: false } : item)));
        return;
    }
    updateThread(key, record.conversationId, (current) => ({
        ...replaceExchange(current, id, (item) => ({
            ...item, status: 'cancelled', error: CANCELLED_MESSAGE, cancelling: false,
        })),
        abandonedIds: capAbandonedIds([...current.abandonedIds, ...exchangeSubmissionIds(exchange)]),
    }));
    controllers.get(id)?.abort();
}

/** Take a failed or cancelled exchange out of the thread and put its text back in the input. */
export function editAssistExchange(key: string, id: string): boolean {
    const record = readThread(key);
    const exchange = record?.exchanges.find((item) => item.id === id);
    if (!record || !exchange || exchange.status === 'pending') {
        return false;
    }
    updateThread(key, record.conversationId, (current) => ({
        ...current,
        exchanges: current.exchanges.filter((item) => item.id !== id),
        abandonedIds: exchange.status === 'done' ? current.abandonedIds
            : capAbandonedIds([...current.abandonedIds, ...exchangeSubmissionIds(exchange)]),
        draft: restoreDraft(current.draft, exchange),
    }));
    return true;
}

/**
 * Put chips back in a thread's input, beside whatever it holds now.
 *
 * For an editor whose answer did not use the chips it was sent with, so they are not lost. They
 * come back as selections, because their `#` text is not restored with them.
 */
export function restoreAssistContext(
    key: string,
    conversationId: string | null,
    items: readonly ContextItem[],
    notice?: string,
): void {
    if (!items.length) {
        return;
    }
    updateThread(key, conversationId, (current) => ({
        ...current,
        draft: {
            ...current.draft,
            contextItems: items.reduce<ContextItem[]>(
                (merged, item) => addContextItem(merged, { ...item, attachment: 'selection' }),
                [...current.draft.contextItems],
            ),
        },
        notice: notice ?? current.notice,
    }));
}

/** Whether a request of this page is still waiting on the network. For tests. */
export function hasActiveAssistRequest(id: string): boolean {
    return controllers.has(id);
}

export interface UseAssistThreadOptions {
    /** Which thread. Null while the editor has nothing it could send to. */
    key: string | null;
    conversationId: string | null;
    mode: AssistThreadMode;
    maxLength: number;
    /** The editor's stored chat, read only for submission ids. */
    storedTurns?: readonly AssistStoredTurn[] | null;
    /** Read when a request starts, so it always uses the editor's latest state. */
    send: AssistSend;
    /** Replaces the default cancel, which only stops the browser waiting. */
    cancel?: (exchange: AssistExchange) => unknown;
}

export interface AssistThreadController {
    key: string | null;
    mode: AssistThreadMode;
    /** The exchanges to show: stored ones are left to the stored chat. */
    exchanges: AssistExchange[];
    pending: AssistExchange | null;
    draft: ComposerDraft;
    setDraft: Dispatch<SetStateAction<ComposerDraft>>;
    notice: string | null;
    dismissNotice: () => void;
    maxLength: number;
    length: number;
    overLimit: boolean;
    /** Submission ids of every exchange this page sent, stored or not. */
    ownSubmissionIds: ReadonlySet<string>;
    inputRef: RefObject<HTMLTextAreaElement>;
    focusInput: () => void;
    send: () => boolean;
    retry: (id: string) => boolean;
    cancel: (id: string) => void;
    editAndResend: (id: string) => boolean;
}

const EMPTY_DRAFT = blankDraft();
const NO_EXCHANGES: AssistExchange[] = [];

export function useAssistThread(options: UseAssistThreadOptions): AssistThreadController {
    const { key, conversationId, mode, maxLength, storedTurns } = options;
    const record = useAssistThreadStore((state) => selectAssistThread(state, key));
    const inputRef = useRef<HTMLTextAreaElement>(null);
    const sendRef = useRef(options.send);
    const cancelRef = useRef(options.cancel);
    sendRef.current = options.send;
    cancelRef.current = options.cancel;

    const storedIds = useMemo(() => {
        const ids = new Set<string>();
        for (const turn of storedTurns ?? []) {
            const id = turn?.submission_id;
            if (typeof id === 'string' && id) {
                ids.add(id);
            }
        }
        return ids;
    }, [storedTurns]);
    const storedSignature = useMemo(() => Array.from(storedIds).join('|'), [storedIds]);

    useEffect(() => {
        if (key && storedIds.size && readThread(key)) {
            updateThread(key, conversationId, (current) => reconcileStoredExchanges(current, storedIds, mode));
        }
        // The signature stands for the id set, which is rebuilt whenever the stored turns are.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key, mode, storedSignature]);

    const allExchanges = record?.exchanges ?? NO_EXCHANGES;
    const exchanges = useMemo(() => mode === 'stored' && storedIds.size
        ? allExchanges.filter((exchange) =>
            !exchangeSubmissionIds(exchange).some((id) => storedIds.has(id)))
        : allExchanges,
    [allExchanges, mode, storedIds]);
    const ownSubmissionIds = useMemo(
        () => new Set(allExchanges.flatMap((exchange) => exchangeSubmissionIds(exchange))),
        [allExchanges],
    );
    const draft = record?.draft ?? EMPTY_DRAFT;

    const focusInput = useCallback(() => {
        const focus = () => {
            const input = inputRef.current;
            if (!input || input.disabled) {
                return;
            }
            input.focus();
            const end = input.value.length;
            input.setSelectionRange(end, end);
        };
        if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(focus);
        } else {
            setTimeout(focus, 0);
        }
    }, []);

    const setDraft = useCallback<Dispatch<SetStateAction<ComposerDraft>>>((action) => {
        if (!key) {
            return;
        }
        updateThread(key, conversationId, (current) => {
            const next = typeof action === 'function' ? action(current.draft) : action;
            return next === current.draft ? current : { ...current, draft: next };
        });
    }, [key, conversationId]);

    const dismissNotice = useCallback(() => {
        if (key) {
            updateThread(key, conversationId, (current) => current.notice ? { ...current, notice: null } : current);
        }
    }, [key, conversationId]);

    const send = useCallback(() => {
        if (!key) {
            return false;
        }
        const id = submitAssistDraft({ key, conversationId, mode, maxLength, send: sendRef.current });
        if (id) {
            focusInput();
        }
        return Boolean(id);
    }, [key, conversationId, mode, maxLength, focusInput]);

    const retry = useCallback((id: string) => {
        const retried = key ? retryAssistExchange(key, id, mode, sendRef.current) : false;
        focusInput();
        return retried;
    }, [key, mode, focusInput]);

    const cancel = useCallback((id: string) => {
        if (key) {
            cancelAssistExchange(key, id, cancelRef.current);
        }
        focusInput();
    }, [key, focusInput]);

    const editAndResend = useCallback((id: string) => {
        const edited = key ? editAssistExchange(key, id) : false;
        focusInput();
        return edited;
    }, [key, focusInput]);

    return {
        key,
        mode,
        exchanges,
        // Taken from every exchange, not just the shown ones: a shared chat can show the stored
        // turns before this page's request has returned, and the thread is still busy until then.
        pending: allExchanges.find((exchange) => exchange.status === 'pending') ?? null,
        draft,
        setDraft,
        notice: record?.notice ?? null,
        dismissNotice,
        maxLength,
        length: draft.text.length,
        overLimit: draft.text.length > maxLength,
        ownSubmissionIds,
        inputRef,
        focusInput,
        send,
        retry,
        cancel,
        editAndResend,
    };
}
