// ApprovalParts.tsx
// Small building blocks shared by every Approvals panel: the list/detail split, status
// badges, fact rows, notices, and list filters.

import type { ReactNode } from 'react';
import { clsx } from 'clsx';
import { ArrowLeft, Search } from 'lucide-react';

/**
 * The center list and right-hand detail of one Approvals category.
 *
 * On wide screens both are visible side by side. On narrow screens only one is: the list,
 * or the selected item's detail with a way back to the list.
 */
export function ApprovalSplit({
    list,
    detail,
    hasSelection,
    onBack,
    listLabel,
}: {
    list: ReactNode;
    detail: ReactNode;
    hasSelection: boolean;
    onBack: () => void;
    listLabel: string;
}) {
    return (
        <div className="flex min-h-0 flex-1">
            <section
                aria-label={listLabel}
                data-testid="v2-approvals-list"
                className={clsx(
                    'min-h-0 w-full shrink-0 flex-col overflow-y-auto border-edge lg:flex lg:w-[26rem] lg:border-r',
                    hasSelection ? 'hidden' : 'flex',
                )}
            >
                {list}
            </section>
            <section
                aria-label="Request details"
                data-testid="v2-approvals-detail"
                className={clsx('min-h-0 min-w-0 flex-1 flex-col overflow-y-auto lg:flex', hasSelection ? 'flex' : 'hidden')}
            >
                {hasSelection ? (
                    <div className="border-b border-edge px-4 py-2 lg:hidden">
                        <button
                            type="button"
                            onClick={onBack}
                            className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm text-text-2 hover:bg-surface-2 hover:text-text-1"
                        >
                            <ArrowLeft size={15} aria-hidden="true" />
                            Back to list
                        </button>
                    </div>
                ) : null}
                {detail}
            </section>
        </div>
    );
}

const STATUS_TONES: Record<string, string> = {
    pending: 'bg-warn-soft text-warn',
    scheduled: 'bg-warn-soft text-warn',
    review_required: 'bg-warn-soft text-warn',
    awaiting_approval: 'bg-warn-soft text-warn',
    awaiting_sign_in: 'bg-warn-soft text-warn',
    ready_to_resume: 'bg-accent-soft text-accent',
    approved: 'bg-ok-soft text-ok',
    executed: 'bg-info-soft text-info',
    sent: 'bg-ok-soft text-ok',
    denied: 'bg-danger-soft text-danger',
    rejected: 'bg-danger-soft text-danger',
    failed: 'bg-danger-soft text-danger',
    recovery_required: 'bg-danger-soft text-danger',
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
    const text = label ?? (status ? status.replace(/_/g, ' ') : 'unknown');
    return (
        <span
            data-status={status}
            className={clsx(
                'inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize',
                STATUS_TONES[status] ?? 'bg-surface-2 text-text-2',
            )}
        >
            {text}
        </span>
    );
}

export function Facts({ children }: { children: ReactNode }) {
    return <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-[minmax(9rem,auto)_1fr]">{children}</dl>;
}

/** One labelled value. Renders nothing for an empty value so the list stays meaningful. */
export function Fact({ label, children }: { label: string; children: ReactNode }) {
    if (children === null || children === undefined || children === '' || children === false) return null;
    return (
        <>
            <dt className="text-xs font-medium tracking-wide text-text-3 uppercase sm:pt-0.5">{label}</dt>
            <dd className="min-w-0 break-words text-text-1">{children}</dd>
        </>
    );
}

export function Notice({
    tone = 'info',
    children,
    testId,
}: {
    tone?: 'info' | 'warn' | 'danger' | 'ok';
    children: ReactNode;
    testId?: string;
}) {
    return (
        <div
            role={tone === 'danger' ? 'alert' : 'status'}
            data-testid={testId}
            className={clsx('rounded-xl px-3 py-2 text-sm', {
                'bg-info-soft text-text-1': tone === 'info',
                'bg-warn-soft text-text-1': tone === 'warn',
                'bg-danger-soft text-danger': tone === 'danger',
                'bg-ok-soft text-text-1': tone === 'ok',
            })}
        >
            {children}
        </div>
    );
}

export function DetailEmpty({ title, description }: { title: string; description?: string }) {
    return (
        <div className="flex flex-1 items-center justify-center p-8 text-center" data-testid="v2-approvals-detail-empty">
            <div className="max-w-sm">
                <p className="text-sm font-medium text-text-1">{title}</p>
                {description ? <p className="mt-1 text-sm text-text-3">{description}</p> : null}
            </div>
        </div>
    );
}

