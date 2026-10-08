// OrchestrationRecoveryNotice.tsx
import { useEffect, useRef, useState } from 'react';
import { GlassButton } from '../ui/primitives';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { useChatStore } from '../../stores/chatStore';
import { useOrchestrationStore } from '../../stores/orchestrationStore';
import {
    cancelOrchestration,
    loadOrchestrationRecovery,
    openOrchestrationRecovery,
    reconcileOrchestrationRun,
    retryOrchestrationRun,
    runPreparedOrchestrationRetry,
} from '../../lib/orchestrationController';
import {
    isOrchestrationRunPending, isOrchestrationRunWaiting, normalizeOrchestrationAttempt,
    type OrchestrationPlan, type PlanStatus,
} from '../../lib/orchestration';
import { legacyPlanErrorMessage } from '../../lib/orchestrationErrors';
import { M365ApprovalInlineCard } from './M365ApprovalInlineCard';
import { OrchestrationM365Notice } from './OrchestrationM365Notice';

function RecoveryConfirmation({
    busy, onConfirm, onClose,
}: { busy?: boolean; onConfirm: () => void; onClose: () => void }) {
    const contentRef = useRef<HTMLParagraphElement>(null);
    useEffect(() => {
        const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        const dialog = contentRef.current?.closest('[role="dialog"]');
        const oldOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        dialog?.querySelector<HTMLElement>('button')?.focus();
        const trapTab = (event: KeyboardEvent) => {
            if (event.key !== 'Tab') return;
            const buttons = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not([disabled])') ?? []);
            const first = buttons[0];
            const last = buttons[buttons.length - 1];
            if (!dialog?.contains(document.activeElement)
                || (event.shiftKey && document.activeElement === first)
                || (!event.shiftKey && document.activeElement === last)) {
                event.preventDefault();
                (event.shiftKey ? last : first)?.focus();
            }
        };
        document.addEventListener('keydown', trapTab);
        return () => {
            document.removeEventListener('keydown', trapTab);
            document.body.style.overflow = oldOverflow;
            if (previous?.isConnected) previous.focus();
        };
    }, []);
    return (
        <ConfirmDialog
            title="Retry this failed step?"
            description="The failed step may already have acted outside this chat. Retrying an agent or action step could repeat changes it made in an external service. A saved workflow that already started is linked again, never started twice."
            confirmLabel="Confirm retry"
            tone="primary"
            busy={busy}
            onConfirm={onConfirm}
            onClose={() => { if (!busy) onClose(); }}
        >
            <p ref={contentRef} className="text-sm text-text-2">
                Previously completed plan steps will not be repeated. Only incomplete work listed for retry will execute.
            </p>
        </ConfirmDialog>
    );
}

