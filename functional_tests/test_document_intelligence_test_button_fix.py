#!/usr/bin/env python3
"""
Functional test for Document Intelligence test connection button fix.
Version: 0.229.018
Implemented in: 0.229.018

This test ensures that the Document Intelligence test connection button works correctly
and uses the proper API parameter format for all Azure environments.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
# Add the parent directory to the path so we can import from the main app
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_document_intelligence_test_button_api_parameters():
    """Test that the test connection function uses correct API parameters."""
    print("🔍 Testing Document Intelligence test connection button API parameters...")
    
    try:
        # Read the route_backend_settings.py file directly
        app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app')
        route_file = os.path.join(app_path, 'route_backend_settings.py')
        
        with open(route_file, 'r') as f:
            source_code = f.read()
        
        # Find the _test_azure_doc_intelligence_connection function
        func_start = source_code.find('def _test_azure_doc_intelligence_connection(payload):')
        if func_start == -1:
            print("❌ Could not find test function")
            return False
            
        # Get the function content (find next function or end of file)
        func_end = source_code.find('\ndef ', func_start + 1)
        if func_end == -1:
            func_content = source_code[func_start:]
        else:
            func_content = source_code[func_start:func_end]
        
        # Check for correct parameter patterns
        # Should use body with base64Source for public cloud
        if 'body=analyze_request' in func_content and '"base64Source": base64_source' in func_content:
            print("✅ Correct body parameter format found")
        else:
            print("❌ Incorrect parameter format - missing body=analyze_request or base64Source")
            return False
                
        # Ensure old document parameter is not used
        if 'document=f' in func_content:
            print("❌ Found old 'document=f' parameter format - this should be removed")
            return False
        else:
            print("✅ Old 'document=f' parameter format correctly removed")
            
        # Check that both environments use proper format
        if func_content.count('"base64Source": base64_source') >= 2:
            print("✅ Both government and public cloud use base64Source format")
        else:
            print("❌ Not all environments use proper base64Source format")
            return False
            
        print("✅ Test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_consistency_with_working_implementation():
    """Test that the test function is consistent with the working implementation."""
    print("🔍 Testing consistency between test function and working implementation...")
    
    try:
        # Read both files directly
        app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app')
        route_file = os.path.join(app_path, 'route_backend_settings.py')
        content_file = os.path.join(app_path, 'functions_content.py')
        
        with open(route_file, 'r') as f:
            test_source = f.read()
            
        with open(content_file, 'r') as f:
            content_source = f.read()
        
        # Both should use the same parameter patterns for public cloud
        if 'body=analyze_request' in test_source and 'body=analyze_request' in content_source:
            print("✅ Both functions use consistent 'body=analyze_request' parameter")
        else:
            print("❌ Inconsistent parameter usage between functions")
            return False
            
        # Both should use base64Source approach
        if '"base64Source"' in test_source and '"base64Source"' in content_source:
            print("✅ Both functions use base64Source approach")
        else:
            print("❌ Inconsistent base64Source usage")
            return False
            
        print("✅ Test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_document_intelligence_test_button_api_parameters,
        test_consistency_with_working_implementation
    ]
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All Document Intelligence test button fix tests passed!")
    else:
        print("💥 Some tests failed. Please check the API parameter formats.")
    
    sys.exit(0 if success else 1)
