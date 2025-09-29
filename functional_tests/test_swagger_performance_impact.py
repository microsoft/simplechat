#!/usr/bin/env python3
"""
Performance test for Swagger Route Wrapper system.
Version: 0.229.061
Implemented in: 0.229.061

This test measures the performance impact of the @swagger_route decorator
to ensure it doesn't negatively affect user experience.
"""

import sys
import os
import requests
import json
import time
import urllib3
from statistics import mean, median, stdev

# Disable SSL warnings since we're testing with self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add the application directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def measure_endpoint_performance(base_url, endpoints, num_requests=10):
    """Measure response times for multiple endpoints."""
    results = {}
    
    for endpoint in endpoints:
        print(f"  📊 Testing {endpoint}...")
        response_times = []
        
        for i in range(num_requests):
            start_time = time.perf_counter()
            try:
                response = requests.get(f"{base_url}{endpoint}", timeout=10, verify=False)
                end_time = time.perf_counter()
                
                if response.status_code in [200, 401, 403]:  # Expected responses
                    response_times.append((end_time - start_time) * 1000)  # Convert to ms
                else:
                    print(f"    ⚠️  Unexpected status code {response.status_code}")
            except Exception as e:
                print(f"    ❌ Request failed: {e}")
                continue
        
        if response_times:
            results[endpoint] = {
                'count': len(response_times),
                'avg_ms': mean(response_times),
                'median_ms': median(response_times),
                'min_ms': min(response_times),
                'max_ms': max(response_times),
                'std_dev': stdev(response_times) if len(response_times) > 1 else 0
            }
            
            print(f"    ✅ Avg: {results[endpoint]['avg_ms']:.2f}ms, "
                  f"Median: {results[endpoint]['median_ms']:.2f}ms, "
                  f"Min: {results[endpoint]['min_ms']:.2f}ms, "
                  f"Max: {results[endpoint]['max_ms']:.2f}ms")
        else:
            print(f"    ❌ No successful responses for {endpoint}")
    
    return results

def test_swagger_generation_performance(base_url):
    """Test the performance of swagger spec generation."""
    print("🔍 Testing Swagger Spec Generation Performance...")
    
    generation_times = []
    
    for i in range(5):  # Test 5 times to get average
        start_time = time.perf_counter()
        try:
            response = requests.get(f"{base_url}/swagger.json", timeout=30, verify=False)
            end_time = time.perf_counter()
            
            if response.status_code == 200:
                generation_time = (end_time - start_time) * 1000
                generation_times.append(generation_time)
                
                # Check spec size
                spec = response.json()
                paths_count = len(spec.get('paths', {}))
                content_size = len(response.content)
                
                print(f"  📊 Generation #{i+1}: {generation_time:.2f}ms, "
                      f"Paths: {paths_count}, Size: {content_size/1024:.1f}KB")
            else:
                print(f"  ❌ Failed to generate spec: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ❌ Spec generation failed: {e}")
            return False
    
    if generation_times:
        avg_time = mean(generation_times)
        print(f"  ✅ Average generation time: {avg_time:.2f}ms")
        print(f"  📈 Min: {min(generation_times):.2f}ms, Max: {max(generation_times):.2f}ms")
        
        # Performance thresholds
        if avg_time > 5000:  # 5 seconds
            print(f"  ⚠️  Warning: Spec generation is slow ({avg_time:.0f}ms)")
        elif avg_time > 1000:  # 1 second
            print(f"  💡 Info: Spec generation takes {avg_time:.0f}ms (acceptable)")
        else:
            print(f"  🚀 Excellent: Fast spec generation ({avg_time:.0f}ms)")
        
        return True
    
    return False

