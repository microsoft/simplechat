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
import { useNavigate } from 'react-router-dom';
import { FileText, Upload } from 'lucide-react';
import {
    buildContextHandoffParams,
    type ContextHandoffState,
} from '../../lib/chatContextHandoff';
import { groupScope, PERSONAL_SCOPE } from '../../lib/chatContext';
import { isScreeningAvailable, isScreeningBusy } from '../../lib/contentScreening';
import {
    documentExplorerScopeKey, documentSelectionReason, PERSONAL_DOCUMENT_READER,
    supportedDocumentQuery, type DocumentReadAdapter,
} from '../../lib/documentReadAdapter';
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
    batched,
    clearAllFilters,
    clearFilterChip,
    describeActiveFilters,
    documentId,
    documentStatus,
    moveSelection,
    normalizeSortField,
    normalizePageSize,
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
    reprocessPersonalDocumentExtraction,
    updatePersonalDocumentMetadata,
    uploadPersonalDocuments,
    type BulkDeleteError,
} from '../../lib/endpoints';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { toast } from '../../stores/toastStore';
import { EmptyState, GlassButton, Skeleton } from '../ui/primitives';
import { Modal } from '../ui/Modal';
import { errorMessage } from '../workspace/useSectionResource';
import { ExplorerRail } from './ExplorerRail';
import {
    ExplorerCommandBar,
    ExplorerProgress,
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

/**
 * How many documents each bulk request covers.
 *
 * Bulk tagging is not cheap server-side: every document costs a cross-partition query, a
 * write, and an update to each of its search-index chunks. Sending one request for a large
 * selection produced a single request that ran for minutes behind an indeterminate spinner.
 * Batching turns that into steady, reportable progress at negligible extra cost.
 */
const BULK_BATCH_SIZE = 5;

/** A bulk operation in flight, and how far through it is. */
interface ExplorerTask {
    label: string;
    completed: number;
    total: number;
}

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

interface DocumentExplorerProps {
    reader?: DocumentReadAdapter;
    canChat?: boolean;
    interactionDisabled?: boolean;
    onOpenClassic?: () => void;
}

export function DocumentExplorer({
    reader = PERSONAL_DOCUMENT_READER, ...props
}: DocumentExplorerProps) {
    const viewerId = useBootstrapStore((state) => state.data?.user.id);
    if (!viewerId) return null;
    return <ScopedDocumentExplorer key={documentExplorerScopeKey(viewerId, reader.scope)} reader={reader} {...props} />;
}

function ScopedDocumentExplorer({
    reader, canChat = true, interactionDisabled = false, onOpenClassic,
}: DocumentExplorerProps & { reader: DocumentReadAdapter }) {
    const navigate = useNavigate();
    const features = useBootstrapStore((state) => state.data?.features);
    const settings = useBootstrapStore((state) => state.data?.settings);
    const userSettings = useUserSettingsStore((state) => state.settings);
    const saveUserSettings = useUserSettingsStore((state) => state.update);
    const readOnly = reader.scope.kind === 'group';

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
        () => readOnly ? [] : parseSavedViews(userSettings.v2DocumentSavedViews),
        [readOnly, userSettings.v2DocumentSavedViews],
    );

    const [query, setQuery] = useState<DocumentQuery>(() => supportedDocumentQuery({
        ...DEFAULT_DOCUMENT_QUERY,
        pageSize: normalizePageSize(prefs.pageSize),
        sortBy: normalizeSortField(prefs.sortBy),
        sortOrder: prefs.sortOrder === 'asc' ? 'asc' : 'desc',
    }, reader));
    const [searchDraft, setSearchDraft] = useState('');

    const [documents, setDocuments] = useState<WorkspaceDocument[]>([]);
    const [totalCount, setTotalCount] = useState(0);
    const [downloadsEnabled, setDownloadsEnabled] = useState(false);
    const [tags, setTags] = useState<WorkspaceTag[]>([]);
    const [facets, setFacets] = useState<Parameters<typeof ExplorerRail>[0]['facets']>(null);

    const [selection, setSelection] = useState<SelectionState>(EMPTY_SELECTION);
    const [inspectedId, setInspectedId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [task, setTask] = useState<ExplorerTask | null>(null);
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [dialog, setDialog] = useState<ActiveDialog>(null);
    const [sidebarError, setSidebarError] = useState<string | null>(null);
    const [pollError, setPollError] = useState<string | null>(null);
    const [detailError, setDetailError] = useState<string | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailRefresh, setDetailRefresh] = useState(0);
    const [chatPending, setChatPending] = useState(false);
    const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 1279px)').matches);
    const [filtersOpen, setFiltersOpen] = useState(false);
    const [detailsOpen, setDetailsOpen] = useState(false);

    // Dialogs disable their controls while any bulk work is running.
    const busy = task !== null;

    const fileInputRef = useRef<HTMLInputElement>(null);
    const containerRef = useRef<HTMLFieldSetElement>(null);
    const mounted = useRef(true);
    const listRequest = useRef<AbortController | null>(null);
    const sidebarRequest = useRef<AbortController | null>(null);
    const detailRequest = useRef<AbortController | null>(null);
    const chatRequest = useRef<AbortController | null>(null);
    const documentReads = useRef(new Map<string, number>());
    const listRevision = useRef(0);
    const access = useRef({ canChat, interactionDisabled });
    access.current = { canChat, interactionDisabled };

    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
            for (const request of [listRequest, sidebarRequest, detailRequest, chatRequest]) request.current?.abort();
        };
    }, []);

    useEffect(() => {
        const media = window.matchMedia('(max-width: 1279px)');
        const update = () => setCompact(media.matches);
        media.addEventListener('change', update);
        return () => media.removeEventListener('change', update);
    }, []);

    useEffect(() => {
        setQuery((current) => {
            const next = supportedDocumentQuery(current, reader);
            return next.place === current.place && next.sortBy === current.sortBy ? current : { ...next, page: 1 };
        });
    }, [reader]);

    const selectionReason = useCallback((document: WorkspaceDocument) =>
        interactionDisabled ? 'Refresh workspace access before selecting documents.'
            : documentSelectionReason(document, reader.scope, canChat),
    [reader, canChat, interactionDisabled]);

    const requirePersonalWrite = useCallback(() => {
        if (readOnly || interactionDisabled) {
            toast.error(readOnly ? 'Document management is available in the classic group workspace.'
                : 'Refresh workspace access before changing documents.');
            return false;
        }
        return true;
    }, [readOnly, interactionDisabled]);

    const readCurrentDocument = useCallback(async (id: string, signal: AbortSignal) => {
        const revision = (documentReads.current.get(id) ?? 0) + 1;
        documentReads.current.set(id, revision);
        try {
            const document = await reader.detail(id, signal);
            return !signal.aborted && documentReads.current.get(id) === revision ? document : null;
        } catch (cause) {
            if (signal.aborted || documentReads.current.get(id) !== revision) return null;
            throw cause;
        }
    }, [reader]);

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
            manage: !readOnly,
            chat: canChat && !interactionDisabled && !loading && !error && !detailError && !chatPending,
            downloads: !readOnly && downloadsEnabled,
            extractMetadata: !readOnly && Boolean(features?.enable_extract_meta_data),
            sharing: !readOnly && Boolean(features?.enable_file_sharing),
            classification: Boolean(features?.enable_document_classification),
            enhancedExtraction: Boolean(features?.enable_enhanced_extraction),
        }),
        [readOnly, canChat, interactionDisabled, loading, error, detailError, chatPending, downloadsEnabled, features],
    );

    const orderedIds = useMemo(
        () => documents.filter((document) => !selectionReason(document)).map(documentId),
        [documents, selectionReason],
    );
    const selectedDocuments = useMemo(
        () => documents.filter((item) => !selectionReason(item) && selection.ids.includes(documentId(item))),
        [documents, selection.ids, selectionReason],
    );
    const detailDocuments = inspectedId
        ? documents.filter((item) => documentId(item) === inspectedId)
        : selectedDocuments;

    useEffect(() => {
        setSelection((current) => pruneSelection(current, orderedIds));
    }, [orderedIds]);

    /* ---------------------------------------------------------------------- */
    /* Loading                                                                 */
    /* ---------------------------------------------------------------------- */

    const loadDocuments = useCallback(
        async () => {
            listRequest.current?.abort();
            listRevision.current += 1;
            if (!mounted.current || interactionDisabled) return;
            const controller = new AbortController();
            listRequest.current = controller;
            setLoading(true);
            setError(null);
            try {
                const response = await reader.list(supportedDocumentQuery(query, reader), controller.signal);
                if (controller.signal.aborted || !mounted.current) return;
                const items = response.documents ?? response.items ?? [];
                const total = Number(response.total_count ?? items.length);
                const lastPage = Math.max(1, Math.ceil(total / query.pageSize));
                if (query.page > lastPage) {
                    setQuery((current) => ({ ...current, page: lastPage }));
                    return;
                }
                setDocuments(items);
                setTotalCount(total);
                setDownloadsEnabled(!readOnly && Boolean(response.file_downloads_enabled));
                setSelection((current) => pruneSelection(current, items.filter((item) => !selectionReason(item)).map(documentId)));
                setInspectedId((current) => items.some((item) => documentId(item) === current) ? current : null);
            } catch (loadError) {
                if (controller.signal.aborted || !mounted.current) return;
                setDocuments([]);
                setTotalCount(0);
                setSelection(EMPTY_SELECTION);
                setInspectedId(null);
                setError(errorMessage(loadError, 'Failed to load documents.'));
            } finally {
                if (!controller.signal.aborted && mounted.current) setLoading(false);
            }
        },
        [query, reader, readOnly, interactionDisabled, selectionReason],
    );

    const loadSidebar = useCallback(async () => {
        sidebarRequest.current?.abort();
        if (!mounted.current || interactionDisabled) return;
        const controller = new AbortController();
        sidebarRequest.current = controller;
        setSidebarError(null);
        const [tagsResult, facetsResult] = await Promise.allSettled([
            reader.tags(controller.signal),
            reader.queries.facets ? reader.facets(controller.signal) : Promise.resolve(null),
        ]);
        if (controller.signal.aborted || !mounted.current) return;
        setTags(tagsResult.status === 'fulfilled' ? tagsResult.value.tags ?? [] : []);
        setFacets(facetsResult.status === 'fulfilled' ? facetsResult.value : null);
        const errors = [tagsResult, facetsResult].flatMap((result) =>
            result.status === 'rejected' ? [errorMessage(result.reason, 'Could not load document filters.')] : []);
        setSidebarError(errors.length ? errors.join(' ') : null);
    }, [reader, interactionDisabled]);

    useEffect(() => {
        void loadDocuments();
        return () => listRequest.current?.abort();
    }, [loadDocuments]);

    useEffect(() => {
        void loadSidebar();
        return () => sidebarRequest.current?.abort();
    }, [loadSidebar]);

    /** Reload the list and the rail together, after anything that changes both. */
    const refreshAll = useCallback(async () => {
        setPollError(null);
        await Promise.all([loadDocuments(), loadSidebar()]);
    }, [loadDocuments, loadSidebar]);

    const detailId = detailDocuments.length === 1 ? documentId(detailDocuments[0]) : null;
    useEffect(() => {
        detailRequest.current?.abort();
        setDetailError(null);
        setDetailLoading(false);
        if (!detailId || interactionDisabled || (!readOnly && detailRefresh === 0)) return;
        const controller = new AbortController();
        detailRequest.current = controller;
        const revision = listRevision.current;
        setDetailLoading(true);
        void readCurrentDocument(detailId, controller.signal).then((document) => {
            if (!document || controller.signal.aborted || !mounted.current || revision !== listRevision.current) return;
            // Replace, never merge: a newly held or unapproved projection omits restricted metadata.
            setDocuments((current) => current.map((item) => documentId(item) === detailId ? document : item));
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted && mounted.current) setDetailError(errorMessage(cause, 'Could not refresh document details.'));
        }).finally(() => {
            if (!controller.signal.aborted && mounted.current) setDetailLoading(false);
        });
        return () => controller.abort();
    }, [detailId, readCurrentDocument, interactionDisabled, detailRefresh, readOnly, query]);

    /* ---------------------------------------------------------------------- */
    /* Progress polling                                                        */
    /* ---------------------------------------------------------------------- */

    const processingIds = useMemo(
        () =>
            documents
                .filter((item) => documentStatus(item).state === 'processing' || isScreeningBusy(item))
                .map(documentId)
                .filter(Boolean),
        [documents],
    );

    useEffect(() => {
        if (processingIds.length === 0 || interactionDisabled) {
            return;
        }

        const controller = new AbortController();
        let polling = false;
        const timer = window.setInterval(async () => {
            if (polling) return;
            polling = true;
            const revision = listRevision.current;
            // Refreshed one document at a time rather than by re-listing: a poll that
            // re-fetched the page would fight the user's scroll position and selection every
            // few seconds for as long as anything was indexing.
            const updates = await Promise.allSettled(
                processingIds.map((id) => readCurrentDocument(id, controller.signal)),
            );
            polling = false;
            if (controller.signal.aborted || !mounted.current || revision !== listRevision.current) return;
            const failure = updates.find((update) => update.status === 'rejected');
            setPollError(failure?.status === 'rejected' ? errorMessage(failure.reason, 'Could not refresh document progress.') : null);

            const byId = new Map<string, WorkspaceDocument>();
            for (const update of updates) {
                if (update.status === 'fulfilled' && update.value) {
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
                (item) => documentStatus(item).state !== 'processing' && !isScreeningBusy(item),
            );
            if (finished) {
                void loadSidebar();
            }
        }, PROGRESS_POLL_MS);

        return () => {
            controller.abort();
            window.clearInterval(timer);
        };
    }, [processingIds, loadSidebar, readCurrentDocument, interactionDisabled, query]);

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
        if (interactionDisabled || chatPending) return;
        setQuery((current) => supportedDocumentQuery(applyQueryChange(current, change), reader));
    }, [reader, interactionDisabled, chatPending]);

    // Debounced so typing does not issue a request per keystroke.
    useEffect(() => {
        if (interactionDisabled || chatPending) return;
        const timer = window.setTimeout(() => {
            setQuery((current) =>
                current.search === searchDraft
                    ? current
                    : applyQueryChange(current, { search: searchDraft }),
            );
        }, 300);
        return () => window.clearTimeout(timer);
    }, [searchDraft, interactionDisabled, chatPending]);

    const onSort = useCallback(
        (field: DocumentSortField) => {
            if (interactionDisabled || chatPending || !reader.queries.sortFields.includes(field)) return;
            setQuery((current) => {
                const next = toggleSort(current, field);
                updatePrefs({ sortBy: next.sortBy, sortOrder: next.sortOrder });
                return { ...next, page: 1 };
            });
        },
        [updatePrefs, reader, interactionDisabled, chatPending],
    );

    /* ---------------------------------------------------------------------- */
    /* Selection                                                               */
    /* ---------------------------------------------------------------------- */

    const onSelect = useCallback(
        (id: string, intent: SelectionIntent) => {
            if (interactionDisabled || chatPending || loading || error || !orderedIds.includes(id)) {
                return;
            }
            setInspectedId(null);
            setSelection((current) => applySelection(current, id, intent, orderedIds));
        },
        [orderedIds, interactionDisabled, chatPending, loading, error],
    );

    const onOpen = useCallback(
        (document: WorkspaceDocument) => {
            if (interactionDisabled || chatPending || loading || error) return;
            setInspectedId(documentId(document));
            if (selectionReason(document)) {
                setSelection(EMPTY_SELECTION);
            }
            if (compact) setDetailsOpen(true);
            updatePrefs({ detailsPaneOpen: true });
        },
        [updatePrefs, compact, selectionReason, interactionDisabled, chatPending, loading, error],
    );

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            const target = event.target as HTMLElement | null;
            const typing =
                target &&
                (target.tagName === 'INPUT' ||
                    target.tagName === 'TEXTAREA' ||
                    target.tagName === 'SELECT' ||
                    target.isContentEditable);
            if (typing || dialog || interactionDisabled || chatPending || loading || error || filtersOpen || detailsOpen) {
                return;
            }
            if (!containerRef.current?.contains(document.activeElement) &&
                document.activeElement !== document.body) {
                return;
            }

            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
                event.preventDefault();
                setInspectedId(null);
                setSelection({ ids: [...orderedIds], anchorId: orderedIds[0] ?? null });
                return;
            }
            if (event.key === 'Escape') {
                setSelection(EMPTY_SELECTION);
                setInspectedId(null);
                return;
            }
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                setInspectedId(null);
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
    }, [orderedIds, dialog, interactionDisabled, chatPending, loading, error, filtersOpen, detailsOpen]);

    const onDragStart = useCallback(
        (event: React.DragEvent, id: string) => {
            if (readOnly || interactionDisabled || !orderedIds.includes(id)) {
                event.preventDefault();
                return;
            }
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
        [selection.ids, orderedIds, readOnly, interactionDisabled],
    );

    /* ---------------------------------------------------------------------- */
    /* Actions                                                                 */
    /* ---------------------------------------------------------------------- */

    const openDialog = useCallback((value: NonNullable<ActiveDialog>) => {
        if (requirePersonalWrite()) setDialog(value);
    }, [requirePersonalWrite]);

    /**
     * Run one request per batch of documents, reporting progress as each lands.
     *
     * Always clears the task, including when a batch throws, so a failure can never leave the
     * progress bar up forever -- which is exactly what an indeterminate spinner around a
     * single long request looked like.
     */
    const runBatched = useCallback(
        async (
            label: string,
            ids: string[],
            perBatch: (batch: string[]) => Promise<void>,
        ): Promise<{ completed: number; failed: number }> => {
            const batches = batched(ids, BULK_BATCH_SIZE);
            let completed = 0;
            let failed = 0;

            setTask({ label, completed: 0, total: ids.length });
            try {
                for (const batch of batches) {
                    try {
                        await perBatch(batch);
                        completed += batch.length;
                    } catch (batchError) {
                        failed += batch.length;
                        toast.error(errorMessage(batchError, `${label} failed.`));
                    }
                    setTask({ label, completed: completed + failed, total: ids.length });
                }
            } finally {
                setTask(null);
            }

            return { completed, failed };
        },
        [],
    );

    const runBulkTag = useCallback(
        async (
            ids: string[],
            action: 'add_tags' | 'remove_tags',
            tagNames: string[],
            options: { undoable?: boolean } = {},
        ) => {
            if (!requirePersonalWrite()) return;
            if (ids.length === 0 || tagNames.length === 0) {
                return;
            }

            const verb = action === 'add_tags' ? 'Tagging' : 'Untagging';
            const { completed } = await runBatched(
                `${verb} ${ids.length} ${ids.length === 1 ? 'document' : 'documents'}`,
                ids,
                (batch) => bulkTagPersonalDocuments(batch, action, tagNames).then(() => undefined),
            );

            await refreshAll();

            if (completed === 0) {
                return;
            }

            const done = action === 'add_tags' ? 'Tagged' : 'Untagged';
            const message = `${done} ${completed} ${completed === 1 ? 'document' : 'documents'} with ${tagNames.join(', ')}`;
            if (options.undoable) {
                toast.success(message, {
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
        },
        [refreshAll, runBatched, requirePersonalWrite],
    );

    const onDropOnTag = useCallback(
        (tagName: string, ids: string[]) => {
            void runBulkTag(ids, 'add_tags', [tagName], { undoable: true });
        },
        [runBulkTag],
    );

    const onUploadFiles = useCallback(
        async (files: File[]) => {
            if (!requirePersonalWrite()) return;
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
        [refreshAll, settings, requirePersonalWrite],
    );

    const onDownload = useCallback(async (targets: WorkspaceDocument[]) => {
        if (!requirePersonalWrite()) return;
        if (targets.some((target) => !isScreeningAvailable(target))) {
            toast.error('Held content cannot be downloaded. Open Content review.');
            return;
        }
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
    }, [requirePersonalWrite]);

    /**
     * Hand the selection to the composer.
     *
     * This used to be `window.location.href = '/chats?…'`, which is a full page load into the
     * *classic* interface: the one action most likely to follow choosing a document quietly
     * moved the user out of V2. Navigating within the router keeps them here, and the document
     * records ride along in router state so the composer does not have to fetch back what this
     * page already has in hand.
     */
    const onChat = useCallback(
        async (targets: WorkspaceDocument[]) => {
            if (!availability.chat) {
                toast.error('Chat is not currently available for this selection. Refresh workspace access and try again.');
                return;
            }
            const reason = targets.map(selectionReason).find(Boolean);
            if (reason) {
                toast.error(reason);
                return;
            }
            let documents = targets.filter((target) => documentId(target));
            if (documents.length === 0) {
                return;
            }
            chatRequest.current?.abort();
            const controller = new AbortController();
            chatRequest.current = controller;
            setChatPending(true);
            try {
                if (readOnly) documents = await Promise.all(documents.map((document) => reader.detail(documentId(document), controller.signal)));
                if (controller.signal.aborted || !mounted.current || access.current.interactionDisabled || !access.current.canChat) return;
                const blocked = documents.map((document) => documentSelectionReason(document, reader.scope)).find(Boolean);
                if (blocked) {
                    setDocuments((current) => current.map((item) => documents.find((document) => documentId(document) === documentId(item)) ?? item));
                    toast.error(blocked);
                    return;
                }
                const scope = reader.scope.kind === 'group' ? groupScope(reader.scope) : PERSONAL_SCOPE;
                const tags = readOnly ? query.tags : [];
                const handoff = buildContextHandoffParams({
                    documentIds: documents.map(documentId),
                    docScope: reader.scope.kind,
                    groupId: reader.scope.kind === 'group' ? reader.scope.id : undefined,
                    tags,
                });
                const state: ContextHandoffState = {
                    contextDocuments: documents.map((document) => ({ document, scope })),
                    contextTags: tags.map((name) => ({ name, scope })),
                };
                navigate(`/chat?${handoff}`, { state });
            } catch (cause) {
                if (!controller.signal.aborted && mounted.current) toast.error(errorMessage(cause, 'Could not confirm the selected documents for chat.'));
            } finally {
                if (!controller.signal.aborted && mounted.current) setChatPending(false);
            }
        },
        [navigate, reader, readOnly, query.tags, availability.chat, selectionReason],
    );

    const onExtractMetadata = useCallback(
        async (targets: WorkspaceDocument[]) => {
            if (!requirePersonalWrite()) return;
            if (targets.some((target) => !isScreeningAvailable(target))) {
                toast.error('Held content cannot be analyzed. Open Content review.');
                return;
            }
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
        [refreshAll, requirePersonalWrite],
    );

    const onReextract = useCallback(
        async (targets: WorkspaceDocument[], mode: 'read' | 'layout') => {
            if (!requirePersonalWrite()) return;
            if (targets.some((target) => !isScreeningAvailable(target))) {
                toast.error('Use Content review to retry screening of held content.');
                return;
            }
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
        [refreshAll, requirePersonalWrite],
    );

    const onSaveMetadata = useCallback(
        async (target: WorkspaceDocument, draft: MetadataDraft) => {
            if (!requirePersonalWrite()) return;
            setTask({ label: 'Saving metadata', completed: 0, total: 1 });
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
                setTask(null);
            }
        },
        [refreshAll, requirePersonalWrite],
    );

    const onConfirmDelete = useCallback(
        async (
            targets: WorkspaceDocument[],
            options: { force: boolean; deleteAllVersions: boolean },
        ) => {
            if (!requirePersonalWrite()) return;
            const ids = targets.map(documentId).filter(Boolean);
            if (ids.length === 0) {
                return;
            }

            // Batched like the tag path: deleting a document removes its search-index chunks
            // as well as its record, so a large selection is slow enough to need reporting.
            const blocked: BulkDeleteError[] = [];
            const failed: BulkDeleteError[] = [];
            let deletedCount = 0;

            setTask({
                label: `Deleting ${ids.length} ${ids.length === 1 ? 'document' : 'documents'}`,
                completed: 0,
                total: ids.length,
            });
            try {
                let processed = 0;
                for (const batch of batched(ids, BULK_BATCH_SIZE)) {
                    try {
                        const response = await bulkDeletePersonalDocuments(batch, {
                            deleteMode: options.deleteAllVersions
                                ? 'all_versions'
                                : 'current_only',
                            conversationLinkedDeleteConfirmed: options.force,
                            fileSyncDeleteAction: options.force ? 'keep_source' : null,
                        });
                        deletedCount += response.deleted_count ?? 0;
                        for (const entry of response.errors ?? []) {
                            (entry.needs_confirmation ? blocked : failed).push(entry);
                        }
                    } catch (batchError) {
                        toast.error(
                            errorMessage(batchError, 'Could not delete some documents.'),
                        );
                    }
                    processed += batch.length;
                    setTask({
                        label: `Deleting ${ids.length} ${ids.length === 1 ? 'document' : 'documents'}`,
                        completed: processed,
                        total: ids.length,
                    });
                }
            } finally {
                setTask(null);
            }

            if (blocked.length > 0) {
                // Kept open, now listing exactly what was refused and why, so the user can
                // decide about those documents rather than about the batch.
                setDialog({ kind: 'delete', documents: targets, blocked });
            } else {
                setDialog(null);
            }

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
        },
        [refreshAll, requirePersonalWrite],
    );

    const onSaveView = useCallback(() => {
        if (!requirePersonalWrite()) return;
        const name = window.prompt('Name this view');
        if (!name?.trim()) {
            return;
        }
        const view = createSavedView(name, query);
        saveUserSettings({ v2DocumentSavedViews: upsertSavedView(savedViews, view) });
        toast.success(`Saved "${view.name}" to the rail.`);
    }, [query, savedViews, saveUserSettings, requirePersonalWrite]);

    const onDeleteSavedView = useCallback(
        (view: DocumentSavedView) => {
            if (!requirePersonalWrite()) return;
            if (!window.confirm(`Remove the saved view "${view.name}"?`)) {
                return;
            }
            saveUserSettings({
                v2DocumentSavedViews: removeSavedView(savedViews, view.id),
            });
        },
        [savedViews, saveUserSettings, requirePersonalWrite],
    );

    /* ---------------------------------------------------------------------- */
    /* Render                                                                  */
    /* ---------------------------------------------------------------------- */

    const chips = describeActiveFilters(query).map((chip) =>
        readOnly && chip.kind === 'place' && chip.value === 'shared'
            ? { ...chip, label: 'Shared with this group' } : chip);

    const content = () => {
        if (error) return (
            <div role="alert">
                <EmptyState icon={<FileText size={28} />} title="Documents could not be loaded"
                    description={error} action={<GlassButton size="sm" onClick={() => void refreshAll()}>Retry documents</GlassButton>} />
            </div>
        );
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
                            : readOnly ? 'This group has no visible documents. Use the classic workspace to manage files.'
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
                        ) : readOnly ? (
                            onOpenClassic ? <GlassButton size="sm" onClick={onOpenClassic}>Manage files in classic</GlassButton> : undefined
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
                onOpen={onOpen}
                onDragStart={readOnly ? undefined : onDragStart}
                selectionReason={selectionReason}
                scope={reader.scope}
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
                onToggleSelectAll={() => {
                    if (interactionDisabled || chatPending || loading || error) return;
                    setInspectedId(null);
                    setSelection((current) => toggleSelectAll(current, orderedIds));
                }}
                onSort={onSort}
                onOpen={onOpen}
                onDragStart={readOnly ? undefined : onDragStart}
                selectionReason={selectionReason}
                scope={reader.scope}
                sortFields={reader.queries.sortFields}
            />
        );
    };

    const rail = <ExplorerRail
        query={query}
        facets={facets}
        tags={tags}
        savedViews={savedViews}
        classifications={availability.classification ? classifications : []}
        onQueryChange={changeQuery}
        onApplySavedView={(view) => {
            if (readOnly || interactionDisabled) return;
            setSearchDraft(view.query.search);
            setQuery((current) => applySavedView(current, view));
        }}
        onDeleteSavedView={onDeleteSavedView}
        onDropOnTag={readOnly ? undefined : onDropOnTag}
        placesEnabled={reader.queries.places}
        sharedLabel={readOnly ? 'Shared with this group' : 'Shared with me'}
        compact={compact}
    />;
    const detailsPane = <DocumentDetailsPane
        documents={detailDocuments}
        availability={availability}
        reader={reader}
        selectionReason={selectionReason}
        loading={detailLoading}
        error={detailError}
        interactionDisabled={interactionDisabled || chatPending}
        compact={compact}
        onRefresh={() => setDetailRefresh((value) => value + 1)}
        actions={{
            onChat: (targets) => void onChat(targets),
            onDownload: (targets) => void onDownload(targets),
            onEditMetadata: (target) => openDialog({ kind: 'metadata', document: target }),
            onExtractMetadata: (targets) => void onExtractMetadata(targets),
            onReextract: (targets, mode) => void onReextract(targets, mode),
            onShare: (target) => openDialog({ kind: 'share', document: target }),
            onManageTags: (targets) => openDialog({ kind: 'tag', documents: targets }),
            onDelete: (targets) => openDialog({ kind: 'delete', documents: targets, blocked: [] }),
            onSelectTag: (tag) => changeQuery({ tags: [tag] }),
            onRemoveTag: (targets, tag) => void runBulkTag(targets.map(documentId).filter(Boolean), 'remove_tags', [tag]),
        }}
        tagColors={tagColors}
        classificationColors={classificationColors}
        onClose={() => {
            setDetailsOpen(false);
            if (!compact) updatePrefs({ detailsPaneOpen: false });
        }}
    />;

    return (
        <fieldset ref={containerRef} disabled={interactionDisabled || chatPending} aria-label="Documents explorer"
            aria-busy={loading}
            className="flex h-full min-h-0 min-w-0 flex-col gap-2">
            {!readOnly ? <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(event) => {
                    const files = Array.from(event.target.files ?? []);
                    event.target.value = '';
                    void onUploadFiles(files);
                }}
            /> : null}

            <ExplorerCommandBar
                searchDraft={searchDraft}
                prefs={compact ? { ...prefs, detailsPaneOpen: detailsOpen } : prefs}
                selectionCount={selectedDocuments.length}
                uploading={uploading}
                availability={availability}
                canSaveView={!readOnly && isSaveableQuery(query)}
                query={query}
                sortFields={reader.queries.sortFields}
                onSort={onSort}
                onShowFilters={compact ? () => setFiltersOpen(true) : undefined}
                onSearchChange={setSearchDraft}
                onSearchSubmit={(value) => {
                    // Enter searches now rather than waiting out the debounce.
                    setSearchDraft(value);
                    changeQuery({ search: value });
                }}
                onUpload={() => fileInputRef.current?.click()}
                onDownload={() => void onDownload(selectedDocuments)}
                onTag={() => openDialog({ kind: 'tag', documents: selectedDocuments })}
                onChat={() => void onChat(selectedDocuments)}
                onExtractMetadata={() => void onExtractMetadata(selectedDocuments)}
                onDelete={() =>
                    openDialog({ kind: 'delete', documents: selectedDocuments, blocked: [] })
                }
                onSaveView={onSaveView}
                onPrefsChange={(change) => {
                    if (compact && change.detailsPaneOpen !== undefined) {
                        setDetailsOpen(change.detailsPaneOpen);
                        return;
                    }
                    updatePrefs(change);
                    if (change.pageSize) {
                        changeQuery({ pageSize: change.pageSize });
                    }
                }}
            />

            {chatPending ? <p role="status" className="text-xs text-text-3">Confirming selected documents for chat...</p> : null}
            {readOnly && !canChat ? <p role="status" className="text-xs text-text-3">Chat is not available for this group. You can still inspect its documents.</p> : null}
            {sidebarError || pollError ? (
                <div className="space-y-1 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
                    <p>{sidebarError || pollError}</p>
                    <GlassButton size="sm" onClick={() => void refreshAll()}>Retry document updates</GlassButton>
                </div>
            ) : null}

            <div className="flex min-h-0 flex-1 gap-3 overflow-hidden">
                {!compact ? rail : null}

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
                        {task ? <ExplorerProgress task={task} /> : null}
                        {content()}
                    </div>

                    {!error ? <ExplorerStatusBar
                        page={query.page}
                        pageSize={query.pageSize}
                        totalCount={totalCount}
                        selectionCount={selectedDocuments.length}
                        onPageChange={(page) => changeQuery({ page })}
                        onPageSizeChange={(pageSize) => {
                            updatePrefs({ pageSize });
                            changeQuery({ pageSize });
                        }}
                    /> : null}
                </div>

                {!compact && prefs.detailsPaneOpen ? detailsPane : null}
            </div>

            {compact && filtersOpen ? <Modal title="Document filters" onClose={() => setFiltersOpen(false)}
                footer={<GlassButton size="sm" onClick={() => setFiltersOpen(false)}>Show documents</GlassButton>}>
                <fieldset disabled={interactionDisabled || chatPending}>{rail}</fieldset>
            </Modal> : null}
            {compact && detailsOpen ? <Modal title="Document details" onClose={() => setDetailsOpen(false)} tall bodyClassName="min-h-0 overflow-hidden p-2">
                {detailsPane}
            </Modal> : null}

            {!readOnly && dialog?.kind === 'tag' ? (
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
                        if (!requirePersonalWrite()) return;
                        try {
                            await createPersonalDocumentTag(name);
                            await loadSidebar();
                        } catch (createError) {
                            toast.error(errorMessage(createError, 'Could not create the tag.'));
                        }
                    }}
                />
            ) : null}

            {!readOnly && dialog?.kind === 'metadata' ? (
                <MetadataDialog
                    document={dialog.document}
                    classifications={classifications}
                    classificationEnabled={availability.classification}
                    busy={busy}
                    onClose={() => setDialog(null)}
                    onSave={(draft) => void onSaveMetadata(dialog.document, draft)}
                />
            ) : null}

            {!readOnly && dialog?.kind === 'share' ? (
                <ShareDialog
                    document={dialog.document}
                    onClose={() => setDialog(null)}
                    onChanged={() => void loadDocuments()}
                />
            ) : null}

            {!readOnly && dialog?.kind === 'delete' ? (
                <DeleteDialog
                    documents={dialog.documents}
                    blocked={dialog.blocked}
                    busy={busy}
                    onClose={() => setDialog(null)}
                    onConfirm={(options) => void onConfirmDelete(dialog.documents, options)}
                />
            ) : null}
        </fieldset>
    );
}
