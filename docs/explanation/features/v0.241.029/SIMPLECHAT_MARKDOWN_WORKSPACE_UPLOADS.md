# SIMPLECHAT_MARKDOWN_WORKSPACE_UPLOADS.md

# SimpleChat Markdown Workspace Uploads

Implemented in version: **0.241.029**

## Overview

This enhancement adds a new SimpleChat capability for creating Markdown files and uploading them into workspaces through the existing document-ingestion pipeline. It is intended for cases where an agent produces a summary, notes, or other structured output that should be saved as a searchable workspace document instead of remaining only in chat.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.029"`.

## Dependencies

- Existing personal workspace document upload pipeline
- Existing group workspace document upload pipeline and group role enforcement
- Existing Markdown document processor in `functions_documents.py`
- Shared SimpleChat Semantic Kernel plugin loading and capability filtering
- Workspace action and agent capability configuration modals

## Technical Specifications

### Architecture Overview

- Shared backend operations: `application/single_app/functions_simplechat_operations.py`
- Built-in SK plugin: `application/single_app/semantic_kernel_plugins/simplechat_plugin.py`
- Document metadata and background ingestion: `application/single_app/functions_documents.py`
- Workspace action capability UI: `application/single_app/static/js/plugin_modal_stepper.js`
- Agent capability UI: `application/single_app/static/js/agent_modal_stepper.js`

### Runtime Behavior

- New SimpleChat capability: `upload_markdown_document`
- New plugin function: `upload_markdown_document(file_name, markdown_content, workspace_scope="personal", group_id="")`
- The helper writes the supplied Markdown into a temporary `.md` file and queues the existing `process_document_upload_background(...)` flow.
- Personal uploads invalidate the personal search cache and log a normal personal document upload activity.
- Group uploads enforce the same upload rules as the group document route:
  - group existence check
  - group status `upload` allowance
  - `Owner`, `Admin`, or `DocumentManager` role requirement
- Group uploads can target an explicit `group_id`, the action's `default_group_id`, or the user's active group when group scope is requested.

### Capability Storage

The new capability follows the existing SimpleChat capability map structure in action defaults and `other_settings.action_capabilities`.

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
      "upload_markdown_document": true,
      "create_personal_collaboration_conversation": false
    }
  }
}
```

## Usage Instructions

1. Create or edit a `Simple Chat` action.
2. Leave `Upload markdown documents` enabled for any agent that should be able to save generated summaries or notes into a workspace.
3. Call `upload_markdown_document` with a file name and Markdown content.
4. Use `workspace_scope="personal"` for the personal workspace, or `workspace_scope="group"` with a target group when the output should be stored in a group workspace.

## Testing And Validation

Functional coverage:

- `functional_tests/test_simplechat_agent_action.py`
- `functional_tests/test_simplechat_markdown_upload.py`

UI coverage:

- `ui_tests/test_agent_modal_simplechat_capabilities.py`
- `ui_tests/test_workspace_simplechat_action_modal.py`

Validation focus:

- capability exposure in workspace and agent modals
- runtime filtering of the new capability
- personal Markdown upload queueing through the existing document processor
- group Markdown upload queueing with normal group permission checks
- plugin forwarding of default group context

## Known Limitations

- This capability currently supports Markdown documents only.
- Upload processing remains asynchronous, so the action returns a queued document record rather than waiting for indexing to finish.