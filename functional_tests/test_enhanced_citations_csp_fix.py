#!/usr/bin/env python3
"""
Functional test for enhanced citations CSP fix.
Version: 0.229.061
Implemented in: 0.229.061

This test ensures that the Content Security Policy (CSP) allows enhanced citations
PDFs to be embedded in iframes by verifying frame-ancestors is set to 'self' instead
of 'none', fixing the CSP violation that prevented PDF modal display.
"""

import sys
import os
import requests
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_csp_frame_ancestors_allows_self_framing():
    """Test that CSP frame-ancestors allows self-framing for enhanced citations."""
    print("🔍 Testing CSP frame-ancestors configuration...")
    
    try:
        # Import the config to check the CSP setting
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "config.py"
        )
        
        if not os.path.exists(config_path):
            print(f"❌ Config file not found: {config_path}")
            return False
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
        
        # Check that CSP contains frame-ancestors 'self' instead of 'none'
        if "frame-ancestors 'self'" not in config_content:
            print("❌ CSP does not contain 'frame-ancestors 'self''")
            return False
        print("✅ CSP contains 'frame-ancestors 'self''")
        
        # Ensure it's NOT set to 'none'
        if "frame-ancestors 'none'" in config_content:
            print("❌ CSP still contains 'frame-ancestors 'none''")
            return False
        print("✅ CSP no longer contains 'frame-ancestors 'none''")
        
        # Check that the CSP configuration is in SECURITY_HEADERS
        if "'Content-Security-Policy':" not in config_content:
            print("❌ Content-Security-Policy not found in SECURITY_HEADERS")
            return False
        print("✅ Content-Security-Policy found in SECURITY_HEADERS")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_enhanced_citations_javascript_iframe_usage():
    """Test that enhanced citations JavaScript properly uses iframes."""
    print("🔍 Testing enhanced citations iframe implementation...")
    
    try:
        # Check the enhanced citations JavaScript file
        js_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "static", "js", "chat", "chat-enhanced-citations.js"
        )
        
        if not os.path.exists(js_file_path):
            print(f"❌ Enhanced citations JS file not found: {js_file_path}")
            return False
        
        with open(js_file_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
        
        # Check that it creates PDF iframes
        if 'id="pdfFrame"' not in js_content:
            print("❌ PDF iframe element not found in enhanced citations")
            return False
        print("✅ PDF iframe element found")
        
        # Check that it sets iframe src to the enhanced citations endpoint
        if '/api/enhanced_citations/pdf' not in js_content:
            print("❌ Enhanced citations PDF endpoint not found")
            return False
        print("✅ Enhanced citations PDF endpoint found")
        
        # Check for proper iframe handling
        if 'pdfFrame.src = pdfUrl' not in js_content:
            print("❌ Direct iframe src assignment not found")
            return False
        print("✅ Direct iframe src assignment found")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_app_applies_security_headers():
    """Test that the Flask app applies the security headers with CSP."""
    print("🔍 Testing Flask app security headers application...")
    
    try:
        # Check that app.py imports and uses security headers
        app_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "app.py"
        )
        
        if not os.path.exists(app_file_path):
            print(f"❌ App file not found: {app_file_path}")
            return False
        
        with open(app_file_path, 'r', encoding='utf-8') as f:
            app_content = f.read()
        
        # Check for security headers function
        if 'add_security_headers' not in app_content:
            print("❌ add_security_headers function not found in app.py")
            return False
        print("✅ add_security_headers function found")
        
        # Check that security headers are applied after request
        if '@app.after_request' not in app_content:
            print("❌ @app.after_request decorator not found")
            return False
        print("✅ @app.after_request decorator found")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_update():
    """Test that the version was updated for this fix."""
    print("🔍 Testing version update...")
    
    try:
        # Import the config to check the version
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "config.py"
        )
        
        if not os.path.exists(config_path):
            print(f"❌ Config file not found: {config_path}")
            return False
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
        
        # Check that version is updated to 0.229.061 or higher
        if 'VERSION = "0.229.061"' not in config_content:
            print("❌ Version not updated to 0.229.061")
            return False
        print("✅ Version updated to 0.229.061")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def run_all_tests():
    """Run all CSP fix tests."""
    print("🧪 Enhanced Citations CSP Fix Test Suite")
    print("=" * 50)
    
    tests = [
        test_csp_frame_ancestors_allows_self_framing,
        test_enhanced_citations_javascript_iframe_usage,
        test_app_applies_security_headers,
        test_version_update
    ]
    
    results = []
    for test in tests:
        print(f"\n🔬 Running {test.__name__}...")
        result = test()
        results.append(result)
        if result:
            print("✅ Test passed!")
        else:
            print("❌ Test failed!")
    
    # Summary
    passed = sum(results)
    total = len(results)
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Enhanced citations CSP fix is working correctly.")
        print("\n📝 Fix Summary:")
        print("   • Changed CSP frame-ancestors from 'none' to 'self'")
        print("   • Enhanced citations PDFs can now be embedded in iframes")
        print("   • Maintains security by only allowing same-origin framing")
        print("   • Version updated to 0.229.061")
        return True
    else:
        print(f"⚠️  {total - passed} test(s) failed. Please review the issues above.")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)