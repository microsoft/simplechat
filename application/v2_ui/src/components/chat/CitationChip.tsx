// CitationChip.tsx
// Inline citation chips and the panel that shows the cited text.
//
// Citations arrive as trailing markers in the answer text. Rendering them as compact
// chips keeps the prose readable while still making the source reachable in one click.

import { useCallback, useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { ExternalLink, FileText, Loader2, Sparkles, TriangleAlert, X } from 'lucide-react';
import { fetchCitation, fetchEnhancedCitationMetadata } from '../../lib/endpoints';
import {
    getEnhancedCitationType,
    type EnhancedCitationMetadata,
    type EnhancedCitationType,
} from '../../lib/enhancedCitations';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { EnhancedCitationViewer } from './EnhancedCitationViewer';
import { M365CitationChips } from './M365CitationChip';
import { useWebCitation, WebProviderBadge } from './WebCitationCards';
import { safeWebSourceUrl } from '../../lib/webCitations';
import { GlassPanel } from '../ui/primitives';
import type { CitationGroup, ParsedCitation } from '../../lib/citations';
import type { Citation } from '../../lib/types';

/** How long to wait for the per-document gate before taking the permissive path. */
const METADATA_TIMEOUT_MS = 6000;

function CitationDetail({
    group,
    citation,
    onClose,
    notice,
}: {
    group: CitationGroup;
    citation: ParsedCitation;
    onClose: () => void;
    /** Explains why the source viewer was not used, when it was attempted and failed. */
    notice?: string | null;
}) {
    const [data, setData] = useState<Citation | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [preview, setPreview] = useState(false);

    useEffect(() => {
        let cancelled = false;

        void (async () => {
            try {
                const result = await fetchCitation({
                    citation_id: citation.citationId,
                    document_id: citation.documentId || undefined,
                    page_number: citation.locationValue || citation.pageNumber || undefined,
                    native_evidence: citation.nativeEvidence,
                    conversation_id: citation.conversationId,
                });
                if (!cancelled) {
                    setData(result);
                }
            } catch (fetchError) {
                if (!cancelled) {
                    setError(
                        fetchError instanceof Error
                            ? fetchError.message
                            : 'Could not load the cited text.',
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
    }, [citation]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                if (preview) setPreview(false);
                else onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose, preview]);

    const wordAnnotation = data?.evidence_kind === 'native_word_annotation'
        || ['docx', 'docm', 'dotx'].includes(data?.native_coverage?.format ?? '');

    if (preview) return <EnhancedCitationViewer
        type="tabular" docId={citation.documentId} location={data?.native_annotation?.sheet || ''}
        locationLabel="Sheet" metadata={{ document_id: citation.documentId, file_name: data?.file_name || group.fileName }}
        onClose={() => setPreview(false)} onFallback={() => setPreview(false)}
    />;

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Citation"
        >
            <div className="absolute inset-0 bg-black/40" aria-hidden="true" onClick={onClose} />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex max-h-[70vh] w-full max-w-2xl flex-col"
            >
                <div className="flex shrink-0 items-start gap-3 border-b border-edge px-5 py-3.5">
                    <FileText size={17} className="mt-0.5 shrink-0 text-text-3" />
                    <div className="min-w-0 flex-1">
                        <h2 className="truncate text-sm font-semibold text-text-1">
                            {data?.file_name || group.fileName}
                        </h2>
                        <p className="text-xs text-text-3">
                            {group.locationLabel} {citation.locationValue || citation.pageNumber}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close citation"
                        autoFocus
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={17} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                    {data?.native_annotation && <section aria-label={wordAnnotation ? 'Native Word comment' : 'Native workbook annotation'} className="mb-4 space-y-2 text-sm">
                        <h3 className="font-semibold text-text-1">
                            {wordAnnotation ? 'Word review comment' : data.native_annotation.kind === 'note' ? 'Workbook note'
                                : data.native_annotation.parent_id ? 'Threaded comment reply' : 'Threaded comment'}
                        </h3>
                        <p>Author: {data.native_annotation.author || 'Unavailable'}</p>
                        {wordAnnotation
                            ? <>
                                <p className="break-words">Anchored text: {data.native_annotation.anchor_text || 'Unavailable'}</p>
                                <p>Anchor coverage: {data.native_annotation.anchor_complete ? 'Complete' : 'Bounded or unavailable'}</p>
                            </>
                            : <p>Worksheet / cell: {data.native_annotation.sheet || 'Unavailable'} / {data.native_annotation.cell || 'Unavailable'}</p>}
                        <p>Date: {data.native_annotation.date || 'Unavailable'}</p>
                        {data.native_annotation.parent_id && <p>Reply to: {data.native_annotation.parent_id}</p>}
                        <p>Resolved: {wordAnnotation
                            ? data.native_annotation.resolution_available && typeof data.native_annotation.done === 'boolean'
                                ? data.native_annotation.done ? 'Yes' : 'No' : 'Unavailable'
                            : typeof data.native_annotation.resolved === 'boolean'
                                ? data.native_annotation.resolved ? 'Yes' : 'No' : 'Unavailable'}</p>
                        {!wordAnnotation && <p>Saved cell value: {data.native_annotation.cell_value_status === 'blank' ? 'Blank'
                            : data.native_annotation.cell_value == null ? 'Unavailable (not recalculated)'
                            : JSON.stringify(data.native_annotation.cell_value)}</p>}
                        <h3 className="pt-2 font-semibold text-text-1">Reviewer text</h3>
                    </section>}
                    {data?.native_coverage && <section aria-label="Native annotation coverage" className="mb-4 space-y-2 text-sm">
                        <h3 className="font-semibold text-text-1">Native annotation inventory</h3>
                        <p>{data.native_coverage.returned_records ?? 'Unknown'} of {data.native_coverage.total_records ?? 'unknown'} records retained.</p>
                        <p>{data.native_coverage.partial || !data.native_coverage.inventory_complete
                            ? 'Partial inventory; remaining annotations were not inspected.' : 'The saved annotation inventory was inspected completely.'}</p>
                        <p>This is inventory coverage, not a cited {wordAnnotation ? 'document passage' : 'worksheet cell'} or reviewer comment.</p>
                    </section>}
                    {notice && (
                        <p className="mb-3 flex items-start gap-2 rounded-xl border border-edge bg-warn-soft px-3 py-2 text-xs text-warn">
                            <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                            <span>
                                The original file could not be shown, so the cited passage is
                                displayed instead. {notice}
                            </span>
                        </p>
                    )}

                    {loading && (
                        <p className="flex items-center gap-2 text-sm text-text-3">
                            <Loader2 size={15} className="animate-spin" />
                            Loading the cited passage…
                        </p>
                    )}

                    {error && (
                        <p className="flex items-start gap-2 text-sm text-danger">
                            <TriangleAlert size={16} className="mt-0.5 shrink-0" />
                            {error}
                        </p>
                    )}

                    {data?.cited_text && (
                        <p className="break-words text-[15px] leading-relaxed whitespace-pre-wrap text-text-1">
                            {data.cited_text}
                        </p>
                    )}

                    {wordAnnotation && data?.native_annotation?.replies && data.native_annotation.replies.length > 0 && (
                        <section aria-label="Word comment replies" className="mt-4 space-y-3 text-sm">
                            <h3 className="font-semibold text-text-1">Replies</h3>
                            {data.native_annotation.replies.map((reply) => (
                                <div key={reply.id} className="space-y-1">
                                    <p>Author: {reply.author || 'Unavailable'}</p>
                                    <p>Date: {reply.date || 'Unavailable'}</p>
                                    <p>Resolved: {reply.resolution_available && typeof reply.done === 'boolean'
                                        ? reply.done ? 'Yes' : 'No' : 'Unavailable'}</p>
                                    <p className="break-words whitespace-pre-wrap">{reply.text || 'No stored reply text.'}</p>
                                </div>
                            ))}
                        </section>
                    )}

                    {!loading && !error && !data?.cited_text && (
                        <p className="text-sm text-text-3">
                            This citation has no stored passage to show.
                        </p>
                    )}
                    {!loading && !error && citation.nativeEvidence && !wordAnnotation && <button type="button"
                        className="mt-4 rounded-lg border border-edge px-3 py-2 text-sm text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                        onClick={() => setPreview(true)}>Open workbook preview (separate from annotation evidence)</button>}
                </div>
            </GlassPanel>
        </div>
    );
}

export function CitationChip({ group }: { group: CitationGroup }) {
    const [active, setActive] = useState<ParsedCitation | null>(null);
    const webCitation = useWebCitation(group.fileName);

    // A Microsoft 365 email, event or file resolves against the message's own records and
    // opens where it lives; it has no workspace passage to look up.
    if (group.kind === 'm365') {
        return <M365CitationChips group={group} />;
    }

    // Web citations point at a real URL, so they open directly rather than resolving a
    // stored passage that does not exist for them.
    if (group.kind === 'web') {
        const url = safeWebSourceUrl(group.fileName);
        if (!url) return <span className="text-xs text-text-3">Source unavailable</span>;
        return (
            <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                title={group.fileName}
                className="mx-0.5 inline-flex max-w-[16rem] items-center gap-1 rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 align-baseline text-[11px] text-accent hover:bg-surface-3"
            >
                <ExternalLink size={10} className="shrink-0" />
                <span className="truncate">{webCitation?.title || group.fileName.replace(/^https?:\/\//, '')}</span>
                {webCitation && <WebProviderBadge citation={webCitation} />}
            </a>
        );
    }

    const icon =
        group.kind === 'agent' ? (
            <Sparkles size={10} className="shrink-0" />
        ) : (
            <FileText size={10} className="shrink-0" />
        );

    return (
        <>
            <span className="mx-0.5 inline-flex flex-wrap items-center gap-0.5 align-baseline">
                {group.citations.map((citation) => (
                    <button
                        key={citation.citationId}
                        type="button"
                        onClick={() => setActive(citation)}
                        title={`${group.fileName} — ${group.locationLabel} ${
                            citation.locationValue || citation.pageNumber
                        }`}
                        className={clsx(
                            'inline-flex max-w-[14rem] items-center gap-1 rounded-full border border-edge',
                            'bg-surface-2 px-1.5 py-0.5 text-[11px] text-accent transition-colors hover:bg-surface-3',
                        )}
                    >
                        {icon}
                        <span className="truncate">{group.fileName}</span>
                        {(citation.locationValue || citation.pageNumber) && (
                            <span className="shrink-0 opacity-70">
                                {citation.locationValue || citation.pageNumber}
                            </span>
                        )}
                    </button>
                ))}
            </span>

            {active && (
                <CitationTarget
                    group={group}
                    citation={active}
                    onClose={() => setActive(null)}
                />
            )}
        </>
    );
}

/**
 * Decides whether a citation opens its source or its extracted text.
 *
 * Mirrors the V1 decision in chat-citations.js: enhanced rendering is attempted whenever
 * it is globally enabled and the document has not explicitly opted out. Missing metadata
 * is deliberately NOT treated as a refusal — V1 attempts anyway and relies on the failure
 * path, which keeps citations working for documents whose metadata cannot be resolved.
 *
 * Any failure at any stage falls through to the text passage.
 */
function CitationTarget({
    group,
    citation,
    onClose,
}: {
    group: CitationGroup;
    citation: ParsedCitation;
    onClose: () => void;
}) {
    const enhancedEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_enhanced_citations),
    );

    const [resolving, setResolving] = useState(enhancedEnabled);
    const [enhanced, setEnhanced] = useState<{
        type: EnhancedCitationType;
        metadata: EnhancedCitationMetadata;
    } | null>(null);
    const [fallbackReason, setFallbackReason] = useState<string | null>(null);

    useEffect(() => {
        if (!enhancedEnabled || !citation.documentId || citation.nativeEvidence || citation.nativeUnavailable) {
            setResolving(false);
            return;
        }

        let cancelled = false;

        void (async () => {
            // A hanging metadata lookup must not leave the click dead. On timeout we take
            // the permissive path — the same one taken when metadata is missing — and let
            // the viewer's own error handling fall back if the source cannot be loaded.
            const metadata = await Promise.race([
                fetchEnhancedCitationMetadata(citation.documentId),
                new Promise<null>((resolve) => {
                    window.setTimeout(() => resolve(null), METADATA_TIMEOUT_MS);
                }),
            ]);

            if (cancelled) {
                return;
            }

            // Only an explicit false is a refusal.
            if (metadata?.enhanced_citations === false) {
                setResolving(false);
                return;
            }

            const type = getEnhancedCitationType(metadata?.file_name || group.fileName);
            if (type) {
                setEnhanced({ type, metadata: metadata ?? { document_id: citation.documentId } });
            }
            setResolving(false);
        })();

        return () => {
            cancelled = true;
        };
    }, [enhancedEnabled, citation.documentId, citation.nativeEvidence, citation.nativeUnavailable, group.fileName]);

    const onFallback = useCallback((reason: string) => {
        // Surfaced rather than silent: the user asked to see the source, and should be
        // told they are getting the passage instead.
        setFallbackReason(reason);
        setEnhanced(null);
    }, []);

    if (resolving) {
        // A brief but visible shell, so the click always produces something.
        return (
            <div
                className="fixed inset-0 z-50 flex items-center justify-center p-4"
                role="dialog"
                aria-modal="true"
                aria-label="Citation"
            >
                <div
                    className="absolute inset-0 bg-black/40"
                    aria-hidden="true"
                    onClick={onClose}
                />
                <GlassPanel
                    elevation="modal"
                    edge
                    className="relative flex w-full max-w-2xl items-center gap-2 px-5 py-4"
                >
                    <Loader2 size={15} className="animate-spin text-text-3" />
                    <span className="text-sm text-text-3">Opening {group.fileName}…</span>
                </GlassPanel>
            </div>
        );
    }

    if (enhanced) {
        return (
            <EnhancedCitationViewer
                type={enhanced.type}
                docId={citation.documentId}
                location={citation.locationValue || citation.pageNumber}
                locationLabel={group.locationLabel}
                metadata={enhanced.metadata}
                onClose={onClose}
                onFallback={onFallback}
                citationId={citation.citationId}
            />
        );
    }

    return (
        <CitationDetail
            group={group}
            citation={citation}
            onClose={onClose}
            notice={fallbackReason}
        />
    );
}
