# V2 Admin Settings: Agents & Actions

## Overview

The V2 React admin surface renders its controls from a server-declared field
schema. Groups with no entry in that schema fall back to scanning the settings
document for `enable_*` booleans and matching each key to a navigation section by
shared word stems.

Agents and actions are not configured with booleans, so that fallback produced an
almost empty tab. This feature declares the Agents & Actions group properly, and
adds the small number of schema and renderer capabilities the group needs that
the Appearance group never exercised.

**Implemented in version:** 0.261.059 (phase 1 of 5)

**Dependencies:** `admin_settings_fields.py`, `admin_settings_nav.py`,
`route_backend_v2.py`, `application/v2_ui`.

## What the fallback produced

Tracing `buildCapabilityIndex` against `ADMIN_NAV` and the settings defaults, the
V2 Agents & Actions group rendered:

| Navigation section | Rendered |
|---|---|
| `agents-config` | nothing; the section was skipped |
| `agent-template-approvals-section` | `enable_agent_template_gallery` |
| `document-action-capabilities-card` | nothing; the section was skipped |
| `actions-config` | `enable_text_plugin` |
| `inbound-mcp-configuration` | `enable_inbound_mcp_server`, `enable_inbound_mcp_rate_limits` |
| "Other capabilities" | `enable_semantic_kernel` and four `enable_*_plugin` keys |
| Chat › Processing Thoughts | `enable_tabular_processing_plugin`, misfiled by stem match |

Everything else in the group — `per_user_semantic_kernel`, the six `allow_*` and
`merge_*` toggles, `orchestration_type`, `max_rounds_per_agent`, the eleven
`agents_page_*` keys, `document_action_capabilities`, and nineteen
`inbound_mcp_*` keys — was invisible, because the fallback only scans `enable_*`
booleans.

## Technical specifications

### Navigation

`ADMIN_NAV` now names the nested cards the V1 panes already carry, so the V2
surface can render one section per concern without any change to the
server-rendered page. Every id below already exists in `templates/admin/_panes/`.

| Tab | Section id | Label | Condition |
|---|---|---|---|
| Agents | `agents-config` | Agent Runtime | — |
| Agents | `agent-toggles-card` | Workspace Agent Permissions | `per_user_semantic_kernel` |
| Agents | `agents-page-customization-card` | Agents Page | — |
| Agents | `agent-template-approvals-section` | Agent Template Approvals | `enable_agent_template_gallery` |
| Actions | `document-action-capabilities-card` | Document Actions | — |
| Actions | `plugin-feature-toggles` | Workspace Action Permissions | `per_user_semantic_kernel` |
| Actions | `core-plugin-toggles` | Built-in Actions | — |
| Actions | `actions-config` | Global Actions | — |

`agents-config` and `actions-config` resolve to the V1 card ids
`agents-configuration` and `actions-configuration` through the existing
`sectionMap` alias in `admin_sidebar_nav.js`.

### Schema additions

| Property | Purpose |
|---|---|
| `depends_on` as a list | A chain of conditions that must all hold. Agents → Workspace Mode → merge behaviour is three links, and judging one link alone puts a control back on screen while an intermediate gate is off. |
| `equals` as a string | Compares against a select value rather than a boolean, so the Agents page hides its gradient colour outside two-tone mode. |
| `group` | A sub-heading collecting related fields inside one section. |
| `collapsed` | Starts a group closed. Only the first field of a group decides this. |

`iter_dependencies(field)` yields each condition regardless of which shape was
declared, so no caller re-derives it.

### Section conditions

`ADMIN_NAV` has always supported a section `condition`, and the server-rendered
sidebar evaluates it. V2 ignored it. `isSectionVisible` now resolves a condition
against, in order:

1. `runtime_flags` from the settings API — currently `mcp_ui_enabled`, which
   comes from an App Service application setting and is never stored in the
   settings document;
