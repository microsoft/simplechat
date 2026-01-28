# Control Center Date Labels Fix (v0.237.001)

## Header Information
- **Fix Title:** Control Center Date Labels Fix
- **Issue Description:** Control Center charts displayed dates one day behind due to UTC parsing of date keys.
- **Root Cause Analysis:** The frontend parsed YYYY-MM-DD strings with `new Date(...)`, which treats the value as UTC and shifts the day in local timezones.
- **Fixed/Implemented in version:** **0.235.074**
- **Config Version Updated:** `config.py` VERSION set to **0.235.074**

## Technical Details
- **Files Modified:**
  - application/single_app/static/js/control-center.js
  - application/single_app/config.py
- **Code Changes Summary:**
  - Added a local date parsing helper for YYYY-MM-DD keys.
  - Updated chart label and tooltip rendering to use local date parsing.
  - Bumped application version in config.py.
- **Testing Approach:**
  - Added a functional test to validate the date parsing helper is present in the chart logic.

## Validation
- **Test Results:** functional_tests/test_control_center_date_labels_fix.py
- **Before/After Comparison:**
  - Before: Date labels in charts appeared one day behind in local timezones.
  - After: Date labels match the correct local date (e.g., Jan 21 for today).
- **User Experience Improvements:**
  - Accurate daily labels across all activity charts.
