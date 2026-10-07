---
layout: page
title: "Governance settings"
description: "Governance decides who may use agents, actions, and model endpoints inside SimpleChat, which remote MCP servers actions may reach, and who may use SimpleChat as an inbound MCP server."
section: "Administration"
audience: admin
admin_tab: governance
---


# Governance settings

## What this group controls

Governance decides who may use what is configured inside SimpleChat. Entra app roles
still decide who may sign in; governance works on the people who are already in.

It covers four things:

- **Feature governance**: who may use personal, group, and global endpoints, agents,
  and actions.
- **Delegated item policies**: who may use one specific shared connection, published
  agent, published action, or action type.
- **MCP destination governance**: which remote MCP servers an action may reach, by
  scope and by person.
- **Inbound MCP source governance**: who may use SimpleChat as an MCP server from an
  external client.

## Why it matters

Workspace permissions under Agents & Actions are all-or-nothing: turning on
**Allow Personal Agents** lets everyone build personal agents. Governance is how you
give a capability to some people first, such as a pilot group, keep one shared model
connection for one team, or stop a known person from using an action type, without
switching the feature off for everyone else.

{% include media.html src="admin/governance-overview.png" alt="Screenshot placeholder for the Governance group in Admin Settings." title="Governance settings" capture="Capture the Governance group in Admin Settings showing its tabs." %}

{% include media.html type="video" title="Governance settings walkthrough" poster="video-posters/admin-governance.png" capture="Recording planned. Walk through each tab in the Governance group and explain when to change each setting." %}

## How a request is checked

Every governed request is decided the same way:

1. A governance switch that is off checks nothing.
2. A block list that names the person, or a group they belong to, refuses them. Block
   lists are checked first and always win.
3. The feature policy must let them through: **Allow everyone**, or an allow list that
   names them or one of their groups. With Allow everyone off and nobody listed,
   nobody passes.
4. For one specific resource, any one of its delegated item policies is enough. With
   no item policy on that resource, the feature policy decides alone.

Two exceptions:

- **Action types.** When an action type has its own policies, one of them is required,
  and one of them can let in someone the feature policy leaves out. A feature block
  list still refuses them.
- **MCP destinations and inbound MCP sources** are deny-by-default. With no policy,
  nothing is allowed.

A group in a policy can be a group workspace or a public workspace, because a person's
governance groups come from both kinds of membership. For a public workspace that means
its owner, admins, and document managers. The workspace works as a reusable cohort, for
example the people piloting personal agents, and being named grants nothing inside it.

## Before you change anything

- Turn on the feature you are governing first, or expect the governance switch to wait
  for it. **Govern Personal Agents** does nothing until **Allow Personal Agents** is on.
- Decide the audience before turning a switch on. A switch with an untouched feature
  policy lets everyone through, so turning it on changes nothing until the policy names
  people.
- Write MCP destination policies for the servers people already use before you turn on
  **Enforce MCP Destination Allowlist**. With enforcement on and no policy, every remote
  MCP action stops working.
- Create a group workspace for each cohort you will name in policies, so membership is
  managed in one place rather than in every policy.

## Feature Governance {#feature-governance}

### Governance Feature Toggles {#governance-feature-toggles-section}

