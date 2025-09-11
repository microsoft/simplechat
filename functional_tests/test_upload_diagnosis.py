#!/usr/bin/env python3
"""
Diagnose file upload 400 error by checking various validation points.
Version: 0.228.007

This test checks all the validation points that could cause a 400 error.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_upload_validation_points():
    """Test all validation points that could cause 400 errors."""
    print("🔍 Diagnosing file upload 400 error...")
    
    try:
        import app
        from functions_settings import get_settings
        from functions_documents import allowed_file
        from config import ALLOWED_EXTENSIONS
        
        # 1. Check if user workspace is enabled
        print("\n1️⃣ Checking if user workspace is enabled...")
        settings = get_settings()
        workspace_enabled = settings.get("enable_user_workspace", False)
        print(f"   enable_user_workspace: {workspace_enabled}")
        
        if not workspace_enabled:
            print("❌ FOUND ISSUE: User workspace is disabled!")
            print("   This would cause a 400 error with message 'Enable User Workspace is disabled.'")
            return False
        else:
            print("✅ User workspace is enabled")
        
        # 2. Check allowed file extensions
        print("\n2️⃣ Checking allowed file extensions...")
        print(f"   Allowed extensions: {sorted(ALLOWED_EXTENSIONS)}")
        
        # Test common file types
        test_files = ['test.txt', 'test.pdf', 'test.docx', 'test.exe', 'test.js']
        for test_file in test_files:
            is_allowed = allowed_file(test_file)
            status = "✅" if is_allowed else "❌"
            print(f"   {test_file}: {status}")
        
        # 3. Test the upload endpoint with a simple text file
        print("\n3️⃣ Testing upload endpoint with valid file...")
        
        client = app.app.test_client()
        
        # Simulate authenticated session
        with client.session_transaction() as session:
            session['user_id'] = '07e61033-ea1a-4472-a1e7-6b9ac874984a'
            session['user'] = {
                'oid': '07e61033-ea1a-4472-a1e7-6b9ac874984a',
                'name': 'Paul Microsoft',
                'preferred_username': 'paullizer@microsoft.com',
                'roles': ['Admin', 'CreatePublicWorkspaces', 'CreateGroups']
            }
            session['logged_in'] = True
        
        # Create a simple test file
        import io
        test_file_content = b'This is a test file for upload validation.'
        test_file = (io.BytesIO(test_file_content), 'test.txt')
        
        response = client.post('/api/documents/upload', 
                              data={'file': test_file},
                              content_type='multipart/form-data')
        
        print(f"   Response status: {response.status_code}")
        response_text = response.get_data(as_text=True)
        print(f"   Response data: {response_text[:200]}...")
        
        if response.status_code == 400:
            print("❌ Still getting 400 error")
            print("   Response details:")
            print(f"   {response_text}")
            return False
        elif response.status_code == 200:
            print("✅ Upload successful!")
            return True
        else:
            print(f"⚠️  Unexpected status: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_temp_directory():
    """Test if temp directory is accessible."""
    print("\n4️⃣ Checking temp directory access...")
    
    try:
        import tempfile
        import os
        
        # Check if /sc-temp-files exists (used by upload)
        sc_temp_dir = "/sc-temp-files"
        if os.path.exists(sc_temp_dir):
            print(f"✅ SC temp directory exists: {sc_temp_dir}")
        else:
            print(f"⚠️  SC temp directory not found, using system temp")
        
        # Test creating a temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as tmp_file:
            tmp_file.write(b'test')
            temp_path = tmp_file.name
        
        print(f"✅ Temp file creation successful: {temp_path}")
        
        # Clean up
        if os.path.exists(temp_path):
            os.remove(temp_path)
            print("✅ Temp file cleanup successful")
        
        return True
        
    except Exception as e:
        print(f"❌ Temp directory test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Diagnosing file upload 400 error...")
    
    # Run validation tests
    validation_success = test_upload_validation_points()
    temp_success = test_temp_directory()
    
    # Summary
    print(f"\n📊 Diagnostic Results:")
    print(f"  Validation tests: {'✅ PASSED' if validation_success else '❌ FAILED'}")
    print(f"  Temp directory: {'✅ PASSED' if temp_success else '❌ FAILED'}")
    
    overall_success = validation_success and temp_success
    print(f"  Overall: {'✅ PASSED' if overall_success else '❌ FAILED'}")
    
    if not overall_success:
        print("\n💡 Next steps:")
        print("   - Check admin settings to enable user workspace")
        print("   - Verify file types are allowed")
        print("   - Check backend logs for detailed error messages")
    
    sys.exit(0 if overall_success else 1)
