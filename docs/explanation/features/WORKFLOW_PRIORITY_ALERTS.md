# Workflow Priority Alerts

Implemented in version: **0.241.029**
Refined in version: **0.241.032**

## Overview and Purpose

Workflow Priority Alerts extend personal workflows with a user-controlled pop-up alert setting. Each workflow can now raise a `high`, `medium`, or `low` priority modal after a run, or stay silent with `none`.

The alert modal is designed for actionable workflow results, not just passive badge updates. It can deep-link into the workflow conversation, and when an agent run creates or updates another conversation through the built-in SimpleChat action, the alert can surface that destination directly as well.

Related config update:
- `application/single_app/config.py` now reports version `0.241.032`.

Dependencies:
- `application/single_app/functions_personal_workflows.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/functions_notifications.py`
- `application/single_app/route_backend_notifications.py`
- `application/single_app/templates/workspace.html`
- `application/single_app/templates/base.html`
- `application/single_app/static/js/workspace/workspace_workflows.js`
- `application/single_app/static/js/notifications.js`

## Technical Specifications

Architecture overview:
- Workflow definitions now store `alert_priority` alongside the existing runner and trigger settings.
- Workflow execution creates personal notifications of type `workflow_priority_alert` when alerting is enabled.
- Priority-specific icon and color treatment is resolved by the notifications backend before the browser renders the alert.
- The global modal lives in the shared base template so it can appear on authenticated pages, not just inside the notifications center.

Deep-link behavior:
- Every alert can point back to the workflow conversation.
- Agent runs capture SimpleChat plugin invocations through the plugin invocation logger scoped to the workflow conversation.
- When the agent creates a personal conversation, group conversation, or personal collaborative conversation, the alert stores those linked destinations as modal actions.
- Group conversation targets align the active group before navigation so the target chat opens in the right workspace context.
- The modal now promotes the event title as the primary heading, keeps workflow identity in a secondary type card when it differs, and uses a redesigned summary panel closer to the security-style alert layout.
- When both personal and group-created conversations exist, only the single highest-value created target is shown; group multi-user conversations outrank personal conversations.
- The modal summarizes long alert bodies into a shorter headline, preserves deeper detail in a nested detail card when it adds signal, highlights the created-conversation action in green, and renders the fallback workflow link as a gray `Open workflow` action.

Notification payload:
- Notification type: `workflow_priority_alert`
- Priority values: `high`, `medium`, `low`
- Disabled state: `none`
- Metadata includes workflow name, run id, trigger source, response preview or error text, and ordered link targets.

## Usage Instructions

How to configure:
1. Open Personal Workspace.
2. Create or edit a workflow.
3. Set `Pop-up Alert Priority` to `No notification`, `Low priority`, `Medium priority`, or `High priority`.
4. Save the workflow.

What happens after a run:
1. The run finishes or fails.
2. If alerting is enabled, the notification system stores a workflow priority alert.
3. The global notifications script polls unread workflow alerts and opens the modal.
4. The modal shows the priority, workflow summary, and one or more conversation links.
5. The user can dismiss the alert, mark it as read, or open a linked conversation immediately.

## Testing and Validation

Functional coverage:
- `functional_tests/test_workflow_priority_alerts.py`

UI coverage:
- `ui_tests/test_workspace_workflows_tab.py`
- `ui_tests/test_workflow_priority_alert_modal.py`

Validation focus:
- workflow save payload includes alert priority
- runner creates workflow alert notifications
- global modal renders unread workflow alerts
- modal actions can target workflow, personal, group, and collaborative conversations

## Known Limitations

- The modal suppresses repeat display for the same alert within the current browser session, even if the user closes it without marking it read.
- Only agent actions captured through the existing plugin invocation logger can contribute extra linked conversations beyond the default workflow conversation.
- Alert delivery remains polling-based, so scheduled workflow alerts are near-real-time rather than push-driven.