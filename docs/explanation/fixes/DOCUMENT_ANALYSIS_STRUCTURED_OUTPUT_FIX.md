# Analyze Structured Output Fix

Version: 0.241.023

Fixed/Implemented in version: **0.241.117**

Related config.py update: `VERSION = "0.241.023"`

## Header Information

- Issue description: Document analysis could finish a large per-document classification run with only a handful of final JSON objects even when all selected documents and windows were analyzed successfully.
- Root cause analysis: The workflow reduced window-level outputs from many different documents into one generic final answer, so the final reduction call could merge, omit, or truncate document-level results instead of preserving one output per source comment.
- Version implemented: 0.241.117

## Technical Details

- Files modified: `application/single_app/functions_document_analysis.py`, `application/single_app/config.py`, `functional_tests/test_document_analysis_structured_output.py`
- Code changes summary: Added document-level window consolidation, added structured JSON-per-comment detection with deterministic final merging, and hardened reduction so it raises instead of silently returning only the first remaining batch when round limits are exhausted.
- Testing approach: Added a focused functional regression test that simulates a multi-document structured analysis and verifies document-level reductions still occur while the lossy final global reduction is skipped.

## Validation

- Test results: The new regression test verifies that structured analysis returns all expected comment objects, preserves multi-window document consolidation, and keeps global structured-output reduction disabled.
- Before/after comparison: Before the fix, a 232-document classification run could collapse to a few synthesized JSON objects after reduction batches. After the fix, structured per-comment results are preserved across documents and merged deterministically into one final JSON array.
- User experience improvements: Large rulemaking or analysis workflows now return the full per-comment structured payload the user asked for instead of a shortened subset.