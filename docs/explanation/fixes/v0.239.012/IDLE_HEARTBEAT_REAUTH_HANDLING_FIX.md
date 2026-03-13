# IDLE HEARTBEAT REAUTH HANDLING FIX

## Header Information

- **Fix Title**: Background heartbeat reauth synchronization
- **Issue Description**: Background heartbeat requests that returned non-OK responses (such as `401` after server-side idle expiry) could return without redirecting, leaving the UI active while the backend session was already cleared.
- **Root Cause Analysis**: `refreshServerSession()` only forced logout for non-OK responses when `forceLogoutOnFailure` was `true` (user-initiated path), but the background path used `false` and silently returned.
- **Version Implemented**: **0.239.012**
- **Related Config Update**: `application/single_app/config.py` updated to `VERSION = "0.239.012"`.

## Technical Details

- **Files Modified**:
  - `application/single_app/static/js/idle-logout-warning.js`
  - `functional_tests/test_idle_logout_timeout.py`
  - `application/single_app/config.py`
- **Code Changes Summary**:
  - Added hard-logout handling for heartbeat responses with HTTP `401`/`403` even in background heartbeat mode.
  - Added fallback parsing of non-OK JSON payloads to check `requires_reauth` and trigger logout accordingly.
  - Kept existing behavior where transient non-auth failures still avoid forced logout for background heartbeats.
- **Testing Approach**:
  - Extended `functional_tests/test_idle_logout_timeout.py` JavaScript marker assertions for status-based and payload-based reauth handling.
- **Impact Analysis**:
  - Prevents client/server auth-state divergence after backend session expiration.
  - Reduces false “still signed in” UI state when the server has already invalidated the session.

## Validation

- **Test Results**:
  - Idle-timeout functional test validates the new reauth marker logic in heartbeat handling.
- **Before/After Comparison**:
  - **Before**: Non-user-initiated heartbeats could silently ignore server reauth responses.
  - **After**: Background heartbeats force logout on auth-failure signals (`401`, `403`, or `requires_reauth`).
- **User Experience Improvements**:
  - Consistent logout behavior when session expiration is detected during background activity monitoring.
