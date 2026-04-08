# NEW_FOUNDRY_REST_STREAMING.md

# New Foundry REST Streaming

## Overview

Version implemented: **0.239.175**

This change adds REST-based streaming support for New Foundry application agents while preserving the existing Semantic Kernel-based path for classic Azure AI Foundry agents.

The goal is to let the app connect to classic and new Foundry simultaneously without taking a runtime dependency on Microsoft Agent Framework or forcing the whole app onto a newer `azure-ai-projects` version that conflicts with Semantic Kernel.

## Dependencies

- Semantic Kernel for classic Foundry agent execution
- Azure Identity credentials for both classic and new Foundry authentication
- Direct REST calls to the New Foundry Responses and project agent-list endpoints
- Existing chat SSE pipeline in the app

## Technical Specification

### Architecture

- Classic Foundry remains on the existing Semantic Kernel + `azure-ai-projects` 1.x path.
- New Foundry uses app-local REST transport in `application/single_app/foundry_agent_runtime.py`.
- New Foundry discovery uses the project `/agents` REST endpoint instead of SDK-only discovery.
- The streaming route in `application/single_app/route_backend_chats.py` now forwards agent deltas as they are produced instead of buffering all chunks first.

### Files Updated

- `application/single_app/foundry_agent_runtime.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_models.py`
- `functional_tests/test_new_foundry_fetch_support.py`
- `functional_tests/test_new_foundry_streaming_runtime.py`

### Runtime Behavior

- New Foundry application requests use the Responses protocol endpoint with `stream=true` for live streaming.
- SSE events are parsed server-side and token deltas are forwarded through the app's `/api/chat/stream` endpoint.
- Final model metadata and citations are still attached to the persisted assistant message when the stream completes.

## Usage

### Configuration

Configure classic and new Foundry endpoints side by side through the existing model endpoint configuration.

- Use provider `aifoundry` for classic Foundry agents.
- Use provider `new_foundry` for New Foundry applications.

### User Workflow

1. Select a classic or new Foundry-backed agent.
2. Send a chat message through the normal chat UI.
3. If the selected agent is New Foundry, the app streams token deltas through `/api/chat/stream`.
4. On completion, the final assistant message includes the full content, model metadata, and any citations captured from the runtime.

## Testing And Validation

- Functional coverage verifies New Foundry fetch support remains available.
- Functional coverage verifies the runtime exposes a REST streaming executor and that the stream route consumes agent chunks incrementally.
- Existing classic Foundry and general stream-route behavior remain on their previous code paths.

## Known Limitations

- Classic Foundry still depends on the existing Semantic Kernel integration and its current Azure SDK boundary.
- `chat_api` still exists for compatibility scenarios outside the initial New Foundry stream path migration.
- Real-time citation SSE events are not expanded in this phase; citations are still finalized when the response completes.