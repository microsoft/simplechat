# Chart Action Inline Rendering

## Overview

Implemented in version: **0.241.047**

The built-in `chart` action adds inline Chart.js visualizations to the chat experience. Agents can now generate interactive charts that render directly inside assistant messages instead of returning detached artifacts or raw JSON.

Dependencies:

- `application/single_app/semantic_kernel_plugins/chart_plugin.py`
- `application/single_app/static/js/chart.min.js`
- `application/single_app/static/js/chat/chat-inline-charts.js`

## Technical Specifications

### Architecture Overview

The feature is implemented as a first-class built-in Semantic Kernel action. The backend chart plugin validates chart requests, produces a constrained chart payload, and returns a fenced inline chart block. The chat backend appends those validated blocks to the saved assistant message so streaming completion, persisted history, and message reloads all render the same chart output.

### Supported Chart Types

- Line
- Bar
- Pie
- Doughnut
- Scatter
- Area
- Bubble
- Radar
- Stacked bar
- Stacked line

### Configuration Model

Action-level configuration stores `additionalFields.chart_capabilities` so admins can choose which chart types are enabled by default for an action.

Agent-level configuration stores per-assignment overrides in `other_settings.action_capabilities`, allowing an agent to narrow the enabled chart types for a selected chart action without changing the shared action definition.

### Rendering Flow

1. The `chart` plugin validates and normalizes chart data into a safe Chart.js payload.
2. The plugin returns `chart_markdown` using a `simplechart` fenced block.
3. `route_backend_chats.py` appends that fenced block to the final assistant content.
4. `chat-messages.js` extracts the fenced block before markdown rendering, sanitizes the rest of the message, injects a safe chart placeholder, and hydrates it with Chart.js.
5. `chat-streaming.js` uses the same renderer during streaming updates and finalization.

## Usage Instructions

### Enable and Configure

Create or edit an action of type `chart` from the actions modal. In the configuration step, enable the chart types that action should expose by default. Assign the action to an agent, then use the agent modal to narrow the chart types for that specific assignment if needed.

### User Workflow

When an agent uses the chart action, the assistant response can contain narrative text plus one or more inline charts. Users can interact with the chart legend, resize with the page layout, and expand a data table for the plotted values.

### Integration Points

- Action creation UI: `templates/_plugin_modal.html`
- Agent assignment UI: `templates/_agent_modal.html`
- Chat rendering: `static/js/chat/chat-messages.js`
- Streaming rendering: `static/js/chat/chat-streaming.js`

## Testing and Validation

Functional coverage:

- `functional_tests/test_chart_action_inline_rendering.py`

UI coverage:

- `ui_tests/test_chat_inline_chart_rendering.py`

Validation focus:

- chart payload normalization and markdown generation
- per-action chart capability defaults
- per-agent chart type narrowing
- inline rendering on both saved messages and streaming updates

Known limitations:

- UI tests require an authenticated chat URL and optional browser storage state supplied through environment variables.