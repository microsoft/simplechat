# Orchestration Chat Reliability Fix

**Version: 0.261.341**

Fixed/Implemented in version: **0.261.341**, recorded in
`application/single_app/config.py`.

## Issue and root causes

Two reported chat failures had different causes. A long direct conversation
completed successfully, but an orchestrated follow-up did not retain its pasted
source material. Its plan searched workspaces instead. Search preview clipping
then marked every output partial, including the source selection, and a
complete-only analysis correctly refused the partial input. Dependent writing
was skipped. The saved attempt did not show a provider context-window error.

The other request failed before invoking the Control Center action. Its worker
did not forward authenticated roles to action discovery and exact manifest
resolution. That defect was already fixed in **0.261.329**; this change does
not introduce another authorization exception. See the
[Control Center role-propagation fix](CONTROL_CENTER_ORCHESTRATION_ROLE_PROPAGATION_FIX.md).

Broader investigation identified two additional reliability problems:

- The V2 Orchestrate choice lived in component state and could reset when the
  composer remounted.
- A deleted workflow could raise during a pending Microsoft 365 continuation's
  readiness check, abort later candidates, and remain eligible for the next
  scheduler tick. Repeated errors were not evidence of unique failed workflows
  or the demonstrated cause of either chat failure.

An HTTP 200 for an established SSE response did not prove that the chat itself
completed. Direct-stream cancellation also used error-level failure logging.

## Changes and impact

Search results retain authoritative content separately from bounded UI/model
previews. Complete source identity selection is distinct from excerpt coverage
and from an exhaustive search of a corpus. A genuinely partial upstream result
still cannot be promoted to complete by analysis or composition.

Full search hits are committed before preview construction. Overflow refuses
the operation instead of committing shortened data. Historical clipped
checkpoints remain incomplete and do not offer an unchanged retry as a repair.
Analysis carries the selected-source lineage and its limitations forward.
`search_result_too_large` identifies retention overflow;
`search_result_incomplete` identifies a retained search that cannot safely
serve as complete input. Neither is repaired by silently shortening the source.

Conversation-first transformation requests use authorized saved-message
references rather than treating a shortened planning snapshot as the full
source. Missing or ambiguous targets require clarification; full input must
fit the selected model's verified budget. Earlier assistant claims remain
conversation content, not independently verified document evidence.

Full input means selected eligible text after existing masking, block-revision,
moderation, and saved-analysis checks, not raw hidden content. When transforming
a selected assistant answer, its associated user source is included. Discovery
still has a 16 KiB budget and reference/count limits, so older whole turns can
be excluded. Oversized input fails explicitly; there is no automatic splitting.
Exact, untruncated legacy snapshots can remain compatible after current checks,
but clipped or count-truncated legacy snapshots require replanning.

The V2 execution-mode choice is associated with the signed-in account and
conversation in the browser. Returning to a conversation or reloading should
not silently switch a deliberately direct conversation into Orchestrate.
Capability availability remains authoritative; remembering a choice never
enables an unavailable capability.

Microsoft 365 continuation checks isolate individual failures. A typed,
confirmed missing workflow can leave the pending queue through a conditional
terminal update. Transient service failures are not classified as deletion,
and uncertain external effects require recovery rather than automatic replay.

`[CHAT_EXECUTION]` records direct and orchestration outcomes independently of
transport status. Events contain categorical outcomes, safe failure and
capability codes, hashed identifiers, and the application version when known.
Orchestration records confirmed saved outcomes rather than declaring success
merely because an HTTP request returned 200. Cancellation is informational.
Prompts, replies, source text, raw identities, and credentials are not included.

## Implementation boundaries

