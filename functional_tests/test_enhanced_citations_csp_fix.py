# test_enhanced_citations_csp_fix.py
"""
Functional test for enhanced citations blob CSP and chat toast placement fixes.
Version: 0.241.010
Implemented in: 0.241.010

This test ensures that the Content Security Policy (CSP) allows blob-backed
enhanced citation PDFs to be embedded in iframes and that chat toasts render in
the dedicated anchored container below the tutorial launcher.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_csp_frame_ancestors_allows_self_framing():
    """Test that CSP allows blob-backed PDF frames for enhanced citations."""
    print("🔍 Testing CSP frame configuration...")
    
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
        
        # Check that CSP contains frame-ancestors 'self'
        if "frame-ancestors 'self'" not in config_content:
            print("❌ CSP does not contain 'frame-ancestors 'self''")
            return False
        print("✅ CSP contains 'frame-ancestors 'self''")

        # Check that blob-backed frames are explicitly allowed
        if "frame-src 'self' blob:'" in config_content:
            print("❌ CSP frame-src blob directive has malformed quoting")
            return False
        if "frame-src 'self' blob:" not in config_content:
            print("❌ CSP does not allow blob-backed frames")
            return False
        print("✅ CSP allows blob-backed frames")
        
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
        
        # Check for the fetch-to-blob PDF loading workflow
        if 'const response = await fetch(pdfUrl' not in js_content:
            print("❌ PDF fetch preflight not found")
            return False
        print("✅ PDF fetch preflight found")

        if 'pdfFrame.src = `${pdfObjectUrl}#page=${encodeURIComponent(viewerPage)}`' not in js_content:
            print("❌ Blob-backed iframe assignment not found")
            return False
        print("✅ Blob-backed iframe assignment found")

        return True

    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_chat_toast_container_anchors_below_tutorial_button():
    """Test that chats use an anchored toast container below the tutorial launcher."""
    print("🔍 Testing chat toast container positioning hooks...")

    try:
        chats_template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "templates", "chats.html"
        )
        toast_helper_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "application", "single_app", "static", "js", "chat", "chat-toast.js"
        )

        with open(chats_template_path, 'r', encoding='utf-8') as f:
            chats_content = f.read()

        with open(toast_helper_path, 'r', encoding='utf-8') as f:
            toast_helper_content = f.read()

        if 'id="chat-toast-container"' not in chats_content:
            print("❌ Dedicated chat toast container not found")
            return False
        print("✅ Dedicated chat toast container found")

        if 'data-toast-anchor="chat-tutorial-launch"' not in chats_content:
            print("❌ Chat toast anchor metadata not found")
            return False
        print("✅ Chat toast anchor metadata found")

        if 'document.querySelector(preferredToastContainerSelector) || document.getElementById("toast-container")' not in toast_helper_content:
            print("❌ Toast helper does not prefer the anchored chat container")
            return False
        print("✅ Toast helper prefers the anchored chat container")

        if 'container.style.top = `${anchoredTop}px`;' not in toast_helper_content:
            print("❌ Toast helper does not reposition the chat toast container")
            return False
        print("✅ Toast helper repositions the chat toast container")
        
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
        
        # Check that version is updated to 0.241.010
        if 'VERSION = "0.241.010"' not in config_content:
            print("❌ Version not updated to 0.241.010")
            return False
        print("✅ Version updated to 0.241.010")
        
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
        test_chat_toast_container_anchors_below_tutorial_button,
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
        print("🎉 All tests passed! Enhanced citations blob CSP and toast positioning fixes are working correctly.")
        print("\n📝 Fix Summary:")
        print("   • Added frame-src blob support for blob-backed PDF iframes")
        print("   • Enhanced citations PDFs can now render from blob URLs under page CSP")
        print("   • Chat toasts now use a dedicated anchored container below the tutorial button")
        print("   • Version updated to 0.241.010")
        return True
    else:
        print(f"⚠️  {total - passed} test(s) failed. Please review the issues above.")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)