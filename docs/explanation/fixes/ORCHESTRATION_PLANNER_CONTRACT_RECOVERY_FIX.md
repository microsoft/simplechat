# Orchestration planner contract and source-binding recovery (v0.261.419)

Fixed/Implemented in version: **0.261.419**, tracked in
`application/single_app/config.py`.

Current integrated version: **0.261.420**. The updated React V2 base adds
saved-findings publication identifiers and status codes to the logger; those
properties and this fix's consumer-run/schema diagnostics are preserved together.
Post-integration validation passed 179 logging/native/saved-findings functional
tests and 75 browser source-inspector checks. The merged V2 build, documentation
checks and reviewed Cosmos inventory also passed.

## Issue and root cause

Similar document requests could either run normally or stop with "The request
could not be planned." Read-only Application Insights and App Service console
investigation distinguished several planning failures on deployment version
0.261.418:

- A native inspection action did not count as selected-document work because its
  contract had no structured document binding.
- Some replacement plans failed output declarations or producer/consumer kind
  validation. Those failures could stop an initial draft without using the
  available correction.
- Generic `plan_invalid` events did not identify their precise rejecting rule,
  and the browser/saved-question boundary lost the typed planning reason.

The failing and successful turns used the same recorded planner binding and Auto
routing. A later Word review completed. These observations identify validation
failures, not an upload/extraction failure or evidence of intermittent Azure
transport failure.

The exact rejected production JSON was not retained. The investigation therefore
does not attribute a particular historical generic rejection to an invented field
or claim that every failure had one cause.

A separate real-module reproduction established an effective-contract defect:
the planner was offered Analyze's optional `records` output, but omitted options
became v2 `source_observations`, which does not expose that projection. A draft
following the advertised output list could then be rejected by server defaults.
This defect requires contract alignment, not merely another retry.

## Technical changes

### One effective capability contract

`functions_orchestration_registry.py` projects Analyze's actual default arguments
and output variants through the existing output resolver. The default projection
offers `findings` and `coverage`, plus optional `report`, not optional `records`.
Explicit legacy semantics and v2 `reconciled_records` retain their record output.
The planner is instructed to declare the appropriate semantics for required
records, rather than silently discard a requested projection.

Fixed producers can omit output declarations and use the server's canonical
defaults. Explicit declarations remain strictly validated.

### Explicit native document action sources

`functions_action_manifest.py` identifies registered Document Search types, not
configured action names or task wording. The planner marks those resolved actions
as supporting document binding. Their `action_invoke` arguments can carry one to
100 exact, unique workspace `document_ids`; other integrations cannot claim this
source coverage.

The compiler, executor, adapter and action runner preserve that binding. The
adapter resolves authorized source snapshots and rechecks identity, scope and
revision before each tool call. The actual loaded plugin must be Document Search.
Its native metadata, chunk and summary reads reject other IDs; search calls with
no model-supplied filter receive the bound IDs before source I/O.

Existing action workspace restrictions and current source-authority checks still
apply. The existing task-local selected-source mechanism pins workspace identity
and isolates concurrent invocations. A document-read error is an explicit action
failure, not successful findings. Native properties that are absent or
inaccessible within an available report remain limitations, not invented facts.

The existing plan UI displays these documents through its standard source chips
and narrowing controls. No extra Search or Analyze step is required solely to
declare that a native action reads the selected file.

### Retention, citations and final composition

`functions_orchestration_result_runtime.py` admits workspace provenance alongside
the current external action reference only for a matching, explicitly bound
Document Search action. Missing or mismatched sources, another integration, or an
undeclared binding remain rejected.

Both kinds of lineage survive result storage and restart. Native tool citations
are projected from the exact retained result, checked against its workspace
lineage, and passed to composition. A citation cannot name an unbound document.
This prevents a valid plan from failing later at retention or losing its native
source references before the final answer.

The executor also preserves the explicit binding at its post-action source
handoff. Its former external-Gather path cleared workspace sources before calling
retention, even though the action had read them. The authenticated Auto-run
regression exercises this handoff rather than substituting a prepared action
result at the adapter boundary.

