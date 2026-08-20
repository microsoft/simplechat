# Admin Settings IA rework — handoff

Everything a new conversation needs to continue this work. The session-local
scratch scripts do **not** survive, so the parts that mattered were moved into
the repository.

---

## Where things stand

Staging branch `feature/admin-settings-ia` on `microsoft/simplechat`, cut from
`Development`. Nothing reaches `Development` until the whole rework is tested
and merged in one final reviewed PR.

```
Development ─── feature/admin-settings-ia ──┬── #1297 stage 1    MERGED
                                            ├── #1304 stage A+B  MERGED
                                            ├── #1306 guardrail   MERGED
                                            ├── stage C          in review
                                            ├── stage D
                                            └── stage E
                                                      └──► final PR ──► Development
```

Current version: **0.260.019**. Fingerprint: **462 field names / 116 card ids**.
Navigation: **14 groups / 44 tabs / 93 sections**. Stages D and E are complete.

### The bug that got through, and why

Splitting one template into 44 partials broke a Jinja rule that never mattered
before: **`{% set %}` scope does not cross an `{% include %}` boundary.** Three
variables were left behind when their consuming card moved to another tab.

Every static test passed. Field names, card ids, tag balance, navigation parity,
modal placement — all green, because **none of them executed the template**.

Two failure modes, and the quiet one is worse:

- Attribute access on a missing name raises and takes the page down.
- A boolean test on a missing name is **silently false**, so the controls it
  guards never render and nothing reports a problem. `enable_dai_debug` sat in
  this state and was only found by auditing for the pattern that caused the crash.

`test_admin_settings_renders.py` now renders the whole page the way Flask does,
and `test_admin_settings_pane_variable_scope.py` catches the silent variant a
render cannot. Both are verified against a planted copy of the real bug.

**Rule: a template is not verified until it has been rendered.**

### Shipped

| Stage | Content |
|---|---|
| 1 | Template split into 18 per-tab partials under `templates/admin/_panes/`; Latest Features moved last and General made the landing tab; Global Identities heading; File Sync sidebar submenu; `sectionMap` pruned 72 → 6; classification banner preview fixed; CodeQL XSS sink fixed |
| A | 12 cross-tab links converted from tab-coupled `switchTab` to `data-admin-link` card targets; two were already broken; `switchTab` removed |
| B | `data-requires` dependency announcements with inline mirror and link; File Sync and Permissions wired |
| — | Form field contract enforced in CI |
| C | Navigation moved into `admin_settings_nav.py` as groups → tabs → sections; both navigations render from it; group level with persisted collapse state and group pills; three-level search |
| D (part 1) | Governance split into three tabs; Scale split into two; Front Door moved to Security; legacy tab redirects added |

---

## Guardrails — these now live in the repo

The single most important rule: **never rename a `name=` attribute.** Admin
Settings posts one form and the backend reads by field name, so a rename
silently stops a setting from saving with no error anywhere.

| Check | How to run |
|---|---|
| **Field contract** | `python -m pytest functional_tests/test_admin_settings_field_contract.py` |
| Regenerate baseline *(only for a deliberate removal)* | `python functional_tests/test_admin_settings_field_contract.py --update-baseline` |
| **Navigation map** | `python -m pytest functional_tests/test_admin_settings_nav_map.py` |
| Composition contract | `python -m pytest functional_tests/test_admin_settings_template_composition.py` |
| Card links | `python -m pytest functional_tests/test_admin_card_links.py` |
| Dependencies | `python -m pytest functional_tests/test_admin_settings_dependencies.py` |
| Sidebar parity | `python -m pytest functional_tests/test_admin_settings_sidebar_card_parity.py` |
| XSS | `python scripts/check_xss_sinks.py --full-file <changed files>` |

**Regression baseline:** the 75 functional test files that reference
`admin_settings.html` now sit at **32 pre-existing failures**, down from 33
after stage C fixed a missing navigation entry. That number must not increase. To reproduce the list:

```
cd functional_tests
python -m pytest $(grep -rl admin_settings.html test_*.py) -q -p no:randomly
```

Exclude `test_enhanced_pii_analysis_standalone.py`, which needs live Azure
credentials.

### Reading templates in tests

