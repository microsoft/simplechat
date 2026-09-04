---
layout: page
title: "Orchestration settings"
description: "Orchestration lets a user describe what they want and have SimpleChat work out which documents, searches and steps are needed to answer it."
section: "Administration"
audience: admin
admin_tab: orchestration
---


# Orchestration settings

## What this group controls

Ordinarily a user assembles their own request before asking it. They decide whether to
search documents and which ones, whether to search the web, whether to read URLs, which
saved prompt to apply, which agent to use and which model should answer. Each of those is
a separate control in the chat composer, and getting a good answer depends on the user
having chosen correctly before they had seen any results.

Orchestration replaces that with a plan. The user asks their question, SimpleChat works
out what the question needs, shows the plan it intends to follow, and runs it. Only the
capabilities this deployment already permits can appear in a plan, so turning orchestration
on does not give anyone access to anything they could not already reach by hand.

This group is available in the V2 interface. The classic interface is unaffected by every
setting on this page.

{% include media.html src="admin/orchestration-overview.png" alt="Screenshot placeholder for the Orchestration group in Admin Settings." title="Orchestration settings" capture="Capture the Orchestration group in Admin Settings showing the Chat Orchestration tab." %}

## Why it matters

Two decisions on this page have real consequences and are worth thinking about before
rollout.

The first is **approval**. A plan can run the moment it is made, run after a countdown, or
wait for the user to read it. Reviewing every plan is the most transparent and the
slowest; running automatically is the fastest and gives the user no opportunity to
intervene before work begins. Deployments where a wrong answer is expensive should start
with review and relax later.

The second is **cost**. Planning is an extra model call on messages that need one, and a
plan that analyses several documents costs considerably more than one that searches them.
The limits below are what stop a vaguely worded request turning into an open-ended amount
of work, and they are enforced regardless of what a plan asks for.

## Before you change anything

- Confirm which retrieval capabilities are already enabled. Orchestration can only plan
  around document search, document analysis, document comparison, spreadsheet analysis and
  web search where those are separately enabled.
- Decide whether users should be able to change their own approval mode, or whether the
  deployment default should apply to everyone.
- Consider configuring a smaller planner model. Planning is a short structured task, so it
  does not need the model that writes the answer.

## Chat Orchestration {#chat-orchestration}

### Chat Orchestration {#chat-orchestration-section}

Adds an orchestration mode to the V2 chat composer. While it is on, the capability toggles
and the model, agent and reasoning pickers collapse behind a disclosure, and the user
simply asks.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Chat Orchestration | Makes orchestration mode available in the V2 chat composer. | Off | `enable_chat_orchestration` |

### Plan Approval {#chat-orchestration-approval-section}

Governs how much say a user has between a plan being made and the work starting.

Countdown mode is a middle position worth understanding: the plan appears with a timer, and
doing nothing runs it. It suits users who mostly agree with the plan but want the chance to
stop an obviously wrong one, without a confirmation on every message.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Default approval mode | Selects whether a plan waits for the user, runs after a countdown, or runs immediately. | Review before running | `chat_orchestration_default_approval_mode` |
| Countdown before running | How long the user has to intervene in countdown mode. Supported range is 3-120 seconds. | 10 | `chat_orchestration_timed_approval_seconds` |
| Let users change their own approval mode | When off, everyone stays on the deployment default and the control is hidden from the composer. | On | `chat_orchestration_allow_user_approval_override` |
| Keep the manual composer controls available | Keeps the document, web, model and agent pickers reachable behind a disclosure. Anything chosen there constrains the plan rather than being ignored. | On | `chat_orchestration_show_manual_controls` |

### Capabilities {#chat-orchestration-capabilities-section}

Narrows what a plan may contain, below whatever the rest of the deployment already allows.

Leaving every capability selected is the normal state and means "whatever is otherwise
enabled". Clearing one keeps it out of plans even where it remains available to users
working by hand, which is how a deployment can adopt orchestration for search while
continuing to require deliberate action for document analysis.

