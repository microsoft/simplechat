# Chat Stream Post-Finalization JSON Sanitization Fix (v0.240.063)

Fixed/Implemented in version: **0.240.063**

## Issue Description

Streaming chat responses could finish rendering most or all assistant content, then fail during the post-stream persistence phase with a Cosmos DB `BadRequest` error indicating that the request JSON could not be parsed.

## Root Cause Analysis

The chat finalization path persisted raw citation payloads directly into assistant message documents and assistant artifact records. When tabular or other plugin-generated citations contained non-finite numeric values such as `NaN`, `Infinity`, or `-Infinity`, those values were treated as already JSON serializable and were allowed to flow into Cosmos DB request payloads.

Python's JSON serializer can emit those values as non-standard JSON literals, but Azure Cosmos DB rejects them when parsing request bodies. Because the failure happened after most streamed content had already been generated, the user saw the answer text followed by a late `Stream interrupted` warning.

## Technical Details

### Files Modified

- `application/single_app/functions_message_artifacts.py`
- `application/single_app/route_backend_chats.py`
- `functional_tests/test_chat_post_stream_json_sanitization.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added shared scalar normalization for JSON-safe serialization, including conversion of non-finite numeric values to `None`.
- Reused the shared serializer in chat finalization instead of keeping three local serializer copies with unsafe float handling.
- Sanitized assistant message persistence payloads for both non-streaming and streaming chat paths.
- Sanitized terminal chat payloads returned through `jsonify()` and final SSE completion events.
- Ensured assistant artifact payload JSON is generated from sanitized content.

### Testing Approach

- Added a functional regression test that verifies `make_json_serializable()` converts `NaN` and infinite values to `None`.
- Added a regression check that artifact payload JSON no longer contains `NaN` or `Infinity` tokens.
- Added route-level assertions to ensure the shared serializer is used in the assistant persistence and final response code paths.

### Impact Analysis

- Prevents repeatable late-stream failures caused by invalid numeric values in citations.
- Keeps partial and completed assistant messages eligible for Cosmos DB persistence even when underlying plugin or search data includes non-finite values.
- Improves response reliability for streaming, compatibility streaming, and the legacy JSON chat route.

## Validation

### Before

- Assistant content could stream successfully.
- Post-stream assistant persistence could fail with a Cosmos DB JSON parsing `BadRequest`.
- The UI displayed a `Stream interrupted` warning after most of the response had already been shown.

### After

- Non-finite numeric values in citations are normalized before persistence and final response emission.
- Assistant artifacts and assistant messages use JSON-safe payloads.
- Streaming chat can complete without tripping a Cosmos DB invalid-JSON error caused by `NaN`-style values.