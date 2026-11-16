# Identity Credential Round Trip Fix (v0.261.170)

## Issue

Editing a workspace identity that signs in with a user-assigned managed
identity erased its client ID, although nobody changed it. The identity then
signed in as the deployment's default managed identity instead. Neither the
classic identity editor nor the V2 group editor can set that ID, so only
identities configured through the API were affected. Both editors also opened
without the stored tenant of a service principal identity, though they kept it.

This is the workspace identity twin of the
[File Source Credential Round Trip Fix](FILE_SOURCE_CREDENTIAL_ROUND_TRIP_FIX.md).

Fixed in version: **0.261.170**, tracked in `application/single_app/config.py`.

## Root cause

- The identity projection, `sanitize_workspace_identity`, returned the
  credential's `auth_type`, `username`, `domain` and `identity` (a service
  principal's client ID), the stored-secret flags and masked secrets. It left
  out `tenant_id` and `managed_identity_client_id`.
- Both editors rebuild the credentials from that projection, and send
  `client_id: ""` for every authentication type except a client secret.
- For a managed identity, the server reads `managed_identity_client_id`, then
  `client_id`, and keeps the stored value only when the request leaves both
  out. So the empty `client_id` cleared it.
- A service principal's tenant was kept only because neither editor sends
  `tenant_id`.

## Technical details

### The change

- `sanitize_workspace_identity` returns `tenant_id` and
  `managed_identity_client_id` in `credentials`. Both are identifiers, not
  secrets; every password and secret is still masked.
  - Only the identity lists and pickers read this projection:
    `route_backend_workspace_identities.py` and the group identity access
    projection.
  - Actions and agents read the stored credentials themselves, so the
    identifiers reach nothing new.
- The V2 editor (`lib/identityFields.ts`) keeps a managed identity's client ID
  in a hidden draft field. It's read from the projection, sent back as
  `managed_identity_client_id` when a managed identity is saved, and merged
  like any other field after a conflict. The server reads it before the empty
  `client_id`, so an untouched save keeps it.
- The classic editor (`static/js/workspace/workspace-identities.js`) sends back
  the stored client ID it opened with, the same way. It serves the personal,
  group and public workspace pages and the admin global identities, so all of
  them are fixed.
- No request validation changed. `credentials` is accepted as a whole, and its
  keys go to the server's normalizer.
- Saving a managed identity as another authentication type still drops its
  client ID, because the server rebuilds the credentials for the new type. That
  is expected, and now pinned.

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_workspace_identities.py` | The projection carries both identifiers |
| `application/v2_ui/src/lib/identityFields.ts` | The hidden client ID field, read and sent back, and in the rebase fields |
| `application/single_app/static/js/workspace/workspace-identities.js` | Sends back the stored client ID for a managed identity |
| `ui_tests/fixtures/group_workspace.py` | The group identity fixture stores and returns both identifiers as the server does |

### Tests

- `functional_tests/test_identity_credential_round_trip_fix.py` (6 cases),
  through the real group identity routes:
  - the projection carries both identifiers, with every secret masked;
  - a V2 rename keeps the managed identity's client ID;
  - the classic editor's save keeps it, including a check of the classic
    payload builder;
  - a V2 rename keeps a service principal's tenant;
  - a switch away from managed identity drops the client ID.
- `functional_tests/test_group_identity_fixture_parity.py` compares
  `tenant_id` and `managed_identity_client_id` in the `credentials` block.
- `ui_tests/test_v2_group_identities.py`: editing a managed identity keeps its
  client ID in the saved body.
- Mutations:
  - removing the projection fails 5 tests;
  - removing the V2 write fails the browser test;
  - removing the classic change fails the classic check.

## Impact

- **Affected:** any workspace identity whose managed identity client ID was
  set through the API, and later edited in the classic editor or the V2 group
  editor.
- **Repair:** set the client ID again through the API.
- **Not changed:** neither editor can set a managed identity client ID. An
  optional field in V2 is a follow-up.

## Validation

- Before: renaming a user-assigned managed identity cleared its client ID, and
  its next sign-in used the default managed identity.
- After: an edit keeps both identifiers unless the authentication type
  changes.

## Related

- [File Source Credential Round Trip Fix](FILE_SOURCE_CREDENTIAL_ROUND_TRIP_FIX.md)
- [V2 Group Identities](../features/V2_GROUP_IDENTITIES.md)
- [Group Identity APIs](../features/GROUP_IDENTITY_APIS.md)
- [Workspace Identities](../features/WORKSPACE_IDENTITIES.md)
