// EnhancedCitationViewer.tsx
// Opens the cited source itself rather than only its extracted text.
//
// Which viewer applies is decided from the file extension, matching V1. Every failure path
// falls back to the plain text citation, because a citation that cannot render its source
// is still more useful as a readable passage than as a dead click.

import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { clsx } from 'clsx';
import {
    ChevronLeft,
    ChevronRight,
    Download,
    FileText,
    Loader2,
    Maximize2,
    Minimize2,
    TriangleAlert,
    X,
} from 'lucide-react';
import {
    enhancedCitationImageUrl,
    enhancedCitationMediaUrl,
    enhancedCitationVisioUrl,
    fetchCitation,
    fetchEnhancedCitationPdf,
    fetchTabularPreview,
    tabularWorkspaceDownloadUrl,
    workspaceDocumentDownloadUrl,
    type TabularPreview,
} from '../../lib/endpoints';
import {
    convertTimestampToSeconds,
    formatTimestamp,
    type EnhancedCitationMetadata,
    type EnhancedCitationType,
} from '../../lib/enhancedCitations';
import { GlassPanel } from '../ui/primitives';

interface ViewerProps {
    docId: string;
    /** Page number for documents, or a seconds/HH:MM:SS offset for media. */
    location: string;
    metadata: EnhancedCitationMetadata;
    /** Called when this viewer cannot render, so the caller can show the text passage. */
    onFail: (reason: string) => void;
    /** The citation being viewed, when known, so a viewer can show the cited passage too. */
    citationId?: string;
}

function ViewerError({ message }: { message: string }) {
    return (
        <p className="flex items-start gap-2 p-6 text-sm text-danger">
            <TriangleAlert size={16} className="mt-0.5 shrink-0" />
            {message}
        </p>
    );
}

function ViewerLoading({ label }: { label: string }) {
    return (
        <p className="flex items-center gap-2 p-6 text-sm text-text-3">
            <Loader2 size={15} className="animate-spin" />
            {label}
        </p>
    );
}

/* -------------------------------------------------------------------------- */
/* PDF                                                                         */
/* -------------------------------------------------------------------------- */

