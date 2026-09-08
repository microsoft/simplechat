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
import { normalizeReasoningAdjustments } from '../lib/reasoning';
import { createElicitationDraft, type ElicitationDraft } from '../lib/elicitationAnswers';
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
    PersistedRunStep,
    PersistedRunSummary,
    PlanEditorState,
    PlanEdits,
    PlanStatus,
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
 * How a run is shown in the map.
 *
 * `interrupted` is the state only stored runs can be in: a run whose record never reached a
 * terminal status because the browser that started it went away. It is not `running`, because
 * this page has no stream for it and must not claim to be watching it.
 */
export type RunDisplayStatus = RunOutcome | 'interrupted';

/** Where a history entry came from, which decides what the drawer may offer for it. */
export type RunOrigin = 'local' | 'server';

/** Progress of a conversation's one-time hydration from the server. */
export type HydrationStatus = 'idle' | 'loading' | 'loaded' | 'error';

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

/**
 * A settled run kept for the conversation's history.
 *
 * Produced two ways, and the difference matters. A `local` entry is written by `endRun` when
 * this page watched the run finish. A `server` entry is hydrated from the stored record, which
 * is the only way a conversation opened on another device has any history at all -- and which
 * carries the extra identifiers (`userMessageId`, `planStatus`) that a locally-observed run
 * never needed because it still had its plan in memory.
 */
export interface RunHistoryEntry {
    runId: string;
    planId: string;
    turnId: string;
    status: RunDisplayStatus;
    finishedAt: number;
    intentSummary: string;
    origin: RunOrigin;
    /** The stored question's message id, for scrolling a reloaded thread back to the turn. */
    userMessageId?: string | null;
    /** The persisted plan status, which decides whether an approval can still be resumed. */
    planStatus?: PlanStatus | null;
    stepCount?: number;
    artifactCount?: number;
}

/** History is bounded per conversation; a long session should not grow one without limit. */
const MAX_HISTORY_PER_CONVERSATION = 25;

/** Plan statuses whose run never reached a terminal state; see `RunDisplayStatus`. */
const NON_TERMINAL_PLAN_STATUSES: ReadonlySet<string> = new Set([
    'draft',
    'awaiting_approval',
    'approved',
    'running',
]);

/**
 * Plan statuses whose approval can still be picked up on another device.
 *
 * Deliberately narrower than "not finished". An `approved` or `running` record has already been
 * handed to the run endpoint, which answers a second attempt with 409, so offering its card
 * would be offering a button that cannot work. Only a plan that was never approved is resumable.
 */
const RESUMABLE_PLAN_STATUSES: ReadonlySet<string> = new Set(['draft', 'awaiting_approval']);

/** Whether a stored run is a plan the user could still approve. */
export function isResumablePlanStatus(status: PlanStatus | null | undefined): boolean {
    return typeof status === 'string' && RESUMABLE_PLAN_STATUSES.has(status);
}

