# Re-uploaded Tabular Source Revision Conflict Fix (v0.261.143)

**Fixed in version: 0.261.143**

The application version is tracked in `application/single_app/config.py`.

This fix shipped in the React V2 branch as 0.261.143. On the V2 shared workspaces branch, which had already assigned 0.261.143 to its group details projection fix, it arrives with the React V2 base merge in version **0.261.190**.

## Issue

After the 0.261.141 compare fix (see `ORCHESTRATION_EXECUTION_FAILURES_FIX.md`),
the same PDF-and-CSV compare was retested twice on a deployed V2 environment
running 0.261.142. Both runs planned correctly and then stalled on the CSV step:

- Recovery reported that the producer stopped before its saved result could be
  confirmed (`result_commit_unconfirmed`), rather than the actual reason.
- The run view kept the CSV step labeled **Reasoning** after the run had ended.

The PDF step behaved differently in each run. In one run it hit the step time
limit, and in the other it reused a partial result. That made the two runs look
like separate problems, but both failed at the same point for the same reason.

## Root cause

### A descriptor schema version was compared with a document revision

`_build_generated_export_query_descriptor_from_location` in
`semantic_kernel_plugins/tabular_processing_plugin.py` builds the replay
descriptor for a tabular export run. The descriptor carries the source's
`screening_provenance`, and it also carries its own schema key, `version: 1`.

Before it reads any rows, native compute re-authorizes that descriptor:
`_authorize_tabular_export_run_execution` calls `assert_evidence_available`,
which calls `assert_document_available`, which calls `_check_source_revision`
in `content_screening/access.py`.

`_check_source_revision` first compared the provenance with the current
document, and that comparison passed. It then went on to compare the source's
`version` key with the document's `version`. For a descriptor, that meant
comparing the descriptor's schema version (1) with the document's revision.

A CSV or workbook that has been re-uploaded under the same name has a revision
of 2 or higher. For those files the check raised `ScreeningConflictError`
(`screening_revision_conflict`), even though the source was current and
authorized. Other tabular export runs that carry the same descriptor were
exposed to the same false conflict.

### Why 0.261.141 exposed it

Before 0.261.141, this step failed earlier, because an older same-name revision
was selected for the CSV's storage location. Fixing that selection let the step
reach this check with the current revision for the first time.

### Why the run stalled instead of failing

Strict source-authority failures are deliberately fenced, so that uncertain
authority is never recorded as a denial. When execution ends with any
`ScreeningError`, including a definitive conflict, finalization raises a
delivery failure (`message_not_saved`) instead of saving a failed run. The
stream route logged `Headless execution could not return its saved outcome`,
and the CSV step was left marked `running`.

The continuation then found that step still `running`, with no committed
result, and raised `result_commit_unconfirmed`. The V2 run view labels a
`running` reasoning step **Reasoning**, even after the run has ended.

### Why it was hard to trace

The conflict event recorded `failure_code=screening_revision_conflict` and
nothing else, so nothing in the logs identified which comparison had failed.

## Evidence

Application Insights showed the same sequence in both runs:

| Run | CSV blob read (UTC) | `ScreeningConflictError` (UTC) | What happened to step 1 (PDF) |
| --- | --- | --- | --- |
| 1 | 16:26:34.333 | 16:26:34.507 | Hit the 180-second step limit and was cancelled at 16:26:32 |
| 2 | 18:06:45.120 | 18:06:45.302 | Reused a partial result |

In both runs:

- The conflict was raised less than 200 ms after the CSV was read, before any
  rows were processed.
- It was followed by `Headless execution did not complete`
  (`execution_interrupted`) and by `could not return its saved outcome`.
- 12 to 17 seconds later, the continuation raised `result_commit_unconfirmed`.

A local reproduction on the real native compute path confirmed the cause:

- The same request completed for a version-1 source.
- For a version-2 source, it raised `ScreeningConflictError` at the trailing
  version comparison in `_check_source_revision`.

