# Markdown Retry Return Contract Fix

Fixed in version: **0.261.007**

## Issue

GitHub Advanced Security flagged the Markdown retry helper for mixing explicit returns with an implicit fall-through return. The helper returned the result from Markdown processing on success and raised the original exception when retries were exhausted, but the loop structure still allowed static analysis to see a possible implicit `None` return.

## Root Cause

The retry loop was logically exhaustive because it either returned from `process_md` or raised when the known transient error exceeded the retry limit. CodeQL could not prove that control flow, so the function contract was ambiguous to static analysis.

## Technical Details

Files modified:

- `application/single_app/functions_documents.py`
- `application/single_app/config.py`

The helper now raises an explicit defensive `RuntimeError` after the retry loop. This keeps the runtime behavior unchanged for normal success and retry-exhaustion paths while making the no-fall-through contract visible to static analysis.

## Validation

Validated with Python compilation and the Markdown processing regression test.