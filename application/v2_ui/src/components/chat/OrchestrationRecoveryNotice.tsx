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
import { normalizeOrchestrationAttempt, type OrchestrationPlan, type PlanStatus } from '../../lib/orchestration';

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
            description="The failed agent or action step may already have performed actions in an external service. Retrying it could repeat actions inside that step."
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
    const failed = outcome === 'failed' || outcome === 'partial' || outcome === 'cancelled';
    const newer = attempt.recovery?.current_run_id || attempt.latest_attempt_run_id;
    const previousRunId = attempt.retry_of_run_id;
    const relevant = failed || saved?.transportUnknown || saved?.error
        || Boolean(newer && newer !== runId) || Boolean(attempt.retry_of_run_id);
    const currentPlan = saved?.plan ?? plan;
    const recovery = attempt.recovery;

    useEffect(() => {
        if (!runId || saved?.detailLoaded || (!relevant && outcome)) return;
        let mounted = true;
        void loadOrchestrationRecovery(conversationId, runId).catch(() => {
            if (mounted) useOrchestrationStore.getState().updateRunRecovery(runId, {
                error: 'Recovery details could not be loaded. The previous result has been kept. Check saved status before retrying.',
            });
        });
        return () => { mounted = false; };
    }, [conversationId, runId, saved?.detailLoaded, Boolean(relevant), outcome]);

    if (!runId || !relevant) return null;
    const active = Object.values(inFlight).some((run) => run.conversationId === conversationId);
    const retryAllowed = failed && recovery?.eligible && recovery.expected_version
        && (!newer || newer === runId) && !saved?.transportUnknown;
    const retry = async (confirmedVersion?: string) => {
        const result = await retryOrchestrationRun(conversationId, runId, confirmedVersion);
        setConfirmationVersion(result.confirmationRequired && result.version ? result.version : null);
    };
    const titleFor = (stepId: string) => currentPlan?.steps.find((step) => step.step_id === stepId)?.title || stepId;

    return (
        <section
            aria-label="Orchestration recovery"
            className="alert mt-3 space-y-2 rounded-xl border border-edge bg-surface-sunken p-3 text-xs text-text-2"
        >
            <p role="status" className="font-medium text-text-1">
                {saved?.transportUnknown ? 'Checking execution status'
                    : outcome === 'partial' ? 'Partially completed'
                    : outcome === 'failed' ? 'The plan could not complete'
                    : outcome === 'cancelled' ? 'This attempt was stopped' : 'Saved execution attempt'}
                {attempt.attempt_index ? ` - Attempt ${attempt.attempt_index}` : ''}
            </p>
            {attempt.failure?.message ? <p>{attempt.failure.message}</p> : null}
            {saved?.error ? <p role="alert">{saved.error}</p> : null}
            {failed && !saved?.transportUnknown ? (
                <p>{recovery?.message || (newer && newer !== runId
                    ? 'A newer execution attempt already exists. Review its saved result.'
                    : recovery?.eligible
                    ? 'Resume the saved plan without repeating completed plan steps.'
                    : 'This historical attempt has no verified recovery checkpoint. It cannot be resumed; start a new plan deliberately if needed.')}</p>
            ) : null}
            {failed && recovery?.reused_step_ids.length ? (
                <p><strong>Reuse saved results:</strong> {recovery.reused_step_ids.map(titleFor).join(', ')}.</p>
            ) : null}
            {failed && recovery?.retry_step_ids.length ? (
                <p><strong>Execute on retry:</strong> {recovery.retry_step_ids.map(titleFor).join(', ')}.</p>
            ) : null}
            <div className="flex flex-wrap gap-2">
                {attempt.retry_of_run_id && (outcome === 'awaiting_approval' || outcome === 'approved') ? (
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
                <GlassButton size="sm" variant="ghost"
                    onClick={() => openOrchestrationRecovery(conversationId, runId)}>
                    Review saved attempt
                </GlassButton>
                {saved?.transportUnknown || saved?.error ? (
                    <GlassButton size="sm" variant="subtle" disabled={saved.checking}
                        onClick={() => void reconcileOrchestrationRun(conversationId, runId)}>
                        Check saved status
                    </GlassButton>
                ) : null}
                {saved?.transportUnknown && inFlight[runId] ? (
                    <GlassButton size="sm" variant="ghost"
                        onClick={() => void cancelOrchestration(conversationId, runId)}>
                        Stop execution
                    </GlassButton>
                ) : null}
            </div>
            {confirmationVersion ? (
                <RecoveryConfirmation
                    busy={saved?.busy}
                    onConfirm={() => void retry(confirmationVersion)}
                    onClose={() => setConfirmationVersion(null)}
                />
            ) : null}
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
