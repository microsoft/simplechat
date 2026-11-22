# Document Analysis Stated Gap Fix

Fixed in version: **0.261.477**

## Issue

A document analysis finished `partial` on almost every orchestration run, although every
source had been read in full. A partial analysis has no `records` output and its consumers
refuse it, so the run ended partial (`result_partial`, once `result_output_missing`) and no
next attempt was offered. In the 0.261.476 rerun this was the largest single cause of partial
runs: 8 of 22.

## Root cause

The analysis model is asked to say what it could not conclude from a slice:

- a top-level `issues` entry for a task requirement the slice leaves open
  (`window_requirement_unresolved`), and
- a finding with status `unresolved`, or with its own `issues` (`unresolved_finding`).

`finalize_document_analysis_result` made the whole analysis `partial` whenever any issue or
any unresolved candidate existed. So the model doing what it was asked (stating that the
source does not settle something) was treated the same as unread sources or a finding whose
evidence could not be located.

Of 9 partial analyses on 0.261.476, all had complete coverage; 8 had a slice-level
statement, 6 a finding-level one, and 3 had a finding the validator could not accept.

## Change

When every source was read, a gap the model states is a result of the analysis, not
unfinished or rejected work. It is kept with the result, in the model's words, and no longer
makes the analysis partial.

In `functions_document_analysis_results.py`:

- `STATED_GAP_CODES` names the two codes above.
- The analysis is `valid` when coverage is complete, every issue is a stated gap, and every
  unresolved candidate is unresolved only because the model did not conclude it.
- **A finding the model supports, with something it could not settle within it, is kept.**
  Before, one stated issue dropped the whole finding and its supported values with it. Now
  the record keeps its values and evidence and gains `open_issues`: the model's statements.
- A finding the model marks `unresolved` is still **not** a record. Nothing is promoted.
- **The gaps are part of the result.** The validation gains `stated_gaps`, one entry per
  statement with its scope (`source`, `finding` for a finding that is not a record, `record`
  for one that is), the file, the finding key, and the statement. It also gains
  `stated_gap_count` and one limitation line.
- Issue messages are still application text only.
- The check `candidate_structure_and_evidence_locations` is `unresolved` only for candidates
  the validator refused.
- The report shows `Not settled:` under a finding that has open issues, and a section
  **Not settled by the sources** for the rest. It is built from the result, so a report
  rendered again from a saved analysis has it too.

In `functions_orchestration_analysis_results.py`:

- Each stated gap becomes a limitation of every output of the analysis step
  (`Not settled by the sources (file, finding): statement`). A step that reads findings or
  records, not only one that reads the report, is given what the sources did not settle.
  At most 8 are listed, each at most 1024 bytes, then a line saying how many more are in the
  report.

In `functions_orchestration_composition.py`:

- A composed result takes the limitations of all its inputs, and a result holds at most 32.
  More than that used to be refused; the list is now cut at 31 with a line saying the rest are
  on the inputs.

Still partial, unchanged:

- any source or slice not read (incomplete coverage);
- a finding with missing or unlocated evidence, an invalid status, identity, values or
  caveats;
- source windows that disagree on a value;
- a record excluded by a declared calculation or a required field.

This is the shared validator, so it applies to document analysis in chat and workflows as
well as in orchestration.

## What this does not do

- **A kept finding's open issue is free text, and nothing ties it to one value.** The step
  that writes the answer is given it. A calculation over the records' values is not stopped
  by it, so a value the model had doubts about can be summed. The limitation on the result
  says so in the model's words, and that is the only guard.
- The records projection (values only) does not carry `open_issues`; its limitations do.
- Diagnostics are still audit-only and are not model input.
- What the model wrote in these statements on the deployed application has not been read:
  the text is not logged. The change rests on the codes and counts.

## Files modified

- `application/single_app/functions_document_analysis_results.py`
- `application/single_app/functions_orchestration_analysis_results.py`
- `application/single_app/functions_orchestration_composition.py`
- `application/single_app/config.py`
- `functional_tests/test_document_analysis_evidence_matching.py`
- `functional_tests/test_document_analysis_final_results.py`
- `functional_tests/test_document_analysis_observation_identity.py`
- `functional_tests/test_orchestration_document_derivation_reliability.py`
- `functional_tests/test_orchestration_server_continuation.py`

## Validation

- `test_a_gap_the_analysis_states_is_reported_and_does_not_make_a_full_read_partial`: a
  finding issue, an unresolved finding and a slice issue each give a valid analysis with the
  gap in `stated_gaps`. The finding with an issue is a record with `open_issues`; the
  unresolved finding is not a record.
- `test_a_stated_gap_never_excuses_unread_sources_or_rejected_findings`: an unread slice, a
  finding with no located evidence, and a supported finding that is refused still give
  `invalid` and `partial`, and no record.
- `test_recovery_revisits_malformed_producer_and_a_stated_gap_needs_no_retry`: an
  orchestration run whose finding has a stated issue completes and publishes its document.
  The composing step reads findings, not the report, and is given the statement both on the
  finding and as a limitation.
- `test_stated_gaps_reach_every_reading_step_as_bounded_limitations`: the limitation lines,
  their size bound, and the cut at 8.
- Eight existing tests asserted the previous rule and were updated to the new one. Cases
  that stay partial (invalid caveats, wrong window, missing evidence, invalid status) are
  still asserted partial.

Before: full read, model states a gap, analysis `partial`, run ends partial.
After: full read, model states a gap, analysis `valid`, supported findings kept, the gap
stated to every step that reads the result.

Not run against the deployed application.
