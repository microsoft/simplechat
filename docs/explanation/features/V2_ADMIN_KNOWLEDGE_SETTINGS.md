# Knowledge Settings in the V2 Admin Surface

**Implemented in version:** 0.261.072

## Overview

The Knowledge group is the largest in Admin Settings: five tabs, thirteen sections and
roughly 150 settings covering web search, URL access, deep research, the search index,
document extraction, audio and video, and file sync.

Until this change none of it was described in `admin_settings_fields.py`, so the V2 React
admin surface rendered the whole group through its `enable_*` fallback scan. That scan can
only draw switches, and only for boolean keys prefixed `enable_`. In practice the group
appeared as about twenty toggles labelled from their key names, and every endpoint,
credential, select, number, domain list, model picker, connection test and status readout
in it was absent from the interface entirely.

This work describes the group and, in doing so, corrects several structural problems that
existed in both interfaces.

## Why the structure changed

Three problems were not presentation issues; they were in the underlying arrangement.

**Document Intelligence was inside out.** In `templates/admin/_panes/extraction.html` the
"Enable Enhanced extraction" toggle is at line 13 and the Document Intelligence endpoint and
key are at line 390 — last in the card, after the extraction mode, formula extraction, the
Content Understanding card and the Office image card. An administrator turned a feature on
and then scrolled past everything depending on the connection before reaching it.

**Two cards were unreachable.** `content-understanding-section` and
`office-embedded-image-section` existed in the markup but were absent from `ADMIN_NAV`, so
neither interface could navigate to them and neither was documented.

**The completion chime was filed under AI Voice.** `enable_chat_completion_audio_cues` plays
a bundled local sound; its own help text says it does not require Azure Speech Service, yet
it was the first control in the AI Voice Conversations card, above the Speech resource
configuration.

## Architecture

### Schema vocabulary

`admin_settings_fields.py` gained the control kinds Knowledge needs.

| Addition | Purpose |
| --- | --- |
| `secret` field type | A credential. Sent to the browser as a redaction placeholder and dropped from an update when submitted unchanged. |
| `string_list` field type | An editable list of short strings, used for the URL Access domain policies. |
| `id_list` field type | A list of opaque identifiers backed by a search endpoint, used for File Sync workspace assignments. |
| `status` field type | A server-computed readout that is displayed but never stored. |
| `depends_on` composition | `equals`, `not_equals`, `any_of` and `all_of`, nestable. Needed because one block can be revealed by several independent capabilities. |
| `requires` | A prerequisite owned by a different section, mirroring the `data-requires` attributes `admin_settings_dependencies.js` reads. |
| `group` | An ordered, labelled cluster of fields with a variant, which is what the renderer discloses progressively. |
| `role: capability` | Marks the switch a section hangs off, so the renderer can lift it into the section header. |
| `paths` | Where a value is stored when that is not a top-level key of its own name. |
| `scale` | The multiplier between the unit a field is edited in and the unit it is stored in. |
| `required` | Marks a field that must hold a value before its section counts as configured. |

### Storage shapes

Three settings in this group are not stored under the name of their form field, and the
`paths` descriptor is what makes them save correctly.

- **The Web Search Foundry connection** is assembled into a nested `web_search_agent`
  object. The containing object is rebuilt from the stored one on every write, because
  `update_settings` merges at the top level only and writing a single leaf would discard
  the agent id and credentials.
- **URL Access domain lists** are stored twice, under `url_access_*` and
  `source_review_*`, because Deep Research reads the second copy.
- **Chunk sizes** live inside one `chunk_size` object as `{value, unit}`, and the assembled
  object is clamped to the embedding model's budget by `PATH_CONTAINER_NORMALIZERS`.

### Section presentation

`SettingsSection.tsx` renders a section as a header and a body. The header carries the
capability toggle and a status chip; the body is a sequence of collapsible groups.

`adminSections.ts` holds the decisions, kept apart from the component so they can be
executed in a test:

