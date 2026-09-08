// OrchestrationPlanCard.tsx
import { ReasoningAdjustmentNotice } from './ReasoningAdjustmentNotice';
import { OrchestrationRecoveryNotice } from './OrchestrationRecoveryNotice';
// The plan, inline in the thread, kept deliberately small.
//
// Orchestration turns the composer inside out: instead of the user picking documents, a model and
// a search before they ask, they ask and the server plans the work. This card is where that plan
// first appears — but only the parts that BLOCK live here. Everything else (the step list, the
// rationales, the narrowing edits) belongs in the drawer, because a card the size of the answer it
// precedes would bury the conversation. So this shows the one-line intent, a count, a cost hint,
// and the three things a reader might need to do right now: approve, review, or cancel.
//
// Its state is read from `orchestrationStore`, never held here, for the reason the whole store
// exists: React rebuilds the message subtree this card lives in on every render, and a run keeps
// going after the reader leaves. State kept in the card would be destroyed by the very events it
// is drawn to reflect. See `orchestrationStore.ts` and `InlineImageProposal.tsx`.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Eye, ListChecks, Loader2, PenLine, TriangleAlert, X } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { useChatStore } from '../../stores/chatStore';
import {
    selectEdits,
    selectCanEditPlan,
    selectHasPlanHold,
    selectPlan,
    selectPlanEditor,
    selectPlanRunBlocked,
    selectStepRuntime,
    useOrchestrationStore,
} from '../../stores/orchestrationStore';
import {
    applyPlanEdits,
    isPlanRunnable,
    isPlanTerminal,
    planRequiresApproval,
    summarizePlan,
} from '../../lib/orchestrationPlan';
import {
    approveAndRunPlan,
    dismissOrchestrationTurn,
    openOrchestrationPlanEditor,
} from '../../lib/orchestrationController';
import type { CostClass, OrchestrationPlan } from '../../lib/orchestration';

/** Highest cost class among the steps that will run, or null when none carry one. */
function highestCost(plan: OrchestrationPlan): CostClass | null {
    const rank: Record<CostClass, number> = { low: 1, medium: 2, high: 3 };
    let best: CostClass | null = null;
    for (const step of plan.steps) {
        if (!step.enabled) {
            continue;
        }
        if (!best || rank[step.estimated_cost] > rank[best]) {
            best = step.estimated_cost;
        }
    }
    return best;
}

const costTone: Record<CostClass, string> = {
    low: 'text-text-3',
    medium: 'text-warn',
    high: 'text-danger',
};

/** The countdown ring for timed approval, drawn from the fraction of time left. */
function CountdownRing({ fraction }: { fraction: number }) {
    // A single SVG arc whose dash offset tracks the time remaining. Purely decorative — the
    // spoken affordance is the "Runs in Ns" text beside it — so it is hidden from assistive tech.
    const radius = 9;
    const circumference = 2 * Math.PI * radius;
    const clamped = Math.max(0, Math.min(1, fraction));
    return (
        <svg
            aria-hidden="true"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            className="shrink-0 -rotate-90"
        >
            <circle
                cx="12"
                cy="12"
                r={radius}
                fill="none"
                strokeWidth="2.5"
                className="stroke-edge"
            />
            <circle
                cx="12"
                cy="12"
                r={radius}
                fill="none"
                strokeWidth="2.5"
                strokeLinecap="round"
                className="stroke-accent transition-[stroke-dashoffset] duration-200 ease-linear"
                strokeDasharray={circumference}
                strokeDashoffset={circumference * (1 - clamped)}
            />
        </svg>
    );
}

