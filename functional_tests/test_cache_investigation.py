#!/usr/bin/env python3
"""
Test to check cached data and clear cache for the problematic user.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def check_cached_user_metrics():
    """Check if there's cached data for the user that might be showing old values."""
    print("🔍 Checking Cached User Metrics")
    print("=" * 60)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        from app import app
        from config import CONTAINERS
        
        with app.app_context():
            print(f"✅ Flask application context created")
            
            # Check if there's cached user metrics in Cosmos DB
            cosmos_container = CONTAINERS["users"]
            
            # Query for any user metrics or cached data
            user_metrics_query = f"""
            SELECT * FROM c 
            WHERE c.user_id = '{test_user_id}'
            AND c.type = 'user_metrics'
            """
            
            print(f"📊 Querying for cached user metrics...")
            cached_metrics = list(cosmos_container.query_items(
                query=user_metrics_query,
                enable_cross_partition_query=True
            ))
            
            if cached_metrics:
                print(f"📊 Found {len(cached_metrics)} cached metric records:")
                for i, metric in enumerate(cached_metrics):
                    print(f"   Record {i+1}:")
                    print(f"     ID: {metric.get('id', 'N/A')}")
                    print(f"     Created: {metric.get('created_date', 'N/A')}")
                    print(f"     Storage size: {metric.get('storage_account_size', 'N/A')}")
                    print(f"     Enhanced citations: {metric.get('enhanced_citation_enabled', 'N/A')}")
                    
                    # Check if this is showing 0 storage size
                    storage_size = metric.get('storage_account_size', 0)
                    if storage_size == 0:
                        print(f"     ❌ This cached record shows 0 storage size!")
                        return metric
                    else:
                        print(f"     ✅ This cached record shows correct storage size")
            else:
                print(f"📊 No cached user metrics found")
            
            # Also check for any general user cache
            user_cache_query = f"""
            SELECT * FROM c 
            WHERE c.user_id = '{test_user_id}'
            AND (c.type = 'user_cache' OR c.type LIKE '%cache%')
            """
            
            print(f"\n📊 Querying for general user cache...")
            cached_users = list(cosmos_container.query_items(
                query=user_cache_query,
                enable_cross_partition_query=True
            ))
            
            if cached_users:
                print(f"📊 Found {len(cached_users)} cached user records:")
                for i, user_cache in enumerate(cached_users):
                    print(f"   Cache Record {i+1}:")
                    print(f"     ID: {user_cache.get('id', 'N/A')}")
                    print(f"     Type: {user_cache.get('type', 'N/A')}")
                    print(f"     Created: {user_cache.get('created_date', 'N/A')}")
                    if 'activity' in user_cache:
                        activity = user_cache['activity']
                        if 'document_metrics' in activity:
                            doc_metrics = activity['document_metrics']
                            storage_size = doc_metrics.get('storage_account_size', 0)
                            print(f"     Storage size in cache: {storage_size}")
                            if storage_size == 0:
                                print(f"     ❌ Cached user data shows 0 storage size!")
                                return user_cache
            else:
                print(f"📊 No general user cache found")
            
            return None
        
    except Exception as e:
        print(f"❌ Cache check failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def clear_user_cache():
    """Clear any cached data for the problematic user."""
    print(f"\n🧹 Clearing User Cache")
    print("=" * 60)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        from app import app
        from config import CONTAINERS
        
        with app.app_context():
            cosmos_container = CONTAINERS["users"]
            
            # Find all cache records for this user
            cache_query = f"""
            SELECT c.id, c._self FROM c 
            WHERE c.user_id = '{test_user_id}'
            AND (c.type = 'user_metrics' OR c.type = 'user_cache' OR c.type LIKE '%cache%')
            """
            
            cache_records = list(cosmos_container.query_items(
                query=cache_query,
                enable_cross_partition_query=True
            ))
            
            if cache_records:
                print(f"📊 Found {len(cache_records)} cache records to delete")
                
                deleted_count = 0
                for record in cache_records:
                    try:
                        cosmos_container.delete_item(
                            item=record['id'],
                            partition_key=test_user_id
                        )
                        deleted_count += 1
                        print(f"   ✅ Deleted cache record: {record['id']}")
                    except Exception as e:
                        print(f"   ❌ Failed to delete {record['id']}: {e}")
                
                print(f"📊 Successfully deleted {deleted_count} cache records")
                return deleted_count
            else:
                print(f"📊 No cache records found to delete")
                return 0
        
    except Exception as e:
        print(f"❌ Cache clear failed: {e}")
        import traceback
        traceback.print_exc()
        return 0

def test_after_cache_clear():
    """Test the enhance function again after clearing cache."""
    print(f"\n🔄 Testing After Cache Clear")
    print("=" * 60)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        from app import app
        from route_backend_control_center import enhance_user_with_activity
        
        with app.app_context():
            mock_user = {
                'id': test_user_id,
                'name': 'Test User',
                'email': f'{test_user_id}@test.com',
                'settings': {
                    'enable_enhanced_citation': True
                }
            }
            
            print(f"📊 Testing enhance_user_with_activity after cache clear...")
            enhanced_user = enhance_user_with_activity(mock_user, force_refresh=True)
            
            if 'activity' in enhanced_user and 'document_metrics' in enhanced_user['activity']:
                doc_metrics = enhanced_user['activity']['document_metrics']
                storage_size = doc_metrics.get('storage_account_size', 0)
                
                print(f"📊 Storage account size after cache clear: {storage_size:,} bytes")
                
                if storage_size > 0:
                    print(f"✅ Storage size calculated correctly: {storage_size / 1024 / 1024:.2f} MB")
                    return True
                else:
                    print(f"❌ Storage size still 0 after cache clear")
                    return False
            else:
                print(f"❌ No document metrics found")
                return False
        
    except Exception as e:
        print(f"❌ Post-cache-clear test failed: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Starting Cache Investigation")
    print("=" * 60)
    
    # Step 1: Check for cached data
    cached_data = check_cached_user_metrics()
    
    # Step 2: Clear cache if problematic data found
    if cached_data:
        print(f"\n❌ Found problematic cached data - clearing cache...")
        deleted_count = clear_user_cache()
        print(f"🧹 Deleted {deleted_count} cache records")
        
        # Step 3: Test after cache clear
        success = test_after_cache_clear()
        if success:
            print(f"\n✅ SOLUTION FOUND: Cache was the issue!")
        else:
            print(f"\n❌ Problem persists after cache clear")
    else:
        print(f"\n📊 No problematic cached data found")
        print(f"🤔 The issue might be in the frontend or API endpoint logic")