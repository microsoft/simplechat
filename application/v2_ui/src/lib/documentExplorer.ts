// documentExplorer.ts
// The rules behind the workspace documents explorer, kept free of React.
//
// Everything here is a plain function over plain data: query state to API parameters, the
// derived processing state, and the formatting the list and details pane share. That
// separation is what lets the awkward parts -- a tag arriving in three different shapes,
// a page range that must not move the Next button -- be exercised directly in a test
// rather than through a renderer.
//
// The selection algebra it also exposes now lives in listSelection.ts, shared with the
// conversation rail, and is re-exported below.

import type {
    DocumentFacets,
    DocumentPlace,
    DocumentQuery,
    DocumentSortField,
    WorkspaceDocument,
} from './types';

/* -------------------------------------------------------------------------- */
/* Query state                                                                 */
/* -------------------------------------------------------------------------- */

export const DOCUMENT_PAGE_SIZES = [25, 50, 100, 250] as const;

/**
 * 50 rather than the classic interface's 10.
 *
 * Ten rows reads as a widget on a settings page; an explorer is expected to show you your
 * files. The list is paginated server-side, so the larger page costs one query either way.
 */
export const DEFAULT_DOCUMENT_PAGE_SIZE = 50;

/** Ordering fields the server will honour. Mirrors ALLOWED_DOCUMENT_SORT_FIELDS. */
export const DOCUMENT_SORT_FIELDS: readonly DocumentSortField[] = [
    '_ts',
    'file_name',
    'title',
    'upload_date',
    'file_size',
    'number_of_pages',
    'version',
    'document_classification',
];

export const DOCUMENT_PLACES: readonly DocumentPlace[] = [
    'all',
    'recent',
    'shared',
    'processing',
    'errors',
    'untagged',
];

export const DEFAULT_DOCUMENT_QUERY: DocumentQuery = {
    place: 'all',
    search: '',
    tags: [],
    classification: null,
    page: 1,
    pageSize: DEFAULT_DOCUMENT_PAGE_SIZE,
    sortBy: '_ts',
    sortOrder: 'desc',
};

/**
 * Turn query state into the list endpoint's query string.
 *
 * Empty values are omitted rather than sent blank: the route treats a present-but-empty
 * `search` as a filter over the empty string, which matches everything and merely makes the
 * request harder to read in a log.
 */
export function buildDocumentListParams(query: Partial<DocumentQuery>): string {
    const resolved = { ...DEFAULT_DOCUMENT_QUERY, ...query };
    const params = new URLSearchParams();

    params.set('page', String(Math.max(1, Math.trunc(resolved.page) || 1)));
    params.set('page_size', String(normalizePageSize(resolved.pageSize)));

    const search = resolved.search.trim();
    if (search) {
        params.set('search', search);
    }

    const tags = normalizeTagList(resolved.tags);
    if (tags.length > 0) {
        params.set('tags', tags.join(','));
    }

    if (resolved.classification) {
        params.set('classification', resolved.classification);
    }

    if (resolved.place && resolved.place !== 'all') {
        params.set('place', resolved.place);
    }

    params.set('sort_by', normalizeSortField(resolved.sortBy));
    params.set('sort_order', resolved.sortOrder === 'asc' ? 'asc' : 'desc');

    return params.toString();
}

export function normalizeSortField(field: unknown): DocumentSortField {
    return DOCUMENT_SORT_FIELDS.includes(field as DocumentSortField)
        ? (field as DocumentSortField)
        : '_ts';
}

export function normalizePageSize(pageSize: unknown): number {
    const parsed = Math.trunc(Number(pageSize));
    if (!Number.isFinite(parsed) || parsed < 1) {
        return DEFAULT_DOCUMENT_PAGE_SIZE;
    }
    // Not clamped to DOCUMENT_PAGE_SIZES: a value restored from a saved preference written
    // by an older build should still be honoured rather than silently reset.
    return Math.min(parsed, 500);
}

/**
 * Apply a change and decide whether it should send the user back to page one.
 *
 * Any change that alters *which* documents match has to reset the page, otherwise narrowing
 * a filter while on page 4 lands on an empty page and reads as "no documents" rather than
 * as "you are past the end".
 */
export function applyQueryChange(
    query: DocumentQuery,
    change: Partial<DocumentQuery>,
): DocumentQuery {
    const next = { ...query, ...change };
    const changesResultSet =
        ('place' in change && change.place !== query.place) ||
        ('search' in change && change.search !== query.search) ||
        ('classification' in change && change.classification !== query.classification) ||
        ('pageSize' in change && change.pageSize !== query.pageSize) ||
        ('tags' in change && !sameTagList(change.tags ?? [], query.tags));

    if (changesResultSet && !('page' in change)) {
        next.page = 1;
    }
    return next;
}

