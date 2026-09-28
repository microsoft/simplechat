# Model Endpoint Secret Reference Scope Fix

Fixed in version: **0.261.140**

## Issue

Personal and group model endpoints store their credentials in Key Vault under
names built from the endpoint ID alone:

```text
{endpoint_id}--model-endpoint--{scope}--model-endpoint-{field}
```

The name carries no group or user ID. `keyvault_model_endpoint_save_helper`
accepted any Key Vault reference a client sent back, as long as
`secret_reference_matches_context` passed. That check compares only the
endpoint ID, the scope and the source. A new plaintext value was also stored
under the deterministic name above.

So the Owner or Admin of any group who knew another group's endpoint ID could
use the legacy `POST /api/group/model-endpoints`. Any member of the other group
can see that ID. There were two ways to use it:

- **Borrow the credential.** Create an endpoint with the same ID whose
  `auth.api_key` is the other group's reference. Model discovery, the model test
  and the chat runtime would then load the other group's key and send it to the
  attacker's URL.
- **Overwrite the credential.** Create an endpoint with the same ID and a
  plaintext key. It was stored under the other group's deterministic name,
  replacing their key.

Personal endpoints (`user` scope) had the same flaw, though a user's endpoint IDs
aren't normally visible to other people.

## Root cause

The Key Vault namespace for these two scopes is keyed by endpoint ID, but endpoint
IDs are unique only within one group or one user. The save helper trusted a
reference because its name looked right, not because this endpoint had stored it.

## Technical details

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_keyvault.py` | `_refuse_foreign_model_endpoint_references` and `MODEL_ENDPOINT_ENDPOINT_KEYED_SCOPES`; the save helper always stages new values under fresh names in the `group` and `user` scopes |
| `application/single_app/route_backend_models.py` | `save_scoped_endpoint_secrets`, used by the legacy group save and every personal save path |
| `functional_tests/test_model_endpoint_secret_reference_hardening.py` | New regression test |

### What changed

In the `group` and `user` scopes only:

- A value shaped like a Key Vault reference is accepted **only if it equals the
  endpoint's own stored reference** for that field. Anything else is refused.
  The check runs even when Key Vault storage is off, so a borrowed name can't be
  stored inline and become resolvable once storage is turned on.
- A new plaintext value is always stored under a fresh name, such as
  `{endpoint_id}--model-endpoint--group--s-<hex>`, never the deterministic
  name another workspace's endpoint could hold.

The legacy group save and the personal routes (create, collection save, PATCH
and DELETE) run the Key Vault pass through `save_scoped_endpoint_secrets`. A
refused credential returns a stable 400 instead of a 500:

```json
{"error": "A model endpoint credential could not be saved. Re-enter the secret value and try again."}
```

Anything that request had already staged for an earlier endpoint is deleted
again, and nothing is written.

The native group routes (`/api/groups/<group_id>/model-endpoints`) refuse any
client-supplied reference outright. See
[Group Model Endpoint APIs](../features/GROUP_MODEL_ENDPOINT_APIS.md).

### What didn't change

- Global callers, meaning the admin settings save and migration.
- The classic round trip:
  - a blank or missing secret keeps the stored value;
  - a plaintext value replaces it;
  - sending back the endpoint's own stored reference is accepted.
- Existing credentials keep their deterministic names until the secret is
  re-entered. The next save that replaces one removes the superseded name. There
  is no migration.

## Validation

`functional_tests/test_model_endpoint_secret_reference_hardening.py`, 17 tests. It
runs the real Key Vault helper and the real legacy routes, with Key Vault storage
enabled in the settings the helpers read. It asserts every vault write, read and
delete by exact name. It covers:

- a borrowed reference refused on the legacy group save, the personal create,
  collection save and PATCH, and the native create;
- a plaintext value on a colliding ID leaves the other group's secret untouched;
- the classic round trip is unchanged;
- a refused save removes what it staged for earlier endpoints;
- the runtime resolves the fresh names;
- superseded names are cleaned up;
- global callers are unchanged.

12 of the 17 fail on the code before this fix.

| Case | Before | After |
| --- | --- | --- |
| Another group's reference in `auth.api_key` | Stored; that group's key sent to the caller's URL | 400; nothing stored |
| Plaintext key on another group's endpoint ID | That group's key overwritten | Stored under a fresh name; the other group's key is untouched |
| Re-sending the endpoint's own reference | Accepted | Accepted |
