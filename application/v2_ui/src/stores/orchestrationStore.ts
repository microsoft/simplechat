// orchestrationStore.ts
// Every orchestration turn's plan, question and live step state, and every run still in flight.
//
// This follows `imageProposalStore.ts` deliberately and for the identical reasons, which are
// worth restating because they are the whole point of the file existing:
//
//   - State is keyed by CONVERSATION AND TURN, never held in a component. React rebuilds the
//     markdown subtree on every message re-render, and `selectConversation` clears the message
//     list, so a plan card that kept its plan, its edits or its running steps in React state
//     would have them destroyed by the very events the user is waiting on -- they leave the
//     conversation, the run keeps going, and coming back shows a plan inviting them to approve
//     work that is already running.
//
//   - A run OUTLIVES the conversation view, and outlives the page. The run is a blocking POST
//     the server finishes whether the browser is there or not, so the fact that one started has
//     to survive a reload: lose it and the card offers to start it again (a duplicate run);
//     forget it and the card shows nothing while the answer is being written. In-flight runs are
//     therefore persisted to `sessionStorage`, kept apart from the plan/step state because they
//     are the part that has to survive the page rather than merely the re-render.
//
// The plan itself is not persisted: it is large, the server owns it, and a reload re-fetches or
// re-plans. What is persisted is the minimum needed to recognise a run that is already running.

import { create } from 'zustand';
import {
    applyPlanEdits,
    disableStep as narrowDisableStep,
    emptyPlanEdits,
    enableStep as narrowEnableStep,
    normalizePlan,
    removeDocumentFromStep as narrowRemoveDocument,
    restoreDocumentToStep as narrowRestoreDocument,
} from '../lib/orchestrationPlan';
import type {
    Elicitation,
    OrchestrationPlan,
    OrchestrationStep,
    PlanEdits,
    RunStreamEvent,
    StepStatus,
} from '../lib/orchestration';

/** Turn state is filed per turn, so one turn's re-plan cannot disturb another's. */
function scopeKey(conversationId: string, turnId: string): string {
    return `${conversationId}\u0000${turnId}`;
}

/** The conversation half of a `scopeKey`, for pruning and per-conversation reads. */
function conversationOfScope(key: string): string {
    return key.split('\u0000')[0] ?? '';
}

const STEP_STATUS_SET: ReadonlySet<StepStatus> = new Set<StepStatus>([
    'pending',
    'running',
    'completed',
    'failed',
    'skipped',
    'cancelled',
]);

function coerceStepStatus(value: unknown): StepStatus | null {
    return typeof value === 'string' && STEP_STATUS_SET.has(value as StepStatus)
        ? (value as StepStatus)
        : null;
}

/* -------------------------------------------------------------------------- */
/* Shapes                                                                      */
/* -------------------------------------------------------------------------- */

/** One step's live runtime, driven by `orchestration_step` frames rather than the plan object. */
export interface StepRuntime {
    status: StepStatus;
    summary: string;
}

export type StepRuntimeMap = Record<string, StepRuntime>;

/** How a run ended. */
export type RunOutcome = 'completed' | 'failed' | 'cancelled';

/**
 * A run that has started and not yet settled.
 *
 * This is the persisted half -- enough to recognise the run after a reload, and nothing that
 * depends on the plan still being in memory. `resumed` marks a record adopted from storage
 * rather than started by this page, which is the difference between "this tab is running it" and
 * "some earlier tab was".
 */
export interface TrackedRun {
    conversationId: string;
    turnId: string;
    runId: string;
    planId: string;
    /** Epoch milliseconds. Bounds the record's own lifetime across a reload. */
    startedAt: number;
    resumed: boolean;
}

/** A settled run kept for the conversation's history. */
export interface RunHistoryEntry {
    runId: string;
    planId: string;
    turnId: string;
    status: RunOutcome;
    finishedAt: number;
    intentSummary: string;
}

/** History is bounded per conversation; a long session should not grow one without limit. */
const MAX_HISTORY_PER_CONVERSATION = 25;

const EMPTY_EDITS: PlanEdits = { disabled_step_ids: [], removed_document_ids: {} };
const EMPTY_STEP_RUNTIME: StepRuntimeMap = {};
const EMPTY_HISTORY: readonly RunHistoryEntry[] = [];
const EMPTY_RUNS: readonly TrackedRun[] = [];

