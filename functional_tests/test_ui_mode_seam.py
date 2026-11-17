#!/usr/bin/env python3
# test_ui_mode_seam.py
"""
Functional test for the interface-mode seam.
Version: 0.261.445
Implemented in: 0.261.445

``functions_ui_mode.get_ui_mode`` is the single place that decides whether a request is
served the classic (legacy) or the modern (V2) interface. Until the interface selector
exists it must answer classic for everyone, so adding modern page variants and redirect
machinery cannot change what any user sees today.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


ui_mode = import_app_module("functions_ui_mode")


def test_default_mode_is_classic_for_every_caller():
    assert_app_version_at_least("0.261.445")

    assert ui_mode.get_ui_mode() == ui_mode.UI_MODE_CLASSIC
    assert ui_mode.get_ui_mode({"anything": True}, {"anything": True}) == ui_mode.UI_MODE_CLASSIC
    assert ui_mode.is_modern_ui() is False


def test_modes_are_the_two_known_interfaces():
    assert ui_mode.UI_MODES == ("classic", "modern")
    assert ui_mode.get_ui_mode() in ui_mode.UI_MODES


if __name__ == "__main__":
    test_default_mode_is_classic_for_every_caller()
    test_modes_are_the_two_known_interfaces()
    print("Interface-mode seam checks passed.")
