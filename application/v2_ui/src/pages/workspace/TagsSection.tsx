// TagsSection.tsx
// The scoped tag vocabulary.
//
// Split out of the documents page on purpose. Browsing by tag and administering the set of
// tags are different jobs done at different times, and the classic interface does both from
// the same toolbar, which is a large part of why that page feels crowded. Here the documents
// page keeps the tags visible and applicable, and this section owns the vocabulary itself.
//
// Tags are deliberately flat. A document carries as many as it needs and none of them nest,
// which is what lets one document belong to several groupings at once -- the thing a folder
// tree cannot express.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, Merge, MessageSquare, Plus, Tag as TagIcon, Trash2 } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import type { WorkspaceTag } from '../../lib/types';
import {
    buildContextHandoffParams,
    type ContextHandoffState,
} from '../../lib/chatContextHandoff';
import { groupScope, PERSONAL_SCOPE } from '../../lib/chatContext';
import { clearContextTagCache } from '../../lib/contextMentions';
import { createGroupDocumentReader, documentExplorerScopeKey, PERSONAL_DOCUMENT_READER, type DocumentReadAdapter } from '../../lib/documentReadAdapter';
import {
    createGroupDocumentOperations, PERSONAL_DOCUMENT_OPERATIONS, type DocumentOperationAdapter,
    type TagMutationOutcome, type TagOperationError,
} from '../../lib/documentOperations';
import type { GroupWorkspaceContext } from '../../lib/workspaceContext';
import { groupWorkspacePath } from '../../lib/groupWorkspaceNavigation';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { GlassButton, EmptyState, Skeleton } from '../../components/ui/primitives';
import { SectionError, SectionIntro, SectionSearch } from '../../components/workspace/primitives';
import { errorMessage } from '../../components/workspace/useSectionResource';
import { readableTextColor } from '../../components/documents/documentPresentation';
import { toast } from '../../stores/toastStore';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { OperationFeedback } from '../../components/documents/DocumentDialogs';

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
    onChat,
    canManage,
    interactionDisabled,
    confirmColour,
    canChat,
    onDirtyChange,
}: {
    tag: WorkspaceTag;
    busy: boolean;
    existingNames: string[];
    onRename: (name: string) => Promise<boolean>;
    onRecolour: (color: string) => Promise<boolean>;
    onDelete: () => void;
    onChat: () => void;
    canManage: boolean;
    interactionDisabled: boolean;
    confirmColour: boolean;
    canChat: boolean;
    onDirtyChange: (name: string, dirty: boolean) => void;
}) {
    const [editing, setEditing] = useState(false);
    const [draftName, setDraftName] = useState(tag.name);
    const [editingColour, setEditingColour] = useState(false);
    const [draftColour, setDraftColour] = useState(tag.color || TAG_COLOR_PRESETS[0]);
    const colour = /^#[0-9a-f]{6}$/i.test(tag.color ?? '') ? tag.color! : TAG_COLOR_PRESETS[0];
    const disabled = busy || interactionDisabled || !canManage;
    useEffect(() => {
        onDirtyChange(tag.name, editing || editingColour);
        return () => onDirtyChange(tag.name, false);
    }, [tag.name, editing, editingColour, onDirtyChange]);
    const rename = async () => {
        if (disabled || !draftName.trim()) return;
        if (await onRename(draftName.trim())) setEditing(false);
    };

    const trimmed = draftName.trim();
    // Renaming onto an existing tag is how two tags are merged: the server rewrites every
    // document carrying the old name, and documents that already had both simply keep one.
    const willMerge =
        Boolean(trimmed) &&
        trimmed.toLowerCase() !== tag.name.toLowerCase() &&
        existingNames.some((name) => name.toLowerCase() === trimmed.toLowerCase());

    return (
        <li className="flex flex-wrap items-center gap-2.5 rounded-xl border border-edge bg-surface-1 px-3 py-2">
            <div className="flex min-w-0 flex-1 basis-full items-center gap-2.5 sm:basis-40">
            <label className="relative shrink-0" title="Change colour">
                <span
                    className="block h-5 w-5 rounded border border-edge"
                    style={{
                        backgroundColor: editingColour ? draftColour : colour,
                        color: readableTextColor(editingColour ? draftColour : colour),
                    }}
                />
                {canManage ? <input
                    type="color"
                    value={editingColour ? draftColour : colour}
                    disabled={disabled}
                    onChange={(event) => {
                        if (confirmColour) { setDraftColour(event.target.value); setEditingColour(true); }
                        else void onRecolour(event.target.value);
                    }}
                    aria-label={`Colour for ${tag.name}`}
                    className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                /> : null}
            </label>

            <div className="min-w-0 flex-1">
                {editing ? (
                    <div className="flex flex-wrap items-center gap-1.5">
                        <input
                            type="text"
                            value={draftName}
                            aria-label={`Rename ${tag.name}`}
                            disabled={busy}
                            autoFocus
                            onChange={(event) => setDraftName(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter') {
                                    event.preventDefault();
                                    void rename();
                                }
                                if (event.key === 'Escape' && !busy) {
                                    setDraftName(tag.name);
                                    setEditing(false);
                                }
                            }}
                            className="w-full min-w-0 basis-full rounded-lg border border-edge bg-surface-1 px-2 py-1 text-sm text-text-1 focus:border-accent focus:outline-none sm:flex-1 sm:basis-24"
                        />
                        <GlassButton
                            variant="primary"
                            size="sm"
                            disabled={!trimmed || disabled}
                            onClick={() => void rename()}
                        >
                            {willMerge ? <Merge size={13} /> : null}
                            {willMerge ? 'Merge' : 'Save'}
                        </GlassButton>
                        <GlassButton
                            variant="ghost"
                            size="sm"
                            disabled={busy}
                            onClick={() => {
                                setDraftName(tag.name);
                                setEditing(false);
                            }}
                        >
                            Cancel
                        </GlassButton>
                    </div>
                ) : canManage ? (
                    <button
                        type="button"
                        onClick={() => { setDraftName(tag.name); setEditing(true); }}
                        disabled={disabled}
                        className="truncate text-left text-sm text-text-1 hover:underline"
                        title="Rename this tag"
                    >
                        {tag.name}
                    </button>
                ) : <span className="block truncate text-sm text-text-1">{tag.name}</span>}
                {editing && willMerge ? (
                    <p className="mt-0.5 text-[11px] text-warn">
                        A tag with that name exists. Saving merges the two.
                    </p>
                ) : null}
            </div>
            </div>
            <div className="ml-auto flex items-center gap-2">
            <span className="shrink-0 text-xs tabular-nums text-text-3">
                {tag.count ?? 0} {tag.count === 1 ? 'document' : 'documents'}
            </span>

            {/* Chatting against a tag is the reason most of them exist: it is how a grouping
                becomes a body of material to ask questions of, rather than a filing label. */}
            <button
                type="button"
                onClick={onChat}
                disabled={!tag.count || !canChat || busy || interactionDisabled}
                aria-label={`Chat with documents tagged ${tag.name}`}
                title={
                    tag.count
                        ? `Chat with documents tagged ${tag.name}`
                        : 'No documents carry this tag yet'
                }
                className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-accent-soft hover:text-accent disabled:opacity-40"
            >
                <MessageSquare size={15} />
            </button>

            {canManage ? <button
                type="button"
                onClick={onDelete}
                disabled={disabled}
                aria-label={`Delete tag ${tag.name}`}
                title={`Delete tag ${tag.name}`}
                className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger disabled:opacity-40"
            >
                <Trash2 size={15} />
            </button> : null}
            </div>
            {editingColour ? <div className="flex basis-full flex-wrap gap-2">
                <GlassButton size="sm" disabled={disabled} onClick={() => {
                    void onRecolour(draftColour).then((saved) => { if (saved) setEditingColour(false); });
                }}>Save colour</GlassButton>
                <GlassButton size="sm" variant="ghost" disabled={busy} onClick={() => setEditingColour(false)}>Cancel colour</GlassButton>
            </div> : null}
        </li>
    );
}

