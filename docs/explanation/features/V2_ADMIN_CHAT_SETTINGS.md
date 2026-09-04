# V2 Admin Chat Settings

**Implemented in version: 0.261.059**

## Overview

The V2 React admin surface renders its controls from a machine-readable field
schema in `admin_settings_fields.py`. Sections with no entry fall back to
scanning the settings document for `enable_*` booleans and guessing which section
each belongs to. That fallback keeps undescribed groups usable, but it can only
draw switches.

This describes the **Chat** group in full — eleven sections across three tabs —
so it renders the same controls the server-rendered admin page does, and moves
six toggles that the fallback had been filing under Chat back to the groups they
belong to.

## Dependencies

- `admin_settings_nav.py` — supplies the section ids the schema keys off
- `admin_settings_secret_utils.py` — masking and resolution for credential fields
- `route_backend_settings.py` — the connection test endpoint reused by the
  storage test component

## What the fallback could not render

Before this change the Chat page had three distinct problems.

**Every non-boolean chat setting was invisible.** The scan only sees `enable_*`
booleans, so these had no control at all:

| Section | Missing |
| --- | --- |
| Chat File Uploads | `require_member_of_chat_file_upload_user` — a switch, but not `enable_`-prefixed |
| Workspace Scope Lock | `enforce_workspace_scope_lock` — same |
| Conversation History | `conversation_history_limit` |
| Default System Prompt | `default_system_prompt` |
| Enhanced Citations | Authentication type, two storage credentials, four numeric limits, chunk model mode and deployment |

**Six toggles from other groups were misfiled into Chat.** The scan matches a key
to the section sharing the most leading word stems, and takes the first section
that scores at all:

| Key | Guessed into | Actually belongs to |
| --- | --- | --- |
| `enable_audio_file_support` | Chat File Uploads | Knowledge › Audio & Video |
| `enable_chat_completion_audio_cues` | Chat File Uploads | Knowledge › Audio & Video |
| `enable_video_file_support` | Chat File Uploads | Knowledge › Audio & Video |
| `enable_enhanced_extraction` | Enhanced Citations | Knowledge › Document Extraction |
| `enable_default_embedding_model_plugin` | Default System Prompt | Agents & Actions › Actions |
| `enable_tabular_processing_plugin` | Processing Thoughts | Nowhere — it is derived |

**Four switches were not editable settings.** `enable_tabular_processing_plugin`
is the clearest: `is_tabular_processing_enabled()` returns
`enable_enhanced_citations`, and `get_settings()` rewrites the stored value on
every read, so toggling it appeared to save and then reverted on the next load.

## Architecture

### Declared sections

| Tab | Section | Fields |
| --- | --- | --- |
| Chat Experience | `processing-thoughts-section` | 1 |
| Chat Experience | `chat-file-uploads-section` | 2 |
| Chat Experience | `conversation-contents-drawer-section` | 1 |
| Chat Experience | `workspace-scope-lock-section` | 1 |
| Chat Experience | `conversation-history-section` | 4 |
| Chat Experience | `default-system-prompt-section` | 1 |
| Chat Experience | `fact-memory-section` | 1 |
| Feedback & Alerts | `user-feedback-section` | 1 |
| Feedback & Alerts | `desktop-notifications-section` | 1 |
| Citations | `standard-citations-section` | 0 — explanatory only |
| Citations | `enhanced-citations-section` | 11 |

Standard Citations is deliberately absent from the schema. Standard citations are
always on and have nothing to configure, so declaring an empty section would
imply otherwise. A section with no fields and no guessed rows is skipped.

### The `secret` field type

Enhanced Citations is the first V2 section to render a credential, which required
a field type that never shows the stored value.

A `secret` renders as a masked input with a reveal toggle and a Clear action, and
receives the stored value alongside the pending one so it can tell "nothing is
configured" from "configured but hidden" from "about to be deleted". The server
sends `***REDACTED***` in place of a populated credential and resolves that same
sentinel back to the stored value on save, so an untouched field round-trips
without the secret reaching the browser. The mask is not rendered into the input
itself — the field is left empty with a placeholder saying a value is saved —
because putting it there would let a keystroke append to it, and clearing it on
focus would turn an idle click into a deleted credential. Clearing submits an
empty string, which is the only way to remove a credential rather than replace it,
and the control warns and offers Undo before a save acts on it.

Adding this type also closed a pre-existing gap in which the V2 admin API
returned every stored credential in cleartext. See
`V2_ADMIN_SETTINGS_SECRET_EXPOSURE_FIX.md`.

### String-valued and multiple dependencies

`depends_on.equals` accepted only a boolean, which is enough to gate a field on a
capability switch. V1 gates each Enhanced Citations credential on the selected
authentication type instead — the connection string appears for key
authentication, the blob endpoint for managed identity. `equals` now also accepts
a string, compared against the gate field's value.

