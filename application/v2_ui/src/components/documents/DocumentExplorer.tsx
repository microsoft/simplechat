// DocumentExplorer.tsx
// The workspace documents explorer.
//
// Command bar, navigation rail, content pane, details pane and status bar. The layout is
// borrowed deliberately: giving each concern a permanent region is what stops the toolbar
// from becoming the dumping ground it is in the classic interface, where navigation,
// filtering, presentation and editing all compete for one band above the list.
//
// This component owns the query, the selection and the loading. The pieces around it are
// presentational, and the rules they share -- how a range selects, what a filter chip
// removes, when a page resets -- live in lib/documentExplorer.ts so they can be tested
// without a renderer.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FileText, Loader2, Upload } from 'lucide-react';
import type {
    DocumentExplorerPrefs,
    DocumentQuery,
    DocumentSavedView,
    DocumentSortField,
    WorkspaceDocument,
    WorkspaceTag,
} from '../../lib/types';
import {
    DEFAULT_DOCUMENT_PAGE_SIZE,
    DEFAULT_DOCUMENT_QUERY,
    EMPTY_SELECTION,
    applyQueryChange,
    applySelection,
    clearAllFilters,
    clearFilterChip,
    describeActiveFilters,
    documentId,
    documentStatus,
    moveSelection,
    normalizeSortField,
    pruneSelection,
    toggleSelectAll,
    toggleSort,
    type SelectionIntent,
    type SelectionState,
} from '../../lib/documentExplorer';
import {
    applySavedView,
    createSavedView,
    isSaveableQuery,
    parseSavedViews,
    removeSavedView,
    upsertSavedView,
} from '../../lib/documentSavedViews';
import {
    bulkDeletePersonalDocuments,
    bulkTagPersonalDocuments,
    createPersonalDocumentTag,
    downloadPersonalDocument,
    downloadPersonalDocuments,
    extractPersonalDocumentMetadata,
    fetchPersonalDocument,
    fetchPersonalDocumentFacets,
    fetchPersonalDocumentTags,
    fetchPersonalDocuments,
    reprocessPersonalDocumentExtraction,
    updatePersonalDocumentMetadata,
    uploadPersonalDocuments,
    type BulkDeleteError,
} from '../../lib/endpoints';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { toast } from '../../stores/toastStore';
import { EmptyState, GlassButton, Skeleton } from '../ui/primitives';
import { errorMessage } from '../workspace/useSectionResource';
import { ExplorerRail } from './ExplorerRail';
import {
    ExplorerCommandBar,
    ExplorerStatusBar,
    FilterChips,
} from './ExplorerCommandBar';
import { DEFAULT_DOCUMENT_COLUMNS, DocumentTable } from './DocumentTable';
import { DocumentTiles } from './DocumentTiles';
import { DocumentDetailsPane } from './DocumentDetailsPane';
import {
    DeleteDialog,
    MetadataDialog,
    ShareDialog,
    TagDialog,
    type MetadataDraft,
} from './DocumentDialogs';

/** How often an in-flight document is re-checked. Matches the classic interface. */
const PROGRESS_POLL_MS = 5000;

const DEFAULT_PREFS: DocumentExplorerPrefs = {
    viewMode: 'details',
    pageSize: DEFAULT_DOCUMENT_PAGE_SIZE,
    detailsPaneOpen: true,
    columns: DEFAULT_DOCUMENT_COLUMNS,
    sortBy: '_ts',
    sortOrder: 'desc',
};

type ActiveDialog =
    | { kind: 'tag'; documents: WorkspaceDocument[] }
    | { kind: 'metadata'; document: WorkspaceDocument }
    | { kind: 'share'; document: WorkspaceDocument }
    | { kind: 'delete'; documents: WorkspaceDocument[]; blocked: BulkDeleteError[] }
    | null;

/** Hand a blob to the browser as a download without navigating the tab. */
function saveBlob(blob: Blob, fileName: string) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

