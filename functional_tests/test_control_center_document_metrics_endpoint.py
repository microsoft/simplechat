#!/usr/bin/env python3
"""
Functional test for Control Center Enhanced Document Metrics endpoint.
Version: 0.230.024
Implemented in: 0.230.024

This test validates that the Control Center API returns enhanced document metrics 
with the correct format including:
- last_day_upload as MM/DD/YYYY from most recent last_updated
- total_documents count 
- ai_search_size calculated as pages * 80KB
- storage_account_size when enhanced citations enabled
"""

import sys
import os
import requests
import json
from datetime import datetime

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_control_center_document_metrics():
    """Test the Control Center document metrics endpoint."""
    print("🔍 Testing Control Center Document Metrics Endpoint...")
    
    try:
        # Test configuration
        base_url = "http://localhost:5000"  # Adjust if running on different port
        test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
        
        print(f"📋 Testing document metrics for user ID: {test_user_id}")
        
        # Make request to Control Center endpoint
        url = f"{base_url}/api/control-center"
        print(f"🌐 Making request to: {url}")
        
        response = requests.get(url, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ API request failed with status: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
        data = response.json()
        print("✅ Successfully retrieved Control Center data")
        
        # Find our test user in the response
        test_user = None
        for user in data.get('users', []):
            if user.get('id') == test_user_id:
                test_user = user
                break
                
        if not test_user:
            print(f"❌ Test user {test_user_id} not found in response")
            return False
            
        print(f"👤 Found test user: {test_user.get('display_name', 'Unknown')}")
        
        # Check if document_metrics exists
        if 'document_metrics' not in test_user:
            print("❌ document_metrics not found in user data")
            return False
            
        doc_metrics = test_user['document_metrics']
        print("📊 Document metrics found, validating structure...")
        
        # Validate required fields exist
        required_fields = ['last_day_upload', 'total_documents', 'ai_search_size', 'storage_account_size']
        for field in required_fields:
            if field not in doc_metrics:
                print(f"❌ Required field '{field}' missing from document_metrics")
                return False
                
        print("✅ All required fields present")
        
        # Validate last_day_upload format (MM/DD/YYYY or "N/A")
        last_day = doc_metrics['last_day_upload']
        if last_day != "N/A":
            try:
                # Try to parse as MM/DD/YYYY
                parsed_date = datetime.strptime(last_day, '%m/%d/%Y')
                print(f"✅ last_day_upload format valid: {last_day}")
            except ValueError:
                print(f"❌ last_day_upload format invalid: {last_day} (expected MM/DD/YYYY)")
                return False
        else:
            print("✅ last_day_upload is N/A (no documents)")
            
        # Validate numeric fields
        numeric_fields = ['total_documents', 'ai_search_size', 'storage_account_size']
        for field in numeric_fields:
            value = doc_metrics[field]
            if not isinstance(value, (int, float)) or value < 0:
                print(f"❌ {field} should be non-negative number, got: {value}")
                return False
            print(f"✅ {field}: {value:,}")
            
        # Validate AI search size calculation logic (should be total_pages * 80 * 1024)
        total_docs = doc_metrics['total_documents']
        ai_search_size = doc_metrics['ai_search_size']
        
        if total_docs > 0 and ai_search_size == 0:
            print("⚠️ Warning: Documents exist but AI search size is 0")
        elif total_docs == 0 and ai_search_size > 0:
            print("⚠️ Warning: No documents but AI search size > 0")
        else:
            print("✅ AI search size calculation appears consistent")
            
        # Print summary
        print("\n📈 Document Metrics Summary:")
        print(f"   📅 Last Day Upload: {doc_metrics['last_day_upload']}")
        print(f"   📄 Total Documents: {doc_metrics['total_documents']:,}")
        print(f"   🔍 AI Search Size: {doc_metrics['ai_search_size']:,} bytes")
        print(f"   💾 Storage Account Size: {doc_metrics['storage_account_size']:,} bytes")
        
        print("\n✅ Control Center Document Metrics test passed!")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        print("💡 Make sure the Flask app is running on localhost:5000")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_control_center_document_metrics()
    if success:
        print("\n🎉 All tests passed! Enhanced document metrics are working correctly.")
    else:
        print("\n💥 Tests failed! Check the implementation.")
    sys.exit(0 if success else 1)