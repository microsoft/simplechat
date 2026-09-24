# Group Model Endpoint APIs (v0.261.140)

## Overview

These are immutable-target routes for a group's own model endpoints, which its
agents and workflows use instead of the deployment's shared models. They let a
client manage one endpoint at a time for a named group, run model discovery
and tests against it, and discover Foundry agents, all without touching the
account's active group.

Implemented in version: **0.261.140**, tracked in
`application/single_app/config.py`.

The endpoints stay where they always were: in `model_endpoints` on the group
document. No new setting, container or index is required. From version
**0.261.145**, the native V2 group workspace edits group endpoints through these
routes; see [V2 Group Endpoints](V2_GROUP_ENDPOINTS.md).

## Why new routes

The legacy routes act on the account's **active** group (`require_active_group`):

- `GET` and `POST /api/group/model-endpoints`;
- `POST /api/group/models/fetch`;
- `POST /api/group/models/test-model`;
- Foundry discovery.

The legacy save also replaces the **whole collection**, upserting the group
document unconditionally. That document holds membership and status too, so a
save that raced a membership change could undo it, and a save could recreate a
deleted group. The legacy save also returns raw exception text on validation
errors.

The new routes differ in four ways:

- they name the group in the path and never read the active group;
- they change one endpoint at a time;
- they write the group document conditionally;
- they return stable messages.

The legacy routes are unchanged, apart from the security hardening described in
[the application identity fix](../fixes/MODEL_ENDPOINT_APPLICATION_IDENTITY_FIX.md)
and [the secret reference fix](../fixes/MODEL_ENDPOINT_SECRET_REFERENCE_SCOPE_FIX.md).

## Availability and roles

- **Availability:** the tenant enables `enable_semantic_kernel`,
  `per_user_semantic_kernel`, `allow_group_custom_endpoints` and
  `enable_multi_model_endpoints`, and the caller passes the
  `governance_group_endpoints` policy. One predicate,
  `group_endpoints_available` in `functions_group_endpoint_policy.py`, decides
  this for the workspace context's Endpoints section and every route.
  Otherwise every route returns 403 with "Group model endpoints are not
  enabled." or the governance reason.
- **Reads:** every group role (Owner, Admin, DocumentManager and User) in
  `active`, `locked` and `upload_disabled` groups.
- **Writes, discovery, model tests and Foundry discovery:** Owner and Admin, in
  `active` groups only. Discovery and tests load the endpoint's stored
  credentials, so they need the write roles, as they always have.
  `require_owner_for_group_agent_management` narrows agent and action
  management, but has never applied to endpoints.
- `inactive` or an unrecognized status is 403.

The context publishes the group's operations as `endpoint_management`:
`{"schema_version": 1, "operations": [...]}`, a subset of `create`, `edit`,
`delete`, `enable` and `test`.

## Routes

| Method and path | Purpose | Success |
|---|---|---|
| `GET /api/groups/G/model-endpoints` | List | `{"endpoints": [...], "multi_endpoint_enabled": ..., "custom_api_types": [...]}` |
| `POST /api/groups/G/model-endpoints` | Create one | 201 `{"endpoint": ...}` |
| `GET /api/groups/G/model-endpoints/E` | Read one | `{"endpoint": ...}` |
| `PATCH /api/groups/G/model-endpoints/E` | Update one, merged on the server | `{"endpoint": ...}` |
| `DELETE /api/groups/G/model-endpoints/E` | Delete one | `{"success": true}` |
| `POST /api/groups/G/models/fetch` | Model discovery | As the legacy fetch |
| `POST /api/groups/G/models/test-model` | Model test | As the legacy test-model |
| `POST /api/groups/G/models/foundry/agents` | Foundry agent and workflow discovery for a group endpoint | As the legacy Foundry discovery |

Every route carries `@swagger_route(security=get_auth_security())`,
`@login_required`, `@user_required` and
`@enabled_required("enable_group_workspaces")`.

- No route accepts a query parameter.
- `GET` takes no body. The `DELETE` body is described below.
- `POST` and `PATCH` take a JSON object with no duplicate keys.

The five endpoint routes are in `route_backend_group_endpoints_scoped.py`. The
three `models` routes are registered in `route_backend_models.py`, beside the
closures they share with the legacy routes.

## The endpoint shape

Each endpoint uses the admin shape that `sanitize_model_endpoints_for_frontend`
produces, so stored credentials are never returned. It adds two fields computed
for each request:

- `revision`: SHA-256 over the canonical JSON of the stored endpoint, with the
  credential fields `api_key`, `client_secret`, `bearer_token`, `access_token`
  and `refresh_token` removed.
  - It never covers a secret, even when Key Vault is off and secrets are stored
    inline.
  - It doesn't change when catalogue settings change.
