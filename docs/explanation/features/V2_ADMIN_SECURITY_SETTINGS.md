# V2 Admin Security Settings

## Overview

The V2 Admin Settings surface renders from `admin_settings_fields.py`, a machine-readable
description of every control. Sections with no entry there fall back to scanning the
settings document for `enable_*` booleans, which can only produce switches.

Security was entirely undescribed, so that fallback was the whole interface for it. This
work describes all six Security tabs, adds the generic schema capabilities that
description required, replaces the DOM-scraped app role roster with a declared registry,
and closes a secret exposure in the V2 settings endpoint.

**Implemented in version:** 0.261.063

**Dependencies:** `admin_settings_nav.py` for section ids, the existing
`/api/admin/settings/test_connection` and `/api/admin/settings/key-vault/secret-reminders`
endpoints, and the `ADMIN_SETTINGS_SECRET_FIELDS` redaction helpers in
`functions_settings.py`.

## What was missing

| Section | V2 before | V2 after |
| --- | --- | --- |
| Permissions | Not rendered at all | Two role switches with role-value guidance |
| App Role Requirements | Two misfiled maintenance toggles | Catalog of all eleven requirements |
| Access Denied Message | Not rendered at all | Message editor |
| Key Vault | Not rendered at all | 10 fields, connection test, reminder inventory |
| Content Safety | 2 switches | 9 fields across two routing paths, connection test |
| Idle Session Timeout | 1 switch | Switch plus 3 configuration fields |
| Azure Front Door | 1 switch | Switch, URL and derived redirect URIs |
| Rate Limit Message | 1 switch | Switch and Markdown message |

A section is skipped when it has neither a declared field nor a guessed switch, which is
why three of them rendered as nothing rather than as an empty card.

## Architecture

### Schema additions

All of these are generic and available to every group.

| Addition | Purpose |
| --- | --- |
| `secret` field type | Write-only credential; the browser receives a placeholder |
| `string_list` field type | Comma-edited list stored as an array |
| `input_type` on `text` | `email` or `url` input semantics |
| `group` on a field | Labelled sub-section inside one card |
| `depends_on` as a list | Every condition must hold |
| `equals` as a string | Gate on a select value, not only a switch |
| `ADMIN_SECTION_STATUS` | Section-level `Off` / `Needs configuration` / `On` |

### Multi-condition visibility

The server-rendered page nests controls inside enclosing `div`s, so a control inherits
every gate above it. A flat list has no equivalent, so each gate is declared on the field.
`content_safety_key` carries all three:

```python
"depends_on": [
    {"key": "enable_content_safety", "equals": True},
    {"key": "enable_content_safety_apim", "equals": False},
    {"key": "content_safety_authentication_type", "equals": "key"},
],
```

`iter_field_dependencies` and `field_dependencies_are_satisfied` read one condition or a
list through the same path, so callers never handle both shapes.

### Section status

`ADMIN_SECTION_STATUS` maps a section id to a capability toggle and rules deciding whether
an enabled section is usable. Rules exist rather than a flat key list because the required
keys change with configuration:

```python
"content-safety-section": {
    "enabled_key": "enable_content_safety",
    "configured": [
        {"when": {"enable_content_safety_apim": False},
         "requires": ["content_safety_endpoint"]},
        {"when": {"enable_content_safety_apim": True},
         "requires": ["azure_apim_content_safety_endpoint"]},
    ],
},
```

`evaluateSectionStatus` in `adminFields.ts` reduces that to one of three words, reading
unsaved edits in preference to stored values so the pill tracks the draft.

### App role registry

`admin_app_roles.py` declares each role requirement with the Entra role value, the section
that owns the real control, what enforcing it grants, what happens when it is off, and the
capability it depends on.

The server-rendered page builds its roster by scanning for
`input[name^="require_member_of_"]`. That cannot work in V2, where the controls are not all
in one document, and it silently misses `file_sync_personal_require_app_role`, whose key
does not match the prefix. The registry covers all eleven.

The roster itself is built by `collectAppRoleEntries`, which walks the navigation and the
field schema so each row knows which tab really owns it, then merges the registry in by
settings key. The two halves answer different questions and neither is redundant: the
schema says which requirements exist and where their controls live, the registry says what
each one means. A requirement the registry does not describe still renders, without the
role value and the before/after copy.

### Secret handling

`GET /api/v2/admin/settings` previously returned `get_settings()` unmodified, so every
credential in the document reached the browser. The flow is now:

1. **GET** passes settings through `redact_admin_settings_secrets_for_api`, replacing each
   stored secret with `***REDACTED***`.
2. **The control** shows `Stored` with a **Replace** action, or an empty password input when
   nothing is stored. There is no reveal, because there is nothing to reveal.
3. **PATCH** resolves every redacted key through `resolve_admin_settings_secret_value`, so
   the placeholder coming back means "leave it alone" and anything else is a real new value.
4. **The response** re-redacts before echoing, so a saved secret is not handed back.
5. **Connection tests** post the placeholder; `_resolve_admin_settings_test_secrets` already
   resolves it server-side.

