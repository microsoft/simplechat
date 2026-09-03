// TabularRunStatus.tsx
// Live progress for a generated export that is still running on the server.
//
// A large export is durable: the request returns as soon as the run is queued, and the file
// appears minutes later. Without this the turn ends with a sentence promising a file and
// nothing to show for it — the user cannot tell a slow run from a dead one, cannot restart a
// run the worker dropped, and cannot stop one they did not mean to start.
//
// Polling is deliberately slow and self-terminating. The first check is quick because a small
// run often finishes almost immediately, and subsequent checks back off to ten seconds. It
// stops as soon as the run reaches a state it cannot leave on its own, so a finished card
// costs nothing.

import { useCallback, useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, XCircle } from 'lucide-react';
import {
    cancelGeneratedOutputRun,
    fetchGeneratedOutputRun,
    resumeGeneratedOutputRun,
} from '../../lib/endpoints';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';
import {
    canCancelRun,
    canResumeRun,
    readRunArtifactSetMembers,
    resumeLabel,
    runDetailParts,
    runProgressPercent,
    runStatusLabel,
    runStatusTone,
    runTimingParts,
    runTypeLabel,
    shouldPollRun,
    type GeneratedArtifact,
    type GeneratedRunStatus,
    type RunTone,
} from '../../lib/generatedArtifacts';

/** How long to wait before the first status check, and between later ones. */
const FIRST_POLL_MS = 2000;
const POLL_INTERVAL_MS = 10000;

const toneClass: Record<RunTone, string> = {
    success: 'bg-ok-soft text-ok',
    warning: 'bg-warn-soft text-warn',
    danger: 'bg-danger-soft text-danger',
    secondary: 'bg-surface-2 text-text-2',
    info: 'bg-accent-soft text-accent',
};

