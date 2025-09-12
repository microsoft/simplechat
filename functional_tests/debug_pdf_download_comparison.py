#!/usr/bin/env python3
"""
Debug test to compare PDF download via SmartHttpPlugin vs direct download.
This will help identify if there's a corruption issue during download.
"""

import sys
import os
import asyncio
import aiohttp
import tempfile
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

async def download_pdf_direct(url):
    """Download PDF directly using aiohttp."""
    print(f"📥 Downloading PDF directly from: {url}")
    
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                print(f"❌ HTTP Error: {response.status} - {response.reason}")
                return None
            
            content = await response.read()
            print(f"📊 Downloaded {len(content)} bytes")
            print(f"🔍 Content type: {response.headers.get('content-type', 'unknown')}")
            print(f"🔍 PDF header check: {content[:10]}")
            print(f"✅ Valid PDF header: {content.startswith(b'%PDF-')}")
            
            return content

async def test_pdf_via_plugin(url):
    """Test PDF processing via SmartHttpPlugin."""
    print(f"🔌 Testing PDF via SmartHttpPlugin from: {url}")
    
    from semantic_kernel_plugins.smart_http_plugin import SmartHttpPlugin
    plugin = SmartHttpPlugin()
    
    # Override the _read_limited_content method to capture the raw content
    original_read_method = plugin._read_limited_content
    captured_content = None
    
    async def capture_content(response):
        nonlocal captured_content
        captured_content = await original_read_method(response)
        print(f"🔍 Plugin captured {len(captured_content)} bytes")
        print(f"🔍 Plugin PDF header: {captured_content[:10]}")
        print(f"✅ Plugin valid PDF header: {captured_content.startswith(b'%PDF-')}")
        return captured_content
    
    plugin._read_limited_content = capture_content
    
    try:
        result = await plugin.get_web_content_async(url)
        print(f"📊 Plugin result length: {len(result)} characters")
        return captured_content, result
    except Exception as e:
        print(f"❌ Plugin error: {e}")
        return captured_content, str(e)

async def compare_downloads():
    """Compare direct download vs plugin download."""
    url = "https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf"
    
    print("=" * 80)
    print("PDF DOWNLOAD COMPARISON TEST")
    print("=" * 80)
    
    # Test direct download
    direct_content = await download_pdf_direct(url)
    
    print("\n" + "-" * 40)
    
    # Test plugin download  
    plugin_content, plugin_result = await test_pdf_via_plugin(url)
    
    print("\n" + "=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)
    
    if direct_content and plugin_content:
        print(f"📊 Direct download size: {len(direct_content)} bytes")
        print(f"📊 Plugin download size: {len(plugin_content)} bytes")
        print(f"✅ Sizes match: {len(direct_content) == len(plugin_content)}")
        print(f"✅ Content identical: {direct_content == plugin_content}")
        
        if direct_content != plugin_content:
            print("🔍 Analyzing differences...")
            # Compare first and last 100 bytes
            print(f"Direct start: {direct_content[:100]}")
            print(f"Plugin start: {plugin_content[:100]}")
            print(f"Direct end: {direct_content[-100:]}")
            print(f"Plugin end: {plugin_content[-100:]}")
    
    # Save both files for manual inspection
    if direct_content:
        with open("debug_direct_download.pdf", "wb") as f:
            f.write(direct_content)
        print("💾 Saved direct download as: debug_direct_download.pdf")
    
    if plugin_content:
        with open("debug_plugin_download.pdf", "wb") as f:
            f.write(plugin_content)
        print("💾 Saved plugin download as: debug_plugin_download.pdf")

if __name__ == "__main__":
    asyncio.run(compare_downloads())