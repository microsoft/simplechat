#!/usr/bin/env python3
"""
Functional test for custom logo sanitization fix.
Version: 0.237.002
Implemented in: 0.237.002

This test ensures that custom logo boolean flags are preserved in sanitized settings
so templates can detect if custom logos exist without exposing the actual base64 data.

Issue: When a logo was uploaded via admin settings, it was visible on the admin page
but not on other pages (like the chat page) because the `sanitize_settings_for_user`
function was stripping `custom_logo_base64`, `custom_logo_dark_base64`, and 
`custom_favicon_base64` keys entirely, which templates use to conditionally display logos.

Fix: Modified `sanitize_settings_for_user` to add boolean flags for logo/favicon
existence after sanitization, allowing templates to check `app_settings.custom_logo_base64`
(which will be True/False) without exposing the actual base64 data.
"""

import sys
import os

# Add the application directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def test_sanitize_settings_preserves_logo_flags():
    """
    Test that sanitize_settings_for_user preserves boolean flags for logo existence.
    """
    print("🔍 Testing sanitize_settings_for_user preserves logo flags...")
    
    try:
        from functions_settings import sanitize_settings_for_user
        
        # Test case 1: Settings with custom logos present
        settings_with_logos = {
            'app_title': 'Test App',
            'show_logo': True,
            'custom_logo_base64': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
            'custom_logo_dark_base64': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
            'custom_favicon_base64': 'AAABAAEAEBAAAAEAIABoBAAAFgAAACgAAAAQAAAAIAAAAAEAIAAAAAAAAAQAAA==',
            'logo_version': 5,
            'some_api_key': 'secret-key-123',
            'azure_openai_key': 'another-secret-key',
        }
        
        sanitized = sanitize_settings_for_user(settings_with_logos)
        
        # Verify non-sensitive fields are preserved
        assert sanitized.get('app_title') == 'Test App', "app_title should be preserved"
        assert sanitized.get('show_logo') == True, "show_logo should be preserved"
        assert sanitized.get('logo_version') == 5, "logo_version should be preserved"
        
        # Verify sensitive keys are removed (api keys, secrets)
        assert 'some_api_key' not in sanitized, "API keys should be removed"
        assert 'azure_openai_key' not in sanitized, "Azure OpenAI key should be removed"
        
        # Verify logo flags are boolean True (not the actual base64 data)
        assert sanitized.get('custom_logo_base64') == True, "custom_logo_base64 should be True (boolean flag)"
        assert sanitized.get('custom_logo_dark_base64') == True, "custom_logo_dark_base64 should be True (boolean flag)"
        assert sanitized.get('custom_favicon_base64') == True, "custom_favicon_base64 should be True (boolean flag)"
        
        # Verify the actual base64 data is NOT exposed
        assert isinstance(sanitized.get('custom_logo_base64'), bool), "custom_logo_base64 should be a boolean, not a string"
        
        print("✅ Test 1 passed: Logo flags are preserved as boolean True when logos exist")
        
        # Test case 2: Settings without custom logos
        settings_without_logos = {
            'app_title': 'Test App',
            'show_logo': True,
            'custom_logo_base64': '',
            'custom_logo_dark_base64': '',
            'custom_favicon_base64': '',
        }
        
        sanitized2 = sanitize_settings_for_user(settings_without_logos)
        
        # Verify logo flags are boolean False when logos are empty
        assert sanitized2.get('custom_logo_base64') == False, "custom_logo_base64 should be False when empty"
        assert sanitized2.get('custom_logo_dark_base64') == False, "custom_logo_dark_base64 should be False when empty"
        assert sanitized2.get('custom_favicon_base64') == False, "custom_favicon_base64 should be False when empty"
        
        print("✅ Test 2 passed: Logo flags are False when logos are empty/not set")
        
        # Test case 3: Settings without logo keys at all
        settings_no_logo_keys = {
            'app_title': 'Test App',
            'show_logo': False,
        }
        
        sanitized3 = sanitize_settings_for_user(settings_no_logo_keys)
        
        # Verify logo keys are not added if they didn't exist
        assert 'custom_logo_base64' not in sanitized3, "custom_logo_base64 should not be added if not in original settings"
        
        print("✅ Test 3 passed: Logo flags are not added if keys not in original settings")
        
        print("\n✅ All tests passed!")
        return True
        
    except AssertionError as e:
        print(f"❌ Assertion failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_template_compatibility():
    """
    Test that the boolean flags work correctly in Jinja2-style conditionals.
    """
    print("\n🔍 Testing template compatibility with boolean flags...")
    
    try:
        from functions_settings import sanitize_settings_for_user
        
        settings = {
            'custom_logo_base64': 'some-base64-data',
            'custom_logo_dark_base64': '',
        }
        
        sanitized = sanitize_settings_for_user(settings)
        
        # Simulate Jinja2 conditional: {% if app_settings.custom_logo_base64 %}
        if sanitized.get('custom_logo_base64'):
            light_logo_condition = "show custom light logo"
        else:
            light_logo_condition = "show default light logo"
        
        assert light_logo_condition == "show custom light logo", "Light logo should use custom"
        
        # Simulate Jinja2 conditional: {% if app_settings.custom_logo_dark_base64 %}
        if sanitized.get('custom_logo_dark_base64'):
            dark_logo_condition = "show custom dark logo"
        else:
            dark_logo_condition = "show default dark logo"
        
        assert dark_logo_condition == "show default dark logo", "Dark logo should use default (empty base64)"
        
        print("✅ Template compatibility test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Template compatibility test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    results = []
    
    print("=" * 60)
    print("Custom Logo Sanitization Fix - Functional Tests")
    print("=" * 60)
    
    results.append(test_sanitize_settings_preserves_logo_flags())
    results.append(test_template_compatibility())
    
    print("\n" + "=" * 60)
    success = all(results)
    print(f"📊 Results: {sum(results)}/{len(results)} tests passed")
    print("=" * 60)
    
    sys.exit(0 if success else 1)
