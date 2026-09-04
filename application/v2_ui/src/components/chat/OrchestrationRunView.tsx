// OrchestrationRunView.tsx
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
import { FileText, Lock, RotateCcw, X } from 'lucide-react';
import { Toggle } from '../ui/primitives';
import {
    selectEdits,
    selectPlan,
    selectStepRuntime,
    useOrchestrationStore,
} from '../../stores/orchestrationStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    DOCUMENT_ARRAY_FIELDS,
    orderStepsForDisplay,
    planRequiresApproval,
    stepDocumentIds,
    stepRemovableDocumentIds,
    TERMINAL_CAPABILITY_ID,
} from '../../lib/orchestrationPlan';
import { ORCHESTRATION_PHASES } from '../../lib/orchestration';
import type {
    CostClass,
    Json,
    OrchestrationPhase,
    OrchestrationStep,
    StepStatus,
} from '../../lib/orchestration';

const statusTone: Record<StepStatus, string> = {
    pending: 'bg-surface-3 text-text-3',
    running: 'bg-accent-soft text-accent',
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

/** The heading shown above each phase's steps. Presentation copy, so it lives with the view. */
const phaseLabels: Record<OrchestrationPhase, string> = {
    knowledge: 'Gathering knowledge',
    reasoning: 'Reasoning',
    output: 'Creating',
};

/** A step argument key/value the run will use, minus the document fields shown as chips. */
function readableArguments(step: OrchestrationStep): Array<[string, string]> {
    const hidden = new Set<string>([...DOCUMENT_ARRAY_FIELDS, 'left_document_id']);
    const entries: Array<[string, string]> = [];
    const args = step.arguments as Json;
    for (const [key, value] of Object.entries(args)) {
        if (hidden.has(key)) {
            continue;
        }
        if (value === null || value === undefined || value === '') {
            continue;
        }
        if (Array.isArray(value) && value.length === 0) {
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
}: {
    conversationId: string;
    turnId: string;
}) {
    const plan = useOrchestrationStore((state) => selectPlan(state, conversationId, turnId));
    const edits = useOrchestrationStore((state) => selectEdits(state, conversationId, turnId));
    const stepRuntime = useOrchestrationStore((state) =>
        selectStepRuntime(state, conversationId, turnId),
    );
    const disableStep = useOrchestrationStore((state) => state.disableStep);
    const enableStep = useOrchestrationStore((state) => state.enableStep);
    const removeDocument = useOrchestrationStore((state) => state.removeDocument);
    const restoreDocument = useOrchestrationStore((state) => state.restoreDocument);

    const orderedSteps = useMemo(
        () => (plan ? orderStepsForDisplay(plan.steps) : []),
        [plan],
    );

    const capabilities = useBootstrapStore((state) => state.data?.orchestration?.capabilities);

    // Steps grouped under their phase, in run order, so the list reads as "gather, then answer"
    // rather than as a flat sequence. A step's phase is resolved from the capability menu when the
    // plan does not carry one itself, so an older or persisted plan still groups correctly; a step
    // whose phase cannot be resolved trails the known phases under no heading rather than vanishing
    // from a plan the user is meant to be able to audit. The running number follows display order,
    // so the steps still read 1..n across the groups.
    const phaseGroups = useMemo(() => {
        const phaseByCapability = new Map<string, string>();
        for (const capability of capabilities ?? []) {
            phaseByCapability.set(capability.id, capability.phase);
        }
        const resolvePhase = (step: OrchestrationStep): string =>
            step.phase ?? phaseByCapability.get(step.capability_id) ?? '';

        const buckets = new Map<string, OrchestrationStep[]>();
        for (const step of orderedSteps) {
            const resolved = resolvePhase(step);
            const key = (ORCHESTRATION_PHASES as string[]).includes(resolved) ? resolved : '';
            const list = buckets.get(key) ?? [];
            list.push(step);
            buckets.set(key, list);
        }

        const groups: Array<{
            key: string;
            label: string | null;
            steps: Array<{ step: OrchestrationStep; number: number }>;
        }> = [];
        let counter = 0;
        const pushGroup = (key: string, label: string | null, steps?: OrchestrationStep[]) => {
            if (!steps || steps.length === 0) {
                return;
            }
            groups.push({
                key,
                label,
                steps: steps.map((step) => {
                    counter += 1;
                    return { step, number: counter };
                }),
            });
        };
        for (const phase of ORCHESTRATION_PHASES) {
            pushGroup(phase, phaseLabels[phase], buckets.get(phase));
        }
        pushGroup('_unclassified', null, buckets.get(''));
        return groups;
    }, [orderedSteps, capabilities]);

    if (!plan) {
        return (
            <p className="p-4 text-sm text-text-3">
                No plan to show for this turn yet.
            </p>
        );
    }

    const editable = planRequiresApproval(plan);
    const disabledStepIds = new Set(edits.disabled_step_ids);

    const renderStep = (step: OrchestrationStep, displayNumber: number) => {
        const isTerminal = step.capability_id === TERMINAL_CAPABILITY_ID;
        const willRun = step.enabled && !disabledStepIds.has(step.step_id);
        const status = stepRuntime[step.step_id]?.status ?? step.status;
        const summary = stepRuntime[step.step_id]?.summary ?? '';
        const removed = new Set(edits.removed_document_ids[step.step_id] ?? []);
        const removable = new Set(stepRemovableDocumentIds(step));
        const documents = stepDocumentIds(step);
        const args = readableArguments(step);

        return (
            <li
                key={step.step_id}
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
                                {step.capability_id}
                            </span>
                            <span className={clsx('text-[11px]', costTone[step.estimated_cost])}>
                                {step.estimated_cost}
                            </span>
                            <span
                                className={clsx(
                                    'ml-auto rounded-full px-1.5 py-0.5 text-[11px] capitalize',
                                    statusTone[status],
                                )}
                            >
                                {status}
                            </span>
                        </div>

                        {step.rationale ? (
                            <p className="mt-1 text-xs text-text-3">{step.rationale}</p>
                        ) : null}

                        {summary ? (
                            <p className="mt-1 text-xs text-text-2">{summary}</p>
                        ) : null}

                        {args.length > 0 ? (
                            <dl className="mt-2 space-y-0.5">
                                {args.map(([key, value]) => (
                                    <div key={key} className="flex gap-1.5 text-xs">
                                        <dt className="shrink-0 font-mono text-text-3">
                                            {key}
                                        </dt>
                                        <dd className="min-w-0 truncate text-text-2" title={value}>
                                            {value}
                                        </dd>
                                    </div>
                                ))}
                            </dl>
                        ) : null}

                        {documents.length > 0 ? (
                            <ul className="mt-2 flex flex-wrap gap-1.5">
                                {documents.map((documentId) => {
                                    const isRemoved = removed.has(documentId);
                                    const canRemove =
                                        editable && removable.has(documentId);
                                    return (
                                        <li
                                            key={documentId}
                                            className={clsx(
                                                'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]',
                                                isRemoved
                                                    ? 'border-edge text-text-3 line-through'
                                                    : 'border-edge-strong text-text-2',
                                            )}
                                        >
                                            <FileText size={10} className="shrink-0" />
                                            <span
                                                className="max-w-[9rem] truncate"
                                                title={documentId}
                                            >
                                                {documentId}
                                            </span>
                                            {isRemoved ? (
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

                        <div className="mt-2">
                            {isTerminal ? (
                                <span className="inline-flex items-center gap-1 text-[11px] text-text-3">
                                    <Lock size={11} />
                                    Always runs
                                </span>
                            ) : editable ? (
                                <Toggle
                                    checked={willRun}
                                    onChange={(next) =>
                                        next
                                            ? enableStep(conversationId, turnId, step.step_id)
                                            : disableStep(conversationId, turnId, step)
                                    }
                                    label={willRun ? 'Will run' : 'Skipped'}
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
            <div>
                <p className="text-sm font-medium text-text-1">{plan.intent.summary}</p>
                {plan.assumptions.length > 0 ? (
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-text-3">
                        {plan.assumptions.map((assumption, index) => (
                            <li key={index}>{assumption}</li>
                        ))}
                    </ul>
                ) : null}
            </div>

            {phaseGroups.map((group) => (
                <section key={group.key} className="space-y-2">
                    {group.label ? (
                        <p className="px-0.5 text-[11px] font-semibold uppercase tracking-wide text-text-3">
                            {group.label}
                        </p>
                    ) : null}
                    <ol className="space-y-2">
                        {group.steps.map(({ step, number }) => renderStep(step, number))}
                    </ol>
                </section>
            ))}
        </div>
    );
}
