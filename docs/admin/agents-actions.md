---
layout: page
title: "Agents & Actions settings"
description: "Agents & Actions controls the Semantic Kernel runtime, agent marketplace presentation, document actions, built-in actions, workspace permissions, orchestration, and inbound MCP."
section: "Administration"
audience: admin
admin_tab: agents-actions
redirect_from:
  - /admin/agents/
---


# Agents & Actions settings

## What this group controls

Agents & Actions controls the Semantic Kernel runtime, agent marketplace presentation, document actions, built-in actions, workspace permissions, orchestration, and inbound MCP.

## Why it matters

Agents and actions can call tools, inspect documents, and automate work. Expose only the actions and agent sources that fit your governance model, then verify permissions before users depend on them.

{% include media.html src="admin-settings/agents-actions.png" alt="Screenshot of the Agents & Actions group in Admin Settings." title="Agents & Actions settings" %}

{% include media.html type="video" title="Agents & Actions settings walkthrough" poster="video-posters/admin-agents-actions.png" capture="Recording planned. Walk through each tab in the Agents & Actions group and explain when to change each setting." %}

## Before you change anything

- Decide whether personal, group, or global agents are allowed.
- Confirm action dependencies before enabling a plugin.
- Configure App Service Authentication excluded paths before exposing inbound MCP.

## Agents {#agents}

### Agents Configuration {#agents-config}