interface OrchestrationState {
    /** The current plan per turn, keyed by `scopeKey`. */
    plans: Record<string, OrchestrationPlan>;
    /** A pending question per turn, when the planner asked instead of planning. */
    elicitations: Record<string, Elicitation>;
    /** The user's narrowing edits per turn, before the run. */
    edits: Record<string, PlanEdits>;
    /** Per-step live status per turn: `scopeKey` then step id. */
    stepRuntime: Record<string, StepRuntimeMap>;
    /** Runs still in flight, by run id. Persisted. */
    inFlight: Record<string, TrackedRun>;
    /** Settled runs per conversation, newest first. */
    history: Record<string, RunHistoryEntry[]>;
    /** The run the drawer is pinned to, or null meaning "the current one". */
    pinnedRunId: string | null;
    /**
     * The conversation whose orchestration surface is actually on screen, or null.
     *
     * Not the same question as which conversation is open: the chat store keeps an active
     * conversation while the user reads their documents elsewhere, where no plan card is visible.
     * Only the chat page knows, so the chat page says.
     */
    visibleConversationId: string | null;

    /**
     * The turn whose plan or question is currently inline in each conversation's thread.
     *
     * `MessageList` has no other way to know which turn to draw a card for. A conversation can
     * hold many settled turns, but only the latest owns the card at the foot of the thread, and
     * that turn identity is minted on submit and reused across the turn's re-plans. Keyed by
     * conversation, not `scopeKey`, so returning to an earlier thread still finds its pending
     * card, and so a fresh submit simply overwrites the one turn a conversation shows inline.
     */
    activeTurns: Record<string, string>;

    /** Adopt a plan for a turn, replacing any pending question and re-seeding on a new revision. */
    setPlan: (conversationId: string, turnId: string, plan: unknown) => void;
    /** Forget a turn's plan. */
    clearPlan: (conversationId: string, turnId: string) => void;

    /** Adopt a question for a turn, replacing any plan it supersedes. */
    setElicitation: (conversationId: string, turnId: string, elicitation: Elicitation) => void;
    /** Forget a turn's question, typically once it has been answered. */
    clearElicitation: (conversationId: string, turnId: string) => void;

    disableStep: (conversationId: string, turnId: string, step: OrchestrationStep) => void;
    enableStep: (conversationId: string, turnId: string, stepId: string) => void;
    removeDocument: (
        conversationId: string,
        turnId: string,
        step: OrchestrationStep,
        documentId: string,
    ) => void;
    restoreDocument: (
        conversationId: string,
        turnId: string,
        stepId: string,
        documentId: string,
    ) => void;
    /** Drop every narrowing on a turn, restoring the plan the planner proposed. */
    resetEdits: (conversationId: string, turnId: string) => void;

    /** Seed every step of a plan to its own status, so the card draws before the first frame. */
    seedStepRuntime: (conversationId: string, turnId: string, plan: OrchestrationPlan) => void;
    /** Patch one step's runtime from an explicit status/summary. */
    updateStepStatus: (
        conversationId: string,
        turnId: string,
        stepId: string,
        patch: Partial<StepRuntime>,
    ) => void;
    /** Patch one step's runtime from an `orchestration_step` frame. */
    applyStepEvent: (conversationId: string, turnId: string, event: RunStreamEvent) => void;

    /**
     * Record a run as started.
     *
     * Returns false when a run with this id is already tracked, which is the guard against a
     * second POST for a run that is already going -- reachable through a double-press, or through
     * a restored record whose card offers Run again before the restore has been reconciled.
     */
    beginRun: (record: Omit<TrackedRun, 'resumed'>) => boolean;
    /** Forget a run, recording how it ended in the conversation's history. */
    endRun: (runId: string, outcome: RunOutcome) => void;
    /** Adopt run records restored from storage after a reload. */
    restoreRuns: (records: TrackedRun[]) => void;

    /** Pin the drawer to a run, or pass null to follow the current one. */
    pinRun: (runId: string | null) => void;

    /** Record which conversation's orchestration surface the user can currently see. */
    setVisibleConversation: (conversationId: string | null) => void;

    /** Mark which turn owns the inline card for a conversation. */
    setActiveTurn: (conversationId: string, turnId: string) => void;
    /** Forget a conversation's inline turn, e.g. once its card is dismissed. */
    clearActiveTurn: (conversationId: string) => void;

    /**
     * Drop the per-turn state of conversations with nothing in flight.
     *
     * Plan, question, edit and runtime state are cheap but unbounded, and a long session that
     * opens many conversations would otherwise keep one entry per turn it ever displayed. A
     * conversation with a run in flight is kept whatever else is true of it, as is the one named.
     */
    pruneSettled: (keepConversationId: string | null) => void;
}

