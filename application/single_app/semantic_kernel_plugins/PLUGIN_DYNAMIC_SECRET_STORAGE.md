# PLUGIN_DYNAMIC_SECRET_STORAGE.md

## Feature: Dynamic Secret Storage for Plugins/Actions

**Implemented in version:** (add your current config.py version here)

### Overview
This feature allows plugin writers to store secrets in Azure Key Vault dynamically by simply naming any key in the plugin's `additionalFields` dictionary with the suffix `__Secret`. The application will automatically detect these keys, store their values in Key Vault, and replace the value with a Key Vault reference. This works in addition to the standard `auth.key` secret handling.


### How It Works
- When saving a plugin, any key in `additionalFields` ending with `__Secret` (two underscores and a capital S) will be stored in Key Vault.
- The Key Vault secret name for these fields is constructed as `{pluginName-additionalsettingnamewithout__Secret}` (e.g., `loganal-alpharoemo` for plugin `loganal` and field `alpharoemo__Secret`).
- The value in the plugin dict will be replaced with the Key Vault reference (the full secret name).
- When retrieving a plugin, any Key Vault reference in `auth.key` or `additionalFields` ending with `__Secret` will be replaced with a UI trigger word (or optionally, the actual secret value).
- When deleting a plugin, any Key Vault reference in `auth.key` or `additionalFields` ending with `__Secret` will be deleted from Key Vault.


### Example
```json
{
  "name": "loganal",
  "auth": {
    "type": "key",
    "key": "my-actual-secret-value"
  },
  "additionalFields": {
    "alpharoemo__Secret": "supersecretvalue",
    "otherSetting__Secret": "anothersecret"
  }
}
```
After saving, the plugin dict will look like:
```json
{
  "name": "loganal",
  "auth": {
    "type": "key",
    "key": "loganal--action--global--loganal" // Key Vault reference
  },
  "additionalFields": {
    "alpharoemo__Secret": "loganal--action-addset--global--loganal-alpharoemo", // Key Vault reference
    "otherSetting__Secret": "loganal--action-addset--global--loganal-otherSetting" // Key Vault reference
  }
}
```
**Note:** The Key Vault secret name for each additional setting is constructed as `{pluginName}-{additionalsettingname}` (with __Secret removed).


### Benefits
- No custom code required for plugin writers to leverage Key Vault for secrets.
- Supports any number of dynamic secrets per plugin.
- Consistent with existing agent secret handling.
- Secret names are AKV-compliant and descriptive, making management and debugging easier.


### Usage
- To store a secret, add a key to `additionalFields` ending with `__Secret` and set its value to the secret.
- The application will handle storing, retrieving, and deleting the secret in Key Vault automatically.
- Secret names for additional settings will follow the `{pluginName-additionalsettingname}` pattern.

### Related Files
- `functions_keyvault.py` (helpers for save, get, delete)
- `plugin.schema.json` (schema supports arbitrary additionalFields)

### Version History
- Feature added in version: (add your current config.py version here)

---
