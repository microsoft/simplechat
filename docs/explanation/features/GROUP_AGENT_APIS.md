# Group Agent APIs (v0.261.138)

## Overview

Immutable-target routes for group agents, so the V2 group workspace can list,
open, create, edit and delete a group's agents in the same editor as personal
agents.

Implemented in version: **0.261.138**, tracked in
`application/single_app/config.py`.

Dependencies are the existing group agents Cosmos container (partitioned by
`/group_id`), current group membership, and the group agent settings described
below. No new setting, container, or index is required.

## Why new routes

The legacy `/api/group/agents` routes find their target in two different ways:

- **Reads** use `?group_id` when it is sent, and otherwise the caller's active
  group (`resolve_delegation_group_scope`).
- **Writes** (POST, PATCH, DELETE) always use the caller's active group
  (`require_active_group`), and save with an unconditional upsert, so a second
  editor silently overwrites the first.

The new routes name the group in the path, so they can only act on the group the
request names. An older server that lacks them returns 404 instead of editing
the wrong group. Every write is conditional.

The legacy routes keep their paths and behaviour, because the classic group
workspace still uses them.

## Availability

The whole native surface is available only when all of these hold:

- `enable_group_workspaces`, `enable_semantic_kernel` and
  `per_user_semantic_kernel` are on;
- `allow_group_agents` is on;
- the caller passes `governance_group_agents`.

One predicate, `group_agents_available` in `functions_group_agent_policy.py`,
decides this. The workspace context uses it for `sections.agents`, the
`agent_management` hint uses it, and every route below uses it. A test pins
that the context and the routes call the same function.

When it fails, every route refuses with 403 and the section's own reason:
"Group agents are not enabled." or "Your administrator has restricted access to
this capability." No data is returned.

## Who may do what

| | Read | Create, edit, delete |
|---|---|---|
| Owner, Admin | yes | yes, in an `active` group |
| DocumentManager, User | yes | no |

When `require_owner_for_group_agent_management` is on, only the Owner may
create, edit or delete. The write roles come from
`get_group_workflow_management_roles`, the function behind the workspace
context's `sections.agents.can_manage`.

| Status | Read | Write |
|---|---|---|
| `active` | yes | Owner, Admin |
| `upload_disabled`, `locked` | yes | no |
| `inactive`, or unrecognized | no | no |

## Immutable API family

`G` is the sole target of every route.

| Method and path | Purpose | Success |
|---|---|---|
| `GET /api/groups/G/agents` | List the group's agents | 200, `{"agents": [...]}` |
| `GET /api/groups/G/agents/A` | Read one agent | 200, editor resource |
| `POST /api/groups/G/agents` | Create an agent | **201**, editor resource |
| `PATCH /api/groups/G/agents/A` | Update an agent | 200, editor resource |
| `DELETE /api/groups/G/agents/A` | Delete an agent | 200, `{"success": true}` only |
| `GET /api/groups/G/agent-options` | Editor options for this group | 200 |
| `GET /api/groups/G/agent-knowledge` | Assigned-knowledge catalogue for this group | 200 |

The two side resources have their own path segments, so they can never collide
with an agent ID, and both send `Cache-Control: no-store`.

Every route carries `@swagger_route(security=get_auth_security())`,
`@login_required`, `@user_required`, and
`@enabled_required("enable_group_workspaces")`.

Requests are strict. **No route accepts a query parameter.** GET and DELETE
reject a request body. POST and PATCH require a JSON object and reject duplicate
keys. Each of these is a 400.

## Editor resources and writes

The routes use the personal agent editor contract, extended to group scope in
`functions_workspace_authoring.py`. A read, create, or update returns
`{record, revision, secret_paths, read_only}`, and POST and PATCH send
`{updates, expected_revision, clear_secret_paths, removed_paths}`.

- **A new agent needs a client-allocated UUID** in `updates.id`, from the
  scope-neutral `/api/agents/generate_id`, as for personal agents.
