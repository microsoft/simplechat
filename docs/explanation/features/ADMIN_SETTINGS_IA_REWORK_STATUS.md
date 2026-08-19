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

Current version: **0.260.014**. Fingerprint: **462 field names / 110 card ids**.
Navigation: **14 groups / 36 tabs / 88 sections**.

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

## Next: Stage D — the risky one, in progress

Re-home cards into the target groups, **one group per commit**, running the
field contract test on each.

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
`legacyModelSettingsModal` in the AI Models pane. Splitting AI Models means
moving a modal, not a card, which is why AI Models and Agents are deliberately
left for their own change rather than bundled with Knowledge and Workspaces.


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

### Remaining

Three complications found while splitting:

- **I1** Modals are interleaved *between* cards, not collected at the end. Each
  modal moves with the tab that owns its trigger.
- **I2** Three cards are nested inside other cards and must move with their
  parents: `conversation-contents-drawer-section` (inside chat file uploads),
  `content-understanding-section` and `office-embedded-image-section` (inside
  document intelligence). All three land in the same target tab as their parent.
- **I4** The Data Management migration workflow is ~985 lines of non-card markup
  forming one unit. Split it across Backup/Migrate/Restore/Jobs **last and on
  its own**.

## Then Stage E

- Split `system-settings-section`: `max_file_size_mb` → Workspaces;
  `conversation_history_limit` and `default_system_prompt` → Chat; idle timeout
  fields → Security; `access_denied_message` → Security. **No renames.**
- Access and Roles roster mirroring the 10 `require_member_of_*` toggles, built
  on the Stage B proxy handling. Mirrors carry **no `name` attribute** — the
  field contract test enforces this.

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
