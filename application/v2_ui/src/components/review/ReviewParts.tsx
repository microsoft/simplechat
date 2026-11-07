// ReviewParts.tsx
// Small pieces the Review center's dashboards, workbenches and editors share: tone badges,
// notices, labelled filter selects, the pager, the filter chips a dashboard link leaves on a
// list, and the ARIA tabs of a record's detail.

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Search, X } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { REVIEW_PAGE_SIZES, type ReviewTone } from '../../lib/reviewCenter';

const TONE_CLASS: Readonly<Record<ReviewTone, string>> = {
    ok: 'bg-ok-soft text-ok',
    warn: 'bg-warn-soft text-warn',
    danger: 'bg-danger-soft text-danger',
    info: 'bg-info-soft text-info',
    neutral: 'bg-surface-2 text-text-2',
    accent: 'bg-accent-soft text-accent',
};

export function ToneBadge({ tone, children, testId }: { tone: ReviewTone; children: ReactNode; testId?: string }) {
    return (
        <span
            data-testid={testId}
            className={clsx(
                'inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] leading-tight font-medium whitespace-nowrap',
                TONE_CLASS[tone],
            )}
        >
            {children}
        </span>
    );
}

export function ReviewNotice({
    tone = 'info',
    children,
    testId,
}: {
    tone?: 'info' | 'ok' | 'warn' | 'danger';
    children: ReactNode;
    testId?: string;
}) {
    return (
        <div
            role={tone === 'danger' ? 'alert' : 'status'}
            data-testid={testId}
            className={clsx('rounded-xl border px-3 py-2 text-sm', {
                'border-info/30 bg-info-soft text-text-1': tone === 'info',
                'border-ok/30 bg-ok-soft text-text-1': tone === 'ok',
                'border-warn/30 bg-warn-soft text-text-1': tone === 'warn',
                'border-danger/30 bg-danger-soft text-danger': tone === 'danger',
            })}
        >
            {children}
        </div>
    );
}

const SELECT_CLASS = clsx(
    'min-h-9 min-w-0 max-w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1',
    'focus:border-accent focus:outline-none',
);

export function FilterSelect<T extends string>({
    label,
    value,
    options,
    onChange,
    testId,
}: {
    label: string;
    value: T;
    options: ReadonlyArray<readonly [T, string]>;
    onChange: (value: T) => void;
    testId?: string;
}) {
    // Labelled by reference rather than by wrapping, so the select's name is the label alone.
    const id = useId();
    return (
        <div className="flex max-w-full min-w-0 items-center gap-2">
            <label htmlFor={id} className="text-xs font-medium text-text-2">{label}</label>
            <select
                id={id}
                className={SELECT_CLASS}
                value={value}
                data-testid={testId}
                onChange={(event) => onChange(event.target.value as T)}
            >
                {options.map(([option, optionLabel]) => <option key={option} value={option}>{optionLabel}</option>)}
            </select>
        </div>
    );
}

export interface FilterChip {
    key: string;
    label: string;
    onRemove: () => void;
}

/**
 * The search box of a workbench. What is typed is sent once typing pauses, so the address
 * and the list follow the search without a request for every key.
 */
export function ReviewSearch({
    value,
    onCommit,
    label,
    testId,
}: {
    value: string;
    onCommit: (value: string) => void;
    label: string;
    testId?: string;
}) {
    const [draft, setDraft] = useState(value);
    const commit = useRef(onCommit);
    commit.current = onCommit;

    useEffect(() => setDraft(value), [value]);
    useEffect(() => {
        if (draft === value) return undefined;
        const timer = window.setTimeout(() => commit.current(draft), 350);
        return () => window.clearTimeout(timer);
    }, [draft, value]);

    return (
        <div className="relative min-w-[min(100%,16rem)] flex-1">
            <Search size={15} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3" />
            <input
                type="search"
                value={draft}
                maxLength={200}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === 'Enter') commit.current(draft);
                }}
                placeholder={label}
                aria-label={label}
                data-testid={testId}
                className="w-full rounded-xl border border-edge bg-surface-1 py-2 pr-3 pl-9 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
            />
        </div>
    );
}

/** The narrower filters a dashboard link applied, each removable on its own. */
export function FilterChips({ chips }: { chips: readonly FilterChip[] }) {
    if (!chips.length) return null;
    return (
        <ul className="flex flex-wrap gap-1.5" aria-label="Applied filters">
            {chips.map((chip) => (
                <li key={chip.key}>
                    <button
                        type="button"
                        onClick={chip.onRemove}
                        className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-1 text-xs text-accent hover:bg-accent hover:text-on-accent"
                    >
                        {chip.label}
                        <X size={12} aria-hidden="true" />
                        <span className="sr-only">Remove filter</span>
                    </button>
                </li>
            ))}
        </ul>
    );
}

