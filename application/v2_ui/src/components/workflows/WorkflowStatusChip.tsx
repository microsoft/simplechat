// WorkflowStatusChip.tsx
// A workflow's run status as the Admin status chip draws a section's: an icon, words, and a tone.

import { clsx } from 'clsx';
import type { LucideIcon } from 'lucide-react';
import { AlertTriangle, CircleCheck, CircleDashed, CircleSlash, CircleX, Clock, Loader2 } from 'lucide-react';
import { workflowRunState, type WorkflowStatusTone } from '../../lib/workflowWorkbench';
import type { WorkflowDefinition } from '../../lib/workflowEditor';

const TONE_CLASS: Record<WorkflowStatusTone, string> = {
    ok: 'text-ok border-ok/40 bg-ok/5',
    warn: 'text-warn border-warn/40 bg-warn/5',
    danger: 'text-danger border-danger/40 bg-danger/5',
    neutral: 'text-text-3 border-edge-strong',
};

/** The icon that says what kind of state a status is, beside the words that name it. */
function statusIcon(status: string, tone: WorkflowStatusTone): LucideIcon {
    if (['running', 'started', 'in_progress'].includes(status)) return Loader2;
    if (['queued', 'pending'].includes(status) || /^(awaiting|waiting)_/.test(status)) return Clock;
    if (status === 'completed_partial') return AlertTriangle;
    if (['cancelled', 'canceled'].includes(status)) return CircleSlash;
    if (tone === 'danger') return CircleX;
    if (tone === 'ok') return CircleCheck;
    return CircleDashed;
}

export function WorkflowStatusChip({ workflow, compact = false }: {
    workflow: WorkflowDefinition;
    /** Icon only, with the words kept for assistive technology, for a narrow list row. */
    compact?: boolean;
}) {
    const state = workflowRunState(workflow);
    if (!state) return null;
    const Icon = statusIcon(state.status, state.tone);
    const spinning = Icon === Loader2;
    if (compact) {
        return (
            <span className={clsx('inline-flex shrink-0', TONE_CLASS[state.tone].split(' ')[0])} title={state.label}>
                <Icon size={14} aria-hidden="true" className={spinning ? 'animate-spin' : undefined} />
                <span className="sr-only">{state.label}</span>
            </span>
        );
    }
    return (
        <span
            className={clsx(
                'inline-flex max-w-full min-w-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
                TONE_CLASS[state.tone],
            )}
        >
            <Icon size={11} aria-hidden="true" className={clsx('shrink-0', spinning && 'animate-spin')} />
            {state.label}
        </span>
    );
}
