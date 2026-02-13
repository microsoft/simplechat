# Custom Logo Not Displaying Across App Fix

## Issue Description
When an admin uploaded a custom logo via Admin Settings, the logo would display correctly on the admin settings page but **not appear elsewhere in the application** (e.g., chat page, sidebar navigation).

### Symptoms
- Logo visible in Admin Settings preview
- Logo not appearing in sidebar navigation
- Logo not appearing on chat/chats pages
- Logo not appearing on index/landing page

## Root Cause Analysis
The issue was in the `sanitize_settings_for_user()` function in [functions_settings.py](../../application/single_app/functions_settings.py).

This function is designed to strip sensitive data before sending settings to the frontend. It filters out any keys containing terms like:
- `key`
- `secret`
- `password`
- `connection`
- **`base64`**
- `storage_account_url`

The logo settings are stored with keys:
- `custom_logo_base64`
- `custom_logo_dark_base64`
- `custom_favicon_base64`

Because these keys contain `base64`, they were being **completely removed** from the sanitized settings.

### Template Logic Impact
Templates check for custom logos using conditions like:
```jinja2
{% raw %}{% if app_settings.custom_logo_base64 %}
    <img src="{{ url_for('static', filename='images/custom_logo.png') }}" />
{% else %}
    <img src="{{ url_for('static', filename='images/logo-lightmode.png') }}" />
{% endif %}{% endraw %}
```

When `custom_logo_base64` was stripped entirely, this condition always evaluated to `False`, causing the default logo to display instead of the custom uploaded logo.

## Solution
Modified `sanitize_settings_for_user()` to add boolean flags for logo/favicon existence **after** the main sanitization loop. This allows templates to check if logos exist without exposing the actual base64 data.

### Code Change
```python
def sanitize_settings_for_user(full_settings: dict) -> dict:
    # ... existing sanitization logic ...

    # Add boolean flags for logo/favicon existence so templates can check without exposing base64 data
    # These fields are stripped by the base64 filter above, but templates need to know if logos exist
    if 'custom_logo_base64' in full_settings:
        sanitized['custom_logo_base64'] = bool(full_settings.get('custom_logo_base64'))
    if 'custom_logo_dark_base64' in full_settings:
        sanitized['custom_logo_dark_base64'] = bool(full_settings.get('custom_logo_dark_base64'))
    if 'custom_favicon_base64' in full_settings:
        sanitized['custom_favicon_base64'] = bool(full_settings.get('custom_favicon_base64'))

    return sanitized
```

### How It Works
1. The sensitive base64 data is still stripped during the main loop
2. After sanitization, boolean flags are added:
   - `True` if the logo exists (base64 string is non-empty)
   - `False` if no logo is set (base64 string is empty)
3. Templates can still use `{% raw %}{% if app_settings.custom_logo_base64 %}{% endraw %}` and it will correctly evaluate to `True` or `False`
4. The actual base64 data is never exposed to the frontend

## Files Modified
- [functions_settings.py](../../application/single_app/functions_settings.py) - Modified `sanitize_settings_for_user()` function

## Version
**Fixed in version:** 0.237.002

## Testing
A functional test was created: [test_custom_logo_sanitization_fix.py](../../functional_tests/test_custom_logo_sanitization_fix.py)

### Test Cases
1. **Logo flags preserved as True** - When logos exist, boolean flags are `True`
2. **Logo flags preserved as False** - When logos are empty, boolean flags are `False`
3. **No spurious flags added** - If logo keys don't exist in settings, they're not added
4. **Template compatibility** - Boolean flags work correctly in Jinja2-style conditionals

### Running the Test
```bash
cd functional_tests
python test_custom_logo_sanitization_fix.py
```

## Impact
This fix affects all pages that display the application logo:
- Landing/Index page
- Chat page
- Sidebar navigation (when left nav is enabled)
- Any other page using `base.html` that references logo settings

## Security Considerations
- ✅ Actual base64 data is still never exposed to the frontend
- ✅ Only boolean True/False values are sent
- ✅ No sensitive data leakage
- ✅ Maintains the security intent of the original sanitization function
