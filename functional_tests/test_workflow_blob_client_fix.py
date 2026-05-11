#!/usr/bin/env python3
"""
Quick test for blob storage client fix in workflow PDF serving.
Version: 0.229.068
Implemented in: 0.229.068

This test ensures that serve_workflow_pdf_content uses the correct blob storage client.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_blob_storage_client_fix():
    """Test that workflow PDF function uses correct blob storage client."""
    print("🔍 Testing blob storage client fix...")
    
    try:
        citations_path = os.path.join('..', 'application', 'single_app', 'route_enhanced_citations.py')
        
        with open(citations_path, 'r') as f:
            content = f.read()
        
        # Find the serve_workflow_pdf_content function
        func_start = content.find('def serve_workflow_pdf_content(')
        func_section = content[func_start:func_start + 3000]  # Get larger chunk
        
        # Check for correct client access
        if 'CLIENTS.get("storage_account_office_docs_client")' in func_section:
            print("   ✅ Uses correct blob storage client (storage_account_office_docs_client)")
        else:
            print("   ❌ Missing correct blob storage client access")
            return False
        
        # Check that problematic client access is removed
        if "CLIENTS['blob_storage']" in func_section:
            print("   ❌ Still uses problematic CLIENTS['blob_storage'] access")
            return False
        else:
            print("   ✅ No longer uses problematic CLIENTS['blob_storage'] access")
        
        # Check for client availability check
        if 'if not blob_service_client:' in func_section:
            print("   ✅ Has blob service client availability check")
        else:
            print("   ❌ Missing blob service client availability check")
            return False
        
        # Check for enhanced debugging
        if 'Attempting to download blob' in func_section and 'downloading content' in func_section:
            print("   ✅ Has enhanced debugging for blob download process")
        else:
            print("   ❌ Missing enhanced debugging")
            return False
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error checking blob storage client fix: {e}")
        return False

def test_version_update():
    """Test that version was updated after the fix."""
    print("🔍 Testing version update...")
    
    try:
        config_path = os.path.join('..', 'application', 'single_app', 'config.py')
        
        with open(config_path, 'r') as f:
            content = f.read()
        
        if 'VERSION = "0.229.068"' in content:
            print("   ✅ Version updated to 0.229.068")
            return True
        else:
            print("   ❌ Version not updated properly")
            return False
            
    except Exception as e:
        print(f"   ❌ Error checking version: {e}")
        return False

def run_blob_client_tests():
    """Run blob storage client fix tests."""
    print("🧪 Running Blob Storage Client Fix Tests")
    print("=" * 50)
    
    tests = [
        test_blob_storage_client_fix,
        test_version_update
    ]
    
    results = []
    for test in tests:
        print(f"\n🔬 {test.__name__.replace('test_', '').replace('_', ' ').title()}:")
        results.append(test())
    
    success_count = sum(results)
    total_count = len(results)
    
    print(f"\n📊 Test Results: {success_count}/{total_count} tests passed")
    
    if success_count == total_count:
        print("✅ Blob storage client fix validated successfully!")
        return True
    else:
        print("❌ Some tests failed - fix may be incomplete")
        return False

if __name__ == "__main__":
    success = run_blob_client_tests()
    sys.exit(0 if success else 1)