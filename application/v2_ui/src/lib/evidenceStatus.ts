// evidenceStatus.ts
// Read the server's per-answer evidence ledger, not the model's prose or citation count.

export type EvidenceState = 'complete' | 'partial' | 'missing' | 'unavailable' | 'pending' | 'unknown';

export interface EvidenceSource {
    name: string;
    state: EvidenceState;
    document_id?: string;
    evidence_count?: number;
}

export interface EvidenceStatus {
    version: 1;
    scope: 'returned_evidence';
    state: EvidenceState;
    sources: EvidenceSource[];
    suggestions: string[];
    source_count?: number;
}

export const EVIDENCE_LABELS: Record<EvidenceState, string> = {
    complete: 'Evidence available',
    partial: 'Partial document evidence',
    missing: 'No supporting document evidence returned',
    unavailable: 'Some sources could not be checked',
    pending: 'Evidence is still pending',
    unknown: 'Coverage is not recorded',
};

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isState(value: unknown): value is EvidenceState {
    return typeof value === 'string' && Object.hasOwn(EVIDENCE_LABELS, value);
}

export function readEvidenceStatus(value: unknown): EvidenceStatus | null {
    if (!isRecord(value) || value.version !== 1 || value.scope !== 'returned_evidence' ||
        !isState(value.state) || !Array.isArray(value.sources) || value.sources.length === 0 ||
        value.sources.length > 100 || !Array.isArray(value.suggestions) || value.suggestions.length > 3) return null;
    const sources: EvidenceSource[] = [];
    for (const source of value.sources) {
        if (!isRecord(source) || typeof source.name !== 'string' || !source.name.trim() ||
            source.name.length > 160 || !isState(source.state) ||
            source.document_id !== undefined && typeof source.document_id !== 'string' ||
            source.evidence_count !== undefined && (
                typeof source.evidence_count !== 'number' || !Number.isSafeInteger(source.evidence_count) ||
                source.evidence_count < 0
            )) return null;
        sources.push({
            name: source.name,
            state: source.state,
            ...(typeof source.document_id === 'string' ? { document_id: source.document_id } : {}),
            ...(typeof source.evidence_count === 'number' ? { evidence_count: source.evidence_count } : {}),
        });
    }
    if (value.state === 'missing' && sources.some((source) => source.state !== 'missing') ||
        value.state === 'complete' && sources.some((source) => source.state !== 'complete')) return null;
    const suggestions: string[] = [];
    for (const suggestion of value.suggestions) {
        if (typeof suggestion !== 'string' || suggestion.length > 240) return null;
        suggestions.push(suggestion);
    }
    if (value.source_count !== undefined && (
        typeof value.source_count !== 'number' || !Number.isSafeInteger(value.source_count) ||
        value.source_count < sources.length
    )) return null;
    return { version: 1, scope: 'returned_evidence', state: value.state, sources, suggestions,
        ...(typeof value.source_count === 'number' ? { source_count: value.source_count } : {}) };
}
