# V2 Admin Settings Layout and Hierarchy

## Overview

V2 Admin Settings now uses the width of the screen. The settings content used to sit
in a 768px column, so on a typical desktop most of the window was empty while every
card ran long. Only the four Agents cards had the header band, icon, larger title, and
nested-switch presentation that made a section easy to scan.

This change does four things:

- The content fills the window beside an **On this page** index of the visible
  sections and their status.
- Every section uses the distinct card that the Agents cards introduced, with an icon
  taken from the navigation definition.
- Which switch leads which settings is read from the field schema, so the nesting the
  Agent Runtime card showed by hand now appears wherever the schema describes it.
- On a wide card each setting puts its label and description on the left and its
  control on the right, and runs of independent switches pair up in two columns.

## Implemented in version: **0.261.253**

The application version is maintained in `application/single_app/config.py`.

**Dependencies:** the React/TypeScript V2 UI, local `lucide-react` icons, Tailwind
container queries, `admin_settings_nav.py`, and `admin_settings_fields.py`. No new
packages, settings, routes, or browser asset sources are required.

## Technical specifications

### Page frame

`AdminSettingsPage` drops its `max-w-3xl` cap. The scrolling pane is an inline-size
container. At 76rem and above it becomes a grid of the cards and a 15rem index; the
whole frame stays within 112rem so an ultra-wide monitor does not stretch it. The
search bar aligns with the content instead of floating in the middle. The category
rail shows each group's icon from the navigation definition.

### Section presentation

`SettingsSection` always renders the distinct card: a labelled region, a header band
with the section icon, a large title that can take focus, the group and tab, and the
status chip. The plain card is gone.

| Piece | Source |
| --- | --- |
| Section icon | The navigation `icon` name, translated by `adminSectionIcons.ts`. All 92 names used today are mapped; an unknown name draws a neutral fallback. |
| Status | `computeSectionStatus` in `adminSections.ts`, computed once per section by the page and shared by the card chip and the index. A search no longer changes a section's status. |
| Field emphasis | `deriveFieldHierarchy` in `adminSections.ts`, overridable per field. |
| Overrides | `agentSectionAppearance.ts` keeps only the person and group icons on workspace permissions. `emphasis: 'none'` can remove a derived emphasis. |

### Derived field hierarchy

`deriveFieldHierarchy(fields)` reads each field's `depends_on`:

- A **lead** is an editable switch that a later field in the same section depends on.
- The **primary** field is the section's capability toggle or, failing that, its first
  field when that field is an ungrouped lead. It gets the accent-backed row.
- A **dependent** is an editable field that depends on a lead, or on another member of
  that lead's run, and follows it without interruption inside the same group. It is
  indented beside a neutral rail. Read-only mirrors, status readouts, and components
  never nest, and nesting is one level deep.

The rule reproduces the hand-built Agent Runtime card exactly, and applies the same
reading to the 37 schema sections that declare a switch with dependent settings, for
example the classification banner, the AI notice, and the APIM routing choice in
Azure AI Search. A lead inside a group, such as that APIM switch, nests its settings
without being promoted to the section's primary switch.

### Field layout

`FieldShell` in `fields.tsx` renders a heading, help, and control region. The rules
live in `theme.css` and resolve against the card through container queries:

| Card width | Layout |
| --- | --- |
| Below 50rem | Stacked: label, control, help. |
| 50rem and above | Label and help in a `minmax(13rem, 26rem)` column, the control beside them. |
| 64rem and above | Independent switches flow into two columns (`.admin-switch-grid`). |

Each control asks for the width its content needs: numbers are compact, selects and
colours standard, text and secrets wide, and textareas, lists, and components take the
full control column. A nested row's label column gives up the indent so its control
lines up with the rows around it. Markdown previews sit under their editor in the
control column. Because the queries use `rem`, larger text sizes move a card back to
the stacked layout on their own.

### On this page index

`SettingsIndex.tsx` lists the sections the current category and search show, grouped by
category when the view spans several. Each entry carries its icon and status as an icon
plus visually hidden text, and the header counts sections that need attention. A scroll
listener marks the current section with `aria-current="location"`; an entry chosen in
the index stays current until the administrator scrolls, which keeps a short final
section selectable. Selecting an entry scrolls to the card, honouring reduced motion,
and focuses its heading.

### File structure

| File | Responsibility |
| --- | --- |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Wide frame, rail icons, shared status, index, fixed in-page jumps. |
| `application/v2_ui/src/components/admin/SettingsSection.tsx` | Distinct card for every section, derived emphasis, switch grid. |
| `application/v2_ui/src/components/admin/SettingsIndex.tsx` | The On this page index. |
| `application/v2_ui/src/components/admin/adminSectionIcons.ts` | Navigation icon names to Lucide icons. |
| `application/v2_ui/src/components/admin/sectionStatusPresentation.ts` | Status labels, tones, and icons. |
| `application/v2_ui/src/components/admin/fields.tsx` | Split field shell and control widths. |
| `application/v2_ui/src/lib/adminSections.ts` | `deriveFieldHierarchy`, `computeSectionStatus`. |
| `application/v2_ui/src/styles/theme.css` | Field, switch-grid, and alignment rules. |
| `application/v2_ui/src/components/ui/primitives.tsx` | Optional label and description classes on `Toggle`. |

There are no API or persistence changes. Field order, visibility, defaults, status
semantics, acknowledgements, and the draft and save flow are unchanged.

## Usage

Open **Admin Settings** in V2 and choose a category, or search. On a wide screen the
index on the right shows every visible section with its status; select one to jump to
it. Settings that only apply while a switch is on appear indented beneath that switch.
See the [administration guide](../../admin/index.md#reading-v2-admin-settings).

## Testing and validation

- `functional_tests/test_v2_admin_section_logic.ts`, run by
  `test_v2_admin_section_shell.py`, executes the hierarchy rule against the Agent
  Runtime, AI notice, APIM, and capability patterns, the switch grid, overrides, and
  status precedence.
- `functional_tests/test_v2_admin_settings_layout.py` checks that every navigation icon
  is mapped and pins the wide frame, the shared status, the jump fix, and the layout rules.
- `ui_tests/test_v2_admin_settings_wide_layout.py` drives the built SPA with the real
  schema: width used at 1920px, label beside control when wide and stacked at 390px,
  paired switches, index status and jumps, and no overflow at 390px and 1920px with
  normal and 200% text, in light and dark.
- `ui_tests/test_v2_admin_agents_visual_hierarchy.py` keeps covering the Agents cards,
  now including Built-in Actions.

### Known limitations

- Nesting follows switches only. A select that reveals fields, such as an
  authentication type, does not nest them.
- Bespoke components, such as the App Role Requirements roster, keep their own layouts
  and use the full card width.
- The classic interface is unchanged.

Related: [V2 Model Catalog Workbench](V2_MODEL_CATALOG_WORKBENCH.md),
[V2 Admin Agents Visual Hierarchy](V2_ADMIN_AGENTS_VISUAL_HIERARCHY.md), and
[V2 Admin Section Jump Fix](../fixes/V2_ADMIN_SECTION_JUMP_FIX.md).
