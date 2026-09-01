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

    useEffect(() => {
        let cancelled = false;

        void (async () => {
            try {
                const result = await fetchCitation({
                    citation_id: citation.citationId,
                    document_id: citation.documentId || undefined,
                    page_number: citation.locationValue || citation.pageNumber || undefined,
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
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

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
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={17} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
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
                        <p className="text-[15px] leading-relaxed whitespace-pre-wrap text-text-1">
                            {data.cited_text}
                        </p>
                    )}

                    {!loading && !error && !data?.cited_text && (
                        <p className="text-sm text-text-3">
                            This citation has no stored passage to show.
                        </p>
                    )}
                </div>
            </GlassPanel>
        </div>
    );
}

export function CitationChip({ group }: { group: CitationGroup }) {
    const [active, setActive] = useState<ParsedCitation | null>(null);

    // Web citations point at a real URL, so they open directly rather than resolving a
    // stored passage that does not exist for them.
    if (group.kind === 'web') {
        return (
            <a
                href={group.fileName}
                target="_blank"
                rel="noopener noreferrer"
                title={group.fileName}
                className="mx-0.5 inline-flex max-w-[16rem] items-center gap-1 rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 align-baseline text-[11px] text-accent hover:bg-surface-3"
            >
                <ExternalLink size={10} className="shrink-0" />
                <span className="truncate">{group.fileName.replace(/^https?:\/\//, '')}</span>
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
        if (!enhancedEnabled || !citation.documentId) {
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
    }, [enhancedEnabled, citation.documentId, group.fileName]);

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
