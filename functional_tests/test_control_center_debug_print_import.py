# test_control_center_debug_print_import.py
#!/usr/bin/env python3
"""
Functional test for Control Center debug logging import.
Version: 0.241.029
Implemented in: 0.241.029

This test ensures the Control Center imports debug_print from the shared
functions_debug shim instead of config.py, preventing startup ImportError
regressions when admin settings routes load Control Center helpers.
"""

import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
CONFIG_FILE = APP_DIR / "config.py"
CONTROL_CENTER_FILE = APP_DIR / "functions_control_center.py"
EXPECTED_VERSION = "0.241.029"


def read_file(file_path):
    """Read a repository text file as UTF-8."""
    return file_path.read_text(encoding="utf-8")


def get_config_version():
    """Read the current application version from config.py."""
    config_source = read_file(CONFIG_FILE)
    match = re.search(r'VERSION = "([^"]+)"', config_source)
    if not match:
        raise AssertionError("Could not find VERSION in config.py")
    return match.group(1)


def test_control_center_uses_debug_shim():
    """Validate Control Center imports debug_print from functions_debug."""
    print("Testing Control Center debug_print import source...")
    control_center_source = read_file(CONTROL_CENTER_FILE)

    if "from functions_debug import debug_print" not in control_center_source:
        raise AssertionError("functions_control_center.py must import debug_print from functions_debug")

    if "from config import debug_print" in control_center_source:
        raise AssertionError("functions_control_center.py must not import debug_print from config.py")

    if get_config_version() != EXPECTED_VERSION:
        raise AssertionError(f"Expected config VERSION {EXPECTED_VERSION}, found {get_config_version()}")

    print("Control Center debug_print import source is correct.")
    return True


if __name__ == "__main__":
    try:
        success = test_control_center_uses_debug_shim()
        sys.exit(0 if success else 1)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)