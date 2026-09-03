// primitives.tsx
// Shared building blocks for the personal workspace sections.
//
// The eight sections list very different things, but they all list *something*, and each
// one having its own idea of a row, a spinner and an empty state is how a page stops
// feeling like one page. These carry that shape so a section only supplies what is
// genuinely specific to it.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, Search } from 'lucide-react';
import type { ReactNode } from 'react';
import { EmptyState, GlassPanel, Skeleton } from '../ui/primitives';

export function SectionIntro({
    title,
    description,
    actions,
}: {
    title: string;
    description: string;
    actions?: ReactNode;
}) {
    return (
        <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
                <h2 className="text-base font-semibold text-text-1">{title}</h2>
                <p className="mt-0.5 max-w-2xl text-sm text-text-3">{description}</p>
            </div>
            {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </div>
    );
}

export function SectionSearch({
    value,
    onChange,
    placeholder,
}: {
    value: string;
    onChange: (next: string) => void;
    placeholder: string;
}) {
    return (
        <div className="relative">
            <Search
                size={15}
                className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
            />
            <input
                type="search"
                value={value}
                onChange={(event) => onChange(event.target.value)}
                placeholder={placeholder}
                aria-label={placeholder}
                className="w-full rounded-xl border border-edge bg-surface-1 py-2 pr-3 pl-9 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
            />
        </div>
    );
}

export function SectionError({ message }: { message: string }) {
    return (
        <GlassPanel elevation="flat" className="p-3 text-sm text-danger" role="alert">
            {message}
        </GlassPanel>
    );
}

export function SectionSkeleton({ rows = 4 }: { rows?: number }) {
    return (
        <div className="space-y-2">
            {Array.from({ length: rows }).map((_, index) => (
                <Skeleton key={index} className="h-14 w-full" />
            ))}
        </div>
    );
}

/**
 * The list body of a section: skeleton, error, empty state or rows.
 *
 * The error is rendered above the rows rather than instead of them, which matters for the
 * delete flows: they put the list back as it was and then report why, and replacing the
 * list would hide the very rows the message refers to.
 */
export function SectionList<T>({
    items,
    loading,
    error,
    emptyIcon,
    emptyTitle,
    emptyDescription,
    emptyAction,
    getKey,
    renderItem,
}: {
    items: T[];
    loading: boolean;
    error?: string | null;
    emptyIcon?: ReactNode;
    emptyTitle: string;
    emptyDescription?: string;
    emptyAction?: ReactNode;
    getKey: (item: T, index: number) => string;
    renderItem: (item: T) => ReactNode;
}) {
    return (
        <div className="space-y-3">
            {error ? <SectionError message={error} /> : null}

            {loading ? <SectionSkeleton /> : null}

            {!loading && items.length === 0 ? (
                <EmptyState
                    icon={emptyIcon}
                    title={emptyTitle}
                    description={emptyDescription}
                    action={emptyAction}
                />
            ) : null}

            {items.length > 0 ? (
                <ul className="space-y-2">
                    {items.map((item, index) => (
                        <li key={getKey(item, index)}>{renderItem(item)}</li>
                    ))}
                </ul>
            ) : null}
        </div>
    );
}

export function ResourceRow({
    icon,
    title,
    subtitle,
    meta,
    actions,
}: {
    icon?: ReactNode;
    title: ReactNode;
    subtitle?: ReactNode;
    meta?: ReactNode;
    actions?: ReactNode;
}) {
    return (
        <GlassPanel elevation="flat" className="flex items-center gap-3 p-3">
            {icon ? <span className="shrink-0 text-text-3">{icon}</span> : null}
            <div className="min-w-0 flex-1">
                <div className="truncate text-sm text-text-1">{title}</div>
                {subtitle ? (
                    <div className="mt-0.5 truncate text-xs text-text-3">{subtitle}</div>
                ) : null}
            </div>
            {meta ? <div className="flex shrink-0 items-center gap-2">{meta}</div> : null}
            {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
        </GlassPanel>
    );
}

export function Pill({
    children,
    tone = 'neutral',
}: {
    children: ReactNode;
    tone?: 'neutral' | 'ok' | 'warn' | 'danger' | 'accent';
}) {
    const toneClass = {
        neutral: 'bg-surface-2 text-text-2',
        ok: 'bg-ok-soft text-ok',
        warn: 'bg-warn-soft text-warn',
        danger: 'bg-danger-soft text-danger',
        accent: 'bg-accent-soft text-accent',
    }[tone];

    return (
        <span
            className={clsx(
                'rounded-full px-2 py-0.5 text-[11px] leading-none font-medium whitespace-nowrap',
                toneClass,
            )}
        >
            {children}
        </span>
    );
}

export function RowAction({
    icon,
    label,
    onClick,
    disabled = false,
    busy = false,
    danger = false,
}: {
    icon: ReactNode;
    label: string;
    onClick: () => void;
    disabled?: boolean;
    busy?: boolean;
    danger?: boolean;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled || busy}
            aria-label={label}
            title={label}
            className={clsx(
                'rounded-lg p-1.5 transition-colors disabled:cursor-not-allowed disabled:opacity-40',
                danger
                    ? 'text-text-3 hover:bg-danger-soft hover:text-danger'
                    : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
            )}
        >
            {busy ? <Loader2 size={15} className="animate-spin" /> : icon}
        </button>
    );
}

/**
 * A destructive action that asks first, in place.
 *
 * A native confirm() dialog would do, but it stops the whole tab and reads as a browser
 * warning rather than as part of the page. Arming the button keeps the question next to the
 * row it refers to, and it disarms itself so a button left armed cannot be triggered later
 * by a stray click.
 */
export function ConfirmAction({
    icon,
    label,
    confirmLabel,
    onConfirm,
    busy = false,
    disabled = false,
}: {
    icon: ReactNode;
    label: string;
    confirmLabel: string;
    onConfirm: () => void;
    busy?: boolean;
    disabled?: boolean;
}) {
    const [armed, setArmed] = useState(false);
    const timer = useRef<number | undefined>(undefined);

    useEffect(() => {
        if (!armed) {
            return;
        }
        timer.current = window.setTimeout(() => setArmed(false), 4000);
        return () => window.clearTimeout(timer.current);
    }, [armed]);

    if (!armed) {
        return (
            <RowAction
                icon={icon}
                label={label}
                onClick={() => setArmed(true)}
                busy={busy}
                disabled={disabled}
                danger
            />
        );
    }

    return (
        <button
            type="button"
            onClick={() => {
                setArmed(false);
                onConfirm();
            }}
            disabled={busy}
            className="rounded-lg bg-danger-soft px-2 py-1 text-[11px] font-semibold text-danger transition-colors hover:bg-danger hover:text-white disabled:opacity-50"
        >
            {busy ? 'Working' : confirmLabel}
        </button>
    );
}
