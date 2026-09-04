// orchestration.ts
// The two-phase chat-orchestration contract, typed, plus the SSE clients that speak it.
//
// Orchestration replaces the composer's pick-everything-first flow: the user asks, the server
// *plans* the work (`POST /api/v2/orchestration/plan`), the plan is shown and approved, and
// then the server *runs* it (`POST /api/v2/orchestration/run`). Both phases are SSE POSTs.
//
// The types here mirror `functions_orchestration_schema.py`, which is the source of truth and
// the security boundary: a plan is language-model output that the server validates and repairs
// before it will run one, and every field below is quoted from that module so the card renders
// what the server actually settled on -- `validation.repairs` included, because a repaired plan
// differs from what the model proposed and the user is owed the difference.
//
// SSE REUSE. There is one SSE reader in this app -- `readSsePost` in `sse.ts` -- and this file
// reuses it rather than adding a second. `sse.ts` was parameterised (the byte pump, the `\n\n`
// framing, the legacy escaped-delimiter repair and malformed-frame tolerance were lifted out of
// the chat-specific `consumeStreamResponse` into `readSsePost`); the chat client and these two
// clients now share that one loop and differ only in how they dispatch a decoded event. Opening
// the POST and reading a pre-stream JSON error is done inline below because that is an HTTP
// concern, not a framing one, and it diverges from chat: chat can reattach a dropped generation
// through `/api/chat/stream/reattach`, and orchestration has no such endpoint, so a dropped
// stream here is reported rather than recovered.

import { apiUrl, CREDENTIALS_MODE } from './apiClient';
import { readSsePost } from './sse';
import type { ChatStreamEvent, Json } from './types';

// `Json` is the shape of a step's `arguments` and the plan's opaque `inputs`/`outputs`, so it is
// part of this contract's surface. Re-exported here (rather than making consumers reach into
// `./types`) so `orchestrationPlan.ts`, the store and the cards all read one type module.
export type { Json } from './types';

/* -------------------------------------------------------------------------- */
/* Contract enumerations                                                       */
/* -------------------------------------------------------------------------- */

/** Triage's read on the request, from `intent.complexity`. */
export type PlanComplexity = 'trivial' | 'simple' | 'complex';

/** A step's lifecycle, from `STEP_STATUSES`. Live status arrives on run-stream frames. */
export type StepStatus =
    | 'pending'
    | 'running'
    | 'completed'
    | 'failed'
    | 'skipped'
    | 'cancelled';

/** How a plan is approved before it runs, from `APPROVAL_MODES`. */
export type ApprovalMode = 'manual' | 'timed' | 'auto';

/** Where approval currently stands, from `APPROVAL_STATES`. */
export type ApprovalState = 'pending' | 'approved' | 'rejected' | 'expired';

/** A plan's lifecycle, from `PLAN_STATUSES`. */
export type PlanStatus =
    | 'draft'
    | 'awaiting_approval'
    | 'approved'
    | 'running'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'superseded';

/** A capability's rough cost, from `COST_CLASSES`. Carried on a step as `estimated_cost`. */
export type CostClass = 'low' | 'medium' | 'high';

/** MCP elicitation response actions, named exactly as MCP names them (`ELICITATION_ACTIONS`). */
export type ElicitationAction = 'accept' | 'decline' | 'cancel';

/** The primitive types an elicitation field may take, from `ELICITATION_PRIMITIVE_TYPES`. */
export type ElicitationPrimitiveType = 'string' | 'number' | 'integer' | 'boolean';

/* -------------------------------------------------------------------------- */
/* Plan                                                                        */
/* -------------------------------------------------------------------------- */

/** Triage's summary of what the user is asking for, from `intent`. */
export interface OrchestrationIntent {
    summary: string;
    complexity: PlanComplexity;
    /** A model-reported confidence, passed through unchanged, so it may be absent. */
    confidence?: number | null;
}

/**
 * One planned unit of work.
 *
 * `arguments` is the capability's own input object (a `document_search` step, say, carries
 * `query`, `document_ids`, `doc_scope`, `top_n`). The document-bearing keys are the ones the
 * narrowing edits in `orchestrationPlan.ts` may prune -- see `DOCUMENT_ARRAY_FIELDS` there.
 * `capability_id` is deliberately a string, not a closed union: the registry is defined and
 * gated server-side, and a client that hard-codes its members would drop a step the moment an
 * admin enables a capability this build had not heard of.
 */
