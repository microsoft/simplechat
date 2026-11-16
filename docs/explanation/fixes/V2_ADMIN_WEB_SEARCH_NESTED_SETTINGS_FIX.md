# V2 admin Web Search nested settings fix (0.261.260)

## Issue

In the V2 Admin Settings page, **Test web search** failed for a Web Search connection that was already saved, even though every value was on screen:

> Web Search test could not start because required settings are missing or invalid.
>
> - Foundry Project Endpoint is required.
> - Foundry API Version is required.
> - Foundry Agent ID is required.

The test only worked while the values were unsaved edits. After **Save** or a page reload, it failed again.

The same section had three related symptoms:

- **Managed Identity Type** stayed hidden while the saved authentication type was Managed Identity. With a saved Service Principal, the Tenant ID, Client ID, Client Secret and Cloud fields stayed hidden.
- The section read as not configured, so its connection group opened as though it needed attention.
- Clearing a saved Service Principal client secret showed no "will be removed when you save" warning and no **Undo**.

The same blind spot also affected the **Document action capabilities** card under Agents & Actions. Its chat and workflow limits for Analyze, Comparison and Merge stayed hidden after their action was saved as enabled.

## Root cause

The V2 page keeps unsaved edits under each field's flat key, such as `web_search_foundry_endpoint`. The Web Search Foundry connection is not saved under those keys. The field schema declares a `paths` storage location inside `web_search_agent`, for example `web_search_agent.other_settings.azure_ai_foundry.endpoint`, and the save handler writes the values there.

Only the input renderer, `readFieldValue`, followed `paths`. Every other reader treated the key as a top-level setting:

| Reader | Before | Effect |
| --- | --- | --- |
| `ConnectionTest` payload builder | Read the draft, then `settings[key]`. | Saved Foundry values were sent as blanks, and the server rejected the test. |
| Dependency reader for field visibility | Followed `settings_path` but not `paths`. | Fields gated on the saved authentication type were hidden. |
| `SettingsSection` visibility filter | Received no field index. | A gate stored at any nested path read as unset, including the `settings_path` flags that gate the document action limits. |
| Section status helpers | Read `settings[key]`. | Required Foundry fields read as empty, so the section showed as incomplete. |
| `SecretField` saved-value check | Read `settings[field.key]`. | The saved client secret was not recognized. |

The server-side Web Search test, secret resolution and save handling were already correct.

## Version

Fixed in version: **0.261.260**, recorded by `VERSION` in `application\single_app\config.py`.

## Technical details

### Files modified

- `application/v2_ui/src/lib/adminFields.ts`
- `application/v2_ui/src/lib/adminSections.ts`
- `application/v2_ui/src/components/admin/ConnectionTest.tsx`
- `application/v2_ui/src/components/admin/SettingsSection.tsx`
- `application/v2_ui/src/pages/AdminSettingsPage.tsx`
- `application/single_app/config.py`

### Code changes

`adminFields.ts` now has one stored-value lookup, `readStoredFieldValue`. It follows `settings_path`, then the first `paths` entry, and otherwise reads the top-level key. `readFieldValue` uses it, so the input renderer behaves as before.

`readSettingValue` replaces the private dependency reader and is exported. It reads an unsaved edit first. Otherwise, it reads the saved value through the field that declares the key. Like the reader it replaces, it does not substitute the schema default, so a condition holds only once a value is saved or chosen.

The payload logic moved out of `ConnectionTest` into `buildConnectionTestPayload`, a pure function that reads every source through `readSettingValue`. `ConnectionTest` now requires the field index, so TypeScript rejects a call site that omits it.

`readSectionValue`, `collectRequirements`, `deriveSectionStatus` and `computeSectionStatus` accept an optional field index. `SettingsSection` accepts it as an optional prop and uses it for visibility, status and prerequisites. `AdminSettingsPage` passes its global index to the section shell, the connection test and the status calculation. It also gives `SecretField` the value saved at the field's storage path.

### Impact

Two areas change behavior:

- **Web Search connection fields.** These are the only `paths` fields referenced by a dependency or connection-test payload whose storage path differs from the field key. The URL Access lists are also referenced, but their first storage path is their own key, so they read the same value as before.
- **Document action limits.** The page already resolved their `settings_path` gates, but the section shell dropped the limits again because it had no field index. They now appear while their action is enabled, as the schema declares.

No settings document, API route or server-side validation changed.

## Validation

### Tests

- `functional_tests/test_v2_admin_nested_setting_reads.py`, with `test_v2_admin_nested_setting_reads.mjs`, runs this end to end:
  1. Saves a Foundry connection through the real `normalize_admin_settings_updates`.
  2. Masks the saved secret with `redact_admin_settings_secrets_for_api`, as the V2 settings response does.
  3. Runs the real TypeScript readers against the real field schema.
  4. Sends the resulting payload through `run_web_search_connection_test`.

  It covers managed identity and service principal connections, field visibility, section status, the saved client secret and an unsaved edit. It also checks that the old top-level read produces the exact three errors shown above.
- `functional_tests/test_v2_admin_section_logic.ts` adds checks for section status and `SettingsSection` visibility with gates saved through both `paths` and `settings_path`.
- `functional_tests/test_v2_admin_secret_field_handling.py` now expects `SecretField` to receive the value saved at the field's storage path.

Removing `paths` support from `readStoredFieldValue` fails 6 of the 8 end-to-end checks. Removing the field index from `SettingsSection`'s visibility filter fails the new shell check.

### Before and after

| Scenario | Before | After |
| --- | --- | --- |
| Test a saved managed identity connection | Endpoint, API version and agent ID reported as required | Saved values reach the Foundry agent call |
| Test a saved service principal connection | Endpoint, API version, agent ID and authentication type sent blank | Tested as a service principal; the server resolves the masked secret |
| Saved authentication type is Managed Identity | Managed Identity Type hidden | Managed Identity Type shown |
| Saved authentication type is Service Principal | Credential fields hidden | Tenant ID, Client ID, Client Secret and Cloud shown |
| Section status with a saved connection | Incomplete | Configured |
| Clearing a saved client secret | No removal warning | Removal warning and **Undo** shown |
| Document action enabled and saved | Chat and workflow limits hidden | Limits shown |
