# File Source Credential Round Trip Fix (v0.261.156)

## Issue

Editing a File Sync source could erase two stored credential identifiers,
although nobody changed them:
- **The service principal's tenant ID, in the V2 group editor.** Any save of a
  source that signs in with a service principal (client secret), even a rename,
  removed the stored tenant. The next sync then signed in against the
  application's own tenant, so a service principal from another tenant stopped
  working. The editor also showed **Tenant ID** empty for every saved source.
- **A managed identity's client ID, in both editors.** Editing a source that
  signs in with a user-assigned managed identity removed its client ID, so the
  next sync used the default managed identity instead. Neither editor can set
  that ID, so only sources configured through the API were affected.

Fixed in version: **0.261.156**, tracked in `application/single_app/config.py`.

## Root cause

- The source projection, `sanitize_file_sync_source`, returned the credential's
  `auth_type`, `username`, `domain` and `identity`, the stored-secret flags and
  masked secrets. It left out `tenant_id` and `managed_identity_client_id`.
- Both editors rebuild the credentials from what the projection gives them. The
  V2 editor always sends `tenant_id` for a service principal and
  `managed_identity_client_id` for a managed identity. The classic editor sends
  `client_id`, which the server reads as the managed identity's client ID.
- When saving, the server keeps a stored value only when the request leaves the
  key out. A value that is present but empty clears it, which is how a user
  removes one. So a blank the projection had caused was saved as a deliberate
  clear.

The classic editor was safe for the tenant only because it has no tenant field
and never sends the key.

## Technical details

### The change

- `sanitize_file_sync_source` now returns `tenant_id` and
  `managed_identity_client_id` in `credentials`. Both are identifiers, not
  secrets; every password and secret is still masked. Both were already part of
  the source's `config_revision`.
- The V2 editor reads the client ID from `identity`, or from
  `managed_identity_client_id` for a managed identity, as the classic editor
  does. It now shows the stored tenant and sends it back unchanged.
- Clearing a value works as before: sending it empty still removes it.
- A source bound to a workspace identity shows that identity's identifiers, as
  it already showed the identity's client ID.

### Files modified

- `functions_file_sync.py`: `sanitize_file_sync_source`.
- `application/v2_ui/src/lib/fileSourceFields.ts`: `draftFromSource`.
- `ui_tests/fixtures/group_workspace.py`: the group file source fixture now
  stores and returns both identifiers the way the server does. It had returned
  an empty tenant and filed the managed identity's client ID under `identity`,
  which kept the browser tests from seeing the loss.

### Tests

- `functional_tests/test_file_source_credential_round_trip_fix.py`
  (7 cases), through the real group file source routes. It covers:
  - the projection carries both identifiers, with every secret masked;
  - a V2 rename keeps the tenant and the managed identity's client ID;
  - the classic editor's save keeps the client ID;
  - a cleared tenant is still cleared;
  - an identity-bound source shows the identity's identifiers.

  Every round-trip case fails on the unfixed code.
- `functional_tests/test_group_file_source_fixture_parity.py` now compares the
  `credentials` block too. On the unfixed server it fails with
  `['managed_identity_client_id', 'tenant_id']`.
- `ui_tests/test_v2_group_file_sources.py` adds two browser tests: renaming a
  service principal source shows and sends back its tenant, and renaming a
  managed identity source sends back its client ID.

## Impact

- **Affected:**
  - group file sources edited in V2 from version 0.261.147, with service
    principal credentials and a stored tenant;
  - any source whose managed identity client ID was set through the API, and
    later edited in either editor.
- **Repair:** open the source, enter the tenant ID again, and save.
- **Related, fixed later:** workspace identities showed neither identifier
  either (`sanitize_workspace_identity`), and both identity editors sent the
  client ID empty for a managed identity. Fixed in version 0.261.170; see the
  [Identity Credential Round Trip Fix](IDENTITY_CREDENTIAL_ROUND_TRIP_FIX.md).

## Validation

- Before: renaming a service principal source in V2 erased its tenant, and the
  next sync signed in to the wrong tenant.
- After: an edit keeps both identifiers unless the user changes them.

## Related

- [Group File Source APIs](../features/GROUP_FILE_SOURCE_APIS.md)
- [V2 Group File Sources](../features/V2_GROUP_FILE_SOURCES.md)