export interface OrchestrationStep {
    step_id: string;
    capability_id: string;
    title: string;
    rationale: string;
    arguments: Json;
    depends_on: string[];
    optional: boolean;
    enabled: boolean;
    estimated_cost: CostClass;
    status: StepStatus;
}

/** The approval block, from `normalize_plan`'s `approval`. */
export interface OrchestrationApproval {
    mode: ApprovalMode;
    /** Countdown length for timed mode; the countdown itself runs in the browser. */
    timeout_seconds: number;
    state: ApprovalState;
    /** ISO timestamp once approved, otherwise null. */
    approved_at: string | null;
    /** User id once approved, otherwise null. */
    approved_by: string | null;
    /** Set once the user narrows the plan; see `apply_plan_edits`. */
    edited: boolean;
}

/**
 * What the validator did to the plan, from `validate_plan`'s `validation`.
 *
 * `ok` is false only when the model's plan contained hard errors; `repairs` is the honest
 * record of what was silently corrected, and the card is expected to show it, because running a
 * repaired plan without saying so would be as opaque as running an invalid one.
 */
export interface OrchestrationValidation {
    ok: boolean;
    errors: string[];
    repairs: string[];
}

/**
 * A validated, runnable plan.
 *
 * `inputs` and `outputs` are carried opaquely: the prompt's contract lists them, but the schema
 * module (`normalize_plan`) does not populate them, so their shape is owned by the planner /
 * executor work being built in parallel. They are typed loosely rather than guessed at, so this
 * client neither drops them nor claims a structure the server has not committed to.
 */
export interface OrchestrationPlan {
    plan_id: string;
    run_id: string;
    /**
     * The turn this plan answers, echoed from the plan request.
     *
     * One turn is one question, and it keeps this id across every re-plan even though `plan_id`
     * and `run_id` are minted fresh each revision. The client mints it and sends it; the server
     * carries it back here rather than one of its own, so both halves key the turn on one value.
     */
    turn_id: string;
    /** Bumped each time the same turn is re-planned. */
    revision: number;
    conversation_id: string;
    user_id: string;
    planner_contract_version: number;
    intent: OrchestrationIntent;
    assumptions: string[];
    inputs?: Json;
    steps: OrchestrationStep[];
    outputs?: Json[];
    approval: OrchestrationApproval;
    validation: OrchestrationValidation;
    status: PlanStatus;
}

/**
 * The user's edits to a plan before it runs. Narrowing only.
 *
 * The one shape both this client and `apply_plan_edits` agree on: a set of step ids to disable,
 * and, per step, a set of document ids to drop. Widening is deliberately unrepresentable here --
 * there is no way to add a step or a document -- because a plan the browser widened would never
 * have passed the planner's reasoning or the authorization check that followed it.
 */
export interface PlanEdits {
    disabled_step_ids: string[];
    removed_document_ids: Record<string, string[]>;
}

/* -------------------------------------------------------------------------- */
/* Elicitation                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * One field of an elicitation's `requested_schema.properties`.
 *
 * MCP restricts elicitation schemas to a flat object of primitives (or arrays of primitives) so
 * that any client can render one without a general JSON Schema implementation. `validate_
 * elicitation_schema` enforces exactly this, which is why nesting cannot appear: a `type` is a
 * primitive, or it is `'array'` with primitive `items`. `enum`, `title`, `description` and
 * `default` pass through.
 */
export interface ElicitationFieldSchema {
    type: ElicitationPrimitiveType | 'array';
    items?: {
        type: ElicitationPrimitiveType;
        enum?: unknown[];
    };
    enum?: unknown[];
    title?: string;
    description?: string;
    default?: unknown;
}

/** The MCP-clean schema the card renders a form from, from `validate_elicitation_schema`. */
export interface ElicitationRequestedSchema {
    type: 'object';
    properties: Record<string, ElicitationFieldSchema>;
    required: string[];
}

/**
 * Our paging, kept beside the schema rather than inside it.
 *
 * Paging is SimpleChat's, not MCP's, so it lives in `ui_hints` and leaves `requested_schema`
 * MCP-clean. `order` is every field in ask order; `pages` groups them, one field per page by
 * default, which reads as an interview rather than a form.
 */