/** Epoch milliseconds for an ISO timestamp, or 0 when it is missing or unparseable. */
function epochMs(value: string | null | undefined): number {
    if (!value) {
        return 0;
    }
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * Turn a stored run into a history entry.
 *
 * The mapping the map view is built on, and the one place the server's plan vocabulary is
 * reduced to the four states a row can draw. `superseded` folds into `cancelled` because that is
 * what it means to the reader -- the run was abandoned for another -- and every non-terminal
 * status folds into `interrupted` rather than `running`, since a stored record is by definition
 * not something this page is streaming.
 */
export function historyEntryFromPersistedRun(run: PersistedRunSummary): RunHistoryEntry | null {
    const runId = run?.run_id;
    const turnId = run?.turn_id || run?.plan_summary?.turn_id || '';
    if (!runId || !turnId) {
        // A run with no turn cannot be selected, scrolled to, or keyed in the plan map. Older
        // records predating `turn_id` are skipped rather than shown as unreachable rows.
        return null;
    }

    const planStatus = (run.status ?? run.plan_summary?.status ?? null) as PlanStatus | null;
    let status: RunDisplayStatus;
    if (planStatus === 'completed') {
        status = 'completed';
    } else if (planStatus === 'failed') {
        status = 'failed';
    } else if (planStatus === 'cancelled' || planStatus === 'superseded') {
        status = 'cancelled';
    } else if (planStatus && NON_TERMINAL_PLAN_STATUSES.has(planStatus)) {
        status = 'interrupted';
    } else {
        status = 'interrupted';
    }

    return {
        runId,
        planId: run.plan_summary?.plan_id ?? '',
        turnId,
        status,
        finishedAt: epochMs(run.completed_at) || epochMs(run.started_at) || epochMs(run.created_at),
        intentSummary: run.plan_summary?.intent_summary || run.user_message || '',
        origin: 'server',
        userMessageId: run.user_message_id ?? null,
        planStatus,
        stepCount: run.plan_summary?.step_count ?? 0,
        artifactCount: run.artifact_count ?? 0,
    };
}

const EMPTY_EDITS: PlanEdits = { disabled_step_ids: [], removed_document_ids: {} };
const EMPTY_STEP_RUNTIME: StepRuntimeMap = {};
const EMPTY_HISTORY: readonly RunHistoryEntry[] = [];
const EMPTY_RUNS: readonly TrackedRun[] = [];

export interface PlanEditorTarget {
    conversationId: string;
    turnId: string;
}

/** Browser-only drafts and request state outlive the modal, not the server's revision record. */
export interface PlanEditorSession {
    state: PlanEditorState | null;
    loading: boolean;
    submitting: boolean;
    cancellationStatus: 'idle' | 'cancelling' | 'failed';
    blocked: boolean;
    error: string | null;
    instruction: string;
    pendingDraft: ElicitationDraft | null;
    submission: { id: string; fingerprint: string } | null;
    tab: 'ask' | 'history';
    previewRunId: string | null;
    previewPlan: OrchestrationPlan | null;
    previewLoading: boolean;
    historyLoading: boolean;
}

function newPlanEditorSession(): PlanEditorSession {
    return {
        state: null,
        loading: false,
        submitting: false,
        cancellationStatus: 'idle',
        blocked: false,
        error: null,
        instruction: '',
        pendingDraft: null,
        submission: null,
        tab: 'ask',
        previewRunId: null,
        previewPlan: null,
        previewLoading: false,
        historyLoading: false,
    };
}

interface OrchestrationState {
    /** The current plan per turn, keyed by `scopeKey`. */
    plans: Record<string, OrchestrationPlan>;
    /** A pending question per turn, when the planner asked instead of planning. */
    elicitations: Record<string, Elicitation>;
    elicitationDrafts: Record<string, ElicitationDraft>;
    /** The user's narrowing edits per turn, before the run. */
    edits: Record<string, PlanEdits>;
    /** Per-step live status per turn: `scopeKey` then step id. */
    stepRuntime: Record<string, StepRuntimeMap>;
    /** Runs still in flight, by run id. Persisted. */
    inFlight: Record<string, TrackedRun>;
    /** Settled runs per conversation, newest first, as observed by this page. */
    history: Record<string, RunHistoryEntry[]>;
    /**
     * Settled runs per conversation, hydrated from the server's stored records.
     *
     * Kept apart from `history` rather than merged into it because the two have different
     * authority: a locally-observed run is something this page watched happen, a hydrated one is
     * a report. Re-hydrating must never overwrite the former, and separating them makes that
     * structural instead of a rule someone has to remember.
     */
    hydratedHistory: Record<string, RunHistoryEntry[]>;
    /** Per-conversation hydration progress, so the fetch happens once and can report itself. */
    hydration: Record<string, HydrationStatus>;
    /**
     * Turns whose plan came from a stored record and must not be edited, keyed by `scopeKey`.
     *
     * A hydrated plan describes work that already ran, or that ran somewhere else. Narrowing it
     * would silently diverge the card from the run it claims to show, so the controls are hidden
     * -- and the flag lives here rather than as a component prop because the run view is reached
     * from two places and both must agree.
     */
    readOnlyTurns: Record<string, true>;
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
    /** Presence immediately pauses automatic approval, even before the hold POST completes. */
    planEditors: Record<string, PlanEditorSession>;
    editorTarget: PlanEditorTarget | null;
    setEditorTarget: (target: PlanEditorTarget | null) => void;
    updatePlanEditor: (
        conversationId: string,
        turnId: string,
        update: (session: PlanEditorSession) => PlanEditorSession,
    ) => void;
    adoptPlanEditor: (
        conversationId: string,
        turnId: string,
        editor: PlanEditorState,
        options?: { retainLocalEdits?: boolean },
    ) => boolean;

    /** Adopt a plan for a turn, replacing any pending question and re-seeding on a new revision. */
    setPlan: (conversationId: string, turnId: string, plan: unknown) => void;
    mergeReasoningAdjustments: (conversationId: string, turnId: string, adjustments: unknown) => void;
    /** Forget a turn's plan. */
    clearPlan: (conversationId: string, turnId: string) => void;

    /** Adopt a question for a turn, replacing any plan it supersedes. */
    setElicitation: (conversationId: string, turnId: string, elicitation: Elicitation) => void;
    /** Forget a turn's question, typically once it has been answered. */
    clearElicitation: (conversationId: string, turnId: string) => void;
    updateElicitationDraft: (
        conversationId: string,
        turnId: string,
        elicitationId: string,
        revision: number,
        update: (draft: ElicitationDraft) => ElicitationDraft,
    ) => void;
    beginElicitationSubmission: (
        conversationId: string,
        turnId: string,
        elicitationId: string,
        submissionId: string,
        fingerprint: string,
    ) => boolean;
    failElicitationSubmission: (
        conversationId: string,
        turnId: string,
        elicitationId: string,
        revision: number,
        message: string,
    ) => void;

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
    /** A rejected approval never executed and must not become a completed/failed run. */
    releaseRunAttempt: (runId: string) => void;
    /** Adopt run records restored from storage after a reload. */
    restoreRuns: (records: TrackedRun[]) => void;

    /** Record where a conversation's one-time hydration has got to. */
    setHydrationStatus: (conversationId: string, status: HydrationStatus) => void;
    /** Adopt a conversation's stored runs as history, without displacing observed ones. */
    hydrateConversationRuns: (conversationId: string, runs: PersistedRunSummary[]) => void;
    /**
     * Adopt a stored plan for a turn, with its steps' real outcomes.
     *
     * Not `setPlan`: that seeds every step from the plan's own status, which for a stored plan is
     * whatever it was when the plan was written, so a finished run would redraw as pending. The
     * step records are the truth about what happened and are used instead.
     */
    adoptPersistedPlan: (
        conversationId: string,
        turnId: string,
        plan: unknown,
        steps: PersistedRunStep[],
        options?: { readOnly?: boolean },
    ) => void;

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
    elicitationDrafts: {},
    edits: {},
    stepRuntime: {},
    inFlight: {},
    history: {},
    hydratedHistory: {},
    hydration: {},
    readOnlyTurns: {},
    pinnedRunId: null,
    visibleConversationId: null,
    activeTurns: {},
    planEditors: {},
    editorTarget: null,

    setEditorTarget: (editorTarget) => set({ editorTarget }),

    updatePlanEditor: (conversationId, turnId, update) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => ({
            planEditors: {
                ...state.planEditors,
                [key]: update(state.planEditors[key] ?? newPlanEditorSession()),
            },
        }));
    },

    adoptPlanEditor: (conversationId, turnId, editor, options) => {
        const plan = normalizePlan(editor?.plan);
        if (!plan?.plan_id || !plan.run_id || typeof editor.version !== 'string' || !editor.version
            || plan.conversation_id !== conversationId || plan.turn_id !== turnId) {
            return false;
        }
        const key = scopeKey(conversationId, turnId);
        const current = get().plans[key];
        if ((current && current.revision > plan.revision)
            || Object.values(get().inFlight).some((run) =>
                run.conversationId === conversationId && run.turnId === turnId)
            || (get().history[conversationId] ?? []).some((run) => run.turnId === turnId)) {
            return false;
        }
        const canonical = { ...plan, edit_version: editor.version };
        set((state) => {
            const previous = state.planEditors[key] ?? newPlanEditorSession();
            const pending = editor.pending;
            const sameQuestion = pending && previous.pendingDraft?.elicitationId === pending.elicitation_id
                && previous.pendingDraft.revision === (pending.revision ?? 0);
            const runtime: StepRuntimeMap = {};
            for (const step of canonical.steps) {
                runtime[step.step_id] = { status: step.status, summary: '' };
            }
            const readOnlyTurns = { ...state.readOnlyTurns };
            if (isResumablePlanStatus(canonical.status)) {
                delete readOnlyTurns[key];
            } else {
                readOnlyTurns[key] = true;
            }
            return {
                plans: { ...state.plans, [key]: canonical },
                // Unlike setPlan, this adopts the authoritative overlay in the same update.
                // Unsaved Review changes may survive reopening only against the identical
                // server version. A stale tab must adopt the server's overlay instead.
                edits: {
                    ...state.edits,
                    [key]: options?.retainLocalEdits && current?.run_id === canonical.run_id
                        && current.edit_version === editor.version
                        && previous.state?.version === editor.version
                        ? state.edits[key] ?? editor.edits : editor.edits,
                },
                stepRuntime: { ...state.stepRuntime, [key]: runtime },
                readOnlyTurns,
                planEditors: {
                    ...state.planEditors,
                    [key]: {
                        ...previous,
                        state: { ...editor, plan: canonical },
                        blocked: false,
                        cancellationStatus: previous.cancellationStatus === 'cancelling'
                            ? 'cancelling' : 'idle',
                        pendingDraft: pending
                            ? sameQuestion ? previous.pendingDraft : createElicitationDraft(pending)
                            : null,
                        previewRunId: null,
                        previewPlan: null,
                        previewLoading: false,
                    },
                },
            };
        });
        return true;
    },

    mergeReasoningAdjustments: (conversationId, turnId, adjustments) => {
        if (!Array.isArray(adjustments) || !adjustments.length) return;
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const plan = state.plans[key];
            if (!plan) return {};
            const merged = normalizeReasoningAdjustments([
                ...(plan.reasoning_adjustments ?? []), ...adjustments,
            ]);
            if (JSON.stringify(merged) === JSON.stringify(plan.reasoning_adjustments ?? [])) return {};
            return { plans: { ...state.plans, [key]: { ...plan, reasoning_adjustments: merged } } };
        });
    },

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
            const elicitationDrafts = { ...state.elicitationDrafts };
            delete elicitations[key];
            delete elicitationDrafts[key];

            if (sameIdentity) {
                return { plans: { ...state.plans, [key]: plan }, elicitations, elicitationDrafts };
            }
            const readOnlyTurns = { ...state.readOnlyTurns };
            delete readOnlyTurns[key];

            const runtime: StepRuntimeMap = {};
            for (const step of plan.steps) {
                runtime[step.step_id] = { status: step.status, summary: '' };
            }

            return {
                plans: { ...state.plans, [key]: plan },
                elicitations,
                elicitationDrafts,
                readOnlyTurns,
                edits: { ...state.edits, [key]: emptyPlanEdits() },
                stepRuntime: { ...state.stepRuntime, [key]: runtime },
            };
        });
    },

    clearPlan: (conversationId, turnId) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const plans = { ...state.plans };
            const planEditors = { ...state.planEditors };
            delete plans[key];
            delete planEditors[key];
            return {
                plans,
                planEditors,
                editorTarget: state.editorTarget?.conversationId === conversationId
                    && state.editorTarget.turnId === turnId ? null : state.editorTarget,
            };
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
            const previous = state.elicitations[key];
            const sameQuestion = previous?.elicitation_id === elicitation.elicitation_id
                && previous.revision === elicitation.revision;
            const draft = sameQuestion ? state.elicitationDrafts[key] : undefined;
            return {
                plans,
                elicitations: { ...state.elicitations, [key]: elicitation },
                elicitationDrafts: {
                    ...state.elicitationDrafts,
                    [key]: draft
                        ? { ...draft, submitting: false, error: null }
                        : createElicitationDraft(elicitation),
                },
            };
        });
    },

    clearElicitation: (conversationId, turnId) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            if (!(key in state.elicitations) && !(key in state.elicitationDrafts)) {
                return {};
            }
            const elicitations = { ...state.elicitations };
            const elicitationDrafts = { ...state.elicitationDrafts };
            delete elicitations[key];
            delete elicitationDrafts[key];
            return { elicitations, elicitationDrafts };
        });
    },

    updateElicitationDraft: (conversationId, turnId, elicitationId, revision, update) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const draft = state.elicitationDrafts[key];
            if (!draft || draft.elicitationId !== elicitationId || draft.revision !== revision) {
                return {};
            }
            const next = update(draft);
            return next === draft ? {} : {
                elicitationDrafts: { ...state.elicitationDrafts, [key]: next },
            };
        });
    },

    beginElicitationSubmission: (conversationId, turnId, elicitationId, submissionId, fingerprint) => {
        const key = scopeKey(conversationId, turnId);
        const draft = get().elicitationDrafts[key];
        if (!draft || draft.elicitationId !== elicitationId || draft.submitting) {
            return false;
        }
        set((state) => ({
            elicitationDrafts: {
                ...state.elicitationDrafts,
                [key]: {
                    ...draft,
                    submitting: true,
                    error: null,
                    submissionId,
                    submissionFingerprint: fingerprint,
                },
            },
        }));
        return true;
    },

    failElicitationSubmission: (conversationId, turnId, elicitationId, revision, message) => {
        const key = scopeKey(conversationId, turnId);
        set((state) => {
            const draft = state.elicitationDrafts[key];
            if (!draft || draft.elicitationId !== elicitationId || draft.revision !== revision) {
                return {};
            }
            return {
                elicitationDrafts: {
                    ...state.elicitationDrafts,
                    [key]: { ...draft, submitting: false, error: message },
                },
            };
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

    releaseRunAttempt: (runId) => {
        const inFlight = { ...get().inFlight };
        delete inFlight[runId];
        set({ inFlight });
        saveRuns(Object.values(inFlight));
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
                origin: 'local',
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

    setHydrationStatus: (conversationId, status) => {
        if (!conversationId || get().hydration[conversationId] === status) {
            return;
        }
        set((state) => ({ hydration: { ...state.hydration, [conversationId]: status } }));
    },

    hydrateConversationRuns: (conversationId, runs) => {
        if (!conversationId) {
            return;
        }
        set((state) => {
            const entries: RunHistoryEntry[] = [];
            const seen = new Set<string>();
            const persistedStatus = new Map<string, PlanStatus | null>();
            for (const run of runs ?? []) {
                const entry = historyEntryFromPersistedRun(run);
                if (!entry || seen.has(entry.runId)) {
                    continue;
                }
                seen.add(entry.runId);
                persistedStatus.set(entry.runId, entry.planStatus ?? null);
                entries.push(entry);
            }
            entries.sort((a, b) => b.finishedAt - a.finishedAt);

            // Settle anything this page adopted from storage but never watched.
            //
            // A record read back from `sessionStorage` has no stream behind it, so without this it
            // would draw a spinner for as long as the tab stayed open -- including for a run that
            // finished, failed, or was never approved in the first place. The stored record is the
            // authority on that, and this is the first moment it is known.
            let inFlight = state.inFlight;
            let changed = false;
            for (const run of Object.values(state.inFlight)) {
                if (run.conversationId !== conversationId || !run.resumed) {
                    continue;
                }
                if (!persistedStatus.has(run.runId)) {
                    continue;
                }
                const status = persistedStatus.get(run.runId);
                if (status && NON_TERMINAL_PLAN_STATUSES.has(status)) {
                    continue;
                }
                if (!changed) {
                    inFlight = { ...state.inFlight };
                    changed = true;
                }
                delete inFlight[run.runId];
            }
            if (changed) {
                saveRuns(Object.values(inFlight));
            }

            return {
                inFlight,
                hydratedHistory: {
                    ...state.hydratedHistory,
                    [conversationId]: entries.slice(0, MAX_HISTORY_PER_CONVERSATION),
                },
                hydration: { ...state.hydration, [conversationId]: 'loaded' },
            };
        });
    },

    adoptPersistedPlan: (conversationId, turnId, rawPlan, steps, options) => {
        if (!conversationId || !turnId) {
            return;
        }
        const plan = normalizePlan(rawPlan);
        if (!plan) {
            return;
        }

        const key = scopeKey(conversationId, turnId);
        const readOnly = options?.readOnly ?? true;

        set((state) => {
            // Seeded from the plan first so a step with no record still draws, then overwritten
            // by whatever the executor actually persisted for it.
            const runtime: StepRuntimeMap = {};
            for (const step of plan.steps) {
                runtime[step.step_id] = { status: step.status, summary: '' };
            }
            for (const record of steps ?? []) {
                const stepId = record?.step_id;
                if (!stepId) {
                    continue;
                }
                const status = coerceStepStatus(record.status) ?? runtime[stepId]?.status ?? 'pending';
                runtime[stepId] = {
                    status,
                    summary: typeof record.summary === 'string' ? record.summary : '',
                };
            }

            const elicitations = { ...state.elicitations };
            const elicitationDrafts = { ...state.elicitationDrafts };
            delete elicitations[key];
            delete elicitationDrafts[key];

            const readOnlyTurns = { ...state.readOnlyTurns };
            if (readOnly) {
                readOnlyTurns[key] = true;
            } else {
                delete readOnlyTurns[key];
            }

            return {
                plans: { ...state.plans, [key]: plan },
                elicitations,
                elicitationDrafts,
                // A stored plan arrives unnarrowed; the edits are this device's to make.
                edits: { ...state.edits, [key]: state.edits[key] ?? emptyPlanEdits() },
                stepRuntime: { ...state.stepRuntime, [key]: runtime },
                readOnlyTurns,
            };
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
        set((state) => ({
            visibleConversationId: conversationId,
            editorTarget: state.editorTarget?.conversationId === conversationId
                ? state.editorTarget : null,
        }));
    },

    setActiveTurn: (conversationId, turnId) => {
        if (!conversationId || !turnId) {
            return;
        }
        if (get().activeTurns[conversationId] === turnId) {
            return;
        }
        set((state) => {
            const previous = state.activeTurns[conversationId];
            const elicitations = { ...state.elicitations };
            const elicitationDrafts = { ...state.elicitationDrafts };
            if (previous && previous !== turnId) {
                const oldKey = scopeKey(conversationId, previous);
                delete elicitations[oldKey];
                delete elicitationDrafts[oldKey];
            }
            return {
                activeTurns: { ...state.activeTurns, [conversationId]: turnId },
                elicitations,
                elicitationDrafts,
                editorTarget: state.editorTarget?.conversationId === conversationId
                    && state.editorTarget.turnId !== turnId ? null : state.editorTarget,
            };
        });
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
        for (const key of Object.keys(get().elicitations)) {
            busy.add(conversationOfScope(key));
        }
        for (const [key, editor] of Object.entries(get().planEditors)) {
            if (editor.submitting || isResumablePlanStatus(get().plans[key]?.status)) {
                busy.add(conversationOfScope(key));
            }
        }

        set((state) => {
            let removed = false;
            const plans: Record<string, OrchestrationPlan> = {};
            const elicitations: Record<string, Elicitation> = {};
            const elicitationDrafts: Record<string, ElicitationDraft> = {};
            const edits: Record<string, PlanEdits> = {};
            const stepRuntime: Record<string, StepRuntimeMap> = {};
            const readOnlyTurns: Record<string, true> = {};
            const planEditors: Record<string, PlanEditorSession> = {};

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
            keep(state.elicitationDrafts, elicitationDrafts as Record<string, unknown>);
            keep(state.edits, edits as Record<string, unknown>);
            keep(state.stepRuntime, stepRuntime as Record<string, unknown>);
            keep(state.readOnlyTurns, readOnlyTurns as Record<string, unknown>);
            keep(state.planEditors, planEditors as Record<string, unknown>);

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

            // Hydration is dropped alongside the plans it fed, so returning to a swept
            // conversation re-fetches rather than showing rows whose plans have gone.
            const hydratedHistory: Record<string, RunHistoryEntry[]> = {};
            const hydration: Record<string, HydrationStatus> = {};
            for (const [conversationId, entries] of Object.entries(state.hydratedHistory)) {
                if (busy.has(conversationId)) {
                    hydratedHistory[conversationId] = entries;
                } else {
                    removed = true;
                }
            }
            for (const [conversationId, status] of Object.entries(state.hydration)) {
                if (busy.has(conversationId)) {
                    hydration[conversationId] = status;
                } else {
                    removed = true;
                }
            }

            return removed
                ? {
                      plans,
                      elicitations,
                      elicitationDrafts,
                      edits,
                      stepRuntime,
                      readOnlyTurns,
                      planEditors,
                      activeTurns,
                      hydratedHistory,
                      hydration,
                  }
                : {};
        });
    },
}));

/* -------------------------------------------------------------------------- */
/* Reading                                                                     */
/* -------------------------------------------------------------------------- */

export function selectPlanEditor(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): PlanEditorSession | null {
    return state.planEditors[scopeKey(conversationId, turnId)] ?? null;
}

export function selectHasPlanHold(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): boolean {
    return Boolean(selectPlanEditor(state, conversationId, turnId)
        || selectPlan(state, conversationId, turnId)?.edit_version);
}

export function selectCanEditPlan(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): boolean {
    const plan = selectPlan(state, conversationId, turnId);
    return Boolean(plan && isResumablePlanStatus(plan.status)
        && plan.approval.state === 'pending'
        && !state.readOnlyTurns[scopeKey(conversationId, turnId)]
        && !Object.values(state.inFlight).some((run) =>
            run.conversationId === conversationId && run.turnId === turnId)
        && !(state.history[conversationId] ?? []).some((run) => run.turnId === turnId));
}

export function selectPlanRunBlocked(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): boolean {
    const editor = selectPlanEditor(state, conversationId, turnId);
    const plan = selectPlan(state, conversationId, turnId);
    return Boolean(state.readOnlyTurns[scopeKey(conversationId, turnId)]
        || (plan?.edit_version && !editor?.state)
        || (editor && (!editor.state || editor.loading || editor.submitting || editor.blocked
            || editor.cancellationStatus !== 'idle'
            || editor.state.busy || editor.state.pending
            || editor.state.version !== plan?.edit_version
            || (editor.previewRunId && state.editorTarget?.conversationId === conversationId
                && state.editorTarget.turnId === turnId))));
}

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

export function selectElicitationDraft(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): ElicitationDraft | null {
    return state.elicitationDrafts[scopeKey(conversationId, turnId)] ?? null;
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

/**
 * Memo for the history merge, keyed by conversation and by the identity of both inputs.
 *
 * `selectHistory` is used directly as a zustand selector, which compares results with `Object.is`.
 * A merge that allocated a fresh array on every call would therefore report a change on every
 * store update, re-rendering the map view continuously and tripping React's "getSnapshot should
 * be cached" guard. Caching on the two input array references makes the result stable for as long
 * as neither side has actually changed, which is exactly the condition under which it may be.
 */
const historyMergeCache = new Map<
    string,
    {
        local: readonly RunHistoryEntry[] | undefined;
        hydrated: readonly RunHistoryEntry[] | undefined;
        merged: readonly RunHistoryEntry[];
    }
>();

/**
 * A conversation's run history, newest first, from both sources.
 *
 * Locally-observed runs win over their stored copies: this page watched them settle, and the
 * stored record may not have caught up -- a run that completed seconds ago can still read
 * `running` in Cosmos if the final write lost the race with the fetch. Stable empty array when
 * there is neither.
 */
export function selectHistory(
    state: OrchestrationState,
    conversationId: string,
): readonly RunHistoryEntry[] {
    if (!conversationId) {
        return EMPTY_HISTORY;
    }
    const local = state.history[conversationId];
    const hydrated = state.hydratedHistory[conversationId];

    if (!hydrated || hydrated.length === 0) {
        return local ?? EMPTY_HISTORY;
    }
    if (!local || local.length === 0) {
        return hydrated;
    }

    const cached = historyMergeCache.get(conversationId);
    if (cached && cached.local === local && cached.hydrated === hydrated) {
        return cached.merged;
    }

    const seen = new Set(local.map((entry) => entry.runId));
    const merged = [...local];
    for (const entry of hydrated) {
        if (!seen.has(entry.runId)) {
            merged.push(entry);
        }
    }
    merged.sort((a, b) => b.finishedAt - a.finishedAt);
    const result = merged.slice(0, MAX_HISTORY_PER_CONVERSATION);

    historyMergeCache.set(conversationId, { local, hydrated, merged: result });
    return result;
}

/** How far a conversation's hydration has got. */
export function selectHydrationStatus(
    state: OrchestrationState,
    conversationId: string,
): HydrationStatus {
    return (conversationId && state.hydration[conversationId]) || 'idle';
}

/** Whether a turn's plan came from a stored record and so cannot be narrowed. */
export function selectIsReadOnly(
    state: OrchestrationState,
    conversationId: string,
    turnId: string,
): boolean {
    if (!conversationId || !turnId) {
        return false;
    }
    return state.readOnlyTurns[scopeKey(conversationId, turnId)] === true;
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
