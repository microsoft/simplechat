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

The MCP Action Destination Governance section belongs to the MCP Governance tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Inbound MCP Source Governance {#governance-inbound-mcp-section}

The Inbound MCP Source Governance section belongs to the MCP Governance tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enforce MCP Destination Allowlist | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_mcp_destination_governance`; capability toggle |
| Block Private/Local Literal IP Destinations | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `mcp_block_unsafe_destinations` |

## Common tasks

1. **Require review for a surface.** Enable the relevant governance toggle and create or edit a test item. Outcome to verify: The item requires administrative review.
2. **Enforce MCP destinations.** Enable destination governance and test one allowed and one blocked target. Outcome to verify: MCP actions reach only approved destinations.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| An MCP call is blocked | Destination governance or private-address blocking rejected the target. | Approve the destination or keep it blocked by policy. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Data Lifecycle settings]({{ '/admin/data-lifecycle/' | relative_url }})
- [Security settings]({{ '/admin/security/' | relative_url }})
