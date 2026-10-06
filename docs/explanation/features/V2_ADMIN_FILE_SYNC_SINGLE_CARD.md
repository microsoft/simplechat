# V2 Admin File Sync Single Card

## Overview

In V2 Admin Settings, File Sync used to be five unrelated cards: File Sync with its run
limits, Visible Source Types, and one card each for Personal, Group, and Public Workspace
Sync, each with its own switch and Access panel. Nothing tied a workspace type or the
source types back to the File Sync switch they depend on, so an administrator had to
read five cards to understand one capability.

File Sync is now one card, read from the top down:

- **Enable File Sync** is the card's switch, with the Redis Cache warning it already had.
- Turning it on shows **Personal workspaces**, **Group workspaces**, and **Public
  workspaces** nested beneath it. A workspace type can sync only while both File Sync
  and its own switch are on (`functions_file_sync.py`), and the nesting now says so.
- Each workspace type that is on has an **Access** panel directly under its switch,
  holding that type's rules: administrators-only source management, the
  PersonalFileSyncUser app role, and the assigned groups or public workspaces.
- **Run limits** and **Source types** (formerly Visible Source Types) are collapsible
  panels shared by every workspace type. Closed, Source types reports how many types
  are selected rather than "1 setting".

## Implemented in version: **0.261.260**

The application version is maintained in `application/single_app/config.py`.

**Dependencies:** the React/TypeScript V2 UI, `admin_settings_nav.py`,
`admin_settings_fields.py`, and `admin_app_roles.py`. No new packages, settings keys,
routes, or browser asset sources are required.

## Technical specifications

### One section in the schema

`ADMIN_NAV` lists a single section for the File Sync tab, `file-sync-section`. The four
sections it replaces (`file-sync-source-types-section`, `file-sync-personal-section`,
`file-sync-group-section`, `file-sync-public-section`) are gone from both the navigation
and `ADMIN_SETTINGS_FIELDS`, so V2 draws one card.

The fields are declared in an order the renderer depends on:

1. `enable_file_sync`, the capability.
2. The three workspace type switches, contiguous and ungrouped, each with
   `depends_on: enable_file_sync`. `deriveFieldHierarchy` nests an uninterrupted run
   under a lead switch, so anything declared between them would leave the switches
   after it un-nested. They no longer declare `role: capability`; a card has one.
3. The three Access groups, one per workspace type.
4. Run limits, unchanged.
5. Source types, now in a `source-types` group labelled "Source types".

Field visibility is not transitive in either renderer, so every field in an Access
panel repeats the File Sync condition as a chain, for example
`[enable_file_sync, enable_file_sync_group]`, and an assignment list adds its
restriction switch. Without the File Sync condition a panel would stay visible after
File Sync is switched off.

No settings keys, defaults, normalizers, legacy field names, or stored shapes changed.

### Anchored groups

A group descriptor may name an `anchor`: the key of an ungrouped switch declared earlier
in the same section.

```python
"group": {
    "id": "group-access",
    "label": "Access",
    "variant": "access",
    "anchor": "enable_file_sync_group",
},
```

`groupFields` carries the anchor through. `placeAnchoredGroups` in `adminSections.ts`
splits a section's groups into those drawn in the card body and those drawn beneath a
switch. A group is anchored only while its switch is actually drawn. When a search
matches a panel's settings but not its switch, the panel falls back to the card body
and its label takes the switch's name ("Group workspaces · Access"), because three
panels called "Access" would otherwise be indistinguishable.

`SettingsSection` renders an anchored panel inside its switch's row, after the control,
so it shares the row's nested rail. An anchor never flows into the two-column switch
grid. The panel button carries the switch's name for assistive technology through a
visually hidden prefix ("Group workspaces: Access"). On a card 50rem and wider,
`.admin-anchored-groups` in `theme.css` indents the panel 3.5rem to line up with the
switch's label, the same offset a switch row uses for its notices; on a narrower card
the panel keeps the full row.

Sections that declare no anchor render exactly as before.

### Collapsed group summaries

`describeCollapsedGroup` in `adminSections.ts` decides what a closed group's header
says. A group holding a single `checkbox_set` reports how many of its declared options
are checked, read from the unsaved draft first, for example "3 selected". Every other
group keeps its count, "6 settings". Only the File Sync Source types panel has that
shape today.

### Related registry change

`admin_app_roles.py` points the `PersonalFileSyncUser` requirement's `section_id` at
`file-sync-section`, so "Go to setting" in the Security roster lands on the card.

### Classic admin page

The server-rendered pane is unchanged: its markup, card ids, and "Visible Source Types"
heading stay as they were, and its deep links still resolve. Because the navigation is
shared, its sidebar now lists a single File Sync destination; that tab was already one
card, so the four sub-links only scrolled within it.

### File structure

| File | Change |
| --- | --- |
| `application/single_app/admin_settings_fields.py` | One `file-sync-section`, nested workspace types, anchored Access groups, Source types group; `anchor` documented. |
| `application/single_app/admin_settings_nav.py` | File Sync tab lists one section. |
| `application/single_app/admin_app_roles.py` | PersonalFileSyncUser links to `file-sync-section`. |
| `application/v2_ui/src/lib/adminFields.ts` | `anchor` on `AdminFieldGroup` and `RenderedFieldGroup`. |
| `application/v2_ui/src/lib/adminSections.ts` | `placeAnchoredGroups`, `describeCollapsedGroup`. |
| `application/v2_ui/src/components/admin/SettingsSection.tsx` | Anchored panels, accessible panel names, collapsed summaries. |
| `application/v2_ui/src/styles/theme.css` | Label-aligned indent for anchored panels on wide cards. |
| `docs/_data/app_surface.yml` | Regenerated; four sections removed. |
| `docs/admin/knowledge.md` | File Sync section rewritten for the single card. |

## Usage

Open **Admin Settings** in V2 and choose **Knowledge**, or search for "File Sync".
Turn on **Enable File Sync**, then turn on the workspace types that should sync. Open a
type's **Access** panel to restrict who manages its sources or which workspaces may
use it. Adjust **Run limits** and **Source types** for every workspace type at once.
See [Knowledge settings](../../admin/knowledge.md#file-sync-section).

## Testing and validation

- `functional_tests/test_v2_admin_knowledge_file_sync.py` pins the single section, the
  contiguous nested workspace types, one anchored Access panel per type, the File Sync
  condition on every anchored field, assignment lists nested under their restriction,
  the Run limits and Source types panels, the Redis prerequisite, the GB-to-bytes
  conversion, and V1 field parity.
- `functional_tests/test_v2_admin_schema_vocabulary.py` rejects an anchor that names no
  earlier ungrouped switch, an anchored field that does not require its switch and the
  switch's own conditions, and a group whose fields disagree on the anchor.
- `functional_tests/test_v2_admin_section_logic.ts`, run by
  `test_v2_admin_section_shell.py`, executes placement, the search fallback label, the
  collapsed summaries, and a rendered File Sync card in which each Access panel sits
  between its own switch and the next.
- `ui_tests/test_v2_admin_file_sync_single_card.py` drives the built SPA with the real
  schema: one card, nested types, folding when File Sync is switched off, panel
  placement and keyboard disclosure at 1440px and 390px, the live "N selected"
  summary, and no overflow at 390px and 1920px with normal and large text in light and
  dark.

### Known limitations

- An anchor must be an ungrouped switch. A panel cannot hang beneath a switch that is
  itself inside a collapsible group.
- The summary is specific to a lone choice list; other groups still report a count.
- The classic page's administrator-managed source search has no V2 equivalent yet.
