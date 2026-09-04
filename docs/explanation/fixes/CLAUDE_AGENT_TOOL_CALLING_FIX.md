# Claude Agent Tool Calling Fix

Fixed/Implemented in version: **0.250.007**

## Issue Description

Claude-backed local Semantic Kernel agents could load actions/plugins successfully but fail to initiate plugin queries during agent turns. The model response completed normally, so users saw an answer, but no per-conversation plugin invocations were recorded for data-backed prompts.

## Root Cause Analysis

The Anthropic Semantic Kernel adapter was marked as not supporting function calling and only forwarded plain chat messages. Semantic Kernel therefore did not have a service-level contract for translating loaded kernel functions into Claude tool calls, even though the agent loader had already registered the SQL and schema plugins.

## Technical Details

Files modified:

- `application/single_app/model_endpoint_clients.py`
- `application/single_app/config.py`
- `functional_tests/test_claude_agent_tool_calling.py`

Code changes summary:

- Added Anthropic tool schema conversion for Semantic Kernel/OpenAI-style function metadata.
- Converted Anthropic `tool_use` responses into Semantic Kernel `FunctionCallContent` so the existing auto-invoke loop can run plugins.
- Converted Semantic Kernel function call and function result history back into Anthropic `tool_use` and `tool_result` message blocks for follow-up turns.
- For streaming Claude agent turns with tools enabled, used a non-streaming Anthropic request internally and emitted the resulting tool call or text as a stream chunk so SK auto invocation remains reliable.

## Validation

Test coverage:

- `functional_tests/test_claude_agent_tool_calling.py`

Expected behavior after the fix:

- Claude-backed local agents still use the Anthropic messages protocol.
- Loaded SQL and other Semantic Kernel plugins are exposed as Claude tools.
- Claude `tool_use` responses trigger normal plugin execution and plugin invocation citations for the active conversation.

Version reference: `application/single_app/config.py` is at **0.250.007** for this fix.