# IDLE HEARTBEAT INTERVAL FIX

## Header Information

- **Fix Title**: Idle heartbeat timing alignment for short timeout configurations
- **Issue Description**: The client initialized `lastServerHeartbeatAt` with `Date.now()` and used a fixed 60-second heartbeat minimum interval. With `timeoutMinutes = 1`, active users could miss a heartbeat before server-side timeout and be logged out unexpectedly.
- **Root Cause Analysis**: Heartbeat throttling was static and did not account for short configured timeout windows, delaying the first heartbeat too long for aggressive timeout settings.
- **Version Implemented**: **0.239.012**
- **Related Config Update**: `application/single_app/config.py` updated to `VERSION = "0.239.012"`.

## Technical Details

- **Files Modified**:
  - `application/single_app/static/js/idle-logout-warning.js`
  - `functional_tests/test_idle_logout_timeout.py`
  - `application/single_app/config.py`
- **Code Changes Summary**:
  - Set `lastServerHeartbeatAt` to `0` so first user activity can trigger an immediate heartbeat.
  - Replaced fixed heartbeat interval with dynamic interval: `Math.min(60000, timeoutMs / 2)`.
  - Added functional test markers to assert both initialization and dynamic heartbeat interval logic.
- **Testing Approach**:
  - Extended `functional_tests/test_idle_logout_timeout.py` JavaScript wiring assertions.
- **Impact Analysis**:
  - Prevents active users from timing out in short (1-minute) idle-timeout configurations due to delayed client heartbeat.
  - Preserves lower heartbeat frequency for normal/larger timeout configurations.

## Validation

- **Test Results**:
  - Functional idle-timeout test includes marker checks for dynamic heartbeat timing logic.
- **Before/After Comparison**:
  - **Before**: First heartbeat could be delayed up to 60 seconds regardless of timeout size.
  - **After**: First heartbeat is eligible on first activity, and recurring heartbeat interval scales with timeout.
- **User Experience Improvements**:
  - More reliable stay-signed-in behavior during active interaction when short idle timeout settings are configured.
