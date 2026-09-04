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

- **Enable Agents** gates this entire group. Decide whether you want agents at all before configuring anything below it.
- Decide whether agents come from one shared global set or from each user's own workspace, because that choice changes which other settings do anything.
- Confirm action dependencies before enabling a plugin.
- Configure App Service Authentication excluded paths before exposing inbound MCP.

## Agents {#agents}

### Agent Runtime {#agents-config}

This is where you decide whether agents run at all, and where they come from.

**Enable Agents** starts the Semantic Kernel runtime. It is the gate for
everything else in this group. While it is off, the Agents catalog page is not
served, no global agent or action is loaded, and the workspace permissions have
nothing to apply to.

**Workspace Mode** answers a question that determines most of the rest of your
configuration: does everyone share one set of agents, or does each user and group
keep their own?

- **Off** — one global set, curated by administrators. You choose the single
  agent that answers, and users pick from what you publish. Use this when agent
  behaviour has to be reviewable and consistent.
- **On** — each user and each group owns a collection. The workspace permissions
  section appears, and the global set is no longer used on its own. Use this when
  people need to build agents for their own work.

**Add Global Agents and Actions to Workspaces** matters only in Workspace Mode.
Turning Workspace Mode on otherwise hides the global set entirely, which is
rarely what an administrator intends; this setting folds the shared agents back
in alongside each person's own.

**Agent Orchestration** appears only when the deployment offers more than one
orchestration mode. This build ships a single mode, single-agent, so the control
is not shown. Orchestration settings save through their own endpoint rather than
with the rest of the page.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Agents | Starts the agent runtime. Gates the Agents catalog page, the global agent and action tables, and every workspace permission in this group. | Off | `enable_semantic_kernel`; capability toggle |
| Workspace Mode | Chooses between one shared global set of agents and actions, and a separate collection per user and group. | Off | `per_user_semantic_kernel` |
| Add Global Agents and Actions to Workspaces | Includes the global set in every workspace collection, so people see both what they built and what you publish. | Off | `merge_global_semantic_kernel_with_workspace`; only applies in Workspace Mode |
| Orchestration Type | Selects how a chat is routed across agents. Hidden while only one mode is available. | default_agent | `orchestration_type`; saved by the orchestration settings API |
| Max Rounds Per Agent | Caps how many turns each agent takes in a multi-agent conversation, which bounds the model calls one message can trigger. | 1 | `max_rounds_per_agent`; forced to 1 outside multi-agent modes |

### Workspace Agent Permissions {#agent-toggles-card}

Shown only in Workspace Mode, because outside it nothing reads these.

Custom endpoints deserve particular attention: they let an agent send prompts to
a model endpoint that the agent's owner configured, rather than one you
administer. Enable them when teams genuinely need their own models, and pair them
with an endpoint governance policy when only some of them should.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Allow Personal Agents | Lets people build and keep agents in their own workspace. | Off | `allow_user_agents`; pair with a personal agent governance policy |
| Allow Group Agents | Lets a group own agents its members share. | Off | `allow_group_agents`; group workspaces must also be enabled |
| Allow Personal Custom Endpoints | Lets people point their own agents at a model endpoint they configure, instead of the deployment's shared models. | Off | `allow_user_custom_endpoints` |
| Allow Group Custom Endpoints | The same for group-owned agents. | Off | `allow_group_custom_endpoints`; group workspaces must also be enabled |
| Enable Agent Template Gallery | Gives workspace users approved agents to start from rather than a blank editor, and adds the Agent Template Approvals section. | On | `enable_agent_template_gallery`; capability toggle |

### Agents Page {#agents-page-customization-card}

Controls how the Agents catalog page presents itself. That page is served behind
**Enable Agents**, so none of this applies while agents are off.

The promotion controls exist because the Popular tab ranks agents by how often
people run them, which leaves a newly published agent unable to be found: nothing
becomes popular until it is already popular. Promoting an agent places it in that
tab regardless of usage. People only ever see promoted agents that are already
visible to them, so a promotion cannot leak an agent someone has no access to.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Hero Title | Headline at the top of the Agents catalog page. Reverts to the default when left empty. | Find your next AI partner | `agents_page_title` |
| Hero Subtitle | Supporting line under the headline. Reverts to the default when left empty. | Explore specialized agents built to accelerate how you work. | `agents_page_subtitle` |
| Hero Color Mode | Draws the hero as a flat colour or as a gradient between the two colours below. | single | `agents_page_hero_color_mode` |
| Primary Color | Hero background, and the first stop of the gradient. | #0f172a | `agents_page_hero_primary_color` |
| Secondary Color | Second stop of the gradient. Only used in two-tone mode. | #1e293b | `agents_page_hero_secondary_color` |
| Disclaimer or Guidance Text | Markdown shown under the hero. Use it for who to contact about a new agent, or the governance reminder people need before choosing one. | Empty | `agents_page_disclaimer_markdown` |
| Show Agent Instructions in Details | Reveals an agent's system prompt in its details popup and in the catalog API response. Turn it off when instructions carry wording or internal references you would rather not publish. | On | `agents_page_show_instructions_in_details` |
| Promoted Placement | Positions promoted agents before, after, or mixed in with the agents that earned their place through usage. | before | `agents_page_promoted_popular_order` |
| Show Promoted Tag | Marks promoted agents so their placement is not mistaken for genuine usage. | On | `agents_page_promoted_popular_tag_enabled` |
| Promoted Tag Label | Wording of that tag. | Promoted | `agents_page_promoted_popular_tag_label` |
| Promoted Agents | The agents placed in the Popular tab regardless of usage, and which time window each promotion applies to. | None | `agents_page_promoted_popular_agents` |

### Agent Template Approvals {#agent-template-approvals-section}

Shown only while the Agent Template Gallery is enabled. Submissions are reviewed
on the shared [approvals queue]({{ '/admin/governance/' | relative_url }}) rather
than here.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Allow User Template Submissions | Lets workspace users offer an agent they built as a template for everyone else, which is how a gallery grows without an administrator authoring every entry. | On | `agent_templates_allow_user_submission` |
| Require Admin Approval | Holds submissions in the approvals queue instead of publishing them straight into the gallery. | On | `agent_templates_require_approval` |

## Actions {#actions}

### Document Actions {#document-action-capabilities-card}

The Document Action Capabilities section belongs to the Actions tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Workspace Action Permissions {#plugin-feature-toggles}

Shown only in Workspace Mode. Whether people may build their own actions, which
is a larger grant than building their own agents: an action carries an endpoint
and its credentials.

### Built-in Actions {#core-plugin-toggles}

The small set of general-purpose actions that ship with the runtime.

### Global Actions {#actions-config}

The actions published to everyone, and the workspace action permissions that sit
alongside them.

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

If the tab shows that the Inbound MCP admin UI is disabled, add the Azure App Service application setting `ENABLE_MCP_UI=true`, save the configuration, and restart the app if your host does not restart it automatically. This only exposes the preview configuration UI; the inbound MCP runtime remains off until **Enable inbound MCP server** is turned on after authentication, client allowlist, source, and governance prerequisites are ready.

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
