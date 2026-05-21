# URL Access HTML Extraction Fix

Fixed in version: **0.241.083**

## Issue Description
URL Access could report `URL Access did not add page evidence` for valid public pages, including GitHub repository pages, even though the URL Access request was enabled and the pasted URL was reviewed.

## Root Cause
The shared Source Review HTML cleanup step decomposed hidden and control nodes, then continued iterating over nested BeautifulSoup tags that had already been removed from the parse tree. Calling `element.get(...)` on one of those decomposed tags raised an `AttributeError`, causing the page to be recorded as an `unexpected_error` skip with no evidence message.

## Technical Details
- Updated `functions_source_review.py` so `_remove_non_evidence_nodes()` skips already-decomposed tags during cleanup.
- Updated URL Access/Source Review result handling so all-skipped URL reviews include a concrete `skipped_reason` for troubleshooting.
- Updated the evidence system message to tell selected agents not to call web or HTTP tools for the same reviewed pasted URL unless a fresh fetch is explicitly needed.
- Added regression coverage in `functional_tests/test_source_review_security.py` for nested hidden/control HTML that previously failed extraction.
- Updated `config.py` version to `0.241.083`.

## Validation
- Functional Source Review tests validate that nested removed nodes no longer fail evidence extraction.
- Direct URL Access fetch validation against `https://github.com/microsoft/simplechat` confirms that URL Access now produces reviewed page evidence and a system evidence message without requiring an agent.

## Impact
URL Access now works for normal model-only chats when a pasted page contains nested hidden or control markup. Selected agents receive the same URL Access evidence and are instructed to avoid duplicating the Smart HTTP fetch for already-reviewed pasted URLs.