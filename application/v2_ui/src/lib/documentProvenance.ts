// documentProvenance.ts
// Reading the origin summary that a document detail read carries.
//
// The server decides what a reader may learn about where a document came from
// (functions_document_provenance.resolve_origin_summary): a reader who may open the workflow
// or chat gets its name and a link, everyone else gets plain text that names nothing. This
// module only checks the shape, keeps links inside the app, and formats the run time in the
// reader's locale.

import type { DocumentOriginKind, DocumentOriginSummary } from './types';

const ORIGIN_KINDS: readonly string[] = ['workflow', 'chat'];
const MAX_LABEL_LENGTH = 300;
const MAX_TIMESTAMP_LENGTH = 64;

/**
 * The only places an origin link may open: a personal or group workflow in the workflows
 * section, or a conversation on the chat page. Any other value is shown as plain text.
 */
const SAFE_ORIGIN_HREFS = [
    /^\/workspace\/workflows\?workflow_id=[^&#\s]+(?:&run_id=[^&#\s]+)?$/,
    /^\/groups\/[^/?#\s]+\/workflows\?workflow_id=[^&#\s]+(?:&run_id=[^&#\s]+)?$/,
    /^\/chat\?conversationId=[^&#\s]+$/,
];
// Browsers resolve `.`/`..` segments, including percent-encoded dots, and read `\` as `/`.
const DOT_SEGMENT = /\/(?:\.|%2e){1,2}(?:[/?#]|$)/i;

export function isDocumentOriginKind(value: unknown): value is DocumentOriginKind {
    return typeof value === 'string' && ORIGIN_KINDS.includes(value);
}

export function isSafeOriginHref(value: unknown): value is string {
    return typeof value === 'string'
        && !value.includes('\\')
        && !DOT_SEGMENT.test(value)
        && SAFE_ORIGIN_HREFS.some((pattern) => pattern.test(value));
}

/** A well-formed summary with any unsafe link dropped, or null. */
export function readDocumentOriginSummary(value: unknown): DocumentOriginSummary | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return null;
    }
    const record = value as Record<string, unknown>;
    if (!isDocumentOriginKind(record.kind)) {
        return null;
    }
    const label = typeof record.label === 'string' ? record.label.trim() : '';
    if (!label || label.length > MAX_LABEL_LENGTH) {
        return null;
    }
    const summary: DocumentOriginSummary = { kind: record.kind, label };
    if (isSafeOriginHref(record.href)) {
        summary.href = record.href;
    }
    if (record.kind === 'workflow' && typeof record.run_started_at === 'string'
        && record.run_started_at.length <= MAX_TIMESTAMP_LENGTH) {
        summary.run_started_at = record.run_started_at;
    }
    return summary;
}

/** The plain text shown before the summary arrives, or when it cannot be read. */
export function originFallbackLabel(kind: DocumentOriginKind): string {
    return kind === 'workflow' ? 'Created by a workflow' : 'Created in a chat';
}

/** When the run started, in the reader's locale, or '' when it is not a readable time. */
export function formatOriginRunTime(value: string | undefined): string {
    if (!value) {
        return '';
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.valueOf()) ? '' : parsed.toLocaleString();
}

/** The full line the details pane shows: the label, plus the run time for a workflow run. */
export function originSummaryText(summary: DocumentOriginSummary): string {
    const runTime = summary.kind === 'workflow' ? formatOriginRunTime(summary.run_started_at) : '';
    return runTime ? `${summary.label} \u00b7 run ${runTime}` : summary.label;
}