export function DocumentExplorer() {
    const features = useBootstrapStore((state) => state.data?.features);
    const settings = useBootstrapStore((state) => state.data?.settings);
    const userSettings = useUserSettingsStore((state) => state.settings);
    const saveUserSettings = useUserSettingsStore((state) => state.update);

    const storedPrefs = userSettings.v2DocumentsPrefs;
    const prefs: DocumentExplorerPrefs = useMemo(
        () => ({
            ...DEFAULT_PREFS,
            ...(storedPrefs ?? {}),
            columns: storedPrefs?.columns?.length
                ? storedPrefs.columns
                : DEFAULT_PREFS.columns,
        }),
        [storedPrefs],
    );

    const savedViews = useMemo(
        () => parseSavedViews(userSettings.v2DocumentSavedViews),
        [userSettings.v2DocumentSavedViews],
    );

    const [query, setQuery] = useState<DocumentQuery>(() => ({
        ...DEFAULT_DOCUMENT_QUERY,
        pageSize: prefs.pageSize,
        sortBy: normalizeSortField(prefs.sortBy),
        sortOrder: prefs.sortOrder === 'asc' ? 'asc' : 'desc',
    }));
    const [searchDraft, setSearchDraft] = useState('');

    const [documents, setDocuments] = useState<WorkspaceDocument[]>([]);
    const [totalCount, setTotalCount] = useState(0);
    const [downloadsEnabled, setDownloadsEnabled] = useState(false);
    const [tags, setTags] = useState<WorkspaceTag[]>([]);
    const [facets, setFacets] = useState<Parameters<typeof ExplorerRail>[0]['facets']>(null);

    const [selection, setSelection] = useState<SelectionState>(EMPTY_SELECTION);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [dialog, setDialog] = useState<ActiveDialog>(null);

    const fileInputRef = useRef<HTMLInputElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    const classifications = useMemo(() => {
        const raw = settings?.document_classification_categories;
        if (!Array.isArray(raw)) {
            return [] as { label: string; color?: string }[];
        }
        return raw
            .map((entry) => {
                const record = entry as { label?: unknown; color?: unknown };
                return {
                    label: String(record?.label ?? '').trim(),
                    color: record?.color ? String(record.color) : undefined,
                };
            })
            .filter((entry) => entry.label);
    }, [settings]);

    const tagColors = useMemo(() => {
        const colors: Record<string, string | undefined> = {};
        for (const tag of tags) {
            colors[tag.name] = tag.color;
        }
        return colors;
    }, [tags]);

    const classificationColors = useMemo(() => {
        const colors: Record<string, string | undefined> = {};
        for (const classification of classifications) {
            colors[classification.label] = classification.color;
        }
        return colors;
    }, [classifications]);

    const availability = useMemo(
        () => ({
            downloads: downloadsEnabled,
            extractMetadata: Boolean(features?.enable_extract_meta_data),
            sharing: Boolean(features?.enable_file_sharing),
            classification: Boolean(features?.enable_document_classification),
        }),
        [downloadsEnabled, features],
    );

    const orderedIds = useMemo(() => documents.map(documentId), [documents]);
    const selectedDocuments = useMemo(
        () => documents.filter((item) => selection.ids.includes(documentId(item))),
        [documents, selection.ids],
    );

    /* ---------------------------------------------------------------------- */
    /* Loading                                                                 */
    /* ---------------------------------------------------------------------- */

    const loadDocuments = useCallback(
        async (signal?: AbortSignal) => {
            setLoading(true);
            setError(null);
            try {
                const response = await fetchPersonalDocuments(query, signal);
                const items = response.documents ?? response.items ?? [];
                setDocuments(items);
                setTotalCount(Number(response.total_count ?? items.length));
                setDownloadsEnabled(Boolean(response.file_downloads_enabled));
                setSelection((current) => pruneSelection(current, items.map(documentId)));
            } catch (loadError) {
                if ((loadError as Error)?.name === 'AbortError') {
                    return;
                }
                setError(errorMessage(loadError, 'Failed to load documents.'));
            } finally {
                setLoading(false);
            }
        },
        [query],
    );

    const loadSidebar = useCallback(async (signal?: AbortSignal) => {
        const [tagsResult, facetsResult] = await Promise.allSettled([
            fetchPersonalDocumentTags(signal),
            fetchPersonalDocumentFacets(signal),
        ]);
        if (tagsResult.status === 'fulfilled') {
            setTags(tagsResult.value.tags ?? []);
        }
        if (facetsResult.status === 'fulfilled') {
            setFacets(facetsResult.value);
        }
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        void loadDocuments(controller.signal);
        return () => controller.abort();
    }, [loadDocuments]);

    useEffect(() => {
        const controller = new AbortController();
        void loadSidebar(controller.signal);
        return () => controller.abort();
    }, [loadSidebar]);

    /** Reload the list and the rail together, after anything that changes both. */
    const refreshAll = useCallback(async () => {
        await Promise.all([loadDocuments(), loadSidebar()]);
    }, [loadDocuments, loadSidebar]);

    /* ---------------------------------------------------------------------- */
    /* Progress polling                                                        */
    /* ---------------------------------------------------------------------- */

    const processingIds = useMemo(
        () =>
            documents
                .filter((item) => documentStatus(item).state === 'processing')
                .map(documentId)
                .filter(Boolean),
        [documents],
    );

    useEffect(() => {
        if (processingIds.length === 0) {
            return;
        }

        let cancelled = false;
        const timer = window.setInterval(async () => {
            // Refreshed one document at a time rather than by re-listing: a poll that
            // re-fetched the page would fight the user's scroll position and selection every
            // few seconds for as long as anything was indexing.
            const updates = await Promise.allSettled(
                processingIds.map((id) => fetchPersonalDocument(id)),
            );
            if (cancelled) {
                return;
            }

            const byId = new Map<string, WorkspaceDocument>();
            for (const update of updates) {
                if (update.status === 'fulfilled') {
                    const id = documentId(update.value);
                    if (id) {
                        byId.set(id, update.value);
                    }
                }
            }
            if (byId.size === 0) {
                return;
            }

            setDocuments((current) =>
                current.map((item) => byId.get(documentId(item)) ?? item),
            );

            const finished = [...byId.values()].some(
                (item) => documentStatus(item).state !== 'processing',
            );
            if (finished) {
                void loadSidebar();
            }
        }, PROGRESS_POLL_MS);

        return () => {
            cancelled = true;
            window.clearInterval(timer);
        };
    }, [processingIds, loadSidebar]);

    /* ---------------------------------------------------------------------- */
    /* Preferences                                                             */
    /* ---------------------------------------------------------------------- */

    const updatePrefs = useCallback(
        (change: Partial<DocumentExplorerPrefs>) => {
            saveUserSettings({ v2DocumentsPrefs: { ...prefs, ...change } });
        },
        [prefs, saveUserSettings],
    );

    /* ---------------------------------------------------------------------- */
    /* Query                                                                   */
    /* ---------------------------------------------------------------------- */

    const changeQuery = useCallback((change: Partial<DocumentQuery>) => {
        setQuery((current) => applyQueryChange(current, change));
    }, []);

    // Debounced so typing does not issue a request per keystroke.
    useEffect(() => {
        const timer = window.setTimeout(() => {
            setQuery((current) =>
                current.search === searchDraft
                    ? current
                    : applyQueryChange(current, { search: searchDraft }),
            );
        }, 300);
        return () => window.clearTimeout(timer);
    }, [searchDraft]);

    const onSort = useCallback(
        (field: DocumentSortField) => {
            setQuery((current) => {
                const next = toggleSort(current, field);
                updatePrefs({ sortBy: next.sortBy, sortOrder: next.sortOrder });
                return { ...next, page: 1 };
            });
        },
        [updatePrefs],
    );

    /* ---------------------------------------------------------------------- */
    /* Selection                                                               */
    /* ---------------------------------------------------------------------- */

    const onSelect = useCallback(
        (id: string, intent: SelectionIntent) => {
            setSelection((current) => applySelection(current, id, intent, orderedIds));
        },
        [orderedIds],
    );

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            const target = event.target as HTMLElement | null;
            const typing =
                target &&
                (target.tagName === 'INPUT' ||
                    target.tagName === 'TEXTAREA' ||
                    target.isContentEditable);
            if (typing || dialog) {
                return;
            }
            if (!containerRef.current?.contains(document.activeElement) &&
                document.activeElement !== document.body) {
                return;
            }

            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
                event.preventDefault();
                setSelection({ ids: [...orderedIds], anchorId: orderedIds[0] ?? null });
                return;
            }
            if (event.key === 'Escape') {
                setSelection(EMPTY_SELECTION);
                return;
            }
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                setSelection((current) =>
                    moveSelection(
                        current,
                        orderedIds,
                        event.key === 'ArrowDown' ? 1 : -1,
                        event.shiftKey,
                    ),
                );
            }
        };

        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [orderedIds, dialog]);

    const onDragStart = useCallback(
        (event: React.DragEvent, id: string) => {
            // Dragging an unselected row drags that row alone, which is what every file
            // manager does and what stops a stale selection being filed by accident.
            const ids = selection.ids.includes(id) ? selection.ids : [id];
            if (!selection.ids.includes(id)) {
                setSelection({ ids: [id], anchorId: id });
            }
            event.dataTransfer.setData(
                'application/x-simplechat-documents',
                JSON.stringify(ids),
            );
            event.dataTransfer.effectAllowed = 'copy';
        },
        [selection.ids],
    );

    /* ---------------------------------------------------------------------- */
    /* Actions                                                                 */
    /* ---------------------------------------------------------------------- */

    const runBulkTag = useCallback(
        async (
            ids: string[],
            action: 'add_tags' | 'remove_tags',
            tagNames: string[],
            options: { undoable?: boolean } = {},
        ) => {
            if (ids.length === 0 || tagNames.length === 0) {
                return;
            }
            setBusy(true);
            try {
                await bulkTagPersonalDocuments(ids, action, tagNames);
                await refreshAll();

                const verb = action === 'add_tags' ? 'Tagged' : 'Untagged';
                const message = `${verb} ${ids.length} ${ids.length === 1 ? 'document' : 'documents'}`;
                if (options.undoable) {
                    toast.success(`${message} with ${tagNames.join(', ')}`, {
                        label: 'Undo',
                        onAct: () => {
                            void runBulkTag(
                                ids,
                                action === 'add_tags' ? 'remove_tags' : 'add_tags',
                                tagNames,
                            );
                        },
                    });
                } else {
                    toast.success(message);
                }
            } catch (tagError) {
                toast.error(errorMessage(tagError, 'Could not update tags.'));
            } finally {
                setBusy(false);
            }
        },
        [refreshAll],
    );

    const onDropOnTag = useCallback(
        (tagName: string, ids: string[]) => {
            void runBulkTag(ids, 'add_tags', [tagName], { undoable: true });
        },
        [runBulkTag],
    );

    const onUploadFiles = useCallback(
        async (files: File[]) => {
            if (files.length === 0) {
                return;
            }

            const maxSizeMb = Number(settings?.max_file_size_mb ?? 0);
            if (maxSizeMb > 0) {
                const tooLarge = files.filter((file) => file.size > maxSizeMb * 1024 * 1024);
                if (tooLarge.length > 0) {
                    toast.error(
                        `${tooLarge.map((file) => file.name).join(', ')} exceeds the ${maxSizeMb} MB limit.`,
                    );
                    files = files.filter((file) => file.size <= maxSizeMb * 1024 * 1024);
                    if (files.length === 0) {
                        return;
                    }
                }
            }

            setUploading(true);
            const pendingId = toast.pending(
                `Uploading ${files.length} ${files.length === 1 ? 'file' : 'files'}…`,
            );
            try {
                const response = await uploadPersonalDocuments(files);
                const uploaded = response.document_ids?.length ?? 0;
                // The route answers 207 for a partial success, so `errors` has to be read
                // even though the request itself succeeded.
                if (response.errors?.length) {
                    toast.settle(
                        pendingId,
                        'error',
                        `Uploaded ${uploaded} of ${files.length}. ${response.errors[0]}`,
                    );
                } else {
                    toast.settle(pendingId, 'success', `Uploaded ${uploaded} of ${files.length}.`);
                }
                await refreshAll();
            } catch (uploadError) {
                toast.settle(
                    pendingId,
                    'error',
                    errorMessage(uploadError, 'Upload failed.'),
                );
            } finally {
                setUploading(false);
            }
        },
        [refreshAll, settings],
    );

    const onDownload = useCallback(async (targets: WorkspaceDocument[]) => {
        const ids = targets.map(documentId).filter(Boolean);
        if (ids.length === 0) {
            return;
        }
        const pendingId = toast.pending('Preparing download…');
        try {
            if (ids.length === 1) {
                const blob = await downloadPersonalDocument(ids[0]);
                saveBlob(blob, String(targets[0].file_name ?? 'document'));
            } else {
                const blob = await downloadPersonalDocuments(ids);
                saveBlob(blob, 'documents.zip');
            }
            toast.settle(pendingId, 'success', 'Download ready.');
        } catch (downloadError) {
            toast.settle(pendingId, 'error', errorMessage(downloadError, 'Download failed.'));
        }
    }, []);

    const onChat = useCallback((targets: WorkspaceDocument[]) => {
        const ids = targets.map(documentId).filter(Boolean);
        if (ids.length === 0) {
            return;
        }
        const params = new URLSearchParams({
            search_documents: 'true',
            doc_scope: 'personal',
            document_ids: ids.join(','),
        });
        window.location.href = `/chats?${params.toString()}`;
    }, []);

    const onExtractMetadata = useCallback(
        async (targets: WorkspaceDocument[]) => {
            const ids = targets.map(documentId).filter(Boolean);
            if (ids.length === 0) {
                return;
            }
            try {
                await extractPersonalDocumentMetadata(ids);
                toast.info(
                    `Metadata extraction queued for ${ids.length} ${ids.length === 1 ? 'document' : 'documents'}.`,
                );
                window.setTimeout(() => void refreshAll(), 1500);
            } catch (extractError) {
                toast.error(errorMessage(extractError, 'Could not queue metadata extraction.'));
            }
        },
        [refreshAll],
    );

    const onReextract = useCallback(
        async (targets: WorkspaceDocument[], mode: 'read' | 'layout') => {
            const ids = targets.map(documentId).filter(Boolean);
            if (ids.length === 0) {
                return;
            }
            try {
                await reprocessPersonalDocumentExtraction(ids, mode);
                toast.info(
                    `Re-extraction queued as ${mode === 'layout' ? 'enhanced' : 'standard'}.`,
                );
                window.setTimeout(() => void refreshAll(), 1500);
            } catch (reextractError) {
                toast.error(errorMessage(reextractError, 'Could not queue re-extraction.'));
            }
        },
        [refreshAll],
    );

    const onSaveMetadata = useCallback(
        async (target: WorkspaceDocument, draft: MetadataDraft) => {
            setBusy(true);
            try {
                await updatePersonalDocumentMetadata(documentId(target), {
                    title: draft.title,
                    abstract: draft.abstract,
                    publication_date: draft.publication_date,
                    document_classification: draft.document_classification,
                    authors: draft.authors
                        .split(',')
                        .map((entry) => entry.trim())
                        .filter(Boolean),
                    keywords: draft.keywords
                        .split(',')
                        .map((entry) => entry.trim())
                        .filter(Boolean),
                });
                setDialog(null);
                toast.success('Metadata saved.');
                await refreshAll();
            } catch (saveError) {
                toast.error(errorMessage(saveError, 'Could not save metadata.'));
            } finally {
                setBusy(false);
            }
        },
        [refreshAll],
    );

    const onConfirmDelete = useCallback(
        async (
            targets: WorkspaceDocument[],
            options: { force: boolean; deleteAllVersions: boolean },
        ) => {
            const ids = targets.map(documentId).filter(Boolean);
            if (ids.length === 0) {
                return;
            }
            setBusy(true);
            try {
                const response = await bulkDeletePersonalDocuments(ids, {
                    deleteMode: options.deleteAllVersions ? 'all_versions' : 'current_only',
                    conversationLinkedDeleteConfirmed: options.force,
                    fileSyncDeleteAction: options.force ? 'keep_source' : null,
                });

                const blocked = (response.errors ?? []).filter(
                    (entry) => entry.needs_confirmation,
                );
                const failed = (response.errors ?? []).filter(
                    (entry) => !entry.needs_confirmation,
                );

                if (blocked.length > 0) {
                    // Kept open, now listing exactly what was refused and why, so the user can
                    // decide about those documents rather than about the batch.
                    setDialog({ kind: 'delete', documents: targets, blocked });
                } else {
                    setDialog(null);
                }

                const deletedCount = response.deleted_count ?? 0;
                if (deletedCount > 0) {
                    toast.success(
                        `Deleted ${deletedCount} ${deletedCount === 1 ? 'document' : 'documents'}.`,
                    );
                }
                if (failed.length > 0) {
                    toast.error(failed[0].message ?? 'Some documents could not be deleted.');
                }

                setSelection(EMPTY_SELECTION);
                await refreshAll();
            } catch (deleteError) {
                toast.error(errorMessage(deleteError, 'Could not delete documents.'));
            } finally {
                setBusy(false);
            }
        },
        [refreshAll],
    );

    const onSaveView = useCallback(() => {
        const name = window.prompt('Name this view');
        if (!name?.trim()) {
            return;
        }
        const view = createSavedView(name, query);
        saveUserSettings({ v2DocumentSavedViews: upsertSavedView(savedViews, view) });
        toast.success(`Saved "${view.name}" to the rail.`);
    }, [query, savedViews, saveUserSettings]);

    const onDeleteSavedView = useCallback(
        (view: DocumentSavedView) => {
            if (!window.confirm(`Remove the saved view "${view.name}"?`)) {
                return;
            }
            saveUserSettings({
                v2DocumentSavedViews: removeSavedView(savedViews, view.id),
            });
        },
        [savedViews, saveUserSettings],
    );

    /* ---------------------------------------------------------------------- */
    /* Render                                                                  */
    /* ---------------------------------------------------------------------- */

    const chips = describeActiveFilters(query);

    const content = () => {
        if (loading && documents.length === 0) {
            return (
                <div className="space-y-2 p-2">
                    {Array.from({ length: 8 }).map((_, index) => (
                        <Skeleton key={index} className="h-10 w-full" />
                    ))}
                </div>
            );
        }

        if (documents.length === 0) {
            const filtered = chips.length > 0;
            return (
                <EmptyState
                    icon={<FileText size={28} />}
                    title={filtered ? 'No documents match these filters' : 'No documents yet'}
                    description={
                        filtered
                            ? undefined
                            : 'Upload a file to make it available for grounded chat.'
                    }
                    action={
                        filtered ? (
                            <GlassButton
                                variant="subtle"
                                size="sm"
                                onClick={() => {
                                    setSearchDraft('');
                                    setQuery((current) => clearAllFilters(current));
                                }}
                            >
                                Clear filters
                            </GlassButton>
                        ) : (
                            <GlassButton
                                variant="primary"
                                size="sm"
                                onClick={() => fileInputRef.current?.click()}
                            >
                                <Upload size={14} />
                                Upload a document
                            </GlassButton>
                        )
                    }
                />
            );
        }

        return prefs.viewMode === 'tiles' ? (
            <DocumentTiles
                documents={documents}
                selection={selection}
                tagColors={tagColors}
                classificationColors={classificationColors}
                onSelect={onSelect}
                onOpen={() => updatePrefs({ detailsPaneOpen: true })}
                onDragStart={onDragStart}
            />
        ) : (
            <DocumentTable
                documents={documents}
                columns={prefs.columns}
                query={query}
                selection={selection}
                tagColors={tagColors}
                classificationColors={classificationColors}
                onSelect={onSelect}
                onToggleSelectAll={() =>
                    setSelection((current) => toggleSelectAll(current, orderedIds))
                }
                onSort={onSort}
                onOpen={() => updatePrefs({ detailsPaneOpen: true })}
                onDragStart={onDragStart}
            />
        );
    };

    return (
        <div ref={containerRef} className="flex h-full min-h-0 flex-col gap-2">
            <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(event) => {
                    const files = Array.from(event.target.files ?? []);
                    event.target.value = '';
                    void onUploadFiles(files);
                }}
            />

            <ExplorerCommandBar
                query={query}
                prefs={prefs}
                selectionCount={selection.ids.length}
                uploading={uploading}
                availability={availability}
                canSaveView={isSaveableQuery(query)}
                onSearchChange={setSearchDraft}
                onUpload={() => fileInputRef.current?.click()}
                onDownload={() => void onDownload(selectedDocuments)}
                onTag={() => setDialog({ kind: 'tag', documents: selectedDocuments })}
                onChat={() => onChat(selectedDocuments)}
                onExtractMetadata={() => void onExtractMetadata(selectedDocuments)}
                onDelete={() =>
                    setDialog({ kind: 'delete', documents: selectedDocuments, blocked: [] })
                }
                onSaveView={onSaveView}
                onPrefsChange={(change) => {
                    updatePrefs(change);
                    if (change.pageSize) {
                        changeQuery({ pageSize: change.pageSize });
                    }
                }}
            />

            {error ? (
                <p className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
                    {error}
                </p>
            ) : null}

            <div className="flex min-h-0 flex-1 gap-3 overflow-hidden">
                <ExplorerRail
                    query={query}
                    facets={facets}
                    tags={tags}
                    savedViews={savedViews}
                    classifications={availability.classification ? classifications : []}
                    onQueryChange={changeQuery}
                    onApplySavedView={(view) => {
                        setSearchDraft(view.query.search);
                        setQuery((current) => applySavedView(current, view));
                    }}
                    onDeleteSavedView={onDeleteSavedView}
                    onDropOnTag={onDropOnTag}
                />

                <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
                    <FilterChips
                        chips={chips}
                        onClearChip={(chip) => {
                            if (chip.kind === 'search') {
                                setSearchDraft('');
                            }
                            setQuery((current) => clearFilterChip(current, chip));
                        }}
                        onClearAll={() => {
                            setSearchDraft('');
                            setQuery((current) => clearAllFilters(current));
                        }}
                    />

                    <div
                        className="min-h-0 flex-1 overflow-auto rounded-xl border border-edge bg-surface-1"
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={(event) => {
                            const files = Array.from(event.dataTransfer.files ?? []);
                            if (files.length > 0) {
                                event.preventDefault();
                                void onUploadFiles(files);
                            }
                        }}
                    >
                        {busy ? (
                            <div className="flex items-center gap-2 border-b border-edge px-3 py-1.5 text-xs text-text-3">
                                <Loader2 size={12} className="animate-spin" />
                                Working…
                            </div>
                        ) : null}
                        {content()}
                    </div>

                    <ExplorerStatusBar
                        page={query.page}
                        pageSize={query.pageSize}
                        totalCount={totalCount}
                        selectionCount={selection.ids.length}
                        onPageChange={(page) => changeQuery({ page })}
                        onPageSizeChange={(pageSize) => {
                            updatePrefs({ pageSize });
                            changeQuery({ pageSize });
                        }}
                    />
                </div>

                {prefs.detailsPaneOpen ? (
                    <DocumentDetailsPane
                        documents={selectedDocuments}
                        availability={availability}
                        actions={{
                            onChat,
                            onDownload: (targets) => void onDownload(targets),
                            onEditMetadata: (target) =>
                                setDialog({ kind: 'metadata', document: target }),
                            onExtractMetadata: (targets) => void onExtractMetadata(targets),
                            onReextract: (targets, mode) => void onReextract(targets, mode),
                            onShare: (target) => setDialog({ kind: 'share', document: target }),
                            onManageTags: (targets) =>
                                setDialog({ kind: 'tag', documents: targets }),
                            onDelete: (targets) =>
                                setDialog({ kind: 'delete', documents: targets, blocked: [] }),
                            onSelectTag: (tag) => changeQuery({ tags: [tag] }),
                            onRemoveTag: (targets, tag) =>
                                void runBulkTag(
                                    targets.map(documentId).filter(Boolean),
                                    'remove_tags',
                                    [tag],
                                ),
                        }}
                        tagColors={tagColors}
                        classificationColors={classificationColors}
                        onClose={() => updatePrefs({ detailsPaneOpen: false })}
                    />
                ) : null}
            </div>

            {dialog?.kind === 'tag' ? (
                <TagDialog
                    documents={dialog.documents}
                    tags={tags}
                    busy={busy}
                    onClose={() => setDialog(null)}
                    onApply={async (added, removed) => {
                        const ids = dialog.documents.map(documentId).filter(Boolean);
                        setDialog(null);
                        if (added.length > 0) {
                            await runBulkTag(ids, 'add_tags', added);
                        }
                        if (removed.length > 0) {
                            await runBulkTag(ids, 'remove_tags', removed);
                        }
                    }}
                    onCreateTag={async (name) => {
                        try {
                            await createPersonalDocumentTag(name);
                            await loadSidebar();
                        } catch (createError) {
                            toast.error(errorMessage(createError, 'Could not create the tag.'));
                        }
                    }}
                />
            ) : null}

            {dialog?.kind === 'metadata' ? (
                <MetadataDialog
                    document={dialog.document}
                    classifications={classifications}
                    classificationEnabled={availability.classification}
                    busy={busy}
                    onClose={() => setDialog(null)}
                    onSave={(draft) => void onSaveMetadata(dialog.document, draft)}
                />
            ) : null}

            {dialog?.kind === 'share' ? (
                <ShareDialog
                    document={dialog.document}
                    onClose={() => setDialog(null)}
                    onChanged={() => void loadDocuments()}
                />
            ) : null}

            {dialog?.kind === 'delete' ? (
                <DeleteDialog
                    documents={dialog.documents}
                    blocked={dialog.blocked}
                    busy={busy}
                    onClose={() => setDialog(null)}
                    onConfirm={(options) => void onConfirmDelete(dialog.documents, options)}
                />
            ) : null}
        </div>
    );
}
