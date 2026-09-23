// OrchestrationOutputs.tsx

import { useEffect, useId, useLayoutEffect, useMemo, useRef } from 'react';
import { clsx } from 'clsx';
import { GlassButton } from '../ui/primitives';
import { GeneratedArtifactCard } from './GeneratedArtifactCard';
import { normalizeOrchestrationAttempt } from '../../lib/orchestration';
import {
    committedOrchestrationArtifact, type OrchestrationOutput, type OrchestrationOutputRetry,
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
    const exhausted = output.state === 'failed' && output.automatic_attempts !== null
        && output.max_automatic_attempts !== null && output.automatic_attempts >= output.max_automatic_attempts;
    return (
        <article ref={cardRef} tabIndex={-1} aria-label={`File ${fileName}`} aria-describedby={descriptionId}
            className="min-w-0 space-y-2 rounded-xl border border-edge bg-surface-2 p-3 text-xs">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                <h4 className="min-w-0 break-all font-medium text-text-1">{fileName}</h4>
                <p role="status" className={clsx('rounded px-2 py-0.5 font-medium',
                    unavailableStatus ? 'bg-warn-soft text-warn'
                        : output.state === 'completed' ? 'bg-ok-soft text-ok'
                        : output.state === 'failed' ? 'bg-danger-soft text-danger'
                        : 'bg-surface-3 text-text-2')}>
                    {unavailableStatus ? 'Unavailable' : output.state ? STATE_LABELS[output.state] : 'Status unavailable'}
                </p>
            </div>
            <p className="break-words text-text-3">
                {output.output_format}{output.profile ? ` / ${output.profile}` : ''}
            </p>
            <div id={descriptionId} className="space-y-1 break-words text-text-2">
                <p>{accessDenied ? 'Current access could not be verified. Downloads and retries are withheld.'
                    : output.available === false && !output.error_code && output.state !== 'cancelled'
                        ? 'This file is unavailable under current source access or screening. Other ready files remain available.'
                    : output.message || 'Check saved file status for the latest progress.'}</p>
                {output.attempt_count !== null ? <p>Attempt {output.attempt_count}</p> : null}
                {output.automatic_attempts !== null && output.max_automatic_attempts !== null ? (
                    <p>Automatic attempts: {output.automatic_attempts} of {output.max_automatic_attempts}</p>
                ) : null}
                {output.state === 'retry_scheduled' && !unavailable ? (
                    <p>{validRetryDate ? (
                        <>Next automatic retry: <time dateTime={output.next_retry_at ?? undefined}>
                            {retryDate.toLocaleString()}
                        </time>. Waiting for the server; reloading does not start a retry.</>
                    ) : 'Waiting for the server to schedule the next automatic retry.'}</p>
                ) : null}
                {exhausted && !unavailable ? <p>Automatic attempts exhausted.</p> : null}
                {output.error_code ? <p className="break-all">Reason: <code>{output.error_code}</code></p> : null}
                {!unavailable && output.state === 'completed' ? (
                    <p className="flex flex-wrap gap-x-3">
                        {output.row_count !== null ? <span>{output.row_count.toLocaleString()} rows</span> : null}
                        {output.character_count !== null ? <span>{output.character_count.toLocaleString()} characters</span> : null}
                        {output.size_bytes !== null ? <span>{output.size_bytes.toLocaleString()} bytes</span> : null}
                    </p>
                ) : null}
            </div>
            {action?.error ? (
                <p role="alert" className="alert break-words rounded-lg bg-warn-soft p-2 text-warn">{action.error}</p>
            ) : null}
            {output.can_retry && !unavailable ? (
                <GlassButton size="sm" variant="subtle"
                    aria-label={`Retry file ${fileName}`} aria-describedby={descriptionId}
                    disabled={Boolean(action?.submitting || action?.blocked || checking)}
                    onClick={(event) => {
                        retainFocus.current = document.activeElement === event.currentTarget;
                        void retryOrchestrationOutput(conversationId, runId, output.output_id);
                    }}>
                    {action?.submitting ? 'Requesting file retry...' : action?.uncertain ? 'Retry same request' : 'Retry file'}
                </GlassButton>
            ) : null}
            {output.state === 'failed' && !output.can_retry && !unavailable ? (
                <p className="text-text-3">The server is not offering a retry for this file.</p>
            ) : null}
            {artifact ? (
                <GeneratedArtifactCard key={artifact.artifact_message_id} artifact={artifact} conversationId={conversationId} />
            ) : output.state === 'completed' && !unavailable ? (
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
            <p className="text-xs text-text-3">
                Each file keeps its own progress. Retrying a file does not repeat producer tasks or other files.
            </p>
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
