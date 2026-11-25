# Plan Document Unavailable Correction Fix

Fixed in version: **0.261.481**

## Issue

In the 0.261.478 run five follow-up prompts were refused at planning with "The request could
not be planned" (`source_unavailable`, rule `document_authorization_required`). No run was
created, so nothing was executed and nothing could be retried.

In the two turns traced in full:

- One had three documents selected. The plan named three documents: two of the selected ones
  and one ID that was not available to the request.
- One had no selection and fifteen candidate documents. The plan named nine documents, at
  least one of which was not among the candidates.

Both were refused on the first proposal with two corrections still unused.

## Root cause

`normalize_plan` refuses a step whose `document_ids` holds an ID outside the documents the
request may read. That refusal's code was not among the codes the planner is asked to correct,
so planning ended there. Every other fault of the same kind (a selected document left out, a
wrong source kind, a missing binding) goes back to the planner with what was wrong.

The ID is the planner's own choice. Where it came from is not known from the telemetry; an
earlier turn's sources are shown to the planner, so one of those is the likely origin.

## Change

- `functions_orchestration_schema.py`: the refusal carries model-only feedback, the argument
  and the IDs in it that are not available to this request. Feedback goes back only to the
  planner that wrote those IDs and is never logged.
- `functions_orchestration_planner.py`: `source_unavailable` with rule
  `document_authorization_required` is corrected within the shared correction allowance. The
  correction states the rule: a step may name only document IDs this request supplies.

Unchanged:

- The set of documents a plan may name. A corrected plan is validated against the same set,
  and a planner that names the ID again is refused once the corrections are used.
- The correction does not say whether the document exists or who may read it.
- The executor authorizes every source again before it is read.

## Files modified

- `application/single_app/functions_orchestration_schema.py`
- `application/single_app/functions_orchestration_planner.py`
- `functional_tests/test_orchestration_document_planning_recovery.py`

## Validation

- `test_a_document_outside_the_readable_set_is_returned_to_the_planner`: a plan naming an
  unavailable document is corrected in one further proposal, the correction names the ID, and
  the ID is absent from every log record.
- `test_correction_cannot_widen_the_authorized_document_selection`: a planner that keeps
  naming the unavailable document is still refused, after the shared corrections.

Before: refused on the first proposal, no run.
After: returned to the planner; refused only if it is named again.

Not run against the deployed application.
