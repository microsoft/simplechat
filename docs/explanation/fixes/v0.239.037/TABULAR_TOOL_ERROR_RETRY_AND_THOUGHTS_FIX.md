# Tabular Tool Error Retry and Thoughts Fix

## Issue Description
A failed analytical tabular tool call could still be treated as successful analysis when the plugin returned a JSON error payload rather than raising an exception. This let the chat stop after a single failed tabular tool attempt and produce a weak follow-up answer instead of retrying or falling back. It also left the visible thought feed too thin compared with the internal debug trail.

**Version implemented:** 0.239.037

Fixed/Implemented in version: **0.239.037**

Related `config.py` update: `VERSION` was bumped to `0.239.037`.

## Root Cause Analysis
1. **Analytical tool presence was treated as success even when the result payload contained an error**
   - `run_tabular_sk_analysis()` counted analytical function invocations without inspecting whether the returned JSON contained an `error` field.
   - A single failed call such as `group_by_datetime_component` missing `aggregate_column` could therefore stop the retry flow early.
2. **Retry attempts did not receive the previous tool error context**
   - When the first tool call failed, the next SK attempt had no direct feedback about what argument was wrong.
3. **Thoughts surfaced the tool call but not the recovery path**
   - The UI could show a failed tool invocation, but not whether the system retried, recovered via fallback, or simply stopped.

## Technical Details
### Files Modified
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_tool_error_retry_and_thoughts.py`

### Code Changes Summary
- Added helpers to inspect tabular invocation result payloads and extract embedded JSON error messages.
- Updated analytical invocation classification so tool calls returning JSON errors are treated as failed, not successful.
- Updated citation filtering so failed analytical tabular calls do not appear as successful tool citations.
- Fed previous tool error messages back into subsequent SK retry prompts.
- Added tabular status thoughts for:
  - recovery after retrying tool errors,
  - recovery via internal fallback after tool errors,
  - tool-error state before fallback when computation still fails.
- Updated tabular tool-call thoughts so JSON error payloads render as failed tool thoughts in the UI.

### Testing Approach
- Added `functional_tests/test_tabular_tool_error_retry_and_thoughts.py` to verify:
  - JSON error payloads are classified as failed analytical calls,
  - failed analytical calls do not become citations,
  - failed tool thoughts show error details,
  - recovery thoughts are emitted for internal fallback,
  - retry prompts include previous tool error feedback.

## Impact Analysis
- A single failed analytical tabular tool call no longer ends the analysis prematurely.
- Retry attempts have better context to correct bad tool arguments.
- The thought feed now better explains the difference between a failed tool call and a recovered final analysis.

## Validation
### Before
- The system could stop after one failed analytical tool call.
- A JSON error payload could still be treated like successful analysis.
- Thoughts did not clearly show recovery after tool errors.

### After
- Failed analytical tool calls trigger retry or fallback instead of being accepted as success.
- Previous tool errors are fed back into the retry prompt.
- The UI can show failed tool calls and the recovery/fallback status more clearly.

## Related Validation Assets
- Functional test: `functional_tests/test_tabular_tool_error_retry_and_thoughts.py`
- Related fix: `docs/explanation/fixes/v0.239.036/TABULAR_GROUPED_PEAK_SUMMARY_FIX.md`
- Related fix: `docs/explanation/fixes/v0.239.035/TABULAR_TOOL_CALL_THOUGHTS_FIX.md`
