#!/usr/bin/env python3
"""
Functional test for document metadata update activity logging.
Version: 0.234.024
Implemented in: 0.234.024

This test ensures that document metadata updates are properly logged
to the activity_logs container for tracking and analytics purposes.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'application', 'single_app'))

def test_metadata_update_logging():
    """Test that document metadata updates are properly logged to activity_logs."""
    print("🔍 Testing Document Metadata Update Activity Logging...")
    
    try:
        from config import cosmos_activity_logs_container, cosmos_user_documents_container
        from functions_activity_logging import log_document_metadata_update_transaction
        import uuid
        from datetime import datetime
        
        # Test setup - create a test document first
        test_user_id = f"test-user-{uuid.uuid4()}"
        test_document_id = f"test-doc-{uuid.uuid4()}"
        
        print(f"\n✓ Test user: {test_user_id}")
        print(f"✓ Test document: {test_document_id}")
        
        # Create a test document in the user documents container
        test_document = {
            'id': test_document_id,
            'user_id': test_user_id,
            'file_name': 'test_document.pdf',
            'file_type': '.pdf',
            'title': 'Original Title',
            'abstract': 'Original Abstract',
            'authors': ['Original Author'],
            'keywords': ['original', 'keyword'],
            'publication_date': '2024-01-01',
            'document_classification': 'Public',
            'created_at': datetime.utcnow().isoformat(),
            'last_updated': datetime.utcnow().isoformat(),
            'status': 'completed',
            'percentage_complete': 100
        }
        
        cosmos_user_documents_container.create_item(body=test_document)
        print("✓ Test document created")
        
        # Test 1: Log a metadata update with multiple fields
        print("\n📝 Test 1: Logging metadata update with multiple fields...")
        updated_fields = {
            'title': 'Updated Title',
            'abstract': 'Updated Abstract',
            'keywords': ['updated', 'keywords', 'test'],
            'authors': ['New Author', 'Second Author']
        }
        
        log_document_metadata_update_transaction(
            user_id=test_user_id,
            document_id=test_document_id,
            workspace_type='personal',
            file_name='test_document.pdf',
            updated_fields=updated_fields,
            file_type='.pdf'
        )
        
        # Query activity_logs to verify the log was created
        query = """
            SELECT * FROM c
            WHERE c.user_id = @user_id
            AND c.document_id = @document_id
            AND c.activity_type = 'document_metadata_update'
            ORDER BY c.timestamp DESC
        """
        parameters = [
            {"name": "@user_id", "value": test_user_id},
            {"name": "@document_id", "value": test_document_id}
        ]
        
        activity_logs = list(cosmos_activity_logs_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if not activity_logs:
            print("❌ No activity log found for metadata update")
            return False
            
        log_entry = activity_logs[0]
        print(f"✓ Activity log created with ID: {log_entry['id']}")
        
        # Verify log structure
        assert log_entry['activity_type'] == 'document_metadata_update', "Activity type mismatch"
        assert log_entry['workspace_type'] == 'personal', "Workspace type mismatch"
        assert log_entry['user_id'] == test_user_id, "User ID mismatch"
        print("✓ Activity type and workspace verified")
        
        # Verify document information
        assert log_entry['document']['document_id'] == test_document_id, "Document ID mismatch"
        assert log_entry['document']['file_name'] == 'test_document.pdf', "File name mismatch"
        assert log_entry['document']['file_type'] == '.pdf', "File type mismatch"
        print("✓ Document information verified")
        
        # Verify updated fields
        assert 'updated_fields' in log_entry, "Updated fields missing"
        assert log_entry['updated_fields']['title'] == 'Updated Title', "Title update not logged"
        assert log_entry['updated_fields']['abstract'] == 'Updated Abstract', "Abstract update not logged"
        assert log_entry['updated_fields']['keywords'] == ['updated', 'keywords', 'test'], "Keywords update not logged"
        assert log_entry['updated_fields']['authors'] == ['New Author', 'Second Author'], "Authors update not logged"
        print("✓ All updated fields verified")
        
        # Verify timestamp fields
        assert 'timestamp' in log_entry, "Timestamp missing"
        assert 'created_at' in log_entry, "Created_at missing"
        print("✓ Timestamp fields verified")
        
        print("✅ Test 1 passed: Metadata update logging works correctly!")
        
        # Test 2: Log metadata update for group workspace
        print("\n📝 Test 2: Logging metadata update for group workspace...")
        test_group_id = f"test-group-{uuid.uuid4()}"
        
        group_updated_fields = {
            'title': 'Group Document Updated',
            'document_classification': 'Internal'
        }
        
        log_document_metadata_update_transaction(
            user_id=test_user_id,
            document_id=test_document_id,
            workspace_type='group',
            file_name='group_document.pdf',
            updated_fields=group_updated_fields,
            file_type='.pdf',
            group_id=test_group_id
        )
        
        # Query for group workspace log
        query = """
            SELECT * FROM c
            WHERE c.user_id = @user_id
            AND c.workspace_type = 'group'
            AND c.activity_type = 'document_metadata_update'
            ORDER BY c.timestamp DESC
        """
        parameters = [{"name": "@user_id", "value": test_user_id}]
        
        group_logs = list(cosmos_activity_logs_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if not group_logs:
            print("❌ No activity log found for group metadata update")
            return False
            
        group_log = group_logs[0]
        assert group_log['workspace_type'] == 'group', "Group workspace type mismatch"
        assert group_log['workspace_context'].get('group_id') == test_group_id, "Group ID not logged"
        print("✓ Group workspace metadata update logged correctly")
        print("✅ Test 2 passed: Group workspace logging works!")
        
        # Test 3: Log metadata update for public workspace
        print("\n📝 Test 3: Logging metadata update for public workspace...")
        test_public_ws_id = f"test-public-{uuid.uuid4()}"
        
        public_updated_fields = {
            'abstract': 'Public Document Abstract Updated',
            'publication_date': '2024-12-20'
        }
        
        log_document_metadata_update_transaction(
            user_id=test_user_id,
            document_id=test_document_id,
            workspace_type='public',
            file_name='public_document.pdf',
            updated_fields=public_updated_fields,
            file_type='.pdf',
            public_workspace_id=test_public_ws_id
        )
        
        # Query for public workspace log
        query = """
            SELECT * FROM c
            WHERE c.user_id = @user_id
            AND c.workspace_type = 'public'
            AND c.activity_type = 'document_metadata_update'
            ORDER BY c.timestamp DESC
        """
        parameters = [{"name": "@user_id", "value": test_user_id}]
        
        public_logs = list(cosmos_activity_logs_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if not public_logs:
            print("❌ No activity log found for public workspace metadata update")
            return False
            
        public_log = public_logs[0]
        assert public_log['workspace_type'] == 'public', "Public workspace type mismatch"
        assert public_log['workspace_context'].get('public_workspace_id') == test_public_ws_id, "Public workspace ID not logged"
        print("✓ Public workspace metadata update logged correctly")
        print("✅ Test 3 passed: Public workspace logging works!")
        
        # Cleanup - delete test document and activity logs
        print("\n🧹 Cleaning up test data...")
        try:
            cosmos_user_documents_container.delete_item(
                item=test_document_id,
                partition_key=test_user_id
            )
            print("✓ Test document deleted")
        except:
            print("⚠️  Test document already deleted or not found")
        
        # Delete all activity logs for test user
        for log in activity_logs + group_logs + public_logs:
            try:
                cosmos_activity_logs_container.delete_item(
                    item=log['id'],
                    partition_key=log['user_id']
                )
            except:
                pass
        print("✓ Activity logs cleaned up")
        
        print("\n✅ All tests passed! Document metadata update activity logging is working correctly.")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_metadata_update_logging()
    sys.exit(0 if success else 1)
