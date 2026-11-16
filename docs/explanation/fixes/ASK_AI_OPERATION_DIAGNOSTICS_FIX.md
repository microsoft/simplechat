# Ask AI Creation Contract and Operation Diagnostics Fix (v0.261.331)

## Issue and root cause

Agent creation through Ask AI returned HTTP 502 with `assistant_output_invalid` after both
model attempts. The final response passed parsing and response-shape validation but failed
operation validation. Existing summaries retained the last stage, not the particular operation
or validation rule. Application Insights also reduced most string dimensions to their lengths.
Consequently, the rejected operation and the first attempt's reason could not be recovered.

The same SQL instruction was then reproduced locally against the application's configured
Azure model using a real browser-generated 12-field new-agent request and synthetic workspace
choices. Two runs returned the same terminal 502. The model used `displayName` and `description`
instead of the required `/displayName` and `/description` paths; it initially also supplied
empty SQL server and database fields. The correction removed the empty connection fields but
still used the wrong name paths, so the required action name remained absent.

The prompt's general path rule referred to the parent draft even for new-item values, and its
creation instructions did not clearly require leading slashes or explain how to represent
unknown connection details. This change clarifies those contracts and fixes the live-reproduced
failure without accepting malformed operations. It also fixes the diagnostic gap. The original
historical response was not retained, so the evidence comes from a fresh live-model reproduction,
not recovery of that request's exact response.

Fixed/Implemented in version: **0.261.329**. The application version is recorded in
`application/single_app/config.py`.

## Technical details

`functions_editor_assist.py` now scopes the parent-draft path rule to `set` operations. Its
`create_item` instructions require exact, case-sensitive paths including the leading `/`,
distinguish new-action fields from the parent agent's fields and give the `/displayName`
example explicitly. Unknown type-specific connection details must be omitted rather than
filled with blank placeholders or invented values; the assistant can instead ask a short
question with no operations. Every required common field still must be supplied.

The validator remains strict: unprefixed field names are rejected, not silently repaired.
Missing required connection details still block saving in the action editor. No SQL connection
or editor persistence occurs during Ask AI.

`functions_assist_diagnostics.py` supplies a bootstrap-free, injected observer and a closed
property allowlist. The editor and workflow cores attach typed diagnostic metadata at the
validation decision, not by parsing human-readable correction messages. Runtime adapters inject
the same observer into the core and its model adapter.

`functions_appinsights.py` gates `log_assist_debug()` on the existing `enable_debug_logging`
setting before emitting an event. Enabled events use ordinary `log_event()` so the configured
Application Insights logger and debug console mirror both receive them. Using
`log_event(debug_only=True)` would reach only the console. The serializer preserves only the
explicitly allowlisted categorical strings; unrelated string properties remain protected.

Affected endpoints are `POST /api/agents/assist`, `POST /api/actions/assist` and
`POST /api/user/workflows/assist`. There are no new routes, settings, retries or browser assets.
Feature gates, authorization, response bodies, atomic proposal validation and deadlines remain
unchanged. Logging failures cannot replace the proposal, rejection or limiter cleanup.

### Events and dimensions

| Event | Useful dimensions |
| --- | --- |
| `model_started` | Core attempt number and remaining deadline |
| `provider_finished` | Provider-call number, duration and whether JSON mode was used |
| `provider_failed` | Safe assistant error code, provider status when available and call duration |
| `json_mode_fallback` | The refused provider-call number and status; no exception text |
| `model_finished` | Output presence and length, normalized finish reason |
| `validation_rejected` | Stage, closed rule, operation index/category, reason index/count and approved field metadata |
| `correction_started` | The rejected attempt and stage that prompted the one correction round |
| `request_finished` | Status, outcome, safe error code, model/correction counts and successful operation counts |

All records carry `assist_surface`, `assist_scope`, `attempt` and elapsed milliseconds.
Once the request is validated, `turn_id_hash` correlates its events without logging the raw
submission ID. Application Insights stores the values with the `sc_` prefix in `Properties`.
The normal request trace supplies `OperationId` when tracing is configured. `provider_attempt`
counts provider calls across the request; a JSON-mode fallback can add a provider call without
adding a core correction attempt.

Rejections record at most 12 reasons per attempt. `reason_count` is the count retained, not an
unbounded total. Editor field identifiers are preserved only for a small explicit allowlist;
other fields retain a kind and whether the descriptor was known. Workflow save failures include
`assist_validation_code` only for approved server codes. Some workflow candidate-finalization
and apply failures remain grouped as `candidate_invalid` or `operation_invalid`.

### Privacy boundary

No new record contains prompts, conversation text, draft values, model replies, document titles,
credentials, endpoints, raw user/workspace IDs, unknown field names or provider exception text.
Provider finish reasons and validation codes outside the allowlist are categorized or omitted.
Measurements are finite and bounded. Debug logging is not permission to log private content.

