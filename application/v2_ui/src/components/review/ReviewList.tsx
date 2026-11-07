// ReviewList.tsx
// The list column of a Review center workbench: one-line rows, each with a checkbox for bulk
// actions and a button that opens the row in the detail pane.
//
// Drawn the way the Workflows workbench draws its list -- a sticky header, one line per row
// with its status at the end -- with a checkbox in front of each row. Up and Down move between
// rows, and Home and End go to the first and last, keeping to the control in focus: from a
// checkbox to the next row's checkbox, from a row to the next row. Only the current row's
// controls are in the tab order, so the list is one stop on the way through the page.
// Shift-clicking a checkbox selects the range from the last one checked.

import { useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Skeleton } from '../ui/primitives';
import { useIndeterminate } from './ReviewParts';

export interface ReviewListRow {
    id: string;
    title: string;
    meta: string;
    /** The row's state, drawn at its end. Decorative: the meta and the detail say it in words. */
    status: ReactNode;
}

export function ReviewList({
    label,
    columnLabel,
    statusLabel,
    rows,
    loading,
    empty,
    selectedId,
    onSelect,
    checkedIds,
    onToggleCheck,
    onToggleAll,
    footer,
    testIdPrefix,
}: {
    /** The list's accessible name, such as "Feedback". */
    label: string;
    columnLabel: string;
    statusLabel: string;
    rows: readonly ReviewListRow[];
    loading: boolean;
    /** Shown in place of rows when the page has none. */
    empty: ReactNode;
    selectedId: string | null;
    onSelect: (id: string) => void;
    checkedIds: readonly string[];
    onToggleCheck: (id: string, range: boolean) => void;
    onToggleAll: () => void;
    footer?: ReactNode;
    testIdPrefix: string;
}) {
    const [focusedId, setFocusedId] = useState<string | null>(null);
    const checked = new Set(checkedIds);
    const pageChecked = rows.length > 0 && rows.every((row) => checked.has(row.id));
    const somePageChecked = rows.some((row) => checked.has(row.id));
    const selectAllRef = useIndeterminate(pageChecked, somePageChecked);
    const tabStopId =
        (focusedId && rows.some((row) => row.id === focusedId) && focusedId)
        || (selectedId && rows.some((row) => row.id === selectedId) && selectedId)
        || rows[0]?.id;

    const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        const target = event.target as HTMLElement;
        const kind = target.dataset.reviewControl;
        if (kind !== 'row' && kind !== 'check') return;
        const controls = Array.from(
            event.currentTarget.querySelectorAll<HTMLElement>(`[data-review-control="${kind}"]`),
        );
        if (!controls.length) return;
        event.preventDefault();
        const index = controls.indexOf(target);
        const next = event.key === 'Home' ? 0
            : event.key === 'End' ? controls.length - 1
                : event.key === 'ArrowDown' ? Math.min(controls.length - 1, index + 1)
                    : Math.max(0, index - 1);
        controls[next]?.focus();
    };

    return (
        <div className="flex min-h-0 flex-col">
            <div className="sticky top-0 z-10 flex items-center gap-2.5 border-b border-edge-strong bg-surface-solid px-3 py-2 text-xs font-semibold text-text-2">
                <input
                    ref={selectAllRef}
                    type="checkbox"
                    aria-label="Select all on this page"
                    checked={pageChecked}
                    disabled={!rows.length}
                    onChange={onToggleAll}
                    data-testid={`${testIdPrefix}-select-page`}
                    className="h-4 w-4 shrink-0 accent-[var(--color-accent)]"
                />
                <span className="min-w-0 flex-1">{columnLabel}</span>
                <span>{statusLabel}</span>
            </div>
            {loading && !rows.length ? (
                <div role="status" className="space-y-2 p-3">
                    <span className="sr-only">Loading</span>
                    {Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-11 w-full" />)}
                </div>
            ) : rows.length ? (
                <ul aria-label={label} onKeyDown={onKeyDown} aria-busy={loading || undefined}>
                    {rows.map((row) => {
                        const isSelected = row.id === selectedId;
                        const isChecked = checked.has(row.id);
                        const tabIndex = row.id === tabStopId ? 0 : -1;
                        const metaId = `${testIdPrefix}-meta-${row.id}`;
                        return (
                            <li
                                key={row.id}
                                className={clsx(
                                    'flex items-center gap-2.5 border-b border-edge pl-3 transition-colors',
                                    isSelected ? 'bg-accent-soft ring-1 ring-accent/40 ring-inset' : 'hover:bg-surface-sunken',
                                )}
                            >
                                <input
                                    type="checkbox"
                                    data-review-control="check"
                                    aria-label={`Select ${row.title}`}
                                    checked={isChecked}
                                    tabIndex={tabIndex}
                                    onFocus={() => setFocusedId(row.id)}
                                    onChange={() => undefined}
                                    onClick={(event: MouseEvent<HTMLInputElement>) => onToggleCheck(row.id, event.shiftKey)}
                                    data-testid={`${testIdPrefix}-check-${row.id}`}
                                    className="h-4 w-4 shrink-0 accent-[var(--color-accent)]"
                                />
                                <button
                                    type="button"
                                    data-review-control="row"
                                    aria-pressed={isSelected}
                                    aria-label={row.title}
                                    aria-describedby={metaId}
                                    tabIndex={tabIndex}
                                    onFocus={() => setFocusedId(row.id)}
                                    onClick={() => onSelect(row.id)}
                                    data-testid={`${testIdPrefix}-row-${row.id}`}
                                    className="flex min-w-0 flex-1 items-center gap-2.5 py-2.5 pr-3 text-left"
                                >
                                    <span className="flex min-w-0 flex-1 flex-col">
                                        <span className={clsx('truncate text-sm font-semibold', isSelected ? 'text-accent' : 'text-text-1')}>
                                            {row.title}
                                        </span>
                                        <span id={metaId} className="truncate text-xs text-text-3">{row.meta}</span>
                                    </span>
                                    <span aria-hidden="true" className="inline-flex shrink-0 flex-wrap justify-end gap-1">
                                        {row.status}
                                    </span>
                                </button>
                            </li>
                        );
                    })}
                </ul>
            ) : (
                empty
            )}
            {footer}
        </div>
    );
}