- `endpoint_actions`: the subset of `edit`, `delete`, `enable` and `test` the
  caller may perform.

The list returns only the providers the endpoint editor offers
(`is_frontend_visible_model_endpoint_provider`). An endpoint with any other
provider isn't listed or addressable (404), switching an endpoint to one is 400,
and every write preserves such endpoints. The admin-only list keys (`migration`,
`embedding_migration`, `default_notices` and `custom_network_policy`) are left
out.

## Writes

### How a write lands on the group document

A write applies exactly one endpoint change to the copy it has just read. It
then re-normalizes and re-validates the whole collection, as the legacy save
does, and replaces the group document conditionally through
`update_group_document_with_etag_guard` in `functions_group.py`:

- `IfNotModified` on the document's `_etag`;
- on a 412, it re-reads and re-applies, up to three attempts. A membership or
  status change that landed in between is kept;
- after the last attempt, it returns 409:

  ```json
  {"error": "The group changed while this model endpoint was being saved. Try again.",
   "error_code": "group_write_conflict"}
  ```

- a group deleted mid-write is 404, and is never recreated;
- a commit whose response was lost is detected, because the re-read matches the
  body that was sent, and it is reported as committed.

The writer's role and status are checked again against the exact document
version being replaced, so a demotion that lands mid-write refuses the write.
Each committed write bumps the chat bootstrap cache once
(`group_model_endpoints_updated`).

`update_group_model_endpoints` stays the unconditional upsert for the legacy
callers. From 0.261.151 the group membership writers are conditional too; the
remaining whole-document writers are listed in the
[membership write safety fix](../fixes/GROUP_MEMBERSHIP_WRITE_SAFETY_FIX.md).

### Create and update

- **Create** takes the endpoint object. `id` is optional: the server allocates a
  UUID. An existing ID is 409. A client ID follows the path-identifier rules and
  is at most 64 characters, which leaves room for a staged Key Vault name.
  `expected_revision` isn't used on create.
- **Update** carries a top-level `expected_revision` beside the endpoint fields.
  A missing revision, or no change, is 400. The fields are merged into the
  stored endpoint on the server. A blank value keeps the stored value, as in the
  admin and personal APIs. To clear a field, replace it with another value. To
  clear a credential, switch the authentication type, which drops the
  credentials the new type doesn't use.
- **Conflicts:** a stale revision is 409, and nothing is written:

  ```json
  {"error": "This model endpoint changed. Reload it before saving.",
   "error_code": "endpoint_conflict"}
  ```

  A change by another writer that touches only a secret doesn't change the
  revision. That is acceptable, because a PATCH replaces only a credential the
  client supplies.

### Credentials

- A client can never supply a Key Vault reference. Reference names are keyed by
  endpoint ID alone, so accepting one would let an endpoint borrow the credential
  of another group's endpoint that has the same ID. The refusal is a 400:
  "Stored credential references cannot be supplied in a request." The masked
  placeholder is also refused where no secret is stored.
- A new secret is stored under a **fresh** name,
  `{endpoint_id}--model-endpoint--group--s-<hex>`, before the conditional write.
  A write that loses its race therefore never overwrites a credential another
  writer committed.
- Replaced and removed credentials are deleted only after the write commits.
- Staged credentials of a write that ends without committing are deleted. That
  covers a conflict, a missing group and a refused change. The one exception is a
  credential the stored document still references, which is never deleted.
- After an uncertain failure, such as a transport error on the replace, staged
  credentials are kept and logged, rather than risk deleting one a committed
  write uses.
- Credentials an endpoint already has under the older deterministic name,
  `{endpoint_id}--model-endpoint--group--model-endpoint-<field>`, keep working
  until the secret is re-entered.

### Delete

The body is exactly `{"expected_revision": "..."}`. A stale revision is the same
409 `endpoint_conflict`.

Before deleting, the server scans the group's agents and workflows. It looks at:

- an agent's `model_endpoint_id`;
- a Foundry agent's `other_settings.<section>.endpoint_id`, for the section its
  agent type reads;
- a workflow's top-level `model_endpoint_id`, and each task runner's
  `model_endpoint_id`.

If anything refers to the endpoint, nothing is deleted:

```json
{"error": "This model endpoint is used by group agents or workflows. Change them to another endpoint, or disable this endpoint instead.",
 "error_code": "endpoint_in_use",
 "references": [{"kind": "agent" | "workflow", "id": "...", "name": "..."}]}
```

The scan runs inside the conditional write, so it runs again whenever the write
is retried.

