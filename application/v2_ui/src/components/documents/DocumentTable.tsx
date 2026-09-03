// DocumentTable.tsx
// The details view: a dense, sortable table of documents.
//
// Two things here are deliberate departures from the classic interface.
//
// Selection is not a mode. The classic page has a "Multi-select" button that must be pressed
// before a checkbox will appear, which means the most common bulk operation starts with a
// step no file manager has ever required. Here click, Ctrl+click and Shift+click do what
// they do everywhere else, and the checkboxes are always reachable.
//
// The name column carries two lines. `file_name` alone is frequently something like
// `MSA_v2_FINAL(3).docx`, so the extracted title leads and the file name sits under it. When
// there is no title the file name is promoted rather than captioned with "Untitled".

import { useEffect, useRef } from 'react';
import { clsx } from 'clsx';
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react';
import type {
    DocumentQuery,
    DocumentSortField,
    WorkspaceDocument,
} from '../../lib/types';
import {
    documentDate,
    documentDisplayName,
    documentId,
    formatFileSize,
    formatRelativeDate,
    normalizeTags,
    type SelectionState,
    type SelectionIntent,
} from '../../lib/documentExplorer';
import {
    ClassificationBadge,
    DocumentIcon,
    DocumentStatusBadge,
    TagChipList,
} from './documentPresentation';

export interface DocumentColumn {
    id: string;
    label: string;
    /** Omitted when the column cannot be ordered by the server. */
    sortField?: DocumentSortField;
    /** Fixed width class. The name column is the one that flexes. */
    className?: string;
    align?: 'left' | 'right';
}

/**
 * Every column the table can show.
 *
 * `sortField` is present only where the list endpoint will actually honour it. A header
 * offering a sort the server silently replaces with `_ts` would look like it worked and
 * quietly reorder by something else.
 */
export const DOCUMENT_COLUMNS: DocumentColumn[] = [
    { id: 'name', label: 'Name', sortField: 'file_name' },
    { id: 'tags', label: 'Tags', className: 'w-56' },
    { id: 'status', label: 'Status', className: 'w-32' },
    { id: 'modified', label: 'Modified', sortField: '_ts', className: 'w-32' },
    { id: 'size', label: 'Size', sortField: 'file_size', className: 'w-24', align: 'right' },
    {
        id: 'classification',
        label: 'Classification',
        sortField: 'document_classification',
        className: 'w-36',
    },
    { id: 'pages', label: 'Pages', sortField: 'number_of_pages', className: 'w-20', align: 'right' },
    { id: 'version', label: 'Version', sortField: 'version', className: 'w-20', align: 'right' },
];

/** Shown unless the user says otherwise. Classification, pages and version are opt-in. */
export const DEFAULT_DOCUMENT_COLUMNS = ['name', 'tags', 'status', 'modified', 'size'];

function SortIndicator({
    active,
    direction,
}: {
    active: boolean;
    direction: 'asc' | 'desc';
}) {
    if (!active) {
        return <ChevronsUpDown size={12} className="opacity-0 group-hover:opacity-50" />;
    }
    return direction === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />;
}

