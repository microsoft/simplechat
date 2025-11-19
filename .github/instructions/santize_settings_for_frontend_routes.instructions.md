---
applyTo: '**'
---

# Security: Sanitize Settings for Frontend Routes

## Critical Security Requirement

**NEVER send raw settings or configuration data directly to the frontend without sanitization.**

## Rule: Always Sanitize Settings Before Sending to Browser

When building or working with Python frontend routes (Flask routes that render templates or return JSON to the browser), **ALL settings data MUST be sanitized** before being sent to prevent exposure of:
- API keys
- Connection strings
- Secrets and passwords
- Internal configuration details
- Database credentials
- Any other sensitive information

## Required Pattern

### ✅ CORRECT - Sanitize Before Sending
```python
from functions_settings import get_settings, sanitize_settings_for_user

@app.route('/some-page')
def some_page():
    # Get raw settings
    settings = get_settings()
    
    # Sanitize before sending to frontend
    public_settings = sanitize_settings_for_user(settings)
    
    # Use sanitized settings in template
    return render_template('some_page.html', 
                         app_settings=public_settings,
                         settings=public_settings)
```

### ❌ INCORRECT - Never Send Raw Settings
```python
# DANGEROUS - Exposes secrets to browser!
@app.route('/some-page')
def some_page():
    settings = get_settings()
    return render_template('some_page.html', 
                         app_settings=settings)  # ❌ NEVER DO THIS
```

## When This Rule Applies

Apply this rule for:
- **Any route** that renders an HTML template (`render_template()`)
- **Any API endpoint** that returns JSON data containing settings (`jsonify()`)
- **Any frontend route** that passes configuration data to JavaScript
- **Dashboard/admin pages** that display configuration information
- **Settings/configuration pages** where users view system settings

## Implementation Checklist

When creating or modifying frontend routes:
1. ✅ Import `sanitize_settings_for_user` from `functions_settings`
2. ✅ Call `get_settings()` to retrieve raw settings
3. ✅ Call `sanitize_settings_for_user(settings)` to create safe version
4. ✅ Pass only the sanitized version to `render_template()` or `jsonify()`
5. ✅ Verify no raw settings objects bypass sanitization

## Examples from Codebase

### Control Center Route
```python
from functions_settings import get_settings, sanitize_settings_for_user

@app.route('/admin/control-center', methods=['GET'])
@login_required
@admin_required
def control_center():
    # Get settings for configuration data
    settings = get_settings()
    public_settings = sanitize_settings_for_user(settings)
    
    # Get statistics
    stats = get_control_center_statistics()
    
    # Send only sanitized settings to frontend
    return render_template('control_center.html', 
                         app_settings=public_settings, 
                         settings=public_settings,
                         statistics=stats)
```

### API Endpoint Pattern
```python
@app.route('/api/get-config', methods=['GET'])
@login_required
def get_config():
    settings = get_settings()
    public_settings = sanitize_settings_for_user(settings)
    
    return jsonify({
        'success': True,
        'config': public_settings
    })
```

## What Gets Sanitized

The `sanitize_settings_for_user()` function removes or masks:
- Azure OpenAI API keys
- Cosmos DB connection strings
- Azure Search admin keys
- Document Intelligence keys
- Authentication secrets
- Internal endpoint URLs
- Database credentials
- Any field containing 'key', 'secret', 'password', 'connection', etc.

## Security Impact

**Failure to sanitize settings can result in:**
- 🚨 Exposure of API keys in browser DevTools/Network tab
- 🚨 Secrets visible in HTML source code
- 🚨 Credentials leaked in JavaScript variables
- 🚨 Potential unauthorized access to Azure resources
- 🚨 Security vulnerabilities and data breaches

## Code Review Checklist

When reviewing code, verify:
- [ ] No `get_settings()` result is sent directly to frontend
- [ ] `sanitize_settings_for_user()` is called before rendering
- [ ] Template variables receiving settings use sanitized version
- [ ] API responses containing config use sanitized data
- [ ] No raw config objects in `render_template()` or `jsonify()` calls

## Related Functions

- `get_settings()` - Returns raw settings (DO NOT send to frontend)
- `sanitize_settings_for_user(settings)` - Returns safe settings (OK to send to frontend)
- Location: `functions_settings.py`