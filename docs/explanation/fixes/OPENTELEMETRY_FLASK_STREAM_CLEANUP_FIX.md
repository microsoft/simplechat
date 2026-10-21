# OpenTelemetry Flask Streaming Cleanup Fix

Fixed/Implemented in version: **0.261.365**

Current application version: **0.261.368**, after integrating base version
**0.261.367** without reverting the telemetry or incoming fixes.

## Issue

Instrumented streaming responses could finish successfully and then log
`Failed to detach context`, with a `RuntimeError` saying a context token
`has already been used once`. This polluted exception telemetry even when the
response body and HTTP status were correct.

This is separate from an answer-quality or UI-test acceptance failure. A
successful HTTP response does not prove the answer is correct, and a telemetry
cleanup error does not by itself prove that the response failed.

## Root cause

The previous `azure-monitor-opentelemetry==1.6.13` requirement resolved to Flask
instrumentation 0.57b0. With the application's Flask 3.1.3, a response wrapped in
`stream_with_context` can tear down the original request context and later tear
it down again when the stream closes.

The older adapter left its activation and context token in the request
environment after cleanup. A subsequent teardown attempted to reset that
single-use token again. A plain Flask app reproduces this without Azure
exporters, background workers, documents, or model calls.

Upstream corrected the lifecycle in
[open-telemetry/opentelemetry-python-contrib#3938](https://github.com/open-telemetry/opentelemetry-python-contrib/pull/3938).
The fix first appears in the 1.40.0/0.61b0 release. The related upstream report is
[open-telemetry/opentelemetry-python-contrib#3937](https://github.com/open-telemetry/opentelemetry-python-contrib/issues/3937).

## Changes

- `application/single_app/requirements.txt` updates the Azure Monitor distribution
  to **1.8.9**, which requires Flask instrumentation **0.64b0** and OpenTelemetry
  SDK **1.43.x**. The distribution keeps the instrumentation packages compatible;
  individual OpenTelemetry packages are not independently forced to other versions.
- `functional_tests/test_appinsights_streaming_context.py` exercises real,
  instrumented Flask request dispatch in isolated processes with in-memory spans
  and network access blocked.
- `docs/troubleshooting/troubleshooting.md` distinguishes this post-response
  token-reuse signature from instrumentation startup failures.
- `application/single_app/config.py` records application version **0.261.368**.
  The telemetry fix was originally implemented in **0.261.365**.

Flask, Werkzeug, and Flask-Executor pins remain unchanged. The fix does not
disable instrumentation, suppress errors, monkeypatch OpenTelemetry internals,
or remove request context from streaming responses. Background execution and
reattachment code are unchanged.

## Validation

The regression matrix covers plain responses, raw generators, completed
context-managed streams, early close, request exceptions, generator exceptions,
copied-context threads, Flask-Executor workers, repeated requests, concurrent
requests, and a new response after a previous consumer disconnects.

Each probe checks response behavior, request/session access where applicable,
finished server spans without duplicates, restored caller context, and absence
of cleanup errors. Request exceptions must still produce an error response and
an error span. Explicit checks in the child process remain active under
optimized Python; the tests do not rely only on a quiet logger.

| Dependency combination | Runtime matrix result |
|---|---|
| Flask 3.1.3, Azure Monitor 1.6.13, Flask instrumentation 0.57b0 | 8 streaming cases fail with cleanup errors; 3 controls pass |
| Flask 3.1.3, Azure Monitor 1.8.9, Flask instrumentation 0.64b0 | All 11 cases pass |
| Same upgraded combination under `python -O` | All 11 cases pass |

Run the focused regression tests in an isolated Python 3.12 environment restored
from the repository requirements:

```powershell
python -m pip install -r .\application\single_app\requirements.txt -r .\requirements-dev.txt
python -m pip check
python -m pytest -q .\functional_tests\test_appinsights_streaming_context.py
python -O -m pytest -q .\functional_tests\test_appinsights_streaming_context.py
```

The full application and development requirements were restored with the adopted
pin; `python -m pip check` reported no broken requirements. The resolved SDK was
1.43.0, Flask instrumentation 0.64b0, and Azure Monitor exporter 1.0.0b56.

The focused existing logging and real-agent streaming suite had **34 passing
checks and one pre-existing failure**:
`test_unified_logging_entrypoint.py::test_debug_print_forwards_tagged_appinsights_trace`.
That test expects raw message text, while the unchanged application emits the
static `[SIMPLE_CHAT_DEBUG_TRACE]` message. It also fails with Azure Monitor
1.6.13, and its Azure SDK entry point is stubbed. It was not changed or marked
as passing. Explicitly deselecting that assertion gives **34 passed,
1 deselected** for this command:

```powershell
python -m pytest -q .\functional_tests\test_appinsights_streaming_context.py .\functional_tests\test_m365_agent_streaming.py .\functional_tests\test_flask_exception_console_logging.py .\functional_tests\test_unified_logging_entrypoint.py .\functional_tests\test_appinsights_logging_recursion_guard.py -k "not test_debug_print_forwards_tagged_appinsights_trace"
```

## Operational impact and limitations

The update corrects the adapter's request-context cleanup; it does not redefine
request-span duration as the duration of the entire streamed response. Use
stream lifecycle events to measure completion, disconnects, and reattachment.

The offline reattachment case verifies independent HTTP response lifecycles,
not replay of persisted conversation events. These checks use synthetic routes
and do not certify live model behavior or a production deployment.

Validation was performed on Windows with Python 3.12. Production Linux
verification and deployment remain separate operations. After an approved
deployment, check both normal/error request telemetry and streaming completion;
absence of the old exception alone is not proof that instrumentation still works.
