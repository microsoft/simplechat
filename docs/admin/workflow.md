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
| Enable Personal Workflows | Lets users build workflows in their personal workspace and run them manually or on an interval schedule. | Off | `allow_user_workflows` |
| Require WorkflowUser App Role | Restricts personal workflows to holders of the `WorkflowUser` Enterprise App role. Covers opening, creating, editing, running and inspecting them, so assign the role before turning this on or every user loses access at once. | Off | `require_member_of_workflow_user` |
| Enable Group Workflows | Lets permitted members create, manage and run workflows from group workspaces. Owners and Admins may author them unless Workspaces restricts group agent, action and workflow management to Owners. | Off | `allow_group_workflows` |
| Require Group Assignment to Use Workflow | Narrows group workflows to an explicit allow list instead of every group. Groups outside the list lose the capability. | Off | `require_group_assignment_for_group_workflows` |
| Assigned Groups | The groups that may use group workflows while assignment is required. Ignored when it is not. | Empty list | `group_workflow_allowed_group_ids` |
| Workflow Agent Action Limit | Caps the automatic tool and action calls an agent may make in one workflow run, which is what stops a run from looping. Large document sets need a higher cap. Values above 100 are capacity-sensitive: enable Cosmos DB throughput automation and watch Azure OpenAI throttling, App Service CPU and memory, and downstream latency. | 60 | `workflow_max_auto_invoke_attempts` |
| Workflow Task Limit | Caps the ordered instruction tasks a single workflow may contain. Supported range is 1–100. | 50 | `workflow_max_tasks` |

The action and task limits apply to personal and group runs alike, so they stay
in effect whichever capability is enabled.

## Common tasks

1. **Pilot group workflows with one team.** Enable Group Workflows, turn on
   Require Group Assignment to Use Workflow, then assign only the pilot group.
   Outcome to verify: members of the pilot group see the Workflows section in
   their group workspace and no other group does.

2. **Raise the action limit for a large document set.** Increase Workflow Agent
   Action Limit and rerun the workflow that stopped early. Outcome to verify: the
   run reaches the end of its task list instead of halting mid-way, and Cosmos RU
   and Azure OpenAI throttling stay within headroom.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A user cannot open personal workflows | Personal workflows are off, or Require WorkflowUser App Role is on and the user does not hold the role. | Check Enable Personal Workflows, then confirm the `WorkflowUser` role assignment in the Enterprise App. |
| A group has no Workflows section | Group workflows are off, or assignment is required and the group is not assigned. | Check Enable Group Workflows, then add the group under Assigned Groups. |
| A workflow run stops before its last task | The run hit the agent action limit. | Raise Workflow Agent Action Limit, and review capacity before going above 100. |
| A workflow rejects a new task | The workflow already holds the maximum number of tasks. | Raise Workflow Task Limit, or split the work across two workflows. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