export function TabularRunStatus({
    artifact,
    onRunUpdate,
    onComplete,
    children,
}: {
    artifact: GeneratedArtifact;
    /** Merge fresh run fields into the artifact the card is drawn from. */
    onRunUpdate: (run: GeneratedRunStatus) => void;
    /** Replace this card with the finished files the run produced. */
    onComplete: (members: GeneratedArtifact[]) => void;
    /** Supporting detail folded into the collapsed section, so it does not crowd the bar. */
    children?: React.ReactNode;
}) {
    const runId = artifact.export_run_id || artifact.run_id;
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState<'resume' | 'cancel' | null>(null);

    // Read inside callbacks without making them a dependency, so a status change does not
    // tear down and restart the poll timer mid-interval.
    const artifactRef = useRef(artifact);
    artifactRef.current = artifact;

    // The parent passes these inline, so their identity changes on every render. Held in a
    // ref because the poll effect must not depend on them: restarting the effect on each
    // update would reset the interval to the initial two-second delay every time a status
    // arrived, quietly polling five times more often than intended.
    const handlersRef = useRef({ onRunUpdate, onComplete });
    handlersRef.current = { onRunUpdate, onComplete };

    const applyRun = useCallback(
        (run: GeneratedRunStatus | undefined): boolean => {
            const current = artifactRef.current;
            const resolvedRunId = String(run?.run_id ?? '').trim() || runId;
            const members = run ? readRunArtifactSetMembers(run, current) : [];

            if (members.length) {
                handlersRef.current.onComplete(members);
                return true;
            }

            handlersRef.current.onRunUpdate({
                ...(run ?? {}),
                export_run_id: resolvedRunId,
                run_id: resolvedRunId,
                background_export: true,
            });
            return false;
        },
        [runId],
    );

    useEffect(() => {
        if (!runId || !shouldPollRun(artifactRef.current)) {
            return;
        }

        let cancelled = false;
        let timer: number | undefined;

        const check = async () => {
            if (cancelled) {
                return;
            }
            try {
                const response = await fetchGeneratedOutputRun(runId);
                if (cancelled) {
                    return;
                }
                setError(null);
                if (applyRun(response.run)) {
                    return;
                }
            } catch (cause) {
                if (cancelled) {
                    return;
                }
                setError(
                    cause instanceof Error ? cause.message : 'Could not refresh export progress.',
                );
            }

            if (!cancelled && shouldPollRun(artifactRef.current)) {
                timer = window.setTimeout(check, POLL_INTERVAL_MS);
            }
        };

        timer = window.setTimeout(check, FIRST_POLL_MS);

        return () => {
            cancelled = true;
            if (timer !== undefined) {
                window.clearTimeout(timer);
            }
        };
        // `artifact.status` restarts polling when a resume moves the run out of a resting
        // state; the ref keeps the callbacks reading the latest artifact either way.
    }, [runId, artifact.status, artifact.background_export, applyRun]);

    const resume = async () => {
        if (!runId) {
            return;
        }
        setBusy('resume');
        try {
            const response = await resumeGeneratedOutputRun(runId);
            setError(null);
            const finished = applyRun(response.run);
            toast.success(
                response.message ||
                    (finished
                        ? 'Background export is already complete.'
                        : 'Background export was queued to continue.'),
            );
        } catch (cause) {
            const message =
                cause instanceof Error ? cause.message : 'Could not continue background export.';
            setError(message);
            toast.error(message);
        } finally {
            setBusy(null);
        }
    };

    const cancel = async () => {
        if (!runId) {
            return;
        }
        setBusy('cancel');
        try {
            const response = await cancelGeneratedOutputRun(runId);
            setError(null);
            applyRun(response.run);
            toast.success(response.message || 'Background export canceled.');
        } catch (cause) {
            const message =
                cause instanceof Error ? cause.message : 'Could not cancel background export.';
            setError(message);
            toast.error(message);
        } finally {
            setBusy(null);
        }
    };

    const percent = Math.round(runProgressPercent(artifact));
    const details = runDetailParts(artifact);
    const timings = runTimingParts(artifact);
    const showResume = canResumeRun(artifact);
    const showCancel = canCancelRun(artifact);

    return (
        <div className="mt-3">
            <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-text-2">{runTypeLabel(artifact)}</span>
                <span
                    className={clsx(
                        'rounded-full px-2 py-0.5 text-[11px] font-medium',
                        toneClass[runStatusTone(artifact)],
                    )}
                >
                    {runStatusLabel(artifact)}
                </span>
            </div>

            <div
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={percent}
                aria-label={`${runTypeLabel(artifact)} progress`}
                className="h-2 overflow-hidden rounded-full bg-surface-sunken"
            >
                <div
                    className="h-full rounded-full bg-accent transition-[width] duration-500"
                    style={{ width: `${percent}%` }}
                />
            </div>

            <p className="mt-2 text-xs text-text-3">
                {error ||
                    (details.length
                        ? details.join(' | ')
                        : 'Waiting for the background worker to start.')}
            </p>

            {(timings.length > 0 || children) && (
                <details className="mt-2">
                    <summary className="cursor-pointer text-xs font-medium text-text-2">
                        Details
                    </summary>
                    <div className="mt-2 space-y-1 text-xs text-text-3">
                        {timings.length > 0 && <p>{timings.join(' | ')}</p>}
                        {children}
                    </div>
                </details>
            )}

            {(showResume || showCancel) && (
                <div className="mt-3 flex flex-wrap gap-2">
                    {showResume && (
                        <GlassButton
                            size="sm"
                            variant="subtle"
                            disabled={busy !== null}
                            onClick={() => void resume()}
                        >
                            {busy === 'resume' ? (
                                <Loader2 size={13} className="animate-spin" />
                            ) : null}
                            {busy === 'resume' ? 'Continuing…' : resumeLabel(artifact)}
                        </GlassButton>
                    )}
                    {showCancel && (
                        <GlassButton
                            size="sm"
                            variant="danger"
                            disabled={busy !== null}
                            aria-label="Cancel background export"
                            onClick={() => void cancel()}
                        >
                            {busy === 'cancel' ? (
                                <Loader2 size={13} className="animate-spin" />
                            ) : (
                                <XCircle size={13} />
                            )}
                            {busy === 'cancel' ? 'Canceling…' : 'Cancel'}
                        </GlassButton>
                    )}
                </div>
            )}
        </div>
    );
}
