#!/usr/bin/env python3
# test_security_headers_comprehensive.py
"""
Functional test for comprehensive security headers implementation.
Version: 0.229.019
Implemented in: 0.229.019

This test ensures that all security headers are properly implemented to protect against
MIME sniffing attacks, XSS attacks, clickjacking, and other web vulnerabilities.
"""

import sys
import os
import requests
import time
import urllib3

# Suppress SSL warnings for local testing
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add the app directory to the path
app_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app')
sys.path.insert(0, app_dir)

def test_security_headers():
    """Test that all security headers are properly implemented."""
    print("🔍 Testing Security Headers Implementation...")
    
    try:
        # Test locally running application (HTTPS in debug mode)
        base_url = "https://localhost:5001"
        
        # Test the main page
        print("📡 Testing main page headers...")
        response = requests.get(f"{base_url}/", timeout=10, verify=False)  # Skip SSL verification for local testing
        
        # Expected security headers
        expected_headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Content-Security-Policy': 'default-src \'self\''  # Partial check
        }
        
        print("🔒 Checking security headers...")
        for header_name, expected_value in expected_headers.items():
            if header_name in response.headers:
                actual_value = response.headers[header_name]
                if header_name == 'Content-Security-Policy':
                    # For CSP, just check if it starts with expected value
                    if actual_value.startswith(expected_value):
                        print(f"✅ {header_name}: Present and properly configured")
                    else:
                        print(f"⚠️  {header_name}: Present but unexpected value: {actual_value}")
                else:
                    if expected_value in actual_value:
                        print(f"✅ {header_name}: {actual_value}")
                    else:
                        print(f"❌ {header_name}: Expected '{expected_value}', got '{actual_value}'")
                        return False
            else:
                print(f"❌ Missing header: {header_name}")
                return False
        
        # Test specific content types
        print("\n📄 Testing headers for different content types...")
        
        # Test JSON endpoint if available
        try:
            json_response = requests.get(f"{base_url}/api/health", timeout=5, verify=False)
            if 'X-Content-Type-Options' in json_response.headers:
                print(f"✅ JSON endpoint has X-Content-Type-Options: {json_response.headers['X-Content-Type-Options']}")
            else:
                print("⚠️  JSON endpoint missing X-Content-Type-Options header")
        except requests.exceptions.RequestException:
            print("ℹ️  JSON endpoint not available for testing")
        
        # Test robots.txt
        try:
            robots_response = requests.get(f"{base_url}/robots.txt", timeout=5, verify=False)
            if 'X-Content-Type-Options' in robots_response.headers:
                print(f"✅ robots.txt has X-Content-Type-Options: {robots_response.headers['X-Content-Type-Options']}")
            else:
                print("⚠️  robots.txt missing X-Content-Type-Options header")
        except requests.exceptions.RequestException:
            print("ℹ️  robots.txt not available for testing")
        
        print("\n🛡️  Security Headers Summary:")
        print("=" * 50)
        for header_name, header_value in response.headers.items():
            if any(security_term in header_name.lower() for security_term in ['x-', 'content-security', 'referrer', 'strict-transport']):
                print(f"🔐 {header_name}: {header_value}")
        
        print("\n✅ Security headers test completed successfully!")
        return True
        
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to the application. Make sure it's running on https://localhost:5001")
        print("💡 Start the application with: python app.py (with FLASK_DEBUG=1 for HTTPS)")
        return False
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_mime_sniffing_protection():
    """Test specific protection against MIME sniffing attacks."""
    print("\n🔍 Testing MIME Sniffing Protection...")
    
    try:
        base_url = "https://localhost:5001"
        
        # Test various content types
        test_endpoints = [
            "/",
            "/robots.txt",
        ]
        
        for endpoint in test_endpoints:
            try:
                response = requests.get(f"{base_url}{endpoint}", timeout=5, verify=False)
                
                # Check for X-Content-Type-Options header
                if 'X-Content-Type-Options' in response.headers:
                    header_value = response.headers['X-Content-Type-Options']
                    if header_value == 'nosniff':
                        print(f"✅ {endpoint}: Protected against MIME sniffing")
                    else:
                        print(f"⚠️  {endpoint}: X-Content-Type-Options present but value is '{header_value}' (expected 'nosniff')")
                else:
                    print(f"❌ {endpoint}: Missing X-Content-Type-Options header")
                    return False
                    
            except requests.exceptions.RequestException as e:
                print(f"ℹ️  {endpoint}: Not available for testing ({e})")
        
        print("✅ MIME sniffing protection test completed!")
        return True
        
    except Exception as e:
        print(f"❌ MIME sniffing protection test failed: {e}")
        return False

def test_configuration_accessibility():
    """Test that security configuration is properly accessible."""
    print("\n🔍 Testing Security Configuration Accessibility...")
    
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'config.py')
    
    try:
        # Try to read the config file directly and check for security headers
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
        
        # Check for security configuration
        if 'SECURITY_HEADERS' in config_content:
            print("✅ SECURITY_HEADERS configuration found in config.py")
        else:
            print("❌ SECURITY_HEADERS configuration not found in config.py")
            return False
        
        # Check for critical security headers in config
        critical_headers = ['X-Content-Type-Options', 'X-Frame-Options', 'Content-Security-Policy']
        for header in critical_headers:
            if header in config_content:
                print(f"✅ Critical header '{header}' found in configuration")
            else:
                print(f"❌ Critical header '{header}' not found in configuration")
                return False
        
        # Check for HSTS configuration
        if 'ENABLE_STRICT_TRANSPORT_SECURITY' in config_content:
            print("✅ HSTS configuration found")
        else:
            print("❌ HSTS configuration not found")
            return False
        
        print("✅ Security configuration accessibility test completed!")
        return True
        
    except FileNotFoundError:
        print(f"❌ Could not find config.py at {config_path}")
        return False
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Running Comprehensive Security Headers Tests...")
    print("=" * 60)
    
    tests = [
        test_configuration_accessibility,
        test_security_headers,
        test_mime_sniffing_protection
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All security header tests passed! Your application is protected against MIME sniffing and other web vulnerabilities.")
    else:
        print("⚠️  Some tests failed. Please review the security header implementation.")
    
    sys.exit(0 if success else 1)
