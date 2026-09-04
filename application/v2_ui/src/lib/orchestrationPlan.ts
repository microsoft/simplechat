// orchestrationPlan.ts
// Reading a plan for display, and narrowing it before it runs.
//
// This module imports nothing but types. The store, the plan card and any Node test that
// exercises the edit rules all read it, and a dependency on React, zustand or the API client in
// any of those directions would make the rules untestable on their own -- the same discipline
// `imageProposalTracking.ts` keeps, and for the same reason.
//
// The one rule worth stating up front: EDITS NARROW, THEY NEVER WIDEN. A user may switch a step
// off or drop a document from one; they may not add a step or a document. That is not a UI
// nicety -- `apply_plan_edits` enforces it server-side because a plan the browser widened would
// never have passed the planner's reasoning or the authorization check that followed it. The
// edit API below is shaped so widening is *unrepresentable*: every operation only ever adds to
// the "disabled" or "removed" sets, and the only way back is to clear the user's own narrowing.

import type {
    ApprovalMode,
    ApprovalState,
    CostClass,
    Json,
    OrchestrationApproval,
    OrchestrationIntent,
    OrchestrationPlan,
    OrchestrationStep,
    OrchestrationValidation,
    PlanComplexity,
    PlanEdits,
    PlanStatus,
    StepStatus,
} from './orchestration';

/**
 * The capability id of the answering step, from `TERMINAL_CAPABILITY_ID` in the registry.
 *
 * Every plan ends with exactly one of these, and it is never narrowable: `apply_plan_edits`
 * skips it, so a user cannot disable the step that writes the answer or empty its inputs.
 */
export const TERMINAL_CAPABILITY_ID = 'respond';

/**
 * The argument keys whose document lists a user may prune, from `apply_plan_edits`.
 *
 * `left_document_id` is deliberately absent: it is a single document, not a list, and removing
 * it would empty the step rather than narrow it -- which is re-planning, not editing.
 */
export const DOCUMENT_ARRAY_FIELDS = ['document_ids', 'right_document_ids'] as const;

const STEP_STATUSES: readonly StepStatus[] = [
    'pending',
    'running',
    'completed',
    'failed',
    'skipped',
    'cancelled',
];

const PLAN_STATUSES: readonly PlanStatus[] = [
    'draft',
    'awaiting_approval',
    'approved',
    'running',
    'completed',
    'failed',
    'cancelled',
    'superseded',
];

/** Plan statuses past which no run will start, from `TERMINAL_PLAN_STATUSES`. */
export const TERMINAL_PLAN_STATUSES: readonly PlanStatus[] = [
    'completed',
    'failed',
    'cancelled',
    'superseded',
];

const APPROVAL_MODES: readonly ApprovalMode[] = ['manual', 'timed', 'auto'];
const APPROVAL_STATES: readonly ApprovalState[] = [
    'pending',
    'approved',
    'rejected',
    'expired',
];
const COMPLEXITIES: readonly PlanComplexity[] = ['trivial', 'simple', 'complex'];
const COST_CLASSES: readonly CostClass[] = ['low', 'medium', 'high'];

/* -------------------------------------------------------------------------- */
/* Coercion                                                                    */
/* -------------------------------------------------------------------------- */

function asString(value: unknown, fallback = ''): string {
    return typeof value === 'string' ? value : fallback;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
    return typeof value === 'boolean' ? value : fallback;
}

function asRecord(value: unknown): Json {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {};
}

/** Non-empty trimmed strings, order preserved and duplicates dropped. Mirrors `_string_list`. */
function asStringList(value: unknown): string[] {
    if (!Array.isArray(value)) {
        return [];
    }
    const seen = new Set<string>();
    const out: string[] = [];
    for (const item of value) {
        if (typeof item !== 'string') {
            continue;
        }
        const text = item.trim();
        if (!text || seen.has(text)) {
            continue;
        }
        seen.add(text);
        out.push(text);
    }
    return out;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
    return typeof value === 'string' && (allowed as readonly string[]).includes(value)
        ? (value as T)
        : fallback;
}