export interface ElicitationUiHints {
    order: string[];
    pages: string[][];
}

/** What the planner returns instead of a plan when it cannot plan without more information. */
export interface Elicitation {
    elicitation_id: string;
    contract_version: number;
    run_id: string;
    /** The turn this question belongs to, echoed from the request; see `OrchestrationPlan.turn_id`. */
    turn_id: string;
    revision: number;
    message: string;
    requested_schema: ElicitationRequestedSchema;
    ui_hints: ElicitationUiHints;
}

/**
 * The answer to an elicitation, in MCP's shape verbatim.
 *
 * `content` is only meaningful when `action` is `accept`; a decline or cancel carries `{}`,
 * because reading answers past the user's refusal would be a way to smuggle them in. The same
 * shape serves an answer typed into our card and one arriving from an MCP client.
 */
export interface ElicitationResponse {
    action: ElicitationAction;
    content: Record<string, unknown>;
}

/* -------------------------------------------------------------------------- */
/* Request bodies                                                              */
/* -------------------------------------------------------------------------- */

/**
 * The plan request.
 *
 * The message and conversation are the parts this client is sure of; the workspace/scope
 * context the planner needs to know which documents are in play is server-resolved and varies,
 * so the body stays open (`[key: string]: unknown`) rather than pinning fields the route
 * contract has not fixed. `elicitation_response` is present when re-planning after the user has
 * answered a question, and `revision` tracks how many times this turn has been re-planned.
 *
 * `turn_id` is minted by the client and sent so the server keys the turn on the same value the
 * client's store does; a re-plan of the same turn sends the same id. The server honours it and
 * echoes it back on the plan, rather than minting one of its own.
 */
export interface OrchestrationPlanRequest {
    message: string;
    conversation_id?: string | null;
    turn_id?: string;
    elicitation_response?: ElicitationResponse;
    revision?: number;
    approval_mode?: ApprovalMode;
    [key: string]: unknown;
}

/**
 * The run request: which plan to run, and the narrowing edits to apply first.
 *
 * `run_id` identifies the run; `plan_id` is sent alongside it for the server to match against
 * the plan it persisted. `edits` is applied server-side by `apply_plan_edits` before the run,
 * so the browser never assembles the plan that executes.
 */
export interface OrchestrationRunRequest {
    run_id: string;
    plan_id?: string;
    conversation_id?: string | null;
    edits?: PlanEdits;
    [key: string]: unknown;
}

/* -------------------------------------------------------------------------- */
/* Stream events                                                               */
/* -------------------------------------------------------------------------- */

/**
 * A frame from the plan stream.
 *
 * `thought` frames stream while the planner reasons; the stream then ends with exactly one of
 * `orchestration_plan` or `orchestration_elicitation`, each carrying `done: true`. An `error`
 * frame ends it too.
 */
export interface PlanStreamEvent {
    type?: 'thought' | 'orchestration_plan' | 'orchestration_elicitation' | string;
    plan?: OrchestrationPlan;
    elicitation?: Elicitation;
    done?: boolean;
    error?: string;
    [key: string]: unknown;
}

/**
 * A frame from the run stream.
 *
 * It is a `ChatStreamEvent` with three step fields added, because the run ends with a terminal
 * frame shaped like chat's own `done` payload (message id, model, citations and the rest) and
 * reusing that type is how the two stay in step. `orchestration_step` frames carry the live
 * status of a step as it runs; content deltas arrive exactly as they do in chat.
 */
export interface RunStreamEvent extends ChatStreamEvent {
    step_id?: string;
    status?: StepStatus;
    summary?: string;
}

/* -------------------------------------------------------------------------- */
/* Plan stream client                                                          */
/* -------------------------------------------------------------------------- */

export interface PlanStreamHandlers {
    /** A planner reasoning step arrived (`type: "thought"`). */
    onThought?: (event: ChatStreamEvent) => void;
    /**
     * The server named the conversation this turn belongs to (`type: "conversation_metadata"`).
     *
     * Emitted before any planning progress, and only when the server had to create the
     * conversation itself. It is the same event the chat stream carries, so the client adopts a
     * new conversation's id by the path it already knows rather than a second mechanism.
     */
    onConversationMetadata?: (event: ChatStreamEvent) => void;
    /** The planner produced a plan; the stream is over. */
    onPlan?: (plan: OrchestrationPlan) => void;
    /** The planner asked a question instead of planning; the stream is over. */
    onElicitation?: (elicitation: Elicitation) => void;
    /** An error frame arrived, or the transport failed. */
    onError?: (message: string) => void;
}

