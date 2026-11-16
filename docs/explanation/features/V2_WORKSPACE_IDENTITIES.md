# V2 Workspace Identities

## Overview

Fixed/Implemented in version: **0.261.315**, recorded in
`application/single_app/config.py`. Refs [#1722, row 5](https://github.com/microsoft/simplechat/issues/1722).

Personal users can create and edit reusable identities without leaving V2.
Group and public managers retain their existing native authoring workflows.
An identity stores credentials for an external system, not the user's own
SimpleChat account. File sources and actions reference it instead of each
storing another copy of its secret.

Dependencies are the existing React workspace shell, authenticated Flask
identity APIs, scope-specific Cosmos DB containers, and Key Vault when
Key Vault secret storage is enabled. No migration or new setting is required.

## Scope and permissions

| Scope | Authoring access | Uses |
| --- | --- | --- |
| Personal | Signed-in users with the User role and an enabled personal Identities section | File Sync and Actions |
| Group | Owner, Admin or DocumentManager; writes require an active group | File Sync and Actions |
| Public | Owner, Admin or DocumentManager; writes require an active workspace | File Sync only |

Personal availability follows the existing workspace rules: the personal
workspace must be enabled and either File Sync must be available to the user
or Semantic Kernel must be enabled. Group/public operation hints and
per-identity actions still govern which controls are offered. Every write
rechecks access on the server.

## Native API contract

The additive personal routes never replace or fall back to the classic API:

| Operation | Route | Result |
| --- | --- | --- |
| List | `GET /api/user/identities` | Sanitized `identities` array |
| Read | `GET /api/user/identities/<identity_id>` | Sanitized `identity` |
| Create | `POST /api/user/identities` | 201 with the saved `identity` and ETag |
| Edit | `PATCH /api/user/identities/<identity_id>` | Conditional update; body requires `expected_etag` |
| Delete | `DELETE /api/user/identities/<identity_id>` | Conditional deletion; body contains only `expected_etag` |

Ownership comes from authentication, never a supplied user ID or active shared
workspace. Unknown fields, duplicate JSON keys, malformed bodies and query
parameters are rejected. Reads reject request bodies. Responses use
`Cache-Control: no-store`; credential projections contain masked values and
stored-secret flags, not raw authentication or Key Vault references.

Group/public retain `/api/groups/<group_id>/identities` and
`/api/public-workspaces/<workspace_id>/identities`. Existing classic personal
APIs keep their original contract and use the same personal container.
Compatible connector read APIs can therefore see a newly created identity
without being a classic-page hand-off.

## Create and reuse an identity

Open the workspace's **Identities** section and choose **New identity**. Give
it a recognizable name and choose the intended **Used for** capabilities.
The editor offers only authentication methods supported by that selection:
API key, bearer token, client secret, connection string, username/password,
managed identity, or anonymous where applicable.

Supply the method's credential fields and choose **Create identity**. The
saved row can then be selected in an eligible action or file-source editor
in that same scope. Creation does not test an external connection; test it
from the connector that will use it. Public identities cannot feed actions.

Use the row's **Edit** action to change details or replace credentials.
Stored secrets open blank. A blank secret preserves the stored value;
typing a replacement rotates it. Existing tenant and user-assigned managed
identity identifiers survive edits even when the form does not expose them.
Changing authentication method is distinct from clearing a stored secret.

## Concurrent edits and failures

An edit uses the ETag captured when the dialog opened, even if the collection
is refreshed separately. Missing tokens are rejected with 400; stale tokens
return 409. **Refresh** after a conflict rebases untouched fields onto the
current record while retaining user edits and any newly typed secret.
Conflicting non-secret fields are named for review.

If another writer deleted the identity, the draft remains available to copy,
but saving is disabled: the missing record is not recreated. Validation and
save failures retain the draft. Saving disables form changes and dismissal,
preventing duplicate submissions. A failed list refresh after a committed
save is shown as a read failure, not a failed creation.

Deleting an identity still referenced by a File Sync source, action or action
proxy credential returns 409 and names the references. Rebind or remove those
references before deleting it.

## Implementation and validation

`functions_personal_identity_access.py` and
`route_backend_personal_identities_scoped.py` reuse the existing conditional
storage and staged-secret helpers. `identityWorkbench.ts` supplies scoped
transport; `IdentityWorkbenchSection.tsx` and `IdentityEditorDialog.tsx`
provide shared authoring behind thin personal/group/public bindings.

| Coverage | Tests |
| --- | --- |
| Real personal routes, ownership, availability, ETags, races and secret storage | `functional_tests/test_personal_identity_apis.py` |
| Browser fixture envelopes, items, credentials, status and error-code parity | `functional_tests/test_personal_identity_fixture_parity.py` |
| Unsupported native URLs cannot execute classic operations | `functional_tests/test_personal_identity_transport.py` |
| Native creation/editing, conflicts, retry, discard, keyboard focus and desktop/mobile light/dark | `ui_tests/test_v2_personal_identities.py` |
| Shared permissions, capability restrictions and scoped writes | Existing group/public identity API, transport, fixture-parity and browser suites |
| Route registration and auth policy | `functional_tests/route_tests/` |

Closed browser fixtures serve the production SPA and local assets, and reject
unknown/classic page navigation. They exercise non-admin users/managers without
live Azure writes. They do not validate the separate legacy-routing or
**New UI only** admin-mode implementation.

Global/admin authoring, model-endpoint identity capabilities and inline
creation inside connector editors remain outside this change.
