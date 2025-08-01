#!/usr/bin/env python3
"""
HTTPS Test Script for SimpleChat

This script tests if HTTPS is working correctly for your SimpleChat instance.
"""

import requests
import ssl
import socket
import sys
import urllib3
from urllib.parse import urlparse

# Disable SSL warnings for self-signed certificates during testing
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_http_endpoint(url):
    """Test if HTTP endpoint is accessible"""
    try:
        response = requests.get(url, timeout=10)
        return {
            'success': True,
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'accessible': True
        }
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': str(e),
            'accessible': False
        }

def test_https_endpoint(url):
    """Test if HTTPS endpoint is accessible"""
    try:
        # Test with SSL verification disabled (for self-signed certs)
        response = requests.get(url, timeout=10, verify=False)
        return {
            'success': True,
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'accessible': True,
            'ssl_verified': False
        }
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': str(e),
            'accessible': False
        }

def test_ssl_certificate(hostname, port):
    """Test SSL certificate details"""
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                return {
                    'success': True,
                    'certificate': cert,
                    'cipher': ssock.cipher(),
                    'version': ssock.version()
                }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

def print_results(test_name, result):
    """Print test results in a formatted way"""
    print(f"\n{test_name}")
    print("=" * len(test_name))
    
    if result['success']:
        print("✅ SUCCESS")
        if 'status_code' in result:
            print(f"   Status Code: {result['status_code']}")
        if 'accessible' in result:
            print(f"   Accessible: {result['accessible']}")
        if 'ssl_verified' in result:
            print(f"   SSL Verified: {result['ssl_verified']}")
        if 'version' in result:
            print(f"   TLS Version: {result['version']}")
        if 'cipher' in result:
            cipher = result['cipher']
            if cipher:
                print(f"   Cipher: {cipher[0]} ({cipher[1]} bits)")
    else:
        print("❌ FAILED")
        print(f"   Error: {result['error']}")

def main():
    print("SimpleChat HTTPS Test")
    print("=" * 20)
    
    # Default URLs to test
    http_url = "http://localhost:5000"
    https_url = "https://localhost:5443"
    
    # Allow custom URLs via command line
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
        parsed = urlparse(test_url)
        if parsed.scheme == 'https':
            https_url = test_url
            http_url = f"http://{parsed.netloc.split(':')[0]}:5000"
        else:
            http_url = test_url
            https_url = f"https://{parsed.netloc.split(':')[0]}:5443"
    
    print(f"Testing HTTP: {http_url}")
    print(f"Testing HTTPS: {https_url}")
    
    # Test HTTP endpoint
    http_result = test_http_endpoint(http_url)
    print_results("HTTP Connectivity Test", http_result)
    
    # Test HTTPS endpoint
    https_result = test_https_endpoint(https_url)
    print_results("HTTPS Connectivity Test", https_result)
    
    # Test SSL certificate if HTTPS is working
    if https_result['success']:
        parsed_https = urlparse(https_url)
        hostname = parsed_https.hostname
        port = parsed_https.port or 443
        
        ssl_result = test_ssl_certificate(hostname, port)
        print_results("SSL Certificate Test", ssl_result)
        
        if ssl_result['success'] and 'certificate' in ssl_result:
            cert = ssl_result['certificate']
            print("\nCertificate Details:")
            print("-" * 20)
            if 'subject' in cert:
                for item in cert['subject']:
                    for key, value in item:
                        print(f"   {key}: {value}")
            if 'notBefore' in cert:
                print(f"   Valid From: {cert['notBefore']}")
            if 'notAfter' in cert:
                print(f"   Valid Until: {cert['notAfter']}")
    
    # Summary
    print("\nSummary:")
    print("-" * 8)
    if http_result['accessible']:
        print("✅ HTTP is working")
    else:
        print("❌ HTTP is not accessible")
    
    if https_result['success'] and https_result['accessible']:
        print("✅ HTTPS is working")
        print("   Note: Browser may still show warnings for self-signed certificates")
    else:
        print("❌ HTTPS is not working")
        if not https_result['success']:
            print(f"   Reason: {https_result['error']}")
    
    print("\nRecommendations:")
    print("-" * 15)
    if not https_result['success']:
        print("• Ensure HTTPS is enabled in SimpleChat settings")
        print("• Check that SSL certificates are properly configured")
        print("• Verify the correct port is being used")
        print("• Check application logs for SSL-related errors")
    elif https_result['success']:
        print("• HTTPS is working correctly!")
        print("• For self-signed certificates, you may need to accept browser warnings")
        print("• Consider using certificates from a trusted CA for production")

if __name__ == "__main__":
    main()
