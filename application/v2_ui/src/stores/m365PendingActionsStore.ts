// m365PendingActionsStore.ts
// State for the Microsoft 365 outgoing-action cards.
//
// One factory builds the store. The chat view uses a single shared instance so the chat stream
// handlers (which run outside React) can hand it cards, and every Approvals detail builds its own
// instance for the one action it shows. Both run the same state machine, so a card behaves the
// same wherever it is drawn: it only ever sends or cancels the version the person reviewed, a
// snapshot from history or a stream is checked against the server before it can be sent, and a
// late response for a conversation the person has left is dropped.

import { createContext, createElement, useContext, type ReactNode } from 'react';
import { createStore, useStore, type StoreApi } from 'zustand';
import { ApiError } from '../lib/apiClient';
import {
    errorMessage,
    fetchConversationPendingActions,
    fetchPendingAction,
    isPendingAction,
    m365ErrorPayload,
    mutatePendingAction,
    pendingActionNeedsFullReview,
    pendingActionSendRoute,
    type PendingAction,
} from '../lib/approvalsApi';
import { connectMicrosoft365, m365Sources } from '../lib/m365Connect';
import {
    EMPTY_PENDING_ACTION_REFERENCE,
    PENDING_ACTION_POLL_MS,
    hasLoadedFullDetails,
    hydratedAuth,
    isActionableStatus,
    isPollDue,
    isStaleSnapshot,
    mergeReference,
    messageTrackKey,
    normalizePendingActionId,
    pendingActionsErrorFromPayload,
    pendingActionsFromPayload,
    referenceForMessage,
    referenceForStreamFrame,
    referencedActionIds,
    type PendingActionNotice,
    type PendingActionReference,
} from '../lib/m365PendingActions';

export type PendingActionOperation = 'send-now' | 'approve' | 'cancel';

export interface PendingActionEntry {
    id: string;
    /** Distinguishes this entry from a later one for the same id, so late responses can be dropped. */
    key: number;
    /** Insertion order, so cards stay in the order they were found. */
    order: number;
    action: PendingAction;
    /** Versions this card has already moved past; a snapshot of one of them is ignored. */
    seenVersions: readonly string[];
    reference: PendingActionReference;
    busy: boolean;
    reviewing: boolean;
    refreshing: boolean;
    /** The card holds an unverified snapshot, so sending is blocked until the server confirms it. */
    needsRefresh: boolean;
    denied: boolean;
    auth: Record<string, unknown> | null;
    authAcknowledgedVersion: string;
    approvalRequired: Record<string, unknown> | null;
    /** The version whose complete saved content was loaded from the server. */
    fullDetailsVersion: string;
    /** The version whose body the person opened and had refreshed. */
    detailVersion: string;
    notice: PendingActionNotice | null;
    bodyOpen: boolean;
    nextRefreshAt: number;
}

export interface PendingActionDetailState {
    status: 'loading' | 'error';
    message: string;
}

export interface PendingActionsLiveStream {
    conversationId: string;
    userMessageId: string;
}

export interface PendingActionsFocusRequest {
    id: string;
    conversationId: string;
    key: number;
}

export interface RefreshOptions {
    clearNotice?: boolean;
    acknowledgeAuthVersion?: string;
}

export interface StreamFrameOptions {
    conversationId?: string;
    messageId?: string;
    userMessageId?: string;
    requestId?: string;
}

interface PendingActionsData {
    scope: 'chat' | 'detail';
    conversationId: string;
    epoch: number;
    entries: Readonly<Record<string, PendingActionEntry>>;
    /** Load state for actions fetched by id (an Approvals link, or a notification deep link). */
    detail: Readonly<Record<string, PendingActionDetailState>>;
    listStatus: 'idle' | 'loading' | 'loaded' | 'error';
    listError: string;
    referenceError: string;
    /** True while a card a message points at is still being fetched, so it may yet move. */
    referenceLoading: boolean;
    continuationToken: string;
    loadingMore: boolean;
    liveStream: PendingActionsLiveStream | null;
    focusRequest: PendingActionsFocusRequest | null;
}

