# Deep Research Explicit Toggle Fix

Fixed/Implemented in version: **0.241.079**

## Issue Description

Web Search-only chat requests could display Deep Research progress such as "Planning Deep Research web searches" and "Reviewing source pages for supporting evidence" even when the user had not selected Deep Research.

## Root Cause Analysis

The legacy Deep Research default mode `auto_with_web_search` allowed the backend to enable Source Review whenever Web Search was active. Existing saved settings using that mode could make a normal Web Search request inspect source pages automatically.

## Version Implemented

- Application version updated in `application/single_app/config.py` to `0.241.079`.

## Technical Details

### Files Modified

- `application/single_app/functions_source_review.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/_deep_research_info.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `functional_tests/test_deep_research_explicit_toggle.py`
- `functional_tests/test_source_review_security.py`
- `ui_tests/test_admin_source_review_settings.py`

### Code Changes Summary

- Changed Deep Research default mode to `manual`.
- Normalized stale saved automatic modes back to `manual`.
- Removed automatic Deep Research enablement from both streaming and non-streaming chat paths.
- Updated Admin Settings and setup guide copy to state that Deep Research runs only when the user selects it.
- Added regression coverage for Web Search-only requests not enabling Deep Research.

### Testing Approach

- Functional test verifies Web Search does not auto-enable Deep Research.
- Functional test verifies chat routes no longer call the auto-enable helper.
- UI test expectations were updated for the manual-only activation control.

## Impact Analysis

Users can run plain Web Search without source-page inspection. Deep Research still works when explicitly selected and still respects the existing app-role, runtime, URL safety, page budget, and traversal controls.

## Validation

Run:

```bash
python functional_tests/test_deep_research_explicit_toggle.py
python functional_tests/test_source_review_security.py
python -m py_compile application/single_app/functions_source_review.py application/single_app/route_backend_chats.py functional_tests/test_deep_research_explicit_toggle.py
```