# TABULAR PREVIEW JSON SANITIZATION FIX

Fixed/Implemented in version: **0.240.030**

## Header Information

- Issue description: Some tabular enhanced-citation previews failed to open because the preview API returned raw `NaN` values that the browser rejected as invalid JSON.
- Root cause analysis: `get_enhanced_citation_tabular_preview()` returned `preview.values.tolist()` directly from pandas, allowing null-like workbook values and blank headers to serialize as bare `NaN` tokens.
- Version implemented: 0.240.030

## Technical Details

- Files modified: `application/single_app/route_enhanced_citations.py`, `application/single_app/config.py`, `functional_tests/test_tabular_preview_json_sanitization_fix.py`
- Code changes summary: Added preview sanitization helpers that convert tabular headers and cells into JSON-safe display strings before calling `jsonify()`.
- Testing approach: Added a focused functional regression test that executes the sanitizer helpers against `NaN`, `NaT`, blank headers, and timestamp values and verifies the preview route uses the sanitized payload.
- Impact analysis: Workbook citations with sparse cells or blank column headers now render in the tabular preview modal instead of falling back to the download-only error state.

## Validation

- Test results: Targeted functional regression test validates both value sanitization behavior and preview route integration.
- Before/after comparison: Before the fix, preview responses could contain invalid `NaN` JSON tokens; after the fix, the endpoint emits only JSON-safe strings for preview rows and headers.
- User experience improvements: Users can open affected CSV/XLSX citation previews reliably, even when the sheet contains missing values.