# Disable Group Creation Setting Fix

**Version:** 0.235.010 
**Fixed in:** 0.235.010  
**Issue Type:** Bug Fix

## Problem Description

The "Disable Group Creation" setting was not being saved from either the Admin Settings page (`admin_settings.html`) or the Control Center page (`control_center.html`). Even when the setting was manually changed in Cosmos DB to `false`, users could not create groups because the setting always appeared to be "on" (disabled).

### Issue 1: Form Field Name Mismatch (Fixed in 0.235.004)

The HTML form field in `admin_settings.html` was named `disable_group_creation`, but the backend code in `route_frontend_admin_settings.py` was reading `enable_group_creation`. This mismatch meant:

1. The form submitted `disable_group_creation=on` when the toggle was checked
2. The backend looked for `enable_group_creation` which was never present in the form data
3. The expression `form_data.get('enable_group_creation') == 'on'` always evaluated to `False`
4. This meant `enable_group_creation` was always set to `False`, effectively disabling group creation regardless of the toggle state

### Issue 2: Missing onclick Handler (Fixed in 0.235.005)

The Control Center's "Save Settings" button had no `onclick` handler. The `GroupManager.bindEvents()` function was supposed to attach an event listener, but `GroupManager.init()` was never called, so the binding never occurred.

## Solution

### Fix 1: Backend Form Field Reading (0.235.004)

Modified the backend to correctly read the `disable_group_creation` form field and invert its value to set `enable_group_creation`:

**Before (Incorrect):**
```python
'enable_group_creation': form_data.get('enable_group_creation') == 'on',
```

**After (Fixed):**
```python
# disable_group_creation is inverted: when checked (on), enable_group_creation = False
'enable_group_creation': form_data.get('disable_group_creation') != 'on',
```

### Fix 2: Add onclick Handler (0.235.005)

Added inline `onclick` handler to the Save Settings button:

**Before:**
```html
<button type="button" class="btn btn-primary" id="saveGlobalGroupSettings">
```

**After:**
```html
<button type="button" class="btn btn-primary" id="saveGlobalGroupSettings" onclick="GroupManager.saveGlobalSettings()">
```

## Files Modified

| File | Change |
|------|--------|
| `route_frontend_admin_settings.py` | Fixed form field name and inversion logic (0.235.004) |
| `control_center.html` | Added onclick handler to Save Settings button (0.235.005) |
| `config.py` | Version updated to 0.235.005 |

## Logic Explanation

The toggle is labeled "Disable Group Creation" which means:
- **Checked (on)**: Users should NOT be able to create groups → `enable_group_creation = False`
- **Unchecked (off)**: Users CAN create groups → `enable_group_creation = True`

The fix uses `!= 'on'` to invert the logic:
- When `disable_group_creation` is `'on'`: `'on' != 'on'` → `False` → groups disabled
- When `disable_group_creation` is not present/null: `None != 'on'` → `True` → groups enabled

## Testing

A functional test was created at:
- `functional_tests/test_disable_group_creation_fix.py`

The test validates:
1. Form field name matches what backend expects
2. Control Center toggle exists with correct binding
3. Default setting exists in `functions_settings.py`
4. API endpoint for updating settings exists

## Related Files

- `templates/admin_settings.html` - Contains the Disable Group Creation toggle
- `templates/control_center.html` - Contains the Global Group Settings with same toggle
- `functions_settings.py` - Contains default value for `enable_group_creation` (defaults to `True`)
- `route_backend_agents.py` - Contains the API endpoint used by Control Center

## Verification Steps

1. Navigate to Admin Settings → Workspaces tab
2. Toggle "Disable Group Creation" ON
3. Save settings
4. Verify users cannot see the "Create Group" button
5. Toggle "Disable Group Creation" OFF
6. Save settings
7. Verify users can now see and use the "Create Group" button

Alternatively, via Control Center:
1. Navigate to Control Center → Group Management tab
2. Use the "Disable Group Creation" toggle in Global Group Settings
3. Click "Save Settings"
4. Verify the setting persists after page refresh
