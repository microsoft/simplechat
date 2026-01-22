#!/usr/bin/env python3
"""
Functional test for group member deletion activity logging.
Version: 0.234.025
Implemented in: 0.234.025

This test ensures that group member removals are properly logged
to the activity_logs container with activity_type 'group_member_deleted'.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'application', 'single_app'))

def test_group_member_deleted_logging():
    """Test that group member deletions are properly logged to activity_logs."""
    print("🔍 Testing Group Member Deleted Activity Logging...")
    
    try:
        from config import cosmos_activity_logs_container
        from functions_activity_logging import log_group_member_deleted
        import uuid
        
        # Test setup
        test_admin_id = f"test-admin-{uuid.uuid4()}"
        test_member_id = f"test-member-{uuid.uuid4()}"
        test_group_id = f"test-group-{uuid.uuid4()}"
        
        print(f"\n✓ Test admin: {test_admin_id}")
        print(f"✓ Test member: {test_member_id}")
        print(f"✓ Test group: {test_group_id}")
        
        # Test 1: Log admin removing a member
        print("\n📝 Test 1: Admin removes member from group...")
        
        log_group_member_deleted(
            removed_by_user_id=test_admin_id,
            removed_by_email="admin@test.com",
            removed_by_role="Admin",
            member_user_id=test_member_id,
            member_email="member@test.com",
            member_name="Test Member",
            group_id=test_group_id,
            group_name="Test Group",
            action="admin_removed_member",
            description="Admin removed member from group"
        )
        
        # Query activity_logs to verify the log was created
        query = """
            SELECT * FROM c
            WHERE c.user_id = @user_id
            AND c.activity_type = 'group_member_deleted'
            AND c.group.group_id = @group_id
            ORDER BY c.timestamp DESC
        """
        parameters = [
            {"name": "@user_id", "value": test_admin_id},
            {"name": "@group_id", "value": test_group_id}
        ]
        
        activity_logs = list(cosmos_activity_logs_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if not activity_logs:
            print("❌ No activity log found for member deletion by admin")
            return False
            
        log_entry = activity_logs[0]
        print(f"✓ Activity log created with ID: {log_entry['id']}")
        
        # Verify log structure
        assert log_entry['activity_type'] == 'group_member_deleted', "Activity type mismatch"
        assert log_entry['action'] == 'admin_removed_member', "Action mismatch"
        assert log_entry['user_id'] == test_admin_id, "User ID mismatch"
        print("✓ Activity type and action verified")
        
        # Verify removed_by information
        assert 'removed_by' in log_entry, "removed_by missing"
        assert log_entry['removed_by']['user_id'] == test_admin_id, "Removed by user ID mismatch"
        assert log_entry['removed_by']['email'] == "admin@test.com", "Removed by email mismatch"
        assert log_entry['removed_by']['role'] == "Admin", "Removed by role mismatch"
        print("✓ Removed by information verified")
        
        # Verify removed_member information
        assert 'removed_member' in log_entry, "removed_member missing"
        assert log_entry['removed_member']['user_id'] == test_member_id, "Removed member user ID mismatch"
        assert log_entry['removed_member']['email'] == "member@test.com", "Removed member email mismatch"
        assert log_entry['removed_member']['name'] == "Test Member", "Removed member name mismatch"
        print("✓ Removed member information verified")
        
        # Verify group information
        assert 'group' in log_entry, "group missing"
        assert log_entry['group']['group_id'] == test_group_id, "Group ID mismatch"
        assert log_entry['group']['group_name'] == "Test Group", "Group name mismatch"
        print("✓ Group information verified")
        
        # Verify timestamp fields
        assert 'timestamp' in log_entry, "Timestamp missing"
        assert 'created_at' in log_entry, "Created_at missing"
        assert 'description' in log_entry, "Description missing"
        print("✓ Timestamp and description fields verified")
        
        print("✅ Test 1 passed: Admin removal logging works correctly!")
        
        # Test 2: Log member leaving group (self-removal)
        print("\n📝 Test 2: Member leaves group (self-removal)...")
        
        test_leaving_member_id = f"test-leaving-{uuid.uuid4()}"
        
        log_group_member_deleted(
            removed_by_user_id=test_leaving_member_id,
            removed_by_email="leaving@test.com",
            removed_by_role="Member",
            member_user_id=test_leaving_member_id,
            member_email="leaving@test.com",
            member_name="Leaving Member",
            group_id=test_group_id,
            group_name="Test Group",
            action="member_left_group",
            description="Member left the group voluntarily"
        )
        
        # Query for self-removal log
        query = """
            SELECT * FROM c
            WHERE c.user_id = @user_id
            AND c.activity_type = 'group_member_deleted'
            AND c.action = 'member_left_group'
            ORDER BY c.timestamp DESC
        """
        parameters = [{"name": "@user_id", "value": test_leaving_member_id}]
        
        self_removal_logs = list(cosmos_activity_logs_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if not self_removal_logs:
            print("❌ No activity log found for self-removal")
            return False
            
        self_log = self_removal_logs[0]
        assert self_log['action'] == 'member_left_group', "Self-removal action mismatch"
        assert self_log['removed_by']['user_id'] == test_leaving_member_id, "Self-removal user mismatch"
        assert self_log['removed_member']['user_id'] == test_leaving_member_id, "Self-removal member mismatch"
        assert self_log['removed_by']['role'] == 'Member', "Self-removal role should be Member"
        print("✓ Self-removal logged correctly")
        print("✅ Test 2 passed: Self-removal logging works!")
        
        # Test 3: Log owner removing a member
        print("\n📝 Test 3: Owner removes member from group...")
        
        test_owner_id = f"test-owner-{uuid.uuid4()}"
        test_removed_member_id = f"test-removed-{uuid.uuid4()}"
        
        log_group_member_deleted(
            removed_by_user_id=test_owner_id,
            removed_by_email="owner@test.com",
            removed_by_role="Owner",
            member_user_id=test_removed_member_id,
            member_email="removed@test.com",
            member_name="Removed Member",
            group_id=test_group_id,
            group_name="Test Group",
            action="admin_removed_member",
            description="Owner removed member from group"
        )
        
        # Query for owner removal log
        query = """
            SELECT * FROM c
            WHERE c.user_id = @user_id
            AND c.activity_type = 'group_member_deleted'
            AND c.removed_by.role = 'Owner'
            ORDER BY c.timestamp DESC
        """
        parameters = [{"name": "@user_id", "value": test_owner_id}]
        
        owner_logs = list(cosmos_activity_logs_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if not owner_logs:
            print("❌ No activity log found for owner removal")
            return False
            
        owner_log = owner_logs[0]
        assert owner_log['removed_by']['role'] == 'Owner', "Owner role mismatch"
        assert owner_log['removed_by']['user_id'] == test_owner_id, "Owner user ID mismatch"
        print("✓ Owner removal logged correctly")
        print("✅ Test 3 passed: Owner removal logging works!")
        
        # Test 4: Query all member deletions for a group
        print("\n📝 Test 4: Query all member deletions for a group...")
        
        query = """
            SELECT * FROM c
            WHERE c.activity_type = 'group_member_deleted'
            AND c.group.group_id = @group_id
            ORDER BY c.timestamp DESC
        """
        parameters = [{"name": "@group_id", "value": test_group_id}]
        
        all_group_deletions = list(cosmos_activity_logs_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        # We should have at least 3 deletions for this group (admin, self, owner)
        if len(all_group_deletions) < 3:
            print(f"❌ Expected at least 3 deletions for group, found {len(all_group_deletions)}")
            return False
            
        print(f"✓ Found {len(all_group_deletions)} member deletions for the test group")
        print("✅ Test 4 passed: Group-level deletion queries work!")
        
        # Cleanup - delete all activity logs
        print("\n🧹 Cleaning up test data...")
        all_test_logs = activity_logs + self_removal_logs + owner_logs
        for log in all_test_logs:
            try:
                cosmos_activity_logs_container.delete_item(
                    item=log['id'],
                    partition_key=log['user_id']
                )
            except:
                pass
        print("✓ Activity logs cleaned up")
        
        print("\n✅ All tests passed! Group member deletion activity logging is working correctly.")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_group_member_deleted_logging()
    sys.exit(0 if success else 1)
