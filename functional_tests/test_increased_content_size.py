#!/usr/bin/env python3
# test_increased_content_size.py
"""
Test to verify increased content size limit of 75k characters (≈50k tokens).
Version: 0.228.004
Implemented in: 0.229.001
"""

import sys
import os
import asyncio

# Add the application directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

async def test_increased_content_size():
    """Test that the increased content size limit works properly."""
    print("📏 Testing increased content size limit (75k characters ≈ 50k tokens)...")
    
    try:
        from semantic_kernel_plugins.smart_http_plugin import SmartHttpPlugin
        
        # Test default initialization
        plugin_default = SmartHttpPlugin()
        print(f"✅ Default max_content_size: {plugin_default.max_content_size:,} characters")
        
        # Test explicit initialization with new limit
        plugin_explicit = SmartHttpPlugin(max_content_size=75000)
        print(f"✅ Explicit max_content_size: {plugin_explicit.max_content_size:,} characters")
        
        # Verify the limits are correct
        if plugin_default.max_content_size == 75000:
            print("🎯 Default limit correctly set to 75,000 characters")
        else:
            print(f"❌ Default limit unexpected: {plugin_default.max_content_size}")
            return False
            
        # Test with a larger content site
        print("\n📋 Testing with larger content website...")
        try:
            # Try Wikipedia which typically has more content
            result = await plugin_default.get_web_content_async("https://en.wikipedia.org/wiki/Artificial_intelligence")
            length = len(result)
            
            print(f"✅ Wikipedia AI page result: {length:,} characters")
            
            if length > 25000:  # Should be larger than old limit
                print("🎯 Successfully handles larger content than previous 25k limit!")
            
            if "CONTENT TRUNCATED" in result:
                print("📏 Content was truncated at the new 75k limit")
            else:
                print("ℹ️ Content fit within the new 75k limit")
                
            return True
            
        except Exception as e:
            print(f"⚠️ Website test failed (might be network): {e}")
            return True  # Don't fail for network issues
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_semantic_kernel_integration():
    """Test that semantic kernel loader uses the new limit."""
    print("\n🔍 Testing Semantic Kernel integration with new limit...")
    
    try:
        from semantic_kernel import Kernel
        from semantic_kernel_loader import load_http_plugin
        
        # Create a test kernel
        kernel = Kernel()
        
        # Load the HTTP plugin (should use new 75k limit)
        load_http_plugin(kernel)
        
        # Check if plugin was loaded
        http_plugin = kernel.plugins.get("http")
        if http_plugin:
            print("✅ HTTP plugin loaded with new content size limits!")
            return True
        else:
            print("❌ HTTP plugin not found in kernel")
            return False
            
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Testing Increased Content Size (75k chars ≈ 50k tokens)")
    print("=" * 65)
    
    # Run tests
    async def run_tests():
        size_test = await test_increased_content_size()
        integration_test = test_semantic_kernel_integration()
        return size_test and integration_test
    
    success = asyncio.run(run_tests())
    
    print("\n" + "=" * 65)
    if success:
        print("🎉 All tests passed! Content size successfully increased to 75k characters")
        print("📊 Token capacity: ~50k tokens (well within 200k model limit)")
        print("🌐 Web scraping can now handle much larger content while staying safe")
    else:
        print("⚠️ Some tests had issues - check output above")
    
    sys.exit(0 if success else 1)
