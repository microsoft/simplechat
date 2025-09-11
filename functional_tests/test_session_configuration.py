#!/usr/bin/env python3
"""
Test if SECRET_KEY configuration fixes session authentication.
Version: 0.228.007
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_session_configuration():
    """Test if Flask session configuration is working properly."""
    print("🔍 Testing Flask session configuration...")
    
    try:
        import app
        
        print(f"SECRET_KEY configured: {'SECRET_KEY' in app.app.config}")
        print(f"SESSION_TYPE: {app.app.config.get('SESSION_TYPE')}")
        print(f"VERSION: {app.app.config.get('VERSION')}")
        
        # Test if session works now
        from werkzeug.test import Client
        import io
        
        client = app.app.test_client()
        
        # Test session creation capability
        with client.session_transaction() as session:
            session['test'] = 'session_works'
        
        with client.session_transaction() as session:
            if 'test' in session and session['test'] == 'session_works':
                print("✅ Session persistence working!")
                session_works = True
            else:
                print("❌ Session persistence not working")
                session_works = False
        
        # Try upload endpoint (should still be 401 but with proper session handling)
        test_file_content = b'Test file with fixed session configuration.'
        test_file = (io.BytesIO(test_file_content), 'test.txt')
        
        response = client.post('/api/documents/upload', 
                              data={'file': test_file},
                              content_type='multipart/form-data')
        
        print(f"Upload response status: {response.status_code}")
        response_text = response.get_data(as_text=True)
        print(f"Response data: {response_text}")
        
        # If we get a proper 401 with authentication message, session is working
        if response.status_code == 401 and "Authentication required" in response_text:
            print("✅ Upload endpoint responding correctly with session support")
            upload_endpoint_ok = True
        else:
            print("⚠️  Upload endpoint response unexpected")
            upload_endpoint_ok = False
            
        return session_works and upload_endpoint_ok
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_session_configuration()
    print(f"\n📊 Session configuration test: {'✅ PASSED' if success else '❌ FAILED'}")
    sys.exit(0 if success else 1)