export function OrchestrationRecoveryNotice({
    conversationId,
    runId,
    metadata,
    plan,
    status,
}: {
    conversationId: string;
    runId: string;
    metadata?: unknown;
    plan?: OrchestrationPlan;
    status?: PlanStatus;
}) {
    const saved = useOrchestrationStore((state) => state.runRecovery[runId]);
    const streaming = useChatStore((state) => state.streaming);
    const inFlight = useOrchestrationStore((state) => state.inFlight);
    const [confirmationVersion, setConfirmationVersion] = useState<string | null>(null);
    const attempt = saved ?? normalizeOrchestrationAttempt(metadata);
    const outcome = attempt.outcome ?? saved?.status ?? status;
    const runState = { ...attempt, status: saved?.status ?? status };
    const waiting = isOrchestrationRunWaiting(runState);
    const failed = !waiting && (outcome === 'failed' || outcome === 'partial' || outcome === 'cancelled');
    const newer = attempt.recovery?.current_run_id || attempt.latest_attempt_run_id;
    const previousRunId = attempt.retry_of_run_id;
    // A retry that finished needs no notice: its answer is the reply, and the attempt it
    // replaced is hidden from the thread. Its saved attempts stay reachable from the message's
    // details. A prepared retry that has not run yet still offers to run it.
    const preparedRetry = Boolean(attempt.retry_of_run_id) && (outcome === 'awaiting_approval' || outcome === 'approved');
    const relevant = failed || waiting || saved?.transportUnknown || saved?.error
        || Boolean(newer && newer !== runId) || preparedRetry;
    const currentPlan = saved?.plan ?? plan;
    const recovery = attempt.recovery;
    const outputs = attempt.outputs ?? [];
    const fileOutputs = outputs.length > 0;
    // A file that failed for good cannot be retried on its own: a file retry runs in the
    // background, where the sign-in some sources need is not available. A plan retry runs it
    // again from this chat, as long as no other file is still being prepared.
    const filesInProgress = outputs.some((output) =>
        output.state === 'waiting' || output.state === 'rendering' || output.state === 'retry_scheduled');
    const planRetryForFiles = fileOutputs && !filesInProgress
        && outputs.some((output) => output.state === 'failed' && !output.can_retry);
    const planRetryOffered = !fileOutputs || planRetryForFiles;
    // The server refuses runs from an earlier orchestration version: there is nothing to reload,
    // check or review, only its message to show.
    const legacy = Boolean(saved?.legacyPlan);

    useEffect(() => {
        if (!runId || saved?.detailLoaded || legacy || (!relevant && outcome)) return;
        let mounted = true;
        void loadOrchestrationRecovery(conversationId, runId).catch((error) => {
            if (!mounted) return;
            const legacyMessage = legacyPlanErrorMessage(error);
            useOrchestrationStore.getState().updateRunRecovery(runId, legacyMessage
                ? { error: legacyMessage, legacyPlan: true }
                : { error: 'Recovery details could not be loaded. The previous result has been kept. Check saved status before retrying.' });
        });
        return () => { mounted = false; };
    }, [conversationId, runId, saved?.detailLoaded, legacy, Boolean(relevant), outcome]);

    if (!runId || !relevant) return null;
    const active = Object.values(inFlight).some((run) => run.conversationId === conversationId);
    const retryAllowed = failed && planRetryOffered && !isOrchestrationRunPending(runState) && recovery?.eligible && recovery.expected_version
        && (!newer || newer === runId) && !saved?.transportUnknown;
    const retry = async (confirmedVersion?: string) => {
        const result = await retryOrchestrationRun(conversationId, runId, confirmedVersion);
        setConfirmationVersion(result.confirmationRequired && result.version ? result.version : null);
    };
    const titleFor = (stepId: string) => currentPlan?.steps.find((step) => step.step_id === stepId)?.title || stepId;
    const allFailures = [...(attempt.failure ? [attempt.failure] : []), ...(attempt.failures ?? [])];
    const replaced = Boolean(newer && newer !== runId);
    const approvalFailure = allFailures.find(
        (failure) => failure.code === 'm365_approval_required' && Boolean(failure.approval_id),
    );
    // The card continues the plan, so it is offered wherever a plan retry is.
    const inlineApproval = failed && !replaced && planRetryOffered && !saved?.transportUnknown && !legacy
        ? approvalFailure : undefined;
    const confirmation = confirmationVersion ? (
        <RecoveryConfirmation
            busy={saved?.busy}
            onConfirm={() => void retry(confirmationVersion)}
            onClose={() => setConfirmationVersion(null)}
        />
    ) : null;

    if (replaced && !waiting && !saved?.transportUnknown && !saved?.error) {
        // The newer attempt carries the outcome now; its message replaces this one once saved.
        return (
            <section aria-label="Orchestration recovery" className="mt-3 flex flex-wrap items-center gap-2 text-xs text-text-3">
                <p role="status">A newer attempt of this plan exists.</p>
                <GlassButton size="sm" variant="ghost"
                    onClick={() => openOrchestrationRecovery(conversationId, newer as string)}>
                    View current attempt
                </GlassButton>
            </section>
        );
    }

    if (inlineApproval?.approval_id) {
        const stepTitle = inlineApproval.step_id
            ? currentPlan?.steps.find((step) => step.step_id === inlineApproval.step_id)?.title
            : undefined;
        return (
            <section aria-label="Orchestration recovery" className="mt-3 space-y-2 text-xs text-text-2">
                <M365ApprovalInlineCard
                    approvalId={inlineApproval.approval_id}
                    stepTitle={stepTitle}
                    canContinue={Boolean(retryAllowed)}
                    continuing={Boolean(saved?.busy || streaming || active)}
                    onContinue={() => retry()}
                />
                {saved?.error ? <p role="alert">{saved.error}</p> : null}
                <GlassButton size="sm" variant="ghost"
                    onClick={() => openOrchestrationRecovery(conversationId, runId)}>
                    Review saved attempt
                </GlassButton>
                {confirmation}
            </section>
        );
    }

    return (
        <section
            aria-label="Orchestration recovery"
            className="alert mt-3 space-y-2 rounded-xl border border-edge bg-surface-sunken p-3 text-xs text-text-2"
        >
            <p role="status" className="font-medium text-text-1">
                {saved?.transportUnknown ? 'Checking execution status'
                    : waiting ? 'Waiting for required results'
                    : outcome === 'partial' ? 'Partially completed'
                    : outcome === 'failed' ? 'The plan could not complete'
                    : outcome === 'cancelled' ? 'This attempt was stopped' : 'Saved execution attempt'}
                {attempt.attempt_index ? ` - Attempt ${attempt.attempt_index}` : ''}
            </p>
            {attempt.failure?.message ? <p>{attempt.failure.message}</p> : null}
            {saved?.error ? <p role="alert">{saved.error}</p> : null}
            {failed && !saved?.transportUnknown && !legacy && !replaced ? (
                <OrchestrationM365Notice failures={allFailures} />
            ) : null}
            {waiting ? (
                <p>
                    This computation is still pending in the same attempt. Dependent tasks will wait for its results.
                    Checking saved status or reloading does not run the task again.
                </p>
            ) : null}
            {failed && !saved?.transportUnknown && !legacy ? (
                <p>{fileOutputs && !planRetryForFiles ? 'Review each file separately. File retry controls do not repeat the plan or its producer tasks.'
                    : planRetryForFiles && recovery?.eligible && (!newer || newer === runId)
                    ? 'A file could not be created and cannot be retried on its own. Retry from failed step creates the plan\'s files again without repeating completed plan steps.'
                    : recovery?.message || (newer && newer !== runId
                    ? 'A newer execution attempt already exists. Review its saved result.'
                    : recovery?.eligible
                    ? 'Resume the saved plan without repeating completed plan steps.'
                    : 'This historical attempt has no verified recovery checkpoint. It cannot be resumed; start a new plan deliberately if needed.')}</p>
            ) : null}
            {failed && planRetryOffered && recovery?.reused_step_ids.length ? (
                <p><strong>Reuse saved results:</strong> {recovery.reused_step_ids.map(titleFor).join(', ')}.</p>
            ) : null}
            {failed && planRetryOffered && recovery?.retry_step_ids.length ? (
                <p><strong>Execute on retry:</strong> {recovery.retry_step_ids.map(titleFor).join(', ')}.</p>
            ) : null}
            <div className="flex flex-wrap gap-2">
                {!fileOutputs && preparedRetry ? (
                    <GlassButton size="sm" disabled={Boolean(saved?.busy || streaming || active)}
                        onClick={() => void runPreparedOrchestrationRetry(conversationId, runId)}>
                        Run prepared retry
                    </GlassButton>
                ) : null}
                {retryAllowed ? (
                    <GlassButton size="sm" disabled={Boolean(saved?.busy || streaming || active)}
                        onClick={() => void retry()}>
                        {saved?.busy ? 'Preparing retry...' : 'Retry from failed step'}
                    </GlassButton>
                ) : null}
                {newer && newer !== runId ? (
                    <GlassButton size="sm" variant="subtle"
                        onClick={() => openOrchestrationRecovery(conversationId, newer)}>
                        View current attempt
                    </GlassButton>
                ) : null}
                {previousRunId ? (
                    <GlassButton size="sm" variant="subtle"
                        onClick={() => openOrchestrationRecovery(conversationId, previousRunId)}>
                        View previous attempt
                    </GlassButton>
                ) : null}
                {!legacy ? (
                    <GlassButton size="sm" variant="ghost"
                        onClick={() => openOrchestrationRecovery(conversationId, runId)}>
                        Review saved attempt
                    </GlassButton>
                ) : null}
                {!legacy && (waiting || saved?.transportUnknown || saved?.error) ? (
                    <GlassButton size="sm" variant="subtle" disabled={saved?.checking}
                        onClick={() => void reconcileOrchestrationRun(conversationId, runId)}>
                        Check saved status
                    </GlassButton>
                ) : null}
                {(waiting || saved?.transportUnknown) && inFlight[runId] ? (
                    <GlassButton size="sm" variant="ghost"
                        onClick={() => void cancelOrchestration(conversationId, runId)}>
                        Stop execution
                    </GlassButton>
                ) : null}
            </div>
            {confirmation}
        </section>
    );
}

export function OrchestrationMessageRecovery({
    conversationId, metadata,
}: { conversationId: string; metadata: unknown }) {
    const attempt = normalizeOrchestrationAttempt(metadata);
    if (!attempt.run_id && (attempt.outcome === 'failed' || attempt.outcome === 'partial' || attempt.outcome === 'cancelled')) {
        return <p role="status" className="alert mt-3 rounded-xl bg-surface-sunken p-3 text-xs text-text-2">
            This historical orchestration message has no saved attempt identity. It cannot be resumed.
        </p>;
    }
    return attempt.run_id ? (
        <OrchestrationRecoveryNotice conversationId={conversationId} runId={attempt.run_id} metadata={metadata} />
    ) : null;
}
