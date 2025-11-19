#!/usr/bin/env python3
"""
Functional test for enhanced Control Center document metrics.
Version: 0.230.024
Implemented in: 0.230.024

This test ensures that the enhanced document metrics work correctly and
prevents regression of the document column functionality.
"""

import sys
import os

def test_enhanced_document_metrics():
    """Test the enhanced document metrics functionality."""
    print("🔍 Testing Enhanced Control Center Document Metrics...")
    
    try:
        # Import the actual function from the route
        from application.single_app.route_backend_control_center import enhance_user_with_activity
        
        # Test user data structure
        test_user = {
            'id': '07e61033-ea1a-4472-a1e7-6b9ac874984a',
            'email': 'paullizer@microsoft.com',
            'display_name': 'Paul Microsoft'
        }
        
        print(f"📋 Testing document metrics for user: {test_user['display_name']}")
        
        # Call the actual enhancement function
        enhanced_user = enhance_user_with_activity(test_user)
        
        # Validate the structure
        assert 'activity' in enhanced_user, "Missing activity data"
        assert 'document_metrics' in enhanced_user['activity'], "Missing document_metrics"
        
        doc_metrics = enhanced_user['activity']['document_metrics']
        
        # Test 1: Check required fields exist
        print("📊 Test 1: Checking required document metric fields...")
        required_fields = [
            'last_day_upload',
            'total_documents', 
            'ai_search_size',
            'enhanced_citation_enabled'
        ]
        
        for field in required_fields:
            assert field in doc_metrics, f"Missing required field: {field}"
            print(f"   ✅ {field}: {doc_metrics[field]}")
        
        # Test 2: Validate data types and formats
        print("🔍 Test 2: Validating data types and formats...")
        
        # Check last_day_upload format (should be MM/DD/YYYY or 'Never')
        last_day = doc_metrics['last_day_upload']
        if last_day != 'Never':
            # Should match MM/DD/YYYY format
            import re
            date_pattern = r'^\d{2}/\d{2}/\d{4}$'
            assert re.match(date_pattern, last_day), f"Invalid date format: {last_day}"
            print(f"   ✅ Last day upload format: {last_day}")
        else:
            print(f"   ✅ Last day upload: {last_day}")
        
        # Check numeric fields
        assert isinstance(doc_metrics['total_documents'], int), "total_documents should be int"
        assert doc_metrics['total_documents'] >= 0, "total_documents should be non-negative"
        print(f"   ✅ Total documents: {doc_metrics['total_documents']}")
        
        assert isinstance(doc_metrics['ai_search_size'], int), "ai_search_size should be int"
        assert doc_metrics['ai_search_size'] >= 0, "ai_search_size should be non-negative"
        print(f"   ✅ AI search size: {doc_metrics['ai_search_size']} bytes")
        
        # Check boolean field
        assert isinstance(doc_metrics['enhanced_citation_enabled'], bool), "enhanced_citation_enabled should be bool"
        print(f"   ✅ Enhanced citation enabled: {doc_metrics['enhanced_citation_enabled']}")
        
        # Test 3: Enhanced citations storage size
        print("💾 Test 3: Checking enhanced citations storage size...")
        if doc_metrics['enhanced_citation_enabled']:
            assert 'storage_account_size' in doc_metrics, "Missing storage_account_size when enhanced citations enabled"
            storage_size = doc_metrics['storage_account_size']
            assert isinstance(storage_size, int), "storage_account_size should be int"
            assert storage_size >= 0, "storage_account_size should be non-negative"
            print(f"   ✅ Storage account size: {storage_size} bytes")
        else:
            print(f"   ✅ Enhanced citations disabled - no storage size required")
        
        # Test 4: Validate calculated values make sense
        print("🧮 Test 4: Validating calculated values...")
        
        # If we have documents, we should have some AI search size
        if doc_metrics['total_documents'] > 0:
            assert doc_metrics['ai_search_size'] > 0, "Should have AI search size if documents exist"
            print(f"   ✅ AI search size calculated correctly for {doc_metrics['total_documents']} documents")
        
        # Test 5: Check complete data structure
        print("📋 Test 5: Checking complete enhanced user structure...")
        
        # Should have all main sections
        main_sections = ['id', 'email', 'display_name', 'activity']
        for section in main_sections:
            assert section in enhanced_user, f"Missing main section: {section}"
        
        # Activity should have all metric types
        activity_sections = ['login_metrics', 'chat_metrics', 'document_metrics']
        for section in activity_sections:
            assert section in enhanced_user['activity'], f"Missing activity section: {section}"
        
        print("   ✅ Complete enhanced user structure validated")
        
        # Summary
        print(f"\n📋 SUMMARY - Document Metrics Test Results:")
        print(f"   📅 Last Day Upload: {doc_metrics['last_day_upload']}")
        print(f"   📊 Total Documents: {doc_metrics['total_documents']}")
        print(f"   🔍 AI Search Size: {doc_metrics['ai_search_size']:,} bytes")
        if doc_metrics['enhanced_citation_enabled']:
            print(f"   💾 Storage Size: {doc_metrics.get('storage_account_size', 0):,} bytes")
        print(f"   🔧 Enhanced Citations: {doc_metrics['enhanced_citation_enabled']}")
        
        print("✅ All document metrics tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_enhanced_document_metrics()
    sys.exit(0 if success else 1)