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

Consider approval, cost and action access before rollout.

The first is **approval**. A plan can run the moment it is made, run after a countdown, or
wait for the user to read it. Reviewing every plan is the most transparent and the
slowest; running automatically is the fastest and gives the user no opportunity to
intervene before work begins. Deployments where a wrong answer is expensive should start
with review and relax later.

The second is **cost**. Planning is an extra model call on messages that need one, and a
plan that analyses several documents costs considerably more than one that searches them.
The limits below are what stop a vaguely worded request turning into an open-ended amount
of work, and they are enforced regardless of what a plan asks for.

**Action access** is a separate, default-off opt-in added in version **0.261.096**. It lets
a plan use an existing action without loading a configured agent. Its focused function
loop can still make model calls, and the action retains its existing behavior and
governance; this is not a read-only mode.

## Before you change anything

- Confirm which knowledge capabilities are already enabled. Orchestration can only plan
  around document search, document analysis, document comparison, spreadsheet analysis,
  web search, reading linked pages, deep research, agents and actions where those are
  separately enabled.
- Note that reading linked pages and deep research are additionally restricted by app role
  where your deployment requires it. A plan will not propose a capability the individual
  user could not reach by hand.
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

From version **0.261.101**, a user's approval selection is saved to their account.
When overrides are allowed, that selection survives chat navigation, reloads, and
future visits from another device. The deployment default applies to users who have
not chosen a mode. Changing that default does not replace an existing user choice.

Disabling user overrides enforces the deployment default without erasing saved
preferences; those preferences apply again if overrides are re-enabled. When an
override is allowed but preferences cannot be loaded, orchestration waits for a retry
rather than risking a different approval mode. The draft remains editable, and
ordinary chat is still available by switching Orchestrate off.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Default approval mode | Determines whether a plan waits for review, runs after a countdown, or runs immediately when the user has no saved choice or overrides are disabled. | Review before running | `chat_orchestration_default_approval_mode` |
| Countdown before running | How long the user has to intervene in countdown mode. Supported range is 3-120 seconds. | 10 | `chat_orchestration_timed_approval_seconds` |
| Let users change their own approval mode | When off, everyone stays on the deployment default and the control is hidden from the composer. | On | `chat_orchestration_allow_user_approval_override` |
| Keep the manual composer controls available | Keeps the document, web, model and agent pickers reachable behind a disclosure. Anything chosen there constrains the plan rather than being ignored. | On | `chat_orchestration_show_manual_controls` |

### Capabilities {#chat-orchestration-capabilities-section}

Narrows what a plan may contain, below whatever the rest of the deployment already allows.

Leaving every capability selected is the normal state and means "whatever is otherwise
enabled". Clearing one keeps it out of plans even where it remains available to users
working by hand, which is how a deployment can adopt orchestration for search while
continuing to require deliberate action for document analysis.

An empty selection also means all otherwise-enabled capabilities. **Use an action**
(`action_invoke`) still requires **Enable Action Access**, even with an empty list or
every capability selected. Selecting the capability alone never opts a deployment in.

Answering is always available and cannot be cleared, because a plan has to end somewhere.

#### How a plan is ordered

Every capability belongs to one of three phases, and a plan always moves through them in
order:

| Phase | What happens | Capabilities |
| --- | --- | --- |
| Gathering knowledge | Finding out what is true | Document search, document analysis, document comparison, spreadsheet analysis, web search, reading linked pages, deep research, Ask an agent, Use an action |
| Reasoning | Saying something about it | Answering |
| Creating | Producing files and other artifacts | Not yet available |

The order is enforced rather than suggested. A plan cannot go looking for something after
it has already answered, because the answer would be written without the very evidence the
later step found.

#### The more expensive capabilities

Three capabilities cost noticeably more than the rest and are each limited to one use per
plan:

- **Deep research** discovers sources through a bounded set of web queries, then reads
  and follows sources. It is useful when broader discovery, detailed reading, or
  reconciling independent evidence would materially improve the answer. Web search is
  still the cheaper choice for focused lookups, even when it returns several sources.
