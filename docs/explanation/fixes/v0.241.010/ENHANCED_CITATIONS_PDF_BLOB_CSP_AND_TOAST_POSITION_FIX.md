# Enhanced Citations PDF Blob CSP and Toast Position Fix

Fixed/Implemented in version: **0.241.010**

## Issue Description

After moving enhanced citation PDF previews to a fetch-first blob-backed iframe flow, successful PDF responses still failed to render in the browser because the page-level Content Security Policy blocked `blob:` frame sources.

At the same time, chat error toasts could render underneath the floating Chat Tutorial launcher because the chat page defined a top-right toast container in the same region as the tutorial button.

## Root Cause Analysis

The page CSP in `application/single_app/config.py` allowed `blob:` for images and media, but it did not explicitly allow `blob:` in `frame-src`. That caused the browser to fall back to `default-src 'self'` for the iframe navigation and reject the blob URL created by `showPdfModal()`.

The chat template also used a duplicate `toast-container` ID while positioning its local chat toasts in the same top-right corner as the tutorial launcher. That made the toast target ambiguous and left no layout rule ensuring the toast stack stayed below the floating tutorial entry point.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/templates/chats.html`, `application/single_app/static/css/chats.css`, `application/single_app/static/js/chat/chat-toast.js`, `functional_tests/test_enhanced_citations_csp_fix.py`, `functional_tests/test_enhanced_citations_pdf_error_logging_fix.py`, `ui_tests/test_enhanced_citations_pdf_error_toast.py`

Code changes summary:

- Added `frame-src 'self' blob:` to the app-level Content Security Policy so blob-backed PDF iframes can render under the existing fetch-first enhanced citations workflow.
- Replaced the chat page's duplicate `toast-container` ID with a dedicated `chat-toast-container` that declares anchor metadata for the tutorial launcher.
- Updated `chat-toast.js` to prefer page-specific toast containers marked as preferred, fall back to the global base container elsewhere, and dynamically reposition anchored containers below their configured launch element.
- Added a default chat toast offset and preserved the existing toast rendering behavior for non-chat pages.
- Updated static and UI regressions to verify the blob CSP allowance, the anchored chat toast container wiring, and the on-screen toast position relative to the tutorial button.

Impact analysis:

- Enhanced citation PDFs now render successfully from blob URLs without regressing the fetch-first error handling path.
- Chat toasts now stack beneath the tutorial launcher instead of appearing partially underneath it.
- Other pages that rely on the shared toast helper continue to fall back to the global base toast container.

## Validation

Test coverage: `functional_tests/test_enhanced_citations_csp_fix.py`, `functional_tests/test_enhanced_citations_pdf_error_logging_fix.py`, `ui_tests/test_enhanced_citations_pdf_error_toast.py`

Test results:

- Validates that the page CSP includes `frame-src 'self' blob:` alongside the existing same-origin frame-ancestor rule.
- Validates that chats use a dedicated anchored toast container and that the shared toast helper prefers and repositions it.
- Validates that a failed enhanced citations PDF request still surfaces the backend error toast and that the toast container stays below the Chat Tutorial launcher.

Before/after comparison:

- Before: Blob-backed enhanced citations PDFs fetched successfully but the browser blocked the blob iframe render under page CSP, and chat toasts could overlap the floating tutorial button.
- After: Blob-backed enhanced citations PDFs render under the page CSP, and chat toasts consistently appear below the tutorial launcher.

Related config.py version update: `VERSION = "0.241.010"`