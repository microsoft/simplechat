---
layout: page
title: "Workflow settings"
description: "Workflow controls who can build and run agent-driven task sequences, and how much work a single run may do."
section: "Administration"
audience: admin
admin_tab: workflow
---


# Workflow settings

## What this group controls

Who may build and run workflows — the ordered instruction sequences an agent or
model executes against a workspace — separately for personal and group
workspaces, and the ceilings that bound a single run.

## Why it matters

A workflow run makes agent calls without a person watching each step, so the
limits here are the difference between a long run and a runaway one. The access
settings decide whether workflows are a pilot for one team or a capability every
user has.

{% include media.html src="admin/workflow-overview.png" alt="Screenshot placeholder for the Workflow group in Admin Settings." title="Workflow settings" capture="Capture the Workflow group in Admin Settings showing its tabs." %}

{% include media.html type="video" title="Workflow settings walkthrough" poster="video-posters/admin-workflow.png" capture="Recording planned. Walk through each tab in the Workflow group and explain when to change each setting." %}

## Before you change anything

- Decide whether personal workflows, group workflows, or both are in scope.
- If you plan to require the `WorkflowUser` app role, assign it in the Enterprise
  App first. Turning the requirement on before assigning it removes access from
  everyone at once.
- If you plan to require group assignment, know which groups belong on the list.

## Workflow {#workflow}

### Workflow {#workflow-settings-section}

Workflows let a person hand a repeatable job to an agent or model: an ordered set
of instruction tasks that runs on demand or on a schedule, against documents in a
workspace. This section decides who may build and run them, and how much work a
single run is allowed to do.

The two capabilities are independent. Personal workflows belong to one user and
run in their own workspace. Group workflows belong to a group workspace and are
visible to its members. Turning one on does not turn on the other.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Personal Workflows | Lets users build workflows in their personal workspace and run them manually or on a schedule, either at a fixed interval or at a local time on a calendar schedule. | Off | `allow_user_workflows` |
| Require WorkflowUser App Role | Restricts personal workflows to holders of the `WorkflowUser` Enterprise App role. Covers opening, creating, editing, running and inspecting them, so assign the role before turning this on or every user loses access at once. | Off | `require_member_of_workflow_user` |
| Enable AI Workflow Assistant | Lets people who can edit personal workflows describe a change in plain language, such as "run this at 7 AM on weekdays", and review the assistant's proposed edit in the V2 workflow editor before they save it. The assistant never saves, runs or shares a workflow, and it only uses documents the person can already open. | On | `enable_workflow_ai_assistant`; personal workflows only; has no effect while Enable Personal Workflows is off |
| Use Workflow Results In Chat | Lets people ask chat about the stored result of one of their own finished personal workflow runs, from **Ask in chat** in the run history or **Ask about this** on a workflow alert. The answer uses only that run's saved output: the workflow isn't re-run and nothing else is searched. It works only in the person's private chats, and an answer stops showing once the run is deleted or the person loses access to the run's sources. | Off | `enable_chat_workflow_results`; personal workflows only; has no effect while Enable Personal Workflows is off, and follows Require WorkflowUser App Role |
| Enable Group Workflows | Lets permitted members create, manage and run workflows from group workspaces. Owners and Admins may author them unless Workspaces restricts group agent, action and workflow management to Owners. | Off | `allow_group_workflows` |
| Require Group Assignment to Use Workflow | Narrows group workflows to an explicit allow list instead of every group. Groups outside the list lose the capability. | Off | `require_group_assignment_for_group_workflows` |
| Assigned Groups | The groups that may use group workflows while assignment is required. Ignored when it is not. | Empty list | `group_workflow_allowed_group_ids` |
| Workflow Agent Action Limit | Caps the automatic tool and action calls an agent may make in one workflow run, independently of authored For each or Repeat blocks. Large document sets may need a higher cap. Values above 100 are capacity-sensitive: enable Cosmos DB throughput automation and watch Azure OpenAI throttling, App Service CPU and memory, and downstream latency. | 60 | `workflow_max_auto_invoke_attempts` |
| Workflow Task Limit | Caps the ordered instruction tasks a single workflow may contain. Supported range is 1–100. | 50 | `workflow_max_tasks` |
| Workflow Loop Item Limit | Bounds the actual per-item body visits in a For each block, not the number of documents that may be searched. A collection above the effective limit must be narrowed before its body can run; it is never silently trimmed. | 500 | `workflow_max_loop_items`; supported range 1-5,000; applies to new runs |
| Workflow Repeat Iteration Limit | Bounds one automatic Repeat until batch, including its first round. Authors must choose an explicit per-block maximum; a new run above this ceiling is rejected rather than shortened. | 25 | `workflow_max_repeat_iterations`; supported range 1-1,000; new runs only; active runs and manual continuation retain the admitted policy |
| Workflow Minimum Schedule Interval (seconds) | Sets the shortest fixed interval a personal or group workflow may be saved with, so no one can schedule a workflow to run every few seconds. It's checked only when an interval schedule is created or changed; workflows already saved on a shorter interval keep running. Calendar schedules run at most once a day and are never checked. The default, 1 second, allows every interval, as before. | 1 | `workflow_min_schedule_interval_seconds`; supported range 1-86,400; new or changed interval schedules only |

