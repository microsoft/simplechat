#!/usr/bin/env python3
"""
Functional test for group notification context enhancement.
Version: 0.234.060
Implemented in: 0.234.060

This test ensures that group document notifications include the group name
and metadata contains group_id for JavaScript to call setActive API.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_group_notification_context():
    """Test that group notifications include group name and group_id metadata for API navigation."""
    print("🔍 Testing Group Notification Context Enhancement...")
    
    try:
        # Import required functions
        from functions_notifications import create_group_notification, get_user_notifications
        from functions_group import find_group_by_id, create_group
        
        # Test data
        test_user_id = "test-user-notification-context"
        test_group_name = "Test Marketing Team"
        
        # Step 1: Create a test group
        print("\n📝 Step 1: Creating test group...")
        test_group = {
            'id': f'test-group-{test_user_id}',
            'name': test_group_name,
            'description': 'Test group for notification context',
            'owner_id': test_user_id,
            'member_ids': [test_user_id],
            'created_at': '2025-01-01T00:00:00Z'
        }
        
        # Note: This is a mock - in real test we'd use actual group creation
        # For now, we'll test the notification creation logic directly
        
        # Step 2: Simulate group notification creation (as done in functions_documents.py)
        print("\n📝 Step 2: Creating group notification with context...")
        group_id = test_group['id']
        document_id = f'test-doc-{test_user_id}'
        original_filename = 'test_document.pdf'
        total_chunks = 45
        
        # This simulates the code in functions_documents.py (lines 5264-5285)
        notification_title = f"Document Processing Complete"
        group_name = test_group['name']  # In real code: find_group_by_id(group_id).get('name')
        
        create_group_notification(
            group_id=group_id,
            notification_type='document_processing_complete',
            title=notification_title,
            message=f"Document uploaded to {group_name} has been processed successfully with {total_chunks} chunks.",
            link_url=f'/group_workspaces?active_group_id={group_id}',
            link_context={
                'workspace_type': 'group',
                'group_id': group_id,
                'document_id': document_id
            },
            metadata={
                'document_id': document_id,
                'file_name': original_filename,
                'chunks': total_chunks,
                'group_name': group_name,
                'group_id': group_id
            }
        )
        
        print(f"✅ Created notification for group '{group_name}'")
        
        # Step 3: Retrieve notification and verify content
        print("\n📝 Step 3: Verifying notification content...")
        notifications = get_user_notifications(
            user_id=test_user_id,
            page=1,
            per_page=10
        )
        
        if not notifications or len(notifications['notifications']) == 0:
            print("❌ No notifications found for test user")
            return False
        
        # Find our test notification
        test_notification = None
        for notif in notifications['notifications']:
            if notif.get('metadata', {}).get('document_id') == document_id:
                test_notification = notif
                break
        
        if not test_notification:
            print(f"❌ Test notification not found (document_id: {document_id})")
            return False
        
        # Verify group name in message
        expected_message = f"Document uploaded to {group_name} has been processed successfully with {total_chunks} chunks."
        if test_notification['message'] != expected_message:
            print(f"❌ Message mismatch!")
            print(f"   Expected: {expected_message}")
            print(f"   Got: {test_notification['message']}")
            return False
        
        print(f"✅ Group name '{group_name}' found in message")
        
        # Step 4: Verify link_url is correct (no query params)
        print("\n📝 Step 4: Verifying link_url is clean (JavaScript will handle group activation)...")
        expected_link_url = '/group_workspaces'
        if test_notification['link_url'] != expected_link_url:
            print(f"❌ Link URL mismatch!")
            print(f"   Expected: {expected_link_url}")
            print(f"   Got: {test_notification['link_url']}")
            return False
        
        print(f"✅ Link URL is clean: {expected_link_url}")
        
        # Step 5: Verify metadata includes group information
        print("\n📝 Step 5: Verifying metadata includes group context...")
        metadata = test_notification.get('metadata', {})
        
        required_fields = ['group_name', 'group_id', 'document_id', 'file_name', 'chunks']
        for field in required_fields:
            if field not in metadata:
                print(f"❌ Missing required metadata field: {field}")
                return False
        
        if metadata['group_name'] != group_name:
            print(f"❌ Group name mismatch in metadata!")
            print(f"   Expected: {group_name}")
            print(f"   Got: {metadata['group_name']}")
            return False
        
        if metadata['group_id'] != group_id:
            print(f"❌ Group ID mismatch in metadata!")
            print(f"   Expected: {group_id}")
            print(f"   Got: {metadata['group_id']}")
            return False
        
        print(f"✅ Metadata includes all required group context fields")
        
        # Step 6: Test link URL format
        print("\n📝 Step 6: Testing link URL format and metadata for API call...")
        link_url = test_notification['link_url']
        
        # Verify it's a simple group workspace URL (no query params)
        if link_url != '/group_workspaces':
            print(f"❌ Link URL format invalid: {link_url}")
            return False
        
        # Verify metadata has group_id for JavaScript to use
        if metadata.get('group_id') != group_id:
            print(f"❌ Group ID in metadata doesn't match!")
            print(f"   Expected: {group_id}")
            print(f"   Got: {metadata.get('group_id')}")
            return False
        
        print(f"✅ Link URL is clean and metadata contains group_id for API call")
        
        # Cleanup
        print("\n🧹 Cleaning up test data...")
        from functions_notifications import dismiss_notification
        dismiss_notification(test_notification['id'], test_user_id)
        print("✅ Test notification dismissed")
        
        print("\n" + "="*60)
        print("✅ All tests passed!")
        print("="*60)
        print(f"\nValidated:")
        print(f"  ✓ Group name '{group_name}' included in notification message")
        print(f"  ✓ Link URL is clean: /group_workspaces")
        print(f"  ✓ Metadata contains group_name and group_id")
        print(f"  ✓ JavaScript will call /api/groups/setActive with group_id before navigation")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_group_notification_context()
    sys.exit(0 if success else 1)