export function OrchestrationPlanCard({
    conversationId,
    turnId,
}: {
    conversationId: string;
    turnId: string;
}) {
    const plan = useOrchestrationStore((state) => selectPlan(state, conversationId, turnId));
    const edits = useOrchestrationStore((state) => selectEdits(state, conversationId, turnId));
    const editor = useOrchestrationStore((state) => selectPlanEditor(state, conversationId, turnId));
    const held = useOrchestrationStore((state) => selectHasPlanHold(state, conversationId, turnId));
    const canEdit = useOrchestrationStore((state) => selectCanEditPlan(state, conversationId, turnId));
    const runBlocked = useOrchestrationStore((state) => selectPlanRunBlocked(state, conversationId, turnId));
    const stepRuntime = useOrchestrationStore((state) =>
        selectStepRuntime(state, conversationId, turnId),
    );
    // Subscribed to the raw records rather than the filtering selectors, whose fresh arrays would
    // defeat the store's reference equality and re-render this card on every unrelated change.
    const inFlightMap = useOrchestrationStore((state) => state.inFlight);
    const historyMap = useOrchestrationStore((state) => state.history);
    const setDrawerMode = useChatStore((state) => state.setDrawerMode);
    const hasSavedNotice = useChatStore((state) => state.messages.some((message) => {
        const metadata = message.metadata?.orchestration;
        return metadata && typeof metadata === 'object' && 'run_id' in metadata
            && metadata.run_id === plan?.run_id;
    }));

    const editedPlan = useMemo(
        () => (plan ? applyPlanEdits(plan, edits) : null),
        [plan, edits],
    );
    const summary = useMemo(
        () => (plan ? summarizePlan(plan, edits) : null),
        [plan, edits],
    );

    const runInFlight = useMemo(
        () =>
            Object.values(inFlightMap).find(
                (run) => run.conversationId === conversationId && run.turnId === turnId,
            ) ?? null,
        [inFlightMap, conversationId, turnId],
    );
    const historyEntry = useMemo(
        () =>
            (historyMap[conversationId] ?? []).find((entry) => entry.turnId === turnId) ?? null,
        [historyMap, conversationId, turnId],
    );

    const isTimed = plan?.approval.mode === 'timed' && !held;
    const awaitingApproval =
        plan !== null &&
        !runInFlight &&
        !historyEntry &&
        !isPlanTerminal(plan) &&
        planRequiresApproval(plan);

    // The countdown lives in the browser: the server leaves a timed plan pending precisely so the
    // clock can be watched and stopped here. On expiry it approves and runs, guarded so a late
    // render tick cannot fire the run twice.
    const timeoutSeconds = plan?.approval.timeout_seconds ?? 0;
    const [remainingMs, setRemainingMs] = useState(timeoutSeconds * 1000);
    const expiredRef = useRef(false);
    const runTimed = awaitingApproval && isTimed && timeoutSeconds > 0;

    useEffect(() => {
        if (!runTimed) {
            return;
        }
        expiredRef.current = false;
        const startedAt = Date.now();
        const totalMs = timeoutSeconds * 1000;
        setRemainingMs(totalMs);
        const id = window.setInterval(() => {
            const left = totalMs - (Date.now() - startedAt);
            if (left <= 0) {
                setRemainingMs(0);
                if (!expiredRef.current) {
                    expiredRef.current = true;
                    void approveAndRunPlan({ conversationId, turnId, automatic: true });
                }
                window.clearInterval(id);
                return;
            }
            setRemainingMs(left);
        }, 200);
        return () => window.clearInterval(id);
    }, [runTimed, timeoutSeconds, conversationId, turnId]);

    if (!plan || !summary) {
        return null;
    }

    const openReview = () => setDrawerMode('plan');

    // Settled: nothing in the thread. The plan is still there -- the header's Plan button
    // opens it, and the drawer's Map view lists every run in the conversation -- but a
    // finished plan is not something the reader has to act on, and leaving a row under
    // every answer turns the thread into a log of machinery rather than a conversation.
    //
    // This is why the card renders from the store rather than from message markdown: there
    // is nothing to clean up when it stops being relevant, it simply stops rendering.
    if ((historyEntry || isPlanTerminal(plan)) && !runInFlight) {
        if (hasSavedNotice) return null;
        return <OrchestrationRecoveryNotice conversationId={conversationId}
            runId={plan.run_id} plan={plan} status={plan.status} />;
    }

    // Running: a compact progress line. The full step list is a click away in the drawer, so this
    // stays a single row rather than duplicating it.
    if (runInFlight) {
        const total = summary.step_count;
        let completed = 0;
        for (const step of editedPlan?.steps ?? []) {
            if (!step.enabled) {
                continue;
            }
            const status = stepRuntime[step.step_id]?.status;
            if (status === 'completed' || status === 'skipped') {
                completed += 1;
            }
        }
        return (
            <div className="my-3 rounded-2xl border border-edge-strong bg-surface-sunken px-3 py-2">
                <ReasoningAdjustmentNotice adjustments={plan.reasoning_adjustments} />
                <OrchestrationRecoveryNotice conversationId={conversationId}
                    runId={plan.run_id} plan={plan} status={plan.status} />
                <div className="flex items-center gap-2 text-sm">
                    <Loader2 size={15} className="shrink-0 animate-spin text-accent" />
                    <span className="min-w-0 flex-1 truncate text-text-1" title={summary.intent_summary}>
                        {summary.intent_summary || 'Running the plan'}
                    </span>
                    <span className="shrink-0 tabular-nums text-text-3">
                        {completed}/{total}
                    </span>
                    <GlassButton
                        size="sm"
                        variant="subtle"
                        onClick={openReview}
                        aria-label="Review the running plan"
                    >
                        <Eye size={14} />
                        Review
                    </GlassButton>
                </div>
            </div>
        );
    }

    // Awaiting approval (manual or timed), or approved-but-not-yet-running for the brief instant
    // before the run registers. The blocking state: this is the only place the card takes space.
    const cost = highestCost(editedPlan ?? plan);
    const runnable = editedPlan ? isPlanRunnable(editedPlan) && !runBlocked : false;
    const repairs = plan.validation.repairs;
    const remainingSeconds = Math.ceil(remainingMs / 1000);

    return (
        <div className="my-3 rounded-2xl border border-edge-strong bg-surface-sunken p-3">
            <ReasoningAdjustmentNotice adjustments={plan.reasoning_adjustments} />
            <div className="flex items-start gap-2">
                <ListChecks size={16} className="mt-0.5 shrink-0 text-accent" />
                <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-text-1">
                        {summary.intent_summary || 'Plan ready'}
                    </p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-3">
                        <span>
                            {summary.step_count} {summary.step_count === 1 ? 'step' : 'steps'}
                        </span>
                        {cost ? (
                            <>
                                <span aria-hidden="true">·</span>
                                <span className={costTone[cost]}>{cost} cost</span>
                            </>
                        ) : null}
                    </p>
                </div>
            </div>

            {repairs.length > 0 ? (
                // The plan that runs may differ from what the model proposed; saying so is the
                // point. `validation.repairs` is the honest record of what the server corrected.
                <div className="mt-2 flex items-start gap-2 rounded-xl bg-warn-soft px-2.5 py-2 text-xs text-warn">
                    <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                    <div className="min-w-0">
                        <p className="font-medium">Adjusted before running</p>
                        <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
                            {repairs.map((repair, index) => (
                                <li key={index}>{repair}</li>
                            ))}
                        </ul>
                    </div>
                </div>
            ) : null}

            {held ? (
                <p className="mt-2 text-xs text-text-3" role="status">
                    {editor?.loading ? 'Saving the manual-approval hold…'
                        : editor?.state || plan.edit_version ? 'Manual approval required — this plan will not run automatically.'
                        : 'Approval paused in this tab. Open Edit to retry saving the hold.'}
                </p>
            ) : null}
            {editor?.error ? (
                <p role="alert" className="alert mt-2 rounded-xl bg-danger-soft px-2.5 py-2 text-xs text-danger">
                    {editor.error}
                </p>
            ) : null}
            <div className="mt-3 flex flex-wrap items-center gap-2">
                {runTimed ? (
                    <span
                        className="flex items-center gap-1.5 text-xs text-text-3"
                        role="timer"
                        aria-label={`Runs automatically in ${remainingSeconds} seconds`}
                    >
                        <CountdownRing fraction={remainingMs / (timeoutSeconds * 1000)} />
                        <span className="tabular-nums">Runs in {remainingSeconds}s</span>
                    </span>
                ) : null}
                <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
                    <GlassButton
                        size="sm"
                        variant="ghost"
                        onClick={() => dismissOrchestrationTurn(conversationId, turnId)}
                        aria-label="Cancel this plan"
                    >
                        <X size={14} />
                        Cancel
                    </GlassButton>
                    <GlassButton
                        size="sm"
                        variant="subtle"
                        onClick={openReview}
                        aria-label="Review the plan in the drawer"
                    >
                        <Eye size={14} />
                        Review
                    </GlassButton>
                    {canEdit ? (
                        <GlassButton
                            size="sm"
                            variant="subtle"
                            onClick={() => void openOrchestrationPlanEditor({ conversationId, turnId })}
                            aria-label="Edit the plan"
                        >
                            <PenLine size={14} />
                            Edit
                        </GlassButton>
                    ) : null}
                    <GlassButton
                        size="sm"
                        variant="primary"
                        disabled={!runnable}
                        onClick={() => void approveAndRunPlan({ conversationId, turnId })}
                        aria-label={held ? 'Run the saved plan' : 'Approve and run the plan'}
                    >
                        <Check size={14} />
                        {held ? 'Run' : 'Approve'}
                    </GlassButton>
                </div>
            </div>
        </div>
    );
}
