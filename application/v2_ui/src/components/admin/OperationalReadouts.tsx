// OperationalReadouts.tsx
// The visual vocabulary every live Scale readout shares.
//
// Redis metrics, the document access index, the caches, Cosmos maintenance and Cosmos
// throughput are four different dashboards inside ordinary settings cards. Built ad hoc
// they would each pick their own tile, badge and button, and an administrator would have
// to relearn every card. These pieces keep them consistent with each other and with the
// settings around them: groups look like the field groups, buttons like the connection
// test, and messages like a connection test's outcome.
//
// Tiles flow on the scroll pane's container width rather than the viewport, so they
// reflow inside a narrow card, at large text sizes, and beside the page index alike.

import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { clsx } from 'clsx';
import {
    AlertTriangle,
    CheckCircle2,
    ChevronRight,
    Info,
    Loader2,
    RefreshCw,
    XCircle,
    type LucideIcon,
} from 'lucide-react';
import { formatRelativeTime, type ReadoutTone, type ToneText } from '../../lib/scaleFormat';
import { Skeleton } from '../ui/primitives';

const PILL_TONE: Record<ReadoutTone, string> = {
    ok: 'border-ok/40 bg-ok/5 text-ok',
    info: 'border-info/40 bg-info/5 text-info',
    warn: 'border-warn/40 bg-warn/5 text-warn',
    danger: 'border-danger/40 bg-danger/5 text-danger',
    neutral: 'border-edge-strong text-text-3',
};

const DOT_TONE: Record<ReadoutTone, string> = {
    ok: 'bg-ok',
    info: 'bg-info',
    warn: 'bg-warn',
    danger: 'bg-danger',
    neutral: 'bg-text-3',
};

const MESSAGE_TONE: Record<ReadoutTone, { className: string; Icon: LucideIcon }> = {
    ok: { className: 'border-ok/40 bg-ok/5', Icon: CheckCircle2 },
    info: { className: 'border-info/40 bg-info/5', Icon: Info },
    warn: { className: 'border-warn/40 bg-warn/5', Icon: AlertTriangle },
    danger: { className: 'border-danger/40 bg-danger/5', Icon: XCircle },
    neutral: { className: 'border-edge bg-surface-1', Icon: Info },
};

const ICON_TONE: Record<ReadoutTone, string> = {
    ok: 'text-ok',
    info: 'text-info',
    warn: 'text-warn',
    danger: 'text-danger',
    neutral: 'text-text-3',
};

/** A state such as "Healthy" or "Disabled". The words carry the meaning; colour repeats it. */
export function StatePill({ state, title }: { state: ToneText; title?: string }) {
    return (
        <span
            title={title}
            className={clsx(
                'inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium',
                PILL_TONE[state.tone],
            )}
        >
            <span aria-hidden="true" className={clsx('h-1.5 w-1.5 shrink-0 rounded-full', DOT_TONE[state.tone])} />
            <span className="min-w-0 break-words">{state.text}</span>
        </span>
    );
}

/** A grid of readouts. A description list, so each label is announced with its value. */
export function ReadoutGrid({ children, className }: { children: ReactNode; className?: string }) {
    return (
        <dl className={clsx('grid grid-cols-1 gap-x-6 gap-y-3 @lg:grid-cols-2 @4xl:grid-cols-4', className)}>
            {children}
        </dl>
    );
}

/**
 * One labelled value. `state` draws a pill instead of plain text.
 *
 * Unframed on purpose: the readouts sit inside a group that already draws the frame, and
 * a box around every value inside it reads as a wall of nested cards.
 */
export function Readout({
    label,
    value,
    state,
    detail,
    wide,
    testId,
}: {
    label: string;
    value?: ReactNode;
    state?: ToneText;
    detail?: ReactNode;
    /** Spans two columns, for values that read better on one line. */
    wide?: boolean;
    testId?: string;
}) {
    return (
        <div data-testid={testId} className={clsx('min-w-0', wide && '@lg:col-span-2')}>
            <dt className="text-xs text-text-3">{label}</dt>
            <dd className="mt-0.5 min-w-0 text-sm font-semibold break-words text-text-1 tabular-nums">
                {state ? <StatePill state={state} /> : value}
            </dd>
            {detail ? <dd className="mt-0.5 text-xs break-words text-text-3">{detail}</dd> : null}
        </div>
    );
}

/** Placeholder rows while the first status loads, so the layout does not jump. */
export function ReadoutSkeleton({ rows = 4 }: { rows?: number }) {
    return (
        <div aria-hidden="true" className="grid grid-cols-1 gap-x-6 gap-y-3 @lg:grid-cols-2 @4xl:grid-cols-4">
            {Array.from({ length: rows }).map((_, index) => (
                <div key={index} className="space-y-1.5">
                    <Skeleton className="h-3 w-24" />
                    <Skeleton className="h-4 w-32" />
                </div>
            ))}
        </div>
    );
}

