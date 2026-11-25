# Native Inspection Cursor Revision Fix

Fixed in version: **0.261.478**

## Issue

In the 0.261.477 run an action step failed with `document_action_read_failed`. The log shows
three document reads completing and the fourth, a continuation of a paged PDF or PowerPoint
inspection, refused with `native_cursor_source_changed`, rule
`native_cursor_revision_changed`, four seconds after the cursor was issued. The step failed,
and a next attempt needs confirmation because an action step may have had effects.

## Root cause

A continuation cursor for a PDF or PowerPoint inspection carried the document record's storage
revision (`_etag`) alongside the document id, the uploaded version and the SHA-256 of the
source bytes. Any write to the record changes that revision, including one that leaves the
source bytes as they were. A page is read from the bytes, so such a write ended the paging
although nothing the page depends on had changed.

The Excel inventory cursor never carried the record revision: it is bound to the subject and
the source digest.

What wrote the record in that run is not known. The telemetry shows the rule that refused, not
the writer.

## Change

`inspect_native_document` in `functions_native_document_inspection.py` no longer puts the
record revision in the cursor identity. A continuation must still match the document id, the
uploaded version, the source digest, the schema version and the section.

Unchanged:

- Access is checked again on every read by the caller, before the bytes are read.
- Different bytes, a different uploaded version, another document or another section still
  refuse the cursor with `native_cursor_source_changed` and the rule that names which.
- A cursor in the earlier format (carrying the revision) is refused as `native_cursor_invalid`.
  Cursors live only within one action step.

## What this does not do

- A read refused for a real change (other bytes, another version) still fails the step. It is
  not returned to the action's model as a correction.
- The other action failure of that run (`step_failed` on the first function call) is not
  explained yet. From 0.261.478 it logs which check stopped it.

## Files modified

- `application/single_app/functions_native_document_inspection.py`
- `functional_tests/test_native_inspection_request_contract.py`
- `functional_tests/test_native_document_fidelity_pipeline.py`

## Validation

- `test_a_pdf_continuation_survives_a_record_write_that_leaves_the_bytes_unchanged`: a second
  page is read after the record revision changes; other bytes, another version and another
  document are still refused.
- `test_pdf_cursor_failure_identifies_the_actual_invariant`: a version change names
  `native_cursor_version_changed`; a cursor carrying a revision is invalid.
- `test_source_bound_pages_continue_and_refuse_changed_identity` asserted the earlier rule and
  now asserts this one, for three PDF and two PowerPoint sources.

Before: record written between two pages, same bytes, cursor refused, step failed.
After: record written between two pages, same bytes, paging continues.

Not run against the deployed application.