/**
 * Toggle a column's sort, starting descending for the fields where that is the useful end.
 *
 * Newest-first and largest-first are what people want from a date or a size; A-Z is what
 * they want from a name. Starting every column ascending makes half of them require two
 * clicks to be useful.
 */
export function toggleSort(
    query: DocumentQuery,
    field: DocumentSortField,
): DocumentQuery {
    if (query.sortBy === field) {
        return { ...query, sortOrder: query.sortOrder === 'asc' ? 'desc' : 'asc' };
    }
    const descendingFirst: DocumentSortField[] = [
        '_ts',
        'upload_date',
        'file_size',
        'number_of_pages',
        'version',
    ];
    return {
        ...query,
        sortBy: field,
        sortOrder: descendingFirst.includes(field) ? 'desc' : 'asc',
    };
}

function sameTagList(left: readonly string[], right: readonly string[]): boolean {
    if (left.length !== right.length) {
        return false;
    }
    return left.every((tag, index) => tag === right[index]);
}

/* -------------------------------------------------------------------------- */
/* Filter chips                                                                */
/* -------------------------------------------------------------------------- */

export interface FilterChip {
    /** Identifies which part of the query the chip removes. */
    kind: 'place' | 'search' | 'tag' | 'classification';
    /** For a tag chip, the tag it removes. */
    value: string;
    label: string;
}

export const DOCUMENT_PLACE_LABELS: Record<DocumentPlace, string> = {
    all: 'All documents',
    recent: 'Recent',
    shared: 'Shared with me',
    processing: 'Processing',
    errors: 'Needs attention',
    untagged: 'Untagged',
};

/**
 * Describe the active filters as removable chips.
 *
 * A flat, tagged workspace has no path to put in a breadcrumb, and the honest equivalent is
 * to say what is currently narrowing the list. The classic interface shows nothing at all,
 * which is why a filter left set on one visit looks like missing documents on the next.
 */
export function describeActiveFilters(query: DocumentQuery): FilterChip[] {
    const chips: FilterChip[] = [];

    if (query.place && query.place !== 'all') {
        chips.push({
            kind: 'place',
            value: query.place,
            label: DOCUMENT_PLACE_LABELS[query.place] ?? query.place,
        });
    }

    const search = query.search.trim();
    if (search) {
        chips.push({ kind: 'search', value: search, label: `Search: ${search}` });
    }

    for (const tag of normalizeTagList(query.tags)) {
        chips.push({ kind: 'tag', value: tag, label: tag });
    }

    if (query.classification) {
        chips.push({
            kind: 'classification',
            value: query.classification,
            label: query.classification,
        });
    }

    return chips;
}

/** Remove one chip from the query, resetting to page one. */
export function clearFilterChip(query: DocumentQuery, chip: FilterChip): DocumentQuery {
    switch (chip.kind) {
        case 'place':
            return applyQueryChange(query, { place: 'all' });
        case 'search':
            return applyQueryChange(query, { search: '' });
        case 'classification':
            return applyQueryChange(query, { classification: null });
        case 'tag':
            return applyQueryChange(query, {
                tags: query.tags.filter((tag) => tag !== chip.value),
            });
        default:
            return query;
    }
}

/** Reset every filter while keeping how the list is presented. */
export function clearAllFilters(query: DocumentQuery): DocumentQuery {
    return applyQueryChange(query, {
        place: 'all',
        search: '',
        tags: [],
        classification: null,
    });
}

/* -------------------------------------------------------------------------- */
/* Tags                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Reduce a tag of any shape to its name.
 *
 * Tags arrive in more than one form: /api/documents/tags returns `{name, count, color}`
 * objects, while a document's own `tags` field may be an array of strings or a
 * comma-separated string. Rendering an object directly is what caused React error #31 on
 * this page, so every tag is funnelled through here.
 */
export function tagName(tag: unknown): string {
    if (typeof tag === 'string') {
        return tag.trim();
    }
    if (tag && typeof tag === 'object' && 'name' in tag) {
        return String((tag as { name: unknown }).name ?? '').trim();
    }
    return '';
}

export function normalizeTags(tags: unknown): string[] {
    if (Array.isArray(tags)) {
        return tags.map(tagName).filter(Boolean);
    }
    if (typeof tags === 'string' && tags.trim()) {
        return tags
            .split(',')
            .map((tag) => tag.trim())
            .filter(Boolean);
    }
    return [];
}

