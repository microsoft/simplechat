# Selected-document orchestration planning recovery (v0.261.413)

Fixed/Implemented in version: **0.261.413**, recorded in
`application/single_app/config.py`.

## Issue and root cause

Document-backed turns could finish upload/source preparation but stop with
"The request could not be planned" before a plan or execution existed. Two
distinct boundaries were involved:

- The Analyze contract advertised independent version and mode choices that its
  semantic normalizer could reject in combination. The `analysis_options_invalid`
  category was not included in the existing correction path.
- A normalized plan omitting selected documents or positive operations was checked
  after leaving the correction loop. That guard correctly prevented silent source
  loss, but its generic rejection could not be corrected and lacked a specific
  rule or proposal attempt.

The Analyze interface was introduced in
[#1874](https://github.com/microsoft/simplechat/pull/1874). Its observation-identity
fix remains necessary; the missing schema/recovery integration is corrected here.
The selected-source guard predates that change.
[#1875](https://github.com/microsoft/simplechat/pull/1875) improves later retained
result and narrative delivery, which cannot help a turn rejected before planning
finishes. This fix preserves both improvements rather than rolling them back.

The deployed diagnostic category did not retain the raw model proposal. It is not
proof of which invalid option or omitted step the model produced. Local real-module
and authenticated-route reproductions distinguish the rejected proposal from a
normalization change; new debug diagnostics make that difference observable.

## Extraction, planning, and execution are different

Picking a file supplies a source requirement, not an unconditional Analyze step.
A new upload may undergo OCR/extraction, image enrichment, chunking, and indexing.
Before planning, a selected spreadsheet can have a bounded schema/sample preview.
The planner then proposes JSON and the server validates it. Only a valid, approved
plan reaches adapters such as `run_document_analyze`; automatic approval still
happens after validation.

`analysis_options` describes result semantics, not an administrator switch. New
ordinary narrative steps receive observation defaults when options are omitted.
Explicit v2 observations require a compatible version/mode and cannot demand
reconciled fields/calculations. Legacy options and existing edited plans keep
their established meaning.

## Technical changes

`functions_orchestration_registry.py` now expresses version/mode dependencies and
observation restrictions in the advertised schema, with complete v2 examples.
`functions_document_analysis_results.py` preserves strict `ValueError` compatibility
while attaching application-owned rejection rules, without retaining supplied
values. `functions_orchestration_schema.py` preserves the dedicated Analyze error
across both schema and semantic validation and classifies source/operation
omissions separately.

`functions_orchestration_planner.py` validates selected requirements inside the
existing correction loop. Targeted feedback preserves every selection and asks
for compatible, explicit source bindings. All repairable categories share
`PLAN_REPAIR_ATTEMPTS = 1`: a second different error does not start another budget.
An unrenderable clarification stays in that same loop rather than recursively
restarting the planner and resetting its allowance.
The same planner/model is used, and uncorrectable proposals return stable, specific
messages rather than an empty plan, an ungrounded answer, or a silently smaller
selection. Explicit later editor narrowing remains visible for review.

Canonical source accounting, authorization, source-kind checks, native Excel
comment evidence, partial-information narrative behavior, and complete-data
requirements are not bypassed. A limited preview is not a missing file and does
not require a blanket re-upload. No new extraction engine, route, setting,
dependency, cloud service, or deployment is introduced.

## Debug diagnostics

The existing debug switch gates content-free input/proposal/default/normalized/
validated snapshots in both console and Application Insights. They record hashed
source/step identity, effective source counts, normalization differences, binding
fingerprints, option-shape flags, exact owned rejection rules, and the shared
attempt budget. Initial invalid proposals remain observable before defaults.

`functions_appinsights.py` narrowly preserves three validated SHA-256 properties
through real logger serialization: document ID, document set, and planner binding.
It does not broadly allow arbitrary diagnostic text. Detail snapshots have explicit
32-entry source/step bounds with omitted counts; totals remain complete.

Raw IDs, document text, filenames, prompts, model replies, arbitrary option values,
settings, URLs, credentials, and provider exception text are excluded. Debug-off
behavior retains concise correction/failure events without detailed snapshots.
See [selected-document planning diagnostics](../../reference/logging-tags.md#selected-document-planning-diagnostics)
for event names, properties, and a bounded query.

## Validation and before/after behavior

`functional_tests/test_orchestration_document_planning_recovery.py` uses the real
request/context/planner/validator/logger boundaries with external I/O isolated.
It covers PNG, PDF, DOCX, CSV and XLSX selections, manual/automatic approval,
Auto routing, correctable and terminal option/source failures, mixed errors
sharing one correction, implicit scoped search, multiple/disabled sources, source-free
controls, existing-plan narrowing, legacy semantics, explicit requirement bounds,
provider failures, and debug privacy/gating/serialization.

| Before | After |
| --- | --- |
| A selected source omitted by the proposal stopped planning immediately. | A specific source/operation rule requests correction within the existing budget. |
| Incompatible Analyze semantics were advertised as valid and then rejected without correction. | The schema expresses compatible declarations; strict rejection retains its rule and can be corrected. |
| A different validation failure could not be diagnosed from a generic message. | Debug snapshots identify source coverage and the rejecting owner without private payloads. |
| Upload extraction or preview reads could be confused with Analyze execution. | Regression coverage proves planning does not invoke an execution adapter, even with automatic approval. |

Related existing suites cover observation identity, native analysis consumption,
selected-source preparation, debug logger privacy, and native Excel comment
evidence. The new tests are behavioral; they do not assert an exact current app
version or substitute schema-text checks for the actual planner boundary.

These are offline contract and route reproductions, not a live model success-rate
claim. The original deployed proposal remains unknown until a separately
authorized instrumented reproduction is collected. Azure configuration and live
conversations are not modified by this implementation.

### Executed checks

Before updating to the guided-question base, the combined picked-document,
observation-identity, internal-analysis, selected-source-planning, and
available-information selection passed **214 tests**:

```powershell
python -m pytest -q -p no:cacheprovider --disable-warnings --tb=short --show-capture=no .\functional_tests\test_orchestration_document_planning_recovery.py .\functional_tests\test_document_analysis_observation_identity.py .\functional_tests\test_orchestration_internal_analysis.py .\functional_tests\test_orchestration_selected_source_planning.py .\functional_tests\test_orchestration_available_information.py
```

Additional selections passed: the existing bound-model/editor unrenderable-question
regression (**1**), native Excel evidence (**7**), logger initialization/recursion
(**1**), standalone privacy audit (**5**), documentation surface coverage (**7/7**),
and documentation site quality (**6/6**). The whitespace check passed. Selections
are not presented as an aggregate count.

The new Auto-routing HTTP fixture replaces only external Graph profile-photo I/O;
the real routing and user-preference paths run with the offline network guard
still active. No blocked network attempt is suppressed or cleared.

After merging the guided-question base at `bc3d2584e`, the document-planning
regressions and guided-input unit/execution tests passed **79 tests** together:

```powershell
python -m pytest -q -p no:cacheprovider --disable-warnings --tb=short --show-capture=no .\functional_tests\test_orchestration_document_planning_recovery.py .\functional_tests\test_guided_user_input.py .\functional_tests\test_guided_user_input_orchestration.py
```

The version conflict was reconciled at **0.261.413** after the base reached
0.261.412. Documentation surface coverage (**7/7**), site quality (**6/6**) and
the staged whitespace check also passed on the merged tree.

### Existing baseline limitations

The broader existing Ask AI debug/initialization selection reported **84 passed
and 3 failed**. The failures are the conversation-reference operations
`bind_conversation_reference`, `set_task_conversation_references`, and
`unbind_conversation_reference`: their existing diagnostics omit
`sc_assist_operation`. All three reproduce with the unchanged `HEAD` serializer
loaded in memory. This change only adds strictly validated source/binding hash
properties; it does not change or weaken Ask AI's operation allowlist.

Before implementation, the older AST-extracted planner-failure fixture also had
ten setup errors from undefined `STORAGE_FAILURE_CODE`. It was not reported as
passing. The new regressions use real modules/routes and cover their own failure,
provider-error, correlation, and privacy behavior without depending on that
fixture or disabling its checks.
