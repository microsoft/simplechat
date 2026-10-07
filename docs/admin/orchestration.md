---
layout: page
title: "Orchestration settings"
description: "Orchestration lets a user describe what they want and have SimpleChat work out which documents, searches and steps are needed to answer it."
section: "Administration"
audience: admin
admin_tab: orchestration
version: "0.261.140"
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

Adds an orchestration mode to the V2 chat composer. While it is on, capability
toggles and the model, agent, and reasoning pickers collapse behind a **Manual
controls** disclosure. The orchestration model picker offers **Auto - choose per
step**, which selects connected models using catalog suitability, administrator
priority, and favorites, or a specific model to pin. This is separate from automatic
plan approval. See [Model Catalog]({{ '/admin/model-catalog/' | relative_url }}).

Since **0.261.137**, the picker sits under **Manual controls** in the normal model
picker's place (from **0.261.126** it was shown above the message box). Auto is the
default wherever a connected model has a catalog profile that allows per-step
selection and is rated for general answering, and each user's choice is saved to their
account. When **Keep The Manual
Composer Controls Available** is off, users cannot reach the picker, so orchestration
uses Auto (or the default model when Auto cannot be used) regardless of a saved pin.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Chat Orchestration | Makes orchestration mode available in the V2 chat composer. New plans use Gather / Reason / Render whenever this is on. | Off | `enable_chat_orchestration` |

### Single Gather / Reason / Render contract

**Single-contract rollout implemented in version: 0.261.139**, tracked by
`application/single_app/config.py`. Refs
[microsoft/simplechat#1509](https://github.com/microsoft/simplechat/issues/1509).

Gather / Reason / Render is now the only plan architecture. New plans separate
acquiring inputs (**Gather**), preparing reusable results (**Reason**), and
producing requested files or images (**Render**) whenever **Enable Chat
Orchestration** is on. There is no separate preview, harness, admission, or
readiness setting. Stored `enable_chat_orchestration_harness` values are removed
when settings load or save.

Retained results let several representations use the same completed work rather
than repeat analysis for each file. Only explicit Render tasks create
downloadable files; retaining evidence, records or a prepared report is not
itself an export. The roles follow dependencies, not a mandatory three-stage
sequence.

Plans created by an earlier orchestration version no longer open or rerun. They
are omitted from the conversation run list and from the planner's earlier-run
context. Direct attempts to open, edit, retry, restore, continue, cancel, or read
catalog information for one return the standard message: "This plan was created
by an earlier orchestration version and can't be opened or rerun. Start a new
request." Their saved data is still removed when the conversation is deleted.

The [file creation guide](../guides/create-files-with-orchestration.md) explains
how to review shared result bindings, choose compatible representations and
recover one file without repeating completed work.

### Retained external-source authorization

Web search, linked-page reading, deep research, agents, actions and explicit Fact
Memory results use the same authority as classic chat: the app roles in the user's
signed-in session. Since **0.261.209**, orchestration no longer looks up each user in
Microsoft Graph and needs no `Directory.Read.All` permission. Earlier versions
required that application permission, and without it every such step failed with
"A required retained result is unavailable or changed." If you granted
`Directory.Read.All` to the app registration only for orchestration, you can revoke it.

Each access still rechecks conversation ownership, Control Center access
restrictions, capability settings, and agent or action governance. A role change in
Entra ID takes effect when the user's session is refreshed, for example at their next
sign-in, as it does for classic chat.

Since **0.261.270**, agent and action steps trust the signed-in session the way manual
chat does. When the step runs, orchestration checks the user's current access to the
conversation, the run and that exact agent or action, and then runs it as chat would.
It no longer captures and compares the agent's or action's configuration. Editing an
agent or action therefore doesn't invalidate a result it already produced, and a result
stays readable until the user loses access to that agent or action. Web search,
linked-page reading and deep research keep their configuration checks. Earlier versions
compared configuration for agents and actions too. Every Microsoft 365 action step then
failed with "A required retained result is unavailable or changed", and local agents
couldn't run as plan steps.

Work that continues in the background, such as a run recovered after a restart, has
no signed-in session. Its steps can't use web search, linked pages, deep research,
agents or actions, and they ask the user to send the request again. Document-backed
and source-free results are unaffected. Group, workspace, agent and action
governance, and content-screening checks still apply independently. See
[Retained external source access]({{ '/explanation/features/ORCHESTRATION_EXTERNAL_SOURCE_ACCESS/' | relative_url }})
for the server callback boundary.

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

From version **0.261.102**, opening **Edit** on a pending plan stops the countdown and
saves a manual-approval hold for that plan. It stays paused after the editor closes or
the conversation reloads; an explicit **Run** is required. This intervention does not
change the deployment default or the user's approval preference. Immediate Auto plans
still start without an editing window. See
[Review and edit orchestration plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }}).