Each switch turns on checking for one kind of capability. Who passes is decided by the
matching feature policy under [Feature Policies](#governance-feature-policies-section).

The switches are paired by resource, personal beside group. A switch can be on while
the feature it governs is off. It keeps its value, the section shows **Prerequisite
missing** with a link to the feature, and checking begins as soon as the feature is
turned on. This is deliberate: turning a feature off and on again does not silently
drop the governance you configured for it.

**Govern Global Endpoints** is always on. SimpleChat always filters the shared AI
connections through it, so it is reported rather than offered as a switch.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Govern Personal Endpoints | Checks the Personal Endpoints feature policy before someone adds, tests, or chats through a model endpoint in their own workspace. | Off | `governance_user_endpoints`; waits for Allow Personal Custom Endpoints |
| Govern Group Endpoints | Checks the Group Endpoints feature policy before someone adds, tests, or chats through a model endpoint in a group workspace. | Off | `governance_group_endpoints`; waits for Allow Group Custom Endpoints |
| Govern Personal Agents | Checks the Personal Agents feature policy before someone creates, edits, or chats with an agent in their own workspace. | Off | `governance_user_agents`; waits for Allow Personal Agents |
| Govern Group Agents | Checks the Group Agents feature policy before someone uses or manages the agents a group workspace shares. | Off | `governance_group_agents`; waits for Allow Group Agents |
| Govern Personal Actions | Checks the Personal Actions feature policy, and any personal action-type policy, before someone creates or runs an action in their own workspace. | Off | `governance_user_actions`; waits for Allow Personal Actions |
| Govern Group Actions | The same check for actions in group workspaces, using the Group Actions feature policy and group action-type policies. | Off | `governance_group_actions`; waits for Allow Group Actions |
| Govern Global Endpoints | People who pass the Global Endpoints feature policy can use the shared AI connections, and a delegated item policy can narrow one connection. | On | `governance_global_endpoints`; always enforced, read-only |
| Govern Global Agents | Checks the Global Agents feature policy, then any item policy on the agent, before someone selects or chats with an agent the organization publishes. | Off | `governance_global_agents_usage`; waits for Enable Agents |
| Govern Global Actions | Checks the Global Actions feature policy and global action-type policies, then any item policy on the action, before an agent uses a published action. | Off | `governance_global_actions_usage`; waits for Enable Agents |

Every change to these switches, and to the two MCP destination switches, is recorded in
the governance activity log with the before and after state of all of them.

## Policies {#governance-policies}

### Feature Policies {#governance-feature-policies-section}

One policy per governance switch, grouped by personal, group, and organization-wide
scope. Every policy is listed, including those whose switch is off, so you can prepare
the audience before you turn the switch on.

Each row says whether the policy is being enforced right now:

| Badge | Meaning |
| --- | --- |
| Enforced | The switch is on and the feature it governs is on. |
| Not enforced | The switch is off. **Go to setting** opens the switch. |
| Waiting for *feature* | The switch is on, but the feature it governs is off. **Go to setting** opens the feature. |
| *state* after you save | An unsaved change on the page will change the badge once saved. |

**Edit** opens the policy in place:

- **Allow everyone** lets everyone through except the people and groups blocked below.
  Turn it off to allow only the people and groups you list. If you turn it off and list
  nobody, the editor warns that nobody passes.
- **Find people** searches the directory by name or email. **Find groups** searches
  group workspaces and public workspaces by name or ID; public workspaces are marked.
- **Paste IDs** takes IDs one per line or separated by commas, and either adds them to
  the list or replaces it. This is the replacement for the classic CSV import.
- An ID that no longer resolves stays in the list, marked **Not found** for a group or
  **Unresolved** for a person, so you can see it and remove it.

A feature policy saves on its own when you select **Save policy**. It does not wait for
the page's Save bar, because policies are stored separately from settings. While a
policy has unsaved changes, settings categories and search are locked, because leaving
the category would discard the edit. Save or discard the policy to unlock them.

### Delegated Item Policies {#governance-item-policies-section}

A delegated item policy narrows one specific resource. Every type is listed here; the
MCP and inbound MCP types also appear on their own cards below.

| Applies to | The item it names | Effect |
| --- | --- | --- |
| Global Endpoint | One shared AI connection | Only the people it allows can use that connection. |
| Global Agent | One published agent | Applies once Govern Global Agents is on. |
| Global Action | One published action | Applies once Govern Global Actions is on. |
| Personal Action Type | One type of action, such as MCP or OpenAPI | Who may create and run that type in their own workspace. |
| Group Action Type | One type of action | The same for group workspaces. |
| Global Action Type | One type of action | Who may use published actions of that type. |
| MCP Personal Destination | A destination pattern | Which remote MCP servers personal actions may reach. |
| MCP Group Destination | A destination pattern, optionally for one group | Which remote MCP servers group actions may reach. |
| MCP Global Destination | A destination pattern | Which remote MCP servers published actions may reach. |
| Inbound MCP Source | `*` or one accepted source ID | Who may use SimpleChat as an inbound MCP server. |

A resource can have several policies. Passing any one of them is enough, and a block
list in any of them refuses the person.

The list searches policy names, items, and people or group IDs, filters by type, and
pages through results. Each row can be expanded to show who it allows and blocks, and
offers four actions:

- **Duplicate** opens a new copy of the policy for you to change.
- **Inverse** opens a new copy with the allowed and blocked people swapped:
  "everyone except Bob" becomes "only Bob", and "only Ada" becomes "everyone except Ada".
- **Edit** changes the policy. Changing what it applies to moves the policy and keeps
  its ID, rather than leaving a copy on the old item.
- **Delete** asks you to confirm first.

System-managed policies are marked and cannot be edited or deleted.

## MCP Governance {#mcp-governance}

### MCP Action Destination Governance {#governance-mcp-destination-section}

Use destination governance to limit which remote MCP servers personal, group, and global
actions may contact. Policies apply to saves, discovery, connection tests, and tool
execution, not just to the server choices shown in the action editor.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enforce MCP Destination Allowlist | Remote MCP actions may only connect to destinations a destination policy allows for the action's scope and the person running it. | Off | `enable_mcp_destination_governance` |
| Block Private and Local IP Destinations | Refuses endpoints written as a loopback, private, link-local, or cloud metadata IP address, or a localhost name. Works with or without the allowlist. | Off | `mcp_block_unsafe_destinations` |

**Deployment Restrictions** reports whether App Service settings already require
enforcement or blocking for the whole deployment, and how many destination patterns
they contribute. Starting in **0.261.029**, environment-enforced destination
restrictions are a non-overridable minimum. Admin Settings may tighten them, but cannot
widen an environment allowlist or turn off environment-required enforcement or
unsafe-address blocking. If the readout says the environment requires the allowlist,
it is enforced even while the switch above is off.

A destination is decided in this order:

1. With blocking on, an unsafe address is refused.
2. With enforcement off, everything else is allowed.
3. A policy that blocks the person refuses any destination its pattern matches, even if
   another policy allows it.
4. A policy that allows the person allows any destination its pattern matches.
5. Anything else is refused.

#### Destination policies

The card lists only the destination policies. **New policy for Personal**, **Group**,
or **Global** opens the editor for that scope. The editor builds the pattern for you: choose what the
policy allows, then pick a preconfigured server, preset, or transport from what the
deployment actually loads, or type a host or URL. The value that will be stored is shown
before you save, and a pattern that could never match is refused.

| Pattern | Matches |
| --- | --- |
| `preconfiguration:github` | One template from the MCP catalog. Enterprise templates only appear in the action editor when a policy names them this way; `*` is not enough. |
| `*.contoso.com` | Every endpoint on a matching host. Host patterns match the host name only, without a port. |
| `https://mcp.contoso.com/mcp*` | One endpoint, or every path under it when the URL ends in `*`. A `*` anywhere else in the path is not a wildcard. |
| `preset:generic` | Every server built from one preset. |
| `transport:streamable_http` | Every server on one transport: `sse`, `streamable_http`, or `websocket`. |
| `*` | Any remote server in the scope, after identity and authentication checks. |
| `group:<group-id>::<pattern>` | Group scope only: the pattern applies to one group instead of every group. Choose **Only for one group** in the editor rather than typing it. |

Some templates also need a host or URL policy for your organization's own endpoint; the
editor says so when you pick one.

Remote authorization uses a consistent MCP action type, the action's server-established
collection or partition origin, the current user or established workflow identity, and
current settings. Cached tools are checked again when used. A global action referenced
by a personal or group agent still uses its global destination policy.

### Retired stdio action cleanup

Stdio and local process command, argument, and environment configuration are removed in
**0.261.029** for all roles and scopes, including Admin/global. No governance toggle or
Admin exemption restores them.

Existing stdio actions remain visible but cannot execute. Owners can inspect and
explicitly delete their retired records even when MCP-usage governance denies execution;
personal ownership, group-management permissions, and Admin boundaries remain in force.
Explicit reconfiguration to a supported remote transport and valid endpoint must pass
normal current governance.

Legacy records remain available for management without automatic conversion or
deletion. Omitting a retired record from a bulk save does not delete it, and migration
retains unsupported or failed records. See the
[MCP action guide]({{ '/reference/actions/mcp/' | relative_url }}#retired-stdio-actions)
for the owner workflow.

### Inbound MCP Source Governance {#governance-inbound-mcp-section}

Inbound MCP is deny-by-default. A request that passes every check on the
[Inbound MCP settings]({{ '/admin/agents-actions/' | relative_url }}#inbound-mcp-configuration)
still returns no tools until a source policy here allows the signed-in person.

A source policy names `*`, which covers every source ID the Inbound MCP allowlist
accepts, or one specific source ID. A request is checked against the policies for its
own source ID and for `*`: a block list in any of them refuses the person, and any one
that allows them is enough.

- While the Inbound MCP allowlist accepts any source ID, only `*` can be chosen.
- New policies start with **Allow everyone** off, so you name who may connect.
- The source ID comes from a request header the client sends. Treat it as advisory
  unless a trusted gateway sets or validates it; the Entra role and delegated scope are
  what authenticate the caller.
- The built-in policy `system-allow-all-sources` is ignored when requests are
  evaluated, so it never lets anyone in.

The card shows whether inbound MCP is available for the deployment, whether the server
is on, and whether any source ID is accepted. It warns when the server is on and no
source policy exists.

## Shortcuts from other settings

Governance is also reachable from the settings it qualifies:

- **Agents & Actions**: Allow Personal Agents, Allow Group Agents, the two custom endpoint
  permissions, the two action permissions, and Enable Agents each show the matching
  governance switch, whether it is on, and a **Review** link to it.
- **Inbound MCP**: the card opens with how many source policies exist, **Create a policy
  for any source** (or **Create a source policy** when sources are listed), and
  **Review in Governance**.
- **AI Connections**: each connection has **Manage access**, which lists the Global
  Endpoint policies on that connection and creates new ones without leaving the page.

## Common tasks

1. **Pilot personal agents with a small group.** Create a group workspace for the pilot.
   Under Feature Policies, edit Personal Agents, turn off Allow everyone, and add the
   group. Then turn on Govern Personal Agents and Allow Personal Agents. Outcome to
   verify: a pilot member can create a personal agent, and someone outside the pilot
   cannot.
2. **Keep one AI connection for one team.** Under AI Models > AI Connections, select
   Manage access on the connection, choose New access policy, turn off Allow everyone,
   and add the team's group. Outcome to verify: the connection disappears from model
   choices for people outside the team.
3. **Prepare MCP destinations before enforcing.** Create a destination policy for each
   server already in use, for example `preconfiguration:microsoft_learn` for personal
   actions, then turn on Enforce MCP Destination Allowlist and save. Outcome to verify:
   an action that uses an allowed server still discovers and runs tools, and a new action
   that points elsewhere is refused when saved.
4. **Let one group reach an internal MCP server.** Choose New policy for Group, pick
   A host name, enter the host, select Only for one group, and choose the group. Outcome
   to verify: that group's actions can reach the host, and other groups' cannot.
5. **Open inbound MCP to a team.** On the Inbound MCP settings, select Create a policy
   for any source, add the team's group, and create the policy. Outcome to verify: a
   team member's MCP client lists tools; anyone else's returns none.

## Differences from the classic page

- The classic save turns a governance switch off when the feature it governs is off.
  The V2 page keeps it and shows that it is waiting, so the governance applies as soon as
  the feature is turned on again.
- The classic destination examples suggested `transport:streamable-http`, which never
  matches because transports are stored with an underscore. Use
  `transport:streamable_http`; the V2 editor refuses the hyphenated form.
- The classic inverse of a policy that allowed only some people produced a policy nobody
  passes. The V2 inverse allows everyone except those people.
- An empty allow list with Allow everyone off refuses everyone. It does not fall back to
  allowing everyone.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A governance switch is on but nobody is restricted | The feature policy still allows everyone. | Edit the feature policy: turn off Allow everyone and name the people or groups, or add a block list. |
| Governance Feature Toggles shows Prerequisite missing | A switch is on while the feature it governs is off. | Nothing is enforced for it yet. Turn on the feature, or turn the switch off if you no longer need it. |
| Everyone is refused after turning off Allow everyone | The allow lists are empty. | Add the people or groups who should pass, or turn Allow everyone back on and use the block lists instead. |
| A person in a named public workspace is refused | Only the owner, admins, and document managers count as members for governance. | Name a group workspace instead, or add the person directly. |
| Every remote MCP action stopped working | The allowlist is enforced and no destination policy matches. | Add destination policies for the servers in use, or check the Deployment Restrictions readout for an environment requirement. |
| A transport policy never matches | It uses a hyphen, such as `transport:streamable-http`. | Recreate it with `transport:streamable_http`. |
| An enterprise MCP template is missing from the action editor | Enterprise templates need a policy that names them. | Add a destination policy for `preconfiguration:<id>`; `*` is not enough. |
| An MCP call is blocked | Destination governance or private-address blocking rejected the target. | Review the action's scope, caller eligibility, environment restrictions, and current settings. Admin Settings cannot relax environment restrictions. |
| An inbound MCP client gets no tools | No source policy allows the person. | Create a source policy for `*` or the client's source ID that names the person or one of their groups. |
| An old MCP action is unsupported even for an Admin | The action uses retired stdio configuration. | Explicitly configure a supported remote transport and endpoint, or delete it. Do not weaken destination governance to try to restore stdio. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Agents & Actions settings]({{ '/admin/agents-actions/' | relative_url }})
- [AI Models settings]({{ '/admin/ai-models/' | relative_url }})
- [MCP action reference]({{ '/reference/actions/mcp/' | relative_url }})
- [Security settings]({{ '/admin/security/' | relative_url }})
