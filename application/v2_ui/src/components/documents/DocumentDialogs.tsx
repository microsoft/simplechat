// DocumentDialogs.tsx
// The modal surfaces the explorer opens: tagging, metadata, sharing and delete confirmation.
//
// Each exists because the work genuinely does not fit in the details pane. Tagging several
// documents needs the whole vocabulary visible; editing metadata is a form with seven
// fields; sharing is a search; and the delete confirmation has to report which documents the
// server refused and why, which is the part the classic interface handles least well.

import { useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, Search, Trash2, X } from 'lucide-react';
import type { ReactNode } from 'react';
import type { WorkspaceDocument, WorkspaceTag } from '../../lib/types';
import {
    commonTags,
    documentDisplayName,
    normalizeStringList,
    normalizeTags,
} from '../../lib/documentExplorer';
import {
    fetchPersonalDocumentSharedUsers,
    searchShareableUsers,
    sharePersonalDocument,
    unsharePersonalDocument,
    type BulkDeleteError,
    type SharedDocumentUser,
} from '../../lib/endpoints';
import { GlassButton } from '../ui/primitives';
import { readableTextColor } from './documentPresentation';

/* -------------------------------------------------------------------------- */
/* Shell                                                                       */
/* -------------------------------------------------------------------------- */

export function Modal({
    title,
    description,
    onClose,
    children,
    footer,
    wide = false,
}: {
    title: string;
    description?: string;
    onClose: () => void;
    children: ReactNode;
    footer?: ReactNode;
    wide?: boolean;
}) {
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
            role="dialog"
            aria-modal="true"
            aria-label={title}
            onClick={onClose}
        >
            <div
                onClick={(event) => event.stopPropagation()}
                className={clsx(
                    'glass-modal flex max-h-[85vh] w-full flex-col rounded-2xl',
                    wide ? 'max-w-2xl' : 'max-w-lg',
                )}
            >
                <div className="flex items-start justify-between gap-3 border-b border-edge px-4 py-3">
                    <div className="min-w-0">
                        <h2 className="text-sm font-semibold text-text-1">{title}</h2>
                        {description ? (
                            <p className="mt-0.5 text-xs text-text-3">{description}</p>
                        ) : null}
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close"
                        className="rounded-lg p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={16} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>

                {footer ? (
                    <div className="flex items-center justify-end gap-2 border-t border-edge px-4 py-3">
                        {footer}
                    </div>
                ) : null}
            </div>
        </div>
    );
}

function TextField({
    label,
    value,
    onChange,
    placeholder,
    hint,
}: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    hint?: string;
}) {
    return (
        <label className="block">
            <span className="mb-1 block text-xs font-medium text-text-2">{label}</span>
            <input
                type="text"
                value={value}
                placeholder={placeholder}
                onChange={(event) => onChange(event.target.value)}
                className="w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
            />
            {hint ? <span className="mt-0.5 block text-[11px] text-text-3">{hint}</span> : null}
        </label>
    );
}

/* -------------------------------------------------------------------------- */
/* Tagging                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Apply and remove tags across a selection.
 *
 * A tag carried by only some of the selected documents is shown as partial rather than as
 * present or absent, because both of those would be a lie and acting on either would quietly
 * change documents the user was not looking at.
 */
