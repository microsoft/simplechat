# Log Event Call Contract Fix

## Header Information

**Issue description:** Conversation fork eligibility conflicts correctly raised
`ConversationForkConflictError`, but the conflict logger passed
`custom_dimensions=` to `log_event()`. Because `log_event()` does not accept
that keyword, logging raised `TypeError` and replaced the intended HTTP 409
response with HTTP 500.

**Root cause:** Conversation fork code used metadata keyword conventions from
other logging APIs (`custom_dimensions=` and `properties=`) instead of the
SimpleChat `log_event()` contract, whose structured metadata argument is
`extra=`.

**Fixed in version:** **0.250.101**

**Associated issue:** Refs #1112

## Technical Details

### Files Modified

- `application/single_app/route_backend_conversations.py`
- `application/single_app/functions_simplechat_operations.py`
- `functional_tests/test_conversation_fork.py`
- `functional_tests/test_log_event_call_contract.py`
- `application/single_app/config.py`

### Code Changes

- Replaced four unsupported `custom_dimensions=` arguments in the conversation
  fork route with canonical `extra=` metadata.
- Replaced five unsupported `properties=` arguments in conversation fork
  cleanup and activity-logging fallback paths with canonical `extra=`
  metadata.
- Added an AST-based application contract test. It derives accepted parameters
  from `functions_appinsights.log_event()` and scans Python callers under
  `application/`, including direct imports, aliased imports, and
  module-qualified calls.
- Added a route-level regression that invokes the production conversation route
  registrar, forces a fork conflict, and verifies both the HTTP 409 response
  and the structured metadata passed to `log_event()`.

### Testing Approach

- Run the application-wide logging call-contract test.
- Run all conversation fork functional tests, including the 409 regression.
- Run the unified logging entry-point and privacy/log-sanitization regression
  suites.
- Compile changed Python files and check the final diff for whitespace errors.

### Impact Analysis

The change does not alter route authorization, fork eligibility rules, response
payloads, log levels, traceback settings, or metadata values. It restores the
intended response behavior and prevents unsupported explicit `log_event()`
keywords from entering production code.

## Validation

### Test Results

The logging-contract and conversation-fork suites pass together, including the
new application-wide scan and route-level conflict regression.

### Before and After

| Scenario | Before | After |
| --- | --- | --- |
| Eligible fork | HTTP 201 | HTTP 201 |
| Invalid fork request | Intended HTTP 400 could be masked by logger `TypeError` | HTTP 400 with structured metadata logged through `extra` |
| Fork eligibility conflict | Intended HTTP 409 became HTTP 500 | HTTP 409 with structured metadata logged through `extra` |
| Unexpected fork failure | Error logger could raise another `TypeError` | HTTP 500 with the original failure logged through `extra` |
| Cleanup logging | `properties=` could fail during recovery | Cleanup diagnostics use supported `extra=` metadata |

### User Experience Improvements

Users now receive the correct conversation-fork conflict response instead of a
misleading server error. Maintainers also get an automated, app-wide guard
against future logger signature mismatches.