`admin_settings.html` is only a shell now. Tests must compose it:

```python
from test_support.templates import read_admin_settings_template
markup = read_admin_settings_template()
```

`test_admin_settings_template_composition.py` fails any test that reads the
template uncomposed while referencing a partial-backed card or field.

---

## Stage D — re-homing the cards — complete

Cards were re-homed into the target groups, one group per pull request, running
the field contract test and the full regression set on each.

### Proven pattern

1. Split the source pane with the split tool. It works line by line and
   **refuses to write unless every source line lands in exactly one output**.
2. Update `admin_settings_nav.py`: the tab entries and their sections.
3. Update the `{% include %}` list in `admin_settings.html`.
4. Add the old tab id to `LEGACY_TAB_REDIRECTS` in `admin_sidebar_nav.js`.
5. Verify: field contract, nav map test, parity test, Jinja compile, full
   regression set.

**Moving a whole tab between groups needs no markup change** — panes are
independent files and groups are entries in the map, so it is a one-line map
edit. Only moving a *card* between tabs requires markup surgery. Front Door
moved from Scale to Security that way.

### Done

| Group | Result |
|---|---|
| Governance | → Feature Governance, Policies, MCP Governance |
| Scale | → Redis & Caching, Cosmos; Front Door moved to Security as Network |
| Data Lifecycle | **New group.** Retention + Classification pulled from Workspaces, Archiving pulled from Safety |
| Chat | **New group.** Chat Experience (thoughts from AI Models, file uploads + contents drawer and scope lock from Workspaces), Feedback & Alerts (feedback + desktop notifications from Safety) |
| Appearance | **General dismantled.** → Branding, Notices & Agreements (+ user agreement from Workspaces), Pages & Links (+ external links) |
| Security | **Safety dismantled.** → Access & Roles, Secrets, Content Safety, Session, Network |
| Operations | Logging is now Logging & Health, gaining health check and API documentation from General |
| Help | Gains Support Menu from General |
| Knowledge | **Search & Extract dismantled.** → Web & Research, Search Index, Document Extraction (+ metadata extraction and multi-modal vision from Workspaces), Audio & Video |
| Workspaces | → Workspace Types, Files & Sharing (+ shared conversation file approvals from AI Models), Global Identities |
| Workflow | **New group**, split out of Workspaces |
| AI Models | → Model Endpoints (carries the legacy modal and its nested Chat Model card), Embeddings, Image Generation |
| Agents & Actions | → Agents, Actions, Inbound MCP (whole tab behind `mcp_ui_enabled`) |
| Backup & Recovery | → Backup, Migrate, Restore, Cosmos Editor, Jobs |

**Stage D is complete.** 14 groups, 44 tabs, from 17 flat tabs.

### Backup & Recovery: complication I4, resolved

The pane was 1,622 lines and needed three things the tools could not do:

- **The migration card is a `<section>`, not a `<div>`**, so every div-balancing
  helper walked straight past it. Its boundaries had to be found by balancing
  `<section>` instead. This is why the tools reported 5 top-level cards when
  there were 6.
- **Eleven dialogs**, six of them opened from JavaScript rather than a button,
  serving what became five different tabs. All were lifted to the shell.
  Checked first that none carried a `name=` attribute: the pane's twelve form
  fields are all radio groups inside the migration card, which stayed put.
- **Shared controls.** One save button, one status line and one operational
  warning serve all five tabs.

### Stage E: the mixed card and the role roster

**`system-settings-section` is gone.** It mixed five unrelated concerns under
one heading. Each moved to the tab that owns it, wrapped in a new card, with the
field markup carried across byte-for-byte:

| Field | New home |
|---|---|
| `max_file_size_mb` | Workspaces → Files & Sharing |
| `conversation_history_limit` | Chat → Chat Experience |
| `default_system_prompt` | Chat → Chat Experience |
| `access_denied_message` | Security → Access & Roles |
| idle timeout (4 fields) | stays in Security → Session, card renamed `idle-timeout-section` |

Splitting a card changes card ids but not field names, which is why the field
contract passed unchanged. Card ids are structural; **field names are the
breaking surface** and the contract test tracks only those, deliberately.