- `deriveSectionStatus` returns `blocked`, `off`, `incomplete`, `ready` or `none`. An unmet
  prerequisite outranks everything, because nothing else takes effect until it is met;
  being off outranks being incomplete, because blank fields under a disabled capability are
  not a problem to solve. A hidden field is never counted as missing.
- `shouldGroupStartOpen` opens a `connection` group while its capability is on and something
  required is still blank, and nothing else.

### Connection tests

`run_admin_settings_connection_test` in `route_backend_settings.py` is a shared dispatcher.
The server-rendered route and `POST /api/v2/admin/settings/test-connection` both go through
it, so the two interfaces cannot support different sets of tests.

A test declaration maps dotted request paths to settings keys, with an optional `when`
condition, which is how a single declaration covers both sides of an APIM-or-direct choice
without sending the branch that is not in use.

### Model vision capability

`functions_model_capabilities.py` resolves whether a model accepts image input in three
tiers: an explicit `supportsVision` flag on the model record, then
`static/json/model_capabilities.json`, then the historical name heuristic. The resolver
returns the source alongside the answer, so an inferred result can be marked as a guess.

The name heuristic is retained deliberately. `gpt-4o` predates the catalog and is absent
from it while remaining widely deployed; refusing to guess would have removed a working
model from the picker.

## Configuration

No new configuration is required. Existing settings documents are read as-is, and every
new descriptor is optional.

## Security

`GET /api/v2/admin/settings` previously returned `get_settings()` untouched, so the V2 admin
surface delivered every stored key, connection string and client secret to the browser in
plain text. The server-rendered page has always redacted these through
`redact_admin_settings_secrets_for_form`.

Both the GET and the PATCH echo now pass through `_redact_admin_settings_for_v2`, which
applies the server-rendered form's list and anything the schema declares as a secret,
following storage paths rather than field names. Submitting the placeholder back is
recognised as "unchanged" and dropped from the update, so a save that touches one toggle
cannot overwrite a credential with the literal placeholder string.

## Deliberate differences from the server-rendered panes

The V1 panes are unchanged. The parity tests require every V1 field to be claimed but not
that the two interfaces order or group them identically. The intentional differences are:

- Field order within Document Intelligence: connection first.
- `enable_chat_completion_audio_cues` filed under Chat › Feedback & Alerts.
- The Speech resource stated before the capabilities that share it.
- `source_review_default_mode` not reproduced. The V1 control is a permanently disabled
  select offering one option, shadowed by a hidden input hard-coded to `manual`, and
  `get_source_review_config` rewrites any other value on read.
- The Video Indexer cloud selector not reproduced. It has no stored setting of its own,
  existing only to compute `video_indexer_endpoint`, which V2 edits directly.

## Testing

| Test | Covers |
| --- | --- |
| `test_v2_admin_schema_vocabulary.py` | Field types, dependency evaluation, list coercion, secret handling |
| `test_v2_admin_settings_secret_handling.py` | Redaction on read and write; untouched credentials never written |
| `test_v2_admin_section_shell.py` | Shared dispatcher, route guards, page wiring, plus the TypeScript checks |
| `test_v2_admin_section_logic.ts` | Status derivation and group disclosure rules |
| `test_v2_admin_knowledge_web_research.py` | Parity, nested storage, consent gate, auth branching |
| `test_v2_admin_knowledge_extraction.py` | Parity, connection-first ordering, chunk size storage |
| `test_v2_admin_knowledge_audio_video.py` | Parity, audio cue relocation, shared Speech disclosure |
| `test_v2_admin_knowledge_file_sync.py` | Parity, Redis prerequisite, GB/bytes conversion, assignments |
| `test_model_vision_capability_resolution.py` | Three-tier resolution and its precedence |

## Known limitations

- The `multimodal-vision-section` picker lists models from `model_endpoints` only. A
  deployment using the legacy single-endpoint settings has no model records to resolve
  against and will see an empty list.
- `model_capabilities.json` covers current models. Older ones, including `gpt-4o`, resolve
  through the name heuristic and are reported as inferred.
