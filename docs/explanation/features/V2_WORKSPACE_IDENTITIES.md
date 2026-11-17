# V2 Workspace Identities

## Overview

Fixed/Implemented in version: **0.261.315**, recorded in
`application/single_app/config.py`. Refs [#1722, row 5](https://github.com/microsoft/simplechat/issues/1722).
The administrator's **global** identities in Admin Settings use the same editor since
**0.261.445**; see [Global identities in Admin Settings](#global-identities-in-admin-settings).

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
| Global | Administrators, in Admin Settings > Security > Global Identities | File Sync and Actions |

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

## Global identities in Admin Settings

**Implemented in version: 0.261.445.**

Global identities are the deployment's own saved credentials. File Sync and
Actions reuse them by name, so the secret itself never travels with a
configuration, and each one keeps its secret in Key Vault when Key Vault is
configured. They are not accounts for signing in to SimpleChat.

Administrators open **Admin Settings > Security > Global Identities** and use
**New identity**, **Edit** and **Delete** on a row. Until 0.261.445 the V2
section was a read-only list that sent the administrator to the classic admin
page for all three, so a deployment could not run on V2 alone.

The editor, list, search, conflict handling and refusal to delete an identity
that is in use are the shared identities workbench (`IdentityWorkbenchSection`
with `IdentityEditorDialog`). `GlobalIdentitiesList.tsx` binds it to the global
adapter, `createGlobalIdentityWorkbench` in `identityWorkbench.ts`, and shows
the card's own help text beside **New identity**. Each change saves on its own,
as the global agents and actions do, so none of it goes through the settings
save bar.

### What the editor offers

The editor offers what the classic Global Identities pane offers, no more and
no less.

| | Global editor |
| --- | --- |
| Used for | File Sync and Actions. A new identity starts on Actions. |
| Authentication methods | Username and password, API key, bearer token, client secret, connection string and managed identity. **Anonymous is not offered**, as in the classic pane. An identity used only for File Sync is offered username and password, managed identity, client secret and connection string. |
| Fields | Name and description, then per method: username and domain, a client ID, or a secret or password |
| Secrets | Held on the server and never sent to the browser. A blank secret on an edit keeps the stored value. |
| Write | The body the classic editor sends: `name`, `description`, `provider`, `source_type`, `usage_contexts`, `supported_source_types` and `credentials` |

### Routes

| Operation | Route | Result |
| --- | --- | --- |
| List | `GET /api/admin/workspace-identities/global/identities` | `{"identities": [...]}` |
| Create | `POST` the same route | 201 and `{"identity": ...}` |
| Edit | `PATCH /api/admin/workspace-identities/global/identities/<identity_id>` | 200 and `{"identity": ...}` |
| Delete | `DELETE` the same route | 200 |

Every route requires a signed-in administrator (`login_required` and
`admin_required`). The administrator-only Admin Settings page is therefore the
client-side gate and the server's check is the authority: a non-administrator
receives 403 from every route. These are the older identity routes rather than
the strict `/api/user/identities` family, and a stored record differs from a
workspace's in two ways the adapter absorbs.

- **No version marker.** A record carries no `etag` and no `identity_actions`.
  V2 therefore offers Edit and Delete on every identity of the global scope, and
  an edit is last-write-wins, exactly as it is in the classic editor. The
  adapter still honours what a record does carry: it follows `identity_actions`
  when present, sends `expected_etag` when a record has an `etag`, and reads a
  409 or 412 as a conflict. The editor and the draft stay open and **Refresh**
  rebases onto the other writer's version. A server that starts versioning these
  records needs no client change.
- **Plain refusals.** A validation message comes from the server and is shown as
  written with the draft kept. A 404 on a save marks the draft as deleted
  elsewhere and disables saving, so the record is not recreated. A 403 is shown as
  it came and is not mistaken for a conflict.

### A delete that something still uses

A global action can reference a global identity by id. Deleting an identity that
a global action still references is refused with **409** and
`error_code: "identity_in_use"`, naming each action as
`{"kind": "action", "id": ..., "name": ...}`. Nothing is removed, and the
section lists the actions under "“Name” is still in use, so it was not deleted".

Until 0.261.445 this refusal answered **400** with only a sentence, which is the
status of a malformed request, so a client could neither recognise it nor name
what used the identity. See
[Global identity in-use delete fix](../fixes/GLOBAL_IDENTITY_IN_USE_DELETE_FIX.md).
The classic editor shows the same sentence as before, and the personal, group
and public classic routes still answer 400 as they always did.

Only global actions are checked. OneDrive File Sync chooses its Microsoft Graph
application credentials by capability: the first global File Sync identity with
a client secret that supports the source type, and the application's own client
credentials when there is none. Nothing stores a reference to that identity, so
the server has nothing to check when it is deleted. Confirm that no OneDrive
source relies on a global identity before deleting it.

### Testing and validation

| Coverage | Tests |
| --- | --- |
| URLs, bodies, etag handling, in-use and conflict reading, scope validation, the gates, and that personal, group and public did not change | `functional_tests/test_v2_global_identities_logic.ts`, run by `functional_tests/test_v2_global_identities.py` |
| The adapter names the four routes the server declares, each administrator-only; the editor offers the classic pane's capabilities and methods; the section composes the workbench | `functional_tests/test_v2_global_identities.py` |
| The real routes: record shape, secrets, the 409 refusal, the personal refusal unchanged, administrator-only; the browser fixture gives the same statuses and keys | `functional_tests/test_global_identity_admin_routes.py` |
| List, create for both uses and several methods, a validation message, an edit that keeps its secret, a conflict and Refresh, a save for an identity deleted elsewhere, delete, a delete refused with the actions named, 403 on read, write and delete, and the keyboard, at 1440px and 390px | `ui_tests/test_v2_admin_global_identities.py` |

### Known limitations

- Edits to a global identity are last-write-wins, because the routes have no
  version marker.
- A delete is checked against global actions only, as described above.
- An identity saved through the API with the anonymous method opens in the editor
  with the first method the classic pane offers selected, as it does in classic,
  and saving it then needs that method's credentials.
- Model-endpoint identity capabilities are not part of the global editor, as in
  the classic pane.

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

Model-endpoint identity capabilities and inline creation inside connector
editors remain outside this change.
