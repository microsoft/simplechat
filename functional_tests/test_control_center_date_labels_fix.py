# test_control_center_date_labels_fix.py
#!/usr/bin/env python3
"""
Functional test for control center date labels fix.
Version: 0.235.074
Implemented in: 0.235.074

This test ensures control center charts parse YYYY-MM-DD dates in local time
so label text matches the correct day.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def test_control_center_date_label_parsing():
    """Validate local date parsing helper usage in control-center.js charts."""
    print("\n🔍 Testing control center date label parsing...")

    try:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        target_path = os.path.join(
            repo_root,
            "application",
            "single_app",
            "static",
            "js",
            "control-center.js",
        )

        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Expected file not found: {target_path}")

        with open(target_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        required_snippets = [
            "function parseDateKey",
            "parseDateKey(dateStr)",
            "parseDateKey(date)",
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        if missing:
            raise AssertionError(f"Missing date parsing helpers: {missing}")

        print("✅ Control center date label parsing helper detected.")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_control_center_date_label_parsing()
    sys.exit(0 if success else 1)
