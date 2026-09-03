// TagsSection.tsx
// The personal tag vocabulary.
//
// Split out of the documents page on purpose. Browsing by tag and administering the set of
// tags are different jobs done at different times, and the classic interface does both from
// the same toolbar, which is a large part of why that page feels crowded. Here the documents
// page keeps the tags visible and applicable, and this section owns the vocabulary itself.
//
// Tags are deliberately flat. A document carries as many as it needs and none of them nest,
// which is what lets one document belong to several groupings at once -- the thing a folder
// tree cannot express.

import { useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, Merge, Plus, Tag as TagIcon, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { WorkspaceTag } from '../../lib/types';
import {
    createPersonalDocumentTag,
    deletePersonalDocumentTag,
    fetchPersonalDocumentTags,
    updatePersonalDocumentTag,
} from '../../lib/endpoints';
import { GlassButton, EmptyState, Skeleton } from '../../components/ui/primitives';
import { SectionError, SectionIntro, SectionSearch } from '../../components/workspace/primitives';
import { errorMessage } from '../../components/workspace/useSectionResource';
import { readableTextColor } from '../../components/documents/documentPresentation';
import { toast } from '../../stores/toastStore';

/** Offered as a starting palette; any hex the colour input produces is accepted. */
const TAG_COLOR_PRESETS = [
    '#3b82f6',
    '#8b5cf6',
    '#ec4899',
    '#ef4444',
    '#f59e0b',
    '#10b981',
    '#14b8a6',
    '#64748b',
];

function TagRow({
    tag,
    busy,
    existingNames,
    onRename,
    onRecolour,
    onDelete,
}: {
    tag: WorkspaceTag;
    busy: boolean;
    existingNames: string[];
    onRename: (name: string) => void;
    onRecolour: (color: string) => void;
    onDelete: () => void;
}) {
    const [editing, setEditing] = useState(false);
    const [draftName, setDraftName] = useState(tag.name);

    const trimmed = draftName.trim();
    // Renaming onto an existing tag is how two tags are merged: the server rewrites every
    // document carrying the old name, and documents that already had both simply keep one.
    const willMerge =
        Boolean(trimmed) &&
        trimmed.toLowerCase() !== tag.name.toLowerCase() &&
        existingNames.some((name) => name.toLowerCase() === trimmed.toLowerCase());

    return (
        <li className="flex items-center gap-2.5 rounded-xl border border-edge bg-surface-1 px-3 py-2">
            <label className="relative shrink-0" title="Change colour">
                <span
                    className="block h-5 w-5 rounded border border-edge"
                    style={{
                        backgroundColor: tag.color || 'transparent',
                        color: readableTextColor(tag.color),
                    }}
                />
                <input
                    type="color"
                    value={tag.color || '#3b82f6'}
                    onChange={(event) => onRecolour(event.target.value)}
                    aria-label={`Colour for ${tag.name}`}
                    className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                />
            </label>

            <div className="min-w-0 flex-1">
                {editing ? (
                    <div className="flex items-center gap-1.5">
                        <input
                            type="text"
                            value={draftName}
                            autoFocus
                            onChange={(event) => setDraftName(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter') {
                                    event.preventDefault();
                                    onRename(trimmed);
                                    setEditing(false);
                                }
                                if (event.key === 'Escape') {
                                    setDraftName(tag.name);
                                    setEditing(false);
                                }
                            }}
                            className="w-full rounded-lg border border-edge bg-surface-1 px-2 py-1 text-sm text-text-1 focus:border-accent focus:outline-none"
                        />
                        <GlassButton
                            variant="primary"
                            size="sm"
                            disabled={!trimmed || busy}
                            onClick={() => {
                                onRename(trimmed);
                                setEditing(false);
                            }}
                        >
                            {willMerge ? <Merge size={13} /> : null}
                            {willMerge ? 'Merge' : 'Save'}
                        </GlassButton>
                        <GlassButton
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                                setDraftName(tag.name);
                                setEditing(false);
                            }}
                        >
                            Cancel
                        </GlassButton>
                    </div>
                ) : (
                    <button
                        type="button"
                        onClick={() => setEditing(true)}
                        className="truncate text-left text-sm text-text-1 hover:underline"
                        title="Rename this tag"
                    >
                        {tag.name}
                    </button>
                )}
                {editing && willMerge ? (
                    <p className="mt-0.5 text-[11px] text-warn">
                        A tag with that name exists. Saving merges the two.
                    </p>
                ) : null}
            </div>

            <span className="shrink-0 text-xs tabular-nums text-text-3">
                {tag.count ?? 0} {tag.count === 1 ? 'document' : 'documents'}
            </span>

            <button
                type="button"
                onClick={onDelete}
                disabled={busy}
                aria-label={`Delete tag ${tag.name}`}
                title={`Delete tag ${tag.name}`}
                className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger disabled:opacity-40"
            >
                <Trash2 size={15} />
            </button>
        </li>
    );
}