export function DetailShell({
    title,
    subtitle,
    badge,
    children,
}: {
    title: string;
    subtitle?: ReactNode;
    badge?: ReactNode;
    children: ReactNode;
}) {
    return (
        <article className="mx-auto w-full max-w-3xl space-y-5 p-4 lg:p-6">
            <header className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                    <h2 className="text-lg font-semibold break-words text-text-1">{title}</h2>
                    {subtitle ? <p className="mt-0.5 text-sm text-text-3">{subtitle}</p> : null}
                </div>
                {badge}
            </header>
            {children}
        </article>
    );
}

export const fieldClass =
    'w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 disabled:opacity-60';

export function ListToolbar({
    search,
    onSearch,
    searchLabel,
    children,
}: {
    search: string;
    onSearch: (value: string) => void;
    searchLabel: string;
    children?: ReactNode;
}) {
    return (
        <div className="sticky top-0 z-10 space-y-2 border-b border-edge bg-surface-1 p-3">
            <div className="relative">
                <Search
                    size={15}
                    aria-hidden="true"
                    className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                />
                <input
                    type="search"
                    value={search}
                    onChange={(event) => onSearch(event.target.value)}
                    placeholder={searchLabel}
                    aria-label={searchLabel}
                    data-testid="v2-approvals-search"
                    className={clsx(fieldClass, 'pl-9')}
                />
            </div>
            {children ? <div className="flex flex-wrap gap-2">{children}</div> : null}
        </div>
    );
}

export function ListSelect({
    label,
    value,
    onChange,
    options,
    testId,
}: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    options: Array<[string, string]>;
    testId?: string;
}) {
    return (
        <select
            aria-label={label}
            value={value}
            data-testid={testId}
            onChange={(event) => onChange(event.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-edge bg-surface-1 px-2 py-1.5 text-xs text-text-1"
        >
            {options.map(([optionValue, optionLabel]) => (
                <option key={optionValue} value={optionValue}>
                    {optionLabel}
                </option>
            ))}
        </select>
    );
}

export function ListRow({
    active,
    onSelect,
    title,
    meta,
    badge,
    testId,
}: {
    active: boolean;
    onSelect: () => void;
    title: string;
    meta?: ReactNode;
    badge?: ReactNode;
    testId?: string;
}) {
    return (
        <li>
            <button
                type="button"
                aria-current={active ? 'true' : undefined}
                data-testid={testId}
                onClick={onSelect}
                className={clsx(
                    'flex w-full items-start gap-3 border-b border-edge px-4 py-3 text-left transition-colors',
                    active ? 'bg-accent-soft' : 'hover:bg-surface-2',
                )}
            >
                <div className="min-w-0 flex-1">
                    <p className={clsx('truncate text-sm font-medium', active ? 'text-accent' : 'text-text-1')}>{title}</p>
                    {meta ? <div className="mt-0.5 truncate text-xs text-text-3">{meta}</div> : null}
                </div>
                {badge}
            </button>
        </li>
    );
}

export function ListMessage({ children }: { children: ReactNode }) {
    return <p className="px-4 py-6 text-center text-sm text-text-3">{children}</p>;
}

export function ListPager({
    page,
    pageCount,
    total,
    onPage,
}: {
    page: number;
    pageCount: number;
    total: number;
    onPage: (page: number) => void;
}) {
    if (pageCount <= 1) {
        return total ? <p className="px-4 py-3 text-xs text-text-3">{`${total} ${total === 1 ? 'request' : 'requests'}`}</p> : null;
    }
    return (
        <nav aria-label="Pages" className="flex items-center justify-between gap-2 px-4 py-3 text-xs text-text-3">
            <button
                type="button"
                disabled={page <= 1}
                onClick={() => onPage(page - 1)}
                className="rounded-lg px-2 py-1 hover:bg-surface-2 hover:text-text-1 disabled:opacity-40"
            >
                Previous
            </button>
            <span>{`Page ${page} of ${pageCount} · ${total} requests`}</span>
            <button
                type="button"
                disabled={page >= pageCount}
                onClick={() => onPage(page + 1)}
                className="rounded-lg px-2 py-1 hover:bg-surface-2 hover:text-text-1 disabled:opacity-40"
            >
                Next
            </button>
        </nav>
    );
}
