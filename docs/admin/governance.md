---
layout: page
title: "Governance settings"
description: "Governance controls review policy for personal, group, and global endpoints, agents, actions, and MCP destinations."
section: "Administration"
audience: admin
admin_tab: governance
---


# Governance settings

## What this group controls

Governance controls review policy for personal, group, and global endpoints, agents, actions, and MCP destinations.

## Why it matters

Governance decides how quickly new tools become usable and how much review happens first. Stronger policy slows rollout but prevents unreviewed endpoints and destinations from becoming dependencies.

{% include media.html src="admin/governance-overview.png" alt="Screenshot placeholder for the Governance group in Admin Settings." title="Governance settings" capture="Capture the Governance group in Admin Settings showing its tabs." %}

{% include media.html type="video" title="Governance settings walkthrough" poster="video-posters/admin-governance.png" capture="Recording planned. Walk through each tab in the Governance group and explain when to change each setting." %}

## Before you change anything

- Choose which item types require review for each scope.
- Define MCP destination and source policy before enforcing it.
- Tell workspace owners how rejected items are remediated.

## Feature Governance {#feature-governance}

### Governance Feature Toggles {#governance-feature-toggles-section}

The Governance Feature Toggles section belongs to the Feature Governance tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

No retired-page setting rows mapped directly to Feature Governance; use the live Admin Settings UI for the current rollout switches.

## Policies {#governance-policies}

### Feature Policies {#governance-feature-policies-section}

The Feature Policies section belongs to the Policies tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Delegated Item Policies {#governance-item-policies-section}

The Delegated Item Policies section belongs to the Policies tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Govern Personal Endpoints | Requires governance review for personal endpoints before those items are used broadly. | Off | `governance_user_endpoints` |
| Govern Personal Agents | Requires governance review for personal agents before those items are used broadly. | Off | `governance_user_agents` |
| Govern Personal Actions | Requires governance review for personal actions before those items are used broadly. | Off | `governance_user_actions` |
| Govern Group Endpoints | Requires governance review for group endpoints before those items are used broadly. | Off | `governance_group_endpoints` |
| Govern Group Agents | Requires governance review for group agents before those items are used broadly. | Off | `governance_group_agents` |
| Govern Group Actions | Requires governance review for group actions before those items are used broadly. | Off | `governance_group_actions` |
| Govern Global Endpoints | Requires governance review for global endpoints before those items are used broadly. | On | `governance_global_endpoints` |
| Govern Global Agents | Requires governance review for global agents before those items are used broadly. | Off | `governance_global_agents_usage` |
| Govern Global Actions | Requires governance review for global actions before those items are used broadly. | Off | `governance_global_actions_usage` |
| Search | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | Runtime UI control |
| Entity Type | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |
| Page Size | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |

## MCP Governance {#mcp-governance}

### MCP Action Destination Governance {#governance-mcp-destination-section}

Use destination governance to limit which remote MCP servers personal, group, and global actions may contact. Policies apply to saves, discovery, connection tests, and tool execution, not just to the server choices shown in the modal.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enforce MCP Destination Allowlist | Requires MCP destinations to satisfy the allowlist for the action's scope and the current caller. | Off | `enable_mcp_destination_governance`; environment enforcement cannot be disabled here. |
| Block Private/Local Literal IP Destinations | Rejects unsafe literal-IP targets, including loopback, private, and link-local addresses, before allowlist matching. | Off | `mcp_block_unsafe_destinations`; environment-required blocking cannot be disabled here. |

Starting in **0.261.029**, environment-enforced destination restrictions are a non-overridable minimum. Admin Settings may tighten them, but cannot widen an environment allowlist or turn off environment-required enforcement or unsafe-address blocking. The defaults above describe the settings, not an exemption from deployment environment restrictions.

Remote authorization uses a consistent MCP action type, the action's server-established collection/partition origin, the current user or established workflow identity, and current settings. Cached tools are checked again when used. A global action referenced by a personal or group agent still uses its global destination policy.

### Retired stdio action cleanup

Stdio and local process command, argument, and environment configuration are removed in **0.261.029** for all roles and scopes, including Admin/global. No governance toggle or Admin exemption restores them.

Existing stdio actions remain visible but cannot execute. Owners can inspect and explicitly delete their retired records even when MCP-usage governance denies execution; personal ownership, group-management permissions, and Admin boundaries remain in force. Explicit reconfiguration to a supported remote transport and valid endpoint must pass normal current governance.

Legacy records remain available for management without automatic conversion or deletion. Omitting a retired record from a bulk save does not delete it, and migration retains unsupported or failed records. See the [MCP action guide]({{ '/reference/actions/mcp/' | relative_url }}#retired-stdio-actions) for the owner workflow.

### Inbound MCP Source Governance {#governance-inbound-mcp-section}

The Inbound MCP Source Governance section belongs to the MCP Governance tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

## Common tasks

1. **Require review for a surface.** Enable the relevant governance toggle and create or edit a test item. Outcome to verify: The item requires administrative review.
2. **Enforce MCP destinations.** Review deployment environment restrictions, enable destination governance as needed, and test one allowed and one blocked remote target. Outcome to verify: MCP actions satisfy both the environment restrictions and current settings.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| An MCP call is blocked | Destination governance or private-address blocking rejected the target. | Review the action's scope, caller eligibility, environment restrictions, and current settings. Admin Settings cannot relax environment restrictions. |
| An old MCP action is unsupported even for an Admin | The action uses retired stdio configuration. | Explicitly configure a supported remote transport and endpoint, or delete it. Do not weaken destination governance to try to restore stdio. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Data Lifecycle settings]({{ '/admin/data-lifecycle/' | relative_url }})
- [Security settings]({{ '/admin/security/' | relative_url }})
