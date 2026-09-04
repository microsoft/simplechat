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
| Multi-Agent Orchestration | Reports whether the runtime coordinates several agents. Follows the orchestration mode rather than being set directly. | Off | `enable_multi_agent_orchestration`; derived |
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

**Analyze** and **Document Comparison** appear in the **Action** menu in chat and
in workflows. They are not searches. Analyze reads every selected document in
full, so an answer covers all of them rather than only the passages a search
returned; Comparison reads one baseline document against the others, which is
what answers questions about what changed between versions.

Because each document is read in full, the limits are the control that matters.
They bound how long a single message can take and how much it costs. Chat and
workflow are limited separately: a chat message has someone waiting on it, while
a workflow run does not and can be allowed a much larger batch.

These six values are stored as one object, `document_action_capabilities`, rather
than as separate settings.

#### Settings

| Setting | What it does | Default | Range | Notes |
| --- | --- | --- | --- | --- |
| Enable Analyze | Offers Analyze in the Action menu. | On | — | `document_action_capabilities.analyze.enabled` |
| Analyze: Chat Document Limit | Most documents one chat message may analyze. | 3 | 2–300 | `analyze.chat_max_documents` |
| Analyze: Workflow Document Limit | The same limit for a workflow run. | 10 | 2–1000 | `analyze.workflow_max_documents` |
| Enable Document Comparison | Offers Document Comparison in the Action menu. | On | — | `document_action_capabilities.comparison.enabled` |
| Comparison: Chat Document Limit | Most documents one chat message may compare, including the baseline. | 3 | 2–300 | `comparison.chat_max_documents` |
| Comparison: Workflow Document Limit | The same limit for a workflow run. | 10 | 2–1000 | `comparison.workflow_max_documents` |

Values outside the range are clamped on save rather than rejected.

### Workspace Action Permissions {#plugin-feature-toggles}

Shown only in Workspace Mode.

Letting someone build an action is a wider grant than letting them build an
agent. An action carries an endpoint and the credentials to reach it, so once
these are on, the traffic an agent can generate is no longer limited to the
destinations you configured. Pair them with an action governance policy when only
some people should have that.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Allow Personal Actions | Lets people create actions in their own workspace. | Off | `allow_user_plugins` |
| Allow Group Actions | The same for a group's shared actions. | Off | `allow_group_plugins`; group workspaces must also be enabled |

### Built-in Actions {#core-plugin-toggles}

The small set of general-purpose actions that ship with the runtime. They are on
by default and are rarely changed, so they are collapsed.

The one worth a decision is **HTTP**: it is the only built-in action that reaches
outside the deployment. Turn it off where agents should only be able to use the
connectors you configured.

Each is loaded independently, so turning one off removes that capability and
affects nothing else.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Time | Lets an agent read the current date and time and calculate with them, instead of answering date questions from training data. | On | `enable_time_plugin` |
| HTTP | Lets an agent fetch a URL directly. The only built-in action that leaves the deployment. | On | `enable_http_plugin` |
| Wait | Lets an agent pause, which workflows use to space out repeated calls. | On | `enable_wait_plugin` |
| Math | Lets an agent calculate rather than predict an answer. | On | `enable_math_plugin` |
| Text | Lets an agent format, trim and reshape text deterministically. | On | `enable_text_plugin` |
| Default Embedding Model | Exposes the embedding model for similarity work outside the normal document search path. Document search already embeds without it. | Off | `enable_default_embedding_model_plugin` |

#### Managed elsewhere

Two actions are listed here because they change what an agent can do, but neither
is set from this page.

| Action | Where it comes from | Notes |
| --- | --- | --- |
| Fact Memory | [Chat › Chat Experience › Fact Memory]({{ '/admin/chat/#fact-memory-section' | relative_url }}) | `enable_fact_memory_plugin`; a chat capability that also gives agents a memory action |
| Tabular Processing | [Chat › Citations › Enhanced]({{ '/admin/chat/#enhanced-citations-section' | relative_url }}) | `enable_tabular_processing_plugin`; recomputed from `enable_enhanced_citations` on every settings read, so it cannot be set independently |

### Global Actions {#actions-config}

The actions published to everyone. Authoring them stays in the classic admin
interface for now.

## Inbound MCP {#inbound-mcp}

### Inbound MCP {#inbound-mcp-configuration}

Inbound MCP lets an external MCP client — an editor, for example — call
SimpleChat tools on a signed-in user's behalf. It is the one part of SimpleChat
that accepts requests from software you do not control, so it is deny-by-default
at five separate layers, and turning it on is the last step rather than the first.

A request is served only if **all** of these hold:

1. the caller presents the required delegated scope;
2. the signed-in user holds the required Entra app role;
3. the caller's application id is on the client allowlist;
4. the caller's tenant is allowed;
5. the source value is allowed, **and** a governance policy grants that user or
   group access to the tool.

Today the tool surface is personal tools only, and every one of them needs a
delegated user token. The app-only role is reserved for future service tools and
grants nothing.

#### If the settings are not shown

