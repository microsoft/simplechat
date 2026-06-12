# Anthropic Analyze/Compare Workflow Stream Fix (v0.241.193)

Fixed/Implemented in version: **0.241.193**

## Issue Description

Chat and workflow Analyze/Compare document actions could fail after selecting a Claude or Anthropic model endpoint. The chat document-action stream surfaced the failure while the underlying workflow execution still built an Azure OpenAI client for selected workflow model endpoints.

Anthropic streaming calls could also fail or hide useful provider errors because stream requests used an `application/json` accept header and Anthropic SSE `error` events were ignored by the OpenAI-shaped adapter.

## Root Cause Analysis

The chat streaming model endpoint builder was already protocol-aware, but the workflow runner's selected model endpoint resolver always instantiated Azure OpenAI clients. Analyze/Compare actions invoked through workflow execution therefore did not preserve the Anthropic protocol selection for Claude deployments.

The Anthropic adapter also treated all requests as JSON responses at the header level and only parsed successful SSE data events. Provider-side stream errors could pass through as an empty or incomplete response instead of a clear runtime failure.

## Technical Details

Files modified:

- `application/single_app/model_endpoint_clients.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/config.py`
- `functional_tests/test_analyze_compare_claude_workflow_stream.py`

Code changes summary:

- Routed workflow-selected Claude/Anthropic model endpoints through `build_anthropic_chat_client` instead of Azure OpenAI client construction.
- Preserved OpenAI-compatible Foundry endpoint behavior through `build_openai_style_chat_client` for non-Claude project endpoints.
- Sent `Accept: text/event-stream` for Anthropic stream requests.
- Surfaced Anthropic SSE `error` events as clear runtime errors and preserved stream usage metadata.
- Added regression coverage for Claude workflow endpoint resolution, OpenAI-style endpoint preservation, Anthropic SSE parsing, and chat document-action stream wiring.
- Updated `application/single_app/config.py` to version **0.241.193**.

## Validation

Test results:

- `python -m py_compile application/single_app/model_endpoint_clients.py application/single_app/functions_workflow_runner.py functional_tests/test_analyze_compare_claude_workflow_stream.py application/single_app/config.py`
- `python functional_tests/test_analyze_compare_claude_workflow_stream.py`
- `python functional_tests/test_model_endpoint_protocol_inference.py`
- `python functional_tests/test_foundry_workflow_agent_payload.py`

Before this fix, Analyze/Compare actions using Claude model endpoints could fail inside workflow execution or produce unclear stream failures. After this fix, chat and workflow Analyze/Compare paths resolve Claude endpoints through the Anthropic adapter and report Anthropic stream provider errors cleanly.