/** De-duplicate a tag list while keeping the order the user built it in. */
export function normalizeTagList(tags: readonly unknown[]): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const tag of tags ?? []) {
        const name = tagName(tag);
        if (name && !seen.has(name)) {
            seen.add(name);
            result.push(name);
        }
    }
    return result;
}

/** Tags carried by every one of the given documents, for the multi-selection pane. */
export function commonTags(documents: readonly WorkspaceDocument[]): string[] {
    if (documents.length === 0) {
        return [];
    }
    const [first, ...rest] = documents;
    let shared = normalizeTags(first.tags);
    for (const document of rest) {
        const tags = new Set(normalizeTags(document.tags));
        shared = shared.filter((tag) => tags.has(tag));
        if (shared.length === 0) {
            break;
        }
    }
    return shared;
}

/* -------------------------------------------------------------------------- */
/* Document state                                                              */
/* -------------------------------------------------------------------------- */

export type DocumentState = 'ready' | 'processing' | 'error' | 'pending_approval';

export interface DocumentStatus {
    state: DocumentState;
    /** 0-100. Only meaningful while processing. */
    percent: number;
    label: string;
}

/**
 * Work out what to show for a document's processing state.
 *
 * Mirrors `_document_processing_state` in route_backend_documents.py. A document with no
 * `percentage_complete` at all predates progress tracking and is treated as ready: showing
 * it as permanently stuck at 0% would be worse than saying nothing.
 */
export function documentStatus(document: WorkspaceDocument): DocumentStatus {
    const statusText = String(document.status ?? '').toLowerCase();

    if (statusText.includes('error') || statusText.includes('failed')) {
        return { state: 'error', percent: 0, label: 'Error' };
    }

    if (document.shared_approval_status === 'not_approved') {
        return { state: 'pending_approval', percent: 100, label: 'Pending approval' };
    }

    const raw = document.percentage_complete;
    if (raw === undefined || raw === null) {
        return { state: 'ready', percent: 100, label: 'Ready' };
    }

    const percent = Number(raw);
    if (!Number.isFinite(percent) || percent >= 100) {
        return { state: 'ready', percent: 100, label: 'Ready' };
    }

    const clamped = Math.max(0, Math.min(99, Math.round(percent)));
    return { state: 'processing', percent: clamped, label: `${clamped}%` };
}

/** True while the document is still being indexed and its row should keep polling. */
export function isProcessing(document: WorkspaceDocument): boolean {
    return documentStatus(document).state === 'processing';
}

export function documentId(document: WorkspaceDocument): string {
    return String(document.id ?? document.document_id ?? '');
}

/**
 * The two lines of the name column.
 *
 * A file name is often something like `MSA_v2_FINAL(3).docx`, which says very little, so the
 * extracted title leads when there is one. When there is not, promoting the file name is
 * better than showing "Untitled" above it.
 */
export function documentDisplayName(document: WorkspaceDocument): {
    primary: string;
    secondary: string | null;
} {
    const title = String(document.title ?? '').trim();
    const fileName = String(document.file_name ?? '').trim();

    if (title && fileName && title !== fileName) {
        return { primary: title, secondary: fileName };
    }
    return { primary: title || fileName || 'Untitled', secondary: null };
}

/** Split a comma-separated or already-split metadata field into a clean list. */
export function normalizeStringList(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.map((entry) => String(entry ?? '').trim()).filter(Boolean);
    }
    if (typeof value === 'string' && value.trim()) {
        return value
            .split(',')
            .map((entry) => entry.trim())
            .filter(Boolean);
    }
    return [];
}

/* -------------------------------------------------------------------------- */
/* Selection                                                                   */
/* -------------------------------------------------------------------------- */

// The selection algebra is not specific to documents -- the conversation rail applies the
// same click / Ctrl+click / Shift+click rules -- so it lives in listSelection.ts and is
// re-exported here. Callers that already import it from this module keep working, and the
// two lists cannot drift apart into subtly different modifier behaviour.
export {
    EMPTY_SELECTION,
    applySelection,
    isEverythingSelected,
    moveSelection,
    pruneSelection,
    selectionIntentFromEvent,
    toggleSelectAll,
} from './listSelection';
export type { SelectionIntent, SelectionState } from './listSelection';

/* -------------------------------------------------------------------------- */
/* Formatting                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Format a byte count the way a file manager does.
 *
 * Binary units with a decimal-looking label, matching what Windows and macOS both report,
 * so a size shown here agrees with the size shown after the file is downloaded.
 */
export function formatFileSize(bytes: unknown): string {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0) {
        return '—';
    }
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = value;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex += 1;
    }
    const rounded = size >= 100 || unitIndex === 0 ? Math.round(size) : Number(size.toFixed(1));
    return `${rounded} ${units[unitIndex]}`;
}

