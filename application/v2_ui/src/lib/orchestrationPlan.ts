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
    OrchestrationDeliverable,
    OrchestrationDeliverableKind,
    OrchestrationIntent,
    OrchestrationInputBinding,
    OrchestrationNamedInput,
    OrchestrationNamedOutput,
    OrchestrationPhase,
    OrchestrationPlan,
    OrchestrationPlanAction,
    OrchestrationPlanDocument,
    OrchestrationPlanInputs,
    OrchestrationPlanner,
    OrchestrationStep,
    OrchestrationRole,
    OrchestrationValidation,
    PlanComplexity,
    PlanEdits,
    PlanStatus,
    StepStatus,
} from './orchestration';
import { normalizeReasoningAdjustments } from './reasoning';

/**
 * The capability id of the answering step, from `TERMINAL_CAPABILITY_ID` in the registry.
 *
 * Legacy plans end with one of these. V2 instead selects prepared content with final_response.
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
    'waiting',
    'partial',
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
    'waiting',
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
export function normalizeModelBinding(raw: unknown): OrchestrationStep['model_binding'] {
    const binding = asRecord(raw);
    if (typeof binding.label !== 'string') return undefined;
    return {
        label: binding.label,
        reason: asString(binding.reason),
        profile_id: asString(binding.profile_id),
    };
}

export function normalizeStep(raw: unknown, index = 0, contractVersion = 1): OrchestrationStep {
    const source = asRecord(raw);
    return {
        model_binding: normalizeModelBinding(source.model_binding),
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
        // Carried through rather than re-derived from the capability menu. The validator
        // stamps each step with the phase it ordered the plan by, so this is the value the
        // run actually used; looking it up again client-side would disagree the moment a
        // capability is disabled after a plan was made.
        phase: asString(source.phase) || undefined,
        ...(contractVersion === 2 ? {
            role: asString(source.role) || undefined,
            inputs: normalizeNamedInputs(source.inputs),
            outputs: normalizeNamedOutputs(source.outputs),
            ...(Array.isArray(source.delivers) ? { delivers: asStringList(source.delivers) } : {}),
        } : {}),
    };
}

const DELIVERABLE_KINDS: readonly OrchestrationDeliverableKind[] = ['answer', 'file', 'image', 'chart', 'diagram'];

/**
 * The plan's deliverables with safe defaults, or undefined for plans that declared none.
 *
 * An entry without an id, a known kind, or a description cannot be shown or matched to a step,
 * so it is dropped rather than rendered as a blank row.
 */
export function normalizeDeliverables(raw: unknown): OrchestrationDeliverable[] | undefined {
    if (!Array.isArray(raw)) return undefined;
    const deliverables: OrchestrationDeliverable[] = [];
    for (const value of raw) {
        const entry = asRecord(value);
        const id = asString(entry.id).trim();
        const description = asString(entry.description).trim();
        const kind = entry.kind as OrchestrationDeliverableKind;
        if (!id || !description || !DELIVERABLE_KINDS.includes(kind)) continue;
        const quantity = entry.quantity;
        deliverables.push({
            id,
            kind,
            description,
            requested: entry.requested === 'suggested' ? 'suggested' : 'explicit',
            status: entry.status === 'unavailable' ? 'unavailable' : 'planned',
            ...(typeof entry.format === 'string' && entry.format.trim() ? { format: entry.format.trim() } : {}),
            ...(typeof quantity === 'number' && Number.isInteger(quantity) && quantity > 0 ? { quantity } : {}),
            ...(typeof entry.unavailable_reason === 'string' ? { unavailable_reason: entry.unavailable_reason } : {}),
            ...(typeof entry.unavailable_message === 'string' ? { unavailable_message: entry.unavailable_message } : {}),
            ...(entry.implicit === true ? { implicit: true } : {}),
        });
    }
    return deliverables;
}

const FILE_FORMAT_LABELS: Record<string, string> = {
    docx: 'Word document', pdf: 'PDF', pptx: 'PowerPoint deck', xlsx: 'Excel workbook',
    csv: 'CSV file', md: 'Markdown file', txt: 'Text file', json: 'JSON file',
    yaml: 'YAML file', xml: 'XML file',
};

/** "Word document", "3 images", "Chart": what a deliverable is, in the plan panel's words. */
export function deliverableKindLabel(deliverable: OrchestrationDeliverable): string {
    switch (deliverable.kind) {
        case 'file': {
            const format = deliverable.format ?? '';
            const label = FILE_FORMAT_LABELS[format] ?? (format ? `${format.toUpperCase()} file` : 'File');
            return deliverable.quantity && deliverable.quantity > 1 ? `${deliverable.quantity} × ${label}` : label;
        }
        case 'image':
            return deliverable.quantity && deliverable.quantity > 1 ? `${deliverable.quantity} images` : 'Image';
        case 'chart':
            return 'Chart';
        case 'diagram':
            return 'Diagram';
        default:
            return 'Answer';
    }
}

