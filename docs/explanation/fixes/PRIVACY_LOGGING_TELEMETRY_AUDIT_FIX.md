# Privacy Logging And Telemetry Audit Fix

Fixed/Implemented in version: **0.242.058**

## Issue Description

The privacy logging and telemetry audit found several diagnostic paths that could copy sensitive payloads into logs or processing activity records. The affected payloads included plugin parameters, plugin result samples, multi-agent message content, document chunk text, full document metadata, and raw vision model response text.

## Root Cause Analysis

Some logging paths favored full diagnostic payloads instead of minimized telemetry. Plugin decorator logs emitted raw parameter dictionaries and result previews, agent orchestrator callbacks logged full response content, and document-processing activity records included uploaded document text or full metadata for troubleshooting.

## Technical Details

Files modified:

- `application/single_app/functions_appinsights.py`
- `application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`
- `application/single_app/agent_orchestrator_groupchat.py`
- `application/single_app/agent_orchestrator_magnetic.py`
- `application/single_app/functions_documents.py`
- `application/single_app/config.py`
- `functional_tests/test_privacy_logging_telemetry_audit.py`

Code changes summary:

- Added central `log_event(...)` redaction for secret-bearing keys, Authorization values, connection strings, tokens, API keys, and SAS-style signatures while preserving general telemetry volume.
- Changed plugin decorator parameter logs to record names, counts, and value shapes instead of raw values.
- Redacted plugin JSON serialization, replaced raw plugin result previews with type/key/length summaries, and removed tabular result value samples from structured telemetry summaries.
- Changed group chat and Magentic agent orchestration logs to record agent names, roles, message types, and content lengths instead of full message content.
- Replaced document-processing task logs that contained raw query results, chunk text, metadata JSON, or vision response text with counts and lengths.

## Validation

Testing approach:

- Added `functional_tests/test_privacy_logging_telemetry_audit.py` to validate redaction helpers and source-level guardrails for the audited logging patterns.
- Updated version-pinned functional tests to match the current `config.py` version.

Before/after comparison:

- Before: diagnostics could store raw uploaded text, full agent responses, plugin parameters, tabular value samples, or secret-bearing fields.
- After: diagnostics keep event names, IDs, counts, shapes, lengths, timings, and status while redacting credentials and minimizing private content payloads.

Related version update:

- `application/single_app/config.py` was incremented to `0.242.058`.