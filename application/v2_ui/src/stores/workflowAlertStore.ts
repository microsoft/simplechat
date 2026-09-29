// workflowAlertStore.ts
// What the workflow-alert notice and card are showing, and what happens next.
//
// Alerts arrive from the runtime (useWorkflowAlertRuntime.ts), which fetches them when N1's
// bell poller says something changed. They wait in `queue` until this tab may show them:
// the tab is visible, the mobile navigation is closed, and no dialog is open. Then every
// waiting alert is claimed at once (workflowAlertClaims.ts) and the ones this tab won become
// `entries`: grouped by workflow, loudest first. The notice shows the first entry and says
// how many more are waiting; the card shows one entry at a time.
//
// A presentation ends when the notice tucks into the bell, is closed, or the card closes.
// Nothing is marked read by ending it. Whatever the reader did not act on stays unread in
// the bell, and because each alert was claimed it does not pop up again, here or elsewhere.
//
//   idle ──alerts claimed──▶ notice ──open──▶ card ──close / last entry handled──▶ idle
//                              │
//                              └──timer or close──▶ tucking ──animation done──▶ idle
//
// New alerts that arrive while the notice or the card is up join it, re-sorted, so a critical
// alert takes the notice over from a medium one. The card keeps the entry it was showing.

import { create } from 'zustand';
import { claimWorkflowAlerts, resetWorkflowAlertClaims } from '../lib/workflowAlertClaims';
import { tuckIntoTarget } from '../lib/workflowAlertMotion';
import {
    WORKFLOW_ALERT_PRIORITY_LABELS,
    describeWorkflowAlertGroup,
    groupWorkflowAlerts,
    isWorkflowAlertPopupEligible,
    workflowAlertEntryIds,
    type WorkflowAlert,
    type WorkflowAlertEntry,
} from '../lib/workflowAlertNotices';
import { workflowAlertServerActions, type WorkflowAlertActions } from '../lib/workflowAlertActions';

export type WorkflowAlertPhase = 'idle' | 'notice' | 'card' | 'tucking';

/** A: a callout under My Workspace in the rail. B: a pill at the top of the content column. */
export type WorkflowAlertNoticeStyle = 'callout' | 'pill';

export interface WorkflowAlertAnnouncement {
    text: string;
    assertive: boolean;
    /** Changes with every announcement, so the same words said twice are still said. */
    token: number;
}

/** Marks every element that belongs to the alert UI, so the dialog gate and focus tracking can skip it. */
export const WORKFLOW_ALERT_UI_ATTRIBUTE = 'data-workflow-alert-ui';

interface WorkflowAlertState {
    /** Eligible alerts this tab has not claimed yet, newest first. */
    queue: WorkflowAlert[];
    /** What is being presented: the alerts this tab claimed, grouped and sorted. */
    entries: WorkflowAlertEntry[];
    phase: WorkflowAlertPhase;
    /** The entry the card shows. */
    cardIndex: number;
    /** True while something on the page means the notice must wait. */
    suspended: boolean;
    style: WorkflowAlertNoticeStyle;
    /** Bumped when a notice tucks into the bell, which swings once in answer. */
    ringToken: number;
    /** Bumped when the presentation gains alerts, which restarts the notice's timer. */
    batchToken: number;
    announcement: WorkflowAlertAnnouncement | null;
    /** A read or dismiss request from the card is on its way. */
    busy: boolean;
    /** The notice's box at the moment it was opened, for the card to grow out of. */
    growFrom: DOMRect | null;

    receiveAlerts: (alerts: WorkflowAlert[], options?: { complete?: boolean }) => void;
    removeAlerts: (ids: Iterable<string>) => void;
    /** Everything unread has gone; drop what is waiting and what is showing. */
    clearAll: () => void;
    setSuspended: (suspended: boolean) => void;
    setStyle: (style: WorkflowAlertNoticeStyle) => void;
    openCard: () => void;
    closeCard: () => void;
    tuck: () => Promise<void>;
    nextEntry: () => void;
    markEntryRead: () => Promise<void>;
    dismissEntry: () => Promise<void>;
    markAllRead: () => Promise<void>;
    /** An open action on the card's current entry: its lead alert is marked read and the card closes. */
    markLeadReadForOpen: () => Promise<void>;
}

// Ids that must not be presented again: claimed by any tab, or acted on here.
const settled = new Set<string>();
let claiming = false;
// Bumped by a reset, so a claim that was on its way does not present into the new slate.
let epoch = 0;
let actions: WorkflowAlertActions = workflowAlertServerActions;
let announcementToken = 0;

