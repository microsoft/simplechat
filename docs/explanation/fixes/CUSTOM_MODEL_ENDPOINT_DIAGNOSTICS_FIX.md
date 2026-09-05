# Custom Model Endpoint Diagnostics Fix

## Issue

Every failure on a Custom model endpoint produced the same message:

```
Custom model request failed.
```

A wrong base path, a wrong API key, a wrong model name, a TLS handshake failure,
a blocked address, and an upstream outage were all indistinguishable. Nothing
was written anywhere that explained which had happened.

This was made worse by URL normalization. SimpleChat rewrites a configured
endpoint URL into a request URL, and that rewrite was invisible, so an
administrator debugging a 404 could not see the URL that was actually called.

**Fixed in version: 0.261.015**

## Root cause

The Custom endpoint paths deliberately sanitized errors before they reached the
browser, which is correct: an upstream error body can echo back a request URL, a
request header, or an API key. But sanitization was implemented by discarding the
cause outright:

```python
raise RuntimeError("Custom model request failed.") from None
```

`from None` suppresses the exception chain, so the original exception never
reached the log either. The result was safe and undebuggable.

Seven failure paths did this:

| Location | Failure |
|---|---|
| `OpenAIStyleChatCompletionClient.create` | OpenAI-compatible request |
| `_SanitizedSyncIterator.__next__` | OpenAI-compatible stream |
| `_SanitizedAsyncIterator.__anext__` | OpenAI-compatible async stream |
| `SanitizedCustomChatCompletionClient.create` | Azure OpenAI SDK request |
| `sanitize_custom_async_openai_client` | Azure OpenAI async SDK request |
| `AnthropicChatCompletionClient._create_direct_custom` | Anthropic request, non-2xx response, and invalid body |
| `AnthropicChatCompletionClient._iter_stream_chunks` | Anthropic stream |

## Files modified

- **`functions_model_endpoint_diagnostics.py`** (new) — redaction, correlation
  ids, and the shared sanitized-error builder.
- **`model_endpoint_clients.py`** — all seven failure paths now route through the
  diagnostics helper and carry API type, protocol, and resolved request URL.
- **`functions_model_endpoint_runtime.py`** — passes the API type and resolved
  request URL into the sanitized client wrappers.

## Behaviour after the fix

### What the browser sees

```
Custom model request failed. (reference f8893cfc)
```

No secret, no internal URL, no upstream body — only the reference id.

### What the server log records

```
[CUSTOM_MODEL_ENDPOINT] Custom model request failed. (correlation_id=f8893cfc)
  correlation_id: f8893cfc
  api_type:       gemini
  request_url:    https://generativelanguage.googleapis.com/v1beta/openai/
  status_code:    401
  detail:         {"error":{"message":"API key not valid"}}
  error_type:     ValueError
  error:          upstream said: invalid api_key: [REDACTED] at https://internal.corp/v1
```

The resolved `request_url` is included on purpose, because it is the single most
useful diagnostic when URL normalization has rewritten what was configured.

### Redaction

Credential-shaped values are redacted before anything is logged:

| Shape | Example |
|---|---|
| `api_key` / `api-key` fields | `api_key: [REDACTED]` |
| `Authorization` headers | `Authorization: [REDACTED]` |
| Bearer tokens | `Bearer [REDACTED]` |
| `x-api-key`, `x-goog-api-key` | `x-api-key: [REDACTED]` |
| `?key=`, `?api_key=`, `?access_token=` | `?key=[REDACTED]` |
| OpenAI-style `sk-` keys | `[REDACTED]` |

Logged detail is truncated at 2000 characters so a large upstream body cannot
flood the log.

### Failure isolation

Diagnostics never replace the original failure. If the logging backend raises,
the exception is swallowed and a correlation id is still returned, so a logging
outage cannot mask a model error.

## Validation

`functional_tests/test_custom_model_endpoint_diagnostics.py` verifies:

- credentials are redacted across six credential shapes, while ordinary
  diagnostic text survives intact and oversized detail is truncated;
- the sanitized browser message contains no secret, no internal URL, and no
  upstream body;
- the reference id shown to the user is the `correlation_id` recorded in the
  log, and the log carries API type, status code, resolved URL, and error type;
- a logging failure does not mask the original error;
- no Custom failure path in `model_endpoint_clients.py` still discards its cause,
  enforced by scanning the source for the `from None` pattern.

`functional_tests/test_custom_model_endpoint_provider.py` was updated: it
previously asserted the message was exactly `"Custom model request failed."`, and
now asserts the security property — no leaked provider detail — plus the presence
of a reference id.

## Before and after

| | Before | After |
|---|---|---|
| Browser message | `Custom model request failed.` | `Custom model request failed. (reference f8893cfc)` |
| Secrets exposed | None | None |
| Server log | Nothing | API type, resolved URL, status, redacted upstream detail |
| Distinguishing a 404 from a 401 | Impossible | Status code in the log |
| Seeing the rewritten URL | Impossible | `request_url` in the log |