**The Access & Roles roster** gathers all ten `require_member_of_*` switches,
which are spread over seven tabs. It is built at runtime by
`admin_access_roles_roster.js` from `input[name^="require_member_of_"]`, not
from a list, so a new role requirement appears automatically.

Each row is a mirror carrying **no name attribute**, following the existing
proxy convention, so the setting is still posted exactly once. Sync is two-way:
the mirror drives the canonical input and dispatches a `change` event, and the
canonical input updates the mirror when changed on its own tab.

### Stage F: the last hardcoded tab ids

Two places still navigated by naming a tab, and both were broken by the rework:

- **The setup walkthrough** mapped each of twelve steps to a tab id. Eleven
  named tabs that no longer existed, so those steps would have moved nowhere.
  Each step already knew which card it was about, so the tab id was a duplicate
  copy of that knowledge. Steps now name the card and `openAdminCard()` finds
  the tab. `scrollToRelevantSection()` became redundant and was deleted.
- **Cosmos throughput validation** clicked `scale-tab` to reveal an invalid
  field. It now walks up from the invalid field to its own card, so it goes to
  wherever that field actually lives.

`test_admin_settings_walkthrough_targets.py` asserts every step points at an
element that exists, that no tab id is hardcoded, and that step numbering has no
gaps. A scan confirms **no stale `-tab` literal remains in executable admin
JavaScript**.

The general rule this rework converged on: **never name a tab; name the setting
and resolve the tab from the page.**

### A structural guard worth keeping
`test_every_pane_partial_is_balanced` checks `<div>` and `<section>` balance in
every pane. An unbalanced pane does not fail to render — it silently nests the
panes that follow it, so the failure surfaces somewhere unrelated and confusing.
This was found the hard way: a stray `</div>` in `access-roles.html` made a
Send Feedback test fail. Verified against a deliberately broken pane.

### Nav order must match markup order

`test_admin_settings_sidebar_card_parity` requires the nav map to list sections
in the same order the cards appear in the pane. Adding a card to a pane means
inserting it at the matching position in the map, not appending.



### Group-shared regions

Shared controls cannot be copied into each pane (duplicate element ids, and the
JavaScript module would bind to the wrong one) and cannot live in one pane (an
inactive pane is hidden, so the other four tabs lose the save button). They now
sit outside the panes in a region marked `data-admin-group-shared="<group>"`,
revealed only while that group is active.

`syncAdminGroupSharedRegions()` resolves the owning group from **either**
navigation. Reading only the top tab strip was a real bug: that strip is not
rendered at all in the sidebar layout, so the Backup & Recovery save button
would have been hidden permanently. Verified against a simulated DOM in both
layouts.


### Card container ids are not the nav section ids

Several cards are wrapped in a container whose id differs from the nav map's
section id, which is an inner anchor:

| Nav section id | Card container id |
|---|---|
| `web-search-section` | `web-search-foundry-section` |
| `embeddings-config` | `embeddings-configuration` |
| `image-config` | `image-generation-configuration` |
| `gpt-config` | `gpt-configuration` |
| `agents-config` | `agents-configuration` |
| `actions-config` | `actions-configuration` |

**The move and split tools take container ids**; the nav map keeps its own.
Run `list_pane_cards.py` for the real container id rather than assuming.

### Trap: gpt-configuration is inside a modal

`gpt-configuration` is **not** a top-level card. It lives inside
`legacyModelSettingsModal` in the AI Models pane.

**How this was resolved.** The modal was relocated to sit directly after
`multi-endpoint-configuration`, the card holding its trigger. The split then
assigned `multi-endpoint-configuration, gpt-configuration` to the same tab, so
the modal's opening lines, the nested card and the closing lines all landed in
`model-endpoints.html` in order and the modal reassembled intact.

### Three more splitting rules learned

- **A modal shared by cards that end up in different tabs must go to the
  shell.** `legacyModelDiscoveryIdentityGuideModal` is opened from endpoints,
  embeddings and image generation. Check for form fields first: a modal with a
  `name=` attribute cannot move outside the `<form>` without changing the save
  payload. That one had none.
- **The split tool cannot write a target with the same name as its source.**
  Rename the source (`agents.html` → `agents-src.html`) and split that.
