// useWorkflowRunTracker.ts
// Runs the tab's one workflow run tracker, and lands each result it sees posted back to a chat.
//
// Called once, from the application root, like useNotificationRuntime, rather than from the chat
// page: the chat list's running tag shows wherever the list does, and a result can be posted while
// the reader is anywhere in the app. The tracker is a module-level singleton and its start is
// idempotent, so a remount or a change of page never adds a second one.
//
// A posted result lands as a streamed reply does. In the open chat the messages are re-read through
// the store's normal path, never while a reply is still streaming, and the unread marker the server
// set is then settled by the same watched-or-deferred rules. In any other chat the marker shows in
// the list and the bell's count is refreshed. The server has already marked the chat unread and
// added the bell notice, so nothing here creates another.

import { useEffect } from 'react';
import { desktopNotificationPermission, desktopNotificationsEnabled } from './desktopNotifications';
import { hasActiveOrchestration } from './orchestrationController';
import { subscribeCompletedReplies, type CompletedReply } from './replyEvents';
import { createWorkflowRunTracker, type WorkflowRunTracker } from './workflowRunTracker';
import { fetchWorkflowRunStatus, type WorkflowRunRow, type WorkflowRunStatusRow } from './workflowRunStatus';
import { settleCompletedReply, useChatStore } from '../stores/chatStore';
import { refreshNotificationCount } from '../stores/notificationStore';
import { useOrchestrationStore } from '../stores/orchestrationStore';
import { useWorkflowRunTrackerStore } from '../stores/workflowRunTrackerStore';

/** How often a result waiting for the open chat to go quiet re-checks it, without a request. */
const CHAT_QUIET_RECHECK_MS = 2_000;

let tracker: WorkflowRunTracker | null = null;

// Results posted to the open chat while it was busy, oldest first.
const waitingDeliveries: WorkflowRunStatusRow[] = [];
let reloadingMessages = false;
let stopWaitingForChat: (() => void) | null = null;

// Runs that dropped out of the read being applied, settled together right after it.
const retiredRows: WorkflowRunRow[] = [];
let retiredQueued = false;

function trackerInstance(): WorkflowRunTracker {
    if (tracker === null) {
        tracker = createWorkflowRunTracker({
            fetchStatus: fetchWorkflowRunStatus,
            setTimer: (callback, delayMs) => window.setTimeout(callback, delayMs),
            clearTimer: (handle) => window.clearTimeout(handle as number),
            now: () => Date.now(),
            isVisible: () => document.visibilityState === 'visible',
            subscribeVisibility: (listener) => {
                document.addEventListener('visibilitychange', listener);
                return () => document.removeEventListener('visibilitychange', listener);
            },
            // The same two checks the desktop notifier makes before it shows anything.
            desktopNotificationsOn: () =>
                desktopNotificationsEnabled() && desktopNotificationPermission() === 'granted',
            onState: (snapshot) => useWorkflowRunTrackerStore.getState().publish(snapshot),
            onDelivered: landDelivery,
            // The server's notice for a result that couldn't be posted is the whole report.
            onClosed: () => {
                void refreshNotificationCount('action');
            },
            onRetired: settleRetiredRun,
        });
    }
    return tracker;
}

/**
 * Read one chat's runs through the tab's tracker. Resolves false when the tracker isn't running,
 * has stopped for the page session, or the read failed.
 */
export function requestWorkflowConversationRuns(
    conversationId: string,
    options?: { force?: boolean },
): Promise<boolean> {
    return tracker ? tracker.requestConversationRuns(conversationId, options) : Promise.resolve(false);
}

/** Tell the tracker a run may have started or changed, so it checks again soon. */
export function kickWorkflowRunTracker(options?: { immediate?: boolean }): void {
    tracker?.kick(options);
}

function chatIsBusy(conversationId: string): boolean {
    const { streaming, messagesLoading } = useChatStore.getState();
    return streaming || messagesLoading || hasActiveOrchestration(conversationId);
}

/** Reload the chat list from its first page, unless it hasn't loaded yet, is loading or is filtered. */
function reloadConversationList(): void {
    const { conversations, conversationsLoading, searchTerm, loadConversations } = useChatStore.getState();
    if (conversations.length === 0 || conversationsLoading || searchTerm) {
        return;
    }
    void loadConversations({ reset: true });
}

function settleDelivery(row: WorkflowRunStatusRow, current: boolean): void {
    const listed = useChatStore.getState().conversations.find((item) => item.id === row.conversation_id);
    settleCompletedReply(
        {
            conversationId: row.conversation_id,
            messageId: row.delivery.message_id,
            runId: row.run_id,
            conversationTitle: listed?.title || null,
            blocked: false,
            source: 'workflow',
        },
        // The server marks a chat unread whenever it posts a result to it.
        { current, serverMarksUnread: true },
    );
}

