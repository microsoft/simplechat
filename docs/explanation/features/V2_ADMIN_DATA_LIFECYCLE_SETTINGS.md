# V2 Admin Data Lifecycle Settings

**Implemented in version: 0.261.260**

## Overview

The V2 React admin surface renders its controls from the field schema in
`admin_settings_fields.py`. Until this change the Data Lifecycle group had no entry there, so
V2 drew it through the `enable_*` fallback scan: five bare switches with their storage keys
printed beneath them. Everything else the server-rendered panes offer was missing.

This describes the group in full -- Retention Policy, Document Classification and
Conversation Archiving -- so V2 reaches parity with the classic page, in V2's own design
language. Two backend gaps found along the way are fixed at the same time; see
[Public Workspace Conversation Retention Fix](../fixes/PUBLIC_WORKSPACE_CONVERSATION_RETENTION_FIX.md).

| Classic capability | V2 before | V2 now |
| --- | --- | --- |
| Per-type retention switches | Bare switches, keys printed | Switches with their scope icon and what they govern |
| Six organization defaults | Missing | Nested beneath their type's switch, shown only while it is on |
| Run hour (UTC) | Missing | 24-hour select, with the administrator's own clock beside it |
| Last and next run | Missing | Date, UTC time and relative time; the projected run while a change is unsaved |
| Manual Execution | Missing | **Run retention now**, an inline review with per-type results |
| Force Push Defaults | Missing | **Reset to the defaults**, an inline review with per-type counts |
| Classification categories | Missing | Row editor with colour, hex, reorder, remove, validation and a badge preview |
| Archiving | Bare switch | Switch with accurate help and the retention interplay |

## Dependencies

- `admin_settings_nav.py` -- the `data-lifecycle` group and its three section ids
- `route_backend_retention_policy.py` -- the existing execute, force-push and settings routes,
  reused unchanged
- `functions_retention_policy.py` -- the retention job
- `components/documents/documentPresentation.tsx` -- `ClassificationBadge`, reused for the
  category preview so it matches what users see

## Technical specifications

### Declared sections

| Section | Fields |
| --- | --- |
| `retention-policy-section` | Three type switches, six default selects (each `depends_on` its type), `retention-schedule`, `retention-reset-defaults`, `retention-run-now` |
| `document-classification-section` | `enable_document_classification` (capability), `document-classification-categories` (component, `required`) |
| `conversation-archiving-section` | `enable_conversation_archiving` (capability, with an info notice) |

The default selects mirror the classic pane's options value for value, which the parity test
checks. The schedule and both actions only appear while at least one type is on, through a
shared `RETENTION_ANY_SCOPE_ENABLED` dependency.

### Component-backed keys

Two values are saved through the settings PATCH but drawn by components, because no generic
control fits them:

| Key | Why a component | Validation |
| --- | --- | --- |
| `retention_policy_execution_hour` | Stored as an int; `execute_retention_policy` passes it to `datetime.replace(hour=...)`, which raises on a string. A generic select saves strings. | Whole number 0 to 23, else refused |
| `document_classification_categories` | A list of `{label, color}` rows | Labels trimmed, non-empty, at most 80 characters, unique without regard to case; colours six-digit hex, saved lower-case |

Both go through the new `_COMPONENT_VALUE_VALIDATORS` in `normalize_admin_settings_updates`.
It runs before the type-driven path, which refuses writes to a component, and unlike
`_DELEGATED_NORMALIZERS` it can refuse a value with a message.

`LEGACY_FIELD_NAMES` maps `document_classification_categories` to the classic form's
`document_classification_categories_json` hidden field.

### Rescheduling the next run

The classic save handler recomputes `retention_policy_next_run` on every save. V2 now does the
equivalent in `_apply_retention_schedule`, applied once a save is known to be valid:

- it runs only when a type switch or the hour is in the save;
- it moves the run only if one of those values changed, or no next run is stored;
- with every type off it clears the next run, otherwise it sets the next occurrence of the hour
  in UTC through `compute_retention_next_run`, the same rule the classic handler and the job use.

The derived key travels back in the PATCH response, so the readout updates without a reload.

### Inline reviews instead of dialogs

