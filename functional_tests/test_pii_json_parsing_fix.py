#!/usr/bin/env python3
"""
Test PII Analysis JSON parsing fix.
Version: 0.229.073

This test verifies that the JSON parsing error for PII patterns is resolved.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import requests
import time

def test_admin_settings_pii_parsing():
    """Test that admin settings page loads without JavaScript JSON parsing errors."""
    print("🔍 Testing PII Analysis JSON parsing fix...")
    
    try:
        # Test the admin settings page
        response = requests.get('http://localhost:8000/admin_settings', timeout=10)
        
        if response.status_code == 200:
            content = response.text
            print("    ✅ Admin settings page loaded successfully")
            
            # Check for the new JSON pattern format
            if 'const piiPatternsData = [' in content:
                print("    ✅ Found new JSON pattern format")
            else:
                print("    ❌ New JSON pattern format not found")
                return False
            
            # Check that the old problematic format is gone
            if "'{{ settings.pii_analysis_patterns|tojson" in content:
                print("    ❌ Old problematic JSON format still present")
                return False
            else:
                print("    ✅ Old problematic JSON format removed")
            
            # Check for PII pattern data structure
            if '"pattern_type"' in content and '"regex"' in content:
                print("    ✅ PII pattern data structure found")
            else:
                print("    ❌ PII pattern data structure not found")
                return False
            
            # Check for escaped regex patterns
            if '\\\\b(?!' in content:  # Should have double-escaped backslashes
                print("    ✅ Regex patterns properly escaped")
            else:
                print("    ❌ Regex patterns may not be properly escaped")
            
            print("    ✅ Admin settings page should load without JSON parsing errors")
            return True
            
        else:
            print(f"    ❌ Failed to load admin settings page: {response.status_code}")
            if response.status_code == 404:
                print("    💡 Make sure the application is running on localhost:8000")
            return False
            
    except requests.exceptions.ConnectionError:
        print("    ❌ Cannot connect to localhost:8000")
        print("    💡 Please start the application with: python app.py")
        return False
    except Exception as e:
        print(f"    ❌ Error testing admin settings: {e}")
        return False

def test_json_pattern_structure():
    """Test the JSON pattern structure directly."""
    print("\n🔍 Testing JSON pattern structure...")
    
    try:
        # Test direct pattern access
        sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))
        from functions_settings import get_settings
        import json
        
        settings = get_settings()
        patterns = settings.get('pii_analysis_patterns', [])
        
        # Test JSON serialization and parsing
        json_str = json.dumps(patterns)
        parsed_patterns = json.loads(json_str)
        
        print(f"    ✅ JSON serialization successful ({len(json_str)} chars)")
        print(f"    ✅ JSON parsing successful ({len(parsed_patterns)} patterns)")
        
        # Check pattern structure
        required_fields = ['pattern_type', 'description', 'regex']
        for i, pattern in enumerate(parsed_patterns):
            missing_fields = [field for field in required_fields if field not in pattern]
            if missing_fields:
                print(f"    ❌ Pattern {i+1} missing fields: {missing_fields}")
                return False
        
        print(f"    ✅ All {len(parsed_patterns)} patterns have required fields")
        return True
        
    except Exception as e:
        print(f"    ❌ Error testing JSON structure: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run PII Analysis JSON parsing fix tests."""
    print("🧪 Testing PII Analysis JSON Parsing Fix")
    print("=" * 60)
    
    tests = [
        ("JSON Pattern Structure", test_json_pattern_structure),
        ("Admin Settings Page Loading", test_admin_settings_pii_parsing)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n🔍 Running {test_name}...")
        try:
            result = test_func()
            results.append(result)
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"📊 {test_name}: {status}")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            results.append(False)
    
    # Final summary
    passed = sum(results)
    total = len(results)
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 JSON parsing error fixed! PII Analysis should work correctly.")
        print("\n💡 Next steps:")
        print("   1. Refresh the admin settings page")
        print("   2. Check browser console for any remaining errors")
        print("   3. Test PII pattern management features")
    else:
        print("⚠️ Some issues remain. Please check the output above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)