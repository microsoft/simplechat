# Workflow Activity View

Implemented in version: **0.241.039**

## Overview

The workflow activity view adds a dedicated execution timeline for workflow runs.
It gives users a live and historical view of what a workflow is doing, including
workflow lifecycle events, tool invocations, and direct model execution stages.

## Dependencies

- Workflow conversations in the shared conversations container
- Workflow run history in `personal_workflow_runs`
- Thought persistence in the existing `thoughts` container
- Server-sent events for live updates while a run is active

## Technical Specifications

### Architecture

- The feature reuses the existing `thoughts` container instead of introducing a new Cosmos container.
- Workflow runs now allocate the assistant message id before execution so live activity can attach to the run immediately.
- Tool invocation start and completion events share a stable `invocation_id`, which lets the activity page merge them into a single timeline card.
- The new workflow activity page is served from `/workflow-activity`.

### Backend Endpoints

- `GET /api/user/workflows/activity`
  - Resolves the latest run for a workflow conversation or a specific historical run.
  - Returns the merged workflow activity snapshot used by the page.
- `GET /api/user/workflows/activity/stream`
  - Streams refreshed workflow activity snapshots over SSE while a run is active.

### Frontend Entry Points

- Workflow conversations show an `Activity View` button in the chat header.
- Workflow run history now includes `Open activity view` links for each recorded run.

## Usage

1. Open a workflow conversation and select `Activity View` to inspect the latest run in a new tab.
2. Open workflow history from the workspace workflows tab and use `Open activity view` on a specific run to inspect the historical snapshot.
3. While a workflow is still running, keep the activity page open to receive live timeline updates over SSE.

## Testing and Validation

- Functional test: `functional_tests/test_workflow_activity_view_feature.py`
- The snapshot builder verifies activity merging, branch lane assignment, and fallback rendering for legacy runs without structured activity thoughts.
- The workflow page renders without introducing a new storage dependency.

## Related Files

- `application/single_app/functions_workflow_activity.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/route_backend_workflows.py`
- `application/single_app/templates/workflow_activity.html`
- `application/single_app/static/js/workflow/workflow-activity.js`
- `application/single_app/static/css/workflow-activity.css`
