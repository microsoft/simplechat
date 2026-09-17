// AnalysisResult.tsx
// Lazy, complete-record pages supporting the readable answer above them.

import { useCallback, useEffect, useState } from 'react';
import { fetchAnalysisEvidence, fetchAnalysisRecords } from '../../lib/endpoints';
import {
    analysisNotices,
    analysisUnavailableMessage,
    analysisValidationNotice,
    analysisValue,
    isAnalysisUnavailable,
    sameAnalysis,
} from '../../lib/savedAnalysis';
import type {
    SavedAnalysisDescriptor,
    SavedAnalysisEvidence,
    SavedAnalysisPage,
    SavedAnalysisRecord,
} from '../../lib/types';
import { useChatStore } from '../../stores/chatStore';
import { GlassButton } from '../ui/primitives';

function Evidence({
    descriptor,
    record,
    onUnavailable,
}: {
    descriptor: SavedAnalysisDescriptor;
    record: SavedAnalysisRecord;
    onUnavailable: (message: string) => void;
}) {
    const [open, setOpen] = useState(false);
    const [evidence, setEvidence] = useState<SavedAnalysisEvidence[] | null>(null);
    const [error, setError] = useState('');
    const [retry, setRetry] = useState(0);

    useEffect(() => {
        if (!open) {
            return;
        }
        const controller = new AbortController();
        setEvidence(null);
        setError('');
        void fetchAnalysisEvidence(descriptor, record.record_id, controller.signal)
            .then((items) => {
                if (!controller.signal.aborted) {
                    setEvidence(items);
                }
            })
            .catch((failure: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }
                if (isAnalysisUnavailable(failure)) {
                    onUnavailable(analysisUnavailableMessage(failure.status));
                } else {
                    setError('Could not load saved evidence. Try again.');
                }
            });
        return () => controller.abort();
    }, [open, descriptor, record.record_id, onUnavailable, retry]);

    if (!record.evidence_refs.length) {
        return <p className="mt-2 text-xs text-text-3">No supporting passage saved for this finding.</p>;
    }
    return (
        <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)} className="mt-2">
            <summary className="cursor-pointer text-xs font-medium text-text-2">
                Evidence for finding {record.record_id}
            </summary>
            {open && (
                <div className="mt-2 text-xs text-text-2">
                    <p role="status" aria-live="polite">
                        {error || (evidence === null ? 'Loading saved evidence…' :
                            evidence.length ? `${evidence.length} saved passage(s).` : 'No supporting passages are available.')}
                    </p>
                    {error && <GlassButton size="sm" onClick={() => setRetry((value) => value + 1)}>Retry evidence</GlassButton>}
                    {evidence?.map((item) => (
                        <figure key={item.evidence_id} className="my-2 border-l-2 border-edge pl-3">
                            <figcaption className="mb-1 font-medium break-words">
                                {item.file_name || item.document_id}
                                {item.page_number != null ? ` · page ${item.page_number}` :
                                    item.start_page != null ? ` · pages ${item.start_page}${item.end_page != null ? `–${item.end_page}` : ''}` : ''}
                                {item.chunk_sequence != null ? ` · chunk ${item.chunk_sequence}` :
                                    item.chunk_id ? ` · chunk ${item.chunk_id}` : ''}
                            </figcaption>
                            <blockquote className="whitespace-pre-wrap break-words">
                                {typeof item.quote === 'string' ? item.quote :
                                    typeof item.text === 'string' ? item.text : 'No passage text was saved.'}
                            </blockquote>
                        </figure>
                    ))}
                </div>
            )}
        </details>
    );
}

