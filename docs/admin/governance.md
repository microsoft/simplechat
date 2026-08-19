---
layout: page
title: "Governance Settings"
description: "Controls governance review for personal, group, and global endpoints, agents, actions, and MCP destinations."
section: "Administration"
audience: admin
admin_tab: governance
---

## What this tab controls

Controls governance review for personal, group, and global endpoints, agents, actions, and MCP destinations.

## Why it matters

Governance settings decide when user, group, and global endpoints, agents, and actions need administrative review before use. MCP destination governance adds network safety controls for tool calls. The tradeoff is speed versus control: stricter governance slows rollout but prevents unreviewed tools and endpoints from becoming production dependencies.

{% include media.html src="admin/governance-overview.png" alt="Screenshot of the Governance settings tab showing governance tab." title="Governance tab" capture="Capture the Governance tab for Governance tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Governance settings walkthrough" poster="video-posters/admin-governance.png" capture="Recording planned. Walk through every setting on the Governance tab and explain when to change each one." %}

## Settings

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
| Enforce MCP Destination Allowlist | Makes enforce mcp destination allowlist available in the product when its required service and access policy are configured. | Off | `enable_mcp_destination_governance`; capability toggle |
| Block Private/Local Literal IP Destinations | Controls how SimpleChat uses block private/local literal ip destinations on this tab. | Off | `mcp_block_unsafe_destinations` |
| Search | Controls how SimpleChat uses search on this tab. | N/A (runtime control) | Runtime UI control |
| Entity Type | Controls how SimpleChat uses entity type on this tab. | Not specified in defaults | Runtime UI control |
| Page Size | Controls how SimpleChat uses page size on this tab. | Not specified in defaults | Runtime UI control |

### MCP destination governance

Destination governance evaluates MCP action targets before tools connect. The private/local literal IP block is a safety backstop for unsafe destinations and should remain enabled unless there is a reviewed exception path.

## Before you change anything

- Decide which surfaces need review: personal, group, global endpoints, agents, and actions.
- Define MCP destination and source policies before enabling enforcement.
- Tell workspace owners what changes when governance begins blocking unapproved items.

## Common tasks

1. **Enable governance for a surface.**
    1. Enable the relevant personal, group, or global endpoint, agent, or action governance toggle.
    2. Save settings.
    3. Create or modify an item in that surface.
    4. Review the item in the governed-item list.
    Outcome to verify: The selected surface requires administrative review.

{% include media.html src="admin/governance-enable-governance-for-a-surface.png" alt="Screenshot of the Governance settings tab showing enable governance for a surface." title="Governance: Enable governance for a surface" capture="Capture the Governance tab while performing Enable governance for a surface. Show the relevant controls and redact secrets." %}

2. **Enforce MCP destination policy.**
    1. Enable **Enforce MCP Destination Allowlist**.
    2. Leave **Block Private/Local Literal IP Destinations** on unless an approved exception exists.
    3. Review destination entries through governance.
    4. Test an allowed and blocked destination.
    Outcome to verify: MCP actions can reach only approved destinations.

{% include media.html src="admin/governance-enforce-mcp-destination-policy.png" alt="Screenshot of the Governance settings tab showing enforce mcp destination policy." title="Governance: Enforce MCP destination policy" capture="Capture the Governance tab while performing Enforce MCP destination policy. Show the relevant controls and redact secrets." %}

3. **Review governed items.**
    1. Use **Search**, **Entity Type**, and **Page Size**.
    2. Open the item requiring review.
    3. Approve or reject according to local policy.
    4. Notify the owner if changes are required.
    Outcome to verify: Pending governed items move to the correct state.

{% include media.html src="admin/governance-review-governed-items.png" alt="Screenshot of the Governance settings tab showing review governed items." title="Governance: Review governed items" capture="Capture the Governance tab while performing Review governed items. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| MCP destinations are blocked | Destination governance or private/local literal IP blocking is enabled. | Approve the destination or keep unsafe IPs blocked by policy. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Agents]({{ '/admin/agents/' | relative_url }})
- [File Sync]({{ '/admin/file-sync/' | relative_url }})
- [Security]({{ '/admin/security/' | relative_url }})
