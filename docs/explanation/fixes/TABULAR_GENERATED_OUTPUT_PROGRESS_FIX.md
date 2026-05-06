# Tabular Generated Output Progress Fix

Fixed in version: **0.241.135**

## Issue Description

Tabular requests that asked for exhaustive JSON or CSV output could show a completed tabular progress card even though the request was still busy building structured export batches or uploading the generated artifact. From the browser and backend logs, the request could look hung for several minutes with no visible errors.

## Root Cause Analysis

- The tabular tool activity card only represented `TabularProcessingPlugin` tool invocations.
- After those tool calls completed, the request could still enter the generated-output pipeline in `maybe_create_tabular_generated_output(...)` and `_generate_tabular_structured_output_entries(...)`.
- That structured export phase could batch rows, retry model transformations, and upload a generated chat artifact without emitting thoughts or consistent backend logs.
- Because the UI never saw activity from that phase, the tabular card could sit at 100 percent while the request was still legitimately working.

## Version Implemented

- **0.241.135**

## Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/chat/chat-thoughts.js`
- `application/single_app/config.py`
- `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`
- `ui_tests/test_chat_tabular_thought_progress.py`

## Code Changes Summary

- Added tabular post-processing activity payloads and callback helpers so generated-output work can publish thoughts just like tabular tool invocations.
- Wired the generated-output helper through both persisted-thought and streaming SSE paths.
- Added lightweight debug logging for structured export batch preparation, batch execution, upload start, and completion.
- Updated the tabular activity card to label mixed tool plus export work as `steps` instead of only `tool calls`, and changed the completion copy to `Tabular export ready` when post-processing activity is present.
- Added backend and UI regression coverage for the previously silent post-processing phase.

## Testing Approach

- Ran `python -m py_compile application/single_app/route_backend_chats.py`.
- Ran `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`.
- Ran `node --check application/single_app/static/js/chat/chat-thoughts.js`.
- Ran `pytest ui_tests/test_chat_tabular_thought_progress.py -q`.

## Impact Analysis

- Requests that ask for exhaustive structured tabular output now show visible activity after the tabular tool pass completes.
- Backend logs now provide checkpoints for the generated-output phase instead of going silent.
- Users can distinguish `tabular tool phase complete` from `request fully done`, which reduces false hang reports and makes real hangs easier to diagnose.

## Validation

- Before: the tabular card could reach 100 percent and stay there while structured export batching or artifact upload continued silently.
- After: the same request continues emitting tabular post-processing activity, the progress card stays active during export work, and completion text reflects export readiness instead of only workbook evidence.