/* -------------------------------------------------------------------------- */
/* Normalisation                                                               */
/* -------------------------------------------------------------------------- */

/**
 * Coerce a raw step into the typed shape with safe defaults.
 *
 * The server validates before it sends, so this is defence rather than repair: a persisted or
 * partial step still arrives as something the card can render, with a status the runtime can
 * key on, rather than as `undefined` reaching a component mid-run.
 */
export function normalizeStep(raw: unknown, index = 0): OrchestrationStep {
    const source = asRecord(raw);
    return {
        step_id: asString(source.step_id) || `step_${index + 1}`,
        capability_id: asString(source.capability_id),
        title: asString(source.title),
        rationale: asString(source.rationale),
        arguments: asRecord(source.arguments),
        depends_on: asStringList(source.depends_on),
        optional: asBoolean(source.optional, false),
        enabled: asBoolean(source.enabled, true),
        estimated_cost: oneOf(source.estimated_cost, COST_CLASSES, 'medium'),
        status: oneOf(source.status, STEP_STATUSES, 'pending'),
    };
}

function normalizeIntent(raw: unknown): OrchestrationIntent {
    const source = asRecord(raw);
    const confidence = source.confidence;
    return {
        summary: asString(source.summary),
        complexity: oneOf(source.complexity, COMPLEXITIES, 'simple'),
        confidence: typeof confidence === 'number' ? confidence : null,
    };
}

function normalizeApproval(raw: unknown): OrchestrationApproval {
    const source = asRecord(raw);
    const timeout = source.timeout_seconds;
    return {
        mode: oneOf(source.mode, APPROVAL_MODES, 'manual'),
        timeout_seconds: typeof timeout === 'number' && Number.isFinite(timeout) ? timeout : 10,
        state: oneOf(source.state, APPROVAL_STATES, 'pending'),
        approved_at: typeof source.approved_at === 'string' ? source.approved_at : null,
        approved_by: typeof source.approved_by === 'string' ? source.approved_by : null,
        edited: asBoolean(source.edited, false),
    };
}

function normalizeValidation(raw: unknown): OrchestrationValidation {
    const source = asRecord(raw);
    return {
        ok: asBoolean(source.ok, true),
        errors: asStringList(source.errors),
        repairs: asStringList(source.repairs),
    };
}

/**
 * Coerce a raw plan object into the typed shape, or return null when it is not a usable plan.
 *
 * Null rather than a throw, because a plan can arrive from an untrusted place -- a persisted
 * blob, a stream frame the server truncated -- and a caller adopting one wants to test the
 * result, not guard a try/catch. `inputs` and `outputs` pass through as-is: their shape is not
 * fixed by the schema module, so re-coercing them would risk discarding a structure the planner
 * work being built in parallel does commit to.
 */
export function normalizePlan(raw: unknown): OrchestrationPlan | null {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        return null;
    }
    const source = raw as Json;

    const rawSteps: unknown[] = Array.isArray(source.steps) ? source.steps : [];
    const steps = rawSteps.map((step, index) => normalizeStep(step, index));

    return {
        plan_id: asString(source.plan_id),
        run_id: asString(source.run_id),
        turn_id: asString(source.turn_id),
        revision: typeof source.revision === 'number' ? source.revision : 0,
        conversation_id: asString(source.conversation_id),
        user_id: asString(source.user_id),
        planner_contract_version:
            typeof source.planner_contract_version === 'number'
                ? source.planner_contract_version
                : 1,
        intent: normalizeIntent(source.intent),
        assumptions: asStringList(source.assumptions),
        inputs: source.inputs !== undefined ? asRecord(source.inputs) : undefined,
        steps,
        outputs: Array.isArray(source.outputs) ? (source.outputs as Json[]) : undefined,
        approval: normalizeApproval(source.approval),
        validation: normalizeValidation(source.validation),
        status: oneOf(source.status, PLAN_STATUSES, 'awaiting_approval'),
    };
}

