# Chat Backend Inline Chart Handoff

Implemented in version: **0.241.124**

Last validated with config.py version: **0.241.126**

## Overview

Normal chat conversations can now participate in the same inline chart rendering flow used by chart-enabled agents. Explicit chart requests receive backend chart guidance, can fall back through the core conversation chart plugin when Semantic Kernel is available, and preserve any returned `simplechart` blocks in the streamed and saved assistant message.

## Dependencies

- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_chart_operations.py`
- `application/single_app/semantic_kernel_plugins/chart_plugin.py`
- `application/single_app/static/js/chat/chat-inline-charts.js`
- `application/single_app/config.py` version `0.241.126`

## Technical Specifications

### Architecture Overview

The chat route already renders inline chart markdown through the frontend `simplechart` fence parser. This update extends the backend handoff so model-only chat requests get chart guidance before raw GPT fallback, and explicit chart requests can use the kernel-native conversation chart plugin even when no agent is selected.

### Backend Flow

1. The chat route detects explicit chart visualization requests and analytical prompts.
2. Chart guidance is inserted into the system-message prefix before final generation.
3. For explicit chart requests with a Semantic Kernel chat service, the core `conversation_charts` plugin can be auto-invoked without requiring an agent selection.
4. Kernel/plugin invocation results are converted into the same citation payload shape used by agent tools.
5. Returned chart markdown is appended to assistant content when the model did not already place it inline.
6. Streaming responses emit any backend-appended chart markdown as a final content delta before the `done` event, so the live message and persisted message render the same chart.

### Rendering Behavior

The frontend remains responsible for parsing and hydrating charts. `chat-messages.js` extracts `simplechart` fences before markdown rendering, sanitizes the surrounding HTML, injects chart placeholders, and hydrates them with local Chart.js. `chat-streaming.js` uses the same renderer for live updates and final message replacement.

## Usage Instructions

Users can ask normal chat questions such as "Create a bar chart of revenue by month" or "Include a chart and table for this comparison." When the response includes a valid `simplechart` block, the chat UI renders it inline and preserves it after the stream finishes.

## Testing and Validation

Functional coverage:

- `functional_tests/test_chat_backend_inline_chart_handoff.py`

Validation focus:

- chart guidance reaches standard chat fallback paths
- explicit chart requests can use kernel chart tooling without an agent
- plugin-returned chart markdown is appended once
- backend-appended chart markdown streams before final message save

## Known Limitations

Direct raw GPT fallback cannot execute the chart plugin by itself. It receives chart guidance and can emit valid `simplechart` blocks, while plugin-backed generation requires Semantic Kernel and an available chat completion service.