export function DocumentTable({
    documents,
    columns,
    query,
    selection,
    tagColors,
    classificationColors,
    onSelect,
    onToggleSelectAll,
    onSort,
    onOpen,
    onDragStart,
}: {
    documents: WorkspaceDocument[];
    columns: string[];
    query: DocumentQuery;
    selection: SelectionState;
    tagColors: Record<string, string | undefined>;
    classificationColors: Record<string, string | undefined>;
    onSelect: (id: string, intent: SelectionIntent) => void;
    onToggleSelectAll: () => void;
    onSort: (field: DocumentSortField) => void;
    onOpen: (document: WorkspaceDocument) => void;
    onDragStart: (event: React.DragEvent, id: string) => void;
}) {
    const activeColumns = DOCUMENT_COLUMNS.filter((column) => columns.includes(column.id));
    const selectedIds = new Set(selection.ids);
    const allSelected = documents.length > 0 && documents.every((item) => selectedIds.has(documentId(item)));
    const someSelected = selection.ids.length > 0 && !allSelected;

    const selectAllRef = useRef<HTMLInputElement>(null);
    useEffect(() => {
        if (selectAllRef.current) {
            // The indeterminate state is not expressible as an attribute, so it has to be
            // written to the node. Without it a partial selection reads as "none selected".
            selectAllRef.current.indeterminate = someSelected;
        }
    }, [someSelected]);

    return (
        <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-surface-1">
                <tr className="border-b border-edge text-left">
                    <th scope="col" className="w-9 px-2 py-2">
                        <input
                            ref={selectAllRef}
                            type="checkbox"
                            checked={allSelected}
                            onChange={onToggleSelectAll}
                            aria-label="Select all documents on this page"
                            className="h-3.5 w-3.5 cursor-pointer accent-[var(--accent)]"
                        />
                    </th>
                    {activeColumns.map((column) => {
                        const active = column.sortField === query.sortBy;
                        return (
                            <th
                                key={column.id}
                                scope="col"
                                aria-sort={
                                    active
                                        ? query.sortOrder === 'asc'
                                            ? 'ascending'
                                            : 'descending'
                                        : undefined
                                }
                                className={clsx(
                                    'px-2 py-2 text-[11px] font-semibold tracking-wide text-text-3 uppercase',
                                    column.className,
                                    column.align === 'right' && 'text-right',
                                )}
                            >
                                {column.sortField ? (
                                    <button
                                        type="button"
                                        onClick={() => onSort(column.sortField!)}
                                        className={clsx(
                                            'group inline-flex items-center gap-1 transition-colors hover:text-text-1',
                                            active && 'text-text-1',
                                            column.align === 'right' && 'flex-row-reverse',
                                        )}
                                    >
                                        {column.label}
                                        <SortIndicator active={active} direction={query.sortOrder} />
                                    </button>
                                ) : (
                                    column.label
                                )}
                            </th>
                        );
                    })}
                </tr>
            </thead>
            <tbody>
                {documents.map((document) => {
                    const id = documentId(document);
                    const selected = selectedIds.has(id);
                    const { primary, secondary } = documentDisplayName(document);
                    const tags = normalizeTags(document.tags);
                    const classification = String(document.document_classification ?? '').trim();

                    return (
                        <tr
                            key={id}
                            draggable
                            onDragStart={(event) => onDragStart(event, id)}
                            onClick={(event) =>
                                onSelect(
                                    id,
                                    event.shiftKey
                                        ? 'range'
                                        : event.ctrlKey || event.metaKey
                                          ? 'toggle'
                                          : 'replace',
                                )
                            }
                            onDoubleClick={() => onOpen(document)}
                            aria-selected={selected}
                            className={clsx(
                                'group cursor-default border-b border-edge/60 transition-colors',
                                selected ? 'bg-accent-soft' : 'hover:bg-surface-2',
                            )}
                        >
                            <td className="px-2 py-2 align-middle">
                                <input
                                    type="checkbox"
                                    checked={selected}
                                    onClick={(event) => event.stopPropagation()}
                                    onChange={(event) =>
                                        onSelect(
                                            id,
                                            (event.nativeEvent as MouseEvent).shiftKey
                                                ? 'range'
                                                : 'toggle',
                                        )
                                    }
                                    aria-label={`Select ${primary}`}
                                    className={clsx(
                                        'h-3.5 w-3.5 cursor-pointer accent-[var(--accent)]',
                                        // Hidden until useful, like Explorer, but never
                                        // removed: it stays reachable by keyboard.
                                        !selected &&
                                            'opacity-0 group-hover:opacity-100 focus:opacity-100',
                                    )}
                                />
                            </td>

                            {activeColumns.map((column) => {
                                switch (column.id) {
                                    case 'name':
                                        return (
                                            <td key={column.id} className="px-2 py-1.5">
                                                <div className="flex min-w-0 items-center gap-2">
                                                    <DocumentIcon document={document} />
                                                    <div className="min-w-0">
                                                        <div className="truncate text-text-1">
                                                            {primary}
                                                        </div>
                                                        {secondary ? (
                                                            <div className="truncate text-xs text-text-3">
                                                                {secondary}
                                                            </div>
                                                        ) : null}
                                                    </div>
                                                </div>
                                            </td>
                                        );
                                    case 'tags':
                                        return (
                                            <td key={column.id} className="px-2 py-1.5">
                                                <TagChipList
                                                    tags={tags}
                                                    colors={tagColors}
                                                    limit={3}
                                                />
                                            </td>
                                        );
                                    case 'status':
                                        return (
                                            <td key={column.id} className="px-2 py-1.5">
                                                <DocumentStatusBadge document={document} />
                                            </td>
                                        );
                                    case 'modified':
                                        return (
                                            <td
                                                key={column.id}
                                                className="px-2 py-1.5 text-xs whitespace-nowrap text-text-3"
                                                title={documentDate(document)?.toLocaleString()}
                                            >
                                                {formatRelativeDate(documentDate(document))}
                                            </td>
                                        );
                                    case 'size':
                                        return (
                                            <td
                                                key={column.id}
                                                className="px-2 py-1.5 text-right text-xs whitespace-nowrap tabular-nums text-text-3"
                                            >
                                                {formatFileSize(document.file_size)}
                                            </td>
                                        );
                                    case 'classification':
                                        return (
                                            <td key={column.id} className="px-2 py-1.5">
                                                {classification ? (
                                                    <ClassificationBadge
                                                        classification={classification}
                                                        color={classificationColors[classification]}
                                                    />
                                                ) : (
                                                    <span className="text-xs text-text-3">—</span>
                                                )}
                                            </td>
                                        );
                                    case 'pages':
                                        return (
                                            <td
                                                key={column.id}
                                                className="px-2 py-1.5 text-right text-xs tabular-nums text-text-3"
                                            >
                                                {document.number_of_pages ?? '—'}
                                            </td>
                                        );
                                    case 'version':
                                        return (
                                            <td
                                                key={column.id}
                                                className="px-2 py-1.5 text-right text-xs tabular-nums text-text-3"
                                            >
                                                {document.version ?? '—'}
                                            </td>
                                        );
                                    default:
                                        return <td key={column.id} />;
                                }
                            })}
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
}
