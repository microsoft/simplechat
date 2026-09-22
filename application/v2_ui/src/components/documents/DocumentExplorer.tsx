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
import { isScreeningBusy } from '../../lib/contentScreening';
import {
    documentExplorerScopeKey, documentSelectionReason, PERSONAL_DOCUMENT_READER,
    supportedDocumentQuery, type DocumentReadAdapter,
} from '../../lib/documentReadAdapter';
import {
    changedDocumentMetadata, createGroupDocumentOperations, PERSONAL_DOCUMENT_OPERATIONS,
    type DocumentBatchOutcome, type DocumentDeleteOptions, type DocumentOperation,
    type DocumentOperationAdapter, type DocumentOperationError, type TagOperationError,
} from '../../lib/documentOperations';
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
    OperationFeedback,
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
    | { kind: 'delete'; documents: WorkspaceDocument[]; blocked: DocumentOperationError[] }
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
    operations?: DocumentOperationAdapter;
    canChat?: boolean;
    interactionDisabled?: boolean;
    onOpenClassic?: () => void;
    onDirtyChange?: (dirty: boolean) => void;
    onBusyChange?: (busy: boolean) => void;
}

export function DocumentExplorer({
    reader = PERSONAL_DOCUMENT_READER, operations, ...props
}: DocumentExplorerProps) {
    const viewerId = useBootstrapStore((state) => state.data?.user.id);
    const resolvedOperations = useMemo(() => operations ?? (reader.scope.kind === 'group'
        ? createGroupDocumentOperations(reader.scope, undefined) : PERSONAL_DOCUMENT_OPERATIONS), [reader, operations]);
    if (!viewerId) return null;
    const scopeKey = documentExplorerScopeKey(viewerId, reader.scope);
    if (documentExplorerScopeKey(viewerId, resolvedOperations.scope) !== scopeKey) return (
        <div role="alert"><EmptyState title="Document management scope does not match"
            description="Refresh this workspace before managing documents." /></div>
    );
    return <ScopedDocumentExplorer key={scopeKey} scopeKey={scopeKey} reader={reader} operations={resolvedOperations} {...props} />;
}

