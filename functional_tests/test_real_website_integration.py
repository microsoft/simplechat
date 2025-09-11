#!/usr/bin/env python3
"""
Quick integration test for Smart HTTP Plugin with real websites.
Tests the actual functionality that was causing token limit issues.
"""

import sys
import os
import asyncio

# Add the application directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

async def test_real_websites():
    """Test with websites that previously caused token limit errors."""
    print("🌐 Testing Smart HTTP Plugin with real websites...")
    
    try:
        from semantic_kernel_plugins.smart_http_plugin import SmartHttpPlugin
        
        # Create plugin with realistic settings
        plugin = SmartHttpPlugin(max_content_size=75000, extract_text_only=True)
        
        test_sites = [
            ("https://www.google.com", "Google homepage"),
            ("https://www.bbc.com/news", "BBC News (large content)"),
            ("https://httpbin.org/json", "JSON endpoint"),
        ]
        
        results = []
        
        for url, description in test_sites:
            print(f"\n📋 Testing {description}: {url}")
            try:
                result = await plugin.get_web_content_async(url)
                length = len(result)
                
                # Check if content looks reasonable
                if length > 0 and length < 30000:  # Allow some buffer
                    print(f"✅ Success! Length: {length} characters")
                    if "CONTENT TRUNCATED" in result:
                        print("🎯 Content was intelligently truncated")
                    else:
                        print("ℹ️ Content within limits, no truncation needed")
                    
                    # Show preview
                    preview = result[:200].replace('\n', ' ')
                    print(f"📄 Preview: {preview}...")
                    results.append(True)
                else:
                    print(f"⚠️ Unexpected length: {length}")
                    results.append(False)
                    
            except Exception as e:
                print(f"❌ Error with {url}: {e}")
                results.append(False)
        
        success_rate = sum(results) / len(results)
        print(f"\n📊 Success rate: {sum(results)}/{len(results)} ({success_rate:.1%})")
        
        if success_rate >= 0.6:  # Allow for some network issues
            print("🎉 Smart HTTP Plugin is working correctly!")
            print("💡 This should resolve your token limit exceeded errors")
            return True
        else:
            print("⚠️ Some issues detected")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Running Real Website Integration Test...")
    print("=" * 60)
    
    success = asyncio.run(test_real_websites())
    
    if success:
        print("\n✅ Integration test passed!")
        print("🔧 The Smart HTTP Plugin should now prevent token overflow errors")
        print("📈 Web scraping functionality is restored and improved")
    else:
        print("\n❌ Integration test had issues")
        print("🔍 Check the output above for details")
    
    sys.exit(0 if success else 1)
