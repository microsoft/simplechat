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

**Implemented in version:** 0.261.074

**Updated for version:** 0.261.093 (`application/single_app/config.py`).

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
| `settings_path` | Reads and writes a value stored inside a nested object. `document_action_capabilities` holds six values across two action types, and nothing reads a flattened form of them. |
| `readonly` + `managed_by` | Reports a value another surface owns, and names where it is set. |
| `depends_on` naming a `flag` | Gates a field on a server-resolved runtime flag rather than a settings key, for a capability gated outside the settings document. |
| `entry_list` | A repeatable `{value, description}` allowlist. |

`iter_dependencies(field)` yields each condition regardless of which shape was
declared, so no caller re-derives it.

### Nested settings values

A field with a `settings_path` keeps its flat `key` for the draft, the PATCH
payload and field errors, and names the path its value really occupies.

On save, `_apply_nested_paths` removes those flat keys from the normalized
payload and rebuilds each container from the stored object, so editing one limit
does not discard the other five. The assembled container is then handed to
`_CONTAINER_NORMALIZERS`, which delegates to
`normalize_document_action_capabilities` — the same function the server-rendered
form uses, so both surfaces clamp to `DOCUMENT_ACTION_LIMIT_BOUNDS` identically.

In the browser, `readFieldValue` walks the path for the saved value while still
preferring a draft entry keyed by the flat name. A gate can itself be nested —
the limits are gated by an `enabled` flag in the same container — so
`isFieldVisible` takes a field index built by `buildFieldIndex` rather than
looking the gate up by key alone.

### Read-only mirrors

Two actions change what an agent can do but are not set from the Actions tab:

| Key | Owner | Why it is mirrored |
|---|---|---|
| `enable_fact_memory_plugin` | Chat › Chat Experience › Fact Memory | A chat capability that also gives agents a memory action |
| `enable_tabular_processing_plugin` | Derived from `enable_enhanced_citations` | Recomputed on every settings read, so it can never be set directly |

A mirror renders its state and its owner instead of a control, and the server
refuses a write to it. Because fact memory is declared twice — editable under
Chat, mirrored under Actions — `get_field_definition` returns the writable
declaration regardless of order, so mirroring a key never removes the control
that actually sets it.

Before this, `enable_tabular_processing_plugin` was rendered by the fallback scan
as a live switch under Chat › Processing Thoughts, purely because "processing"
matched that section id. Flipping it did nothing.

### Runtime-flag gates and derived keys

Inbound MCP is gated by `ENABLE_MCP_UI`, an App Service application setting. It
has no entry in the settings document, so a `depends_on` may name a `flag`
instead of a `key`; the flag is answered from `runtime_flags` and cannot be
changed from the page at all. The section itself stays unconditional so the
`inbound-mcp-disabled-notice` component can explain how to turn the gate on —
that notice is simply the one field gated on the flag being *false*.

The inbound MCP settings are also the first where one edit has to produce several
stored keys. The runtime does not read the `*_entries` lists an administrator
edits; it reads `*_ids` lists, and single-role settings are mirrored into
`*_roles` arrays. `_apply_inbound_mcp_derivations` reproduces the block the
server-rendered form runs on save, reusing
`normalize_inbound_mcp_value_entries`, `inbound_mcp_entry_values`,
`ensure_inbound_mcp_default_tenant_entry` and
`normalize_inbound_mcp_single_value` rather than restating the rules, because
those rules are not a straight mapping:

- the tenant id list only reflects the entries while additional tenants are
  allowed, and always includes the deployment's own tenant. Restricting tenants
  changes the id list and keeps the entries, so a partner tenant survives the
  switch being turned off and on again;
- the source id list collapses to `["*"]` when all sources are allowed, and the
  wildcard row is stripped when they are not — otherwise a controlled list would
  keep accepting every source while the screen showed a restriction.

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
  "version": "0.261.074"
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
| `functional_tests/test_v2_admin_actions_parity.py` | Every V1 field name in the Actions pane is claimed; document action paths, bounds and defaults match the application; the container is rebuilt without losing siblings; mirrors name their owner and the derived one refuses writes |
| `functional_tests/test_v2_admin_inbound_mcp_parity.py` | Every V1 field name in the Inbound MCP pane is claimed; every setting is gated on the runtime flag and the notice covers the disabled state; the derivations are executed against the real helpers, loaded through `stubbed_config` |
| `functional_tests/test_v2_admin_agents_logic.mjs` | Executes group layout, dependency chains, string and flag dependencies, section conditions, nested value reads, field-index ownership, allowlist normalization, orchestration visibility, and promotion normalization |
| `functional_tests/test_v2_admin_settings_schema.py` | Field shape, defaults matching the application, key ownership, dependency references including string comparisons and runtime flags |
| `functional_tests/test_v2_admin_field_renderer_coverage.py` | Every field type and every named component has a renderer branch |

## Known limitations

- General global agent and connector authoring remains in the classic interface.
  From version **0.261.093**, focused V2 controls can create/edit **Call agent**
  actions and attach them to existing global agents. These are resource updates
  through the agent/action APIs, not fields in the settings draft. See
  [Agent delegation actions](AGENT_DELEGATION_ACTION.md).
- `functions_document_actions` reaches `config.py` and a live Cosmos client, so
  its normalizer is imported lazily and cannot be exercised in a test process.
  The tests read its bounds from source and pin the delegation instead.
  `functions_mcp_server_config` needs only five constants from `config`, so its
  real behaviour is exercised through `stubbed_config`.
- The V1 sidebar cannot render a section whose `condition` is not one of the two
  names hard-coded in its template, so the two Workspace Mode sections do not
  appear as sidebar links there. The V1 cards themselves are unaffected, and V2
  honours the condition correctly.

## Related

- `docs/admin/agents-actions.md` — administrator-facing reference
- `docs/explanation/features/ADMIN_SETTINGS_IA_REWORK_STATUS.md` — the wider rework
