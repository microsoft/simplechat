---
layout: page
title: "Create an agent with actions"
description: "Attach approved actions to an agent so it can use tools while answering."
section: "Guides"
audience: user
---

## What this does

This guide connects an existing action to an agent and narrows what the agent can do with it. The result is an assistant with both instructions and approved tool access.

{% include media.html type="video"
                      title="Create an agent with actions walkthrough"
                      poster="video-posters/guide-create-an-agent-with-actions.png"
                      capture="Recording planned. Show create an agent with actions end to end and explain why this task helps a user." %}

## Why you would use this

Binding an action to an agent turns a broad tool into a safer task assistant. Use it for jobs like querying a known reporting source or calling an approved API; avoid it when the action exposes more access than the agent's job requires.

## Before you start

- `enable_semantic_kernel` must be on, and the workspace must allow agents and actions; see [Agents settings]({{ '/admin/agents-actions/' | relative_url }}).
- Create and test the action first.
- Decide which capabilities the agent may use before attaching the action.

## Steps

1. Open the workspace that owns the agent.
2. Open **Your Agents** or **Agents** and create or edit an agent.
3. Complete **Basic Information** and **Model & Connection**.

{% include media.html src="guides/create-an-agent-with-actions-step-3.png"
                      alt="The Actions step of the Add Agent wizard showing searchable action cards for document search, Microsoft Graph, and a Yamcs simulation, above an empty Selected Actions panel."
                      title="Create an agent with actions step 3"
                      capture="Capture the create an agent with actions task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. On **Actions**, select the action you want the agent to use.
5. If capability controls appear, enable only the operations this agent needs.
6. In **Instructions**, explain when to use the action and when to answer without it.

{% include media.html src="guides/create-an-agent-with-actions-step-6.png"
                      alt="The Instructions step of the Add Agent wizard, showing the Selected Actions and Knowledge summary bar with its counts, the Instruction Brief box, a Draft Instructions button, and the agent instructions editor."
                      title="Create an agent with actions step 6"
                      capture="Capture the create an agent with actions task at this step in SimpleChat with realistic sample data and redact secrets." %}

7. Use `#` references from **Selected Actions & Knowledge** when helpful, then save the agent.

## Verify it worked

In chat, select the agent and ask for a task that requires the action. The response should follow the agent instructions and use the attached action only when appropriate.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The action is not listed | It is not in the same allowed scope or actions are disabled | Confirm the action exists in the workspace and governance allows it. |
| A Foundry agent cannot attach actions | Foundry agents cannot attach local SimpleChat actions | Use a **Local** agent for SimpleChat actions. |

## Related

- [Create an action]({{ '/guides/create-an-action/' | relative_url }})
- [Create an agent]({{ '/guides/create-an-agent/' | relative_url }})
- [Agents settings]({{ '/admin/agents-actions/' | relative_url }})
