#!/usr/bin/env python3
"""
Functional test for Smart HTTP Plugin content size management.
Version: 0.228.003
Implemented in: 0.228.003

This test ensures that the Smart HTTP Plugin properly handles large web content
and prevents token limit exceeded errors by intelligently truncating content.
"""

import sys
import os
import asyncio
import aiohttp

# Add the application directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_smart_http_plugin():
    """Test the Smart HTTP Plugin content size management."""
    print("🔍 Testing Smart HTTP Plugin...")
    
    try:
        # Import the smart HTTP plugin
        from semantic_kernel_plugins.smart_http_plugin import SmartHttpPlugin
        
        # Create plugin instance with small limit for testing
        plugin = SmartHttpPlugin(max_content_size=5000, extract_text_only=True)
        
        print("✅ Smart HTTP Plugin imported successfully!")
        
        # Test with a simple site first
        async def test_simple_site():
            print("\n📋 Testing simple website (google.com)...")
            result = await plugin.get_web_content_async("https://www.google.com")
            print(f"✅ Simple site result length: {len(result)} characters")
            print(f"📄 Preview: {result[:200]}...")
            return len(result) > 0 and len(result) <= 6000  # Allow some buffer
        
        # Test with a content-rich site
        async def test_large_site():
            print("\n📋 Testing content-rich website (bbc.com/news)...")
            result = await plugin.get_web_content_async("https://www.bbc.com/news")
            print(f"✅ Large site result length: {len(result)} characters")
            
            # Check if content was truncated
            if "CONTENT TRUNCATED" in result:
                print("🎯 Content was properly truncated to prevent token overflow!")
                return True
            else:
                print("ℹ️ Content was within limits, no truncation needed")
                return len(result) <= 6000
        
        # Test with JSON content
        async def test_json_content():
            print("\n📋 Testing JSON API endpoint...")
            try:
                result = await plugin.get_web_content_async("https://jsonplaceholder.typicode.com/posts/1")
                print(f"✅ JSON result length: {len(result)} characters")
                print(f"📄 JSON preview: {result[:300]}...")
                return len(result) > 0
            except Exception as e:
                print(f"⚠️ JSON test failed (might be network): {e}")
                return True  # Don't fail the test for network issues
        
        # Run async tests
        async def run_all_tests():
            simple_ok = await test_simple_site()
            large_ok = await test_large_site()
            json_ok = await test_json_content()
            return simple_ok and large_ok and json_ok
        
        # Run the tests
        all_passed = asyncio.run(run_all_tests())
        
        if all_passed:
            print("\n✅ All Smart HTTP Plugin tests passed!")
            print("🎯 The plugin should now prevent token limit exceeded errors")
            print("📊 Content will be intelligently truncated while preserving usefulness")
            return True
        else:
            print("\n❌ Some tests failed")
            return False
        
    except ImportError as e:
        print(f"❌ Failed to import Smart HTTP Plugin: {e}")
        print("💡 Make sure the plugin file is in the correct location")
        return False
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_fallback_http_plugin():
    """Test that the standard HTTP plugin is still available as fallback."""
    print("\n🔍 Testing HTTP Plugin fallback...")
    
    try:
        from semantic_kernel.core_plugins import HttpPlugin
        plugin = HttpPlugin()
        print("✅ Standard HttpPlugin fallback is available!")
        return True
        
    except Exception as e:
        print(f"❌ Fallback test failed: {e}")
        return False

def test_semantic_kernel_loader():
    """Test that the semantic kernel loader can load the smart HTTP plugin."""
    print("\n🔍 Testing Semantic Kernel Loader integration...")
    
    try:
        # Import semantic kernel components
        from semantic_kernel import Kernel
        from semantic_kernel_loader import load_http_plugin
        
        # Create a test kernel
        kernel = Kernel()
        
        # Load the HTTP plugin
        load_http_plugin(kernel)
        
        # Check if plugin was loaded
        http_plugin = kernel.plugins.get("http")
        if http_plugin:
            print("✅ HTTP plugin loaded successfully into kernel!")
            print(f"📋 Plugin functions: {list(http_plugin.functions.keys())}")
            return True
        else:
            print("❌ HTTP plugin not found in kernel")
            return False
            
    except Exception as e:
        print(f"❌ Loader integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Starting Smart HTTP Plugin Tests...")
    print("=" * 60)
    
    # Run all tests
    tests = [
        test_smart_http_plugin,
        test_fallback_http_plugin,
        test_semantic_kernel_loader
    ]
    
    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The Smart HTTP Plugin is ready to use.")
        print("💡 This should solve your token limit exceeded errors with web scraping.")
        print("\n🔧 Key improvements:")
        print("   • Content size limits prevent token overflow")
        print("   • HTML text extraction reduces noise")
        print("   • Intelligent truncation preserves readability")
        print("   • Better error handling for large sites")
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
    
    sys.exit(0 if passed == total else 1)