export type DeliverableState = 'planned' | 'unavailable' | 'running' | 'delivered' | 'not_delivered' | 'turned_off';

export interface DeliverableRow {
    deliverable: OrchestrationDeliverable;
    label: string;
    state: DeliverableState;
    stateLabel: string;
    /** The steps that produce it, by title, in plan order. */
    steps: string[];
    /** The server's explanation for an unavailable deliverable. */
    reason?: string;
}

const DELIVERABLE_STATE_LABELS: Record<DeliverableState, string> = {
    planned: 'Planned',
    unavailable: 'Not available',
    running: 'In progress',
    delivered: 'Delivered',
    not_delivered: 'Not delivered',
    turned_off: 'Turned off',
};

/**
 * Each declared deliverable with the state its producing steps imply.
 *
 * `statusOf` reports a step's live or saved status. A deliverable is delivered only when
 * every step that produces it completed; a step switched off in `edits` or in the plan turns
 * it off. The server's delivery notes remain the authority after a run; this is the preview.
 * The implicit answer of plans that declared nothing is left out.
 */
export function deliverableRows(
    plan: OrchestrationPlan,
    statusOf: (stepId: string) => StepStatus | undefined,
    edits?: PlanEdits,
): DeliverableRow[] {
    const disabled = new Set(edits?.disabled_step_ids ?? []);
    return (plan.deliverables ?? []).filter((deliverable) => !deliverable.implicit).map((deliverable) => {
        const producers = plan.steps.filter((step) => step.delivers?.includes(deliverable.id));
        const enabled = producers.filter((step) => step.enabled && !disabled.has(step.step_id));
        let state: DeliverableState = 'planned';
        if (deliverable.status === 'unavailable') {
            state = 'unavailable';
        } else if (producers.length > 0 && enabled.length === 0) {
            state = 'turned_off';
        } else {
            const statuses = enabled.map((step) => statusOf(step.step_id) ?? step.status);
            if (statuses.length > 0 && statuses.every((status) => status === 'completed')) {
                state = 'delivered';
            } else if (statuses.some((status) => status === 'failed' || status === 'skipped' || status === 'cancelled')) {
                state = 'not_delivered';
            } else if (statuses.some((status) => status === 'running' || status === 'waiting' || status === 'partial')) {
                state = 'running';
            }
        }
        return {
            deliverable,
            label: deliverableKindLabel(deliverable),
            state,
            stateLabel: DELIVERABLE_STATE_LABELS[state],
            steps: producers.map((step) => step.title || step.step_id),
            ...(deliverable.status === 'unavailable'
                ? { reason: deliverable.unavailable_message || 'This is not available here.' }
                : {}),
        };
    });
}

/** Whether an orchestrated answer's metadata lists images that were generated for it. */
export function hasGeneratedImages(orchestrationMetadata: unknown): boolean {
    const images = asRecord(orchestrationMetadata).generated_images;
    return Array.isArray(images) && images.some((image) => typeof asRecord(image).message_id === 'string');
}

/** Whether a named input binds a generated image rather than gathered information. */
export function bindsGeneratedImage(plan: OrchestrationPlan, binding: OrchestrationInputBinding | null): boolean {
    if (!binding?.step_id) return false;
    const producer = plan.steps.find((step) => step.step_id === binding.step_id);
    return Boolean(producer?.outputs?.some(
        (output) => output.name === binding.output_name && output.kind === 'image-asset-v1',
    ));
}

function normalizeInputBinding(raw: unknown): OrchestrationInputBinding | null {
    const source = asRecord(raw);
    if (source.version !== 'orchestration-input-binding-v1') return null;
    if (typeof source.step_id === 'string' && typeof source.output_name === 'string'
        && source.existing_result === null) {
        return {
            version: source.version, step_id: source.step_id,
            output_name: source.output_name, existing_result: null,
        };
    }
    if (typeof source.existing_result === 'string' && source.step_id === null && source.output_name === null) {
        return {
            version: source.version, step_id: null, output_name: null,
            existing_result: source.existing_result,
        };
    }
    return null;
}

