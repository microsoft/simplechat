# Global Identity In-Use Delete Fix (v0.261.445)

## Issue

Deleting a global identity that a global action still uses was refused with
HTTP **400** and one sentence, "This workspace identity is still used by one or
more File Sync sources or actions". Nothing else came with it: no machine
readable code and no list of what used the identity.

400 is the status of a malformed request. A client could not tell this refusal
from a validation failure, and could not name the actions that were in the way.
The strict personal, group and public identity routes have always answered the
same refusal as **409** with `error_code: "identity_in_use"` and a `references`
list, and the V2 identities section reads exactly that to say what still uses
an identity. Without it, V2 could not offer administrators the same
help in the Global Identities section it gives every other scope.

Fixed in version: **0.261.445**, tracked in `application/single_app/config.py`.

## Root cause

`route_backend_workspace_identities.py` checks references in
`_assert_not_referenced` and raised a plain `ValueError`. Every identity route in
that module maps a `ValueError` to 400 with `str(error)`, so the refusal looked
like any other bad request. The references were counted for the audit log
(`log_workspace_identity_reference_block`) and then thrown away.

The module predates the strict routes. The classic editors read only `error`
from a failed response, so the sentence was all they needed, and the personal,
group and public routes here still behave that way.

## Technical details

### The change

- `_assert_not_referenced` raises `IdentityInUse`, a `ValueError` subclass that
  carries the references: `{"kind": "file_source"|"action", "id", "name"}`,
  built the way the group identity module builds them.
- Only the global delete route, `DELETE
  /api/admin/workspace-identities/global/identities/<identity_id>`, catches it
  and answers **409** with:

  ```json
  {
    "error": "This workspace identity is still used by one or more File Sync sources or actions",
    "error_code": "identity_in_use",
    "references": [{"kind": "action", "id": "ticket_search", "name": "Ticket search"}]
  }
  ```

- Every other route, including the personal, group and public classic routes and
  the generic admin target route, still maps it as a `ValueError`: 400 with the
  sentence, as before. The sentence is unchanged, so the classic editors show the
  same text.
- The check itself is unchanged. For the global scope it covers global actions
  only, because nothing references a global identity from a File Sync source by
  id; OneDrive File Sync picks its Microsoft Graph application identity by
  capability. See
  [V2 Workspace Identities](../features/V2_WORKSPACE_IDENTITIES.md#a-delete-that-something-still-uses).

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/route_backend_workspace_identities.py` | `IDENTITY_IN_USE_MESSAGE`, `IdentityInUse`, the references, and the 409 answer on the global delete route |

### Tests

- `functional_tests/test_global_identity_admin_routes.py`, through the real route
  registration, storage and sanitizer over an in-memory Cosmos stub:
  - the refused delete is 409 with the code and the two actions named, and
    nothing is removed; once the references go, the same request deletes it;
  - the personal route still answers 400 with only the sentence;
  - every global route is administrator-only;
  - record shape and masked secrets for list, create and update;
  - the V2 browser fixture gives the same statuses, bodies and keys as the real
    routes.
- Before the change the refusal test failed with `assert 400 == 409`.

## Impact

- **Affected:** callers of the global identity delete route that read the
  status. The classic Global Identities editor reads only the message, so it is
  unaffected. V2 Admin Settings reads the 409 and the references.
- **Not changed:** the personal, group and public classic routes, the strict
  routes, and what is checked before a delete.

## Validation

- Before: a global identity referenced by a global action answered 400 and a
  sentence.
- After: it answers 409, `identity_in_use` and the actions that reference it, and
  the V2 Global Identities section lists them.

## Related

- [V2 Workspace Identities](../features/V2_WORKSPACE_IDENTITIES.md)
- [Action Workspace Identity Scope Fix](ACTION_WORKSPACE_IDENTITY_SCOPE_FIX.md)
- [Workspace Identities](../features/WORKSPACE_IDENTITIES.md)
