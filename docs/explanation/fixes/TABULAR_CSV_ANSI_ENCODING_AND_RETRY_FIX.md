# Tabular CSV ANSI Encoding and Retry Fix

## Issue

ANSI-encoded CSV files could upload successfully while producing unreadable metadata and failed `search_rows` calls. Repeated tool failures could also consume a long automatic-invocation sequence before the outer tabular retry logic completed, without clearly reporting the failure in the live analysis stream.

## Root Cause

CSV readers passed raw files directly to pandas, which defaults to UTF-8 and does not reliably decode Windows-1252 content. Tabular analysis had no targeted circuit breaker for equivalent failed calls, so the model could repeat the same invalid request while consuming its automatic-invocation budget.

## Implemented in version: **0.261.030**

## Technical Details

- Added shared CSV decoding that prefers UTF-8, then UTF-8 with BOM, Windows-1252, and Latin-1.
- Applied the decoder to tabular metadata, indexing, citation previews, foreground queries, and durable row replay.
- Restored the broader 20-call automatic-invocation budget so complex analysis is not cut short by a universal cap.
- Detect repeated equivalent failures by function, arguments, and normalized error, then route the next model pass away from the failed call shape.
- Emit an explicit tabular retry lifecycle thought and server-side failure event when repeated failures are detected.

## Validation

The regression test in `functional_tests/test_tabular_csv_ansi_encoding.py` verifies Windows-1252 characters are preserved, the 20-call budget remains available for complex analysis, and repeated-failure routing is present.
