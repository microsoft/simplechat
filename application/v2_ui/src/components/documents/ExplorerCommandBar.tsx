// ExplorerCommandBar.tsx
// The command bar, filter chips and status bar.
//
// The classic interface stacks a search box, four metadata filters, a tag multi-select, a
// classification select, a shared-only checkbox, two buttons, a view switcher and two page
// size selects into one band above the list. This splits that into three: what you can *do*
// on top, what is currently *narrowing* the list beneath it, and where you *are* in the
// results at the bottom.
//
// The action group is selection-aware. Buttons that operate on documents are disabled with
// nothing selected rather than hidden, so the bar keeps its shape and the capability stays
// discoverable.

import { clsx } from 'clsx';
import {
    ArrowDown,
    ArrowUp,
    Bookmark,
    Columns3,
    Download,
    LayoutGrid,
    List,
    Loader2,
    MessageSquare,
    PanelRight,
    Search,
    SlidersHorizontal,
    Sparkles,
    Tag as TagIcon,
    Trash2,
    Upload,
    Users,
    X,
} from 'lucide-react';
import type { DocumentExplorerPrefs, DocumentQuery, DocumentSortField, WorkspaceDocument } from '../../lib/types';
import type { DocumentActionAvailability } from './DocumentDetailsPane';
import {
    DOCUMENT_PAGE_SIZES,
    describePage,
    paginationItems,
    type FilterChip,
} from '../../lib/documentExplorer';
import { GlassButton } from '../ui/primitives';
import { Dropdown } from '../ui/Dropdown';
import { DOCUMENT_COLUMNS } from './DocumentTable';

const SORT_LABELS: Record<DocumentSortField, string> = {
    _ts: 'Modified',
    file_name: 'File name',
    title: 'Title',
    upload_date: 'Uploaded',
    file_size: 'Size',
    number_of_pages: 'Pages',
    version: 'Version',
    document_classification: 'Classification',
};

