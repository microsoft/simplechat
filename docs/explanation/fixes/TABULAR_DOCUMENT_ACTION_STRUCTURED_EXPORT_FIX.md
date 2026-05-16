# TABULAR DOCUMENT ACTION STRUCTURED EXPORT FIX

Fixed in version: **0.241.139**

## Issue Description

Tabular document Analyze and compare requests could use workbook analysis internally but still return only a short synthesized answer, even when the prompt explicitly asked for exhaustive row-level JSON or CSV output. In large classification runs, users could see thousands of matched rows in tool results but only a handful of final objects in the response.

## Root Cause Analysis

- The shared tabular document-action helper in `functions_workflow_runner.py` stopped after collecting workbook analysis text and never reused the chat tabular generated-output pipeline.
- That helper also skipped row-linked related-document augmentation, so references resolved from workbook rows were not carried into structured export generation or synthesis prompts.
- As a result, tabular analysis/compare behaved like a summary shortcut instead of reusing the more exhaustive tabular export path already available in the main chat/search flow.

## Version Implemented

- **0.241.139**

## Files Modified

- `application/single_app/functions_workflow_runner.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_document_actions_workflow.py`

## Code Changes Summary

- Reused `augment_tabular_invocations_with_related_document_evidence(...)` inside the shared tabular document-action helper.
- Reused `maybe_create_tabular_generated_output(...)` so analysis/compare can attach exhaustive row-level JSON or CSV exports when the prompt asks for them.
- Passed related-document evidence summaries into the computed-results prompt handoff for analysis and comparison synthesis.
- Updated synthesis prompts so the assistant summarizes key findings and points users to attached exports instead of implying the full dataset is inline.

## Testing Approach

- Ran `pytest functional_tests/test_tabular_document_actions_workflow.py`
- Planned narrow Python syntax validation on `functions_workflow_runner.py` and the updated regression file

## Impact Analysis

- Tabular document Analyze and compare now behave much closer to the main chat/search tabular flow for exhaustive structured-output requests.
- Large per-row classification prompts can now attach downloadable exhaustive exports instead of collapsing everything into one short synthesized answer.
- Row-linked external-document evidence is now available to both export generation and the final synthesis prompt when the workbook rows reference supporting documents.

## Validation

- Before: the workflow could find the full matching workbook rows but still produce only a small synthesized response with no reusable structured export.
- After: the same workflow can prepare exhaustive tabular exports, preserve related-document evidence, and return a concise summary that points to the attached full result set.