# Chat Inline Chart Export PNG Fix

Fixed/Implemented in version: **0.241.136**

## Issue Description

Inline `simplechart` blocks rendered correctly inside chat, but per-message export paths could preserve the raw chart code instead of exporting a chart image. This affected exports to Word, PowerPoint, and email drafts when the model produced a YAML-style chart block rather than strict JSON.

## Root Cause Analysis

The browser chart renderer accepted both JSON and loose YAML-style `simplechart` payloads. The server export helper only parsed strict JSON before rendering charts to PNG data URIs. When parsing failed, export output kept the original fenced code block.

## Technical Details

### Files Modified

- `application/single_app/functions_chart_export.py`
- `application/single_app/config.py`
- `functional_tests/test_conversation_export_inline_chart_images.py`

### Code Changes Summary

- Added server-side loose `simplechart` parsing for model-authored YAML-style chart blocks.
- Normalized chart specs before rendering so JSON and YAML-style payloads follow the same export path.
- Preserved existing PNG data URI generation used by Markdown/PDF, Word, PowerPoint, and email draft exports.
- Bumped `config.py` version to `0.241.136`.

### Testing Approach

- Extended functional export tests to validate YAML-style charts are converted to PNG data URIs.
- Added Word export coverage to confirm YAML-style charts are embedded as DOCX media.
- Added PowerPoint appendix asset coverage to confirm converted charts are extractable as PNG images.

## Impact Analysis

Chat rendering behavior is unchanged. Export paths now handle the same chart block format already supported in the chat UI, reducing the chance that model-generated chart code appears in exported artifacts.

## Validation

- `python -m py_compile application/single_app/functions_chart_export.py application/single_app/route_backend_conversation_export.py functional_tests/test_conversation_export_inline_chart_images.py`
- `python functional_tests/test_conversation_export_inline_chart_images.py` (direct JSON/YAML chart conversion passed locally; route-dependent export assertions skip if optional export packages such as `python-pptx` are unavailable)
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`