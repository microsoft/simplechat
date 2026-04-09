#!/usr/bin/env python3
# test_video_indexer_dual_authentication_support.py
"""
Functional test for current Video Indexer managed-identity guidance.
Version: 0.241.007
Implemented in: 0.241.007

This legacy-named test now ensures the admin and backend flows reflect the
current managed-identity-only Video Indexer configuration.
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def test_video_indexer_settings_shape():
    """Test that current Video Indexer settings keep ARM fields and omit legacy auth toggles."""
    print("🔍 Testing current Video Indexer settings shape...")

    try:
        settings_file_path = os.path.join('application', 'single_app', 'functions_settings.py')

        if not os.path.exists(settings_file_path):
            print("❌ functions_settings.py not found")
            return False

        with open(settings_file_path, 'r', encoding='utf-8') as file_handle:
            settings_content = file_handle.read()

        required_settings = [
            "'video_indexer_endpoint':",
            "'video_indexer_resource_group':",
            "'video_indexer_subscription_id':",
            "'video_indexer_account_name':",
            "'video_indexer_account_id':",
            "'video_indexer_location':",
        ]

        for setting_name in required_settings:
            if setting_name not in settings_content:
                print(f"❌ Missing Video Indexer setting: {setting_name}")
                return False

        if 'video_indexer_authentication_type' in settings_content:
            print("❌ Legacy video_indexer_authentication_type should not be present")
            return False

        print("✅ Current Video Indexer settings verified")
        return True

    except Exception as exc:
        print(f"❌ Test failed with error: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_authentication_functions():
    """Test that the runtime uses the ARM managed-identity token flow."""
    print("🔍 Testing Video Indexer authentication functions...")

    try:
        auth_file_path = os.path.join('application', 'single_app', 'functions_authentication.py')

        if not os.path.exists(auth_file_path):
            print(f"❌ functions_authentication.py not found at {os.path.abspath(auth_file_path)}")
            return False

        with open(auth_file_path, 'r', encoding='utf-8') as file_handle:
            auth_content = file_handle.read()

        required_functions = [
            'def get_video_indexer_account_token(',
            'def get_video_indexer_managed_identity_token(',
            'DEFAULT_VIDEO_INDEXER_ARM_API_VERSION',
        ]

        for func_name in required_functions:
            if func_name not in auth_content:
                print(f"❌ Missing function or constant: {func_name}")
                return False

        if 'get_video_indexer_api_key_token' in auth_content:
            print("❌ Legacy Video Indexer API key helper should not be present")
            return False

        print("✅ Authentication functions verified")
        return True

    except Exception as exc:
        print(f"❌ Test failed with error: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_video_processing_authentication_support():
    """Test that video processing relies on the ARM token flow."""
    print("🔍 Testing video processing authentication support...")

    try:
        docs_file_path = os.path.join('application', 'single_app', 'functions_documents.py')

        if not os.path.exists(docs_file_path):
            print("❌ functions_documents.py not found")
            return False

        with open(docs_file_path, 'r', encoding='utf-8') as file_handle:
            docs_content = file_handle.read()

        required_patterns = [
            '"accessToken": token',
            'get_video_indexer_account_token',
        ]

        for pattern in required_patterns:
            if pattern not in docs_content:
                print(f"❌ Missing pattern in video processing: {pattern}")
                return False

        print("✅ Video processing authentication support verified")
        return True

    except Exception as exc:
        print(f"❌ Test failed with error: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_admin_ui_authentication_controls():
    """Test that the admin UI reflects the managed-identity-only guidance."""
    print("🔍 Testing admin UI authentication controls...")

    try:
        template_file_path = os.path.join('application', 'single_app', 'templates', 'admin_settings.html')

        if not os.path.exists(template_file_path):
            print("❌ admin_settings.html template not found")
            return False

        with open(template_file_path, 'r', encoding='utf-8') as file_handle:
            template_content = file_handle.read()

        required_ui_elements = [
            'id="video_indexer_cloud"',
            'id="video_indexer_endpoint_display"',
            'id="video_indexer_custom_endpoint_group"',
            'App Service system-assigned managed identity',
            'Video Indexer API keys are not used by the current setup',
        ]

        for element in required_ui_elements:
            if element not in template_content:
                print(f"❌ Missing UI element: {element}")
                return False

        removed_ui_elements = [
            'id="video_indexer_api_key"',
            'id="video_indexer_authentication_type"',
            'toggleVideoIndexerAuthFields',
        ]

        for removed in removed_ui_elements:
            if removed in template_content:
                print(f"❌ Legacy UI element still present: {removed}")
                return False

        print("✅ Admin UI authentication controls verified")
        return True

    except Exception as exc:
        print(f"❌ Test failed with error: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_backend_form_handling():
    """Test that backend persists the current ARM-based Video Indexer fields."""
    print("🔍 Testing backend form handling...")

    try:
        route_file_path = os.path.join('application', 'single_app', 'route_frontend_admin_settings.py')

        if not os.path.exists(route_file_path):
            print("❌ route_frontend_admin_settings.py not found")
            return False

        with open(route_file_path, 'r', encoding='utf-8') as file_handle:
            route_content = file_handle.read()

        required_fields = [
            "'video_indexer_endpoint':",
            "'video_indexer_resource_group':",
            "'video_indexer_subscription_id':",
            "'video_indexer_account_name':",
            "'video_indexer_account_id':",
            "'video_indexer_location':",
        ]

        for field_name in required_fields:
            if field_name not in route_content:
                print(f"❌ Missing backend form field handling: {field_name}")
                return False

        if 'video_indexer_authentication_type' in route_content:
            print("❌ Legacy authentication type form field should not be present")
            return False

        print("✅ Backend form handling verified")
        return True

    except Exception as exc:
        print(f"❌ Test failed with error: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = True

    tests = [
        test_video_indexer_settings_shape,
        test_authentication_functions,
        test_video_processing_authentication_support,
        test_admin_ui_authentication_controls,
        test_backend_form_handling,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        result = test()
        results.append(result)
        if not result:
            success = False

    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")

    if success:
        print("✅ All Video Indexer managed-identity guidance tests passed!")
    else:
        print("❌ Some tests failed")
    
    sys.exit(0 if success else 1)