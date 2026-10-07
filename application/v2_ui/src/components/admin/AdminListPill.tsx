// AdminListPill.tsx
// The small status pill an Admin Settings list shows beside a record's name, drawn the way
// the AI Connections list draws "Enabled" and "Disabled".

import type { ReactNode } from 'react';
import { clsx } from 'clsx';

export function AdminListPill({ tone, children }: { tone: 'ok' | 'muted' | 'warn' | 'accent'; children: ReactNode }) {
    return (
        <span
            className={clsx(
                'rounded-full px-1.5 py-0.5 text-[10px] font-semibold tracking-wide whitespace-nowrap uppercase',
                tone === 'ok' && 'bg-ok-soft text-ok',
                tone === 'warn' && 'bg-warn-soft text-warn',
                tone === 'muted' && 'bg-surface-2 text-text-3',
                tone === 'accent' && 'bg-accent-soft text-accent',
            )}
        >
            {children}
        </span>
    );
}
