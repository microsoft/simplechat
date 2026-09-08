// orchestrationController.ts
// The seam between the orchestration transport and the two stores that display it.
//
// The plan and run clients (`orchestration.ts`) are pure transport, and the two stores hold
// display state; neither drives the other. This module is the thing that does — it owns the
// AbortControllers, mints the turn id, and folds each stream's events into `chatStore` (the
// thread and streaming surface) and `orchestrationStore` (the plan, question and per-step state).
//
// It is plain functions rather than a hook on purpose. A plan or a run OUTLIVES the component
// that started it: the composer that submits a plan, the card that approves a run and the drawer
// that watches it are three different components, any of which can unmount while the work
// continues. Holding the in-flight controllers in React state would tie them to whichever of
// those happened to still be mounted. Held at module scope, keyed by conversation, they survive a
// component coming and going exactly as `chatStore`'s own stream controller does — and for the
// same reason.

import { createConversation } from './endpoints';
import { ApiError } from './apiClient';
import {
    beginPlanEdit,
    cancelOrchestrationRun,
    fetchOrchestrationRun,
    fetchRunSteps,
    isOrchestrationRunPending,
    normalizeOrchestrationAttempt,
    normalizeOrchestrationRecovery,
    orchestrationTerminalStatus,
    prepareOrchestrationRetry,
    fetchPlanEditor,
    MAX_PLAN_INSTRUCTION_LENGTH,
    orchestrationErrorInfo,
    planOrchestration,
    reviseOrchestrationPlan,
    runOrchestration,
    type ApprovalMode,
    type ElicitationContext,
    type Elicitation,
    type ElicitationResponse,
    type OrchestrationPlan,
    type OrchestrationPlanRequest,
    type OrchestrationSeeds,
    type OrchestrationRunRequest,
    type OrchestrationRequestError,
    type PlanRevisionAction,
    type PlanRevisionRequest,
    type RunStreamEvent,
    type PersistedRun,
    type PlanEdits,
} from './orchestration';
import { applyPlanEdits, isPlanApproved, isPlanAwaitingApproval, isPlanRunnable, normalizePlan } from './orchestrationPlan';
import type { Json } from './types';
import { normalizeReasoningAdjustments, type ReasoningResolution } from './reasoning';
import { useChatStore } from '../stores/chatStore';
import {
    selectEdits,
    selectCanEditPlan,
    selectElicitation,
    selectElicitationDraft,
    selectPlan,
    selectHasPlanHold,
    selectPlanEditor,
    selectPlanRunBlocked,
    useOrchestrationStore,
    type PlanEditorTarget,
} from '../stores/orchestrationStore';

/** Mirrors `orchestrationStore`'s own `scopeKey`; the separator has to match to share a key space. */
function scopeKey(conversationId: string, turnId: string): string {
    return `${conversationId}\u0000${turnId}`;
}

/**
 * The turn id the whole turn is keyed on.
 *
 * Minted here, by the client, and sent on the plan request: a turn is one question, and this
 * client's store keys every plan, edit and run of it on this one value. It is STABLE across a
 * turn's re-plans (an answered question, a step asking to re-plan) — that is the point of holding
 * it apart from `plan_id`/`run_id`, which the server mints fresh each revision. The server honours
 * the id it is sent and echoes it back on the plan, and `dispatchPlan` reconciles the rare case
 * where the two ever disagree. `crypto.randomUUID` is present in every browser this app targets;
 * the fallback only guards a non-secure context or a test.
 */
