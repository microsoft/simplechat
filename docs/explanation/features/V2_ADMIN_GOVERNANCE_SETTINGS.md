# V2 Admin Governance Settings

## Overview

The V2 Admin Settings surface renders from `admin_settings_fields.py`, a machine-readable
description of every control. A section with no entry there falls back to guessing
switches from `enable_*` keys in the settings document.

Governance was entirely undescribed, so that fallback was the whole interface for it: one
switch labelled "Mcp destination governance", and nothing else. Feature policies,
delegated item policies, MCP destination policies, and inbound MCP source policies could
only be managed on the server-rendered page.

This work describes all five Governance sections, builds editors for the four kinds of
policy on the existing governance API, ties governance into the settings it qualifies, and
records V2 governance switch changes in the governance audit log.

**Implemented in version:** 0.261.273

**Dependencies:** the governance API in `route_backend_governance.py`, the policy store and
evaluation in `functions_governance.py`, MCP destination evaluation in
`functions_mcp_destinations.py`, inbound evaluation in
`functions_mcp_server_governance.py`, and section ids from `admin_settings_nav.py`.

## What was missing

| Section | V2 before | V2 after |
| --- | --- | --- |
| Governance Feature Toggles | Not rendered | Overview, nine switches paired by resource, prerequisite notices |
| Feature Policies | Not rendered | Every policy with its enforcement state, edited in place |
| Delegated Item Policies | Not rendered | Searchable, filtered, paged list with create, edit, move, duplicate, inverse, delete |
| MCP Action Destination Governance | One fallback switch | Two switches, deployment restrictions readout, destination policies, pattern builder |
| Inbound MCP Source Governance | Not rendered | Posture summary, warnings, source policies |

## Architecture

### Schema

Five sections are declared in `admin_settings_fields.py`, after the Security sections.

- `governance-feature-toggles-section` leads with the `governance-overview` component, then
  the switches ordered personal, group, personal, group so a wide card reads as pairs.
  Each switch whose feature can be off declares `requires` in `warn` mode with a
  `target_section`. `governance_global_endpoints` is `readonly` with `managed_by`, because
  the runtime always enforces it.
- `governance-feature-policies-section` and `governance-item-policies-section` are single
  components.
- `governance-mcp-destination-section` declares `enable_mcp_destination_governance` as the
  capability, `mcp_block_unsafe_destinations`, a `status` field reading the
  `mcp_destination_environment_policy` readout, and the destination policy component.
- `governance-inbound-mcp-section` is a single component.

A new optional field property, `related_settings`, lists governance settings that qualify a
field. `enable_semantic_kernel`, `allow_user_agents`, `allow_group_agents`,
`allow_user_custom_endpoints`, `allow_group_custom_endpoints`, `allow_user_plugins`, and
`allow_group_plugins` carry it, and the page shows each related switch's state with a link
to it.

### Fail-closed switches

The server-rendered save turns a governance switch off whenever the feature it governs is
off. V2 does not. The switch keeps its value, the `requires` notice says it is waiting and
links to the feature, the section status reads Prerequisite missing, and the feature
policy row shows "Waiting for *feature*". Checking starts when the feature is turned on.

Nothing about enforcement changes: `ensure_governance_access` only checks a switch that is
on, and the features themselves are still gated by their own settings.

### Audit

`_log_governance_setting_changes` in `route_backend_v2.py` runs after a successful settings
PATCH. When any key in `GOVERNANCE_AUDITED_SETTING_KEYS` changed, it writes one
`governance_feature_toggles_updated` entry with the before and after state of all eleven
keys, the same record the server-rendered save writes. A failed audit write is logged with
`[V2_ADMIN_SETTINGS]` and does not fail the save, which has already happened.

### API additions

All routes are on the governance blueprint and require `@login_required` and
`@admin_required`.

| Route | Change |
| --- | --- |
| `GET /api/admin/governance/item-policies/review` | `entity_type` accepts a comma-separated list; an unknown type returns 400 rather than every policy. `item_id` filters to one exact item. The response adds `entity_types` and `item_id`. |
| `GET /api/admin/governance/principal-groups` | New. `search=` finds group workspaces and public workspaces, up to 25 of each; `ids=` resolves up to 100 saved ids in order, omitting ids that no longer exist. Each row carries `kind`. |
| `GET /api/admin/governance/mcp-destination-catalog` | New. Preconfiguration ids with label, tier, scopes, and review needs; preset ids; and the remote transports. No endpoints are returned. |

The settings payload adds the `mcp_destination_environment_policy` status readout, built
from `describe_mcp_destination_environment_policy()`, which reports booleans and a pattern
count but never the patterns themselves.

Supporting helpers: `normalize_item_policy_entity_type_filter` and
`list_item_policies_for_entity_types` in `functions_governance.py`;
`find_public_workspaces_by_ids` and `list_public_workspaces_for_admin_directory` in
`functions_public_workspaces.py`; `build_mcp_preconfiguration_policy_catalog` in
`functions_mcp_preconfigurations.py`.

### Front end

