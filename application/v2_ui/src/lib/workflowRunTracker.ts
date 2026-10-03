// workflowRunTracker.ts
// The one tracker a tab keeps for the saved workflow runs its user's chats started.
//
// A plan that starts a workflow ends straight away; the server posts the run's result back into the
// chat later, marks the chat unread and adds one bell notice. This engine follows those runs through
// the batched status route so the app can show them: the run card, the chat list's running tag and
// the delivered-message footers read what it keeps, and nothing else polls.
//
// The engine is plain logic with every outside dependency passed in (the request, timers, the clock,
// page visibility and the desktop-notification check), so its cadence and its baseline can be
// tested without a browser. `useWorkflowRunTracker` owns the one instance a tab has.
//
// Cadence. While the tab is visible and a run is in flight it checks after 15 s, then 30 s, 1 min,
// 2 min and every 5 min after that. A hidden tab is paused and checks as soon as it is shown again,
// except that a reader with desktop notifications on keeps a check every 5 min while a run is in
// flight. With nothing in flight it stops until something kicks it: a plan's answer, the run card
// or Check now. Errors back off (30 s, 1 min, 2 min, then 5 min); 401 and 403, and a 400 on the
// global read, halt it for the page session.
//
// Baseline. The first response in a page session records every result already posted, silently.
// Only a posting seen later in the same page session is announced, so a reload never announces a
// result twice, never marks a chat unread again and never shows a second desktop notification.

import {
    isStatusConversationId,
    isWorkflowRunInFlight,
    WORKFLOW_DELIVERY_MESSAGE_PREFIX,
    WORKFLOW_STATUS_READ_ERROR_TEXT,
    type WorkflowRunRow,
    type WorkflowRunStatusResponse,
    type WorkflowRunStatusRow,
} from './workflowRunStatus';

/** Visible-tab delays while a run is in flight: 15 s easing to every 5 min. */
export const WORKFLOW_RUN_POLL_DELAYS_MS: readonly number[] = [15_000, 30_000, 60_000, 120_000, 300_000];
/** Delays after consecutive failed reads. */
export const WORKFLOW_RUN_ERROR_DELAYS_MS: readonly number[] = [30_000, 60_000, 120_000, 300_000];
/** A hidden tab's delay, only while desktop notifications are on and a run is in flight. */
export const WORKFLOW_RUN_HIDDEN_DELAY_MS = 300_000;
/** How long a chat's own read stands in for another one. */
export const WORKFLOW_RUN_CONVERSATION_DEDUPE_MS = 10_000;

export interface TrackedWorkflowRun {
    row: WorkflowRunRow;
    /** The `checked_at` of the response the row came from. */
    checkedAt: string;
    /**
     * A complete read of every chat's runs no longer lists it although it was in flight: it has
     * stopped, and how isn't known until its chat is read. A retired row is never in flight.
     */
    retired: boolean;
}

export interface WorkflowRunConversationRead {
    /** The newest `checked_at` of this chat's own reads. */
    checkedAt: string | null;
    reading: boolean;
    /** Why the last read of this chat failed, as fixed text; cleared by the next good read. */
    error: string | null;
}

export interface WorkflowRunTrackerSnapshot {
    running: boolean;
    /** Stopped for the page session after the server refused the reads. */
    halted: boolean;
    /** Whether chats can start workflows now, from the newest response; null before the first. */
    available: boolean | null;
    runs: Readonly<Record<string, TrackedWorkflowRun>>;
    /** The newest `checked_at` of a complete read of every chat's runs. */
    globalCheckedAt: string | null;
    /** The last read of every chat's runs failed. */
    globalError: boolean;
    conversations: Readonly<Record<string, WorkflowRunConversationRead>>;
}

