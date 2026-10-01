// WorkflowRunLinks.tsx
// Links to the saved workflows an orchestration plan started, under the answer that started them.
//
// Each link names the workflow, shows its run's status when the answer loaded, and offers Open
// run, which opens the run in Workflows with its run history open. Nothing polls: a reload reads
// the status again, and the run page shows live progress and results. A run that cannot be
// opened says why instead. Workflow names are the requester's own text, rendered as plain text.

import { useCallback, useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Link } from 'react-router-dom';
import { GlassButton } from '../ui/primitives';
import { ApiError } from '../../lib/apiClient';
import {
    fetchWorkflowRunLinks,
    workflowRunDisplayName,
    workflowRunReasonText,
    workflowRunStateLabel,
    type WorkflowRunLinkItem,
    type WorkflowRunLinkState,
} from '../../lib/orchestrationWorkflowRuns';

const LOAD_ERROR = 'Could not load the workflow runs this plan started.';

function stateTone(state: WorkflowRunLinkState): string {
    if (state === 'completed') return 'bg-ok-soft text-ok';
    if (state === 'failed' || state === 'cancelled' || state === 'unavailable' || state === 'completed_partial') {
        return 'bg-warn-soft text-warn';
    }
    return 'bg-surface-3 text-text-2';
}

function RunLink({ item }: { item: WorkflowRunLinkItem }) {
    const name = workflowRunDisplayName(item);
    return (
        <li className="min-w-0 space-y-1 rounded-xl border border-edge bg-surface-2 p-3 text-xs">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                    <p className="text-text-3">Started workflow</p>
                    <p className="break-words text-sm font-medium text-text-1">{name}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <p className={clsx('rounded px-2 py-0.5 font-medium', stateTone(item.state))}>
                        {workflowRunStateLabel(item.state)}
                    </p>
                    {item.href ? (
                        <Link to={item.href} aria-label={`Open run of ${name}`}
                            className="inline-flex h-8 items-center rounded-xl px-3 text-sm font-medium text-accent hover:bg-surface-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                            Open run
                        </Link>
                    ) : null}
                </div>
            </div>
            {item.href ? null : <p className="break-words text-text-2">{workflowRunReasonText(item.reason)}</p>}
        </li>
    );
}

/**
 * The saved workflow runs an answer's plan started, for its requester, in a personal conversation.
 *
 * The caller mounts this only when the answer's run completed a workflow_run step. The link route
 * decides what each link may show; a run the reader cannot open renders nothing.
 */
export function WorkflowRunLinks({ conversationId, runId }: { conversationId: string; runId: string }) {
    const [items, setItems] = useState<WorkflowRunLinkItem[] | null>(null);
    const [loadError, setLoadError] = useState('');
    const [missing, setMissing] = useState(false);
    const request = useRef<AbortController | null>(null);

    const load = useCallback(async () => {
        request.current?.abort();
        const controller = new AbortController();
        request.current = controller;
        try {
            const list = await fetchWorkflowRunLinks(runId, conversationId, controller.signal);
            if (controller.signal.aborted) return;
            setItems(list.workflow_runs);
            setLoadError('');
        } catch (cause) {
            if (controller.signal.aborted) return;
            if (cause instanceof ApiError && cause.status === 404) {
                setMissing(true);
                return;
            }
            setLoadError(LOAD_ERROR);
        } finally {
            if (request.current === controller) request.current = null;
        }
    }, [runId, conversationId]);

    useEffect(() => {
        void load();
        return () => request.current?.abort();
    }, [load]);

    if (missing || (!loadError && !items?.length)) return null;
    return (
        <section aria-label="Started workflows" className="mt-3 min-w-0 space-y-2">
            {loadError ? (
                <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg bg-warn-soft p-2 text-xs text-warn">
                    <span className="break-words">{loadError}</span>
                    <GlassButton size="sm" variant="ghost" onClick={() => void load()}>Try again</GlassButton>
                </div>
            ) : null}
            {items?.length ? (
                <>
                    <ul className="min-w-0 space-y-2">
                        {items.map((item) => <RunLink key={item.step_id} item={item} />)}
                    </ul>
                    <p className="text-[11px] text-text-3">
                        Status when this message loaded. Open the run for its progress and results.
                    </p>
                </>
            ) : null}
        </section>
    );
}
