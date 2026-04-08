# Tabular Entity Lookup Cross-Sheet Retry Fix

## Fix Title
Cross-sheet workbook entity lookups now retry when the analytical pass only succeeds on one worksheet and stops before collecting the related records requested by the user.

## Issue Description
Questions such as finding one taxpayer and showing their profile, return summary, W-2, 1099, payment, refund, notice, audit, and installment agreement records could appear to succeed while still returning an incomplete answer. The analytical tabular pass repeatedly queried `Taxpayers`, found the primary row, and then stopped without traversing the related worksheets.

## Root Cause Analysis
- The route layer treated any successful analytical invocation as sufficient to finish the inner tabular analysis pass.
- For cross-sheet entity questions, that success condition was too weak because the first worksheet could succeed while leaving most requested record types untouched.
- Multi-sheet default-sheet behavior also made the initial worksheet selection too sticky for entity/profile prompts that should span several tabs.
- Worksheet matching did not preserve `W2` cleanly for sheet names such as `W2Forms`, which weakened related-sheet hinting for tax-document lookups.

## Version Implemented
Fixed in version: **0.239.119**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/route_backend_chats.py` | Added `entity_lookup` routing, related-worksheet hinting, execution-gap retries for incomplete one-sheet success, and stronger worksheet tokenization for `W2` sheet names |
| `functional_tests/test_tabular_entity_lookup_mode.py` | Added regression coverage for entity-lookup routing, related-sheet ranking, and incomplete-success retry guardrails |
| `functional_tests/test_tabular_workbook_schema_summary_mode.py` | Updated helper extraction to include the new execution-mode dependency and refreshed the file version header |
| `application/single_app/config.py` | Version bump to 0.239.119 |

## Code Changes Summary
- Added a dedicated `entity_lookup` execution mode for cross-sheet profile and related-record questions.
- Prevented multi-sheet entity lookups from relying on a sticky default worksheet during the analytical pass.
- Added execution-gap retry feedback so the inner SK loop retries when successful tool calls only touched one worksheet or when the narrative still claims the data is unavailable.
- Improved worksheet tokenization so `W2Forms` contributes a usable `w2` token during related-sheet scoring.

## Testing Approach
- Added `functional_tests/test_tabular_entity_lookup_mode.py`.
- Re-ran focused tabular functional tests covering workbook schema-summary routing, retry-sheet recovery, and the new cross-sheet entity-lookup path.

## Impact Analysis
- Cross-sheet taxpayer and case-history questions should now keep traversing related worksheets instead of stopping after the first successful row.
- Existing workbook summary and wrong-sheet recovery behavior remain intact because the new retry logic is scoped to `entity_lookup` mode.
- Related-sheet hinting is stronger for IRS-style workbook tabs that encode tax forms directly in sheet names.

## Validation
- Before: a taxpayer lookup could query `Taxpayers` successfully several times, never inspect the other tabs, and still finish with a generic answer.
- After: incomplete one-sheet success is treated as an execution gap, the analytical pass is retried with explicit cross-sheet guidance, and related tax-form worksheets such as `W2Forms` remain visible to the ranking logic.

## Related Config Update
- `application/single_app/config.py` now sets `VERSION = "0.239.119"`.
- Related functional tests: `functional_tests/test_tabular_entity_lookup_mode.py` and `functional_tests/test_tabular_workbook_schema_summary_mode.py`.