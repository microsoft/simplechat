# Agent delegation actions (v0.261.093)

## Overview

Call agent is a reusable Semantic Kernel action that connects a local SimpleChat
agent to one explicitly selected agent. It supports specialization without
replacing the caller's chat identity or automatically sharing its conversation.

Implemented in version: **0.261.093**.

The version update is in `application/single_app/config.py`. Dependencies are the
existing Semantic Kernel runtime, agent/action Cosmos containers, governance and
workspace access helpers, and the configured target model or Foundry runtime.
No new browser runtime dependency, storage container, or deployment setting is required.

## Configuration and authorization

The action uses type `agent`, endpoint `internal://agent`, and current-user
authentication. `additionalFields.target_agent` contains the target's ID,
`scope_type`, and `scope_id`. The action never stores a copy of the target's
connection settings or credentials.

`functions_agent_delegation.py` validates manifests, resolves canonical stored
records, builds a safe target catalogue, and checks action attachment and target
authorization. Target references use exact IDs and scopes; there is no fallback
to another same-named agent or to the default agent.

Personal calls stay with the invoking user's agents; group calls stay with their
group. Both can use permitted global agents when global workspace merging is
enabled. Global callers/actions can reference only global agents. Runtime checks
include current group membership, scope enablement, agent-use governance,
action-type governance, and applicable global item policies.

Manual group workflow runs use the authenticated member who started the run,
not the workflow creator. Scheduled runs without an interactive actor use the
workflow owner's declared execution identity. Workflow ownership remains
separate from the identity used to authorize agent calls.

The target catalogue is served by `GET /api/plugins/agent-targets`, with a
personal/group/global `scope` and an optional explicit `group_id`. It returns
display metadata rather than instructions or secrets.

The `PATCH /api/user/agents/<agent_id>/agent-actions`,
`PATCH /api/group/agents/<agent_id>/agent-actions`, and
`PATCH /api/admin/agents/<agent_id>/agent-actions`
handlers accept selected `action_ids` and the original
`expected_actions_to_load`. They preserve unrelated bindings and configuration,
then apply a conditional Cosmos patch using the current ETag. A changed list or
ETag returns a conflict instead of overwriting another editor.

Foundry consent links use `GET /api/agents/foundry-auth` with the canonical
target reference. This normal authenticated request rechecks target access,
derives OAuth scopes from the saved configuration, and persists the scope request
before redirecting to Entra. Streaming responses cannot persist session changes
after their headers have been sent, so they do not redirect directly to an
unpersisted consent flow.

## Runtime

`semantic_kernel_plugins/agent_plugin.py` exposes an async `call_agent` function
with task and optional context inputs. Target identity and authorization are
resolved server-side, not accepted as model-selected arguments.

The delegation runtime constructs an isolated target instance using existing
model-resolution and action-loading code. Local targets use their own
instructions, actions, capability restrictions, and authorized assigned
knowledge. Foundry targets use the existing async classic, application, or
workflow execution adapter. Their tools remain managed in Foundry.

A root-owned budget is shared across nested calls and sibling calls: at most
3 delegated levels, 10 delegated attempts, and 120 seconds per delegated call.
Ancestor identity includes scope, so renames or same-name agents cannot defeat
cycle checks. Deadlines include descendants.

Integration covers both chat invocation paths, agent workflows, and V2
orchestration workers. The worker boundary carries trusted execution context
instead of assuming that Flask request state is present. Failed or cancelled
calls restore context and do not change selected-agent or active-workspace
preferences.

Only the task and explicit context are automatically handed to the target. The
parent remains responsible for the final response. Delegation activity, original
source citations, and observed usage remain associated with the root message/run.

## User interfaces

Classic configuration extends the shared plugin and agent modal steppers.
Call agent has a target picker and summary rather than external endpoint or
credential inputs.

V2 uses focused reusable delegation controls in personal Actions/Agents, group
delegation management, and the admin Agents & Actions area. These controls do
not replace unrelated connector, model, or full group-management interfaces.

See [Call another agent](../../guides/call-another-agent.md) for a workflow and
[Call agent](../../reference/actions/agent.md) for permissions and troubleshooting.

## Coverage and limitations

Functional coverage includes manifest validation, exact scoped references,
permission changes, disabled/deleted targets, explicit attachment, conditional
binding updates, nested limits, cancellation, provider adaptation, worker
contexts, and preservation of existing agent behavior.

Python Playwright coverage exercises classic and V2 authoring and attachment,
including personal/group/admin scopes, unavailable targets, conflicts, and
safe rendering. These tests live under `ui_tests/`; backend regression tests
use the `functional_tests/test_agent_delegation_*` prefix.

Delegation adds model calls and therefore latency and usage. Provider usage is
reported only when observed, not estimated. A provider may continue a request
already submitted when local cancellation occurs; stopping a conversation is
not a rollback of external writes. Scheduled execution cannot bypass a target's
delegated-user authentication requirements.
