# Enhanced Citations Storage Key Reset Fix

**Fixed in version: 0.261.059**

## Issue

Every save of the server-rendered Admin Settings page overwrote three stored
Azure Storage account keys with an empty string:

- `office_docs_key`
- `video_files_key`
- `audio_files_key`

`office_docs_key` is the key used to sign the SAS tokens that grant access to
Enhanced Citations source files. Once it was blanked, citation file downloads
returned `500 Internal server error: Storage access not configured` for every
user, and the only recovery was writing the key back into the settings document
directly.

The trigger was any admin save, for any unrelated reason.

## Root cause

The save handler wrote all three from form data with a literal empty default:

```python
'office_docs_key': form_data.get('office_docs_key', '').strip(),
'video_files_key': form_data.get('video_files_key', '').strip(),
'audio_files_key': form_data.get('audio_files_key', '').strip(),
```

No template renders an input named `office_docs_key`, `video_files_key` or
`audio_files_key`. A repository-wide search finds the names only in the settings
defaults, these three save lines, the two consumers in `route_frontend_chats.py`,
and some orphaned `getElementById` calls in `static/js/admin/admin_settings.js`
whose elements no longer exist.

With no field in the submission, `form_data.get(name, '')` returned `''` every
time, so the save stored an empty key.

The neighbouring fields in the same block escaped this. `office_docs_storage_account_url`
and `office_docs_storage_account_blob_endpoint` go through `admin_secret(...)`,
and `citation.html` does render inputs for them.

Note that `admin_secret` would **not** have fixed these three. It maps the
`***REDACTED***` sentinel back to the stored value, and an absent field yields
`''`, not the sentinel — and `''` is a legitimate "clear this credential"
signal. Preserving the stored value is what is needed when the field is absent.

## Consumers of the blanked key

| Location | Use |
| --- | --- |
| `route_frontend_chats.py:1711` | `generate_blob_sas(..., account_key=settings.get("office_docs_key"), ...)` |
| `route_frontend_chats.py:1870-1874` | Returns HTTP 500 when the key is empty |

## Fix

All three now fall back to the stored setting when the form does not carry the
field, matching the pattern already used by `tabular_generated_output_chunk_model_deployment`
a few lines above:

```python
'office_docs_key': form_data.get('office_docs_key', settings.get('office_docs_key', '')).strip(),
'video_files_key': form_data.get('video_files_key', settings.get('video_files_key', '')).strip(),
'audio_files_key': form_data.get('audio_files_key', settings.get('audio_files_key', '')).strip(),
```

`form_data.get` returns the fallback only when the key is absent from the
submission, so if an input is added later an explicit empty submission still
clears the key, which is the expected behaviour for a credential field.

The three keys were also added to `ADMIN_SETTINGS_FORM_SECRET_FIELDS` in the same
change, so they are masked before any settings document reaches a browser. See
`V2_ADMIN_SETTINGS_SECRET_EXPOSURE_FIX.md`.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/route_frontend_admin_settings.py` | Stored-value fallback for the three storage account keys |
| `application/single_app/admin_settings_secret_utils.py` | The three keys added to the mask list |
| `application/single_app/config.py` | Version bump to 0.261.059 |

## Validation

`functional_tests/test_admin_settings_absent_field_preservation.py` generalises
the rule rather than pinning these three keys. It parses the save handler for
every `'key': form_data.get('field', '')` read and requires each `field` to be
submitted by the composed admin template, so the whole bug class fails the build:

- 66 literal-default form reads are checked; all are backed by a real input.
- The three storage keys are separately asserted to use the stored fallback.
- One remaining unbacked read, `web_search_foundry_notes`, is recorded in
  `KNOWN_UNBACKED_FORM_READS` with a written reason. It belongs to Web Search,
  nothing renders or reads it, and there is no stored value to lose. The list is
  itself checked for staleness, so the exemption cannot outlive the setting.

This is the second instance of the same bug class found in this version; the
first was the conversation history summarize settings. See
`CHAT_HISTORY_SUMMARIZE_SETTINGS_RESET_FIX.md`.

### Before and after

| | Before | After |
| --- | --- | --- |
| `office_docs_key` after any admin save | `''` | Preserved |
| Enhanced Citations file download after a save | HTTP 500 | Works |
| Key visible in the settings sent to a browser | Yes | Masked |

## Related

- `docs/explanation/fixes/CHAT_HISTORY_SUMMARIZE_SETTINGS_RESET_FIX.md`
- `docs/explanation/fixes/V2_ADMIN_SETTINGS_SECRET_EXPOSURE_FIX.md`
- `docs/admin/chat.md` — Enhanced Citations settings reference
