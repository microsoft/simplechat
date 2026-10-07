# V2 Control Center Validation Error Safety

Fixed in version: **0.261.283**, tracked in `application/single_app/config.py`.

Public workspace handlers fixed in version: **0.261.285**.

## Issue and root cause

Users and Groups API validation handlers returned exception text to the browser.
Even when a custom validation exception normally contains a reviewed message,
returning exception text creates an unnecessary client-visible exception boundary.
CodeQL identified nine such handlers in the V2 Control Center routes.

The same boundary affected all five public workspace handlers: list, detail,
bulk status, individual status, and CSV export. These now return fixed messages
while preserving HTTP 400 and existing input bounds.

## Technical details

`application/single_app/route_backend_control_center.py` uses stable validation
responses instead of serializing caught exceptions. Existing authorization,
validation status codes, status-change audit behavior, and approval gating are
preserved. Related review cleanup clarifies the intentional legacy token fallback
and removes unused Flask imports from the Groups functional test.

## Validation

Focused Users and Groups regression tests cover validation failures and safe
storage-error responses. The prior Control Center tests and route-policy tests
check that the merged integration retains the same authorization boundaries.
The built local V2 bundle is exercised by Groups and Users browser workflows.

Before the fix, client responses could contain exception text. After the fix,
validation failures use stable messages and do not expose exception details.

`functional_tests/test_control_center_safe_exception_responses.py` injects
sensitive exception text into all fourteen Users, Groups, and Public Workspaces
validation handlers and checks their exact safe response and status.

See [V2 Control Center](../features/V2_CONTROL_CENTER.md) for the API contracts.