function ScopedDocumentExplorer({
    reader, operations, scopeKey, canChat = true, interactionDisabled = false, onOpenClassic,
    onDirtyChange, onBusyChange,
}: DocumentExplorerProps & { reader: DocumentReadAdapter; operations: DocumentOperationAdapter; scopeKey: string }) {
    const navigate = useNavigate();
    const features = useBootstrapStore((state) => state.data?.features);
    const settings = useBootstrapStore((state) => state.data?.settings);
    const userSettings = useUserSettingsStore((state) => state.settings);
    const saveUserSettings = useUserSettingsStore((state) => state.update);
    const isGroup = reader.scope.kind === 'group';
    const scopeLabel = reader.scope.kind === 'group' ? reader.scope.name : 'My workspace';

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
        () => isGroup ? [] : parseSavedViews(userSettings.v2DocumentSavedViews),
        [isGroup, userSettings.v2DocumentSavedViews],
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
    const [dialogError, setDialogError] = useState<string | null>(null);
    const [feedback, setFeedback] = useState<{ title: string; errors: TagOperationError[] } | null>(null);

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
    const failedSelection = useRef(new Set<string>());
    const mutationBusy = useRef(false);
    const listRevision = useRef(0);
    const access = useRef({ canChat, interactionDisabled });
    access.current = { canChat, interactionDisabled };
    const operationContext = useRef({ operations, documents, interactionDisabled, loading, downloadsEnabled, features });
    operationContext.current = { operations, documents, interactionDisabled, loading, downloadsEnabled, features };

    useEffect(() => {
        onDirtyChange?.(dialog !== null);
        return () => onDirtyChange?.(false);
    }, [dialog, onDirtyChange]);

    useEffect(() => () => onBusyChange?.(false), [onBusyChange]);

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

    const chatSelectionReason = useCallback((document: WorkspaceDocument) =>
        interactionDisabled ? 'Refresh workspace access before selecting documents.' : documentSelectionReason(document, reader.scope, canChat),
    [reader, canChat, interactionDisabled]);

    const selectionReason = useCallback((document: WorkspaceDocument) => {
        const chatReason = chatSelectionReason(document);
        if (interactionDisabled || !isGroup || !chatReason) return chatReason;
        return [...operations.supported].some((operation) => !['upload', 'manage_tags'].includes(operation)
            && operations.allows(operation, [document])) ? null : chatReason;
    }, [chatSelectionReason, interactionDisabled, isGroup, operations]);

    const requirePersonalFeature = useCallback(() => {
        if (isGroup || interactionDisabled || mutationBusy.current) {
            toast.error(isGroup ? 'This personal workspace feature is not available for group documents.'
                : 'Refresh workspace access before changing documents.');
            return false;
        }
        return true;
    }, [isGroup, interactionDisabled]);

    const canPerform = useCallback((operation: DocumentOperation, targets: readonly WorkspaceDocument[] = []) => {
        const current = operationContext.current;
        if (current.interactionDisabled || mutationBusy.current
            || (targets.length > 0 && current.loading)) return false;
        if (current.operations.scope.kind === 'personal') {
            if (operation === 'download' && !current.downloadsEnabled) return false;
            if (operation === 'extract_metadata' && !current.features?.enable_extract_meta_data) return false;
        }
        const fresh = targets.map((target) => current.documents.find((document) => documentId(document) === documentId(target)));
        if (fresh.some((document) => !document)) return false;
        return current.operations.allows(operation, fresh.filter((document): document is WorkspaceDocument => Boolean(document)));
    }, []);

    const operationTargets = useCallback((operation: DocumentOperation, targets: WorkspaceDocument[] = []) => {
        if (!mounted.current) return null;
        if (!canPerform(operation, targets)) {
            const current = operationContext.current;
            const message = current.operations.scope.kind === 'group' && current.operations.supported.size === 0
                ? 'Document management is available in the classic group workspace.'
                : 'This operation is not currently permitted for every selected document. Refresh access or adjust the selection.';
            setDialogError(message);
            toast.error(message);
            return null;
        }
        const current = operationContext.current;
        return {
            adapter: current.operations,
            targets: targets.map((target) => current.documents.find((document) => documentId(document) === documentId(target))!),
        };
    }, [canPerform]);

    const beginMutation = useCallback((label: string, total: number) => {
        mutationBusy.current = true;
        onBusyChange?.(true);
        setDialogError(null);
        setFeedback(null);
        setTask({ label, completed: 0, total });
    }, [onBusyChange]);

    const finishMutation = useCallback(() => {
        mutationBusy.current = false;
        if (mounted.current) {
            setTask(null);
            setUploading(false);
            onBusyChange?.(false);
        }
    }, [onBusyChange]);

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
            upload: operations.supported.has('upload'),
            tagDocuments: operations.supported.has('tag_documents'),
            manageTags: operations.supported.has('manage_tags'),
            editMetadata: operations.supported.has('edit_metadata'),
            deleteDocuments: operations.supported.has('delete'),
            reprocess: operations.supported.has('reprocess'),
            allows: canPerform,
            chat: canChat && !interactionDisabled && !busy && !loading && !error && !detailError && !chatPending,
            downloads: isGroup ? operations.supported.has('download') : downloadsEnabled,
            extractMetadata: isGroup ? operations.supported.has('extract_metadata') : Boolean(features?.enable_extract_meta_data),
            sharing: !isGroup && Boolean(features?.enable_file_sharing),
            classification: Boolean(features?.enable_document_classification),
            enhancedExtraction: Boolean(features?.enable_enhanced_extraction),
        }),
        [isGroup, operations, canPerform, canChat, interactionDisabled, busy, loading, error, detailError, chatPending, downloadsEnabled, features],
    );

    const orderedIds = useMemo(
        () => documents.filter((document) => !selectionReason(document)).map(documentId),
        [documents, selectionReason],
    );
    const selectedDocuments = useMemo(
        () => documents.filter((item) => selection.ids.includes(documentId(item))),
        [documents, selection.ids],
    );
    const detailDocuments = inspectedId
        ? documents.filter((item) => documentId(item) === inspectedId)
        : selectedDocuments;

    useEffect(() => {
        const retained = documents.filter((document) => failedSelection.current.has(documentId(document))).map(documentId);
        setSelection((current) => pruneSelection(current, [...orderedIds, ...retained]));
    }, [orderedIds, documents]);

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
                setDownloadsEnabled(!isGroup && Boolean(response.file_downloads_enabled));
                setSelection((current) => pruneSelection(current, items.filter((item) =>
                    !selectionReason(item) || failedSelection.current.has(documentId(item))).map(documentId)));
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
        [query, reader, isGroup, interactionDisabled, selectionReason],
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
        if (!detailId || interactionDisabled || (!isGroup && detailRefresh === 0)) return;
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
    }, [detailId, readCurrentDocument, interactionDisabled, detailRefresh, isGroup, query]);

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
        if (interactionDisabled || chatPending || mutationBusy.current) return;
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
            if (interactionDisabled || chatPending || mutationBusy.current || !reader.queries.sortFields.includes(field)) return;
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
            if (interactionDisabled || chatPending || mutationBusy.current || loading || error || !orderedIds.includes(id)) {
                return;
            }
            setInspectedId(null);
            setSelection((current) => applySelection(current, id, intent, orderedIds));
        },
        [orderedIds, interactionDisabled, chatPending, loading, error],
    );

    const onOpen = useCallback(
        (document: WorkspaceDocument) => {
            if (interactionDisabled || chatPending || mutationBusy.current || loading || error) return;
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
            if (typing || dialog || interactionDisabled || chatPending || mutationBusy.current || loading || error || filtersOpen || detailsOpen) {
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
            const ids = selection.ids.includes(id) ? selection.ids : [id];
            const targets = documents.filter((document) => ids.includes(documentId(document)));
            if (interactionDisabled || targets.length !== ids.length || !canPerform('tag_documents', targets)) {
                event.preventDefault();
                return;
            }
            // Dragging an unselected row drags that row alone, which is what every file
            // manager does and what stops a stale selection being filed by accident.
            if (!selection.ids.includes(id)) {
                setSelection({ ids: [id], anchorId: id });
            }
            event.dataTransfer.setData(
                'application/x-simplechat-documents',
                JSON.stringify({ scopeKey, documentIds: ids }),
            );
            event.dataTransfer.effectAllowed = 'copy';
        },
        [selection.ids, documents, scopeKey, canPerform, interactionDisabled],
    );

    /* ---------------------------------------------------------------------- */
    /* Actions                                                                 */
    /* ---------------------------------------------------------------------- */

    const openDialog = useCallback((value: NonNullable<ActiveDialog>) => {
        const targets = value.kind === 'metadata' || value.kind === 'share' ? [value.document] : value.documents;
        const allowed = value.kind === 'share' ? requirePersonalFeature()
            : operationTargets(value.kind === 'metadata' ? 'edit_metadata' : value.kind === 'tag' ? 'tag_documents' : 'delete', targets);
        if (allowed) {
            setDetailsOpen(false);
            setDialogError(null);
            setFeedback(null);
            onDirtyChange?.(true);
            setDialog(value);
        }
    }, [operationTargets, requirePersonalFeature, onDirtyChange]);

    const closeDialog = useCallback(() => {
        if (mutationBusy.current) {
            toast.info('Wait for the current operation to finish. Closing does not cancel server work.');
            return;
        }
        setDialog(null);
        setDialogError(null);
        onDirtyChange?.(false);
    }, [onDirtyChange]);

    /**
     * Run one request per batch of documents, reporting progress as each lands.
     *
     * Always clears the task, including when a batch throws, so a failure can never leave the
     * progress bar up forever -- which is exactly what an indeterminate spinner around a
     * single long request looked like.
     */
    const runBatched = useCallback(
        async (
            operation: DocumentOperation,
            label: string,
            targets: WorkspaceDocument[],
            perBatch: (adapter: DocumentOperationAdapter, batch: WorkspaceDocument[]) => Promise<DocumentBatchOutcome>,
        ): Promise<DocumentBatchOutcome | null> => {
            const captured = operationTargets(operation, targets);
            if (!captured) return null;
            const batches = batched(captured.targets, BULK_BATCH_SIZE);
            const outcome: DocumentBatchOutcome = { succeeded: [], errors: [] };
            let processed = 0;
            beginMutation(label, captured.targets.length);
            try {
                for (const batch of batches) {
                    if (!mounted.current) return null;
                    try {
                        const result = await perBatch(captured.adapter, batch);
                        outcome.succeeded.push(...result.succeeded);
                        outcome.errors.push(...result.errors);
                    } catch (batchError) {
                        outcome.errors.push(...batch.map((document) => ({
                            document_id: documentId(document),
                            message: errorMessage(batchError, `${label} was not confirmed. Refresh before retrying.`),
                        })));
                    }
                    processed += batch.length;
                    if (mounted.current) setTask({ label, completed: processed, total: captured.targets.length });
                }
                if (!mounted.current) return null;
                const failedIds = [...new Set(outcome.errors.map((error) => error.document_id))];
                failedSelection.current = new Set(failedIds);
                if (failedIds.length || operation === 'delete') {
                    setSelection({ ids: failedIds, anchorId: failedIds[0] ?? null });
                }
                const title = `${label}: ${outcome.succeeded.length} of ${captured.targets.length} confirmed.`;
                setFeedback({ title, errors: outcome.errors });
                if (outcome.errors.length) toast.error(`${title} Review the failed items before retrying.`);
                else toast.success(title);
                await refreshAll();
                return outcome;
            } finally {
                finishMutation();
            }
        },
        [operationTargets, beginMutation, finishMutation, refreshAll],
    );

    const runBulkTag = useCallback(
        async (
            targets: WorkspaceDocument[],
            action: 'add_tags' | 'remove_tags',
            tagNames: string[],
            options: { undoable?: boolean } = {},
        ): Promise<DocumentBatchOutcome | null> => {
            if (!targets.length || !tagNames.length) return null;
            const verb = action === 'add_tags' ? 'Tagging' : 'Untagging';
            const outcome = await runBatched(
                'tag_documents', verb, targets,
                (adapter, batch) => adapter.tagDocuments(batch, action, tagNames),
            );
            if (mounted.current && outcome && !outcome.errors.length && options.undoable) {
                toast.success(`${verb} confirmed.`, {
                    label: 'Undo',
                    onAct: () => {
                        if (mounted.current) void runBulkTag(targets, action === 'add_tags' ? 'remove_tags' : 'add_tags', tagNames);
                    },
                });
            }
            return outcome;
        },
        [runBatched],
    );

    const onDropOnTag = useCallback(
        (tagName: string, ids: string[], draggedScope?: string) => {
            const targets = documents.filter((document) => ids.includes(documentId(document)));
            if ((draggedScope !== scopeKey && (isGroup || draggedScope)) || !ids.length || targets.length !== ids.length) {
                toast.error('Drag documents from this workspace only. No tags were changed.');
                return;
            }
            void runBulkTag(targets, 'add_tags', [tagName], { undoable: true });
        },
        [documents, scopeKey, isGroup, runBulkTag],
    );

    const onUploadFiles = useCallback(
        async (files: File[]) => {
            if (!files.length) return;
            const captured = operationTargets('upload');
            if (!captured) return;
            const maxSizeMb = Number(settings?.max_file_size_mb ?? 0);
            const tooLarge = maxSizeMb > 0 ? files.filter((file) => file.size > maxSizeMb * 1024 * 1024) : [];
            const accepted = files.filter((file) => !tooLarge.includes(file));
            const validationErrors = tooLarge.map((file) => ({
                document_id: file.name, message: `Exceeds the ${maxSizeMb} MB upload limit.`,
            }));
            beginMutation('Uploading files', files.length);
            setUploading(true);
            try {
                const response = accepted.length ? await captured.adapter.upload(accepted)
                    : { document_ids: [], processed_filenames: [], errors: [] };
                if (!mounted.current) return;
                const errors = [...validationErrors, ...response.errors.map((message) => ({ document_id: 'Upload', message }))];
                if (response.document_ids.length + errors.length < files.length) {
                    errors.push({ document_id: 'Upload', message: 'The server did not confirm every file. Refresh before retrying.' });
                }
                const title = `Accepted ${response.document_ids.length} of ${files.length} files. Processing is queued, not complete.`;
                setFeedback({ title, errors });
                if (errors.length) toast.error(title);
                else toast.info(title);
                await refreshAll();
            } catch (uploadError) {
                if (mounted.current) {
                    const message = errorMessage(uploadError, 'Upload was not confirmed. Refresh before retrying.');
                    setFeedback({ title: 'Upload was not confirmed', errors: [{ document_id: 'Upload', message }] });
                    toast.error(message);
                }
            } finally {
                finishMutation();
            }
        },
        [operationTargets, beginMutation, finishMutation, refreshAll, settings],
    );

    const onDownload = useCallback(async (targets: WorkspaceDocument[]) => {
        const captured = operationTargets('download', targets);
        if (!captured) return;
        beginMutation('Preparing download', captured.targets.length);
        try {
            const blob = await captured.adapter.download(captured.targets);
            if (!mounted.current) return;
            saveBlob(blob, targets.length === 1 ? String(targets[0].file_name ?? 'document') : 'documents.zip');
            toast.success('Download ready.');
        } catch (downloadError) {
            if (mounted.current) toast.error(errorMessage(downloadError, 'Download failed. No file was saved.'));
        } finally {
            finishMutation();
        }
    }, [operationTargets, beginMutation, finishMutation]);

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
            if (!availability.chat || mutationBusy.current) {
                toast.error('Chat is not currently available for this selection. Refresh workspace access and try again.');
                return;
            }
            const reason = targets.map(chatSelectionReason).find(Boolean);
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
                if (isGroup) documents = await Promise.all(documents.map((document) => reader.detail(documentId(document), controller.signal)));
                if (controller.signal.aborted || !mounted.current || access.current.interactionDisabled || !access.current.canChat) return;
                const blocked = documents.map((document) => documentSelectionReason(document, reader.scope)).find(Boolean);
                if (blocked) {
                    setDocuments((current) => current.map((item) => documents.find((document) => documentId(document) === documentId(item)) ?? item));
                    toast.error(blocked);
                    return;
                }
                const scope = reader.scope.kind === 'group' ? groupScope(reader.scope) : PERSONAL_SCOPE;
                const tags = isGroup ? query.tags : [];
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
        [navigate, reader, isGroup, query.tags, availability.chat, chatSelectionReason],
    );

    const onExtractMetadata = useCallback(
        async (targets: WorkspaceDocument[]) => {
            await runBatched('extract_metadata', 'Metadata extraction queued', targets, (adapter, batch) => adapter.extractMetadata(batch));
        },
        [runBatched],
    );

    const onReextract = useCallback(
        async (targets: WorkspaceDocument[], mode: 'read' | 'layout') => {
            if (mode === 'layout' && !features?.enable_enhanced_extraction) {
                toast.error('Enhanced extraction is not enabled.');
                return;
            }
            await runBatched('reprocess', 'Reprocessing queued', targets, (adapter, batch) => adapter.reprocess(batch, mode));
        },
        [runBatched, features],
    );

    const onSaveMetadata = useCallback(
        async (target: WorkspaceDocument, draft: MetadataDraft) => {
            const captured = operationTargets('edit_metadata', [target]);
            if (!captured) return;
            const changes = changedDocumentMetadata(target, draft);
            beginMutation('Saving metadata', 1);
            try {
                const status = await captured.adapter.editMetadata(captured.targets[0], changes);
                if (!mounted.current) return;
                setDialog(null);
                if (status === 'queued') {
                    setDocuments((current) => current.filter((document) => documentId(document) !== documentId(target)));
                    setInspectedId(null);
                    toast.info('Metadata saved. Screening is queued; the document remains unavailable until released.');
                } else toast.success('Metadata saved.');
                await refreshAll();
            } catch (saveError) {
                if (mounted.current) {
                    const message = errorMessage(saveError, 'Could not save metadata. Your draft is kept.');
                    setDialogError(message);
                    toast.error(message);
                }
            } finally {
                finishMutation();
            }
        },
        [operationTargets, beginMutation, finishMutation, refreshAll],
    );

    const onConfirmDelete = useCallback(
        async (
            targets: WorkspaceDocument[],
            options: DocumentDeleteOptions,
        ) => {
            const outcome = await runBatched('delete', 'Deleting documents', targets, (adapter, batch) => adapter.deleteDocuments(batch, options));
            if (!outcome || !mounted.current) return;
            setDialog(outcome.errors.length ? {
                kind: 'delete', documents: targets.filter((document) => outcome.errors.some((error) => error.document_id === documentId(document))),
                blocked: outcome.errors,
            } : null);
        },
        [runBatched],
    );

    const onApplyTags = useCallback(async (added: string[], removed: string[]) => {
        if (dialog?.kind !== 'tag') return;
        const targets = dialog.documents;
        const outcome = await runBatched('tag_documents', 'Updating document tags', targets, async (adapter, batch) => {
            const results: DocumentBatchOutcome[] = [];
            if (added.length) results.push(await adapter.tagDocuments(batch, 'add_tags', added));
            if (removed.length) results.push(await adapter.tagDocuments(batch, 'remove_tags', removed));
            const errors = results.flatMap((result) => result.errors);
            return {
                succeeded: batch.map(documentId).filter((id) =>
                    results.every((result) => result.succeeded.includes(id)) && !errors.some((error) => error.document_id === id)),
                errors,
            };
        });
        if (!outcome || !mounted.current) return;
        setDialog(outcome.errors.length ? {
            kind: 'tag', documents: targets.filter((document) => outcome.errors.some((error) => error.document_id === documentId(document))),
        } : null);
    }, [dialog, runBatched]);

    const onCreateTag = useCallback(async (name: string): Promise<string | null> => {
        const captured = operationTargets('manage_tags');
        if (!captured) return null;
        beginMutation('Creating tag', 1);
        try {
            const outcome = await captured.adapter.createTag(name);
            if (!mounted.current) return null;
            if (outcome.errors.length || outcome.vocabularyRetained) {
                setFeedback({ title: 'The tag change is not complete', errors: outcome.errors });
                setDialogError('The tag change is not complete. Refresh the vocabulary before retrying.');
                await loadSidebar();
                return null;
            }
            await loadSidebar();
            return outcome.tag?.name ?? name.trim();
        } catch (cause) {
            if (mounted.current) setDialogError(errorMessage(cause, 'Could not create the tag. Your draft is kept.'));
            return null;
        } finally {
            finishMutation();
        }
    }, [operationTargets, beginMutation, finishMutation, loadSidebar]);

    const onSaveView = useCallback(() => {
        if (!requirePersonalFeature()) return;
        const name = window.prompt('Name this view');
        if (!name?.trim()) {
            return;
        }
        const view = createSavedView(name, query);
        saveUserSettings({ v2DocumentSavedViews: upsertSavedView(savedViews, view) });
        toast.success(`Saved "${view.name}" to the rail.`);
    }, [query, savedViews, saveUserSettings, requirePersonalFeature]);

    const onDeleteSavedView = useCallback(
        (view: DocumentSavedView) => {
            if (!requirePersonalFeature()) return;
            if (!window.confirm(`Remove the saved view "${view.name}"?`)) {
                return;
            }
            saveUserSettings({
                v2DocumentSavedViews: removeSavedView(savedViews, view.id),
            });
        },
        [savedViews, saveUserSettings, requirePersonalFeature],
    );

    /* ---------------------------------------------------------------------- */
    /* Render                                                                  */
    /* ---------------------------------------------------------------------- */

    const chips = describeActiveFilters(query).map((chip) =>
        isGroup && chip.kind === 'place' && chip.value === 'shared'
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
                            : !availability.upload ? 'This group has no visible documents. Use the classic workspace to manage files.'
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
                        ) : !availability.upload ? (
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
                onDragStart={availability.tagDocuments ? onDragStart : undefined}
                canDrag={(document) => canPerform('tag_documents', [document])}
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
                    if (interactionDisabled || chatPending || mutationBusy.current || loading || error) return;
                    setInspectedId(null);
                    setSelection((current) => toggleSelectAll(current, orderedIds));
                }}
                onSort={onSort}
                onOpen={onOpen}
                onDragStart={availability.tagDocuments ? onDragStart : undefined}
                canDrag={(document) => canPerform('tag_documents', [document])}
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
            if (isGroup || interactionDisabled) return;
            setSearchDraft(view.query.search);
            setQuery((current) => applySavedView(current, view));
        }}
        onDeleteSavedView={onDeleteSavedView}
        onDropOnTag={availability.tagDocuments ? onDropOnTag : undefined}
        placesEnabled={reader.queries.places}
        sharedLabel={isGroup ? 'Shared with this group' : 'Shared with me'}
        compact={compact}
    />;
    const detailsPane = <DocumentDetailsPane
        documents={detailDocuments}
        availability={{ ...availability, chat: availability.chat && detailDocuments.every((document) => !chatSelectionReason(document)) }}
        reader={reader}
        selectionReason={chatSelectionReason}
        loading={detailLoading}
        error={detailError}
        interactionDisabled={interactionDisabled || chatPending || busy}
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
            onRemoveTag: (targets, tag) => void runBulkTag(targets, 'remove_tags', [tag]),
        }}
        tagColors={tagColors}
        classificationColors={classificationColors}
        onClose={() => {
            setDetailsOpen(false);
            if (!compact) updatePrefs({ detailsPaneOpen: false });
        }}
    />;

    return (
        <fieldset ref={containerRef} disabled={interactionDisabled || chatPending || busy} aria-label="Documents explorer"
            aria-busy={loading}
            className="flex h-full min-h-0 min-w-0 flex-col gap-2">
            {availability.upload ? <input
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
                selectedDocuments={selectedDocuments}
                uploading={uploading}
                availability={{ ...availability, chat: availability.chat && selectedDocuments.every((document) => !chatSelectionReason(document)) }}
                canSaveView={!isGroup && isSaveableQuery(query)}
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
            {isGroup && !canChat ? <p role="status" className="text-xs text-text-3">Chat is not available for this group. You can still inspect its documents.</p> : null}
            {feedback && !dialog ? <div className="space-y-1">
                {feedback.errors.length ? <OperationFeedback {...feedback} documents={documents} />
                    : <p role="status" className="text-xs text-text-3">{feedback.title}</p>}
            </div> : null}
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

            {dialog?.kind === 'tag' ? (
                <TagDialog
                    documents={dialog.documents}
                    tags={tags}
                    busy={busy}
                    disabled={!canPerform('tag_documents', dialog.documents)}
                    canCreateTag={availability.manageTags}
                    scopeLabel={isGroup ? scopeLabel : undefined}
                    error={dialogError}
                    errors={feedback?.errors}
                    onClose={closeDialog}
                    onApply={(added, removed) => void onApplyTags(added, removed)}
                    onCreateTag={onCreateTag}
                />
            ) : null}

            {dialog?.kind === 'metadata' ? (
                <MetadataDialog
                    document={dialog.document}
                    classifications={classifications}
                    classificationEnabled={availability.classification}
                    busy={busy}
                    disabled={!canPerform('edit_metadata', [dialog.document])}
                    disabledReason={isGroup && !loading && !interactionDisabled
                        && !documents.some((document) => documentId(document) === documentId(dialog.document))
                        ? 'This document is no longer in the current results. Your draft still targets its original revision and will not be saved onto a replacement.'
                        : undefined}
                    error={dialogError}
                    scopeLabel={isGroup ? scopeLabel : undefined}
                    onClose={closeDialog}
                    onSave={(draft) => void onSaveMetadata(dialog.document, draft)}
                />
            ) : null}

            {!isGroup && dialog?.kind === 'share' ? (
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
                    disabled={!canPerform('delete', dialog.documents)}
                    scopeLabel={scopeLabel}
                    legacyPersonal={!isGroup}
                    onClose={closeDialog}
                    onConfirm={(options) => void onConfirmDelete(dialog.documents, options)}
                />
            ) : null}
        </fieldset>
    );
}