export interface PlanStreamResult {
    plan: OrchestrationPlan | null;
    elicitation: Elicitation | null;
    completed: boolean;
    cancelled: boolean;
    errored: boolean;
}

export interface RunStreamHandlers {
    /** A step changed status (`type: "orchestration_step"`). */
    onStep?: (event: RunStreamEvent) => void;
    /**
     * A run-time progress step arrived (`type: "thought"`).
     *
     * The run reports each step starting and finishing on the same `thought` event planning
     * uses, so the orchestration progress lane is fed by the same handler in both phases. These
     * frames carry a `content` summary that is progress, not answer text, which is why the reader
     * routes them here rather than appending them to the streamed answer.
     */
    onThought?: (event: ChatStreamEvent) => void;
    /** A content delta arrived. Append it to the answer being built. */
    onContent?: (delta: string, accumulated: string) => void;
    /** Terminal frame carrying the final assistant message and its metadata. */
    onDone?: (event: RunStreamEvent, accumulated: string) => void;
    /** The run was cancelled, either by the user or server-side. */
    onCancelled?: (event: RunStreamEvent, accumulated: string) => void;
    /** An error frame arrived, or the transport failed. */
    onError?: (message: string, event?: RunStreamEvent) => void;
}

export interface RunStreamResult {
    accumulated: string;
    completed: boolean;
    cancelled: boolean;
    errored: boolean;
}

export const ORCHESTRATION_PLAN_PATH = '/api/v2/orchestration/plan';
export const ORCHESTRATION_RUN_PATH = '/api/v2/orchestration/run';

/**
 * Open a POST SSE stream and hand back the response, or report why it could not open.
 *
 * A failure before the stream opens comes back as an ordinary JSON error, not an SSE frame, so
 * it is read here rather than in the framing loop. An abort before the response arrives is
 * returned as a plain null with no error reported, so the caller can record it as a cancellation
 * rather than a failure -- pressing Stop before the first byte is not an error.
 */
async function openOrchestrationStream(
    path: string,
    body: unknown,
    signal: AbortSignal | undefined,
    onError: (message: string) => void,
): Promise<Response | null> {
    let response: Response;
    try {
        response = await fetch(apiUrl(path), {
            method: 'POST',
            credentials: CREDENTIALS_MODE,
            headers: {
                'Content-Type': 'application/json',
                Accept: 'text/event-stream',
            },
            body: JSON.stringify(body),
            signal,
        });
    } catch (error) {
        if (signal?.aborted) {
            return null;
        }
        onError(error instanceof Error ? error.message : 'Network error');
        return null;
    }

    if (!response.ok || !response.body) {
        let message = `Request failed with status ${response.status}`;
        try {
            const payload = (await response.json()) as { error?: string };
            if (payload?.error) {
                message = payload.error;
            }
        } catch {
            /* Non-JSON error body; keep the status-based message. */
        }
        onError(message);
        return null;
    }

    return response;
}

/**
 * Plan a turn: POST the request, stream the planner's thoughts, and resolve once the planner
 * has committed to either a plan or a question.
 *
 * Aborting via `signal` resolves with `cancelled: true` rather than throwing, matching how the
 * chat transport treats a Stop press: it is a normal outcome, not a failure.
 */
