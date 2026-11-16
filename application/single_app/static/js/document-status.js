// document-status.js
// Kept in parity with Python and React through document_processing_status_cases.json.

window.DocumentStatus = (() => {
    const failure = /^(?:(?:error|failed)(?:$|[\s:!]|\.(?:$|\s))|(?:processing|document processing|approval|content screening) failed(?:$|[\s:;!]|\.(?:$|\s))|video:\s*(?:blob upload|auth|upload|indexing) failed(?:$|[\s:!]|\.(?:$|\s)))/i;
    const complete = /^(?:(?:ready|complete|completed|processed|finished)[.!]?$|processing complete(?:$|[.!]$|\s+[-(]))/i;

    return Object.freeze({
        isFailure(status) {
            return typeof status === "string" && failure.test(status.trim());
        },
        isComplete(status) {
            return typeof status === "string" && complete.test(status.trim());
        },
    });
})();
