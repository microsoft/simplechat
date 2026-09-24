// OrchestrationRunView.tsx
import { ReasoningAdjustmentNotice } from './ReasoningAdjustmentNotice';
import { OrchestrationRecoveryNotice } from './OrchestrationRecoveryNotice';
import { OrchestrationResultBindings } from './OrchestrationResultBindings';
import { OrchestrationExportCatalog } from './OrchestrationExportCatalog';
import { OrchestrationPlannedFile } from './OrchestrationPlannedFile';
import { OrchestrationOutputs } from './OrchestrationOutputs';
import { OrchestrationDeliverables } from './OrchestrationDeliverables';
// The full step list for one run or one pending plan, with the narrowing edits and live status.
//
// This is the detail the inline card deliberately omits. It reads the RAW plan, not the edited
// twin, so a step the user switched off still shows -- greyed, with its toggle off -- rather than
// vanishing, because a plan you can only narrow is far less alarming when you can see what you
// turned off and turn it back on. The edited twin is what the run request carries; this view is
// what lets a person decide what that twin should be.
//
// Editing is narrowing only, and the affordances here cannot express anything else: a step has an
// off switch but no "add", a document has a remove but the list cannot grow. `orchestrationPlan.ts`
// makes widening unrepresentable and the server enforces it again; this view simply never offers
// it. Editing is available only while the plan is still awaiting approval -- once it is approved or
// running or settled, `planRequiresApproval` is false and every control is read-only.

import { useMemo } from 'react';
import { clsx } from 'clsx';
import { Archive, FileText, Lock, RotateCcw, X } from 'lucide-react';
import { Toggle } from '../ui/primitives';
import {
    selectEdits,
    selectCanEditPlan,
    selectIsReadOnly,
    selectPlan,
    selectStepRuntime,
    selectPlanEditor,
    useOrchestrationStore,
    type StepRuntimeMap,
} from '../../stores/orchestrationStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    DOCUMENT_ARRAY_FIELDS,
    KNOWLEDGE_BASIS_LABELS,
    VISUAL_KIND_LABELS,
    describeInputBinding,
    describePlanner,
    groupStepsForDisplay,
    orderStepsForDisplay,
    planBindingIssues,
    planRequiresApproval,
    stepDisableExplanation,
    stepDocumentIds,
    stepRoleLabel,
    stepRemovableDocumentIds,
    TERMINAL_CAPABILITY_ID,
} from '../../lib/orchestrationPlan';
import type {
    CostClass,
    Json,
    OrchestrationPlan,
    PlanEdits,
    OrchestrationPlanAction,
    OrchestrationStep,
    StepStatus,
} from '../../lib/orchestration';
import { useDocumentTitles } from '../../lib/documentTitles';
import { plannedFileSpecification, type OrchestrationExportFormat } from '../../lib/orchestrationExports';

const PREVIEW_EDITS: PlanEdits = { disabled_step_ids: [], removed_document_ids: {} };
const PREVIEW_RUNTIME: StepRuntimeMap = {};

const statusTone: Record<StepStatus, string> = {
    pending: 'bg-surface-3 text-text-3',
    running: 'bg-accent-soft text-accent',
    waiting: 'bg-warn-soft text-warn',
    partial: 'bg-warn-soft text-warn',
    completed: 'bg-ok-soft text-ok',
    failed: 'bg-danger-soft text-danger',
    skipped: 'bg-surface-3 text-text-3',
    cancelled: 'bg-surface-3 text-text-3',
};

const costTone: Record<CostClass, string> = {
    low: 'text-text-3',
    medium: 'text-warn',
    high: 'text-danger',
};

/** A step argument key/value the run will use, minus the document fields shown as chips. */
function readableArguments(step: OrchestrationStep): Array<[string, string]> {
    const hidden = new Set<string>([
        ...DOCUMENT_ARRAY_FIELDS,
        'left_document_id',
        // Shown as its own chip, naming the step rather than repeating its id.
        'documents_from_step',
    ]);
    const entries: Array<[string, string]> = [];
    const args = step.arguments as Json;
    for (const [key, value] of Object.entries(args)) {
        // Action identity is named from validated inputs below, not from planner arguments.
        if (
            step.capability_id === 'action_invoke'
            && !((key === 'task' && typeof value === 'string') || key === 'visuals')
        ) {
            continue;
        }
        if (hidden.has(key)) {
            continue;
        }
        if (value === null || value === undefined || value === '') {
            continue;
        }
        if (Array.isArray(value) && value.length === 0) {
            continue;
        }
        if (key === 'knowledge_basis' && typeof value === 'string') {
            entries.push(['answer basis', KNOWLEDGE_BASIS_LABELS[value] ?? value]);
            continue;
        }
        if (key === 'visuals' && Array.isArray(value)) {
            entries.push(['visuals', value.map((kind) => VISUAL_KIND_LABELS[String(kind)] ?? String(kind)).join(', ')]);
            continue;
        }
        if (step.capability_id === 'generate_image' && (key === 'prompt' || key === 'title')) {
            entries.push([key === 'prompt' ? 'image prompt' : 'caption', String(value)]);
            continue;
        }
        const text =
            typeof value === 'string'
                ? value
                : typeof value === 'number' || typeof value === 'boolean'
                  ? String(value)
                  : JSON.stringify(value);
        entries.push([key, text]);
    }
    return entries;
}