/* -------------------------------------------------------------------------- */
/* Store                                                                       */
/* -------------------------------------------------------------------------- */

export const useOrchestrationStore = create<OrchestrationState>((set, get) => ({
    plans: {},
    elicitations: {},
    edits: {},
    stepRuntime: {},
    inFlight: {},
    history: {},
    pinnedRunId: null,
    visibleConversationId: null,
    activeTurns: {},

    setPlan: (conversationId, turnId, rawPlan) => {
        if (!conversationId || !turnId) {
            return;
        }
        const plan = normalizePlan(rawPlan);
        if (!plan) {
            return;
        }

        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const previous = state.plans[key];
            // A new plan identity (a re-plan) invalidates the edits and runtime, which reference
            // the previous plan's step ids; the same identity keeps them, so a redundant set --
            // or a plan echoed mid-run -- does not wipe a user's narrowing or a step's progress.
            const sameIdentity =
                previous &&
                previous.plan_id === plan.plan_id &&
                previous.revision === plan.revision;

            const elicitations = { ...state.elicitations };
            delete elicitations[key];

            if (sameIdentity) {
                return { plans: { ...state.plans, [key]: plan }, elicitations };
            }

            const runtime: StepRuntimeMap = {};
            for (const step of plan.steps) {
                runtime[step.step_id] = { status: step.status, summary: '' };
            }

            return {
                plans: { ...state.plans, [key]: plan },
                elicitations,
                edits: { ...state.edits, [key]: emptyPlanEdits() },
                stepRuntime: { ...state.stepRuntime, [key]: runtime },
            };
        });
    },

    clearPlan: (conversationId, turnId) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            if (!(key in state.plans)) {
                return {};
            }
            const plans = { ...state.plans };
            delete plans[key];
            return { plans };
        });
    },

    setElicitation: (conversationId, turnId, elicitation) => {
        if (!conversationId || !turnId || !elicitation) {
            return;
        }
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            // A question and a plan are mutually exclusive answers to the same turn, so adopting
            // one clears the other.
            const plans = { ...state.plans };
            delete plans[key];
            return {
                plans,
                elicitations: { ...state.elicitations, [key]: elicitation },
            };
        });
    },

    clearElicitation: (conversationId, turnId) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            if (!(key in state.elicitations)) {
                return {};
            }
            const elicitations = { ...state.elicitations };
            delete elicitations[key];
            return { elicitations };
        });
    },

    disableStep: (conversationId, turnId, step) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const current = state.edits[key] ?? emptyPlanEdits();
            const next = narrowDisableStep(current, step);
            if (next === current) {
                return {};
            }
            return { edits: { ...state.edits, [key]: next } };
        });
    },

    enableStep: (conversationId, turnId, stepId) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const current = state.edits[key] ?? emptyPlanEdits();
            const next = narrowEnableStep(current, stepId);
            if (next === current) {
                return {};
            }
            return { edits: { ...state.edits, [key]: next } };
        });
    },

    removeDocument: (conversationId, turnId, step, documentId) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const current = state.edits[key] ?? emptyPlanEdits();
            const next = narrowRemoveDocument(current, step, documentId);
            if (next === current) {
                return {};
            }
            return { edits: { ...state.edits, [key]: next } };
        });
    },

    restoreDocument: (conversationId, turnId, stepId, documentId) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const current = state.edits[key] ?? emptyPlanEdits();
            const next = narrowRestoreDocument(current, stepId, documentId);
            if (next === current) {
                return {};
            }
            return { edits: { ...state.edits, [key]: next } };
        });
    },

    resetEdits: (conversationId, turnId) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const current = state.edits[key];
            if (!current || (current.disabled_step_ids.length === 0 &&
                Object.keys(current.removed_document_ids).length === 0)) {
                return {};
            }
            return { edits: { ...state.edits, [key]: emptyPlanEdits() } };
        });
    },

    seedStepRuntime: (conversationId, turnId, plan) => {
        const key = scopeKey(conversationId, turnId);
        const runtime: StepRuntimeMap = {};
        for (const step of plan.steps) {
            runtime[step.step_id] = { status: step.status, summary: '' };
        }
        set((state) => ({ stepRuntime: { ...state.stepRuntime, [key]: runtime } }));
    },

    updateStepStatus: (conversationId, turnId, stepId, patch) => {
        if (!stepId) {
            return;
        }
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const current = state.stepRuntime[key] ?? EMPTY_STEP_RUNTIME;
            const existing = current[stepId] ?? { status: 'pending', summary: '' };
            const merged: StepRuntime = {
                status: patch.status ?? existing.status,
                summary: patch.summary ?? existing.summary,
            };
            if (merged.status === existing.status && merged.summary === existing.summary) {
                return {};
            }
            return {
                stepRuntime: {
                    ...state.stepRuntime,
                    [key]: { ...current, [stepId]: merged },
                },
            };
        });
    },

    applyStepEvent: (conversationId, turnId, event) => {
        const stepId = typeof event.step_id === 'string' ? event.step_id : '';
        if (!stepId) {
            return;
        }
        const patch: Partial<StepRuntime> = {};
        const status = coerceStepStatus(event.status);
        if (status) {
            patch.status = status;
        }
        if (typeof event.summary === 'string') {
            patch.summary = event.summary;
        }
        if (patch.status === undefined && patch.summary === undefined) {
            return;
        }
        get().updateStepStatus(conversationId, turnId, stepId, patch);
    },

    beginRun: (record) => {
        if (!record.runId) {
            return false;
        }
        if (get().inFlight[record.runId]) {
            return false;
        }
        const tracked: TrackedRun = { ...record, resumed: false };
        const inFlight = { ...get().inFlight, [record.runId]: tracked };
        set({ inFlight });
        saveRuns(Object.values(inFlight));
        return true;
    },

    endRun: (runId, outcome) => {
        const run = get().inFlight[runId];
        if (!run) {
            return;
        }

        const inFlight = { ...get().inFlight };
        delete inFlight[runId];

        set((state) => {
            const summary =
                state.plans[scopeKey(run.conversationId, run.turnId)]?.intent.summary ?? '';
            const entry: RunHistoryEntry = {
                runId: run.runId,
                planId: run.planId,
                turnId: run.turnId,
                status: outcome,
                finishedAt: Date.now(),
                intentSummary: summary,
            };
            const existing = state.history[run.conversationId] ?? [];
            const nextEntries = [entry, ...existing].slice(0, MAX_HISTORY_PER_CONVERSATION);

            // A pin to the run that just ended is released, so the drawer falls back to the
            // current run rather than staying pinned to a finished one.
            const pinnedRunId = state.pinnedRunId === runId ? null : state.pinnedRunId;

            return {
                inFlight,
                history: { ...state.history, [run.conversationId]: nextEntries },
                pinnedRunId,
            };
        });
        saveRuns(Object.values(inFlight));
    },

    restoreRuns: (records) => {
        if (records.length === 0) {
            return;
        }
        set((state) => {
            const inFlight = { ...state.inFlight };
            for (const record of records) {
                // A record started by this page is authoritative; it has a request behind it.
                if (inFlight[record.runId]) {
                    continue;
                }
                inFlight[record.runId] = record;
            }
            saveRuns(Object.values(inFlight));
            return { inFlight };
        });
    },

    pinRun: (runId) => {
        if (get().pinnedRunId === runId) {
            return;
        }
        set({ pinnedRunId: runId });
    },

    setVisibleConversation: (conversationId) => {
        if (get().visibleConversationId === conversationId) {
            return;
        }
        set({ visibleConversationId: conversationId });
    },

    setActiveTurn: (conversationId, turnId) => {
        if (!conversationId || !turnId) {
            return;
        }
        if (get().activeTurns[conversationId] === turnId) {
            return;
        }
        set((state) => ({
            activeTurns: { ...state.activeTurns, [conversationId]: turnId },
        }));
    },

    clearActiveTurn: (conversationId) => {
        set((state) => {
            if (!(conversationId in state.activeTurns)) {
                return {};
            }
            const activeTurns = { ...state.activeTurns };
            delete activeTurns[conversationId];
            return { activeTurns };
        });
    },

    pruneSettled: (keepConversationId) => {
        const busy = new Set<string>();
        for (const record of Object.values(get().inFlight)) {
            busy.add(record.conversationId);
        }
        if (keepConversationId) {
            busy.add(keepConversationId);
        }

        set((state) => {
            let removed = false;
            const plans: Record<string, OrchestrationPlan> = {};
            const elicitations: Record<string, Elicitation> = {};
            const edits: Record<string, PlanEdits> = {};
            const stepRuntime: Record<string, StepRuntimeMap> = {};

            const keep = (map: Record<string, unknown>, into: Record<string, unknown>) => {
                for (const [key, value] of Object.entries(map)) {
                    if (busy.has(conversationOfScope(key))) {
                        into[key] = value;
                    } else {
                        removed = true;
                    }
                }
            };

            keep(state.plans, plans as Record<string, unknown>);
            keep(state.elicitations, elicitations as Record<string, unknown>);
            keep(state.edits, edits as Record<string, unknown>);
            keep(state.stepRuntime, stepRuntime as Record<string, unknown>);

            // `activeTurns` is keyed by conversation, not `scopeKey`, so it is pruned on the plain
            // id. Dropping it in step with the plan it points at stops MessageList holding a turn
            // id whose plan has just been swept away.
            const activeTurns: Record<string, string> = {};
            for (const [conversationId, turnId] of Object.entries(state.activeTurns)) {
                if (busy.has(conversationId)) {
                    activeTurns[conversationId] = turnId;
                } else {
                    removed = true;
                }
            }

            return removed
                ? { plans, elicitations, edits, stepRuntime, activeTurns }
                : {};
        });
    },
}));

