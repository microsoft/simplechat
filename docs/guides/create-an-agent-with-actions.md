---
layout: page
title: "Create an agent with actions"
description: "Attach approved actions to an agent so it can use tools while answering."
section: "Guides"
audience: user
version: "0.261.347"
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

## Personal agents in V2

In the V2 agent editor, the **Actions** section uses one picker for ordinary
connectors and Call agent actions. Review the selected action's capabilities in
context. **New action** opens the normal action editor and returns to the
retained agent draft after the action is saved; the attachment takes effect only
when you save the agent.

This workflow was implemented in **0.261.096**, recorded in
`application/single_app/config.py`. See the [workspace guide]({{ '/guides/workspace-agents-and-actions/' | relative_url }})
for navigation and unsaved-change behavior.

## Classic interface steps

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

An action can also call another agent. Create a **Call agent** action for the
specialist, attach it here, and explain when the caller should delegate. The
specialist receives the task and explicitly supplied context, not the whole
conversation. See [Call another agent]({{ '/guides/call-another-agent/' | relative_url }}).

## Verify it worked

In chat, select the agent and ask for a task that requires the action. The response should follow the agent instructions and use the attached action only when appropriate.

A shared Yamcs action can require your own identity instead of a shared
credential, starting in **0.261.333** (`application/single_app/config.py`).
When the action is first used, complete the private credential card and choose
**Save and continue**. Do not paste the credential into the agent's instructions
or a chat message. The same card supports authorized direct action
orchestration; creating an agent is not required solely for authentication.
See [Personal action credentials]({{ '/guides/personal-action-credentials/' | relative_url }}).

## Troubleshooting

Since **0.261.347** (`application/single_app/config.py`), classic and V2 chat
identify assigned actions that cannot load before starting a local-agent
response. **Recheck** after fixing the action, keep the message unsent with
**Cancel / choose another agent**, or explicitly **Continue without these
actions** for this request. An editor link appears only when you may edit the
action's owning scope. **Notify owner/admin** sends an optional in-app report;
it does not disclose your question.

Saved action names may contain hyphens. SimpleChat now gives those actions
compatible runtime-only identifiers; you do not need to rename saved actions
or recreate their assignments. Successful loading still does not establish
service sign-in, consent, or successful delivery. Never resend an uncertain
calendar/email operation merely because an availability check passes.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The action is not listed | It is not in the same allowed scope or actions are disabled | Confirm the action exists in the workspace and governance allows it. |
| A Foundry agent cannot attach actions | Foundry agents cannot attach local SimpleChat actions | Use a **Local** agent for SimpleChat actions. |
| Chat identifies unavailable assigned actions | One or more actions failed registration or preparation | Review the named actions, use an authorized editor or report, then recheck. Continue without them only if the remaining capabilities are sufficient. |

## Related

- [Create an action]({{ '/guides/create-an-action/' | relative_url }})
- [Create an agent]({{ '/guides/create-an-agent/' | relative_url }})
- [Agents settings]({{ '/admin/agents-actions/' | relative_url }})