export function ExplorerCommandBar({
    searchDraft,
    prefs,
    selectionCount,
    uploading,
    availability,
    canSaveView,
    onSearchChange,
    onSearchSubmit,
    onUpload,
    onDownload,
    onTag,
    onChat,
    onExtractMetadata,
    onDelete,
    onSaveView,
    onPrefsChange,
    query,
    sortFields,
    onSort,
    onShowFilters,
    selectedDocuments,
    onReview,
}: {
    /** What the user has typed. Distinct from `query.search`, which lags it by the debounce. */
    searchDraft: string;
    prefs: DocumentExplorerPrefs;
    selectionCount: number;
    uploading: boolean;
    availability: DocumentActionAvailability;
    selectedDocuments: WorkspaceDocument[];
    onReview?: () => void;
    canSaveView: boolean;
    onSearchChange: (value: string) => void;
    onSearchSubmit: (value: string) => void;
    onUpload: () => void;
    onDownload: () => void;
    onTag: () => void;
    onChat: () => void;
    onExtractMetadata: () => void;
    onDelete: () => void;
    onSaveView: () => void;
    onPrefsChange: (change: Partial<DocumentExplorerPrefs>) => void;
    query: DocumentQuery;
    sortFields: readonly DocumentSortField[];
    onSort: (field: DocumentSortField) => void;
    onShowFilters?: () => void;
}) {
    const hasSelection = selectionCount > 0;
    const canReview = Boolean(onReview && selectedDocuments.length === 1 && availability.canReview?.(selectedDocuments[0]));
    const compactActions = Boolean(onShowFilters && (
        availability.upload || availability.downloads || availability.tagDocuments
        || availability.extractMetadata || availability.deleteDocuments
    ));
    const actions = [
        { value: 'chat', label: 'Chat', visible: true, enabled: hasSelection && availability.chat, run: onChat },
        { value: 'download', label: 'Download', visible: availability.downloads, enabled: hasSelection && availability.allows('download', selectedDocuments), run: onDownload },
        { value: 'tag', label: 'Tag', visible: availability.tagDocuments, enabled: hasSelection && availability.allows('tag_documents', selectedDocuments), run: onTag },
        { value: 'extract', label: 'Extract', visible: availability.extractMetadata, enabled: hasSelection && availability.allows('extract_metadata', selectedDocuments), run: onExtractMetadata },
        { value: 'delete', label: 'Delete', visible: availability.deleteDocuments, enabled: hasSelection && availability.allows('delete', selectedDocuments), run: onDelete },
        { value: 'review', label: 'Review', visible: canReview, enabled: canReview, run: () => onReview?.() },
    ].filter((action) => action.visible);

    return (
        <div className="flex flex-wrap items-center gap-2 border-b border-edge px-1 pb-2">
            {availability.upload ? (
                <>
                    <GlassButton variant="primary" size="sm" onClick={onUpload} disabled={uploading || !availability.allows('upload')}>
                        <Upload size={14} />
                        Upload
                    </GlassButton>
                    {!compactActions ? <span aria-hidden="true" className="h-5 w-px bg-edge" /> : null}
                </>
            ) : null}

            {compactActions ? (
                <select aria-label="Document actions" value="" disabled={!actions.some((action) => action.enabled)}
                    onChange={(event) => {
                        const action = actions.find((entry) => entry.value === event.target.value);
                        if (action?.enabled) action.run();
                    }}
                    className="h-8 min-w-0 rounded-lg border border-edge bg-surface-1 px-2 text-sm text-text-2 disabled:opacity-50">
                    <option value="" disabled>Actions</option>
                    {actions.map((action) => <option key={action.value} value={action.value} disabled={!action.enabled}>{action.label}</option>)}
                </select>
            ) : <>
            {availability.downloads ? (
                <GlassButton
                    variant="ghost"
                    size="sm"
                    onClick={onDownload}
                    disabled={!hasSelection || !availability.allows('download', selectedDocuments)}
                    title={
                        selectionCount > 1
                            ? 'Download the selected documents as a ZIP'
                            : 'Download the selected document'
                    }
                >
                    <Download size={14} />
                    Download
                </GlassButton>
            ) : null}

            {availability.tagDocuments ? (
                <GlassButton variant="ghost" size="sm" onClick={onTag} disabled={!hasSelection || !availability.allows('tag_documents', selectedDocuments)}>
                    <TagIcon size={14} />
                    Tag
                </GlassButton>
            ) : null}

            <GlassButton variant={availability.upload ? 'ghost' : 'primary'} size="sm"
                onClick={onChat} disabled={!hasSelection || !availability.chat} title="Chat with selected documents">
                <MessageSquare size={14} />
                Chat
            </GlassButton>

            {availability.extractMetadata ? (
                <GlassButton
                    variant="ghost"
                    size="sm"
                    onClick={onExtractMetadata}
                    disabled={!hasSelection || !availability.allows('extract_metadata', selectedDocuments)}
                >
                    <Sparkles size={14} />
                    Extract
                </GlassButton>
            ) : null}

            {availability.deleteDocuments ? <GlassButton
                variant="ghost"
                size="sm"
                onClick={onDelete}
                disabled={!hasSelection || !availability.allows('delete', selectedDocuments)}
                className="hover:bg-danger-soft hover:text-danger"
            >
                <Trash2 size={14} />
                Delete
            </GlassButton> : null}
            {canReview ? <GlassButton variant="ghost" size="sm" onClick={onReview}>
                <Users size={14} />Sharing and review
            </GlassButton> : null}
            </>}

            {onShowFilters && !compactActions ? <GlassButton variant="ghost" size="sm" onClick={onShowFilters}>
                <SlidersHorizontal size={14} />Filters
            </GlassButton> : null}

            <div className="ml-auto flex min-w-0 flex-1 basis-full flex-wrap items-center gap-2 xl:basis-auto">
                <div className="flex min-w-0 grow basis-full items-center gap-1 sm:basis-44">
                    {compactActions && onShowFilters ? (
                        <button type="button" aria-label="Filters" title="Filters" onClick={onShowFilters}
                            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-edge bg-surface-1 text-text-2 hover:bg-surface-2">
                            <SlidersHorizontal size={14} />
                        </button>
                    ) : null}
                    <div className="relative min-w-0 flex-1">
                    <Search
                        size={14}
                        className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3"
                    />
                    <input
                        type="search"
                        // Bound to the draft, not to `query.search`. Binding a controlled
                        // input to the debounced value meant every keystroke was reverted
                        // until the debounce caught up, which is what dropped characters
                        // while typing at speed.
                        value={searchDraft}
                        onChange={(event) => onSearchChange(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault();
                                onSearchSubmit(event.currentTarget.value);
                            }
                            if (event.key === 'Escape') {
                                event.preventDefault();
                                onSearchSubmit('');
                            }
                        }}
                        placeholder="Search name or title"
                        aria-label="Search documents. Press Enter to search immediately."
                        className="h-8 w-full rounded-lg border border-edge bg-surface-1 pr-2 pl-7 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
                    </div>
                </div>

                {canSaveView ? (
                    <GlassButton
                        variant="ghost"
                        size="sm"
                        onClick={onSaveView}
                        title="Pin these filters to the rail as a saved view"
                    >
                        <Bookmark size={14} />
                        Save view
                    </GlassButton>
                ) : null}

                {sortFields.length > 0 ? (
                    <div className="flex items-center gap-1">
                        <select aria-label="Sort documents" value={query.sortBy}
                            onChange={(event) => {
                                const field = sortFields.find((entry) => entry === event.target.value);
                                if (field) onSort(field);
                            }}
                            className="h-8 max-w-36 rounded-lg border border-edge bg-surface-1 px-2 text-xs text-text-2">
                            {sortFields.map((field) => <option key={field} value={field}>{SORT_LABELS[field]}</option>)}
                        </select>
                        <button type="button" onClick={() => onSort(query.sortBy)}
                            aria-label={`Sort ${query.sortOrder === 'asc' ? 'descending' : 'ascending'}`}
                            className="rounded-lg border border-edge p-1.5 text-text-2 hover:bg-surface-2">
                            {query.sortOrder === 'asc' ? <ArrowUp size={15} /> : <ArrowDown size={15} />}
                        </button>
                    </div>
                ) : null}

                <Dropdown
                    compact
                    align="right"
                    icon={<Columns3 size={15} />}
                    placeholder="Columns"
                    options={DOCUMENT_COLUMNS.filter((column) => column.id !== 'name').map(
                        (column) => ({
                            value: column.id,
                            label: prefs.columns.includes(column.id)
                                ? `✓ ${column.label}`
                                : column.label,
                        }),
                    )}
                    onChange={(value) => {
                        if (!value) {
                            return;
                        }
                        onPrefsChange({
                            columns: prefs.columns.includes(value)
                                ? prefs.columns.filter((column) => column !== value)
                                : [...prefs.columns, value],
                        });
                    }}
                />

                <div
                    role="group"
                    aria-label="View mode"
                    className="flex items-center rounded-lg border border-edge"
                >
                    {(
                        [
                            { mode: 'details', icon: List, label: 'Details view' },
                            { mode: 'tiles', icon: LayoutGrid, label: 'Tiles view' },
                        ] as const
                    ).map(({ mode, icon: Icon, label }) => (
                        <button
                            key={mode}
                            type="button"
                            onClick={() => onPrefsChange({ viewMode: mode })}
                            aria-label={label}
                            aria-pressed={prefs.viewMode === mode}
                            title={label}
                            className={clsx(
                                'p-1.5 transition-colors first:rounded-l-md last:rounded-r-md',
                                prefs.viewMode === mode
                                    ? 'bg-accent-soft text-accent'
                                    : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
                            )}
                        >
                            <Icon size={15} />
                        </button>
                    ))}
                </div>

                <button
                    type="button"
                    onClick={() => onPrefsChange({ detailsPaneOpen: !prefs.detailsPaneOpen })}
                    aria-label="Toggle details pane"
                    aria-pressed={prefs.detailsPaneOpen}
                    title="Toggle details pane"
                    className={clsx(
                        'rounded-lg border border-edge p-1.5 transition-colors',
                        prefs.detailsPaneOpen
                            ? 'bg-accent-soft text-accent'
                            : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
                    )}
                >
                    <PanelRight size={15} />
                </button>
            </div>
        </div>
    );
}

