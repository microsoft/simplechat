# Tabular Retry Sheet Recovery Fix

## Fix Title
Multi-sheet tabular analysis now recovers from a wrong initial worksheet guess by promoting candidate recovery sheets from failed analytical tool calls.

## Issue Description
Identifier-based workbook questions could fail even when the needed row existed in the workbook and document search had already surfaced the file. The analytical tabular pass sometimes started on a plausible but wrong worksheet, then kept retrying analytical tools against that same sheet until it exhausted retries and fell back to schema-only context.

## Root Cause Analysis
- The route layer used a lightweight likely-sheet heuristic to establish a default worksheet for multi-sheet analytical calls.
- That heuristic did not tokenize camel-case sheet names such as `TaxReturns` very well, which weakened the initial sheet guess for many workbook naming conventions.
- When a tool call failed because the requested column was missing on the chosen sheet, the tool only returned a generic missing-column error. The retry loop had no structured signal telling it which other worksheet was a better candidate.
- As a result, retries could keep hitting the same wrong worksheet even though the workbook schema already contained enough information to steer recovery.

## Version Implemented
Fixed in version: **0.239.117**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py` | Added workbook-aware missing-column payloads with `selected_sheet`, `missing_column`, and ordered `candidate_sheets` recovery hints |
| `application/single_app/route_backend_chats.py` | Added retry-sheet override helpers, camel-case sheet tokenization, and retry-time default-sheet promotion based on failed tool payloads |
| `functional_tests/test_tabular_retry_sheet_recovery.py` | Added regression coverage for camel-case sheet tokenization, candidate-sheet error payloads, and retry-sheet override selection |
| `application/single_app/config.py` | Version bump to 0.239.117 |

## Code Changes Summary
- Improved worksheet tokenization so camel-case sheet names participate in likely-sheet matching more accurately.
- Extended analytical tool errors so missing-column failures identify the current sheet and suggest candidate recovery sheets from the same workbook.
- Added retry orchestration that reads those candidate sheets and updates the plugin's default worksheet before the next analytical attempt.
- Updated the analytical system prompt so recovery-sheet hints override the original likely-sheet guess after a wrong-sheet failure.

## Testing Approach
- Added `functional_tests/test_tabular_retry_sheet_recovery.py`.
- Re-ran focused multi-sheet and tool-error tabular functional tests to confirm retry recovery stays compatible with the existing analytical-only orchestration.

## Impact Analysis
- Identifier-based workbook questions should now recover when the first worksheet guess is wrong instead of repeating the same failing call.
- This remains tool-driven behavior inside the analytical SK pass; it does not rely on schema-only fallback to answer workbook calculation questions.
- The recovery behavior is generic across multi-sheet workbooks because it is based on missing-column signals and workbook sheet/column structure rather than workbook-specific rules.

## Validation
- Before: a wrong initial worksheet guess could lead to repeated analytical retries on the same sheet until the route fell back to schema context.
- After: missing-column failures expose better candidate sheets and the next analytical retry can be redirected to the stronger worksheet automatically.