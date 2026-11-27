#!/usr/bin/env python3
# test_refresh_mechanism_debug.py
"""
Test the refresh mechanism to see why storage account size isn't being updated.
Version: Current version from config.py
Implemented in: [version when fix/feature was added]

This test investigates the refresh button functionality in the control center.
Version: 0.261.474
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_storage_client_initialization():
    """Test if the storage client is being initialized correctly."""
    print("🔍 Testing Storage Client Initialization")
    print("=" * 60)
    
    try:
        from app import app
        from config import CLIENTS
        from functions_settings import get_settings
        
        with app.app_context():
            print(f"✅ Flask application context created")
            
            # Check app settings
            settings = get_settings()
            enhanced_citations = settings.get("enable_enhanced_citations")
            auth_type = settings.get("office_docs_authentication_type")
            storage_url = settings.get("office_docs_storage_account_url")
            
            print(f"\n📊 APP SETTINGS:")
            print(f"   Enhanced Citations Enabled: {enhanced_citations}")
            print(f"   Office Docs Auth Type: {auth_type}")
            print(f"   Storage Account URL Present: {bool(storage_url)}")
            
            # Check if storage client is initialized
            storage_client = CLIENTS.get("storage_account_office_docs_client")
            print(f"   Storage Client Initialized: {storage_client is not None}")
            
            if storage_client:
                print(f"   Storage Client Type: {type(storage_client)}")
                return True
            else:
                print(f"❌ Storage client not initialized!")
                print(f"🔍 This explains why storage size is 0")
                return False
        
    except Exception as e:
        print(f"❌ Storage client test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_enhance_user_with_specific_user():
    """Test the enhance_user_with_activity function with the specific user and force_refresh=True."""
    print(f"\n🔄 Testing enhance_user_with_activity with force_refresh=True")
    print("=" * 60)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        from app import app
        from route_backend_control_center import enhance_user_with_activity
        from config import cosmos_user_settings_container
        
        with app.app_context():
            print(f"✅ Flask application context created")
            
            # Get the actual user from Cosmos DB
            user_query = f"SELECT * FROM c WHERE c.id = '{test_user_id}'"
            users = list(cosmos_user_settings_container.query_items(
                query=user_query,
                enable_cross_partition_query=True
            ))
            
            if not users:
                print(f"❌ User not found: {test_user_id}")
                return False
            
            user = users[0]
            print(f"📊 Found user: {user.get('email', 'N/A')}")
            
            # Show current cached metrics
            cached_metrics = user.get('settings', {}).get('metrics', {})
            if cached_metrics:
                doc_metrics = cached_metrics.get('document_metrics', {})
                print(f"\n📊 CURRENT CACHED METRICS:")
                print(f"   Calculated At: {cached_metrics.get('calculated_at', 'N/A')}")
                print(f"   Total Documents: {doc_metrics.get('total_documents', 'N/A')}")
                print(f"   Storage Account Size: {doc_metrics.get('storage_account_size', 'N/A')}")
            else:
                print(f"📊 No cached metrics found")
            
            # Test enhance_user_with_activity with force_refresh=True
            print(f"\n🔄 Calling enhance_user_with_activity(force_refresh=True)...")
            enhanced_user = enhance_user_with_activity(user, force_refresh=True)
            
            # Check the results
            if 'activity' in enhanced_user and 'document_metrics' in enhanced_user['activity']:
                doc_metrics = enhanced_user['activity']['document_metrics']
                
                print(f"\n📊 ENHANCED USER RESULTS:")
                print(f"   Total Documents: {doc_metrics.get('total_documents', 'N/A')}")
                print(f"   Storage Account Size: {doc_metrics.get('storage_account_size', 'N/A')}")
                print(f"   AI Search Size: {doc_metrics.get('ai_search_size', 'N/A')}")
                
                storage_size = doc_metrics.get('storage_account_size', 0)
                if storage_size > 0:
                    print(f"✅ Storage size calculated: {storage_size:,} bytes ({storage_size / 1024 / 1024:.2f} MB)")
                    return True
                else:
                    print(f"❌ Storage size still 0!")
                    return False
            else:
                print(f"❌ No document metrics in enhanced user")
                return False
        
    except Exception as e:
        print(f"❌ Enhance user test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_update_user_settings():
    """Test if the user settings are being updated correctly after refresh."""
    print(f"\n💾 Testing User Settings Update")
    print("=" * 60)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        from app import app
        from config import cosmos_user_settings_container
        
        with app.app_context():
            print(f"✅ Flask application context created")
            
            # Get the user again after potential update
            user_query = f"SELECT * FROM c WHERE c.id = '{test_user_id}'"
            users = list(cosmos_user_settings_container.query_items(
                query=user_query,
                enable_cross_partition_query=True
            ))
            
            if not users:
                print(f"❌ User not found: {test_user_id}")
                return False
            
            user = users[0]
            
            # Check if metrics were updated
            cached_metrics = user.get('settings', {}).get('metrics', {})
            if cached_metrics:
                doc_metrics = cached_metrics.get('document_metrics', {})
                calculated_at = cached_metrics.get('calculated_at', 'N/A')
                storage_size = doc_metrics.get('storage_account_size', 0)
                
                print(f"📊 UPDATED USER SETTINGS:")
                print(f"   Calculated At: {calculated_at}")
                print(f"   Storage Account Size: {storage_size}")
                
                if storage_size > 0:
                    print(f"✅ User settings updated with correct storage size!")
                    return True
                else:
                    print(f"❌ User settings still show 0 storage size")
                    return False
            else:
                print(f"❌ No metrics found in user settings")
                return False
        
    except Exception as e:
        print(f"❌ User settings check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Starting Refresh Mechanism Investigation")
    print("=" * 60)
    
    # Test 1: Check storage client initialization
    client_ok = test_storage_client_initialization()
    
    # Test 2: Test enhance_user_with_activity with force_refresh
    enhance_ok = test_enhance_user_with_specific_user()
    
    # Test 3: Check if user settings are updated
    settings_ok = test_update_user_settings()
    
    print("\n" + "=" * 60)
    print("📊 REFRESH MECHANISM INVESTIGATION SUMMARY:")
    print(f"   Storage Client Initialization: {'✅ PASSED' if client_ok else '❌ FAILED'}")
    print(f"   Force Refresh Function: {'✅ PASSED' if enhance_ok else '❌ FAILED'}")
    print(f"   User Settings Update: {'✅ PASSED' if settings_ok else '❌ FAILED'}")
    
    if not client_ok:
        print(f"\n🎯 ROOT CAUSE IDENTIFIED:")
        print(f"   Storage client is not being initialized properly")
        print(f"   This prevents both actual storage querying and fallback estimation")
        print(f"   Solution: Check storage account configuration in app settings")
    elif enhance_ok and not settings_ok:
        print(f"\n🎯 PARTIAL ISSUE:")
        print(f"   Function calculates correctly but doesn't save to user settings")
        print(f"   Solution: Check the user settings update mechanism")
    elif client_ok and enhance_ok and settings_ok:
        print(f"\n✅ SYSTEM WORKING CORRECTLY:")
        print(f"   All components are functioning properly")
        print(f"   The refresh should update storage size correctly")