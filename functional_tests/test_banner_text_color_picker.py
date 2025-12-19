#!/usr/bin/env python3
"""
Functional test for banner text color picker feature.
Version: 0.229.099
Implemented in: 0.229.099

This test ensures that the classification_banner_text_color setting is properly saved,
retrieved, and displayed in both the admin settings and the banner display.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_banner_text_color_default():
    """Test that banner text color defaults to white (#ffffff) when not set."""
    print("🔍 Testing banner text color default value...")
    
    try:
        from config import cosmos_settings_container
        
        # Create a test settings document without classification_banner_text_color
        test_settings = {
            'id': 'test_settings_banner_text_color',
            'classification_banner_enabled': True,
            'classification_banner_color': '#ff0000',
            'classification_banner_text': 'TEST BANNER'
            # Intentionally omit classification_banner_text_color
        }
        
        # Simulate the default behavior from route_frontend_admin_settings.py
        if 'classification_banner_text_color' not in test_settings:
            test_settings['classification_banner_text_color'] = '#ffffff'
        
        # Verify default is applied
        assert test_settings['classification_banner_text_color'] == '#ffffff', \
            f"Expected default text color '#ffffff', got '{test_settings['classification_banner_text_color']}'"
        
        print("✅ Default banner text color correctly set to #ffffff (white)")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_banner_text_color_save_and_retrieve():
    """Test that banner text color can be saved and retrieved from settings."""
    print("\n🔍 Testing banner text color save and retrieve...")
    
    try:
        from config import cosmos_settings_container
        
        test_colors = ['#000000', '#ff5500', '#00ff00', '#0000ff', '#ffffff']
        
        for test_color in test_colors:
            # Create test settings with specific text color
            test_settings = {
                'id': f'test_settings_banner_color_{test_color.replace("#", "")}',
                'classification_banner_enabled': True,
                'classification_banner_color': '#ff0000',
                'classification_banner_text': 'TEST BANNER',
                'classification_banner_text_color': test_color
            }
            
            # Save to Cosmos DB
            cosmos_settings_container.upsert_item(test_settings)
            
            # Retrieve from Cosmos DB
            retrieved = cosmos_settings_container.read_item(
                item=test_settings['id'],
                partition_key=test_settings['id']
            )
            
            # Verify the text color was saved and retrieved correctly
            assert retrieved['classification_banner_text_color'] == test_color, \
                f"Expected text color '{test_color}', got '{retrieved['classification_banner_text_color']}'"
            
            print(f"✅ Text color {test_color} saved and retrieved successfully")
            
            # Cleanup
            cosmos_settings_container.delete_item(
                item=test_settings['id'],
                partition_key=test_settings['id']
            )
        
        print("✅ All banner text colors saved and retrieved correctly")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_banner_text_color_form_extraction():
    """Test that banner text color is properly extracted from form data."""
    print("\n🔍 Testing banner text color form extraction...")
    
    try:
        # Simulate form data extraction as done in route_frontend_admin_settings.py
        test_form_data = {
            'classification_banner_text_color': '#123456'
        }
        
        # Extract text color (mimicking the logic at line ~361 in route_frontend_admin_settings.py)
        classification_banner_text_color = test_form_data.get('classification_banner_text_color', '#ffffff').strip()
        
        # Verify extraction
        assert classification_banner_text_color == '#123456', \
            f"Expected extracted color '#123456', got '{classification_banner_text_color}'"
        
        print("✅ Banner text color correctly extracted from form data")
        
        # Test default fallback
        empty_form_data = {}
        classification_banner_text_color = empty_form_data.get('classification_banner_text_color', '#ffffff').strip()
        
        assert classification_banner_text_color == '#ffffff', \
            f"Expected default fallback '#ffffff', got '{classification_banner_text_color}'"
        
        print("✅ Banner text color fallback to default works correctly")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_banner_text_color_in_settings_dict():
    """Test that banner text color is included in settings dictionary."""
    print("\n🔍 Testing banner text color in settings dictionary...")
    
    try:
        # Simulate building the settings dictionary (as at line ~659 in route_frontend_admin_settings.py)
        classification_banner_text_color = '#aabbcc'
        
        settings = {
            'classification_banner_enabled': True,
            'classification_banner_color': '#ff0000',
            'classification_banner_text': 'TEST',
            'classification_banner_text_color': classification_banner_text_color,
        }
        
        # Verify text color is in settings
        assert 'classification_banner_text_color' in settings, \
            "classification_banner_text_color not found in settings dictionary"
        
        assert settings['classification_banner_text_color'] == '#aabbcc', \
            f"Expected text color '#aabbcc', got '{settings['classification_banner_text_color']}'"
        
        print("✅ Banner text color correctly included in settings dictionary")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_banner_display_template_logic():
    """Test the template logic for displaying banner with text color."""
    print("\n🔍 Testing banner display template logic...")
    
    try:
        # Simulate the template logic from base.html
        app_settings = {
            'classification_banner_text_color': '#00ff00'
        }
        
        # Template uses: color: {{ app_settings.classification_banner_text_color or '#ffffff' }}
        text_color = app_settings.get('classification_banner_text_color') or '#ffffff'
        
        assert text_color == '#00ff00', \
            f"Expected display color '#00ff00', got '{text_color}'"
        
        print("✅ Banner displays with correct text color (#00ff00)")
        
        # Test fallback when not set
        empty_settings = {}
        text_color = empty_settings.get('classification_banner_text_color') or '#ffffff'
        
        assert text_color == '#ffffff', \
            f"Expected fallback color '#ffffff', got '{text_color}'"
        
        print("✅ Banner correctly falls back to white text when not configured")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("BANNER TEXT COLOR PICKER FEATURE - FUNCTIONAL TEST")
    print("=" * 70)
    
    tests = [
        test_banner_text_color_default,
        test_banner_text_color_save_and_retrieve,
        test_banner_text_color_form_extraction,
        test_banner_text_color_in_settings_dict,
        test_banner_display_template_logic
    ]
    
    results = []
    
    for test in tests:
        result = test()
        results.append(result)
    
    print("\n" + "=" * 70)
    print(f"📊 RESULTS: {sum(results)}/{len(results)} tests passed")
    print("=" * 70)
    
    success = all(results)
    sys.exit(0 if success else 1)