Retained results keep their existing conversation/run access semantics; recorded
native sources are provenance, not permission to reread an original. External
integration access continues to be checked. The change does not replace those
policies or promote partial findings into complete datasets.

### One targeted correction, not blanket retries

`functions_orchestration_schema.py` and
`functions_orchestration_result_contracts.py` identify owned step-shape,
argument, output, named-input and graph failures. The same planner receives
contract-aware feedback, and the complete replacement plan passes every normal
validator.

All eligible failures share **one correction attempt total**. A different second
error does not reset that allowance. Unknown model argument names can be
corrected without logging those names. Permission failures, unavailable
capabilities, untrusted retained aliases, held sources, provider refusals and
unclassified exceptions do not become blanket-retryable. Workflow-owned argument
validation keeps its existing correction/drop policy.

No tool executes during planning or correction. No selection, required operation,
approval or exact-data validation is disabled to make a plan succeed.

### Failure meaning survives reload

`functions_orchestration_events.py`, `route_backend_orchestration.py` and
`functions_orchestration_planning.py` carry known failure classifications through
SSE and the saved question:

| Stream field | Saved planning field | Meaning |
| --- | --- | --- |
| `code` | `error_code` | Stable owned failure category |
| `error_stage` | `error_stage` | Rejecting planning phase |
| `error_rule` | `error_rule` | Specific rule, when known |
| `error_attempt` | `error_attempt` | Proposal attempt, when known |

The stream can still use HTTP 200; an error frame and failed planning state are
not a completed request. Explicit retry keeps the original question/selections
and clears obsolete failure metadata when the new plan is ready.

Debug diagnostics add only known schema keywords, registered argument-field
names or `unknown`, result-kind codes, counts and hashed step identity. Raw model
JSON, prompts, arbitrary property names, document contents and provider exceptions
are not added to logging.

### Debug checkpoints from binding to final preparation

With the existing debug switch enabled, correlated checkpoints now cover binding,
snapshot rechecks, native function attempts/outcomes, the executor source handoff,
retention, citation projection and final content preparation. They contain hashes,
counts, known operations, shape/presence flags and safe error types. Cross-run
consumption uses a validated consumer-run hash.

