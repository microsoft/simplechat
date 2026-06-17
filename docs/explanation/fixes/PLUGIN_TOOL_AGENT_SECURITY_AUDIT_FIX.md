# Plugin Tool And Agent Security Audit Fix

Fixed/Implemented in version: **0.242.056**

## Issue Description

The plugin/tool/agent security audit found that resolved action credentials and sensitive tool payload fields could be echoed into plugin invocation logs, chat citations, workflow citations, and OpenAPI diagnostic/error payloads after runtime secret resolution.

## Root Cause Analysis

Plugin invocation records stored raw parameters, results, and errors, and browser-facing log APIs serialized those records directly. Chat and workflow citation builders also copied raw invocation fields into assistant citation payloads. The OpenAPI plugin logged request headers, query parameters, resolved request URLs, and error payloads without redacting API keys, bearer tokens, basic credentials, or secret-bearing query strings. SimpleChat group helper fallback also read `activeGroupOid` directly instead of using the shared active-group authorization helper.

## Technical Details

Files modified:

- `application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`
- `application/single_app/route_plugin_logging.py`
- `application/single_app/semantic_kernel_plugins/logged_plugin_loader.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/semantic_kernel_plugins/openapi_plugin.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/config.py`
- `functional_tests/test_plugin_tool_agent_security_audit.py`

Code changes summary:

- Added a reusable plugin invocation redactor for secret-like keys, Authorization values, credentials embedded in URLs, and sensitive query parameters.
- Added safe invocation serialization for plugin log API responses and logged plugin loader helpers.
- Updated chat and workflow citation builders to use redacted parameters, results, and errors.
- Redacted OpenAPI debug/log statements, response headers, request URLs, exception payloads, and HTTP error payload URLs.
- Replaced the SimpleChat active group fallback with `require_active_group(...)`.

## Validation

Testing approach:

- Added a focused functional regression test covering plugin invocation safe serialization, OpenAPI redaction helpers, and SimpleChat source-level use of `require_active_group(...)` for active group fallback.

Before/after comparison:

- Before: resolved auth headers, API-key query parameters, and secret-like invocation fields could appear in logs, citations, exports, or OpenAPI errors.
- After: browser/model-visible plugin invocation payloads and OpenAPI diagnostics redact secret-bearing values while preserving non-sensitive diagnostic context.

Related version update:

- `application/single_app/config.py` was incremented from `0.242.054` to `0.242.056`.