The action and task limits apply to personal and group runs alike, so they stay
in effect whichever capability is enabled.

### Workflow schedules {#workflow-schedules}

Version **0.261.193** adds calendar schedules. Besides repeating at a fixed
interval, a personal or group workflow can run daily, on weekdays, on chosen
days of the week, or on a day of the month, at a local time in an IANA time
zone such as `America/New_York`. Runs keep their local time through daylight
saving changes. Authors set calendar schedules in the V2 workflow editor; the
classic editor sends those workflows to V2. There's nothing to turn on, and
existing interval workflows, with their Microsoft 365 Run as approvals, don't
change.

**Workflow Minimum Schedule Interval (seconds)** limits how often an interval
schedule may run. Raising it doesn't stop or change any saved workflow. It
refuses a save that creates an interval workflow below the minimum, or changes a
workflow to such an interval, with a message that names the minimum, for
example "This schedule runs more often than the administrator allows. Choose an
interval of at least 5 minutes." A workflow already saved on a shorter interval
can still be saved with it, including when it's turned off and on, until someone
changes its schedule. The scheduler doesn't read the minimum.

The time zones offered come from the server's time zone database. See
[Workflow calendar schedules](../explanation/features/WORKFLOW_CALENDAR_SCHEDULES.md)
for the daylight saving rules and the stored format.

### AI workflow assistant {#workflow-ai-assistant}

Version **0.261.208** adds the server side of the AI workflow assistant. A person
editing a personal workflow can ask for a change in plain language, such as "run
this at 7 AM on weekdays and only alert me when something is urgent", and gets a
proposed edit that the V2 editor shows as highlighted, revertible changes. The
editor's **Ask AI** tab arrives in a later release.

The assistant is on by default wherever personal workflows are on, and it
follows the same `WorkflowUser` role rule. Things to know before relying on it:

- **It proposes; it never saves.** Nothing changes until the person reviews the
  edit and saves it through the normal save, with the usual checks and the Run
  as re-approval when a change needs one. The assistant can't turn a workflow on
  or off, change Run as, sharing, approvals or URL access, or set up File Sync.
- **It uses only what the person can already use.** Documents attached with `#`,
  agents and models are checked against the person's own access, and group
  workflows aren't supported.
- **It uses the existing model.** Requests go to the deployment that already
  drafts agent and workflow instructions, so there's no model to configure.
- **It's rate limited.** Each person may have one request running and send 20
  requests every 10 minutes, across all app instances. The count is kept in a
  small document per user in the settings container, which is the only thing the
  assistant writes. If that store can't be reached, the assistant reports that
  it's temporarily unavailable rather than running without a limit.
- **Its logs hold no content.** Telemetry records counts, outcomes and error
  categories, never instructions, workflows, replies or document text.

See [AI workflow assistant](../explanation/features/WORKFLOW_AI_ASSISTANT.md)
for the request contract, the changes it can propose, and its security model.

## Durable runs

In **0.261.111**, durability is a workflow-definition option, not another global
capability toggle. New native V2 workflows enable it; existing definitions do not
change automatically. The existing background scheduler must run for queued
work to progress. Each application process uses at most two durable workers,
with renewable Cosmos leases preventing simultaneous ownership of one run.