function makeTurnId(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    return `turn-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * What a turn needs remembered between its plan and its re-plans.
 *
 * The plan request carries the original message, the seeds that constrained it and the approval
 * mode; none of that is in the plan the server returns, so a re-plan after an answered question
 * would lose it unless it is held here. `revision` is bumped each re-plan, and
 * `pendingUserMessageId` is the optimistic user bubble the run reconciles with the server's id.
 */
interface TurnContext {
    message: string;
    approvalMode: ApprovalMode;
    seeds: OrchestrationSeeds;
    revision: number;
    pendingUserMessageId: string;
}

const turnContexts = new Map<string, TurnContext>();

/**
 * The in-flight plan or run per conversation.
 *
 * One at a time per conversation: a turn plans, is approved, then runs, so a conversation never
 * has a plan stream and a run stream open together. Keyed by conversation so cancelling — or a
 * re-plan superseding a plan — reaches the right one while another conversation's run is untouched.
 */
const activeControllers = new Map<string, AbortController>();
const activeRunIds = new Map<string, string>();
/** Editor requests never abort, begin, settle, or append a main-thread turn. */
const editorControllers = new Map<string, AbortController>();

export type ElicitationSubmitResult = { ok: true } | { ok: false; error: string };

interface ElicitationContinuation {
    elicitation: Elicitation;
    response: ElicitationResponse;
    context?: ElicitationContext;
    elicitationId: string;
    revision: number;
    submissionId: string;
}

export interface StartPlanParams {
    /** The open conversation, or null to create one for this first message. */
    conversationId: string | null;
    message: string;
    approvalMode: ApprovalMode;
    /**
     * Manual-control selections that constrain the plan rather than being ignored:
     * `selected_document_ids`, `agent_info`, the `model_*` quartet, `prompt_info`,
     * `required_capabilities` and legacy `web_search_enabled`. Unchecked controls are neutral.
     */
    seeds?: OrchestrationSeeds;
}

/**
 * Create the conversation a first message needs, or pass an existing one through.
 *
 * Mirrors the minimal half of `sendMessage`'s creation: claim `activeConversationId` only if
 * nothing has been opened in the round trip, so a reader who opens another thread meanwhile keeps
 * their place while this turn still attaches to the conversation it created.
 */
async function ensureConversation(
    conversationId: string | null,
    message: string,
): Promise<string | null> {
    if (conversationId) {
        return conversationId;
    }
    try {
        const created = await createConversation(message);
        const chat = useChatStore.getState();
        if (chat.activeConversationId === null) {
            useChatStore.setState({
                activeConversationId: created.conversation_id,
                activeConversationKind: 'personal',
            });
        }
        // Refresh the rail so the new conversation appears with its server-side title.
        void chat.loadConversations({ reset: true });
        return created.conversation_id;
    } catch {
        return null;
    }
}

/**
 * Open the drawer's plan mode, but only for a manual-mode plan awaiting approval on screen.
 *
 * Asymmetric by design. Auto and timed plans leave the drawer shut: the inline card already
 * carries the countdown and the controls to intervene, and throwing a panel open on every message
 * is intrusive. Manual is the one mode where approval is a deliberate gate, so the panel earns its
 * interruption. Guarded on the visible conversation so a plan arriving for a thread the reader has
 * left does not yank a panel open over the one they are reading.
 */
function maybeAutoOpenDrawer(conversationId: string, plan: OrchestrationPlan): void {
    if (plan.approval.mode !== 'manual' || !isPlanAwaitingApproval(plan)) {
        return;
    }
    if (useOrchestrationStore.getState().visibleConversationId !== conversationId) {
        return;
    }
    const chat = useChatStore.getState();
    if (chat.drawerMode !== 'plan') {
        chat.setDrawerMode('plan');
    }
}

/**
 * Drive one plan stream for a turn, fresh or a re-plan, into both stores.
 *
 * `addUserMessage` is false for a re-plan: the user's question is already in the thread from the
 * first plan, and a second bubble for the same turn would be a phantom. A produced plan or
 * question leaves the thinking state via a `planned` settle; a bare abort drops it and forgets the
 * card; an error settle has already run from `onError`.
 */
async function dispatchPlan(
    conversationId: string,
    turnId: string,
    context: TurnContext,
    addUserMessage: boolean,
    continuation?: ElicitationContinuation,
): Promise<ElicitationSubmitResult> {
    // The ids the turn is keyed on. Mutable because the server can, in principle, reconcile
    // either one mid-stream: it names a brand-new conversation on `conversation_metadata`, and it
    // echoes the turn id back on the plan. The client sends both and the server honours both, so
    // these only ever move on a genuine disagreement — the helpers below make that move safe.
    let currentConversationId = conversationId;
    let currentTurnId = turnId;

    const key = scopeKey(currentConversationId, currentTurnId);
    turnContexts.set(key, context);

    const orchestration = useOrchestrationStore.getState();
    orchestration.setActiveTurn(currentConversationId, currentTurnId);

    const pendingUserMessageId = useChatStore
        .getState()
        .beginOrchestrationTurn(
            currentConversationId,
            context.message,
            addUserMessage,
            currentTurnId,
            context.seeds.prompt_info as Json | undefined,
        );
    if (addUserMessage) {
        context.pendingUserMessageId = pendingUserMessageId;
        turnContexts.set(key, context);
    }

    const controller = new AbortController();
    // A re-plan supersedes whatever was open for this conversation.
    activeControllers.get(currentConversationId)?.abort();
    activeControllers.set(currentConversationId, controller);
    activeRunIds.delete(currentConversationId);

    /**
     * Adopt the conversation id the server just announced, if it is not the one we already hold.
     *
     * The rail title belongs to the conversation whichever id won, so it is applied first, exactly
     * as the ordinary chat stream's handler does. The id itself only moves when it genuinely
     * differs — the normal path pre-created the conversation and sent that id, so the server has
     * nothing new to say and this returns early. When it does move, the turn was keyed under the
     * old id (its controller, its context, its store entry and its on-screen bubble), so each of
     * those follows the id across rather than being stranded under a conversation that never was.
     */
    const adoptServerConversationId = (serverConversationId: string, title: unknown): void => {
        const targetId = serverConversationId || currentConversationId;
        if (typeof title === 'string' && title) {
            useChatStore.setState((state) => ({
                conversations: state.conversations.map((item) =>
                    item.id === targetId ? { ...item, title } : item,
                ),
            }));
        }
        if (!serverConversationId || serverConversationId === currentConversationId) {
            return;
        }
        console.warn(
            `[orchestration] server named conversation ${serverConversationId}; client held ` +
                `${currentConversationId}. Adopting the server id.`,
        );
        const previousConversationId = currentConversationId;
        const inFlight = activeControllers.get(previousConversationId);
        if (inFlight) {
            activeControllers.delete(previousConversationId);
            activeControllers.set(serverConversationId, inFlight);
        }
        const previousKey = scopeKey(previousConversationId, currentTurnId);
        const heldContext = turnContexts.get(previousKey);
        if (heldContext) {
            turnContexts.delete(previousKey);
            turnContexts.set(scopeKey(serverConversationId, currentTurnId), heldContext);
        }
        orchestration.clearActiveTurn(previousConversationId);
        orchestration.setActiveTurn(serverConversationId, currentTurnId);
        useChatStore.getState().reassignOrchestrationTurn({
            fromConversationId: previousConversationId,
            toConversationId: serverConversationId,
            fromTurnId: currentTurnId,
            toTurnId: currentTurnId,
        });
        currentConversationId = serverConversationId;
    };

    /**
     * Adopt the turn id echoed on the plan, if it is not the one we sent.
     *
     * `activeTurns` is keyed by conversation, so re-pointing it overwrites the old value with no
     * orphan; the controller's context map and the question bubble carry the old turn id and are
     * moved to match. The plan and its edits are written by the caller AFTER this runs, so they
     * land under the reconciled id directly and need no move.
     */
    const adoptServerTurnId = (serverTurnId: string | undefined): void => {
        if (!serverTurnId || serverTurnId === currentTurnId) {
            return;
        }
        console.warn(
            `[orchestration] server keyed turn ${serverTurnId}; client sent ${currentTurnId}. ` +
                `Adopting the server id.`,
        );
        const previousTurnId = currentTurnId;
        const previousKey = scopeKey(currentConversationId, previousTurnId);
        const heldContext = turnContexts.get(previousKey);
        if (heldContext) {
            turnContexts.delete(previousKey);
            turnContexts.set(scopeKey(currentConversationId, serverTurnId), heldContext);
        }
        orchestration.setActiveTurn(currentConversationId, serverTurnId);
        useChatStore.getState().reassignOrchestrationTurn({
            fromConversationId: currentConversationId,
            toConversationId: currentConversationId,
            fromTurnId: previousTurnId,
            toTurnId: serverTurnId,
        });
        currentTurnId = serverTurnId;
    };

    const body: OrchestrationPlanRequest = {
        message: context.message,
        conversation_id: currentConversationId,
        turn_id: currentTurnId,
        revision: context.revision,
        approval_mode: context.approvalMode,
        ...context.seeds,
    };
    if (continuation) {
        body.elicitation = continuation.elicitation;
        body.elicitation_response = continuation.response;
        body.elicitation_id = continuation.elicitationId;
        body.elicitation_revision = continuation.revision;
        body.elicitation_submission_id = continuation.submissionId;
        if (continuation.response.action === 'accept' && continuation.context) {
            body.elicitation_context = continuation.context;
        }
    }

    let produced = false;
    let errored = false;
    let failure = '';
    let reasoningAdjustments: ReasoningResolution[] = [];
    const isCurrentRequest = () =>
        !controller.signal.aborted && activeControllers.get(currentConversationId) === controller;
    await planOrchestration(
        body,
        {
            onThought: (event) => {
                if (isCurrentRequest()) {
                    reasoningAdjustments = normalizeReasoningAdjustments(
                        event.reasoning_adjustments, reasoningAdjustments,
                    );
                    useOrchestrationStore.getState().mergeReasoningAdjustments(
                        currentConversationId, currentTurnId, event.reasoning_adjustments,
                    );
                    useChatStore.getState()
                        .pushOrchestrationThought(currentConversationId, event as RunStreamEvent);
                }
            },
            onConversationMetadata: (event) => {
                if (!isCurrentRequest()) {
                    return;
                }
                adoptServerConversationId(
                    typeof event.conversation_id === 'string' ? event.conversation_id : '',
                    event.conversation_title ?? event.title,
                );
            },
            onPlan: (plan) => {
                if (!isCurrentRequest()) {
                    return;
                }
                adoptServerTurnId(plan.turn_id);
                context.revision = plan.revision ?? context.revision;
                useOrchestrationStore.getState().setPlan(currentConversationId, currentTurnId, {
                    ...plan,
                    reasoning_adjustments: normalizeReasoningAdjustments([
                        ...reasoningAdjustments, ...(plan.reasoning_adjustments ?? []),
                    ]),
                });
                if (!selectPlan(useOrchestrationStore.getState(), currentConversationId, currentTurnId)) {
                    errored = true;
                    failure = 'The planner returned an invalid plan. Please try again.';
                    useChatStore.getState().settleOrchestrationTurn(currentConversationId, {
                        status: 'failed',
                        error: failure,
                    });
                    return;
                }
                produced = true;
                maybeAutoOpenDrawer(currentConversationId, plan);
            },
            onElicitation: (elicitation) => {
                if (!isCurrentRequest()) {
                    return;
                }
                adoptServerTurnId(elicitation.turn_id);
                context.revision = elicitation.revision ?? context.revision;
                useOrchestrationStore
                    .getState()
                    .setElicitation(currentConversationId, currentTurnId, elicitation);
                produced = true;
            },
            onError: (message) => {
                if (!isCurrentRequest()) {
                    return;
                }
                errored = true;
                failure = message;
                useChatStore
                    .getState()
                    .settleOrchestrationTurn(currentConversationId, {
                        status: 'failed',
                        error: message,
                    });
            },
        },
        controller.signal,
    );

    if (activeControllers.get(currentConversationId) !== controller) {
        return { ok: false, error: 'This request was superseded by another request.' };
    }
    activeControllers.delete(currentConversationId);

    if (produced && !errored) {
        // Auto mode is pre-approved on arrival, so its run starts here rather than waiting for a
        // click or a countdown — and it starts INSTEAD OF settling `planned`, so the thinking
        // state flows straight into the run's streaming without a flicker to idle between them.
        // Manual and timed settle `planned` and wait for the card.
        const settledPlan = selectPlan(
            useOrchestrationStore.getState(),
            currentConversationId,
            currentTurnId,
        );
        const autoRun =
            settledPlan !== null &&
            settledPlan.approval.mode === 'auto' &&
            !selectHasPlanHold(useOrchestrationStore.getState(), currentConversationId, currentTurnId) &&
            isPlanApproved(settledPlan) &&
            isPlanRunnable(settledPlan);
        if (autoRun) {
            void approveAndRunPlan({
                conversationId: currentConversationId, turnId: currentTurnId, automatic: true,
            });
        } else {
            useChatStore
                .getState()
                .settleOrchestrationTurn(currentConversationId, { status: 'planned' });
        }
        return { ok: true };
    } else if (!errored && controller.signal.aborted) {
        // Cancelled before the planner committed: drop the thinking state and forget the card,
        // rather than leaving an empty plan slot the drawer would puzzle over.
        useChatStore
            .getState()
            .settleOrchestrationTurn(currentConversationId, { status: 'cancelled', accumulated: '' });
        if (!continuation) {
            useOrchestrationStore.getState().clearActiveTurn(currentConversationId);
        }
        return { ok: false, error: 'The request was interrupted. You can try again.' };
    }
    failure ||= 'The planner did not return a plan or a question. Please try again.';
    if (!errored) {
        useChatStore.getState().settleOrchestrationTurn(currentConversationId, {
            status: 'failed',
            error: failure,
        });
    }
    return { ok: false, error: failure };
}

/**
 * Plan a fresh turn from the composer.
 *
 * Creates the conversation if there is none, mints the turn id, and dispatches the first plan.
 */
export async function startOrchestrationPlan(params: StartPlanParams): Promise<void> {
    const message = params.message.trim();
    if (!message) {
        return;
    }
    const conversationId = await ensureConversation(params.conversationId, message);
    if (!conversationId) {
        return;
    }
    const turnId = makeTurnId();
    await dispatchPlan(
        conversationId,
        turnId,
        {
            message,
            approvalMode: params.approvalMode,
            seeds: params.seeds ?? {},
            revision: 0,
            pendingUserMessageId: '',
        },
        true,
    );
}

/**
 * Answer a planner's question and re-plan the same turn.
 *
 * Accept and decline continue the same turn with its original message, seeds and stored-question
 * identity. The draft stays until that continuation succeeds. Cancel abandons the local turn
 * without another planning request.
 */
export async function answerElicitation(params: {
    conversationId: string;
    turnId: string;
    response: ElicitationResponse;
    context?: ElicitationContext;
    elicitationId?: string;
    elicitationRevision?: number;
}): Promise<ElicitationSubmitResult> {
    const { conversationId, turnId, response } = params;
    const key = scopeKey(conversationId, turnId);
    const store = useOrchestrationStore.getState();
    const elicitation = selectElicitation(store, conversationId, turnId);
    const draft = selectElicitationDraft(store, conversationId, turnId);
    const fail = (message: string): ElicitationSubmitResult => {
        if (elicitation && draft && (!params.elicitationId || params.elicitationId === elicitation.elicitation_id)
            && (params.elicitationRevision === undefined || params.elicitationRevision === (elicitation.revision ?? 0))) {
            useOrchestrationStore.getState().failElicitationSubmission(
                conversationId, turnId, elicitation.elicitation_id, elicitation.revision ?? 0, message,
            );
        }
        return { ok: false, error: message };
    };
    if (!elicitation || !draft || (params.elicitationId && params.elicitationId !== elicitation.elicitation_id)
        || (params.elicitationRevision !== undefined && params.elicitationRevision !== (elicitation.revision ?? 0))
        || store.activeTurns[conversationId] !== turnId) {
        return fail('This question is no longer active. Open the current request to continue.');
    }
    if (draft.submitting) {
        return { ok: false, error: 'An answer is already being submitted.' };
    }
    if (response.action === 'cancel') {
        cancelOrchestration(conversationId);
        turnContexts.delete(key);
        store.clearElicitation(conversationId, turnId);
        store.clearActiveTurn(conversationId);
        useChatStore.getState().settleOrchestrationTurn(conversationId, {
            status: 'cancelled',
            accumulated: '',
        });
        return { ok: true };
    }
    const previous = turnContexts.get(key);
    if (!previous) {
        return fail('This request is no longer available in this browser session. Send the request again.');
    }
    const cleanedResponse: ElicitationResponse = {
        action: response.action,
        content: response.action === 'accept' ? response.content : {},
    };
    const answerContext = response.action === 'accept' ? params.context : undefined;
    const fingerprint = JSON.stringify({ response: cleanedResponse, context: answerContext });
    const submissionId = draft.submissionFingerprint === fingerprint && draft.submissionId
        ? draft.submissionId
        : makeTurnId();
    if (!store.beginElicitationSubmission(
        conversationId, turnId, elicitation.elicitation_id, submissionId, fingerprint,
    )) {
        return { ok: false, error: 'This answer is already being submitted or is no longer current.' };
    }
    const nextContext = { ...previous, revision: previous.revision + 1 };
    const result = await dispatchPlan(
        conversationId,
        turnId,
        nextContext,
        false,
        {
            elicitation,
            response: cleanedResponse,
            context: answerContext,
            elicitationId: elicitation.elicitation_id,
            revision: elicitation.revision ?? previous.revision,
            submissionId,
        },
    );
    if (!result.ok) {
        if (turnContexts.get(key) === nextContext) {
            turnContexts.set(key, previous);
        }
        return fail(result.error);
    }
    return result;
}

/**
 * Approve a plan and run it, streaming its answer into the thread.
 *
 * The run request carries the narrowing edits so the server applies them before executing; the
 * browser never assembles the plan that runs. `beginRun` guards a double approval — a second press
 * or a restored record — by refusing a run id already tracked. Every terminal path settles the
 * thread and ends the run. A dropped reader is reconciled against the saved attempt instead of
 * guessing that execution ended or that the user cancelled it.
 */
export async function approveAndRunPlan(params: {
    conversationId: string;
    turnId: string;
    automatic?: boolean;
}): Promise<void> {
    const { conversationId, turnId } = params;
    const store = useOrchestrationStore.getState();
    const plan = selectPlan(store, conversationId, turnId);
    if (!plan || selectPlanRunBlocked(store, conversationId, turnId)
        || (params.automatic && selectHasPlanHold(store, conversationId, turnId))) {
        return;
    }
    const edits = selectEdits(store, conversationId, turnId);
    if (!isPlanRunnable(applyPlanEdits(plan, edits))) {
        return;
    }
    await executeSavedPlan(conversationId, turnId, plan, edits);
}

async function executeSavedPlan(
    conversationId: string,
    turnId: string,
    plan: OrchestrationPlan,
    edits?: PlanEdits,
): Promise<void> {
    const store = useOrchestrationStore.getState();

    const runId = plan.run_id;
    const planId = plan.plan_id;
    const began = store.beginRun({
        conversationId,
        turnId,
        runId,
        planId,
        startedAt: Date.now(),
    });
    if (!began) {
        return;
    }
    if (store.editorTarget?.conversationId === conversationId && store.editorTarget.turnId === turnId) {
        store.setEditorTarget(null);
    }

    const context = turnContexts.get(scopeKey(conversationId, turnId));
    // Enter the streaming state for the answer without a second user bubble — the question is
    // already in the thread from planning.
    useChatStore.getState().beginOrchestrationTurn(conversationId, '', false);

    const controller = new AbortController();
    activeControllers.get(conversationId)?.abort();
    activeControllers.set(conversationId, controller);
    activeRunIds.set(conversationId, runId);

    const runBody: OrchestrationRunRequest = {
        run_id: runId,
        plan_id: planId,
        conversation_id: conversationId,
        ...(edits ? { edits } : {}),
        // A retry uses its returned child plan version, not the source recovery token.
        ...(plan.edit_version ? { expected_version: plan.edit_version } : {}),
    };

    let settled = false;
    let conflictMessage = '';
    const result = await runOrchestration(
        runBody,
        {
            onStep: (event) => {
                const current = useOrchestrationStore.getState();
                current.applyStepEvent(conversationId, turnId, event);
                current.mergeReasoningAdjustments(conversationId, turnId, event.reasoning_adjustments);
            },
            // A run reports each step starting and finishing as a `thought`, the same event
            // planning uses, so it lands in the same place a planning thought does — feeding the
            // orchestration progress lane while the answer is still being assembled.
            onThought: (event) => {
                useOrchestrationStore.getState().mergeReasoningAdjustments(
                    conversationId, turnId, event.reasoning_adjustments,
                );
                useChatStore
                    .getState()
                    .pushOrchestrationThought(conversationId, event as RunStreamEvent);
            },
            onContent: (_delta, accumulated) =>
                useChatStore.getState().pushOrchestrationContent(conversationId, accumulated),
            onDone: (event, accumulated) => {
                settled = true;
                const status = orchestrationTerminalStatus(event);
                const terminal = { ...event, run_id: runId, turn_id: turnId };
                useOrchestrationStore.getState().updateRunRecovery(runId, {
                    ...normalizeOrchestrationAttempt(terminal), status, plan,
                    transportUnknown: false, checking: false,
                    error: event.message_saved === false
                        ? 'This explanation could not be saved to the conversation. It is kept in this tab; review saved progress before leaving.' : null,
                });
                useOrchestrationStore.getState().mergeReasoningAdjustments(
                    conversationId, turnId, event.reasoning_adjustments ?? event.metadata?.reasoning_adjustments,
                );
                useChatStore.getState().settleOrchestrationTurn(conversationId, {
                    status,
                    event: terminal,
                    accumulated,
                    pendingUserMessageId: context?.pendingUserMessageId ?? null,
                });
                useOrchestrationStore.getState().endRun(runId, status);
            },
            onCancelled: (event, accumulated) => {
                settled = true;
                const terminal = { ...event, run_id: runId, turn_id: turnId, status: 'cancelled' as const };
                useOrchestrationStore.getState().updateRunRecovery(runId, {
                    ...normalizeOrchestrationAttempt(terminal), status: 'cancelled', plan,
                    transportUnknown: false, checking: false,
                    error: event.message_saved === false
                        ? 'This explanation could not be saved to the conversation. It is kept in this tab; review saved progress before leaving.' : null,
                });
                useChatStore
                    .getState()
                    .settleOrchestrationTurn(conversationId, { status: 'cancelled', event: terminal, accumulated });
                useOrchestrationStore.getState().endRun(runId, 'cancelled');
            },
            // Older error-only frames do not prove that finalization reached storage.
            onError: () => {},
            onConflict: (message) => {
                settled = true;
                conflictMessage = message;
                const current = useOrchestrationStore.getState();
                current.releaseRunAttempt(runId);
                current.updatePlanEditor(conversationId, turnId, (editor) => ({
                    ...editor, blocked: true, error: message,
                }));
                useChatStore.getState().settleOrchestrationTurn(conversationId, { status: 'planned' });
            },
            // The plan was already run somewhere else.
            //
            // Only reachable now that a pending approval can be picked up on a second device: two
            // tabs can hold the same card, and the server refuses the second approval rather than
            // doing the work twice. That is not a failure of this turn, so the thread is settled
            // quietly and the conversation re-read -- the answer the other device produced is
            // already stored, and fetching it is how this device catches up.
            onAlreadyRun: () => {
                // Read the existing attempt; it might still be running, failed, or stopped.
            },
        },
        controller.signal,
    );

    if (activeControllers.get(conversationId) === controller) {
        activeControllers.delete(conversationId);
        activeRunIds.delete(conversationId);
    }
    if (result.conflict) {
        await refreshOrchestrationPlanEditor(
            { conversationId, turnId }, result.conflict.current_run_id ?? runId, conflictMessage,
        );
    }
    if (result.rejection) {
        const current = useOrchestrationStore.getState();
        current.releaseRunAttempt(runId);
        current.updateRunRecovery(runId, {
            run_id: runId, turn_id: turnId, plan, status: plan.status,
            transportUnknown: false,
            error: 'The saved attempt was not started. Its saved progress or access may have changed. Review the current attempt; no steps were replayed.',
        });
        useChatStore.getState().settleOrchestrationTurn(conversationId, { status: 'planned' });
        return;
    }

    if (!settled) {
        useOrchestrationStore.getState().updateRunRecovery(runId, {
            run_id: runId, turn_id: turnId, plan, transportUnknown: true,
        });
        if (!activeControllers.has(conversationId)) {
            useChatStore.getState().settleOrchestrationTurn(conversationId, {
                status: 'unknown',
                event: { run_id: runId, turn_id: turnId },
                accumulated: result.accumulated,
            });
        }
        await reconcileOrchestrationRun(conversationId, runId);
    }
}

const reconciliationTimers = new Map<string, ReturnType<typeof setTimeout>>();
const recoverySubmissions = new Map<string, { id: string; version: string; confirmed: boolean; unresolved: boolean }>();
const recoveryLocks = new Set<string>();

export async function loadOrchestrationRecovery(conversationId: string, runId: string): Promise<PersistedRun | null> {
    const record = await fetchOrchestrationRun(runId, { conversationId });
    if (!record || record.run_id !== runId || record.conversation_id !== conversationId) {
        throw new Error('Recovery record unavailable');
    }
    const plan = normalizePlan(record.plan);
    useOrchestrationStore.getState().updateRunRecovery(runId, {
        ...normalizeOrchestrationAttempt(record),
        status: record.status,
        ...(plan ? { plan } : {}),
        detailLoaded: true,
    });
    return record;
}

/** Read-only polling never approves, retries, or invents a cancellation reason. */
export async function reconcileOrchestrationRun(conversationId: string, runId: string): Promise<void> {
    const timer = reconciliationTimers.get(runId);
    if (timer) clearTimeout(timer);
    reconciliationTimers.delete(runId);
    const store = useOrchestrationStore.getState();
    if (store.runRecovery[runId]?.checking) return;
    store.updateRunRecovery(runId, { checking: true, transportUnknown: true });
    try {
        const record = await loadOrchestrationRecovery(conversationId, runId);
        if (!record) return;
        const steps = await fetchRunSteps(runId, { conversationId }).catch(() => []);
        const current = useOrchestrationStore.getState();
        if (record.turn_id && selectPlan(current, conversationId, record.turn_id)?.run_id === runId) {
            current.adoptPersistedPlan(conversationId, record.turn_id, record.plan, steps);
        }
        const terminal = record.status === 'completed' || record.status === 'failed' || record.status === 'cancelled';
        if (terminal && !isOrchestrationRunPending(record)) {
            const event: RunStreamEvent = {
                ...normalizeOrchestrationAttempt(record),
                status: record.status === 'cancelled' ? 'cancelled' : record.status === 'failed' ? 'failed' : 'completed',
                message_id: record.assistant_message_id ?? undefined,
            };
            const status = orchestrationTerminalStatus(event);
            current.updateRunRecovery(runId, { transportUnknown: false, checking: false, error: null });
            current.endRun(runId, status);
            const chat = useChatStore.getState();
            const otherRun = Object.values(current.inFlight)
                .some((run) => run.conversationId === conversationId && run.runId !== runId);
            const activeTurn = current.activeTurns[conversationId];
            if (chat.activeConversationId === conversationId && !otherRun
                && (!chat.streaming || !activeTurn || activeTurn === record.turn_id)) {
                const partial = chat.messages.find((message) => message.id === `orchestration-status-${runId}`)?.content ?? '';
                chat.settleOrchestrationTurn(conversationId, {
                    status, event, accumulated: record.assistant_message_id ? '' : partial,
                });
                // Saved messages own final content, citations and artifact metadata.
                if (record.assistant_message_id) await useChatStore.getState().reloadMessages();
                else current.updateRunRecovery(runId, {
                    error: record.finalization_status === 'interrupted'
                        ? 'Execution was interrupted before a final conversation message could be confirmed. Review the saved status and recovery options.'
                        : record.message_saved === false || record.finalization_status === 'failed'
                        ? 'The run ended, but its conversation message was not saved. This visible status is kept in this tab.'
                        : 'This run ended without a linked conversation message. Review its saved status and recovery options.',
                });
            }
            return;
        }
        current.updateRunRecovery(runId, {
            checking: false,
            error: terminal
                ? 'The server is saving the final response. Checking saved status; no retry will start.'
                : 'The server has not confirmed a final result. Execution may still be running. Checking saved status; no retry will start.',
        });
    } catch {
        useOrchestrationStore.getState().updateRunRecovery(runId, {
            checking: false,
            error: 'The saved run status could not be reached. Execution may still be running. No retry will start until its status is confirmed.',
        });
    }
    reconciliationTimers.set(runId, setTimeout(() => {
        void reconcileOrchestrationRun(conversationId, runId);
    }, 5000));
}

export function openOrchestrationRecovery(conversationId: string, runId: string): void {
    useOrchestrationStore.setState({ recoveryTarget: { conversationId, runId } });
    useChatStore.getState().setDrawerMode('plan');
    void loadOrchestrationRecovery(conversationId, runId).then((record) => {
        if (record && isOrchestrationRunPending(record)) {
            return reconcileOrchestrationRun(conversationId, runId);
        }
    }).catch(() => {
        useOrchestrationStore.getState().updateRunRecovery(runId, {
            error: 'The saved attempt could not be loaded. Your previous failure and progress have been kept.',
        });
    });
}

export async function retryOrchestrationRun(
    conversationId: string,
    runId: string,
    confirmedVersion?: string,
): Promise<{ confirmationRequired?: boolean; version?: string }> {
    const key = scopeKey(conversationId, runId);
    const store = useOrchestrationStore.getState();
    if (recoveryLocks.has(key)) return {};
    const fail = (error: string) => useOrchestrationStore.getState().updateRunRecovery(runId, { error });
    if (useChatStore.getState().activeConversationId !== conversationId
        || useChatStore.getState().streaming
        || Object.values(store.inFlight).some((run) => run.conversationId === conversationId)) {
        fail('Finish or stop the current request, then review this saved attempt before retrying.');
        return {};
    }
    recoveryLocks.add(key);
    store.updateRunRecovery(runId, { busy: true, error: null });
    const initialTurn = store.activeTurns[conversationId];
    try {
        const record = await loadOrchestrationRecovery(conversationId, runId);
        const recovery = normalizeOrchestrationRecovery(record?.recovery);
        const previous = recoverySubmissions.get(key);
        if (!record || !recovery || (!previous?.unresolved && (!recovery.eligible || !recovery.expected_version
            || recovery.source_run_id !== runId
            || (recovery.current_run_id && recovery.current_run_id !== runId)))) {
            fail(recovery?.message || 'This saved attempt cannot be resumed. Review the current attempt or start a new plan deliberately.');
            return {};
        }
        if (!previous?.unresolved && confirmedVersion && confirmedVersion !== recovery.expected_version) {
            fail('The recovery preview changed. Review the updated saved steps before confirming another retry.');
            return {};
        }
        if (!previous?.unresolved && recovery.requires_confirmation && confirmedVersion !== recovery.expected_version) {
            return { confirmationRequired: true, version: recovery.expected_version ?? undefined };
        }
        const confirmed = recovery.requires_confirmation && confirmedVersion === recovery.expected_version;
        const submission = previous?.unresolved ? previous
            : { id: makeTurnId(), version: recovery.expected_version ?? '', confirmed, unresolved: true };
        recoverySubmissions.set(key, submission);
        const child = await prepareOrchestrationRetry(runId, {
            conversation_id: conversationId,
            submission_id: submission.id,
            expected_version: submission.version,
            confirm_external_effects: submission.confirmed,
        });
        submission.unresolved = false;
        const plan = normalizePlan(child.plan);
        if (!plan || child.conversation_id !== conversationId || child.turn_id !== record.turn_id
            || child.retry_of_run_id !== runId || child.run_id !== plan.run_id
            || plan.conversation_id !== conversationId || plan.turn_id !== record.turn_id) {
            fail('The prepared attempt could not be verified. Nothing was executed. Reload the saved run before continuing.');
            return {};
        }
        const current = useOrchestrationStore.getState();
        current.updateRunRecovery(runId, {
            latest_attempt_run_id: child.run_id,
            recovery: { ...recovery, eligible: false, current_run_id: child.run_id },
        });
        current.updateRunRecovery(child.run_id, { ...normalizeOrchestrationAttempt(child), plan, status: child.status });
        if (useChatStore.getState().activeConversationId !== conversationId
            || useChatStore.getState().streaming
            || current.activeTurns[conversationId] !== initialTurn
            || Object.values(current.inFlight).some((run) => run.conversationId === conversationId)) {
            fail('A retry was prepared but not started because the active request changed. Open the current saved attempt to continue manually.');
            return {};
        }
        // Never replan or append a user message. The saved child is the server's effective plan.
        current.setPlan(conversationId, plan.turn_id, plan);
        current.setActiveTurn(conversationId, plan.turn_id);
        current.pinRun(null);
        useOrchestrationStore.setState({ recoveryTarget: null });
        await executeSavedPlan(conversationId, plan.turn_id, plan);
        return {};
    } catch (error) {
        const info = error instanceof ApiError ? orchestrationErrorInfo(error.payload, error.status) : {};
        if (info.code) recoverySubmissions.delete(key);
        const payload = error instanceof ApiError && error.payload && typeof error.payload === 'object'
            ? error.payload as Record<string, unknown> : {};
        const recovery = normalizeOrchestrationRecovery(payload.recovery);
        if (recovery) useOrchestrationStore.getState().updateRunRecovery(runId, { recovery });
        if (info.code === 'confirmation_required' && recovery?.expected_version) {
            return { confirmationRequired: true, version: recovery.expected_version };
        }

        if (info.current_run_id) useOrchestrationStore.getState().updateRunRecovery(runId, {
            latest_attempt_run_id: info.current_run_id,
        });
        fail(info.code === 'recovery_changed'
            ? 'Recovery changed or a newer attempt already exists. Review the current attempt; no work was started by this request.'
            : 'Recovery could not be prepared. Your previous failure and saved progress have been kept. Check the saved status and try again.');
        return {};
    } finally {
        recoveryLocks.delete(key);
        useOrchestrationStore.getState().updateRunRecovery(runId, { busy: false });
    }
}

export async function runPreparedOrchestrationRetry(conversationId: string, runId: string): Promise<void> {
    const key = scopeKey(conversationId, runId);
    if (recoveryLocks.has(key)) return;
    recoveryLocks.add(key);
    const fail = () => useOrchestrationStore.getState().updateRunRecovery(runId, {
        error: 'This saved retry cannot start right now. Check the current attempt and finish any active request first.',
    });
    try {
        const record = await loadOrchestrationRecovery(conversationId, runId);
        const plan = normalizePlan(record?.plan);
        if (!plan || !record?.retry_of_run_id || (record.status !== 'awaiting_approval' && record.status !== 'approved')
            || plan.run_id !== runId || plan.conversation_id !== conversationId || plan.turn_id !== record.turn_id
            || useChatStore.getState().activeConversationId !== conversationId || useChatStore.getState().streaming
            || Object.values(useOrchestrationStore.getState().inFlight).some((run) => run.conversationId === conversationId)) {
            fail();
            return;
        }
        const source = await loadOrchestrationRecovery(conversationId, record.retry_of_run_id);
        const latest = source?.latest_attempt_run_id || source?.recovery?.current_run_id;
        if (latest !== runId || useChatStore.getState().activeConversationId !== conversationId
            || useChatStore.getState().streaming) {
            fail();
            return;
        }
        const current = useOrchestrationStore.getState();
        current.setPlan(conversationId, plan.turn_id, plan);
        current.setActiveTurn(conversationId, plan.turn_id);
        useOrchestrationStore.setState({ recoveryTarget: null });
        await executeSavedPlan(conversationId, plan.turn_id, plan);
    } catch {
        fail();
    } finally {
        recoveryLocks.delete(key);
    }
}

export async function cancelOrchestration(conversationId: string, runId?: string): Promise<void> {
    if (!runId && activeControllers.has(conversationId) && !activeRunIds.has(conversationId)) {
        activeControllers.get(conversationId)?.abort();
        return;
    }
    const runs = Object.values(useOrchestrationStore.getState().inFlight)
        .filter((candidate) => candidate.conversationId === conversationId);
    const targetId = runId ?? activeRunIds.get(conversationId);
    const run = targetId ? runs.find((candidate) => candidate.runId === targetId)
        : runs.sort((left, right) => right.startedAt - left.startedAt)[0];
    if (!run) {
        if (!runId) activeControllers.get(conversationId)?.abort();
        return;
    }
    const controller = activeRunIds.get(conversationId) === run.runId
        ? activeControllers.get(conversationId) : undefined;
    try {
        await cancelOrchestrationRun(run.runId, conversationId);
        if (activeControllers.get(conversationId) === controller) controller?.abort();
        await reconcileOrchestrationRun(conversationId, run.runId);
    } catch {
        useOrchestrationStore.getState().updateRunRecovery(run.runId, {
            error: 'Stop could not be confirmed by the server. Execution may still be running. Try Stop again or check saved status.',
        });
    }
}

/** Whether a plan or run is streaming for a conversation, so Stop can route to the right cancel. */
export function hasActiveOrchestration(conversationId: string): boolean {
    return activeControllers.has(conversationId)
        || Object.values(useOrchestrationStore.getState().inFlight).some((run) => run.conversationId === conversationId);
}

/**
 * Dismiss a turn's plan or question outright.
 *
 * The card's Cancel, which is a different act from Stop: it throws the proposal away rather than
 * interrupting work in progress. Any in-flight stream is aborted first (a plan still arriving),
 * then the plan, question and inline card are forgotten and the thinking state dropped. The run
 * history is left untouched — a run that already finished stays in the timeline.
 */
export function dismissOrchestrationTurn(conversationId: string, turnId: string): void {
    cancelOrchestration(conversationId);
    const key = scopeKey(conversationId, turnId);
    editorControllers.get(key)?.abort();
    editorControllers.delete(key);
    const store = useOrchestrationStore.getState();
    store.clearPlan(conversationId, turnId);
    store.clearElicitation(conversationId, turnId);
    store.clearActiveTurn(conversationId);
    useChatStore
        .getState()
        .settleOrchestrationTurn(conversationId, { status: 'cancelled', accumulated: '' });
}

function editorRequestFailure(error: unknown): { message: string; info: OrchestrationRequestError } {
    if (error instanceof ApiError) {
        const payload = error.payload as { error?: unknown } | null;
        return {
            message: typeof payload?.error === 'string'
                ? payload.error : 'The saved plan could not be loaded. Please try again.',
            info: orchestrationErrorInfo(error.payload, error.status),
        };
    }
    return {
        message: 'The request could not connect. Your current plan and instruction have been kept.',
        info: {},
    };
}

function isEditorRequestCurrent(target: PlanEditorTarget, controller: AbortController): boolean {
    return !controller.signal.aborted
        && editorControllers.get(scopeKey(target.conversationId, target.turnId)) === controller
        && Boolean(selectPlanEditor(useOrchestrationStore.getState(), target.conversationId, target.turnId));
}

async function loadPlanEditorState(
    target: PlanEditorTarget,
    begin: boolean,
    runId?: string,
    preservedError?: string,
): Promise<ElicitationSubmitResult> {
    const { conversationId, turnId } = target;
    const key = scopeKey(conversationId, turnId);
    const store = useOrchestrationStore.getState();
    const plan = selectPlan(store, conversationId, turnId);
    if (!plan || !selectCanEditPlan(store, conversationId, turnId)) {
        return { ok: false, error: 'Only a pending plan can be edited.' };
    }
    if (editorControllers.has(key)) {
        return { ok: true };
    }
    const controller = new AbortController();
    editorControllers.set(key, controller);
    store.updatePlanEditor(conversationId, turnId, (editor) => ({
        ...editor,
        loading: true,
        error: preservedError ?? (begin && editor.state && !editor.blocked ? editor.error : null),
    }));
    const currentRunId = runId ?? plan.run_id;
    try {
        const editor = begin
            ? await beginPlanEdit(currentRunId, {
                conversation_id: conversationId,
                plan_id: plan.plan_id,
                edits: selectEdits(store, conversationId, turnId),
                ...(plan.edit_version ? { expected_version: plan.edit_version } : {}),
            }, controller.signal)
            : await fetchPlanEditor(currentRunId, conversationId, { signal: controller.signal });
        if (!isEditorRequestCurrent(target, controller)) {
            return { ok: false, error: 'This editor request is no longer active.' };
        }
        if (!useOrchestrationStore.getState().adoptPlanEditor(
            conversationId, turnId, editor, { retainLocalEdits: begin },
        )) {
            throw new Error('Invalid or stale editor identity');
        }
        return { ok: true };
    } catch (error) {
        const { message, info } = editorRequestFailure(error);
        if (isEditorRequestCurrent(target, controller)) {
            if (info.code === 'plan_changed' || info.code === 'edit_in_progress') {
                try {
                    const editor = await fetchPlanEditor(
                        info.current_run_id ?? currentRunId, conversationId, { signal: controller.signal },
                    );
                    if (isEditorRequestCurrent(target, controller)
                        && useOrchestrationStore.getState().adoptPlanEditor(conversationId, turnId, editor)) {
                        useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId,
                            (session) => ({ ...session, error: message }));
                        return { ok: true };
                    }
                } catch {
                    // The local pause remains; a failed refresh must not authorize stale work.
                }
            }
            useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId, (editor) => ({
                ...editor, blocked: true, error: message,
            }));
        }
        return { ok: false, error: message };
    } finally {
        if (isEditorRequestCurrent(target, controller)) {
            editorControllers.delete(key);
            useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId, (editor) => ({
                ...editor, loading: false,
            }));
        }
    }
}

/** Pause synchronously, then acquire the durable hold; closing never undoes either. */
export async function openOrchestrationPlanEditor(target: PlanEditorTarget): Promise<void> {
    const store = useOrchestrationStore.getState();
    if (!selectCanEditPlan(store, target.conversationId, target.turnId)) {
        return;
    }
    store.updatePlanEditor(target.conversationId, target.turnId, (editor) => editor);
    store.setEditorTarget(target);
    await loadPlanEditorState(target, true);
}

/** Read-only hydration also works with an old run ID; the server resolves the current revision. */
export async function refreshOrchestrationPlanEditor(
    target: PlanEditorTarget,
    runId?: string,
    preservedError?: string,
): Promise<ElicitationSubmitResult> {
    return loadPlanEditorState(target, false, runId, preservedError);
}

export async function submitPlanRevision(
    target: PlanEditorTarget,
    action: PlanRevisionAction,
): Promise<ElicitationSubmitResult> {
    const { conversationId, turnId } = target;
    const key = scopeKey(conversationId, turnId);
    const store = useOrchestrationStore.getState();
    const session = selectPlanEditor(store, conversationId, turnId);
    const plan = selectPlan(store, conversationId, turnId);
    const discarding = action.action === 'discard';
    if (!session?.state || !plan || !selectCanEditPlan(store, conversationId, turnId)
        || session.loading || session.cancellationStatus === 'cancelling'
        || (!discarding && (session.submitting || session.blocked || session.state.busy
            || editorControllers.has(key) || plan.edit_version !== session.state.version))) {
        return { ok: false, error: 'Wait for the current plan to be saved before editing.' };
    }
    const pending = session.state.pending;
    const cancellationChangedError = 'The plan changed. Review the current change before cancelling it.';
    if (action.action === 'discard' && action.elicitation_id !== undefined
        && (action.elicitation_id !== pending?.elicitation_id
            || action.elicitation_revision !== pending?.revision)) {
        store.updatePlanEditor(conversationId, turnId, (editor) => ({
            ...editor, error: cancellationChangedError,
        }));
        return { ok: false, error: cancellationChangedError };
    }
    if ((pending && (action.action === 'ask' || action.action === 'restore'))
        || (action.action === 'answer' && (!pending
            || action.elicitation_id !== pending.elicitation_id
            || action.elicitation_revision !== (pending.revision ?? 0)))) {
        return { ok: false, error: 'Answer or cancel the current edit question first.' };
    }
    if (action.action === 'ask') {
        action = { ...action, instruction: action.instruction.trim() };
        if (!action.instruction || action.instruction.length > MAX_PLAN_INSTRUCTION_LENGTH) {
            const error = `Enter an instruction of 1–${MAX_PLAN_INSTRUCTION_LENGTH} characters.`;
            store.updatePlanEditor(conversationId, turnId, (editor) => ({ ...editor, error }));
            return { ok: false, error };
        }
    }
    const controller = new AbortController();
    const previousController = editorControllers.get(key);
    editorControllers.set(key, controller);
    if (discarding) {
        // The explicit discard owns this turn now. Aborting the reader alone is not
        // cancellation: the server must acknowledge the token-rotating discard below.
        previousController?.abort();
    }
    store.updatePlanEditor(conversationId, turnId, (editor) => ({
        ...editor,
        submitting: true,
        cancellationStatus: discarding ? 'cancelling' : 'idle',
        error: null,
        pendingDraft: editor.pendingDraft ? { ...editor.pendingDraft, submitting: true } : null,
    }));
    let failure = 'The planner did not return a saved revision. Your current plan has been kept.';
    let info: OrchestrationRequestError | undefined;
    let accepted = false;
    try {
        let requestPlan = plan;
        let version = session.state.version;
        if (discarding) {
            const latest = await fetchPlanEditor(plan.run_id, conversationId, { signal: controller.signal });
            if (!isEditorRequestCurrent(target, controller)) {
                return { ok: false, error: 'This editor request is no longer active.' };
            }
            if (!useOrchestrationStore.getState().adoptPlanEditor(conversationId, turnId, latest)) {
                throw new Error('Invalid or stale editor identity');
            }
            requestPlan = latest.plan;
            version = latest.version;
            if (!latest.busy && !latest.pending && (!previousController
                || latest.version !== session.state.version || latest.plan.run_id !== plan.run_id)) {
                accepted = true;
                useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId, (editor) => ({
                    ...editor,
                    submission: null,
                    error: 'No pending change remains. Review the latest saved plan before running it.',
                }));
                return { ok: true };
            }
            const sameQuestion = pending === null
                ? latest.pending === null
                : latest.pending?.elicitation_id === pending.elicitation_id
                    && latest.pending?.revision === pending.revision;
            if (latest.plan.run_id !== plan.run_id || latest.plan.plan_id !== plan.plan_id
                || latest.version !== session.state.version || !sameQuestion) {
                failure = cancellationChangedError;
                useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId, (editor) => ({
                    ...editor, submission: null, error: failure,
                }));
                return { ok: false, error: failure };
            }
            if (pending) {
                action = {
                    action: 'discard',
                    elicitation_id: pending.elicitation_id,
                    elicitation_revision: pending.revision ?? 0,
                };
            }
        }
        const edits = discarding ? undefined : selectEdits(store, conversationId, turnId);
        const fingerprint = JSON.stringify({ runId: requestPlan.run_id, version, edits, action });
        const submissionId = session.submission?.fingerprint === fingerprint
            ? session.submission.id : makeTurnId();
        const body: PlanRevisionRequest = {
            ...action,
            conversation_id: conversationId,
            expected_version: version,
            ...(edits ? { edits } : {}),
            submission_id: submissionId,
        };
        useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId, (editor) => ({
            ...editor, submission: { id: submissionId, fingerprint },
        }));
        const result = await reviseOrchestrationPlan(requestPlan.run_id, body, {
            onThought: (event) => {
                if (isEditorRequestCurrent(target, controller)) {
                    useOrchestrationStore.getState().mergeReasoningAdjustments(
                        conversationId, turnId, event.reasoning_adjustments,
                    );
                }
            },
            onError: (message, error) => { failure = message; info = error; },
        }, controller.signal);
        if (!isEditorRequestCurrent(target, controller)) {
            return { ok: false, error: 'This editor request is no longer active.' };
        }
        accepted = !result.errored && !result.cancelled && Boolean(result.editor)
            && useOrchestrationStore.getState().adoptPlanEditor(conversationId, turnId, result.editor!);
        if (accepted) {
            const context = turnContexts.get(key);
            if (context && result.editor) {
                context.revision = result.editor.plan.revision;
            }
            useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId, (editor) => ({
                ...editor,
                instruction: action.action === 'ask' && !result.editor?.pending
                    && editor.instruction.trim() === action.instruction ? '' : editor.instruction,
                submission: null,
            }));
        } else {
            useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId, (editor) => ({
                ...editor, error: failure,
                blocked: discarding || info?.code === 'plan_changed' || info?.code === 'edit_in_progress'
                    || info?.code === 'already_run' || info?.status === 403 || info?.status === 404,
            }));
        }
    } catch (error) {
        failure = editorRequestFailure(error).message;
        if (isEditorRequestCurrent(target, controller)) {
            useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId,
                (editor) => ({ ...editor, error: failure, blocked: discarding || editor.blocked }));
        }
    } finally {
        if (isEditorRequestCurrent(target, controller)) {
            editorControllers.delete(key);
            useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId, (editor) => ({
                ...editor,
                submitting: false,
                cancellationStatus: discarding && !accepted ? 'failed' : 'idle',
                pendingDraft: editor.pendingDraft ? { ...editor.pendingDraft, submitting: false } : null,
            }));
        }
    }
    if (info?.code === 'plan_changed' || info?.code === 'edit_in_progress') {
        await refreshOrchestrationPlanEditor(target, info.current_run_id ?? plan.run_id, failure);
    }
    return accepted ? { ok: true } : { ok: false, error: failure };
}

export async function loadPlanEditorHistory(target: PlanEditorTarget): Promise<void> {
    const { conversationId, turnId } = target;
    const session = selectPlanEditor(useOrchestrationStore.getState(), conversationId, turnId);
    const editor = session?.state;
    if (!editor || session.historyLoading || editor.next_before_revision === null) {
        return;
    }
    useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId,
        (current) => ({ ...current, historyLoading: true }));
    try {
        const page = await fetchPlanEditor(editor.plan.run_id, conversationId, {
            beforeRevision: editor.next_before_revision,
        });
        const current = selectPlanEditor(useOrchestrationStore.getState(), conversationId, turnId);
        if (current?.state?.version !== editor.version || page.version !== editor.version) {
            return;
        }
        const byRun = new Map([...current.state.history, ...page.history].map((entry) => [entry.run_id, entry]));
        useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId, (value) => ({
            ...value,
            state: value.state ? {
                ...value.state,
                history: [...byRun.values()].sort((left, right) => right.revision - left.revision),
                next_before_revision: page.next_before_revision,
            } : null,
        }));
    } catch (error) {
        if (selectPlanEditor(useOrchestrationStore.getState(), conversationId, turnId)) {
            useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId,
                (current) => ({ ...current, error: editorRequestFailure(error).message }));
        }
    } finally {
        if (selectPlanEditor(useOrchestrationStore.getState(), conversationId, turnId)) {
            useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId,
                (current) => ({ ...current, historyLoading: false }));
        }
    }
}

export async function previewPlanEditorRevision(target: PlanEditorTarget, runId: string): Promise<void> {
    const { conversationId, turnId } = target;
    const store = useOrchestrationStore.getState();
    const session = selectPlanEditor(store, conversationId, turnId);
    if (!session?.state) {
        return;
    }
    if (session.state.plan.run_id === runId) {
        store.updatePlanEditor(conversationId, turnId, (editor) => ({
            ...editor, previewRunId: null, previewPlan: null, previewLoading: false,
        }));
        return;
    }
    store.updatePlanEditor(conversationId, turnId, (editor) => ({
        ...editor, previewRunId: runId, previewPlan: null, previewLoading: true, error: null,
    }));
    const stillSelected = () => {
        const current = selectPlanEditor(useOrchestrationStore.getState(), conversationId, turnId);
        return current?.previewRunId === runId && current.state?.version === session.state?.version;
    };
    try {
        const run = await fetchOrchestrationRun(runId, { conversationId });
        const plan = normalizePlan(run?.plan);
        if (!stillSelected()) {
            return;
        }
        if (!plan || plan.run_id !== runId || plan.turn_id !== turnId
            || plan.conversation_id !== conversationId) {
            throw new Error('Invalid history identity');
        }
        useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId,
            (editor) => ({ ...editor, previewPlan: plan }));
    } catch {
        if (stillSelected()) {
            useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId,
                (editor) => ({ ...editor, error: 'This revision could not be previewed. The current plan is unchanged.' }));
        }
    } finally {
        if (stillSelected()) {
            useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId,
                (editor) => ({ ...editor, previewLoading: false }));
        }
    }
}