`depends_on` also accepts a **list** of conditions, all of which must hold. That
is required because the renderer evaluates each field's conditions on its own
rather than recursively: a field gated only on a sibling stays visible whenever
that sibling's *value* matches, even when the sibling is itself hidden. Gating the
connection string on the authentication type alone left it on screen while
Enhanced Citations was off, because the authentication type defaults to `key`
either way. Each field therefore repeats the conditions its gate carries:

```python
{
    "key": "office_docs_storage_account_blob_endpoint",
    "type": "secret",
    "label": "Storage Account Blob Service Endpoint",
    "default": "",
    "depends_on": [
        {"key": "enable_enhanced_citations", "equals": True},
        {"key": "office_docs_authentication_type", "equals": "managed_identity"},
    ],
}
```

Two schema tests hold this: a string condition must name a value its gate actually
offers, and a gated field must repeat every condition its gate carries. The second
also caught a pre-existing instance of the same bug in the Appearance group, where
the Latest Features documentation links toggle stayed visible with the Support
menu switched off.

### Suppressed capabilities

`SUPPRESSED_CAPABILITY_KEYS` names keys the fallback scan must not draw, each
with a written reason. Declaring them was not an option, because a declared field
claims there is something to edit.

| Key | Why |
| --- | --- |
| `enable_tabular_processing_plugin` | Derived from `enable_enhanced_citations` and rewritten on every read |
| `enable_enhanced_citations_mount` | No control in either interface; forced off unless Enhanced Citations is on |
| `enable_mixed_source_chat_search` | Staged rollout flag with no administrator control |
| `enable_mixed_source_conversation_continuity` | Staged rollout flag gated behind the above |

The list is served on the settings GET as `suppressed_capabilities` and honoured
by `buildCapabilityIndex`.

### Enhanced Citations storage test

Startup deliberately skips live storage checks so a storage outage cannot block
application boot, which means a wrong credential is otherwise only discovered
when a citation fails to open.

The `enhanced-citations-storage-test` component posts to
`/api/admin/settings/test_connection` with `test_type: enhanced_citations_storage`
and the values currently on screen. Because the credentials are masked, the draft
usually holds the sentinel; the endpoint already resolves it through
`_resolve_admin_settings_test_secrets`, so a stored credential can be validated
without the browser holding it. The response's status, message, details and
guidance are rendered inline.

## File structure

| File | Role |
| --- | --- |
| `application/single_app/admin_settings_fields.py` | Section declarations, the `secret` type, `SUPPRESSED_CAPABILITY_KEYS` |
| `application/single_app/admin_settings_secret_utils.py` | Masking and resolution, importable without Azure clients |
| `application/single_app/route_backend_v2.py` | Serves the schema and suppression list; masks secrets both ways |
| `application/single_app/templates/admin/_panes/chat-experience.html` | V1 counterpart, including the new summarization controls |
| `application/v2_ui/src/components/admin/fields.tsx` | Generic field controls |
| `application/v2_ui/src/components/admin/SecretField.tsx` | Masked credential control |
| `application/v2_ui/src/components/admin/EnhancedCitationsStorageTest.tsx` | Storage connection test |
| `application/v2_ui/src/lib/adminFields.ts` | `secret` type, string dependencies, the sentinel |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Component branch and capability suppression |

## Usage

No configuration is required. Administrators see the controls at
**Admin Settings › Chat** in the V2 interface, matching the server-rendered page.

To add a Chat setting, declare it in `admin_settings_fields.py` under its section
id and add the matching control to the V1 pane. The parity test fails if either
half is missing, so the two interfaces cannot drift apart.

## Testing and validation

| Test | Covers |
| --- | --- |
| `test_v2_admin_chat_parity.py` | Panes match navigation; every V1 field is claimed; no invented schema field; select options and number bounds agree; V1 password inputs are declared as secrets |
| `test_v2_admin_secret_field_handling.py` | Masking, the sentinel round trip, replace, clear, nested secrets, and both endpoint responses |
| `test_v2_admin_capability_placement.py` | Appearance and Chat receive no guessed rows; relocated keys stay declared; suppressed keys stay suppressed and carry a reason |
| `test_v2_admin_settings_schema.py` | Field shape, defaults against the application, string dependencies reachable, gated fields inherit their gate's conditions |
| `test_v2_admin_field_renderer_coverage.py` | Every declared type and component has a renderer branch |

### Known limitations

- The `enable_*` fallback still serves every group that is not yet described.
  Around 22 rollout and telemetry flags remain under "Other capabilities".
- Number bounds are compared only where V1 declares them. V1 leaves
  `conversation_history_limit` unbounded; the schema gives it a floor of 1 so the
  control cannot produce a negative, and V1's save now clamps to the same floor.
- The storage test reports reachability and container existence. It does not
  verify write permission, which is only exercised on a real upload.

## Related

- `docs/admin/chat.md` — administrator-facing settings reference
- `docs/explanation/fixes/CHAT_HISTORY_SUMMARIZE_SETTINGS_RESET_FIX.md`
- `docs/explanation/fixes/V2_ADMIN_SETTINGS_SECRET_EXPOSURE_FIX.md`