/* -------------------------------------------------------------------------- */
/* Reading                                                                     */
/* -------------------------------------------------------------------------- */

/** The plan for a turn, or null. */
export function selectPlan(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): OrchestrationPlan | null {
    if (!conversationId || !turnId) {
        return null;
    }
    return state.plans[scopeKey(conversationId, turnId)] ?? null;
}

/** The turn that owns a conversation's inline card, or null when it has none. */
export function selectActiveTurn(
    state: OrchestrationState,
    conversationId: string,
): string | null {
    if (!conversationId) {
        return null;
    }
    return state.activeTurns[conversationId] ?? null;
}

/** The pending question for a turn, or null. */
export function selectElicitation(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): Elicitation | null {
    if (!conversationId || !turnId) {
        return null;
    }
    return state.elicitations[scopeKey(conversationId, turnId)] ?? null;
}

/** The user's edits for a turn. Stable empty object when there are none. */
export function selectEdits(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): PlanEdits {
    if (!conversationId || !turnId) {
        return EMPTY_EDITS;
    }
    return state.edits[scopeKey(conversationId, turnId)] ?? EMPTY_EDITS;
}

/** The live step runtime for a turn. Stable empty object when there is none. */
export function selectStepRuntime(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): StepRuntimeMap {
    if (!conversationId || !turnId) {
        return EMPTY_STEP_RUNTIME;
    }
    return state.stepRuntime[scopeKey(conversationId, turnId)] ?? EMPTY_STEP_RUNTIME;
}