/* -------------------------------------------------------------------------- */
/* Documents on a step                                                         */
/* -------------------------------------------------------------------------- */

function argumentDocumentIds(step: OrchestrationStep, field: string): string[] {
    return asStringList((step.arguments as Json)[field]);
}

/**
 * The document ids a user is allowed to prune from a step.
 *
 * Only the list-valued fields, in the order `apply_plan_edits` reads them, and de-duplicated
 * across the two so a document named in both is offered once.
 */
export function stepRemovableDocumentIds(step: OrchestrationStep): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const field of DOCUMENT_ARRAY_FIELDS) {
        for (const id of argumentDocumentIds(step, field)) {
            if (!seen.has(id)) {
                seen.add(id);
                out.push(id);
            }
        }
    }
    return out;
}

/**
 * Every document id a step reads, including the single `left_document_id` a compare step pins.
 *
 * For display of what a step touches; the single field is shown but cannot be removed, which is
 * why the removable set above excludes it.
 */
export function stepDocumentIds(step: OrchestrationStep): string[] {
    const ids = stepRemovableDocumentIds(step);
    const left = asString((step.arguments as Json).left_document_id);
    if (left && !ids.includes(left)) {
        ids.push(left);
    }
    return ids;
}

/* -------------------------------------------------------------------------- */
/* Edits (narrowing only)                                                      */
/* -------------------------------------------------------------------------- */

/** A fresh, empty edit set: nothing disabled, nothing removed. */
export function emptyPlanEdits(): PlanEdits {
    return { disabled_step_ids: [], removed_document_ids: {} };
}

/** Whether the user has narrowed the plan at all. */
export function planEditsAreEmpty(edits: PlanEdits): boolean {
    if (edits.disabled_step_ids.length > 0) {
        return false;
    }
    return Object.values(edits.removed_document_ids).every((ids) => ids.length === 0);
}

export function isStepDisabled(edits: PlanEdits, stepId: string): boolean {
    return edits.disabled_step_ids.includes(stepId);
}

export function isDocumentRemoved(
    edits: PlanEdits,
    stepId: string,
    documentId: string,
): boolean {
    return (edits.removed_document_ids[stepId] ?? []).includes(documentId);
}

/**
 * Switch a step off.
 *
 * The terminal step is never disableable, so a request to disable it is ignored rather than
 * producing an edit the server will silently drop -- keeping the client's idea of the edit set
 * identical to the one `apply_plan_edits` will honour.
 */
export function disableStep(edits: PlanEdits, step: OrchestrationStep): PlanEdits {
    if (step.capability_id === TERMINAL_CAPABILITY_ID) {
        return edits;
    }
    if (edits.disabled_step_ids.includes(step.step_id)) {
        return edits;
    }
    return {
        ...edits,
        disabled_step_ids: [...edits.disabled_step_ids, step.step_id],
    };
}

/** Clear a step's disable, restoring the plan's own default for it. Not a widening. */
export function enableStep(edits: PlanEdits, stepId: string): PlanEdits {
    if (!edits.disabled_step_ids.includes(stepId)) {
        return edits;
    }
    return {
        ...edits,
        disabled_step_ids: edits.disabled_step_ids.filter((id) => id !== stepId),
    };
}

export function setStepEnabled(
    edits: PlanEdits,
    step: OrchestrationStep,
    enabled: boolean,
): PlanEdits {
    return enabled ? enableStep(edits, step.step_id) : disableStep(edits, step);
}

/**
 * Drop a document from a step.
 *
 * Only a document the step actually reads through a removable field can be dropped; anything
 * else is ignored, so the removed set can never name a document the plan did not contain and so
 * cannot be read as an instruction to add one.
 */
