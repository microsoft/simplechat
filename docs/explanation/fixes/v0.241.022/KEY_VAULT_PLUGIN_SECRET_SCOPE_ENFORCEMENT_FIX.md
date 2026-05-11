# Key Vault Plugin Secret Scope Enforcement Fix

Fixed/Implemented in version: **0.241.011**

## Header Information

Issue description:
This fix closes a broken-access-control path where plugin-related Key Vault secret references were treated as valid based on format alone. An authenticated user could submit or retain a full secret name from another scope, and later runtime/plugin flows could resolve or delete that foreign secret through the application's Key Vault identity.

Root cause analysis:
The plugin Key Vault helpers validated only the `{scope_value}--{source}--{scope}--{name}` format and did not verify that the provided reference matched the caller's expected scope and source. The runtime plugin loader and SQL test-connection flow also dereferenced stored secret names without checking ownership context first.

Version implemented:
`config.py` was updated to `VERSION = "0.241.011"` for this fix.

## Technical Details

Files modified:
- `application/single_app/functions_keyvault.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/config.py`
- `functional_tests/test_keyvault_plugin_secret_scope_enforcement.py`

Code changes summary:
- Added explicit parsing for dynamic Key Vault secret references and a shared scope/source matcher in `functions_keyvault.py`.
- Hardened plugin save-time handling so user-supplied full secret names are preserved only when they match the expected plugin scope and source.
- Prevented poisoned existing references from surviving an edit round-trip through the `Stored_In_KeyVault` trigger path unless they still match the expected context.
- Hardened plugin delete-time cleanup so mismatched stored references are logged and skipped instead of being deleted through the app Key Vault identity.
- Added `resolve_secret_reference_for_context(...)` and reused it for scope-aware resolution.
- Hardened `resolve_key_vault_secrets_in_plugins(...)` so runtime plugin loading resolves only plugin secret-bearing fields and blanks fields whose references fail scope validation instead of dereferencing them.
- Hardened `_resolve_secret_value_for_sql_test(...)` so SQL connection tests resolve only same-scope `action-addset` secrets.

Testing approach:
- Added a focused functional regression test covering secret-reference parsing, save-time rejection of cross-scope references, runtime loader non-resolution, SQL test-route scope binding, delete-path scope checks, and the versioned fix-document target.
- Validated the touched Python modules with targeted `py_compile` runs after each implementation slice.

Impact analysis:
This change is narrow and low-risk for legitimate plugin flows because it does not change how unrelated global or infrastructure secrets are retrieved. It only tightens plugin secret preservation, resolution, and deletion to the scope already known by the surrounding action/plugin helpers.

## Validation

Test results:
- `python -m py_compile application/single_app/functions_keyvault.py application/single_app/semantic_kernel_loader.py application/single_app/route_backend_plugins.py`
- `python functional_tests/test_keyvault_plugin_secret_scope_enforcement.py`

Before/after comparison:
- Before: a well-formed full secret name from another user, group, or global scope could be stored or retained in a plugin manifest and later be resolved or deleted via the application's Key Vault identity.
- After: plugin secret references must match the expected scope and source before they are preserved, resolved, or deleted, and runtime/plugin test flows fail closed when they encounter a mismatched stored reference.

User experience improvements:
Legitimate stored plugin secrets continue to work. When a stored reference is no longer valid for the current scope, the app now asks the user to re-enter the secret instead of silently dereferencing or deleting the wrong Key Vault secret.