export async function planOrchestration(
    body: OrchestrationPlanRequest,
    handlers: PlanStreamHandlers,
    signal?: AbortSignal,
): Promise<PlanStreamResult> {
    const result: PlanStreamResult = {
        plan: null,
        elicitation: null,
        completed: false,
        cancelled: false,
        errored: false,
    };

    const response = await openOrchestrationStream(
        ORCHESTRATION_PLAN_PATH,
        body,
        signal,
        (message) => {
            result.errored = true;
            handlers.onError?.(message);
        },
    );
    if (!response) {
        if (signal?.aborted) {
            result.cancelled = true;
        }
        return result;
    }

    const onEvent = (event: PlanStreamEvent): boolean => {
        if (typeof event.error === 'string' && event.error) {
            result.errored = true;
            handlers.onError?.(event.error);
            return true;
        }

        if (event.type === 'thought') {
            handlers.onThought?.(event as ChatStreamEvent);
            return false;
        }

        if (event.type === 'conversation_metadata') {
            // Not terminal: it precedes planning progress and merely names the conversation, so
            // the reader keeps going after handing it to the caller.
            handlers.onConversationMetadata?.(event as ChatStreamEvent);
            return false;
        }

        if (event.type === 'orchestration_plan') {
            result.plan = event.plan ?? null;
            result.completed = true;
            if (result.plan) {
                handlers.onPlan?.(result.plan);
            }
            return true;
        }

        if (event.type === 'orchestration_elicitation') {
            result.elicitation = event.elicitation ?? null;
            result.completed = true;
            if (result.elicitation) {
                handlers.onElicitation?.(result.elicitation);
            }
            return true;
        }

        // A done frame naming no recognised terminal still ends the stream, so a malformed
        // terminal does not leave the reader waiting for a frame that will never come.
        if (event.done) {
            result.completed = true;
            return true;
        }

        return false;
    };

    const outcome = await readSsePost<PlanStreamEvent>(response, onEvent, signal);

    if (outcome.aborted) {
        result.cancelled = true;
    } else if (outcome.transportError) {
        result.errored = true;
        handlers.onError?.(outcome.transportError.message);
    } else if (
        outcome.endedWithoutTerminal &&
        !result.completed &&
        !result.cancelled &&
        !result.errored
    ) {
        result.errored = true;
        handlers.onError?.('The plan stream ended before a plan arrived.');
    }

    return result;
}

/**
 * Run an approved plan: POST the run request, stream step status and content deltas, and
 * resolve on the terminal frame.
 *
 * The terminal frame is shaped like chat's `done` payload, so `onDone` receives the same
 * assistant-message metadata a chat completion would carry. As with the plan stream, an abort
 * resolves with `cancelled: true` rather than throwing.
 */
export async function runOrchestration(
    body: OrchestrationRunRequest,
    handlers: RunStreamHandlers,
    signal?: AbortSignal,
): Promise<RunStreamResult> {
    const result: RunStreamResult = {
        accumulated: '',
        completed: false,
        cancelled: false,
        errored: false,
    };

    const response = await openOrchestrationStream(
        ORCHESTRATION_RUN_PATH,
        body,
        signal,
        (message) => {
            result.errored = true;
            handlers.onError?.(message);
        },
    );
    if (!response) {
        if (signal?.aborted) {
            result.cancelled = true;
        }
        return result;
    }

    const onEvent = (event: RunStreamEvent): boolean => {
        if (typeof event.error === 'string' && event.error) {
            result.errored = true;
            handlers.onError?.(event.error, event);
            return true;
        }

        // A run streams progress on the same `thought` event planning uses, and those frames
        // carry a `content` summary of the step. Handed to the caller and returned here so that
        // summary drives the progress lane rather than being appended to the answer below as if
        // the model had written it.
        if (event.type === 'thought') {
            handlers.onThought?.(event);
            return false;
        }

        if (event.type === 'orchestration_step') {
            handlers.onStep?.(event);
            // A step frame carries neither content nor a terminal marker, but fall through
            // rather than return so a frame that ever carried both is still fully handled.
        }

        if (typeof event.content === 'string' && event.content.length > 0) {
            result.accumulated += event.content;
            handlers.onContent?.(event.content, result.accumulated);
        }

        if (event.done) {
            const wasCancelled =
                Boolean(event.cancelled) ||
                Boolean(event.canceled) ||
                event.type === 'cancelled' ||
                event.type === 'canceled';

            if (wasCancelled) {
                result.cancelled = true;
                handlers.onCancelled?.(event, result.accumulated);
            } else {
                result.completed = true;
                handlers.onDone?.(event, result.accumulated);
            }
            return true;
        }

        return false;
    };

    const outcome = await readSsePost<RunStreamEvent>(response, onEvent, signal);

    if (outcome.aborted) {
        result.cancelled = true;
    } else if (outcome.transportError) {
        result.errored = true;
        handlers.onError?.(outcome.transportError.message);
    } else if (
        outcome.endedWithoutTerminal &&
        !result.completed &&
        !result.cancelled &&
        !result.errored
    ) {
        result.errored = true;
        handlers.onError?.('The run ended unexpectedly.');
    }

    return result;
}
