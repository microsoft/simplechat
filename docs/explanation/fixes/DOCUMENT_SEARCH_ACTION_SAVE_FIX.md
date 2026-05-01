# Document Search Action Save Fix

Fixed/Implemented in version: **0.241.024**

## Overview

Saving a document-search action could fail in the workspace modal with a raw HTML `404 Not Found` page rendered inside the error banner.

## Root Cause

- The workspace save flow performs an optional pre-save validation call to `/api/plugins/validate`.
- When that validation endpoint was unavailable in the running app instance, the shared client helper treated the returned HTML 404 page as a plain error string and injected it directly into the modal.
- The document-search action also needed explicit `document_search` schema aliases so both internal type names (`search` and `document_search`) resolve consistently during save and edit flows.

## Files Modified

- `application/single_app/static/js/plugin_common.js`
- `application/single_app/static/json/schemas/document_search.definition.json`
- `application/single_app/static/json/schemas/document_search_plugin.additional_settings.schema.json`
- `ui_tests/test_workspace_document_search_action_modal.py`
- `functional_tests/test_document_search_action_save_validation_fallback.py`

## Technical Details

1. Added a validation fallback in the shared plugin client helper so a missing `/api/plugins/validate` endpoint no longer blocks save.
2. Prevented raw HTML error pages from being surfaced directly in the modal by normalizing HTML API responses into concise messages.
3. Added `document_search` schema aliases so auth-type lookup and additional-settings resolution work even when the UI or persisted manifest uses `document_search` instead of `search`.
4. Extended the document-search modal UI test to verify save succeeds even when the validation endpoint returns 404.

## Validation

- Targeted functional regression test passes for the validation fallback contract.
- The document-search UI modal regression test covers the save path with a mocked 404 validation response.
- Existing document-search functional tests continue to pass.