export function AnalysisResult({
    descriptor,
    onUnavailable,
}: {
    descriptor: SavedAnalysisDescriptor;
    onUnavailable: () => void;
}) {
    const [open, setOpen] = useState(false);
    const [offset, setOffset] = useState(0);
    const [previousOffsets, setPreviousOffsets] = useState<number[]>([]);
    const [page, setPage] = useState<SavedAnalysisPage | null>(null);
    const [error, setError] = useState('');
    const [unavailable, setUnavailable] = useState('');
    const [retry, setRetry] = useState(0);
    const activeConversationId = useChatStore((state) => state.activeConversationId);
    const selectAnalysisResult = useChatStore((state) => state.selectAnalysisResult);
    const belongsHere = descriptor.conversation_id === activeConversationId;
    const blocked = descriptor.available === false || !belongsHere || Boolean(unavailable);

    const reportUnavailable = useCallback((message: string) => {
        setUnavailable(message);
        setPage(null);
        onUnavailable();
        const store = useChatStore.getState();
        if (sameAnalysis(store.analysisResultContext, descriptor)) {
            store.clearAnalysisResultContext();
        }
    }, [descriptor, onUnavailable]);

    useEffect(() => {
        if (!open || blocked) {
            return;
        }
        const controller = new AbortController();
        setPage(null);
        setError('');
        void fetchAnalysisRecords(descriptor, offset, controller.signal)
            .then((result) => {
                if (!controller.signal.aborted && useChatStore.getState().activeConversationId === descriptor.conversation_id) {
                    setPage(result);
                }
            })
            .catch((failure: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }
                if (isAnalysisUnavailable(failure)) {
                    reportUnavailable(analysisUnavailableMessage(failure.status));
                } else {
                    setError('Could not load saved findings. Try again.');
                }
            });
        return () => controller.abort();
    }, [descriptor, offset, open, blocked, retry, reportUnavailable]);

    const displayed = page?.records.length ?? 0;
    const displayedSources = new Set(page?.records.map((record) => record.document_id).filter(Boolean)).size;
    const status = page?.validation.status ?? descriptor.validation_status;
    const notices = page ? [...analysisNotices(page.validation.limitations), ...analysisNotices(page.validation.issues)] : [];

    return (
        <section aria-label="Saved analysis" className="mt-3 min-w-0 rounded-xl border border-edge p-3">
            <p className="text-sm font-medium text-text-1">Saved analysis</p>
            {blocked ? (
                <p role="status" aria-live="polite" className="mt-1 text-sm text-text-2">
                    {unavailable || analysisUnavailableMessage()}
                </p>
            ) : (
                <>
                    <p role="status" aria-live="polite" className="mt-1 text-xs text-text-3">
                        {open && !page && !error ? 'Loading saved findings… ' : ''}
                        {error || (open && page
                            ? `Showing ${displayed ? page.offset + 1 : 0}–${page.offset + displayed} of ${page.total_records} records · ${displayedSources} of ${page.source_count} sources on this page.`
                            : `0 of ${descriptor.record_count} records displayed · ${descriptor.source_count} sources in the saved analysis.`)}
                    </p>
                    <p className="mt-1 text-xs text-text-2">{analysisValidationNotice(status)}</p>
                    <GlassButton size="sm" className="mt-2" onClick={() => {
                        selectAnalysisResult(descriptor);
                        document.getElementById('composer-input')?.focus();
                    }}>
                        Ask about this analysis
                    </GlassButton>
                    <a
                        className="ml-3 text-xs text-text-3 underline underline-offset-2"
                        href={`/api/analysis_results?${new URLSearchParams({
                            conversation_id: descriptor.conversation_id,
                            message_id: descriptor.message_id,
                            result_sha256: descriptor.result_sha256,
                            representation: 'diagnostics',
                        })}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label="View diagnostics as JSON (opens a new tab)"
                    >
                        View diagnostics (JSON)
                    </a>
                    <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)} className="mt-2">
                        <summary className="cursor-pointer text-sm font-medium text-text-2">
                            Findings and limitations
                        </summary>
                        {open && (
                            <div className="mt-2 min-w-0">
                                {error && <GlassButton size="sm" onClick={() => setRetry((value) => value + 1)}>Retry findings</GlassButton>}
                                {notices.length > 0 && (
                                    <div className="mb-3 rounded-lg bg-surface-2 p-2 text-xs text-text-2">
                                        <h3 className="font-medium">Limitations and validation issues</h3>
                                        <ul className="mt-1 list-disc space-y-1 pl-4">
                                            {notices.map((notice, index) => <li key={index} className="break-words">{notice}</li>)}
                                        </ul>
                                    </div>
                                )}
                                {page?.records.map((record, index) => (
                                    <article key={record.record_id} className="min-w-0 border-t border-edge py-3">
                                        <h3 className="text-sm font-medium text-text-1">Finding {page.offset + index + 1}</h3>
                                        <p className="mt-1 text-xs text-text-3 break-words">
                                            {record.source.file_name || record.document_id} · {record.record_id}
                                        </p>
                                        <dl className="mt-2 space-y-2 text-sm">
                                            {Object.entries(record.values).map(([field, value]) => (
                                                <div key={field}>
                                                    <dt className="text-xs font-medium text-text-3 break-words">{field.replace(/_/g, ' ')}</dt>
                                                    <dd className="whitespace-pre-wrap break-words text-text-2">{analysisValue(value)}</dd>
                                                </div>
                                            ))}
                                        </dl>
                                        <Evidence descriptor={descriptor} record={record} onUnavailable={reportUnavailable} />
                                    </article>
                                ))}
                                {page && page.total_records === 0 && <p className="text-sm text-text-2">No accepted findings were saved.</p>}
                                <nav aria-label="Findings pages" className="mt-2 flex flex-wrap gap-2">
                                    <GlassButton size="sm" disabled={!page || previousOffsets.length === 0} onClick={() => {
                                        setOffset(previousOffsets[previousOffsets.length - 1]);
                                        setPreviousOffsets((values) => values.slice(0, -1));
                                    }}>Previous findings</GlassButton>
                                    <GlassButton size="sm" disabled={!page || page.next_offset === null} onClick={() => {
                                        if (page?.next_offset != null) {
                                            setPreviousOffsets((values) => [...values, offset]);
                                            setOffset(page.next_offset);
                                        }
                                    }}>Next findings</GlassButton>
                                </nav>
                            </div>
                        )}
                    </details>
                </>
            )}
        </section>
    );
}
