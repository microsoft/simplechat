#!/usr/bin/env python3
# test_ui_mode_seam.py
"""
Functional test for the interface-mode seam.
Version: 0.261.449
Implemented in: 0.261.448

``functions_ui_mode.get_ui_mode`` is the single place that decides whether a request is
served the classic (legacy) or modern interface. Policy overrides the account choice,
which overrides the modern default.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


ui_mode = import_app_module("functions_ui_mode")


def test_default_mode_is_modern_for_unconfigured_callers():
    assert_app_version_at_least("0.261.449")

    assert ui_mode.get_ui_mode() == ui_mode.UI_MODE_MODERN
    assert ui_mode.get_ui_mode({"anything": True}, {"anything": True}) == ui_mode.UI_MODE_MODERN
    assert ui_mode.is_modern_ui() is True


def test_policy_overrides_but_does_not_erase_account_choice():
    preference = {"settings": {"preferredUiMode": "classic"}}
    for default in ui_mode.UI_MODES:
        settings = {"ui_mode_policy": "both", "ui_default_mode": default}
        assert ui_mode.get_ui_mode(settings, preference) == "classic"
        assert ui_mode.get_ui_mode(settings, {}) == default
        for policy in ui_mode.UI_MODES:
            settings["ui_mode_policy"] = policy
            result = ui_mode.get_ui_policy(settings, preference)
            assert result["effective"] == policy
            assert result["can_switch"] is False
        settings["ui_mode_policy"] = "both"
        assert ui_mode.get_ui_mode(settings, preference) == "classic"
    assert preference == {"settings": {"preferredUiMode": "classic"}}


def test_invalid_enum_writes_are_refused():
    for value in (None, True, [], {}, "legacy", "MODERN", ""):
        for key in ("ui_mode_policy", "ui_default_mode", "preferredUiMode"):
            try:
                ui_mode.validate_ui_setting(key, value)
            except ValueError:
                continue
            raise AssertionError(f"{key} accepted {value!r}")


def test_modes_are_the_two_known_interfaces():
    assert ui_mode.UI_MODES == ("classic", "modern")
    assert ui_mode.get_ui_mode() in ui_mode.UI_MODES


if __name__ == "__main__":
    test_default_mode_is_modern_for_unconfigured_callers()
    test_policy_overrides_but_does_not_erase_account_choice()
    test_invalid_enum_writes_are_refused()
    test_modes_are_the_two_known_interfaces()
    print("Interface-mode seam checks passed.")
