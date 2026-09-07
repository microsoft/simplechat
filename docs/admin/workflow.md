---
layout: page
title: "Workflow settings"
description: "Workflow centralizes task sequence, assignment, and approval behavior used across SimpleChat surfaces."
section: "Administration"
audience: admin
admin_tab: workflow
---


# Workflow settings

## What this group controls

Workflow centralizes task sequence, assignment, and approval behavior used across SimpleChat surfaces.

## Why it matters

Workflow settings affect handoffs between people and automated steps. Keep the path understandable so workspace owners can diagnose stalled approvals.

{% include media.html src="admin/workflow-overview.png" alt="Screenshot placeholder for the Workflow group in Admin Settings." title="Workflow settings" capture="Capture the Workflow group in Admin Settings showing its tabs." %}

{% include media.html type="video" title="Workflow settings walkthrough" poster="video-posters/admin-workflow.png" capture="Recording planned. Walk through each tab in the Workflow group and explain when to change each setting." %}

## Before you change anything

- Document which teams own workflow templates.
- Confirm assignment roles before enabling a workflow path.

## Workflow {#workflow}

### Workflow {#workflow-settings-section}

The Workflow section belongs to the Workflow tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Personal Workflows | Permits enable personal workflows when the related workspace or agent feature is enabled. | Off | `allow_user_workflows` |
| Require WorkflowUser App Role | Requires the `WorkflowUser` app role before users can use this capability or view. | Off | `require_member_of_workflow_user` |
| Workflow Agent Action Limit | Maximum automatic tool or action calls an agent can make during one workflow run. Default is 60; increase for large document sets. | 60 | `workflow_max_auto_invoke_attempts` |
| Workflow Task Limit | Maximum ordered instruction tasks users can add to one workflow. Default is 50; supported range is 1-100. | 50 | `workflow_max_tasks` |
| Enable Group Workflows | Permits enable group workflows when the related workspace or agent feature is enabled. | Off | `allow_group_workflows` |
| Require Group Assignment to Use Workflow | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `require_group_assignment_for_group_workflows` |
| Group Workflow Allowed Group Ids | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `group_workflow_allowed_group_ids` |

## Common tasks

1. **Validate a workflow path.** Review the Workflow tab and run a simple test sequence. Outcome to verify: The sequence reaches the expected state and assignee.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A workflow does not advance | Assignment or approval state is not configured for the path. | Check workflow settings and rerun with a small item. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
