#!/usr/bin/env python3
"""
Functional test for public workspace statistics and status management.
Version: 0.234.112
Implemented in: 0.234.112

This test ensures that public workspace statistics (last activity, recent activity count, 
document metrics) and status management (active, locked, upload_disabled, inactive) work 
correctly and match the group workspace functionality.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add parent directory to path to import from application
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))
sys.path.insert(0, parent_dir)

from config import *
from functions_public_workspaces import (
    create_public_workspace,
    find_public_workspace_by_id,
    check_public_workspace_status_allows_operation
)
from functions_documents import create_document, update_document
from route_backend_control_center import enhance_public_workspace_with_activity
from datetime import datetime, timedelta, timezone


def test_status_validation():
    """Test status validation function for public workspaces"""
    print("\n🧪 Test 1: Status Validation Function")
    print("=" * 60)
    
    # Create test workspace
    test_ws_name = f"Test Workspace Status {uuid.uuid4()}"
    
    try:
        # Create workspace
        ws = create_public_workspace(
            name=test_ws_name,
            description="Test workspace for status validation"
        )
        ws_id = ws['id']
        print(f"✅ Created test workspace: {ws_id}")
        
        # Test 1: Active status allows all operations
        print("\n📋 Test 1.1: Active status (default)")
        allowed, reason = check_public_workspace_status_allows_operation(ws, 'upload')
        assert allowed == True, f"Active workspace should allow uploads, got: {reason}"
        print("✅ Upload allowed for active workspace")
        
        allowed, reason = check_public_workspace_status_allows_operation(ws, 'delete')
        assert allowed == True, f"Active workspace should allow deletes"
        print("✅ Delete allowed for active workspace")
        
        allowed, reason = check_public_workspace_status_allows_operation(ws, 'chat')
        assert allowed == True, f"Active workspace should allow chat"
        print("✅ Chat allowed for active workspace")
        
        # Test 2: Locked status blocks uploads and deletes
        print("\n📋 Test 1.2: Locked status")
        ws['status'] = 'locked'
        
        allowed, reason = check_public_workspace_status_allows_operation(ws, 'upload')
        assert allowed == False, "Locked workspace should not allow uploads"
        assert 'locked' in reason.lower(), f"Error message should mention locked status: {reason}"
        print(f"✅ Upload blocked for locked workspace: {reason}")
        
        allowed, reason = check_public_workspace_status_allows_operation(ws, 'delete')
        assert allowed == False, "Locked workspace should not allow deletes"
        print(f"✅ Delete blocked for locked workspace: {reason}")
        
        allowed, reason = check_public_workspace_status_allows_operation(ws, 'chat')
        assert allowed == True, "Locked workspace should still allow chat"
        print("✅ Chat allowed for locked workspace")
        
        # Test 3: Upload disabled status
        print("\n📋 Test 1.3: Upload disabled status")
        ws['status'] = 'upload_disabled'
        
        allowed, reason = check_public_workspace_status_allows_operation(ws, 'upload')
        assert allowed == False, "Upload disabled workspace should not allow uploads"
        print(f"✅ Upload blocked: {reason}")
        
        allowed, reason = check_public_workspace_status_allows_operation(ws, 'delete')
        assert allowed == True, "Upload disabled workspace should still allow deletes"
        print("✅ Delete allowed for upload_disabled workspace")
        
        # Test 4: Inactive status blocks everything
        print("\n📋 Test 1.4: Inactive status")
        ws['status'] = 'inactive'
        
        allowed, reason = check_public_workspace_status_allows_operation(ws, 'upload')
        assert allowed == False, "Inactive workspace should not allow uploads"
        print(f"✅ Upload blocked: {reason}")
        
        allowed, reason = check_public_workspace_status_allows_operation(ws, 'chat')
        assert allowed == False, "Inactive workspace should not allow chat"
        print(f"✅ Chat blocked: {reason}")
        
        # Cleanup
        cosmos_public_workspaces_container.delete_item(item=ws_id, partition_key=ws_id)
        print(f"\n🧹 Cleaned up test workspace: {ws_id}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_activity_calculations():
    """Test last activity and recent activity calculations"""
    print("\n🧪 Test 2: Activity Calculations")
    print("=" * 60)
    
    test_ws_name = f"Test Workspace Activity {uuid.uuid4()}"
    
    try:
        # Create workspace
        ws = create_public_workspace(
            name=test_ws_name,
            description="Test workspace for activity calculations"
        )
        ws_id = ws['id']
        print(f"✅ Created test workspace: {ws_id}")
        
        # Create test documents with different dates
        print("\n📄 Creating test documents...")
        
        # Document 1: 10 days ago
        doc1_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime('%Y-%m-%d')
        create_document(
            file_name="test_old_doc.pdf",
            public_workspace_id=ws_id,
            user_id="test-user-123",
            document_id=str(uuid.uuid4()),
            num_file_chunks=0,
            status='Completed',
            upload_date=doc1_date,
            number_of_pages=5
        )
        print(f"  ✅ Created document from 10 days ago")
        
        # Document 2: 3 days ago (recent)
        doc2_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime('%Y-%m-%d')
        create_document(
            file_name="test_recent_doc.pdf",
            public_workspace_id=ws_id,
            user_id="test-user-123",
            document_id=str(uuid.uuid4()),
            num_file_chunks=0,
            status='Completed',
            upload_date=doc2_date,
            number_of_pages=3
        )
        print(f"  ✅ Created document from 3 days ago")
        
        # Document 3: Today (recent)
        doc3_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        create_document(
            file_name="test_today_doc.pdf",
            public_workspace_id=ws_id,
            user_id="test-user-123",
            document_id=str(uuid.uuid4()),
            num_file_chunks=0,
            status='Completed',
            upload_date=doc3_date,
            number_of_pages=2
        )
        print(f"  ✅ Created document from today")
        
        # Enhance workspace to calculate activity
        print("\n📊 Calculating activity metrics...")
        enhanced = enhance_public_workspace_with_activity(ws, force_refresh=True)
        
        # Verify document count
        assert enhanced['document_count'] == 3, f"Expected 3 documents, got {enhanced['document_count']}"
        print(f"✅ Document count correct: {enhanced['document_count']}")
        
        # Verify last activity exists
        last_activity = enhanced.get('last_activity')
        assert last_activity is not None, "Last activity should be calculated"
        print(f"✅ Last activity calculated: {last_activity}")
        
        # Verify recent activity count (should be 2: 3 days ago and today)
        recent_count = enhanced.get('recent_activity_count', 0)
        assert recent_count == 2, f"Expected 2 recent documents (last 7 days), got {recent_count}"
        print(f"✅ Recent activity count correct: {recent_count} documents in last 7 days")
        
        # Verify AI search size calculation (10 pages total * 80KB)
        ai_search_size = enhanced['activity']['document_metrics']['ai_search_size']
        expected_size = 10 * 80 * 1024  # 10 pages * 80KB per page
        assert ai_search_size == expected_size, f"Expected {expected_size}, got {ai_search_size}"
        print(f"✅ AI search size correct: {ai_search_size} bytes")
        
        # Verify status reading with default
        status = enhanced.get('status')
        assert status == 'active', f"Expected default status 'active', got {status}"
        print(f"✅ Status defaults to 'active': {status}")
        
        # Test caching
        print("\n🗄️ Testing metrics caching...")
        cached_ws = cosmos_public_workspaces_container.read_item(item=ws_id, partition_key=ws_id)
        assert 'metrics' in cached_ws, "Metrics should be cached in workspace document"
        assert 'calculated_at' in cached_ws['metrics'], "Cache should have timestamp"
        assert 'last_activity' in cached_ws['metrics'], "Cache should include last_activity"
        assert 'recent_activity_count' in cached_ws['metrics'], "Cache should include recent_activity_count"
        print(f"✅ Metrics cached successfully with timestamp: {cached_ws['metrics']['calculated_at']}")
        
        # Test cache usage (force_refresh=False)
        print("\n🔄 Testing cache usage...")
        enhanced_cached = enhance_public_workspace_with_activity(cached_ws, force_refresh=False)
        assert enhanced_cached['last_activity'] == enhanced['last_activity'], "Cached last_activity should match"
        assert enhanced_cached['recent_activity_count'] == enhanced['recent_activity_count'], "Cached recent_activity_count should match"
        print("✅ Cached metrics used correctly")
        
        # Cleanup
        print("\n🧹 Cleaning up test data...")
        # Delete documents
        doc_query = "SELECT c.id FROM c WHERE c.public_workspace_id = @ws_id"
        doc_params = [{"name": "@ws_id", "value": ws_id}]
        docs = list(cosmos_public_documents_container.query_items(
            query=doc_query,
            parameters=doc_params,
            enable_cross_partition_query=True
        ))
        for doc in docs:
            cosmos_public_documents_container.delete_item(item=doc['id'], partition_key=ws_id)
        print(f"  ✅ Deleted {len(docs)} test documents")
        
        # Delete workspace
        cosmos_public_workspaces_container.delete_item(item=ws_id, partition_key=ws_id)
        print(f"  ✅ Deleted test workspace: {ws_id}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_status_management():
    """Test status management endpoint functionality"""
    print("\n🧪 Test 3: Status Management")
    print("=" * 60)
    
    test_ws_name = f"Test Workspace Status Mgmt {uuid.uuid4()}"
    
    try:
        # Create workspace
        ws = create_public_workspace(
            name=test_ws_name,
            description="Test workspace for status management"
        )
        ws_id = ws['id']
        print(f"✅ Created test workspace: {ws_id}")
        
        # Test status field initialization
        print("\n📋 Testing graceful status field handling...")
        enhanced = enhance_public_workspace_with_activity(ws, force_refresh=False)
        assert enhanced['status'] == 'active', "Status should default to 'active' when missing"
        assert enhanced['statusHistory'] == [], "Status history should default to empty array when missing"
        print("✅ Missing fields handled gracefully with defaults")
        
        # Update status to locked
        print("\n🔒 Testing status change to 'locked'...")
        ws['status'] = 'locked'
        ws['statusHistory'] = [{
            'old_status': 'active',
            'new_status': 'locked',
            'changed_by_user_id': 'test-admin',
            'changed_by_email': 'admin@test.com',
            'changed_at': datetime.utcnow().isoformat(),
            'reason': 'Testing status change'
        }]
        cosmos_public_workspaces_container.upsert_item(ws)
        print("✅ Status updated to 'locked'")
        
        # Verify status is read correctly
        updated_ws = cosmos_public_workspaces_container.read_item(item=ws_id, partition_key=ws_id)
        enhanced = enhance_public_workspace_with_activity(updated_ws, force_refresh=False)
        assert enhanced['status'] == 'locked', f"Expected 'locked', got {enhanced['status']}"
        assert len(enhanced['statusHistory']) == 1, "Status history should have 1 entry"
        print(f"✅ Status read correctly: {enhanced['status']}")
        print(f"✅ Status history tracked: {len(enhanced['statusHistory'])} entries")
        
        # Cleanup
        cosmos_public_workspaces_container.delete_item(item=ws_id, partition_key=ws_id)
        print(f"\n🧹 Cleaned up test workspace: {ws_id}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all functional tests"""
    print("\n" + "=" * 60)
    print("🚀 PUBLIC WORKSPACE STATISTICS FUNCTIONAL TEST")
    print("=" * 60)
    print(f"Version: 0.234.112")
    print(f"Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("Status Validation", test_status_validation()))
    results.append(("Activity Calculations", test_activity_calculations()))
    results.append(("Status Management", test_status_management()))
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    
    return all(result for _, result in results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
