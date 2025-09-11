#!/usr/bin/env python3
"""
Test file upload with simulated authenticated session.
Version: 0.228.007
Implemented in: 0.228.007

This test validates that file upload works correctly when properly authenticated
using a simulated user session.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_authenticated_session_upload():
    """Test file upload with simulated authenticated session."""
    print("🔍 Testing file upload with simulated authenticated session...")
    
    try:
        import app
        
        # Create a test client
        client = app.app.test_client()
        
        # Simulate an authenticated session
        with client.session_transaction() as session:
            # Set the session variables that would be set during authentication
            session['user_id'] = '07e61033-ea1a-4472-a1e7-6b9ac874984a'  # Your user ID from the token
            session['user'] = {
                'oid': '07e61033-ea1a-4472-a1e7-6b9ac874984a',
                'name': 'Paul Microsoft',
                'preferred_username': 'paullizer@microsoft.com',
                'roles': ['Admin', 'CreatePublicWorkspaces', 'CreateGroups']
            }
            session['logged_in'] = True
        
        # Create a test file
        import io
        test_file_content = b'This is a test file for authenticated upload testing.'
        test_file = (io.BytesIO(test_file_content), 'test_upload.txt')
        
        print("📤 Attempting authenticated file upload...")
        
        # Test the upload endpoint with authentication
        response = client.post('/api/documents/upload', 
                              data={'file': test_file},
                              content_type='multipart/form-data')
        
        print(f"Response Status: {response.status_code}")
        response_text = response.get_data(as_text=True)
        print(f"Response Data: {response_text}")
        
        if response.status_code == 200:
            print("✅ File upload successful with session authentication!")
            return True
        elif response.status_code == 401:
            print("⚠️  Still getting 401 - checking session content...")
            with client.session_transaction() as session:
                print(f"Session user_id: {session.get('user_id')}")
                print(f"Session logged_in: {session.get('logged_in')}")
            return False
        elif response.status_code == 400:
            print("⚠️  Getting 400 - possible validation issue")
            return False
        else:
            print(f"⚠️  Unexpected status code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_login_required_function():
    """Test the login_required authentication function directly."""
    print("\n🔍 Testing login_required authentication function...")
    
    try:
        import functions_authentication
        
        # Test if get_current_user_id works
        if hasattr(functions_authentication, 'get_current_user_id'):
            print("✅ get_current_user_id function found")
        else:
            print("❌ get_current_user_id function not found")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Authentication function test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing authenticated file upload...")
    
    # Run the upload test
    upload_success = test_authenticated_session_upload()
    
    # Run the authentication function test
    auth_func_success = test_login_required_function()
    
    # Summary
    print(f"\n📊 Test Results:")
    print(f"  Authenticated upload: {'✅ PASSED' if upload_success else '❌ FAILED'}")
    print(f"  Auth functions: {'✅ PASSED' if auth_func_success else '❌ FAILED'}")
    
    overall_success = upload_success and auth_func_success
    print(f"  Overall: {'✅ PASSED' if overall_success else '❌ FAILED'}")
    
    sys.exit(0 if overall_success else 1)
