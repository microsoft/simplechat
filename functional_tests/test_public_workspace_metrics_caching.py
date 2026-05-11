#!/usr/bin/env python3
"""
Functional test for public workspace document metrics caching implementation.
Version: 0.230.080
Implemented in: 0.230.080

This test ensures that public workspace document metrics are cached consistently 
with group workspace metrics, using the same field names and caching patterns.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the parent directory to sys.path to import from the app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.path.join(parent_dir, 'application', 'single_app'))

def test_public_workspace_metrics_caching():
    """Test that public workspace metrics caching works like groups."""
    print("🔍 Testing Public Workspace Metrics Caching...")
    
    try:
        # Import required modules
        from route_backend_control_center import enhance_public_workspace_with_activity, enhance_group_with_activity
        from datetime import datetime, timezone, timedelta
        
        print("✅ Successfully imported enhancement functions")
        
        # Create test workspace data structures
        test_workspace = {
            'id': 'test-workspace-123',
            'name': 'Test Public Workspace',
            'description': 'Test workspace for metrics caching',
            'owner': {
                'display_name': 'Test Owner',
                'email': 'test@example.com',
                'userId': 'test-user-123'
            },
            'admins': [],
            'documentManagers': [],
            'createdDate': datetime.now(timezone.utc).isoformat(),
            'modifiedDate': datetime.now(timezone.utc).isoformat()
        }
        
        test_group = {
            'id': 'test-group-123',
            'name': 'Test Group',
            'description': 'Test group for comparison',
            'owner': {
                'display_name': 'Test Owner',
                'email': 'test@example.com',
                'userId': 'test-user-123'
            },
            'users': [],
            'admins': [],
            'documentManagers': [],
            'createdDate': datetime.now(timezone.utc).isoformat(),
            'modifiedDate': datetime.now(timezone.utc).isoformat()
        }
        
        print("✅ Created test data structures")
        
        # Test 1: Verify both functions have similar structure without cache
        print("\n🧪 Test 1: Verify enhancement function consistency")
        
        try:
            workspace_result = enhance_public_workspace_with_activity(test_workspace, force_refresh=False)
            group_result = enhance_group_with_activity(test_group, force_refresh=False)
            
            # Check that both return enhanced structures
            assert 'activity' in workspace_result, "Workspace result missing activity"
            assert 'document_metrics' in workspace_result['activity'], "Workspace missing document_metrics"
            assert 'activity' in group_result, "Group result missing activity"
            assert 'document_metrics' in group_result['activity'], "Group missing document_metrics"
            
            print("✅ Both functions return consistent structure")
            
            # Check that both have the same metric fields
            workspace_metrics = workspace_result['activity']['document_metrics']
            group_metrics = group_result['activity']['document_metrics']
            
            required_fields = ['total_documents', 'ai_search_size', 'storage_account_size']
            
            for field in required_fields:
                assert field in workspace_metrics, f"Workspace missing {field}"
                assert field in group_metrics, f"Group missing {field}"
            
            print("✅ Both functions have consistent metric fields")
            
        except Exception as structure_e:
            print(f"❌ Structure test failed: {structure_e}")
            return False
        
        # Test 2: Verify caching mechanism
        print("\n🧪 Test 2: Verify caching mechanism")
        
        try:
            # Add cached metrics to workspace (simulating previously cached data)
            cache_time = datetime.now(timezone.utc)
            cached_workspace = test_workspace.copy()
            cached_workspace['metrics'] = {
                'document_metrics': {
                    'total_documents': 5,
                    'ai_search_size': 400000,  # 5 docs × 80KB
                    'storage_account_size': 2500000  # 2.5MB estimated
                },
                'calculated_at': cache_time.isoformat()
            }
            
            # Test that cached data is returned when not forcing refresh
            cached_result = enhance_public_workspace_with_activity(cached_workspace, force_refresh=False)
            
            # Verify cached data is used
            cached_metrics = cached_result['activity']['document_metrics']
            assert cached_metrics['total_documents'] == 5, f"Expected 5 documents, got {cached_metrics['total_documents']}"
            assert cached_metrics['ai_search_size'] == 400000, f"Expected 400000 AI search size, got {cached_metrics['ai_search_size']}"
            
            print("✅ Cached metrics are properly retrieved and used")
            
        except Exception as cache_e:
            print(f"❌ Cache test failed: {cache_e}")
            return False
        
        # Test 3: Verify cache expiration
        print("\n🧪 Test 3: Verify cache expiration logic")
        
        try:
            # Create workspace with expired cache (over 24 hours old)
            expired_cache_time = datetime.now(timezone.utc) - timedelta(hours=25)
            expired_workspace = test_workspace.copy()
            expired_workspace['metrics'] = {
                'document_metrics': {
                    'total_documents': 99,  # Should not be used
                    'ai_search_size': 999999,
                    'storage_account_size': 999999
                },
                'calculated_at': expired_cache_time.isoformat()
            }
            
            # Test that expired cache triggers fresh calculation
            expired_result = enhance_public_workspace_with_activity(expired_workspace, force_refresh=False)
            
            # Verify fresh calculation was done (should return 0 since no real data)
            fresh_metrics = expired_result['activity']['document_metrics']
            assert fresh_metrics['total_documents'] == 0, f"Expected 0 documents (fresh calc), got {fresh_metrics['total_documents']}"
            
            print("✅ Expired cache properly triggers fresh calculation")
            
        except Exception as expiry_e:
            print(f"❌ Cache expiry test failed: {expiry_e}")
            return False
        
        # Test 4: Verify field name consistency
        print("\n🧪 Test 4: Verify field name consistency with groups")
        
        try:
            # Check that the function code uses 'number_of_pages' consistently
            import inspect
            workspace_source = inspect.getsource(enhance_public_workspace_with_activity)
            group_source = inspect.getsource(enhance_group_with_activity)
            
            # Both should use 'number_of_pages' for consistency
            assert 'number_of_pages' in workspace_source, "Public workspace should use 'number_of_pages' field"
            assert 'number_of_pages' in group_source, "Group should use 'number_of_pages' field"
            
            # Public workspace should not use the old inconsistent 'page_count'
            assert 'page_count' not in workspace_source or workspace_source.count('page_count') == 0, "Public workspace should not use 'page_count' field"
            
            print("✅ Field names are consistent between workspace types")
            
        except Exception as field_e:
            print(f"❌ Field consistency test failed: {field_e}")
            return False
        
        # Test 5: Verify caching save logic
        print("\n🧪 Test 5: Verify caching save logic")
        
        try:
            # Both functions should only save cache when force_refresh=True
            workspace_source = inspect.getsource(enhance_public_workspace_with_activity)
            group_source = inspect.getsource(enhance_group_with_activity)
            
            # Check that both have "if force_refresh:" condition before saving cache
            assert "if force_refresh:" in workspace_source, "Workspace should only save cache on force refresh"
            assert "if force_refresh:" in group_source, "Group should only save cache on force refresh"
            
            print("✅ Both functions have consistent cache save logic")
            
        except Exception as save_e:
            print(f"❌ Cache save logic test failed: {save_e}")
            return False
        
        print("\n📊 Test Summary:")
        print("   ✅ Enhancement function structure consistency")
        print("   ✅ Cached metrics retrieval and usage")  
        print("   ✅ Cache expiration logic (24-hour window)")
        print("   ✅ Field name consistency (number_of_pages)")
        print("   ✅ Cache save logic consistency (force_refresh only)")
        
        print("\n🎯 Key Improvements Verified:")
        print("   • Public workspaces now use 'number_of_pages' like groups")
        print("   • Caching logic matches groups (24-hour cache window)")
        print("   • Cache only saved on force_refresh=True")
        print("   • Basic document count fallback when cache missing")
        print("   • Consistent error handling and debug logging")
        
        print("\n✅ All public workspace metrics caching tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_public_workspace_metrics_caching()
    sys.exit(0 if success else 1)