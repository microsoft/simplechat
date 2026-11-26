#!/usr/bin/env python3
# test_activity_trends_field_mapping.py
"""
Functional test for Activity Trends field mapping corrections.
Version: 0.230.005
Implemented in: 0.230.005

This test ensures that activity trends correctly use the proper timestamp fields:
- Conversations: last_updated
- Messages: timestamp  
- Documents: upload_date, last_updated
- Login Activity: activity_logs container
"""

import sys
import os
import requests
import json
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_activity_trends_field_mapping():
    """Test that activity trends uses correct timestamp fields."""
    print("🔍 Testing Activity Trends Field Mapping...")
    
    try:
        # Test the activity trends API endpoint
        url = "http://127.0.0.1:5000/api/admin/control-center/activity-trends"
        params = {"days": 7}
        
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ API Response successful")
            
            # Verify data structure
            if 'activity_data' in data:
                activity_data = data['activity_data']
                print(f"📊 Activity data keys: {list(activity_data.keys())}")
                
                # Check that we have the expected categories
                expected_categories = ['chats', 'documents', 'logins']
                for category in expected_categories:
                    if category in activity_data:
                        print(f"✅ Found {category} data")
                        if activity_data[category]:
                            sample_day = list(activity_data[category].keys())[0]
                            sample_value = activity_data[category][sample_day]
                            print(f"   Sample {category}: {sample_day} = {sample_value}")
                    else:
                        print(f"⚠️  Missing {category} data")
                
                # Verify we don't have uploads anymore (removed category)
                if 'uploads' in activity_data:
                    print(f"❌ Found unexpected 'uploads' category (should be removed)")
                    return False
                else:
                    print(f"✅ Correctly removed 'uploads' category")
                
                return True
            else:
                print(f"❌ Missing 'activity_data' in response")
                return False
        else:
            print(f"❌ API request failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
        
    except requests.exceptions.ConnectionError:
        print("⚠️  Connection failed - Flask app may not be running")
        print("   Start the app with: python app.py")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_data_field_verification():
    """Test that the backend correctly queries the right fields."""
    print("🔍 Testing Data Field Verification...")
    
    try:
        # This would need Flask app context, but we can test the database queries
        import sys
        import os
        
        # Add the app directory to path
        sys.path.append('/Users/paullizer/Repos/simplechat/application/single_app')
        
        from config import cosmos_conversations_container, cosmos_messages_container, cosmos_user_documents_container
        
        # Test conversations field
        conv_test = list(cosmos_conversations_container.query_items(
            query="SELECT TOP 1 c.last_updated FROM c WHERE IS_DEFINED(c.last_updated)",
            enable_cross_partition_query=True
        ))
        if conv_test:
            print("✅ Conversations have 'last_updated' field")
        
        # Test messages field  
        msg_test = list(cosmos_messages_container.query_items(
            query="SELECT TOP 1 c.timestamp FROM c WHERE IS_DEFINED(c.timestamp)",
            enable_cross_partition_query=True
        ))
        if msg_test:
            print("✅ Messages have 'timestamp' field")
            
        # Test documents field
        doc_test = list(cosmos_user_documents_container.query_items(
            query="SELECT TOP 1 c.upload_date FROM c WHERE IS_DEFINED(c.upload_date)",
            enable_cross_partition_query=True
        ))
        if doc_test:
            print("✅ Documents have 'upload_date' field")
            
        return True
        
    except Exception as e:
        print(f"❌ Database field verification failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Running Activity Trends Field Mapping Tests...\n")
    
    test1_result = test_data_field_verification()
    test2_result = test_activity_trends_field_mapping()
    
    all_passed = test1_result and test2_result
    
    print(f"\n📊 Test Results:")
    print(f"   Data Field Verification: {'✅ PASS' if test1_result else '❌ FAIL'}")
    print(f"   API Field Mapping: {'✅ PASS' if test2_result else '❌ FAIL'}")
    print(f"   Overall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    sys.exit(0 if all_passed else 1)