interface PendingActionsApi {
    remember(
        action: PendingAction,
        options?: { authoritative?: boolean; reference?: Partial<PendingActionReference> },
    ): PendingActionEntry | null;
    refresh(id: string, options?: RefreshOptions): Promise<PendingAction | null>;
    loadById(id: string, options?: { reference?: Partial<PendingActionReference> }): Promise<PendingAction | null>;
    reviewFull(id: string): Promise<void>;
    submit(id: string, operation: PendingActionOperation): Promise<void>;
    reconnect(id: string): Promise<void>;
    setBodyOpen(id: string, open: boolean): void;
    pollIfDue(id: string): void;
    setConversation(conversationId: string): void;
    loadList(options?: { more?: boolean }): Promise<void>;
    /** Read the first page again, after one already running has settled, so nothing newer is missed. */
    refreshList(): Promise<void>;
    trackMessage(message: unknown, options?: { history?: boolean }): void;
    ingestMessages(messages: readonly unknown[]): void;
    handleStreamPayload(payload: unknown, options?: StreamFrameOptions): void;
    setLiveStream(stream: PendingActionsLiveStream | null): void;
    requestFocus(id: string, conversationId: string): void;
    clearFocus(): void;
    reset(): void;
}

export type PendingActionsStore = PendingActionsData & PendingActionsApi;

export const LIST_PERMISSION_MESSAGE = 'You do not have permission to view outgoing actions for this conversation.';
export const LIST_FAILED_MESSAGE =
    'Outgoing actions could not be loaded. Refresh to recover saved actions; this is not an empty inbox.';
export const REFERENCE_FAILED_MESSAGE =
    'A saved Microsoft 365 action could not be recovered. Refresh outgoing actions to check its status.';
const NOT_LOADED_MESSAGE = 'The outgoing action could not be loaded.';
const PERMISSION_MESSAGE = 'You do not have permission to access this action. No action was sent.';
const STATUS_UNKNOWN_MESSAGE = 'The current action status could not be checked. Refresh status before trying again.';

const info = (text: string): PendingActionNotice => ({ text, tone: 'info' });
const warn = (text: string): PendingActionNotice => ({ text, tone: 'warn' });

function newEntry(action: PendingAction, key: number, order: number, reference: PendingActionReference): PendingActionEntry {
    return {
        id: action.id,
        key,
        order,
        action,
        seenVersions: [],
        reference,
        busy: false,
        reviewing: false,
        refreshing: false,
        needsRefresh: false,
        denied: false,
        auth: null,
        authAcknowledgedVersion: '',
        approvalRequired: null,
        fullDetailsVersion: '',
        detailVersion: '',
        notice: null,
        bodyOpen: false,
        nextRefreshAt: 0,
    };
}

/** Whether the person may send or cancel this card right now. */
export function canChangeEntry(entry: PendingActionEntry): boolean {
    return (
        !entry.busy &&
        !entry.refreshing &&
        !entry.needsRefresh &&
        !entry.denied &&
        entry.action.viewer_is_owner !== false &&
        typeof entry.action.version === 'string' &&
        Boolean(entry.action.version) &&
        isActionableStatus(entry.action.status)
    );
}

function statusOf(error: unknown): number {
    return error instanceof ApiError ? error.status : 0;
}

