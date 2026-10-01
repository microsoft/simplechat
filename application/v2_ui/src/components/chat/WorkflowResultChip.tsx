// WorkflowResultChip.tsx
// The composer's note that the next question is answered from a finished workflow run's
// stored result (roadmap phase 6a), with the control that removes it.

import { Loader2, Workflow, X } from 'lucide-react';
import {
    WORKFLOW_RESULT_OPENING_NOTICE,
    workflowResultChipLabel,
} from '../../lib/workflowResults';
import type { WorkflowResultDescriptor } from '../../lib/types';

/**
 * Shown above the composer while a workflow result is selected, or while Ask in chat is still
 * reading the run (`descriptor` null).
 *
 * The workflow name is user-authored and is rendered as text only. The run's time is written
 * in the reader's own locale and time zone, which is also the zone the answer's disclosure uses.
 */
export function WorkflowResultChip({
    descriptor,
    onRemove,
}: {
    descriptor: WorkflowResultDescriptor | null;
    onRemove: () => void;
}) {
    return (
        <div
            role="status"
            aria-live="polite"
            data-workflow-result-chip={descriptor ? 'selected' : 'opening'}
            className="mb-2 flex items-start gap-2 rounded-xl bg-surface-2 px-3 py-2"
        >
            {descriptor
                ? <Workflow size={14} aria-hidden="true" className="mt-0.5 shrink-0 text-text-3" />
                : <Loader2 size={14} aria-hidden="true" className="mt-0.5 shrink-0 animate-spin text-text-3" />}
            <span className="min-w-0 flex-1 text-xs text-text-2">
                {descriptor ? workflowResultChipLabel(descriptor) : WORKFLOW_RESULT_OPENING_NOTICE}
            </span>
            <button
                type="button"
                aria-label="Remove workflow result context"
                className="shrink-0 rounded-md p-1 text-text-3 hover:bg-surface-3"
                onClick={onRemove}
            ><X size={14} /></button>
        </div>
    );
}
