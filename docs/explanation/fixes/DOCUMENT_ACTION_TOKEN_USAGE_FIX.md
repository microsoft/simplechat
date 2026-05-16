# Document Action Token Usage Fix

Fixed in version: **0.241.116**

## Overview

Analyze and comparison document actions were not preserving aggregate token usage across their internal model calls.
This caused large multi-document runs to under-report usage even when the coverage metadata showed hundreds or thousands of processed windows and chunks.

## Root Cause

The document action workflow wrapped every model and agent invocation in an `invoke_prompt` adapter that converted responses directly to strings.
That adapter dropped `usage`, so analysis and comparison only kept text and coverage, not the cumulative prompt and completion totals from all internal calls.

## Technical Details

Files modified:

- `application/single_app/functions_workflow_runner.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_document_action_token_usage_aggregation.py`

Code changes summary:

- Added token usage extraction and aggregation helpers in the workflow runner.
- Aggregated token usage across every internal analysis and comparison model call.
- Persisted aggregated token usage on workflow and chat assistant message metadata.
- Logged aggregated document action token usage to activity logs for reporting.

## Validation

Functional test:

- `functional_tests/test_document_action_token_usage_aggregation.py`

Validation approach:

- Verifies analysis token totals are summed across multiple internal invokes.
- Verifies comparison token totals are summed across multiple internal invokes.
- Verifies workflow assistant metadata stores the aggregated token usage.
- Verifies chat document action persistence includes the aggregated token usage field and activity logging call.

## Impact

Before:

- Large analysis and comparison runs could report token usage from only a subset of internal model calls.

After:

- Analyze and comparison runs store and log aggregate prompt, completion, and total tokens for the full document action execution.