The configuration is a preview and stays hidden until the deployment opts in. Add
the Azure App Service application setting `ENABLE_MCP_UI=true`, save, and restart
the app if your host does not restart it for you.

That reveals the settings and nothing else. The endpoint stays closed until
**Enable Inbound MCP Server** is switched on.

#### Runtime gate

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Inbound MCP Server | Accepts requests from external MCP clients. Every check above still applies afterwards. | Off | `enable_inbound_mcp_server`; capability toggle |
| Required Delegated Scope | The delegated scope a client must present. Must match the scope exposed on the Entra application registration, or every request is refused. | DelegatedMcpServerAccess | `inbound_mcp_required_scope` |
| Required Delegated User Role | The Entra app role a signed-in user must hold to connect at all. Which tools they then get is decided by governance policy. | InboundMCPUserAccess | `inbound_mcp_required_user_role` |
| Required App-Only Role | Reserved for future service-to-service tools. No tool uses it today. | InboundMCPAppAccess | `inbound_mcp_required_app_role` |

#### Request limits

Throttles are **on by default** while the server itself is off, so seeing them
enabled does not mean the endpoint is reachable. They take effect only once the
server is enabled, and are counted per caller and per tool category across app
instances.

| Setting | What it does | Default | Range |
| --- | --- | --- | --- |
| Enable Tool Throttles | Caps how often one caller may invoke each category of tool, so a client stuck in a loop cannot exhaust the deployment. | On | — |
| Max Request Bytes | Largest request body accepted. Anything bigger is refused unread. | 65536 | 1 KB – 1 MB |
| Throttle Window (Seconds) | The period each limit below is counted over. | 60 | 10 – 3600 |
| Read Calls Per Window | Reads are cheap, so this is the most permissive limit. | 120 | 1 – 10000 |
| Search Calls Per Window | Each search costs an index query, so it is limited harder than reads. | 30 | 1 – 10000 |
| Write Calls Per Window | Writes change stored data, so this is the tightest limit. | 10 | 1 – 10000 |

#### Allowlists

Each allowlist row pairs the identifier the runtime matches with a description of
who it belongs to. Fill the description in: a list of bare GUIDs becomes
impossible to audit within weeks, and nobody can then say which entry is safe to
remove.

**Client app IDs are required.** While that list is empty no client can connect,
whatever else is configured.

**Source IDs are weaker than they look.** The source arrives in a request header
the client sets, so it identifies rather than authenticates, and it can be
spoofed unless a gateway or APIM policy sets and enforces it. Leaving **Allow all
source IDs** on accepts any value at this layer; a governance policy still
decides who gets tools. Turn it off only where something upstream controls the
header.

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Allowed Client App IDs | The Entra application ids permitted to connect. | Empty, so nothing can connect | `inbound_mcp_allowed_client_app_entries` |
| Allow Additional Tenant IDs | Off restricts callers to this deployment's own tenant. | Off | `inbound_mcp_allow_external_tenants` |
| Allowed Tenant IDs | Additional tenants whose users may connect. The deployment's own tenant is always included. | Empty | `inbound_mcp_allowed_tenant_entries` |
| Allow All Source IDs | Accepts any source value at the allowlist layer. | On | `inbound_mcp_allow_all_source_ids` |
| Source Header Name | The request header the source value is read from. | X-SimpleChat-MCP-Source | `inbound_mcp_source_header` |
| Allowed Source IDs | The source values accepted when not allowing all of them. | Empty | `inbound_mcp_allowed_source_entries` |

Turning **Allow Additional Tenant IDs** off does not delete the tenants you
listed; it stops admitting them. Turning it back on restores them.

Application Insights records `mcp_request_id`, the calling app, the delegated
user, the source, the tool, duration, result and rate-limit category for each
request — and never prompts, document content, bearer tokens or secrets.

## Common tasks

1. **Turn on governed agents.** Enable the runtime, choose allowed scopes, and create a test agent. Outcome to verify: Only approved agent scopes are available.
2. **Limit document actions.** Review analyze and comparison limits, then run a small action. Outcome to verify: Document actions complete within configured caps.
3. **Prepare inbound MCP.** Set delegated scope, roles, throttles, and sources, then connect a test client. Outcome to verify: Approved clients can reach tools and blocked sources fail cleanly.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| An action is missing from an agent | The built-in action toggle or workspace action permission is disabled. | Enable the action and confirm the agent scope allows it. |
| The Agents page returns an error instead of the catalog | **Enable Agents** is off. That page is served behind it. | Turn on Enable Agents, or remove the link from navigation. |
| An agent setting has no effect | Workspace Mode changes where agents come from, so a global agent is unused in Workspace Mode unless the merge setting is on. | Check Workspace Mode first, then the merge setting. |
| A document action ignores the limit you set | The value was outside the supported range and was clamped on save. | Re-open the setting to see the stored value. |
| An MCP client is refused after the allowlist was updated | Every layer must pass, and a governance policy is still required after the allowlists. | Check the client app id, the tenant, the source, and the governance policy in that order. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
- [AI Models settings]({{ '/admin/ai-models/' | relative_url }})
