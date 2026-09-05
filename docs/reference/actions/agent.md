---
layout: page
title: "Call agent"
description: "Let a local agent delegate a task to an explicitly selected specialist."
section: "Reference"
audience: user
version: "0.261.093"
---

<!-- action-slug: agent -->

## What this action does

**Call agent** gives a local SimpleChat agent a tool for asking one configured
agent to complete a task. The caller receives the specialist's result and can
use it in its own answer. It does not switch the selected chat agent or create a
second conversation.

Implemented in version: **0.261.093**. The application version is recorded in
`application/single_app/config.py`.

## Why and when to use it

Use separate specialists when they need different instructions, models, assigned
knowledge, or approved tools. For example, a report-writing agent can ask a
financial-analysis agent for a calculation, then explain the result in the report.
Give each specialist only the actions needed for its job.

## Configuration

Choose **Call agent** when creating an action, then select its target agent.
The action stores the target's ID and workspace scope, not a copy of its
instructions or connection settings. Renaming the target does not break the
reference; deleting it does not silently select a replacement.

This action needs no external URL, API key, or reusable identity. Saving or
validating the configuration does not run the specialist. Attach the saved
action to a local agent before it can be used.

The tool accepts a task and optional context supplied by the caller. It does not
automatically send the complete chat history, the caller's instructions, or chat
attachments. A local specialist uses its own configuration and authorized tools.

## Permissions and supported targets

| Action/caller scope | Allowed targets |
| --- | --- |
| Personal | The invoking user's personal agents and permitted global agents. |
| Group | Agents in that same group and permitted global agents. |
| Global | Global agents only. |

Global agents in workspaces require the existing global-merge setting and
applicable governance permissions. Access is checked again when the action runs;
an existing reference does not bypass a revoked permission or a disabled agent.

Targets can be local, classic Foundry, new Foundry, or Foundry workflow agents.
Foundry-backed targets keep their tools in Foundry: they cannot attach local
SimpleChat Call agent actions themselves. Their configured authentication still
applies, including any delegated-user sign-in requirements.

## Execution limits

Nested calls share a maximum of **10 delegated attempts per root turn**, with at
most **3 delegation levels**. A call has a **120-second deadline**, including any
calls it makes in turn. Self-calls and ancestor loops are rejected.

The same rules apply to chat, streaming chat, agent workflows, and V2
orchestration. Local cancellation stops waiting for nested work, but it cannot
undo a write already performed by a tool or guarantee that a remote provider
rolls back an accepted request.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| A target is missing | Confirm its scope, enabled state, group membership, global-merge setting, and governance permissions. |
| An existing action no longer works | The target or action may have been deleted, disabled, or made inaccessible. Select a permitted target rather than relying on its old name. |
| A call is rejected as a loop | Remove the path that calls an ancestor, or give the specialist a narrower set of agent actions. |
| A workflow reports authentication is needed | The target requires delegated credentials that are not available to that execution. Do not replace them with a more privileged identity to bypass the requirement. |
| A binding save conflicts | Reload the agent's current action list before retrying; another editor changed it. |

## Related

- [Call another agent]({{ '/guides/call-another-agent/' | relative_url }})
- [Create an agent with actions]({{ '/guides/create-an-agent-with-actions/' | relative_url }})
- [Agents & Actions settings]({{ '/admin/agents-actions/' | relative_url }})
