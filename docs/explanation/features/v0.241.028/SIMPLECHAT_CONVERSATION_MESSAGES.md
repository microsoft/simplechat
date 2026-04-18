# SIMPLECHAT_CONVERSATION_MESSAGES.md

# SimpleChat Conversation Messaging

Implemented in version: **0.241.028**

## Overview

This enhancement extends the SimpleChat action so agents can do more than create conversations. They can now add a user-authored message to an existing personal or collaborative conversation, and they can optionally seed a newly created conversation with an initial message when the add-message capability is enabled.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.028"`.

## Dependencies

- Existing personal conversation storage in Cosmos DB
- Existing collaborative conversation persistence and notification helpers
- Shared SimpleChat Semantic Kernel plugin loading and capability filtering
- Workspace action and agent capability configuration modals

## Technical Specifications

### Architecture Overview

- Shared backend operations: `application/single_app/functions_simplechat_operations.py`
- Built-in SK plugin: `application/single_app/semantic_kernel_plugins/simplechat_plugin.py`
- Workspace action capability UI: `application/single_app/static/js/plugin_modal_stepper.js`
- Agent capability UI: `application/single_app/static/js/agent_modal_stepper.js`

### Runtime Behavior

- New SimpleChat capability: `add_conversation_message`
- New plugin function: `add_conversation_message(conversation_id, content, reply_to_message_id="")`
- Personal conversation message posting writes a user message into the existing personal message container and updates the conversation timestamp and default title.
- Collaborative conversation message posting reuses the existing collaboration authorization, persistence, and notification pipeline.
- `create_personal_conversation`, `create_group_conversation`, and `create_personal_collaboration_conversation` now accept an optional `initial_message`.
- Initial-message seeding is blocked unless the action instance also enables the `add_conversation_message` capability.

### Capability Storage

The capability continues to follow the existing SimpleChat capability map structure in action defaults and `other_settings.action_capabilities`.

Example:

```json
{
  "action_capabilities": {
    "simplechat-action-id": {
      "create_group": false,
      "add_group_member": false,
      "create_group_conversation": true,
      "create_personal_conversation": true,
      "add_conversation_message": true,
      "create_personal_collaboration_conversation": false
    }
  }
}
```

## Usage Instructions

1. Create or edit a `Simple Chat` action.
2. Leave `Add conversation messages` enabled for any agent that should be able to seed or append messages.
3. Attach the action to an agent and adjust per-agent capability overrides if needed.
4. Call either the dedicated `add_conversation_message` function or pass `initial_message` when creating a supported conversation.

## Testing And Validation

Functional coverage:

- `functional_tests/test_simplechat_agent_action.py`
- `functional_tests/test_simplechat_conversation_messages.py`

UI coverage:

- `ui_tests/test_agent_modal_simplechat_capabilities.py`
- `ui_tests/test_workspace_simplechat_action_modal.py`

Validation focus:

- capability exposure in workspace and agent modals
- runtime filtering of the new capability
- personal conversation message persistence
- collaborative conversation message persistence reuse
- initial-message seeding guard behavior

## Known Limitations

- Initial-message seeding currently applies only to the SimpleChat create-conversation plugin functions that were extended in this change.
- The inserted message is always written as a user-authored message in the invoking user's context.