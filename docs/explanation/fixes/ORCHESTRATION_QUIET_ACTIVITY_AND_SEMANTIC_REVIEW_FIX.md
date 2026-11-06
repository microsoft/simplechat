# Quiet activity and semantic answer review (v0.261.416)

Fixed/Implemented in version: **0.261.416**
(`application/single_app/config.py`).

## Issue and root cause

Two investigated runs prepared source findings but failed answer checking with
`completeness_requirements_changed`. The assessment parser compared requirement
descriptions verbatim, so a checker could reject a paraphrased checklist without
establishing a defect in the answer. The public failure incorrectly suggested
model availability, access, or context limits.

The main conversation also exposed operational controls and diagnostics instead
of a compact account of progress. Clarification forms stayed large during
replanning, and conversation attachments were not consistently resolved before
asking for a source. Excel annotation requests could take a tabular path that
did not hand off the existing native Notes/threaded-comment evidence.

## Assessment and correction

`functions_task_completeness.py` keeps assessment identifiers and transport
structure strict, but joins returned judgments to canonical descriptions.
Requirement descriptions may be paraphrased; identifiers cannot be added,
removed, or replaced during reassessment. The checker evaluates the full approved
request and evidence, not a word-similarity score. Equivalent wording is allowed;
missing obligations, unsupported positive claims, contradictory values, and
explicit exact-output constraints still matter.

Content preparation, required output validation, and optional semantic review
have distinct persisted version-2 report stages. Each new stage identifies its
owner and candidate revision. Public projections omit candidates, prompts, and
raw evidence. Version-1 reports remain readable without inventing stage history.
The classic workflow outcome also accepts both report versions, so shared
version-2 assessments do not disappear from its saved results.
Model-assisted review is not a guarantee of factual correctness.

One malformed assessment can be repaired before the answer is changed. A
repairable content failure instead supplies the current answer, original scope,
immutable contract, authorized evidence, actual findings, and prior diagnoses to
the correction request. JSON-schema feedback includes the affected path,
constraint, expected value/type, and observed type. Changed answers undergo fresh
required validation and applicable semantic review.

Format and semantic correction share the existing allowance: normally two
corrections, with an explicit administrative zero preserved. Reservations are
saved before provider calls; interrupted calls are not automatically replayed.
Unchanged corrections stop without a blind retry. Private checkpoints retain
candidate revisions and findings, while public progress carries only the
allowlisted report.

An eligible explicit retry of a failed composition reopens its retained
candidate and diagnosis instead of generating an unrelated replacement.
Execution-plan bindings and the checker identity still bind the scope, contract,
evidence, policy, and original candidate. Changed context blocks reuse; it does
not silently reset the allowance. Existing file-specific recovery remains
separate, and external operations are not replayed to correct prose.
The server advertises **Retry check** only for eligible prepared-content checking
recovery. If that retry loses its retained candidate checkpoint, it refuses the
attempt rather than silently generating a replacement answer.

## Optional review and user experience

The plan's **Auto / On / Off** semantic-review choice goes through existing
revision and approval validation. Auto retains default-on review of substantive
prepared content. On cannot override administrative disablement. Off skips
optional semantic review, not required schema/output checks, current access,
provenance, or safety checks. A failed elected check never silently switches Off
to release an answer.

The V2 conversation uses Quiet activity rather than an execution dashboard.
Detailed stages and diagnoses belong in plan/run inspection. Preparation can be
shown as finished while checking still needs attention; an unavailable checker
does not imply that source work never ran. Stop remains in the composer.
Answered clarification forms collapse without discarding recoverable drafts.

## Image and workbook source handoff

The planner receives an authorized conversation-attachment inventory instead of
mistaking an existing image for a missing source. When saved extracted text is
absent, source gathering passes the actual image bytes through the existing chat
vision helpers and the run's authorized answer-model invocation. Access, masking,
attachment linkage, and revision are rechecked before and after reading.
Unavailable bytes and models without vision support fail explicitly; they do not
become a fabricated transcription. No separate OCR tooling was added.

Native workbook annotation routing reuses existing Excel inspection rather than
inventing another parser. Notes and threaded-comment records retain available
authors, replies, timestamps/status, saved cell values, pagination coverage, and
citation lineage. Native inventory requires a workspace-backed workbook, and
resource-limited results remain explicitly partial.

See [Review and edit orchestration plans](../../guides/review-and-edit-orchestration-plans.md)
and [Chat interface controls](../../reference/chat-controls.md).

## Validation and limitations

Regression coverage includes:

- `functional_tests/test_task_completeness_engine.py`: paraphrased descriptions,
  unchanged obligation identities, shared correction budgets, actual correction
  feedback, no-progress termination, persisted revisions, report repair,
  interruption, and historical projections.
- `functional_tests/test_task_completeness_runtime.py`: real composition/workflow
  wiring, concrete schema feedback with semantic review Off, failure publication
  gates, durable checkpoints, and checking-only retry without regeneration.
- `functional_tests/test_orchestration_plan_schema.py` and
  `test_orchestration_plan_revision_store.py`: validated review choices and
  rejection of unknown steps, unsupported modes, and non-content targets.
- `ui_tests/test_v2_orchestration_quiet_activity.py` and the existing recovery,
  inline Microsoft 365 approval, and Microsoft 365 recovery suites: compact
  activity, question retirement, stage inspection, review controls, and retained
  approval/retry safeguards. The combined selection passed 84 tests.
- `ui_tests/test_task_completeness_ui.py`: historical report inspection and
  inert text rendering of classic workflow outcomes for both report versions.
- `functional_tests/test_orchestration_attachment_native_evidence.py`: real HTTP
  planning/execution with actual decoded PNG pixels reaching the simulated
  provider, retained transcription inputs, native annotation evidence, missing
  bytes, vision capability, and masking before/during reading. The attachment,
  selected-source, search-integrity, source-kind, and current-turn vision
  selection passed 115 tests; the attachment suite also passed 21 tests with
  Cosmos network access blocked.

The V2 typecheck and production build passed. Quiet activity was visually
inspected at 1440px in light mode and 390px in dark mode without overflow.
An older Composer script still expects a public-source tooltip that had already
changed before this fix; that unrelated assertion and its missing endpoint stub
were left unchanged.

Scripted model responses establish control flow and contract behavior, not an
empirical semantic-accuracy score. Source extraction remains limited to the
authorized material and recorded coverage; unread material cannot certify a
positive fact. No deployment or replay of the investigated production runs is
performed by this change.
