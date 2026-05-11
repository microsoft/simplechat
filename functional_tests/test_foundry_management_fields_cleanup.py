# test_foundry_management_fields_cleanup.py
#!/usr/bin/env python3
"""
Functional test for Foundry management field cleanup.
Version: 0.236.029
Implemented in: 0.236.029

This test ensures Foundry endpoints no longer use subscription/resource/location fields in the modal payload.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_foundry_management_fields_cleanup():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    js_path = os.path.join(repo_root, 'application', 'single_app', 'static', 'js', 'admin', 'admin_model_endpoints.js')
    content = read_file_text(js_path)

    assert "const management = provider === \"aoai\"" in content, "Expected management fields only for AOAI."
    assert "endpointLocation" not in content, "Foundry/AOAI location field should be removed from the modal script."

    print("✅ Foundry management field cleanup verified.")


if __name__ == "__main__":
    test_foundry_management_fields_cleanup()
