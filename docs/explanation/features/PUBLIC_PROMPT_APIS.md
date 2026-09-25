# Public Prompt APIs (v0.261.177)

## Overview

Routes for public workspace prompts that name the workspace in the path,
together with a status check on the classic public prompt writes.

Implemented in version: **0.261.177**, tracked in
`application/single_app/config.py`.

Dependencies are the existing public prompts storage and
`enable_public_workspaces`. No new setting, container or index is required.

## Why new routes

The classic `/api/public_prompts` routes act on the user's stored active public
workspace. A stale selection, from another tab or a recent switch, would send a
change to a different workspace from the one on screen. The new routes name the
workspace in the path, so they can only act on the workspace the request names.
The classic routes keep their paths and active-workspace targeting, because the
classic public workspace page still uses them.

## Who may change public prompts

Every signed-in user can read a public workspace's prompts and use them in
chat. Only **Owner**, **Admin** and **DocumentManager** may create, edit or
delete them, on the new routes as on the classic ones.

## Immutable API family

All paths start `/api/public-workspaces/W/prompts`, where `W` is the only
target.

| Method and path | Purpose |
|---|---|
| `GET /api/public-workspaces/W/prompts` | List the workspace's prompts |
| `GET /api/public-workspaces/W/prompts/P` | Read one prompt |
| `POST /api/public-workspaces/W/prompts` | Create a prompt |
| `PATCH /api/public-workspaces/W/prompts/P` | Update a prompt |
| `DELETE /api/public-workspaces/W/prompts/P` | Delete a prompt |

Every route carries `@swagger_route(security=get_auth_security())`, login and
user checks, and `@enabled_required("enable_public_workspaces")`. Requests are
strict: unknown fields and `is_favorite` are refused with 400. The list returns
`{prompts, page, page_size, total_count}`.

## Workspace status

| Status | Read and use | Create, edit, delete |
|---|---|---|
| `active` | yes | Owner, Admin, DocumentManager |
| `upload_disabled` | yes | no |
| `locked` | yes | no |
| `inactive` | no | no |

An unrecognized status is treated as unavailable, never as active. The rules
live in `functions_public_prompt_policy.py`, with their own status list.

### Classic public prompt writes (a behaviour change)

From this release, the classic `/api/public_prompts` create, update and delete
routes also require an `active` workspace. Before, they wrote in any status.
A write in another status is refused with 403, "This public workspace is not
accepting prompt changes right now." The classic reads are unchanged. This is
decision 19's default. The group's classic prompt routes check no status, so
this is a difference between the two.

## Conflicting edits

List and read responses include each prompt's `etag`. PATCH and DELETE must send
it back as `expected_etag` in the JSON body.

| Case | Result |
|---|---|
| `expected_etag` missing | 400 |
| `expected_etag` no longer current | **409**, `error_code: "prompt_changed"`, nothing written |

On a 409 the V2 workbench keeps the editor and its draft open, and a reload
merges the other person's changes into the fields you didn't touch.

## Response shape

Each response carries `public_id`, the workspace the prompt belongs to, so a
client can confirm it asked for this workspace, and `etag`. Omitted from every
response: the author's `user_id`, `group_id`, `is_favorite`, and every Cosmos
internal field. `prompt_actions` (`edit` and `delete`) is computed fresh on
every request, for a manager in an `active` workspace; a stored copy is never
served.

Public prompts have no favorites. A favorite is stored on the prompt itself,
so one reader starring a shared prompt would change it for everyone.

## Workspace context

The public workspace context gains `prompt_management`,
`{schema_version: 1, operations: [...]}`, with `create`, `edit` and `delete` for
a manager in an `active` workspace, and none otherwise. The `prompts` section is
now available, and managed by an active manager. The hint is never an
authorization grant; every route checks role and status on each request.

## Testing and validation

| Suite | Coverage |
|---|---|
| `functional_tests/test_public_prompt_policy_logic.py` | The status allowlist and the operations per role and status |
| `functional_tests/test_public_prompt_scoped_apis.py` | Roles, status, strict requests, conditional writes, `is_favorite` refused, the projection |
| `functional_tests/test_public_prompt_transport.py` | No new route can match a classic one |
| `functional_tests/test_public_prompt_legacy_status_gate.py` | The classic writes' status check |
| `functional_tests/test_public_prompt_fixture_parity.py` | The browser fixture held to the routes |
| `functional_tests/test_public_context_fixture_parity.py` | `prompt_management` and the `prompts` section |

## Related

- [V2 Public Prompts](V2_PUBLIC_PROMPTS.md): the browser surface
- [Group Prompt APIs](GROUP_PROMPT_APIS.md): the group equivalent