function normalizeNamedInputs(raw: unknown): Record<string, OrchestrationNamedInput> {
    return Object.fromEntries(Object.entries(asRecord(raw)).map(([name, value]) => {
        const input = asRecord(value);
        return [name, {
            binding: normalizeInputBinding(input.binding),
            allow_partial: input.allow_partial === true,
            ...(input.optional === true ? { optional: true } : {}),
        }];
    }));
}

function normalizeNamedOutputs(raw: unknown): OrchestrationNamedOutput[] {
    if (!Array.isArray(raw)) return [];
    return raw.map((value) => {
        const output = asRecord(value);
        return {
            name: asString(output.name),
            kind: asString(output.kind),
            ...(typeof output.profile === 'string' ? { profile: output.profile } : {}),
            ...(output.schema !== undefined ? { schema: asRecord(output.schema) } : {}),
            ...(Array.isArray(output.columns) ? {
                columns: output.columns.map((value) => {
                    const column = asRecord(value);
                    return {
                        name: asString(column.name), value_type: asString(column.value_type),
                        nullable: column.nullable === true,
                    };
                }),
            } : {}),
        };
    });
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

const PLANNER_SOURCES: readonly OrchestrationPlanner['source'][] = ['selected', 'planner_setting', 'default'];

/** The model that wrote a plan, or undefined for plans saved before it was recorded. */
export function normalizePlanner(raw: unknown): OrchestrationPlanner | undefined {
    const source = asRecord(raw);
    const label = asString(source.label).trim();
    if (!label) return undefined;
    return {
        label,
        source: oneOf(source.source, PLANNER_SOURCES, 'default'),
        ...(typeof source.reasoning_effort === 'string' && source.reasoning_effort.trim()
            ? { reasoning_effort: source.reasoning_effort.trim() } : {}),
    };
}

const PLANNER_SOURCE_LABELS: Record<OrchestrationPlanner['source'], string> = {
    selected: 'the model you selected',
    planner_setting: "the administrator's planning model",
    default: 'the default model',
};

/** "Planned by gpt-5.4 (the model you selected)", or null when the plan does not say. */
export function describePlanner(plan: Pick<OrchestrationPlan, 'planner' | 'model_routing'>): string | null {
    if (!plan.planner) return null;
    const origin = PLANNER_SOURCE_LABELS[plan.planner.source];
    const routing = plan.model_routing === 'auto' ? '; each step uses its own Auto-routed model' : '';
    return `Planned by ${plan.planner.label} (${origin})${routing}`;
}

/** What an answer step may rely on, as the plan panel names it. */
export const KNOWLEDGE_BASIS_LABELS: Record<string, string> = {
    general_knowledge: 'General knowledge',
    sources: 'Gathered sources only',
    sources_and_general_knowledge: 'Gathered sources, plus general knowledge for stable facts',
};

/** Visual kinds a step was asked to author. */
export const VISUAL_KIND_LABELS: Record<string, string> = {
    chart: 'Chart',
    diagram: 'Mermaid diagram',
    image_proposal: 'Image proposals',
};

/**
 * Coerce a raw plan object into the typed shape, or return null when it is not a usable plan.
 *
 * Null rather than a throw, because a plan can arrive from an untrusted place -- a persisted
 * blob, a stream frame the server truncated -- and a caller adopting one wants to test the
 * result, not guard a try/catch. `outputs` passes through as-is: its shape is not fixed by the
 * schema module, so re-coercing it would risk discarding a structure the executor work being
 * built in parallel does commit to.
 */
export function normalizePlan(raw: unknown): OrchestrationPlan | null {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        return null;
    }
    const source = raw as Json;
    const contractVersion = typeof source.planner_contract_version === 'number'
        ? source.planner_contract_version : 1;

    const rawSteps: unknown[] = Array.isArray(source.steps) ? source.steps : [];
    const steps = rawSteps.map((step, index) => normalizeStep(step, index, contractVersion));

    return {
        plan_id: asString(source.plan_id),
        reasoning_adjustments: normalizeReasoningAdjustments(source.reasoning_adjustments),
        run_id: asString(source.run_id),
        edit_version: typeof source.edit_version === 'string' ? source.edit_version : undefined,
        turn_id: asString(source.turn_id),
        revision: typeof source.revision === 'number' ? source.revision : 0,
        conversation_id: asString(source.conversation_id),
        user_id: asString(source.user_id),
        planner_contract_version: contractVersion,
        intent: normalizeIntent(source.intent),
        assumptions: asStringList(source.assumptions),
        inputs: source.inputs !== undefined ? normalizeInputs(source.inputs) : undefined,
        steps,
        outputs: Array.isArray(source.outputs) ? (source.outputs as Json[]) : undefined,
        ...(contractVersion === 2 && source.final_response !== undefined
            ? { final_response: normalizeInputBinding(source.final_response) } : {}),
        ...(contractVersion === 2 && normalizeDeliverables(source.deliverables)
            ? { deliverables: normalizeDeliverables(source.deliverables) } : {}),
        ...(normalizePlanner(source.planner) ? { planner: normalizePlanner(source.planner) } : {}),
        ...(source.model_routing === 'auto' ? { model_routing: 'auto' as const } : {}),
        approval: normalizeApproval(source.approval),
        validation: normalizeValidation(source.validation),
        status: oneOf(source.status, PLAN_STATUSES, 'awaiting_approval'),
    };
}

