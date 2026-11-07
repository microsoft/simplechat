// ReadoutRow.tsx
// The frame an Operations readout sits in, and the status line inside it.
//
// A readout reports something rather than editing it -- when a refresh runs next, whether a
// saved setting is live yet -- but it still reads as one of the section's settings. It uses
// the same label, help and control columns as every field (see `.admin-field` in
// theme.css), so on a wide card it lines up with the controls around it instead of
// floating as a banner.

import type { ReactNode } from 'react';
import { clsx } from 'clsx';
import type { LucideIcon } from 'lucide-react';
import type { FieldWidth } from './fields';

export type ReadoutTone = 'ok' | 'warn' | 'info' | 'muted';

const TONE_CLASS: Record<ReadoutTone, string> = {
    ok: 'border-ok/40 bg-ok/5 text-text-2',
    warn: 'border-warn/40 bg-warn/5 text-text-1',
    info: 'border-edge bg-surface-2 text-text-2',
    muted: 'border-edge bg-surface-1 text-text-3',
};

const ICON_CLASS: Record<ReadoutTone, string> = {
    ok: 'text-ok',
    warn: 'text-warn',
    info: 'text-text-3',
    muted: 'text-text-3',
};

export function ReadoutRow({
    label,
    help,
    width = 'wide',
    children,
}: {
    label: string;
    help?: string;
    width?: FieldWidth;
    children: ReactNode;
}) {
    return (
        <div className="admin-field py-3" data-field-width={width}>
            <div className="admin-field-heading text-sm font-semibold text-text-1">{label}</div>
            {help ? (
                <p className="admin-field-help text-[0.8125rem] leading-relaxed text-text-3">{help}</p>
            ) : null}
            <div className="admin-field-control min-w-0">{children}</div>
        </div>
    );
}

/** One status statement, with its tone carried by colour, icon and wording together. */
export function ReadoutLine({
    tone,
    icon: Icon,
    children,
    detail,
}: {
    tone: ReadoutTone;
    icon: LucideIcon;
    children: ReactNode;
    /** A quieter second line, for the supporting fact. */
    detail?: ReactNode;
}) {
    return (
        <div
            className={clsx(
                'flex items-start gap-2 rounded-lg border px-3 py-2 text-[0.8125rem] leading-relaxed',
                TONE_CLASS[tone],
            )}
        >
            <Icon size={14} aria-hidden="true" className={clsx('mt-0.5 shrink-0', ICON_CLASS[tone])} />
            <div className="min-w-0">
                <p>{children}</p>
                {detail ? <p className="mt-0.5 text-xs text-text-3">{detail}</p> : null}
            </div>
        </div>
    );
}
