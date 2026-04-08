# test_admin_action_activity_log.py
#!/usr/bin/env python3
"""
Functional test for general admin action logging.
Version: 0.236.017
Implemented in: 0.236.017

This test ensures a helper exists for logging general admin actions with
admin identity fields and a description for activity log display.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_admin_action_activity_log_helper():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    log_path = os.path.join(repo_root, 'application', 'single_app', 'functions_activity_logging.py')
    content = read_file_text(log_path)

    assert 'def log_general_admin_action' in content, "Missing admin action logging helper."
    assert "activity_type': 'admin_action'" in content, "Expected admin_action activity type."
    assert "'admin':" in content, "Expected admin identity metadata in activity record."
    assert "'description':" in content, "Expected description for activity display."

    print("✅ Admin action activity logging helper verified.")


if __name__ == "__main__":
    test_admin_action_activity_log_helper()