// The control that last held focus outside the alert UI, for the card to hand focus back to.
// The notice never takes focus, so this is where the reader was before they reached for it.
let lastOutsideFocus: HTMLElement | null = null;
if (typeof document !== 'undefined') {
    document.addEventListener('focusin', (event) => {
        const target = event.target;
        if (target instanceof HTMLElement && target !== document.body
            && !target.closest(`[${WORKFLOW_ALERT_UI_ATTRIBUTE}]`)) {
            lastOutsideFocus = target;
        }
    }, true);
}

/**
 * Where focus goes when the card closes and nothing else claimed it: back where the reader
 * was, or to the bell, which is where every alert can be found again.
 */
export function workflowAlertReturnFocusTarget(): HTMLElement | null {
    if (lastOutsideFocus?.isConnected && !lastOutsideFocus.closest('[inert], [hidden]')) {
        return lastOutsideFocus;
    }
    return document.querySelector<HTMLElement>('[data-notification-bell]');
}

/** Swap the read and dismiss calls. Only the alert lab does, so its samples never reach the server. */
export function setWorkflowAlertActions(next: WorkflowAlertActions | null): void {
    actions = next ?? workflowAlertServerActions;
}

function announcementFor(entries: WorkflowAlertEntry[]): WorkflowAlertAnnouncement | null {
    const head = entries[0];
    if (!head) {
        return null;
    }
    const alert = head.lead;
    const kind = alert.category === 'failure' ? 'workflow run failed' : 'workflow alert';
    const parts = [`${WORKFLOW_ALERT_PRIORITY_LABELS[head.priority]} priority ${kind}: ${alert.title}, from ${alert.workflowName}.`];
    const group = describeWorkflowAlertGroup(head);
    if (group) {
        parts.push(`${group}.`);
    }
    if (entries.length > 1) {
        parts.push(`${entries.length - 1} more waiting.`);
    }
    announcementToken += 1;
    return { text: parts.join(' '), assertive: head.priority === 'critical', token: announcementToken };
}

function withoutIds(entries: WorkflowAlertEntry[], ids: Set<string>): WorkflowAlertEntry[] {
    const kept = entries.flatMap((entry) => entry.alerts).filter((alert) => !ids.has(alert.id));
    return groupWorkflowAlerts(kept);
}