From version **0.261.212**, a plan that starts a saved workflow always waits for the user
to approve it, whatever the deployment default or the user's own choice. Starting a
workflow begins work that carries on outside the conversation, so neither a countdown nor
Auto ever starts one. The plan card says why the plan is waiting and names each workflow
it would start. Plans that start no workflow follow the approval modes above. See **Run
Workflows From Chat** under [Capabilities](#chat-orchestration-capabilities-section).

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

**Prepare content** (`compose`) controls reusable drafting, structured content,
and the chat answer selected by `final_response`. **Create a file**
(`render_file`) controls explicit exports. If a stored nonempty capability list
still contains the removed `respond` capability, it is read as `compose`, so
narrowed deployments keep answering. The stored list is not rewritten, because
runs saved before the upgrade are bound to the settings they ran under; both
admin pages show **Prepare content** selected, and the next save of the list
stores `compose`. Nothing adds `render_file` or `generate_image`; include those
explicitly when restricted plans should create files or requested images.

Since **0.261.138**, **Generate images** (`generate_image`) lets a plan generate
the images a user asks for, one planned task per image and at most four per plan. The
images appear in the answer and are embedded in DOCX, PDF, and PowerPoint files. It also
requires **Enable Image Generation** and a configured image model; users gain no image
access they did not already have. Clearing it keeps requested images out of plans, and
the plan then lists them as not available with the reason "The capability that produces
this is not enabled for orchestration." Images a plan only suggests remain approval cards,
controlled by image generation alone.

Since **0.261.217**, **Read workflow results** (`workflow_results`) lets a plan
read the stored result of one of the user's own finished personal workflow runs
when the user asks about it, such as "what did my weekly digest find on
Monday?". The plan reads the workflow's latest finished run, or the newest run
that finished on a day the user names in their own time zone, and the answer
uses the run's saved output as notes rather than as a cited source. The workflow
isn't re-run, and a plan reads at most two results. There is no setting for it on
this page: it's offered only while **Use Workflow Results In Chat** is on in
[Workflow settings]({{ '/admin/workflow/' | relative_url }}), to users who may
use personal workflows, in their own private conversations. Reading a result
changes nothing, so it never makes a plan wait for approval. Clearing it keeps
saved results out of plans; **Ask in chat** on a run is not affected.

Since **0.261.239**, **Merge spreadsheets** (`tabular_merge`) combines the rows
of two or more CSV or Excel files into one table, which the plan then delivers as
a CSV or Excel file through **Create a file**. Code appends every row exactly, in
the order the files are listed, and adds a **Source File** column by default; no
model reads or rewrites the rows, so codes such as `007` keep their leading
zeros. Columns may appear in any order. Since **0.261.240**, a merge can also
reconcile files whose columns differ: keep every column, treat differently named
headers as one column, keep only listed columns, leave out files or sheets that
don't fit, read headers below a title row, merge every sheet of a workbook,
remove duplicate rows and sort. Without one of those choices, files whose
columns differ are not merged: the run says so and nothing is created. Merge
never matches rows on a key column the way a lookup or join would.

**Inspect spreadsheets** (`tabular_inspect`), since **0.261.240**, reads the
sheet names, headers, row counts and a few sample rows of CSV or Excel files and
reports how their columns line up, without changing anything. Plans use it to
answer questions about files' structure, and before a merge whose columns may
differ, so **Prepare content** can line up the columns as a column mapping that
the merge checks and applies with code.

**Merge documents** (`document_merge`), since **0.261.245**, joins two or more
PDFs into one PDF, Word documents into one Word document or PowerPoint decks into
one deck, or puts CSV and Excel files on separate sheets of one workbook, which
the plan then delivers through **Create a file**. Code copies the files in the
order listed; no model reads or rewrites them. The merge step checks the merged
file and keeps only a description of it, and **Create a file** assembles the same
files again and delivers the file only if it is identical, so a file that changed
in between is never delivered. Word documents whose fields start other programs
are refused, and PowerPoint actions that start programs or run macros are
removed.

Since **0.261.246**, while both **Merge spreadsheets** and **Merge documents** are
offered, a plan asks whether spreadsheets merged into one Excel file should share
one sheet or keep a sheet each, unless the request already says. Clearing **Merge
documents** keeps that question out of plans, and merged rows always share one
sheet.

All three are offered while **Enable Merge** is on under
[Document Action Capabilities]({{ '/admin/agents-actions/' | relative_url }}#document-action-capabilities-card),
which also sets how many files and rows one chat request may merge or inspect.
Clearing any of them here keeps it out of plans; a narrowed list needs **Inspect
spreadsheets** and **Prepare content** for merges that line up columns, and
**Create a file** to deliver any merged file. See
[Merge files in chat]({{ '/guides/merge-files/' | relative_url }}).

Selecting a capability does not grant source/model access or enable another
feature's prerequisite. Orchestration still publishes truthful delivery status
when composition is not requested, including file-only plans that consume already
retained results.

#### How a plan is ordered

Gather, Reason and Render are roles, not mandatory phase buckets. Named result
bindings and explicit dependencies decide the order, so a plan may gather,
reason, gather again, and then reason from the combined results. The answer is
written by the `compose` step selected by `final_response`; that step cannot be
disabled in the plan editor. Invalid plans are refused rather than repaired by
silently reordering phases, dropping documents, or appending an answer step.

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
[Knowledge settings]({{ '/admin/knowledge/' | relative_url }}), including its query
planning and linked-page planning options, as manual Deep Research does. It does not
enable web search if that capability is disabled globally; permitted supplied sources
can still be reviewed. Before **0.261.209**, those planners, which are on by default,
stopped every orchestrated research step before it started. A query-planning model
that is unavailable or fails leaves the existing backup query generation available. Recovery is recorded in logs, without a user-facing fallback
notice when useful evidence is obtained. If no usable evidence is found, the answer must
not claim that research verified the requested details.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Action Access | Lets the planner choose an existing action the user may already use, without loading a configured agent. | Off | `enable_chat_orchestration_actions`; requires Chat Orchestration and Semantic Kernel. |
| Propose Workflows From Chat | Lets a plan turn a request for recurring or automated work, such as "email me a summary of my week every Monday", into a personal workflow proposal. The proposal appears as a card in the conversation, and no workflow exists until the user approves it there. Proposals are offered only in the user's own private conversations, and only to users who may already create personal workflows. | Off | `enable_chat_orchestration_workflows`; requires Chat Orchestration and personal workflows (`allow_user_workflows`), and the **Propose workflows** capability when the Capabilities list is narrowed. Since **0.261.207** |
| Run Workflows From Chat | Lets a plan start one of the user's saved personal workflows when the user asks for it, such as "run my weekly digest now". A plan that starts a workflow always waits for the user to run it, even when the approval mode would run it automatically or after a countdown, and approving it starts each named workflow once. Runs are offered only in the user's own private conversations, only to users who may already create personal workflows, and only for workflows with durable execution on. It is independent of Propose Workflows From Chat, so either can be on without the other. | Off | `enable_chat_orchestration_workflow_runs`; requires Chat Orchestration and personal workflows (`allow_user_workflows`), and the **Run workflows** capability when the Capabilities list is narrowed. Since **0.261.212** |
| Hand Off Large Work From Chat | Lets a plan hand a request that is too big for one chat plan, such as reviewing hundreds of documents, to a one-time durable workflow. The workflow reviews each document with Analyze and writes one report. The user approves the plan, then approves a hand-off card that names the documents, or says how many matching documents at most, the workflow will review. Accepting the card creates the workflow turned off, so it never runs on a schedule, and starts it once; when the run finishes, its report is posted back into the conversation. Hand-offs are offered only in the user's own private conversations. It is off by default because a hand-off starts background work that keeps running with the user's access after the chat turn ends. | Off | `enable_chat_orchestration_workflow_handoff`; requires Chat Orchestration, personal workflows (`allow_user_workflows`), Propose Workflows From Chat, Run Workflows From Chat and **Use Workflow Results In Chat**, and the **Hand off large work** capability when the Capabilities list is narrowed. Since **0.261.250**; since **0.261.291**, users accept, edit or decline a hand-off on the V2 hand-off card under the answer. |
| Capabilities | Restricts which capabilities a plan may use. An empty selection means every capability the other settings already permit. | All | `chat_orchestration_enabled_capabilities` |

When **Run Workflows From Chat** starts a durable personal workflow, the plan
still ends right away. If **Use Workflow Results In Chat** is also on in
Workflow settings, the server records enough context to post the run's eventual
outcome back to the same private chat later, mark it unread and send one bell
notification. If the chat can no longer take the result, the server posts
nothing and sends one workflow notification instead.

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

Since **0.261.270**, tagging an agent with @ in an Orchestrate message chooses that agent
just as the agent picker does, and tagging a model with @ chooses that model. A chosen
agent is always offered to the planner, even when the user turned agents off in the
classic interface's settings. Local agents run as plan steps, including agents that use
Microsoft 365 actions.

Since **0.261.289**, a chosen agent's step also runs while that setting is off. The
setting is the agents button on the classic chat page (`/chats`). V2 has no control for
it, and it's saved as off for a user whose settings were saved before they turned agents
on, so many V2 users have it off. It still applies to agents the user didn't choose.

Before **0.261.291**, every Ask an agent step was refused just before the agent ran, with
"This step's agent or action isn't available to you right now". The step's access check
accepted only a plain dictionary, and Cosmos DB returns a stored agent as an SDK subclass
of one. Chat without Orchestrate was unaffected.

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
and cancellation. No composer action picker is added.

#### Microsoft 365 actions in plans

Since **0.261.238**, a **Use an action** step can run a Microsoft 365 Calendar, Email,
OneDrive, SharePoint Online or legacy Microsoft Graph action. Earlier versions refused every
Microsoft 365 call in a plan with `m365_context_required`, before reaching Microsoft Graph,
and still reported the step as completed. From 0.261.238 until **0.261.270**, these steps
failed with "A required retained result is unavailable or changed", because the step's
configuration check couldn't see the action's Microsoft 365 selection. See
[Retained external-source authorization](#retained-external-source-authorization).

Each such step gets its own Microsoft 365 request, the same kind chat creates, with these
limits:

- **The signed-in user's own access.** The step reads as the person who sent the request,
  never as an action owner, the app, or a workflow Run as account. Their delegated sign-in
  is checked before the step's model or any Microsoft Graph call. When it is missing or
  expired, the step stops with "Microsoft 365 needs you to sign in or grant access", and
  the V2 run details offer **Connect Microsoft 365** for the sources the step needs.
- **Only the selected action.** The request selects only the step's saved action, read
  again from storage on each call. Its own capabilities and current governance apply.
- **Read only.** Send mail, calendar invitations and mark-as-read are removed from a plan
  step, even when the action enables them. An action that enables only those functions
  stops with "Plans can only read Microsoft 365 data".
- **In a shared conversation, asking is consent.** Since **0.261.270**, a step in a shared
  conversation reads for that conversation's participants. The user's own request counts
  as consent to share what the step reads with them, so no source-sharing approval waits.
  Each request and source is recorded as a `shared_by_request` audit event. Workflow Run
  as approvals, and approvals to share earlier answers' Microsoft 365 history, still ask.
  Earlier versions stopped the step before it read anything.
- **Approvals don't resume plans.** A step that needs an approval, such as deeper file
  analysis, stops and links to Approvals. The user decides there and then selects **Retry
  from failed step**. A retried step reuses its request, so the decision applies while
  the action is unchanged.

A refused Microsoft 365 call stops the step instead of becoming findings that the model
reports as data. Ordinary Microsoft Graph outcomes, such as nothing found or throttling,
are still findings. An answer that used Microsoft 365 keeps the tool calls in its sources,
so sharing the conversation later asks the user to approve Microsoft 365 history, as it
does for a chat answer. Since **0.261.270**, an **Ask an agent** step whose agent uses
Microsoft 365 actions gets a step request for that agent's own Microsoft 365 actions, with
the same limits. An agent without Microsoft 365 actions gets none.

### Shared conversations

Since **0.261.270**, Orchestrate applies the same rule in a shared conversation that a
manual send does:

- A message that addresses only people, such as "@Ada can you check this?", is posted to
  them. It never reaches a model or a plan.
- A message that addresses the assistant is planned. It addresses the assistant when it
  tags an agent or model with @, or uses the agent picker, a saved prompt or a source
  toggle.
- Only the person who started the shared conversation plans in it. When another
  participant asks the assistant with Orchestrate on, they get a classic answer, the same
  as with Orchestrate off.
- The question and the run's final answer are posted to the shared thread, replying to
  each other, and every participant sees them arrive.

Plans run in a hidden conversation that has the shared conversation's ID and workspace
lock and belongs to the person who started it. Memory and source rules treat it as shared,
so plans there never propose, run or read personal workflows. Anything that looks up the
shared conversation by ID, such as reopening it, images, exports or uploads, still gets
the shared conversation. Deleting the shared conversation, by its owner or by retention,
deletes the plans too. A co-owner who didn't start the conversation removes it without
deleting its creator's plans.

The question and answer are posted only while the person who started the conversation is
still a participant, and while a group conversation still allows chat. When a run
finishes later than its first answer, for example after a waiting step, the shared copy
of the answer is updated in place.

Current limits:

- Other participants see the question and the answer, not the plan card or run details.
- Files, images and charts that a plan creates stay with the person who started the
  conversation. The shared copy of the answer carries its text and citations.
- The planner reads earlier planned turns of the conversation, not messages that
  participants exchanged or that the classic assistant answered.

Before 0.261.270, Orchestrate planned every message in a shared conversation, including
ones that addressed only people, and kept the question and answer in a private copy that
other participants never saw. Those private copies no longer appear in conversation lists.
The copy that belongs to the person who started the conversation becomes its hidden plan
conversation, and its earlier turns aren't posted to the shared thread.

### Charts, diagrams, and images in answers

Since **0.261.132**, orchestrated answers can include inline charts, Mermaid diagrams, and
image proposal cards, without an extra setting:

- A chart of data an action retrieves is drawn by a short chart step inside that action
  step, from the exact returned rows. The chart step can use only the built-in chart tools,
  so it cannot call the integration again, and it is not counted against
  `max_auto_invoke_attempts`. It adds one model call per charted step.
- Mermaid diagrams are written by the answer step.
- Image proposal cards appear only when **Image generation** (`enable_image_generation`) is
  on, and each image is generated only after the user approves its card. The composer's
  Image control is usable in Orchestrate and asks for at least one card.

Users' saved Instruction memories shape these visuals; for example, a saved "no charts"
instruction stops charts they did not ask for. Since **0.261.134**, Gather/Reason/Render
Gather / Reason / Render plans produce these visuals too: the planner names them on the task that
authors them, and a charted action step works under orchestration invocation capture
without calling the integration again.

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
| Step timeout | How long a single step may run before it is abandoned. Since **0.261.141** it also bounds file rendering: a render still producing its file at the limit is stopped before the file is saved, and the step's failure message points admins to this setting. A step whose work had already finished when the limit passed, such as a file already being saved, keeps its result. Raise it when large Word, PowerPoint, or PDF files routinely stop at the limit. Supported range is 30-1800 seconds. | 180 | `chat_orchestration_step_timeout_seconds` |
| Run timeout | How long a whole run may take before it is abandoned. Supported range is 60-7200 seconds. | 900 | `chat_orchestration_total_timeout_seconds` |
| Earlier runs shown to the planner | How many previous run summaries the planner can see. Zero disables the activity ledger, not recent message history. Supported range is 0-50. | 10 | `chat_orchestration_ledger_max_runs` |
| Earlier-run summary size | Caps the size of that summary. Older runs lose their detail first when the budget is reached. Supported range is 1024-131072 bytes. | 16384 | `chat_orchestration_ledger_max_bytes` |
| Workflows created from chat per user | Caps how many workflows a chat plan may create for one user, so a conversation cannot fill a workspace with workflows. Workflows a user builds in the workflow editor never count toward it, and deleting a workflow created from chat frees its place. Supported range is 1-100. | 20 | `chat_orchestration_max_workflows_per_user`; since **0.261.202** |
| Minimum schedule interval for workflows created from chat | The shortest repeat interval a chat plan may give a workflow it creates. When the general **Workflow Minimum Schedule Interval** on the Workflow tab is longer, that one applies instead. Daily, weekly and monthly schedules always pass. It is checked when the workflow is created; the owner's later edits follow the general minimum only. Supported range is 60-86,400 seconds. | 3600 | `chat_orchestration_min_workflow_interval_seconds`; since **0.261.202** |
| Hand-offs from chat per user per day | Caps how many hand-offs one user may accept from chat in any rolling 24 hours. Each hand-off creates a one-time workflow and starts a durable run, so this bounds how much background work one user can start from chat. It counts the hand-off workflows that still exist, so deleting one frees its place, and hand-off workflows never count toward **Workflows created from chat per user**. It applies only when **Hand Off Large Work From Chat** is on. Supported range is 1-100. | 5 | `chat_orchestration_max_workflow_handoffs_per_day`; since **0.261.250** |

Since **0.261.202**, **Workflows created from chat per user** and **Minimum schedule
interval for workflows created from chat** are enforced by the workflow draft service
that chat orchestration uses to turn a plan into a saved workflow. Workflows created any
other way are not affected by either one.

### Planner Model {#chat-orchestration-planner-model-section}

Selects the model that writes plans.

Planning is a short, structured task rather than a conversational one, so a smaller and
faster deployment usually does it well and costs less per message than the model that
writes the answer. Since **0.261.103**, leaving all planner fields blank uses the model
chosen in **Manual controls** first, then the administrator's default model connection,
rather than an unrelated legacy GPT deployment. Classic chat/APIM settings remain the
fallback when no model-connection selection or default applies.

A dedicated planner remains independent of the model that writes the answer. For a
configured model connection, supply its endpoint and model IDs; the deployment and
provider, when supplied, must agree with that selection. Model access is checked for
the requesting user. A deployment-only override uses the classic chat/APIM connection.

Since **0.261.137**, both admin pages set this with one **Planner model** dropdown
instead of four text boxes. The dropdown lists the same models the default chat model
picker offers: the chat models your AI Connections publish, or the classic
(single-endpoint or APIM) deployments when connections are off. **Use the answer
model (default)** leaves all four settings blank. Choosing a connection model saves its
endpoint, model ID, and provider and leaves the deployment blank, so the runtime reads
the request model from the connection. Choosing a classic deployment saves only its
name. The V2 page lists saved connections, so save a new connection there before choosing
it; the classic page lists connections as they are edited on the page and saves them
together with the planner choice.

A saved planner model that no longer appears in the list, for example after its
connection was removed, is shown as not in the current model list and kept until you
choose another. It is never replaced automatically; planning fails with a model
availability error instead. A V2 save that could never resolve is refused, such as a
model ID without its endpoint, or a classic deployment with a provider other than
Azure OpenAI.

The answer choice is saved with the plan and checked again when it runs. Changing the
admin default during approval does not switch that answer to a different model.
Plan edits and editor questions retain that saved choice, unless a separate planner
is configured; the separate planner never replaces the saved answer model.
If the saved model is no longer available to the user, execution stops with a model
availability error rather than silently falling back to GPT-4o.

The same deployment resolves substantive follow-ups before retrieval. This adds a small
completion when usable conversation history or clarification answers are present.
First turns without history and simple acknowledgments skip that call.

#### Settings

The **Planner model** dropdown writes these four stored settings together.

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Planner deployment name | Names a separate classic planning deployment without changing the answer model. When all planner fields are blank, planning uses the manual selection or admin default. | Empty | `chat_orchestration_planner_deployment`; blank for a connection model |
| Planner model id | Identifies the model when planning through a configured model connection. | Empty | `chat_orchestration_planner_model_id` |
| Planner model endpoint id | Identifies the connection when planning through a configured model connection rather than the classic deployment. | Empty | `chat_orchestration_planner_model_endpoint_id` |
| Planner model provider | Records the connection's provider for a connection model. | Empty | `chat_orchestration_planner_model_provider` |

## Run history and switching devices

Every plan, every step and every result is stored against the conversation, not against
the browser that produced it. There is nothing to configure here, but it changes what
users can expect, so it is worth knowing when you answer questions about it.

Opening a conversation on a second device rebuilds the orchestration panel from what the
server holds. A user who plans on a laptop and then opens the same conversation on a
phone sees the same list of runs, can expand any of them, and can read the steps and
results of a run they were not present for. Runs opened this way are shown as a record:
they cannot be edited or directly executed again. Since **0.261.105**, an incomplete
run with valid checkpoints can instead prepare a separate, user-approved recovery
attempt that reuses its completed results.

A plan that was still waiting for approval when the user moved is the one case that stays
actionable. It reappears as a plan the user can approve, edit or discard, so a plan is
never stranded on a device the user has walked away from. Two things are deliberately
adjusted when this happens. A plan that had a countdown is restored without one, so
nothing starts running on a device where nobody was watching. And if the plan was in fact
approved elsewhere in the meantime, approving it again is refused rather than run twice,
and the conversation reloads to show the answer that already exists.

A closed browser or dropped connection does not prove that server execution stopped.
The interface checks the saved attempt rather than treating transport loss as user
cancellation or automatically running the work again.

## Failure explanations and checkpoint recovery

Implemented in version **0.261.105**, tracked in `application/single_app/config.py`.
Execution failures and measured timeouts are reported in the conversation and Run
view. If the answering model also fails, an application-generated status explanation
still describes the incomplete work. Errors are not classified from integration
names or exception-message keywords.

Completed step results are saved in the existing orchestration Cosmos containers.
No new storage connection or settings switch is required. **Retry from failed step**
uses these results with the same effective plan and current authorization, rather
than invoking the planner or repeating the whole request.

Retry is always deliberate, even under Auto approval. If a failed agent/action
may already have changed an external system, the user must acknowledge that the
step's internal effects could repeat. Checkpoints do not restore an agent's
individual tool calls, and cannot guarantee exactly-once remote execution.

From **0.261.212**, a failed, stopped or interrupted step that starts a saved workflow
also asks for that confirmation, because its workflow may already have started. Its
retry never starts the workflow a second time. Each run the plan starts gets an
identifier derived from the plan's first attempt and the step, so the retry finds the run
that attempt started and links it. Stopping a plan does not stop a workflow it already
started; the user cancels that run in Workflows.

A live execution cannot be retried. Missing, incompatible, or unauthorized
checkpoints block recovery rather than causing completed actions to run again.
Older runs without full checkpoints remain readable but require a new plan.
Checkpoint payloads are removed on conversation deletion, including bulk
deletion and archive-and-remove; existing archived messages are unaffected.

## Common tasks

1. **Introduce orchestration to a pilot group.** Enable Chat Orchestration, leave the
   default approval mode on review, and leave the manual controls available. Outcome to
   verify: pilot users see an orchestration control in the V2 composer, and a plan appears
   for review before any work runs.

2. **Reduce planning cost.** Choose a smaller model in the **Planner model** dropdown. Outcome
   to verify: plans are still produced for document questions, and the planner model shows the traffic.

3. **Adopt orchestration for search only.** Clear document analysis and document comparison
   in Capabilities. Outcome to verify: plans use document search and answering, and never
   propose analysing a whole document.

4. **Allow direct use of an existing integration.** Confirm Semantic Kernel and the
   action's existing scope/governance permissions, then enable Action Access. Include
   **Use an action** if Capabilities is narrowed. Ask a question that needs the integration;
   review its action name, scope and task in the plan before running it. Verify the step's
   findings reach the answer without selecting a configured agent.

## Troubleshooting

Since **0.261.140**, planner rejection events identify the specific validation rule,
and execution failures include their preparation stage. Use the conversation or
run ID to correlate its hashed identifier in
[orchestration failure diagnostics](../reference/logging-tags.md#orchestration-failure-diagnostics).
The HTTP status alone is insufficient: a planning stream can return HTTP 200 and
then report a rejected proposal.

Since **0.261.291**, when a web search, linked-page, deep research, agent, action or
memory step is refused, `[ORCHESTRATION_EXTERNAL_SOURCES] A step's source was refused.`
names the check that failed in `sc_reason`. It shares `sc_run_id_hash` and
`sc_step_id_hash` with the step's failure event.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| No orchestration control appears in chat | The setting is off, or the user is in the classic interface. | Confirm Enable Chat Orchestration is on, and that the user is on a V2 chat page. |
| A saved run says it was created by an earlier orchestration version | The run predates the current plan architecture and is refused rather than interpreted. | Start a new request in the same conversation. Earlier-version runs are omitted from the run list and cannot be rerun. |
| Plans never mention documents | No workspace capability is enabled, or nothing in the user's documents matched the question. | Confirm at least one workspace type is enabled, and that the user has documents that have finished processing. |
| Every plan is a single answering step | Capabilities are narrowed to answering only, or the retrieval capabilities are disabled elsewhere. | Review Capabilities on this page, then confirm document search and web search are enabled in their own settings groups. |
| A plan is smaller than expected | The step cap trimmed it. | Raise Maximum steps in a plan, or ask a narrower question. |
| A follow-up loses its subject | The relevant message is outside the history window, masked, inactive, or truncated. | Check Conversation History Limit in Chat settings and whether the earlier turn is still eligible. Repeat the missing detail if it is outside the retained context. |
| A question is asked that was already answered | The earlier answer may be outside retained message history and the activity ledger. | Check the history window and ledger limits; the ledger alone does not contain the full earlier answer. |
| A pending plan reports changed conversation context | A referenced message or its visibility changed after planning. | Create a new plan using the current conversation. |
| A web or research step says it continued in the background, where the user's sign-in is not available | The run continued without the user's browser session, for example after a restart, so their app roles couldn't be confirmed. | Ask the user to send the request again from the chat. The new run uses their signed-in session. |
| Every web search, linked-page or deep research step says a required retained result is unavailable or changed | Before 0.261.209, orchestration checked each user's roles through Microsoft Graph, which needs `Directory.Read.All`, and refused research whenever query or linked-page planning was on. | Upgrade to 0.261.209 or later; no Graph permission or settings change is needed. If a step still fails, check `sc_authority_reason` on its failure event in [orchestration failure diagnostics](../reference/logging-tags.md#orchestration-failure-diagnostics). |
| Every step completed, but the run is partially completed with "A required retained result is unavailable or changed" | Before 0.261.237, settings read from Cosmos DB instead of the shared Redis copy came back as an SDK type that the access recheck refused. That happens while any settings save is in progress, for example the Cosmos throughput autoscale saving its status, and on every read when Redis is off. The failure event logs `sc_authority_reason=result_external_context_unavailable`. | Upgrade to 0.261.237 or later. No setting change is needed. See the [settings document type fix]({{ '/explanation/fixes/ORCHESTRATION_SETTINGS_DOCUMENT_TYPE_FIX/' | relative_url }}). |
| Plans never propose deep research or reading a link | The user does not hold the required app role, or the capability is disabled in its own settings group. | Confirm the user holds `DeepResearchUser` or `UrlAccessUser` where your deployment requires them, and that the capability is enabled outside this page. |
| Plans never propose an agent | Semantic Kernel is off, the user's own agents setting is off, or the user has no agent they can reach. | Confirm Semantic Kernel is enabled, then check the user's own agents setting, the agents button on the classic chat page (`/chats`), and that at least one agent is shared with them. An agent the user picks, or tags with @, is always offered to the planner. |
| The planner model shows "not in the current model list" | Its connection or model was removed or disabled, or connections were switched on or off since it was chosen. | Choose a listed model, or **Use the answer model (default)**. Until then planning keeps trying the saved model and fails rather than switching. |
| Plans never propose Use an action | Action Access is off, Semantic Kernel is off, the capability is excluded, or no eligible action is available to this user. | Check the opt-in and capability selection, then the existing action scope and governance. Call agent actions are not eligible for direct use. |
| An action step fails after plan approval | The action or its access changed, or its model/tool connection could not run. | Check current action access and configuration. Review the visible step failure; the run does not silently switch to an agent or another action. |
| Before 0.261.238, a Microsoft 365 action step showed completed, but the answer said it couldn't read mail, calendar or files | The plan step had no Microsoft 365 request, so every call was refused with `m365_context_required` before reaching Microsoft Graph. `[MS_GRAPH_PLUGIN]` failure events show it as `sc_error_code_length` 21. | Upgrade to 0.261.238 or later. See [Microsoft 365 actions in plans](#microsoft-365-actions-in-plans). |
| A Microsoft 365 step says Microsoft 365 needs the user to sign in or grant access | The user hasn't connected that source for chat, or their sign-in expired or Microsoft Graph rejected it. | The user selects **Connect Microsoft 365** in the run details, or connects in Profile, then **Retry from failed step**. `[ORCHESTRATION_M365] A Microsoft 365 step stopped.` logs the reason as `sc_authority_reason`. |
| A Microsoft 365 step says plans can only read Microsoft 365 data | The action enables only send, invitation or mark-as-read functions, which plans never run. | Enable a read function on the action, or use it from chat without a plan. |
| Before 0.261.270, a Microsoft 365 step said plans can't use Microsoft 365 in a shared conversation | Earlier versions refused Microsoft 365 steps in shared conversations. | Upgrade to 0.261.270 or later. The user's own request now counts as consent to share what the step reads. See [Microsoft 365 actions in plans](#microsoft-365-actions-in-plans). |
| Before 0.261.270, every action or agent step failed with "A required retained result is unavailable or changed", while the same request worked with Orchestrate off | The step's configuration check refused it. For Microsoft 365 actions, the check couldn't see the action's Microsoft 365 selection. Local agents were refused outright. Failure events log `sc_authority_reason=external_configuration_unavailable` for `action_invoke` or `agent_invoke`. | Upgrade to 0.261.270 or later. Agent and action steps now trust the signed-in session, as manual chat does. See [Retained external-source authorization](#retained-external-source-authorization). |
| Before 0.261.289, an Ask an agent step for an agent the user picked, or tagged with @, failed with "This step's agent or action isn't available to you right now, so it didn't run" | The user's own agents setting was off. Planning offered the picked agent, but the step's access check didn't count the pick as permission. Failure events log `sc_authority_reason=result_external_capability_unavailable` for `agent_invoke`. It isn't specific to shared conversations: a request without a picked agent can still work because its plan uses an action instead. | Upgrade to 0.261.291 or later. 0.261.289 fixed this check, but the step still failed at a later one until 0.261.291, so turning agents on doesn't help before then; see the next row. See the [selected agent with agents turned off fix]({{ '/explanation/fixes/ORCHESTRATION_SELECTED_AGENT_DISABLED_PREFERENCE_FIX/' | relative_url }}). |
| Before 0.261.291, every Ask an agent step failed with "This step's agent or action isn't available to you right now", while the same agent answered with Orchestrate off | Cosmos DB returns a stored agent as an SDK subclass of a dictionary, and the step's access check accepted only a plain dictionary, so it refused every agent. Failure events log `sc_authority_reason=result_external_source_unavailable` for `agent_invoke`. | Upgrade to 0.261.291 or later. No setting or data change is needed. Before upgrading, turn Orchestrate off to use the agent. See the [agent document type fix]({{ '/explanation/fixes/ORCHESTRATION_AGENT_DOCUMENT_TYPE_FIX/' | relative_url }}). |
| Before 0.261.270, an @mention of a person in a shared conversation was sent to the model when Orchestrate was on | Orchestrate planned every message without applying the shared conversation's send rule. | Upgrade to 0.261.270 or later. See [Shared conversations](#shared-conversations). |
| A participant sees "Only the person who started this shared conversation can use Orchestrate here" | A request reached the planner from someone other than the person who started the shared conversation. The V2 composer normally answers their requests the classic way instead. | Turn off Orchestrate for that request, or ask the person who started the conversation to ask it. |
| The person who started a shared conversation sees "Orchestrate can't be used in this shared conversation because an earlier version kept another participant's private copy of it" | Before 0.261.270, Orchestrate saved a private copy for whoever used it first, under the shared conversation's ID. Only one record can have that ID. | Turn off Orchestrate to ask the assistant. To restore Orchestrate, remove that participant's record from the conversations container: its ID is the shared conversation's ID. The `[ORCHESTRATION]` warning logs `sc_reason=shared_conversation_stale_copy`. |
| A plan proposed reading a link but found nothing | The link was not available in the eligible user-authored context. | Paste the URL into the current request. Assistant-generated links and omitted historical text do not authorize page reads. |
| Earlier runs are missing after switching devices | The conversation list has loaded but its run history has not been fetched yet, or the fetch failed. | The orchestration panel shows its own loading and retry states. If retrying keeps failing, check that the user can reach `/api/v2/orchestration/runs` and is the owner of the conversation. |
| A restored plan will not run | It was already approved on the other device. | This is expected. The conversation reloads to show the answer that run produced. |
| A step reports a timeout or failure | Execution hit a recorded time limit or an operation failed. | Read the conversation/Run explanation. Address the reported dependency or limit, then use Retry from failed step when recovery is available. |
| A connection was interrupted | The browser cannot yet confirm the server's execution state. | Check the existing run. Do not resend the request while that attempt may still be active. |
| Execution returns 503, run detail repeatedly returns 404, and every step remains pending | In affected versions, Cosmos SDK response objects were rejected as invalid dictionaries at execution and status-read boundaries. | Upgrade to 0.261.140 or later, then inspect the existing attempt. Do not reset its deadline or assume that resubmitting is safe. |
| The plan could not account for everything requested | The proposal and its correction failed deliverables validation. Earlier guidance could lead the model to put file-only fields on an answer. | Upgrade to 0.261.140 for explicit kind-specific guidance. For a remaining rejection, inspect `sc_validation_rule` and `sc_attempt`; preserve selected sources and requested outputs rather than disabling validation. |
| A PDF/CSV comparison tries to analyze the CSV as a narrative document | Earlier planning relied on display labels rather than current source-kind metadata. | Version 0.261.140 supplies authorized file types and rejects incompatible steps before execution. Native tabular work still requires its existing capability; inspect `source_kind_invalid` or `source_binding_required` if a correction cannot produce a valid plan. |
| Plans never start a saved workflow | Run Workflows From Chat or personal workflows are off, the **Run workflows** capability is excluded, the user lacks the `WorkflowUser` role your deployment requires, the conversation is shared, the workflow does not have durable execution on, or the request did not ask to run a workflow now. | Check the setting and the capability selection, then the user's role. Ask from the user's own conversation, name the workflow and ask to run it now, and turn on **Durable execution** for the workflow in its editor. |
| A workflow step says the user's sign-in is not available | The plan's remaining work continued in the background after the user's browser request ended, so the user's signed-in session was not available to start a new workflow run. A run the plan had already started is still linked. | Ask the user to select **Retry from failed step** in the chat. The retry uses their signed-in session and never starts a workflow the plan already started. |
| A workflow step says saved workflows were temporarily unavailable | Workflow storage could not be read or written when the step ran, so the workflow may not have started. It is not retried automatically. | Once storage is reachable, the user can select **Retry from failed step**. A run the plan already started is linked rather than started again. |
| Retry requires confirmation | An agent/action may have performed external effects before it failed, or a step may already have started a saved workflow. | Review those effects before confirming. Retry reexecutes that failed step, not its internal tool-call checkpoint. A workflow the plan already started is linked again, never started twice. |
| Plans never read a saved workflow's result | Use Workflow Results In Chat or personal workflows are off, the **Read workflow results** capability is excluded, the user lacks the `WorkflowUser` role your deployment requires, the conversation is shared, or the request did not name one of the user's saved workflows. | Check Use Workflow Results In Chat in [Workflow settings]({{ '/admin/workflow/' | relative_url }}) and the capability selection, then the user's role. Ask from the user's own conversation and name the workflow. |
| A step says "Your workflow results couldn't be read right now. Try again in a moment." | Workflow storage could not be read when the step ran. The step is retried once automatically. | Once storage is reachable, the user can select **Retry from failed step** or ask again. Reading a result changes nothing, so trying again is safe. |
| An answer says a workflow result it used changed or is no longer available, so it was not saved | A run the plan read was deleted or changed, or its owner lost access to a source it used, while the answer was being written. | Expected. Ask again in a new message to read the current result. |
| A saved run cannot be resumed | Checkpoints are absent or invalid, relevant context/access changed, or a newer/live attempt exists. | Follow the recovery explanation. Open the current attempt or create a new plan as appropriate; do not infer results from old summaries. |
| A chat-started workflow finishes but no result appears in the chat | The workflow settings gate for result post-back is off, the chat was deleted or shared after the run started, access to personal workflows was lost, the workflow was deleted, or the delivery worker deferred or closed the generation after retryable storage/notification failures. | Check **Use Workflow Results In Chat** under Workflow settings, keep the request in the user's private chat, and open the run from Workflows or the workflow notification. The plan itself is already complete and does not wait for delivery. |
| Plans never hand large work off to a workflow | Hand Off Large Work From Chat or one of the settings it requires is off, the **Hand off large work** capability is excluded, the user lacks the `WorkflowUser` role your deployment requires, or the conversation is shared. The capability is left out without a reason, so the planner can't say which. | Check Hand Off Large Work From Chat, personal workflows, Propose Workflows From Chat, Run Workflows From Chat and Use Workflow Results In Chat, then the capability selection and the user's role, and ask from the user's own conversation. If all of them pass, look for `workflow_context_unavailable` on `[ORCHESTRATION_WORKFLOWS]` log events. |
| Accepting a hand-off says "You reached the daily limit for workflow hand-offs. Try again later." | The user already has as many hand-off workflows from the last 24 hours as **Hand-offs from chat per user per day** allows. | Wait, or raise the limit. Deleting a hand-off workflow frees its place. |
| A hand-off run pauses before reviewing any document | A workspace query for all matching documents matched more than the hand-off may review. A best-matches query reviews only its best N, so more matches don't pause it. The run's deadline doesn't expire the pause. | Cancel the run with **Cancel run** on the hand-off card, which says why it paused, or from Workflows, and ask again with a narrower request. The hand-off workflow can't be resumed, and it still counts toward the daily limit. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Chat settings]({{ '/admin/chat/' | relative_url }})
- [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
- [Agents and actions settings]({{ '/admin/agents-actions/' | relative_url }})
- [Create an action]({{ '/guides/create-an-action/' | relative_url }})
- [Actions reference]({{ '/reference/actions/' | relative_url }})
- [Workflow settings]({{ '/admin/workflow/' | relative_url }})
- [Recover a failed run]({{ '/guides/review-and-edit-orchestration-plans/#recover-from-a-failed-run' | relative_url }})