A setting the runtime would not read isn't counted as a reference. If the scan
itself fails, the delete is refused with 503 "Unable to confirm this model
endpoint is unused. Try again." Disabling an endpoint (`enabled: false`) is
always allowed.

### Errors and logging

| Case | Response |
|---|---|
| Endpoint validation | 400 `{"error": <public message>, "code": "invalid_custom_endpoint"}`, the admin shape |
| Token budget or catalog profile | 400 `{"error": <public message>, "error_code": <code>}`, the legacy shape |
| Connection configuration | 400 `{"error": <public message>, "code": <code>}` |
| Anything unexpected | A stable 500, "Unable to complete the model endpoint request." |

Committed writes log one tagged `[MODELS]` diagnostic for create, update or
delete, with `group_id`, `endpoint_id` and `user_id`. They write no activity
event, which matches the legacy group save and the personal and admin per-item
APIs. Refused writes log no change.

## Discovery and tests use the named group

The five discovery closures in `route_backend_models.py` take an optional
`group_id`:

- `resolve_scoped_model_endpoints`;
- `resolve_endpoint_by_id`;
- `resolve_request_endpoint_payload`;
- `handle_fetch_model_list`;
- `handle_test_model_connection`.

When `group_id` is set, it replaces `require_active_group`. The native routes
authorize the path group first and pass it. The default, `None`, keeps every
legacy caller as it was.

With an `endpoint_id`, the request is rebuilt from the stored configuration only.
So a stored key reaches only the stored destination, and a URL or secret in the
request is ignored. Without an `endpoint_id`, the request's own fields are used,
with no stored secrets. The application identity rule below applies to both.

## The application identity

An endpoint that would use the application's own credential follows one rule,
`functions_model_endpoint_app_identity.py`. That covers managed identity, a
missing authentication type, or any type other than an API key or service
principal:

- the host must be an Azure AI service host of the deployment's cloud;
- no token audience, authority or custom cloud may differ from the deployment's
  own;
- no managed identity client ID may be selected.

The rule applies to personal and group endpoints on the native and legacy
routes, at save time and at use time. See
[the application identity fix](../fixes/MODEL_ENDPOINT_APPLICATION_IDENTITY_FIX.md)
for the details.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_group_endpoint_apis.py` | 96 | The role, status and availability matrix; list and endpoint shapes; strict requests; create, update and delete; revision conflicts with nothing written; the group-document discipline, including a membership change kept, a deleted group not recreated, a lost-response commit and a mid-write demotion; credential staging, replacement, cleanup and deletion by exact Key Vault name; the in-use references; hidden providers; error shapes; audit parity; the cache bump |
| `functional_tests/test_group_endpoint_discovery_scope.py` | 46 | The native fetch, test and Foundry routes resolve only the path group, never call `require_active_group`, and use the stored configuration; legacy routes still resolve the active group; roles and status for discovery; the legacy Foundry auth-required body is byte-identical |
| `functional_tests/test_group_endpoint_policy.py` | 34 | The availability predicate, roles and statuses, and the management projection |
| `functional_tests/test_group_endpoint_hint_seam.py` | 6 | The context and the routes use the same predicate and projection |
| `functional_tests/test_group_endpoint_transport.py` | 9 | None of the new routes can fall through to a legacy route |
| `functional_tests/test_group_document_etag_guard.py` | 7 | `update_group_document_with_etag_guard` |

The harness in `functional_tests/test_support/group_endpoint_harness.py` runs
these modules unchanged, loaded from their files:

- the real settings, Key Vault, group, policy, access and route modules;
- the etag-enforcing `FakeContainer`;
- an in-memory Key Vault with storage enabled in the settings the helpers read.

The Key Vault assertions check exact names, so none of them can pass vacuously.

Integrated with the branch tip, the related functional test files show no
failure that isn't already on the tip. Route policy passes 8/8, 4/4 and 2/2,
and the broken-access-control scanner passes on every changed backend module.

## Related

- [V2 Group Endpoints](V2_GROUP_ENDPOINTS.md)
- [Model Endpoint Application Identity Fix](../fixes/MODEL_ENDPOINT_APPLICATION_IDENTITY_FIX.md)
- [Model Endpoint Secret Reference Scope Fix](../fixes/MODEL_ENDPOINT_SECRET_REFERENCE_SCOPE_FIX.md)
- [Model Endpoint Catalog Profile Validation Fix](../fixes/MODEL_ENDPOINT_CATALOG_PROFILE_VALIDATION_FIX.md)
- [Group Agent APIs](GROUP_AGENT_APIS.md)
- [Group Identity APIs](GROUP_IDENTITY_APIS.md)
