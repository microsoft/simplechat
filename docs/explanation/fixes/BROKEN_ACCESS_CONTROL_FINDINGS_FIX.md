# Broken Access Control Findings Fix

Fixed/Implemented in version: **0.242.049**

## Issue Description

The Broken Access Control audit identified several places where caller-controlled object identifiers were used before a fresh authorization decision for the exact object. The affected paths included workflow conversation bindings, SimpleChat plugin conversation tool calls, and group document deletion.

## Root Cause Analysis

Workflow save helpers accepted arbitrary `conversation_id` values and workflow execution later reused those conversation records without confirming that the conversation belonged to the workflow owner or active group. SimpleChat plugin helper calls could return distinguishable errors for missing, foreign, and wrong-type conversation IDs. The group document delete route read a caller-provided document ID directly before proving that it belonged to the active group.

## Technical Details

Files modified:

- `application/single_app/functions_personal_workflows.py`
- `application/single_app/functions_group_workflows.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/functions_collaboration.py`
- `application/single_app/route_backend_group_documents.py`
- `functional_tests/test_broken_access_control_findings_fix.py`
- `application/single_app/config.py`

Code changes summary:

- Added save-time workflow conversation validation for personal and group workflows.
- Added a workflow-runner backstop so already-persisted foreign conversation IDs cannot be reused for workflow message writes.
- Collapsed SimpleChat plugin conversation lookup failures to a generic not-found/access-denied response.
- Added an authorized collaboration invite boundary before participant management logic.
- Changed group document deletion to query by both document ID and owning active group before delete processing.
- Replaced raw `activeGroupOid` reads in group document routes with a `require_active_group(...)`-backed resolver.

## Validation

Testing approach:

- Added a focused functional regression test that verifies personal/group workflow conversation validation, workflow runner authorization, SimpleChat plugin conversation oracle collapse, scoped group document deletion source structure, and removal of raw active-group reads from group document routes.

Before/after comparison:

- Before: known foreign conversation or document IDs could produce distinguishable responses, and workflow runs could write into an unauthorized conversation.
- After: workflow conversation IDs are authorized at save and execution time, plugin tool-call lookups collapse unauthorized targets, group document routes resolve the active group through an authorization helper, and group delete requests only proceed after a scoped owning-group document lookup succeeds.

Related version update:

- `application/single_app/config.py` was incremented from `0.242.048` to `0.242.049`.