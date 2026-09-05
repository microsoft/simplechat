---
layout: page
title: "Call another agent"
description: "Connect a coordinating agent to approved specialists without sharing its whole conversation."
section: "Guides"
audience: user
version: "0.261.093"
---

## What this does

An agent can use another agent as an action. The first agent decides when to
delegate, supplies the task and relevant context, and uses the returned result
to finish its answer.

Implemented in version: **0.261.093**, recorded in
`application/single_app/config.py`.

## Prepare the specialist

Create or choose an agent with a clear responsibility, such as interpreting a
policy or analyzing financial data. Configure its own instructions, model,
knowledge, and tools. These belong to the specialist rather than being inherited
from the agent that calls it.

Use a target in the same workspace, or a global target permitted by the
deployment's workspace and governance settings. Group management requires the
appropriate group role; only administrators manage global configuration.

## Connect the agents

1. Create a **Call agent** action and select the specialist from the target list.
2. Give the action a name and description that explain the specialist's job.
3. Save the action. No model call or connection test is needed to save it.
4. Attach the saved action to the local agent that should coordinate the work.
5. Describe when to delegate in that agent's instructions. For example:
   "Ask the policy specialist to interpret ambiguous policy clauses. Give it the
   specific clause and the question, then explain its answer to the user."
6. Select the coordinating agent in chat and ask for a task that needs the specialist.

The specialist's result is a tool result; the coordinating agent still produces
the final response. Activity identifies the delegated call and retains source
citations when the target supplies them.

## Where to configure it

In the **classic interface**, use the normal action wizard and the agent's
**Actions** step in the personal workspace, group workspace, or admin area.

In **V2**, personal Actions and Agents include focused delegation controls.
The Groups page provides group selection and delegation management without
switching the active workspace. The admin Agents & Actions area provides the
equivalent controls for global agents. Other connector configuration and
unrelated group management remain in their existing interfaces.

Owned Call agent actions can also be deleted in V2 after confirmation. Deleting
an action stops future calls through that action; it does not rewrite agents or
roll back work the target already performed.

V2 binding updates change only the selected Call agent actions. They preserve
other attached actions, model settings, instructions, and assigned knowledge.
If someone changes the agent while it is open, reload before saving again.

## Decide what to share

The caller supplies the delegated task and any additional context. The complete
conversation, parent instructions, and attachments are not automatically
forwarded. Include only what the specialist needs.

The target may use its own authorized actions, including actions with write
effects. Delegation does not remove those actions' permission or approval
requirements.

## Nested delegation and failures

A specialist may call its own configured specialists. The runtime rejects loops
and enforces 3 delegation levels, 10 delegated attempts per root turn, and a
120-second deadline per call. A workflow's root agent execution has its own
budget; orchestration agent steps in the same turn share a budget.

Unavailable targets, denied access, authentication requirements, and exhausted
limits are reported rather than replaced with a different agent. Stop/cancel
propagates to local nested execution, but already completed external actions
cannot be rolled back by cancelling the chat.

## Related

- [Call agent action reference]({{ '/reference/actions/agent/' | relative_url }})
- [Create an agent with actions]({{ '/guides/create-an-agent-with-actions/' | relative_url }})
- [Agents & Actions settings]({{ '/admin/agents-actions/' | relative_url }})
