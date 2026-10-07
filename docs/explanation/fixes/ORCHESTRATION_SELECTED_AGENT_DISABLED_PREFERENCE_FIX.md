# Orchestration Selected Agent With Agents Turned Off Fix

**Version: 0.261.279**

Fixed in version: **0.261.279**, recorded in
`application/single_app/config.py`.

## Issue

A user picked their personal `m365` agent in the V2 composer, turned on Orchestrate and
asked "What are my latest emails?" in a shared conversation. Planning produced an
**Ask an agent** step for that agent, and the step failed with "This step's agent or
action isn't available to you right now, so it didn't run." The answering step then
reported "A required dependency did not complete."

The same question worked in the user's own conversation, so the failure looked like a
shared-conversation problem. It wasn't one.

The executor's failure event logged `OrchestrationInvocationDeniedError` with
`sc_authority_reason=result_external_capability_unavailable` for `agent_invoke`.

## Root cause

The user's own agents setting (`enable_agents`, the agents button on the classic chat
page) was off. V2 has no control for it, and `update_user_settings` stores it as off the
first time it saves a user's settings without it, so any V2 user who never turned agents
on in classic chat could hit this.

Picking an agent by hand is itself permission to use that agent. Classic chat lets a
picked agent answer while the setting is off (`force_enable_agents`), and the planner,
plan editing and the execution harness treat a picked agent as enabled and narrow the
agent catalog to it.

`OrchestrationExternalSourceProvider` didn't. It rechecks access to an agent step's exact
agent just before the step runs, and on every later read of the step's result. It used
the raw setting and an un-narrowed catalog, so the agent request gate
(`_agent_request_gate`) refused `agent_invoke` and the step was denied before it ran. The
deployment allowed Semantic Kernel, personal agents and `agent_invoke`, so the refusal
didn't come from the deployment settings check, which reports the same reason.

The user's own conversation worked only because no agent was picked there. Without a
pick, the planner offers agents only while the setting is on, so that plan used a **Use
an action** step instead, and action steps don't depend on the agents setting. Sharing
played no part. The provider accepted the shared conversation's audience before its
capability check, and that check reads the same setting in personal and shared
conversations, so a picked agent fails the same way in a personal conversation.

An earlier failure in the same deployment, logged with `external_configuration_unavailable`,
came from the configuration check that 0.261.270 removed for agent and action steps. See
the [session-trusted action and agent steps fix](ORCHESTRATION_SESSION_TRUSTED_ACTION_AGENT_STEPS_FIX.md).

## Changes

In `functions_orchestration_external_sources.py`:

- `_seeded_agent(run)` reads the agent picked for the run, `run["seeds"]["agent"]`. Only a
  dictionary with a non-blank string `name` counts. Anything else is treated as no pick,
  so the setting still applies.
- `_catalog()` passes a pick to the agent catalog reader as `seeds={"agent": ...}`, so
  `resolve_agent_catalog` narrows the catalog to that agent exactly as planning and
  execution did. A pick that no longer resolves (`selected_agent_unavailable`) is
  reported as `result_external_source_unavailable`, and a catalog outage still raises
  `catalog_unavailable`. A narrowed catalog with more than one agent is refused.
- `_capability()` treats the agents setting as on when there's a pick. The catalog is
  already narrowed, so this lifts the setting for the picked agent only.
- The check before a step runs (`_gather_invocation_state`), result admission and every
  later read (`_reference`) all use the pick. Action steps never receive it.

What doesn't change:

- The provider still calls `resolve_delegation_agent` for the exact agent, so scope
  settings, group membership, governance and the agent's enabled state are rechecked
  every time the step runs or its result is read.
- A step for an agent the user didn't pick still needs the agents setting on.
- A pick only selects a record from the user's current catalog. Its own name, scope and
  ID fields are never proof of access.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_orchestration_external_sources.py` | Narrow the agent catalog to the run's picked agent and honour the pick in the capability check. |
| `application/single_app/config.py` | Version `0.261.279`. |
| `functional_tests/test_orchestration_seeded_agent_preference_fix.py` | New regression test. |
| `docs/admin/orchestration.md` | Picked agents run while the agents setting is off; troubleshooting row. |
| `docs/explanation/features/ORCHESTRATION_EXTERNAL_SOURCE_ACCESS.md` | Picked-agent catalog narrowing in the provider contract. |

## Validation

### Tests

`functional_tests/test_orchestration_seeded_agent_preference_fix.py` runs the real
provider and the real `resolve_agent_catalog` over in-memory agents:

- The reported case: a personal agent picked while the agents setting is off is checked,
  admitted and read back.
- A picked group agent runs and stays readable with the setting on or off, and every
  catalog read is narrowed to its group.
- Removing group membership, denying group-agent governance, turning off group agents or
  disabling the agent still denies the check before the step and later reads.
- Without a pick, the setting still applies.
- A pick doesn't lift the setting for a different agent named in the plan step.
- A pick that no longer resolves (a removed agent, another group, or a name alone) is
  unavailable, and a catalog outage is still reported as an outage.
- A narrowed catalog with more than one agent is refused.
- Malformed picks don't lift the setting, and action steps never receive the pick.

16 of its 29 tests fail against the provider from 0.261.278, including the reported case.

With the new file, these existing suites pass unchanged, 506 tests and 282 subtests in
all: `test_orchestration_external_sources.py`, `test_orchestration_session_trusted_sources.py`,
`test_orchestration_external_identity.py`, `test_orchestration_external_bootstrap.py`,
`test_orchestration_external_pre_effect.py`, `test_orchestration_external_preflight_adapter.py`,
`test_orchestration_agent_selection.py` and `test_orchestration_v2_plan_backend.py`.

### Deployment check

Read-only reads of the affected deployment confirmed that, with the fix, the picked agent
also passes the scope, governance and agent record checks that follow. It's a personal
`local` agent owned by the user and isn't disabled, and the deployment allows Semantic
Kernel, personal agents (with personal-agent governance off) and `agent_invoke`.

### Before and after

| Before | After |
| --- | --- |
| With the agents setting off, an Ask an agent step for a picked agent failed with "This step's agent or action isn't available to you right now". | The step runs, as the same agent does in chat. |
| The planner offered a picked agent that the step's access check then refused. | Planning, execution and the access check agree on the picked agent. |
| An agent the user didn't pick needed the agents setting on. | Unchanged. |

## Limitations

- A pick narrows the access check to that agent, so in a run with a pick, a step for any
  other agent is refused even with the agents setting on. Planning and plan editing offer
  only the picked agent, so a valid plan never contains one.
- Results that a picked agent's step already produced stay readable only while the user
  can still reach that agent, as for any agent step.

## Workaround for earlier versions

Turn agents on with the agents button on the classic chat page (`/chats`). Or, when the
work is also available as one of the user's actions, ask without picking an agent so the
plan uses the action directly, as it did in the user's own conversation.

## Related

- [Retained orchestration external source access](../features/ORCHESTRATION_EXTERNAL_SOURCE_ACCESS.md)
- [Orchestration session-trusted action and agent steps fix](ORCHESTRATION_SESSION_TRUSTED_ACTION_AGENT_STEPS_FIX.md)
- [Actions and agents](../../admin/orchestration.md#actions-and-agents)
