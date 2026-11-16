# Foundry orchestration polling budget fix

Fixed/Implemented in version: **0.261.370**

The corresponding application version is maintained in
`application/single_app/config.py`.

## Issue and verified root cause

A Foundry-backed orchestration search could fail before its configured execution
budget expired. SimpleChat constructed Semantic Kernel's `AzureAIAgent` without
polling options. In the repository-pinned Semantic Kernel **1.39.4**,
`RunPollingOptions.run_polling_timeout` defaults to one minute. The SDK could
therefore abandon polling and cause the executor's existing transient retry to
start another provider run, even when the original run might still be active.

Observed status requests returned HTTP 200, while SDK telemetry recorded
one-minute polling timeouts. This establishes an application/SDK budget mismatch;
it does **not** establish a Foundry service limit, a provider outage, or the final
outcome of those remote runs. Waiting longer cannot guarantee provider success.

## Implementation

The executor creates a private `OrchestrationExecutionControl` from the current
step's monotonic deadline, the existing durable run deadline, and the existing
cancellation probe. The step-scoped adapter forwards that object through the web
search helper to the shared Foundry runtime. Research searches forward the same
control rather than receiving a fresh budget for each query.

The shared wrapper:

- Configures `RunPollingOptions`, imported from
  `semantic_kernel.agents.open_ai.run_polling_options`, with the remaining
  execution budget instead of the independent one-minute default.
- Watches cancellation and deadlines while the SDK awaits definition lookup,
  run creation, polling or message retrieval. A deadline or cancellation remains
  executor-owned control flow, not a transient provider error.
- Continues polling the same provider run until completion or an application
  stop. It does not create another run merely because a minute passed.
- Retains actual-run configuration capture and authorization. Polling options,
  callbacks and deadlines are not added to persisted settings, provider metadata,
  capture overrides, progress payloads or retained results.
- Cancels the invocation task on a stop and, when an actual run has been captured,
  attempts to cancel that run before deleting its owned thread. Run cancellation,
  thread deletion, client close and credential close each have a five-second
  best-effort cleanup timeout. Failure of one cleanup does not skip subsequent
  resources or replace the original stop reason.

The existing single transient retry remains unchanged. Both attempts share the
original step/run deadlines, including the retry delay; a second attempt gets
only the time that remains. Non-transient errors are not newly retried.

No timeout setting, default budget, retry count, provider configuration or
authentication policy changes. Callers that supply no private execution control
keep the supported SDK default polling behavior and completion-token handling.
Client-construction failure now also closes its already-created credential.

### Files changed

- `application/single_app/functions_orchestration_timing.py`: invocation-only
  control and stop exception; existing timeout-setting semantics are unchanged.
- `application/single_app/functions_orchestration_executor.py`: construct one
  control per step and preserve it across the existing retry.
- `application/single_app/functions_orchestration_adapters.py`: forward control
  through web and research searches without changing adapter contracts.
- `application/single_app/route_backend_chats.py`: optional private forwarding in
  existing search helpers; no route or storage behavior changes.
- `application/single_app/foundry_agent_runtime.py`: bounded SDK execution,
  remaining-budget polling options and resource cleanup.
- `functional_tests/test_foundry_orchestration_polling_budget.py`: offline
  regressions using real wrappers, real SDK polling and provider-operation doubles.

## Validation

The new module contains **39 passing tests** in normal Python and **39 passing
tests** in optimized Python. These use the real pinned SDK with a controllable
clock, not a replacement polling implementation.

Coverage includes:

- Success after more than 60 virtual seconds within budget, with exactly one
  provider run, actual-run capture and retained-result admission/readback.
- Cancellation before resource creation and while awaiting definition, run
  creation and status requests.
- Step expiry, a shorter run deadline, an already exhausted budget, an endless
  pending run, and an existing run deadline despite changed settings.
- Remaining-budget retries, budget exhaustion during retry delay, the existing
  one-retry limit, HTTP/transport classification and non-transient refusal.
- Thread/client/credential cleanup on success, provider failure, cancellation and
  expiry, including stalled cleanup, cleanup errors and cancellation during
  cleanup.
- Rejection of a changed actual provider configuration; controls remain absent
  from settings and public progress.
- Compatibility without an orchestration control, including completion tokens.

One owner-runtime boundary regression exercises the unchanged
`_collect_recent_chat_upload_file_inputs` helper. It verifies the existing
SDK-default container's `CosmosDict` point responses, plain query rows, real file
input construction, upload filtering, size limits and deduplication, with only
blob I/O doubled. Its evidence selector is:

```text
functional_tests/test_foundry_orchestration_polling_budget.py::test_recent_chat_upload_inputs_consume_sdk_query_rows
```

### Reproducible focused commands

Use the repository-pinned dependencies and an initialized offline test environment:

```powershell
$env:PYTHONPATH = 'application\single_app;functional_tests'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard functional_tests\test_foundry_orchestration_polling_budget.py --disable-warnings
python -O -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard functional_tests\test_foundry_orchestration_polling_budget.py --disable-warnings
```

Results: **39 passed** for each command. Required setup, provider calls and state
changes occur outside assertions; optimized pytest still rewrites test assertions.

The combined invocation-capture compatibility run also passed:

```powershell
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard functional_tests\test_foundry_orchestration_polling_budget.py functional_tests\test_orchestration_external_configuration_capture.py --disable-warnings --tb=short
```

Result: **149 passed**, using Semantic Kernel 1.39.4, Flask 3.1.3 and Werkzeug
3.1.6 in the isolated validation interpreter.

The expanded executor, research, capture and route-policy run passed:

```powershell
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard functional_tests\test_foundry_orchestration_polling_budget.py functional_tests\test_orchestration_external_configuration_capture.py functional_tests\test_orchestration_step_budget_outcome.py functional_tests\test_orchestration_executor.py functional_tests\test_orchestration_deep_research.py functional_tests\test_orchestration_research_capture.py functional_tests\test_orchestration_research_pre_effect.py functional_tests\route_tests\test_route_blueprint_policy_inventory.py functional_tests\route_tests\test_route_unauthenticated_policy_contract.py functional_tests\route_tests\test_route_policy_test_coverage.py --disable-warnings --tb=short --show-capture=no
```

Result: **297 passed, 5 subtests passed**. This includes all three documented route
policy suites; no route security policy was changed.

## Impact and limitations

Before the fix, the SDK's default minute could end polling before the application's
budget and trigger a new-run retry. After the fix, an orchestration-owned search
uses the remaining application budget on the same run while cancellation and
expiry remain effective.

Cleanup is best effort: a remote service or network failure can prevent confirmation
of provider cancellation or thread deletion. This change does not claim that a
remote run stopped successfully when cleanup could not confirm it.

Validation is offline only. No live conversation, provider retry, deployment,
settings change or historical-answer rewrite was performed. A live post-deployment
rerun requires separate authorization.
