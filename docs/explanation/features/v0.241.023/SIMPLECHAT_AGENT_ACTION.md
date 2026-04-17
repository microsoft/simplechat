# SimpleChat Agent Action

Implemented in version: **0.241.023**

## Overview

The SimpleChat Agent Action adds a native action type that can create groups, add users to groups, create group collaborative conversations, create personal conversations, and create personal collaborative conversations.

This action always runs in the invoking user's identity and permission context, even when the action itself is globally defined.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.023"`.

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
- Loader overlay for per-agent capability filtering: `application/single_app/semantic_kernel_loader.py`
- Plugin validation and registration support: `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`, `application/single_app/semantic_kernel_plugins/logged_plugin_loader.py`
- Shared agent modal capability UI: `application/single_app/templates/_agent_modal.html`, `application/single_app/static/js/agent_modal_stepper.js`

### Runtime Behavior

- Group creation reuses the existing `enable_group_workspaces`, `enable_group_creation`, and `CreateGroups` role checks.
- Group membership changes reuse the existing direct-add behavior; no new approval workflow was introduced.
- Group conversation creation falls back to the agent's group context or the user's active group when `group_id` is omitted.
- Personal collaborative conversation creation resolves invitees through Microsoft Graph using the current user's access token.
- Per-agent capability selections are stored in `other_settings.action_capabilities` and trimmed into the plugin's exposed SK functions at load time.

### Per-Agent Capability Storage

Capability settings are stored per selected action ID under `other_settings.action_capabilities`.

Example:

```json
{
  "action_capabilities": {
    "simplechat-action-id": {
      "create_group": true,
      "add_group_member": false,
      "create_group_conversation": true,
      "create_personal_conversation": true,
      "create_personal_collaboration_conversation": false
    }
  }
}
```

## Usage Instructions

1. Create or edit an action and select the `Simple Chat` action type.
2. Attach that action to an agent in the agent modal.
3. Select the Simple Chat action in step 4.
4. Enable only the capabilities that agent should expose.
5. Save the agent. The runtime will expose only those enabled Simple Chat functions to the model.

## Testing and Validation

Functional coverage:

- `functional_tests/test_simplechat_agent_action.py`

UI coverage:

- `ui_tests/test_agent_modal_simplechat_capabilities.py`

Validation focus:

- plugin discovery
- SK function filtering
- agent runtime capability overlay
- modal rendering and persistence into additional settings JSON

## Known Limitations

- Group member resolution is only as precise as the signed-in user's Microsoft Graph access and search results.
- Capability toggles are currently exposed only in the shared agent modal, not in action creation.
- The action intentionally reuses the existing direct-add group member flow instead of introducing a separate invite acceptance workflow.