# V2 Admin Settings Secret Exposure Fix

**Fixed in version: 0.261.059**

## Issue

`GET /api/v2/admin/settings` returned the settings document unchanged. Every
stored credential in it — Azure OpenAI keys, APIM subscription keys, the Redis
key, Azure AI Search and Document Intelligence keys, the Speech service key, the
storage connection strings used by Enhanced Citations, and the Azure AI Foundry
client secret — was serialized into the JSON response and delivered to the
administrator's browser in cleartext.

Once there, the values were readable in the network response, in memory, and in
anything that captured either.

## Root cause

The endpoint documented a deliberate decision not to sanitize:

> Admin settings are not sanitized. Sanitization removes keys, secrets and
> endpoint configuration, which are exactly the values an administrator is here
> to manage.

That reasoning is correct, but it applies to `sanitize_settings_for_user()`,
which strips the keys outright and would leave the admin page unable to show that
a credential exists at all.

It does not apply to `redact_admin_settings_secrets_for_form()`, which is a
different mechanism built for exactly this situation. The server-rendered admin
form has used it for some time:

- On render, every populated secret is replaced with the sentinel
  `***REDACTED***`. Unset secrets stay empty, so "not configured" remains
  distinguishable from "configured but hidden".
- On save, `resolve_admin_settings_secret_value()` turns a submitted sentinel
  back into the stored value, so an untouched field round-trips without the
  credential ever leaving the server.

The V2 endpoint implemented neither half. The gap went unnoticed because no V2
section had rendered a secret yet — describing Enhanced Citations for the Chat
group is what first put one on the page.

## Fix

**Masked the read.** The GET now returns
`redact_admin_settings_secrets_for_form(settings)`. The branding assets payload
is still built from the unmasked document, because it reads image presence and
version counters rather than secrets.

**Stripped the model endpoint credentials.** Each entry in the `model_endpoints`
list carries `auth.api_key` and `auth.client_secret`, nested inside a list rather
than at a fixed settings key, so the key-based mask cannot reach them. The GET now
runs the list through `sanitize_model_endpoints_for_frontend` first, which
replaces the credentials with `has_api_key` and `has_client_secret` booleans —
the same substitution the server-rendered page makes before rendering its
template.

**Refused writing them back.** Because the browser only ever holds the stripped
copy, saving it would erase the credentials of every configured endpoint. The V2
surface has no model endpoint editor, so `model_endpoints` is listed in
`NON_PATCHABLE_KEYS` and the settings PATCH rejects it with an explanation rather
than passing it through.

**Masked the storage account keys.** `office_docs_key`, `video_files_key` and
`audio_files_key` were absent from the mask list on both surfaces.
`office_docs_key` is used directly as `account_key=` to sign the SAS tokens that
grant citation file access, so it is a live credential. No form submits any of
the three, so masking them affects only what is sent out.

**Masked the echo.** The PATCH responds with the keys it saved, and the client
merges that response into its state. Because a `secret` field resolves the
sentinel back to the real credential before saving, echoing `normalized`
unchanged would have handed the browser the exact value the GET now withholds.
The response is re-masked:

```python
"settings": redact_admin_settings_secrets_for_form(normalized),
```

**Extracted the helpers so the schema could use them.** The masking helpers lived
in `functions_settings.py`, which builds a Cosmos client at import time and
therefore cannot be imported by `admin_settings_fields.py`. They are pure
functions, so they moved to a new `admin_settings_secret_utils.py`.
`functions_settings.py` re-exports all of them, leaving every existing caller
unchanged.

**Added the `secret` field type.** The schema can now declare a field as a
credential rather than as text. Its normalizer resolves the sentinel against the
current settings, so an unedited field keeps its stored value instead of
overwriting a working credential with the literal string `***REDACTED***`.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/admin_settings_secret_utils.py` | New: the masking and resolution helpers, importable without Azure clients; adds the three storage account keys |
| `application/single_app/functions_settings.py` | Delegates to the new module and re-exports it |
| `application/single_app/admin_settings_fields.py` | `secret` field type and its normalizer; `NON_PATCHABLE_KEYS` |
| `application/single_app/route_backend_v2.py` | Masks the GET response, strips model endpoint credentials, masks the PATCH echo |
| `application/v2_ui/src/components/admin/SecretField.tsx` | New: masked input, reveal, clear, and the pending-removal warning |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Passes the stored value to the secret control |
| `application/single_app/config.py` | Version bump to 0.261.059 |

## Interface behaviour

The control shows a masked input, and its job is to keep three states apart. An
empty box could otherwise mean "nothing is configured", "something is configured
and hidden", or "the configured value is about to be deleted" — and deleting a
working connection string by backspacing, with no visible difference from the
untouched state, is the outcome that must not happen quietly. The component
therefore receives the stored value alongside the pending one.

When a credential is stored, the input is left empty and its placeholder says a
value is saved. The mask itself is never rendered into the input: a keystroke
would append to it and save `***REDACTED***newvalue` as the credential, and
clearing it on focus instead would turn an idle click into a deleted secret.

**Clear** submits an empty string, which is the only way to remove a credential
rather than replace it. Whenever a stored credential has a pending empty value —
whether from Clear or from erasing what was typed — the control says "The saved
value will be removed when you save" and offers **Undo**, which restores the
sentinel and returns the field to untouched.

| State | Input | Says |
| --- | --- | --- |
| Not configured | Empty | "Not configured" |
| Configured, untouched | Empty | "A value is saved and hidden" + Clear |
| Being replaced | The typed value | — |
| Pending removal | Empty | "The saved value will be removed when you save" + Undo |

The Enhanced Citations connection test sends whatever the field currently holds,
including the sentinel. The existing test endpoint already resolves it through
`_resolve_admin_settings_test_secrets`, so a stored credential can be validated
without the browser ever seeing it.

## Validation

`functional_tests/test_v2_admin_secret_field_handling.py` covers:

- a populated secret is masked, an unset one is not, and the caller's document is
  not mutated
- every field declared as a `secret` is in the masked-key list, so a control that
  promises to hide a value cannot be pointed at an unmasked key
- an untouched secret survives a save — the destructive case, where failing to
  resolve the sentinel would overwrite a working connection string
- a submitted secret replaces the stored value
- an empty submission clears it
- both endpoints mask before responding, and the GET strips model endpoint
  credentials
- `model_endpoints` is refused by the PATCH
- the three storage account keys are masked
- nested secrets are masked on a deep copy
- the control can tell untouched from pending removal, and the page supplies the
  stored value it needs to do so

### Before and after

| | Before | After |
| --- | --- | --- |
| GET response | 20 top-level secrets, 1 nested secret, and every model endpoint's API key and client secret in cleartext | All masked or stripped |
| Storage account keys | Unmasked on both surfaces | Masked |
| PATCH echo | Resolved secret returned to the browser | Re-masked |
| PATCH of `model_endpoints` | Would have written the stripped copy, erasing every key | Rejected |
| Saving an untouched Enhanced Citations section | N/A — no control existed | Stored credential preserved |
| Erasing a typed credential then saving | N/A | Warns and offers Undo before removing |

## Related

- `docs/admin/chat.md` — Enhanced Citations settings reference
- `docs/explanation/features/V2_ADMIN_CHAT_SETTINGS.md` — the described Chat group
