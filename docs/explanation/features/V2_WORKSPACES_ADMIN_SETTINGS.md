# Workspaces Admin Settings in the V2 Interface

**Implemented in version: 0.261.060**

## Overview

The V2 React admin surface renders from the declarative field schema in
`admin_settings_fields.py`. A section with no entry there falls back to scanning the
settings document for `enable_*` booleans and guessing a home for each one from shared
word stems. That fallback keeps undescribed groups usable, but it can only ever draw
switches: a text box, a number, a list of assigned record ids, or any `require_member_of_*`
role gate is invisible to it.

The Workspaces group was almost entirely undescribed, which left thirteen settings with no
control anywhere in V2 and one tab that rendered nothing at all. This change describes the
group, adds the field type and three widgets it needs, and takes two structural decisions
about settings that were filed in the wrong place.

## What was invisible

| Setting | State before | State now |
| --- | --- | --- |
| `enable_user_workspace` | Declared | Declared, with copy naming the V2 "My Workspace" label |
| `enable_group_workspaces` | Guessed toggle, no help | Declared |
| `enable_group_creation` | Guessed toggle, no help | Declared positively, gated on group workspaces |
| `enable_public_workspaces` | Guessed toggle, no help | Declared |
| `enable_file_sharing` | Guessed toggle, no help | Declared |
| `require_member_of_create_group` | Not rendered | Declared |
| `require_owner_for_group_agent_management` | Not rendered | Declared |
| `public_workspace_display_name` | Not rendered | Declared (`text`, 32 characters) |
| `require_member_of_create_public_workspace` | Not rendered | Declared |
| `allow_personal_workspace_file_downloads` | Not rendered | Declared |
| `allow_group_workspace_file_downloads` | Not rendered | Declared |
| `require_group_assignment_for_file_downloads` | Not rendered | Declared |
| `file_download_allowed_group_ids` | Not rendered | Declared (`id_list`) |
| `allow_public_workspace_file_downloads` | Not rendered | Declared |
| `require_public_workspace_assignment_for_file_downloads` | Not rendered | Declared |
| `file_download_allowed_public_workspace_ids` | Not rendered | Declared (`id_list`) |
| `require_shared_conversation_file_approval` | Not rendered | Declared |
| `max_file_size_mb` | Not rendered | Declared, and moved to Knowledge |
| Global Identities | Empty tab | Read-only list, moved to Security |

Separately, none of the ten `require_member_of_*` settings rendered anywhere in V2, for the
same reason: the fallback scan only ever sees `enable_*` keys. All ten are now declared in
the sections that own them, and Security gained a roster that mirrors them.

## Architecture

### The `id_list` field type

Two file-download settings hold a list of record ids. `component` fields are non-patchable
by design, and `link_list` is the wrong shape, so a new patchable type was added:

```python
{
    "key": "file_download_allowed_group_ids",
    "type": "id_list",
    "label": "Groups allowed to download",
    "default": [],
    "search_endpoint": "/api/groups/discover",
    "search_param": "search",
    "search_extra": {"showAll": "true"},
    "results_key": "groups",
    "item_noun": "group",
    "item_noun_plural": "groups",
    "depends_on": {"key": "require_group_assignment_for_file_downloads", "equals": True},
}
```

Normalization is `_normalize_id_list` in `admin_settings_fields.py`: blanks dropped,
duplicates removed, order preserved, non-list input refused. It deliberately does not import
`normalize_file_download_allowed_group_ids` from `functions_settings`, because that module
reaches `config.py` and a live Cosmos client and is one of the modules the functional tests
replace with a stub. The V2 surface always sends a real JSON array, which is the input shape
where both implementations agree.

The V2 renderer dispatches `id_list` from `AdminSettingsPage.tsx` the way `link_list` is
already dispatched, to `components/admin/AssignmentPicker.tsx`.

### Two structural moves

**Maximum File Size moved to Knowledge > Document Extraction.** `max_file_size_mb` is read
by `functions_documents.py` for workspace uploads and by `route_frontend_chats.py` for chat
attachments, so Workspaces only ever owned half of what it does. It is checked before any
extraction runs, which is what puts it next to Chunk Sizes.

**Global Identities moved to Security, after Secrets.** They are credentials that File Sync
sources and actions reuse, referenced by name so the secret never travels with a
configuration, and stored in Key Vault where Key Vault is configured. Workspaces owns neither
consumer. The tab id `workspace-identities` is unchanged so deep links and the documentation
anchor still resolve, and the tab gained the `workspace-identities-section` entry it was
missing -- without a section, the V2 surface, which builds its page from group > tab >
section, had nowhere to render it.

Both moves change the server-rendered interface too, because `admin_settings_nav.py` is the
single definition both interfaces render from. The pane markup moved with each nav entry;
`test_admin_settings_sidebar_card_parity.py` fails if only one of the two is done.