export function TagDialog({
    documents,
    tags,
    busy,
    onClose,
    onApply,
    onCreateTag,
}: {
    documents: WorkspaceDocument[];
    tags: WorkspaceTag[];
    busy: boolean;
    onClose: () => void;
    onApply: (added: string[], removed: string[]) => void;
    onCreateTag: (name: string) => Promise<void>;
}) {
    const shared = useMemo(() => new Set(commonTags(documents)), [documents]);
    const present = useMemo(() => {
        const all = new Set<string>();
        for (const document of documents) {
            for (const tag of normalizeTags(document.tags)) {
                all.add(tag);
            }
        }
        return all;
    }, [documents]);

    const [added, setAdded] = useState<Set<string>>(new Set());
    const [removed, setRemoved] = useState<Set<string>>(new Set());
    const [newTag, setNewTag] = useState('');
    const [creating, setCreating] = useState(false);

    const toggle = (name: string) => {
        const isOnAll = shared.has(name);
        if (isOnAll) {
            setRemoved((current) => {
                const next = new Set(current);
                next.has(name) ? next.delete(name) : next.add(name);
                return next;
            });
            return;
        }
        setAdded((current) => {
            const next = new Set(current);
            next.has(name) ? next.delete(name) : next.add(name);
            return next;
        });
    };

    const createTag = async () => {
        const name = newTag.trim();
        if (!name) {
            return;
        }
        setCreating(true);
        try {
            await onCreateTag(name);
            setAdded((current) => new Set(current).add(name));
            setNewTag('');
        } finally {
            setCreating(false);
        }
    };

    return (
        <Modal
            title={
                documents.length === 1
                    ? `Tag ${documentDisplayName(documents[0]).primary}`
                    : `Tag ${documents.length} documents`
            }
            description="Tags are flat: a document can carry as many as it needs."
            onClose={onClose}
            footer={
                <>
                    <GlassButton variant="ghost" size="sm" onClick={onClose}>
                        Cancel
                    </GlassButton>
                    <GlassButton
                        variant="primary"
                        size="sm"
                        disabled={busy || (added.size === 0 && removed.size === 0)}
                        onClick={() => onApply([...added], [...removed])}
                    >
                        {busy ? <Loader2 size={14} className="animate-spin" /> : null}
                        Apply
                    </GlassButton>
                </>
            }
        >
            <div className="space-y-3">
                <div className="flex gap-2">
                    <input
                        type="text"
                        value={newTag}
                        placeholder="New tag name"
                        onChange={(event) => setNewTag(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault();
                                void createTag();
                            }
                        }}
                        className="flex-1 rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
                    <GlassButton
                        variant="subtle"
                        size="sm"
                        onClick={() => void createTag()}
                        disabled={!newTag.trim() || creating}
                    >
                        {creating ? <Loader2 size={14} className="animate-spin" /> : null}
                        Create
                    </GlassButton>
                </div>

                {tags.length === 0 ? (
                    <p className="py-4 text-center text-xs text-text-3">
                        No tags yet. Create one above.
                    </p>
                ) : (
                    <ul className="space-y-0.5">
                        {tags.map((tag) => {
                            const onAll = shared.has(tag.name);
                            const onSome = !onAll && present.has(tag.name);
                            const willAdd = added.has(tag.name);
                            const willRemove = removed.has(tag.name);
                            const checked = onAll ? !willRemove : willAdd;

                            return (
                                <li key={tag.name}>
                                    <label className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-surface-2">
                                        <input
                                            type="checkbox"
                                            checked={checked}
                                            ref={(node) => {
                                                if (node) {
                                                    node.indeterminate = onSome && !willAdd;
                                                }
                                            }}
                                            onChange={() => toggle(tag.name)}
                                            className="h-3.5 w-3.5 accent-[var(--accent)]"
                                        />
                                        <span
                                            aria-hidden="true"
                                            className="h-2.5 w-2.5 shrink-0 rounded-full border border-edge"
                                            style={{ backgroundColor: tag.color || 'transparent' }}
                                        />
                                        <span className="min-w-0 flex-1 truncate text-sm text-text-1">
                                            {tag.name}
                                        </span>
                                        {onSome ? (
                                            <span className="text-[10px] text-text-3">
                                                on some
                                            </span>
                                        ) : null}
                                        {typeof tag.count === 'number' ? (
                                            <span className="text-[11px] tabular-nums text-text-3">
                                                {tag.count}
                                            </span>
                                        ) : null}
                                    </label>
                                </li>
                            );
                        })}
                    </ul>
                )}
            </div>
        </Modal>
    );
}

/* -------------------------------------------------------------------------- */
/* Metadata                                                                    */
/* -------------------------------------------------------------------------- */

export interface MetadataDraft {
    title: string;
    authors: string;
    keywords: string;
    abstract: string;
    publication_date: string;
    document_classification: string;
}

