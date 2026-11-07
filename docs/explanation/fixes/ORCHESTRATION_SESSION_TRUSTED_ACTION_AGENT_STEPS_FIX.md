# Orchestration Session-Trusted Action and Agent Steps Fix

**Version: 0.261.270**

Fixed in version: **0.261.270**, recorded in
`application/single_app/config.py`.

Fixes [#1660](https://github.com/microsoft/simplechat/issues/1660) and
[#1661](https://github.com/microsoft/simplechat/issues/1661). This affects the React
V2 branch (`paullizer-react-v2-ui`) and deployments built from it.

## Issue

With **Orchestrate** on, "what are my emails" failed in both personal and shared
chats. The plan's **Use an action** step for the user's Microsoft 365 Email action
failed with "A required retained result is unavailable or changed." The same
request worked with Orchestrate off.

Plans also couldn't use local agents. Picking an agent and asking it to read mail
produced a plan whose **Ask an agent** step failed the same way.

Production telemetry showed every affected step failing with
`authority_reason=external_configuration_unavailable` for `action_invoke` and
`agent_invoke`.

## Root cause

Before 0.261.270, agent and action steps were held to configuration attestation, the
check that web search, linked-page reading and deep research use. A step captured
the agent's or action's configuration when it ran, and the result was admitted and
read back only while a fresh read of that configuration matched the capture.

That check couldn't work for these steps:

1. **Microsoft 365 actions.** `invoke_action` enters the step's Microsoft 365 scope
   (0.261.238) before the engine runs. The attestor's fresh read called
   `prepare_action_plugin_manifest`, whose Microsoft 365 preflight rebuilt the
   manifest as a plain dictionary and dropped its `ScopedActionManifest` origin.
   The origin check then refused it with `external_configuration_action_origin_required`,
   reported as `external_configuration_unavailable`. Results retained before an
   action edit would also have read as "changed".
2. **Local agents.** `_preflight_captured_agent` refused local agents and agents
   with knowledge or web sources while a capture was active, and the Semantic Kernel
   loader refused most plugins under capture.
3. **Agent Microsoft 365 actions.** An agent step had no Microsoft 365 request, so
   an agent's Microsoft 365 actions were refused with `m365_context_required`.
4. **Agent tags.** In Orchestrate mode an explicit @agent tag in the message didn't
   choose that agent. Planning only offered agents when one was picked, or when the
   user's classic agents switch was on, which V2 users can't change.

## Changes

### Agent and action steps trust the signed-in session

Agent and action steps now trust the signed-in session the way manual chat does.
Web search, linked-page reading and deep research keep configuration attestation.

- `OrchestrationExternalSourceProvider` (`functions_orchestration_external_sources.py`)
  treats agent and action sources as session-trusted. A new reference gets a stable
  identity and revision from its scope and ID, without calling the configuration
  reader. Each later read rechecks current access to that exact agent or action, and
  results admitted under attestation by earlier versions stay readable.
  `preflight_session_acquisition()` checks current access to the exact selection
  before the step runs.
- `build_orchestration_services` (`functions_orchestration_bootstrap.py`) routes
  agent and action captures to that preflight and records the selector the step
  checked. Admission of an agent or action result requires that record, so the
  root still refuses a result without a session-checked acquisition.
- `run_action_invoke` and `run_agent_invoke` (`functions_orchestration_adapters.py`)
  check access once and then run the classic engines without an invocation capture.

### Agents in plans

- An agent step whose agent loads actions enters a Microsoft 365 step scope for
  that agent's own Microsoft 365 actions (`agent_step_scope()` in
  `functions_orchestration_m365.py`). `step_selected_m365_manifests()` resolves a
  selection of kind `agent` the way a chat-selected agent's actions resolve, and an
  agent without Microsoft 365 actions gets no context and leaves no request record.
  `execute_target()` and `invoke_scoped_agent()` in `agent_delegation_runtime.py`
  accept an optional `scope`, entered inside the agent's bridge.
- The V2 composer (`Composer.tsx`) seeds the plan with an explicit @agent tag as its
  agent, or an @model tag as its model, ahead of the composer's pickers. A seeded
  agent is always offered to the planner, and the planner asks it rather than using
  its actions directly.

### Diagnostics

- `_read_metadata` (`functions_orchestration_external_configuration.py`) keeps a
  specific refusal code instead of reporting every refusal as
  `external_configuration_unavailable`.
- A refusal from an integration now fails with the new `integration_unavailable`
  failure, whose message names the integration instead of retained results.

## Files modified

| File | Change |
| --- | --- |
| `functions_orchestration_external_sources.py` | Session-trusted references and `preflight_session_acquisition()`. |
| `functions_orchestration_bootstrap.py` | Session preflight for agent and action captures, and admission from its record. |
| `functions_orchestration_adapters.py` | Access check, then the classic engines; the agent Microsoft 365 scope. |
| `functions_orchestration_m365.py` | `agent_loads_actions()` and `agent_step_scope()`. |
| `functions_m365_runtime.py` | Agent selections in `step_selected_m365_manifests()` and `step_m365_context()`. |
| `agent_delegation_runtime.py` | Optional `scope` for `execute_target()` and `invoke_scoped_agent()`. |
| `functions_orchestration_external_configuration.py` | Specific refusal codes. |
| `functions_orchestration_schema.py`, `functions_orchestration_executor.py` | `integration_unavailable` failure. |
| `v2_ui/src/components/chat/Composer.tsx` | @agent and @model tags seed the plan. |
| `config.py` | Version `0.261.270`. |

## Validation

### Tests

- `functional_tests/test_orchestration_session_trusted_sources.py` runs the real
  provider for agents and actions: admission rechecks access without reading
  configuration, results survive configuration edits until access is revoked,
  results admitted under attestation stay readable, and the session preflight needs
  current access to the exact selection. All nine tests fail on 0.261.264.
- `functional_tests/test_orchestration_external_bootstrap.py` runs the real root:
  an action step trusts the session without rereading configuration, and admission
  without its session-checked acquisition is refused.
- `functional_tests/test_orchestration_m365_actions.py` adds agent step scopes: an
  agent's own Microsoft 365 action is the only one selected, an agent without one
  gets no context, and a removed agent stops before any Microsoft 365 work.
- `functional_tests/test_orchestration_external_configuration_capture.py` and
  `test_orchestration_external_capture_integration.py` were updated deliberately:
  their agent and action cases asserted attestation, and now assert one session
  access check followed by the classic engine. Their web, URL and deep research
  cases are unchanged.
- `functional_tests/test_v2_shared_orchestration_routing.mjs` checks the composer's
  tag seeding.

### Before and after

| Before | After |
| --- | --- |
| Every Microsoft 365 action step failed with "A required retained result is unavailable or changed." | The step reads mail, calendar or files, as manual chat does. |
| Local agents couldn't run as plan steps. | Local agents run, including their Microsoft 365 actions. |
| Editing an action invalidated results it had already produced. | Results stay readable until access to the action or agent is lost. |
| An @agent tag didn't choose the agent in Orchestrate mode. | An @agent or @model tag seeds the plan. |

## Limitations

- This relaxes a check, deliberately. Access to the conversation, run, agent and
  action is still checked on every read, but a mid-run edit to an agent or action is
  no longer detected. A lighter check may follow.
- Without a seed, planning still offers agents only when the user's classic agents
  switch is on.

## Related

- [Retained external-source authorization](../../admin/orchestration.md#retained-external-source-authorization)
- [Microsoft 365 actions in plans](../../admin/orchestration.md#microsoft-365-actions-in-plans)
- [Orchestration Microsoft 365 action context fix](ORCHESTRATION_M365_ACTION_CONTEXT_FIX.md)
- [Orchestration shared conversations fix](ORCHESTRATION_SHARED_CONVERSATIONS_FIX.md)
