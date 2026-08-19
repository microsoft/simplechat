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
                                            ├── stage C          next
                                            ├── stage D
                                            └── stage E
                                                      └──► final PR ──► Development
```

Current version: **0.260.009**. Fingerprint: **462 field names / 110 card ids**.

### Shipped

| Stage | Content |
|---|---|
| 1 | Template split into 18 per-tab partials under `templates/admin/_panes/`; Latest Features moved last and General made the landing tab; Global Identities heading; File Sync sidebar submenu; `sectionMap` pruned 72 → 6; classification banner preview fixed; CodeQL XSS sink fixed |
| A | 12 cross-tab links converted from tab-coupled `switchTab` to `data-admin-link` card targets; two were already broken; `switchTab` removed |
| B | `data-requires` dependency announcements with inline mirror and link; File Sync and Permissions wired |
| — | Form field contract enforced in CI |

---

## Guardrails — these now live in the repo

The single most important rule: **never rename a `name=` attribute.** Admin
Settings posts one form and the backend reads by field name, so a rename
silently stops a setting from saving with no error anywhere.

| Check | How to run |
|---|---|
| **Field contract** | `python -m pytest functional_tests/test_admin_settings_field_contract.py` |
| Regenerate baseline *(only for a deliberate removal)* | `python functional_tests/test_admin_settings_field_contract.py --update-baseline` |
| Composition contract | `python -m pytest functional_tests/test_admin_settings_template_composition.py` |
| Card links | `python -m pytest functional_tests/test_admin_card_links.py` |
| Dependencies | `python -m pytest functional_tests/test_admin_settings_dependencies.py` |
| Sidebar parity | `python -m pytest functional_tests/test_admin_settings_sidebar_card_parity.py` |
| XSS | `python scripts/check_xss_sinks.py --full-file <changed files>` |

**Regression baseline:** the 75 functional test files that reference
`admin_settings.html` sit at **33 pre-existing failures**. That number must not
change. To reproduce the list:

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

## Next: Stage C

Add the group navigation level **against the current 18 tabs**, so grouping is
proven before any card moves.

1. Group row in the top-tab strip; collapsible group headers in
   `_sidebar_nav.html` with persisted state.
2. Three-level sidebar search (group → tab → card).
3. Legacy hash redirect map inside `showAdminTab`.

A server-side nav map is worth introducing here, since both navs need to render
the same group structure. Note it is **not** needed for link resolution —
`admin_card_links.js` resolves card → tab from the DOM via
`closest('.tab-pane')`, which is why links already survive any IA change.

## Then Stage D — the risky one

Re-home cards into the 14 groups, **one group per commit**, running the field
contract test on each. Three complications found while splitting:

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