export function totalFileSize(documents: readonly WorkspaceDocument[]): number {
    return documents.reduce((total, document) => {
        const size = Number(document.file_size);
        return Number.isFinite(size) && size > 0 ? total + size : total;
    }, 0);
}

/** The document's upload time as a Date, or null when it has none that can be read. */
export function documentDate(document: WorkspaceDocument): Date | null {
    const ts = Number(document._ts);
    if (Number.isFinite(ts) && ts > 0) {
        return new Date(ts * 1000);
    }
    const raw = document.upload_date ?? document.last_updated;
    if (!raw) {
        return null;
    }
    const parsed = new Date(String(raw));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * A short relative time, falling back to an absolute date once that stops being useful.
 *
 * "3 months ago" is harder to act on than the date itself, so anything beyond a month is
 * shown as a date. The exact timestamp is available in the details pane either way.
 */
export function formatRelativeDate(value: Date | null, now: Date = new Date()): string {
    if (!value) {
        return '—';
    }
    const seconds = Math.round((now.getTime() - value.getTime()) / 1000);
    if (seconds < 0) {
        return value.toLocaleDateString();
    }
    if (seconds < 60) {
        return 'Just now';
    }
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) {
        return `${minutes} min ago`;
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
        return `${hours} hr ago`;
    }
    const days = Math.floor(hours / 24);
    if (days === 1) {
        return 'Yesterday';
    }
    if (days < 30) {
        return `${days} days ago`;
    }
    return value.toLocaleDateString();
}

export function formatAbsoluteDate(value: Date | null): string {
    if (!value) {
        return '—';
    }
    return value.toLocaleString();
}

/* -------------------------------------------------------------------------- */
/* Pagination                                                                  */
/* -------------------------------------------------------------------------- */

export interface PageRange {
    /** 1-based index of the first item on the page, or 0 when there are none. */
    from: number;
    to: number;
    total: number;
    pageCount: number;
}

export function describePage(
    page: number,
    pageSize: number,
    totalCount: number,
): PageRange {
    const total = Math.max(0, Math.trunc(totalCount) || 0);
    const size = normalizePageSize(pageSize);
    const pageCount = Math.max(1, Math.ceil(total / size));
    if (total === 0) {
        return { from: 0, to: 0, total: 0, pageCount: 1 };
    }
    const currentPage = Math.max(1, Math.min(pageCount, Math.trunc(page) || 1));
    const from = (currentPage - 1) * size + 1;
    const to = Math.min(total, currentPage * size);
    return { from, to, total, pageCount };
}

/**
 * Page numbers to offer, with nulls standing in for gaps.
 *
 * Always renders exactly `maxButtons` slots once there are more pages than that, counting a
 * gap marker as a slot. Budgeting for the gaps is the whole point: sizing only the numbers
 * lets the control change width as the window moves away from an edge, which shifts the
 * Next button out from under the pointer on the click that moved it.
 */
export function paginationItems(
    page: number,
    pageCount: number,
    maxButtons = 7,
): (number | null)[] {
    if (pageCount <= maxButtons) {
        return Array.from({ length: pageCount }, (_, index) => index + 1);
    }

    const current = Math.max(1, Math.min(pageCount, Math.trunc(page) || 1));
    const range = (start: number, end: number) =>
        Array.from({ length: end - start + 1 }, (_, index) => start + index);

    // One anchor and one gap at the far side leave this many contiguous pages.
    const edgeRun = maxButtons - 2;
    // Two anchors and two gaps leave this many, centred on the current page.
    const middleRun = maxButtons - 4;

    if (current <= maxButtons - 3) {
        return [...range(1, edgeRun), null, pageCount];
    }

    if (current >= pageCount - middleRun) {
        return [1, null, ...range(pageCount - edgeRun + 1, pageCount)];
    }

    const half = Math.floor(middleRun / 2);
    return [1, null, ...range(current - half, current - half + middleRun - 1), null, pageCount];
}

/** Split a list into fixed-size batches. */
export function batched<T>(items: readonly T[], size: number): T[][] {
    const batchSize = Math.max(1, Math.trunc(size) || 1);
    const batches: T[][] = [];
    for (let index = 0; index < items.length; index += batchSize) {
        batches.push(items.slice(index, index + batchSize));
    }
    return batches;
}

/* -------------------------------------------------------------------------- */
/* Extraction mode                                                             */
/* -------------------------------------------------------------------------- */

export type ExtractionMode = 'read' | 'layout';

