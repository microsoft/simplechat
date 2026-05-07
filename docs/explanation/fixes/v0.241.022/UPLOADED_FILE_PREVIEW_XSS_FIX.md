# UPLOADED_FILE_PREVIEW_XSS_FIX.md

# Uploaded File Preview XSS Fix

Fixed/Implemented in version: **0.241.022**

## Issue Description

Uploaded file preview content in the chat modal rendered attacker-controlled file bodies through dynamic HTML sinks. Plain-text previews used `innerHTML` with a `<pre>` wrapper, modern CSV previews assembled table markup as HTML strings, and legacy table payloads were inserted directly into the modal body.

## Root Cause Analysis

- `application/single_app/static/js/chat/chat-input-actions.js` used `fileContentElement.innerHTML` for both plain-text and tabular preview bodies.
- CSV preview rendering escaped cell text but still concatenated untrusted content into HTML strings before injecting it into the DOM.
- Legacy HTML table payloads from older stored previews were treated as trusted markup instead of untrusted file content.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-input-actions.js`
- `functional_tests/test_uploaded_file_preview_xss_fix.py`
- `ui_tests/test_uploaded_file_preview_escaping.py`
- `application/single_app/config.py`

### Code Changes Summary

- Replaced preview-body `innerHTML` updates with DOM construction and `textContent` assignments.
- Rebuilt CSV previews with DOM-created table elements so headers and cells stay inert even when they contain attacker-controlled strings.
- Tightened legacy detection to full-table HTML payloads only.
- Legacy HTML table payloads now render as inert preformatted text instead of executable markup.
- Replaced the blob download button injection with a DOM-created anchor element.

### Testing Approach

- `functional_tests/test_uploaded_file_preview_xss_fix.py` verifies the preview renderer no longer uses the removed file-content HTML sinks and that the fix documentation and version stay in sync.
- `ui_tests/test_uploaded_file_preview_escaping.py` exercises plain-text, CSV, and legacy table preview flows in the browser and asserts no injected `img`, `svg`, or `script` nodes appear.

## Impact Analysis

- Plain-text uploads still display with preserved whitespace in the modal.
- CSV-backed previews still render as visible tables for current uploads.
- Older HTML-backed table previews remain readable, but they no longer render as live HTML.

## Validation

### Before

- Opening an uploaded file preview could inject stored file content into the modal DOM.
- A CSV value beginning with HTML-like text could be misclassified and routed toward the unsafe HTML path.

### After

- Uploaded file preview bodies render through safe DOM APIs.
- CSV cells remain visible as text, including cells that begin with HTML-like payloads.
- Legacy HTML table payloads now render as inert preformatted text.