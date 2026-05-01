# Workflow Activity Response Preview Toggle

Version implemented: **0.241.042**

## Overview

The workflow activity page now keeps the response preview collapsed by default and exposes a top-level toggle button so users can open it only when needed. This preserves more vertical space for the live timeline and the right-side activity detail panel.

## Dependencies

- `application/single_app/templates/workflow_activity.html`
- `application/single_app/static/js/workflow/workflow-activity.js`
- `application/single_app/static/css/workflow-activity.css`

## Technical Specifications

### Architecture Overview

The response preview remains part of the workflow activity hero section, but the page now drives its visibility through a dedicated client-side toggle state. The toggle only appears when a response preview or run error exists.

### Configuration And File Structure

- The page template defines the toggle button and keeps the preview region wired with `aria-controls`.
- The workflow activity script tracks whether the preview is expanded and keeps it collapsed by default.
- The activity stylesheet rotates the toggle chevron when the preview is expanded.

## Usage Instructions

- Open any workflow activity page that has a response preview or captured run error.
- Use the `Show response preview` button in the top action row to expand the preview.
- Use the same button again to collapse it and restore more room for the timeline and details.

## Testing And Validation

- Regression coverage is provided by `functional_tests/test_workflow_activity_response_preview_toggle.py`.
- Existing workflow activity snapshot coverage remains in `functional_tests/test_workflow_activity_view_feature.py`.
- The feature is intended to improve live monitoring ergonomics without changing workflow activity data or SSE behavior.