- Names must be unique within the group (409 otherwise). Unlike group actions,
  a group agent may reuse a global agent's name, as personal agents can.
- A masked secret sent back unchanged keeps its stored value, a secret is
  removed only through `clear_secret_paths`, and a client can never supply a
  Key Vault reference.
- **Group agent secrets are stored in the group's Key Vault namespace for the
  agent,** `{agent_id}--agent--group--…`, the namespace the legacy group route
  uses. A credential saved in V2 gets a fresh name within it. The classic and V2
  editors therefore interoperate in both directions:
  - an agent created in the classic workspace can be edited in V2 without
    re-entering its keys;
  - an agent created in V2 keeps its keys when edited in the classic workspace,
    and the classic delete removes them.

  Before this release the shared editor engine always used the `user` namespace
  for agents. One limitation remains: deleting in V2 an older agent whose stored
  record still holds the legacy placeholder, rather than a Key Vault reference,
  leaves that agent's secret in Key Vault.

Each save runs the same preparation as the personal editor, bound to `G`:

- payload sanitizing;
- assigned knowledge, resolved in group scope when it changed;
- `validate_agent`;
- the Call agent delegation bindings, in group scope.

**Agent types** follow the group flags: `allow_group_ai_foundry_agents` for
Azure AI Foundry, and `allow_group_new_foundry_agents` for New Foundry and
Foundry Workflow. A **custom model connection** needs
`allow_group_custom_endpoints` and `governance_group_endpoints`.

Conflicting edits behave as for group actions:

- a PATCH without `expected_revision` is 400;
- a stale revision is 409 with nothing written;
- DELETE takes no body or revision and deletes against the revision it has just
  read.

## Per-agent operations

Each agent carries `agent_actions`, computed on every request and never stored:

- `edit` and `delete` for a writer in an available, `active` group;
- `chat` whenever the agent is in the caller's chat agent picker. That is,
  `enable_group_workspaces` and `allow_group_agents` are on and the caller
  passes `governance_group_agents`, which is the rule the chat catalogue
  applies. `chat` is independent of edit rights, so an ordinary member sees
  `["chat"]`.

A seam test pins that the projector calls the policy function rather than using
a constant.

## Provided (global) agents

When `merge_global_semantic_kernel_with_workspace` is on, the list includes the
global agents the caller may use, and each opens read-only through
`GET /api/groups/G/agents/A`. They carry no `agent_actions`, so the group page
offers no edit, delete or "Use in chat" for them; they stay available from the
chat picker. With the merge off, a global ID is 404. PATCH and DELETE on a
global ID are refused.

## Editor options

`GET /api/groups/G/agent-options` returns the personal options shape, built for
the group:

- `agent_types`, enabled by the group flags, with the reason "Disabled for group
  workspaces by your administrator." when a flag is off;
- `model_endpoints`:
  - global endpoints the caller passes `governance_global_endpoints` for;
  - group endpoints when custom group endpoints are allowed;
  - never personal endpoints;
  - secrets masked;
- `builtin_actions`;
- `settings`, which carry `allow_group_custom_endpoints` (the flag and the
  governance check) and **no `allow_user_*` key**;
- `settings.agent_template_submission_allowed`: whether this caller may submit
  the agent to the template gallery. It uses the same rule as the template
  route, `agent_template_submission_decision` in `functions_agent_templates.py`:
  - the gallery must be on;
  - `allow_user_agents` and `agent_templates_allow_user_submission` must also
    be on, unless the caller is an administrator.

  The button is therefore offered exactly when a submission would be accepted.

A template submitted from a group agent is recorded as a personal submission,
as it is from the classic group workspace.

A caller without the write roles receives no model endpoints, no `gpt_model`, no
`default_model_selection` and no `builtin_actions`, and every `agent_types` entry is
disabled with the reason "Agent authoring is unavailable for this group
workspace."

## Assigned knowledge and drafting

