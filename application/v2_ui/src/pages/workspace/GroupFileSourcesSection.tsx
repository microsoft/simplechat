// GroupFileSourcesSection.tsx
// The group workspace file sources section: connections a group syncs documents from.
//
// This mirrors the personal FileSourcesSection's list and run history, but adds the writes a group
// manager can make natively -- create, edit, sync, test and delete -- through the scope-aware
// fileSourceWorkbench adapter. Every gate comes from that adapter: the New control appears only when
// the workspace advertises creation, and a row's Edit, Sync and Delete appear only when the row
// itself carries the operation, so a member sees a read-only list. Writing happens in a dialog that
// can test the connection and browse the remote path before the source is saved.
//
// Three refusals are handled honestly. A stale config_revision on save keeps the draft open and
// offers a reload rather than losing the edit. A sync that is already running is explained rather
// than swallowed. And a delete is deliberate about the documents the source produced: the manager
// chooses whether to remove them, the counts are shown, and a refusal that already removed the
// documents says so instead of claiming nothing changed.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, FolderSync, Pencil, Play, Plus, Trash2 } from 'lucide-react';
import {
    Pill,
    ResourceRow,
    RowAction,
    SectionIntro,
    SectionList,
    SectionSearch,
} from '../../components/workspace/primitives';
import { GlassButton } from '../../components/ui/primitives';
import { Modal } from '../../components/ui/Modal';
import { errorMessage, useSectionResource } from '../../components/workspace/useSectionResource';
import { FileSourceEditorDialog } from '../../components/fileSources/FileSourceEditorDialog';
import {
    FileSourceBusyError,
    FileSourceConflictError,
    FileSourceDeleteIncompleteError,
    FileSourcePartialDeleteError,
    FileSourceWriteConflictError,
    createPublicFileSourceWorkbench,
    type FileSourceDeleteOutcome,
    type FileSourceWorkbenchAdapter,
} from '../../lib/fileSourceWorkbench';
import {
    buildFileSourceWrite,
    connectionDescriptor,
    draftFromSource,
    emptyFileSourceDraft,
    sourcePathText,
    sourceTypeLabel,
    visibleSourceTypes,
    FILE_SOURCE_REBASE_FIELDS,
    type FileSourceDraft,
} from '../../lib/fileSourceFields';
import { rebaseDraft, rebaseNotice, REBASE_DELETED_NOTICE } from '../../lib/rebaseDraft';
import { statusTone } from './WorkflowsSection';
import { toast } from '../../stores/toastStore';
import { ApiError, safeSameOriginUrl } from '../../lib/apiClient';
import type {
    FileSourceOptions,
    WorkspaceIdentity,
    WorkspaceSyncRun,
    WorkspaceSyncSource,
} from '../../lib/types';
import type { PublicWorkspaceContext } from '../../lib/workspaceContext';

function formatTimestamp(value: unknown): string {
    const raw = String(value ?? '');
    if (!raw) {
        return '';
    }
    const parsed = new Date(raw);
    return Number.isNaN(parsed.valueOf()) ? raw : parsed.toLocaleString();
}

function GroupSourceRuns({
    adapter,
    sourceId,
}: {
    adapter: FileSourceWorkbenchAdapter;
    sourceId: string;
}) {
    const load = useCallback((signal: AbortSignal) => adapter.runs(sourceId, signal), [adapter, sourceId]);
    const { items, loading, error } = useSectionResource<WorkspaceSyncRun>(load, 'Failed to load sync history.');

    if (loading) {
        return <p className="px-3 pb-3 text-xs text-text-3">Loading history…</p>;
    }
    if (error) {
        return <p className="px-3 pb-3 text-xs text-danger">{error}</p>;
    }
    if (items.length === 0) {
        return <p className="px-3 pb-3 text-xs text-text-3">This source has not run yet.</p>;
    }

    return (
        <ul className="space-y-1 px-3 pb-3">
            {items.slice(0, 10).map((run) => (
                <li key={run.id} className="flex items-center gap-2 text-xs text-text-3">
                    <Pill tone={statusTone(run.status)}>{String(run.status ?? 'unknown')}</Pill>
                    <span className="truncate">
                        {formatTimestamp(run.started_at) || 'Not started'}
                        {run.completed_at ? ` → ${formatTimestamp(run.completed_at)}` : ''}
                    </span>
                </li>
            ))}
        </ul>
    );
}

