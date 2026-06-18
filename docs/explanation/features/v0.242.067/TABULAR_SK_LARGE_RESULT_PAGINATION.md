# Tabular SK Large Result Pagination

Implemented in version: **0.242.067**

## Overview

Tabular Semantic Kernel analysis now supports safer large-result handling for row-returning tools. The feature adds explicit pagination metadata, preserves caller-requested projections with `return_columns`, trims oversized row payloads when projection is not provided, and raises the computed-results handoff guardrail from 24K to 100K characters.

## Technical Specifications

### Architecture

The tabular processing plugin centralizes row payload shaping through a shared helper that:

- Normalizes `start_row` and `max_rows`.
- Returns `has_more` and `next_start_row` for continuation.
- Applies `return_columns` projection when requested.
- Preserves protected row metadata such as `_sheet`, `_matched_columns`, `_matched_values`, `_matched_on`, `_matched_source_values`, and `_related_document_reference_values`.
- Estimates serialized JSON size and auto-excludes heavy non-protected columns when the row payload would exceed the safe output budget.
- Reduces rows only when column trimming is insufficient, advancing `next_start_row` by the number of rows actually returned.

### Tools Updated

- `lookup_value`
- `filter_rows`
- `search_rows`
- `query_tabular_data`
- `filter_rows_by_related_values`

Count and aggregation tools remain compact summary tools and do not expose row pagination.

### Handoff Limits

`route_backend_chats.py` now uses a 100K-character guardrail for tabular SK analysis text and computed-results handoff messages. Truncation emits warning logs with the original and configured limit details.

## Usage Instructions

Call row-returning tabular tools with `max_rows` to limit page size. If the tool response includes `has_more: true`, call the same tool again with `start_row` set to `next_start_row`.

Use `return_columns` when the answer only needs specific fields. This bypasses automatic heavy-column exclusion and keeps returned rows focused.

## Testing and Validation

Functional tests:

- `functional_tests/test_tabular_large_result_pagination.py`
- `functional_tests/test_tabular_large_result_handoff.py`

These tests validate row continuation, auto-trim behavior, `return_columns` projection, cross-sheet pagination, attachment-reference preservation, and the 100K handoff guardrail.

## Attribution

This feature was inspired by and adapted from the design direction in PR #894 by @vivche, which proposed tabular SK pagination, `return_columns` forwarding, automatic large-result trimming, and a larger computed-results handoff guardrail.

The implementation in this branch was rebuilt against the current Development tabular pipeline to preserve newer model-context routing, related-document evidence, generated tabular outputs, and thought tracking.

## Related Version Updates

- `application/single_app/config.py` updated to `0.242.067` for the initial feature.
- `application/single_app/config.py` updated to `0.242.068` for the Python 3.13 Semantic Kernel parameter compatibility follow-up.
