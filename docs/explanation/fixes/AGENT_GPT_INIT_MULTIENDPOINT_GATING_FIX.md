# Agent GPT Init Multi-Endpoint Gating Fix (Version 0.236.052)

## Overview
Ensures multi-endpoint GPT resolution is skipped for agent-based requests and avoids APIM initialization failures when no model deployment is provided.

## Issue Description
Agent chat requests include `agent_info` but no `model_id` or `model_deployment`. With APIM enabled and multiple deployments configured, GPT initialization failed before agent invocation, blocking the request.

## Root Cause Analysis
`resolve_multi_endpoint_gpt_config` runs early in chat initialization, and APIM requires `model_deployment` when multiple deployments are configured. Agent requests do not send these fields, causing premature failures.

## Fix Summary
- Skip multi-endpoint GPT resolution when `agent_info` is present.
- Default to the first APIM deployment for agent requests without `model_deployment`.

## Files Modified
- application/single_app/route_backend_chats.py
- application/single_app/config.py
- functional_tests/test_agent_gpt_init_skips_multiendpoint.py

## Testing
- Added functional test: `test_agent_gpt_init_skips_multiendpoint.py`.

## Validation
- Verified GPT init gating logs and APIM defaulting behavior for agent requests.

## Version
Fixed/Implemented in version: **0.236.052**

## Config Version Reference
`config.py` updated to `VERSION = "0.236.052"`.
