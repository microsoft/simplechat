#!/usr/bin/env python3
"""
Functional test for External Health Check duplicate sections bug fix.
Version: 0.229.015
Implemented in: 0.229.015

This test ensures that there is only one External Health Check section in the admin settings template
and prevents regression of duplicate UI elements.
"""

import sys
import os
import re

def test_external_health_check_duplication():
    """Test that there is only one External Health Check section in admin settings."""
    print("🔍 Testing External Health Check duplication fix...")
    
    try:
        # Read the admin settings template
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            "..", "application", "single_app", "templates", "admin_settings.html"
        )
        
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Count occurrences of "External Health Check" headers
        header_pattern = r'<h5>External Health Check</h5>'
        headers = re.findall(header_pattern, content)
        header_count = len(headers)
        
        print(f"   Found {header_count} 'External Health Check' headers")
        
        # Count occurrences of the enable_external_healthcheck input field
        input_pattern = r'id="enable_external_healthcheck"'
        inputs = re.findall(input_pattern, content)
        input_count = len(inputs)
        
        print(f"   Found {input_count} 'enable_external_healthcheck' input fields")
        
        # Validate results
        if header_count != 1:
            raise AssertionError(f"Expected 1 'External Health Check' header, found {header_count}")
        
        if input_count != 1:
            raise AssertionError(f"Expected 1 'enable_external_healthcheck' input field, found {input_count}")
        
        # Check for nested div structure that could indicate duplication
        nested_pattern = r'<div class="card mb-3 p-3">\s*<h5>External Health Check</h5>.*?<div class="card mb-3 p-3">\s*<h5>External Health Check</h5>'
        nested_match = re.search(nested_pattern, content, re.DOTALL)
        
        if nested_match:
            raise AssertionError("Found nested External Health Check sections indicating duplication")
        
        print("✅ External Health Check duplication fix verified!")
        print("   - Only one External Health Check header found")
        print("   - Only one enable_external_healthcheck input field found")
        print("   - No nested duplicate sections detected")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ui_structure_integrity():
    """Test that the overall UI structure is intact after the fix."""
    print("\n🔍 Testing UI structure integrity...")
    
    try:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            "..", "application", "single_app", "templates", "admin_settings.html"
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for proper card structure
        card_open_count = len(re.findall(r'<div class="card[^"]*">', content))
        card_close_count = len(re.findall(r'</div>', content))
        
        print(f"   Card opening tags: {card_open_count}")
        print(f"   Total closing div tags: {card_close_count}")
        
        # Check that the external health check has proper form structure
        health_check_section = re.search(
            r'<h5>External Health Check</h5>.*?</div>',
            content,
            re.DOTALL
        )
        
        if not health_check_section:
            raise AssertionError("Could not find External Health Check section")
        
        section_content = health_check_section.group()
        
        # Verify required elements are present
        required_elements = [
            'id="enable_external_healthcheck"',
            'name="enable_external_healthcheck"',
            'type="checkbox"',
            'Enable External Health Check Endpoint'
        ]
        
        for element in required_elements:
            if element not in section_content:
                raise AssertionError(f"Missing required element: {element}")
        
        print("✅ UI structure integrity verified!")
        print("   - External Health Check section has proper form structure")
        print("   - All required form elements are present")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_external_health_check_duplication,
        test_ui_structure_integrity
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All tests passed! External Health Check duplication fix is working correctly.")
    else:
        print("💥 Some tests failed. Please review the output above.")
    
    sys.exit(0 if success else 1)
