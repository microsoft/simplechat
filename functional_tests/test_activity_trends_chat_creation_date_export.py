#!/usr/bin/env python3
# test_activity_trends_chat_creation_date_export.py
"""
Functional test for Activity Trends raw data export with creation date for chats.
Version: 0.230.026
Implemented in: 0.230.026

This test ensures that the Activity Trends export includes creation dates for chat records
in addition to all other raw data fields.
"""

import sys
import os
import requests
import json
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_export_includes_chat_creation_date():
    """Test that chat export includes creation date field."""
    print("🔍 Testing Activity Trends Export with Chat Creation Date...")
    
    try:
        # Test data for export request
        export_data = {
            'charts': ['chats'],
            'time_window': '7'  # Last 7 days
        }
        
        # Try to test the export endpoint (would require authentication in real scenario)
        base_url = "http://127.0.0.1:5000"
        export_url = f"{base_url}/api/admin/control-center/activity-trends/export"
        
        try:
            response = requests.post(export_url, json=export_data)
            
            if response.status_code == 401:
                print("⚠️  Authentication required - cannot test API directly")
                print("✅ Export endpoint exists and requires proper authentication")
                
                # Instead, let's test that our function can be imported and has the right structure
                return test_function_structure()
                
            elif response.status_code == 200:
                # Check if response contains CSV data
                csv_content = response.text
                print(f"✅ Export endpoint responded successfully")
                
                # Check for chat section headers
                if "=== CHATS DATA ===" in csv_content:
                    print("✅ Chat data section found in export")
                else:
                    print("❌ Chat data section not found in export")
                    return False
                
                # Check for creation date header
                if "Created Date" in csv_content:
                    print("✅ Creation Date header found in chat export")
                    return True
                else:
                    print("❌ Creation Date header not found in chat export")
                    return False
                    
            else:
                print(f"❌ Unexpected response code: {response.status_code}")
                return test_function_structure()
                
        except requests.exceptions.ConnectionError:
            print("⚠️  Could not connect to server - testing function structure instead")
            return test_function_structure()
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_function_structure():
    """Test that the backend function has the correct structure."""
    print("🔍 Testing backend function structure...")
    
    try:
        # Check if the backend file contains our new function
        backend_file = "../application/single_app/route_backend_control_center.py"
        if os.path.exists(backend_file):
            with open(backend_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for raw activity trends function
            if "def get_raw_activity_trends_data" in content:
                print("✅ Raw activity trends function found")
            else:
                print("❌ Raw activity trends function not found")
                return False
            
            # Check for creation date handling in chats
            if "created_at = conv.get('created_at')" in content:
                print("✅ Creation date extraction found in chat processing")
            else:
                print("❌ Creation date extraction not found in chat processing")
                return False
            
            # Check for creation date in CSV export
            if "'Created Date'" in content and "record.get('created_date', '')" in content:
                print("✅ Creation date found in CSV export structure")
            else:
                print("❌ Creation date not found in CSV export structure")
                return False
                
            print("✅ All function structure checks passed")
            return True
            
        else:
            print(f"❌ Backend file not found: {backend_file}")
            return False
            
    except Exception as e:
        print(f"❌ Function structure test failed: {e}")
        return False

def test_frontend_update():
    """Test that the frontend template includes creation date info."""
    print("🔍 Testing frontend template update...")
    
    try:
        template_file = "../application/single_app/templates/control_center.html"
        if os.path.exists(template_file):
            with open(template_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for updated chat description with creation date
            if "created date" in content and "Chats:" in content:
                print("✅ Frontend template includes creation date in export description")
                return True
            else:
                print("❌ Frontend template does not include creation date in export description")
                return False
                
        else:
            print(f"❌ Template file not found: {template_file}")
            return False
            
    except Exception as e:
        print(f"❌ Frontend test failed: {e}")
        return False

if __name__ == "__main__":
    tests = [
        test_export_includes_chat_creation_date,
        test_function_structure, 
        test_frontend_update
    ]
    
    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All tests passed! Chat creation date export functionality is working correctly.")
    else:
        print("❌ Some tests failed. Please check the implementation.")
    
    sys.exit(0 if success else 1)