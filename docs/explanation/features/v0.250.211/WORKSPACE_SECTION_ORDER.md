# Workspace Section Order

## Overview

Workspace sections now render in a single canonical order of operations across every surface
that lists them. Previously each surface used its own ordering, which made it hard for users and
admins to see how the pieces relate — that Identities feed both Sync and Actions, that Actions
belong to Agents, and that Workflows consume Agents.

- **Version implemented:** 0.250.211
- **Related issue:** [#1255](https://github.com/microsoft/simplechat/issues/1255)
- **Dependencies:** none — this change is presentation-only and adds no new settings

## Canonical order

Sections still appear only when their existing feature gates are enabled. When a section is
enabled it always appears in this position relative to the others:

| # | Section | Why it sits here |
|---|---------|------------------|
| 1 | **Documents** | The knowledge you bring into the workspace |
| 2 | **Prompts** | The instructions you reuse against that knowledge |
| 3 | **Identities** | The credentials both Sync and Actions resolve against |
| 4 | **Sync** | Uses Identities to pull Documents in automatically |
| 5 | **Endpoints** | The models that Actions, Agents, and Workflows run on |
| 6 | **Actions** | Governed tools, built on Identities and Endpoints |
| 7 | **Agents** | Assemble Documents, Prompts, Actions, and Endpoints |
| 8 | **Workflows** | Run Agents manually, on a schedule, or on a trigger |

Each entry depends on the ones above it, so reading the tab strip left to right now describes how
a workspace is actually built up.

## Architecture

### Surfaces kept in sync

Three separate surfaces list workspace sections, and all three now use the canonical order:

| Surface | Personal | Group |
|---------|----------|-------|
| Top `nav-tabs` bar | `#workspaceTab` in `templates/workspace.html` | `#groupWorkspaceTab` in `templates/group_workspaces.html` |
| Collapsed/mobile **Section** dropdown | `#workspace-section-select` | `#group-workspace-section-select` |
| Left-hand sidebar submenu | `#personal-workspace-submenu` in `templates/_sidebar_nav.html` | `#group-workspace-submenu` in `templates/_sidebar_nav.html` |

`static/js/workspace_section_switcher.js` maps the dropdown's option values onto tab button ids,
so the dropdown and the tab strip must be edited together — the switcher does not derive one from
the other.

### Public workspaces

Public workspaces already satisfied the canonical relative order and were left unchanged:

- `templates/public_workspaces.html` lists **Documents** then **Prompts**.
- `templates/manage_public_workspace.html` lists **Identities** before **Sync** among its
  management tabs (General, Membership, Stats, Identities, Sync, Settings).

### Tab panes are deliberately not reordered

Bootstrap resolves tab panes by `id` / `data-bs-target`, and inactive panes are hidden, so pane
DOM order has no visual or accessibility effect. Panes were left in place to keep the change
reviewable — `group_workspaces.html` alone is roughly 389 KB.

### Gate restructuring

Moving Actions ahead of Agents, and Endpoints ahead of both, required unwinding nested Jinja
conditionals without changing their effective conditions. For example, the personal workspace
Actions tab was nested inside the Agents gate:

```jinja
{% if settings.per_user_semantic_kernel and settings.enable_semantic_kernel %}
  {% if settings.allow_user_agents %}
    {% if settings.allow_user_plugins %}
      {# Actions #}
    {% endif %}
    {# Agents #}
  {% endif %}
{% endif %}
```

Actions still requires `per_user_semantic_kernel`, `enable_semantic_kernel`, `allow_user_agents`,
and `allow_user_plugins` — only its render position changed.

## Navigation gating fixes

The sidebar previously used gates that did not match the tabs they linked to, so a sidebar link
could point at a tab that was never rendered. Those gates are now aligned:

| Navigation item | Previous gate | Corrected gate |
|-----------------|---------------|----------------|
| Personal → Your Agents | `per_user_semantic_kernel and enable_semantic_kernel` | added `allow_user_agents` |
| Personal → Your Actions | `per_user_semantic_kernel and enable_semantic_kernel` | added `allow_user_agents and allow_user_plugins` |
| Personal → Identities | `file_sync_enabled or enable_semantic_kernel or enable_multi_model_endpoints` | `file_sync_enabled or enable_semantic_kernel` |
| Group → Group Agents | `allow_group_agents and enable_semantic_kernel` | added `per_user_semantic_kernel` |
| Group → Group Actions | `allow_group_agents and enable_semantic_kernel` | added `per_user_semantic_kernel and allow_group_plugins` |
| Group → Identities | `file_sync_enabled or enable_semantic_kernel or enable_multi_model_endpoints` | `file_sync_enabled or enable_semantic_kernel` |
| Group → Group Workflows | *link did not exist* | added, gated by `allow_group_workflows` |

The group sidebar had no Workflows entry at all even though the group Workflows tab has shipped
for some time, so group workflows were unreachable from the left-hand navigation.

## Configuration

No new configuration. The sections that appear continue to be controlled by the existing settings:

| Section | Personal gate | Group gate |
|---------|---------------|------------|
| Documents | always | always |
| Prompts | always | always |
| Identities | `enable_file_sync*` or `enable_semantic_kernel` | `enable_file_sync*` or `enable_semantic_kernel` |
| Sync | `enable_file_sync*` | `enable_file_sync*` |
| Endpoints | `allow_user_custom_endpoints` + `enable_multi_model_endpoints` | `per_user_semantic_kernel` + `enable_semantic_kernel` + `allow_group_custom_endpoints` + `enable_multi_model_endpoints` |
| Actions | `per_user_semantic_kernel` + `enable_semantic_kernel` + `allow_user_agents` + `allow_user_plugins` | `per_user_semantic_kernel` + `enable_semantic_kernel` + `allow_group_agents` + `allow_group_plugins` |
| Agents | `per_user_semantic_kernel` + `enable_semantic_kernel` + `allow_user_agents` | `per_user_semantic_kernel` + `enable_semantic_kernel` + `allow_group_agents` |
| Workflows | `allow_user_workflows` | `allow_group_workflows` |

`enable_file_sync*` is the resolved per-scope File Sync availability computed by
`is_file_sync_enabled_for_user` / `is_file_sync_enabled_for_group`.

## File structure

| File | Change |
|------|--------|
| `application/single_app/templates/workspace.html` | Reordered `#workspaceTab` and `#workspace-section-select` |
| `application/single_app/templates/group_workspaces.html` | Reordered `#groupWorkspaceTab` and `#group-workspace-section-select` |
| `application/single_app/templates/_sidebar_nav.html` | Reordered both submenus, added the group Workflows link, aligned gates, refreshed parent tooltips |
| `application/single_app/config.py` | `VERSION` bumped to `0.250.211` |
| `functional_tests/test_workspace_section_order.py` | New coverage for the canonical order and gating parity |
| `functional_tests/test_endpoints_tab_order_visibility.py` | Updated for the new Endpoints → Actions → Agents order |

## Usage

Nothing to enable. Users see the new order the next time they open a workspace page. Sections that
an admin has disabled remain hidden, and the remaining sections close up while preserving their
relative positions.

## Testing and validation

`functional_tests/test_workspace_section_order.py` renders each of the six section lists in
isolation with Jinja and checks:

1. **Canonical order when everything is enabled** — all six surfaces render exactly the eight
   sections in the canonical order.
2. **Disabled features only remove sections** — every combination of the eight relevant feature
   flags (256 per scope) still yields a subsequence of the canonical order, with no duplicates and
   with Documents and Prompts always leading.
3. **Gating lockstep** — for every flag combination, the tab strip, the Section dropdown, and the
   sidebar submenu expose an identical set of sections. This is what guards the navigation gating
   fixes above.
4. **Permission markers survive** — the permission-aware group Identities markers
   (`data-group-identities-tab-nav`, `data-group-identities-sidebar-nav`,
   `data-group-identities-section-option`) are still present after the reordering.
5. **Public workspaces** — Documents precedes Prompts, and Identities precedes Sync on the manage
   page.

The test was verified against the pre-change templates and fails there, confirming it is not
vacuous.

### Known limitations

- Tab pane DOM order still reflects the historical ordering. This is intentional and has no user
  impact, but it means pane order and tab order no longer visually correspond when reading the
  template source.
- The personal workspace guided tutorial (`static/js/workspace/workspace-tutorial.js`) still walks
  Documents → Prompts → Agents → Actions. Its selectors are id-based so it functions correctly,
  but its narrative sequence no longer mirrors the tab order.
- Section grouping (dividers or group labels such as Content / Connections / Automation) is a
  possible follow-up; this change establishes the ordering those groups would build on.

## Related documentation

- `docs/explanation/fixes/v0.241.001/ENDPOINTS_TAB_ORDER_VISIBILITY_FIX.md` — earlier work that
  introduced the endpoints tab gating this change reorders
- `docs/explanation/features/v0.229.001/LEFT_HAND_NAVIGATION_MENU.md` — the left-hand navigation
  this change keeps in sync with the tab strip