function PdfViewer({ docId, location, onFail }: ViewerProps) {
    const [objectUrl, setObjectUrl] = useState<string | null>(null);
    const [subPage, setSubPage] = useState(1);
    const [showAll, setShowAll] = useState(false);
    const [loading, setLoading] = useState(true);

    const requestedPage = Math.max(1, Number.parseInt(location, 10) || 1);

    useEffect(() => {
        let cancelled = false;
        let createdUrl: string | null = null;

        setLoading(true);
        void (async () => {
            try {
                const result = await fetchEnhancedCitationPdf(docId, requestedPage, showAll);
                if (cancelled) {
                    return;
                }
                createdUrl = URL.createObjectURL(result.blob);
                setObjectUrl(createdUrl);
                setSubPage(result.page);
            } catch (error) {
                if (!cancelled) {
                    onFail(
                        error instanceof Error ? error.message : 'Could not load the PDF.',
                    );
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        })();

        return () => {
            cancelled = true;
            // Object URLs hold the whole document in memory until revoked.
            if (createdUrl) {
                URL.revokeObjectURL(createdUrl);
            }
        };
    }, [docId, requestedPage, showAll, onFail]);

    if (loading) {
        return <ViewerLoading label="Loading the cited pages…" />;
    }

    if (!objectUrl) {
        return <ViewerError message="The PDF could not be displayed." />;
    }

    return (
        <div className="flex h-full flex-col">
            <div className="flex shrink-0 items-center gap-2 border-b border-edge px-4 py-2">
                <span className="text-xs text-text-3">
                    {showAll
                        ? 'Showing the whole document'
                        : `Showing around page ${requestedPage}`}
                </span>
                <button
                    type="button"
                    onClick={() => setShowAll((current) => !current)}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    {showAll ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                    {showAll ? 'Just the cited pages' : 'Show all pages'}
                </button>
            </div>

            {/*
              Rendered by the browser's built-in PDF viewer via a blob URL, which is how V1
              does it. The CSP already permits frame-src blob:, and this avoids vendoring a
              PDF engine purely to display a document the browser can already render.
            */}
            <iframe
                title="Cited document"
                // xss-check: ignore reviewed: objectUrl is created by URL.createObjectURL from the authenticated PDF blob, never caller text.
                src={`${objectUrl}#page=${subPage}`}
                className="min-h-0 w-full flex-1 border-0"
            />
        </div>
    );
}

/* -------------------------------------------------------------------------- */
/* Image                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * The original cited passage, independent of worksheet/table preview navigation.
 *
 * The passage remains tied to the citation rather than the table currently being previewed.
 */
function CitedSourcePassage({
    citationId,
    docId,
    location,
    sourceLabel = 'What was extracted from this image',
}: {
    citationId: string;
    docId: string;
    location: string;
    sourceLabel?: string;
}) {
    const [passage, setPassage] = useState<string | null>(null);
    const [failed, setFailed] = useState(false);

    useEffect(() => {
        let cancelled = false;
        setPassage(null);
        setFailed(false);

        fetchCitation({
            citation_id: citationId,
            document_id: docId || undefined,
            page_number: location || undefined,
        })
            .then((result) => {
                if (!cancelled) {
                    setPassage(String(result?.cited_text ?? '').trim());
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setFailed(true);
                }
            });

        return () => {
            cancelled = true;
        };
    }, [citationId, docId, location]);

    if (failed || passage === '') {
        return null;
    }

    return (
        <details
            open
            className="max-h-[40%] shrink-0 overflow-y-auto border-t border-edge px-5 py-3"
        >
            <summary className="cursor-pointer text-xs font-medium text-text-3 hover:text-text-1">
                {sourceLabel}
            </summary>
            {passage === null ? (
                <p className="mt-2 flex items-center gap-2 text-sm text-text-3">
                    <Loader2 size={14} className="animate-spin" />
                    Loading the cited passage…
                </p>
            ) : (
                <p className="mt-2 text-sm leading-relaxed whitespace-pre-wrap text-text-1">
                    {passage}
                </p>
            )}
        </details>
    );
}

function ImageViewer({ docId, location, metadata, onFail, citationId }: ViewerProps) {
    const [loading, setLoading] = useState(true);

    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-4">
                {loading && <ViewerLoading label="Loading the image…" />}
                <img
                    src={enhancedCitationImageUrl(docId)}
                    alt={metadata.file_name || 'Cited image'}
                    onLoad={() => setLoading(false)}
                    onError={() => {
                        setLoading(false);
                        onFail('The image could not be loaded.');
                    }}
                    className={clsx(
                        'max-h-full max-w-full rounded-xl object-contain',
                        loading && 'hidden',
                    )}
                />
            </div>
            {citationId ? (
                <CitedSourcePassage citationId={citationId} docId={docId} location={location} />
            ) : null}
        </div>
    );
}

/* -------------------------------------------------------------------------- */
/* Video and audio                                                             */
/* -------------------------------------------------------------------------- */

function MediaViewer({ docId, location, metadata, onFail, kind }: ViewerProps & {
    kind: 'video' | 'audio';
}) {
    const elementRef = useRef<HTMLVideoElement & HTMLAudioElement>(null);
    const offset = useMemo(() => convertTimestampToSeconds(location), [location]);

    // Seek once metadata is known, since duration is needed to clamp the offset.
    const onLoadedMetadata = () => {
        const element = elementRef.current;
        if (!element || offset <= 0) {
            return;
        }
        element.currentTime =
            offset < element.duration ? offset : Math.max(0, element.duration - 1);
    };

    const source = enhancedCitationMediaUrl(kind, docId);
    // Pointed at the endpoint rather than a blob so the browser can request byte ranges
    // itself. Note the server advertises Accept-Ranges but does not return 206, so seeking
    // a long file still waits for the full download.
    const shared = {
        ref: elementRef,
        src: source,
        controls: true,
        onLoadedMetadata,
        onError: () => onFail(`The ${kind} could not be played.`),
    };

    return (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-4">
            {offset > 0 && (
                <p className="text-xs text-text-3">
                    Cited at {formatTimestamp(offset)}
                </p>
            )}
            {kind === 'video' ? (
                <video {...shared} className="max-h-full max-w-full rounded-xl" />
            ) : (
                <audio {...shared} className="w-full max-w-xl" />
            )}
            <p className="text-xs text-text-3">{metadata.file_name}</p>
        </div>
    );
}

/* -------------------------------------------------------------------------- */
/* Tabular                                                                     */
/* -------------------------------------------------------------------------- */

function TabularViewer({ docId, location, metadata, onFail, citationId }: ViewerProps) {
    const [preview, setPreview] = useState<TabularPreview | null>(null);
    const [sheet, setSheet] = useState<string | undefined>();
    const [tableId, setTableId] = useState<string | undefined>();
    const [startRow, setStartRow] = useState(0);
    const [previousStarts, setPreviousStarts] = useState<number[]>([]);
    const [jumpRecord, setJumpRecord] = useState('1');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [retry, setRetry] = useState(0);
    const hasLoaded = useRef(false);
    const initialLocationApplied = useRef(false);
    const sheetButtons = useRef(new Map<string, HTMLButtonElement>());
    const panelId = useId();
    const tableSelectId = useId();
    const recordInputId = useId();

    useEffect(() => {
        let cancelled = false;
        let redirected = false;
        const controller = new AbortController();
        setLoading(true);
        setError('');

        void (async () => {
            try {
                const result = await fetchTabularPreview(
                    docId, { sheetName: sheet, tableId, startRow }, controller.signal,
                );
                if (!cancelled) {
                    if (!initialLocationApplied.current) {
                        initialLocationApplied.current = true;
                        const requested = (result.sheet_names ?? []).find((name) =>
                            name === location || `${name}!` === location.slice(0, name.length + 1),
                        );
                        if (requested && requested !== result.selected_sheet) {
                            redirected = true;
                            setSheet(requested);
                            return;
                        }
                    }
                    setPreview(result);
                    setJumpRecord(String((result.start_row ?? startRow) + 1));
                    hasLoaded.current = true;
                }
            } catch (error) {
                if (!cancelled) {
                    const message = error instanceof Error ? error.message : 'Could not load the spreadsheet.';
                    setError(message);
                    if (!hasLoaded.current) {
                        onFail(message);
                    }
                }
            } finally {
                if (!cancelled && !redirected) {
                    setLoading(false);
                }
            }
        })();

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [docId, location, sheet, tableId, startRow, retry, onFail]);

    if (loading && !preview) {
        return <ViewerLoading label="Loading the spreadsheet…" />;
    }

    if (!preview) {
        return <ViewerError message="The spreadsheet could not be displayed." />;
    }

    const sheets = preview.sheet_names ?? [];
    const tables = preview.tables ?? [];
    const selectedSheet = preview.selected_sheet ?? sheets[0];
    const currentStart = preview.start_row ?? 0;
    const rowCount = preview.rows?.length ?? 0;
    const hasMore = preview.has_more ?? preview.truncated ?? false;
    const nextStart = preview.next_start_row ?? currentStart + rowCount;

    function changeSheet(name: string) {
        if (name === selectedSheet && !loading && !error) {
            return;
        }
        setLoading(true);
        setSheet(name);
        setTableId(undefined);
        setStartRow(0);
        setPreviousStarts([]);
    }

    function moveSheet(event: ReactKeyboardEvent<HTMLButtonElement>, index: number) {
        let next: number;
        if (event.key === 'ArrowRight') {
            next = (index + 1) % sheets.length;
        } else if (event.key === 'ArrowLeft') {
            next = (index - 1 + sheets.length) % sheets.length;
        } else if (event.key === 'Home') {
            next = 0;
        } else if (event.key === 'End') {
            next = sheets.length - 1;
        } else {
            return;
        }
        event.preventDefault();
        changeSheet(sheets[next]);
        sheetButtons.current.get(sheets[next])?.focus();
    }

    return (
        <div className="flex min-h-0 flex-1 flex-col">
            {sheets.length > 1 && (
                <div role="tablist" aria-label="Workbook worksheets" className="flex shrink-0 flex-wrap gap-1 border-b border-edge px-4 py-2">
                    {sheets.map((name, index) => (
                        <button
                            key={name}
                            type="button"
                            role="tab"
                            aria-selected={selectedSheet === name}
                            aria-controls={panelId}
                            tabIndex={selectedSheet === name ? 0 : -1}
                            ref={(element) => {
                                if (element) {
                                    sheetButtons.current.set(name, element);
                                } else {
                                    sheetButtons.current.delete(name);
                                }
                            }}
                            onClick={() => changeSheet(name)}
                            onKeyDown={(event) => moveSheet(event, index)}
                            className={clsx(
                                'min-h-11 rounded-lg px-3 py-1 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-accent',
                                selectedSheet === name
                                    ? 'bg-accent-soft text-accent'
                                    : 'text-text-2 hover:bg-surface-2',
                            )}
                        >
                            {name}
                        </button>
                    ))}
                </div>
            )}

            <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-edge px-4 py-2">
                <p className="min-w-0 text-sm text-text-2" aria-live="polite">
                    {selectedSheet ? `Worksheet: ${selectedSheet}` : 'CSV data'}
                    {preview.table_range ? ` · ${preview.table_range}` : ''}
                    {preview.header_row ? ` · Header row ${preview.header_row}` : ''}
                    {preview.header_status === 'inferred' ? ' (detected)' : ''}
                    {preview.header_status === 'ambiguous' ? ' · Header is unconfirmed; cell coordinates are retained.' : ''}
                </p>
                {tables.length > 1 && (
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <label htmlFor={tableSelectId} className="text-sm text-text-2">Table</label>
                        <select
                            id={tableSelectId}
                            value={preview.table_id ?? tables[0].id}
                            disabled={loading}
                            onChange={(event) => {
                                setLoading(true);
                                setTableId(event.target.value);
                                setStartRow(0);
                                setPreviousStarts([]);
                            }}
                            className="min-h-11 min-w-0 max-w-full rounded-lg border border-edge-strong bg-surface-1 px-2 py-1 text-base text-text-1 sm:max-w-md sm:text-sm"
                        >
                            {tables.map((table) => (
                                <option key={table.id} value={table.id}>{table.name} · {table.range}</option>
                            ))}
                        </select>
                    </div>
                )}
            </div>
            {error && (
                <div role="alert" className="flex shrink-0 flex-wrap items-center gap-2 border-b border-edge p-3 text-sm text-danger">
                    <span>{error}</span>
                    <button type="button" onClick={() => setRetry((current) => current + 1)} className="min-h-11 rounded-lg px-3 underline">
                        Retry preview
                    </button>
                </div>
            )}
            <div id={panelId} role="tabpanel" aria-label={selectedSheet ? `${selectedSheet} data preview` : 'CSV data preview'} aria-busy={loading} className="min-h-0 flex-1 overflow-auto p-4">
                {loading ? <ViewerLoading label="Loading the selected worksheet and table…" /> : rowCount === 0 ? (
                    <p className="text-sm text-text-3">No data rows in this selection.</p>
                ) : <table className="w-full border-collapse text-sm">
                    <caption className="sr-only">{preview.table_name || selectedSheet || 'CSV'} data preview</caption>
                    <thead>
                        <tr>
                            <th scope="col" className="sticky top-0 border border-edge-strong bg-surface-3 px-2 py-1 text-left font-semibold">
                                {sheets.length ? 'Worksheet row' : 'File row'}
                            </th>
                            {(preview.columns ?? []).map((column, index) => (
                                <th
                                    key={`${column}-${index}`}
                                    scope="col"
                                    className="sticky top-0 border border-edge-strong bg-surface-3 px-2 py-1 text-left font-semibold"
                                >
                                    {column}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {(preview.rows ?? []).map((row, rowIndex) => (
                            <tr key={rowIndex}>
                                <th scope="row" className="border border-edge-strong bg-surface-2 px-2 py-1 text-left font-normal text-text-3">
                                    {preview.row_numbers?.[rowIndex] ?? currentStart + rowIndex + 2}
                                </th>
                                {row.map((cell, cellIndex) => (
                                    <td
                                        key={cellIndex}
                                        className="border border-edge-strong px-2 py-1 whitespace-nowrap"
                                    >
                                        {cell}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>}
            </div>

            <div className="flex shrink-0 flex-wrap items-center gap-3 border-t border-edge px-4 py-2">
                <p className="text-xs text-text-3" aria-live="polite">
                    {rowCount ? `Records ${currentStart + 1}–${currentStart + rowCount}` : '0 records'}
                    {preview.total_rows != null ? ` of ${preview.total_rows}` : ''}
                    {hasMore ? ' · More records available' : ''}
                </p>
                <button
                    type="button"
                    disabled={loading || previousStarts.length === 0}
                    onClick={() => {
                        const previous = previousStarts[previousStarts.length - 1];
                        if (previous !== undefined) {
                            setLoading(true);
                            setStartRow(previous);
                            setPreviousStarts((starts) => starts.slice(0, -1));
                        }
                    }}
                    className="min-h-11 rounded-lg border border-edge px-3 text-sm text-text-2 hover:bg-surface-2 disabled:opacity-40"
                >Previous records</button>
                <button
                    type="button"
                    disabled={loading || !hasMore || rowCount === 0}
                    onClick={() => {
                        setLoading(true);
                        setPreviousStarts((starts) => [...starts, currentStart]);
                        setStartRow(nextStart);
                    }}
                    className="min-h-11 rounded-lg border border-edge px-3 text-sm text-text-2 hover:bg-surface-2 disabled:opacity-40"
                >Next records</button>
                <form
                    className="flex min-w-0 flex-wrap items-center gap-2"
                    onSubmit={(event) => {
                        event.preventDefault();
                        const record = Number(jumpRecord);
                        if (!Number.isSafeInteger(record) || record < 1 || (preview.total_rows != null && record > preview.total_rows)) {
                            setError('Choose a record number within this table.');
                            return;
                        }
                        if (record - 1 === currentStart) {
                            if (error) {
                                setRetry((current) => current + 1);
                            }
                            return;
                        }
                        setLoading(true);
                        setPreviousStarts((starts) => [...starts, currentStart]);
                        setStartRow(record - 1);
                    }}
                >
                    <label htmlFor={recordInputId} className="text-xs text-text-3">Go to record</label>
                    <input
                        id={recordInputId}
                        type="number"
                        min={1}
                        max={preview.total_rows ?? undefined}
                        value={jumpRecord}
                        onChange={(event) => setJumpRecord(event.target.value)}
                        className="min-h-11 w-24 rounded-lg border border-edge-strong bg-surface-1 px-2 text-base text-text-1 sm:text-sm"
                    />
                    <button type="submit" disabled={loading || rowCount === 0} className="min-h-11 rounded-lg px-3 text-sm text-accent hover:bg-accent-soft disabled:opacity-40">Go</button>
                </form>
            </div>
            {(preview.columns_truncated || preview.cell_text_truncated) && (
                <p className="shrink-0 px-4 pb-2 text-xs text-text-3">Some preview columns or long cell text are shortened. Inspect a smaller cell range or download the original for full content.</p>
            )}
            {citationId ? (
                <CitedSourcePassage
                    citationId={citationId} docId={docId} location={location}
                    sourceLabel={metadata.file_name?.toLowerCase().endsWith('.csv') ? 'Cited CSV evidence' : 'Cited workbook evidence'}
                />
            ) : null}
        </div>
    );
}

/* -------------------------------------------------------------------------- */
/* Visio                                                                       */
/* -------------------------------------------------------------------------- */

function VisioViewer({ docId, location, onFail }: ViewerProps) {
    const [page, setPage] = useState(Math.max(1, Number.parseInt(location, 10) || 1));
    const [loading, setLoading] = useState(true);

    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex shrink-0 items-center gap-2 border-b border-edge px-4 py-2">
                <button
                    type="button"
                    onClick={() => {
                        setLoading(true);
                        setPage((current) => Math.max(1, current - 1));
                    }}
                    disabled={page <= 1}
                    aria-label="Previous page"
                    className="rounded-md p-1 text-text-3 hover:bg-surface-2 hover:text-text-1 disabled:opacity-40"
                >
                    <ChevronLeft size={15} />
                </button>
                <span className="text-xs text-text-3">Page {page}</span>
                <button
                    type="button"
                    onClick={() => {
                        setLoading(true);
                        setPage((current) => current + 1);
                    }}
                    aria-label="Next page"
                    className="rounded-md p-1 text-text-3 hover:bg-surface-2 hover:text-text-1"
                >
                    <ChevronRight size={15} />
                </button>
            </div>

            <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-4">
                {loading && <ViewerLoading label="Rendering the diagram…" />}
                <img
                    src={enhancedCitationVisioUrl(docId, page)}
                    alt={`Diagram page ${page}`}
                    onLoad={() => setLoading(false)}
                    onError={() => {
                        setLoading(false);
                        // Stepping past the last page is a normal outcome, so only the
                        // first page failing is treated as the viewer being unusable.
                        if (page === 1) {
                            onFail('The diagram could not be rendered.');
                        } else {
                            setPage((current) => Math.max(1, current - 1));
                        }
                    }}
                    className={clsx(
                        'max-h-full max-w-full rounded-xl object-contain',
                        loading && 'hidden',
                    )}
                />
            </div>
        </div>
    );
}

/* -------------------------------------------------------------------------- */
/* Shell                                                                       */
/* -------------------------------------------------------------------------- */

const VIEWER_LABELS: Record<EnhancedCitationType, string> = {
    pdf: 'Document',
    image: 'Image',
    video: 'Video',
    audio: 'Audio',
    tabular: 'Spreadsheet',
    visio: 'Diagram',
};

export function EnhancedCitationViewer({
    type,
    docId,
    location,
    locationLabel,
    metadata,
    onClose,
    onFallback,
    citationId,
}: {
    type: EnhancedCitationType;
    docId: string;
    location: string;
    locationLabel: string;
    metadata: EnhancedCitationMetadata;
    onClose: () => void;
    onFallback: (reason: string) => void;
    /** The citation being viewed; lets the image viewer show the cited passage. */
    citationId?: string;
}) {
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    // Stable so viewer effects do not re-run on every render of this shell.
    const handleFail = useCallback((reason: string) => onFallback(reason), [onFallback]);

    const viewerProps: ViewerProps = {
        docId,
        location,
        metadata,
        onFail: handleFail,
        citationId,
    };

    // Tabular has its own download endpoint; everything else uses the generic one.
    const downloadUrl =
        type === 'tabular'
            ? tabularWorkspaceDownloadUrl(docId)
            : type === 'visio'
              ? enhancedCitationVisioUrl(docId, 1, true)
              : workspaceDocumentDownloadUrl(docId);

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Cited source"
        >
            <div className="absolute inset-0 bg-black/50" aria-hidden="true" onClick={onClose} />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex h-[82vh] w-full max-w-5xl flex-col overflow-hidden"
            >
                <div className="flex shrink-0 items-start gap-3 border-b border-edge px-5 py-3">
                    <FileText size={17} className="mt-0.5 shrink-0 text-text-3" />
                    <div className="min-w-0 flex-1">
                        <h2 className="truncate text-sm font-semibold text-text-1">
                            {metadata.file_name || 'Cited source'}
                        </h2>
                        <p className="text-xs text-text-3">
                            {VIEWER_LABELS[type]}
                            {location ? type === 'tabular'
                                ? ` · ${/^\d+$/.test(location) ? `Evidence segment ${location}` : locationLabel === 'Sheet' ? `Sheet ${location}` : location}`
                                : ` · ${locationLabel} ${location}` : ''}
                        </p>
                    </div>

                    <a
                        href={downloadUrl}
                        download
                        title="Download the original file"
                        aria-label="Download the original file"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <Download size={16} />
                    </a>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close cited source"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={17} />
                    </button>
                </div>

                <div className="flex min-h-0 flex-1 flex-col">
                    {type === 'pdf' && <PdfViewer {...viewerProps} />}
                    {type === 'image' && <ImageViewer {...viewerProps} />}
                    {type === 'video' && <MediaViewer {...viewerProps} kind="video" />}
                    {type === 'audio' && <MediaViewer {...viewerProps} kind="audio" />}
                    {type === 'tabular' && <TabularViewer key={`${docId}:${location}`} {...viewerProps} />}
                    {type === 'visio' && <VisioViewer {...viewerProps} />}
                </div>
            </GlassPanel>
        </div>
    );
}