| Area | Main files |
| --- | --- |
| Search retention and completeness | `functions_orchestration_adapters.py`, `functions_orchestration_result_runtime.py`, analysis result and recovery owners |
| Failure and dependency semantics | `functions_orchestration_schema.py`, `functions_orchestration_executor.py`, `functions_orchestration_recovery.py` |
| Conversation source resolution | `functions_orchestration_context.py`, `functions_orchestration_planner.py`, composition and execution owners, `route_backend_orchestration.py` |
| Conversation mode | V2 `conversationMode.ts`, `Composer.tsx`, chat/bootstrap stores and conversation lifecycle callers |
| Continuation containment | `functions_m365_continuations.py`, `functions_m365_runtime.py`, `background_tasks.py` |
| Semantic diagnostics | `functions_appinsights.py`, `functions_orchestration_execution.py`, `route_backend_chats.py` |
| Application version | `application/single_app/config.py`: `0.261.340` to `0.261.341` |

No new route, capability setting, deployment setting, source permission, model
context limit, or automatic retry policy is added.

## Validation

Regression coverage includes authoritative search bytes and genuine partial
lineage, long conversation references and input budgets, account/conversation
mode isolation, deleted/transient/conflicting continuation cases, and semantic
outcome privacy and cancellation. The execution harness also verifies durable
publication, authorization revocation, and cached SSE replay without another
execution outcome.

Related tests:

- `functional_tests/test_orchestration_search_result_integrity.py`
- `functional_tests/test_orchestration_conversation_sources.py`
- `functional_tests/test_v2_conversation_mode_logic.mjs`
- `ui_tests/test_v2_conversation_mode_persistence.py`
- `functional_tests/test_m365_continuations.py`
- `functional_tests/test_m365_workflow_continuation_boundary.py`
- `functional_tests/test_orchestration_failure_telemetry.py`
- `functional_tests/test_chat_content_streaming.py`
- `functional_tests/test_control_center_orchestration_roles.py`

The original Control Center role and dependency baseline passed **112 tests**
in an isolated environment with the application's pinned Flask, Werkzeug, and
Semantic Kernel versions. The initial semantic-outcome and direct-stream run
passed **39 tests and 4 subtests**.

Additional completed checks:

| Check | Result |
| --- | --- |
| Search retention, native analysis, dependency runtime, result/recovery safety | 322 passed |
| Conversation source and context regressions | 74 passed, 27 subtests |
| Microsoft 365 continuation, SDK boundary, authorization and operation integration | 204 passed, 32 subtests |
| Optimized continuation/boundary regressions | 44 passed, 13 subtests |
| Real execution/publication harness, Control Center roles and write fences | 684 passed, 2 expected failures |
| Combined semantic diagnostics, direct streaming and dependency runtime | 134 passed, 4 subtests |
| Final combined context, search, continuation, diagnostics, direct streaming and Control Center regressions | 146 passed, 17 subtests |
| V2 TypeScript check and production build | Passed |
| Browser mode persistence, approval preference and existing composer | 11, 23 and 7 passed respectively |
| Browser saved-run recovery | 35 passed |
| Browser conversation-context transport | 5 passed, 3 subtests |
| Account/conversation mode logic | 5 Node tests passed |
| Reviewed Cosmos response-boundary inventory | 1,059 owners, 404 doubles, 0 review gaps |
| Mandatory network-blocked Cosmos contract gate | 945 passed, 244 subtests passed |
| Documentation surface coverage and site quality | 13 passed |

The final combined 146-test run was repeated with the manifest-pinned
`azure-cosmos==4.9.0`. Missing/mismatched validation dependencies were restored
only in the session's isolated Python environment; application requirements and
shared Python installations were not changed. Tokenizer data is warmed in a
session cache so network-blocked tests do not download assets while running.
The full `scripts/check_cosmos_response_boundaries.py --run-contracts` gate
passed after restoring the declared `yamcs-client==2.1.0` dependency in that
same isolated environment. Missing validation dependencies were not treated as
application defects, and the contract checks were not weakened.

Browser suites with different Playwright fixture lifecycles run in separate
processes. The recovery fixture now answers the existing pending-credentials
lookup with an empty request list, rather than treating that unrelated
background lookup as an unexpected API call.