function deleteCountsText(result: FileSourceDeleteOutcome): string {
    const parts = [`${result.documents_deleted} deleted`];
    if (result.documents_skipped) {
        parts.push(`${result.documents_skipped} skipped`);
    }
    if (result.documents_failed) {
        parts.push(`${result.documents_failed} failed`);
    }
    return parts.join(', ');
}

interface DeleteState {
    source: WorkspaceSyncSource;
    busy: boolean;
    error: string | null;
    conflict: boolean;
    /** Counts from a delete that was refused after removing some documents, kept visible on retry. */
    result: FileSourceDeleteOutcome | null;
}

export function FileSourcesWorkbenchSection({
    adapter,
    scopeNoun = 'group',
}: {
    adapter: FileSourceWorkbenchAdapter;
    // Scope-specific copy so a public workspace reuses this section verbatim: 'group' keeps the
    // shipped group wording byte-identical; a public workspace passes 'workspace'. Everything else
    // -- reads, gates, the editor dialog, sync/test/browse and delete handling -- is scope-agnostic
    // and comes from the adapter.
    scopeNoun?: string;
}) {
    const load = useCallback((signal: AbortSignal) => adapter.list(signal), [adapter]);
    const { items, loading, error, loadFailed, refresh, setItems, setError } =
        useSectionResource<WorkspaceSyncSource>(load, 'Failed to load file sources.');

    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState<string | null>(null);
    const [expandedId, setExpandedId] = useState<string | null>(null);

    // Editor state.
    const [draft, setDraft] = useState<FileSourceDraft | null>(null);
    // The source as the editor loaded it, so a conflict reload can tell the user's edits from the
    // other writer's. Set only for an edit; a new source cannot conflict.
    const [baseline, setBaseline] = useState<FileSourceDraft | null>(null);
    const [editingId, setEditingId] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    // A conditional-write conflict on save: the draft stays open and a reload is offered.
    const [saveConflict, setSaveConflict] = useState(false);
    const [editorLoading, setEditorLoading] = useState(false);
    const [editorOpen, setEditorOpen] = useState(false);
    const [editorTarget, setEditorTarget] = useState<WorkspaceSyncSource | null>(null);
    const [editingSource, setEditingSource] = useState<WorkspaceSyncSource | null>(null);
    const [sourceDeleted, setSourceDeleted] = useState(false);
    const editorRequest = useRef<AbortController | null>(null);
    const editorOpener = useRef<HTMLElement | null>(null);
    const [options, setOptions] = useState<FileSourceOptions | null>(null);
    const [identities, setIdentities] = useState<WorkspaceIdentity[]>([]);
    // Existing workspace tags are optional suggestions; a failed read
    // only costs the suggestions, so the editor still opens and a tag can still be typed.
    const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
    const [tagSuggestionsFailed, setTagSuggestionsFailed] = useState(false);

    const [deleteState, setDeleteState] = useState<DeleteState | null>(null);

    const canCreate = adapter.allows('create');
    const documentsHref = adapter.scope.kind === 'personal'
        ? '/workspace/documents'
        : adapter.scope.kind === 'group'
            ? `/groups/${encodeURIComponent(adapter.scope.id)}/documents`
            : `/public/${encodeURIComponent(adapter.scope.id)}/documents`;

    // Scope wrappers remount for another target; same-scope permission refreshes keep the draft.
    useEffect(() => () => editorRequest.current?.abort(), []);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return items;
        }
        return items.filter((source) =>
            `${source.name ?? ''} ${sourcePathText(source)}`.toLowerCase().includes(needle),
        );
    }, [items, query]);

    const openEditor = async (source: WorkspaceSyncSource | null) => {
        if (!editorOpen) {
            editorOpener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        }
        editorRequest.current?.abort();
        const controller = new AbortController();
        editorRequest.current = controller;
        setEditorOpen(true);
        setEditorTarget(source);
        setDraft(null);
        setBaseline(null);
        setEditingSource(null);
        setSaving(false);
        setSourceDeleted(false);
        setSaveError(null);
        setSaveConflict(false);
        setEditingId(source ? source.id : null);
        setEditorLoading(true);
        setTagSuggestions([]);
        setTagSuggestionsFailed(false);
        void adapter.tags(controller.signal).then((tags) => {
            if (!controller.signal.aborted) setTagSuggestions(tags);
        }, () => {
            if (!controller.signal.aborted) setTagSuggestionsFailed(true);
        });
        try {
            const [loadedOptions, loadedIdentities, loadedSource] = await Promise.all([
                adapter.options(controller.signal),
                adapter.identities(controller.signal),
                source ? adapter.read(source, controller.signal) : Promise.resolve(null),
            ]);
            if (controller.signal.aborted) return;
            if (!loadedOptions) {
                throw new Error('The editor options are unavailable. Retry to load them.');
            }
            setOptions(loadedOptions);
            setIdentities(loadedIdentities);
            const minInterval = loadedOptions?.schedule?.min_interval_minutes ?? 1;
            if (loadedSource) {
                connectionDescriptor(String(loadedSource.source_type));
                const loadedDraft = draftFromSource(loadedSource, minInterval);
                setDraft(loadedDraft);
                setBaseline(loadedDraft);
                setEditingSource(loadedSource);
            } else {
                const firstType = visibleSourceTypes(loadedOptions)[0]?.value;
                if (!firstType) {
                    throw new Error('No source types are available. Ask an administrator to review File Sync settings.');
                }
                connectionDescriptor(firstType);
                setDraft({
                    ...emptyFileSourceDraft(firstType, minInterval),
                    recursive: loadedOptions.recursive_allowed,
                    remoteDeletePolicy: loadedOptions.default_remote_delete_policy ?? 'ignore',
                });
            }
        } catch (loadError) {
            if (!controller.signal.aborted) setSaveError(errorMessage(loadError, 'Could not load the editor options.'));
        } finally {
            if (!controller.signal.aborted) setEditorLoading(false);
        }
    };

    const closeEditor = () => {
        editorRequest.current?.abort();
        setEditorOpen(false);
        setDraft(null);
        setBaseline(null);
        setEditingId(null);
        setEditingSource(null);
        setSaving(false);
        setSaveError(null);
        setSaveConflict(false);
    };

    const onSave = async () => {
        if (!draft || sourceDeleted) {
            return;
        }
        const controller = editorRequest.current;
        setSaving(true);
        setSaveError(null);
        setSaveConflict(false);
        try {
            const write = buildFileSourceWrite(draft);
            if (editingId) {
                const current = editingSource;
                if (!current) {
                    throw new Error('This file source is no longer available. Reload and try again.');
                }
                await adapter.update(current, write);
            } else {
                await adapter.create(write);
            }
            if (controller?.signal.aborted) return;
            closeEditor();
            await refresh();
            toast.success(editingId ? 'File source saved' : 'File source created');
        } catch (writeError) {
            if (controller?.signal.aborted) return;
            if (writeError instanceof FileSourceConflictError) {
                // The config revision moved. Keep the draft open. Reload brings the new
                // config_revision, and saving again applies the edit on top of it.
                setSaveConflict(true);
                setSaveError(writeError.message);
            } else if (writeError instanceof FileSourceWriteConflictError) {
                // A bare etag race whose config revision is unchanged. Nothing the draft depends on
                // moved, so keep it and let a plain retry through -- no reload is offered.
                setSaveConflict(false);
                setSaveError(writeError.message);
            } else {
                // Any other failure, including the server's reviewed 400 validation messages, is
                // shown verbatim and the draft is kept so the fields are not lost.
                setSaveError(errorMessage(writeError, 'Could not save the file source.'));
            }
        } finally {
            if (!controller?.signal.aborted) setSaving(false);
        }
    };

    const onConflictReload = async () => {
        if (!editingId || !draft || !baseline) {
            setSaveConflict(false);
            setSaveError(null);
            await refresh();
            return;
        }
        const controller = editorRequest.current;
        setSaving(true);
        try {
            if (!editingSource) throw new Error(REBASE_DELETED_NOTICE);
            const current = await adapter.read(editingSource, controller?.signal);
            if (controller?.signal.aborted) return;
            setItems(items.map((source) => source.id === current.id ? current : source));
            const minInterval = options?.schedule?.min_interval_minutes ?? 1;
            const freshDraft = draftFromSource(current, minInterval);
            const { draft: rebased, conflicts } = rebaseDraft(baseline, freshDraft, draft, FILE_SOURCE_REBASE_FIELDS);
            setDraft(rebased);
            setBaseline(freshDraft);
            setEditingSource(current);
            setSaveConflict(false);
            setSaveError(rebaseNotice(conflicts));
        } catch (reloadError) {
            if (controller?.signal.aborted) return;
            if (reloadError instanceof ApiError && reloadError.status === 404) {
                setSourceDeleted(true);
                setSaveConflict(false);
                setSaveError(REBASE_DELETED_NOTICE);
                return;
            }
            setSaveError(errorMessage(reloadError, 'Could not reload the latest version.'));
        } finally {
            if (!controller?.signal.aborted) setSaving(false);
        }
    };

    const onTest = async () => {
        if (sourceDeleted) throw new Error(REBASE_DELETED_NOTICE);
        if (!draft) {
            throw new Error('There is nothing to test yet.');
        }
        const write = buildFileSourceWrite(draft);
        const saved = editingSource;
        if (editingId && !saved) throw new Error(REBASE_DELETED_NOTICE);
        return adapter.testConnection(saved, write);
    };

    const onBrowse = async (browsePath: string) => {
        if (sourceDeleted) throw new Error(REBASE_DELETED_NOTICE);
        if (!draft) {
            throw new Error('There is nothing to browse yet.');
        }
        const write = buildFileSourceWrite(draft);
        const saved = editingSource;
        if (editingId && !saved) throw new Error(REBASE_DELETED_NOTICE);
        return adapter.browse(saved, write, browsePath);
    };

    const onIgnore = editingId
        ? async (remotePath: string, ignored: boolean) => {
              if (sourceDeleted) throw new Error(REBASE_DELETED_NOTICE);
              const item = await adapter.ignorePath(editingId, remotePath, ignored);
              return Boolean(item.ignored);
          }
        : undefined;

    const onSync = async (source: WorkspaceSyncSource) => {
        setBusyId(source.id);
        setError(null);
        try {
            await adapter.sync(source.id);
            toast.success(`Sync started for ${source.name ?? 'source'}`);
            await refresh();
        } catch (syncError) {
            // The two reviewed Sync now refusals (already running, concurrent-run limit) carry a
            // public message that is shown verbatim.
            setError(errorMessage(syncError, 'Could not start the sync.'));
        } finally {
            setBusyId(null);
        }
    };

    const openDelete = (source: WorkspaceSyncSource) => {
        setDeleteState({ source, busy: false, error: null, conflict: false, result: null });
    };

    const closeDelete = () => setDeleteState(null);

    const onConfirmDelete = async (deleteAssociatedFiles: boolean) => {
        if (!deleteState) {
            return;
        }
        const target = deleteState.source;
        setDeleteState({ ...deleteState, busy: true, error: null, conflict: false });
        try {
            const outcome = await adapter.remove(target, deleteAssociatedFiles);
            setItems(items.filter((source) => source.id !== target.id));
            closeDelete();
            const counts = deleteAssociatedFiles ? ` (${deleteCountsText(outcome)})` : '';
            toast.success(`File source deleted${counts}`);
            await refresh();
        } catch (deleteError) {
            if (deleteError instanceof FileSourceDeleteIncompleteError) {
                // The documents were removed but the source could not be, so it stays in the list.
                // Keep the modal open with the counts so the manager can retry.
                setDeleteState({
                    source: target,
                    busy: false,
                    error: deleteError.message,
                    conflict: false,
                    result: deleteError.result,
                });
            } else if (deleteError instanceof FileSourcePartialDeleteError) {
                // The documents were deleted even though removing the source did not finish. Say so
                // plainly, then reload to show the true state rather than guessing at the row.
                closeDelete();
                toast.info(
                    `The documents were deleted (${deleteCountsText(deleteError.result)}), but removing the source did not finish. Reloading.`,
                );
                await refresh();
            } else if (deleteError instanceof FileSourceBusyError) {
                setDeleteState({ source: target, busy: false, error: deleteError.message, conflict: false, result: null });
            } else if (deleteError instanceof FileSourceWriteConflictError) {
                // A bare etag race with an unchanged config revision: a plain retry is enough, so
                // keep the modal without offering a reload.
                setDeleteState({ source: target, busy: false, error: deleteError.message, conflict: false, result: null });
            } else if (deleteError instanceof FileSourceConflictError) {
                setDeleteState({ source: target, busy: false, error: deleteError.message, conflict: true, result: null });
            } else {
                setDeleteState({
                    source: target,
                    busy: false,
                    error: errorMessage(deleteError, 'Could not delete the file source.'),
                    conflict: false,
                    result: null,
                });
            }
        }
    };

    const onDeleteConflictReload = async () => {
        closeDelete();
        await refresh();
    };

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <SectionIntro
                    title="File sources"
                    description={`Places this ${scopeNoun}'s files already live. Approved files are brought in and processed the same way an upload is, then appear in the ${scopeNoun}'s documents. Secrets are held server-side and never sent back to the browser.`}
                />
                {canCreate ? (
                    <GlassButton variant="primary" size="sm" onClick={() => void openEditor(null)}>
                        <Plus size={14} />
                        New file source
                    </GlassButton>
                ) : null}
            </div>

            <p className="text-xs text-text-3">
                {canCreate
                    ? 'Connect a source to bring documents in without uploading them one by one.'
                    : `A workspace manager can connect a source for this ${scopeNoun}.`}
                {' '}Files appear in{' '}
                <Link to={safeSameOriginUrl(documentsHref, '/workspace/documents')} className="text-accent hover:underline">Documents</Link>.
            </p>

            <SectionSearch value={query} onChange={setQuery} placeholder="Search file sources" />

            <SectionList
                items={visible}
                loading={loading}
                error={error}
                loadFailed={loadFailed}
                onRetry={() => void refresh()}
                retryLabel="Retry file sources"
                emptyIcon={<FolderSync size={28} />}
                emptyTitle={items.length === 0 ? 'No file sources yet' : 'No sources match your search'}
                emptyDescription={
                    items.length === 0
                        ? canCreate
                            ? 'Connect a source to bring documents in without uploading them one by one.'
                            : `This ${scopeNoun} has no file sources yet. A workspace manager can add one.`
                        : undefined
                }
                getKey={(source, index) => String(source.id ?? index)}
                renderItem={(source) => {
                    const expanded = expandedId === source.id;
                    const canEdit = adapter.allows('edit', source);
                    const canSync = adapter.allows('sync', source);
                    const canDelete = adapter.allows('delete', source);
                    return (
                        <div>
                            <ResourceRow
                                icon={<FolderSync size={17} />}
                                title={String(source.name ?? 'Untitled source')}
                                subtitle={sourcePathText(source)}
                                meta={
                                    <>
                                        <Pill>{sourceTypeLabel(source.source_type)}</Pill>
                                        <Pill tone={source.enabled ? 'ok' : 'neutral'}>
                                            {source.enabled ? 'Enabled' : 'Paused'}
                                        </Pill>
                                        {source.identity_name ? (
                                            <Pill tone="accent">{String(source.identity_name)}</Pill>
                                        ) : null}
                                    </>
                                }
                                actions={
                                    <>
                                        <RowAction
                                            icon={expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                                            label={expanded ? 'Hide sync history' : 'Show sync history'}
                                            onClick={() => setExpandedId(expanded ? null : source.id)}
                                        />
                                        {canSync ? (
                                            <RowAction
                                                icon={<Play size={15} />}
                                                label={`Sync ${source.name ?? 'source'} now`}
                                                busy={busyId === source.id}
                                                onClick={() => void onSync(source)}
                                            />
                                        ) : null}
                                        {canEdit ? (
                                            <RowAction
                                                icon={<Pencil size={15} />}
                                                label={`Edit ${source.name ?? 'source'}`}
                                                onClick={() => void openEditor(source)}
                                            />
                                        ) : null}
                                        {canDelete ? (
                                            <RowAction
                                                icon={<Trash2 size={15} />}
                                                label={`Delete ${source.name ?? 'source'}`}
                                                danger
                                                onClick={() => openDelete(source)}
                                            />
                                        ) : null}
                                    </>
                                }
                            />
                            {expanded ? <GroupSourceRuns adapter={adapter} sourceId={source.id} /> : null}
                        </div>
                    );
                }}
            />

            {editorOpen && !draft ? (
                <Modal
                    title={editingId ? 'Edit file source' : 'New file source'}
                    returnFocusTo={editorOpener.current}
                    onClose={closeEditor}
                    footer={
                        <>
                            <GlassButton size="sm" onClick={closeEditor}>Cancel</GlassButton>
                            {!editorLoading ? (
                                <GlassButton size="sm" onClick={() => void openEditor(editorTarget)}>
                                    Retry editor
                                </GlassButton>
                            ) : null}
                        </>
                    }
                >
                    {editorLoading ? <p role="status">Loading file source configuration…</p>
                        : <p role="alert" className="text-sm text-danger">{saveError}</p>}
                </Modal>
            ) : null}

            {draft ? (
                <FileSourceEditorDialog
                    draft={draft}
                    returnFocusTo={editorOpener.current}
                    options={options}
                    identities={identities}
                    scopeNoun={scopeNoun}
                    tagSuggestions={tagSuggestions}
                    tagSuggestionsFailed={tagSuggestionsFailed}
                    saving={saving || editorLoading}
                    saveBlocked={sourceDeleted}
                    error={saveError}
                    onChange={setDraft}
                    onSave={() => void onSave()}
                    onCancel={closeEditor}
                    onRefresh={saveConflict ? () => void onConflictReload() : undefined}
                    onTest={onTest}
                    onBrowse={onBrowse}
                    onIgnore={onIgnore}
                />
            ) : null}

            {deleteState ? (
                <Modal
                    title={`Delete “${deleteState.source.name ?? 'file source'}”?`}
                    description="Removing the connection stops future syncs. Choose whether the documents it already brought in should be removed too."
                    onClose={deleteState.busy ? () => undefined : closeDelete}
                    footer={
                        <>
                            {deleteState.error ? (
                                <span className="mr-auto text-xs text-danger">{deleteState.error}</span>
                            ) : null}
                            <GlassButton size="sm" onClick={closeDelete} disabled={deleteState.busy}>
                                Cancel
                            </GlassButton>
                            {deleteState.conflict ? (
                                <GlassButton size="sm" onClick={() => void onDeleteConflictReload()}>
                                    Reload
                                </GlassButton>
                            ) : null}
                            <GlassButton
                                size="sm"
                                onClick={() => void onConfirmDelete(false)}
                                disabled={deleteState.busy}
                            >
                                Keep documents
                            </GlassButton>
                            <GlassButton
                                variant="danger"
                                size="sm"
                                onClick={() => void onConfirmDelete(true)}
                                disabled={deleteState.busy}
                            >
                                Delete documents too
                            </GlassButton>
                        </>
                    }

                >
                    <div className="space-y-3 text-sm text-text-2">
                        <p>
                            <strong>Keep documents</strong> removes the source but leaves everything it has already
                            imported in the {scopeNoun}'s documents.
                        </p>
                        <p>
                            <strong>Delete documents too</strong> also removes every document this source produced. This
                            cannot be undone.
                        </p>
                        {deleteState.result ? (
                            <p className="rounded-lg bg-warn-soft p-2 text-xs text-warn">
                                The documents were removed ({deleteCountsText(deleteState.result)}), but the source could
                                not be deleted. It is still listed. You can try deleting it again.
                            </p>
                        ) : null}
                    </div>
                </Modal>
            ) : null}
        </div>
    );
}