Approval, pending-output, and recovery gates keep a run active without holding
a worker. A scheduled trigger does not start a second run while that run waits.
Completed outputs remain in the configured result store; run memory and lease
controls are private records in the existing run-items partition. No additional
Cosmos container is required.

See [Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }}) for
the operator's approval, continuation, and cancellation workflow.

### Structured control-flow budgets

Version **0.261.116** adds an explicit definition-version-3 option in the V2
List editor. It uses the existing personal/group permissions and requires
durable execution; it does not introduce another global capability toggle.
Existing ordered definitions retain their previous behavior.

The existing **Workflow Task Limit** still caps authored tasks, not runtime
admissions. A structured definition additionally stores a finite admission
limit (default/maximum 5,000) and elapsed deadline (default/maximum 86,400
seconds). Time spent waiting for approval or output counts toward that
deadline. These limits survive restart and Resume. Exhaustion pauses the run
without releasing it for overlapping scheduled runs; cancellation is required
before starting a replacement.

Conditions and joins are deterministic engine operations. Model input limits
still come from the selected catalog/deployment, not the admission limit.
See [Structured workflow control flow](../explanation/features/WORKFLOW_STRUCTURED_CONTROL_FLOW.md)
for the supported If/else, Run when, and forward-routing scope.

### Serial loop inputs

Version **0.261.117** adds serial For each and exact Collect. Users can choose
documents, complete saved records, or a workspace query frozen when the loop
starts. Query authoring distinguishes exhaustive metadata/keyword matches from
an explicit best-N relevance selection.

The loop-item setting is an administrator ceiling; authors can choose a lower
maximum. Existing runs retain the ceiling captured when admitted, so changing
the setting does not alter an active run's frozen membership. A larger item
allowance does not raise the 5,000 execution-admission maximum, and a multi-task
body may reach that budget before its item allowance.

Loop tasks and explicit saved-record reporting require locally metered runners.
Per-task context limits still come from the model catalog and deployment. There
is no cumulative run-token/spend cap in this slice.

See [Serial For each and exact Collect](../explanation/features/WORKFLOW_FOR_EACH_COLLECT.md)
for retained-data behavior, partial coverage, and inspection.

### Repeat batches and manual continuation

Version **0.261.120** adds **Repeat until** to the durable V2 List editor.
Its separate setting limits automatic rounds, not selected document counts.
The value 25 is the administrator default, never an implicit authored block
maximum. A saved workflow above a newly lowered ceiling stays unchanged, but
cannot start a new run until its authored maximum or administrator policy is
deliberately adjusted.

When the condition remains false at the block's maximum, the run pauses with
its saved state and earlier rounds retained. An authorized person can explicitly
grant another batch of the same frozen size. Changing this administrator
setting cannot enlarge an active run, and ordinary Resume cannot grant a batch.

Manual continuation resets only batch usage. It preserves lifetime round
numbers, the admitted execution budget (at most 5,000), and the original elapsed
deadline (at most 86,400 seconds, including the time waiting for a person).
Remaining global budgets can prevent the grant or stop a later round before
the batch allowance is used.

The run retains bounded exhaustion and continuation counters/audit records.
Control Center personal-user monitoring, group monitoring, and a dedicated
**Workflow Monitoring** section are an approved future follow-up, **not
implemented here**. This setting adds no monitoring role or cross-run access.
See [Repeat until](../explanation/features/WORKFLOW_REPEAT_UNTIL.md).

## Common tasks

### Publication completion

Version **0.261.118** lets authors of version-3 durable workflows choose
Submitted, Approved, or Indexed and ready for an existing native Analyze
artifact. This is a task option, not another administrator toggle. Existing
workflows without a policy retain their prior behavior.

Publication waits use the existing scheduler and lease. They keep the run
active and count against its existing elapsed deadline. Unmet policies cannot
be skipped with continue-on-error; neither Resume nor a changed administrator
limit resets the active run's admitted bounds. Destination approval and content
screening retain their existing permissions.

See [Workflow publication completion](../explanation/features/WORKFLOW_PUBLICATION_COMPLETION.md).

### Administration examples

