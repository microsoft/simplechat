# SIMPLECHAT_WORKFLOWS_AND_GROUP_STATUS.md

# SimpleChat Workflows And Group Status

Implemented in version: **0.241.030**

## Overview

This enhancement adds two new SimpleChat capabilities that let an agent act through the signed-in user's own permissions for automation and administrative tasks:

- Create personal workflows through the existing personal workflow engine.
- Mark groups inactive through the same Control Center admin permission boundary used by the existing group status management UI.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.030"`.

## Dependencies

- Existing SimpleChat capability filtering and plugin loading
- Existing personal workflow storage and validation in `functions_personal_workflows.py`
- Existing Control Center group status model and audit logging
- Workspace action and agent capability configuration modals

## Technical Specifications

### Architecture Overview

- Shared backend operations: `application/single_app/functions_simplechat_operations.py`
- Built-in SK plugin: `application/single_app/semantic_kernel_plugins/simplechat_plugin.py`
- Personal workflow persistence: `application/single_app/functions_personal_workflows.py`
- Group activity audit logging: `application/single_app/functions_activity_logging.py`
- Workspace action capability UI: `application/single_app/static/js/plugin_modal_stepper.js`
- Agent capability UI: `application/single_app/static/js/agent_modal_stepper.js`

### New SimpleChat Capabilities

- `create_personal_workflow`
  - Creates a personal workflow under the current user's identity.
  - Reuses `save_personal_workflow(...)` so the same runner validation, schedule validation, model binding, and selected-agent checks apply as the normal workflow UI.
  - Supports both `model` and `agent` runners and both `manual` and `interval` triggers.

- `make_group_inactive`
  - Marks a group `inactive` and records status history.
  - Reuses the same Control Center admin access boundary as the existing admin route:
    - If `require_member_of_control_center_admin` is enabled, the caller must have `ControlCenterAdmin`.
    - Otherwise, the caller must have `Admin`.
  - Logs the group status change through the existing activity log helper.

### Group Resolution Behavior

For `make_group_inactive`, the target group is resolved in this order:

1. Explicit `group_id`
2. Action `default_group_id`
3. The user's active group setting

## Usage Instructions

1. Create or edit a `Simple Chat` action.
2. Leave `Create personal workflows` enabled for agents that should be able to save automation jobs for the current user.
3. Leave `Make groups inactive` enabled only where the current user should be allowed to invoke Control Center-style group status changes.
4. Call `create_personal_workflow` with a workflow name, task prompt, runner type, and optional schedule or model selection.
5. Call `make_group_inactive` with a target `group_id` or rely on the current group context when appropriate.

## Testing And Validation

Functional coverage:

- `functional_tests/test_simplechat_agent_action.py`
- `functional_tests/test_simplechat_workflow_and_group_inactive.py`

UI coverage:

- `ui_tests/test_agent_modal_simplechat_capabilities.py`
- `ui_tests/test_workspace_simplechat_action_modal.py`

Validation focus:

- runtime overlay exposure of the new capability names
- workflow payload mapping into the existing personal workflow store
- admin-only permission enforcement for group inactivity
- status history and audit logging for inactive transitions
- modal visibility and persistence of the new capability toggles

## Known Limitations

- The SimpleChat workflow capability currently creates personal workflows only; it does not edit or delete existing workflows.
- The group status capability only marks groups inactive; it does not expose other Control Center status transitions through SimpleChat.