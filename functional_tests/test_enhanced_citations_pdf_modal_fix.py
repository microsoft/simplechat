#!/usr/bin/env python3
"""
Functional test for enhanced citations PDF modal fix.
Version: 0.228.006
Implemented in: 0.228.006

This test ensures that enhanced citations use the new server-side rendering
endpoint instead of the old SAS URL approach for PDF documents.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_pdf_modal_server_side_rendering():
    """Test that PDF modal uses server-side rendering endpoint."""
    print("🔍 Testing PDF Modal Server-Side Rendering...")
    
    try:
        # Read the enhanced citations JavaScript file
        js_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "static", "js", "chat", "chat-enhanced-citations.js"
        )
        
        if not os.path.exists(js_file_path):
            print(f"❌ Enhanced citations JS file not found: {js_file_path}")
            return False
        
        with open(js_file_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
        
        # Check that it's using the new server-side rendering endpoint
        if '/api/enhanced_citations/pdf' not in js_content:
            print("❌ New server-side rendering endpoint not found in enhanced citations")
            return False
        print("✅ New server-side rendering endpoint found")
        
        # Check that it's not delegating to the old view_pdf endpoint
        if 'module.showPdfModal(docId, pageNumber, citationId)' in js_content:
            print("❌ Still delegating to old showPdfModal implementation")
            return False
        print("✅ No longer delegating to old implementation")
        
        # Check for createPdfModal function
        if 'function createPdfModal()' not in js_content:
            print("❌ createPdfModal function not found")
            return False
        print("✅ createPdfModal function found")
        
        # Check for iframe implementation
        if 'id="pdfFrame"' not in js_content:
            print("❌ PDF iframe not found in modal structure")
            return False
        print("✅ PDF iframe found in modal structure")
        
        # Check for proper error handling with fallback
        if 'fetchCitedText(citationId)' not in js_content:
            print("❌ Error fallback to text citation not found")
            return False
        print("✅ Error fallback to text citation found")
        
        print("✅ PDF modal server-side rendering test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_update():
    """Test that version was properly updated."""
    print("🔍 Testing Version Update...")
    
    try:
        # Read config.py to check version
        config_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "config.py"
        )
        
        if not os.path.exists(config_file_path):
            print(f"❌ Config file not found: {config_file_path}")
            return False
        
        with open(config_file_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
        
        # Check for the updated version
        if 'VERSION = "0.228.006"' not in config_content:
            print("❌ Version not updated to 0.228.006")
            return False
        
        print("✅ Version properly updated to 0.228.006")
        return True
        
    except Exception as e:
        print(f"❌ Version test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_route_enhanced_citations_unchanged():
    """Test that route_enhanced_citations.py wasn't broken by this change."""
    print("🔍 Testing Route Enhanced Citations Integrity...")
    
    try:
        # Read the route_enhanced_citations.py file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "route_enhanced_citations.py"
        )
        
        if not os.path.exists(route_file_path):
            print(f"❌ Route file not found: {route_file_path}")
            return False
        
        with open(route_file_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Check that server-side rendering functions are still there
        if 'def serve_enhanced_citation_content(' not in route_content:
            print("❌ serve_enhanced_citation_content function missing")
            return False
        print("✅ serve_enhanced_citation_content function found")
        
        # Check that PDF endpoint is still there
        if '@app.route("/api/enhanced_citations/pdf", methods=["GET"])' not in route_content:
            print("❌ PDF endpoint missing")
            return False
        print("✅ PDF endpoint found")
        
        # Check that no SAS URL generation remains
        if 'generate_blob_sas' in route_content:
            print("❌ SAS URL generation still present")
            return False
        print("✅ No SAS URL generation found")
        
        print("✅ Route enhanced citations integrity test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Route integrity test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Enhanced Citations PDF Modal Fix Test")
    print("=" * 55)
    
    tests = [
        test_pdf_modal_server_side_rendering,
        test_version_update,
        test_route_enhanced_citations_unchanged
    ]
    
    results = []
    for test in tests:
        print()
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Test Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All tests passed!")
    else:
        print("❌ Some tests failed!")
    
    sys.exit(0 if success else 1)
