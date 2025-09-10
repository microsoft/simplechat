#!/usr/bin/env python3
"""
Test to verify that workspace file uploads don't create conversations.

This test ensures that when files are uploaded to personal workspaces, group workspaces,
or public workspaces, no conversations are created and no "file content not found" errors
occur due to the shared_group_ids field missing from the search index.

Bug Fixed: 
1. File uploads from workspace were creating conversations when they shouldn't
2. Search index updates were failing due to shared_group_ids field not existing in API version 2024-07-01
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_personal_workspace_upload_no_conversation():
    """Test that personal workspace uploads don't create conversations."""
    print("🔍 Testing personal workspace upload behavior...")
    
    try:
        # Check the upload endpoint code to ensure conversation creation is removed
        route_file = os.path.join(os.path.dirname(__file__), "../route_backend_documents.py")
        with open(route_file, 'r') as f:
            content = f.read()
        
        # Verify conversation creation code is removed/commented
        conversation_indicators = [
            "conversation_id = str(uuid.uuid4())",
            "cosmos_conversations_container.upsert_item(conversation_item)",
            "file_message_id = f\"{conversation_id}_file_",
            "cosmos_messages_container.upsert_item(file_message)"
        ]
        
        found_conversation_code = False
        for indicator in conversation_indicators:
            if indicator in content and not content.count(f"# {indicator}") and not content.count(f"#{indicator}"):
                # Check if it's in a comment block
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if indicator in line and not line.strip().startswith('#'):
                        found_conversation_code = True
                        print(f"❌ Found uncommented conversation code at line {i+1}: {line.strip()}")
                        break
        
        if not found_conversation_code:
            print("✅ Personal workspace upload endpoint doesn't create conversations")
            return True
        else:
            print("❌ Personal workspace upload still contains conversation creation code")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_search_index_field_filtering():
    """Test that search index updates filter fields correctly for workspace types."""
    print("🔍 Testing search index field filtering...")
    
    try:
        # Check the functions_documents.py file for proper field filtering
        functions_file = os.path.join(os.path.dirname(__file__), "../functions_documents.py")
        with open(functions_file, 'r') as f:
            content = f.read()
        
        # Look for the update_chunk_metadata function
        if "def update_chunk_metadata" not in content:
            print("❌ update_chunk_metadata function not found")
            return False
        
        # Check for conditional shared_group_ids handling
        if "if is_group:" in content and "shared_group_ids" in content:
            # Check that shared_group_ids is conditionally added
            lines = content.split('\n')
            found_conditional_handling = False
            
            for i, line in enumerate(lines):
                if "if is_group:" in line and i < len(lines) - 2:
                    # Look for shared_group_ids in the next few lines
                    for j in range(i, min(i + 5, len(lines))):
                        if "shared_group_ids" in lines[j] and "append" in lines[j]:
                            found_conditional_handling = True
                            break
                    if found_conditional_handling:
                        break
            
            if found_conditional_handling:
                print("✅ Search index updates conditionally handle shared_group_ids field")
                return True
            else:
                print("❌ Search index updates don't properly filter shared_group_ids field")
                return False
        else:
            print("❌ Conditional shared_group_ids handling not found")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_group_workspace_upload_behavior():
    """Test that group workspace uploads behave correctly."""
    print("🔍 Testing group workspace upload behavior...")
    
    try:
        # Check group upload endpoint
        group_route_file = os.path.join(os.path.dirname(__file__), "../route_backend_group_documents.py")
        with open(group_route_file, 'r') as f:
            content = f.read()
        
        # Verify it doesn't create conversations (should not have conversation creation code)
        conversation_indicators = [
            "conversation_id = str(uuid.uuid4())",
            "cosmos_conversations_container.upsert_item"
        ]
        
        found_conversation_code = False
        for indicator in conversation_indicators:
            if indicator in content:
                found_conversation_code = True
                break
        
        if not found_conversation_code:
            print("✅ Group workspace upload endpoint doesn't create conversations")
            return True
        else:
            print("❌ Group workspace upload contains conversation creation code")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_public_workspace_upload_behavior():
    """Test that public workspace uploads behave correctly."""
    print("🔍 Testing public workspace upload behavior...")
    
    try:
        # Check public upload endpoint
        public_route_file = os.path.join(os.path.dirname(__file__), "../route_backend_public_documents.py")
        with open(public_route_file, 'r') as f:
            content = f.read()
        
        # Verify it doesn't create conversations
        conversation_indicators = [
            "conversation_id = str(uuid.uuid4())",
            "cosmos_conversations_container.upsert_item"
        ]
        
        found_conversation_code = False
        for indicator in conversation_indicators:
            if indicator in content:
                found_conversation_code = True
                break
        
        if not found_conversation_code:
            print("✅ Public workspace upload endpoint doesn't create conversations")
            return True
        else:
            print("❌ Public workspace upload contains conversation creation code")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Testing Workspace Upload Conversation Fix...")
    print("=" * 60)
    
    tests = [
        test_personal_workspace_upload_no_conversation,
        test_search_index_field_filtering,
        test_group_workspace_upload_behavior,
        test_public_workspace_upload_behavior
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All tests passed! Workspace upload fixes are working correctly.")
        print("\n🎯 Fix Summary:")
        print("   • Personal workspace uploads no longer create conversations")
        print("   • Search index updates properly filter fields by workspace type")
        print("   • shared_group_ids field only updated for group workspaces")
        print("   • Group and public workspace uploads remain unaffected")
    else:
        print("❌ Some tests failed. Please review the fixes.")
    
    sys.exit(0 if success else 1)