- **A Jinja conditional wrapping a card and its modals must be lifted out
  whole.** The inbound MCP block is `{% if mcp_ui_enabled %}` … `{% endif %}`
  spanning the card and three modals; it was extracted as one unit into its own
  pane rather than split.

### Tab-level conditions

The nav map now supports `condition` on a **tab**, not just a section, so a tab
whose entire pane is behind a feature flag disappears rather than rendering
empty. Both renderers honour it. Verified: 40 tabs with `mcp_ui_enabled`, 39
without.


### Two hardcoded-id traps found and closed

Both were latent breakage that only surfaced because a tab id changed:

- **`openKeyVaultSettings`** in `admin_data_management.js` switched tabs by the
  literal id `security-tab`. It was dead weight anyway — the link now carries
  `data-admin-link` and `admin_card_links.js` resolves the tab from the DOM.
- **The landing pane** was `show active` hardcoded in one pane's markup and
  `showAdminTab('general')` hardcoded in the sidebar script. Splitting that
  pane left Admin Settings with **no active pane at all**. Every pane now
  renders `{% if admin_landing_tab == '<id>' %} show active{% endif %}`, fed by
  `get_landing_tab_id()`, and the sidebar reads the first rendered tab.

**Assert durable properties, not current ids.** Four test files hardcoded
`general` or `security` and had to be rewritten to assert what actually matters
— Latest Features is last, exactly one pane is active, every tab renders one
pane. Any new test that names a tab id will need the same treatment next time.


### The cross-pane move tool

`move_card.py` moves a top-level card from one pane to another with the same
every-line-accounted-for guarantee as the split tool. Two behaviours matter:

- **Nested cards travel with their parent automatically**, because the card
  scanner skips over card bodies. `conversation-contents-drawer-section` moved
  inside `chat-file-uploads-section` without being named.
- **The gap after a card travels with it**, which is what correctly routes an
  interleaved modal to the tab that owns its trigger.

### Complications, all now resolved

- **I1** Modals are interleaved *between* cards, not collected at the end. Each
  modal moves with the tab that owns its trigger. Where a modal is shared by
  cards that end up in different tabs, it goes to the shell instead.
- **I2** Some cards are nested inside other cards and move with their parents:
  `conversation-contents-drawer-section` (inside chat file uploads),
  `content-understanding-section` and `office-embedded-image-section` (inside
  document intelligence). The card scanner skips card bodies, so this is
  automatic.
- **I4** The Data Management migration workflow is one `<section>` of non-card
  markup. It was split last and on its own, driven from explicit line ranges.

## Stage E — complete

- `system-settings-section` split to four destinations, no renames.
- Access & Roles roster mirroring the ten `require_member_of_*` toggles, built
  from the page rather than a list. Mirrors carry **no `name` attribute**.

---

## Decisions already locked

| | Decision |
|---|---|
| D1 | Split `system-settings-section` across Chat / Security / Workspaces |
| D2 | Workflow becomes its own group |
| D3 | Mirror role toggles rather than move them |
| D4 | Legacy hash redirect map |
| D5 | Per-tab partials |
| Q2 | File Sync warns rather than blocks; hard-disable elsewhere |
| — | Land each stage as its own PR into the staging branch |

## Target structure — 14 groups

`Appearance · Chat · AI Models · Agents & Actions · Workspaces · Workflow ·
Knowledge · Security · Governance · Data Lifecycle · Backup & Recovery · Scale ·
Operations · Help`

Full card-by-card placement is in the PR description of #1304 and in the
stage 2 plan. Key rationale: grouping follows *capability weight*, not card
titles — Governance has 196 KB of backing JS so it cannot be a Security
sub-tab; Video and audio are extraction pipelines, not chat features; Retention
is data lifecycle, not a workspace toggle.

---

## Before the final merge to Development

Revert the CI branch filters added in #1297. Six workflows list
`feature/admin-settings-ia` in their `pull_request` branch filters so staged
PRs are gated; `Development` should end up with its original configuration.

Files: `codeql.yml`, `xss-sink-check.yml`, `broken-access-control-check.yml`,
`malicious-pr-security-review.yml`, `python-syntax-check.yml`,
`swagger-route-check.yml`.
