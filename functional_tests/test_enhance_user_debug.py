#!/usr/bin/env python3
"""
Test the enhance_user_with_activity function with proper Flask context to identify the exact bug.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_enhance_user_with_flask_context():
    """Test enhance_user_with_activity with proper Flask application context."""
    print("🔍 Testing enhance_user_with_activity with Flask Context")
    print("=" * 60)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        # Import Flask app and create context
        from app import app
        from route_backend_control_center import enhance_user_with_activity
        
        with app.app_context():
            print(f"✅ Flask application context created")
            
            # Create mock user exactly as expected
            mock_user = {
                'id': test_user_id,
                'name': 'Test User',
                'email': f'{test_user_id}@test.com',
                'settings': {
                    'enable_enhanced_citation': True
                }
            }
            
            print(f"📊 Testing user: {test_user_id}")
            print(f"📊 Enhanced citation enabled: {mock_user['settings']['enable_enhanced_citation']}")
            
            # Call the function with force_refresh to avoid cached data
            enhanced_user = enhance_user_with_activity(mock_user, force_refresh=True)
            
            # Check the results
            if 'activity' in enhanced_user and 'document_metrics' in enhanced_user['activity']:
                doc_metrics = enhanced_user['activity']['document_metrics']
                
                print(f"\n📊 ENHANCED USER RESULTS:")
                print(f"   Enhanced citations enabled: {doc_metrics.get('enhanced_citation_enabled', 'N/A')}")
                print(f"   Total documents: {doc_metrics.get('total_documents', 'N/A')}")
                print(f"   AI search size: {doc_metrics.get('ai_search_size', 'N/A')}")
                print(f"   Storage account size: {doc_metrics.get('storage_account_size', 'N/A')}")
                print(f"   Last day upload: {doc_metrics.get('last_day_upload', 'N/A')}")
                
                storage_size = doc_metrics.get('storage_account_size', 0)
                
                if storage_size == 0:
                    print(f"\n❌ BUG CONFIRMED: Storage account size is 0!")
                    print(f"🔍 Expected: ~1,325,363,200 bytes (1263.96 MB)")
                    print(f"🔍 Actual: {storage_size} bytes")
                    
                    # Check if enhanced citation is properly set
                    enhanced_citation = doc_metrics.get('enhanced_citation_enabled', False)
                    if not enhanced_citation:
                        print(f"❌ Enhanced citation is not enabled in results - this might be the issue")
                    else:
                        print(f"✅ Enhanced citation is enabled in results")
                        print(f"❌ The bug is in the storage calculation logic within the function")
                        
                elif storage_size > 1000000000:  # > 1GB
                    print(f"\n✅ Storage account size calculated correctly: {storage_size:,} bytes ({storage_size / 1024 / 1024:.2f} MB)")
                else:
                    print(f"\n⚠️  Storage account size seems low: {storage_size:,} bytes ({storage_size / 1024 / 1024:.2f} MB)")
                    print(f"🔍 Expected: ~1,325,363,200 bytes (1263.96 MB)")
                
                return storage_size
                
            else:
                print(f"❌ No document metrics found in enhanced user data")
                print(f"🔍 Enhanced user keys: {list(enhanced_user.keys())}")
                if 'activity' in enhanced_user:
                    print(f"🔍 Activity keys: {list(enhanced_user['activity'].keys())}")
                return 0
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 0

def test_enhance_user_debug_logging():
    """Test with debug logging to see exactly what happens inside the function."""
    print(f"\n🔍 Testing enhance_user_with_activity with Debug Logging")
    print("=" * 60)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        from app import app
        import logging
        
        # Set up debug logging
        logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
        
        with app.app_context():
            print(f"✅ Flask application context created with debug logging")
            
            # Import and patch the enhance function to add our own debug prints
            from route_backend_control_center import enhance_user_with_activity
            import route_backend_control_center
            
            # Create mock user
            mock_user = {
                'id': test_user_id,
                'name': 'Test User',
                'email': f'{test_user_id}@test.com',
                'settings': {
                    'enable_enhanced_citation': True
                }
            }
            
            print(f"📊 Calling enhance_user_with_activity with force_refresh=True")
            
            # Call the function
            result = enhance_user_with_activity(mock_user, force_refresh=True)
            
            # Check storage client availability inside the context
            from config import CLIENTS
            storage_client = CLIENTS.get("storage_account_office_docs_client")
            print(f"📊 Storage client inside Flask context: {storage_client is not None}")
            
            # Check document metrics specifically
            if 'activity' in result and 'document_metrics' in result['activity']:
                doc_metrics = result['activity']['document_metrics']
                enhanced_citation = doc_metrics.get('enhanced_citation_enabled', False)
                storage_size = doc_metrics.get('storage_account_size', 0)
                
                print(f"\n📊 FINAL RESULTS:")
                print(f"   Enhanced citations enabled: {enhanced_citation}")
                print(f"   Storage account size: {storage_size:,} bytes")
                
                if enhanced_citation and storage_size == 0:
                    print(f"❌ BUG CONFIRMED: Enhanced citations enabled but storage size is 0")
                    print(f"🔍 The fallback logic is not executing inside the function")
                
                return storage_size
            else:
                print(f"❌ No document metrics in result")
                return 0
        
    except Exception as e:
        print(f"❌ Debug test failed: {e}")
        import traceback
        traceback.print_exc()
        return 0

if __name__ == "__main__":
    print("🚀 Starting Enhanced User Activity Debug Test")
    print("=" * 60)
    
    # Test 1: Basic function test with Flask context
    basic_result = test_enhance_user_with_flask_context()
    
    # Test 2: Debug logging test
    debug_result = test_enhance_user_debug_logging()
    
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY:")
    print(f"   Basic Function Test: {'✅ PASSED' if basic_result > 0 else '❌ FAILED'} ({basic_result:,} bytes)")
    print(f"   Debug Logging Test: {'✅ PASSED' if debug_result > 0 else '❌ FAILED'} ({debug_result:,} bytes)")
    
    if basic_result == 0 and debug_result == 0:
        print(f"❌ BUG CONFIRMED: enhance_user_with_activity is not properly calculating storage size")
        print(f"🔍 Next step: Review the exact code path and exception handling")
    else:
        print(f"✅ Function works - issue might be in caching or other integration")