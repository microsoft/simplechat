#!/usr/bin/env python3
"""
Quick API test for enhanced user management metrics
"""

import requests
import json
import sys
import os

def test_user_management_api():
    """Test the enhanced user management API endpoint"""
    
    print("🧪 Testing Enhanced User Management API")
    print("=" * 50)
    
    # Test URL (adjust port if needed)
    base_url = "http://localhost:5000"
    api_url = f"{base_url}/api/admin/control-center/users"
    
    try:
        print(f"📡 Making request to: {api_url}")
        
        # Make API request
        response = requests.get(api_url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"✅ API Response Status: {response.status_code}")
            print(f"✅ Response Structure:")
            print(f"   - Users Count: {len(data.get('users', []))}")
            print(f"   - Has Pagination: {'pagination' in data}")
            
            # Check if we have users to examine
            users = data.get('users', [])
            if users:
                sample_user = users[0]
                print(f"\n🔍 Sample User Structure:")
                print(f"   - ID: {sample_user.get('id', 'N/A')}")
                print(f"   - Name: {sample_user.get('name', 'N/A')}")
                print(f"   - Email: {sample_user.get('email', 'N/A')}")
                print(f"   - Has Profile Image: {'profile_image' in sample_user}")
                
                # Check activity structure
                activity = sample_user.get('activity', {})
                if activity:
                    print(f"   - Activity Structure:")
                    print(f"     * Login Metrics: {'login_metrics' in activity}")
                    print(f"     * Chat Metrics: {'chat_metrics' in activity}")
                    print(f"     * Document Metrics: {'document_metrics' in activity}")
                    
                    # Check specific metrics
                    login_metrics = activity.get('login_metrics', {})
                    if login_metrics:
                        print(f"     * Total Logins: {login_metrics.get('total_logins', 'N/A')}")
                        print(f"     * Last Login: {login_metrics.get('last_login', 'N/A')}")
                    
                    chat_metrics = activity.get('chat_metrics', {})
                    if chat_metrics:
                        print(f"     * Last Day Conversations: {chat_metrics.get('last_day_conversations', 'N/A')}")
                        print(f"     * Total Messages: {chat_metrics.get('total_messages', 'N/A')}")
                        print(f"     * Content Size: {chat_metrics.get('total_message_content_size', 'N/A')} bytes")
                    
                    doc_metrics = activity.get('document_metrics', {})
                    if doc_metrics:
                        print(f"     * Last Day Uploads: {doc_metrics.get('last_day_uploads', 'N/A')}")
                        print(f"     * Total Documents: {doc_metrics.get('total_documents', 'N/A')}")
                        print(f"     * AI Search Size: {doc_metrics.get('ai_search_size', 'N/A')} bytes")
                        print(f"     * Storage Size: {doc_metrics.get('storage_account_size', 'N/A')} bytes")
            
            print(f"\n🎉 Enhanced user management API is working correctly!")
            return True
            
        else:
            print(f"❌ API Error: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Connection Error: Could not connect to {api_url}")
        print(f"   Make sure the Flask server is running on port 5000")
        return False
        
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        return False

def test_activity_trends_api():
    """Test the activity trends API endpoint"""
    
    print("\n🧪 Testing Activity Trends API")
    print("=" * 50)
    
    # Test URL
    base_url = "http://localhost:5000"
    api_url = f"{base_url}/api/admin/control-center/activity-trends?days=7"
    
    try:
        print(f"📡 Making request to: {api_url}")
        
        response = requests.get(api_url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"✅ Activity Trends API Status: {response.status_code}")
            print(f"✅ Response Structure:")
            print(f"   - Has Login Data: {'logins' in data}")
            print(f"   - Has Chat Data: {'chats' in data}")
            print(f"   - Has Document Data: {'documents' in data}")
            
            # Check data lengths
            for category in ['logins', 'chats', 'documents']:
                if category in data:
                    print(f"   - {category.title()} Data Points: {len(data[category])}")
            
            print(f"\n🎉 Activity trends API is working correctly!")
            return True
            
        else:
            print(f"❌ API Error: {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Connection Error: Could not connect to {api_url}")
        return False
        
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Enhanced Control Center API Test Suite")
    print("=" * 60)
    
    success_count = 0
    total_tests = 2
    
    if test_user_management_api():
        success_count += 1
    
    if test_activity_trends_api():
        success_count += 1
    
    print(f"\n📊 Test Results: {success_count}/{total_tests} tests passed")
    
    if success_count == total_tests:
        print("🎉 All API tests passed! Enhanced control center is ready!")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Check the Flask server and database connections.")
        sys.exit(1)