The API redaction list is deliberately wider than the form's. The form list covers what
the server-rendered page draws; this endpoint returns the whole document, so it also
redacts `office_docs_key`, `video_files_key` and `audio_files_key`.
`office_docs_key` is an Azure Storage account key used to sign SAS URLs and no admin
template renders it as a secret. Those three stay out of the form list because the
server-rendered save path submits them back verbatim rather than through `admin_secret`,
so redacting them there would store the placeholder as the credential.

**Replace stages nothing.** Clicking Replace only switches the control into entry mode. It
does not write an empty value into the draft, because the control can unmount before
anything is typed — moving between groups, searching, or flipping a switch the field
depends on all drop it — which would leave a queued deletion behind with no visible cause.
An empty box while replacing means "keep what is stored"; clearing a value you typed is
what removes a secret.

### Components

| Component | File | Backing endpoint |
| --- | --- | --- |
| `app-role-requirements-roster` | `AppRoleRoster.tsx` | none; registry in the settings payload |
| `key-vault-secret-reminders` | `KeyVaultReminders.tsx` | `/api/admin/settings/key-vault/secret-reminders` |
| `connection-test` | `ConnectionTest.tsx` | `/api/admin/settings/test_connection` |
| `front-door-redirect-preview` | `FrontDoorRedirectPreview.tsx` | none; derived from the draft |

`connection-test` fields carry a `test_type`, and the component builds the payload shape
that branch expects.

## Capability placement

Undescribed `enable_*` keys are filed by matching word stems against section ids. Three
were landing in the wrong place, and declaring them is what stops the guess:

| Key | Was guessed into | Now declared in |
| --- | --- | --- |
| `enable_app_maintenance` | Security > App Role Requirements | `cosmos-maintenance-section` |
| `enable_startup_app_maintenance` | Security > App Role Requirements | `cosmos-maintenance-section` |
| `enable_key_vault_secret_storage` | Backup & Recovery | `keyvault-section` |
| `enable_key_vault_secret_expiration_reminders` | "Other capabilities" | `keyvault-section` |

The two maintenance toggles matched the token `app` in `app-role-requirements-section`.
Neither has a control on the server-rendered page, so declaring them puts V2 ahead of V1;
both are recorded in `V2_ONLY_FIELDS` with the reason.

## Cross-field rules

`_apply_cross_field_rules` handles settings that constrain each other, which cannot live on
either field's own definition because they may be saved independently. Today that is the
idle warning, lowered to the sign-out time with a warning rather than rejecting the save —
matching what the server-rendered form does silently.

Field-level normalization delegates where an implementation already exists:
`normalize_content_safety_violation_message`, `normalize_rate_limit_message`, and the
bounds enforced by `normalize_key_vault_secret_reminder_config`. `front_door_url` is
validated rather than silently blanked, so a refused URL is reported on the field.

## File structure

```
application/single_app/
  admin_app_roles.py                 # new: role requirement registry
  admin_settings_fields.py           # Security sections, new types, section status
  route_backend_v2.py                # redaction, section_status, role payload
  config.py                          # VERSION

application/v2_ui/src/
  lib/adminFields.ts                 # types, multi-condition visibility, status
  components/admin/fields.tsx        # secret and string_list controls
  components/admin/AppRoleRoster.tsx
  components/admin/ConnectionTest.tsx
  components/admin/FrontDoorRedirectPreview.tsx
  components/admin/KeyVaultReminders.tsx
  pages/AdminSettingsPage.tsx        # sub-sections, status pills, component branches
```

## Testing

| Test | What it holds |
| --- | --- |
| `test_v2_admin_security_parity.py` | Every V1 Security field is claimed; no invented fields; select values, number bounds and dependency chains match; credentials are declared as secrets; status descriptors reference real settings |
| `test_v2_admin_app_role_registry.py` | Every role-shaped settings key is registered; entries resolve to real sections and capabilities; role values match the V1 panes |
| `test_v2_admin_settings_secret_redaction.py` | The endpoint redacts, resolves and re-redacts; the API list covers every known credential; API-only keys stay out of the form list |
| `test_v2_admin_capability_placement.py` | Neither Appearance nor Security receives a guessed row; relocations stay declared; V2-only fields are documented |
| `test_v2_admin_field_renderer_coverage.py` | Every field type and named component has a renderer branch |
| `test_docs_app_surface_coverage.py` | Every capability toggle is documented or justified as exempt |

Run them together:

```powershell
python .\functional_tests\test_v2_admin_security_parity.py
python .\functional_tests\test_v2_admin_app_role_registry.py
python .\functional_tests\test_v2_admin_settings_secret_redaction.py
python .\functional_tests\test_v2_admin_capability_placement.py
python .\functional_tests\test_v2_admin_field_renderer_coverage.py
```

## Known limitations

- The Key Vault and Front Door **Configuration Guide** modals from the server-rendered page
  are not ported. Their content is on the documentation site.
- The tracked secret inventory loads on demand rather than with the page, so it shows
  "Refresh to load tracked secrets" until asked.
- A secret cannot be read back once stored. Removing one means replacing it and clearing
  the typed value, which is the same outcome the server-rendered form produces when its
  field is cleared.

## Related

- [Security settings](../../admin/security.md)
- [Scale settings](../../admin/scale.md)
- [React V2 UI](REACT_V2_UI.md)