/**
 * A determinate progress bar for a bulk operation.
 *
 * Determinate rather than a spinner because these operations are genuinely slow: tagging
 * updates each document *and* its search-index chunks, so a large selection takes long enough
 * that an indeterminate "Working…" is indistinguishable from a hang. Saying "14 of 50" is the
 * difference between waiting and giving up.
 */
export function ExplorerProgress({
    task,
}: {
    task: { label: string; completed: number; total: number };
}) {
    const total = Math.max(1, task.total);
    const percent = Math.min(100, Math.round((task.completed / total) * 100));

    return (
        <div
            className="flex items-center gap-2.5 border-b border-edge px-3 py-2"
            role="status"
            aria-live="polite"
        >
            <Loader2 size={13} className="shrink-0 animate-spin text-accent" />
            <span className="shrink-0 text-xs text-text-2">{task.label}</span>
            <span
                className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-sunken"
                role="progressbar"
                aria-valuenow={task.completed}
                aria-valuemin={0}
                aria-valuemax={task.total}
                aria-label={task.label}
            >
                <span
                    className="block h-full rounded-full bg-accent transition-[width] duration-200"
                    style={{ width: `${percent}%` }}
                />
            </span>
            <span className="shrink-0 text-xs tabular-nums text-text-3">
                {task.completed} of {task.total}
            </span>
        </div>
    );
}

