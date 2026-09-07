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
    fetchOrchestrationRun,
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
    type OrchestrationRunRequest,
    type OrchestrationRequestError,
    type PlanRevisionAction,
    type PlanRevisionRequest,
    type RunStreamEvent,
} from './orchestration';
import { applyPlanEdits, isPlanApproved, isPlanAwaitingApproval, isPlanRunnable, normalizePlan } from './orchestrationPlan';
import type { Json } from './types';
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
    seeds: Record<string, unknown>;
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
     * `web_search_enabled`. Assembled by the composer; passed through to the plan request as-is.
     */
    seeds?: Record<string, unknown>;
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
    const isCurrentRequest = () =>
        !controller.signal.aborted && activeControllers.get(currentConversationId) === controller;
    await planOrchestration(
        body,
        {
            onThought: (event) => {
                if (isCurrentRequest()) {
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
                useOrchestrationStore.getState().setPlan(currentConversationId, currentTurnId, plan);
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
 * thread and ends the run; a bare abort (Stop, with no terminal frame) is settled after the await,
 * because `runOrchestration` reports that as `cancelled` without calling a handler.
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

    const runBody: OrchestrationRunRequest = {
        run_id: runId,
        plan_id: planId,
        conversation_id: conversationId,
        edits,
        ...(plan.edit_version ? { expected_version: plan.edit_version } : {}),
    };

    let settled = false;
    let conflictMessage = '';
    const result = await runOrchestration(
        runBody,
        {
            onStep: (event) =>
                useOrchestrationStore.getState().applyStepEvent(conversationId, turnId, event),
            // A run reports each step starting and finishing as a `thought`, the same event
            // planning uses, so it lands in the same place a planning thought does — feeding the
            // orchestration progress lane while the answer is still being assembled.
            onThought: (event) =>
                useChatStore
                    .getState()
                    .pushOrchestrationThought(conversationId, event as RunStreamEvent),
            onContent: (_delta, accumulated) =>
                useChatStore.getState().pushOrchestrationContent(conversationId, accumulated),
            onDone: (event, accumulated) => {
                settled = true;
                useChatStore.getState().settleOrchestrationTurn(conversationId, {
                    status: 'completed',
                    event,
                    accumulated,
                    pendingUserMessageId: context?.pendingUserMessageId ?? null,
                });
                useOrchestrationStore.getState().endRun(runId, 'completed');
            },
            onCancelled: (_event, accumulated) => {
                settled = true;
                useChatStore
                    .getState()
                    .settleOrchestrationTurn(conversationId, { status: 'cancelled', accumulated });
                useOrchestrationStore.getState().endRun(runId, 'cancelled');
            },
            onError: (message) => {
                settled = true;
                useChatStore
                    .getState()
                    .settleOrchestrationTurn(conversationId, { status: 'failed', error: message });
                useOrchestrationStore.getState().endRun(runId, 'failed');
            },
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
                settled = true;
                useChatStore.getState().settleOrchestrationTurn(conversationId, {
                    status: 'cancelled',
                    accumulated: '',
                });
                useOrchestrationStore.getState().endRun(runId, 'completed');
                useOrchestrationStore.getState().clearActiveTurn(conversationId);
                void useChatStore.getState().reloadMessages();
            },
        },
        controller.signal,
    );

    if (activeControllers.get(conversationId) === controller) {
        activeControllers.delete(conversationId);
    }
    if (result.conflict) {
        await refreshOrchestrationPlanEditor(
            { conversationId, turnId }, result.conflict.current_run_id ?? runId, conflictMessage,
        );
    }

    if (!settled) {
        // A bare abort: Stop was pressed and the stream dropped before any terminal frame. Keep
        // whatever partial answer had arrived, matching a cancelled chat stream.
        useChatStore.getState().settleOrchestrationTurn(conversationId, {
            status: 'cancelled',
            accumulated: result.accumulated,
        });
        useOrchestrationStore.getState().endRun(runId, 'cancelled');
    }
}

/**
 * Stop the in-flight plan or run for a conversation.
 *
 * Aborting the reader is all that is available: orchestration has no run-cancel endpoint the way
 * chat does, so the server may finish the work unwatched. The UI settles either way, and the
 * partial answer is kept.
 */
export function cancelOrchestration(conversationId: string): void {
    activeControllers.get(conversationId)?.abort();
}

/** Whether a plan or run is streaming for a conversation, so Stop can route to the right cancel. */
export function hasActiveOrchestration(conversationId: string): boolean {
    return activeControllers.has(conversationId);
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