## Diagnosing a reproduced failure

For diagnosis through the app, deploy the instrumented build to an approved environment, enable
**Enable Debug Logging** and send one Ask AI request without saving the resulting draft.
Any deployment, restart or production settings change requires its own approval. A local
reproduction can instead use the configured model with a synthetic browser-generated request
and local debug logging, as this investigation did; neither app deployment nor stored settings
needs to change.

Find the request in `AppRequests`, then inspect its operation's diagnostic events. Both rejected
attempts matter: the correction can fail for a different reason. A `required_value` on the SQL
server field differs from `new_required_field` on a missing action name, `new_type_invalid`,
`choice_handle_invalid` or an unknown path. Only an observed rejection supports choosing the
corresponding behavioral fix.

### Application Insights through Log Analytics

Run these against the Log Analytics workspace linked to the application's diagnostic settings.
Keep the time window narrow and replace the operation placeholder with the observed request's
ID. These queries are deliberately single-line: when invoking the Azure CLI from PowerShell,
passing multiline KQL can result in only the first line being applied.

```kusto
AppRequests | where TimeGenerated > ago(30m) | where Url contains "/api/agents/assist" or Url contains "/api/actions/assist" or Url contains "/api/user/workflows/assist" | project TimeGenerated, OperationId, ResultCode, DurationMs | order by TimeGenerated desc | take 50
```

```kusto
AppTraces | where TimeGenerated > ago(30m) | where OperationId == "PASTE_REQUEST_OPERATION_ID" | where tostring(Properties.sc_message) in ("[EDITOR_ASSIST] Ask AI diagnostic", "[WORKFLOW_ASSIST] Ask AI diagnostic") | project TimeGenerated, OperationId, Surface=tostring(Properties.sc_assist_surface), Event=tostring(Properties.sc_assist_event), Attempt=toint(Properties.sc_attempt), Stage=tostring(Properties.sc_assist_stage), Rule=tostring(Properties.sc_assist_rule), Operation=tostring(Properties.sc_assist_operation), Index=toint(Properties.sc_operation_index), Field=tostring(Properties.sc_assist_field), ValidationCode=tostring(Properties.sc_assist_validation_code), Code=tostring(Properties.sc_assist_code), TurnHash=tostring(Properties.sc_turn_id_hash) | order by TimeGenerated asc | take 100
```

### App Service console

If trace correlation is unavailable, use the same window and the submission hash from the
structured records to narrow these console results further.

```kusto
AppServiceConsoleLogs | where TimeGenerated > ago(30m) | where ResultDescription contains "[EDITOR_ASSIST] Ask AI diagnostic" or ResultDescription contains "[WORKFLOW_ASSIST] Ask AI diagnostic" | project TimeGenerated, ResultDescription | order by TimeGenerated asc | take 100
```

## Validation and impact

`functional_tests/test_ask_ai_debug_diagnostics.py` exercises the real serializer and captures
both logging sinks. It covers all three surfaces, debug on/off, per-attempt rejection and
correction, finish reasons, provider failure/fallback, bounded reasons, unknown/private data
and observer failure isolation.

`functional_tests/test_editor_assist_create_item_prompt.py` checks the clarified prompt and
replays the observed malformed-operation pattern with synthetic values. The prompt regression
failed before the fix and passes afterward; strict rejection and a valid unfinished SQL draft
are covered separately.

`ui_tests/test_v2_agent_action_ask_ai.py` runs the shipped V2 bundle with the real action catalog,
browser-generated new-agent descriptors and the backend core. SQL scenarios verify an unfinished
read-only draft, assigning an existing SQL action, a clarification without mutation, a corrected
blank-server proposal, correction of unprefixed common fields, a terminal missing-name rejection
and undo.
The fixture refuses unexpected service requests and asserts no editor persistence before save.
No test connects to SQL or calls a live model.

The new diagnostic suite passes all 44 cases, the creation-contract suite passes all 3 cases,
and the real-bundle editor suite passes all 11 cases. Combined core/runtime/operation/route
coverage reports 407 passed with the known pre-existing bootstrap source assertion deselected:
that assertion does not recognize the existing `measure()` wrapper. Additional workflow
request/save/client parity coverage passes. Documentation coverage
and quality checks pass, and the patch has no whitespace errors. The repository-wide logging-tag
test still reports pre-existing mixed-case tags outside the new diagnostics; the new tags use
the normalized format.

Before this change, a terminal operations-stage failure could not identify its rejected rule.
After this change, a reproduced failure on the instrumented build yields content-free
per-attempt rule and operation metadata while debug logging is enabled. With debug disabled,
the new detailed records are absent.

