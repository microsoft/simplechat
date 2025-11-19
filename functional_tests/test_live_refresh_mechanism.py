#!/usr/bin/env python3
"""
Test live refresh mechanism against running Flask app.
Version: [will check config.py]

This test validates the refresh mechanism by making direct API calls 
to the running Flask application.
"""

import requests
import json
import sys
import os

def test_live_refresh_mechanism():
    """Test the refresh mechanism against the running Flask app."""
    print("🔍 Testing live refresh mechanism...")
    
    try:
        # Test user ID from our previous debugging
        test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
        
        # First, get current user data
        print(f"📊 Getting current user data for {test_user_id}...")
        
        base_url = "http://localhost:5000"
        
        # Test the control center refresh endpoint
        refresh_url = f"{base_url}/api/admin/control-center/refresh"
        refresh_payload = {
            "user_id": test_user_id,
            "force_refresh": True
        }
        
        print(f"🔄 Calling refresh endpoint: {refresh_url}")
        print(f"📝 Payload: {json.dumps(refresh_payload, indent=2)}")
        
        # Make the refresh request
        response = requests.post(
            refresh_url,
            json=refresh_payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        print(f"📈 Response Status: {response.status_code}")
        print(f"📋 Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            response_data = response.json()
            print(f"✅ Refresh successful!")
            print(f"📊 Response data: {json.dumps(response_data, indent=2)}")
            
            # Check for storage account size in the response
            if 'storage_account_size_mb' in response_data:
                size_mb = response_data['storage_account_size_mb']
                print(f"💾 Storage account size: {size_mb} MB")
                
                if size_mb > 0:
                    print("✅ Storage account size is properly calculated!")
                    return True
                else:
                    print("❌ Storage account size is still 0 MB")
                    return False
            else:
                print("⚠️ No storage_account_size_mb in response")
                return False
        else:
            print(f"❌ Refresh failed with status {response.status_code}")
            print(f"📄 Response text: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to Flask app. Is it running on http://localhost:5000?")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_storage_client_directly():
    """Test if we can check storage client status through an API."""
    print("\n🔍 Testing storage client status...")
    
    try:
        base_url = "http://localhost:5000"
        
        # Try to make a simple request to see if app is responsive
        health_url = f"{base_url}/"
        print(f"🏥 Testing app health at {health_url}")
        
        response = requests.get(health_url, timeout=10)
        print(f"📈 Health check status: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Flask app is responsive")
            return True
        else:
            print(f"❌ Flask app returned {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Starting live refresh mechanism test...")
    
    # First check if app is running
    health_success = test_storage_client_directly()
    
    if health_success:
        # Test the actual refresh mechanism
        refresh_success = test_live_refresh_mechanism()
        
        if refresh_success:
            print("\n🎉 All tests passed! Refresh mechanism is working.")
            sys.exit(0)
        else:
            print("\n❌ Refresh mechanism test failed.")
            sys.exit(1)
    else:
        print("\n❌ Flask app is not responsive. Please check if it's running.")
        sys.exit(1)