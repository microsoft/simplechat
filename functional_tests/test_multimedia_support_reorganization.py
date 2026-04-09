#!/usr/bin/env python3
# test_multimedia_support_reorganization.py
"""
Functional test for multimedia support reorganization and shared speech guidance.
Version: 0.241.010
Implemented in: 0.241.010

This test ensures that:
1. Multimedia Support remains in the Search and Extract tab
2. The Video Indexer modal reflects the managed-identity-only ARM setup
3. The AI Voice setup guide is integrated with the shared Speech settings
4. Shared Speech and Video Indexer settings are accessible in the current admin UI
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def test_multimedia_support_move():
    """Test that multimedia support remains in the Search and Extract tab."""
    print("🔍 Testing Multimedia Support section location...")

    try:
        admin_settings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'admin_settings.html'
        )

        with open(admin_settings_path, 'r', encoding='utf-8') as file_handle:
            content = file_handle.read()

        search_extract_section = content.find('id="search-extract" role="tabpanel"')
        multimedia_support_section = content.find('id="video-intelligence-section"')

        if search_extract_section == -1:
            print("❌ Search and Extract tab not found")
            return False

        if multimedia_support_section == -1:
            print("❌ Multimedia Support section not found")
            return False

        if multimedia_support_section < search_extract_section:
            print("❌ Multimedia Support section is not within Search and Extract")
            return False

        print("✅ Multimedia Support section is in Search and Extract")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_video_indexer_modal():
    """Test that Video Indexer configuration modal is properly integrated."""
    print("🔍 Testing Video Indexer configuration modal...")

    try:
        modal_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', '_video_indexer_info.html'
        )

        if not os.path.exists(modal_path):
            print("❌ Video Indexer modal template file not found")
            return False

        with open(modal_path, 'r', encoding='utf-8') as file_handle:
            modal_content = file_handle.read()

        required_elements = [
            'id="videoIndexerInfoModal"',
            'Azure AI Video Indexer Configuration Guide',
            'Cloud / Endpoint Mode',
            'App Service system-assigned managed identity',
            'Contributor role',
            'updateVideoIndexerModalInfo()'
        ]

        for element in required_elements:
            if element not in modal_content:
                print(f"❌ Missing modal element: {element}")
                return False

        admin_settings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'admin_settings.html'
        )

        with open(admin_settings_path, 'r', encoding='utf-8') as file_handle:
            admin_content = file_handle.read()

        if '_video_indexer_info.html' not in admin_content:
            print("❌ Video Indexer modal not included in admin_settings.html")
            return False

        if 'data-bs-target="#videoIndexerInfoModal"' not in admin_content:
            print("❌ Video Indexer modal trigger button not found")
            return False

        print("✅ Video Indexer configuration modal properly integrated")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_speech_service_modal():
    """Test that the AI Voice configuration modal is properly integrated."""
    print("🔍 Testing AI Voice configuration modal...")

    try:
        modal_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', '_speech_service_info.html'
        )

        if not os.path.exists(modal_path):
            print("❌ Speech Service modal template file not found")
            return False

        with open(modal_path, 'r', encoding='utf-8') as file_handle:
            modal_content = file_handle.read()

        required_elements = [
            'id="speechServiceInfoModal"',
            'Azure AI Voice Conversations Configuration Guide',
            'Cognitive Services Speech User',
            'custom-domain Speech endpoint',
            'Generate Custom Domain Name',
            'Keys and Endpoint',
            'updateSpeechServiceModalInfo()'
        ]

        for element in required_elements:
            if element not in modal_content:
                print(f"❌ Missing Speech modal element: {element}")
                return False

        admin_settings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'admin_settings.html'
        )

        with open(admin_settings_path, 'r', encoding='utf-8') as file_handle:
            admin_content = file_handle.read()

        if '_speech_service_info.html' not in admin_content:
            print("❌ Speech Service modal not included in admin_settings.html")
            return False

        if 'data-bs-target="#speechServiceInfoModal"' not in admin_content:
            print("❌ Speech Service modal trigger button not found")
            return False

        print("✅ AI Voice configuration modal properly integrated")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_multimedia_settings_preserved():
    """Test that all multimedia settings are preserved in the new location."""
    print("🔍 Testing multimedia settings preservation...")

    try:
        admin_settings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'admin_settings.html'
        )

        with open(admin_settings_path, 'r', encoding='utf-8') as file_handle:
            content = file_handle.read()

        video_settings = [
            'id="enable_video_file_support"',
            'id="video_indexer_cloud"',
            'id="video_indexer_endpoint"',
            'id="video_indexer_endpoint_display"',
            'id="video_indexer_custom_endpoint"',
            'id="video_indexer_account_id"',
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

        audio_settings = [
            'id="enable_audio_file_support"',
            'id="enable_speech_to_text_input"',
            'id="enable_text_to_speech"',
            'id="speech_service_endpoint"',
            'id="speech_service_location"',
            'id="speech_service_subscription_id"',
            'id="speech_service_resource_group"',
            'id="speech_service_resource_name"',
            'id="speech_service_locale"',
            'id="speech_service_authentication_type"',
            'id="speech_service_resource_id"',
            'id="speech_service_key"'
        ]

        for setting in audio_settings:
            if setting not in content:
                print(f"❌ Missing audio setting: {setting}")
                return False

        if 'video_indexer_api_key' in content:
            print("❌ Legacy Video Indexer API key field should not be present")
            return False

        print("✅ All multimedia settings preserved in current location")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_version_update():
    """Test that the version has been updated in config.py."""
    print("🔍 Testing version update...")

    try:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'config.py'
        )

        with open(config_path, 'r', encoding='utf-8') as file_handle:
            content = file_handle.read()

        if 'VERSION = "0.241.010"' not in content:
            print("❌ Version not updated to 0.241.010")
            return False

        print("✅ Version successfully updated to 0.241.010")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_multimedia_support_move,
        test_video_indexer_modal,
        test_speech_service_modal,
        test_multimedia_settings_preserved,
        test_version_update,
    ]

    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")

    if success:
        print("✅ All tests passed! Multimedia support guidance matches the current shared Speech and Video Indexer configuration.")
    else:
        print("❌ Some tests failed. Please review the changes.")

    sys.exit(0 if success else 1)
