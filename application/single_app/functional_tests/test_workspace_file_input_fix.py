#!/usr/bin/env python3
"""
Test to verify that workspace file upload uses correct endpoint and element IDs.

This test ensures that workspace.html and chats.html have separate file input elements
to prevent conflicts where workspace uploads would incorrectly use chat upload endpoints.

Bug Fixed: File uploads from workspace were creating conversations instead of uploading
to workspace because both templates shared the same file input ID.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_file_input_id_separation():
    """Test that workspace and chat templates have different file input IDs."""
    print("🔍 Testing file input ID separation...")
    
    try:
        # Read workspace template
        workspace_path = os.path.join(os.path.dirname(__file__), "../templates/workspace.html")
        with open(workspace_path, 'r') as f:
            workspace_content = f.read()
        
        # Read chat template
        chat_path = os.path.join(os.path.dirname(__file__), "../templates/chats.html")
        with open(chat_path, 'r') as f:
            chat_content = f.read()
        
        # Check workspace uses workspace-file-input
        if 'id="workspace-file-input"' not in workspace_content:
            print("❌ workspace.html should have id='workspace-file-input'")
            return False
        
        # Check workspace doesn't use file-input  
        if 'id="file-input"' in workspace_content:
            print("❌ workspace.html should NOT have id='file-input' (conflicts with chat)")
            return False
            
        # Check chat uses file-input
        if 'id="file-input"' not in chat_content:
            print("❌ chats.html should have id='file-input'")
            return False
            
        # Check chat doesn't use workspace-file-input
        if 'id="workspace-file-input"' in chat_content:
            print("❌ chats.html should NOT have id='workspace-file-input'")
            return False
        
        print("✅ File input IDs are properly separated")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_workspace_javascript_references():
    """Test that workspace JavaScript uses correct file input ID."""
    print("🔍 Testing workspace JavaScript file input references...")
    
    try:
        # Read workspace documents JavaScript
        js_path = os.path.join(os.path.dirname(__file__), "../static/js/workspace/workspace-documents.js")
        with open(js_path, 'r') as f:
            js_content = f.read()
        
        # Check it references workspace-file-input
        if 'getElementById("workspace-file-input")' not in js_content:
            print("❌ workspace-documents.js should reference workspace-file-input")
            return False
            
        # Check it doesn't reference the generic file-input (which could conflict)
        if 'getElementById("file-input")' in js_content:
            print("❌ workspace-documents.js should NOT reference file-input")
            return False
        
        print("✅ Workspace JavaScript uses correct file input ID")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_workspace_upload_endpoint():
    """Test that workspace JavaScript uses correct upload endpoint."""
    print("🔍 Testing workspace upload endpoint...")
    
    try:
        # Read workspace documents JavaScript
        js_path = os.path.join(os.path.dirname(__file__), "../static/js/workspace/workspace-documents.js")
        with open(js_path, 'r') as f:
            js_content = f.read()
        
        # Check it uses the correct API endpoint
        if '"/api/documents/upload"' not in js_content:
            print("❌ workspace-documents.js should use /api/documents/upload endpoint")
            return False
            
        # Check it doesn't use the chat upload endpoint
        if '"/upload"' in js_content:
            print("❌ workspace-documents.js should NOT use /upload endpoint (that's for chat)")
            return False
        
        print("✅ Workspace JavaScript uses correct upload endpoint")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_chat_upload_endpoint():
    """Test that chat JavaScript uses correct upload endpoint."""
    print("🔍 Testing chat upload endpoint...")
    
    try:
        # Read chat input actions JavaScript
        js_path = os.path.join(os.path.dirname(__file__), "../static/js/chat/chat-input-actions.js")
        with open(js_path, 'r') as f:
            js_content = f.read()
        
        # Check it uses the correct upload endpoint
        if '"/upload"' not in js_content:
            print("❌ chat-input-actions.js should use /upload endpoint")
            return False
            
        # Check it doesn't accidentally use the documents API
        if '"/api/documents/upload"' in js_content:
            print("❌ chat-input-actions.js should NOT use /api/documents/upload (that's for workspace)")
            return False
        
        print("✅ Chat JavaScript uses correct upload endpoint")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_file_input_id_separation,
        test_workspace_javascript_references,
        test_workspace_upload_endpoint,
        test_chat_upload_endpoint
    ]
    
    results = []
    
    print("🧪 Testing Workspace File Input ID Fix...")
    print("=" * 60)
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All tests passed! Workspace file upload fix is working correctly.")
        print("\n🎯 Fix Summary:")
        print("   • workspace.html now uses id='workspace-file-input'")
        print("   • chats.html continues to use id='file-input'")
        print("   • workspace uploads go to /api/documents/upload")
        print("   • chat uploads go to /upload")
        print("   • No more ID conflicts between templates")
    else:
        print("❌ Some tests failed. Check the output above.")
    
    sys.exit(0 if success else 1)
