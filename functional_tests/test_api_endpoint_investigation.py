#!/usr/bin/env python3
"""
Test the actual API endpoint that serves user data to confirm if the bug is in the endpoint.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_api_endpoint_direct():
    """Test the /api/admin/control-center/users endpoint directly."""
    print("🔍 Testing API Endpoint /api/admin/control-center/users")
    print("=" * 60)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        from app import app
        
        with app.test_client() as client:
            with app.app_context():
                print(f"✅ Flask test client created")
                
                # Make request to the API endpoint with force_refresh
                response = client.get('/api/admin/control-center/users?force_refresh=true&search=07e61033')
                
                print(f"📊 API Response Status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.get_json()
                    
                    if 'users' in data and data['users']:
                        users = data['users']
                        print(f"📊 Found {len(users)} users in API response")
                        
                        target_user = None
                        for user in users:
                            if user.get('id') == test_user_id:
                                target_user = user
                                break
                        
                        if target_user:
                            print(f"✅ Found target user in API response")
                            
                            if 'activity' in target_user and 'document_metrics' in target_user['activity']:
                                metrics = target_user['activity']['document_metrics']
                                storage_size = metrics.get('storage_account_size', 0)
                                enhanced_citation = metrics.get('enhanced_citation_enabled', False)
                                total_docs = metrics.get('total_documents', 0)
                                
                                print(f"\n📊 API ENDPOINT RESULTS:")
                                print(f"   Enhanced citations enabled: {enhanced_citation}")
                                print(f"   Total documents: {total_docs}")
                                print(f"   Storage account size: {storage_size:,} bytes")
                                
                                if storage_size == 0:
                                    print(f"❌ BUG CONFIRMED: API endpoint returns 0 storage size!")
                                    print(f"🔍 This means the issue is NOT in enhance_user_with_activity")
                                    print(f"🔍 The issue is either in caching or authentication/authorization")
                                    return False
                                else:
                                    print(f"✅ API endpoint returns correct storage size: {storage_size / 1024 / 1024:.2f} MB")
                                    return True
                            else:
                                print(f"❌ No document metrics found in API response")
                                print(f"🔍 User data keys: {list(target_user.keys())}")
                                return False
                        else:
                            print(f"❌ Target user not found in API response")
                            print(f"🔍 Available user IDs: {[u.get('id', 'N/A') for u in users]}")
                            return False
                    else:
                        print(f"❌ No users found in API response")
                        print(f"🔍 Response data keys: {list(data.keys()) if data else 'No data'}")
                        return False
                elif response.status_code == 401:
                    print(f"❌ API endpoint requires authentication")
                    print(f"🔍 This test cannot authenticate as admin user")
                    return False
                else:
                    print(f"❌ API endpoint returned error: {response.status_code}")
                    print(f"🔍 Response: {response.get_data(as_text=True)}")
                    return False
        
    except Exception as e:
        print(f"❌ API endpoint test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_user_settings_directly():
    """Check the user's settings directly from Cosmos DB to see if enhanced_citation is enabled."""
    print(f"\n🔍 Testing User Settings in Cosmos DB")
    print("=" * 60)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        from app import app
        from config import cosmos_user_settings_container
        
        with app.app_context():
            print(f"✅ Flask application context created")
            
            # Query for the user's settings
            settings_query = f"""
            SELECT * FROM c 
            WHERE c.id = '{test_user_id}'
            """
            
            print(f"📊 Querying user settings in Cosmos DB...")
            user_settings = list(cosmos_user_settings_container.query_items(
                query=settings_query,
                enable_cross_partition_query=True
            ))
            
            if user_settings:
                user = user_settings[0]
                print(f"✅ Found user settings in Cosmos DB")
                
                settings = user.get('settings', {})
                enhanced_citation = settings.get('enable_enhanced_citation', False)
                
                print(f"\n📊 USER SETTINGS:")
                print(f"   User ID: {user.get('id', 'N/A')}")
                print(f"   Email: {user.get('email', 'N/A')}")
                print(f"   Display Name: {user.get('display_name', 'N/A')}")
                print(f"   Enhanced Citation Enabled: {enhanced_citation}")
                
                if enhanced_citation:
                    print(f"✅ Enhanced citation is enabled in user settings")
                    return True
                else:
                    print(f"❌ Enhanced citation is NOT enabled in user settings")
                    print(f"🔍 This explains why storage size might be 0")
                    print(f"🔍 Settings: {settings}")
                    return False
            else:
                print(f"❌ User settings not found in Cosmos DB")
                print(f"🔍 User ID might be incorrect: {test_user_id}")
                return False
        
    except Exception as e:
        print(f"❌ User settings test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Starting API Endpoint and Settings Investigation")
    print("=" * 60)
    
    # Test 1: Check user settings first
    settings_ok = test_user_settings_directly()
    
    # Test 2: Try to test API endpoint (might fail due to auth)
    api_ok = test_api_endpoint_direct()
    
    print("\n" + "=" * 60)
    print("📊 INVESTIGATION SUMMARY:")
    print(f"   User Settings Test: {'✅ PASSED' if settings_ok else '❌ FAILED'}")
    print(f"   API Endpoint Test: {'✅ PASSED' if api_ok else '❌ FAILED/SKIPPED'}")
    
    if not settings_ok:
        print(f"\n🎯 ROOT CAUSE IDENTIFIED:")
        print(f"   Enhanced citation is not enabled in user settings")
        print(f"   This explains the 0 storage account size")
        print(f"   Solution: Enable enhanced citation for the user")
    elif api_ok:
        print(f"\n✅ SYSTEM WORKING CORRECTLY:")
        print(f"   Both user settings and API endpoint show correct data")
        print(f"   Issue might be in frontend caching or different environment")
    else:
        print(f"\n🤔 INCONCLUSIVE:")
        print(f"   Settings are correct but API endpoint test failed")
        print(f"   Issue might be in authentication or caching")