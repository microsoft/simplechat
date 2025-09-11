#!/usr/bin/env python3
"""
Azure Document Intelligence Parameter Fix Test

This test validates that the Azure Document Intelligence API parameters
are correctly formatted to prevent the "urlSource or base64Source is required" error
when processing PDF files through the document upload functionality.
"""

import sys
import os

# Add the parent directory to the path so we can import from the main app
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def test_azure_di_api_parameter_format():
    """Test that Azure DI API calls use correct parameter format."""
    print("🔍 Testing Azure Document Intelligence API parameter format...")
    
    try:
        # Import the function to test
        from functions_content import extract_content_with_azure_di
        from config import CLIENTS, AZURE_ENVIRONMENT
        
        # Check if Document Intelligence client is available
        if 'document_intelligence_client' not in CLIENTS:
            print("⚠️  Document Intelligence client not configured - skipping test")
            return True
        
        # Read the source code to verify parameter format
        import inspect
        source_code = inspect.getsource(extract_content_with_azure_di)
        
        # Check for correct parameter patterns
        if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
            # For US Government/Custom, should use base64Source
            if '{"base64Source": base64_source}' in source_code:
                print("✅ US Gov/Custom environment: Correct base64Source parameter format found")
            else:
                print("❌ US Gov/Custom environment: Missing correct base64Source parameter format")
                return False
        else:
            # For public cloud, should use model_id and document parameters
            if 'model_id="prebuilt-read"' in source_code and 'document=f' in source_code:
                print("✅ Public cloud environment: Correct model_id and document parameter format found")
            else:
                print("❌ Public cloud environment: Missing correct model_id and document parameter format")
                return False
        
        # Verify that both branches handle parameters correctly
        has_base64_branch = '{"base64Source": base64_source}' in source_code
        has_document_branch = 'model_id="prebuilt-read"' in source_code and 'document=f' in source_code
        
        if has_base64_branch and has_document_branch:
            print("✅ Both environment parameter formats are correctly implemented")
        else:
            print("❌ One or both environment parameter formats are missing")
            return False
        
        print("✅ Azure Document Intelligence API parameter format test passed!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_api_consistency_with_settings_route():
    """Test that API calls are consistent between functions_content.py and route_backend_settings.py."""
    print("🔍 Testing API consistency between modules...")
    
    try:
        import inspect
        from functions_content import extract_content_with_azure_di
        
        # Read source code
        content_source = inspect.getsource(extract_content_with_azure_di)
        
        # Read settings route source
        with open(os.path.join(os.path.dirname(__file__), '..', 'route_backend_settings.py'), 'r') as f:
            settings_source = f.read()
        
        # Check that both use the same parameter patterns
        content_has_base64 = '{"base64Source": base64_source}' in content_source
        settings_has_base64 = '{"base64Source": base64_source}' in settings_source
        
        content_has_document = 'model_id="prebuilt-read"' in content_source and 'document=f' in content_source
        settings_has_document = 'model_id="prebuilt-read"' in settings_source and 'document=f' in settings_source
        
        if content_has_base64 and settings_has_base64:
            print("✅ Both modules use consistent base64Source parameter format")
        else:
            print("❌ Inconsistent base64Source parameter format between modules")
            return False
        
        if content_has_document and settings_has_document:
            print("✅ Both modules use consistent document parameter format")
        else:
            print("❌ Inconsistent document parameter format between modules")
            return False
        
        print("✅ API consistency test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Consistency test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_azure_di_api_parameter_format,
        test_api_consistency_with_settings_route
    ]
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All Azure Document Intelligence parameter tests passed!")
    else:
        print("💥 Some tests failed. Please check the parameter formats.")
    
    sys.exit(0 if success else 1)