/**
 * Extensions the extraction mode can be changed for.
 *
 * Only PDFs and images go through Document Intelligence, so offering the choice on a .docx
 * would queue a job that changes nothing. Quoted from
 * EXTRACTION_MODE_CHANGE_IMAGE_EXTENSIONS in workspace-documents.js.
 */
export const EXTRACTION_MODE_IMAGE_EXTENSIONS = [
    '.jpg',
    '.jpeg',
    '.png',
    '.bmp',
    '.tiff',
    '.tif',
    '.heif',
    '.heic',
] as const;

export function supportsExtractionModeChange(document: WorkspaceDocument): boolean {
    const fileName = String(document.file_name ?? '').toLowerCase();
    if (!fileName) {
        return false;
    }
    return (
        fileName.endsWith('.pdf') ||
        EXTRACTION_MODE_IMAGE_EXTENSIONS.some((extension) => fileName.endsWith(extension))
    );
}

/** The mode a document was last extracted with, or null when it was never recorded. */
export function extractionMode(document: WorkspaceDocument): ExtractionMode | null {
    const mode = String(document.document_intelligence_extraction_mode ?? '')
        .trim()
        .toLowerCase();
    if (mode === 'layout' || mode === 'read') {
        return mode;
    }
    return null;
}

export function extractionModeLabel(mode: ExtractionMode | null): string {
    if (mode === 'layout') {
        return 'Enhanced';
    }
    if (mode === 'read') {
        return 'Standard';
    }
    return 'Unknown';
}

export interface ExtractionSummary {
    /** Documents whose extraction mode can be changed. */
    supported: WorkspaceDocument[];
    /** Documents that are not PDFs or images, so the choice does not apply to them. */
    unsupported: WorkspaceDocument[];
    /**
     * The mode the supported documents are currently on.
     *
     * `mixed` when they disagree and `null` when none of them recorded one, which are
     * different situations: the first means switching will change some of them, the second
     * means nothing is known about any of them.
     */
    current: ExtractionMode | 'mixed' | null;
}

/**
 * Work out what to say about a selection's extraction mode.
 *
 * The pane previously offered Standard and Enhanced as two equal buttons without saying
 * which one the document was already on, so the only way to change it was to guess and then
 * check. Reporting the current mode is what turns two buttons into one meaningful choice.
 */
export function summarizeExtraction(
    documents: readonly WorkspaceDocument[],
): ExtractionSummary {
    const supported: WorkspaceDocument[] = [];
    const unsupported: WorkspaceDocument[] = [];

    for (const document of documents) {
        (supportsExtractionModeChange(document) ? supported : unsupported).push(document);
    }

    const modes = new Set<ExtractionMode>();
    for (const document of supported) {
        const mode = extractionMode(document);
        if (mode) {
            modes.add(mode);
        }
    }

    let current: ExtractionMode | 'mixed' | null = null;
    if (modes.size === 1) {
        current = [...modes][0];
    } else if (modes.size > 1) {
        current = 'mixed';
    }

    return { supported, unsupported, current };
}

/* -------------------------------------------------------------------------- */
/* Facets                                                                      */
/* -------------------------------------------------------------------------- */

export const EMPTY_FACETS: DocumentFacets = {
    total: 0,
    untagged: 0,
    processing: 0,
    errors: 0,
    recent: 0,
    shared_with_me: 0,
    by_tag: {},
    by_classification: {},
};

/** The count to show against a place in the rail, or null when it should show none. */
export function placeCount(facets: DocumentFacets | null, place: DocumentPlace): number | null {
    if (!facets) {
        return null;
    }
    switch (place) {
        case 'all':
            return facets.total;
        case 'recent':
            return facets.recent;
        case 'shared':
            return facets.shared_with_me;
        case 'processing':
            return facets.processing;
        case 'errors':
            return facets.errors;
        case 'untagged':
            return facets.untagged;
        default:
            return null;
    }
}

/**
 * Places worth showing in the rail.
 *
 * "All" is always offered; the rest appear only once they describe something, so a workspace
 * with nothing in flight does not carry a permanent "Processing 0" entry.
 */
export function visiblePlaces(facets: DocumentFacets | null): DocumentPlace[] {
    const places: DocumentPlace[] = ['all'];
    if (!facets) {
        return places;
    }
    if (facets.recent > 0) {
        places.push('recent');
    }
    if (facets.shared_with_me > 0) {
        places.push('shared');
    }
    if (facets.processing > 0) {
        places.push('processing');
    }
    if (facets.errors > 0) {
        places.push('errors');
    }
    if (facets.untagged > 0) {
        places.push('untagged');
    }
    return places;
}
