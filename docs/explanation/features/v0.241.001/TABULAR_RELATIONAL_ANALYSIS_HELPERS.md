# Tabular Relational Analysis Helpers

## Overview
This feature extends the tabular processing plugin with deterministic helpers for cross-sheet cohort, count, and relationship-style workbook questions. It adds distinct-value discovery, row counting, set-membership filtering and counting, normalized entity matching, and workbook relationship metadata so the analysis layer can answer relational questions without relying on sampled row counting or workbook-specific prompting.

**Version Implemented:** 0.240.017

## Dependencies
- Flask chat orchestration in `route_backend_chats.py`
- `TabularProcessingPlugin` in `semantic_kernel_plugins/tabular_processing_plugin.py`
- Azure Blob Storage-backed workbook access
- Azure Cosmos DB message and citation persistence
- Existing tabular SK analysis routing and citation compaction

## Architecture Overview

### Plugin Enhancements
- Added deterministic helper functions for distinct values, row counts, and cross-sheet set-membership analysis.
- Added normalized entity matching for text comparisons such as names, owners, assignees, and engineer-style identifiers.
- Extended workbook schema summaries with inferred `sheet_role_hints` and `relationship_hints` so orchestration can see likely reference-to-fact sheet relationships.

### Orchestration Enhancements
- Updated the tabular SK analysis prompt to advertise the new helpers.
- Added prompt guidance that prefers deterministic count helpers over manual counting from sampled rows.
- Added prompt guidance for cohort and ownership-share questions that span multiple worksheets.

## Feature Set

### `get_distinct_values`
- Returns deterministic distinct values from a worksheet or, when appropriate, across worksheets.
- Supports optional `query_expression` and filter conditions.
- Supports normalized string/entity matching for stable deduplication.

### `count_rows`
- Returns a deterministic row count after optional query or filter criteria.
- Avoids relying on the model to estimate counts from partial row payloads.

### `filter_rows_by_related_values`
- Filters a target worksheet by membership in a cohort defined on a source worksheet.
- Returns explainable metadata including source cohort size, matched source values, unmatched source values, and matched target row count.

### `count_rows_by_related_values`
- Counts target rows by membership in a source-sheet cohort.
- Designed for numerator/denominator and percentage-style questions across related worksheets.

### Normalized Entity Matching
- Canonicalizes text by trimming, casefolding, normalizing punctuation, and collapsing whitespace.
- Supports optional alias columns on both source and target worksheets when available.

### Workbook Relationship Metadata
- Adds `sheet_role_hints` for likely dimension, fact, metadata, or unknown worksheet roles.
- Adds `relationship_hints` with likely reference and fact sheets, candidate join columns, overlap counts, and overlap ratios.

## File Structure

| File | Purpose |
|---|---|
| `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py` | New deterministic relational helpers, normalized matching, and relationship metadata inference |
| `application/single_app/route_backend_chats.py` | Prompt guidance and schema preload exposure for the new helpers |
| `application/single_app/functions_message_artifacts.py` | Compact citation support for the new tabular helper outputs |
| `functional_tests/test_tabular_relational_analysis_helpers.py` | Regression coverage for relationship metadata and deterministic relational helpers |

## Explainable Outputs

The new relational helpers return structured metadata such as:
- Source and target sheets
- Source and target match columns
- Source cohort size
- Matched and unmatched source value counts
- Matched target row count
- Applied filter summaries
- Normalization flags
- Row truncation indicators when applicable

## Testing and Validation

### Covered Scenarios
- Workbook schema summaries infer likely reference/fact relationships.
- Distinct-value discovery returns a deterministic filtered cohort.
- Deterministic row counting returns explicit counts rather than sampled approximations.
- Cross-sheet set-membership helpers return explainable outputs and normalized matching works across owner/name variants.
- Tabular SK prompt guidance advertises and prefers the new deterministic helpers.

### Functional Test
- `functional_tests/test_tabular_relational_analysis_helpers.py`

## Known Tradeoffs
- Relationship hints are heuristic and intended to guide tool choice, not to prove a guaranteed join.
- Normalized matching improves robustness for entity-style text, but ambiguous aliases still depend on the workbook data being reasonably consistent.
- The new helpers reduce reasoning ambiguity, but they do not replace the existing large-dataset artifact and prompt-budget protections.

## Cross-References
- `docs/explanation/fixes/ASSISTANT_CITATION_ARTIFACT_STORAGE_FIX.md`
- `docs/explanation/fixes/TABULAR_PROMPT_BUDGET_FALLBACK_FIX.md`
- `docs/explanation/features/TABULAR_LARGE_DATASET_ANALYSIS_REDESIGN_PLAN.md`