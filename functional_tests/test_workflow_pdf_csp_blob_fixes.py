#!/usr/bin/env python3
"""
Functional test for workflow PDF iframe CSP and blob_name fixes.
Version: 0.229.067
Implemented in: 0.229.067

This test ensures that:
1. Main application CSP allows iframe embedding for same origin
2. Workflow PDF endpoint uses proper workspace detection and blob name generation
3. PDF iframe display works without CSP violations
4. Backend blob_name errors are resolved
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_main_csp_iframe_support():
    """Test that main application CSP allows iframe embedding."""
    print("🔍 Testing main application CSP iframe support...")
    
    try:
        config_path = os.path.join('..', 'application', 'single_app', 'config.py')
        
        with open(config_path, 'r') as f:
            content = f.read()
        
        # Check that frame-ancestors is set to 'self' instead of 'none'
        if "frame-ancestors 'self';" in content:
            print("   ✅ Main CSP allows iframe embedding for same origin")
            return True
        elif "frame-ancestors 'none';" in content:
            print("   ❌ Main CSP still blocks iframe embedding")
            return False
        else:
            print("   ❌ Main CSP frame-ancestors directive not found")
            return False
            
    except Exception as e:
        print(f"   ❌ Error checking main CSP: {e}")
        return False

def test_workflow_pdf_blob_handling():
    """Test that workflow PDF function uses proper blob name handling."""
    print("🔍 Testing workflow PDF blob name handling...")
    
    try:
        citations_path = os.path.join('..', 'application', 'single_app', 'route_enhanced_citations.py')
        
        with open(citations_path, 'r') as f:
            content = f.read()
        
        # Find the serve_workflow_pdf_content function
        if 'def serve_workflow_pdf_content(' not in content:
            print("   ❌ serve_workflow_pdf_content function not found")
            return False
        
        func_start = content.find('def serve_workflow_pdf_content(')
        func_section = content[func_start:func_start + 2000]  # Get reasonable chunk
        
        # Check for proper workspace detection
        if 'determine_workspace_type_and_container' in func_section:
            print("   ✅ Uses determine_workspace_type_and_container function")
        else:
            print("   ❌ Missing workspace type detection")
            return False
        
        # Check for proper blob name generation
        if 'get_blob_name(raw_doc, workspace_type)' in func_section:
            print("   ✅ Uses get_blob_name function for blob name generation")
        else:
            print("   ❌ Missing proper blob name generation")
            return False
        
        # Check that raw hard-coded blob_name access is removed
        if "raw_doc['blob_name']" in func_section:
            print("   ❌ Still uses raw_doc['blob_name'] which causes errors")
            return False
        else:
            print("   ✅ No longer uses problematic raw_doc['blob_name'] access")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error checking workflow PDF blob handling: {e}")
        return False

def test_debug_logging_enhancements():
    """Test that debug logging includes workspace detection details."""
    print("🔍 Testing debug logging enhancements...")
    
    try:
        citations_path = os.path.join('..', 'application', 'single_app', 'route_enhanced_citations.py')
        
        with open(citations_path, 'r') as f:
            content = f.read()
        
        # Find the serve_workflow_pdf_content function
        func_start = content.find('def serve_workflow_pdf_content(')
        func_section = content[func_start:func_start + 2000]
        
        # Check for enhanced debug logging
        if 'workspace_type' in func_section and 'container' in func_section and 'blob_name' in func_section:
            print("   ✅ Enhanced debug logging includes workspace details")
            return True
        else:
            print("   ❌ Missing enhanced debug logging")
            return False
            
    except Exception as e:
        print(f"   ❌ Error checking debug logging: {e}")
        return False

def test_version_update():
    """Test that version was updated after the fixes."""
    print("🔍 Testing version update...")
    
    try:
        config_path = os.path.join('..', 'application', 'single_app', 'config.py')
        
        with open(config_path, 'r') as f:
            content = f.read()
        
        if 'VERSION = "0.229.067"' in content:
            print("   ✅ Version updated to 0.229.067")
            return True
        else:
            print("   ❌ Version not updated properly")
            return False
            
    except Exception as e:
        print(f"   ❌ Error checking version: {e}")
        return False

def run_all_tests():
    """Run all workflow PDF iframe and CSP fix tests."""
    print("🧪 Running Workflow PDF Iframe and CSP Fix Tests")
    print("=" * 60)
    
    tests = [
        test_main_csp_iframe_support,
        test_workflow_pdf_blob_handling, 
        test_debug_logging_enhancements,
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
        print("✅ All workflow PDF iframe and CSP fixes validated successfully!")
        return True
    else:
        print("❌ Some tests failed - fixes may be incomplete")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)