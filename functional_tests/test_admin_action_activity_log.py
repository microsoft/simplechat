# test_admin_action_activity_log.py
#!/usr/bin/env python3
"""
Functional test for general admin action logging.
Version: 0.241.021
Implemented in: 0.241.021

This test ensures admin activity logging normalizes admin user identifiers
before persistence and that the admin settings route passes a string user id.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_admin_action_activity_log_helper():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    log_path = os.path.join(repo_root, 'application', 'single_app', 'functions_activity_logging.py')
    route_path = os.path.join(repo_root, 'application', 'single_app', 'route_frontend_admin_settings.py')
    content = read_file_text(log_path)
    route_content = read_file_text(route_path)

    assert 'def log_general_admin_action' in content, "Missing admin action logging helper."
    assert 'def coerce_activity_log_user_id' in content, "Missing user id normalization helper."
    assert 'normalized_admin_user_id = coerce_activity_log_user_id(admin_user_id)' in content, (
        "Admin action logging should normalize admin_user_id before storage."
    )
    assert "activity_type': 'admin_action'" in content, "Expected admin_action activity type."
    assert "'admin':" in content, "Expected admin identity metadata in activity record."
    assert "'description':" in content, "Expected description for activity display."
    assert 'admin_user_id=user_id' in route_content, "Admin settings route should pass a scalar user_id."

    print("✅ Admin action activity logging user id normalization verified.")


if __name__ == "__main__":
    test_admin_action_activity_log_helper()