export function removeDocumentFromStep(
    edits: PlanEdits,
    step: OrchestrationStep,
    documentId: string,
): PlanEdits {
    if (!stepRemovableDocumentIds(step).includes(documentId)) {
        return edits;
    }
    const current = edits.removed_document_ids[step.step_id] ?? [];
    if (current.includes(documentId)) {
        return edits;
    }
    return {
        ...edits,
        removed_document_ids: {
            ...edits.removed_document_ids,
            [step.step_id]: [...current, documentId],
        },
    };
}

/** Put a document back, clearing the user's own removal of it. Not a widening. */
export function restoreDocumentToStep(
    edits: PlanEdits,
    stepId: string,
    documentId: string,
): PlanEdits {
    const current = edits.removed_document_ids[stepId] ?? [];
    if (!current.includes(documentId)) {
        return edits;
    }
    const remaining = current.filter((id) => id !== documentId);
    const nextRemoved = { ...edits.removed_document_ids };
    if (remaining.length > 0) {
        nextRemoved[stepId] = remaining;
    } else {
        delete nextRemoved[stepId];
    }
    return { ...edits, removed_document_ids: nextRemoved };
}

/** The documents a step will still read once the user's removals are applied. */
export function remainingStepDocumentIds(
    step: OrchestrationStep,
    edits: PlanEdits,
): string[] {
    const removed = new Set(edits.removed_document_ids[step.step_id] ?? []);
    return stepRemovableDocumentIds(step).filter((id) => !removed.has(id));
}

/**
 * Apply the user's edits to a plan, producing a new plan for preview.
 *
 * A faithful client-side twin of `apply_plan_edits`, so the card can show the effect of a
 * narrowing before the run request carries the same edits to the server that will apply them
 * for real. The terminal step is skipped, only the list-valued document fields are pruned, and
 * `approval.edited` is set the moment anything actually changed. The input is never mutated.
 */
export function applyPlanEdits(plan: OrchestrationPlan, edits: PlanEdits): OrchestrationPlan {
    const disabled = new Set(edits.disabled_step_ids);
    let edited = false;

    const steps = plan.steps.map((step) => {
        if (step.capability_id === TERMINAL_CAPABILITY_ID) {
            return step;
        }

        let next = step;

        if (disabled.has(step.step_id) && next.enabled) {
            next = { ...next, enabled: false };
            edited = true;
        }

        const drop = new Set(edits.removed_document_ids[step.step_id] ?? []);
        if (drop.size > 0) {
            let argumentsChanged = false;
            const nextArguments: Json = { ...next.arguments };
            for (const field of DOCUMENT_ARRAY_FIELDS) {
                const value = nextArguments[field];
                if (!Array.isArray(value)) {
                    continue;
                }
                const kept = value.filter((id) => !(typeof id === 'string' && drop.has(id)));
                if (kept.length !== value.length) {
                    nextArguments[field] = kept;
                    argumentsChanged = true;
                }
            }
            if (argumentsChanged) {
                next = { ...next, arguments: nextArguments };
                edited = true;
            }
        }

        return next;
    });

    if (!edited) {
        return plan;
    }

    return {
        ...plan,
        steps,
        approval: { ...plan.approval, edited: true },
    };
}

/* -------------------------------------------------------------------------- */
/* Ordering for display                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Order steps so a step is drawn after the steps it depends on.
 *
 * A depth-first topological sort mirroring `_order_steps`: a dependency on a step that is not in
 * the list is ignored, and a cycle is tolerated rather than looped on -- a back-edge is simply
 * skipped, which leaves a defensible order instead of hanging. The server de-cycles the plan it
 * sends, so this is belt-and-braces for a persisted or hand-built plan.
 */
export function orderStepsForDisplay(steps: OrchestrationStep[]): OrchestrationStep[] {
    const byId = new Map(steps.map((step) => [step.step_id, step]));
    const permanent = new Set<string>();
    const temporary = new Set<string>();
    const resolved: OrchestrationStep[] = [];

    const visit = (stepId: string): void => {
        if (permanent.has(stepId) || temporary.has(stepId)) {
            return;
        }
        const step = byId.get(stepId);
        if (!step) {
            return;
        }
        temporary.add(stepId);
        for (const dependency of step.depends_on) {
            if (byId.has(dependency)) {
                visit(dependency);
            }
        }
        temporary.delete(stepId);
        permanent.add(stepId);
        resolved.push(step);
    };

    for (const step of steps) {
        visit(step.step_id);
    }

    return resolved;
}

