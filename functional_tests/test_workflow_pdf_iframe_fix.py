#!/usr/bin/env python3
"""
Functional test for workflow PDF iframe embedding fix.
Version: 0.229.066
Implemented in: 0.229.066

This test ensures that the workflow PDF iframe embedding works
by using a dedicated endpoint with proper CSP headers.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_workflow_dedicated_pdf_endpoint():
    """Test that workflow has dedicated PDF endpoint for iframe embedding."""
    print("🔍 Testing workflow dedicated PDF endpoint...")
    
    try:
        citations_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_enhanced_citations.py'
        )
        
        with open(citations_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for dedicated workflow PDF route
        required_patterns = [
            '@app.route("/api/workflow/pdf"',  # Dedicated route
            'def get_workflow_pdf():',  # Function name
            'serve_workflow_pdf_content',  # Helper function
            "frame-ancestors 'self';",  # CSP header
            "'X-Frame-Options': 'SAMEORIGIN'",  # X-Frame-Options
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise Exception(f"Missing workflow PDF patterns: {missing_patterns}")
        
        print("   - Dedicated /api/workflow/pdf route: ✅")
        print("   - serve_workflow_pdf_content function: ✅")
        print("   - Iframe-friendly CSP headers: ✅")
        print("   - X-Frame-Options header: ✅")
        print("✅ Workflow dedicated PDF endpoint is implemented!")
        return True
        
    except Exception as e:
        print(f"❌ Workflow PDF endpoint test failed: {e}")
        return False

def test_workflow_template_updated():
    """Test that workflow template uses the new endpoint."""
    print("🔍 Testing workflow template uses new PDF endpoint...")
    
    try:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'workflow_summary_view.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that template uses the new endpoint
        required_patterns = [
            '/api/workflow/pdf',  # New endpoint
            'doc_id=${encodeURIComponent(fileId)}',  # Proper encoding
            'dedicated workflow URL',  # Comment indicating new approach
        ]
        
        # Check that old endpoint is not used for iframe loading
        deprecated_patterns = [
            'pdfViewer.src = `/api/enhanced_citations/pdf',  # Old iframe endpoint
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        found_deprecated = []
        for pattern in deprecated_patterns:
            if pattern in content:
                found_deprecated.append(pattern)
        
        if missing_patterns:
            raise Exception(f"Missing new endpoint patterns: {missing_patterns}")
        
        if found_deprecated:
            raise Exception(f"Still using deprecated patterns: {found_deprecated}")
        
        print("   - Uses /api/workflow/pdf endpoint: ✅")
        print("   - Proper URL encoding: ✅")
        print("   - No deprecated endpoints: ✅")
        print("✅ Workflow template updated correctly!")
        return True
        
    except Exception as e:
        print(f"❌ Workflow template test failed: {e}")
        return False

def test_debug_logging_added():
    """Test that debug logging was added for troubleshooting."""
    print("🔍 Testing debug logging for troubleshooting...")
    
    try:
        # Check enhanced citations route
        citations_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_enhanced_citations.py'
        )
        
        with open(citations_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        debug_patterns = [
            'debug_debug_print(f"[DEBUG]:: Enhanced citations PDF request',
            'debug_debug_print(f"[DEBUG]:: serve_enhanced_citation_pdf_content',
            'debug_debug_print(f"[DEBUG]:: Setting CSP headers for iframe embedding',
            'debug_debug_print(f"[DEBUG]:: serve_workflow_pdf_content',
        ]
        
        missing_debug = []
        for pattern in debug_patterns:
            if pattern not in content:
                missing_debug.append(pattern)
        
        if missing_debug:
            raise Exception(f"Missing debug logging: {missing_debug}")
        
        # Check workflow template
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'workflow_summary_view.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        if 'console.log(\'DEBUG: Loading PDF with' not in template_content:
            raise Exception("Missing JavaScript debug logging")
        
        print("   - Backend debug logging: ✅")
        print("   - Frontend debug logging: ✅")
        print("   - CSP header debug info: ✅")
        print("✅ Debug logging is comprehensive!")
        return True
        
    except Exception as e:
        print(f"❌ Debug logging test failed: {e}")
        return False

def test_version_update():
    """Test that version was updated."""
    print("🔍 Testing version update...")
    
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'config.py'
        )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'VERSION = "0.229.066"' in content:
            print("   - Version updated to 0.229.066")
            print("✅ Version update confirmed!")
            return True
        else:
            raise Exception("Version not updated to 0.229.066")
        
    except Exception as e:
        print(f"❌ Version update test failed: {e}")
        return False

if __name__ == "__main__":
    tests = [
        test_workflow_dedicated_pdf_endpoint,
        test_workflow_template_updated,
        test_debug_logging_added,
        test_version_update
    ]
    
    results = []
    print("🧪 Running Workflow PDF Iframe Fix Tests...\n")
    
    for test in tests:
        print(f"Running {test.__name__}...")
        results.append(test())
        print()
    
    success = all(results)
    print(f"📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All workflow PDF iframe fixes validated successfully!")
        print("🎉 The workflow should now display PDFs without CSP violations!")
        print("")
        print("Changes applied:")
        print("• Created dedicated /api/workflow/pdf endpoint")
        print("• Added iframe-friendly CSP headers")
        print("• Updated workflow template to use new endpoint") 
        print("• Added comprehensive debug logging")
    else:
        print("❌ Some tests failed - PDF iframe embedding may still have issues")
    
    sys.exit(0 if success else 1)