# Foundry Workflow Agents

Implemented in version: **0.241.127**

Updated in version: **0.241.128**

## Overview

SimpleChat supports generic Microsoft Foundry workflow agents as selectable chat agents through the `foundry_workflow` agent type. The feature is workflow-name driven and does not hardcode any specific workflow names.

## Dependencies

- Microsoft Foundry project endpoint with permission to invoke workflow agents
- Existing SimpleChat Foundry managed identity, service principal, or default credential access
- Project workflow OpenAI-compatible REST protocol version configured on the agent or endpoint

## Technical Specifications

### Architecture

- Agent records store workflow configuration in `other_settings.foundry_workflow`.
- Runtime invocation mirrors the Foundry SDK flow: create a Foundry OpenAI conversation, call Responses with `agent_reference`, stream events, and delete the Foundry conversation after the run.
- The verified OpenAI-compatible workflow REST protocol for the test project uses `v1` paths such as `/openai/v1/responses` and `/openai/v1/conversations`, without an `api-version` query parameter.
- The UI defaults workflow agents to `v1` and no longer exposes `v2` as a normal REST protocol option. Existing saved `v2` workflow values are normalized to `v1` at runtime.
- Dated preview versions are sent as `api-version` query parameters on both conversation and response endpoints.
- Streaming chat keeps the HTTP stream open for workflow action events but buffers workflow text deltas and emits the completed final answer once, avoiding partial outline-only chat bubbles.
- Foundry `response.failed` streaming events surface `response.error.message` directly, so workflow-internal failures are readable.
- Existing selected workspace document and chat-upload context continues to flow through the normal chat history and augmentation pipeline.
- Selected workspace files and recent blob-backed chat uploads are attached to workflow requests when possible as Foundry `input_file` content parts with `data:<mime>;base64,...` file data. This includes image uploads, which were verified against Foundry workflows using the `input_file` shape. The same shared collector and payload shape is used for normal new-Foundry Responses agents.

### Configuration

Required workflow settings:

```json
{
  "agent_type": "foundry_workflow",
  "other_settings": {
    "foundry_workflow": {
      "workflow_name": "YourWorkflowName",
      "endpoint": "https://<resource>.services.ai.azure.com/api/projects/<project>",
      "responses_api_version": "v1",
      "include_document_context": true,
      "max_context_chars": 24000,
      "include_file_inputs": true,
      "max_file_inputs": 5,
      "max_file_input_bytes": 8388608
    }
  }
}
```

Optional settings include `project_name`, `responses_path`, `conversations_path`, authentication fields, `foundry_scope`, `include_file_inputs`, `max_file_inputs`, `max_file_input_bytes`, and admin `notes`. A saved Foundry connection can be selected to fetch workflows and reuse endpoint credentials, but users can also enter the project endpoint, project name, workflow name, and workflow REST protocol version manually.

### File Structure

- `application/single_app/foundry_agent_runtime.py` - workflow runtime, conversation lifecycle, protocol path routing, stream text buffering/error extraction, and discovery facade
- `application/single_app/functions_agent_payload.py` - workflow payload validation
- `application/single_app/semantic_kernel_loader.py` - workflow agent construction
- `application/single_app/route_backend_chats.py` - selected-agent chat invocation and metadata persistence
- `application/single_app/route_backend_agents.py` - manual Foundry endpoint preservation for personal and group agents
- `application/single_app/templates/_agent_modal.html` - workflow configuration controls
- `application/single_app/static/js/agent_modal_stepper.js` - workflow modal state and serialization

## Usage Instructions

1. Create or edit an agent.
2. Select **Foundry Workflow** as the agent type.
3. Optionally select a saved Foundry connection to fetch workflows and reuse credentials.
4. Enter the Foundry project endpoint, project name, workflow name, and workflow REST protocol version.
5. Save the agent and select it in chat.
6. Send normal chat text with optional selected workspace documents or uploaded chat files.
7. For blob-backed uploads and selected documents, SimpleChat attaches bounded file bytes directly to the Foundry workflow request when the file is available and within the configured size/count limits.

## Testing and Validation

- Functional payload validation: `functional_tests/test_foundry_workflow_agent_payload.py`
- Modal control coverage: `ui_tests/test_agent_modal_foundry_workflow.py`
- Live endpoint probe confirmed `POST /openai/v1/conversations`, `POST /openai/v1/responses`, and `DELETE /openai/v1/conversations/{id}` against the Retroburn Foundry project.
- Live file probe confirmed that Foundry workflows accept image bytes as `input_file` with a data URI in `file_data`; raw Base64 and `input_image` data URI requests returned server errors for the tested workflow.

## Known Limitations

- Workflow discovery currently uses the project agent/application listing facade and can be refined if Foundry exposes a more specific workflow list endpoint.
- File pass-through is bounded by count and byte-size limits. Files that cannot be resolved from existing authorized document/chat context, cannot be downloaded, or exceed the configured limit are skipped while the text context still flows.
- `responses_path` and `conversations_path` can override the default project OpenAI paths if a Foundry project uses a different endpoint shape.

## Config Version Reference

This feature corresponds to the `VERSION = "0.241.128"` update in `application/single_app/config.py` for file input handoff support.
