// documentProcessingStatus.ts
// Kept in parity with Python and classic through document_processing_status_cases.json.

const FAILURE = /^(?:(?:error|failed)(?:$|[\s:!]|\.(?:$|\s))|(?:processing|document processing|approval|content screening) failed(?:$|[\s:;!]|\.(?:$|\s))|video:\s*(?:blob upload|auth|upload|indexing) failed(?:$|[\s:!]|\.(?:$|\s)))/i;
const COMPLETE = /^(?:(?:ready|complete|completed|processed|finished)[.!]?$|processing complete(?:$|[.!]$|\s+[-(]))/i;

export function isDocumentProcessingFailure(status: unknown): boolean {
    return typeof status === 'string' && FAILURE.test(status.trim());
}

export function isDocumentProcessingComplete(status: unknown): boolean {
    return typeof status === 'string' && COMPLETE.test(status.trim());
}
