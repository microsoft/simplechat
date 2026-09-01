---
layout: page
title: "Create an action"
description: "Create a reusable tool that an agent can call when chat alone is not enough."
section: "Guides"
audience: user
---

## What this does

An action is a governed tool definition that lets an agent call an API, database, built-in utility, file source, or MCP server. This guide creates an action in a workspace and leaves it ready to attach to an agent.

{% include media.html type="video"
                      title="Create an action walkthrough"
                      poster="video-posters/guide-create-an-action.png"
                      capture="Recording planned. Show create an action end to end and explain why this task helps a user." %}

## Why you would use this

Use an action when a model needs to do more than write an answer, such as query a read-only system or call an approved service. It replaces manual lookups and pasted context, but it is the wrong choice for unrestricted network access, unapproved tools, or secrets that should not be stored in SimpleChat.

## Before you start

- An admin must enable `enable_semantic_kernel` and allow actions with `allow_user_plugins` or `allow_group_plugins`; see [Agents settings]({{ '/admin/agents-actions/' | relative_url }}).
- Workspace actions require `per_user_semantic_kernel` when actions are personal or group scoped.
- Have the OpenAPI file, endpoint, credential, reusable identity, or MCP server details required by the action type.

## Steps

1. Open **Personal Workspace** or the target **Group Workspace**.
2. Choose **Your Actions** or the **Actions** tab.
3. Select **Add Action** or the workspace new action button.

{% include media.html src="guides/create-an-action-step-3.png"
                      alt="The Add Action dialog on Select Type, showing a searchable grid of action type cards including Azure Maps, Blob Storage, Cosmos Query, Databricks, Document Search, Interactive Charts, Log Analytics, Microsoft Graph, and Model Context Protocol."
                      title="Choosing an action type"
                      capture="Capture the create an action task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. On **Select Action Type**, search for the type you need, such as **OpenAPI**, **MCP**, **Log Analytics**, or another enabled card.
5. Enter **Display Name**, review **Name**, and write a **Description** that tells agent authors when to use it.
6. Complete the type-specific configuration, including **OpenAPI Specification File**, **Base URL**, **Authentication Type**, **Reusable Identity**, or MCP discovery fields when shown.

{% include media.html src="guides/create-an-action-step-6.png"
                      alt="Screenshot showing create an action step 6."
                      title="Create an action step 6"
                      capture="Capture the create an action task at this step in SimpleChat with realistic sample data and redact secrets." %}

7. Use **Test Connection** when available, then save the action.

## Verify it worked

The action appears in the Actions list or card view. When you create or edit an agent, it is available on the agent **Actions** step.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The Actions tab is missing | Actions are disabled for your workspace or account | Ask an admin to enable `enable_semantic_kernel` and the matching action scope. |
| **Test Connection** fails | The endpoint, identity, or credential cannot reach the target service | Fix the connection details and test again before saving. |

## Related

- [Create an agent]({{ '/guides/create-an-agent/' | relative_url }})
- [Create an agent with actions]({{ '/guides/create-an-agent-with-actions/' | relative_url }})
- [Agents settings]({{ '/admin/agents-actions/' | relative_url }})
