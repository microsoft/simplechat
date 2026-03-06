#!/usr/bin/env python3
"""
Functional test for Processing Thoughts feature.
Version: 0.239.003
Implemented in: 0.239.003

This test ensures that the Processing Thoughts feature is properly implemented
across backend (ThoughtTracker, API endpoints, chat instrumentation) and
frontend (polling, streaming, toggle, rendering) components.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'application', 'single_app'))


def test_thoughts_backend_module():
    """Test that functions_thoughts.py has proper ThoughtTracker and CRUD functions."""
    print("Testing functions_thoughts.py module structure...")
    try:
        backend_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'functions_thoughts.py'
        )

        with open(backend_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'ThoughtTracker class': 'class ThoughtTracker' in content,
            'add_thought method': 'def add_thought' in content,
            'complete_thought method': 'def complete_thought' in content,
            'enabled property': 'def enabled' in content or 'enabled' in content,
            'get_thoughts_for_message': 'def get_thoughts_for_message' in content,
            'get_pending_thoughts': 'def get_pending_thoughts' in content,
            'archive_thoughts_for_conversation': 'def archive_thoughts_for_conversation' in content,
            'delete_thoughts_for_conversation': 'def delete_thoughts_for_conversation' in content,
            'delete_thoughts_for_message': 'def delete_thoughts_for_message' in content,
            'cosmos_thoughts_container import': 'cosmos_thoughts_container' in content,
            'step_index tracking': 'step_index' in content,
            'step_type field': 'step_type' in content,
            'error handling (try/except)': 'except Exception' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_route_module():
    """Test that route_backend_thoughts.py has proper API endpoints."""
    print("\nTesting route_backend_thoughts.py API endpoints...")
    try:
        route_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'route_backend_thoughts.py'
        )

        with open(route_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'register function': 'def register_route_backend_thoughts' in content,
            'message thoughts endpoint': '/messages/' in content and '/thoughts' in content,
            'pending thoughts endpoint': '/thoughts/pending' in content,
            'swagger_route decorator': 'swagger_route' in content,
            'login_required decorator': 'login_required' in content,
            'user_required decorator': 'user_required' in content,
            'get_auth_security import': 'get_auth_security' in content,
            'enable_thoughts check': 'enable_thoughts' in content,
            'returns enabled flag': "'enabled'" in content or '"enabled"' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_chat_instrumentation():
    """Test that route_backend_chats.py has thought instrumentation points."""
    print("\nTesting route_backend_chats.py thought instrumentation...")
    try:
        chats_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'route_backend_chats.py'
        )

        with open(chats_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'ThoughtTracker import': 'ThoughtTracker' in content,
            'thought_tracker instantiation': 'thought_tracker' in content and 'ThoughtTracker(' in content,
            'add_thought calls': 'thought_tracker.add_thought' in content,
            'content_safety thought': "'content_safety'" in content or '"content_safety"' in content,
            'search thought': "add_thought('search'" in content or 'add_thought("search"' in content,
            'web_search thought': "'web_search'" in content or '"web_search"' in content,
            'generation thought': "'generation'" in content or '"generation"' in content,
            'thoughts_enabled in response': 'thoughts_enabled' in content,
            'SSE thought event (streaming)': '"type": "thought"' in content or "'type': 'thought'" in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_frontend_module():
    """Test that chat-thoughts.js has polling, streaming, and toggle logic."""
    print("\nTesting chat-thoughts.js frontend module...")
    try:
        js_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'static', 'js', 'chat', 'chat-thoughts.js'
        )

        with open(js_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'startThoughtPolling export': 'export function startThoughtPolling' in content,
            'stopThoughtPolling export': 'export function stopThoughtPolling' in content,
            'handleStreamingThought export': 'export function handleStreamingThought' in content,
            'createThoughtsToggleHtml export': 'export function createThoughtsToggleHtml' in content,
            'attachThoughtsToggleListener export': 'export function attachThoughtsToggleListener' in content,
            'polling interval setup': 'setInterval' in content,
            'polling endpoint fetch': '/thoughts/pending' in content,
            'message thoughts fetch': '/thoughts' in content,
            'icon map (search)': 'bi-search' in content,
            'icon map (globe)': 'bi-globe' in content,
            'icon map (robot)': 'bi-robot' in content,
            'icon map (lightning)': 'bi-lightning' in content,
            'icon map (shield)': 'bi-shield-check' in content,
            'enable_thoughts check': 'enable_thoughts' in content,
            'd-none toggle': 'd-none' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_chat_messages_integration():
    """Test that chat-messages.js integrates thought polling and toggle."""
    print("\nTesting chat-messages.js thoughts integration...")
    try:
        messages_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'static', 'js', 'chat', 'chat-messages.js'
        )

        with open(messages_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'chat-thoughts import': 'chat-thoughts' in content,
            'startThoughtPolling import': 'startThoughtPolling' in content,
            'stopThoughtPolling import': 'stopThoughtPolling' in content,
            'createThoughtsToggleHtml import': 'createThoughtsToggleHtml' in content,
            'attachThoughtsToggleListener import': 'attachThoughtsToggleListener' in content,
            'startThoughtPolling call': 'startThoughtPolling(' in content,
            'stopThoughtPolling call': 'stopThoughtPolling(' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_streaming_integration():
    """Test that chat-streaming.js handles thought SSE events."""
    print("\nTesting chat-streaming.js thought event handling...")
    try:
        streaming_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'static', 'js', 'chat', 'chat-streaming.js'
        )

        with open(streaming_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'handleStreamingThought import': 'handleStreamingThought' in content,
            'thought type check': "'thought'" in content or '"thought"' in content,
            'handleStreamingThought call': 'handleStreamingThought(' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_loading_indicator():
    """Test that chat-loading-indicator.js supports thought text updates."""
    print("\nTesting chat-loading-indicator.js thought text support...")
    try:
        indicator_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'static', 'js', 'chat', 'chat-loading-indicator.js'
        )

        with open(indicator_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'updateLoadingIndicatorText export': 'export function updateLoadingIndicatorText' in content
                                                  or 'updateLoadingIndicatorText' in content,
            'text element update': 'thought-live-text' in content or 'loading-text' in content
                                   or 'textContent' in content or 'innerHTML' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_admin_settings():
    """Test that admin settings UI includes the thoughts toggle."""
    print("\nTesting admin settings UI for thoughts toggle...")
    try:
        html_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'templates', 'admin_settings.html'
        )

        with open(html_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'enable_thoughts checkbox': 'id="enable_thoughts"' in content,
            'enable_thoughts name attr': 'name="enable_thoughts"' in content,
            'Processing Thoughts label': 'Processing Thoughts' in content,
            'lightbulb icon': 'bi-lightbulb' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_settings_default():
    """Test that functions_settings.py includes enable_thoughts default."""
    print("\nTesting functions_settings.py default setting...")
    try:
        settings_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'functions_settings.py'
        )

        with open(settings_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'enable_thoughts in defaults': 'enable_thoughts' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_cosmos_containers():
    """Test that config.py defines thoughts Cosmos DB containers."""
    print("\nTesting config.py Cosmos DB container definitions...")
    try:
        config_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'config.py'
        )

        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'thoughts container name': 'cosmos_thoughts_container_name' in content,
            'thoughts container object': 'cosmos_thoughts_container' in content,
            'archive_thoughts container name': 'cosmos_archived_thoughts_container_name' in content,
            'archive_thoughts container object': 'cosmos_archived_thoughts_container' in content,
            'partition key /user_id': '/user_id' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_conversation_archive():
    """Test that route_backend_conversations.py handles thought archive/delete."""
    print("\nTesting route_backend_conversations.py thought archive support...")
    try:
        conv_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'route_backend_conversations.py'
        )

        with open(conv_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'archive_thoughts_for_conversation import': 'archive_thoughts_for_conversation' in content,
            'delete_thoughts_for_conversation import': 'delete_thoughts_for_conversation' in content,
            'archive_thoughts call': 'archive_thoughts_for_conversation(' in content,
            'delete_thoughts call': 'delete_thoughts_for_conversation(' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_css_styles():
    """Test that chats.css includes thought-related styles."""
    print("\nTesting chats.css thought styles...")
    try:
        css_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'static', 'css', 'chats.css'
        )

        with open(css_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'thoughts-toggle-btn style': '.thoughts-toggle-btn' in content,
            'thoughts-container style': '.thoughts-container' in content,
            'thought-step style': '.thought-step' in content,
            'animate-pulse animation': '.animate-pulse' in content,
            'thought-pulse keyframes': '@keyframes thought-pulse' in content,
            'dark mode thoughts toggle': '[data-bs-theme="dark"] .thoughts-toggle-btn' in content,
            'dark mode thought step': '[data-bs-theme="dark"] .thought-step' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


def test_thoughts_app_registration():
    """Test that app.py registers the thoughts route blueprint."""
    print("\nTesting app.py route registration...")
    try:
        app_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'application', 'single_app', 'app.py'
        )

        with open(app_file, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            'import register function': 'register_route_backend_thoughts' in content,
            'register call': 'register_route_backend_thoughts(app)' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f"  [{status}] {name}")
            if not passed:
                all_passed = False

        return all_passed

    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Processing Thoughts Feature - Functional Tests")
    print("Version: 0.239.003")
    print("=" * 60)

    tests = [
        test_thoughts_backend_module,
        test_thoughts_route_module,
        test_thoughts_chat_instrumentation,
        test_thoughts_frontend_module,
        test_thoughts_chat_messages_integration,
        test_thoughts_streaming_integration,
        test_thoughts_loading_indicator,
        test_thoughts_admin_settings,
        test_thoughts_settings_default,
        test_thoughts_cosmos_containers,
        test_thoughts_conversation_archive,
        test_thoughts_css_styles,
        test_thoughts_app_registration,
    ]

    results = []
    for test_fn in tests:
        try:
            result = test_fn()
            results.append(result)
        except Exception as e:
            print(f"  [FAIL] Unhandled exception: {e}")
            results.append(False)

    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Results: {passed}/{total} test groups passed")

    if passed == total:
        print("All tests passed!")
    else:
        print("Some tests failed. Review output above.")

    print("=" * 60)
    sys.exit(0 if passed == total else 1)