| File | Role |
| --- | --- |
| `lib/governance.ts` | Policy types, normalization that mirrors `_normalize_policy_state`, save payloads, enforcement state, duplicate and inverse, MCP pattern parse, build, and check, and the principal directory cache |
| `stores/governanceStore.ts` | Which governance dialog is open, and a revision every policy list refetches on |
| `components/admin/governance/GovernanceOverview.tsx` | Two-layer summary and how a request is checked |
| `components/admin/governance/GovernanceFeaturePolicies.tsx` | Feature policy rows, enforcement badges, inline editor |
| `components/admin/governance/PrincipalListEditor.tsx` | Chips with resolved names, inline search, paste to merge or replace |
| `components/admin/governance/GovernanceItemPolicyManager.tsx` | The policy list used by every section and dialog |
| `components/admin/governance/GovernanceItemPolicyEditor.tsx` | Create, edit, or move one item policy |
| `components/admin/governance/McpDestinationPatternField.tsx` | Builds and checks a destination pattern |
| `components/admin/governance/GovernanceMcpSections.tsx` | The destination and inbound policy cards |
| `components/admin/governance/GovernanceDialogHost.tsx` | Renders the open editor or a resource's access list |
| `components/admin/governance/InboundMcpGovernanceShortcut.tsx` | Source policy status on the Inbound MCP card |
| `components/admin/governance/RelatedSettingsLinks.tsx` | Related governance under a feature switch |

Policies save through the governance API as soon as they are applied, separately from the
page's Save bar, because they are not stored in the settings document. Allow all is sent
with empty allow lists, because the server reads a non-empty list as a restricted policy.

An inline feature policy edit lives in its section, so changing category or searching it
out of view would discard it. While one has unsaved changes it reports that to the page,
which disables the category navigation and search and refuses navigation to another
category until the policy is saved or discarded.

Only one governance dialog is open at a time, because every open `AdminModal` closes on
Escape. An editor opened from a resource's access list hands back to that list when it
closes. A dialog closes only itself, by id, so a save that settles after its dialog was
replaced cannot close the replacement, and the editor ignores Escape, the backdrop, and its
close button while a save is in flight.

### Destination pattern checks

The server stores any string as a destination pattern, so a pattern that can never match
saves cleanly and then allows nothing. The editor refuses:

- `transport:streamable-http` and other hyphenated transports, which never match because
  transports are stored with an underscore;
- host patterns with a port or path, which never match because host patterns are compared
  to the host name only;
- URL patterns with a `*` before the end of the path, a query string, or a fragment;
- catalog ids outside `[a-z0-9][a-z0-9_-]{0,63}`.

## Tie-ins

| Where | What it adds |
| --- | --- |
| Agents & Actions: Agent Runtime, Workspace Agent Permissions, Workspace Action Permissions | The related governance switch's state and a Review link |
| Agents & Actions: Inbound MCP | Source policy count, Create a policy, Review in Governance |
| AI Models: AI Connections | Manage access on each connection, listing and creating that connection's policies |
| Governance requirement notices | Navigate within the page instead of opening the classic page |

## Usage

1. Open **Admin Settings > Governance**.
2. Prepare the audience under **Feature Policies** before turning a switch on.
3. Turn on the switch under **Governance Feature Toggles** and save.
4. Narrow specific resources under **Delegated Item Policies**, or from the resource
   itself, such as **Manage access** on an AI connection.
5. For MCP, write destination policies first, then turn on **Enforce MCP Destination
   Allowlist**.

The administrator guide is `docs/admin/governance.md`.

## Testing

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_admin_governance_parity.py` | Every V1 governance field is claimed; switches warn and are never coerced; global endpoint governance is read-only; V2 saves write the same audit entry as V1; review filters, the group directory, and the catalog route behave through the real blueprint; route guards; the hyphenated transport never matches on the server; the environment readout reports no patterns; related settings resolve; the inbound shortcut is flag-gated |
| `functional_tests/test_v2_admin_governance_logic.ts` | Normalization, save payloads, enforcement states checked against the schema's prerequisites, duplicate and inverse, pattern round-trips and checks, inbound sources, request building, principal resolution, and the dialog store |
| `ui_tests/test_v2_admin_governance_settings.py` | The group replaces the fallback switch; prerequisite and related links navigate; a feature policy saves without the Save bar; an unsaved feature policy edit locks navigation; item policy create, inverse, duplicate, delete; the destination builder refuses bad patterns and saves a group pattern; the inbound shortcut; AI connection access, including Escape during a save; narrow dark layouts |
| `functional_tests/test_v2_admin_section_logic.ts` | The governance switches keep their person, group, or everyone icons, and only icons are declared by hand |

## Known limitations

- The server-rendered page is unchanged. It still clears a governance switch whose
  feature is off, and its destination examples still suggest
  `transport:streamable-http`.
- A person whose profile cannot be read shows as Unresolved, because the profile endpoint
  answers 404 both for an unknown id and for a directory failure.
- Feature and item policies save immediately; they are not part of the page's draft, so
  Discard does not undo them.

## Related

- Feature: `docs/explanation/features/V2_ADMIN_SECURITY_SETTINGS.md`
- Feature: `docs/explanation/features/V2_ENHANCED_EXTRACTION_ADMIN_SECTION.md`, which made
  section cards honor runtime flags, so the flag-gated Inbound MCP governance shortcut renders
- Administrator guide: `docs/admin/governance.md`