export function ReviewPager({
    page,
    pageSize,
    total,
    loading,
    noun,
    onPage,
    onPageSize,
}: {
    page: number;
    pageSize: number;
    total: number;
    loading: boolean;
    noun: string;
    onPage: (page: number) => void;
    onPageSize: (size: number) => void;
}) {
    const pageCount = Math.max(1, Math.ceil(total / pageSize));
    const sizeId = useId();
    return (
        <nav aria-label="Pages" className="flex flex-wrap items-center justify-between gap-2 border-t border-edge-strong px-3 py-2 text-xs text-text-3">
            <span>{total ? `Page ${Math.min(page, pageCount)} of ${pageCount} · ${total.toLocaleString()} ${noun}` : `No ${noun}`}</span>
            <div className="flex items-center gap-2">
                <label htmlFor={sizeId} className="sr-only">Rows per page</label>
                <select
                    id={sizeId}
                    value={pageSize}
                    onChange={(event) => onPageSize(Number(event.target.value))}
                    className="rounded-lg border border-edge bg-surface-1 px-1.5 py-1 text-text-1"
                >
                    {REVIEW_PAGE_SIZES.map((size) => <option key={size} value={size}>{size} per page</option>)}
                </select>
                <GlassButton type="button" size="sm" disabled={page <= 1 || loading} onClick={() => onPage(page - 1)}>Previous</GlassButton>
                <GlassButton type="button" size="sm" disabled={page >= pageCount || loading} onClick={() => onPage(page + 1)}>Next</GlassButton>
            </div>
        </nav>
    );
}

/** A labelled read-only fact in a detail pane or editor. Nothing is drawn for an empty value. */
export function ReviewFact({ label, children }: { label: string; children: ReactNode }) {
    if (children === null || children === undefined || children === '' || children === false) return null;
    return (
        <div className="py-2.5">
            <dt className="text-xs font-semibold text-text-3">{label}</dt>
            <dd className="mt-1 min-w-0 text-sm break-words whitespace-pre-wrap text-text-1">{children}</dd>
        </div>
    );
}

/** Long text, such as a prompt or an AI response, in a bounded scroll box. */
export function ReviewTextBlock({ label, text, empty, testId }: { label: string; text?: string | null; empty: string; testId?: string }) {
    return (
        <div>
            <h4 className="text-xs font-semibold text-text-3">{label}</h4>
            <p
                data-testid={testId}
                className="mt-1 max-h-64 overflow-y-auto rounded-lg bg-surface-2 p-3 text-sm break-words whitespace-pre-wrap text-text-1"
            >
                {text || empty}
            </p>
        </div>
    );
}

export interface ReviewTab<T extends string> {
    id: T;
    label: string;
}

/**
 * The tabs of a selected record's detail, drawn as the Workflows workbench draws them: arrow
 * keys move between tabs, and the panel below scrolls on its own.
 */
export function ReviewDetailTabs<T extends string>({
    label,
    tabs,
    active,
    onChange,
    children,
}: {
    label: string;
    tabs: readonly ReviewTab<T>[];
    active: T;
    onChange: (tab: T) => void;
    children: ReactNode;
}) {
    const baseId = useId();
    const refs = useRef<Partial<Record<T, HTMLButtonElement | null>>>({});
    const shown = tabs.some((tab) => tab.id === active) ? active : tabs[0]?.id;

    const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || !tabs.length) return;
        event.preventDefault();
        const index = tabs.findIndex((tab) => tab.id === shown);
        const next = event.key === 'Home' ? 0
            : event.key === 'End' ? tabs.length - 1
                : event.key === 'ArrowRight' ? (index + 1) % tabs.length
                    : (index - 1 + tabs.length) % tabs.length;
        onChange(tabs[next].id);
        refs.current[tabs[next].id]?.focus();
    };

    return (
        <>
            <div
                role="tablist"
                aria-label={label}
                onKeyDown={onKeyDown}
                className="sticky top-0 z-10 flex gap-1 overflow-x-auto border-y border-edge-strong bg-surface-solid px-4 sm:px-5"
            >
                {tabs.map((tab) => {
                    const selected = tab.id === shown;
                    return (
                        <button
                            key={tab.id}
                            ref={(element) => {
                                refs.current[tab.id] = element;
                            }}
                            id={`${baseId}-tab-${tab.id}`}
                            type="button"
                            role="tab"
                            aria-selected={selected}
                            aria-controls={`${baseId}-panel`}
                            tabIndex={selected ? 0 : -1}
                            onClick={() => onChange(tab.id)}
                            className={clsx(
                                '-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm transition-colors',
                                selected
                                    ? 'border-accent font-semibold text-accent'
                                    : 'border-transparent text-text-2 hover:text-text-1',
                            )}
                        >
                            {tab.label}
                        </button>
                    );
                })}
            </div>
            <div
                id={`${baseId}-panel`}
                role="tabpanel"
                aria-labelledby={`${baseId}-tab-${shown}`}
                tabIndex={0}
                className="flex-1 px-4 py-4 sm:px-5"
            >
                {children}
            </div>
        </>
    );
}

/** Keeps a checkbox's indeterminate state in step, which has no attribute of its own. */
export function useIndeterminate(checked: boolean, partial: boolean) {
    const ref = useRef<HTMLInputElement>(null);
    useEffect(() => {
        if (ref.current) ref.current.indeterminate = partial && !checked;
    }, [checked, partial]);
    return ref;
}
