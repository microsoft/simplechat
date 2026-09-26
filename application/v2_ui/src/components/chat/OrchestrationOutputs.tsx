// OrchestrationOutputs.tsx
// The files a plan was asked to produce, one card each, under the answer that promised them.
//
// A card answers three questions and stops: which file, where it stands, and what can be done
// with it. The server's bookkeeping -- attempt counters, retry budgets, failure codes -- is
// kept in the saved projection and the server logs rather than printed here, because none of it
// changes what the reader can do next.

import { useEffect, useId, useLayoutEffect, useMemo, useRef } from 'react';
import { clsx } from 'clsx';
import { GlassButton } from '../ui/primitives';
import { GeneratedArtifactCard } from './GeneratedArtifactCard';
import { normalizeOrchestrationAttempt } from '../../lib/orchestration';
import { formatFileSize } from '../../lib/documentExplorer';
import {
    committedOrchestrationArtifact, orchestrationOutputTypeLabel,
    type OrchestrationOutput, type OrchestrationOutputRetry,
} from '../../lib/orchestrationOutputs';
import {
    observeOrchestrationOutputs, refreshOrchestrationOutputs, retryOrchestrationOutput,
} from '../../lib/orchestrationOutputController';
import type { GeneratedArtifact } from '../../lib/generatedArtifacts';
import { useOrchestrationStore } from '../../stores/orchestrationStore';

const EMPTY_ARTIFACTS: readonly GeneratedArtifact[] = [];
const STATE_LABELS = {
    waiting: 'Waiting',
    rendering: 'Rendering',
    retry_scheduled: 'Automatic retry scheduled',
    completed: 'Completed',
    failed: 'Failed',
    cancelled: 'Cancelled',
};
const STATUS_FALLBACK = 'Check saved file status for the latest progress.';

function rowLabel(rows: number): string {
    return `${rows.toLocaleString()} ${rows === 1 ? 'row' : 'rows'}`;
}

function sizeLabel(bytes: number): string {
    // An empty file is still a finished file; the shared formatter reserves its dash for unknown sizes.
    return bytes === 0 ? '0 B' : formatFileSize(bytes);
}

