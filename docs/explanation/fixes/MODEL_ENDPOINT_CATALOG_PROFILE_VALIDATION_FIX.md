# Model Endpoint Catalog Profile Validation Fix

Fixed in version: **0.261.140**

## Issue

Saving a model endpoint whose model carried a malformed `catalogProfileId` failed
with a server error instead of explaining the problem. This affected every
endpoint save path: the admin settings save, the personal
`/api/user/model-endpoints` routes, the legacy `/api/group/model-endpoints` save,
and the native `/api/groups/<group_id>/model-endpoints` routes.

A malformed profile ID is one that isn't a string, is longer than 160
characters, or isn't a letter or digit followed only by letters, digits, `.`,
`_`, `:` or `-`. The admin save path goes through the same
`normalize_model_endpoints` call, so it showed a server error instead of the
reviewed flash message.

## Root cause

`normalize_model_endpoints` in `functions_settings.py` rejects a malformed
profile ID with:

```python
raise ModelTokenBudgetError("invalid_model_profile", "Choose a valid catalog profile.")
```

`functions_settings.py` never imported `ModelTokenBudgetError`. It imported only
`normalize_model_budget_overrides` from `functions_model_capabilities`. So the
`raise` itself failed with `NameError`. The callers already map
`ModelTokenBudgetError` to a reviewed 400, but a `NameError` bypassed that
mapping and reached the client as a 500.

## Technical details

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_settings.py` | Import `ModelTokenBudgetError` beside `normalize_model_budget_overrides`. |
| `functional_tests/test_model_endpoint_catalog_profile_validation_fix.py` | New regression test. |

The import comes from a module `functions_settings.py` already imports, so it
adds no new import-order dependency.

### Behaviour after the fix

A malformed profile ID now returns the existing token-budget shape on each path,
and nothing is written:

```json
{"error": "Choose a valid catalog profile.", "error_code": "invalid_model_profile"}
```

## Validation

`functional_tests/test_model_endpoint_catalog_profile_validation_fix.py` runs
the real settings, Key Vault, group, and route modules through the shared group
endpoint harness. It checks four things:

- `functions_settings.py` binds the error it raises. This is a static check.
- The native group create returns the 400 and writes nothing.
- The personal create returns the 400 and writes nothing.
- The legacy group save returns the 400 and writes nothing.

All four tests fail without the import and pass with it.

| Path | Before | After |
| --- | --- | --- |
| Native group create | 500, "Unable to complete the model endpoint request." | 400, `invalid_model_profile` |
| Personal create | `NameError` (500) | 400, `invalid_model_profile` |
| Legacy group save | `NameError` (500) | 400, `invalid_model_profile` |