Answering is always available and cannot be cleared, because a plan has to end somewhere.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Capabilities | Restricts which capabilities a plan may use. An empty selection means every capability the other settings already permit. | All | `chat_orchestration_enabled_capabilities` |

### Limits {#chat-orchestration-limits-section}

Bounds on a single run.

The two ledger settings decide how much of a conversation's earlier work the planner can
see. This is what lets a follow-up question reuse what an earlier turn already found
instead of searching for it again, and what stops the assistant asking a question the user
has already answered. Setting the run count to zero makes every turn plan from scratch.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Maximum steps in a plan | Caps how much work one plan may describe. Supported range is 1-30. | 8 | `chat_orchestration_max_steps` |
| Maximum re-plans per run | Limits how often a step may send the plan back to be reconsidered after discovering something. Supported range is 0-5. | 2 | `chat_orchestration_max_replans` |
| Step timeout | How long a single step may run before it is abandoned. Supported range is 30-1800 seconds. | 180 | `chat_orchestration_step_timeout_seconds` |
| Run timeout | How long a whole run may take before it is abandoned. Supported range is 60-7200 seconds. | 900 | `chat_orchestration_total_timeout_seconds` |
| Earlier runs shown to the planner | How many of the conversation's previous runs the planner can see. Zero makes every turn plan from scratch. Supported range is 0-50. | 10 | `chat_orchestration_ledger_max_runs` |
| Earlier-run summary size | Caps the size of that summary. Older runs lose their detail first when the budget is reached. Supported range is 1024-131072 bytes. | 16384 | `chat_orchestration_ledger_max_bytes` |

### Planner Model {#chat-orchestration-planner-model-section}

Selects the model that writes plans.

Planning is a short, structured task rather than a conversational one, so a smaller and
faster deployment usually does it well and costs less per message than the model that
writes the answer. Leaving the deployment blank plans with the deployment's default chat
model, which means orchestration works as soon as it is switched on.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Planner deployment name | Names the deployment used for planning. Blank uses the default chat model. | Empty | `chat_orchestration_planner_deployment` |
| Planner model id | Identifies the model when planning through a configured model endpoint. | Empty | `chat_orchestration_planner_model_id` |
| Planner model endpoint id | Identifies the endpoint when planning through a configured model endpoint rather than the default deployment. | Empty | `chat_orchestration_planner_model_endpoint_id` |
| Planner model provider | Identifies the provider when planning through a configured model endpoint. | Empty | `chat_orchestration_planner_model_provider` |

## Common tasks

1. **Introduce orchestration to a pilot group.** Enable Chat Orchestration, leave the
   default approval mode on review, and leave the manual controls available. Outcome to
   verify: pilot users see an orchestration control in the V2 composer, and a plan appears
   for review before any work runs.

2. **Reduce planning cost.** Set a smaller planner deployment. Outcome to verify: plans are
   still produced for document questions, and the planner deployment shows the traffic.

3. **Adopt orchestration for search only.** Clear document analysis and document comparison
   in Capabilities. Outcome to verify: plans use document search and answering, and never
   propose analysing a whole document.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| No orchestration control appears in chat | The setting is off, or the user is in the classic interface. | Confirm Enable Chat Orchestration is on, and that the user is on a V2 chat page. |
| Plans never mention documents | No workspace capability is enabled, or nothing in the user's documents matched the question. | Confirm at least one workspace type is enabled, and that the user has documents that have finished processing. |
| Every plan is a single answering step | Capabilities are narrowed to answering only, or the retrieval capabilities are disabled elsewhere. | Review Capabilities on this page, then confirm document search and web search are enabled in their own settings groups. |
| A plan is smaller than expected | The step cap trimmed it. | Raise Maximum steps in a plan, or ask a narrower question. |
| A question is asked that was already answered | The ledger is disabled or too small to reach the earlier turn. | Raise Earlier runs shown to the planner, and confirm the summary size is not set to its minimum. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Chat settings]({{ '/admin/chat/' | relative_url }})
- [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
- [Workflow settings]({{ '/admin/workflow/' | relative_url }})