/**
 * What the plan will act on.
 *
 * A document with no id is dropped rather than kept with an empty one: it could not be shown,
 * removed or acted on, so carrying it would only put a blank row on the approval card.
 */
function normalizeInputs(raw: unknown): OrchestrationPlanInputs {
    const source = asRecord(raw);
    const rawDocuments: unknown[] = Array.isArray(source.documents) ? source.documents : [];

    const documents: OrchestrationPlanDocument[] = [];
    for (const entry of rawDocuments) {
        const record = asRecord(entry);
        const documentId = asString(record.document_id);
        if (!documentId) {
            continue;
        }
        documents.push({
            document_id: documentId,
            // The server already falls back to the id when it cannot name a document, but a
            // truncated frame could still arrive without one, and a blank chip is worse than
            // an ugly one.
            display_name: asString(record.display_name) || documentId,
            selected_by_user: asBoolean(record.selected_by_user, false),
        });
    }

    const rawActions: unknown[] = Array.isArray(source.actions) ? source.actions : [];
    const actions: OrchestrationPlanAction[] = [];
    for (const entry of rawActions) {
        const record = asRecord(entry);
        const actionRef = asString(record.action_ref);
        if (!actionRef) {
            continue;
        }
        actions.push({
            action_ref: actionRef,
            display_name: asString(record.display_name) || 'Unnamed action',
            scope_label: asString(record.scope_label) || 'Unknown scope',
        });
    }

    return {
        required_capabilities: asStringList(source.required_capabilities),
        documents,
        actions: source.actions !== undefined ? actions : undefined,
        web: asBoolean(source.web, false),
        agent: source.agent !== undefined ? asRecord(source.agent) : undefined,
        model: source.model !== undefined ? asRecord(source.model) : undefined,
        prompt: source.prompt !== undefined ? asRecord(source.prompt) : undefined,
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
export function disableStep(edits: PlanEdits, step: OrchestrationStep, plan?: OrchestrationPlan): PlanEdits {
    if (step.capability_id === TERMINAL_CAPABILITY_ID) {
        return edits;
    }
    if (plan && stepDisableExplanation(plan, step.step_id)) return edits;
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
export function orderStepsForDisplay(steps: OrchestrationStep[], contractVersion = 1): OrchestrationStep[] {
    // V2 is already a stable topological order compiled by the server. A second sort could
    // move independent tasks and misrepresent the actual execution sequence.
    if (contractVersion === 2) return steps.slice();
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

const ROLE_LABELS: Record<OrchestrationRole, { label: string; progress: string }> = {
    gather: { label: 'Gather', progress: 'Gathering' },
    reason: { label: 'Reason', progress: 'Reasoning' },
    render: { label: 'Render', progress: 'Rendering' },
};
const LEGACY_PHASE_LABELS: Record<OrchestrationPhase, string> = {
    knowledge: 'Gathering knowledge', reasoning: 'Reasoning', output: 'Creating',
};

export function stepRoleLabel(step: OrchestrationStep, progress = false): string | null {
    const role = step.role;
    if (role !== 'gather' && role !== 'reason' && role !== 'render') return null;
    return ROLE_LABELS[role][progress ? 'progress' : 'label'];
}

export interface OrchestrationStepGroup {
    key: string;
    label: string | null;
    steps: Array<{ step: OrchestrationStep; number: number }>;
}

export function groupStepsForDisplay(
    plan: OrchestrationPlan,
    capabilities: readonly { id: string; phase?: string }[] = [],
): OrchestrationStepGroup[] {
    const ordered = orderStepsForDisplay(plan.steps, plan.planner_contract_version);
    if (plan.planner_contract_version === 2) {
        const groups: OrchestrationStepGroup[] = [];
        ordered.forEach((step, index) => {
            const label = stepRoleLabel(step);
            let group = groups[groups.length - 1];
            if (!group || group.label !== label) {
                group = { key: `${step.role ?? 'unclassified'}-${index}`, label, steps: [] };
                groups.push(group);
            }
            group.steps.push({ step, number: index + 1 });
        });
        return groups;
    }
    const phases = new Map(capabilities.map((capability) => [capability.id, capability.phase]));
    const buckets = new Map<string, OrchestrationStep[]>();
    for (const step of ordered) {
        const phase = step.phase ?? phases.get(step.capability_id) ?? '';
        const key = Object.hasOwn(LEGACY_PHASE_LABELS, phase) ? phase : '';
        buckets.set(key, [...(buckets.get(key) ?? []), step]);
    }
    let number = 0;
    return [...Object.entries(LEGACY_PHASE_LABELS), ['', null] as const].flatMap(([key, label]) => {
        const steps = buckets.get(key);
        return steps?.length ? [{
            key: key || 'unclassified', label,
            steps: steps.map((step) => ({ step, number: ++number })),
        }] : [];
    });
}

export function describeInputBinding(
    plan: OrchestrationPlan,
    binding: OrchestrationInputBinding | null,
): string {
    if (!binding) return 'Binding details unavailable';
    if (binding.existing_result) return `Retained result: ${binding.existing_result}`;
    const producer = plan.steps.find((step) => step.step_id === binding.step_id);
    const output = producer?.outputs?.find((output) => output.name === binding.output_name);
    return `Output ${binding.output_name} from ${producer?.title || binding.step_id}`
        + (output ? ` (${output.kind})` : '');
}

/** Even a disabled consumer keeps its bindings under the server's v2 validation contract. */
export function stepDisableExplanation(plan: OrchestrationPlan, stepId: string): string | null {
    if (plan.planner_contract_version !== 2) return null;
    const consumers = plan.steps.filter((step) =>
        step.depends_on.includes(stepId)
        || Object.values(step.inputs ?? {}).some((input) => input.binding?.step_id === stepId),
    ).map((step) => step.title || step.step_id);
    if (plan.final_response?.step_id === stepId) consumers.push('Final chat response');
    if (!consumers.length) return null;
    return `Required by: ${consumers.join('; ')}. Use Ask planner to change or remove these consumers first.`;
}

/** Explain broken edges without rewriting them. Kind, scope and source validation stay server-owned. */
export function planBindingIssues(plan: OrchestrationPlan, edits?: PlanEdits): string[] {
    if (plan.planner_contract_version !== 2) return [];
    const issues = new Set<string>();
    const disabled = new Set(edits?.disabled_step_ids ?? []);
    const requireProducer = (consumer: string, stepId: string) => {
        const producer = plan.steps.find((step) => step.step_id === stepId);
        if (!producer) issues.add(`${consumer} requires unavailable producer ${stepId}. Ask planner to revise the plan.`);
        else if (!producer.enabled || disabled.has(stepId)) {
            issues.add(`${consumer} requires ${producer.title || stepId}. Restore the producer or ask the planner to revise its consumers.`);
        }
        return producer;
    };
    const requireBinding = (consumer: string, binding: OrchestrationInputBinding | null) => {
        if (!binding) {
            issues.add(`${consumer} has unavailable binding details. Refresh the saved plan before running.`);
        } else if (binding.step_id) {
            const producer = requireProducer(consumer, binding.step_id);
            if (producer && !producer.outputs?.some((output) => output.name === binding.output_name)) {
                issues.add(`${consumer} requires missing output ${binding.output_name} from ${producer.title || binding.step_id}.`);
            }
        }
    };
    for (const step of plan.steps) {
        for (const dependency of step.depends_on) requireProducer(step.title || step.step_id, dependency);
        for (const [name, input] of Object.entries(step.inputs ?? {})) {
            requireBinding(`${step.title || step.step_id}, input ${name}`, input.binding);
        }
    }
    if (plan.final_response !== undefined) requireBinding('Final chat response', plan.final_response);
    return [...issues];
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
 * Active and terminal attempts cannot run again. Legacy plans retain their terminal answer;
 * v2 plans also require the declared producer edges to survive narrowing. The server still
 * authorizes and validates the saved plan before executing it.
 */
export function isPlanRunnable(plan: OrchestrationPlan, edits?: PlanEdits): boolean {
    if (isPlanTerminal(plan) || plan.status === 'running' || plan.status === 'waiting'
        || ![1, 2].includes(plan.planner_contract_version)) {
        return false;
    }
    if (plan.planner_contract_version === 2 && (!plan.validation.ok || planBindingIssues(plan, edits).length > 0)) {
        return false;
    }
    return enabledSteps(plan, edits).length > 0;
}
