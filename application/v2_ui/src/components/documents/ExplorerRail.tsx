// ExplorerRail.tsx
// The documents explorer navigation pane.
//
// This is where the redesign spends its main idea. The classic interface offers "folders" as
// a view mode you switch into, which shows tags rendered as folder cards in the content
// area -- so browsing by tag means leaving the list, and the tags are invisible the rest of
// the time. Here the same information is a permanent rail, which is how Finder presents
// tags and how Explorer presents libraries and saved searches.
//
// The rail also accepts a drop. Dragging a selection onto a tag applies it, which is the
// filing gesture people already have for folders, offered without inventing a hierarchy the
// data model does not have.

import { useState } from 'react';
import { clsx } from 'clsx';
import {
    Bookmark,
    CircleAlert,
    Clock,
    FolderOpen,
    Loader2,
    Tag as TagIcon,
    Users,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type {
    DocumentFacets,
    DocumentPlace,
    DocumentQuery,
    DocumentSavedView,
    WorkspaceTag,
} from '../../lib/types';
import {
    DOCUMENT_PLACE_LABELS,
    placeCount,
    visiblePlaces,
} from '../../lib/documentExplorer';
import { matchesSavedView } from '../../lib/documentSavedViews';

const PLACE_ICONS: Record<DocumentPlace, LucideIcon> = {
    all: FolderOpen,
    recent: Clock,
    shared: Users,
    processing: Loader2,
    errors: CircleAlert,
    untagged: TagIcon,
};

function RailGroup({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <div className="space-y-0.5">
            <p className="px-2.5 pt-2 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                {label}
            </p>
            {children}
        </div>
    );
}

function RailEntry({
    icon,
    label,
    count,
    active,
    onClick,
    onContextMenu,
    dropActive,
    swatch,
    ...dropHandlers
}: {
    icon?: React.ReactNode;
    label: string;
    count?: number | null;
    active: boolean;
    onClick: () => void;
    onContextMenu?: (event: React.MouseEvent) => void;
    dropActive?: boolean;
    swatch?: string;
    onDragOver?: (event: React.DragEvent) => void;
    onDragLeave?: (event: React.DragEvent) => void;
    onDrop?: (event: React.DragEvent) => void;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            onContextMenu={onContextMenu}
            aria-current={active ? 'true' : undefined}
            className={clsx(
                'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors',
                active
                    ? 'bg-accent-soft font-medium text-accent'
                    : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                dropActive && 'ring-2 ring-accent ring-inset',
            )}
            {...dropHandlers}
        >
            {swatch !== undefined ? (
                <span
                    aria-hidden="true"
                    className="h-2.5 w-2.5 shrink-0 rounded-full border border-edge"
                    style={{ backgroundColor: swatch || 'transparent' }}
                />
            ) : null}
            {icon}
            <span className="min-w-0 flex-1 truncate">{label}</span>
            {typeof count === 'number' ? (
                <span className="shrink-0 text-[11px] tabular-nums text-text-3">{count}</span>
            ) : null}
        </button>
    );
}

export function ExplorerRail({
    query,
    facets,
    tags,
    savedViews,
    classifications,
    onQueryChange,
    onApplySavedView,
    onDeleteSavedView,
    onDropOnTag,
}: {
    query: DocumentQuery;
    facets: DocumentFacets | null;
    tags: WorkspaceTag[];
    savedViews: DocumentSavedView[];
    classifications: { label: string; color?: string }[];
    onQueryChange: (change: Partial<DocumentQuery>) => void;
    onApplySavedView: (view: DocumentSavedView) => void;
    onDeleteSavedView: (view: DocumentSavedView) => void;
    /** Applies a tag to the dragged documents. Undefined disables the drop target. */
    onDropOnTag?: (tagName: string, documentIds: string[]) => void;
}) {
    const [dropTarget, setDropTarget] = useState<string | null>(null);

    const places = visiblePlaces(facets);

    /**
     * Ctrl-click adds a tag to the filter rather than replacing it.
     *
     * Tags combine with AND server-side, so accumulating them narrows -- which is the useful
     * direction and the one a plain click cannot express.
     */
    const selectTag = (name: string, additive: boolean) => {
        const active = query.tags.includes(name);
        if (additive) {
            onQueryChange({
                tags: active
                    ? query.tags.filter((tag) => tag !== name)
                    : [...query.tags, name],
            });
            return;
        }
        onQueryChange({ tags: active && query.tags.length === 1 ? [] : [name] });
    };

    const readDraggedIds = (event: React.DragEvent): string[] => {
        const raw = event.dataTransfer.getData('application/x-simplechat-documents');
        if (!raw) {
            return [];
        }
        try {
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : [];
        } catch {
            return [];
        }
    };

    return (
        <nav
            aria-label="Document filters"
            className="flex w-56 shrink-0 flex-col gap-1 overflow-y-auto pr-1"
        >
            <RailGroup label="Places">
                {places.map((place) => {
                    const Icon = PLACE_ICONS[place];
                    return (
                        <RailEntry
                            key={place}
                            icon={<Icon size={15} className="shrink-0" />}
                            label={DOCUMENT_PLACE_LABELS[place]}
                            count={placeCount(facets, place)}
                            active={query.place === place}
                            onClick={() => onQueryChange({ place })}
                        />
                    );
                })}
            </RailGroup>

            {savedViews.length > 0 ? (
                <RailGroup label="Saved views">
                    {savedViews.map((view) => (
                        <RailEntry
                            key={view.id}
                            icon={<Bookmark size={15} className="shrink-0" />}
                            label={view.name}
                            active={matchesSavedView(query, view)}
                            onClick={() => onApplySavedView(view)}
                            onContextMenu={(event) => {
                                event.preventDefault();
                                onDeleteSavedView(view);
                            }}
                        />
                    ))}
                    <p className="px-2.5 pt-1 pb-1 text-[10px] leading-snug text-text-3">
                        Right-click a view to remove it.
                    </p>
                </RailGroup>
            ) : null}

            {tags.length > 0 ? (
                <RailGroup label="Tags">
                    {tags.map((tag) => (
                        <RailEntry
                            key={tag.name}
                            swatch={tag.color ?? ''}
                            label={tag.name}
                            count={facets?.by_tag?.[tag.name] ?? tag.count ?? null}
                            active={query.tags.includes(tag.name)}
                            onClick={() => selectTag(tag.name, false)}
                            dropActive={dropTarget === tag.name}
                            onDragOver={
                                onDropOnTag
                                    ? (event) => {
                                          event.preventDefault();
                                          event.dataTransfer.dropEffect = 'copy';
                                          setDropTarget(tag.name);
                                      }
                                    : undefined
                            }
                            onDragLeave={onDropOnTag ? () => setDropTarget(null) : undefined}
                            onDrop={
                                onDropOnTag
                                    ? (event) => {
                                          event.preventDefault();
                                          setDropTarget(null);
                                          const ids = readDraggedIds(event);
                                          if (ids.length > 0) {
                                              onDropOnTag(tag.name, ids);
                                          }
                                      }
                                    : undefined
                            }
                        />
                    ))}
                    <p className="px-2.5 pt-1 pb-1 text-[10px] leading-snug text-text-3">
                        Drag documents onto a tag to apply it. Ctrl-click to combine tags.
                    </p>
                </RailGroup>
            ) : null}

            {classifications.length > 0 ? (
                <RailGroup label="Classification">
                    {classifications.map((classification) => (
                        <RailEntry
                            key={classification.label}
                            swatch={classification.color ?? ''}
                            label={classification.label}
                            count={facets?.by_classification?.[classification.label] ?? null}
                            active={query.classification === classification.label}
                            onClick={() =>
                                onQueryChange({
                                    classification:
                                        query.classification === classification.label
                                            ? null
                                            : classification.label,
                                })
                            }
                        />
                    ))}
                </RailGroup>
            ) : null}
        </nav>
    );
}
