// ActivityStatusBadge.tsx
// A run's, or one activity's, status as words, a glyph and a tone.
//
// The words come from the rest of V2's workflow vocabulary (lib/workflowWorkbench.ts), so "Awaiting
// sign in" reads the same here as in the Workflows section. The glyph is there so the state is
// never carried by colour alone. The tone colours the border, the tint and the glyph; the words are
// in the body text colour, because a status colour on its own tint is too faint for small text in
// the light theme.

import { clsx } from 'clsx';
import type { LucideIcon } from 'lucide-react';
import { CircleCheck, CircleDashed, CircleSlash, CircleX, Clock, Loader2 } from 'lucide-react';
import {
    activityStatusView,
    type ActivityStatusView,
    type ActivityTone,
} from '../../lib/workflowActivitySnapshot';

const TONE_CLASS: Record<ActivityTone, { badge: string; glyph: string }> = {
    accent: { badge: 'border-accent/40 bg-accent-soft', glyph: 'text-accent' },
    warn: { badge: 'border-warn/40 bg-warn-soft', glyph: 'text-warn' },
    danger: { badge: 'border-danger/40 bg-danger-soft', glyph: 'text-danger' },
    ok: { badge: 'border-ok/40 bg-ok-soft', glyph: 'text-ok-strong' },
    neutral: { badge: 'border-edge-strong bg-surface-2', glyph: 'text-text-3' },
};

const GLYPH: Record<ActivityStatusView['glyph'], LucideIcon> = {
    running: Loader2,
    waiting: Clock,
    done: CircleCheck,
    failed: CircleX,
    cancelled: CircleSlash,
    idle: CircleDashed,
};

export function ActivityStatusBadge({
    status,
    className,
    testId,
}: {
    status: string;
    className?: string;
    testId?: string;
}) {
    const view = activityStatusView(status);
    const Icon = GLYPH[view.glyph];
    const tone = TONE_CLASS[view.tone];
    return (
        <span
            data-testid={testId}
            data-status={status || 'idle'}
            data-tone={view.tone}
            className={clsx(
                'inline-flex max-w-full min-w-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium text-text-1',
                tone.badge,
                className,
            )}
        >
            <Icon
                size={12}
                aria-hidden="true"
                className={clsx('shrink-0', tone.glyph, view.glyph === 'running' && 'animate-spin motion-reduce:animate-none')}
            />
            <span className="min-w-0 break-words">{view.label}</span>
        </span>
    );
}