- **Agents** load the agent's tools, connections and instructions before running. That
  setup is the expensive part of the turn, so a plan uses at most one agent.
- **Reading linked pages** uses links the user pasted in the current request or an
  explicitly referenced recent user message, including links supplied in accepted
  clarification answers. A rewritten request, a clarification question, or an earlier
  assistant suggestion cannot authorize a new link.

Reading linked pages and deep research also honour the `UrlAccessUser` and
`DeepResearchUser` app roles where your deployment requires them. A user without the role
does not get the capability, whether they ask by hand or a plan proposes it.

#### How research depth is chosen

The planner compares the expected benefit of additional gathering with its cost. It sees
the request, available capabilities, selected context, and earlier-run summaries. There
is no separate deep-research score or keyword rule that turns a subject into a research
task. A long request, several preferences, or a need for current information does not by
itself require deep research.

A research step includes its own discovery, so a plan does not need a separate web-search
step merely to give research its first sources. Distinct searches can still serve distinct
parts of a request. The step's rationale explains why that depth of gathering is useful;
choosing ordinary search does not start an automatic research-upgrade loop afterward.

Discovery honours the existing Deep Research query limit and source-review limits in
[Knowledge settings]({{ '/admin/knowledge/' | relative_url }}). It does not enable web
search if that capability is disabled globally; permitted supplied sources can still be
reviewed. A query-planning model that is unavailable or fails leaves the existing backup
query generation available. Recovery is recorded in logs, without a user-facing fallback
notice when useful evidence is obtained. If no usable evidence is found, the answer must
not claim that research verified the requested details.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Action Access | Lets the planner choose an existing action the user may already use, without loading a configured agent. | Off | `enable_chat_orchestration_actions`; requires Chat Orchestration and Semantic Kernel. |
| Capabilities | Restricts which capabilities a plan may use. An empty selection means every capability the other settings already permit. | All | `chat_orchestration_enabled_capabilities` |

### Actions and agents

Use **Use an action** for a question that needs a particular integration, such as a ticket
status lookup. The step selects one existing personal, group or global action and may call
several of that action's functions. The planner receives descriptive metadata, not the
action's manifest, credentials or connection settings. The plan's Run view identifies the
selected action by its server-resolved display name and scope, alongside the step's task
and status. The answer's existing Sources panel lists tool calls separately from web
sources.

Use **Ask an agent** when the work depends on that agent's configured instructions,
knowledge or broader procedure. A user-selected agent is not silently replaced with direct
actions, and the planner should not send the same work through both paths. **Call agent**
actions remain on the existing agent path and are excluded from direct action selection.

The opt-in adds no second action allowlist or approval system. Existing scope,
ownership, group membership, enablement and governance rules still determine which actions
are available, and access is checked again when work runs. An action removed or revoked
after planning produces a visible failure rather than a substitute action or agent.

Existing scope settings still apply:

| Action scope | Required scope enablement |
| --- | --- |
| Personal | Personal actions (`allow_user_plugins`) and the personal workspace (`enable_user_workspace`) must be enabled. |
| Group | Group actions (`allow_group_plugins`) and group workspaces (`enable_group_workspaces`) must be enabled; the caller must still be a current member of the group. |
| Global | Global mode must be in use (`per_user_semantic_kernel` off), or **Add Global Agents and Actions to Workspaces** (`merge_global_semantic_kernel_with_workspace`) must include global actions in Workspace Mode. |

These are the existing [Agents and actions settings]({{ '/admin/agents-actions/' | relative_url }}),
not additional orchestration permissions. Global merging does not bypass action-type or
global-item governance.

Action steps gather findings before the normal answering step. This ordering describes
the plan's intent, not a guarantee that an action cannot change data. Existing operation
restrictions and confirmation behavior remain intact. The focused loop can make model
calls and is bounded by the existing `max_auto_invoke_attempts` setting, step/run timeouts
and cancellation. No output phase or composer action picker is added.

### Limits {#chat-orchestration-limits-section}

Bounds on a single run.

