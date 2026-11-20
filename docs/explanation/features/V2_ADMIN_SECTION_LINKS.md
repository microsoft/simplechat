# V2 Admin Section Links

## Overview

Admin Settings in V2 refers administrators to other places: a setting says where its effect
shows up, a prerequisite says what must be turned on first, a release announcement offers a
shortcut to the setting it describes, and a notice says where the classic single chat endpoint
is configured. Some of those links used to leave V2 for the classic admin page even though V2
draws the section they name, and the ones that did leave opened a page address the classic page
does not understand.

Every such link now follows one rule. When V2 draws the section, the link moves within the page.
Only a section V2 never draws opens the classic page, in a new tab, on the tab that holds it, and
that address carries the classic escape pair (`ui=classic`) so it keeps opening the classic page
once the classic-to-V2 redirect is switched on.

**Implemented in version:** **0.261.448** (`application/single_app/config.py`)

**Dependencies:** `admin_settings_nav.py` (the navigation), `admin_settings_fields.py` (the field
schema), the V2 Admin Settings page and the Latest Features catalogue
(`functions_support_latest_features.py`). No new routes, settings, packages or browser assets.

## Technical specifications

### The classic page reads a tab, not a section

The server-rendered Admin Settings page reads the address fragment as a **tab id** and shows that
tab's pane. A section or card id in the fragment finds no pane and leaves the page showing none.
A link into the classic page therefore has to name the tab that holds the section.
`safeClassicAdminTabHref(tabId)` in `lib/adminOperations.ts` is the one place that builds that
address (`/admin/settings?ui=classic#<tab>`), and a functional test fails if any other V2 file
builds one by hand. `/admin_settings#...`, which an earlier link used, was never a classic route.

### The classic escape pair

Once an administrator has selected the modern interface, the server answers a plain classic page
address with a redirect to that page's V2 counterpart (see
[V2 Interface Selection Prerequisites](V2_INTERFACE_SELECTION_PREREQUISITES.md)). A V2 link that
really means "the classic page" would then land straight back in V2. `safeClassicAdminTabHref`
therefore wraps the address with `withClassicEscape` from `lib/classicLinks.ts`, which adds
`ui=classic` before the fragment and keeps everything else, so a link to the Backup tab is
`/admin/settings?ui=classic#backup`.

- The pair applies to that one request. It sets no cookie and no session flag, and the classic page
  ignores it, so adding it is harmless whichever interface is selected. Nothing changes for anyone
  today, because the redirect is switched off (`get_ui_mode()` still answers classic).
- The result is always a same-site absolute path. `withClassicEscape` extends only such a path, the
  tab id is percent-encoded, and the fragment stays the tab id the classic page reads.
- `lib/adminOperations.ts` imports `lib/classicLinks.ts`, which imports only the generated route map
  and the conversation URL helpers, so the import adds no cycle.

### Deciding where a link leads

`resolveAdminSectionLink(nav, sectionId, nativeSectionIds)` returns one of three answers:

| Answer | When | What the reader sees |
| --- | --- | --- |
| `section` | V2 has something to draw for the section, even if a condition hides it right now | A button that scrolls to the section; a hidden section takes the reader to whatever switches it on |
| `classic` | The navigation names the section but V2 draws nothing for it | A link to `/admin/settings?ui=classic#<tab>` that opens in a new tab, with "(opens in a new tab)" for assistive technology |
| none | The navigation does not name the section | The notice states what is missing and offers no link, rather than one that leads nowhere |

The page builds `nativeSectionIds` from the schema's sections that have fields, the fallback
`enable_*` capability rows, and the Latest Features tab. The three places that follow it are:

- **Prerequisite notices** (`SettingsSection`, through the new optional `sectionLink` prop):
  "Configure Redis Cache" moves within the page; the classic wording is "Configure Redis Cache on
  the classic admin page".
- **Related-section links** (`RelatedSectionLink`, `renderRelatedSection`): the page passes
  `onNavigate` for any section it draws unless the field sets `classic_only`.
- **Latest Features shortcuts** (`resolveAdminActionTarget`): a named section wins when it is
  drawn; otherwise the shortcut lands on the first card V2 draws for the tab; the classic tab is
  the last resort.

### Classic element ids in announcements

Release announcements were written against the classic page, so a few name an element inside a
classic pane rather than a navigation section. V2 draws each as a section of its own, and one
sits under a different tab than the announcement says (Global Actions is under Actions, where the
announcement says Agents). `CLASSIC_ELEMENT_SECTIONS` in `lib/latestFeatures.ts` maps them:

| Classic element | V2 section |
| --- | --- |
| `model-endpoints-wrapper` | `multi-endpoint-configuration` (AI Connections) |
| `plugins-table` | `actions-config` (Global Actions) |
| `agents-configuration` | `organization-agents-section` (Global Agents) |
| `global-workspace-identities-root` | `workspace-identities-section` (Global Identities) |

The alias is used only when the section it names is drawn, so a mapping to a section a future
build removes falls back to the tab instead of to nothing.

Run against the shipped catalogue, all 71 admin shortcuts land on a V2 section; none falls back to
the classic page. Eight shortcuts name one of the four elements above. Before the alias map, three
landed on the wrong card (**Open Actions**, twice, and **Open Global Agents** opened Agent Runtime)
and the other five reached the right section only because it was the first card of its tab. Now
every shortcut that names an element rather than a navigation section resolves to the section that
holds it, and none names an element V2 does not draw.

