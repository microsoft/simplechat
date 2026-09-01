// EnhancedCitationViewer.tsx
// Opens the cited source itself rather than only its extracted text.
//
// Which viewer applies is decided from the file extension, matching V1. Every failure path
// falls back to the plain text citation, because a citation that cannot render its source
// is still more useful as a readable passage than as a dead click.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
                src={`${objectUrl}#page=${subPage}`}
                className="min-h-0 w-full flex-1 border-0"
            />
        </div>
    );
}

/* -------------------------------------------------------------------------- */
/* Image                                                                       */
/* -------------------------------------------------------------------------- */

function ImageViewer({ docId, metadata, onFail }: ViewerProps) {
    const [loading, setLoading] = useState(true);

    return (
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

function TabularViewer({ docId, location, onFail }: ViewerProps) {
    const [preview, setPreview] = useState<TabularPreview | null>(null);
    const [sheet, setSheet] = useState<string | undefined>(
        // A sheet citation carries the sheet name where a page citation carries a number.
        Number.isNaN(Number.parseInt(location, 10)) ? location || undefined : undefined,
    );
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);

        void (async () => {
            try {
                const result = await fetchTabularPreview(docId, { sheetName: sheet });
                if (!cancelled) {
                    setPreview(result);
                }
            } catch (error) {
                if (!cancelled) {
                    onFail(
                        error instanceof Error
                            ? error.message
                            : 'Could not load the spreadsheet.',
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
        };
    }, [docId, sheet, onFail]);

    if (loading && !preview) {
        return <ViewerLoading label="Loading the spreadsheet…" />;
    }

    if (!preview) {
        return <ViewerError message="The spreadsheet could not be displayed." />;
    }

    const sheets = preview.sheet_names ?? [];

    return (
        <div className="flex min-h-0 flex-1 flex-col">
            {sheets.length > 1 && (
                <div className="flex shrink-0 flex-wrap gap-1 border-b border-edge px-4 py-2">
                    {sheets.map((name) => (
                        <button
                            key={name}
                            type="button"
                            onClick={() => setSheet(name)}
                            className={clsx(
                                'rounded-lg px-2 py-1 text-xs transition-colors',
                                (preview.selected_sheet ?? sheets[0]) === name
                                    ? 'bg-accent-soft text-accent'
                                    : 'text-text-2 hover:bg-surface-2',
                            )}
                        >
                            {name}
                        </button>
                    ))}
                </div>
            )}

            <div className="min-h-0 flex-1 overflow-auto p-4">
                <table className="w-full border-collapse text-sm">
                    <thead>
                        <tr>
                            {(preview.columns ?? []).map((column, index) => (
                                <th
                                    key={`${column}-${index}`}
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
                </table>
            </div>

            {preview.truncated && (
                <p className="shrink-0 border-t border-edge px-4 py-2 text-xs text-text-3">
                    Showing the first {preview.rows?.length ?? 0} rows. Download the file for
                    the rest.
                </p>
            )}
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
}: {
    type: EnhancedCitationType;
    docId: string;
    location: string;
    locationLabel: string;
    metadata: EnhancedCitationMetadata;
    onClose: () => void;
    onFallback: (reason: string) => void;
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
                            {location ? ` · ${locationLabel} ${location}` : ''}
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
                    {type === 'tabular' && <TabularViewer {...viewerProps} />}
                    {type === 'visio' && <VisioViewer {...viewerProps} />}
                </div>
            </GlassPanel>
        </div>
    );
}
