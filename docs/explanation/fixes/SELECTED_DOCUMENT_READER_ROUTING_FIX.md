# Selected-document reader routing and source continuity fix

Version: **0.261.432**

Fixed/Implemented in version: **0.261.432**

Application version tracking remains in `application/single_app/config.py`.

## Issue and root cause

Selected CSV requests could call the Document Search native accessibility report
instead of the data reader. CSVs do not have that native-property inventory.
The inspection returned an error, the action correctly refused to use it as
findings, and dependent analysis or file generation did not run.

A completed seven-scenario investigation correlated all 17 reported read failures
with `get_document_accessibility_report`, an earlier native `LookupError`, and
`document_action_read_failed`. Forty-three chunk reads had succeeded in twelve
of those failed runs. One separate follow-up merged all 74 records from its
three files and answered successfully. The evidence distinguished an incompatible
reader choice from generally unavailable files.

An additional follow-up lost its explicit source set and used a bounded relevance
candidate list. Absence from that list was not proof that the file was missing.
Accepted clarification attachments were already additive; they were not replaced
with a new overwrite rule.

These observations did not independently establish a Word, CSV or chart-renderer
defect. Rendering skipped after failed dependencies is not the same as a renderer
that ran and failed.

## Changes and preserved behavior

Document-bound actions project verified source capabilities and restrict
incompatible native-reader calls both in tool admission and at invocation.
Supported PDF, Office, workbook structure and comment inspections remain
available. Content/data readers are not replaced with accessibility reports,
and missing native metadata is not converted into an empty success.

Related continuations preserve requested source identities separately from
successfully acquired results and re-resolve them with current access. New
explicit selections, new topics and scope restrictions remain authoritative.
Candidate suggestions remain non-exhaustive.

Exact cross-file calculations use a separate typed operation on the existing
native-result bridge. See [Multi-file tabular calculations](../features/MULTI_FILE_TABULAR_CALCULATIONS.md).
It reads complete authorized tables, validates relationships, calculates precise
values and retains records/coverage/lineage before composition or export.
Existing single-source operations and append/union semantics are unchanged.

Accessibility did not delete the calculation implementation: the one-source
native orchestration contract predates the later accessibility-reader addition,
and existing tabular calculation helpers remain. The repair preserves both
capabilities rather than disabling one to make the other work.

## Technical scope

The affected owners are the document-bound action executor/adapters,
orchestration context and continuation route, native-result bridge, capability
registry/schema, complete tabular reader and precise relational calculation
engine. Storage authorization, exact citation authority, source snapshots,
producer guards and truthful completeness remain mandatory.

No example filename, row identifier, expected amount or canned answer is used
for routing or calculation. Invalid, stale, revoked, ambiguous and over-limit
inputs remain explicit failures. A failed required acquisition/computation does
not start rendering or publish complete findings.

## Validation and limits

The document-action and selected-source planning suites cover format-aware
reading, native inspection coexistence and related continuation behavior.
The multi-file calculation/retention suites cover actual computed rows, matching
diagnostics, source authority, exact exports and failure controls. Existing
precision and merge suites guard compatibility.

The investigation observed serving version 0.261.428 and inspected matching
core source contracts. Implementation regressions are offline; they do not
claim a new deployment, a replay of the failed batch or successful live file
delivery. Deployment and live acceptance require separate approval.
