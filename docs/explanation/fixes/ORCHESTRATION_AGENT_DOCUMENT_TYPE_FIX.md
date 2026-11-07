# Orchestration Agent Document Type Fix

**Version: 0.261.291**

Fixed in version: **0.261.291**, recorded in
`application/single_app/config.py`. Fixes
[#1699](https://github.com/microsoft/simplechat/issues/1699).

This affects the React V2 branch (`paullizer-react-v2-ui`) and deployments built
from it.

## Issue

In V2 chat with **Orchestrate** on, every **Ask an agent** (`agent_invoke`) step
failed before the agent ran:

> This step's agent or action isn't available to you right now, so it didn't run.
> Check that it still exists, is enabled and is shared with you, then retry.

The answering step then reported "A required dependency did not complete." It
happened in personal and shared conversations, for the agent the user picked and
for agents the planner chose. The same agent answered when Orchestrate was off.

It persisted after 0.261.289, the
[selected agent with agents turned off fix](ORCHESTRATION_SELECTED_AGENT_DISABLED_PREFERENCE_FIX.md).
Before that update, the reported deployment logged these failures with
`sc_authority_reason=result_external_capability_unavailable`. After it, the step
got past that check and failed at a later one:

- `[ORCHESTRATION_EXECUTOR] A dependency-bound step could not complete.`
- `sc_capability_id=agent_invoke`
- `sc_error_type=OrchestrationInvocationDeniedError`
- `sc_failure_code=integration_unavailable`
- `sc_authority_reason=result_external_source_unavailable`

## Root cause

Before an agent step runs, when its result is saved, and whenever the result is
read again, `OrchestrationExternalSourceProvider` rechecks that the user can still
reach that exact agent. It calls `resolve_delegation_agent`, which rechecks the
agent's scope settings, owner or group membership, governance and enabled state,
and returns the stored agent. The provider then required that agent to be exactly
a `dict`:

```python
if type(resolved) is not dict or agent_reference(resolved, identity.user_id) != expected:
    raise ResultUnavailableError("result_external_source_unavailable")
```

`resolve_delegation_agent` returned `deepcopy()` of a Cosmos DB point read. The
pinned `azure-cosmos==4.9.0` returns point reads as `CosmosDict`, a `dict` subclass
that carries response headers, and `deepcopy` keeps the subclass. So the check
refused every agent the resolver had just authorized. Action steps weren't
affected, because the action branch of the same method already used
`isinstance`.

The check has been in the provider since 0.261.127, when the Gather, Reason and
Render harness was added. It's the same class of bug as the
[Cosmos response compatibility fix](ORCHESTRATION_COSMOS_RESPONSE_COMPATIBILITY_FIX.md)
(0.261.140) and the [settings document type fix](ORCHESTRATION_SETTINGS_DOCUMENT_TYPE_FIX.md)
(0.261.237).

Chat without Orchestrate was unaffected because it loads the selected agent
through the Semantic Kernel loader, which never runs this check.

### How it was found

The provider logged one reason, `result_external_source_unavailable`, from nine
different places. The Azure SDK request logs in Application Insights placed it.
In both failed runs, the shared one and the personal one, the executor:

1. Read the user's settings, the conversation and the run.
2. Queried the agent catalogs. Narrowing to the picked agent succeeded: no
   `[ORCHESTRATION_CONTEXT] The selected agent is no longer available.` warning.
3. Made one point read of the picked agent's document, which returned 200.
4. Logged the refusal about 50 to 70 ms later.

The point read happens only after the resolver's scope and governance checks pass,
and a 200 rules out a missing agent. That left the checks after the read. The
existing provider tests, with only the fake container's point reads changed to
the real azure-cosmos 4.9.0 `CosmosDict`, reproduced the refusal after exactly one
agent point read.

### Why the tests missed it

The shared test fake, `functional_tests/test_support/agent_delegation.py`,
returned point reads as plain `dict` copies, so no test ever gave the provider the
SDK's type. The 0.261.289 deployment check confirmed the agent record's contents,
not the type the SDK returns.

## Changes

### The stored agent is a plain dictionary

In `functions_agent_delegation.py`, `_canonical_agent()` copies the point read into
a plain `dict` before it returns it. Every caller of `resolve_delegation_agent`
benefits, including chat delegation and prompt variables. The document's own
fields, including `_etag`, are unchanged. Only the SDK's separate response-header
object is dropped, and no caller uses it.

### The provider accepts any dictionary and still matches the exact agent

In `functions_orchestration_external_sources.py`, `_resolve_integration()` accepts
any `dict` from the agent resolver and copies it into a plain `dict`. It then
compares the agent's exact scoped reference (ID, scope type and scope ID) with
the catalog selection, as before. The provider never trusts the mapping's own
type or claims: the copy is what it checks and what it returns.

The 0.261.237 fix kept the provider's settings check exact and fixed the settings
store instead. That check is unchanged. Agents are handled at both layers so that
another reader of stored agents can't reintroduce this failure.

### Each refusal names the check that failed

The provider now logs each refusal once:
`[ORCHESTRATION_EXTERNAL_SOURCES] A step's source was refused.` It's a Warning
before and during a step, and Information when a saved result is read again,
because saved results are rechecked whenever they're opened. Its properties are:

- `sc_stage`: `external_source_preflight`, `external_source_admission` or
  `external_source_read`.
- `sc_authority_reason`: the refusal code the executor also logs.
- `sc_reason`: the check that failed, when the code covers more than one.
- `sc_capability_id`, plus `sc_conversation_id_hash`, `sc_run_id_hash` and
  `sc_step_id_hash`, which match the executor's failure event for the same step.

No user, agent, action, group or selector identifiers are logged.

| `sc_reason` | What failed |
| --- | --- |
| `selected_agent_unavailable` | The agent picked for the run no longer resolves in the user's catalog. |
| `selected_agent_ambiguous` | The catalog narrowed to the picked agent has more than one agent. |
| `selection_not_in_catalog`, `selection_ambiguous` | The step's agent or action isn't in the user's current catalog, or matches more than one entry. |
| `reference_not_in_catalog`, `reference_ambiguous` | A saved result's agent or action isn't in the user's current catalog, or matches more than one entry. |
| `integration_not_mapping` | The resolver didn't return a dictionary. |
| `integration_reference_mismatch` | The resolved agent isn't the exact agent selected. |
| `integration_origin_mismatch` | The resolved action isn't the exact action selected. |
| `integration_access_denied` | The resolver refused access: the scope is turned off, the user isn't the owner or a group member, or governance denies it. |
| `integration_not_found` | The agent or action is missing or disabled. |
| `reference_binding_mismatch` | A saved reference doesn't belong to this user, conversation or step. |
| `reference_identity_changed` | A saved reference no longer matches the current agent or action. |
| `required_setting_off` | A deployment setting the source needs is off. |
| `capability_allowlist_invalid` | The admin capability allowlist is malformed. |
| `capability_not_available` | The capability isn't available to this request, for example because the user's agents setting is off and no agent was picked. |
| `url_access_not_permitted` | The user's roles don't allow linked pages. |

The executor's failure event and the user's message are unchanged.

### The test fake returns the SDK's type

`DelegationServices` point reads now return `CosmosDictLike`, a `dict` subclass
that stands in for `CosmosDict`. Queries still return plain dictionaries, as the SDK
does. Any code that requires exactly `dict` on a stored record now fails in tests
as it did in production.

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_agent_delegation.py` | `_canonical_agent()` returns a plain `dict`. |
| `application/single_app/functions_orchestration_external_sources.py` | Accepts any `dict` from the agent resolver, names each refusal's check, and logs refusals. |
| `application/single_app/config.py` | Version `0.261.291`. |
| `functional_tests/test_support/agent_delegation.py` | Point reads return `CosmosDictLike`. |
| `functional_tests/test_orchestration_agent_document_type_fix.py` | New regression tests. |
| `docs/admin/orchestration.md` | Troubleshooting row. |
| `docs/explanation/features/ORCHESTRATION_EXTERNAL_SOURCE_ACCESS.md` | Resolver contract and refusal logging. |
| `docs/reference/logging-tags.md` | New tag and event. |
| `docs/explanation/release_notes.md` | 0.261.291 entry, and the missing 0.261.289 entry. |

No setting, deployment or data change is needed.

## Validation

### Tests

`functional_tests/test_orchestration_agent_document_type_fix.py` runs the real
provider, `resolve_agent_catalog` and `resolve_delegation_agent` over the test fake:

- The fake's point reads behave like the real azure-cosmos 4.9.0 `CosmosDict`, and
  its queries return plain dictionaries.
- `resolve_delegation_agent` returns a plain `dict`, with `_etag` kept, for
  personal, group and global agents.
- The reported case: a personal `m365` agent picked in the composer, with the
  agents setting on or off, passes the checks before and during the step, is saved,
  and stays readable. Picked and unpicked group agents do too.
- The provider accepts a dictionary subclass from its resolver, and refuses a
  non-dictionary or a different agent.
- Disabled agents, a group the user left, governance denial, group agents turned
  off, another user's agent and an agent missing from the catalog are still
  refused, each with its own `sc_reason`.
- Each refusal logs once, with the right stage and level, correlation hashes that
  match the executor's, and no identifiers. The properties survive the logging
  allowlist. Successful steps log no refusal.
- Action steps are unchanged.

On the previous code, 27 of its 31 tests fail. All 31 pass with the fix.

With the fake returning the SDK's type and before the fix, 35 tests and 9 subtests
failed in the existing suites, all of them Ask an agent steps refused at the same
check. With the fix, those suites match their plain-dictionary results exactly,
both with the updated fake and with the real azure-cosmos 4.9.0 `CosmosDict`: 968
tests and 232 subtests pass. The suites are `test_agent_delegation_*`,
`test_workspace_authoring_backend.py`, `test_app_settings_store_plain_dict_reads.py`
and the ten external-source orchestration suites. The 98 tests that fail do so with
or without this change: 79 in `test_workspace_authoring_backend.py`, and 19
`NameError`s in `test_agent_delegation_action.py` and
`test_agent_delegation_workflow_actor.py`.

These suites also pass with the change: `test_orchestration_agent_selection.py`,
`test_orchestration_v2_plan_backend.py`, `test_orchestration_external_identity.py`,
`test_orchestration_external_bootstrap.py` and `test_orchestration_external_pre_effect.py`
(202 tests and 180 subtests).

### Before and after

| Before | After |
| --- | --- |
| Every orchestrated Ask an agent step failed with "This step's agent or action isn't available to you right now". | The step runs the agent, as chat without Orchestrate does. |
| One refusal code came from nine places, and finding which one failed took request-level SDK logs. | A refusal event names the failed check. |
| Tests returned plain dictionaries for stored records, unlike the SDK. | Tests return the SDK's dictionary subclass. |
| Agents the user can't reach were refused. | Unchanged. |

## Limitations

- An agent that loads Microsoft 365 actions next goes through the existing
  Microsoft 365 checks, which can still stop the step to ask the user to sign in,
  approve, or use the agent from chat. Those have their own messages.
- Other orchestration code that reads Cosmos DB point reads wasn't audited for
  checks that require exactly `dict`.
- The executor's failure event doesn't carry `sc_reason`. Join it to the refusal
  event on `sc_run_id_hash` and `sc_step_id_hash`; see
  [orchestration failure diagnostics](../../reference/logging-tags.md#orchestration-failure-diagnostics).

## Related

- [Selected agent with agents turned off fix](ORCHESTRATION_SELECTED_AGENT_DISABLED_PREFERENCE_FIX.md)
- [Orchestration settings document type fix](ORCHESTRATION_SETTINGS_DOCUMENT_TYPE_FIX.md)
- [Orchestration Cosmos response compatibility fix](ORCHESTRATION_COSMOS_RESPONSE_COMPATIBILITY_FIX.md)
- [Retained orchestration external source access](../features/ORCHESTRATION_EXTERNAL_SOURCE_ACCESS.md)
- [Orchestration troubleshooting](../../admin/orchestration.md#troubleshooting)