export function MetadataDialog({
    document,
    classifications,
    classificationEnabled,
    busy,
    onClose,
    onSave,
}: {
    document: WorkspaceDocument;
    classifications: { label: string; color?: string }[];
    classificationEnabled: boolean;
    busy: boolean;
    onClose: () => void;
    onSave: (draft: MetadataDraft) => void;
}) {
    const [draft, setDraft] = useState<MetadataDraft>({
        title: String(document.title ?? ''),
        authors: normalizeStringList(document.authors).join(', '),
        keywords: normalizeStringList(document.keywords).join(', '),
        abstract: String(document.abstract ?? ''),
        publication_date: String(document.publication_date ?? ''),
        document_classification: String(document.document_classification ?? ''),
    });

    const update = (change: Partial<MetadataDraft>) =>
        setDraft((current) => ({ ...current, ...change }));

    return (
        <Modal
            title="Edit metadata"
            description={String(document.file_name ?? '')}
            onClose={onClose}
            wide
            footer={
                <>
                    <GlassButton variant="ghost" size="sm" onClick={onClose}>
                        Cancel
                    </GlassButton>
                    <GlassButton
                        variant="primary"
                        size="sm"
                        disabled={busy}
                        onClick={() => onSave(draft)}
                    >
                        {busy ? <Loader2 size={14} className="animate-spin" /> : null}
                        Save
                    </GlassButton>
                </>
            }
        >
            <div className="space-y-3">
                <TextField
                    label="Title"
                    value={draft.title}
                    onChange={(title) => update({ title })}
                    hint="Shown above the file name everywhere the document is listed."
                />

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <TextField
                        label="Authors"
                        value={draft.authors}
                        onChange={(authors) => update({ authors })}
                        placeholder="Comma separated"
                    />
                    <TextField
                        label="Publication date"
                        value={draft.publication_date}
                        onChange={(publication_date) => update({ publication_date })}
                        placeholder="YYYY-MM-DD"
                    />
                </div>

                <TextField
                    label="Keywords"
                    value={draft.keywords}
                    onChange={(keywords) => update({ keywords })}
                    placeholder="Comma separated"
                />

                {classificationEnabled && classifications.length > 0 ? (
                    <label className="block">
                        <span className="mb-1 block text-xs font-medium text-text-2">
                            Classification
                        </span>
                        <select
                            value={draft.document_classification}
                            onChange={(event) =>
                                update({ document_classification: event.target.value })
                            }
                            className="w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1 focus:border-accent focus:outline-none"
                        >
                            <option value="">None</option>
                            {classifications.map((classification) => (
                                <option key={classification.label} value={classification.label}>
                                    {classification.label}
                                </option>
                            ))}
                        </select>
                    </label>
                ) : null}

                <label className="block">
                    <span className="mb-1 block text-xs font-medium text-text-2">Abstract</span>
                    <textarea
                        value={draft.abstract}
                        rows={5}
                        onChange={(event) => update({ abstract: event.target.value })}
                        className="w-full resize-y rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
                </label>
            </div>
        </Modal>
    );
}

/* -------------------------------------------------------------------------- */
/* Delete                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Confirm a delete, and report what the server refused.
 *
 * The second part is the reason this is a dialog rather than an inline confirm. A document
 * uploaded through chat, or one managed by file sync, is guarded server-side and comes back
 * unrefused with a reason. Presenting those documents by name -- and offering to go ahead
 * anyway -- is the only way the user can act on the answer.
 */
