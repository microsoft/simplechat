# Deep Research Ledger Source Review Traversal Fix

Fixed in version: **0.241.051**

## Issue Description

The generated Deep Research Ledger showed planned search queries, web-search runs, reviewed pages, and skipped pages, but it did not clearly show the child pages that Deep Source Review followed from a returned seed page. Users could infer that deeper review happened from citations, but the audit artifact did not explain the parent page, child page, depth, or selection reason.

## Root Cause Analysis

Source Review page records already carried traversal metadata such as `parent_url`, `depth`, and `reason`, but `build_deep_research_ledger(...)` discarded those fields when building the compact ledger. `build_deep_research_ledger_markdown(...)` then rendered reviewed and skipped pages as flat lists, losing the deeper path context.

## Version Implemented

Fixed in version: **0.241.051**

## Technical Details

### Files Modified

- `application/single_app/functions_source_review.py`
- `functional_tests/test_deep_research_query_planning_and_ledger.py`
- `docs/explanation/features/v0.241.051/DEEP_RESEARCH.md`
- `application/single_app/config.py`

### Code Changes Summary

- Preserved Source Review traversal fields in Deep Research ledger reviewed/skipped page metadata.
- Added grouped `source_review_traversal` ledger data for seed pages and their reviewed/skipped child pages.
- Added a Markdown `Source Review Traversal` section showing parent URL, child URL, depth, selection reason, publish date, skip reason, link count, and Load More activity when available.
- Fixed skipped-page reason extraction so `skip_reason` values are shown instead of the generic skipped status.

### Testing Approach

- Updated the Deep Research functional test to validate traversal metadata and Markdown output for seed pages, reviewed child pages, skipped child pages, parent URLs, and selection reasons.

## Impact Analysis

Deep Research artifacts are more transparent and auditable. Users can now see where the system went after an initial source page and how Deep Source Review reached detail pages that later appear in citations.

## Validation

### Before

- Reviewed and skipped pages appeared as flat lists.
- Child pages reached via Source Review did not show their parent page or traversal reason.

### After

- The ledger includes a `Source Review Traversal` section that groups deeper reviewed/skipped pages under their seed or parent URL.
- Reviewed and skipped page lists include depth and parent information.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.241.051**.