export interface WorkflowRunTrackerDeps {
    /** One read of the status route: one chat's runs, or with null every chat's. */
    fetchStatus: (conversationId: string | null, signal: AbortSignal) => Promise<WorkflowRunStatusResponse>;
    setTimer: (callback: () => void, delayMs: number) => unknown;
    clearTimer: (handle: unknown) => void;
    /** Milliseconds, for the conversation-read dedupe only. */
    now: () => number;
    isVisible: () => boolean;
    subscribeVisibility: (listener: () => void) => () => void;
    /** Desktop notifications are on and permitted, so a hidden tab keeps checking. */
    desktopNotificationsOn: () => boolean;
    onState?: (snapshot: WorkflowRunTrackerSnapshot) => void;
    /** A run's result was posted to its chat during this page session. Once per posting. */
    onDelivered?: (row: WorkflowRunStatusRow) => void;
    /** A run seen in flight can no longer post to its chat (undeliverable or expired). */
    onClosed?: (row: WorkflowRunStatusRow) => void;
    /** A run seen in flight dropped out of a complete read. */
    onRetired?: (row: WorkflowRunRow) => void;
    onHalted?: () => void;
}

export interface WorkflowRunTracker {
    /** Start tracking and check straight away. Starting a running tracker does nothing. */
    start: () => void;
    /** Stop every timer and request. What was already posted stays recorded. */
    stop: () => void;
    /**
     * Something may have started a run: check again soon, from the start of the ladder.
     * `immediate` checks now, as a plan's answer does.
     */
    kick: (options?: { immediate?: boolean }) => void;
    /**
     * Read one chat's runs. Deduped while a read is in flight and for 10 s after a good one,
     * unless forced. Resolves whether the read succeeded.
     */
    requestConversationRuns: (conversationId: string, options?: { force?: boolean }) => Promise<boolean>;
    getSnapshot: () => WorkflowRunTrackerSnapshot;
}

const EMPTY_CONVERSATION: WorkflowRunConversationRead = { checkedAt: null, reading: false, error: null };

function errorStatus(error: unknown): number | null {
    if (error && typeof error === 'object' && typeof (error as { status?: unknown }).status === 'number') {
        return (error as { status: number }).status;
    }
    return null;
}

/** Every posting of a run has its own key: a retried run posts again under a new generation. */
function deliveryKey(row: WorkflowRunStatusRow): string {
    return `${row.run_id}:${row.delivery.generation ?? 'none'}`;
}

function safely(callback: () => void): void {
    try {
        callback();
    } catch {
        /* A reader's failure never stops the tracker. */
    }
}

export function isTrackedRunInFlight(tracked: TrackedWorkflowRun | undefined): boolean {
    return tracked !== undefined && !tracked.retired && isWorkflowRunInFlight(tracked.row);
}

/**
 * Whether a tab should keep a tracker at all: the user can use saved workflows and chats can start
 * them. Both come from the bootstrap payload's role-aware feature flags. Results posting back to
 * chat is not required, because a run's progress shows on its card either way.
 */
export function workflowRunTrackerShouldRun(features: Readonly<Record<string, boolean>> | null | undefined): boolean {
    return features?.allow_user_workflows === true && features?.enable_chat_orchestration_workflow_runs === true;
}

