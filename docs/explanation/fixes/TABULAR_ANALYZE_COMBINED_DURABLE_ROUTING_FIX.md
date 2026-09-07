# TABULAR ANALYZE COMBINED DURABLE ROUTING FIX

Fixed in version: **0.250.185**

## Issue Description

Selected tabular Analyze requests that asked for row-level answers and a CSV output could fail mid-stream with `Document action failed (500)`. Production logs showed foreground tabular tools returning no computed inline results, followed by mixed-source Analyze failing because no evidence was prepared.

## Root Cause Analysis

- The shared tabular planner treated generated-output Analyze as dependent on the older hierarchical-analysis enablement flag.
- When that flag was off, an Analyze prompt such as `for each row, answer each question and generate a csv` was routed through foreground tabular tools instead of the combined durable generated-output path.
- Empty foreground tool output then caused the selected-source workflow to raise `Mixed-source Analyze could not prepare evidence from any selected source.`
- After combined routing was enabled, background runs for non-default model endpoints could fail immediately if the selected model endpoint context was not carried into the durable run record.

## Version Implemented

- **0.250.185**

## Files Modified

- `application/single_app/functions_tabular_orchestration.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/functions_tabular_analysis.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_analyze_deliverable_contract.py`
- `functional_tests/test_tabular_document_actions_workflow.py`
- `docs/explanation/features/ANALYZE_DELIVERABLE_CONTRACT.md`
- `docs/explanation/release_notes.md`

## Code Changes Summary

- Maps generated-output Analyze requests to the existing `combined` durable task type as first-class planner behavior.
- Queues planner-approved combined tabular Analyze work before foreground tabular tools run.
- Carries the selected model endpoint id, model id, provider, and active group context into the tabular generated-output run.
- Preserves pending, failed, and canceled generated-output evidence handling without synthesizing from empty computed results.
- Keeps bounded inline tabular Analyze on the foreground path when no generated output is requested.

## Testing Approach

- Updated Analyze deliverable-contract coverage to assert generated-output Analyze remains `combined` even when hierarchical-analysis-only settings are off.
- Added workflow coverage proving generated-output Analyze queues durable work before foreground tabular tools run and passes selected model endpoint context.
- Compiled changed Python files with `py_compile`.

## Impact Analysis

- Analyze requests that ask for both row-level analysis and a structured file now produce the intended Markdown analysis artifact plus the requested output file artifact.
- Exhaustive generated-output Analyze no longer depends on foreground tabular tools producing inline text.
- Background generated-output workers use the same selected endpoint context as the document-action request instead of assuming the model name is an Azure OpenAI deployment on the default resource.
- Non-generated-output Analyze and comparison workflows remain on their existing paths.

## Validation

- Before: explicit row-level Analyze plus CSV requests could be routed to foreground tools and fail with `Document action failed (500)` when no inline computed result was returned.
- After: the planner classifies the request as combined durable Analyze and the workflow queues that durable work with selected model endpoint context before foreground tabular tools run.