export function DeleteDialog({
    documents,
    blocked,
    busy,
    onClose,
    onConfirm,
}: {
    documents: WorkspaceDocument[];
    blocked: BulkDeleteError[];
    busy: boolean;
    onClose: () => void;
    onConfirm: (options: { force: boolean; deleteAllVersions: boolean }) => void;
}) {
    const [deleteAllVersions, setDeleteAllVersions] = useState(true);
    const hasBlocked = blocked.length > 0;

    return (
        <Modal
            title={hasBlocked ? 'Some documents need confirmation' : 'Delete documents'}
            description={
                hasBlocked
                    ? undefined
                    : documents.length === 1
                      ? documentDisplayName(documents[0]).primary
                      : `${documents.length} documents will be removed from your workspace.`
            }
            onClose={onClose}
            footer={
                <>
                    <GlassButton variant="ghost" size="sm" onClick={onClose}>
                        Cancel
                    </GlassButton>
                    <GlassButton
                        variant="danger"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                            onConfirm({ force: hasBlocked, deleteAllVersions })
                        }
                    >
                        {busy ? (
                            <Loader2 size={14} className="animate-spin" />
                        ) : (
                            <Trash2 size={14} />
                        )}
                        {hasBlocked ? 'Delete anyway' : 'Delete'}
                    </GlassButton>
                </>
            }
        >
            {hasBlocked ? (
                <div className="space-y-2">
                    <p className="text-xs text-text-2">
                        These are referenced elsewhere. Deleting them will not remove those
                        references.
                    </p>
                    <ul className="space-y-1.5">
                        {blocked.map((entry) => {
                            const document = documents.find(
                                (candidate) =>
                                    String(candidate.id ?? candidate.document_id) ===
                                    entry.document_id,
                            );
                            return (
                                <li
                                    key={entry.document_id}
                                    className="rounded-lg border border-edge bg-surface-1 px-2.5 py-2"
                                >
                                    <p className="truncate text-xs font-medium text-text-1">
                                        {document
                                            ? documentDisplayName(document).primary
                                            : entry.document_id}
                                    </p>
                                    <p className="mt-0.5 text-[11px] text-text-3">
                                        {entry.message ?? entry.error}
                                    </p>
                                </li>
                            );
                        })}
                    </ul>
                </div>
            ) : (
                <div className="space-y-3">
                    <ul className="max-h-48 space-y-1 overflow-y-auto">
                        {documents.slice(0, 20).map((document) => (
                            <li
                                key={String(document.id ?? document.document_id)}
                                className="truncate text-xs text-text-2"
                            >
                                {documentDisplayName(document).primary}
                            </li>
                        ))}
                        {documents.length > 20 ? (
                            <li className="text-xs text-text-3">
                                and {documents.length - 20} more
                            </li>
                        ) : null}
                    </ul>

                    <label className="flex cursor-pointer items-start gap-2">
                        <input
                            type="checkbox"
                            checked={deleteAllVersions}
                            onChange={(event) => setDeleteAllVersions(event.target.checked)}
                            className="mt-0.5 h-3.5 w-3.5 accent-[var(--accent)]"
                        />
                        <span className="text-xs text-text-2">
                            Delete every version
                            <span className="mt-0.5 block text-[11px] text-text-3">
                                Clearing this removes only the current revision and restores the
                                one before it.
                            </span>
                        </span>
                    </label>
                </div>
            )}
        </Modal>
    );
}

/* -------------------------------------------------------------------------- */
/* Sharing                                                                     */
/* -------------------------------------------------------------------------- */