The two ledger settings decide how much earlier orchestration activity the planner can
see. They help it recognize previous searches and answered questions, but the ledger is
not the conversation's actual text or a cache of verified source evidence. Setting the run
count to zero disables that activity summary, not recent conversational context.

Recent context uses **Conversation History Limit** from Chat settings. Orchestration
loads eligible user/assistant messages on the server, rounds the count up to an even
number, and applies hard ceilings of 50 messages and 16 KiB of serialized history.
Zero disables historical messages. Masked text and inactive attempts are excluded.
There are no orchestration rolling summaries or cross-chat memory.

The contextualized request and its history are retained with each plan, so all approval
modes interpret the same request. If a referenced message is edited or hidden before
execution or synthesis, the user must create a new plan rather than run against stale
context.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Maximum steps in a plan | Caps how much work one plan may describe. Supported range is 1-30. | 8 | `chat_orchestration_max_steps` |
| Maximum re-plans per run | Limits how often a step may send the plan back to be reconsidered after discovering something. Supported range is 0-5. | 2 | `chat_orchestration_max_replans` |
| Step timeout | How long a single step may run before it is abandoned. Supported range is 30-1800 seconds. | 180 | `chat_orchestration_step_timeout_seconds` |
| Run timeout | How long a whole run may take before it is abandoned. Supported range is 60-7200 seconds. | 900 | `chat_orchestration_total_timeout_seconds` |
| Earlier runs shown to the planner | How many previous run summaries the planner can see. Zero disables the activity ledger, not recent message history. Supported range is 0-50. | 10 | `chat_orchestration_ledger_max_runs` |
| Earlier-run summary size | Caps the size of that summary. Older runs lose their detail first when the budget is reached. Supported range is 1024-131072 bytes. | 16384 | `chat_orchestration_ledger_max_bytes` |

### Planner Model {#chat-orchestration-planner-model-section}

Selects the model that writes plans.

Planning is a short, structured task rather than a conversational one, so a smaller and
faster deployment usually does it well and costs less per message than the model that
writes the answer. Since **0.261.102**, leaving all planner fields blank uses the model
chosen in **Manual controls** first, then the administrator's default model connection,
rather than an unrelated legacy GPT deployment. Classic chat/APIM settings remain the
fallback when no model-connection selection or default applies.

A dedicated planner remains independent of the model that writes the answer. For a
configured model connection, supply its endpoint and model IDs; the deployment and
provider, when supplied, must agree with that selection. Model access is checked for
the requesting user. A deployment-only override uses the classic chat/APIM connection.

The answer choice is saved with the plan and checked again when it runs. Changing the
admin default during approval does not switch that answer to a different model.
If the saved model is no longer available to the user, execution stops with a model
availability error rather than silently falling back to GPT-4o.

The same deployment resolves substantive follow-ups before retrieval. This adds a small
completion when usable conversation history or clarification answers are present.
First turns without history and simple acknowledgments skip that call.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Planner deployment name | Names a separate planning deployment without changing the answer model. When all planner fields are blank, planning uses the manual selection or admin default. | Empty | `chat_orchestration_planner_deployment` |
| Planner model id | Identifies the model when planning through a configured model endpoint. | Empty | `chat_orchestration_planner_model_id` |
| Planner model endpoint id | Identifies the endpoint when planning through a configured model endpoint rather than the default deployment. | Empty | `chat_orchestration_planner_model_endpoint_id` |
| Planner model provider | Identifies the provider when planning through a configured model endpoint. | Empty | `chat_orchestration_planner_model_provider` |

## Run history and switching devices

Every plan, every step and every result is stored against the conversation, not against
the browser that produced it. There is nothing to configure here, but it changes what
users can expect, so it is worth knowing when you answer questions about it.

Opening a conversation on a second device rebuilds the orchestration panel from what the
server holds. A user who plans on a laptop and then opens the same conversation on a
phone sees the same list of runs, can expand any of them, and can read the steps and
results of a run they were not present for. Runs opened this way are shown as a record:
they can be read but not edited or run again, because they have already happened.

