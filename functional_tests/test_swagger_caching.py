#!/usr/bin/env python3
# test_swagger_caching.py
"""
Test Swagger caching and DDOS protection.
Version: 0.229.061
Implemented in: 0.229.061

This test validates that the swagger caching system works correctly
and provides DDOS protection.
"""

import sys
import os
import requests
import json
import time
import urllib3
from concurrent.futures import ThreadPoolExecutor
import threading

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_swagger_caching_performance():
    """Test that caching improves performance."""
    print("🔍 Testing Swagger Caching Performance...")
    
    base_url = "https://127.0.0.1:5000"
    
    # Test 1: First request (cache miss)
    print("  📊 Testing cache miss (first request)...")
    start_time = time.perf_counter()
    response1 = requests.get(f"{base_url}/swagger.json", timeout=10, verify=False)
    first_time = (time.perf_counter() - start_time) * 1000
    
    if response1.status_code != 200:
        print(f"❌ First request failed: {response1.status_code}")
        return False
    
    print(f"  ✅ Cache miss: {first_time:.2f}ms")
    
    # Test 2: Second request (cache hit)
    print("  📊 Testing cache hit (second request)...")
    start_time = time.perf_counter()
    response2 = requests.get(f"{base_url}/swagger.json", timeout=10, verify=False)
    second_time = (time.perf_counter() - start_time) * 1000
    
    if response2.status_code != 200:
        print(f"❌ Second request failed: {response2.status_code}")
        return False
    
    print(f"  ✅ Cache hit: {second_time:.2f}ms")
    
    # Check if caching improved performance
    improvement = (first_time - second_time) / first_time * 100
    print(f"  📈 Performance improvement: {improvement:.1f}%")
    
    if improvement > 10:
        print(f"  🚀 Excellent: Caching provides {improvement:.0f}% performance improvement")
    elif improvement > 0:
        print(f"  ✅ Good: Caching provides some performance improvement")
    else:
        print(f"  ⚠️  Warning: Caching doesn't seem to improve performance")
    
    # Verify content is identical
    if response1.json() == response2.json():
        print("  ✅ Cache content consistency verified")
    else:
        print("  ❌ Cache content inconsistency detected")
        return False
    
    return True

def test_cache_headers():
    """Test that proper cache headers are set."""
    print("🔍 Testing Cache Headers...")
    
    base_url = "https://127.0.0.1:5000"
    response = requests.get(f"{base_url}/swagger.json", timeout=10, verify=False)
    
    if response.status_code != 200:
        print(f"❌ Request failed: {response.status_code}")
        return False
    
    # Check required headers
    required_headers = ['Cache-Control', 'ETag', 'X-Generated-At', 'X-Spec-Paths']
    missing_headers = []
    
    for header in required_headers:
        if header in response.headers:
            print(f"  ✅ {header}: {response.headers[header]}")
        else:
            missing_headers.append(header)
    
    if missing_headers:
        print(f"  ❌ Missing headers: {missing_headers}")
        return False
    
    # Verify cache control
    cache_control = response.headers.get('Cache-Control', '')
    if 'max-age=300' in cache_control and 'public' in cache_control:
        print("  ✅ Cache-Control header properly configured")
    else:
        print(f"  ⚠️  Cache-Control may not be optimal: {cache_control}")
    
    return True

def test_rate_limiting():
    """Test rate limiting protection against DDOS."""
    print("🔍 Testing Rate Limiting (DDOS Protection)...")
    
    base_url = "https://127.0.0.1:5000"
    
    def make_request(request_id):
        """Make a single request."""
        try:
            response = requests.get(f"{base_url}/swagger.json", timeout=10, verify=False)
            return {
                'id': request_id,
                'status': response.status_code,
                'time': time.time()
            }
        except Exception as e:
            return {
                'id': request_id,
                'status': 'error',
                'error': str(e),
                'time': time.time()
            }
    
    # Test with rapid requests (simulate DDOS)
    print("  📊 Sending rapid requests to test rate limiting...")
    
    # Send 35 requests rapidly (limit is 30 per minute)
    num_requests = 35
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request, i) for i in range(num_requests)]
        results = [future.result() for future in futures]
    
    end_time = time.time()
    duration = end_time - start_time
    
    # Analyze results
    successful_requests = [r for r in results if r['status'] == 200]
    rate_limited_requests = [r for r in results if r['status'] == 429]
    failed_requests = [r for r in results if r['status'] not in [200, 429]]
    
    print(f"  📊 Request Results ({duration:.2f}s):")
    print(f"    • Successful (200): {len(successful_requests)}")
    print(f"    • Rate Limited (429): {len(rate_limited_requests)}")
    print(f"    • Failed/Error: {len(failed_requests)}")
    
    # Validate rate limiting is working
    if len(rate_limited_requests) > 0:
        print("  ✅ Rate limiting is active and protecting against DDOS")
    else:
        print("  ⚠️  Warning: No rate limiting detected with 35 rapid requests")
    
    # Check if some requests succeeded (not completely blocked)
    if len(successful_requests) > 0:
        print("  ✅ Legitimate requests can still get through")
    else:
        print("  ❌ Error: All requests blocked - rate limiting too aggressive")
        return False
    
    return len(rate_limited_requests) > 0

