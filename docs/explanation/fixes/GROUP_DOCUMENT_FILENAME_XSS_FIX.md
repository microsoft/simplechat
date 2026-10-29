# Group Document Filename XSS Fix (v0.261.029)

Fixed in version: **0.261.029**

Related advisory: [GHSA-qwcw-r653-j8c6](https://github.com/microsoft/simplechat/security/advisories/GHSA-qwcw-r653-j8c6).
The application patch version is recorded in `application/single_app/config.py`.

## Issue

A stored group document filename could become executable JavaScript when an eligible group member clicked Share. The vulnerable controls appeared in ordinary list rows, document cards, and folder list rows. Folder cards reused the same affected card renderer.

The card renderer also inserted filenames and document titles into tooltip attributes without a safe attribute boundary. This allowed a separate event-handler injection path on hover, including for ordinary group Users who could not share documents.

The paths remained present in the inspected `v0.261.001`, `v0.261.027`, and `0.261.028` revisions. Earlier [sharing-modal hardening](v0.241.022/STORED_XSS_SHARE_ACTIVITY_AND_MASKING_FIX.md) protected content inside the modal but did not repair the controls that opened it.

## Root Cause

Share controls interpolated the stored filename into an inline `onclick` handler. HTML entity escaping was insufficient because the browser decoded the entities before compiling the JavaScript handler.

Card headings and filename subtitles used an HTML text escaper inside double-quoted `title` attributes. That escaper did not encode quotation marks, allowing data to escape the intended attribute.

## Changes

| File | Change |
|---|---|
| `application/single_app/templates/group_workspaces.html` | Removes all three filename-bearing inline Share handlers, binds each newly rendered control, and populates card titles/subtitles through DOM properties. |
| `application/single_app/static/js/workspace/group-documents-sharing.js` | Adds a shared event-binding helper that captures the original document ID and filename as data and passes them directly to the existing sharing modal. |
| `functional_tests/test_group_document_filename_xss.py` | Guards the rendering boundaries, all three binding locations, and the minimum implementation version. |
| `ui_tests/test_group_document_filename_xss_rendering.py` | Exercises actual rendered controls, tooltips, permissions, refreshes, and polling in an isolated browser. |
| `application/single_app/config.py` | Increments the application patch version from `0.261.028` to `0.261.029`. |

The Share links now contain static action markup rather than executable document data. Their event listeners prevent link navigation and invoke the existing modal with the unchanged filename. Card text uses `textContent`; tooltips use the DOM `title` property.

Bindings are installed when cards and ordinary rows are created and after folder table markup is inserted. Polling completion uses the same ordinary row renderer, so replacement rows receive the same safe behavior.

## Behavior and Impact

Original filenames remain unchanged in storage, API responses, visible text, tooltips, and sharing dialogs. No document migration or filename rewriting is required, and previously stored filenames receive the same protection as new uploads.

Existing Share permissions, owning-group restrictions, processing/error checks, group status restrictions, and share-count badges are preserved. The fix does not change CSP, introduce browser dependencies, or add settings or routes. The event-binding helper is served from the existing local sharing asset.

## Validation

Before the fix, four focused browser cases executed the injected marker: ordinary-list and folder-list Share clicks, and ordinary-card and folder-card hover. After the fix, all 74 browser scenarios pass:

- Share clicks in list, card, folder-list, and folder-card views preserve literal filenames containing quotes, HTML-like text, entities, backslashes, and Unicode.
- Card heading, subtitle, and document-title tooltips remain inert for ordinary Users at desktop and mobile widths.
- Owner, Admin, DocumentManager, and User roles retain their existing behavior, including receiving-group restrictions and active, upload-disabled, locked, inactive, processing, and error states.
- Refreshes and view changes select the correct document without duplicate handlers; polling completion binds the replacement row.
- Empty filenames retain their previous fallback behavior.

The existing sharing-modal functional regression also passes. That regression alone does not cover the launcher vulnerability because it checks the modal's rendering rather than clicking a filename-bearing launcher.

Run the focused coverage with:

```powershell
python -B -m pytest -q .\functional_tests\test_group_document_filename_xss.py .\ui_tests\test_group_document_filename_xss_rendering.py ".\functional_tests\test_stored_xss_share_activity_and_masking_fix.py::test_document_share_modals_use_safe_rendering_and_delegated_clicks"
node --check .\application\single_app\static\js\workspace\group-documents-sharing.js
```

### Scope and limitations

Browser coverage uses the real template rendering functions, access/processing checks, fetch/refresh/polling paths, local sharing asset, Bootstrap, and modal markup. Unrelated metadata, selection, and generated-artifact helpers are stubbed. Every request is intercepted; the suite does not upload live documents, require authentication, or provision Azure resources. This is isolated Chromium coverage, not an authenticated Azure deployment test.

The complete historical sharing/activity/masking script has separate pre-existing failures involving chat source expectations and an exact historical version assertion. Those unrelated checks were not changed by this fix.
