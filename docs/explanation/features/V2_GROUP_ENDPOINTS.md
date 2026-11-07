# V2 Group Endpoints

## Overview

Implemented in version: **0.261.145**, tracked in
`application/single_app/config.py`.

A group can own model connections that its agents and workflows use instead of
the connections an administrator shares with everyone. The native V2 group
workspace now lists and edits them in its **Endpoints** section. Before this
release, the section was marked Classic.

The section talks only to the group's immutable-target routes, described in
[Group Model Endpoint APIs](GROUP_MODEL_ENDPOINT_APIS.md). Every request names
the group in its path, so a group changed in another tab can't redirect a save.

This release also turns on Foundry discovery for group-scoped connections in the
group agent editor.

## Who can do what

| | Owner, Admin | DocumentManager, ordinary member |
|---|---|---|
| See the Endpoints section, list connections, open one | yes | yes |
| Add, edit, enable or disable, delete | yes, in an `active` group | no |
| Discover models, test chat | yes, in an `active` group | no |

These are the server's rules. The section is offered when the group endpoint
surface is available, which needs all four of `enable_semantic_kernel`,
`per_user_semantic_kernel`, `allow_group_custom_endpoints` and
`enable_multi_model_endpoints`, and the caller's `governance_group_endpoints`
access. Members can read connections in `active`, `locked` and
`upload_disabled` groups. Changes need an `active` group.

## How the section is built

The section reuses the admin **ModelConnectionsManager** through a scope-aware
adapter, rather than a copy of it. The administrator's page uses the same
component with an admin adapter, and its behaviour is unchanged.

In group scope the adapter:

- lists, creates, edits and deletes through
  `/api/groups/<group_id>/model-endpoints[/<endpoint_id>]`;
- discovers models through `POST /api/groups/<group_id>/models/fetch`, and tests
  chat through `POST /api/groups/<group_id>/models/test-model`;
- hides the administrator-only parts of the page: the tenant connection test,
  the image and embedding capability tests, the custom network policy, the
  default-model notices, and the migration notices.

The catalog profile picker stays, because it reads only public profile metadata
from `GET /api/models/catalog`, which any signed-in user may call.

### Offering only what the server allows

- **Add** is shown only when the workspace context's `endpoint_management` hint
  includes `create`.
- **Edit, enable or disable, and delete** are shown for a connection only when
  the hint offers the operation **and** the connection's own `endpoint_actions`
  include it.
- **Discover models** and **Test chat** follow the `test` operation in the same
  way.

A missing or malformed hint hides the operation; there is no fallback. A member
sees a read-only list. Opening a connection shows it in a read-only form with the
note "You can view this connection. Only group Owners and Admins can change it
while the group is active."

A list or row the section can't trust is a load error, not an empty list.
That covers a response with no `endpoints` array, and a row without an `id`, a
`revision`, or an `endpoint_actions` array.

### Saving

- An edit sends that one connection with `expected_revision`, never the whole
  collection. A stored key or secret is never sent back to the browser. Leaving
  it untouched keeps it, and entering a new value replaces it.
- **Enable or disable** sends just `{enabled, expected_revision}`.
- A delete sends `{expected_revision}` and asks for confirmation first. Deleting
  also removes the connection's stored key or secret.

When a save is refused:

- **Changed elsewhere** (`endpoint_conflict`): the editor keeps your changes and
  offers **Reload latest**. From version **0.261.152**, it merges the stored
  connection into your draft: the other person's changes fill the fields you
  didn't touch, your edits stay, and a field you both changed is named. Review,
  then save again. If the connection was deleted meanwhile, the editor says so
  and saves nothing.
- **The group changed during the save** (`group_write_conflict`): the editor
  keeps your changes, and you can save again as they are.
- **Still in use** (`endpoint_in_use`): a delete is refused while a group agent
  or workflow uses the connection. A dialog names each one, so you can move it
  to another connection, or disable this one instead.
- **Invalid details:** the server's reviewed message is shown as returned, with
  the draft kept.

## Foundry discovery in the group agent editor

For a Foundry agent on a **group-scoped** connection, **Discover agents**,
**Discover applications** or **Discover workflows** now calls
`POST /api/groups/<group_id>/models/foundry/agents` with the connection's ID. The
server resolves the group from the path, not from the account's active group.
A **global** connection keeps the existing `POST /api/models/foundry/agents`
route. Personal agents are unchanged.

Discovery needs an Owner or Admin in an active group. A member's agent editor is
read-only, so the button is disabled for them.

## Known limitations

- **Reload latest kept your whole draft until 0.261.152.** Saving after a
  conflict re-sent every field, which could undo the other person's changes. It
  now merges instead; see the
  [conflict rebase fix](../fixes/GROUP_EDITOR_CONFLICT_REBASE_FIX.md).
- **No tenant connection test in group scope.** The server offers no group
  connection test, so the section doesn't show one. Discover models and Test chat
  exercise the connection instead.

## Testing and validation

`ui_tests/test_v2_group_endpoints.py` (26 cases) drives the production V2 build
against a closed fixture, `ui_tests/fixtures/group_endpoints.py` on the shared
group harness. The fixture serves only the group routes, and it treats any
request for a tenant-admin `/api/v2/admin/*` route or a personal route as
unexpected. It covers:

- the layout in both themes at desktop and mobile sizes;
- reads going only to the group's routes, and a malformed list failing loudly;
- the administrator-only parts being absent;
- per-connection gating from `endpoint_actions`, beside an editable control;
- create, a conditional edit that keeps the stored key, the enable toggle's
  partial write, and delete with `expected_revision` alone;
- both conflicts keeping the draft, with and without the reload offer;
- the in-use refusal naming its references, and a reviewed message shown as
  returned;
- discovery and Test chat through the group routes, for a new draft too;
- read-only views with no write, discovery or test affordance, for a member, for
  a DocumentManager, and for a manager in a locked group.

The fixture enforces the server's rules: Owner and Admin writes,
`endpoint_actions` computed from the policy, discovery refused to non-writers,
stored-secret references and placeholders refused, and the server's exact
messages.

`functional_tests/test_group_endpoint_fixture_parity.py` (12 cases) runs the
same requests against the real Flask routes and the fixture, and compares the
response shape of every route: list, read, create, update, delete, both
conflicts, the in-use refusal, a reviewed 400, discovery, the model test and
Foundry discovery.

`ui_tests/test_v2_group_agents.py` (29 cases) now checks that a group-scoped
Foundry connection discovers through the named-group route.

## Related

- [Group Model Endpoint APIs](GROUP_MODEL_ENDPOINT_APIS.md)
- [V2 Group Agents](V2_GROUP_AGENTS.md)
- [V2 Group Identities](V2_GROUP_IDENTITIES.md)