export function GroupFileSourcesSection({
    adapter,
    scopeNoun = 'group',
}: {
    adapter: FileSourceWorkbenchAdapter;
    scopeNoun?: string;
}) {
    const key = adapter.scope.kind === 'personal' ? 'personal' : `${adapter.scope.kind}:${adapter.scope.id}`;
    return <FileSourcesWorkbenchSection key={key} adapter={adapter} scopeNoun={scopeNoun} />;
}

/**
 * The file sources workbench bound to a public workspace (M10B).
 *
 * Mirrors the way GroupWorkspacePage builds the group file source adapter, but for public scope:
 * the adapter is memoised on the workspace identity and its management hint so switching workspaces
 * or receiving a fresh hint re-gates the write affordances. The public adapter reads and writes the
 * immutable-target `/api/public-workspaces/<id>/file-sources` family and never falls back to
 * personal or group behaviour.
 */
export function PublicFileSourcesSection({ context }: { context: PublicWorkspaceContext }) {
    const adapter = useMemo(
        () =>
            createPublicFileSourceWorkbench(
                { kind: 'public', id: context.scope.id, name: context.workspace.name },
                context.file_source_management,
            ),
        [context.scope.id, context.workspace.name, context.file_source_management],
    );
    return <GroupFileSourcesSection adapter={adapter} scopeNoun="workspace" />;
}