/* -------------------------------------------------------------------------- */
/* Summary and runnability                                                     */
/* -------------------------------------------------------------------------- */

/** The compact description a collapsed card or a ledger row shows. Mirrors `summarize_plan`. */
export interface PlanSummary {
    run_id: string;
    plan_id: string;
    intent_summary: string;
    /** Count of steps that will actually run, the terminal answering step included. */
    step_count: number;
    /** Distinct capabilities the enabled steps use, in first-seen order. */
    capabilities_used: string[];
    status: PlanStatus;
}

/**
 * The steps that will run once `edits` are applied.
 *
 * Both gates are honoured: a step the plan itself left disabled, and a step the user disabled
 * through `edits`. Callers pass the current edit set to see the plan as it will actually run.
 */
export function enabledSteps(
    plan: OrchestrationPlan,
    edits?: PlanEdits,
): OrchestrationStep[] {
    const disabled = edits ? new Set(edits.disabled_step_ids) : null;
    return plan.steps.filter((step) => {
        if (!step.enabled) {
            return false;
        }
        if (disabled && step.capability_id !== TERMINAL_CAPABILITY_ID) {
            return !disabled.has(step.step_id);
        }
        return true;
    });
}

/** Summarise a plan for the collapsed card, honouring any edits the user has made. */
export function summarizePlan(plan: OrchestrationPlan, edits?: PlanEdits): PlanSummary {
    const steps = enabledSteps(plan, edits);
    const capabilities: string[] = [];
    const seen = new Set<string>();
    for (const step of steps) {
        if (step.capability_id && !seen.has(step.capability_id)) {
            seen.add(step.capability_id);
            capabilities.push(step.capability_id);
        }
    }
    return {
        run_id: plan.run_id,
        plan_id: plan.plan_id,
        intent_summary: plan.intent.summary,
        step_count: steps.length,
        capabilities_used: capabilities,
        status: plan.status,
    };
}

/** Whether the plan has finished, one way or another, from `TERMINAL_PLAN_STATUSES`. */
export function isPlanTerminal(plan: OrchestrationPlan): boolean {
    return TERMINAL_PLAN_STATUSES.includes(plan.status);
}

/** Whether approval has been granted, whether by the user or by auto mode on arrival. */
export function isPlanApproved(plan: OrchestrationPlan): boolean {
    return plan.approval.state === 'approved' || plan.status === 'approved';
}

/** Whether the plan is still waiting for the user to approve it. */
export function isPlanAwaitingApproval(plan: OrchestrationPlan): boolean {
    return plan.status === 'awaiting_approval' && plan.approval.state === 'pending';
}

/**
 * Whether the plan still needs a human before it runs.
 *
 * Auto mode is pre-approved on arrival, so it never does; manual and timed both wait, timed
 * included, because the countdown belongs to the browser -- the server leaves a timed plan
 * pending precisely so the user can stop the clock.
 */
export function planRequiresApproval(plan: OrchestrationPlan): boolean {
    return plan.approval.mode !== 'auto' && plan.approval.state === 'pending';
}

/**
 * Whether a run could be started from this plan as edited.
 *
 * A plan that has already reached a terminal status cannot run again; otherwise it is runnable
 * as long as at least one step survives the edits -- which the terminal answering step always
 * does, so a plan narrowed to nothing but its answer is still runnable.
 */
export function isPlanRunnable(plan: OrchestrationPlan, edits?: PlanEdits): boolean {
    if (isPlanTerminal(plan)) {
        return false;
    }
    return enabledSteps(plan, edits).length > 0;
}
