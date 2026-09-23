# Group Prompt APIs (v0.261.136)

## Overview

Immutable-target routes for group prompts, together with a fix to who may
change group prompts through the existing legacy routes.

Implemented in version: **0.261.136**, tracked in
`application/single_app/config.py`.

Dependencies are the existing group prompts Cosmos container, current group
membership, and `enable_group_workspaces`. No new setting, container, or index
is required.

## Why new routes

The five legacy `/api/group_prompts` routes find their target group from the
user's stored active group. If that selection is stale — another tab, a recent
switch — a create, edit, or delete lands in a different group from the one on
screen. The new routes name the group in the path, so they can only act on the
group the request names. An older server that lacks them returns 404 instead of
acting on the wrong group.

The legacy routes keep their paths and active-group targeting, because the
classic group workspace still uses them.

## Who may change group prompts

Only **Owner**, **Admin**, and **DocumentManager** may create, edit, or delete a
group prompt. Ordinary members (`User`) may read prompts and use them in chat.
Rewording a prompt in the chat composer is a change to that one message; it is
never saved to the group's prompt.

This applies to **both** the new routes and the legacy routes.

> **Fixed in this release.** The legacy POST, PATCH, and DELETE routes admitted
> ordinary members, so any member could create, edit, or delete the group's
> shared prompts by calling the API directly. The classic interface never
> offered them those actions — its own check allows management only for the
> manager roles — so the server simply had not enforced what the interface
> showed. The legacy writes now refuse ordinary members with 403, "Only group
> owners, admins, and document managers can change group prompts", matching the
> rule public prompts already enforced. The legacy reads are unchanged. See the
> [fix write-up](../fixes/GROUP_PROMPT_WRITE_ACCESS_FIX.md).

The classic interface's check also names a `PromptManager` role. It appears
nowhere else in the application and nothing can assign it, so it grants
nothing. It is not part of the server policy.

## Immutable API family

All paths start `/api/groups/G/prompts`. `G` is the sole target.

| Method and path | Purpose | Success |
|---|---|---|
| `GET /api/groups/G/prompts` | List the group's prompts | 200 |
| `GET /api/groups/G/prompts/P` | Read one prompt | 200 |
| `POST /api/groups/G/prompts` | Create a prompt | **201**, the new prompt |
| `PATCH /api/groups/G/prompts/P` | Update a prompt | 200, the updated prompt |
| `DELETE /api/groups/G/prompts/P` | Delete a prompt | 200, `{message}` only |

Every route carries `@swagger_route(security=get_auth_security())`,
`@login_required`, `@user_required`, and
`@enabled_required("enable_group_workspaces")`.

Requests are strict. Reads reject a request body. Writes require a JSON object
and reject duplicate keys and unknown fields. The list accepts only `page`,
`page_size`, and `search`, each at most once; every other route accepts no query
parameters. Each of these is a 400.

The list returns `{prompts, page, page_size, total_count}`.

## Workspace status

Writes are allowed only when the group is `active`, matching the classic
interface.

| Status | Read and use | Create, edit, delete |
|---|---|---|
| `active` | yes | Owner, Admin, DocumentManager |
| `upload_disabled` | yes | no |
| `locked` | yes | no |
| `inactive` | no | no |

An unrecognized status is treated as unavailable, never as active.

## Conflicting edits

Group prompts are shared, so two managers can edit the same one. Without a
check, the second save silently overwrites the first.

List and read responses include each prompt's `etag`. PATCH and DELETE must send
it back as `expected_etag` **in the JSON body**. DELETE follows the same rule as
PATCH; this matches the group document sharing routes.

| Case | Result |
|---|---|
| `expected_etag` missing | 400 |
| `expected_etag` no longer current | **409**, `error_code: "prompt_changed"`, nothing written |
| `expected_etag` sent as a query parameter | 400, never honoured |

On a 409, refresh the prompt and reapply the change rather than resending the
old version. The V2 workbench keeps the editor and its draft open so nothing
typed is lost.

## Response shape

Prompts are serialized in one place, `_project_group_prompt`. Each response
carries `group_id`, so a client can confirm the prompt belongs to the group it
asked for, and `etag` for conditional writes.

Omitted from every response: the author's `user_id`, `public_id`, `is_favorite`,
and every Cosmos internal field such as `_rid` and `_ts`.

`prompt_actions` is computed fresh on every request. It lists `edit` and
`delete` for a manager in an `active` group and is empty otherwise. A stored
copy is always stripped and recomputed, so a stale value is never served.

## Favorites

Group prompts have no favorites. A favorite is stored on the prompt document, so
in a group one member starring a prompt would change it for everyone. The new
routes reject `is_favorite` in create and update requests, and omit it from
responses. The classic group workspace never offered favorites either.

Personal prompt favorites are unchanged.

## Workspace context

The group workspace context gains `prompt_management`,
`{schema_version: 1, operations: [...]}`. Its operations are `create`, `edit`,
and `delete` for a manager in an `active` group, and empty otherwise.

It is an interface hint, never an authorization grant. Every route checks role
and status on each request.

## Testing and validation

| Suite | Coverage |
|---|---|
| `functional_tests/test_group_prompt_apis.py` | Roles, 404 vs 403, status, cross-group isolation, paging and search, conditional writes, `is_favorite` rejection, strict request validation |
| `functional_tests/test_group_prompt_legacy_policy.py` | Legacy writes refuse ordinary members while legacy reads still admit them; no server role list contains `PromptManager` |
| `functional_tests/test_group_prompt_transport.py` | No new route can match a legacy route |
| `functional_tests/test_group_prompt_action_hint_seam.py` | `prompt_actions` is computed from policy, never a constant |
| `functional_tests/test_v2_group_workspace_context.py` | The context's advertised operations, computed by the same policy the routes enforce |

At the closeout commit the prompt suites and cross-cutting guards pass **140**
cases, the workspace context suite **48**, and the group and public document
regression **584**. Route policy passes **8/8, 4/4, 2/2**, and the
broken-access-control scanner passes on all eight changed backend modules.

## Related

- [V2 Group Prompts](V2_GROUP_PROMPTS.md) — the browser surface
- [V2 Prompts Workbench](V2_PROMPTS_WORKBENCH.md) — the personal workbench it extends
