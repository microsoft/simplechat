---
layout: page
title: "Create an agent"
description: "Build a reusable assistant with a clear role, model, knowledge, and instructions."
section: "Guides"
audience: user
---

## What this does

An agent is a specialized assistant that keeps the same role, instructions, knowledge choices, and optional tools every time someone uses it. This guide creates a local workspace agent that can be selected from chat.

{% include media.html type="video"
                      title="Create an agent walkthrough"
                      poster="video-posters/guide-create-an-agent.png"
                      capture="Recording planned. Show create an agent end to end and explain why this task helps a user." %}

## Why you would use this

Create an agent when a task benefits from consistent behavior, such as policy review, proposal help, research assistance, or workspace-specific expertise. It reduces prompt rewriting and makes approved instructions reusable; it is not needed for a one-time question or for bypassing document permissions.

## Before you start

- Admins must enable `enable_semantic_kernel`; workspace agents also require `per_user_semantic_kernel` and `allow_user_agents` or `allow_group_agents`; see [Agents settings]({{ '/admin/agents-actions/' | relative_url }}).
- At least one GPT model endpoint must be configured; see [AI Models]({{ '/admin/ai-models/' | relative_url }}).
- Upload and process workspace documents first if the agent should use assigned knowledge.

## Steps

1. Open **Personal Workspace** or the target **Group Workspace**.
2. Choose **Your Agents** or the **Agents** tab.
3. Select **New Agent**.

{% include media.html src="guides/create-an-agent-step-3.png"
                      alt="Screenshot showing create an agent step 3."
                      title="Create an agent step 3"
                      capture="Capture the create an agent task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Choose **Local** in **Agent Type** unless an admin told you to use a Foundry option.
5. In **Basic Information**, enter **Display Name**, **Description**, optional **Tags**, and an icon.
6. In **Model & Connection**, select the model or connection for the workspace.
7. In **Assigned Knowledge**, enable **Restrict this agent to assigned workspace knowledge** only when the agent needs a defined document pool.
8. In **Instructions**, write **Agent Instructions** or use **Instruction Brief** and **Draft Instructions**.

{% include media.html src="guides/create-an-agent-step-8.png"
                      alt="Screenshot showing create an agent step 8."
                      title="Create an agent step 8"
                      capture="Capture the create an agent task at this step in SimpleChat with realistic sample data and redact secrets." %}

9. Review **Summary** and save the agent.

## Verify it worked

The agent appears in the Agents list. In chat, select **Agents**, open **Select an Agent**, and confirm your new agent is available.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **New Agent** is not shown | Personal or group agents are disabled by governance | Ask an admin to enable the relevant agent scope. |
| The agent cannot use expected documents | Assigned knowledge is empty or documents are not processed | Add source workspaces, tags, or specific documents and confirm **Active Documents**. |

## Related

- [Create an action]({{ '/guides/create-an-action/' | relative_url }})
- [Create an agent with actions]({{ '/guides/create-an-agent-with-actions/' | relative_url }})
- [Agents settings]({{ '/admin/agents-actions/' | relative_url }})