export const useWorkflowAlertStore = create<WorkflowAlertState>((set, get) => {
    /** The index of the entry with `key` in `entries`, or the nearest one that still exists. */
    const indexFor = (entries: WorkflowAlertEntry[], key: string | undefined, fallback: number): number => {
        const found = key ? entries.findIndex((entry) => entry.key === key) : -1;
        if (found >= 0) {
            return found;
        }
        return Math.max(0, Math.min(fallback, entries.length - 1));
    };

    /** Claim what is waiting and present it, if this tab may present anything now. */
    const pump = (): void => {
        const state = get();
        if (claiming || state.suspended || state.phase === 'tucking') {
            return;
        }
        const now = Date.now();
        const candidates = state.queue.filter((alert) => !settled.has(alert.id) && isWorkflowAlertPopupEligible(alert, now));
        if (!candidates.length) {
            if (state.queue.length) {
                set({ queue: [] });
            }
            return;
        }
        claiming = true;
        const claimEpoch = epoch;
        const ids = candidates.map((alert) => alert.id);
        void claimWorkflowAlerts(ids)
            .catch(() => [] as string[])
            .then((won) => {
                if (claimEpoch !== epoch) {
                    return;
                }
                claiming = false;
                for (const id of ids) {
                    settled.add(id);
                }
                const current = get();
                const queue = current.queue.filter((alert) => !settled.has(alert.id));
                const wonIds = new Set(won);
                const winners = candidates.filter((alert) => wonIds.has(alert.id));
                if (!winners.length || current.phase === 'tucking') {
                    set({ queue });
                    pump();
                    return;
                }
                const entries = groupWorkflowAlerts([...current.entries.flatMap((entry) => entry.alerts), ...winners]);
                if (current.phase === 'idle') {
                    set({
                        queue,
                        entries,
                        phase: 'notice',
                        cardIndex: 0,
                        batchToken: current.batchToken + 1,
                        announcement: announcementFor(entries),
                    });
                } else {
                    const headChanged = current.entries[0]?.key !== entries[0]?.key
                        || current.entries[0]?.priority !== entries[0]?.priority;
                    set({
                        queue,
                        entries,
                        cardIndex: indexFor(entries, current.entries[current.cardIndex]?.key, current.cardIndex),
                        batchToken: current.batchToken + 1,
                        announcement: current.phase === 'notice' && headChanged ? announcementFor(entries) : current.announcement,
                    });
                }
                pump();
            });
    };

    /** End the presentation. Whatever was not acted on stays unread, and claimed. */
    const finish = (patch: Partial<WorkflowAlertState> = {}): void => {
        set({ entries: [], phase: 'idle', cardIndex: 0, growFrom: null, busy: false, ...patch });
        pump();
    };

    /** Forget alerts that were handled, and close whatever has nothing left to show. */
    const drop = (ids: Iterable<string>): void => {
        const gone = new Set(ids);
        if (!gone.size) {
            return;
        }
        for (const id of gone) {
            settled.add(id);
        }
        const state = get();
        const queue = state.queue.filter((alert) => !gone.has(alert.id));
        const entries = withoutIds(state.entries, gone);
        if (!entries.length && state.phase !== 'idle') {
            if (state.phase === 'tucking') {
                set({ queue });
                return;
            }
            finish({ queue });
            return;
        }
        set({
            queue,
            entries,
            cardIndex: indexFor(entries, state.entries[state.cardIndex]?.key, state.cardIndex),
        });
    };

    const act = async (ids: string[], request: (ids: string[]) => Promise<string[]>): Promise<void> => {
        if (!ids.length || get().busy) {
            return;
        }
        set({ busy: true });
        let done: string[] = [];
        try {
            done = await request(ids);
        } catch {
            done = [];
        }
        set({ busy: false });
        // Only what the server accepted goes; a group that partly failed stays, smaller.
        drop(done);
    };

    return {
        queue: [],
        entries: [],
        phase: 'idle',
        cardIndex: 0,
        suspended: true,
        style: 'callout',
        ringToken: 0,
        batchToken: 0,
        announcement: null,
        busy: false,
        growFrom: null,

        receiveAlerts: (alerts, { complete = false } = {}) => {
            const now = Date.now();
            const queue = alerts.filter((alert) => !settled.has(alert.id) && isWorkflowAlertPopupEligible(alert, now));
            set({ queue });
            if (complete) {
                // A short answer is every unread pop-up alert there is, so one missing from it
                // was read or dismissed somewhere else.
                const present = new Set(alerts.map((alert) => alert.id));
                const missing = get().entries.flatMap(workflowAlertEntryIds).filter((id) => !present.has(id));
                drop(missing);
            }
            pump();
        },

        removeAlerts: (ids) => drop(ids),

        clearAll: () => {
            const state = get();
            drop([...state.queue.map((alert) => alert.id), ...state.entries.flatMap(workflowAlertEntryIds)]);
            set({ queue: [] });
        },

        setSuspended: (suspended) => {
            if (get().suspended === suspended) {
                return;
            }
            set({ suspended });
            if (!suspended) {
                pump();
            }
        },

        setStyle: (style) => set({ style }),

        openCard: () => {
            if (get().phase !== 'notice' || !get().entries.length) {
                return;
            }
            const notice = document.querySelector(`[data-workflow-alert-notice]`);
            set({ phase: 'card', cardIndex: 0, growFrom: notice ? notice.getBoundingClientRect() : null });
        },

        closeCard: () => {
            if (get().phase === 'card') {
                finish();
            }
        },

        tuck: async () => {
            if (get().phase !== 'notice') {
                return;
            }
            set({ phase: 'tucking' });
            await tuckIntoTarget(
                document.querySelector<HTMLElement>('[data-workflow-alert-notice]'),
                document.querySelector('[data-notification-bell]'),
            );
            if (get().phase === 'tucking') {
                finish({ ringToken: get().ringToken + 1 });
            }
        },

        nextEntry: () => {
            const { entries, cardIndex } = get();
            if (entries.length > 1) {
                set({ cardIndex: (cardIndex + 1) % entries.length });
            }
        },

        markEntryRead: async () => {
            const entry = get().entries[get().cardIndex];
            if (entry) {
                await act(workflowAlertEntryIds(entry), (ids) => actions.markRead(ids));
            }
        },

        dismissEntry: async () => {
            const entry = get().entries[get().cardIndex];
            if (entry) {
                await act(workflowAlertEntryIds(entry), (ids) => actions.dismiss(ids));
            }
        },

        markAllRead: async () => {
            await act(get().entries.flatMap(workflowAlertEntryIds), (ids) => actions.markRead(ids));
        },

        markLeadReadForOpen: async () => {
            const entry = get().entries[get().cardIndex];
            if (!entry) {
                return;
            }
            const leadId = entry.lead.id;
            settled.add(leadId);
            finish();
            try {
                await actions.markRead([leadId]);
            } catch {
                /* The adapter reports its own failures; the alert simply stays unread in the bell. */
            }
        },
    };
});

/** Back to a clean slate: nothing waiting, nothing claimed. Only the alert lab and tests call this. */
export function resetWorkflowAlertsForLab(): void {
    epoch += 1;
    settled.clear();
    claiming = false;
    resetWorkflowAlertClaims();
    useWorkflowAlertStore.setState({
        queue: [],
        entries: [],
        phase: 'idle',
        cardIndex: 0,
        batchToken: 0,
        announcement: null,
        busy: false,
        growFrom: null,
    });
}