export function createWorkflowRunTracker(deps: WorkflowRunTrackerDeps): WorkflowRunTracker {
    let running = false;
    let halted = false;
    let available: boolean | null = null;
    let availableAt = '';
    const runs = new Map<string, TrackedWorkflowRun>();
    let globalCheckedAt: string | null = null;
    let globalError = false;
    const conversations = new Map<string, WorkflowRunConversationRead>();
    const conversationReads = new Map<string, { controller: AbortController; promise: Promise<boolean> }>();
    const conversationReadAt = new Map<string, number>();

    // What this page session has already seen. Kept across stop and start, so a tracker that
    // restarts (a flag flipped back on, or React mounting twice) announces nothing again.
    let baselineCheckedAt: string | null = null;
    const deliveredKeys = new Set<string>();
    const seenUndelivered = new Set<string>();
    const seenInFlight = new Set<string>();
    const closedKeys = new Set<string>();

    let timer: unknown = null;
    let timerDueAt = 0;
    let globalRead: AbortController | null = null;
    let ladderIndex = 0;
    let failures = 0;
    let kickPending = false;
    let unsubscribeVisibility: (() => void) | null = null;
    let snapshot = buildSnapshot();

    function buildSnapshot(): WorkflowRunTrackerSnapshot {
        return {
            running,
            halted,
            available,
            runs: Object.fromEntries(runs),
            globalCheckedAt,
            globalError,
            conversations: Object.fromEntries(conversations),
        };
    }

    function emit(): void {
        snapshot = buildSnapshot();
        safely(() => deps.onState?.(snapshot));
    }

    function somethingInFlight(): boolean {
        for (const tracked of runs.values()) {
            if (isTrackedRunInFlight(tracked)) {
                return true;
            }
        }
        return false;
    }

    function clearTimer(): void {
        if (timer !== null) {
            deps.clearTimer(timer);
            timer = null;
        }
    }

    function setTimer(delay: number): void {
        clearTimer();
        timerDueAt = deps.now() + delay;
        timer = deps.setTimer(() => {
            timer = null;
            onTimer();
        }, delay);
    }

    /** When the next check is due under the current rules, or null to wait for a kick or for the tab. */
    function nextDelay(): number | null {
        const wanted = somethingInFlight() || kickPending;
        if (!deps.isVisible()) {
            // Paused while hidden, except for a reader who would be told by a desktop notification.
            return wanted && deps.desktopNotificationsOn() ? WORKFLOW_RUN_HIDDEN_DELAY_MS : null;
        }
        if (failures > 0) {
            return WORKFLOW_RUN_ERROR_DELAYS_MS[Math.min(failures - 1, WORKFLOW_RUN_ERROR_DELAYS_MS.length - 1)];
        }
        return wanted ? WORKFLOW_RUN_POLL_DELAYS_MS[ladderIndex] : null;
    }

    /** Replace the pending check with the one the rules call for now. */
    function schedule(): void {
        clearTimer();
        if (!running || halted || globalRead) {
            return;
        }
        const delay = nextDelay();
        if (delay !== null) {
            setTimer(delay);
        }
    }

    /** Bring the next check forward when the rules now want it sooner; never push it back. */
    function scheduleSooner(): void {
        if (!running || halted || globalRead) {
            return;
        }
        const delay = nextDelay();
        if (delay !== null && (timer === null || deps.now() + delay < timerDueAt)) {
            setTimer(delay);
        }
    }

    function onTimer(): void {
        if (!running || halted) {
            return;
        }
        if (failures === 0) {
            ladderIndex = Math.min(ladderIndex + 1, WORKFLOW_RUN_POLL_DELAYS_MS.length - 1);
        }
        void checkAll();
    }

    function onVisibilityChange(): void {
        if (!running || halted) {
            return;
        }
        if (!deps.isVisible()) {
            schedule();
            return;
        }
        if (globalRead) {
            return;
        }
        if (somethingInFlight() || failures > 0 || kickPending) {
            ladderIndex = 0;
            void checkAll();
        } else {
            schedule();
        }
    }

    function abortAll(): void {
        globalRead?.abort();
        globalRead = null;
        for (const [conversationId, read] of conversationReads) {
            read.controller.abort();
            const state = conversations.get(conversationId);
            if (state?.reading) {
                conversations.set(conversationId, { ...state, reading: false });
            }
        }
        conversationReads.clear();
    }

    function halt(): void {
        halted = true;
        clearTimer();
        abortAll();
        emit();
        safely(() => deps.onHalted?.());
    }

    function isAnnounceable(row: WorkflowRunStatusRow): boolean {
        const { generation, message_id: messageId, delivered_at: deliveredAt } = row.delivery;
        if (generation === null || !messageId || !messageId.startsWith(WORKFLOW_DELIVERY_MESSAGE_PREFIX)) {
            return false;
        }
        if (seenUndelivered.has(row.run_id)) {
            return true;
        }
        // Both are server times in whole seconds, so a posting in the same second as the
        // first read, but missing from it, still counts as new.
        return baselineCheckedAt !== null && deliveredAt !== null && deliveredAt >= baselineCheckedAt;
    }

    function noteTransitions(
        row: WorkflowRunRow,
        first: boolean,
        delivered: WorkflowRunStatusRow[],
        closed: WorkflowRunStatusRow[],
    ): void {
        if (row.kind !== 'status') {
            return;
        }
        const { delivery } = row;
        if (delivery.status === 'delivered') {
            const key = deliveryKey(row);
            if (deliveredKeys.has(key)) {
                return;
            }
            deliveredKeys.add(key);
            if (!first && isAnnounceable(row)) {
                delivered.push(row);
            }
            return;
        }
        if (
            !first && seenInFlight.has(row.run_id)
            && (delivery.status === 'undeliverable' || delivery.status === 'expired')
        ) {
            const key = `${deliveryKey(row)}:${delivery.status}`;
            if (!closedKeys.has(key)) {
                closedKeys.add(key);
                closed.push(row);
            }
        }
        seenUndelivered.add(row.run_id);
        if (isWorkflowRunInFlight(row)) {
            seenInFlight.add(row.run_id);
        }
    }

    function apply(response: WorkflowRunStatusResponse, conversationId: string | null): void {
        const delivered: WorkflowRunStatusRow[] = [];
        const closed: WorkflowRunStatusRow[] = [];
        const retired: WorkflowRunRow[] = [];
        const first = baselineCheckedAt === null;
        if (response.checked_at >= availableAt) {
            available = response.available;
            availableAt = response.checked_at;
        }
        for (const row of response.runs) {
            // A chat's own read speaks for that chat only.
            if (conversationId !== null && row.conversation_id !== conversationId) {
                continue;
            }
            const tracked = runs.get(row.run_id);
            // A newer read already said more about this run.
            if (tracked && tracked.checkedAt > response.checked_at) {
                continue;
            }
            noteTransitions(row, first, delivered, closed);
            runs.set(row.run_id, { row, checkedAt: response.checked_at, retired: false });
        }
        if (first) {
            baselineCheckedAt = response.checked_at;
        }
        // Only a complete read of every chat's runs can say a run has dropped out. A chat's own
        // read is capped, and a truncated read leaves rows out.
        if (conversationId === null && !response.truncated) {
            const listed = new Set(response.runs.map((row) => row.run_id));
            for (const [runId, tracked] of runs) {
                if (
                    listed.has(runId) || !isTrackedRunInFlight(tracked)
                    || tracked.checkedAt >= response.checked_at
                ) {
                    continue;
                }
                runs.set(runId, { ...tracked, retired: true });
                retired.push(tracked.row);
            }
            if (globalCheckedAt === null || response.checked_at >= globalCheckedAt) {
                globalCheckedAt = response.checked_at;
            }
        }
        emit();
        for (const row of delivered) {
            safely(() => deps.onDelivered?.(row));
        }
        for (const row of closed) {
            safely(() => deps.onClosed?.(row));
        }
        for (const row of retired) {
            safely(() => deps.onRetired?.(row));
        }
    }

    async function checkAll(): Promise<void> {
        if (!running || halted || globalRead) {
            return;
        }
        clearTimer();
        const controller = new AbortController();
        globalRead = controller;
        kickPending = false;
        let response: WorkflowRunStatusResponse;
        try {
            response = await deps.fetchStatus(null, controller.signal);
        } catch (error) {
            if (globalRead !== controller) {
                return;
            }
            globalRead = null;
            const status = errorStatus(error);
            // The global read sends nothing a 400 could be about, so a 400 means the route
            // refuses this reader, as 401 and 403 do.
            if (status === 401 || status === 403 || status === 400) {
                halt();
                return;
            }
            failures += 1;
            globalError = true;
            emit();
            schedule();
            return;
        }
        if (globalRead !== controller) {
            return;
        }
        globalRead = null;
        failures = 0;
        globalError = false;
        apply(response, null);
        schedule();
    }

    function setConversation(conversationId: string, change: Partial<WorkflowRunConversationRead>): void {
        conversations.set(conversationId, { ...(conversations.get(conversationId) ?? EMPTY_CONVERSATION), ...change });
    }

    async function readConversation(conversationId: string, controller: AbortController): Promise<boolean> {
        const current = () => conversationReads.get(conversationId)?.controller === controller;
        setConversation(conversationId, { reading: true });
        emit();
        let response: WorkflowRunStatusResponse;
        try {
            response = await deps.fetchStatus(conversationId, controller.signal);
        } catch (error) {
            if (!current()) {
                return false;
            }
            conversationReads.delete(conversationId);
            setConversation(conversationId, { reading: false, error: WORKFLOW_STATUS_READ_ERROR_TEXT });
            const status = errorStatus(error);
            if (status === 401 || status === 403) {
                halt();
                return false;
            }
            emit();
            return false;
        }
        if (!current()) {
            return false;
        }
        conversationReads.delete(conversationId);
        conversationReadAt.set(conversationId, deps.now());
        const previous = conversations.get(conversationId)?.checkedAt ?? null;
        setConversation(conversationId, {
            reading: false,
            error: null,
            checkedAt: previous !== null && previous > response.checked_at ? previous : response.checked_at,
        });
        apply(response, conversationId);
        if (response.runs.some((row) => row.conversation_id === conversationId && isWorkflowRunInFlight(row))) {
            ladderIndex = 0;
            scheduleSooner();
        }
        return true;
    }

    return {
        start(): void {
            if (running) {
                return;
            }
            running = true;
            halted = false;
            ladderIndex = 0;
            failures = 0;
            kickPending = true;
            unsubscribeVisibility = deps.subscribeVisibility(onVisibilityChange);
            emit();
            if (deps.isVisible() || deps.desktopNotificationsOn()) {
                void checkAll();
            }
        },

        stop(): void {
            if (!running) {
                return;
            }
            running = false;
            clearTimer();
            abortAll();
            unsubscribeVisibility?.();
            unsubscribeVisibility = null;
            kickPending = false;
            failures = 0;
            globalError = false;
            emit();
        },

        kick(options = {}): void {
            if (!running || halted) {
                return;
            }
            ladderIndex = 0;
            kickPending = true;
            if (globalRead) {
                // The read under way may predate the new run; its completion schedules another.
                return;
            }
            if (options.immediate && (deps.isVisible() || deps.desktopNotificationsOn())) {
                void checkAll();
                return;
            }
            if (failures > 0 && timer !== null) {
                // Keep backing off.
                return;
            }
            scheduleSooner();
        },

        requestConversationRuns(conversationId, options = {}): Promise<boolean> {
            if (!running || halted || !isStatusConversationId(conversationId)) {
                return Promise.resolve(false);
            }
            const pending = conversationReads.get(conversationId);
            if (pending && !options.force) {
                return pending.promise;
            }
            if (!options.force) {
                const readAt = conversationReadAt.get(conversationId);
                if (readAt !== undefined && deps.now() - readAt < WORKFLOW_RUN_CONVERSATION_DEDUPE_MS) {
                    return Promise.resolve(true);
                }
            }
            // A forced read replaces one under way, which may predate what forced it.
            pending?.controller.abort();
            const controller = new AbortController();
            // Registered before the read starts, so even a read that fails at once is the current one.
            const read = { controller, promise: Promise.resolve(false) };
            conversationReads.set(conversationId, read);
            read.promise = readConversation(conversationId, controller);
            return read.promise;
        },

        getSnapshot(): WorkflowRunTrackerSnapshot {
            return snapshot;
        },
    };
}