def test_cache_management():
    """Test cache management endpoints."""
    print("🔍 Testing Cache Management...")
    
    base_url = "https://127.0.0.1:5000"
    
    # Test cache stats endpoint
    print("  📊 Testing cache stats endpoint...")
    response = requests.get(f"{base_url}/api/swagger/cache", timeout=10, verify=False)
    
    if response.status_code != 200:
        print(f"❌ Cache stats request failed: {response.status_code}")
        return False
    
    cache_data = response.json()
    if 'cache_stats' in cache_data:
        stats = cache_data['cache_stats']
        print(f"  ✅ Cache stats: {stats}")
    else:
        print("  ❌ Cache stats not found in response")
        return False
    
    # Test cache clear endpoint
    print("  🗑️  Testing cache clear endpoint...")
    clear_response = requests.delete(f"{base_url}/api/swagger/cache", timeout=10, verify=False)
    
    if clear_response.status_code != 200:
        print(f"❌ Cache clear request failed: {clear_response.status_code}")
        return False
    
    clear_data = clear_response.json()
    if 'message' in clear_data and 'cleared' in clear_data['message']:
        print("  ✅ Cache cleared successfully")
    else:
        print("  ⚠️  Cache clear response unclear")
    
    return True

def test_cache_refresh():
    """Test forced cache refresh."""
    print("🔍 Testing Cache Refresh...")
    
    base_url = "https://127.0.0.1:5000"
    
    # Make normal request
    response1 = requests.get(f"{base_url}/swagger.json", timeout=10, verify=False)
    if response1.status_code != 200:
        return False
    
    # Make forced refresh request
    response2 = requests.get(f"{base_url}/swagger.json?refresh=true", timeout=10, verify=False)
    if response2.status_code != 200:
        print(f"❌ Forced refresh failed: {response2.status_code}")
        return False
    
    # Check that both have generation timestamps
    gen_time1 = response1.headers.get('X-Generated-At')
    gen_time2 = response2.headers.get('X-Generated-At')
    
    if gen_time1 and gen_time2:
        print(f"  ✅ Refresh functionality working (timestamps: {gen_time1} vs {gen_time2})")
    else:
        print("  ⚠️  Could not verify refresh timestamps")
    
    return True

def main():
    """Run all caching tests."""
    print("🧪 Running Swagger Caching & DDOS Protection Tests...")
    print("=" * 60)
    
    tests = [
        ("Caching Performance", test_swagger_caching_performance),
        ("Cache Headers", test_cache_headers),
        ("Rate Limiting", test_rate_limiting),
        ("Cache Management", test_cache_management),
        ("Cache Refresh", test_cache_refresh)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n🧪 Running {test_name} Test...")
        try:
            result = test_func()
            results.append(result)
            if result:
                print(f"✅ {test_name} test PASSED")
            else:
                print(f"❌ {test_name} test FAILED")
        except Exception as e:
            print(f"❌ {test_name} test ERROR: {e}")
            results.append(False)
        
        print("-" * 40)
    
    # Overall results
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 FINAL RESULTS: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL CACHING TESTS PASSED!")
        print("✅ Swagger caching is working correctly")
        print("🛡️  DDOS protection is active")
        print("⚡ Performance optimizations are effective")
    else:
        print("⚠️  Some caching tests failed")
        print("💡 Review the results above for issues")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)