export function OrchestrationRunView({
    conversationId,
    turnId,
    previewPlan,
    previewRuntime,
    exportCatalog,
}: {
    conversationId: string;
    turnId: string;
    /** A display-only plan; history previews never replace the live execution target. */
    previewPlan?: OrchestrationPlan;
    previewRuntime?: StepRuntimeMap;
    /** A supplied server catalog takes precedence over the saved run/editor projection. */
    exportCatalog?: readonly OrchestrationExportFormat[];
}) {
    const storedPlan = useOrchestrationStore((state) => selectPlan(state, conversationId, turnId));
    const storedEdits = useOrchestrationStore((state) => selectEdits(state, conversationId, turnId));
    const storedRuntime = useOrchestrationStore((state) =>
        selectStepRuntime(state, conversationId, turnId),
    );
    const canEdit = useOrchestrationStore((state) => selectCanEditPlan(state, conversationId, turnId));
    const editor = useOrchestrationStore((state) => selectPlanEditor(state, conversationId, turnId));
    const plan = previewPlan ?? storedPlan;
    const savedRun = useOrchestrationStore((state) => plan ? state.runRecovery[plan.run_id] : undefined);
    const edits = previewPlan ? PREVIEW_EDITS : storedEdits;
    const stepRuntime = previewPlan ? previewRuntime ?? PREVIEW_RUNTIME : storedRuntime;
    const disableStep = useOrchestrationStore((state) => state.disableStep);
    const enableStep = useOrchestrationStore((state) => state.enableStep);
    const removeDocument = useOrchestrationStore((state) => state.removeDocument);
    const restoreDocument = useOrchestrationStore((state) => state.restoreDocument);
    const readOnly = useOrchestrationStore((state) =>
        selectIsReadOnly(state, conversationId, turnId),
    );

    const orderedSteps = useMemo(
        () => (plan ? orderStepsForDisplay(plan.steps, plan.planner_contract_version) : []),
        [plan],
    );

    /**
     * Names for every document the plan touches, and which of them the user chose.
     *
     * The plan describes its own documents in `inputs`, resolved server-side from the composer's
     * selection and the relevance probe. Preferring that to a second lookup means a picked
     * document is named immediately rather than after three fetches, and it is the only source
     * for `selected_by_user` -- which is the distinction actually worth showing on a card whose
     * purpose is confirming the planner picked the right thing.
     */
    const planInputDocuments = useMemo(() => {
        const byId = new Map<string, { name: string; selectedByUser: boolean }>();
        for (const entry of plan?.inputs?.documents ?? []) {
            byId.set(entry.document_id, {
                name: entry.display_name,
                selectedByUser: entry.selected_by_user,
            });
        }
        return byId;
    }, [plan]);

    const planInputActions = useMemo(
        () => new Map<string, OrchestrationPlanAction>(
            (plan?.inputs?.actions ?? []).map((action) => [action.action_ref, action]),
        ),
        [plan],
    );

    /**
     * Names for anything the plan did not describe.
     *
     * Only ids the plan left unnamed are looked up, so the common case costs no request at all.
     * A step edited after planning, or a plan persisted before the server named its inputs, still
     * resolves rather than showing a uuid.
     */
    const planDocumentIds = useMemo(
        () =>
            [...new Set(orderedSteps.flatMap((step) => stepDocumentIds(step)))].filter(
                (id) => !(planInputDocuments.get(id)?.name),
            ),
        [orderedSteps, planInputDocuments],
    );
    const documentTitles = useDocumentTitles(planDocumentIds);

    const capabilities = useBootstrapStore((state) => state.data?.orchestration?.capabilities);

    /** Step titles by id, so a reference to another step can name it rather than show its id. */
    const stepTitles = useMemo(
        () => new Map(orderedSteps.map((step) => [step.step_id, step.title])),
        [orderedSteps],
    );

    const stepGroups = useMemo(
        () => plan ? groupStepsForDisplay(plan, capabilities) : [],
        [plan, capabilities],
    );

    if (!plan) {
        return (
            <p className="p-4 text-sm text-text-3">
                No plan to show for this turn yet.
            </p>
        );
    }

    // A stored plan is a record of what happened, not a proposal. Its status is adopted verbatim,
    // so one written down while it still awaited approval would otherwise offer to narrow steps
    // that were settled long ago, on a device that is not the one being asked.
    const editable = planRequiresApproval(plan) && !readOnly && !previewPlan && canEdit
        && !editor?.loading && !editor?.submitting && !editor?.state?.busy && !editor?.state?.pending;
    const disabledStepIds = new Set(edits.disabled_step_ids);
    const bindingIssues = planBindingIssues(plan, edits);
    const dependencyPlan = plan.planner_contract_version === 2;

    const renderStep = (step: OrchestrationStep, displayNumber: number) => {
        const isTerminal = step.capability_id === TERMINAL_CAPABILITY_ID;
        const roleLabel = dependencyPlan ? stepRoleLabel(step) : null;
        const disableExplanation = stepDisableExplanation(plan, step.step_id);
        const isAction = step.capability_id === 'action_invoke';
        const actionRef = (step.arguments as Record<string, unknown>).action_ref;
        const selectedAction = typeof actionRef === 'string' ? planInputActions.get(actionRef) : undefined;
        const willRun = step.enabled && !disabledStepIds.has(step.step_id);
        const status = stepRuntime[step.step_id]?.status ?? step.status;
        const summary = stepRuntime[step.step_id]?.summary ?? '';
        const removed = new Set(edits.removed_document_ids[step.step_id] ?? []);
        const removable = new Set(stepRemovableDocumentIds(step));
        const explicitDocuments = stepDocumentIds(step);
        const documents = step.capability_id === 'document_search' && explicitDocuments.length === 0
            ? [...planInputDocuments].filter(([, document]) => document.selectedByUser).map(([id]) => id)
            : explicitDocuments;
        const fileSpecification = dependencyPlan ? plannedFileSpecification(step) : null;
        const args = readableArguments(step).filter(([key]) =>
            !fileSpecification || !['file_name', 'output_format', 'profile', 'options'].includes(key),
        );
        // A step can defer its documents to whatever an earlier step finds, so it may have
        // none of its own to show.
        const documentsFromStep = String(
            (step.arguments as Record<string, unknown>).documents_from_step ?? '',
        ).trim();
        const documentsFromStepLabel =
            stepTitles.get(documentsFromStep) ?? 'the earlier step';

        return (
            <li
                key={step.step_id}
                data-step-id={step.step_id}
                aria-label={`Step ${displayNumber}: ${step.title}`}
                className={clsx(
                    'rounded-xl border border-edge p-3 transition-opacity',
                    willRun ? 'bg-surface-2' : 'bg-surface-sunken opacity-60',
                )}
            >
                <div className="flex items-start gap-2">
                    <span className="mt-0.5 shrink-0 font-mono text-xs text-text-3">
                        {displayNumber}
                    </span>
                    <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <span className="text-sm font-medium text-text-1">
                                {step.title}
                            </span>
                            <span className="rounded-full bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-text-3">
                                {isAction ? 'Use an action' : step.capability_id}
                            </span>
                            {roleLabel ? (
                                <span className="rounded-full border border-edge px-1.5 py-0.5 text-[11px] text-text-2">
                                    {roleLabel}
                                </span>
                            ) : null}
                            <span className={clsx('text-[11px]', costTone[step.estimated_cost])}>
                                {step.estimated_cost}
                            </span>
                            <span
                                className={clsx(
                                    'ml-auto rounded-full px-1.5 py-0.5 text-[11px] capitalize',
                                    statusTone[status],
                                )}
                            >
                                {status === 'running' && roleLabel ? stepRoleLabel(step, true) : status}
                            </span>
                            {stepRuntime[step.step_id]?.reused ? (
                                <span className="rounded-full bg-ok-soft px-2 py-0.5 text-[11px] text-ok">
                                    Reused saved result
                                </span>
                            ) : null}
                        </div>

                        {step.rationale ? (
                            <p className="mt-1 text-xs text-text-3">{step.rationale}</p>
                        ) : null}
                        {step.model_binding ? (
                            <p className="mt-2 text-xs text-text-2" data-testid="orchestration-step-model">
                                {stepRuntime[step.step_id]?.model_binding ? 'Execution model: ' : 'Planned model: '}
                                <strong>{stepRuntime[step.step_id]?.model_binding?.label || step.model_binding.label}</strong>
                                {' — '}{stepRuntime[step.step_id]?.model_binding?.reason || step.model_binding.reason}
                            </p>
                        ) : null}

                        {summary ? (
                            <p className="mt-1 text-xs text-text-2">{summary}</p>
                        ) : null}

                        {isAction ? (
                            <dl className="mt-2 text-xs" data-testid="orchestration-action-input">
                                <dt className="font-medium text-text-3">Action</dt>
                                <dd className="mt-0.5 break-words text-text-2">
                                    <span>{selectedAction?.display_name || 'Action details unavailable'}</span>
                                    {selectedAction ? (
                                        <span className="ml-2 text-text-3">({selectedAction.scope_label})</span>
                                    ) : null}
                                </dd>
                            </dl>
                        ) : null}

                        {args.length > 0 ? (
                            <dl className="mt-2 space-y-0.5">
                                {args.map(([key, value]) => (
                                    <div key={key} className="flex gap-1.5 text-xs">
                                        <dt className="shrink-0 font-mono text-text-3">
                                            {key}
                                        </dt>
                                        <dd className={clsx('min-w-0 text-text-2', dependencyPlan ? 'whitespace-pre-wrap break-all' : 'truncate')} title={value}>
                                            {value}
                                        </dd>
                                    </div>
                                ))}
                            </dl>
                        ) : null}

                        <OrchestrationPlannedFile plan={plan} step={step} />
                        <OrchestrationResultBindings plan={plan} step={step} />

                        {documents.length > 0 ? (
                            <ul className="mt-2 flex flex-wrap gap-1.5">
                                {documents.map((documentId) => {
                                    const isRemoved = removed.has(documentId);
                                    const canRemove =
                                        editable && removable.has(documentId);
                                    const planned = planInputDocuments.get(documentId);
                                    // The plan's own name first, then a lookup, then the id, so
                                    // a chip is never blank.
                                    const title =
                                        planned?.name ??
                                        documentTitles.get(documentId) ??
                                        documentId;
                                    // Worth distinguishing: a document the user picked is not a
                                    // decision the planner made, so it is not one they are being
                                    // asked to check.
                                    const chosenByUser = planned?.selectedByUser ?? false;
                                    return (
                                        <li
                                            key={documentId}
                                            className={clsx(
                                                'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]',
                                                isRemoved
                                                    ? 'border-edge text-text-3 line-through'
                                                    : chosenByUser
                                                      ? 'border-accent/50 bg-accent/5 text-text-2'
                                                      : 'border-edge-strong text-text-2',
                                            )}
                                        >
                                            <FileText size={10} className="shrink-0" />
                                            <span
                                                className="max-w-[12rem] truncate"
                                                title={
                                                    [
                                                        title === documentId ? null : title,
                                                        documentId,
                                                        chosenByUser
                                                            ? 'You chose this document'
                                                            : 'Chosen by the planner',
                                                    ]
                                                        .filter(Boolean)
                                                        .join(' · ')
                                                }
                                            >
                                                {title}
                                            </span>
                                            {chosenByUser && !isRemoved ? (
                                                <span className="text-[10px] text-text-3">
                                                    yours
                                                </span>
                                            ) : null}
                                            {isRemoved && editable ? (
                                                <button
                                                    type="button"
                                                    onClick={() =>
                                                        restoreDocument(
                                                            conversationId,
                                                            turnId,
                                                            step.step_id,
                                                            documentId,
                                                        )
                                                    }
                                                    aria-label={`Restore document ${documentId}`}
                                                    className="text-accent hover:text-accent-hover"
                                                >
                                                    <RotateCcw size={11} />
                                                </button>
                                            ) : canRemove ? (
                                                <button
                                                    type="button"
                                                    onClick={() =>
                                                        removeDocument(
                                                            conversationId,
                                                            turnId,
                                                            step,
                                                            documentId,
                                                        )
                                                    }
                                                    aria-label={`Remove document ${documentId} from this step`}
                                                    className="text-text-3 hover:text-danger"
                                                >
                                                    <X size={11} />
                                                </button>
                                            ) : null}
                                        </li>
                                    );
                                })}
                            </ul>
                        ) : null}

                        {documentsFromStep ? (
                            // A step reading whatever an earlier one finds has no documents
                            // to list yet. Saying so is more honest than showing nothing,
                            // which reads as "this step touches no documents at all".
                            <p className="mt-2 inline-flex items-center gap-1 rounded-full border border-dashed border-edge-strong px-2 py-0.5 text-[11px] text-text-3">
                                <FileText size={10} className="shrink-0" />
                                Whatever {documentsFromStepLabel} finds
                            </p>
                        ) : null}

                        <div className="mt-2">
                            {isTerminal ? (
                                <span className="inline-flex items-center gap-1 text-[11px] text-text-3">
                                    <Lock size={11} />
                                    Always runs
                                </span>
                            ) : editable ? (
                                <Toggle
                                    checked={willRun}
                                    disabled={dependencyPlan && Boolean((willRun && disableExplanation) || !step.enabled)}
                                    onChange={(next) =>
                                        next
                                            ? enableStep(conversationId, turnId, step.step_id)
                                            : disableStep(conversationId, turnId, step)
                                    }
                                    label={dependencyPlan ? `Run ${step.title}` : willRun ? 'Will run' : 'Skipped'}
                                    description={dependencyPlan
                                        ? !step.enabled ? 'Disabled in the saved plan. Use Ask planner to change it.'
                                        : willRun ? disableExplanation ?? undefined : 'Explicitly skipped in this plan edit.'
                                        : undefined}
                                />
                            ) : (
                                <span className="text-[11px] text-text-3">
                                    {willRun ? 'Will run' : 'Skipped'}
                                </span>
                            )}
                        </div>
                    </div>
                </div>
            </li>
        );
    };

    return (
        <div className="space-y-3 p-3">
            <ReasoningAdjustmentNotice adjustments={plan.reasoning_adjustments} />
            <OrchestrationRecoveryNotice
                conversationId={conversationId} runId={plan.run_id} plan={plan} status={plan.status}
            />
            {readOnly && !previewPlan ? (
                <p className="flex items-center gap-1.5 rounded-lg border border-edge bg-surface-2 px-2 py-1.5 text-[11px] text-text-3">
                    <Archive size={12} className="shrink-0" />
                    A record of a run from this conversation. It cannot be changed or re-run.
                </p>
            ) : null}
            <div>
                <p className="text-sm font-medium text-text-1">{plan.intent.summary}</p>
                {describePlanner(plan) ? (
                    <p className="mt-1 text-xs text-text-3" data-testid="orchestration-plan-planner">
                        {describePlanner(plan)}
                    </p>
                ) : null}
                {dependencyPlan ? (
                    <p className="mt-1 text-xs text-text-3">
                        Tasks follow their dependencies in the saved execution order. Roles can repeat.
                    </p>
                ) : null}
                {plan.assumptions.length > 0 ? (
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-text-3">
                        {plan.assumptions.map((assumption, index) => (
                            <li key={index}>{assumption}</li>
                        ))}
                    </ul>
                ) : null}
            </div>

            <OrchestrationDeliverables
                plan={plan} edits={edits}
                statusOf={(stepId) => stepRuntime[stepId]?.status}
            />

            {dependencyPlan && plan.final_response !== undefined ? (
                <p className="break-words text-xs text-text-2" aria-label="Final chat response binding">
                    <strong>Final chat response:</strong> {describeInputBinding(plan, plan.final_response)}
                </p>
            ) : null}
            {bindingIssues.length ? (
                <div role="alert" className="alert rounded-xl border border-warn/30 bg-warn-soft p-3 text-xs text-warn">
                    <p className="font-medium">Review required inputs before running</p>
                    <ul className="mt-1 list-disc space-y-1 pl-4">
                        {bindingIssues.map((issue) => <li key={issue}>{issue}</li>)}
                    </ul>
                </div>
            ) : null}
            {dependencyPlan ? (
                <OrchestrationExportCatalog
                    catalog={exportCatalog ?? (editor?.state?.plan.run_id === plan.run_id
                        ? editor.state.export_catalog : undefined) ?? savedRun?.export_catalog}
                    conversationId={conversationId} runId={plan.run_id}
                />
            ) : null}
            <OrchestrationOutputs conversationId={conversationId} runId={plan.run_id} />

            {stepGroups.map((group) => (
                <section key={group.key} className="space-y-2">
                    {group.label ? (
                        <h3 className="px-0.5 text-[11px] font-semibold uppercase tracking-wide text-text-3">
                            {group.label}
                        </h3>
                    ) : null}
                    <ol className="space-y-2" start={group.steps[0].number}>
                        {group.steps.map(({ step, number }) => renderStep(step, number))}
                    </ol>
                </section>
            ))}
        </div>
    );
}