2. the unsaved draft, so a section appears the moment its gate is switched
   rather than only after a save;
3. the stored settings.

A section whose declared fields are all hidden by their own dependencies is
dropped too, so no empty titled panel is left behind.

### API

`GET /api/v2/admin/settings` gained a `runtime_flags` object:

```json
{
  "settings": { },
  "admin_nav": [],
  "field_schema": { },
  "branding_assets": { },
  "runtime_flags": { "mcp_ui_enabled": false },
  "version": "0.261.059"
}
```

### Normalization

`normalize_admin_settings_updates` now consults `_DELEGATED_NORMALIZERS` before
looking up a field definition. Previously a key with no declared field passed
straight through unvalidated, which would have applied to
`agents_page_promoted_popular_agents`: it is edited by a component rather than a
typed field, so it has no type-driven normalization of its own. It is now
normalized by `normalize_agents_page_promoted_popular_agents`, the same function
the server-rendered form uses.

### Components

**`agent-orchestration`** reads `GET /api/orchestration_types` and
`GET /api/orchestration_settings`, and saves through
`POST /api/orchestration_settings` rather than the settings PATCH, because that
endpoint also derives `enable_multi_agent_orchestration` from the chosen mode and
forces `max_rounds_per_agent` back to 1 outside multi-agent modes.

It renders nothing while fewer than two types are offered.
`get_agent_orchestration_types()` currently returns one entry, `default_agent`;
`group_chat` and `magnetic` are inside a string literal in
`semantic_kernel_loader.py` and are not built. The card therefore stays hidden,
and reappears by itself if those modes return.

**`promoted-popular-agents`** loads candidates from
`GET /api/agents/catalog?include_usage=true` and writes
`agents_page_promoted_popular_agents` into the page draft. It produces entries of
exactly the shape the server keeps — `catalog_key`, `display_name`,
`scope_label`, `scope_type`, `window` — and never offers an agent that is already
promoted, because the server drops duplicate catalog keys on save.

## Usage

Admin Settings → Agents & Actions → Agents in the V2 interface (`/v2`).

The dependency chain an administrator now sees:

```
Enable Agents  (enable_semantic_kernel, default off)
├─ Workspace Mode  (per_user_semantic_kernel)
│   ├─ Add Global Agents and Actions to Workspaces
│   └─ Workspace Agent Permissions section
│       ├─ Allow Personal / Group Agents
│       ├─ Allow Personal / Group Custom Endpoints
│       └─ Enable Agent Template Gallery
│            └─ Agent Template Approvals section
├─ Agents Page section  (hero, guidance, promotions)
└─ Agent Orchestration  (hidden: one mode available)
```

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_v2_admin_agents_parity.py` | Every V1 field name in the Agents pane is claimed by the schema; the gate chain is declared; conditional sections name their gate; tracks which panes remain undeclared |
| `functional_tests/test_v2_admin_agents_logic.mjs` | Executes group layout, dependency chains, string dependencies, section conditions, orchestration visibility, and promotion normalization |
| `functional_tests/test_v2_admin_settings_schema.py` | Field shape, defaults matching the application, dependency references including string comparisons |
| `functional_tests/test_v2_admin_field_renderer_coverage.py` | Both new components have a renderer branch |

## Known limitations

- The Actions and Inbound MCP tabs still use the `enable_*` fallback. Phases 2
  and 3 declare them; `PANES_PENDING_DECLARATION` in the parity test tracks this.
- Global agent and global action authoring stays in the classic interface until
  phases 4 and 5.
- The V1 sidebar cannot render a section whose `condition` is not one of the two
  names hard-coded in its template, so the two Workspace Mode sections do not
  appear as sidebar links there. The V1 cards themselves are unaffected, and V2
  honours the condition correctly.

## Related

- `docs/admin/agents-actions.md` — administrator-facing reference
- `docs/explanation/features/ADMIN_SETTINGS_IA_REWORK_STATUS.md` — the wider rework
