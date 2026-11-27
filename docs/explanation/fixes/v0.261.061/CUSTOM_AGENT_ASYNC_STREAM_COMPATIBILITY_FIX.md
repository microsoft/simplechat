# Custom Agent Async Stream Compatibility Fix

Fixed/Implemented in version: **0.261.061**

## Issue

Schema-v2 custom endpoint agents reached APIM successfully and received an HTTP
200 streaming response, but the chat ended before returning content.

## Root Cause

SimpleChat sanitizes provider errors by wrapping OpenAI SDK streams. The async
wrapper delegated iteration correctly, but it no longer satisfied the SDK's
`AsyncStream` runtime type contract. Semantic Kernel therefore treated the
response as a completed response and attempted to read a `usage` attribute that
streaming responses do not provide.

## Technical Details

- Updated `application/single_app/model_endpoint_clients.py`.
- Preserved the OpenAI SDK `Stream` and `AsyncStream` runtime contracts while
  retaining SimpleChat's provider-error sanitization.
- Added an actual Semantic Kernel streaming-agent regression using an OpenAI
  SDK client and mock server-sent events.
- Updated `application/single_app/config.py` to version `0.261.061`.

## Validation

The regression reproduces the deployed failure path: a schema-v2 agent invokes
an OpenAI-compatible streaming endpoint through the sanitized client. It
verifies that Semantic Kernel consumes the stream and returns the expected text
instead of accessing a nonexistent stream-level `usage` attribute.

## Impact

Custom OpenAI-compatible agents can consume streaming APIM responses without
exposing raw provider errors to browser clients. Non-streaming requests and
existing route capability enforcement are unchanged.
