# SQL Plugin Key Vault Secret Storage Fix

## Fix Title
SQL plugin credentials now use Azure Key Vault secret storage when it is enabled.

## Issue Description
SQL plugin configuration stored sensitive values such as `connection_string` and `password` directly in plugin manifests because those fields did not pass through the existing plugin Key Vault helper. The helper already supported `auth.key` and dynamic `__Secret` additional fields, but SQL credentials used regular field names, so Key Vault-enabled deployments still left SQL secrets in stored plugin data.

## Root Cause Analysis
- The shared plugin Key Vault helper only recognized `auth.key` and additional field names ending in `__Secret`.
- SQL plugins used standard additional field names like `connection_string` and `password`, so those values bypassed Key Vault storage.
- Edit flows returned `Stored_In_KeyVault` placeholders to the browser, but several save and delete paths did not reliably load the stored Key Vault reference names during updates and deletes.
- The personal workspace bulk-save flow dropped plugin ids, which made rename and placeholder-preservation scenarios unreliable.

## Version Implemented
Fixed in version: **0.239.114**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/functions_keyvault.py` | Added SQL secret-field handling for plugin save/get/delete helpers and a shared plugin redaction helper |
| `application/single_app/functions_personal_actions.py` | Preserved existing Key Vault references during personal action updates and deletes |
| `application/single_app/functions_global_actions.py` | Preserved existing Key Vault references during global action updates and deletes |
| `application/single_app/functions_group_actions.py` | Passed existing group action manifests into the Key Vault helper for placeholder-preserving updates |
| `application/single_app/route_backend_plugins.py` | Preserved personal plugin ids during bulk saves, resolved stored SQL Key Vault secrets for edit-time connection tests, removed delete-then-save global edit behavior, and redacted plugin logs |
| `application/single_app/static/js/plugin_modal_stepper.js` | Fixed SQL edit population, mapped SQL service-principal auth to the shared auth schema, and sent scope/id context for edit-time SQL connection tests |
| `application/single_app/static/js/workspace/workspace_plugins.js` | Preserved plugin ids across personal workspace edits so stored Key Vault references survive rename/update flows |
| `application/single_app/semantic_kernel_plugins/plugin_health_checker.py` | Validated SQL manifests using nested `additionalFields` values as well as top-level fields |
| `functional_tests/test_sql_plugin_key_vault_secret_storage.py` | Added regression coverage for helper behavior and personal/global/group wrapper flows |
| `application/single_app/config.py` | Version bump to 0.239.114 |

## Code Changes Summary
- SQL plugin `connection_string` and `password` additional fields are now treated as secret-bearing fields by the shared plugin Key Vault helper.
- Existing stored Key Vault references are preserved during edit flows instead of being regenerated or dropped when the UI submits `Stored_In_KeyVault` placeholders.
- Personal workspace plugin edits now preserve plugin ids so updates can target the existing stored document even when the plugin name changes.
- The SQL connection test endpoint can now resolve previously stored Key Vault-backed SQL secrets during edit flows without forcing the user to re-enter them.
- Plugin logging now redacts secret-bearing values before writing plugin manifests to logs.

## Testing Approach
- Added `functional_tests/test_sql_plugin_key_vault_secret_storage.py`.
- The functional test stubs Key Vault, Cosmos, and action-helper dependencies so it can exercise:
  - Shared SQL Key Vault secret save/get/delete behavior.
  - Placeholder-preserving personal action save/delete flows.
  - Placeholder-preserving global and group action save/delete flows.

## Impact Analysis
- New and updated SQL plugins now store secret-bearing configuration in Key Vault when `enable_key_vault_secret_storage` is enabled.
- Existing plaintext SQL plugin records are not backfilled automatically; they remain unchanged until the plugin is saved again.
- Edit flows for SQL plugins no longer require re-entering an unchanged stored connection string or password just to test or save the plugin.
- Non-SQL plugin Key Vault behavior for `auth.key` and `additionalFields.*__Secret` remains intact.

## Validation
- Regression test: `functional_tests/test_sql_plugin_key_vault_secret_storage.py`
- Before: SQL plugin `connection_string` and `password` values could remain in stored plugin data even when Key Vault was enabled.
- After: those values are stored as Key Vault references, resolved at runtime and test time, preserved across edits, and cleaned up on delete.