/**
 * The plan for a turn with the user's edits applied, ready for the card to render.
 *
 * Null when there is no plan. This is the same twin `applyPlanEdits` produces, computed against
 * the live edit set so the card shows exactly what the run request will carry.
 */
export function selectEditedPlan(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): OrchestrationPlan | null {
    const plan = selectPlan(state, conversationId, turnId);
    if (!plan) {
        return null;
    }
    return applyPlanEdits(plan, selectEdits(state, conversationId, turnId));
}

/** The runs in flight for a conversation. */
export function selectInFlightForConversation(
    state: OrchestrationState,
    conversationId: string,
): TrackedRun[] {
    if (!conversationId) {
        return EMPTY_RUNS as TrackedRun[];
    }
    return Object.values(state.inFlight).filter(
        (run) => run.conversationId === conversationId,
    );
}

/** How many runs are in flight for a conversation. Drives a row indicator. */
export function selectInFlightCount(
    state: OrchestrationState,
    conversationId: string,
): number {
    if (!conversationId) {
        return 0;
    }
    let count = 0;
    for (const run of Object.values(state.inFlight)) {
        if (run.conversationId === conversationId) {
            count += 1;
        }
    }
    return count;
}

/** A conversation's run history, newest first. Stable empty array when there is none. */
export function selectHistory(
    state: OrchestrationState,
    conversationId: string,
): readonly RunHistoryEntry[] {
    if (!conversationId) {
        return EMPTY_HISTORY;
    }
    return state.history[conversationId] ?? EMPTY_HISTORY;
}

/**
 * The run the drawer should show for a conversation.
 *
 * The explicitly pinned run if one is pinned and still tracked; otherwise "the current one",
 * read as the most recently started run in flight for the conversation. Null when neither
 * applies, which the drawer reads as "nothing running to show".
 */