- `GET /api/groups/G/agent-knowledge` returns the group's assigned-knowledge
  catalogue, `build_assigned_knowledge_catalog(agent_scope="group")`: the group's
  own documents and their tags, the same catalogue the classic group workspace
  uses. It never reads the caller's active group, personal knowledge or public
  workspaces.
- `POST /api/agents/draft-instructions` with `agent_scope: "group"` and a body
  `group_id`:
  - authorizes membership of **that** group and the availability above;
  - never falls back to the active group when `group_id` is present;
  - refuses with 404 "The selected group was not found." or 403 "You do not
    have access to the selected group.";
  - without `group_id`, behaves as before.

## Chat and activity

- Every save and delete bumps the global chat bootstrap cache version, exactly
  as the legacy `save_group_agent` and `delete_group_agent` do, so every
  member's chat picker refreshes.
- Every committed create, update and delete records the same activity event as
  the legacy routes: `log_agent_creation`, `log_agent_update` or
  `log_agent_deletion`, with `scope='group'` and the path group. A refused write
  records nothing, and a failure to record activity never undoes the committed
  change. The native group **action** routes now do the same with
  `log_action_*`; they logged nothing in 0.261.137.
- The stored document carries `is_group: true` and `is_global: false`, the shape
  the legacy `save_group_agent` writes. Runtime code, such as the agent loader
  choosing where Foundry secrets are resolved, branches on those flags. A first
  save in V2 of an agent created in the classic workspace keeps them.

## Workspace context

The selected-group context gains `agent_management`:

```json
{"schema_version": 1, "operations": ["create", "edit", "delete"]}
```

The operations are empty for anyone who cannot manage, and when the surface is
unavailable.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_group_agent_apis.py` | 92 | Every route's role, status and availability matrix; the owner-only setting; conditional writes and the DELETE shape; secret mask, clear and reference rules; the bootstrap cache bump; activity logging, including a failing logger and refused writes; stored `is_group`/`is_global` after create, update and a first V2 edit of a classic record; the template submission flag against the template route's rule for every combination of settings and administrator |
| `functional_tests/test_group_agent_chat_catalogue_pin.py` | 26 | `chat` in `agent_actions` exactly when the agent is in the real chat catalogue after the real governance filter; the Semantic Kernel flags do not move it; merged global rows advertise nothing |
| `functional_tests/test_group_agent_secret_roundtrip.py` | 5 | With Key Vault storage enabled: a classic key kept through a V2 edit; a V2 key removed by the classic delete, with no `user`-scope secret; a V2 key kept through a classic edit |
| `functional_tests/test_group_agent_secret_scope.py` | 5 | Agent secrets resolve to the `group` scope only with a group |
| `functional_tests/test_group_agent_runtime_compat.py` | 7 | A record saved through these routes works in the group agent reader, the chat catalogue, chat resolution, delegation, agent scope selection, and group workflow eligibility |
| `functional_tests/test_group_agent_drafting.py` | 8 | Drafting with a named group, without the active group; refusals and their messages; unchanged behaviour without a group |
| `functional_tests/test_group_agent_hint_seam.py`, `test_group_agent_transport.py` | 4, 7 | Hints come from policy; no route collides with a legacy route |
| `functional_tests/test_group_action_apis.py` | 63 | Includes activity logging for native group action writes |

On the integrated tree, the personal authoring suites are unchanged. That covers
`test_workspace_authoring_backend.py` (137, plus one failure inherited from the
base branch), `test_workspace_authoring_credential_compatibility.py` (11) and
`test_workspace_authoring_persistence.py` (17), with delegation permissions
(113), delegation runtime (41) and the workspace context (48). Route policy
passes 8/8, 4/4 and 2/2, and the broken-access-control scanner passes on every
changed backend module. Across 51 related functional test files, the failing
tests are identical to the base: zero regressions.

## Related

- [Group Action APIs](GROUP_ACTION_APIS.md)
- [V2 Group Agents](V2_GROUP_AGENTS.md)
