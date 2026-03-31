# test_model_endpoints_save_toast_message.py
#!/usr/bin/env python3
"""
Functional test for model endpoint save toast messaging.
Version: 0.236.022
Implemented in: 0.236.022

This test ensures the save toast reminds admins to save settings to persist changes.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_model_endpoints_save_toast_message():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    js_path = os.path.join(repo_root, 'application', 'single_app', 'static', 'js', 'admin', 'admin_model_endpoints.js')
    content = read_file_text(js_path)

    assert "Please save your settings" in content, "Expected save toast reminder in endpoint save flow."

    print("✅ Save toast reminder verified.")


if __name__ == "__main__":
    test_model_endpoints_save_toast_message()
