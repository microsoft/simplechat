# M365 JSON response finalization and static-file delivery

Fixed/Implemented in version: **0.261.048**

Tracking: [#1602](https://github.com/microsoft/simplechat/issues/1602).

## Issue and root cause

Requests for `/static/json/schemas/plugin.schema.json` failed with:

```text
RuntimeError: Attempted implicit sequence conversion but the response object is in direct passthrough mode.
```

The global `finalize_m365_json_request` after-request hook inspected every response
with a JSON content type using `response.get_json()`. Flask serves static files
through a direct-passthrough response. Reading that response body requires implicit
buffering, which Werkzeug deliberately rejects in this mode. The schema itself
is valid and does not need changing.

An ordinary generator-backed JSON response could also be consumed prematurely
by this hook even without direct-passthrough mode.

## Changes and impact

- [app.py](../../../application/single_app/app.py): return direct-passthrough and
  streamed responses unchanged before attempting JSON parsing.
- [config.py](../../../application/single_app/config.py): application version
  incremented to `0.261.048`.
- Buffered JSON API responses retain the existing success, error, pending, and
  status-code completion behavior. Completion errors are not suppressed.
- No MIME types, schema contents, authentication rules, routes, response buffering
  settings, or cloud resources are changed.
- The chat streaming worker retains responsibility for M365 completion at the
  stream's terminal event; the after-request hook does not finalize streams early.

This protects static JSON files and JSON downloads without forcing files into
memory or applying a path-specific exception.

## Validation

[Regression tests](../../../functional_tests/test_m365_json_response_finalization.py)
register the actual hook in an isolated Flask app. They avoid importing the
cloud-initializing application bootstrap and block outbound networking.

Coverage includes:

- Actual plugin schema GET with exact bytes, JSON MIME type, length, ETag, and
  Last-Modified headers.
- HEAD, byte-range GET (206), and conditional GET (304).
- File downloads, buffered direct-passthrough responses, generator-backed JSON,
  structured JSON MIME types, and SSE without premature consumption.
- Existing buffered JSON success/failure/pending classification and explicit
  propagation of completion failures.

Before the change, the static schema tests reproduced the reported Werkzeug
exception. After the change, the hook skips file/stream bodies while preserving
normal JSON request finalization.

Related feature: [Microsoft 365 actions](../features/MICROSOFT_365_ACTIONS.md).