export function createPendingActionsStore(
    options: { scope?: 'chat' | 'detail'; onUpdated?: (action: PendingAction) => void } = {},
): StoreApi<PendingActionsStore> {
    const scope = options.scope ?? 'chat';
    let keyCounter = 0;
    let orderCounter = 0;
    let focusCounter = 0;
    // Bookkeeping that never drives rendering lives here, beside the state.
    const refreshes = new Map<string, Promise<PendingAction | null>>();
    const sequences = new Map<string, number>();
    const referenceLoads = new Map<string, Promise<void>>();
    const referenceFailures = new Map<string, PendingActionReference>();
    const trackedMessages = new Map<string, string>();
    let listPromise: Promise<void> | null = null;
    let listController: AbortController | null = null;

    return createStore<PendingActionsStore>()((set, get) => {
        const current = (id: string, key: number): PendingActionEntry | null => {
            const entry = get().entries[id];
            return entry && entry.key === key ? entry : null;
        };

        const patchEntry = (
            id: string,
            key: number,
            patch: Partial<PendingActionEntry> | ((entry: PendingActionEntry) => Partial<PendingActionEntry>),
        ) => {
            set((state) => {
                const entry = state.entries[id];
                if (!entry || entry.key !== key) return state;
                const changes = typeof patch === 'function' ? patch(entry) : patch;
                return { entries: { ...state.entries, [id]: { ...entry, ...changes } } };
            });
        };

        const detailConversationId = (entry: PendingActionEntry): string => {
            if (scope === 'chat') return get().conversationId;
            return entry.action.viewer_is_owner === false ? (entry.action.conversation_id ?? '') : '';
        };

        const clearReferenceError = () => {
            if (!referenceFailures.size && get().referenceError) set({ referenceError: '' });
        };

        /* Entries -------------------------------------------------------------- */

        const remember: PendingActionsApi['remember'] = (action, rememberOptions = {}) => {
            if (!isPendingAction(action)) return null;
            const authoritative = rememberOptions.authoritative === true;
            let accepted = false;
            let restoreFullReview = false;
            set((state) => {
                const existing = state.entries[action.id];
                if (!existing) {
                    accepted = true;
                    const reference = mergeReference(EMPTY_PENDING_ACTION_REFERENCE, rememberOptions.reference);
                    const created = newEntry(action, ++keyCounter, ++orderCounter, reference);
                    const auth = hydratedAuth(action, authoritative, '', null);
                    created.auth = auth.auth;
                    created.authAcknowledgedVersion = auth.acknowledgedVersion;
                    if (authoritative && hasLoadedFullDetails(action, true)) created.fullDetailsVersion = action.version ?? '';
                    return { entries: { ...state.entries, [action.id]: created } };
                }
                const reference = mergeReference(existing.reference, rememberOptions.reference);
                if (isStaleSnapshot(existing.action, new Set(existing.seenVersions), action, authoritative)) {
                    if (reference === existing.reference) return state;
                    return { entries: { ...state.entries, [action.id]: { ...existing, reference } } };
                }
                accepted = true;
                const next: PendingActionEntry = { ...existing, reference, action };
                const previousVersion = existing.action.version;
                if (previousVersion && previousVersion !== action.version) {
                    next.seenVersions = [...existing.seenVersions, previousVersion];
                    next.fullDetailsVersion = '';
                    next.authAcknowledgedVersion = '';
                    next.auth = null;
                }
                restoreFullReview =
                    !authoritative &&
                    pendingActionNeedsFullReview(action) &&
                    Boolean(action.version) &&
                    next.fullDetailsVersion === action.version;
                if (authoritative) {
                    next.needsRefresh = false;
                    // The sharing decision may have been settled elsewhere; sending again asks the server.
                    next.approvalRequired = null;
                    if (hasLoadedFullDetails(action, true)) next.fullDetailsVersion = action.version ?? '';
                    else if (pendingActionNeedsFullReview(action)) next.fullDetailsVersion = '';
                }
                const auth = hydratedAuth(action, authoritative, next.authAcknowledgedVersion, next.auth);
                next.auth = auth.auth;
                next.authAcknowledgedVersion = auth.acknowledgedVersion;
                return { entries: { ...state.entries, [action.id]: next } };
            });
            const entry = get().entries[action.id] ?? null;
            if (entry && accepted) {
                options.onUpdated?.(entry.action);
                // Reauthorize details rather than restoring permissions from a cached full-body response.
                if (restoreFullReview && !entry.busy) void refresh(entry.id);
            }
            return entry;
        };

        /** Add a card found in a message, a stream frame or a list, remembering where it was seen. */
        const add = (
            action: PendingAction,
            reference: Partial<PendingActionReference>,
            addOptions: { authoritative?: boolean; history?: boolean } = {},
        ) => {
            const authoritative = addOptions.authoritative === true;
            const before = get().entries[action.id];
            const entry = remember(action, { authoritative, reference });
            if (!entry) return;
            referenceFailures.delete(entry.id);
            clearReferenceError();
            const changed = !before || before.action !== entry.action;
            if (addOptions.history && !authoritative && changed) {
                patchEntry(entry.id, entry.key, { needsRefresh: true });
                if (!pendingActionNeedsFullReview(entry.action)) void refresh(entry.id);
            }
        };

        const refresh: PendingActionsApi['refresh'] = (id, refreshOptions = {}) => {
            const entry = get().entries[id];
            if (!entry) return Promise.resolve(null);
            const key = entry.key;
            const reviewedVersion = refreshOptions.acknowledgeAuthVersion || entry.action.version || '';
            const inFlight = refreshes.get(id);
            if (inFlight) {
                if (!refreshOptions.clearNotice) return inFlight;
                return inFlight.then(() =>
                    current(id, key) ? refresh(id, { ...refreshOptions, acknowledgeAuthVersion: reviewedVersion }) : null,
                );
            }
            const sequence = (sequences.get(id) ?? 0) + 1;
            sequences.set(id, sequence);
            patchEntry(id, key, { refreshing: true, nextRefreshAt: Date.now() + PENDING_ACTION_POLL_MS });
            const isCurrent = () => Boolean(current(id, key)) && sequences.get(id) === sequence;
            let run: Promise<PendingAction | null> | undefined;
            run = (async () => {
                try {
                    const next = await fetchPendingAction(id, undefined, detailConversationId(entry));
                    if (!isCurrent()) return null;
                    remember(next, { authoritative: true });
                    patchEntry(id, key, (latest) => {
                        const changes: Partial<PendingActionEntry> = { denied: false };
                        if (refreshOptions.clearNotice) {
                            if (
                                latest.action.viewer_is_owner !== false &&
                                reviewedVersion &&
                                latest.action.version === reviewedVersion
                            ) {
                                changes.authAcknowledgedVersion = reviewedVersion;
                                changes.auth = null;
                            }
                            changes.notice = info(
                                'Current server status loaded. Review the saved action before choosing Send or Cancel.',
                            );
                        }
                        return changes;
                    });
                    return next;
                } catch (error) {
                    if (!isCurrent()) return null;
                    const status = statusOf(error);
                    const payload = m365ErrorPayload(error);
                    const changes: Partial<PendingActionEntry> = {
                        needsRefresh: true,
                        denied: status === 403 || status === 404,
                        notice: warn(status === 403 ? PERMISSION_MESSAGE : STATUS_UNKNOWN_MESSAGE),
                    };
                    if (status === 401 || payload.auth_required === true) {
                        changes.authAcknowledgedVersion = '';
                        changes.auth = payload;
                    }
                    patchEntry(id, key, changes);
                    return null;
                } finally {
                    if (refreshes.get(id) === run) refreshes.delete(id);
                    patchEntry(id, key, { refreshing: false });
                }
            })();
            refreshes.set(id, run);
            return run;
        };

        const loadById: PendingActionsApi['loadById'] = async (rawId, loadOptions = {}) => {
            const id = normalizePendingActionId(rawId);
            if (!id) {
                set((state) => ({ detail: { ...state.detail, [rawId]: { status: 'error', message: NOT_LOADED_MESSAGE } } }));
                return null;
            }
            if (get().entries[id]) {
                if (loadOptions.reference) {
                    const entry = get().entries[id];
                    patchEntry(id, entry.key, (latest) => ({ reference: mergeReference(latest.reference, loadOptions.reference) }));
                }
                return refresh(id);
            }
            const epoch = get().epoch;
            set((state) => ({ detail: { ...state.detail, [id]: { status: 'loading', message: '' } } }));
            try {
                const action = await fetchPendingAction(id, undefined, scope === 'chat' ? get().conversationId : '');
                if (get().epoch !== epoch) return null;
                remember(action, { authoritative: true, reference: loadOptions.reference });
                set((state) => {
                    const { [id]: _done, ...rest } = state.detail;
                    return { detail: rest };
                });
                return action;
            } catch (error) {
                if (get().epoch !== epoch) return null;
                set((state) => ({
                    detail: {
                        ...state.detail,
                        [id]: { status: 'error', message: statusOf(error) === 403 ? PERMISSION_MESSAGE : NOT_LOADED_MESSAGE },
                    },
                }));
                return null;
            }
        };

        const reviewFull: PendingActionsApi['reviewFull'] = async (id) => {
            const entry = get().entries[id];
            if (!entry || entry.busy || entry.reviewing) return;
            const key = entry.key;
            patchEntry(id, key, {
                reviewing: true,
                notice: info('Loading the complete saved content for review. This review does not send the action.'),
            });
            const action = await refresh(id);
            if (!current(id, key)) return;
            const complete =
                Boolean(action) && !pendingActionNeedsFullReview(action as PendingAction) && typeof action?.summary?.body_preview === 'string';
            patchEntry(id, key, (latest) => {
                if (complete) {
                    return {
                        reviewing: false,
                        detailVersion: latest.action.version ?? '',
                        bodyOpen: true,
                        notice: info('Complete saved content loaded. Review the recipients and full content before sending.'),
                    };
                }
                if (action) {
                    return {
                        reviewing: false,
                        needsRefresh: true,
                        notice: warn('The complete saved content could not be verified. Review full details again before sending.'),
                    };
                }
                return { reviewing: false };
            });
        };

        const submit: PendingActionsApi['submit'] = async (id, operation) => {
            const entry = get().entries[id];
            if (!entry) return;
            const key = entry.key;
            const allowed =
                operation === 'cancel'
                    ? entry.action.can_cancel === true
                    : Boolean(pendingActionSendRoute(entry.action)) && !entry.auth && !entry.approvalRequired;
            const version = entry.action.version;
            if (!canChangeEntry(entry) || !allowed || !version) return;
            patchEntry(id, key, {
                busy: true,
                notice: info(operation === 'cancel' ? 'Cancelling this saved action…' : 'Submitting this saved action…'),
            });
            sequences.set(id, (sequences.get(id) ?? 0) + 1);
            try {
                await refreshes.get(id);
                const next = await mutatePendingAction(id, operation, version);
                if (!current(id, key)) return;
                remember(next, { authoritative: true });
                patchEntry(id, key, {
                    auth: null,
                    denied: false,
                    notice: info(
                        operation === 'cancel'
                            ? 'Cancellation checked. The server status below is authoritative; this does not recall an already sent item.'
                            : 'Send request checked. Review the server status and delivery note below.',
                    ),
                });
            } catch (error) {
                if (!current(id, key)) return;
                const payload = m365ErrorPayload(error);
                const status = statusOf(error);
                const returned = isPendingAction(payload.pending_action) && payload.pending_action.id === id;
                if (returned) remember(payload.pending_action as PendingAction, { authoritative: true });
                if (payload.approval_required === true) {
                    patchEntry(id, key, {
                        approvalRequired: payload,
                        notice: warn(
                            'Review the saved Microsoft 365 sharing decision before sending. Approving it does not send this action; return here and select Send again.',
                        ),
                    });
                } else if (status === 401 || payload.auth_required === true) {
                    patchEntry(id, key, {
                        authAcknowledgedVersion: '',
                        auth: payload,
                        notice: warn(
                            'Microsoft 365 sign-in is required. Reconnect, review this same saved action, then select Send again. Signing in does not send it.',
                        ),
                    });
                } else if (status === 403) {
                    patchEntry(id, key, {
                        denied: true,
                        notice: warn('You do not have permission to change this action. Refresh status to check your current access.'),
                    });
                } else if (status === 409) {
                    patchEntry(id, key, {
                        notice: warn(
                            'This action changed or is already being processed. Review its current status and details before making another choice.',
                        ),
                    });
                    if (!returned) {
                        patchEntry(id, key, { needsRefresh: true });
                        await refresh(id);
                    }
                } else {
                    patchEntry(id, key, {
                        needsRefresh: true,
                        notice: warn(
                            'The response was not confirmed. Checking the current server status; the send will not be retried automatically.',
                        ),
                    });
                    const refreshed = await refresh(id);
                    if (refreshed) {
                        patchEntry(id, key, {
                            notice: warn(
                                'The response was not confirmed. Current server status has been refreshed. Review it before making another choice; no send was retried automatically.',
                            ),
                        });
                    }
                }
            } finally {
                patchEntry(id, key, { busy: false });
            }
        };

        const reconnect: PendingActionsApi['reconnect'] = async (id) => {
            const entry = get().entries[id];
            if (!entry || entry.busy) return;
            const key = entry.key;
            const reviewedVersion = entry.action.version ?? '';
            patchEntry(id, key, {
                busy: true,
                notice: info('Opening sign-in for this saved action. No chat request will be resumed and nothing will be sent.'),
            });
            try {
                const fromPayload = m365Sources(entry.auth?.sources);
                await connectMicrosoft365(
                    fromPayload.length ? fromPayload : [entry.action.graph_resource_type === 'calendar' ? 'calendar' : 'email'],
                );
                if (!current(id, key)) return;
                await refresh(id, { clearNotice: true, acknowledgeAuthVersion: reviewedVersion });
            } catch (error) {
                patchEntry(id, key, { notice: warn(errorMessage(error, 'Sign-in was not confirmed. No action was sent.')) });
            } finally {
                patchEntry(id, key, { busy: false });
            }
        };

        /* The conversation's cards ---------------------------------------------- */

        const loadReference = (id: string, reference: PendingActionReference): Promise<void> => {
            const pending = referenceLoads.get(id);
            if (pending) return pending;
            const { conversationId, epoch } = get();
            let run: Promise<void> | undefined;
            run = (async () => {
                try {
                    const action = await fetchPendingAction(id, undefined, conversationId);
                    if (get().epoch !== epoch) return;
                    referenceFailures.delete(id);
                    remember(action, { authoritative: true, reference });
                    clearReferenceError();
                } catch {
                    if (get().epoch !== epoch) return;
                    referenceFailures.set(id, reference);
                    set({ referenceError: REFERENCE_FAILED_MESSAGE });
                } finally {
                    if (referenceLoads.get(id) === run) referenceLoads.delete(id);
                    if (get().referenceLoading && referenceLoads.size === 0) set({ referenceLoading: false });
                }
            })();
            referenceLoads.set(id, run);
            if (!get().referenceLoading) set({ referenceLoading: true });
            return run;
        };

        const trackMessage: PendingActionsApi['trackMessage'] = (message, trackOptions = {}) => {
            if (!message || typeof message !== 'object') return;
            const history = trackOptions.history === true;
            const reference = referenceForMessage(message);
            for (const action of pendingActionsFromPayload({
                m365_pending_actions: (message as { m365_pending_actions?: unknown }).m365_pending_actions,
            })) {
                add(action, reference, { history });
            }
            for (const id of referencedActionIds(message)) {
                const entry = get().entries[id];
                if (entry) {
                    patchEntry(id, entry.key, (latest) => ({
                        reference: mergeReference(latest.reference, reference),
                        needsRefresh: true,
                    }));
                    if (!pendingActionNeedsFullReview(entry.action)) void refresh(id);
                } else {
                    void loadReference(id, reference);
                }
            }
        };

        const loadList: PendingActionsApi['loadList'] = (loadOptions = {}) => {
            const { conversationId, epoch } = get();
            if (!conversationId) return Promise.resolve();
            if (listPromise) return listPromise;
            const more = loadOptions.more === true;
            const token = more ? get().continuationToken : '';
            if (more && !token) return Promise.resolve();
            const controller = new AbortController();
            listController = controller;
            set({ listStatus: more ? get().listStatus : 'loading', loadingMore: more, listError: '' });
            let run: Promise<void> | undefined;
            run = (async () => {
                try {
                    await Promise.all([...referenceFailures].map(([id, reference]) => loadReference(id, reference)));
                    const page = await fetchConversationPendingActions(conversationId, token, controller.signal);
                    if (get().epoch !== epoch) return;
                    for (const action of page.items) add(action, {}, { authoritative: true });
                    set({
                        continuationToken: page.continuationToken,
                        listStatus: 'loaded',
                        listError: '',
                        loadingMore: false,
                        referenceError: referenceFailures.size ? REFERENCE_FAILED_MESSAGE : '',
                    });
                } catch (error) {
                    if (controller.signal.aborted || get().epoch !== epoch) return;
                    const denied = statusOf(error) === 403;
                    set((state) => ({
                        entries: Object.fromEntries(
                            Object.entries(state.entries).map(([id, entry]) => [id, { ...entry, needsRefresh: true, denied }]),
                        ),
                        listStatus: 'error',
                        listError: denied ? LIST_PERMISSION_MESSAGE : LIST_FAILED_MESSAGE,
                        loadingMore: false,
                    }));
                } finally {
                    if (listPromise === run) listPromise = null;
                    if (listController === controller) listController = null;
                }
            })();
            listPromise = run;
            return run;
        };

        return {
            scope,
            conversationId: '',
            epoch: 0,
            entries: {},
            detail: {},
            listStatus: 'idle',
            listError: '',
            referenceError: '',
            referenceLoading: false,
            continuationToken: '',
            loadingMore: false,
            liveStream: null,
            focusRequest: null,

            remember,
            refresh,
            loadById,
            reviewFull,
            submit,
            reconnect,
            trackMessage,
            loadList,

            refreshList: async () => {
                // A load that began before the announcement may not include what it announced.
                if (listPromise) await listPromise;
                await loadList();
            },

            setBodyOpen: (id, open) => {
                const entry = get().entries[id];
                if (!entry || entry.bodyOpen === open) return;
                patchEntry(id, entry.key, { bodyOpen: open });
                const latest = get().entries[id];
                // Opening the body of a card whose version was not reviewed yet re-checks it first.
                if (
                    open &&
                    latest &&
                    !latest.busy &&
                    !pendingActionNeedsFullReview(latest.action) &&
                    latest.detailVersion !== (latest.action.version ?? '')
                ) {
                    patchEntry(id, latest.key, { detailVersion: latest.action.version ?? '' });
                    void refresh(id);
                }
            },

            pollIfDue: (id) => {
                const entry = get().entries[id];
                if (entry && isPollDue(entry.action, entry.busy || entry.refreshing, entry.nextRefreshAt)) void refresh(id);
            },

            setConversation: (rawId) => {
                const conversationId = typeof rawId === 'string' ? rawId.trim() : '';
                if (conversationId === get().conversationId) return;
                listController?.abort();
                listController = null;
                listPromise = null;
                refreshes.clear();
                sequences.clear();
                referenceLoads.clear();
                referenceFailures.clear();
                trackedMessages.clear();
                set((state) => ({
                    conversationId,
                    epoch: state.epoch + 1,
                    entries: {},
                    detail: {},
                    listStatus: 'idle',
                    listError: '',
                    referenceError: '',
                    referenceLoading: false,
                    continuationToken: '',
                    loadingMore: false,
                    liveStream: null,
                    // A deep link asks for its card before the conversation has finished switching.
                    focusRequest: state.focusRequest?.conversationId === conversationId ? state.focusRequest : null,
                }));
            },

            ingestMessages: (messages) => {
                for (const message of messages) {
                    const signature = messageTrackKey(message);
                    if (!signature) continue;
                    const messageId = referenceForMessage(message).messageId;
                    if (trackedMessages.get(messageId) === signature) continue;
                    trackedMessages.set(messageId, signature);
                    trackMessage(message, { history: true });
                }
            },

            handleStreamPayload: (payload, frameOptions = {}) => {
                const state = get();
                if (!state.conversationId) return;
                if (frameOptions.conversationId && frameOptions.conversationId !== state.conversationId) return;
                const reference = referenceForStreamFrame(payload, frameOptions);
                for (const action of pendingActionsFromPayload(payload)) add(action, reference);
                const failure = pendingActionsErrorFromPayload(payload);
                if (failure) {
                    set({ referenceError: failure });
                    void loadList();
                }
            },

            setLiveStream: (stream) => {
                const previous = get().liveStream;
                if (!stream) {
                    if (previous) set({ liveStream: null });
                    return;
                }
                if (previous && previous.conversationId === stream.conversationId && previous.userMessageId === stream.userMessageId) return;
                const renamed = previous?.conversationId === stream.conversationId ? previous.userMessageId : '';
                set((state) => {
                    if (!renamed || renamed === stream.userMessageId) return { liveStream: stream };
                    // The temporary id the user turn had while it streamed is replaced by its saved id.
                    const entries = Object.fromEntries(
                        Object.entries(state.entries).map(([id, entry]) => [
                            id,
                            entry.reference.userMessageId === renamed || entry.reference.fallbackMessageId === renamed
                                ? {
                                      ...entry,
                                      reference: {
                                          ...entry.reference,
                                          userMessageId:
                                              entry.reference.userMessageId === renamed ? stream.userMessageId : entry.reference.userMessageId,
                                          fallbackMessageId:
                                              entry.reference.fallbackMessageId === renamed
                                                  ? stream.userMessageId
                                                  : entry.reference.fallbackMessageId,
                                      },
                                  }
                                : entry,
                        ]),
                    );
                    return { liveStream: stream, entries };
                });
            },

            requestFocus: (id, conversationId) => {
                const safeId = normalizePendingActionId(id);
                if (!safeId) return;
                set({ focusRequest: { id: safeId, conversationId: conversationId.trim(), key: ++focusCounter } });
            },

            clearFocus: () => {
                if (get().focusRequest) set({ focusRequest: null });
            },

            reset: () => {
                listController?.abort();
                listController = null;
                listPromise = null;
                refreshes.clear();
                sequences.clear();
                referenceLoads.clear();
                referenceFailures.clear();
                trackedMessages.clear();
                set((state) => ({
                    epoch: state.epoch + 1,
                    conversationId: '',
                    entries: {},
                    detail: {},
                    listStatus: 'idle',
                    listError: '',
                    referenceError: '',
                    referenceLoading: false,
                    continuationToken: '',
                    loadingMore: false,
                    liveStream: null,
                    focusRequest: null,
                }));
            },
        };
    });
}

/* React access ---------------------------------------------------------------- */

/** The store the chat view and its stream handlers share. */
export const chatPendingActionsStore: StoreApi<PendingActionsStore> = createPendingActionsStore({ scope: 'chat' });

const PendingActionsContext = createContext<StoreApi<PendingActionsStore> | null>(null);

export function PendingActionsProvider({ store, children }: { store: StoreApi<PendingActionsStore>; children?: ReactNode }) {
    return createElement(PendingActionsContext.Provider, { value: store }, children);
}

/** The store of the nearest provider, or the chat store when there is none. */
export function usePendingActionsStoreApi(): StoreApi<PendingActionsStore> {
    return useContext(PendingActionsContext) ?? chatPendingActionsStore;
}

/** Selectors must return a stable reference or a primitive; derive collections with useMemo. */
export function usePendingActions<T>(selector: (state: PendingActionsStore) => T): T {
    return useStore(usePendingActionsStoreApi(), selector);
}
