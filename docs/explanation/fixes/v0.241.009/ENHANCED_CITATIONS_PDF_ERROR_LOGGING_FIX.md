# Enhanced Citations PDF Error Logging Fix

Fixed/Implemented in version: **0.241.009**

## Issue Description

Enhanced citation PDF requests could fail with a 500 response at `/api/enhanced_citations/pdf` even when the cited document still existed and the user had access to it.

The failing response body showed `name 'get_document_blob_storage_info' is not defined`, and the backend console only emitted the request entry trace plus a generic helper call trace. The browser-side PDF modal also hid the backend JSON error because it relied on a direct iframe request to load the PDF.

## Root Cause Analysis

`get_blob_name()` in `application/single_app/route_enhanced_citations.py` called `get_document_blob_storage_info(raw_doc)` but the module only imported `get_document_metadata` from `functions_documents.py`.

That left the PDF and shared blob-serving code paths vulnerable to a `NameError` before the blob lookup completed.

The same route file also used `print(...)` in `serve_enhanced_citation_content()` and `serve_enhanced_citation_pdf_content()` instead of `log_event(...)`, so failures did not emit structured diagnostics with request and blob context.

On the browser side, `showPdfModal()` in `application/single_app/static/js/chat/chat-enhanced-citations.js` assigned the backend URL directly to the iframe. That meant the JSON error body from a failed fetch never became visible to the toast workflow.

## Technical Details

Files modified: `application/single_app/route_enhanced_citations.py`, `application/single_app/static/js/chat/chat-enhanced-citations.js`, `application/single_app/config.py`, `functional_tests/test_enhanced_citations_csp_fix.py`, `functional_tests/test_enhanced_citations_pdf_error_logging_fix.py`, `ui_tests/test_enhanced_citations_pdf_error_toast.py`

Code changes summary:

- Added the missing `get_document_blob_storage_info` import to `route_enhanced_citations.py` so enhanced citations can resolve stored blob metadata before falling back to legacy blob paths.
- Added tagged debug and error helpers around the enhanced citations blob-resolution and PDF-serving path using `log_event(...)`.
- Replaced the `print(...)`-based exception handling in the shared blob-serving helpers with structured logging that includes document, container, blob-name, and PDF page context.
- Updated `showPdfModal()` to fetch the PDF endpoint first, extract backend JSON error messages when present, and only then create a blob-backed iframe URL for successful PDF responses.
- Preserved the text-citation fallback path so failed PDF previews still have a readable fallback.
- Updated the existing CSP-focused regression and added new functional and UI regression coverage for the dependency fix and toast-based error reporting path.

Impact analysis:

- Enhanced citation PDFs now load without the missing-helper `NameError`.
- Backend failures now emit tagged diagnostics that are visible in local debug output and structured logging sinks.
- Users now see the backend PDF error message in the toast UI instead of only seeing a failed iframe GET in the browser console.

## Validation

Test coverage: `functional_tests/test_enhanced_citations_csp_fix.py`, `functional_tests/test_enhanced_citations_pdf_error_logging_fix.py`, `ui_tests/test_enhanced_citations_pdf_error_toast.py`

Test results:

- Validates that the enhanced citations route imports `get_document_blob_storage_info` and emits `[EnhancedCitations]` logging markers through `log_event`.
- Validates that the PDF modal now fetches first, reads `X-Sub-PDF-Page`, creates a blob-backed iframe URL, and preserves the text fallback path.
- Validates that a failing `/api/enhanced_citations/pdf` response surfaces the backend error message in a toast instead of showing the modal.

Before/after comparison:

- Before: `/api/enhanced_citations/pdf` could fail with `name 'get_document_blob_storage_info' is not defined`, the route used thin print-based exception logging, and the PDF modal hid the JSON error body behind a failed iframe request.
- After: The route imports the helper correctly, emits structured diagnostics through `log_event`, and `showPdfModal` exposes backend PDF errors through a toast while still falling back to text citations.

Related config.py version update: `VERSION = "0.241.009"`