export function TagsSection({ documentsEnabled }: { documentsEnabled: boolean }) {
    const [tags, setTags] = useState<WorkspaceTag[]>([]);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [newName, setNewName] = useState('');
    const [newColor, setNewColor] = useState(TAG_COLOR_PRESETS[0]);

    const load = async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetchPersonalDocumentTags();
            setTags(response.tags ?? []);
        } catch (loadError) {
            setError(errorMessage(loadError, 'Failed to load tags.'));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        void load();
    }, []);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        const filtered = needle
            ? tags.filter((tag) => tag.name.toLowerCase().includes(needle))
            : tags;
        return [...filtered].sort((left, right) => (right.count ?? 0) - (left.count ?? 0));
    }, [tags, query]);

    const names = useMemo(() => tags.map((tag) => tag.name), [tags]);
    const unused = useMemo(() => tags.filter((tag) => !tag.count), [tags]);

    const onCreate = async () => {
        const name = newName.trim();
        if (!name) {
            return;
        }
        setBusy(true);
        try {
            await createPersonalDocumentTag(name, newColor);
            setNewName('');
            await load();
            toast.success(`Created "${name}".`);
        } catch (createError) {
            toast.error(errorMessage(createError, 'Could not create the tag.'));
        } finally {
            setBusy(false);
        }
    };

    const onRename = async (tag: WorkspaceTag, name: string) => {
        if (!name || name === tag.name) {
            return;
        }
        setBusy(true);
        try {
            const response = await updatePersonalDocumentTag(tag.name, { new_name: name });
            await load();
            const updated = response.documents_updated ?? 0;
            toast.success(
                updated > 0
                    ? `Renamed to "${name}" on ${updated} ${updated === 1 ? 'document' : 'documents'}.`
                    : `Renamed to "${name}".`,
            );
        } catch (renameError) {
            toast.error(errorMessage(renameError, 'Could not rename the tag.'));
        } finally {
            setBusy(false);
        }
    };

    const onRecolour = async (tag: WorkspaceTag, color: string) => {
        // Applied locally first: a colour picker fires continuously while dragging, and
        // waiting for each round trip would make the swatch lag the pointer.
        setTags((current) =>
            current.map((item) => (item.name === tag.name ? { ...item, color } : item)),
        );
        try {
            await updatePersonalDocumentTag(tag.name, { color });
        } catch (colourError) {
            toast.error(errorMessage(colourError, 'Could not save the colour.'));
            await load();
        }
    };

    const onDelete = async (tag: WorkspaceTag) => {
        const count = tag.count ?? 0;
        const warning =
            count > 0
                ? `Delete "${tag.name}"? It will be removed from ${count} ${count === 1 ? 'document' : 'documents'}. The documents themselves are kept.`
                : `Delete "${tag.name}"?`;
        if (!window.confirm(warning)) {
            return;
        }
        setBusy(true);
        try {
            await deletePersonalDocumentTag(tag.name);
            await load();
            toast.success(`Deleted "${tag.name}".`);
        } catch (deleteError) {
            toast.error(errorMessage(deleteError, 'Could not delete the tag.'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-4">
            <SectionIntro
                title="Tags"
                description="The vocabulary your documents are filed under. Tags are flat, so a document can carry as many as it needs and appear under each of them."
            />

            {documentsEnabled ? (
                <p className="text-xs text-text-3">
                    Apply tags from{' '}
                    <Link to="/workspace/documents" className="text-accent hover:underline">
                        Documents
                    </Link>
                    , where you can also drag files onto a tag to file them.
                </p>
            ) : null}

            <div className="flex flex-wrap items-end gap-2 rounded-xl border border-edge bg-surface-1 p-3">
                <label className="min-w-[12rem] flex-1">
                    <span className="mb-1 block text-xs font-medium text-text-2">New tag</span>
                    <input
                        type="text"
                        value={newName}
                        onChange={(event) => setNewName(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault();
                                void onCreate();
                            }
                        }}
                        placeholder="e.g. contracts"
                        className="w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
                </label>

                <div>
                    <span className="mb-1 block text-xs font-medium text-text-2">Colour</span>
                    <div className="flex items-center gap-1">
                        {TAG_COLOR_PRESETS.map((color) => (
                            <button
                                key={color}
                                type="button"
                                onClick={() => setNewColor(color)}
                                aria-label={`Use colour ${color}`}
                                className={clsx(
                                    'h-6 w-6 rounded border transition-transform',
                                    newColor === color
                                        ? 'scale-110 border-text-1'
                                        : 'border-edge hover:scale-105',
                                )}
                                style={{ backgroundColor: color }}
                            />
                        ))}
                    </div>
                </div>

                <GlassButton
                    variant="primary"
                    size="sm"
                    onClick={() => void onCreate()}
                    disabled={!newName.trim() || busy}
                >
                    {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                    Create
                </GlassButton>
            </div>

            {error ? <SectionError message={error} /> : null}

            {tags.length > 6 ? (
                <SectionSearch value={query} onChange={setQuery} placeholder="Search tags" />
            ) : null}

            {loading ? (
                <div className="space-y-2">
                    {Array.from({ length: 4 }).map((_, index) => (
                        <Skeleton key={index} className="h-12 w-full" />
                    ))}
                </div>
            ) : visible.length === 0 ? (
                <EmptyState
                    icon={<TagIcon size={28} />}
                    title={tags.length === 0 ? 'No tags yet' : 'No tags match your search'}
                    description={
                        tags.length === 0
                            ? 'Create a tag above, then apply it to documents from the Documents section.'
                            : undefined
                    }
                />
            ) : (
                <>
                    <ul className="space-y-2">
                        {visible.map((tag) => (
                            <TagRow
                                key={tag.name}
                                tag={tag}
                                busy={busy}
                                existingNames={names}
                                onRename={(name) => void onRename(tag, name)}
                                onRecolour={(color) => void onRecolour(tag, color)}
                                onDelete={() => void onDelete(tag)}
                            />
                        ))}
                    </ul>

                    {unused.length > 0 ? (
                        <p className="text-xs text-text-3">
                            {unused.length} {unused.length === 1 ? 'tag is' : 'tags are'} not
                            applied to any document. Renaming one onto an existing tag merges
                            the two.
                        </p>
                    ) : null}
                </>
            )}
        </div>
    );
}
