#!/usr/bin/env python3
# test_context_usage_display_setting.py
"""
Functional test for the admin setting that shows or hides context usage.
Version: 0.261.489
Implemented in: 0.261.489

This test ensures that administrators can hide the context usage display from users in the
Chat settings, that it is on by default, that both admin interfaces offer and save it, that
the modern chat interface hides the ring and the Context tab when it is off, and that the
server keeps recording usage either way.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
UI = ROOT / "application" / "v2_ui" / "src"
SETTING = "enable_context_usage_display"


def _read(path):
    return path.read_text(encoding="utf-8")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"context_usage_setting_{name}", APP / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setting_defaults_on_and_is_offered_in_chat_settings():
    """The setting is on by default and sits in the Chat group of the modern admin settings."""
    assert f"'{SETTING}': True," in _read(APP / "functions_settings.py")

    fields = _load("admin_settings_fields").ADMIN_SETTINGS_FIELDS["context-usage-section"]
    assert [field["key"] for field in fields] == [SETTING]
    field = fields[0]
    assert field["type"] == "switch" and field["default"] is True
    # The help text tells the administrator that hiding the display does not stop recording.
    assert "still" in field["help"] and "recorded" in field["help"]

    nav = _load("admin_settings_nav").ADMIN_NAV
    chat = next(group for group in nav if group["id"] == "chat")
    experience = next(tab for tab in chat["tabs"] if tab["id"] == "chat-experience")
    assert "context-usage-section" in [section["id"] for section in experience["sections"]]


def test_classic_admin_settings_offer_and_save_the_setting():
    """The classic form posts every switch, so a missing input would turn the setting off."""
    pane = _read(APP / "templates" / "admin" / "_panes" / "chat-experience.html")
    assert 'id="context-usage-section"' in pane
    assert f'name="{SETTING}"' in pane
    assert "{% if settings." + SETTING + " %}checked{% endif %}" in pane

    route = _read(APP / "route_frontend_admin_settings.py")
    assert f"'{SETTING}': form_data.get('{SETTING}') == 'on'," in route
    # Settings saved before the setting existed open with it on.
    assert f"if '{SETTING}' not in settings:\n            settings['{SETTING}'] = True" in route.replace("\r\n", "\n")


def test_modern_chat_hides_the_display_when_the_setting_is_off():
    """One hook decides; the ring, the header button and the Context tab all follow it."""
    usage = _read(UI / "components" / "chat" / "ContextUsage.tsx")
    # Only an explicit false hides it, so settings that predate the setting keep the display.
    assert f"state.data?.features?.{SETTING} !== false" in usage
    assert "enabled ? readContextUsage(messages, selectedModel) : null" in usage

    drawer = _read(UI / "components" / "chat" / "ConversationDrawer.tsx")
    assert "const contextUsageEnabled = useContextUsageEnabled();" in drawer
    assert "...(contextUsageEnabled" in drawer
    assert "drawerMode === 'context' && !contextUsageEnabled" in drawer

    # The composer ring and the header button render nothing without a usage reading.
    assert "const usage = useContextUsage();\n" in usage.replace("\r\n", "\n")
    assert "const contextUsage = useContextUsage();" in _read(UI / "pages" / "ChatPage.tsx")


def test_recording_does_not_depend_on_the_setting():
    """The setting hides the display only: nothing on the server reads it."""
    for name in (
        "route_backend_chats.py", "functions_context_usage.py", "functions_orchestration_usage.py",
        "functions_orchestration_execution.py", "functions_chat_model_catalog.py",
    ):
        assert SETTING not in _read(APP / name), name
    # The modern interface receives it with the other boolean feature settings.
    bootstrap = _read(APP / "route_backend_v2.py")
    assert 'if key.startswith("enable_") and isinstance(value, bool)' in bootstrap


def run_all():
    tests = [
        test_setting_defaults_on_and_is_offered_in_chat_settings,
        test_classic_admin_settings_offer_and_save_the_setting,
        test_modern_chat_hides_the_display_when_the_setting_is_off,
        test_recording_does_not_depend_on_the_setting,
    ]
    for test in tests:
        print(f"Testing {test.__name__}...")
        try:
            test()
            print("Test passed!")
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback
            traceback.print_exc()
            return False
    return True


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