An extra broad logging run found two pre-existing failures: nonstandard tags
in unchanged modules, and a legacy test expecting a pre-sanitization debug
message. Both were reproduced against `HEAD` without changing the worktree.
This change adds no missing or stale documented logging tag. Those unrelated
checks were not weakened to make the run pass.

A broader planner/route/harness run passed **803 tests with 2 expected
failures**, but had **10 setup errors** in an older AST-extraction diagnostic
fixture. That fixture omits `normalize_public_workspace_selection` from the
namespace used by `resolve_seeds`. Both the failing production function and
the extraction fixture are unchanged from `HEAD`; attribution is based on
that source identity, not a clean-HEAD rerun of the entire suite.

### Configured production image evidence

Read-only registry inspection identified the configured image digest
`sha256:f36fb6a60c7205923639118aefababc6a7f3ab7b455d4bd6a6d72eaa6fbb5118`
as application **0.261.337**. Its
`functions_orchestration_external_sources.py` matches the already-fixed
worktree source after newline normalization. The file's SHA-256 is
`1f792e425bbc54a3cd7fa6fd5dfad7aa5e54c16e3d7611c0a57d4c675116cd96`.
The image has no OCI revision/version labels, so an exact repository commit
was not inferred from its timestamp.

This verifies the configured immutable image's contents, not every active
worker or the end-to-end metrics/chart outcome. No production deployment,
conversation retry, continuation cleanup, or permissions change was performed.

## Operational diagnosis

Application Insights stores the useful fields in `Properties`; `Message` is
usually the literal `[SIMPLE_CHAT_LOG_EVENT]`. Do not count all HTTP 200
orchestration requests as successful chats.

### Semantic outcomes by execution path

```kusto
AppTraces
| where TimeGenerated > ago(24h)
| where Message == "[SIMPLE_CHAT_LOG_EVENT]"
| extend p = todynamic(Properties)
| where tostring(p.sc_message) == "[CHAT_EXECUTION] Execution outcome recorded."
| summarize executions=count()
    by path=tostring(p.sc_execution_path),
       outcome=tostring(p.sc_outcome),
       failure=tostring(p.sc_failure_code),
       version=tostring(p.sc_application_version)
| order by executions desc
```

These are observed outcome transitions, not a denominator for every submitted
request. Waiting/resumption and separate retry attempts can produce different
transitions. Correlate hashed run and attempt fields when measuring unique runs;
telemetry sampling or a worker failure can also affect event counts.

### Follow one conversation without logging its contents

Compute the UTF-8 SHA-256 hex digest of the conversation identifier locally,
then substitute it below. Do not paste prompts, raw IDs, or keys into telemetry.

```kusto
AppTraces
| where TimeGenerated > ago(7d)
| where Message == "[SIMPLE_CHAT_LOG_EVENT]"
| extend p = todynamic(Properties)
| where tostring(p.sc_conversation_id_hash) == "<sha256-hex>"
| project TimeGenerated,
    event=tostring(p.sc_message),
    path=tostring(p.sc_execution_path),
    outcome=tostring(p.sc_outcome),
    failure=tostring(p.sc_failure_code),
    capability=tostring(p.sc_capability_id),
    run=tostring(p.sc_run_id_hash),
    step=tostring(p.sc_step_id_hash)
| order by TimeGenerated asc
| take 200
```

### Check the historical stale-workflow error storm

```kusto
AppServiceConsoleLogs
| where TimeGenerated > ago(24h)
| where ResultDescription contains "[WORKFLOW_SCHEDULER]"
| where ResultDescription contains "The workflow no longer exists."
| summarize events=count() by bin(TimeGenerated, 15m)
| order by TimeGenerated asc
```

After an explicitly approved rollout, confirm the running immutable build,
exercise fresh authorized direct/context and Control Center requests, and check
that stale errors stop while valid continuations still proceed. Do not treat
quiet logs alone as proof that workflow processing works. Saved-attempt retries
must pass their current recovery and authorization checks; no completed external
effect should be replayed to test the fix.