export function resolveDrawerRun(
    state: OrchestrationState,
    conversationId: string,
): TrackedRun | null {
    if (state.pinnedRunId) {
        const pinned = state.inFlight[state.pinnedRunId];
        if (pinned) {
            return pinned;
        }
    }
    let current: TrackedRun | null = null;
    for (const run of Object.values(state.inFlight)) {
        if (run.conversationId !== conversationId) {
            continue;
        }
        if (!current || run.startedAt > current.startedAt) {
            current = run;
        }
    }
    return current;
}

/** Every run still in flight, whichever conversation it belongs to. */
export function inFlightRuns(): TrackedRun[] {
    return Object.values(useOrchestrationStore.getState().inFlight);
}

/**
 * Adopt whatever the previous page left behind.
 *
 * Separate from the store's creation so it runs once, at a point where failing is survivable,
 * rather than as a side effect of the first component to import the module.
 */
export function restorePersistedRuns(): TrackedRun[] {
    const records = loadRuns();
    useOrchestrationStore.getState().restoreRuns(records);
    return records;
}

/* -------------------------------------------------------------------------- */
/* Storage                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Where in-flight run records are kept.
 *
 * Versioned in the key rather than inside the payload, so a change to the record shape simply
 * leaves the old entry unread instead of requiring a migration.
 */
export const RUN_STORAGE_KEY = 'simplechat.v2.orchestrationRuns.v1';

/**
 * Discard a restored record older than this.
 *
 * Long enough that a genuinely long run -- several steps, each with its own timeout -- is still
 * recovered, short enough that a tab reopened the next day does not claim to be waiting for a run
 * that finished hours ago.
 */
export const STALE_RECORD_MS = 30 * 60 * 1000;

/** Anything that behaves like `sessionStorage`, so this can be exercised without a browser. */
export interface RunStorage {
    getItem: (key: string) => string | null;
    setItem: (key: string, value: string) => void;
    removeItem: (key: string) => void;
}

/**
 * The tab's own `sessionStorage`, or null where there is none.
 *
 * `sessionStorage` and not `localStorage`: it survives the reload this is recovering from, and it
 * does not reach a second tab, which would otherwise show a run in progress that the tab never
 * started and cannot settle. Access is guarded because a browser with storage disabled throws on
 * the property itself, not merely on the read.
 */
export function defaultRunStorage(): RunStorage | null {
    try {
        return typeof window === 'undefined' ? null : window.sessionStorage;
    } catch {
        return null;
    }
}

/** Read a record as untrusted input: storage is shared with whatever else wrote to it. */
function readRunRecord(raw: unknown): TrackedRun | null {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        return null;
    }
    const source = raw as Record<string, unknown>;
    const conversationId = String(source.conversationId ?? '');
    const turnId = String(source.turnId ?? '');
    const runId = String(source.runId ?? '');
    const startedAt = Number(source.startedAt);

    if (!conversationId || !turnId || !runId || !Number.isFinite(startedAt)) {
        return null;
    }

    return {
        conversationId,
        turnId,
        runId,
        planId: String(source.planId ?? ''),
        startedAt,
        // Anything read back from storage was, by definition, not started by this page.
        resumed: true,
    };
}

/** Load the records worth resuming, dropping malformed and stale ones. */
export function loadRuns(
    storage: RunStorage | null = defaultRunStorage(),
    now = Date.now(),
): TrackedRun[] {
    if (!storage) {
        return [];
    }

    let parsed: unknown;
    try {
        const raw = storage.getItem(RUN_STORAGE_KEY);
        if (!raw) {
            return [];
        }
        parsed = JSON.parse(raw);
    } catch {
        return [];
    }

    if (!Array.isArray(parsed)) {
        return [];
    }

    const records: TrackedRun[] = [];
    for (const entry of parsed) {
        const record = readRunRecord(entry);
        if (record && now - record.startedAt <= STALE_RECORD_MS) {
            records.push(record);
        }
    }
    return records;
}

/** Write the current records, removing the entry entirely once none are left. */
export function saveRuns(
    records: TrackedRun[],
    storage: RunStorage | null = defaultRunStorage(),
): void {
    if (!storage) {
        return;
    }
    try {
        if (records.length === 0) {
            storage.removeItem(RUN_STORAGE_KEY);
            return;
        }
        storage.setItem(RUN_STORAGE_KEY, JSON.stringify(records));
    } catch {
        // A full or disabled storage costs the reload recovery, not the run itself.
    }
}