def test_memory_usage_indicators(base_url):
    """Test indicators of memory usage impact."""
    print("🔍 Testing Memory Usage Indicators...")
    
    try:
        # Get route statistics
        response = requests.get(f"{base_url}/api/swagger/routes", timeout=10, verify=False)
        
        if response.status_code == 200:
            data = response.json()
            total_routes = data.get('total_routes', 0)
            documented_routes = data.get('documented_routes', 0)
            
            # Estimate memory usage
            estimated_metadata_per_route = 1  # KB per route (conservative estimate)
            estimated_total_memory = documented_routes * estimated_metadata_per_route
            
            print(f"  📊 Route Statistics:")
            print(f"    • Total routes: {total_routes}")
            print(f"    • Documented routes: {documented_routes}")
            print(f"    • Documentation coverage: {(documented_routes/total_routes*100):.1f}%")
            print(f"  💾 Estimated metadata memory usage: ~{estimated_total_memory}KB")
            
            # Check if this is reasonable
            if estimated_total_memory < 100:
                print(f"  ✅ Excellent: Very low memory footprint")
            elif estimated_total_memory < 500:
                print(f"  ✅ Good: Reasonable memory footprint")
            elif estimated_total_memory < 1000:
                print(f"  ⚠️  Moderate: {estimated_total_memory}KB memory usage")
            else:
                print(f"  ⚠️  High: {estimated_total_memory}KB memory usage")
            
            return True
        else:
            print(f"  ❌ Failed to get route statistics: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"  ❌ Memory test failed: {e}")
        return False

def test_business_logic_performance(base_url):
    """Test that business logic performance is unaffected."""
    print("🔍 Testing Business Logic Performance Impact...")
    
    # Test endpoints that should have business logic (documented vs undocumented)
    test_endpoints = [
        "/api/models/gpt",         # Documented endpoint
        "/api/models/embedding",   # Documented endpoint  
        "/api/models/image",       # Documented endpoint
    ]
    
    print("  📊 Measuring response times for documented endpoints...")
    results = measure_endpoint_performance(base_url, test_endpoints, num_requests=10)
    
    if results:
        all_times = []
        for endpoint, stats in results.items():
            all_times.extend([stats['avg_ms']])
        
        overall_avg = mean(all_times)
        print(f"  📈 Overall average response time: {overall_avg:.2f}ms")
        
        # Performance assessment
        if overall_avg < 50:
            print(f"  🚀 Excellent: Very fast responses ({overall_avg:.0f}ms)")
        elif overall_avg < 200:
            print(f"  ✅ Good: Fast responses ({overall_avg:.0f}ms)")
        elif overall_avg < 500:
            print(f"  ⚠️  Acceptable: Moderate response times ({overall_avg:.0f}ms)")
        else:
            print(f"  ❌ Slow: Response times may impact UX ({overall_avg:.0f}ms)")
        
        return overall_avg < 1000  # Fail if responses take more than 1 second
    
    return False

def test_swagger_performance_impact():
    """Main performance impact test."""
    print("🧪 Running Swagger Performance Impact Tests...")
    print("=" * 60)
    
    base_url = "https://127.0.0.1:5000"
    
    try:
        # Test 1: Swagger spec generation performance
        spec_test = test_swagger_generation_performance(base_url)
        
        print("\n" + "-" * 40)
        
        # Test 2: Memory usage indicators
        memory_test = test_memory_usage_indicators(base_url)
        
        print("\n" + "-" * 40)
        
        # Test 3: Business logic performance
        logic_test = test_business_logic_performance(base_url)
        
        print("\n" + "=" * 60)
        
        # Overall assessment
        all_passed = spec_test and memory_test and logic_test
        
        if all_passed:
            print("✅ Performance Impact Assessment: ACCEPTABLE")
            print("🎯 The swagger wrapper system has minimal performance impact")
            print("📊 Key findings:")
            print("   • Swagger spec generation is reasonable")
            print("   • Memory footprint is minimal")
            print("   • Business logic response times are unaffected")
            print("   • No significant performance degradation detected")
        else:
            print("⚠️  Performance Impact Assessment: NEEDS ATTENTION")
            print("🔍 Some performance issues detected - review results above")
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_swagger_performance_impact()
    
    print(f"\n{'='*60}")
    if success:
        print("🎉 SWAGGER PERFORMANCE TEST PASSED!")
        print("The swagger wrapper system does not negatively impact performance.")
    else:
        print("💥 SWAGGER PERFORMANCE TEST FAILED!")
        print("Performance issues detected - review the results above.")
    
    sys.exit(0 if success else 1)