/** A titled cluster of readouts that collapses, drawn like the settings field groups. */
export function ReadoutGroup({
    title,
    description,
    defaultOpen = true,
    children,
}: {
    title: string;
    description?: string;
    defaultOpen?: boolean;
    children: ReactNode;
}) {
    const [open, setOpen] = useState(defaultOpen);

    return (
        <div className="rounded-xl border border-edge-strong bg-surface-solid">
            <button
                type="button"
                aria-expanded={open}
                onClick={() => setOpen((previous) => !previous)}
                className={clsx(
                    'flex min-h-10 w-full items-center gap-2 rounded-xl px-3 py-2 text-left hover:bg-surface-sunken',
                    open && 'rounded-b-none bg-surface-sunken',
                )}
            >
                <ChevronRight
                    size={14}
                    aria-hidden="true"
                    className={clsx('shrink-0 text-text-2 transition-transform', open && 'rotate-90')}
                />
                <span className="min-w-0 text-sm font-semibold text-text-1">{title}</span>
            </button>
            {open ? (
                <div className="space-y-2 border-t border-edge-strong p-3">
                    {description ? (
                        <p className="max-w-[72ch] text-xs leading-relaxed text-text-3">{description}</p>
                    ) : null}
                    {children}
                </div>
            ) : null}
        </div>
    );
}

type OpsButtonTone = 'default' | 'primary' | 'danger';

const BUTTON_TONE: Record<OpsButtonTone, string> = {
    default: 'border-edge text-text-1 hover:border-accent hover:bg-surface-2',
    primary: 'border-accent/50 text-accent hover:bg-accent-soft',
    danger: 'border-danger/50 text-danger hover:bg-danger/10',
};

/** A compact action button. Shows a spinner in place of its icon while busy. */
export function OpsButton({
    icon: Icon,
    tone = 'default',
    busy = false,
    children,
    className,
    disabled,
    ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
    icon?: LucideIcon;
    tone?: OpsButtonTone;
    busy?: boolean;
    children: ReactNode;
}) {
    return (
        <button
            type="button"
            disabled={disabled || busy}
            aria-busy={busy || undefined}
            className={clsx(
                'inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
                'disabled:cursor-not-allowed disabled:opacity-60',
                BUTTON_TONE[tone],
                className,
            )}
            {...rest}
        >
            {busy ? (
                <Loader2 size={13} aria-hidden="true" className="animate-spin" />
            ) : Icon ? (
                <Icon size={13} aria-hidden="true" />
            ) : null}
            {children}
        </button>
    );
}

/**
 * The bar above a live readout: when it was read, Refresh, and the card's own actions.
 *
 * The age is re-rendered every half minute so "Updated 2 min ago" stays true while the
 * page sits open.
 */
export function OpsToolbar({
    loadedAt,
    loading,
    onRefresh,
    refreshLabel = 'Refresh',
    label,
    children,
}: {
    loadedAt: number | null;
    loading: boolean;
    onRefresh: () => void;
    refreshLabel?: string;
    /** Names the toolbar for assistive technology, e.g. "Redis monitoring actions". */
    label: string;
    children?: ReactNode;
}) {
    const [now, setNow] = useState(() => Date.now());

    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), 30000);
        return () => window.clearInterval(timer);
    }, []);

    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-text-3">
                {loading ? 'Loading…' : formatRelativeTime(loadedAt, now)}
            </span>
            <div role="group" aria-label={label} className="flex flex-wrap items-center gap-2">
                <OpsButton icon={RefreshCw} busy={loading} onClick={onRefresh}>
                    {refreshLabel}
                </OpsButton>
                {children}
            </div>
        </div>
    );
}

/** The outcome of the last load or action, announced politely. */
export function OpsMessage({ message, children }: { message: ToneText | null; children?: ReactNode }) {
    if (!message) {
        return null;
    }
    const { className, Icon } = MESSAGE_TONE[message.tone];
    return (
        <div
            role="status"
            aria-live="polite"
            className={clsx('rounded-lg border px-3 py-2 text-xs leading-relaxed text-text-2', className)}
        >
            <div className="flex items-start gap-2">
                <Icon size={13} aria-hidden="true" className={clsx('mt-0.5 shrink-0', ICON_TONE[message.tone])} />
                <span className="min-w-0 break-words">{message.text}</span>
            </div>
            {children}
        </div>
    );
}

/** Standing context beneath a readout, such as where counters come from. */
export function OpsNote({ icon: Icon = Info, children }: { icon?: LucideIcon; children: ReactNode }) {
    return (
        <p className="flex items-start gap-2 text-xs leading-relaxed text-text-3">
            <Icon size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
            <span className="min-w-0">{children}</span>
        </p>
    );
}

/** A readout with nothing to show yet, and what would change that. */
export function OpsEmptyState({ title, children }: { title: string; children?: ReactNode }) {
    return (
        <div className="rounded-lg border border-dashed border-edge-strong bg-surface-1 px-4 py-5 text-center">
            <p className="text-sm font-medium text-text-1">{title}</p>
            {children ? (
                <div className="mx-auto mt-1 max-w-[60ch] text-xs leading-relaxed text-text-3">{children}</div>
            ) : null}
        </div>
    );
}

/** The heading and help a component field carries, laid out like a field's own. */
export function OpsHeading({ label, help }: { label: string; help?: string }) {
    return (
        <div>
            <p className="text-sm font-semibold text-text-1">{label}</p>
            {help ? <p className="mt-0.5 max-w-[80ch] text-[0.8125rem] leading-relaxed text-text-3">{help}</p> : null}
        </div>
    );
}

/** The live region every Scale component sits in, spaced like a field row. */
export function OpsPanel({ children, testId }: { children: ReactNode; testId?: string }) {
    return (
        <div data-testid={testId} className="min-w-0 space-y-3 py-3">
            {children}
        </div>
    );
}
