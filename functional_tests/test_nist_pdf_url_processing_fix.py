#!/usr/bin/env python3
# test_nist_pdf_url_processing_fix.py
"""
Functional test for NIST PDF URL processing fix.
Version: 0.228.024
Implemented in: 0.228.024

This test ensures that the NIST CSWP.29 PDF that works via workspace upload
also works correctly when accessed via SmartHttpPlugin URL.
"""

import sys
import os
import asyncio
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_nist_pdf_url_processing():
    """Test that NIST PDF URL processes correctly with SmartHttpPlugin."""
    print("🔍 Testing NIST PDF URL processing via SmartHttpPlugin...")
    
    try:
        # Test URL that was failing
        test_url = "https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf"
        
        # Import SmartHttpPlugin
        from semantic_kernel_plugins.smart_http_plugin import SmartHttpPlugin
        
        # Create plugin instance
        plugin = SmartHttpPlugin()
        
        # Test the PDF processing
        async def run_test():
            print(f"📥 Attempting to process PDF from: {test_url}")
            result = await plugin.get_web_content_async(test_url)
            
            # Check if we got a valid result (not an error)
            if result.startswith("📄 **PDF"):
                if "ERROR" in result or "INVALID" in result or "NOT SUPPORTED" in result:
                    print(f"❌ PDF processing failed with error: {result[:200]}...")
                    return False
                else:
                    print("✅ PDF processed successfully!")
                    print(f"📊 Result length: {len(result)} characters")
                    print(f"📄 Result preview: {result[:300]}...")
                    return True
            else:
                print(f"❌ Unexpected result format: {result[:200]}...")
                return False
        
        # Run the async test
        success = asyncio.run(run_test())
        
        if success:
            print("✅ NIST PDF URL processing test passed!")
            return True
        else:
            print("❌ NIST PDF URL processing test failed!")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pdf_header_validation():
    """Test PDF header validation logic."""
    print("🔍 Testing PDF header validation...")
    
    try:
        from semantic_kernel_plugins.smart_http_plugin import SmartHttpPlugin
        
        plugin = SmartHttpPlugin()
        
        # Test with invalid PDF data (HTML response)
        html_content = b"<html><body>Not a PDF</body></html>"
        
        async def run_validation_test():
            result = await plugin._process_pdf_content(html_content, "test://invalid-pdf", None)
            
            if "INVALID PDF FORMAT" in result:
                print("✅ PDF header validation working correctly!")
                return True
            else:
                print(f"❌ PDF header validation failed: {result[:200]}...")
                return False
        
        success = asyncio.run(run_validation_test())
        return success
        
    except Exception as e:
        print(f"❌ PDF header validation test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Running NIST PDF URL processing tests...\n")
    
    tests = [
        test_pdf_header_validation,
        test_nist_pdf_url_processing
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("\n🎯 All tests completed successfully! NIST PDF URL processing should now work correctly.")
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
    
    sys.exit(0 if success else 1)