interface TagsSectionProps {
    documentsEnabled: boolean;
    reader?: DocumentReadAdapter;
    operations?: DocumentOperationAdapter;
    canChat?: boolean;
    interactionDisabled?: boolean;
    onDirtyChange?: (dirty: boolean) => void;
    onBusyChange?: (busy: boolean) => void;
    onOpenClassic?: () => void;
}

export function GroupTagsSection({
    context, ...props
}: Omit<TagsSectionProps, 'documentsEnabled' | 'reader' | 'operations'> & { context: GroupWorkspaceContext }) {
    const reader = useMemo(() => createGroupDocumentReader(
        context.scope.id, context.workspace.name, context.document_queries,
    ), [context.scope.id, context.workspace.name, context.document_queries]);
    const operations = useMemo(() => createGroupDocumentOperations(
        { kind: 'group', id: context.scope.id, name: context.workspace.name }, context.document_management,
    ), [context.scope.id, context.workspace.name, context.document_management]);
    return <TagsSection {...props} documentsEnabled={context.document_permissions.can_view}
        canChat={context.document_permissions.can_chat} reader={reader} operations={operations} />;
}

export function TagsSection({
    reader = PERSONAL_DOCUMENT_READER, operations, ...props
}: TagsSectionProps) {
    const viewerId = useBootstrapStore((state) => state.data?.user.id);
    const resolved = useMemo(() => operations ?? (reader.scope.kind === 'group'
        ? createGroupDocumentOperations(reader.scope, undefined) : PERSONAL_DOCUMENT_OPERATIONS), [reader, operations]);
    if (!viewerId) return null;
    const scopeKey = documentExplorerScopeKey(viewerId, reader.scope);
    if (documentExplorerScopeKey(viewerId, resolved.scope) !== scopeKey) return (
        <SectionError message="Tag management scope does not match. Refresh this workspace before continuing." />
    );
    return <ScopedTagsSection key={scopeKey} reader={reader} operations={resolved} {...props} />;
}

