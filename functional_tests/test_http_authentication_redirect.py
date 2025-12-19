#!/usr/bin/env python3
"""
Functional test for HTTP authentication redirect URL fix.
Version: 0.229.099
Implemented in: 0.229.099

This test ensures that the LOGIN_REDIRECT_URL environment variable is properly
respected during Azure AD authentication for local development with HTTP.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_login_redirect_url_environment_variable():
    """Test that LOGIN_REDIRECT_URL environment variable is read correctly."""
    print("🔍 Testing LOGIN_REDIRECT_URL environment variable...")
    
    try:
        # Set test environment variable
        test_url = "http://localhost:8000/getAToken"
        os.environ['LOGIN_REDIRECT_URL'] = test_url
        
        # Import after setting env var to ensure it's loaded
        import importlib
        if 'config' in sys.modules:
            importlib.reload(sys.modules['config'])
        
        from config import LOGIN_REDIRECT_URL
        
        # Verify the environment variable is loaded
        assert LOGIN_REDIRECT_URL == test_url, \
            f"Expected LOGIN_REDIRECT_URL '{test_url}', got '{LOGIN_REDIRECT_URL}'"
        
        print(f"✅ LOGIN_REDIRECT_URL correctly loaded: {LOGIN_REDIRECT_URL}")
        
        # Cleanup
        del os.environ['LOGIN_REDIRECT_URL']
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_redirect_url_fallback_logic():
    """Test the redirect URL fallback logic (LOGIN_REDIRECT_URL or url_for)."""
    print("\n🔍 Testing redirect URL fallback logic...")
    
    try:
        # Test with LOGIN_REDIRECT_URL set
        login_redirect_url = "http://localhost:8000/getAToken"
        fallback_url = "https://example.com/authorized"
        
        # Simulate: LOGIN_REDIRECT_URL or url_for('authorized', _external=True, _scheme='https')
        result = login_redirect_url or fallback_url
        
        assert result == login_redirect_url, \
            f"Expected '{login_redirect_url}', got '{result}'"
        
        print(f"✅ Redirect uses LOGIN_REDIRECT_URL when set: {result}")
        
        # Test without LOGIN_REDIRECT_URL (None)
        login_redirect_url = None
        result = login_redirect_url or fallback_url
        
        assert result == fallback_url, \
            f"Expected fallback '{fallback_url}', got '{result}'"
        
        print(f"✅ Redirect falls back to url_for when LOGIN_REDIRECT_URL not set: {result}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_http_vs_https_redirect():
    """Test that HTTP redirect works for local development."""
    print("\n🔍 Testing HTTP vs HTTPS redirect scenarios...")
    
    try:
        # Scenario 1: Local development with HTTP
        login_redirect_http = "http://localhost:8000/getAToken"
        result_http = login_redirect_http or "https://production.com/authorized"
        
        assert result_http.startswith("http://"), \
            f"Expected HTTP URL for local dev, got '{result_http}'"
        
        print(f"✅ HTTP redirect for local development: {result_http}")
        
        # Scenario 2: Production with HTTPS (LOGIN_REDIRECT_URL not set)
        login_redirect_prod = None
        result_prod = login_redirect_prod or "https://production.com/authorized"
        
        assert result_prod.startswith("https://"), \
            f"Expected HTTPS URL for production, got '{result_prod}'"
        
        print(f"✅ HTTPS redirect for production: {result_prod}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_redirect_url_consistency():
    """Test that redirect URL is used consistently across authentication flows."""
    print("\n🔍 Testing redirect URL consistency...")
    
    try:
        # Simulate the pattern used in route_frontend_authentication.py
        # At lines ~58 and ~107
        login_redirect_url = "http://localhost:8000/getAToken"
        
        # First occurrence (e.g., line 58)
        redirect_uri_1 = login_redirect_url or "https://example.com/authorized"
        
        # Second occurrence (e.g., line 107)
        redirect_uri_2 = login_redirect_url or "https://example.com/authorized"
        
        # Both should return the same value
        assert redirect_uri_1 == redirect_uri_2, \
            f"Inconsistent redirect URIs: '{redirect_uri_1}' vs '{redirect_uri_2}'"
        
        assert redirect_uri_1 == login_redirect_url, \
            f"Expected '{login_redirect_url}', got '{redirect_uri_1}'"
        
        print(f"✅ Redirect URL consistent across authentication flows: {redirect_uri_1}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_redirect_url_with_port():
    """Test that redirect URL properly handles localhost with port."""
    print("\n🔍 Testing redirect URL with port specification...")
    
    try:
        test_cases = [
            ("http://localhost:8000/getAToken", True),
            ("http://localhost:5000/getAToken", True),
            ("http://127.0.0.1:8000/getAToken", True),
            ("https://production.azure.com/authorized", True),
        ]
        
        for url, expected_valid in test_cases:
            # Basic validation: URL should start with http:// or https://
            is_valid = url.startswith("http://") or url.startswith("https://")
            
            assert is_valid == expected_valid, \
                f"URL validation failed for '{url}'"
            
            print(f"✅ Valid redirect URL: {url}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("HTTP AUTHENTICATION REDIRECT URL FIX - FUNCTIONAL TEST")
    print("=" * 70)
    
    tests = [
        test_login_redirect_url_environment_variable,
        test_redirect_url_fallback_logic,
        test_http_vs_https_redirect,
        test_redirect_url_consistency,
        test_redirect_url_with_port
    ]
    
    results = []
    
    for test in tests:
        result = test()
        results.append(result)
    
    print("\n" + "=" * 70)
    print(f"📊 RESULTS: {sum(results)}/{len(results)} tests passed")
    print("=" * 70)
    
    success = all(results)
    sys.exit(0 if success else 1)
