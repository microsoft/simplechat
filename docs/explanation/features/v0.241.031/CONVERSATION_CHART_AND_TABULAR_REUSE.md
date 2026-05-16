# Conversation Chart and Tabular Reuse - v0.241.031

## Overview

Implemented in version: **0.241.031**

This feature makes the built-in chart action available as a core conversation ability and adds a reusable tabular analysis import surface for workflow execution. Users can ask for charts directly in conversation, while agents can still be assigned chart actions for workflow-oriented tool use.

## Dependencies

- `application/single_app/config.py` version `0.241.031`
- Semantic Kernel plugin loading in `application/single_app/semantic_kernel_loader.py`
- Built-in chart plugin in `application/single_app/semantic_kernel_plugins/chart_plugin.py`
- Tabular chat analysis helpers currently implemented in `application/single_app/route_backend_chats.py`

## Technical Specifications

### Architecture

- The conversation-level chart plugin is registered under the non-colliding core plugin name `conversation_charts`.
- Assigned chart actions remain supported through normal action manifests and per-agent `actions_to_load` behavior.
- Workflow tabular document actions now import reusable helpers through `functions_tabular_analysis.py` instead of importing the chat route directly.

### File Structure

- `application/single_app/functions_chart_operations.py` defines the shared core chart plugin name.
- `application/single_app/semantic_kernel_loader.py` loads the chart plugin in model-only, global, and per-user kernel paths.
- `application/single_app/functions_tabular_analysis.py` provides the workflow-facing tabular helper surface.
- `application/single_app/functions_workflow_runner.py` consumes tabular helpers through the reusable module.

## Usage Instructions

Users can ask for charts in chat with prompts such as “make a bar chart of revenue by month.” The chat route now adds chart-tool guidance for chart requests even when no selected agent is active.

Agents can still be configured with chart actions when workflow authors want charting available as an explicit assigned tool.

## Testing and Validation

Functional coverage is provided by `functional_tests/test_conversation_chart_and_tabular_reuse.py`.

The test validates:

- The app version was updated to `0.241.031`.
- The chart plugin is loaded as a core conversation ability.
- Chart prompt guidance applies without a selected agent.
- Workflow tabular execution imports a reusable tabular analysis module.

## Known Limitations

The reusable tabular module is currently a lazy compatibility surface over chat-route implementations. This keeps the runtime behavior stable while creating a dedicated module boundary for a future deeper extraction of the tabular analysis implementation.