function ScopedTagsSection({
    documentsEnabled, reader, operations, canChat = true, interactionDisabled = false,
    onDirtyChange, onBusyChange, onOpenClassic,
}: TagsSectionProps & { reader: DocumentReadAdapter; operations: DocumentOperationAdapter }) {
    const navigate = useNavigate();
    const [tags, setTags] = useState<WorkspaceTag[]>([]);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [newName, setNewName] = useState('');
    const [newColor, setNewColor] = useState(TAG_COLOR_PRESETS[0]);
    const [mutationError, setMutationError] = useState<string | null>(null);
    const [feedback, setFeedback] = useState<{ title: string; errors: TagOperationError[]; partial: boolean } | null>(null);
    const [dirtyTags, setDirtyTags] = useState<Set<string>>(new Set());
    const [deleting, setDeleting] = useState<WorkspaceTag | null>(null);
    const mounted = useRef(true);
    const request = useRef<AbortController | null>(null);
    const mutationBusy = useRef(false);
    const latest = useRef({ operations, interactionDisabled, loading, error });
    latest.current = { operations, interactionDisabled, loading, error };
    const isGroup = reader.scope.kind === 'group';
    const canManage = operations.supported.has('manage_tags');
    const paused = interactionDisabled || loading || Boolean(error);
    const dirty = Boolean(newName.trim() || dirtyTags.size || deleting);
    const reportRowDirty = useCallback((name: string, value: boolean) => {
        setDirtyTags((current) => {
            if (current.has(name) === value) return current;
            const next = new Set(current);
            value ? next.add(name) : next.delete(name);
            return next;
        });
    }, []);

    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; request.current?.abort(); };
    }, []);
    useEffect(() => {
        onDirtyChange?.(dirty);
        return () => onDirtyChange?.(false);
    }, [dirty, onDirtyChange]);
    useEffect(() => () => onBusyChange?.(false), [onBusyChange]);

    const load = useCallback(async (): Promise<boolean> => {
        request.current?.abort();
        if (!mounted.current || interactionDisabled) return false;
        const controller = new AbortController();
        request.current = controller;
        setLoading(true);
        setError(null);
        try {
            const response = await reader.tags(controller.signal);
            if (controller.signal.aborted || !mounted.current) return false;
            setTags(response.tags ?? []);
            return true;
        } catch (loadError) {
            if (!controller.signal.aborted && mounted.current) setError(errorMessage(loadError, 'Failed to load tags.'));
            return false;
        } finally {
            if (!controller.signal.aborted && mounted.current) setLoading(false);
        }
    }, [reader, interactionDisabled]);

    /**
     * Reload after a change, and drop the composer's memoized vocabulary with it.
     *
     * The `#` menu caches the tag list for a minute so it is not re-fetched on every
     * keystroke. Without this, a tag created or renamed here would be missing from that menu
     * -- or offered under its old name -- for up to that long afterwards.
     */
    const reload = useCallback(async () => {
        clearContextTagCache();
        return load();
    }, [load]);

    useEffect(() => {
        void load();
        return () => request.current?.abort();
    }, [load]);

    const mutate = async (
        title: string, operation: (adapter: DocumentOperationAdapter) => Promise<TagMutationOutcome>,
    ): Promise<boolean> => {
        const current = latest.current;
        if (!mounted.current) return false;
        if (mutationBusy.current || current.interactionDisabled || current.loading || current.error
            || !current.operations.allows('manage_tags')) {
            setMutationError('Tag changes are not currently permitted. Refresh access before saving; your draft is kept.');
            return false;
        }
        const adapter = current.operations;
        mutationBusy.current = true;
        setBusy(true);
        setMutationError(null);
        setFeedback(null);
        onBusyChange?.(true);
        try {
            const outcome = await operation(adapter);
            if (!mounted.current) return false;
            const partial = outcome.errors.length > 0 || outcome.vocabularyRetained;
            setFeedback({
                title: partial ? `${title} is incomplete. ${outcome.documentsUpdated} document updates were confirmed; retained vocabulary and failed items need attention.`
                    : isGroup ? `${title} confirmed for this group's owned documents.` : `${title} confirmed.`,
                errors: outcome.errors, partial,
            });
            const refreshed = await reload();
            if (!mounted.current) return false;
            if (partial) toast.error(`${title} is incomplete. Review the propagation failures before retrying.`);
            else if (refreshed) toast.success(`${title} confirmed.`);
            else toast.error(`${title} was confirmed, but the tag list could not be refreshed. Reload before another change.`);
            return !partial;
        } catch (cause) {
            if (mounted.current) setMutationError(errorMessage(cause, 'Could not confirm the tag change. Your draft is kept.'));
            return false;
        } finally {
            mutationBusy.current = false;
            if (mounted.current) { setBusy(false); onBusyChange?.(false); }
        }
    };

    /**
     * Take a tag to the composer as a context chip.
     *
     * The tag travels as a filter rather than as the documents carrying it, so the message
     * searches whatever holds the tag when it is sent rather than a list captured here.
     */
    const onChat = (tag: WorkspaceTag) => {
        if (mutationBusy.current || interactionDisabled || !canChat) {
            toast.error('Chat is not currently available for this tag selection.');
            return;
        }
        const scope = reader.scope.kind === 'group' ? groupScope(reader.scope) : PERSONAL_SCOPE;
        const query = buildContextHandoffParams({
            tags: [tag.name],
            docScope: reader.scope.kind,
            groupId: reader.scope.kind === 'group' ? reader.scope.id : undefined,
        });
        const state: ContextHandoffState = {
            contextTags: [{ name: tag.name, scope }],
        };
        navigate(`/chat?${query}`, { state });
    };

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
        if (!name) { setMutationError('Enter a tag name before creating it.'); return; }
        const saved = await mutate(`Create "${name}"`, (adapter) => adapter.createTag(name, newColor));
        if (saved && mounted.current) setNewName('');
    };

    const onRename = async (tag: WorkspaceTag, name: string) => {
        if (name === tag.name) return true;
        return mutate(`Rename "${tag.name}" to "${name}"`, (adapter) => adapter.updateTag(tag.name, { new_name: name }));
    };

    const onRecolour = async (tag: WorkspaceTag, color: string) => {
        return mutate(`Recolour "${tag.name}"`, (adapter) => adapter.updateTag(tag.name, { color }));
    };

    const onDelete = async (tag: WorkspaceTag) => {
        const removed = await mutate(`Delete "${tag.name}"`, (adapter) => adapter.deleteTag(tag.name));
        if (removed && mounted.current) setDeleting(null);
    };

    return (
        <div className="space-y-4">
            <SectionIntro
                title="Tags"
                description={isGroup
                    ? 'Group vocabulary changes affect only current documents owned by this group. Tags on incoming shares and older revisions remain unchanged.'
                    : 'The vocabulary your documents are filed under. Tags are flat, so a document can carry as many as it needs and appear under each of them.'}
            />
            {isGroup && onOpenClassic ? <GlassButton size="sm" disabled={busy || interactionDisabled}
                onClick={onOpenClassic}>Open classic group workspace</GlassButton> : null}
            {!canManage ? <p className="text-sm text-text-3">Tag management is not available with this workspace's current permissions. You can still browse its vocabulary.</p> : null}

            {documentsEnabled ? (
                <p className="text-xs text-text-3">
                    Apply tags from{' '}
                    <Link to={reader.scope.kind === 'group' ? groupWorkspacePath(reader.scope.id, 'documents') : '/workspace/documents'} className="text-accent hover:underline">
                        Documents
                    </Link>
                    , where you can also drag files onto a tag to file them.
                </p>
            ) : null}

            {canManage || newName ? <fieldset disabled={busy} className="flex min-w-0 flex-wrap items-end gap-2 rounded-xl border border-edge bg-surface-1 p-3">
                <label className="min-w-0 flex-1 basis-48">
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
                    <div className="flex flex-wrap items-center gap-1">
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
                    disabled={!newName.trim() || busy || !canManage || paused}
                >
                    {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                    Create
                </GlassButton>
                {newName ? <GlassButton size="sm" variant="ghost" disabled={busy}
                    onClick={() => { setNewName(''); setMutationError(null); }}>Cancel new tag</GlassButton> : null}
            </fieldset> : null}

            {error ? <div className="space-y-2"><SectionError message={error} />
                <GlassButton size="sm" disabled={busy || interactionDisabled} onClick={() => void reload()}>Retry tags</GlassButton>
            </div> : null}
            {mutationError && !deleting ? <SectionError message={mutationError} /> : null}
            {feedback && !deleting ? (feedback.errors.length ? <OperationFeedback title={feedback.title} errors={feedback.errors} />
                : <p role={feedback.partial ? 'alert' : 'status'} className="text-sm text-text-2">{feedback.title}</p>) : null}

            {tags.length > 6 ? (
                <fieldset disabled={busy || dirtyTags.size > 0}><SectionSearch value={query} onChange={setQuery} placeholder="Search tags" /></fieldset>
            ) : null}

            {loading && tags.length === 0 ? (
                <div className="space-y-2">
                    {Array.from({ length: 4 }).map((_, index) => (
                        <Skeleton key={index} className="h-12 w-full" />
                    ))}
                </div>
            ) : visible.length === 0 && !error ? (
                <EmptyState
                    icon={<TagIcon size={28} />}
                    title={tags.length === 0 ? 'No tags yet' : 'No tags match your search'}
                    description={
                        tags.length === 0
                            ? canManage ? 'Create a tag above, then apply it to documents from the Documents section.'
                                : 'This workspace has no visible tags.'
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
                                canManage={canManage}
                                canChat={canChat}
                                interactionDisabled={paused}
                                confirmColour={isGroup}
                                onDirtyChange={reportRowDirty}
                                existingNames={names}
                                onRename={(name) => onRename(tag, name)}
                                onRecolour={(color) => onRecolour(tag, color)}
                                onDelete={() => { setMutationError(null); setFeedback(null); setDeleting(tag); }}
                                onChat={() => onChat(tag)}
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
            {deleting ? <ConfirmDialog title="Delete tag" confirmLabel="Delete tag" busy={busy}
                confirmDisabled={!canManage || paused}
                description={`Remove "${deleting.name}" from ${reader.scope.kind === 'group' ? reader.scope.name : 'My workspace'}? Documents themselves are kept.`}
                onClose={() => {
                    if (mutationBusy.current) { toast.info('Wait for the tag operation to finish. It has not been cancelled.'); return; }
                    setDeleting(null);
                }}
                onConfirm={() => void onDelete(deleting)}>
                <p className="text-xs text-text-2">{isGroup
                    ? 'Only current owned documents are changed. Incoming shares and historical revisions are not rewritten.'
                    : 'The tag will be removed from documents that carry it.'}</p>
                {mutationError ? <SectionError message={mutationError} /> : null}
                {feedback ? <OperationFeedback title={feedback.title} errors={feedback.errors} /> : null}
            </ConfirmDialog> : null}
        </div>
    );
}
