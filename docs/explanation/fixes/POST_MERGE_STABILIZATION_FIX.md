# Post-Merge Stabilization Fix

## Header Information

- Status: **0.261.430 live retested; remaining staging failures and configuration blockers**
- Initial version implemented: **0.261.429**
- Corrective implementation: **0.261.430**
- Prepared: 2026-11-16
- Latest live validation: **2026-11-17 UTC**
- Related plan:
  [Post-Merge Stabilization and V1/V2 UI Parity Plan](../features/POST_MERGE_STABILIZATION_AND_UI_PARITY_PLAN.md)
- Related issue:
  [microsoft/simplechat#1928](https://github.com/microsoft/simplechat/issues/1928)

The .429 implementation and live evidence below remain historical. The .430
sections distinguish local implementation checks from the subsequent actual
staging retest. The admin deployed .430; staging sign-off remains withheld.

## Issue Description

The reviewed merge preserved the custom-endpoint and Development feature sets,
but staging exposed several integration defects:

- embedding-only models reached V1 and V2 chat pickers;
- V2 discarded partial output when Stop detached the reader;
- custom endpoint workflow failures could enter recovery without a durable,
  safe diagnostic;
- CSV analysis accepted Excel selector arguments and repeatedly retried them;
- duplicate Responses tool calls could execute the same action more than once.

## Root Cause

The merge had retained parallel implementations or missing cross-layer
contracts:

- `route_frontend_chats.py` shadowed the shared filtered chat catalog with an
  unfiltered local implementation.
- V2 treated Stop primarily as transport detachment and only retained ordinary
  partial text for admitted retry presentations.
- Workflow policy classification recognized application policy errors but not
  safe model-provider rejections and diagnostics.
- Tabular tools advertised Excel selectors for every tabular format, then
  rejected those values after the CSV source was selected.
- Responses conversion preserved duplicate function-call items, so downstream
  Semantic Kernel invocation could execute the same call twice.

## Technical Details

### Files Modified

- `application/single_app/functions_chat_model_catalog.py`
- `application/single_app/route_frontend_chats.py`
- `application/v2_ui/src/stores/chatStore.ts`
- `application/v2_ui/src/components/chat/MessageList.tsx`
- `application/single_app/functions_model_endpoint_diagnostics.py`
- `application/single_app/functions_workflow_policy_errors.py`
- `application/single_app/functions_workflow_execution.py`
- `application/single_app/functions_workflow_structured_execution.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/model_responses_chat.py`
- `application/single_app/config.py`

### Code Changes

1. V1 and V2 now use the shared capability-filtered model catalog.
2. Legacy, global, personal, and group catalogs use the same chat eligibility
   predicate.
3. V2 Stop stores a provisional interrupted assistant message with safe
   partial text, reasoning entries, and stable reconciliation identity.
4. Stop before the first token locally marks the originating user turn
   interrupted without creating a blank assistant bubble. The live retest
   found that this state does not survive reload or guarantee cancellation.
5. Recognized provider/configuration rejections receive a typed terminal or
   retryable classification. The live adapter and UI coverage gaps below
   prevent treating this as complete across all workflow paths.
6. Provider diagnostics contain only stable public messages and correlation
   references.
7. CSV boundary handling normalizes or non-retryably rejects Excel-only
   selectors. End-to-end TSV and advertised-schema coverage remain unverified.
8. Tabular auto-tool work is capped across the complete request and deduplicates
   re-read invocation records.
9. Responses function calls are deduplicated before tool dispatch.

## Corrective Tranche: 0.261.430

Fixed/Implemented in version: **0.261.430**.
Related config.py update: `VERSION = "0.261.430"`.

### Implementation

- Ordinary sends reuse retry's `submission_id`, thread/attempt metadata and
  server-created message IDs. Mismatched retry submission IDs are refused
  without consuming the correct prepared attempt.
- `ChatAttemptStore` conditionally serializes cancellation and completion in
  the existing destination-control container. Because messages are in another
  container, committed output is recoverably and idempotently materialized
  from an outbox. No cross-container transaction or Redis linearizability is
  assumed; storage failure is not acknowledged from local state.
- Pre-admission collaborative Stop authorizes membership before storing an
  actor-scoped intent against the public destination. Only that generating
  actor's submission is affected. Its hidden source is bound on admission;
  no caller-supplied operator identity is trusted.
- Replay/cache keys, cancellation, reconciliation and history use exact
  submission/message/thread/attempt identity. Terminal status checks consult
  Cosmos. V1/V2 render persisted and legacy interruption flags without a data
  migration; uncertain cancellation and provider interruption are not presented
  as confirmed user Stop. Safety replacements retain the attempt binding.
- Capability errors name the required capability and validation stage. Empty
  Auto function choice is not treated as an actual required tool. Real required
  tools, selected endpoint/model/protocol and APIM paths are preserved.
- Completeness uses native JSON where supported, otherwise prompted JSON on
  the same route, with the existing strict closed schema, bounded
  candidate-only repair/correction/checkpoint engine. Invalid or unavailable
  checking never publishes a false complete result.
- Narrow native SDK and legacy Anthropic boundaries preserve observed numeric
  status, exception type, protocol, stage and safe correlation. They do not
  serialize provider bodies, headers, URLs or continuation state.
- A later request rejection cannot erase earlier effects. Tool-result history
  and existing execution-journal uncertainty prevent automatic effectful
  replay. Safe pre-effect transients retain bounded retries.
- Legacy task history, structured execution/attempt history and runtime gates
  show allowlisted diagnostics without requiring an artifact. Missing results
  retain failure HTTP semantics and machine-readable reasons. Absent excerpts
  are not fetched; structured results use exact execution/attempt routes.
- The Cosmos test runtime now defaults to the installed SDK's `CosmosDict`,
  retaining ETags, partitions and atomic batches. A reproduced Python 3.13 AST
  formatting difference was corrected in the inventory checker without
  weakening review rules or changing CI definitions.

### Proven Causes and Limits

Local red/green regressions reproduced pre-admission Stop returning 404,
unnamed capability rejection, known-unsupported JSON request construction,
legacy Anthropic status flattening, unclassified genuine native SDK failures,
missing failure fields in structured projections and misleading artifact
unavailability. Browser regressions exercise actual persisted history API
payloads, fresh reload and a later turn, as well as failed Stop acknowledgments
and text-only diagnostic rendering.

The exact .429 registry miss/older-reply presentation sequence, the deployed
Claude missing capability and the isolated workflow's real provider status
remain unproven. No capability flags were flipped to conceal those
uncertainties, and no staging success is asserted.

### Validation Ledger

Focused commands and final results are recorded below after the implementation
is frozen. The inherited full-suite baseline remains **exit 2, 80 collection
errors, 17 warnings, no executed tests (54.69 seconds)**. The coordinator retains
the baseline XML and owns the identical post-change comparison.

The Cosmos inventory refresh revealed inherited stale reviews and module-wide
invalidations from corrective edits. These are not silently approved or excluded. A
blocked inventory gate is not a passed contract suite; any broader baseline
review requires coordinator disposition.

#### Reproduction Evidence

| Regression | Before corrective code | Local result after correction |
|---|---|---|
| Real pre-admission cancel route | HTTP 404 instead of accepted intent | Accepted actor/submission intent; real generator barriers prevent producer preparation |
| Required capability / JSON selection / legacy Anthropic | Nine focused failures: unnamed capability, invalid native JSON shape, status/body flattening | Corresponding set passed; full protocol suite subsequently passed 64 tests |
| Genuine native SDK invocation | Fourteen focused failures: definitive errors entered recovery; 429/503 did not retry; effect diagnostics absent | Corresponding set passed; native SDK defaults and journal/prior-tool effect coverage retained |
| Failure history / unavailable artifact | Four focused failures: missing typed fields and unavailability reasons | Final result route/projection suite: 32 passed, including modern non-durable failures and genuine legacy previews |
| Lost user acknowledgment with a later turn | Browser placed retained partial after the later answer | Exact submission/actor reconciliation; final browser suite: 27 passed |
| Python 3.13 inventory serialization | Focused digest regression failed; unchanged reviews invalidated | Preserve empty AST fields; retain original reviews only for exact unchanged boundaries |

These are local reproductions, not proof of the incident-specific .429 timing
sequence or of a deployed provider's missing capability/status.

#### Reproducible Commands

All commands use the actual repository, not the nominal Azure SDK workspace:

```powershell
Set-Location 'C:\Repos\simplechatmsft'
$Py = 'C:\Repos\simplechatmsft\.venv\Scripts\python.exe'
$env:PYTHONPATH = 'C:\Repos\simplechatmsft\application\single_app;C:\Repos\simplechatmsft\functional_tests;C:\Repos\simplechatmsft'
$Safe = @('-p', 'test_support.cosmos_network_guard', '-p', 'no:cacheprovider', '-q', '--tb=short', '--disable-warnings')
```

Initial-handoff Stop/retry/SDK/checker/local-CSP group:

```powershell
& $Py -m pytest @Safe functional_tests/test_chat_stream_stop_control.py functional_tests/test_chat_retry_attempt_lifecycle.py functional_tests/test_cosmos_contract_runner.py functional_tests/test_chat_local_openlayers_assets.py
```

Fresh-process model, completeness and result-history groups:

```powershell
& $Py -m pytest @Safe functional_tests/test_model_endpoint_protocol_inference.py
& $Py -m pytest @Safe functional_tests/test_task_completeness_runtime.py
& $Py -m pytest @Safe functional_tests/test_workflow_result_routes.py
```

Workflow execution/journal/history/access group, **including** the inherited
hard-coded access-count guard:

```powershell
& $Py -m pytest @Safe functional_tests/test_workflow_policy_failures.py functional_tests/test_workflow_durable_execution.py functional_tests/test_workflow_runtime_store.py functional_tests/test_workflow_structured_flow.py functional_tests/test_workflow_history_source_access.py functional_tests/test_workflow_access_controls.py
```

Preserved routing, Claude, Responses/action and meaningful CSV coverage:

```powershell
& $Py -m pytest @Safe functional_tests/test_analyze_compare_claude_workflow_stream.py functional_tests/test_responses_model_tool_execution.py functional_tests/test_chat_explicit_model_routing.py functional_tests/test_tabular_csv_selector_contract.py
```

Browser tests use local static servers, the repository page fixture, isolated
backend I/O and installed-SDK storage defaults. They do not use the socket
guard that would prevent local browser transport:

```powershell
& $Py -m pytest -p no:cacheprovider -q --tb=short --disable-warnings ui_tests/test_v2_stream_stop_partial.py ui_tests/test_chat_stream_stop_button.py ui_tests/test_v2_workflow_durable_runtime.py ui_tests/test_v2_workflow_control_runtime.py
```

Frontend, route and storage guards:

```powershell
Set-Location 'C:\Repos\simplechatmsft\application\v2_ui'
npm run typecheck
npm run build
Set-Location 'C:\Repos\simplechatmsft'
node --check application/single_app/static/js/chat/chat-streaming.js
node --check application/single_app/static/js/chat/chat-messages.js
& $Py functional_tests/route_tests/test_route_blueprint_policy_inventory.py
& $Py functional_tests/route_tests/test_route_unauthenticated_policy_contract.py
& $Py functional_tests/route_tests/test_route_policy_test_coverage.py
& $Py scripts/check_cosmos_response_boundaries.py --refresh
& $Py scripts/check_cosmos_response_boundaries.py --run-contracts
```

Additional docs/local-assets selection:

```powershell
& $Py -m pytest @Safe functional_tests/test_docs_app_surface_coverage.py functional_tests/test_docs_site_quality.py functional_tests/test_v2_ui_local_assets.py functional_tests/test_chat_local_openlayers_assets.py
```

The official `check_xss_sinks.py` and `check_broken_access_control.py`
`inspect_file` entry points were run against `git diff --unified=0 HEAD`
added-line sets, with untracked application files inspected in full. This
preserves CI inspection logic without staging or manufacturing commits.
The final-source repeat checked **35 XSS files / 22 Python access-control
files, zero findings**, exit 0.

The route-policy scripts passed **15/15, 10/10 and 3/3**. V2 typecheck/build
passed, retaining only the existing Vite large-chunk warning. Editor diagnostics
reported no errors in the checked changed Python/TypeScript files. Final
run totals and remaining failed gates are recorded below.

#### Initial .430 Handoff Results (Before Independent Lifecycle Review)

| Selection above | Result |
|---|---|
| Stop/retry/SDK/checker/local-CSP group | **61 passed**, exit 0 |
| Protocol and real adapter boundaries | **64 passed**, exit 0 |
| Real-module completeness engine | **47 passed**, exit 0 |
| Workflow result routes/projections | **32 passed**, exit 0 |
| Claude/Responses/routing/meaningful CSV preservation | **55 passed**, exit 0 |
| Workflow execution/journal/history/access group | **135 passed, 1 failed**, exit 1; retained access-count assertion below |
| Final browser suites, including lost acknowledgment | **27 passed**, exit 0 |
| V2 typecheck/build | Passed; existing large-chunk warning retained |
| Changed V1 JavaScript `node --check` | Both passed |
| Three route-policy scripts | **15/15, 10/10, 3/3**, all exit 0 |
| Docs/site quality/local browser assets | **21 passed**, exit 0 |
| Official added-line XSS / access inspectors | **35 / 22 files, zero findings**, exit 0 |
| Whitespace / Git state | `git diff --check` passed; staged paths empty; HEAD `864bfe8eb`, branch `feature/customendpoints` |
| Cosmos review / guarded contracts | Exit 1; **595 review gaps**, contract child not executed |

This is not a green full suite. The inherited root collection gate and the
specific retained review/access-test gates remain open.

At this initial handoff, the affected-owner review and independent root-suite
comparison were still pending. The 595 gaps were not wholly inherited: 162
messages represented 81 pending owners in the five .430-edited files. The
follow-up below records their in-scope review and the lifecycle corrections.
Deployment and live retesting still require separate permission.

#### Retained Validation Gates

- The Cosmos review gate reported **1,109 owners, 428 doubles and 595 review
  gaps**. There are **266 review-required owners and four review-required
  doubles**, including inherited merge staleness and module-wide invalidations.
  At that point, only the explicitly reviewed subset had installed-SDK runtime
  evidence; all 81 affected-file pending owners were not yet complete. The
  guarded contract child did not run when review validation failed.
- The legacy workflow-access wiring test expects **14** personal workflow
  gates. Read-only comparison found **33 in HEAD and 33 in the working tree**.
  No routes were added by this tranche. The three dedicated route-policy
  inventories pass; the stale assertion remains visible for coordinator
  disposition rather than being weakened to manufacture a green result.
- A structural dispatcher fixture omitted the real completeness-policy
  dependency and passed `{}` instead of its already-declared
  completeness-off fixture settings. Its namespace/settings binding was
  corrected; production defaults remain enabled and independently covered by
  the real-module completeness suite.
- An old local-assets test asserted exact application version `0.242.053`.
  It now uses the repository's minimum-version helper; all CSP/local-asset
  assertions remain intact.
- The terminal executable reported **Python 3.13.17** although initial tool
  selection reported 3.13.14. The same supplied venv executable was used; no
  interpreter or dependency installation was performed.

### Independent Lifecycle Review Follow-up (.430)

The coordinator explicitly unfroze this same approved lifecycle/validation scope
after independently reproducing the initial focused results. No second design,
new Azure resource, deployment, release-note update or version change was
authorized or performed. The sole implementation owner made these corrections.

#### Proven Causes and Corrective Behavior

| Finding | Failing production-owner evidence | Correction |
|---|---|---|
| Admitted, undispatched question-write failure | Repeating the identical request raised `retry_already_submitted`; history did not recover its prepared question. A shared HTTP repetition created two public questions and no reply. | Recover the exact admitted request fingerprint and original server question/reply IDs. History materializes prepared questions without dispatch. The shared bridge reuses the recorded public question rather than generating a conflicting request fingerprint. Dispatch still requires its one-time CAS. |
| Shared committed outbox lost after crash/write failure | Authorized shared history returned zero answers for both generating owner and collaborator; the control partition was the public destination, not the hidden source. | Query the verified canonical partition and recorded source binding. Recheck current viewer membership and both source relationship directions. Materialize committed output only; actor-scoped cancellation/execution authority is unchanged. Source and public publication have separate durable acknowledgments. |
| Settled interruption/deletion causes perpetual recovery | Three settled deletion variants returned history HTTP 503; interrupted records were revisited regardless of acknowledgment. | Track applied question state and settled publication. Select only pending work, honor intentional soft/hard deletion, and retain errors for unexpected pending-outbox storage failures. No deletion is repaired by recreating a settled message. |
| Late partial reactivates an older attempt | A's canceled partial remained active after B preparation. An additional red test showed deletion-based promotion could miss a concurrently created answer. | Derive publication visibility from the current question. Conditional question replacement plus reply create are one message-partition transaction; retry preparation, carousel selection and deletion promotion use that same ETag fence and requery on conflicts. |
| Duplicate publisher replaces legitimate mutation | Two materializers observed absence; the stale publisher undid a soft delete, edit, or hard delete through a fresh-ETag replacement. | Publication is create-only. A receipt on the existing question is atomic with reply creation and survives answer hard deletion. Existing reply conflicts verify immutable identity and retain body/metadata/retraction/deletion changes; no mutating legacy publisher is called. |

Controls and messages remain in different existing containers. The terminal
control decision plus its recoverable outbox is **not** described as a
cross-container transaction. Native question/reply publication and public
question/reply publication each use their actual co-partitioned message batch.
The existing actor/submission/thread/attempt identity is reused throughout; the
public copy ID derives from the existing destination/source message IDs.
After-dispatch upstream compute cessation remains best effort.

#### Red/Green Evidence and SDK Review Scope

- Initial lifecycle red run: 13 failed / one passed. Two retry fixture failures
  were missing `conversation_id`; after correcting only that fixture, all three
  selection cases were rerun red, including the observed `active_thread=True`
  failure. Admission, shared recovery, settled deletion and mutation-loss
  failures were already genuine production-owner failures.
- Separate shared HTTP admission and deletion-promotion regressions were red
  before their respective production corrections.
- Intermediate corrected lifecycle/Stop/retry/checker selections passed 77 and
  then 113 cases. Deletion preservation, its SDK-default fixture migration and
  promotion/publication validation passed four cases, including the existing
  normal/optimized subprocess probes.
- The real generator now consumes an installed-SDK retry question in both
  pre-provider and simulated partial-provider cancellation paths. Its actual
  cancellation finalizer persists the safe partial and stopped state.
- All original **81** pending owners received consumer-specific review, not
  function-fingerprint approval. With the five previously classified entries
  and three new shared recovery/admission scopes, the five edited modules now
  contain **89 reviewed owners**. The chat-attempt module has **17** reviewed
  boundaries; the 12 prior runtime-store/journal reviews remain in scope.
- The exact affected SDK selection covers **118 owners plus four doubles**:
  **71 inventory selectors, 229 tests passed**, exit 0. Query/scalar consumers,
  Mapping consumers, normalized strict copies and unused write responses have
  separate specific contracts and real-owner evidence. Workflow route-loader
  evidence now imports the real route module instead of relying on AST copies.
- Three changed chat/deletion doubles use installed `CosmosDict` defaults,
  retained ETags/partition checks and SDK-formatted atomic batches. The two
  obsolete chat/deletion legacy-inline exemptions were removed, not expanded.
- The **185 unrelated owners and four unrelated doubles were not reviewed,
  repaired or waived**. Their sorted semantic inventory snapshot hash stayed
  `ddccd5b0e7b237ce153f6e84714bd12d7c25a1b8db0ba008b1b7993d96744f03`.
- Final global gate: **1,114 owners / 429 doubles / 433 review messages**,
  exit 1. These are 189 missing classification/contracts, 189 missing evidence
  messages, one stale legacy-double exemption and 54 stale source-only reviews.
  The global guarded contract child **did not execute**. The successful scoped
  execution is a separate command, not a bypassed or passing global child.

#### Warning Attribution

Repeating the original 61-case selection reproduced **25,568 warnings**.
**25,519** came from legacy `ast.Num`, `ast.Str` and `ast.NameConstant`
references in unchanged `swagger_wrapper.py`; the rest were existing
dependency/timestamp deprecations. A direct fingerprint-helper probe emitted
zero warnings. The added warning regression preserves the existing Python 3.13
empty-field digest contract without suppressing warnings or modifying unrelated
Swagger/dependency code. Expanded route selections naturally register more
routes and therefore report more of those same warnings.

#### Exact Follow-up Validation Commands

The existing executable and the `@Safe` arguments defined above were reused.
Machine-readable reports are under:

```text
C:\Users\nadoyle\.copilot\session-state\33ce100d-60b8-42be-84ee-7de961f33e13\files
```

The report variable in the commands below names that existing directory:

```powershell
$Reports = 'C:\Users\nadoyle\.copilot\session-state\33ce100d-60b8-42be-84ee-7de961f33e13\files'
```

Failing-first commands (each used the Cosmos network guard and no pytest cache):

```powershell
& $Py -m pytest @Safe functional_tests/test_chat_stream_stop_control.py -k 'undispatched_admission or recovers_prepared_question or shared_history_recovers_canonical or settled_interruption_history or late_stopped_partial or selection_and_late_publication or duplicate_outbox_materialization' --junitxml="$Reports\corrective-430-lifecycle-review-red.xml"
& $Py -m pytest @Safe functional_tests/test_chat_stream_stop_control.py -k 'late_stopped_partial or selection_and_late_publication' --junitxml="$Reports\corrective-430-selection-review-red.xml"
& $Py -m pytest @Safe functional_tests/test_chat_stream_stop_control.py::test_shared_stream_resumes_exact_undispatched_admission_without_another_public_question --junitxml="$Reports\corrective-430-shared-admission-red.xml"
& $Py -m pytest @Safe functional_tests/test_chat_stream_stop_control.py::test_deleted_attempt_promotion_and_late_reply_share_the_selection_fence --junitxml="$Reports\corrective-430-selection-promotion-red.xml"
```

The exact affected SDK selector extraction and execution was:

```powershell
$selectorJson = @'
import json,pathlib
m=json.loads(pathlib.Path('functional_tests/cosmos_response_boundaries.json').read_text(encoding='utf-8'))
files={'application/single_app/'+name for name in ('functions_chat_retry.py','functions_workflow_runner.py','functions_workflow_runtime_store.py','functions_workflow_journal.py','route_backend_chats.py','route_backend_collaboration.py','route_backend_conversations.py','route_backend_workflows.py')}
doubles={'functional_tests/test_chat_retry_attempt_lifecycle.py::AttemptContainer','functional_tests/test_chat_soft_deleted_message_visibility_fix.py::FakeContainer','ui_tests/fixtures/chat_stop_runtime.py::StopMessageContainer','functional_tests/test_workflow_durable_execution.py::RuntimeContainer'}
entries=[v for k,v in m['owners'].items() if k.split('::')[0] in files]+[m['doubles'][k] for k in sorted(doubles)]
assert all(e['classification']!='review-required' for e in entries)
print(json.dumps(sorted({t for e in entries for t in e.get('tests',[])})))
'@
$Targets = ($selectorJson | & $Py -) | ConvertFrom-Json
& $Py -m pytest @Safe --junitxml="$Reports\corrective-430-scoped-owner-contracts.xml" @Targets
```

Result: **229 passed**, exit 0. The selector union was 71; no unrelated global
review entry or failing access-count test was changed to achieve this.

Final lifecycle/deletion/checker/CSP selection and separately blocked global gate:

```powershell
& $Py -m pytest @Safe functional_tests/test_chat_stream_stop_control.py functional_tests/test_chat_retry_attempt_lifecycle.py functional_tests/test_chat_soft_deleted_message_visibility_fix.py functional_tests/test_cosmos_contract_runner.py functional_tests/test_chat_local_openlayers_assets.py --junitxml="$Reports\corrective-430-final-lifecycle-sdk.xml"
& $Py scripts/check_cosmos_response_boundaries.py --run-contracts
```

Protocol, completeness, result-route and preservation commands above were
rerun in fresh processes: **64 / 47 / 32 / 55 passed**, all exit 0. The identical
workflow group retained **135 passed / one failed** at
`test_workflow_access_controls.py::test_workflow_access_control_wiring`
(`14` expected, `33` actual); its assertion and HEAD/current route counts remain
unchanged.

The guarded root command was rerun with the original two-directory `PYTHONPATH`
and no warning suppression, changing only the output XML filename to
`corrective-430-post-review-root.xml`. Both baseline and follow-up contain
**80 collection-error modules**, no added/removed modules and **zero changed
normalized full-error signatures**. Normalization canonicalized path separators
and replaced only Python source line numbers and object addresses, not exception
content. This agrees with the
coordinator's independent pre-follow-up comparison; neither root run is green.

V2 typecheck/build and both changed V1 `node --check` commands passed again.
Route-policy scripts passed **15/15, 10/10 and 3/3**. Official XSS/BAC
`inspect_file` entry points consumed actual `git diff --unified=0 HEAD` added
lines (and complete untracked application files): **35 / 22 files, zero findings**.
No checker or CI policy was weakened. `git diff --check` passed.

An initial browser validation overlapped the SPA build and reported 24 passes /
three missing-build-artifact failures. That was a validation scheduling error,
not an accepted green result; the complete browser selection was rerun only
after the build finished. Final browser/lifecycle/docs totals are recorded in
the completion block below.

#### Follow-up Completion Results

| Executed selection/check | Final result |
|---|---|
| Full lifecycle/retry/deletion/checker/CSP selection | **119 passed**, exit 0 |
| Exact affected-owner SDK subset | **71 selectors / 229 passed**, exit 0 |
| Installed SDK pin, actual mocked-HTTP point/ETag/partition contracts and shared atomic doubles | **12 passed**, exit 0 |
| Protocol / completeness / result routes / preservation | **64 / 47 / 32 / 55 passed**, all exit 0 |
| Workflow group, including the unchanged access-count guard | **135 passed / one failed**, exit 1 |
| Browser rerun after build completion | **27 passed**, exit 0; 5,328 legacy/dependency warnings retained |
| V2 typecheck/build and both changed V1 syntax checks | Passed; existing Vite chunk-size warning retained |
| Route policy / unauthenticated policy / route-test coverage | **15/15 / 10/10 / 3/3**, exit 0 |
| Official actual-added-line XSS / access inspectors | **35 / 22 files, zero findings** |
| Docs/site quality/local browser assets | **21 passed**, exit 0 |
| Guarded root before/after | Both exit 2, **80 identical collector modules / zero changed normalized full-error signatures** |
| Global Cosmos review/contract gate | Exit 1; **433 unrelated review messages**; global contract child not run |
| Required .430-affected owner/double review gaps | **0** |

The additional installed-SDK API command was:

```powershell
& $Py -m pytest @Safe functional_tests/test_cosmos_document_boundaries.py::test_installed_sdk_matches_the_application_dependency_pin functional_tests/test_cosmos_document_boundaries.py::test_shared_double_point_shapes_query_rows_etags_and_atomicity functional_tests/test_m365_cosmos_sdk_contract.py::test_real_sdk_routes_replacements_from_body_and_preserves_etag functional_tests/test_m365_cosmos_sdk_contract.py::test_real_sdk_point_documents_are_wrapped_but_nested_json_and_query_rows_are_plain functional_tests/test_m365_cosmos_sdk_contract.py::test_real_sdk_returned_write_documents_use_the_same_top_level_wrapper functional_tests/test_m365_cosmos_sdk_contract.py::test_real_sdk_rejects_the_unsupported_partition_keyword functional_tests/test_m365_cosmos_sdk_contract.py::test_other_partition_cannot_replace_an_existing_item --junitxml="$Reports\corrective-430-sdk-api-contracts.xml"
```

Final browser and documentation commands were:

```powershell
# Only after npm run build has finished:
& $Py -m pytest -p no:cacheprovider -q --tb=short --disable-warnings ui_tests/test_v2_stream_stop_partial.py ui_tests/test_chat_stream_stop_button.py ui_tests/test_v2_workflow_durable_runtime.py ui_tests/test_v2_workflow_control_runtime.py --junitxml="$Reports\corrective-430-post-review-browser.xml"
& $Py -m pytest @Safe functional_tests/test_docs_app_surface_coverage.py functional_tests/test_docs_site_quality.py functional_tests/test_v2_ui_local_assets.py functional_tests/test_chat_local_openlayers_assets.py --junitxml="$Reports\corrective-430-post-review-docs-assets.xml"
```

The follow-up modifies four production files only:
`functions_chat_retry.py`, `route_backend_chats.py`,
`route_backend_collaboration.py`, and `route_backend_conversations.py`.
Tests/fixtures changed are `test_chat_stream_stop_control.py`,
`test_chat_retry_attempt_lifecycle.py`,
`test_chat_soft_deleted_message_visibility_fix.py`,
`test_cosmos_contract_runner.py`,
`test_workflow_authoring_sdk_boundaries.py`, and
`ui_tests/fixtures/chat_stop_runtime.py`. The reviewed inventory and these
existing plan/fix documents are the remaining follow-up edits. Earlier approved
.429/.430 changes remain preserved.

Existing reusable evidence files include the failing-first XMLs named above,
`corrective-430-final-lifecycle-sdk.xml`,
`corrective-430-scoped-owner-contracts.xml`,
`corrective-430-sdk-api-contracts.xml`,
`corrective-430-post-review-browser.xml`,
`corrective-430-post-review-workflow.xml`,
`corrective-430-post-review-root.xml`, and
`corrective-430-post-review-docs-assets.xml`. The captured final failed global
gate output is:

```text
C:\Users\nadoyle\AppData\Local\Temp\1794923836336-copilot-tool-output-1188-709b5c5a-5cf3-4046-8fc8-1a3b2d1fb0eb.txt
```

**Historical local closeout, before the live retest below:** local corrective implementation/affected-owner evidence is
complete, not a green repository-wide gate or staging sign-off. The unrelated
433 review messages, unchanged access-count assertion and existing root
collection failure remain visible. Exact .429 staging incident registry/identity
causes, deployed Claude missing capability and isolated provider status still
require separately authorized live evidence. Optional live Responses actions
remain blocked/unauthorized. Version stays **0.261.430**; existing release-note
changes were not touched. No staging, commit, push, deployment, new resources or
live configuration changes were performed.

### Actual Staging Retest: 0.261.430

Fixed/Implemented in version: **0.261.430**.
The existing config.py version remains unchanged by this documentation-only
report. Detailed scenarios, identifiers, permanent configuration and remaining
checkboxes are in the related plan's
[.430 staging retest](../features/POST_MERGE_STABILIZATION_AND_UI_PARITY_PLAN.md#staging-retest-0261430).

The signed-in browser visibly reported .430. App Service was Running on image
`sha256:9674b77ca3945513fc91ccede6ed01053c890bc716239c9be6a391821e48fd69`;
its configured `/external/healthcheck` returned 200. The assistant did not
deploy or restart it.

The live ledger contains **25 check entries: 19 passed, 3 failed, 3 blocked**,
including aggregate/configuration entries. The separate 80 unchanged local
collection errors and 433 untouched Cosmos review messages are not staging
failures, and local passes do not establish live functionality.

| Live behavior | Result |
|---|---|
| Four-model menus, direct chat and all three existing APIM agents in V1/V2 | Passed through visible selections and unique-token responses. |
| V1/V2 ordinary Stop, full reload and later turn | Partial text and accurate stopped label remain, without duplication. |
| Actual pre-token V2 Stop | 200/accepted with matching submission and `dispatch_prevented=true`; no blank/delayed answer or old-reply reassociation on later reloads. Reload wording is generic interrupted/retry. |
| Active navigation detach | One complete 40-item answer and final marker remained after navigating away while visibly streaming. |
| Fresh CSV tools | Actual three-tool computation: total 35, North 18, South 17, rows 3; 12.7 seconds, no selector loop. Expected values were not in the prompt. |
| Claude, chat capabilities Off | Exact durable result and mandatory answer review completed, with zero adjustments. |
| Legacy and structured provider rejection/history | Observed provider 404/NotFoundError, one attempt despite two configured retries, terminal failure and safe diagnostics without a nonexistent-artifact fetch. |
| Known staging Azure Responses | Real V1/V2 inference, incremental Stop, persisted label and later follow-up passed. No live action-execution claim. |

Still failing:

1. Immediate Retry on a newly completed V2 Terra reply requires a reload.
   Retry after reload, edit/resend and intentional partial-message deletion
   work and preserve their route/attempt semantics.
2. Claude Legacy core still rejects the required `toolCalling` capability.
   The useful named diagnostic is a handling improvement, not functional
   core-mode success; the no-tools verifier pass does not replace that gate.
3. Reopening the saved APIM Responses configuration and testing a model returns
   application 409 asking to save changes first, without a provider request.

Still blocked:

- Shared Luna/Terra Responses: read-only discovery proved APIM revision 2 has
  a versioned `/openai/responses?api-version=...` operation, not the application's
  compatible `/openai/v1/responses` path. Direct shared-resource requests still
  return actual upstream 401 after the explicitly approved inference-role
  grant. The remaining authentication cause is unresolved.
- Live Responses actions and true two-authenticated-participant collaborative
  cancellation were not supplied. Local coverage is recorded separately.

The admin requested permanent working Responses configuration, chose a separate
APIM connection after same-model uniqueness validation blocked variants, entered
its key through the protected UI, and authorized direct Foundry fallback.
At the end of that retest, both new connections were retained **disabled**:
`SharedAPIM Responses` and `Shared Foundry Responses (Direct)`.
The explicitly approved **Cognitive Services OpenAI User** assignment is retained
at only the existing shared Foundry account. No broader/admin grant, APIM
operation/policy change or credential extraction was performed during that
original retest.

All 11 disposable conversations, both temporary workflows, the temporary
failure/known-Responses connection and synthetic uploaded/local CSV were removed
and checked. Original connections, model IDs, APIM paths, agents, current
baseline flags and the pre-existing CSV remain unchanged. The default user
model is back to direct `gpt-5.6-terra`, with an empty draft and no generation.
Personal/group workflows were already enabled at this pass's start and remain
enabled; they were not reset to the old .429 baseline.

No application code, application version, release notes or GitHub issues were
changed. No Git staging, commit, push or deployment was performed during this
live pass. Permanent app configuration and the account-scoped role grant above
were separate explicit approvals. Foundry's readiness script installed its
missing evaluations tooling extension; project/Python dependencies were not
changed.

**Disposition: actual staging testing completed; sign-off withheld pending
the recorded failures and configuration/coverage gates.**

### Approved APIM Operation Follow-Up: 2026-11-17

Configuration-only follow-up on **0.261.430**; no application version change.
The admin explicitly requested a compatible Responses operation in the existing
revision, with **no new revision or version**.

Added only `OpenAI_v1_Responses`, `POST /openai/v1/responses`, to
`shared-foundry;rev=2` (ARM HTTP 201). It accepts native Responses JSON and
documents JSON/SSE output, inheriting the existing backend, managed identity
and unbuffered forwarding. Before/after hashes confirmed all 50 revision-1
and 51 pre-existing revision-2 operations and parent policies were unchanged.
Revision 2 now has 52 operations.

After separate approval to enable the saved `SharedAPIM Responses` connection,
both Luna and Terra saved-model diagnostics returned HTTP 200 through the exact
new gateway URL. Visible V1 Luna and V2 Terra chat tests passed; the V2 request
returned HTTP 200 `text/event-stream`. A full reload retained both replies once,
with all 50 requested tips. The single test conversation was deleted and the
original direct model selection restored.

The APIM connection is retained **enabled**, as approved. Direct Foundry remains
**disabled**, with its separate 401 unresolved. The visible editor's application
409 remains **UI-R1**; its draft was cancelled without saving, and successful
saved-ID diagnostics are not claimed as an editor fix. No credentials were
extracted, no additional role was granted, and no application code, release
notes, GitHub issue, commit or deployment was changed.

**CFG-R1 is satisfied through APIM; overall staging sign-off remains withheld.**
See the [tracked operation and live evidence](../features/POST_MERGE_STABILIZATION_AND_UI_PARITY_PLAN.md#approved-in-place-apim-responses-operation-2026-11-17).

### Resolution Tranche: 0.261.431–0.261.433

Fixed/Implemented in version: **0.261.433**. The deployment used the
repository ACR publisher with no local container build.

#### Resolved defects

1. **Immediate V2 Retry**
   - New completed replies now reconcile their saved thread and attempt
     identity into the optimistic question.
   - Retry no longer depends on a full reload when an assistant arrives with
     thread metadata before the optimistic question does.
   - Fresh `.431` and `.432` live retries completed at attempt 2/2 on the original
     `gpt-6.1-terra` route.

2. **Claude Legacy core `toolCalling`**
   - Explicit Custom routing now uses an exact catalog capability record when
     the administrator did not declare a conflicting model/endpoint override.
   - `claude-opus-4-6` retains Messages routing and catalog capability metadata;
     explicit endpoint/model `false` overrides still win.
   - A live `.432` Legacy-core workflow completed 1/1 with Review complete and
     exact result `CLAUDE-432-LEGACY-OK.`.

3. **Saved Responses Test Connection 409**
   - The classic editor preserves a saved `inference_api=responses` when it
     recreates its options.
   - It also preserves the saved per-model `api_path_order` rather than
     replacing it with the endpoint's different default.
   - Live `.432` Test Connection returned HTTP 200 for the saved Luna route
     at `/shared-foundry;rev=2/openai/v1/responses`; the unsaved draft was
     cancelled and no configuration was changed.

4. **GPT-6 workflow capacities**
   - Added first-party verified exact records for `gpt-6-luna` and
     `gpt-6.1-terra`: 1,050,000 context, 922,000 input, 128,000 output and
     `total_generation` output accounting.
   - Luna Chat Completions tool requests use the verified
     `reasoning_effort=none` contract.
   - Terra tool workflows use the saved Responses connection; direct Foundry
     remains disabled and out of scope.

#### .433 staging evidence

- ACR run: `cpf`
- Tested image:
  `simplechat2026stageacr.azurecr.io/simplechat@sha256:2eaaf3fefe9fcca072dd48dba3962bf89a37fbb967870523404324487a914cf9`
- Rollback image:
  `simplechat2026stageacr.azurecr.io/simplechat@sha256:5b68eb83dccc189394f80657e216dc0d0a97e19f81e297ceab5bdff5d3e5f735`
- App Service: Running; authenticated `/external/healthcheck` returned 200.
- Luna workflow reached inference with a known catalog budget and one request.
  The old provider 400 disappeared. Its mandatory checker ended incomplete
  with `completeness_no_progress`.
- Terra Responses produced `TERRA-433-RESPONSES-CAPACITY-OK` with a known
  catalog budget. Its mandatory checker ended incomplete with
  `completeness_verification_unavailable`.
- These checker outcomes are not mislabeled as route/capacity failures, and
  the producer results are not claimed as completed workflows.
- The one temporary workflow and all six generated retry/workflow
  conversations were deleted. Original `gpt-5.6-terra`, empty composer and
  permanent connection/default state were restored.

Focused validation passed:

- 15 V2 Retry browser tests.
- 9 endpoint routing/editor browser tests.
- 95 catalog/routing/workflow tests plus 25 subtests.
- 52 retry/Responses tests.
- V2 typecheck/build, Node syntax, diff whitespace and editor diagnostics.

The user separately approved the local .433 release-note entry. No GitHub
change was made. Direct Foundry remained disabled and was not retested.

### Final batch: Responses verification and native dropdown contrast

Fixed/Implemented in version: **0.261.434** (`application/single_app/config.py`).

- **Workflow answer review:** The saved Responses producer reached the exact v1
  APIM operation, but the sync checker's `timeout=120` entered the adapter's
  strict model-body validator. The transport rejected it before any checker
  HTTP request. The adapter now passes timeout to the Responses SDK as a
  transport option, not a JSON field. It continues to enforce model-body options,
  the authorized model and route, native schema where advertised, and mandatory
  assessment. The real SDK mock-transport regression in
  `functional_tests/test_task_completeness_runtime.py` fails before the fix and
  verifies an accepted assessment and a still-rejected malformed assessment,
  without replaying the producer.
- **V2 AI Connections picker:** On .433 the open default chat model menu drew
  the dark theme's light text on a white native popup. The shared capability
  picker now applies the opaque theme surface to option and optgroup rows
  while retaining the native control, disabled behavior and saved binding.
  `ui_tests/test_admin_shared_ai_connections.py` measures option/group contrast
  in both themes; opened-popup visual evidence is tracked in the plan.
- **Luna control:** A fresh .433 Legacy-core run
  `fb2bd089-ace1-5656-9260-3a3b0869e4b6` completed 1/1 with Review complete
  and digest-verified `STAGE-LUNA-ANSWER-OK`. This disambiguates the earlier
  no-progress case from a general route/checker failure. No Luna policy was
  weakened or replaced.
- **Build stage:** With explicit approval, move only the static React build
  stage to Azure Linux Node.js 24 LTS. The Python runtime and App Service
  identity/configuration are unchanged by this Dockerfile change.

#### .434 verification

ACR run `cpg` succeeded. Authenticated health and bootstrap both returned
200, with bootstrap reporting `0.261.434`. See the
[living plan](../features/POST_MERGE_STABILIZATION_AND_UI_PARITY_PLAN.md#final-batch-deployment-0261434)
for exact image and rollback digests, run IDs and the cleanup record.

- **Passed live:** opened dropdown in dark and light modes; Terra Responses,
  Luna and Claude text workflows with mandatory review; immediate Responses
  Retry and Stop/reload/follow-up; classic saved Responses diagnostic;
  synthetic XLSX worksheet/table/range query.
- **Still open:** The tool-backed Math answer was numerically correct, but
  workflow completeness received the result without the action's identity
  or complete history. Retain the distinction between answer correctness
  and verified action provenance. TSV is rejected by V2 chat upload.
  Real two-user collaboration and the dedicated live agent/action fixture
  still lack prerequisites.
- **Local:** 279 focused backend tests, 42 isolated tabular compute tests,
  15 Retry browser tests and all 13 docs checks passed. The broader
  admin/classic browser run had 146 passes and 6 invalid-route preview
  assertion failures. Full collection and the global Cosmos review gate
  are still blocked; no tests or guardrails were disabled.

### Endpoint and agent editor follow-up

Fixed/Implemented in version: **0.261.435** (`application/single_app/config.py`).
Verified locally and on staging (ACR `cph`).

- Classic Save uses one existing mutation request. The earlier preview
  assertions assumed a separate preflight request that the merge
  intentionally removed. The production 500 on invalid explicit routing
  came from an untyped validation exception, not an accepted unsafe route.
  The shared normalizer now returns a safe 400, and the classic modal keeps
  the draft open and focuses the inline error. Explicit Preview remains
  independent and never writes.
- On .434, V2 **New agent** failed on `GET /api/v2/admin/agent-options`:
  the admin options path normalized model endpoints a second time after
  their base URLs were stripped. The .435 path normalizes the stored
  global records once and retains the existing no-credentials,
  no-connection-details projection. A real request-handler regression
  verifies the saved Responses model and scope survive the projection.
- The dedicated .434 local agent reached `/shared-foundry;rev=2/openai/v1/responses`
  and received HTTP 400 (`BadRequestError`). The real SDK regression
  reproduced the Semantic Kernel adapter sending `stream_options.include_usage`,
  a Chat Completions option. .435 no longer injects it and strips stale copies
  at the Responses translation boundary. Native stream options are retained,
  and usage is still read from `response.completed`. Provider error bodies
  were not read or recorded.
- **Local evidence:** 21 classic browser cases passed, including all six
  routing/viewport combinations and adjacent saved Responses/preview tests;
  2 real-handler tests passed in normal and optimized Python; 48 adjacent
  routing/group/agent-option cases, 30 route-policy cases, 73 Responses and
  workflow review cases, and 6 native V2 Custom editor tests passed.
- Repository-wide pytest startup and the global Cosmos review were
  explicitly moved to the next test-suite workstream. No global checks
  were disabled or rerun for this follow-up.
- Live .435 recheck: the classic invalid draft received a focused inline
  error and was not saved; the V2 New agent page loaded both saved
  Responses models; the retained staging agent returned `MATH=588877997`
  with one successful persisted Math invocation after reload. See the
  [staging ledger](../features/POST_MERGE_STABILIZATION_AND_UI_PARITY_PLAN.md#endpoint-and-responses-agent-staging-retest-0261435).

### Agent Settings and Authentication Dropdown Follow-Up

Fixed/Implemented in version: **0.261.437** (`application/single_app/config.py`).

- **Agent settings:** Classic attempted to validate a filtered connection with
  no chat models as a complete saved schema-v2 route. The same failure
  reproduced in the global, personal and group V2 option builders. The readers
  now normalize and redact complete, authorized saved records once before
  filtering. Empty picker entries are allowed without relaxing the saved-route
  schema or exposing credentials. Coverage:
  `functional_tests/test_agent_model_governance_filtering.py`.
- **V2 authentication dropdown:** The earlier default-model fix did not cover
  the **Method** menu. The shared connection editor now uses the same opaque
  theme surface on native options and groups as the default-model pickers.
  `ui_tests/test_admin_shared_ai_connections.py` opens the menus and checks
  both themes at a minimum 4.5:1 text contrast, with no connection save.
- **Validation:** 33 focused backend, 30 route-policy, and 6 Chromium cases
  passed along with the React typecheck and build. On staging .437, Classic
  and V2 global agent settings returned 200 with a disabled explicit route
  still saved. The existing Responses choices remained available and the
  fixture model was not offered. The open Method popup was readable in both
  themes. See the [staging retest](../features/POST_MERGE_STABILIZATION_AND_UI_PARITY_PLAN.md#0261437-staging-retest).

### App-Wide V2 Native Dropdown Contrast

Fixed/Implemented in version: **0.261.438** (`application/single_app/config.py`).

The .437 fix was limited to the connection editor and default-model pickers.
The Model Catalog Connections filter and My Workspace agent picker still had
transparent native option backgrounds. `application/v2_ui/src/styles/theme.css`
now sets readable foreground and opaque background colors on native option
and optgroup rows throughout V2; the opt-in wrappers have been removed.
Native controls, keyboard behavior and disabled states are kept.

The six new Catalog and My Workspace cases failed against the old CSS. All
ten focused Chromium cases passed with the rebuilt .438 bundle, including the
previous menu tests. Typecheck and production build passed. On staging .438,
the exact Catalog popup was readable in both themes. The grouped default
picker, Method popup and an independent My Workspace Workflow picker were
also visibly readable in dark mode. See the [staging retest](../features/POST_MERGE_STABILIZATION_AND_UI_PARITY_PLAN.md#0261438-staging-dropdown-verification).

### Corrective Files

Backend (`application/single_app/`):

- `config.py`
- `functions_chat_retry.py`, `functions_chat_content_checks.py`
- `functions_model_endpoint_diagnostics.py`,
  `functions_model_endpoint_validation.py`, `functions_model_capabilities.py`,
  `model_endpoint_clients.py`, `static/json/model_capabilities.json`
- `functions_workflow_context.py`, `functions_workflow_execution.py`,
  `functions_workflow_structured_execution.py`,
  `functions_workflow_execution_history.py`, `functions_workflow_journal.py`,
  `functions_workflow_policy_errors.py`, `functions_workflow_runner.py`,
  `functions_workflow_runtime_store.py`
- `route_backend_chats.py`, `route_backend_collaboration.py`,
  `route_backend_conversations.py`, `route_backend_workflows.py`
- `static/js/chat/chat-streaming.js`, `static/js/chat/chat-messages.js`,
  `static/js/model_routing_editor.js`

V2 (`application/v2_ui/src/`):

- `stores/chatStore.ts`
- `lib/chatRetryAttempts.ts`, `lib/sse.ts`, `lib/types.ts`,
  `lib/workflowEditor.ts`, `lib/workflowExecutionHistory.ts`
- `components/chat/MessageList.tsx`
- `components/workflows/WorkflowFailureDetails.tsx` (new),
  `WorkflowRunHistory.tsx`, `WorkflowRuntimePanel.tsx`,
  `WorkflowExecutionHistory.tsx`

Validation:

- `scripts/check_cosmos_response_boundaries.py`
- `functional_tests/cosmos_response_boundaries.json`
- `functional_tests/test_chat_stream_stop_control.py`,
  `test_chat_retry_attempt_lifecycle.py`, `test_cosmos_contract_runner.py`,
  `test_chat_soft_deleted_message_visibility_fix.py`,
  `test_workflow_authoring_sdk_boundaries.py`,
  `test_chat_local_openlayers_assets.py`,
  `test_model_endpoint_protocol_inference.py`,
  `test_model_capability_catalog_resolution.py`,
  `test_task_completeness_runtime.py`, `test_workflow_policy_failures.py`,
  `test_workflow_result_routes.py`, `test_workflow_durable_execution.py`,
  `test_workflow_structured_flow.py`, `test_support/workflow_results.py`
- `ui_tests/fixtures/chat_stop_runtime.py` (new),
  `ui_tests/test_v2_stream_stop_partial.py`,
  `ui_tests/test_chat_stream_stop_button.py`,
  `ui_tests/test_v2_workflow_durable_runtime.py`,
  `ui_tests/test_v2_workflow_control_runtime.py`,
  `ui_tests/test_v2_chat_retry.py`,
  `ui_tests/test_model_endpoint_capacity_editor.py`

Documentation:

- This existing fix record and the existing stabilization/UI-parity plan
- `docs/reference/chat-controls.md`

All pre-existing .429 source/test/document deltas were preserved. Existing
release-note edits were not changed; no GitHub issue operations were performed.
No commit, staging, push, merge, source refresh, dependency install, Azure
resource/settings change or deployment was performed.

## Historical .429 Testing and Validation

### Focused Python

Passed: **102 tests**

Coverage includes:

- legacy/APIM/global/personal/group chat catalog identity;
- embedding-only exclusion;
- V2 cancellation state through the store;
- deterministic, transient, and ambiguous workflow failures;
- CSV `None`, blank, `0`, and `"0"` selectors;
- exact synthetic CSV aggregate of `35`;
- non-retryable CSV selector errors;
- request-wide invocation budget;
- Responses continuation, malformed arguments, denied actions, duplicate
  calls, cancellation, and private reasoning isolation.

### Browser

Passed: **3 tests**

- V1 Stop retains and labels partial output.
- V2 Stop retains partial output without a terminal SSE event.
- V2 Stop before the first token creates no blank assistant answer.

### Frontend

Passed:

```powershell
npm run typecheck
npm run build
```

The build retained the existing Vite large-chunk warning.

### Full-Suite Limitation

The earlier root and broad functional commands encountered collection-time
failures involving module-path setup and invalid/unavailable live Cosmos
credentials. No changed test file appeared in those collector failures, but
there is no clean baseline comparison proving every broader failure unrelated.

### Live Staging Retest

Tested **2026-11-16 UTC**, visible application version **0.261.429**.
Read-only App Service configuration reports:

`simplechat2026stageacr.azurecr.io/simplechat@sha256:7295681b21a4652f3dcaa3ec7d675cf37e7d736292f031635db6a150c7d28bce`

Passed:

- Actual V1/V2 model menus exclude the embedding model while preserving its
  saved embedding capability.
- Direct chat and all three existing APIM agents return exact unique tokens
  in both UIs.
- The uploaded synthetic CSV computes total 35, North 15, South 20 and three
  rows using three actual tool calls, without a selector retry loop.
  `TOTAL=35` persists after reload; expected totals were not in the prompts.
- An isolated Responses-enabled managed-identity connection works in V1/V2.
  Partial output survives Stop, reload and a later successful turn.

Still failing:

- Stopped/incomplete indicators disappear during reconciliation/reload,
  including V1, V2 and Responses.
- A pre-token V2 Stop returned 404, then generated and persisted all 150
  requested items. V2 temporarily displayed an older reply beneath that
  stopped turn.
- The Claude workflow fails its legacy capability check. With chat
  capabilities Off it produces the correct token, but the run remains
  incomplete because completeness verification is unavailable.
- An isolated nonexistent-deployment workflow entered recovery without a
  specific diagnostic. Its actual provider HTTP status was not observable,
  so the underlying failure must be traced before assigning a root cause.
- V2 omits the safe error already stored on a failed task and returns a
  misleading older-run/no-durable-result message when its excerpt is loaded.

The session ledger has 12 passed, 7 failed and 1 blocked check entries,
including aggregate and cross-UI checks rather than seven independent causes.
See the related plan's staging retest section for identifiers and acceptance
follow-ups.

## Historical .429 Impact

- Chat users no longer receive embedding-only models in model pickers.
- Stopping V2 retains already-visible text, but durable interruption status
  and early cancellation are not complete.
- Recognized configuration failures are stored safely; workflow adapter
  classification and user-visible diagnostics still require work.
- CSV analysis completes deterministic simple totals without repeated Excel
  selector retries.
- Local duplicate Responses tool-call tests execute the identical call once;
  no live action fixture was exercised.
- Existing endpoint identity, APIM protocol selection, and authorization
  behavior remain unchanged.

## Historical .429 Known Limitations

- The admin deployed the application; this validation did not commit, push,
  deploy, change credentials or modify application code.
- The configured image and visible version were recorded. The ACR run ID,
  rollback target and health/readiness checks remain unverified.
- Cancellation and workflow failures above block sign-off despite the
  successful APIM, picker, Responses-baseline and CSV checks.
- GPT-6 Luna/Terra workflow token limits remain a separate blocked item until
  authoritative deployment capacities are supplied.
- Optional live Responses action testing remains pending an approved temporary
  no-network action fixture.

## Rollback

If rollback is approved, verify the intended previous image before selecting
its digest. This change does not require a data migration, endpoint-policy
migration, secret change, or settings reset. All temporary settings and objects from the live retest were
removed: two workflows, one isolated connection, seven conversations and one
synthetic CSV. Original connections, SharedAPIM routes, the pre-existing CSV
and the direct-model preference were preserved.
