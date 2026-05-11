#!/usr/bin/env python3
"""
Functional test for enhanced user management with profile images and detailed metrics.
Version: 0.230.018
Implemented in: 0.230.018

This test ensures that the enhanced user management system correctly:
1. Extracts profile images from user settings
2. Provides detailed chat metrics (total conversations, messages, estimated size)
3. Provides detailed document metrics (total docs, storage size, AI search size)
4. Shows proper last activity timestamps for both chat and documents
5. Displays personal workspace and enhanced citation status
"""

import sys
import os

# Import required modules
from application.single_app.route_backend_control_center import enhance_user_with_activity

def test_enhanced_user_activity():
    """Test enhanced user activity data extraction."""
    print("🧪 Testing Enhanced User Management Activity Data...")
    
    try:
        # Test data - sample user with comprehensive settings
        test_user = {
            'id': 'test-user-12345',
            'email': 'test.user@microsoft.com',
            'display_name': 'Test User',
            'lastUpdated': '2025-10-03T10:00:00Z',
            'settings': {
                'profileImage': 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/test123...',
                'enable_personal_workspace': True,
                'enable_enhanced_citation': True,
                'activeGroupOid': '1b954a67-90fc-4975-aac1-3ba7e8f3a58e',
                'darkModeEnabled': False,
                'preferredModelDeployment': 'gpt-4o',
                'chatLayout': 'docked',
                'navbar_layout': 'left'
            }
        }
        
        # Test the enhance_user_with_activity function
        enhanced_user = enhance_user_with_activity(test_user)
        
        # Validate profile image extraction
        assert 'profile_image' in enhanced_user, "Profile image should be extracted"
        assert enhanced_user['profile_image'] == test_user['settings']['profileImage'], "Profile image should match settings"
        print("✅ Profile image extraction working correctly")
        
        # Validate chat metrics structure
        assert 'chat_metrics' in enhanced_user['activity'], "Chat metrics should be present"
        chat_metrics = enhanced_user['activity']['chat_metrics']
        
        required_chat_fields = ['total_conversations', 'total_messages', 'chat_volume_3m', 'estimated_size']
        for field in required_chat_fields:
            assert field in chat_metrics, f"Chat metrics should include {field}"
        print("✅ Chat metrics structure is correct")
        
        # Validate document metrics structure
        assert 'document_metrics' in enhanced_user['activity'], "Document metrics should be present"
        doc_metrics = enhanced_user['activity']['document_metrics']
        
        required_doc_fields = ['personal_workspace_enabled', 'enhanced_citation_enabled', 'total_documents', 'total_storage_size', 'ai_search_size']
        for field in required_doc_fields:
            assert field in doc_metrics, f"Document metrics should include {field}"
        print("✅ Document metrics structure is correct")
        
        # Validate feature flags
        assert doc_metrics['personal_workspace_enabled'] == True, "Personal workspace should be enabled"
        assert doc_metrics['enhanced_citation_enabled'] == True, "Enhanced citation should be enabled"
        print("✅ Feature flags extracted correctly")
        
        # Validate activity timestamps structure
        assert 'last_chat_activity' in enhanced_user['activity'], "Last chat activity should be tracked"
        assert 'last_document_activity' in enhanced_user['activity'], "Last document activity should be tracked"
        assert 'last_login' in enhanced_user['activity'], "Last login should be tracked"
        print("✅ Activity timestamp structure is correct")
        
        # Test with user without profile image
        test_user_no_image = {
            'id': 'test-user-67890',
            'email': 'no.image@microsoft.com',
            'display_name': 'No Image User',
            'settings': {
                'enable_personal_workspace': False,
                'enable_enhanced_citation': False
            }
        }
        
        enhanced_no_image = enhance_user_with_activity(test_user_no_image)
        assert enhanced_no_image['profile_image'] is None, "Profile image should be None when not set"
        assert enhanced_no_image['activity']['document_metrics']['personal_workspace_enabled'] == False, "Personal workspace should be disabled"
        assert enhanced_no_image['activity']['document_metrics']['enhanced_citation_enabled'] == False, "Enhanced citation should be disabled"
        print("✅ Handling users without profile images or disabled features")
        
        print("✅ Enhanced User Management test passed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Enhanced User Management test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_user_metrics_display_format():
    """Test the display format for user metrics."""
    print("🧪 Testing User Metrics Display Format...")
    
    try:
        # Mock enhanced user data with realistic values
        enhanced_user = {
            'id': 'user-123',
            'display_name': 'John Doe',
            'profile_image': 'data:image/jpeg;base64,/9j/test...',
            'activity': {
                'last_chat_activity': '2025-10-01T14:30:00Z',
                'last_document_activity': '2025-09-28T09:15:00Z',
                'last_login': '2025-10-03T08:00:00Z',
                'chat_metrics': {
                    'total_conversations': 45,
                    'total_messages': 892,
                    'chat_volume_3m': 23,
                    'estimated_size': 446000  # 892 * 500 chars
                },
                'document_metrics': {
                    'personal_workspace_enabled': True,
                    'enhanced_citation_enabled': True,
                    'total_documents': 15,
                    'total_storage_size': 2457600,  # ~2.4MB
                    'ai_search_size': 1966080     # 80% of storage
                }
            }
        }
        
        # Test display formatting
        chat_metrics = enhanced_user['activity']['chat_metrics']
        doc_metrics = enhanced_user['activity']['document_metrics']
        
        # Format chat display
        chat_display = f"Conversations: {chat_metrics['total_conversations']}, Messages: {chat_metrics['total_messages']}, Size: {chat_metrics['estimated_size'] // 1024}KB"
        assert "Conversations: 45" in chat_display, "Should show conversation count"
        assert "Messages: 892" in chat_display, "Should show message count"
        assert "Size: 435KB" in chat_display, "Should show estimated size in KB"
        print(f"✅ Chat metrics display: {chat_display}")
        
        # Format document display
        storage_mb = doc_metrics['total_storage_size'] / (1024 * 1024)
        ai_search_mb = doc_metrics['ai_search_size'] / (1024 * 1024)
        
        doc_display = f"Docs: {doc_metrics['total_documents']}, Storage: {storage_mb:.1f}MB"
        if doc_metrics['enhanced_citation_enabled']:
            doc_display += f", AI Search: {ai_search_mb:.1f}MB"
        if doc_metrics['personal_workspace_enabled']:
            doc_display += " (Personal Workspace)"
            
        assert "Docs: 15" in doc_display, "Should show document count"
        assert "Storage: 2.3MB" in doc_display, "Should show storage size in MB"
        assert "AI Search: 1.9MB" in doc_display, "Should show AI search size when enabled"
        assert "(Personal Workspace)" in doc_display, "Should indicate personal workspace status"
        print(f"✅ Document metrics display: {doc_display}")
        
        print("✅ User Metrics Display Format test passed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ User Metrics Display Format test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_enhanced_user_activity,
        test_user_metrics_display_format
    ]
    
    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Enhanced User Management Test Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All enhanced user management tests passed!")
    else:
        print("❌ Some tests failed. Please check the implementation.")
    
    sys.exit(0 if success else 1)