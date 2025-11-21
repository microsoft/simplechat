#!/usr/bin/env python3
"""
Functional test for Video Indexer dual authentication support.
Version: 0.229.064
Implemented in: 0.229.064

This test ensures that the video indexer supports both API key and managed identity
authentication methods, with proper UI controls and backend logic.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_video_indexer_authentication_settings():
    """Test that video indexer authentication type setting is properly configured in default settings."""
    print("🔍 Testing video indexer authentication settings...")
    
    try:
        # Check the functions_settings.py file directly for default value
        settings_file_path = os.path.join(
            'application', 'single_app', 'functions_settings.py'
        )
        
        if not os.path.exists(settings_file_path):
            print("❌ functions_settings.py not found")
            return False
            
        with open(settings_file_path, 'r', encoding='utf-8') as f:
            settings_content = f.read()
        
        # Check if video_indexer_authentication_type is defined
        if 'video_indexer_authentication_type' not in settings_content:
            print("❌ video_indexer_authentication_type not found in default settings file")
            return False
        
        # Check that default value is managed_identity
        if "'video_indexer_authentication_type': 'managed_identity'" not in settings_content:
            print("❌ Expected default authentication type to be 'managed_identity' in functions_settings.py")
            return False
        
        print("✅ Video indexer authentication type setting verified in default settings")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_authentication_functions():
    """Test that both authentication functions are available and work correctly."""
    print("🔍 Testing authentication functions...")
    
    try:
        # Check if the authentication functions exist
        auth_file_path = os.path.join(
            'application', 'single_app', 'functions_authentication.py'
        )
        
        if not os.path.exists(auth_file_path):
            print(f"❌ functions_authentication.py not found at {os.path.abspath(auth_file_path)}")
            return False
            
        with open(auth_file_path, 'r', encoding='utf-8') as f:
            auth_content = f.read()
        
        # Check for required functions
        required_functions = [
            'def get_video_indexer_account_token(',
            'def get_video_indexer_api_key_token(',
            'def get_video_indexer_managed_identity_token('
        ]
        
        for func in required_functions:
            if func not in auth_content:
                print(f"❌ Missing function: {func}")
                return False
        
        # Check for proper conditional logic
        if 'auth_type = settings.get("video_indexer_authentication_type"' not in auth_content:
            print("❌ Missing authentication type conditional logic")
            return False
        
        # Check for API key authentication pattern - should generate access token
        if 'if auth_type == "key":' not in auth_content:
            print("❌ Missing API key authentication conditional logic")
            return False
        
        # Verify API key method generates an access token via API
        required_api_key_patterns = [
            '/auth/',
            '/AccessToken',
            'Ocp-Apim-Subscription-Key',
            'requests.get',
            'allowEdit'
        ]
        
        for pattern in required_api_key_patterns:
            if pattern not in auth_content:
                print(f"❌ Missing API key token generation pattern: {pattern}")
                return False
        
        print("✅ Authentication functions verified")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_video_processing_authentication_support():
    """Test that video processing functions support both authentication methods."""
    print("🔍 Testing video processing authentication support...")
    
    try:
        docs_file_path = os.path.join(
            'application', 'single_app', 'functions_documents.py'
        )
        
        if not os.path.exists(docs_file_path):
            print("❌ functions_documents.py not found")
            return False
            
        with open(docs_file_path, 'r', encoding='utf-8') as f:
            docs_content = f.read()
        
        # Check for authentication type handling in upload
        # Both methods now use accessToken parameter
        required_patterns = [
            'auth_type = settings.get("video_indexer_authentication_type"',
            '"accessToken": token',
            'get_video_indexer_account_token'
        ]
        
        for pattern in required_patterns:
            if pattern not in docs_content:
                print(f"❌ Missing pattern in video processing: {pattern}")
                return False
        
        print("✅ Video processing authentication support verified")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_admin_ui_authentication_controls():
    """Test that admin UI includes authentication type controls."""
    print("🔍 Testing admin UI authentication controls...")
    
    try:
        template_file_path = os.path.join(
            'application', 'single_app', 'templates', 'admin_settings.html'
        )
        
        if not os.path.exists(template_file_path):
            print("❌ admin_settings.html template not found")
            return False
            
        with open(template_file_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Check for authentication type selector
        required_ui_elements = [
            'id="video_indexer_authentication_type"',
            'name="video_indexer_authentication_type"',
            'value="managed_identity"',
            'value="key"',
            'Managed Identity (Azure ARM)',
            'API Key',
            'id="video_indexer_api_key_section"',
            'id="video_indexer_arm_section"',
            'id="video_indexer_arm_fields"',
            'toggleVideoIndexerAuthFields'
        ]
        
        for element in required_ui_elements:
            if element not in template_content:
                print(f"❌ Missing UI element: {element}")
                return False
        
        # Check for conditional display logic
        if 'style="display: none;"' not in template_content:
            print("❌ Missing conditional display logic")
            return False
        
        print("✅ Admin UI authentication controls verified")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_backend_form_handling():
    """Test that backend properly handles the authentication type form field."""
    print("🔍 Testing backend form handling...")
    
    try:
        route_file_path = os.path.join(
            'application', 'single_app', 'route_frontend_admin_settings.py'
        )
        
        if not os.path.exists(route_file_path):
            print("❌ route_frontend_admin_settings.py not found")
            return False
            
        with open(route_file_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Check for authentication type form handling
        if "'video_indexer_authentication_type':" not in route_content:
            print("❌ Missing authentication type form field handling")
            return False
        
        if "form_data.get('video_indexer_authentication_type'" not in route_content:
            print("❌ Missing authentication type form data extraction")
            return False
        
        print("✅ Backend form handling verified")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = True
    
    # Run the tests
    tests = [
        test_video_indexer_authentication_settings,
        test_authentication_functions,
        test_video_processing_authentication_support,
        test_admin_ui_authentication_controls,
        test_backend_form_handling
    ]
    
    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        result = test()
        results.append(result)
        if not result:
            success = False
    
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All Video Indexer dual authentication support tests passed!")
    else:
        print("❌ Some tests failed")
    
    sys.exit(0 if success else 1)