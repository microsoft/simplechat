# SimpleChat Agent Action

Implemented in version: **0.241.022**

## Overview

The SimpleChat Agent Action adds a native action type that can create groups, add users to groups, create group collaborative conversations, create personal conversations, and create personal collaborative conversations.

This action always runs in the invoking user's identity and permission context, even when the action itself is globally defined.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.022"`.

## Dependencies

- Existing group workspace APIs and permission helpers
- Existing personal and collaborative conversation storage paths
- Microsoft Graph user lookup with the signed-in user's token
- Shared action modal and agent modal workflows
- Shared Semantic Kernel plugin loader

## Technical Specifications

### Architecture

- Shared backend operations: `application/single_app/functions_simplechat_operations.py`
- Built-in SK plugin: `application/single_app/semantic_kernel_plugins/simplechat_plugin.py`
- Loader overlay for action-level defaults and per-agent capability filtering: `application/single_app/semantic_kernel_loader.py`
- Plugin validation and registration support: `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`, `application/single_app/semantic_kernel_plugins/logged_plugin_loader.py`
- Shared action modal capability UI: `application/single_app/templates/_plugin_modal.html`, `application/single_app/static/js/plugin_modal_stepper.js`
- Shared agent modal capability UI: `application/single_app/templates/_agent_modal.html`, `application/single_app/static/js/agent_modal_stepper.js`

### Runtime Behavior

- Group creation reuses the existing `enable_group_workspaces`, `enable_group_creation`, and `CreateGroups` role checks.
- Group membership changes reuse the existing direct-add behavior; no new approval workflow was introduced.
- Group conversation creation falls back to the agent's group context or the user's active group when `group_id` is omitted.
- Personal collaborative conversation creation resolves invitees through Microsoft Graph using the current user's access token.
- Action-level capability defaults are stored in `additionalFields.simplechat_capabilities`.
- Per-agent capability selections are stored in `other_settings.action_capabilities` and override the action defaults when the plugin is loaded.

### Capability Storage

Action defaults are stored on the action itself:

```json
{
  "simplechat_capabilities": {
    "create_group": true,
    "add_group_member": true,
    "create_group_conversation": true,
    "create_personal_conversation": true,
    "create_personal_collaboration_conversation": true
  }
}
```

Agent-specific overrides are stored per selected action ID under `other_settings.action_capabilities`.

## Usage Instructions

1. Create or edit an action and select the `Simple Chat` action type.
2. In the action modal, enable only the default SimpleChat capabilities that action should expose.
3. Attach that action to an agent in the agent modal.
4. Optionally narrow the capabilities further for that specific agent assignment.
5. Save the agent. The runtime will expose only the resulting enabled SimpleChat functions to the model.

## Testing and Validation

Functional coverage:

- `functional_tests/test_simplechat_agent_action.py`

UI coverage:

- `ui_tests/test_agent_modal_simplechat_capabilities.py`
- `ui_tests/test_workspace_simplechat_action_modal.py`

Validation focus:

- plugin discovery
- action-level capability defaults
- per-agent runtime capability override behavior
- action modal rendering and summary behavior
- agent modal rendering and persistence into additional settings JSON

## Known Limitations

- Group member resolution is only as precise as the signed-in user's Microsoft Graph access and search results.
- The action intentionally reuses the existing direct-add group member flow instead of introducing a separate invite acceptance workflow.