Run now and Reset open a review inside their own row rather than a modal: the workspace types
it may touch with the defaults each follows, plainly worded consequences that reflect the saved
archiving setting, then Cancel or confirm. Results replace the review in place. Keeping it
inline leaves the defaults above in view and does not hold the page behind a dialog during a
run that can take minutes. Focus moves to the review's heading when it opens and back to its
button when it closes.

Both actions:

- offer only the types whose retention is on in the **saved** settings;
- wait while an edit they depend on is unsaved -- any retention key for both, plus
  `enable_conversation_archiving` for a run -- because the routes read the stored settings;
- never show the server's error text for a 500, which can carry a raw exception; a 400's
  validation message is shown, and a gateway timeout is described as a run that may still be
  in progress.

After a run, the schedule is re-read from `GET /api/admin/retention-policy/settings` and merged
into the page through `mergeStoredSettings`, so **Last run** and **Next run** update.

### APIs used

| Route | Used by |
| --- | --- |
| `GET /api/v2/admin/settings`, `PATCH /api/v2/admin/settings` | Every declared field |
| `POST /api/admin/retention-policy/execute` | Run retention now |
| `POST /api/admin/retention-policy/force-push` | Reset to the defaults |
| `GET /api/admin/retention-policy/settings` | Schedule readout refresh |

No route was added. All are `@admin_required`.

### File structure

| File | Role |
| --- | --- |
| `application/single_app/admin_settings_fields.py` | Section declarations, validators, `compute_retention_next_run`, `_apply_retention_schedule` |
| `application/single_app/functions_retention_policy.py` | Public workspace conversation retention |
| `application/v2_ui/src/lib/retentionPolicy.ts` | Pure helpers: held state, saved scopes, labels, timestamps, summaries, error wording |
| `application/v2_ui/src/lib/classificationCategories.ts` | Reading and checking categories |
| `application/v2_ui/src/components/admin/RetentionSchedule.tsx` | Run hour and schedule readout |
| `application/v2_ui/src/components/admin/RetentionOperations.tsx` | Run now and Reset reviews |
| `application/v2_ui/src/components/admin/ClassificationCategoriesEditor.tsx` | Category editor and preview |
| `application/v2_ui/src/components/admin/retentionScopeIcons.ts` | One icon per workspace type |
| `application/v2_ui/src/components/admin/agentSectionAppearance.ts` | Scope icons on the switches; the Personal switch opted out of the derived primary emphasis, since the three types are peers |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Component branches and `mergeStoredSettings` |

## Usage

No configuration is required. Administrators find the controls at **Admin Settings > Data
Lifecycle** in the V2 interface. Behaviour, defaults and troubleshooting are described for
administrators in `docs/admin/data-lifecycle.md`.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_admin_data_lifecycle_parity.py` | Panes match navigation; every classic field claimed; no invented fields; select values match classic; defaults match the application; hour and category normalization; next-run rescheduling against the classic rule; the routes the controls call exist and are admin-only; runs the TypeScript checks |
| `functional_tests/test_v2_admin_data_lifecycle_logic.ts` | Held states, saved scopes, labels, the local-clock hint, timestamps, run and reset summaries, error wording, category problems, and the rendered held and empty states |
| `functional_tests/test_retention_policy_conversation_scope_coverage.py` | Public rows in the ownership matrix, chats from deleted public workspaces returning to personal policy, public-grounded deletion and logging, notification privacy |
| `functional_tests/test_v2_admin_capability_placement.py` | Data Lifecycle receives no guessed fallback rows |
| `ui_tests/test_v2_admin_data_lifecycle.py` | Real controls instead of bare switches; reveal and reschedule on save; the hour saved as a number; run and reset reviews, results and focus; held while unsaved; failure wording without exception text; category editing, validation and ordered save; no overflow at 390px with large text in light and dark |

### Known limitations

- Run now is synchronous on the existing route. On a very large deployment the request can
  outlast the gateway; the run continues, and the page says so.
- Category reordering uses row positions as keys, as the external links editor does, so focus
  stays on the button that was pressed rather than following the moved row.
- At the largest text size on a phone, long words in the review can break mid-word, as they do
  elsewhere on the page, rather than overflow the card.
