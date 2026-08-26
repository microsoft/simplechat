#!/usr/bin/env python3
# test_chat_fact_memory_admin_placement.py
"""
Functional test for the Chat-owned fact memory admin control.
Version: 0.261.001
Implemented in: 0.261.001

Fact memory used to be configured only from Agents & Actions, which hid a plain-chat
capability behind an agents workflow. The live toggle now lives in Chat > Chat Experience
and the Actions pane carries a read-only pointer, mirroring how Tabular Processing points
at Enhanced Citations.

This test locks in that placement and, critically, guards the save-path hazard it created:
the Actions toggle used to post through /api/admin/plugins/settings where the key was a
REQUIRED field. If the input is removed but the JavaScript payload or the endpoint contract
still carries the key, changing any unrelated core plugin would silently disable fact
memory. Refs #1352.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.nav import ADMIN_NAV  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, 'application', 'single_app')
PANES_DIR = os.path.join(APP_DIR, 'templates', 'admin', '_panes')
CHAT_PANE = os.path.join(PANES_DIR, 'chat-experience.html')
ACTIONS_PANE = os.path.join(PANES_DIR, 'actions.html')
ADMIN_SETTINGS_TEMPLATE = os.path.join(APP_DIR, 'templates', 'admin_settings.html')
ADMIN_SETTINGS_JS = os.path.join(APP_DIR, 'static', 'js', 'admin', 'admin_settings.js')
ADMIN_SETTINGS_ROUTE = os.path.join(APP_DIR, 'route_frontend_admin_settings.py')
PLUGINS_ROUTE = os.path.join(APP_DIR, 'route_backend_plugins.py')
SETTINGS_MODULE = os.path.join(APP_DIR, 'functions_settings.py')

SETTING_KEY = 'enable_fact_memory_plugin'


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_toggle_lives_in_the_chat_pane():
    """The live control renders in Chat > Chat Experience inside its own card."""
    print("🔍 Testing fact memory toggle placement in the Chat pane...")

    try:
        chat_pane = read_file_text(CHAT_PANE)

        assert 'id="fact-memory-section"' in chat_pane, \
            'Expected a fact-memory-section card in chat-experience.html'
        assert f'name="{SETTING_KEY}"' in chat_pane, \
            'Expected the fact memory form field in chat-experience.html'
        assert '{% if settings.enable_fact_memory_plugin %}checked{% endif %}' in chat_pane, \
            'Expected the Chat toggle to render current state from settings'

        card_match = re.search(
            r'id="fact-memory-section".*?(?=<div class="card|\Z)',
            chat_pane,
            re.DOTALL,
        )
        assert card_match, 'Could not isolate the fact-memory-section card'
        card_html = card_match.group(0)
        assert f'name="{SETTING_KEY}"' in card_html, \
            'The fact memory field must live inside the fact-memory-section card'
        assert 'does not require agents or actions' in card_html, \
            'The Chat card must state that agents and actions are not required'
        assert 'Profile' in card_html, \
            'The Chat card should point users at Profile for managing their own memories'

        print("✅ Chat pane placement passed!")
        return True
    except Exception as e:
        print(f"❌ Chat pane placement failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_actions_pane_shows_a_read_only_pointer():
    """The Actions pane no longer owns the control and points at Chat instead."""
    print("🔍 Testing Actions pane read-only dependency note...")

    try:
        actions_pane = read_file_text(ACTIONS_PANE)

        assert 'toggle-fact-memory-plugin' not in actions_pane, \
            'The Actions pane must not keep a fact memory toggle input'
        assert f'name="{SETTING_KEY}"' not in actions_pane, \
            'The Actions pane must not submit the fact memory form field'
        assert 'id="fact-memory-dependency-note"' in actions_pane, \
            'Expected a fact-memory-dependency-note in the Actions pane'
        assert 'Chat Experience' in actions_pane, \
            'The Actions note must tell admins where the setting now lives'

        print("✅ Actions pane pointer passed!")
        return True
    except Exception as e:
        print(f"❌ Actions pane pointer failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_single_form_field_across_admin_settings():
    """Only one admin form field may carry the key, or the form POST becomes ambiguous."""
    print("🔍 Testing for duplicate fact memory form fields...")

    try:
        template_paths = [ADMIN_SETTINGS_TEMPLATE]
        for entry in sorted(os.listdir(PANES_DIR)):
            if entry.endswith('.html'):
                template_paths.append(os.path.join(PANES_DIR, entry))

        owners = []
        for template_path in template_paths:
            occurrences = read_file_text(template_path).count(f'name="{SETTING_KEY}"')
            if occurrences:
                owners.append((os.path.basename(template_path), occurrences))

        assert owners == [('chat-experience.html', 1)], \
            f'Expected exactly one fact memory form field, in chat-experience.html. Found: {owners}'

        print("✅ Single form field ownership passed!")
        return True
    except Exception as e:
        print(f"❌ Single form field ownership failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_navigation_registers_the_section():
    """The section id must be registered so the tab strip and sidebar can reach it."""
    print("🔍 Testing admin navigation registration...")

    try:
        chat_experience_sections = None
        for group in ADMIN_NAV:
            for tab in group.get('tabs', []):
                if tab.get('id') == 'chat-experience':
                    chat_experience_sections = [
                        section.get('id') for section in tab.get('sections', [])
                    ]

        assert chat_experience_sections is not None, 'chat-experience tab not found in ADMIN_NAV'
        assert 'fact-memory-section' in chat_experience_sections, \
            f'fact-memory-section missing from chat-experience sections: {chat_experience_sections}'

        print("✅ Navigation registration passed!")
        return True
    except Exception as e:
        print(f"❌ Navigation registration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_admin_form_persists_the_setting():
    """The main admin settings form POST must actually write the key."""
    print("🔍 Testing admin settings form persistence...")

    try:
        route_source = read_file_text(ADMIN_SETTINGS_ROUTE)

        assert f"'{SETTING_KEY}': form_data.get('{SETTING_KEY}') == 'on'" in route_source, \
            'The admin settings form handler must persist enable_fact_memory_plugin'

        print("✅ Admin form persistence passed!")
        return True
    except Exception as e:
        print(f"❌ Admin form persistence failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_plugins_endpoint_no_longer_owns_the_key():
    """The core plugins endpoint must not require or write the Chat-owned key.

    This is the regression that would silently disable fact memory whenever an admin
    toggled an unrelated core plugin.
    """
    print("🔍 Testing core plugins endpoint contract...")

    try:
        plugins_source = read_file_text(PLUGINS_ROUTE)

        expected_block = re.search(
            r'expected_keys\s*=\s*\[(.*?)\]',
            plugins_source,
            re.DOTALL,
        )
        assert expected_block, 'Could not locate expected_keys in route_backend_plugins.py'
        assert SETTING_KEY not in expected_block.group(1), \
            'enable_fact_memory_plugin must not be a required field on the plugins endpoint'

        deprecated_block = re.search(
            r'deprecated_optional_keys\s*=\s*\[(.*?)\]',
            plugins_source,
            re.DOTALL,
        )
        assert deprecated_block, 'Could not locate deprecated_optional_keys in route_backend_plugins.py'
        assert SETTING_KEY in deprecated_block.group(1), \
            'enable_fact_memory_plugin should stay accepted-but-ignored for older clients'

        assert f"'{SETTING_KEY}': bool(settings.get('{SETTING_KEY}'" in plugins_source, \
            'The plugins GET response should still expose the value for the Actions note'

        print("✅ Plugins endpoint contract passed!")
        return True
    except Exception as e:
        print(f"❌ Plugins endpoint contract failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_admin_javascript_no_longer_posts_the_key():
    """admin_settings.js must not send the key, and must render the dependency note."""
    print("🔍 Testing admin_settings.js core plugin wiring...")

    try:
        js_source = read_file_text(ADMIN_SETTINGS_JS)

        assert 'factMemoryToggle' not in js_source, \
            'admin_settings.js must not reference the removed fact memory toggle'
        assert 'toggle-fact-memory-plugin' not in js_source, \
            'admin_settings.js must not look up the removed toggle element id'
        assert f'{SETTING_KEY}:' not in js_source, \
            'admin_settings.js must not include enable_fact_memory_plugin in the plugins payload'
        assert "getElementById('fact-memory-dependency-note')" in js_source, \
            'admin_settings.js should refresh the Actions dependency note'
        assert f'settings.{SETTING_KEY}' in js_source, \
            'The dependency note should reflect the value returned by the plugins GET endpoint'

        print("✅ Admin JavaScript wiring passed!")
        return True
    except Exception as e:
        print(f"❌ Admin JavaScript wiring failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_settings_helper_exists():
    """A named helper keeps the 'chat capability, not an action' intent in one place."""
    print("🔍 Testing is_fact_memory_enabled helper...")

    try:
        settings_source = read_file_text(SETTINGS_MODULE)

        assert 'def is_fact_memory_enabled(settings):' in settings_source, \
            'Expected is_fact_memory_enabled in functions_settings.py'
        assert 'never requires agents or actions' in settings_source, \
            'The helper docstring should record why fact memory is a chat capability'

        assert_app_version_at_least('0.261.001')

        print("✅ Settings helper passed!")
        return True
    except Exception as e:
        print(f"❌ Settings helper failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_toggle_lives_in_the_chat_pane,
        test_actions_pane_shows_a_read_only_pointer,
        test_single_form_field_across_admin_settings,
        test_navigation_registers_the_section,
        test_admin_form_persists_the_setting,
        test_plugins_endpoint_no_longer_owns_the_key,
        test_admin_javascript_no_longer_posts_the_key,
        test_settings_helper_exists,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