The Agents Configuration section belongs to the Agents tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Agent Template Approvals {#agent-template-approvals-section}

The Agent Template Approvals section belongs to the Agents tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Hero Title | Provides displayed text that users see in the affected interface. | Find your next AI partner | `agents_page_title` |
| Hero Subtitle | Provides displayed text that users see in the affected interface. | Explore specialized agents built to accelerate how you work. | `agents_page_subtitle` |
| Hero Color Mode | Defines behavior for the related admin workflow; verify the affected feature after saving. | single | `agents_page_hero_color_mode` |
| Primary Color | Defines behavior for the related admin workflow; verify the affected feature after saving. | #0f172a | `agents_page_hero_primary_color` |
| Secondary Color | Defines behavior for the related admin workflow; verify the affected feature after saving. | #1e293b | `agents_page_hero_secondary_color` |
| Disclaimer / Guidance Text (Markdown supported) | Shown below the Agents page hero. Use this for contact details, request guidance, or governance reminders. | Empty | `agents_page_disclaimer_markdown` |
| Show agent instructions in Agents page details | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `agents_page_show_instructions_in_details` |
| Agents Page Promoted Popular Agents Json | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `agents_page_promoted_popular_agents_json` |
| Placement | Defines behavior for the related admin workflow; verify the affected feature after saving. | before | `agents_page_promoted_popular_order` |
| Promoted Tag Label | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `agents_page_promoted_popular_tag_label` |
| Show promoted tag | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `agents_page_promoted_popular_tag_enabled` |
| Add Agent | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |
| Enable Agents | Enables the agent and action runtime so users can work with configured agents instead of only the base chat experience. | Off | `enable_semantic_kernel`; capability toggle |
| Workspace Mode (workspace-specific agents/plugins and disables global configuration) | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `per_user_semantic_kernel` |
| Allow User Agents | Permits user agents when the related workspace or agent feature is enabled. | Off | `allow_user_agents` |
| Allow Group Agents | Permits group agents when the related workspace or agent feature is enabled. | Off | `allow_group_agents` |
| Allow User Custom Endpoints | Permits user custom endpoints when the related workspace or agent feature is enabled. | Off | `allow_user_custom_endpoints` |
| Allow Group Custom Endpoints | Permits group custom endpoints when the related workspace or agent feature is enabled. | Off | `allow_group_custom_endpoints` |
| Merge Global Agents/Plugins into Workspace | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `merge_global_semantic_kernel_with_workspace` |
| Enable Agent Template Gallery | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_agent_template_gallery`; capability toggle |
| Orchestration Type | Defines behavior for the related admin workflow; verify the affected feature after saving. | default_agent | `orchestration_type` |
| Multi-agent orchestration | Derived from **Orchestration Type**; enables group-chat orchestration paths when the selected orchestration mode is multi-agent, so the runtime can coordinate multiple configured agents instead of routing to a single default agent. | Off | `enable_multi_agent_orchestration`; saved by orchestration settings API |
| Max Rounds Per Agent (Group Chat) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 1 | `max_rounds_per_agent` |
| Selected Agent: | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |
| Allow User Template Submissions | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `agent_templates_allow_user_submission` |
| Require Admin Approval | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `agent_templates_require_approval` |
| Enable tool throttles | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_inbound_mcp_rate_limits`; capability toggle |
| Value | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |
| Description | Use descriptions to explain who owns this app, tenant, or source value without making the value easy to guess. | Not specified in defaults | Runtime UI control |
| I have added the required App Service Authentication excluded paths for this SimpleChat App Service. | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |

## Actions {#actions}

### Document Action Capabilities {#document-action-capabilities-card}

The Document Action Capabilities section belongs to the Actions tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Actions Configuration {#actions-config}

The Actions Configuration section belongs to the Actions tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Analyze | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `document_action_analyze_enabled` |
| Document Action Analyze Chat Max Documents Range | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 3 | `document_action_analyze_chat_max_documents_range` |
| Chat max documents | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 3 | `document_action_analyze_chat_max_documents` |
| Document Action Analyze Workflow Max Documents Range | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 10 | `document_action_analyze_workflow_max_documents_range` |
| Workflow max documents | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 10 | `document_action_analyze_workflow_max_documents` |
| Enable Document Comparison | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `document_action_comparison_enabled` |
| Document Action Comparison Chat Max Documents Range | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 3 | `document_action_comparison_chat_max_documents_range` |
| Chat max documents | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 3 | `document_action_comparison_chat_max_documents` |
| Document Action Comparison Workflow Max Documents Range | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 10 | `document_action_comparison_workflow_max_documents_range` |
| Workflow max documents | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 10 | `document_action_comparison_workflow_max_documents` |
| Allow Personal Actions | Permits personal actions when the related workspace or agent feature is enabled. | Off | `allow_user_plugins` |
| Allow Group Actions | Permits group actions when the related workspace or agent feature is enabled. | Off | `allow_group_plugins` |
| Enable Time Action | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_time_plugin`; capability toggle |
| Enable HTTP Action | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_http_plugin`; capability toggle |
| Enable Wait Action | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_wait_plugin`; capability toggle |
| Enable Math Action | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_math_plugin`; capability toggle |
| Enable Text Action | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_text_plugin`; capability toggle |
| Enable Default Embedding Model Action | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_default_embedding_model_plugin`; capability toggle |
| Fact Memory Action | Lets agents store, update, and remove durable facts and instructions for the current user or group. Fact memory is a chat capability, so its availability follows the Chat setting rather than being edited here. | On | `enable_fact_memory_plugin`; configured in [Chat settings]({{ '/admin/chat/#fact-memory-section' | relative_url }}) |
| Tabular Processing Action | Makes the tabular-processing action available to agents for CSV and XLSX analysis when Enhanced Citations is enabled; the setting is normalized from Enhanced Citations rather than edited directly in the UI. | Off | `enable_tabular_processing_plugin`; effective value follows `enable_enhanced_citations` |

## Inbound MCP {#inbound-mcp}

### Inbound MCP {#inbound-mcp-configuration}

The Inbound MCP section belongs to the Inbound MCP tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable inbound MCP server | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_inbound_mcp_server`; capability toggle |
| Required delegated scope | Default: DelegatedMcpServerAccess. VS Code and other user clients must present this delegated scope. | DelegatedMcpServerAccess | `inbound_mcp_required_scope` |
| Required delegated user role | Default: InboundMCPUserAccess. Governance determines which users/groups can use tools after this Entra role and delegated scope pass. | InboundMCPUserAccess | `inbound_mcp_required_user_role` |
| Required app-only role | Default: InboundMCPAppAccess. Reserved for future app-only MCP tools and still governed separately. | InboundMCPAppAccess | `inbound_mcp_required_app_role` |
| Max request bytes | Default: 65536. Range: 1 KB to 1 MB. | 65536 | `inbound_mcp_max_request_bytes` |
| Rate window seconds | Default: 60. Applies to each throttle category. | 60 | `inbound_mcp_rate_limit_window_seconds` |
| Read limit | Default: 120. | 120 | `inbound_mcp_rate_limit_read_per_window` |
| Search limit | Default: 30. | 30 | `inbound_mcp_rate_limit_search_per_window` |
| Write limit | Default: 10. | 10 | `inbound_mcp_rate_limit_write_per_window` |
| Allow additional tenant IDs | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `inbound_mcp_allow_external_tenants` |
| Allow all source IDs | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `inbound_mcp_allow_all_source_ids` |
| Source header name | Default: X-SimpleChat-MCP-Source. | X-SimpleChat-MCP-Source | `inbound_mcp_source_header` |

## Common tasks

1. **Turn on governed agents.** Enable the runtime, choose allowed scopes, and create a test agent. Outcome to verify: Only approved agent scopes are available.
2. **Limit document actions.** Review analyze and comparison limits, then run a small action. Outcome to verify: Document actions complete within configured caps.
3. **Prepare inbound MCP.** Set delegated scope, roles, throttles, and sources, then connect a test client. Outcome to verify: Approved clients can reach tools and blocked sources fail cleanly.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| An action is missing from an agent | The built-in action toggle or workspace action permission is disabled. | Enable the action and confirm the agent scope allows it. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
- [AI Models settings]({{ '/admin/ai-models/' | relative_url }})