export function ShareDialog({
    document,
    onClose,
    onChanged,
}: {
    document: WorkspaceDocument;
    onClose: () => void;
    onChanged: () => void;
}) {
    const documentId = String(document.id ?? document.document_id ?? '');
    const [sharedUsers, setSharedUsers] = useState<SharedDocumentUser[]>([]);
    const [term, setTerm] = useState('');
    const [results, setResults] = useState<SharedDocumentUser[]>([]);
    const [loading, setLoading] = useState(true);
    const [searching, setSearching] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const loadSharedUsers = async () => {
        setLoading(true);
        try {
            const response = await fetchPersonalDocumentSharedUsers(documentId);
            setSharedUsers(response.shared_users ?? []);
        } catch {
            setError('Could not load who this is shared with.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        void loadSharedUsers();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [documentId]);

    const search = async () => {
        const query = term.trim();
        if (!query) {
            return;
        }
        setSearching(true);
        setError(null);
        try {
            setResults(await searchShareableUsers(query));
        } catch {
            setError('User search failed.');
        } finally {
            setSearching(false);
        }
    };

    const share = async (userId: string) => {
        try {
            await sharePersonalDocument(documentId, userId);
            await loadSharedUsers();
            onChanged();
        } catch {
            setError('Could not share the document with that person.');
        }
    };

    const unshare = async (userId: string) => {
        try {
            await unsharePersonalDocument(documentId, userId);
            await loadSharedUsers();
            onChanged();
        } catch {
            setError('Could not stop sharing with that person.');
        }
    };

    return (
        <Modal
            title="Share document"
            description={String(document.file_name ?? '')}
            onClose={onClose}
            footer={
                <GlassButton variant="ghost" size="sm" onClick={onClose}>
                    Done
                </GlassButton>
            }
        >
            <div className="space-y-4">
                {error ? (
                    <p className="rounded-lg bg-danger-soft px-2.5 py-1.5 text-xs text-danger">
                        {error}
                    </p>
                ) : null}

                <div>
                    <h3 className="mb-1.5 text-xs font-semibold text-text-2">Shared with</h3>
                    {loading ? (
                        <p className="text-xs text-text-3">Loading…</p>
                    ) : sharedUsers.length === 0 ? (
                        <p className="text-xs text-text-3">Not shared with anyone yet.</p>
                    ) : (
                        <ul className="space-y-1">
                            {sharedUsers.map((user) => (
                                <li
                                    key={user.id}
                                    className="flex items-center gap-2 rounded-lg border border-edge px-2.5 py-1.5"
                                >
                                    <div className="min-w-0 flex-1">
                                        <p className="truncate text-xs text-text-1">
                                            {user.displayName || user.id}
                                        </p>
                                        {user.email ? (
                                            <p className="truncate text-[11px] text-text-3">
                                                {user.email}
                                            </p>
                                        ) : null}
                                    </div>
                                    {user.approval_status === 'not_approved' ? (
                                        <span className="rounded-full bg-warn-soft px-2 py-0.5 text-[10px] font-medium text-warn">
                                            Pending
                                        </span>
                                    ) : null}
                                    <button
                                        type="button"
                                        onClick={() => void unshare(user.id)}
                                        className="rounded px-1.5 py-0.5 text-[11px] text-text-3 hover:bg-danger-soft hover:text-danger"
                                    >
                                        Remove
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>

                <div>
                    <h3 className="mb-1.5 text-xs font-semibold text-text-2">Add someone</h3>
                    <div className="flex gap-2">
                        <div className="relative flex-1">
                            <Search
                                size={14}
                                className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3"
                            />
                            <input
                                type="search"
                                value={term}
                                onChange={(event) => setTerm(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter') {
                                        event.preventDefault();
                                        void search();
                                    }
                                }}
                                placeholder="Search by name or email"
                                className="w-full rounded-lg border border-edge bg-surface-1 py-1.5 pr-2 pl-7 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                            />
                        </div>
                        <GlassButton
                            variant="subtle"
                            size="sm"
                            onClick={() => void search()}
                            disabled={searching || !term.trim()}
                        >
                            {searching ? <Loader2 size={14} className="animate-spin" /> : null}
                            Search
                        </GlassButton>
                    </div>

                    {results.length > 0 ? (
                        <ul className="mt-2 space-y-1">
                            {results.map((user) => (
                                <li
                                    key={user.id}
                                    className="flex items-center gap-2 rounded-lg border border-edge px-2.5 py-1.5"
                                >
                                    <div className="min-w-0 flex-1">
                                        <p className="truncate text-xs text-text-1">
                                            {user.displayName || user.id}
                                        </p>
                                        {user.email ? (
                                            <p className="truncate text-[11px] text-text-3">
                                                {user.email}
                                            </p>
                                        ) : null}
                                    </div>
                                    <GlassButton
                                        variant="subtle"
                                        size="sm"
                                        onClick={() => void share(user.id)}
                                    >
                                        Add
                                    </GlassButton>
                                </li>
                            ))}
                        </ul>
                    ) : null}
                </div>
            </div>
        </Modal>
    );
}

/** A tag swatch used by the tag manager, kept here so the colour maths has one home. */
export function TagSwatch({ color }: { color?: string }) {
    return (
        <span
            className="inline-flex h-5 w-5 items-center justify-center rounded border border-edge"
            style={{ backgroundColor: color || 'transparent', color: readableTextColor(color) }}
        />
    );
}