export function FilterChips({
    chips,
    onClearChip,
    onClearAll,
}: {
    chips: FilterChip[];
    onClearChip: (chip: FilterChip) => void;
    onClearAll: () => void;
}) {
    if (chips.length === 0) {
        return null;
    }

    return (
        <div className="flex flex-wrap items-center gap-1.5 px-1 py-2">
            <span className="text-[11px] text-text-3">Filtered by</span>
            {chips.map((chip) => (
                <button
                    key={`${chip.kind}:${chip.value}`}
                    type="button"
                    onClick={() => onClearChip(chip)}
                    className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent transition-opacity hover:opacity-80"
                >
                    <span className="max-w-[14rem] truncate">{chip.label}</span>
                    <X size={11} />
                </button>
            ))}
            <button
                type="button"
                onClick={onClearAll}
                className="text-[11px] text-text-3 underline-offset-2 hover:text-text-1 hover:underline"
            >
                Clear all
            </button>
        </div>
    );
}

export function ExplorerStatusBar({
    page,
    pageSize,
    totalCount,
    selectionCount,
    onPageChange,
    onPageSizeChange,
}: {
    page: number;
    pageSize: number;
    totalCount: number;
    selectionCount: number;
    onPageChange: (page: number) => void;
    onPageSizeChange: (pageSize: number) => void;
}) {
    const range = describePage(page, pageSize, totalCount);
    const items = paginationItems(page, range.pageCount);

    return (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-edge px-1 pt-2 text-xs text-text-3">
            <p>
                {range.total === 0
                    ? 'No documents'
                    : `${range.from}\u2013${range.to} of ${range.total}`}
                {selectionCount > 0 ? ` · ${selectionCount} selected` : ''}
            </p>

            <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
                {range.pageCount > 1 ? (
                    <nav aria-label="Pagination" className="flex max-w-full flex-wrap items-center gap-0.5">
                        <button
                            type="button"
                            onClick={() => onPageChange(page - 1)}
                            disabled={page <= 1}
                            className="rounded px-2 py-1 hover:bg-surface-2 hover:text-text-1 disabled:opacity-40 disabled:hover:bg-transparent"
                        >
                            Prev
                        </button>
                        {items.map((item, index) =>
                            item === null ? (
                                <span key={`gap-${index}`} className="px-1">
                                    …
                                </span>
                            ) : (
                                <button
                                    key={item}
                                    type="button"
                                    onClick={() => onPageChange(item)}
                                    aria-current={item === page ? 'page' : undefined}
                                    className={clsx(
                                        'min-w-[1.75rem] rounded px-1.5 py-1 tabular-nums',
                                        item === page
                                            ? 'bg-accent-soft font-medium text-accent'
                                            : 'hover:bg-surface-2 hover:text-text-1',
                                    )}
                                >
                                    {item}
                                </button>
                            ),
                        )}
                        <button
                            type="button"
                            onClick={() => onPageChange(page + 1)}
                            disabled={page >= range.pageCount}
                            className="rounded px-2 py-1 hover:bg-surface-2 hover:text-text-1 disabled:opacity-40 disabled:hover:bg-transparent"
                        >
                            Next
                        </button>
                    </nav>
                ) : null}

                <label className="flex items-center gap-1">
                    <span className="sr-only">Documents per page</span>
                    <select
                        aria-label="Documents per page"
                        value={pageSize}
                        onChange={(event) => onPageSizeChange(Number(event.target.value))}
                        className="rounded border border-edge bg-surface-1 px-1.5 py-1 text-xs text-text-2 focus:border-accent focus:outline-none"
                    >
                        {DOCUMENT_PAGE_SIZES.map((size) => (
                            <option key={size} value={size}>
                                {size} per page
                            </option>
                        ))}
                    </select>
                </label>
            </div>
        </div>
    );
}
