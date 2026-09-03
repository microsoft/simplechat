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
    Bookmark,
    Columns3,
    Download,
    LayoutGrid,
    List,
    MessageSquare,
    PanelRight,
    Search,
    Sparkles,
    Tag as TagIcon,
    Trash2,
    Upload,
    X,
} from 'lucide-react';
import type { DocumentExplorerPrefs, DocumentQuery } from '../../lib/types';
import {
    DOCUMENT_PAGE_SIZES,
    describePage,
    paginationItems,
    type FilterChip,
} from '../../lib/documentExplorer';
import { GlassButton } from '../ui/primitives';
import { Dropdown } from '../ui/Dropdown';
import { DOCUMENT_COLUMNS } from './DocumentTable';

export function ExplorerCommandBar({
    query,
    prefs,
    selectionCount,
    uploading,
    availability,
    canSaveView,
    onSearchChange,
    onUpload,
    onDownload,
    onTag,
    onChat,
    onExtractMetadata,
    onDelete,
    onSaveView,
    onPrefsChange,
}: {
    query: DocumentQuery;
    prefs: DocumentExplorerPrefs;
    selectionCount: number;
    uploading: boolean;
    availability: { downloads: boolean; extractMetadata: boolean };
    canSaveView: boolean;
    onSearchChange: (value: string) => void;
    onUpload: () => void;
    onDownload: () => void;
    onTag: () => void;
    onChat: () => void;
    onExtractMetadata: () => void;
    onDelete: () => void;
    onSaveView: () => void;
    onPrefsChange: (change: Partial<DocumentExplorerPrefs>) => void;
}) {
    const hasSelection = selectionCount > 0;

    return (
        <div className="flex flex-wrap items-center gap-2 border-b border-edge px-1 pb-2">
            <GlassButton variant="primary" size="sm" onClick={onUpload} disabled={uploading}>
                <Upload size={14} />
                Upload
            </GlassButton>

            <span aria-hidden="true" className="h-5 w-px bg-edge" />

            {availability.downloads ? (
                <GlassButton
                    variant="ghost"
                    size="sm"
                    onClick={onDownload}
                    disabled={!hasSelection}
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

            <GlassButton variant="ghost" size="sm" onClick={onTag} disabled={!hasSelection}>
                <TagIcon size={14} />
                Tag
            </GlassButton>

            <GlassButton variant="ghost" size="sm" onClick={onChat} disabled={!hasSelection}>
                <MessageSquare size={14} />
                Chat
            </GlassButton>

            {availability.extractMetadata ? (
                <GlassButton
                    variant="ghost"
                    size="sm"
                    onClick={onExtractMetadata}
                    disabled={!hasSelection}
                >
                    <Sparkles size={14} />
                    Extract
                </GlassButton>
            ) : null}

            <GlassButton
                variant="ghost"
                size="sm"
                onClick={onDelete}
                disabled={!hasSelection}
                className="hover:bg-danger-soft hover:text-danger"
            >
                <Trash2 size={14} />
                Delete
            </GlassButton>

            <div className="ml-auto flex items-center gap-2">
                <div className="relative">
                    <Search
                        size={14}
                        className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3"
                    />
                    <input
                        type="search"
                        value={query.search}
                        onChange={(event) => onSearchChange(event.target.value)}
                        placeholder="Search name or title"
                        aria-label="Search documents"
                        className="h-8 w-56 rounded-lg border border-edge bg-surface-1 pr-2 pl-7 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
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

            <div className="flex items-center gap-2">
                {range.pageCount > 1 ? (
                    <nav aria-label="Pagination" className="flex items-center gap-0.5">
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
