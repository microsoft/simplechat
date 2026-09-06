---
layout: page
title: "Build agents and actions in My Workspace"
description: "Configure a reusable assistant and its approved tools without leaving the V2 workspace."
section: "Guides"
audience: user
version: "0.261.096"
---

## What this does

Use **My Workspace > Agents** to give an assistant a lasting role, model, knowledge
pool, and approved tools. Use **My Workspace > Actions** to configure those tools
once and reuse them across agents. Both open full-page editors in V2 instead of
the classic popup wizards.

Implemented in version: **0.261.096**, recorded in
`application/single_app/config.py`.

This guide concerns your personal workspace. Group and administrator management
continue to use their existing interfaces and permissions.

## Decide what belongs where

An agent describes a job, such as reviewing a contract against an approved policy.
An action supplies a capability that the job needs, such as searching documents,
querying a database, or calling a specialist agent.

Keep connection and authentication details on the action. Explain when the tool
should be used in the agent's instructions, and narrow the agent's action
capabilities when it does not need every available operation.

The available types depend on your administrator's configuration and governance
policy. A provided resource may be usable without being yours to edit.

## Configure an agent

Start with **New agent**, or use an available example/template as a draft. Choose
Local when SimpleChat should manage the instructions, knowledge, and actions.
Choose a Foundry type when connecting a remote agent or workflow; controls explain
which behavior remains managed in Foundry.

Give the agent a recognizable display name and a description of its responsibility.
Select a permitted model connection. Custom connection details and additional
configuration are available without making them necessary for an ordinary agent.

For a policy-bound assistant, use assigned knowledge to choose the source
workspaces and then narrow that pool with tags or specific documents. Review
the active documents rather than assuming that selecting a tag adds every file
you expected. User-provided context and assigned URL review remain separate
permissions.

Write instructions that say when to use the selected actions and knowledge. The
instruction-brief drafting command can help produce an initial draft; review it
before saving. Action and knowledge references make those instructions more
specific without expanding the agent's permissions.

## Configure an action

**New action** opens the normal type chooser. Select the tool the agent needs,
then configure only the connection, authentication, and capability fields that
apply to that type. For example, OpenAPI actions use a specification, while MCP
actions can discover the server's available tools.

If an OpenAPI specification is hosted at a URL, download it first and import its
content. Direct URL import remains disabled; entering the API's base URL is not
the same operation as downloading its specification.

Use a saved reusable identity where appropriate. A field that reports a stored
secret does not reveal its value; leave it unchanged to keep the credential,
replace it deliberately, or use its explicit clear control.

Connection tests and discovery are separate commands. Saving configuration
does not run the action. If a test fails, resolve the connection or permission
problem rather than assuming that a successful configuration save proves the
remote service is reachable.

## Connect the two without losing a draft

An agent's **Actions** section lists all permitted action types together.
Select an existing action and review its capabilities.

If the needed action does not exist, choose **New action** from that section.
The agent draft stays in this tab's memory while the action editor opens. After
saving the new action, you return to the agent with that action selected.
Save the agent separately to apply the attachment. Cancelling action creation
does not save or replace the agent.

**Call agent** follows this same flow. Choose it as an action type and select its
target; then attach it like any other action. There is no separate Call agent
management section. See [Call another agent]({{ '/guides/call-another-agent/' | relative_url }})
for what context is shared and how nested calls are limited.

## Save and use the agent

Save explicitly when the configuration is ready. Navigation away from an
unfinished editor asks before discarding changes. Failed saves keep the draft
and explain the problem. If another editor changed the record, review the
current configuration before retrying.

Drafts are not browser backups: they are not stored across tab closure or reload.
Keep the tab open when moving from an agent draft to action setup.

After saving, **Use in chat** starts a new conversation with that agent. It does
not change an existing conversation's agent or replace its model configuration
with a manual model selection.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| An agent/action type is unavailable | Check the personal workspace and type-specific governance settings with an administrator. |
| A resource says it is provided | Use it where permitted, but do not expect personal edit/delete controls. |
| An attached resource becomes unavailable | Review the unresolved reference. An unrelated edit should not silently replace it with another resource of the same name. |
| A Foundry agent has no local action controls | Configure tools in Foundry, or choose a Local agent for SimpleChat-managed actions. |
| A save reports a conflict | Keep the draft available, reload/review the current record, and apply the intended changes against that revision. |

## Related

- [Create an agent]({{ '/guides/create-an-agent/' | relative_url }})
- [Create an action]({{ '/guides/create-an-action/' | relative_url }})
- [Create an agent with actions]({{ '/guides/create-an-agent-with-actions/' | relative_url }})
- [Agents and Actions settings]({{ '/admin/agents-actions/' | relative_url }})