Manual live-model verification returned 502 in both pre-fix reproductions. Six post-fix
reproductions returned successful outcomes: four unfinished SQL-action drafts and two useful
clarifications about the missing database details. The final two runs also explicitly checked
that drafts contained no invented server/database/endpoint, credential field or read-write SQL
setting. Neither validation rules nor retry counts were relaxed. Automated tests remain offline
and do not depend on Azure access.

The corrected build still needs the normal approved deployment before the live App Service
benefits from the fix. This investigation did not deploy, restart the app or change stored
settings.

Related feature references: [Agent and action Ask AI](../features/AGENT_ACTION_AI_ASSISTANT.md)
and [Workflow Ask AI](../features/WORKFLOW_AI_ASSISTANT.md).

## Cosmos contract review follow-up (v0.261.330)

Fixed in version: **0.261.330**, recorded in `application/single_app/config.py`.
PR [#1760](https://github.com/microsoft/simplechat/pull/1760) changed the workflow
runtime module when adding diagnostics, invalidating the Cosmos inventory's
closed source-only review for `read_workflow_base`. Its function implementation
did not change; the module fingerprint did. The PR base still matched the
original review, so this was a PR-caused review gap, not a service outage.

`functional_tests/test_workflow_assist_cosmos_response_contract.py` now runs the
real reader against the installed Cosmos SDK through the existing offline HTTP
transport fixture. It checks wrapped point responses, plain editor projections,
authored revisions, metadata removal, alert diagnostic sanitization, read-only
behavior, personal partition isolation, real SDK 404 responses and rejected
identifiers. The inventory replaces the stale source-only exemption with
owner-runtime evidence that the Cosmos contract job executes automatically.
No runtime behavior, validator, CI workflow or contract guard is weakened.

The full contract run also exposed an import failure in the existing M365 action
card harness: its isolated `functions_appinsights` module supplied `log_event`
but not the PR's new `log_assist_debug` adapter. The harness now supplies both
logger methods so the real pending-action routes can import the editor assistant
runtime. Authorization, delivery and route assertions remain unchanged.

### Follow-up validation

Validation uses Python 3.12 and the application's pinned `azure-cosmos==4.9.0`.
The review gate reports **1,051 owners, 394 doubles and zero review gaps**.
With the application and functional-test directories on `PYTHONPATH`, this
network-blocked targeted command passes **85 tests**:

```powershell
python -m pytest -p test_support.cosmos_network_guard .\functional_tests\test_m365_action_card_api.py .\functional_tests\test_m365_pending_authorization.py .\functional_tests\test_workflow_assist_cosmos_response_contract.py .\functional_tests\test_ask_ai_debug_diagnostics.py .\functional_tests\test_editor_assist_create_item_prompt.py -q --disable-warnings --tb=short
```

`python .\functional_tests\test_docs_app_surface_coverage.py` passes all seven
checks, and `python .\functional_tests\test_docs_site_quality.py` passes all six.
The full CI contract command,
`python .\scripts\check_cosmos_response_boundaries.py --run-contracts`, passes
**704 tests and 231 subtests** locally with external network access blocked.
It automatically selects the new owner-runtime evidence with its existing suites.

## Operation error container review follow-up (v0.261.331)

Fixed in version: **0.261.331**, recorded in `application/single_app/config.py`.
The CodeQL review on PR [#1760](https://github.com/microsoft/simplechat/pull/1760)
flagged `py/missing-equals`: `_OperationErrors` inherited list equality while
adding separate diagnostic metadata that those comparisons ignored.

The accumulator is now a plain object with explicit `messages` and `diagnostics`
lists, rather than a list subclass. Validation checks `messages` and supplies
that ordinary list to the correction exception. This removes the inherited
collection equality contract without adding unnecessary equality operators or
changing correction text, diagnostic limits, proposal atomicity or response bodies.
No CodeQL rule, CI check or domain validation is weakened.

`functional_tests/test_ask_ai_debug_diagnostics.py` adds regression cases for empty
accumulators, multiple messages, and a rejection count above the diagnostic limit.
They verify that messages remain an ordinary, ordered list while diagnostic
records are retained separately and capped. Existing core and creation-contract
tests exercise successful proposals, corrected rejections and terminal failures.

The three new cases fail against the original list subclass and pass after the
change. The targeted validation command passes **76 tests**:

```powershell
python -m pytest .\functional_tests\test_ask_ai_debug_diagnostics.py .\functional_tests\test_editor_assist_core.py .\functional_tests\test_editor_assist_create_item_prompt.py -q --tb=short
```

`python .\functional_tests\test_docs_app_surface_coverage.py` passes all seven
checks, and `python .\functional_tests\test_docs_site_quality.py` passes all six.