### Group creation polarity

The server-rendered page renders an inverted `disable_group_creation` checkbox and flips it
before storing `enable_group_creation`. V2 declares the stored key directly, as "Allow Users
to Create Groups", so the switch and the value it writes agree. `LEGACY_FIELD_NAMES` records
the mapping so the parity test can resolve either name. The V1 pane is unchanged.

### Gating chains

The server-rendered File Downloads card shows every control unconditionally. V2 hides a
setting whose parent makes it inert:

```
allow_group_workspace_file_downloads
  └── require_group_assignment_for_file_downloads
        └── file_download_allowed_group_ids
```

with the same shape for the public workspace trio, and the group and public role
requirements gated on their workspace type.

### The app role roster

`collectAppRoleEntries` in `lib/adminFields.ts` walks the navigation and the field schema
together, collecting every declared field whose key starts with `require_member_of_`, and
records which group, tab and section owns each one. `components/admin/AppRoleRoster.tsx`
renders that list in Security > App Role Requirements.

Each roster switch binds to the same draft key as the control on the owning tab, so the two
are one edit rather than two values that can disagree. This mirrors what
`admin_access_roles_roster.js` does in the server-rendered page, except that it is built from
the schema instead of from the DOM, which means it cannot pick up a control that is not
really a settings key.

## File structure

| File | Change |
| --- | --- |
| `application/single_app/admin_settings_fields.py` | `id_list` type, `_normalize_id_list`, all Workspaces sections, `max_file_size_mb`, ten role gates, two component fields |
| `application/single_app/admin_settings_nav.py` | File size section and Global Identities tab relocated; the tab gained a section |
| `application/single_app/templates/admin/_panes/files-sharing.html` | File size card removed |
| `application/single_app/templates/admin/_panes/extraction.html` | File size card added after Chunk Sizes |
| `application/v2_ui/src/lib/adminFields.ts` | `id_list` type and properties, `collectAppRoleEntries` |
| `application/v2_ui/src/components/admin/AssignmentPicker.tsx` | New |
| `application/v2_ui/src/components/admin/GlobalIdentitiesList.tsx` | New |
| `application/v2_ui/src/components/admin/AppRoleRoster.tsx` | New |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Dispatch for the new type and two components |

## Usage

No configuration is required. Administrators open **Admin settings** in the V2 interface and
find the Workspaces group fully populated, Maximum File Size under Knowledge, and Global
Identities under Security.

Creating and editing a global identity is still done on the server-rendered admin page. The
V2 list links to it. The editor there handles Key Vault round-tripping and per-auth-type
field sets, and rebuilding it was not worth doing for a surface with very few users; a list
that says what exists and where to change it is more useful than the blank tab it replaces.

## Testing

`functional_tests/test_v2_admin_workspaces_parity.py` holds eleven checks:

- The Workspaces panes match `ADMIN_NAV`.
- Every form field the V1 Workspaces panes submit is claimed by the schema.
- The schema invents no Workspaces field V1 does not have.
- The group creation polarity mapping is recorded and defaults to on.
- The public workspace name limit in the schema matches `functions_settings.py`.
- Each relocated section moved in `ADMIN_NAV` **and** in the pane markup, and is not left behind in the pane it came from.
- Each relocated tab is in its new group and declares at least one section.
- All ten `require_member_of_*` keys the application seeds are declared, in the right section, as switches, and exist in their V1 pane.
- Every `id_list` search endpoint is a route the application registers.
- Every schema section id exists in `ADMIN_NAV`.
- The V2 renderer has a branch for the new type and both new components.

Also extended:

- `test_v2_admin_settings_schema.py` — `id_list` required properties and default type.
- `test_v2_admin_settings_normalization.py` — assignment lists are deduplicated and trimmed, and non-list input is refused.

Run:

```powershell
python .\functional_tests\test_v2_admin_workspaces_parity.py
python .\functional_tests\test_v2_admin_settings_schema.py
python .\functional_tests\test_v2_admin_settings_normalization.py
python .\functional_tests\test_v2_admin_field_renderer_coverage.py
python .\functional_tests\test_v2_admin_capability_placement.py
python .\functional_tests\test_docs_app_surface_coverage.py
```

## Known limitations

- The assignment pickers summarise a selection as a count and resolve names only through search. There is no endpoint that turns a set of ids back into names in bulk, and the server-rendered page has the same constraint.
- The group picker calls `/api/groups/discover`, which is gated on `enable_group_workspaces`. With group workspaces disabled the picker reports that the search is unavailable, which matches the server-rendered behaviour.
- Global Identities are read-only in V2.
- The roster shows only declared role requirements. All ten are declared today, so it is complete, but a new role gate added without a schema entry would be absent from it — and from the rest of V2 — until it is declared.