These events explicitly gate the ordinary structured logger, reaching both console
and Application Insights. Existing console-only debug calls are not globally
exported. Diagnostics use already available data and do not reread a source,
invoke another model, or serialize its private content to build a log message.
See the [lifecycle checkpoint reference](../../reference/logging-tags.md#native-action-and-retained-result-lifecycle-checkpoints)
for event names and a bounded workspace KQL query.

## Validation and impact

The new functional suites cover effective Analyze contracts, source-free and
document-backed correction, mixed errors sharing one budget, protected sources,
real Semantic Kernel native calls, authority/revision changes, scope isolation,
SDK-default retention, integration reauthorization, citation confinement and
native findings reaching final composition with completeness checking enabled.
The browser regression verifies bound source visibility and narrowing using the
existing components, without production traffic.

`test_orchestration_document_action_end_to_end.py` submits a real authenticated
HTTP request with automatic approval and requires a persisted cited answer. It
uses the real plugin loader, native report projection, execution leases, SDK-shaped
stores, retention, composition, completeness and publication. PDF and Word cases
run with debug on/off and with successful/failed native reads. Known native
metadata, its limits and its citation must reach composition unchanged. Failure
must stop before retention/composition instead of producing successful findings.

The same tests check saved turn state, one original question, model/source call
counts, absent debug checkpoints when disabled, structured log privacy when
enabled, and the absence of private error text from the stream. The shared SDK
double now accepts the bounded read transport options used by real external
identity checks while retaining partition routing, ETags, failures and conditional
writes. Its behavior has a dedicated regression.

Additional suites:

- `test_orchestration_planner_contract_recovery.py`: effective defaults, owned
  draft errors, single-budget repair, source constraints and non-document work.
- `test_orchestration_document_action_binding.py`: real native tool filters,
  scope isolation, snapshot checks and debug-sink/call-count parity.
- `test_orchestration_document_action_lineage.py`: mixed lineage, restart/current
  integration access, citation confinement and final composition, with completeness
  and debug independently enabled/disabled.
- `test_orchestration_planning_persistence.py`: typed terminal reasons, reload,
  explicit retry, claim fencing, cancellation and Auto handoff.
- `ui_tests/test_v2_orchestration_actions.py`: existing source-chip review and
  narrowing controls for bound actions.

| Before | After |
| --- | --- |
| A valid advertised Analyze projection could conflict with later defaults. | Default and conditional output projections agree with the shared resolver. |
| A native action could not declare selected-file coverage. | A supported action binds its exact sources without redundant reading work. |
| Passing planning could still fail at mixed native/action retention. | Both authorized lineage kinds and source citations reach retained readers and composition. |
| Draft shape/type mistakes could terminate before correction. | Classified model-draft errors receive the same single targeted correction. |
| Reload showed only a generic failure category. | Known phase, rule and attempt remain available in saved planning state. |

This is branch-local implementation and offline/browser verification, not a
live-model success-rate claim. It does not change Azure configuration, deploy the
application, reprocess files, alter the user's conversations, or guarantee that
every model-generated draft will be valid.

### Executed checks

The combined 18-file shared-contract, native-action, source-selection, external
authorization, retained-citation, observation, available-information and saved-turn
selection passed **507 tests and 184 subtests**. The full HTTP regression by
itself passed **9 tests**:

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -q -p no:cacheprovider --disable-warnings --tb=short --show-capture=no .\functional_tests\test_orchestration_document_action_end_to_end.py
```

The source-review browser regression and planning-retry suite passed **16 tests**:

```powershell
python -m pytest -q -p no:cacheprovider --disable-warnings --tb=short .\ui_tests\test_v2_orchestration_actions.py::test_native_action_bound_sources_are_visible_and_can_be_narrowed .\ui_tests\test_v2_orchestration_planning_retry.py
```

The production V2 build, including TypeScript checking, passed with output isolated
under UI-test artifacts. Route Blueprint inventory, unauthenticated policy,
route-test coverage and logger initialization passed **31 tests** together.
Documentation surface coverage passed **7/7**, and site quality **6/6**.
Regenerating the application surface did not add a setting, route, plugin or UI
control. The reviewed Cosmos inventory has **1,094 owners, 425 doubles and zero
review gaps**.

The changed SDK owners and shared double also passed **251 tests** with
`test_support.cosmos_network_guard` loaded before collection. This selection covers
the normalizer, SDK orchestration responses, saved planning, conversation/source
authorization, shared/regenerated turns, retained citations, attachments and the
new authenticated native Auto-run path. Inventory updates are limited to
22 reviewed planning/route owners and the SDK-default conditional container;
there are no added or removed owner/double entries.

The full reviewed storage-contract gate also passed **2,015 tests and 431
subtests**, with network access blocked before collection:

```powershell
python .\scripts\check_cosmos_response_boundaries.py --run-contracts
```

### Broader baseline limitations

These are not presented as a fully green repository-wide test run. Five unrelated
existing checks were also executed against unchanged `HEAD` production modules
and reproduced the same failures:

- The tabular composition-profile assertion expects two profiles although
  `document_transform_v1` is already registered.
- An older hand-off check expects that capability to be last although conversation
  capabilities already follow it.
- The hand-off-off golden context expects a 3,600-second interval although the
  current definition already permits one second.
- A workflow-proposal result-alias fixture is rejected as
  `result_reference_untrusted`.
- The legacy AST-only research harness lacks `STORAGE_FAILURE_CODE` in its
  extracted namespace.

An existing debug-settings integration check also needs cloud configuration
outside the isolated harness; it is not counted as passing. A broader browser
selection reported 49 passed, two failed restored-state selector checks and two
teardown errors from an unexpected resource request. Application frontend source
was unchanged, and those failures are not suppressed or counted as passing.
The targeted browser selection above is independently green.

Related explanations:
[selected-document planning recovery](ORCHESTRATION_DOCUMENT_PLANNING_RECOVERY_FIX.md),
[action access](../features/CHAT_ORCHESTRATION_ACTIONS.md), and
[Document Search](../../reference/actions/document-search.md).
