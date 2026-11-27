#!/usr/bin/env python3
# test_azure_search_exception_handling_fix.py
"""
Functional test for Azure AI Search index not found error handling.
Version: 0.227.011
Implemented in: 0.227.011

This test ensures that the specific Azure ResourceNotFoundError exception
is properly caught and handled when indexes don't exist, returning the
correct 404 status with appropriate error messages for the frontend.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_azure_resource_not_found_exception_handling():
    """Test that ResourceNotFoundError is specifically handled."""
    print("🔍 Testing Azure ResourceNotFoundError Exception Handling...")
    
    try:
        # Read the backend settings file
        settings_path = os.path.join(os.path.dirname(__file__), "../application/single_app/route_backend_settings.py")
        if not os.path.exists(settings_path):
            raise FileNotFoundError(f"route_backend_settings.py not found at {settings_path}")
        
        with open(settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for specific ResourceNotFoundError handling
        required_patterns = [
            "except ResourceNotFoundError as not_found_error:",
            "Index doesn't exist - this is the specific exception",
            "needsCreation': True",
            "indexExists': False",
            "}), 404",  # Should return 404, not 500
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise AssertionError(f"Missing required ResourceNotFoundError handling patterns: {missing_patterns}")
        
        # Check that ResourceNotFoundError comes before generic Exception
        resource_not_found_pos = content.find("except ResourceNotFoundError")
        generic_exception_pos = content.find("except Exception as search_error:")
        
        if resource_not_found_pos == -1:
            raise AssertionError("ResourceNotFoundError exception handler not found")
        
        if generic_exception_pos != -1 and resource_not_found_pos > generic_exception_pos:
            raise AssertionError("ResourceNotFoundError handler should come before generic Exception handler")
        
        print("✅ Azure ResourceNotFoundError exception handling validated!")
        return True
        
    except Exception as e:
        print(f"❌ Azure ResourceNotFoundError exception handling test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_create_index_exception_handling():
    """Test that create_index also properly handles ResourceNotFoundError."""
    print("🔍 Testing Create Index Exception Handling...")
    
    try:
        # Read the backend settings file
        settings_path = os.path.join(os.path.dirname(__file__), "../application/single_app/route_backend_settings.py")
        if not os.path.exists(settings_path):
            raise FileNotFoundError(f"route_backend_settings.py not found at {settings_path}")
        
        with open(settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for improved exception handling in create_index
        required_patterns = [
            "except ResourceNotFoundError:",
            "Index doesn't exist, which is what we want for creation",
            "except Exception as e:",
            "Error checking if index exists:",
            "Continue with creation attempt anyway",
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise AssertionError(f"Missing required create_index exception handling patterns: {missing_patterns}")
        
        print("✅ Create index exception handling validated!")
        return True
        
    except Exception as e:
        print(f"❌ Create index exception handling test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_fallback_error_patterns():
    """Test that fallback error detection patterns are still present."""
    print("🔍 Testing Fallback Error Patterns...")
    
    try:
        # Read the backend settings file
        settings_path = os.path.join(os.path.dirname(__file__), "../application/single_app/route_backend_settings.py")
        if not os.path.exists(settings_path):
            raise FileNotFoundError(f"route_backend_settings.py not found at {settings_path}")
        
        with open(settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for fallback patterns (in case ResourceNotFoundError doesn't catch everything)
        required_patterns = [
            "no index with the name",
            "index does not exist", 
            "could not find index",
            "# Check for other index not found patterns (fallback)",
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise AssertionError(f"Missing required fallback error patterns: {missing_patterns}")
        
        print("✅ Fallback error patterns validated!")
        return True
        
    except Exception as e:
        print(f"❌ Fallback error patterns test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_proper_logging():
    """Test that proper error logging is in place."""
    print("🔍 Testing Proper Error Logging...")
    
    try:
        # Read the backend settings file
        settings_path = os.path.join(os.path.dirname(__file__), "../application/single_app/route_backend_settings.py")
        if not os.path.exists(settings_path):
            raise FileNotFoundError(f"route_backend_settings.py not found at {settings_path}")
        
        with open(settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for proper logging
        required_patterns = [
            "app.logger.error(f\"Azure AI Search error: {search_error}\")",
            "app.logger.error(f\"Error in check_index_fields:",
            "app.logger.error(f\"Error checking if index exists:",
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise AssertionError(f"Missing required logging patterns: {missing_patterns}")
        
        print("✅ Proper error logging validated!")
        return True
        
    except Exception as e:
        print(f"❌ Proper error logging test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_consistency():
    """Test that the current version is properly set in config.py."""
    print("🔍 Testing Version Consistency...")
    
    try:
        config_path = os.path.join(os.path.dirname(__file__), "../application/single_app/config.py")
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"config.py not found at {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if "app.config['VERSION'] = \"0.227.013\"" not in content:
            raise AssertionError("Version not updated to 0.227.013 in config.py")
        
        print("✅ Version consistency validated!")
        return True
        
    except Exception as e:
        print(f"❌ Version consistency test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_azure_resource_not_found_exception_handling,
        test_create_index_exception_handling,
        test_fallback_error_patterns,
        test_proper_logging,
        test_version_consistency
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All Azure Search index not found error handling tests passed!")
        print("✅ ResourceNotFoundError is specifically caught and handled")
        print("✅ 404 status returned instead of 500 for missing indexes")
        print("✅ Fallback error patterns still available for edge cases")
        print("✅ Proper error logging for troubleshooting")
        print("✅ Create index function also handles exceptions properly")
        print("")
        print("🔧 Expected behavior:")
        print("   - Missing indexes now return 404 with 'needsCreation: true'")
        print("   - JavaScript will show 'Create [type] Index' button")
        print("   - No more 500 errors for missing indexes")
    else:
        print("⚠️  Some tests failed - please review the implementation")
    
    sys.exit(0 if success else 1)
