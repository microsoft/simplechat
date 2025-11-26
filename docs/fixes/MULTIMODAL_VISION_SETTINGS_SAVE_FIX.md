# Multi-Modal Vision Settings Not Saving Fix

**Version**: 0.229.090  
**Date**: November 21, 2025  
**Issue**: Multi-modal vision toggle and model selection reverted when saving admin settings

## Problem

When users enabled multi-modal vision analysis and selected a vision model in the admin settings, clicking "Save Settings" would cause the values to revert to their previous state. The settings appeared to save momentarily but would reset on page reload or when navigating away.

**User Report**: "i tested the multi-modal model in app settings but when i click save it reverts so its not saving"

## Root Cause

The backend form processing code in `route_frontend_admin_settings.py` was not extracting and saving the new multi-modal vision fields from the form data. When the settings were saved to Cosmos DB, these fields were omitted:

- `enable_multimodal_vision` (checkbox)
- `multimodal_vision_model` (dropdown selection)

The HTML form had the correct `name` attributes:
```html
<input ... name="enable_multimodal_vision" ...>
<select ... name="multimodal_vision_model" ...>
```

But the backend was not processing them:
```python
new_settings = {
    # ... other settings ...
    'metadata_extraction_model': form_data.get('metadata_extraction_model', '').strip(),
    # ❌ Missing: enable_multimodal_vision
    # ❌ Missing: multimodal_vision_model
    # --- Banner fields ---
}
```

## Solution

Added the multi-modal vision fields to the form data processing in `route_frontend_admin_settings.py`:

```python
'metadata_extraction_model': form_data.get('metadata_extraction_model', '').strip(),

# Multi-modal vision settings
'enable_multimodal_vision': form_data.get('enable_multimodal_vision') == 'on',
'multimodal_vision_model': form_data.get('multimodal_vision_model', '').strip(),

# --- Banner fields ---
```

### Implementation Details

1. **Checkbox Processing**: Used `== 'on'` pattern to convert HTML checkbox value to boolean
   - When checked: form sends `'on'` → evaluates to `True`
   - When unchecked: form sends nothing → evaluates to `False`

2. **Dropdown Processing**: Used `.strip()` to remove whitespace from model selection
   - Empty selection: returns `''` (empty string)
   - Valid selection: returns deployment name (e.g., `'gpt-4o'`)

3. **Field Order**: Placed immediately after `metadata_extraction_model` for logical grouping
   - Both are extraction/analysis features
   - Both use similar model selection pattern

## Testing

### Validation Steps

1. **Enable Toggle**:
   - Go to Admin Settings → Search and Extract → Multi-Modal Vision Analysis
   - Toggle "Enable Multi-Modal Vision Analysis" ON
   - Click "Save Settings"
   - Reload page
   - ✅ Toggle should remain ON

2. **Model Selection**:
   - Enable toggle
   - Select a vision model from dropdown (e.g., "gpt-4o")
   - Click "Save Settings"
   - Reload page
   - ✅ Selected model should still be shown in dropdown

3. **Disable Toggle**:
   - Toggle OFF
   - Click "Save Settings"
   - Reload page
   - ✅ Toggle should remain OFF

4. **Database Verification**:
   ```python
   # Check Cosmos DB settings document
   settings = cosmos_settings_container.read_item(
       item='settings',
       partition_key='settings'
   )
   print(settings.get('enable_multimodal_vision'))  # Should be True/False
   print(settings.get('multimodal_vision_model'))   # Should be deployment name or ''
   ```

## Files Modified

1. **route_frontend_admin_settings.py** - Added form field processing for multi-modal vision settings
2. **config.py** - Updated version from 0.229.089 → 0.229.090
3. **MULTIMODAL_VISION_SETTINGS_SAVE_FIX.md** - This fix documentation

## Impact

### Before Fix
- ❌ Settings appeared to save but reverted
- ❌ Database not updated with new values
- ❌ Feature unusable after page reload
- ❌ User confusion and frustration

### After Fix
- ✅ Settings persist across page reloads
- ✅ Database correctly stores toggle and model selection
- ✅ Feature fully functional
- ✅ User can configure and use multi-modal vision

## Related Issues

This pattern of missing form field processing could affect future feature additions. When adding new settings:

1. **HTML**: Add `name` attribute to form elements
2. **Backend**: Add form field extraction to `route_frontend_admin_settings.py`
3. **Database Schema**: Ensure default values in `functions_settings.py`
4. **Testing**: Always test save/reload cycle

## Prevention

### Checklist for New Settings

When adding new admin settings:

- [ ] Add HTML form element with `name` attribute
- [ ] Add form field processing in backend route
- [ ] Add default value in `functions_settings.py`
- [ ] Test save functionality
- [ ] Test page reload persistence
- [ ] Verify database values

### Code Review Points

- Verify all HTML `name` attributes have corresponding backend processing
- Check that checkbox fields use `== 'on'` pattern
- Ensure text fields use `.strip()` for whitespace handling
- Confirm boolean conversions are explicit

## Version History

- **0.229.088**: Initial multi-modal vision implementation
- **0.229.089**: Expanded vision model detection
- **0.229.090**: Fixed settings save/persistence issue

## References

- Multi-Modal Vision Analysis Feature (v0.229.088)
- Vision Model Detection Expansion (v0.229.089)
- Admin Settings Form Processing Pattern