1. **Pilot group workflows with one team.** Enable Group Workflows, turn on
   Require Group Assignment to Use Workflow, then assign only the pilot group.
   Outcome to verify: members of the pilot group see the Workflows section in
   their group workspace and no other group does.

2. **Raise the action limit for a large document set.** Increase Workflow Agent
   Action Limit and rerun the workflow that stopped early. Outcome to verify: the
   run reaches the end of its task list instead of halting mid-way, and Cosmos RU
   and Azure OpenAI throttling stay within headroom.

3. **Stop workflows that run every few seconds.** Set Workflow Minimum Schedule
   Interval (seconds) to 300. Outcome to verify: saving a new workflow that
   repeats every 30 seconds is refused with "Choose an interval of at least 5
   minutes.", while workflows already saved on shorter intervals keep running
   until their authors change them.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A user cannot open personal workflows | Personal workflows are off, or Require WorkflowUser App Role is on and the user does not hold the role. | Check Enable Personal Workflows, then confirm the `WorkflowUser` role assignment in the Enterprise App. |
| A group has no Workflows section | Group workflows are off, or assignment is required and the group is not assigned. | Check Enable Group Workflows, then add the group under Assigned Groups. |
| A workflow run stops before its last task | The run hit the agent action limit. | Raise Workflow Agent Action Limit, and review capacity before going above 100. |
| A workflow rejects a new task | The workflow already holds the maximum number of tasks. | Raise Workflow Task Limit, or split the work across two workflows. |
| A saved Repeat workflow cannot start a new run | Its explicit block maximum exceeds the current Repeat ceiling. | Deliberately reduce the authored maximum or adjust Workflow Repeat Iteration Limit; the app does not silently clamp it. |
| Repeat pauses with its condition unmet | The automatic batch ended, or a separate global budget blocked progress. | Inspect the gate and remaining budgets. Only a Repeat-limit gate can receive an explicit same-sized manual continuation; global budget exhaustion cannot be reset. |
| Authors can't save a workflow that repeats every few seconds or minutes | The new or changed interval is shorter than Workflow Minimum Schedule Interval (seconds). | Expected when the minimum is raised. Lower the minimum, or have the author choose a longer interval or a calendar schedule. |
| A calendar-scheduled workflow stopped running | Its saved time zone is no longer in the server's time zone database, so it has no next run. The server logs `[Workflows] Calendar schedule could not compute a next run.` with the workflow ID. | Have the author open it in the V2 editor, choose a listed time zone, and save. |
| The AI workflow assistant refuses every request from a user | Enable AI Workflow Assistant or Enable Personal Workflows is off, or Require WorkflowUser App Role is on and the user doesn't hold the role. | Check both settings, then the `WorkflowUser` role assignment. |
| The AI workflow assistant says it has had too many requests | Each person may have one request running and send 20 requests every 10 minutes. The limit is fixed. | Wait for the current request to finish, or for the time the response gives. |
| The AI workflow assistant is temporarily unavailable for everyone | The model deployment is throttled or unreachable, or the settings container that holds the rate-limit count can't be reached. The assistant won't run without its limit. | Check the GPT deployment's health and throttling, and Cosmos DB availability. Each request logs `[WorkflowAssist] Assist request finished` with its `status` and error `code`, and no content. |
| Users don't see **Ask in chat** or **Ask about this** in V2 | Use Workflow Results In Chat or Enable Personal Workflows is off, or Require WorkflowUser App Role is on and the user doesn't hold the role. Both buttons also need a completed run of a personal workflow, and **Ask in chat** isn't offered on structured runs. | Check both settings, then the `WorkflowUser` role assignment. |
| A chat answer reads "This answer is unavailable because access to the workflow result it used could not be confirmed." | The run was deleted, its result changed, its owner can no longer read a source its tasks used, the chat was shared or converted to a collaboration, or storage couldn't be read during the check. | Expected. An answer is shown only while its result still checks out for the chat's owner in a private chat; after a storage failure it shows again once a check succeeds. The stored messages are unchanged. Each withheld answer logs `[WorkflowResults] A chat answer's workflow result was withheld on read.` with a `check` of `conversation` or `result`, a `code` or `error_type`, and no content. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