### The chat mode notice

When chat runs on the classic single endpoint, the notice used to link to a tab with a malformed
address and told the administrator to turn on a switch it called "Use connections for chat".

- **Go to AI Connections** moves to `multi-endpoint-configuration`, where the switch is.
- The classic endpoint's own fields (address, key, deployment) stay on the classic page by design:
  V2 does not carry them, because AI Connections replace them. That one link names the
  `model-endpoints` tab and opens in a new tab.
- The switch is named as the page labels it, **Use AI Connections for chat**.

### Global Identities

The Global Identities section (Admin Settings > Security > Global Identities) used to be a
read-only list that sent the administrator to the classic page to add, edit or delete one. It is
now the identities workbench the workspaces use, bound to the administrator routes that name
the global scope, so an administrator creates, edits and deletes a global identity in place. How it
works, and how it differs from a workspace's identities, is in
[V2 Workspace Identities](V2_WORKSPACE_IDENTITIES.md#global-identities-in-admin-settings).

The section no longer links to the classic page at all: the "Adding, editing and deleting an
identity is done on the classic admin settings page" paragraph and its link are gone, and the card
keeps its own help text from the settings schema.

### The Document Access Index diagnostics switch

`enable_dai_debug` was marked `classic_only` because its diagnostics were believed to be drawn
only by the server-rendered DAI card. The V2 DAI Metrics panel draws them: **Run one backfill
batch**, **Reset checkpoint** and the shadow validation figures. The flag is removed, so the
switch's link to DAI Metrics moves within the page. `classic_only` remains in the schema
vocabulary; no field sets it now.

### The fallback scan note

The page used to say that groups relying on the fallback scan "still" needed the classic page and
linked to it. The classic page cannot render those switches any better, and the link addressed a
section where the classic page reads a tab, so it did not work. The note now says only that the
switches are listed by their setting name, have no description yet, and save exactly as stored.
The fallback scan currently draws eleven `enable_*` keys with no declared field
(`enable_analysis_deliverable_contract_telemetry`, `enable_collaborative_conversations` and the
`enable_tabular_*` rollout flags); none has a classic control either. Since 0.261.474,
`enable_model_catalog_online_updates` is suppressed: the Catalog updates card owns it.

## Usage

Nothing needs to be configured. From any Admin Settings link:

- A button reading **Go to ...** or **Configure ...** stays on the page and scrolls to the section.
- A link reading **... on the classic admin page** opens the classic page in a new tab on the right
  tab, with the classic escape pair in its address. Use it only for the items listed below.

### What still opens the classic page

| Link | Why |
| --- | --- |
| Standard citations (Chat > Citation) | An informational card that states how citations behave. It has no setting, so V2 has nothing to draw. No V2 link points at it today, but one that did would open the classic Chat tab. |
| The classic single chat endpoint's fields | V2 deliberately omits them; AI Connections replace them. |
| Latest Features shortcuts for a tab V2 draws no card for | None today; the fallback exists for a catalogue entry written ahead of its V2 section. |

Creating, editing and deleting a global identity is no longer on this list: V2 does it in place.
Every link from V2 Admin Settings to the classic page is now one of the three above, because the
only classic address the page builds comes from `safeClassicAdminTabHref` and its four callers (the
related-section link, the prerequisite notice, the chat mode notice and the Latest Features
fallback) are those three cases.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_admin_parity.py` | Runs the TypeScript checks below; the diagnostics flag is gone and the V2 panel draws the controls it revealed; every link target is a navigation section and the only undrawn section is documented; the aliases name drawn sections; the real resolver lands all 71 shipped shortcuts in V2; no V2 file builds a classic address by hand, and the one helper wraps it with the escape pair |
| `functional_tests/test_v2_admin_parity_logic.ts` | Tab-id addresses with the escape pair (a same-site path whose query is the pair alone and whose fragment is the tab id, for hostile tab ids too), the three link answers, the related-section and chat mode markup, the alias map and its fallbacks |
| `functional_tests/test_v2_admin_help_logic.ts` | The Latest Features shortcut lands on a drawn card or on the classic tab, and the classic address carries the pair |
| `ui_tests/test_v2_admin_section_links.py` | The built page with the real schema, at 1440px and 390px with no sideways scrolling: a related link and a prerequisite move within the page or open the classic tab (with `ui=classic`) in a new tab; a target the navigation does not name has no link; the chat mode notice; the Global Identities section has no link to classic |
| `ui_tests/test_v2_admin_operations_settings.py` | The DAI link still opens the classic tab, with the pair, when the fixture serves no DAI section |
| `ui_tests/test_v2_admin_help_settings.py` | A Latest Features shortcut to a tab V2 draws no card for opens the classic tab with the pair |
| `functional_tests/test_v2_global_identities.py`, `ui_tests/test_v2_admin_global_identities.py` | The Global Identities editor itself; see the identities feature page |

### Known limitations

- The links are checked against the navigation and schema the server sends. A section added to
  the navigation without fields is reported by the functional test until it is documented.
- Not run against a deployment: the classic page's reading of `#<tab>` was verified from
  `admin_sidebar_nav.js`, not in a browser, and the escape pair has been exercised only against
  the redirect's own tests, because the redirect to V2 is switched off today.
- The classic page ignores `ui=classic` and V2 does not read it, so a classic address copied from
  the address bar carries it along. That is harmless.
