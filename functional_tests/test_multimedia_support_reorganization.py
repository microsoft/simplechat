#!/usr/bin/env python3
"""
Functional test for multimedia support reorganization and Video Indexer configuration modal.
Version: 0.229.017
Implemented in: 0.229.017

This test ensures that:
1. Multimedia Support section has been moved from Other tab to Search and Extract tab
2. Video Indexer configuration modal is properly integrated
3. All multimedia settings are accessible in the new location
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_multimedia_support_move():
    """Test that multimedia support has been moved to Search and Extract tab."""
    print("🔍 Testing Multimedia Support section move...")
    
    try:
        # Read the admin_settings.html file
        admin_settings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 'templates', 'admin_settings.html'
        )
        
        with open(admin_settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that multimedia support is in search-extract tab
        search_extract_section = content.find('id="search-extract" role="tabpanel"')
        multimedia_support_section = content.find('<h5 class="mb-0">Multimedia Support</h5>')
        
        if search_extract_section == -1:
            print("❌ Search and Extract tab not found")
            return False
            
        if multimedia_support_section == -1:
            print("❌ Multimedia Support section not found")
            return False
        
        # Check that multimedia support appears after the search-extract tab
        if multimedia_support_section < search_extract_section:
            print("❌ Multimedia Support section not in Search and Extract tab")
            return False
        
        # Find the end of search-extract tab
        search_extract_end = content.find('</div>', content.find('id="other" role="tabpanel"'))
        
        if multimedia_support_section > search_extract_end:
            print("❌ Multimedia Support section appears to be outside Search and Extract tab")
            return False
        
        print("✅ Multimedia Support section successfully moved to Search and Extract tab")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_video_indexer_modal():
    """Test that Video Indexer configuration modal is properly integrated."""
    print("🔍 Testing Video Indexer configuration modal...")
    
    try:
        # Check that the modal template file exists
        modal_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 'templates', '_video_indexer_info.html'
        )
        
        if not os.path.exists(modal_path):
            print("❌ Video Indexer modal template file not found")
            return False
        
        # Read the modal template
        with open(modal_path, 'r', encoding='utf-8') as f:
            modal_content = f.read()
        
        # Check for essential modal components
        required_elements = [
            'id="videoIndexerInfoModal"',
            'Azure AI Video Indexer Configuration Guide',
            'Create Azure AI Video Indexer Account',
            'Get API Keys and Configuration',
            'Configuration Values Reference',
            'updateVideoIndexerModalInfo()'
        ]
        
        for element in required_elements:
            if element not in modal_content:
                print(f"❌ Missing modal element: {element}")
                return False
        
        # Check that admin_settings.html includes the modal
        admin_settings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 'templates', 'admin_settings.html'
        )
        
        with open(admin_settings_path, 'r', encoding='utf-8') as f:
            admin_content = f.read()
        
        if "_video_indexer_info.html" not in admin_content:
            print("❌ Video Indexer modal not included in admin_settings.html")
            return False
        
        # Check for the modal trigger button
        if 'data-bs-target="#videoIndexerInfoModal"' not in admin_content:
            print("❌ Video Indexer modal trigger button not found")
            return False
        
        print("✅ Video Indexer configuration modal properly integrated")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_multimedia_settings_preserved():
    """Test that all multimedia settings are preserved in the new location."""
    print("🔍 Testing multimedia settings preservation...")
    
    try:
        # Read the admin_settings.html file
        admin_settings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 'templates', 'admin_settings.html'
        )
        
        with open(admin_settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for video file support settings
        video_settings = [
            'id="enable_video_file_support"',
            'id="video_indexer_endpoint"',
            'id="video_indexer_account_id"',
            'id="video_indexer_api_key"',
            'id="video_indexer_location"',
            'id="video_indexer_resource_group"',
            'id="video_indexer_subscription_id"',
            'id="video_indexer_account_name"',
            'id="video_index_timeout"'
        ]
        
        for setting in video_settings:
            if setting not in content:
                print(f"❌ Missing video setting: {setting}")
                return False
        
        # Check for audio file support settings
        audio_settings = [
            'id="enable_audio_file_support"',
            'id="speech_service_endpoint"',
            'id="speech_service_location"',
            'id="speech_service_locale"',
            'id="speech_service_key"'
        ]
        
        for setting in audio_settings:
            if setting not in content:
                print(f"❌ Missing audio setting: {setting}")
                return False
        
        # Check for Enhanced Citations reference
        if 'Enhanced Citations' not in content:
            print("❌ Enhanced Citations reference not found")
            return False
        
        print("✅ All multimedia settings preserved in new location")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_update():
    """Test that the version has been updated in config.py."""
    print("🔍 Testing version update...")
    
    try:
        # Read the config.py file
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 'config.py'
        )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for version update
        if 'VERSION = "0.229.017"' not in content:
            print("❌ Version not updated to 0.229.017")
            return False
        
        print("✅ Version successfully updated to 0.229.017")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_multimedia_support_move,
        test_video_indexer_modal,
        test_multimedia_settings_preserved,
        test_version_update
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All tests passed! Multimedia support successfully moved to Search and Extract tab with Video Indexer configuration modal.")
    else:
        print("❌ Some tests failed. Please review the changes.")
    
    sys.exit(0 if success else 1)