## Technical details

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/content_screening/access.py` | Screening provenance is authoritative in `_check_source_revision`, and revision conflicts carry an `authority_reason`. |
| `functional_tests/test_native_tabular_compute_service.py` | End-to-end test for a re-uploaded source; `native_runtime` accepts `document_version`. |
| `functional_tests/test_content_screening_access.py` | Tests for provenance beside a schema `version`, per-path conflict reasons, and cached-evidence reasons. |
| `functional_tests/test_orchestration_source_access.py` | Strict-mode telemetry tests for revision conflicts. |
| `docs/reference/logging-tags.md` | New `sc_authority_reason` codes. |
| `application/single_app/config.py` | Version 0.261.143. |

### Provenance is authoritative

When a source carries a `screening_provenance` mapping, `_check_source_revision`
compares it with the current document's `document_provenance()` and then
returns. The carrier's own `version` key is no longer read.

This does not weaken the check:

- Provenance pins the document id, the scope type and scope id, the
  `source_revision` (the document version), and the screening `generation`.
- The comparison requires an exact match, so a matching provenance already
  proves that the carrier refers to the current revision.
- The removed comparison could therefore only disagree when the carrier's
  `version` meant something else. The descriptor's schema version is one
  example. The chat-upload context in `functions_search_service.py` is another:
  it pairs a chat message's own `version` with the linked workspace document's
  provenance.

Sources without provenance keep their existing checks unchanged:

- legacy `{document_id, version}` references;
- saved copies of a screened document record;
- cached evidence from before screening enrollment.

### Conflict reasons

Revision conflicts now say what no longer matches:

| `authority_reason` | Raised when |
| --- | --- |
| `source_revision_changed` | The provenance `source_revision` differs from the current document's version. |
| `screening_generation_changed` | The provenance screening generation differs, because the document was re-screened or remediated. |
| `source_scope_changed` | The provenance document id, scope type, or scope id differs. |
| `provenance_shape_invalid` | The provenance has a different set of fields from the current format. |
| `screened_record_changed` | A saved copy of the screened document record differs from the current record. |
| `source_version_changed` | A legacy reference without provenance names a different version. |
| `cached_evidence_unproven` | Cached evidence has no provenance proving that it survived screening enrollment. |

The cached-evidence check in `assert_evidence_available` uses the same codes.
When some proof exists but is stale, it reports the changed field instead of
`cached_evidence_unproven`.

Reasons are logged only through the existing strict-mode
`raise_source_authority_error`, as `sc_authority_reason` on the
`[CONTENT_SCREENING] Current source authority could not be verified.` event. They
contain no document values. Non-strict callers raise the same conflict as before
and still log nothing. The cached-evidence conflict now uses the same strict-mode
path as other authority failures, so a strict caller logs it too.

## Testing

New tests:

- `test_native_tabular_compute_service.py::test_reuploaded_source_revision_computes_and_replays`
  - A version-2 source computes all 25 rows in the foreground.
  - Its result reopens with `require_current_sources=True`.
  - The durable background path completes with the same rows and publishes
    nothing.
- `test_content_screening_access.py`
  - A current provenance beside a different schema `version` is accepted by both
    `assert_document_available` and `assert_evidence_available`.
  - Each conflict path reports its own reason.
  - Cached evidence reports either a missing proof or the changed field of a
    stale proof.
- `test_orchestration_source_access.py`
  - Strict revision conflicts log `failure_code=screening_revision_conflict` and
    the reason, without values.
  - A current provenance beside a schema `version` logs nothing.
  - The strict cached-evidence conflict is logged with its reason.

Existing revision tests still pass unchanged. These include:

- `test_historical_version_cannot_borrow_a_current_approval`
- `test_snapshot_read_is_historical_but_current_read_and_resume_refuse_change`
- `test_real_current_hold_missing_and_revision_are_unavailable`
- `test_legacy_malformed_authority_stays_a_quiet_hold`

## Validation

- With only the `access.py` change reverted, 14 new test cases fail: 8 tests
  and all 6 subtests of the conflict-reason test. The re-uploaded source test
  fails with the same `ScreeningConflictError`, at the same line, as the
  deployed runs.
- With the change applied, every new test passes, as do the complete
  content-screening access, orchestration source-access, native tabular
  compute, and docs suites.
- 117 related test files were run, each in its own process. The 30 that still
  report failures fail identically on the unmodified base commit, so none come
  from this change. One of them, `test_tabular_row_orchestration_scale.py`, also
  hangs on the same test on both commits.

### Before and after

| Scenario | Before | After |
| --- | --- | --- |
| Tabular step on a re-uploaded CSV or workbook | False `screening_revision_conflict`; the run stalled and recovery reported `result_commit_unconfirmed`. | The step computes and replays the current revision. |
| A source whose revision really changed | Conflict, with no logged reason. | The same conflict, with `sc_authority_reason` naming what changed. |

### Verify after deployment

Re-run the PDF-and-CSV compare, then run this query in Log Analytics:

```kusto
AppTraces
| where TimeGenerated > ago(2h)
| where tostring(Properties.sc_message) has "CONTENT_SCREENING"
    or tostring(Properties.sc_execution_code) == "result_commit_unconfirmed"
| project TimeGenerated, m = tostring(Properties.sc_message),
    code = tostring(Properties.sc_failure_code), reason = tostring(Properties.sc_authority_reason),
    exec = tostring(Properties.sc_execution_code)
| order by TimeGenerated asc
```

The CSV step should complete, and no `screening_revision_conflict` should
appear. If a conflict still occurs, `reason` names the check that fired.

## Follow-ups

These were found during the investigation and are not changed here:

- **A definitive conflict is fenced like an outage.** A `ScreeningConflictError`
  becomes `result_commit_unconfirmed` and leaves the step marked `running`. It
  could fail the step with the conflict's public message instead. That changes a
  deliberate fencing contract with extensive tests, so it belongs in its own
  change.
- **Steps on a finished run still say "Reasoning".** In
  `OrchestrationRunView.tsx` and the `OrchestrationPlanCard.tsx` progress line, a
  step still marked `running` on a terminal run should read **Interrupted**.
- **The PDF step needs more time.** In run 1, `document_analyze` took 3 minutes
  21 seconds: four PDF windows at 30 to 40 seconds each, plus two window
  retries. The default step limit is 180 seconds, so raise **Step timeout**
  under **Admin Settings > Orchestration** before retesting.
- **Window retries log only an exception type.** Window attempts that fail with
  `ValueError` should also log a safe failure category, so an empty model
  response can be told apart from one that could not be parsed.
- **Re-authorization volume.** Step transitions made about 550 Cosmos calls in
  2.6 seconds.