A plan that was still waiting for approval when the user moved is the one case that stays
actionable. It reappears as a plan the user can approve, edit or discard, so a plan is
never stranded on a device the user has walked away from. Two things are deliberately
adjusted when this happens. A plan that had a countdown is restored without one, so
nothing starts running on a device where nobody was watching. And if the plan was in fact
approved elsewhere in the meantime, approving it again is refused rather than run twice,
and the conversation reloads to show the answer that already exists.

A run that was interrupted — the browser closed, the device slept, the network dropped
mid-run — is shown as interrupted rather than silently disappearing or appearing to still
be working.

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

4. **Allow direct use of an existing integration.** Confirm Semantic Kernel and the
   action's existing scope/governance permissions, then enable Action Access. Include
   **Use an action** if Capabilities is narrowed. Ask a question that needs the integration;
   review its action name, scope and task in the plan before running it. Verify the step's
   findings reach the answer without selecting a configured agent.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| No orchestration control appears in chat | The setting is off, or the user is in the classic interface. | Confirm Enable Chat Orchestration is on, and that the user is on a V2 chat page. |
| Plans never mention documents | No workspace capability is enabled, or nothing in the user's documents matched the question. | Confirm at least one workspace type is enabled, and that the user has documents that have finished processing. |
| Every plan is a single answering step | Capabilities are narrowed to answering only, or the retrieval capabilities are disabled elsewhere. | Review Capabilities on this page, then confirm document search and web search are enabled in their own settings groups. |
| A plan is smaller than expected | The step cap trimmed it. | Raise Maximum steps in a plan, or ask a narrower question. |
| A follow-up loses its subject | The relevant message is outside the history window, masked, inactive, or truncated. | Check Conversation History Limit in Chat settings and whether the earlier turn is still eligible. Repeat the missing detail if it is outside the retained context. |
| A question is asked that was already answered | The earlier answer may be outside retained message history and the activity ledger. | Check the history window and ledger limits; the ledger alone does not contain the full earlier answer. |
| A pending plan reports changed conversation context | A referenced message or its visibility changed after planning. | Create a new plan using the current conversation. |
| Plans never propose deep research or reading a link | The user does not hold the required app role, or the capability is disabled in its own settings group. | Confirm the user holds `DeepResearchUser` or `UrlAccessUser` where your deployment requires them, and that the capability is enabled outside this page. |
| Plans never propose an agent | Semantic Kernel is off, the user has turned agents off in their own settings, or the user has no agent they can reach. | Confirm Semantic Kernel is enabled, then check the user's own agent setting and that at least one agent is shared with them. |
| Plans never propose Use an action | Action Access is off, Semantic Kernel is off, the capability is excluded, or no eligible action is available to this user. | Check the opt-in and capability selection, then the existing action scope and governance. Call agent actions are not eligible for direct use. |
| An action step fails after plan approval | The action or its access changed, or its model/tool connection could not run. | Check current action access and configuration. Review the visible step failure; the run does not silently switch to an agent or another action. |
| A plan proposed reading a link but found nothing | The link was not available in the eligible user-authored context. | Paste the URL into the current request. Assistant-generated links and omitted historical text do not authorize page reads. |
| Earlier runs are missing after switching devices | The conversation list has loaded but its run history has not been fetched yet, or the fetch failed. | The orchestration panel shows its own loading and retry states. If retrying keeps failing, check that the user can reach `/api/v2/orchestration/runs` and is the owner of the conversation. |
| A restored plan will not run | It was already approved on the other device. | This is expected. The conversation reloads to show the answer that run produced. |
| A run is shown as interrupted | The browser or device that started it went away before the run finished. | Ask the user to send the question again. An interrupted run is a record of what happened, not a run that can be continued. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Chat settings]({{ '/admin/chat/' | relative_url }})
- [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
- [Agents and actions settings]({{ '/admin/agents-actions/' | relative_url }})
- [Create an action]({{ '/guides/create-an-action/' | relative_url }})
- [Actions reference]({{ '/reference/actions/' | relative_url }})
- [Workflow settings]({{ '/admin/workflow/' | relative_url }})
