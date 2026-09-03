// DocumentTiles.tsx
// The tiles view: the same documents as cards.
//
// One of two views, down from the classic interface's four. The two folder modes it also
// offers are not carried over: the rail lists tags permanently, which is what those modes
// were reaching for, and a folder grid that has to be entered and left again is a worse way
// to reach the same place.

import { clsx } from 'clsx';
import type { WorkspaceDocument } from '../../lib/types';
import {
    documentDate,
    documentDisplayName,
    documentId,
    formatFileSize,
    formatRelativeDate,
    normalizeTags,
    type SelectionIntent,
    type SelectionState,
} from '../../lib/documentExplorer';
import {
    ClassificationBadge,
    DocumentIcon,
    DocumentStatusBadge,
    TagChipList,
} from './documentPresentation';

export function DocumentTiles({
    documents,
    selection,
    tagColors,
    classificationColors,
    onSelect,
    onOpen,
    onDragStart,
}: {
    documents: WorkspaceDocument[];
    selection: SelectionState;
    tagColors: Record<string, string | undefined>;
    classificationColors: Record<string, string | undefined>;
    onSelect: (id: string, intent: SelectionIntent) => void;
    onOpen: (document: WorkspaceDocument) => void;
    onDragStart: (event: React.DragEvent, id: string) => void;
}) {
    const selectedIds = new Set(selection.ids);

    return (
        <ul className="grid grid-cols-1 gap-2 p-1 sm:grid-cols-2 xl:grid-cols-3">
            {documents.map((document) => {
                const id = documentId(document);
                const selected = selectedIds.has(id);
                const { primary, secondary } = documentDisplayName(document);
                const tags = normalizeTags(document.tags);
                const classification = String(document.document_classification ?? '').trim();

                return (
                    <li key={id}>
                        <div
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
                                'group flex h-full cursor-default flex-col gap-2 rounded-xl border p-3 transition-colors',
                                selected
                                    ? 'border-accent bg-accent-soft'
                                    : 'border-edge bg-surface-1 hover:bg-surface-2',
                            )}
                        >
                            <div className="flex items-start gap-2">
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
                                        'mt-0.5 h-3.5 w-3.5 shrink-0 cursor-pointer accent-[var(--accent)]',
                                        !selected &&
                                            'opacity-0 group-hover:opacity-100 focus:opacity-100',
                                    )}
                                />
                                <DocumentIcon document={document} size={20} />
                                <div className="min-w-0 flex-1">
                                    <p className="truncate text-sm text-text-1">{primary}</p>
                                    {secondary ? (
                                        <p className="truncate text-xs text-text-3">{secondary}</p>
                                    ) : null}
                                </div>
                            </div>

                            <div className="flex flex-wrap items-center gap-1.5">
                                <DocumentStatusBadge document={document} showProgressBar />
                                {classification ? (
                                    <ClassificationBadge
                                        classification={classification}
                                        color={classificationColors[classification]}
                                    />
                                ) : null}
                            </div>

                            <TagChipList tags={tags} colors={tagColors} limit={4} />

                            <p className="mt-auto text-[11px] text-text-3">
                                {formatRelativeDate(documentDate(document))}
                                {document.file_size
                                    ? ` · ${formatFileSize(document.file_size)}`
                                    : ''}
                            </p>
                        </div>
                    </li>
                );
            })}
        </ul>
    );
}
