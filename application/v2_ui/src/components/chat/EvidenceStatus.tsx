// EvidenceStatus.tsx
import { Info, TriangleAlert } from 'lucide-react';
import { clsx } from 'clsx';
import { EVIDENCE_LABELS, type EvidenceSource, type EvidenceStatus } from '../../lib/evidenceStatus';

export function EvidenceSourceBadge({ source }: { source: EvidenceSource }) {
    const Icon = source.state === 'missing' || source.state === 'partial' ? TriangleAlert : Info;
    return (
        <span className="inline-flex items-center gap-1 text-xs text-text-2">
            <Icon size={12} aria-hidden="true" className={source.state === 'missing' ? 'text-danger'
                : source.state === 'complete' || source.state === 'unknown' ? 'text-text-3' : 'text-warn'} />
            {EVIDENCE_LABELS[source.state]}
        </span>
    );
}

export function EvidenceStatusFooter({ status, analysisNotice, expanded, onOpen, controlsId }: {
    status: EvidenceStatus | null; expanded: boolean; onOpen: () => void; controlsId?: string;
    analysisNotice?: string | null;
}) {
    const state = status && status.state !== 'complete' && status.state !== 'unknown' ? status.state : null;
    const label = state ? EVIDENCE_LABELS[state] : analysisNotice;
    if (!label) return null;
    return (
        <div role="status" className="mt-2">
            <button type="button" aria-expanded={expanded} onClick={onOpen}
                aria-controls={controlsId}
                data-evidence-state={state ?? undefined}
                aria-label={`${label}. View source coverage`}
                className={clsx('inline-flex max-w-full items-center gap-1.5 rounded-lg px-2 py-1 text-left text-xs text-text-1 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
                    state === 'missing' ? 'bg-danger-soft' : 'bg-warn-soft')}>
                <TriangleAlert size={13} className={clsx('shrink-0', state === 'missing' ? 'text-danger' : 'text-warn')} aria-hidden="true" />
                <span>{label} <span className="underline underline-offset-2">View sources</span></span>
            </button>
        </div>
    );
}

export function EvidenceStatusDetails({ status }: { status: EvidenceStatus | null }) {
    if (!status) return null;
    return (
        <section aria-label="Evidence for this answer" className="space-y-2 py-2">
            <h4 className="text-xs font-medium text-text-2">Evidence for this answer</h4>
            <p className="text-xs text-text-3">These details describe returned evidence, not an exhaustive search of every document.</p>
            {status.source_count !== undefined && status.source_count > status.sources.length &&
                <p className="text-xs text-text-3">Showing {status.sources.length} of {status.source_count} source records.</p>}
            <ul className="divide-y divide-edge">
                {status.sources.map((source, index) => (
                    <li key={`${source.document_id ?? index}:${index}`} className="flex flex-wrap items-start justify-between gap-2 py-2 text-xs">
                        <span className="min-w-0 flex-1 break-words text-text-1">{source.name}</span>
                        <span className="flex flex-col items-end gap-0.5">
                            <EvidenceSourceBadge source={source} />
                            {source.evidence_count !== undefined && <span className="text-text-3">
                                {source.state === 'complete' && source.evidence_count === 0
                                    ? 'Inspection completed with no matching records'
                                    : `${source.evidence_count} evidence item${source.evidence_count === 1 ? '' : 's'} returned`}
                            </span>}
                        </span>
                    </li>
                ))}
            </ul>
            {status.suggestions.length > 0 && (
                <div className="space-y-1 text-xs text-text-2">
                    <p className="font-medium">What you can try next</p>
                    <ul className="list-disc space-y-1 pl-4">{status.suggestions.map((suggestion) => <li key={suggestion}>{suggestion}</li>)}</ul>
                </div>
            )}
        </section>
    );
}