function OutputCard({
    output, artifacts, conversationId, runId, action, checking, accessDenied,
}: {
    output: OrchestrationOutput;
    artifacts: readonly GeneratedArtifact[];
    conversationId: string;
    runId: string;
    action?: OrchestrationOutputRetry;
    checking?: boolean;
    accessDenied?: boolean;
}) {
    const descriptionId = useId();
    const cardRef = useRef<HTMLElement>(null);
    const retainFocus = useRef(false);
    useLayoutEffect(() => {
        if (!output.can_retry && retainFocus.current) {
            retainFocus.current = false;
            if (document.activeElement === document.body) cardRef.current?.focus({ preventScroll: true });
        }
    }, [output.can_retry]);
    const unavailable = output.available === false || accessDenied;
    const unavailableStatus = accessDenied || (output.available === false && output.state !== 'cancelled');
    const artifact = unavailable ? undefined : committedOrchestrationArtifact(output, artifacts, conversationId);
    const retryDate = output.next_retry_at ? new Date(output.next_retry_at) : null;
    const validRetryDate = retryDate && !Number.isNaN(retryDate.getTime());
    const fileName = output.file_name || 'Unnamed file';
    const completed = output.state === 'completed' && !unavailable;
    const details = [
        orchestrationOutputTypeLabel(output.output_format),
        completed && output.row_count !== null ? rowLabel(output.row_count) : '',
        completed && output.size_bytes !== null ? sizeLabel(output.size_bytes) : '',
    ].filter(Boolean).join(' · ');
    // Waiting, rendering and completed say everything in the badge. Only an outcome the reader
    // could act on, or a scheduled time they could not otherwise see, earns a sentence.
    const note = accessDenied ? 'Current access could not be verified. Downloads and retries are withheld.'
        : output.available === false && !output.error_code && output.state !== 'cancelled'
            ? 'This file is unavailable under current source access or screening. Other ready files remain available.'
        : output.available === false || output.state === 'failed' || output.state === 'cancelled'
            ? output.message || STATUS_FALLBACK
        : output.state === null ? STATUS_FALLBACK : '';
    const retryNote = output.state === 'retry_scheduled' && !unavailable && validRetryDate ? (
        <>Retrying automatically at <time dateTime={output.next_retry_at ?? undefined}>
            {retryDate.toLocaleString()}
        </time>.</>
    ) : null;
    const describedBy = note || retryNote ? descriptionId : undefined;
    return (
        <article ref={cardRef} tabIndex={-1} aria-label={`File ${fileName}`} aria-describedby={describedBy}
            className="min-w-0 space-y-2 rounded-xl border border-edge bg-surface-2 p-3 text-xs">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <h4 className="break-all font-medium text-text-1">{fileName}</h4>
                    <p className="mt-0.5 break-words text-text-3">{details}</p>
                </div>
                <p role="status" className={clsx('rounded px-2 py-0.5 font-medium',
                    unavailableStatus ? 'bg-warn-soft text-warn'
                        : output.state === 'completed' ? 'bg-ok-soft text-ok'
                        : output.state === 'failed' ? 'bg-danger-soft text-danger'
                        : 'bg-surface-3 text-text-2')}>
                    {unavailableStatus ? 'Unavailable' : output.state ? STATE_LABELS[output.state] : 'Status unavailable'}
                </p>
            </div>
            {describedBy ? (
                <p id={descriptionId} className="break-words text-text-2">{note || retryNote}</p>
            ) : null}
            {action?.error ? (
                <p role="alert" className="alert break-words rounded-lg bg-warn-soft p-2 text-warn">{action.error}</p>
            ) : null}
            {output.can_retry && !unavailable ? (
                <GlassButton size="sm" variant="subtle"
                    aria-label={`Retry file ${fileName}`} aria-describedby={describedBy}
                    disabled={Boolean(action?.submitting || action?.blocked || checking)}
                    onClick={(event) => {
                        retainFocus.current = document.activeElement === event.currentTarget;
                        void retryOrchestrationOutput(conversationId, runId, output.output_id);
                    }}>
                    {action?.submitting ? 'Requesting file retry...' : action?.uncertain ? 'Retry same request' : 'Retry file'}
                </GlassButton>
            ) : null}
            {artifact ? (
                <GeneratedArtifactCard key={artifact.artifact_message_id} artifact={artifact}
                    conversationId={conversationId} embedded />
            ) : completed ? (
                <p className="text-text-3">Download details are not available in this response. Check saved file status.</p>
            ) : null}
        </article>
    );
}

export function OrchestrationOutputs({
    conversationId, runId, metadata, artifacts = EMPTY_ARTIFACTS,
}: {
    conversationId: string;
    runId: string;
    metadata?: unknown;
    artifacts?: readonly GeneratedArtifact[];
}) {
    const saved = useOrchestrationStore((state) => state.runRecovery[runId]);
    const supplied = useMemo(() => normalizeOrchestrationAttempt(metadata), [metadata]);
    const outputs = saved?.outputs ?? supplied.outputs;
    const hasProjection = outputs !== undefined;
    useEffect(() => {
        if (!conversationId || !runId || !hasProjection) return;
        const store = useOrchestrationStore.getState();
        if (store.runRecovery[runId]?.outputs === undefined && supplied.outputs !== undefined) {
            store.updateRunRecovery(runId, { outputs: supplied.outputs });
        }
        return observeOrchestrationOutputs(conversationId, runId);
    }, [conversationId, runId, hasProjection, supplied.outputs]);
    if (!outputs?.length) return null;
    const committed = saved?.generated_artifacts ?? supplied.generated_artifacts ?? artifacts;
    return (
        <section aria-label="Files from this plan" className="mt-3 min-w-0 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-medium text-text-1">Files</h3>
                <GlassButton size="sm" variant="ghost" disabled={saved?.outputChecking}
                    onClick={() => void refreshOrchestrationOutputs(conversationId, runId, true)}>
                    {saved?.outputChecking ? 'Checking file status...' : 'Check saved file status'}
                </GlassButton>
            </div>
            {saved?.outputError ? (
                <p role="alert" className="alert rounded-lg bg-warn-soft p-2 text-xs text-warn">{saved.outputError}</p>
            ) : null}
            {outputs.map((output, index) => (
                <OutputCard key={output.output_id || `unavailable-${index}`} output={output}
                    artifacts={committed} conversationId={conversationId} runId={runId}
                    action={saved?.outputRetries?.[output.output_id]} checking={saved?.outputChecking}
                    accessDenied={saved?.outputAccessDenied} />
            ))}
        </section>
    );
}
