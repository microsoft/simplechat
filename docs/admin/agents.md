---
layout: page
title: "Agents Settings"
description: "Controls document actions, agent availability, agent marketplace copy, orchestration, workspace agent/action permissions, core actions, and inbound MCP."
section: "Administration"
audience: admin
admin_tab: agents
---

## What this tab controls

Controls document actions, agent availability, agent marketplace copy, orchestration, workspace agent/action permissions, core actions, and inbound MCP.

## Why it matters

Agents and actions can combine model calls with tools, documents, HTTP calls, memory, tabular analysis, and inbound MCP clients. Enabling them expands what users can automate, but it also expands cost and data-access paths. The safest rollout starts with model endpoints, then agent scope, then actions, then governance and MCP.

{% include media.html src="admin/agents-overview.png" alt="Screenshot of the Agents settings tab showing agents tab." title="Agents tab" capture="Capture the Agents tab for Agents tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Agents settings walkthrough" poster="video-posters/admin-agents.png" capture="Recording planned. Walk through every setting on the Agents tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Analyze | Controls how SimpleChat uses enable analyze on this tab. | On | `document_action_analyze_enabled` |
| Document Action Analyze Chat Max Documents Range | Caps or schedules document action analyze chat max documents range so the feature stays within expected capacity. | 3 | `document_action_analyze_chat_max_documents_range` |
| Chat max documents | Caps or schedules chat max documents so the feature stays within expected capacity. | 3 | `document_action_analyze_chat_max_documents` |
| Document Action Analyze Workflow Max Documents Range | Caps or schedules document action analyze workflow max documents range so the feature stays within expected capacity. | 10 | `document_action_analyze_workflow_max_documents_range` |
| Workflow max documents | Caps or schedules workflow max documents so the feature stays within expected capacity. | 10 | `document_action_analyze_workflow_max_documents` |
| Enable Document Comparison | Controls how SimpleChat uses enable document comparison on this tab. | On | `document_action_comparison_enabled` |
| Document Action Comparison Chat Max Documents Range | Caps or schedules document action comparison chat max documents range so the feature stays within expected capacity. | 3 | `document_action_comparison_chat_max_documents_range` |
| Chat max documents | Caps or schedules chat max documents so the feature stays within expected capacity. | 3 | `document_action_comparison_chat_max_documents` |
| Document Action Comparison Workflow Max Documents Range | Caps or schedules document action comparison workflow max documents range so the feature stays within expected capacity. | 10 | `document_action_comparison_workflow_max_documents_range` |
| Workflow max documents | Caps or schedules workflow max documents so the feature stays within expected capacity. | 10 | `document_action_comparison_workflow_max_documents` |
| Hero Title | Controls the user-facing copy or name shown for hero title. | Find your next AI partner | `agents_page_title` |
| Hero Subtitle | Controls the user-facing copy or name shown for hero subtitle. | Explore specialized agents built to accelerate how you work. | `agents_page_subtitle` |
| Hero Color Mode | Controls how SimpleChat uses hero color mode on this tab. | single | `agents_page_hero_color_mode` |
| Primary Color | Controls how SimpleChat uses primary color on this tab. | #0f172a | `agents_page_hero_primary_color` |
| Secondary Color | Controls how SimpleChat uses secondary color on this tab. | #1e293b | `agents_page_hero_secondary_color` |
| Disclaimer / Guidance Text (Markdown supported) | Shown below the Agents page hero. Use this for contact details, request guidance, or governance reminders. | Empty | `agents_page_disclaimer_markdown` |
| Show agent instructions in Agents page details | Controls how SimpleChat uses show agent instructions in agents page details on this tab. | On | `agents_page_show_instructions_in_details` |
| Agents Page Promoted Popular Agents Json | Controls how SimpleChat uses agents page promoted popular agents json on this tab. | Not specified in defaults | `agents_page_promoted_popular_agents_json` |
| Placement | Controls how SimpleChat uses placement on this tab. | before | `agents_page_promoted_popular_order` |
| Promoted Tag Label | Controls how SimpleChat uses promoted tag label on this tab. | Not specified in defaults | `agents_page_promoted_popular_tag_label` |
| Show promoted tag | Controls how SimpleChat uses show promoted tag on this tab. | On | `agents_page_promoted_popular_tag_enabled` |
| Add Agent | Controls how SimpleChat uses add agent on this tab. | Not specified in defaults | Runtime UI control |
| Enable Agents | Enables the agent and action runtime so users can work with configured agents instead of only the base chat experience. | Off | `enable_semantic_kernel`; capability toggle |
| Workspace Mode (workspace-specific agents/plugins and disables global configuration) | Controls how SimpleChat uses workspace mode (workspace-specific agents/plugins and disables global configuration) on this tab. | Off | `per_user_semantic_kernel` |
| Allow User Agents | Permits user agents when the related workspace or agent feature is enabled. | Off | `allow_user_agents` |
| Allow Group Agents | Permits group agents when the related workspace or agent feature is enabled. | Off | `allow_group_agents` |
| Allow User Custom Endpoints | Permits user custom endpoints when the related workspace or agent feature is enabled. | Off | `allow_user_custom_endpoints` |
| Allow Group Custom Endpoints | Permits group custom endpoints when the related workspace or agent feature is enabled. | Off | `allow_group_custom_endpoints` |
| Merge Global Agents/Plugins into Workspace | Controls how SimpleChat uses merge global agents/plugins into workspace on this tab. | Off | `merge_global_semantic_kernel_with_workspace` |
| Enable Agent Template Gallery | Makes agent template gallery available in the product when its required service and access policy are configured. | On | `enable_agent_template_gallery`; capability toggle |
| Orchestration Type | Controls how SimpleChat uses orchestration type on this tab. | default_agent | `orchestration_type` |
| Multi-agent orchestration | Derived from **Orchestration Type**; enables group-chat orchestration paths when the selected orchestration mode is multi-agent, so the runtime can coordinate multiple configured agents instead of routing to a single default agent. | Off | `enable_multi_agent_orchestration`; saved by orchestration settings API |
| Max Rounds Per Agent (Group Chat) | Caps or schedules max rounds per agent (group chat) so the feature stays within expected capacity. | 1 | `max_rounds_per_agent` |
| Selected Agent: | Controls how SimpleChat uses selected agent: on this tab. | Not specified in defaults | Runtime UI control |
| Allow User Template Submissions | Controls how SimpleChat uses allow user template submissions on this tab. | On | `agent_templates_allow_user_submission` |
| Require Admin Approval | Controls how SimpleChat uses require admin approval on this tab. | On | `agent_templates_require_approval` |
| Allow Personal Actions | Permits personal actions when the related workspace or agent feature is enabled. | Off | `allow_user_plugins` |
| Allow Group Actions | Permits group actions when the related workspace or agent feature is enabled. | Off | `allow_group_plugins` |
| Enable Time Action | Makes time action available in the product when its required service and access policy are configured. | On | `enable_time_plugin`; capability toggle |
| Enable HTTP Action | Makes http action available in the product when its required service and access policy are configured. | On | `enable_http_plugin`; capability toggle |
| Enable Wait Action | Makes wait action available in the product when its required service and access policy are configured. | On | `enable_wait_plugin`; capability toggle |
| Enable Math Action | Makes math action available in the product when its required service and access policy are configured. | On | `enable_math_plugin`; capability toggle |
| Enable Text Action | Makes text action available in the product when its required service and access policy are configured. | On | `enable_text_plugin`; capability toggle |
| Enable Default Embedding Model Action | Makes default embedding model action available in the product when its required service and access policy are configured. | Off | `enable_default_embedding_model_plugin`; capability toggle |
| Enable Fact Memory Action | Makes fact memory action available in the product when its required service and access policy are configured. | On | `enable_fact_memory_plugin`; capability toggle |
| Tabular Processing Action | Makes the tabular-processing action available to agents for CSV and XLSX analysis when Enhanced Citations is enabled; the setting is normalized from Enhanced Citations rather than edited directly in the UI. | Off | `enable_tabular_processing_plugin`; effective value follows `enable_enhanced_citations` |
| Enable inbound MCP server | Makes inbound mcp server available in the product when its required service and access policy are configured. | Off | `enable_inbound_mcp_server`; capability toggle |
| Required delegated scope | Default: DelegatedMcpServerAccess . VS Code and other user clients must present this delegated scope. | DelegatedMcpServerAccess | `inbound_mcp_required_scope` |
| Required delegated user role | Default: InboundMCPUserAccess . Governance determines which users/groups can use tools after this Entra role and delegated scope pass. | InboundMCPUserAccess | `inbound_mcp_required_user_role` |
| Required app-only role | Default: InboundMCPAppAccess . Reserved for future app-only MCP tools and still governed separately. | InboundMCPAppAccess | `inbound_mcp_required_app_role` |
| Enable tool throttles | Makes tool throttles available in the product when its required service and access policy are configured. | On | `enable_inbound_mcp_rate_limits`; capability toggle |
| Max request bytes | Default: 65536 . Range: 1 KB to 1 MB. | 65536 | `inbound_mcp_max_request_bytes` |
| Rate window seconds | Default: 60 . Applies to each throttle category. | 60 | `inbound_mcp_rate_limit_window_seconds` |
| Read limit | Default: 120 . | 120 | `inbound_mcp_rate_limit_read_per_window` |
| Search limit | Default: 30 . | 30 | `inbound_mcp_rate_limit_search_per_window` |
| Write limit | Default: 10 . | 10 | `inbound_mcp_rate_limit_write_per_window` |
| Allow additional tenant IDs | Controls how SimpleChat uses allow additional tenant ids on this tab. | Off | `inbound_mcp_allow_external_tenants` |
| Allow all source IDs | Controls how SimpleChat uses allow all source ids on this tab. | On | `inbound_mcp_allow_all_source_ids` |
| Source header name | Default: X-SimpleChat-MCP-Source . | X-SimpleChat-MCP-Source | `inbound_mcp_source_header` |
| Value | Controls how SimpleChat uses value on this tab. | Not specified in defaults | Runtime UI control |
| Description | Use descriptions to explain who owns this app, tenant, or source value without making the value easy to guess. | Not specified in defaults | Runtime UI control |
| I have added the required App Service Authentication excluded paths for this SimpleChat App Service. | Controls how SimpleChat uses i have added the required app service authentication excluded paths for this simplechat app service on this tab. | Not specified in defaults | Runtime UI control |

### Agent enablement and orchestration

The Agents switch exposes Semantic Kernel-powered agents. Orchestration controls whether a selected default agent handles work or multiple agents participate in group chat, which can multiply model calls and tool invocations.

### Core action toggles

Core actions make built-in tools available to agents. Keep any action off unless users need it; HTTP and MCP-related capabilities deserve extra review because they can reach network destinations.

### Inbound MCP server

Inbound MCP allows external clients such as development tools to call approved SimpleChat tools. Configure delegated scope, user role, source header, source allowlist, request size, throttles, and App Service Authentication exclusions before enabling it.

### Multi-agent orchestration

Multi-agent orchestration is controlled by **Orchestration Type**, not by a separate checkbox in the page. Choosing a multi-agent mode sets `enable_multi_agent_orchestration` and can increase model calls because more than one agent may participate. Configure the global agents and default/orchestrator agent first, then set **Max Rounds Per Agent** low enough to bound cost and latency.

### Tabular Processing Action

The Tabular Processing Action is displayed in the Core Action Toggles area, but it is automatically enabled when Enhanced Citations is enabled. That dependency matters because tabular analysis relies on blob-backed source access for CSV and XLSX files. Disable Enhanced Citations if the deployment should not expose tabular-processing behavior.

## Before you change anything

- Configure at least one working GPT model endpoint before enabling agents.
- Decide whether agents and actions are global, personal, group-scoped, or merged across scopes.
- Review each core action before enabling it for users because actions can call tools or external services.
- For inbound MCP, configure App Service Authentication exclusions and Entra scopes/roles first.

## Common tasks

1. **Enable agents for users.**
    1. Enable **Enable Agents**.
    2. Choose workspace mode and whether global agents merge into workspaces.
    3. Select the global default agent if using global configuration.
    4. Save and open the Agents page.
    Outcome to verify: Users see the intended agent experience.

{% include media.html src="admin/agents-enable-agents-for-users.png" alt="Screenshot of the Agents settings tab showing enable agents for users." title="Agents: Enable agents for users" capture="Capture the Agents tab while performing Enable agents for users. Show the relevant controls and redact secrets." %}

2. **Configure action availability.**
    1. Enable or disable **Allow Personal Actions** and **Allow Group Actions**.
    2. Review each **Core Action Toggle**.
    3. Keep network-capable actions off unless approved.
    4. Save and verify agent action menus.
    Outcome to verify: Only approved actions are available to agents.

{% include media.html src="admin/agents-configure-action-availability.png" alt="Screenshot of the Agents settings tab showing configure action availability." title="Agents: Configure action availability" capture="Capture the Agents tab while performing Configure action availability. Show the relevant controls and redact secrets." %}

3. **Roll out the agent template gallery.**
    1. Enable **Enable Agent Template Gallery**.
    2. Set user submission and approval requirements.
    3. Customize Agents page hero and disclaimer copy.
    4. Save and review the Agents page.
    Outcome to verify: The gallery appears with approved copy and approval flow.

{% include media.html src="admin/agents-roll-out-the-agent-template-gallery.png" alt="Screenshot of the Agents settings tab showing roll out the agent template gallery." title="Agents: Roll out the agent template gallery" capture="Capture the Agents tab while performing Roll out the agent template gallery. Show the relevant controls and redact secrets." %}

4. **Configure inbound MCP.**
    1. Enable **Enable inbound MCP server** only after App Service Authentication exclusions are configured.
    2. Set delegated scope, user role, app-only role, source header, and source policy.
    3. Review request-size and rate-limit fields.
    4. Test with an authorized MCP client.
    Outcome to verify: Inbound MCP calls pass authentication and governance checks.

{% include media.html src="admin/agents-configure-inbound-mcp.png" alt="Screenshot of the Agents settings tab showing configure inbound mcp." title="Agents: Configure inbound MCP" capture="Capture the Agents tab while performing Configure inbound MCP. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Agent controls do not appear to users | `enable_semantic_kernel` is off. | Enable Agents, configure model prerequisites, and save settings. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [AI Models]({{ '/admin/ai-models/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
- [Security]({{ '/admin/security/' | relative_url }})
