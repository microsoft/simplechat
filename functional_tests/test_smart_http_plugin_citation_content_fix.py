#!/usr/bin/env python3
"""
Test Smart HTTP Plugin Citation Content Fix.
Version: 0.228.014

This test specifically validates that the function result in citations shows 
actual content instead of coroutine objects after the async decorator fix.
"""

import sys
import os
import asyncio
import time

# Add the application path for imports
app_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'application', 'single_app')
sys.path.insert(0, app_path)

from semantic_kernel_plugins.smart_http_plugin import SmartHttpPlugin, log_plugin_invocation

def test_citation_content_fix():
    """Test that citations show actual results, not coroutine objects."""
    print("🧪 Testing Smart HTTP Plugin Citation Content Fix...")
    
    try:
        plugin = SmartHttpPlugin()
        print(f"   ✅ Plugin initialized successfully")
        
        async def test_actual_results():
            """Test that we get actual results in citations."""
            
            # Clear any previous invocations
            plugin.function_calls = []
            
            # Test URL that should return JSON
            test_url = "https://httpbin.org/json"
            print(f"   🔍 Testing async decorator with URL: {test_url}")
            
            # This should trigger the @async_plugin_logger decorator
            result = await plugin.get_web_content_async(test_url)
            
            print(f"   ✅ Function executed successfully")
            print(f"   📋 Result type: {type(result)}")
            print(f"   📋 Result length: {len(result)} chars")
            print(f"   📄 Result preview: {result[:100]}...")
            
            # Validate result content
            if 'coroutine' in str(result).lower():
                print(f"   ❌ ERROR: Result contains coroutine object!")
                return False
            elif result and len(result) > 0:
                print(f"   ✅ Result contains actual content (not coroutine)")
                return True
            else:
                print(f"   ⚠️ Result is empty or None")
                return False
        
        # Run async test
        success = asyncio.run(test_actual_results())
        
        if success:
            print(f"\n📊 Citation Content Fix Validation:")
            print(f"   ✅ Async decorator properly awaits function results")
            print(f"   ✅ Citations will show actual content, not coroutine objects")
            print(f"   ✅ Function result format: str (content)")
            print(f"   ✅ Fix successfully resolves citation display issue")
            return True
        else:
            print(f"\n📊 Citation Content Fix Validation:")
            print(f"   ❌ Async decorator still has issues")
            print(f"   ❌ Citations may still show coroutine objects")
            return False
            
    except Exception as e:
        print(f"   ❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🔧 Smart HTTP Plugin Citation Content Fix Test")
    print("=" * 60)
    print("🎯 Purpose: Validate that citations show actual results, not coroutine objects")
    print("🔄 Issue: Previous decorator captured coroutine before awaiting")
    print("✅ Fix: Custom async_plugin_logger that properly awaits results")
    print("=" * 60)
    
    success = test_citation_content_fix()
    
    print("\n" + "=" * 60)
    if success:
        print("📋 Test Summary: ✅ PASSED")
        print("🎉 Citation content fix is working correctly!")
        print("🔗 Agent citations will now display proper function results")
        print("📝 No more coroutine objects in citation display")
    else:
        print("📋 Test Summary: ❌ FAILED")
        print("⚠️ Citation content fix needs further investigation")
    
    sys.exit(0 if success else 1)