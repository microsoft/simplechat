# Orchestration crash diagnostics

Version: **0.261.451**

Fixed/Implemented in version: **0.261.451** (`application/single_app/config.py`).

## Issue description

An orchestration request failed during planning with "The request could not be planned or
saved. Please retry." The only telemetry record was `[ORCHESTRATION] Planning failed.` with
`sc_exception_type_length: 8`. It carried no exception class, no code location and no
conversation hash, so the failure could not be found or tied to the conversation.

## Root cause

- `log_event` keeps the text of a property only when its key is on an allow-list. `error_type`
  was listed; `exception_type` was not. Every `exception_type` property in the application,
  about 110 call sites, was therefore recorded as a length.
- Unexpected-failure handlers recorded the class name only. Nothing recorded where the
  failure happened, and tracebacks are not sent because exception messages can carry request
  content.
- The planning catch-all did not include the conversation hash.

## Technical details

Files modified:

- `application/single_app/functions_appinsights.py`
  - `exception_type` text is retained when it is a plain class name
    (`[A-Za-z_][A-Za-z0-9_]{0,127}`); any other text stays a length.
  - New `exception_log_fields(exc)` returns `error_type` and `error_site`. `error_site` lists
    up to six innermost application frames as `file.py:function:line`, innermost first. It
    never reads the exception message, arguments or local values, and skips frames outside
    `application/single_app`.
  - `error_site` added to the retained diagnostic keys.
- `application/single_app/route_backend_orchestration.py`
  - The planning stream, clarification resume, background planning worker and headless
    execution stream catch-alls log `exception_log_fields(exc)`. The planning stream and
    clarification resume also log the conversation hash and a `stage`.
- `scripts/orchestration_scorecard.py` (new)
  - Reads the existing orchestration events from Application Insights and reports, per
    application version, requests, unplanned requests, planning crashes, correction rounds,
    runs and completion rate, plus the leading rejection rules, run failures and crash sites.
- `functional_tests/test_orchestration_crash_diagnostics.py` (new)
- `functional_tests/cosmos_response_boundaries.json` refreshed for the edited route owner.

No setting, dependency or user-visible message changed.

## Validation

- `functional_tests/test_orchestration_crash_diagnostics.py`: 5 passed. Covers class and
  location without the message, exclusion of non-application frames, the frame limit, the
  allow-list behaviour for both keys, and the planning handler's fields.
- `functional_tests/test_orchestration_failure_telemetry.py`,
  `test_privacy_logging_telemetry_audit.py`, `test_log_event_call_contract.py`,
  `test_unified_logging_entrypoint.py`, `test_appinsights_logging_recursion_guard.py`: passed.
- `test_logging_tag_standardization.py` (1 test) and `test_appinsights_streaming_context.py`
  (8 tests) fail identically on the unmodified commit `316bcf67f`; they are not caused by
  this change.
- The scorecard was run against the live Application Insights resource and reproduced the
  manually queried 7-day figures.

Not validated: the change is not deployed, so no live crash record with `sc_error_site` has
been observed, and the original planning crash is still not identified.

## Before and after

Before: `{"sc_message": "[ORCHESTRATION] Planning failed.", "sc_exception_type_length": "8"}`.

After: the same record also carries `sc_error_type`, `sc_error_site`, `sc_stage` and
`sc_conversation_id_hash`.