function stopWaiting(): void {
    stopWaitingForChat?.();
    stopWaitingForChat = null;
}

function waitForQuietChat(): void {
    if (stopWaitingForChat) {
        return;
    }
    const recheck = () => landWaitingDeliveries();
    const stopChat = useChatStore.subscribe((state, previous) => {
        if (
            state.streaming !== previous.streaming
            || state.messagesLoading !== previous.messagesLoading
            || state.activeConversationId !== previous.activeConversationId
        ) {
            recheck();
        }
    });
    const stopOrchestration = useOrchestrationStore.subscribe((state, previous) => {
        if (state.inFlight !== previous.inFlight) {
            recheck();
        }
    });
    // A plan's stream ends in the orchestration controller, which no store reports directly.
    const interval = window.setInterval(recheck, CHAT_QUIET_RECHECK_MS);
    stopWaitingForChat = () => {
        stopChat();
        stopOrchestration();
        window.clearInterval(interval);
    };
}

/** Re-read the open chat, then settle the results that were waiting for it. */
async function reloadAndSettle(rows: WorkflowRunStatusRow[]): Promise<void> {
    try {
        await useChatStore.getState().reloadMessages();
    } finally {
        reloadingMessages = false;
        const { activeConversationId, messages } = useChatStore.getState();
        for (const row of rows) {
            // Only a result now on screen counts as seen; one the re-read missed stays unread.
            const shown = row.conversation_id === activeConversationId
                && messages.some((message) => message.id === row.delivery.message_id);
            settleDelivery(row, shown);
        }
        landWaitingDeliveries();
    }
}

/**
 * Land what is waiting: results for any other chat straight away, results for the open chat once
 * it is quiet, with one re-read for all of them.
 */
function landWaitingDeliveries(): void {
    if (reloadingMessages) {
        return;
    }
    if (waitingDeliveries.length === 0) {
        stopWaiting();
        return;
    }
    const openId = useChatStore.getState().activeConversationId;
    const elsewhere = waitingDeliveries.filter((row) => row.conversation_id !== openId);
    const here = waitingDeliveries.filter((row) => row.conversation_id === openId);
    const reloadNow = here.length > 0 && openId !== null && !chatIsBusy(openId);
    waitingDeliveries.splice(0, waitingDeliveries.length, ...(reloadNow ? [] : here));
    // Set before anything is settled, so a store change made while settling can't start a second
    // re-read of the same results.
    reloadingMessages = reloadNow;
    if (waitingDeliveries.length === 0) {
        stopWaiting();
    } else {
        waitForQuietChat();
    }
    for (const row of elsewhere) {
        settleDelivery(row, false);
        if (!useChatStore.getState().conversations.some((item) => item.id === row.conversation_id)) {
            reloadConversationList();
        }
    }
    if (reloadNow) {
        void reloadAndSettle(here);
    }
}

function landDelivery(row: WorkflowRunStatusRow): void {
    waitingDeliveries.push(row);
    landWaitingDeliveries();
}

/**
 * Runs that were in flight and dropped out of one complete read, so they have stopped and how is
 * not known. They are settled together once that read has been applied: the open chat's runs are
 * read again, forced past the dedupe because the card's last read predates the drop; for any other
 * chat the list and the bell are refreshed, because a result may have been posted while this tab
 * wasn't looking. Each happens at most once per read, however many runs dropped out.
 */
function settleRetiredRuns(): void {
    retiredQueued = false;
    const rows = retiredRows.splice(0, retiredRows.length);
    const openId = useChatStore.getState().activeConversationId;
    if (openId !== null && rows.some((row) => row.conversation_id === openId)) {
        void tracker?.requestConversationRuns(openId, { force: true });
    }
    if (rows.some((row) => row.conversation_id !== openId)) {
        reloadConversationList();
        void refreshNotificationCount('action');
    }
}

function settleRetiredRun(row: WorkflowRunRow): void {
    retiredRows.push(row);
    if (!retiredQueued) {
        retiredQueued = true;
        queueMicrotask(settleRetiredRuns);
    }
}

function checkAfterPlanAnswer(reply: CompletedReply): void {
    // A plan's answer may have started workflows.
    if (reply.source === 'orchestration') {
        tracker?.kick({ immediate: true });
    }
}

/**
 * `ready` is whether the signed-in session has loaded and the user can use saved workflows that
 * chats start (`workflowRunTrackerShouldRun`). The tracker stops when it turns false.
 */
export function useWorkflowRunTracker(ready: boolean): void {
    useEffect(() => {
        if (!ready) {
            return undefined;
        }
        const instance = trackerInstance();
        instance.start();
        const stopListening = subscribeCompletedReplies(checkAfterPlanAnswer);
        return () => {
            stopListening();
            instance.stop();
            stopWaiting();
            waitingDeliveries.length = 0;
            retiredRows.length = 0;
        };
    }, [ready]);
}
