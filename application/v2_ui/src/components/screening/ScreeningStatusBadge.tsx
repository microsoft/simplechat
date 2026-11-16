// ScreeningStatusBadge.tsx

import { clsx } from 'clsx';
import { Loader2, ShieldAlert, ShieldCheck } from 'lucide-react';
import {
    isScreeningAvailable,
    screeningPresentation,
    type ContentScreeningSummary,
} from '../../lib/contentScreening';

const tones = {
    muted: 'bg-surface-2 text-text-3',
    warning: 'bg-warn-soft text-warn',
    danger: 'bg-danger-soft text-danger',
    success: 'bg-ok-soft text-ok',
};

export function ScreeningStatusBadge({
    summary,
    detail = false,
}: {
    summary: ContentScreeningSummary | null;
    detail?: boolean;
}) {
    const presentation = screeningPresentation(summary);
    const available = isScreeningAvailable({ content_screening: summary });
    const Icon = presentation.busy ? Loader2 : available ? ShieldCheck : ShieldAlert;

    return (
        <span className="inline-flex max-w-full flex-col items-start gap-1">
            <span
                className={clsx(
                    'inline-flex max-w-full items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium',
                    tones[presentation.tone],
                )}
                title={presentation.description}
                data-testid="screening-status"
            >
                <Icon size={12} className={presentation.busy ? 'shrink-0 animate-spin' : 'shrink-0'} aria-hidden="true" />
                {!available && !presentation.label.includes('held') ? 'Held · ' : ''}
                {presentation.label}
                {summary && summary.finding_count > 0 ? ` · ${summary.finding_count} findings` : ''}
            </span>
            {detail ? (
                <span className="text-xs leading-relaxed text-text-3">{presentation.description}</span>
            ) : null}
        </span>
    );
}
